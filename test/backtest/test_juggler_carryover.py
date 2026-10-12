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


def test_halls_do_not_mix(tmp_path):
    """別ホールのDBの台番号・結果が混ざらない(同じ台番号でも別ホールの行を読まない)。"""
    layout = [(u, "20250101", None, "A") for u in (1, 2, 3, 4)]
    _make_db(tmp_path, "店A", _rows(), layout)
    _make_db(tmp_path, "店B", _rows(units=(1, 2, 3, 4), dates=("20260801", "20260802")), layout)
    da = jc.build("店A", "20260801", db_dir=tmp_path)
    db = jc.build("店B", "20260801", db_dir=tmp_path)
    assert da.d.nunique() == 5 and db.d.nunique() == 2
    assert da.attrs["audit"]["hall"] == "店A" and db.attrs["audit"]["hall"] == "店B"
