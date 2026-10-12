"""juggler_carryover の監査(配置のエポック、スペック不明の報告、スペック不一致での停止、ホール混入)。

合成データだけを使い、実運用のDBは読まない。
"""

import copy
import sqlite3

import numpy as np
import pandas as pd
import pytest

from backtest import juggler_carryover as jc
from backtest.bonus_specs import find_spec, load_specs

MODEL = "マイジャグラーV"


def _make_db(db_dir, hall, rows, layout):
    con = sqlite3.connect(db_dir / f"{hall}.db")
    con.execute(
        "create table machine_detailed_results (date text, machine_number integer, machine_name text,"
        " games_normalized integer, bb_count integer, rb_count integer, diff_coins_normalized integer)"
    )
    con.execute(
        "create table machine_layout_history (machine_number integer, hall_name text, valid_from text,"
        " valid_to text, section text)"
    )
    con.executemany("insert into machine_detailed_results values (?,?,?,?,?,?,?)", rows)
    con.executemany(
        "insert into machine_layout_history (machine_number, hall_name, valid_from, valid_to, section)"
        " values (?,?,?,?,?)",
        [(u, hall, vf, vt, sec) for u, vf, vt, sec in layout],
    )
    con.commit()
    con.close()


def _rows(model=MODEL, units=(1, 2, 3, 4), dates=("20260801", "20260802", "20260803", "20260804", "20260805")):
    rng = np.random.default_rng(0)
    out = []
    for d in dates:
        for u in units:
            g = 3000
            out.append(
                (d, u, model, g, int(rng.poisson(g / 270)), int(rng.poisson(g / 330)), int(rng.integers(-500, 500)))
            )
    return out


def test_layout_epoch_is_assigned_by_date():
    """配置替え(valid_from/valid_to)をまたぐ台日に、その日に有効な島が付く。現行配置を過去に当てない。"""
    raw = pd.DataFrame({"date": ["20260801", "20260805"], "u": [1, 1]})
    hist = pd.DataFrame(
        {
            "u": [1, 1],
            "section": ["旧島", "新島"],
            "valid_from": ["20250101", "20260803"],
            "valid_to": ["20260802", None],
        }
    )
    out = jc.attach_section(raw, hist)
    assert list(out.section) == ["旧島", "新島"]


def test_layout_missing_gives_nan_not_crash():
    raw = pd.DataFrame({"date": ["20260801"], "u": [99]})
    hist = pd.DataFrame({"u": [1], "section": ["A"], "valid_from": ["20250101"], "valid_to": [None]})
    assert jc.attach_section(raw, hist).section.isna().all()
    assert jc.attach_section(raw, hist.iloc[0:0]).section.isna().all()


def test_unknown_model_is_reported_not_skipped_silently(tmp_path):
    hall = "テスト店"
    rows = _rows() + _rows(model="謎ジャグラー", units=(11, 12, 13, 14))
    layout = [(u, "20250101", None, "A") for u in (1, 2, 3, 4, 11, 12, 13, 14)]
    _make_db(tmp_path, hall, rows, layout)
    d = jc.build(hall, "20260801", db_dir=tmp_path)
    audit = d.attrs["audit"]
    assert "謎ジャグラー" in audit["excluded"]
    assert audit["excluded"]["謎ジャグラー"][1] == "スペックなし"
    assert "謎ジャグラー" in jc.format_audit(audit)
    assert "謎ジャグラー" not in set(d.m)


def test_spec_mismatch_stops(tmp_path):
    """find_specがマスターCSVと食い違う(2026-10-13のスペック誤りの再発)なら、結論を出さず停止する。"""
    hall = "テスト店"
    _make_db(tmp_path, hall, _rows(), [(u, "20250101", None, "A") for u in (1, 2, 3, 4)])
    specs = copy.deepcopy(load_specs(hall=hall))
    spec = find_spec(MODEL, specs)
    spec["settings"][6]["rb_probability"] *= 1.1  # 公表値から10%ずらす
    with pytest.raises(SystemExit) as e:
        jc.build(hall, "20260801", db_dir=tmp_path, specs=specs)
    assert MODEL in str(e.value) and "スペック不整合" in str(e.value)
    d = jc.build(hall, "20260801", db_dir=tmp_path, specs=specs, allow_spec_mismatch=True)
    assert d.attrs["audit"]["spec_mismatches"]


def test_shared_specs_agree_with_master_for_all_jugglers():
    """共有スペックは全ジャグラー機種でマスターCSV(公表値)と一致する。"""
    specs = load_specs(hall="みとや大森町店")
    models = [
        "アイムジャグラーEX-TP",
        "ウルトラミラクルジャグラー",
        "ゴーゴージャグラー3",
        "ジャグラーガールズ",
        "ネオアイムジャグラーEX",
        "ハッピージャグラーVIII",
        "ファンキージャグラー2",
        "マイジャグラーV",
        "マイジャグラーⅥ",
        "ミスタージャグラー",
    ]
    mismatches, unsupported = jc.audit_specs(models, specs)
    assert mismatches == []
    assert unsupported == []


def _write_config(path, hall):
    import json

    path.write_text(
        json.dumps(
            {
                "halls": {
                    hall: {
                        "exclusions": [{"date": "20260803", "reason": "特殊日", "source": "test"}],
                        "regime_boundaries": [
                            {"date": "20260804", "reason": "店長交代", "source": "test"},
                            {"date": "20271231", "reason": "期間外", "source": "test"},
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def test_hall_config_exclusion_and_regime_are_applied_and_reported(tmp_path):
    """ホール設定の除外日は集計から除かれ、期間内の変化点だけが監査に出る(自動では分割しない)。"""
    hall = "テスト店"
    _make_db(tmp_path, hall, _rows(), [(u, "20250101", None, "A") for u in (1, 2, 3, 4)])
    cfg = tmp_path / "juggler_analysis.json"
    _write_config(cfg, hall)
    d = jc.build(hall, "20260801", db_dir=tmp_path, config_path=cfg)
    assert "20260803" not in set(d.date)
    a = d.attrs["audit"]
    assert a["excluded_rows"] == 4
    assert [b["date"] for b in a["regime_in_period"]] == ["20260804"]
    text = jc.format_audit(a)
    assert "除外日" in text and "期間内の変化点 20260804" in text and "20271231" not in text


def test_other_hall_config_is_not_applied(tmp_path):
    """ある店の除外日は、設定にない別の店には効かない(ホール横断の混入を防ぐ)。"""
    _make_db(tmp_path, "店B", _rows(), [(u, "20250101", None, "A") for u in (1, 2, 3, 4)])
    cfg = tmp_path / "juggler_analysis.json"
    _write_config(cfg, "店A")
    d = jc.build("店B", "20260801", db_dir=tmp_path, config_path=cfg)
    assert "20260803" in set(d.date)
    assert d.attrs["audit"]["excluded_rows"] == 0


def _synthetic_ph(effect, days=40, noise=0.02, seed=0, model=MODEL):
    """台ごとの高設定になりやすさ(effect)に日替わりのノイズを足した、台×日のph。"""
    rng = np.random.default_rng(seed)
    dates = [f"2026{(8 + i // 30):02d}{(i % 30) + 1:02d}" for i in range(days)]
    rows = []
    for u, e in enumerate(effect, start=1):
        for d in dates:
            rows.append({"u": u, "m": model, "date": d, "ph": float(np.clip(e + rng.normal(0, noise), 0, 1))})
    return pd.DataFrame(rows)


def test_split_half_rank_detects_persistent_machine_effect():
    """台ごとの偏りが前後半で続くデータでは、順位相関が高く、並べ替え検定で有意になる。"""
    d = _synthetic_ph(effect=[0.02, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5])
    t = jc.split_half_rank(d, cut="20260901", min_days=10, n_perm=500)
    r = t.iloc[0]
    assert r.n == 8 and r.rho > 0.9 and r.p < 0.05
    assert r.top3_next > r.all_next  # 前半の上位3台は、後半も全台より高い


def test_split_half_rank_random_has_no_reproduction():
    """台ごとの偏りが無い(全台同じ水準)データでは、再現しない。"""
    d = _synthetic_ph(effect=[0.1] * 10, noise=0.05, seed=3)
    t = jc.split_half_rank(d, cut="20260901", min_days=10, n_perm=500)
    r = t.iloc[0]
    assert r.p > 0.05


def test_split_half_rank_skips_machines_with_few_days_and_small_models():
    d = _synthetic_ph(effect=[0.1, 0.2, 0.3, 0.4, 0.5], days=40)
    d = d[~((d.u == 5) & (d.date >= "20260901"))]  # 5番の台は後半のデータが無い
    t = jc.split_half_rank(d, cut="20260901", min_days=10, n_perm=100)
    assert t.iloc[0].n == 4 and np.isnan(t.iloc[0].rho)  # 5台未満になるので相関は出さない


def test_carry_by_half_splits_by_previous_day():
    """持ち越しの前半・後半は、前日の日付で分ける(翌日の日付ではない)。"""
    rows = []
    for u in range(1, 5):
        for i, d in enumerate(["20260810", "20260820", "20260901", "20260910"]):
            for k in range(80):  # 各区間300台日以上にするため台日を水増し
                rows.append(
                    {
                        "u": u,
                        "m": MODEL,
                        "date": d,
                        "rb_good": k % 2 == 0,
                        "r7band": "-500~500",
                        "ph_next": 0.30 if (k % 2 == 0 and d < "20260901") else 0.10,
                    }
                )
    z = pd.DataFrame(rows)
    out = jc.carry_by_half(z, cut="20260901")
    lines = {(half, label): line for _, half, label, line in out}
    # 前半は前日RB良のほうが高く(自群比がプラス)、後半は差が無い
    assert "自群比 +0.100" in lines[("前半", "前日RB良")]
    assert "自群比 +0.000" in lines[("後半", "前日RB良")]


def _positioned(effect, dists, days=60, noise=0.02, seed=0):
    """台ごとの高設定になりやすさ effect と、島の端からの距離 dists を持つ台×日の表。"""
    rng = np.random.default_rng(seed)
    dates = [f"2026{(7 + i // 30):02d}{(i % 30) + 1:02d}" for i in range(days)]
    rows = []
    for u, (e, dist) in enumerate(zip(effect, dists), start=1):
        for d in dates:
            rows.append(
                {"u": u, "m": MODEL, "date": d, "dist": dist, "ph": float(np.clip(e + rng.normal(0, noise), 0, 1))}
            )
    return pd.DataFrame(rows)


def test_attach_section_adds_edge_rank_by_date():
    """配置替えをまたぐと、その日に有効な配置の端からの距離(dist)が付く。"""
    raw = pd.DataFrame({"date": ["20260801", "20260805"], "u": [1, 1]})
    hist = pd.DataFrame(
        {
            "u": [1, 1],
            "section": ["旧", "新"],
            "rmin": [1, 5],
            "rmax": [9, 2],
            "raisle": [1, 3],
            "valid_from": ["20250101", "20260803"],
            "valid_to": ["20260802", None],
        }
    )
    out = jc.attach_section(raw, hist)
    assert list(out.dist) == [1, 2]  # 旧: min(1,9)=1(端)、新: min(5,2)=2


def test_edge_effect_detects_low_edge_in_both_halves():
    dists = [1, 1, 5, 5, 5, 6, 6, 7, 7, 8]
    d = _positioned(effect=[0.02, 0.02] + [0.2] * 8, dists=dists)
    t = jc.edge_effect(d, cut="20260731", n_boot=200)
    assert len(t) == 2
    for r in t.itertuples():
        assert r.diff < -0.1 and r.hi < 0  # 前半も後半も、端が明確に低い


def test_edge_effect_is_zero_when_no_position_effect():
    dists = [1, 1, 5, 5, 5, 6, 6, 7, 7, 8]
    d = _positioned(effect=[0.2] * 10, dists=dists, seed=2)
    t = jc.edge_effect(d, cut="20260731", n_boot=200)
    assert all(abs(r.diff) < 0.03 for r in t.itertuples())


def test_residual_fixed_vanishes_when_position_explains_everything():
    """台固定が位置(端が低い)だけで説明できるデータでは、位置を除いた残差の相関は有意でない。"""
    dists = [1] * 4 + [5] * 12
    d = _positioned(effect=[0.02] * 4 + [0.2] * 12, dists=dists, noise=0.03, seed=1)
    r = jc.residual_fixed(d, cut="20260731", min_days=10, n_perm=500).iloc[0]
    assert r.rho_all > 0.5  # 位置を除く前は強い相関(端と端以外の差)
    assert r.p_resid > 0.05  # 位置を除くと消える


def test_residual_fixed_remains_when_machines_differ_beyond_position():
    """位置とは別に台ごとの偏りがあるデータでは、位置を除いても残差の相関が残る。"""
    dists = [5] * 14
    effect = [0.05, 0.08, 0.1, 0.12, 0.15, 0.17, 0.2, 0.22, 0.25, 0.28, 0.3, 0.33, 0.36, 0.4]
    d = _positioned(effect=effect, dists=dists, noise=0.03, seed=4)
    r = jc.residual_fixed(d, cut="20260731", min_days=10, n_perm=500).iloc[0]
    assert r.rho_resid > 0.8 and r.p_resid < 0.05


def test_halls_do_not_mix(tmp_path):
    """別ホールのDBの台番号・結果が混ざらない(同じ台番号でも別ホールの行を読まない)。"""
    layout = [(u, "20250101", None, "A") for u in (1, 2, 3, 4)]
    _make_db(tmp_path, "店A", _rows(), layout)
    _make_db(tmp_path, "店B", _rows(units=(1, 2, 3, 4), dates=("20260801", "20260802")), layout)
    da = jc.build("店A", "20260801", db_dir=tmp_path)
    db = jc.build("店B", "20260801", db_dir=tmp_path)
    assert da.d.nunique() == 5 and db.d.nunique() == 2
    assert da.attrs["audit"]["hall"] == "店A" and db.attrs["audit"]["hall"] == "店B"
