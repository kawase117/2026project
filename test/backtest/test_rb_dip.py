"""凹み戻り(rbdip)の選択・凍結・別系列の採点(2026-10-25)。"""

import json
import sqlite3
from datetime import datetime, timedelta

import pytest

from backtest import prediction_ledger as ledger, prediction_rb as rb, rb_candidates as cand, scoreboard

HALL = "楽園蒲田店"
TARGET = "20261025"
ASOF = "20261024"


def _db(path):
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE machine_detailed_results (date TEXT, machine_number INT, machine_name TEXT, "
        "games_normalized REAL, rb_count REAL, diff_coins_normalized REAL)"
    )
    return con


def _dates(end, n):
    last = datetime.strptime(end, "%Y%m%d")
    return [(last - timedelta(days=age)).strftime("%Y%m%d") for age in range(n - 1, -1, -1)]


def _seed(con, units=10, days=200, recent=7, families=1, name="F{f}"):
    """機種(既定F0)の10台。台 u の長期RBは 8+u 回/日(強い台ほど番号が大きい)。
    直近7日は、台番号が偶数なら大きく凹む(1回/日)、奇数なら好調(30回/日)。
    直近の順位は機種内の相対なので、長期が強い偶数の台でも、直近で下位になるよう差を大きくしてある。
    families>1 のとき、機種ごとに台番号を f*100 ずらす(ホールの機種数の条件を満たすため)。"""
    all_dates = _dates(ASOF, days)
    recent_dates = set(all_dates[-recent:])
    for date in all_dates:
        for f in range(families):
            for u in range(units):
                rb_count = (1 if u % 2 == 0 else 30) if date in recent_dates else 8 + u
                con.execute(
                    "INSERT INTO machine_detailed_results VALUES (?,?,?,?,?,?)",
                    (date, f * 100 + u, name.format(f=f), 4000, rb_count, 0),
                )
    con.commit()


@pytest.fixture
def specs(monkeypatch):
    monkeypatch.setattr(rb, "rb_family", lambda name: (name, 0.002, 0.006) if name.startswith("F") else None)
    if hasattr(rb.family_offsets, "cache_clear"):
        rb.family_offsets.cache_clear()
    yield
    if hasattr(rb.family_offsets, "cache_clear"):
        rb.family_offsets.cache_clear()


def test_pct_ranks_matches_pandas_average_rank():
    assert cand._pct_ranks([10, 20, 20, 40]) == [0.25, 0.625, 0.625, 1.0]
    assert cand._pct_ranks([5]) == [1.0]


def test_rank_dip_units_splits_dip_and_hot(tmp_path, specs):
    with _db(tmp_path / "a.db") as con:
        _seed(con)
        result = cand.rank_dip_units(con, TARGET, ASOF)
    # 長期が強いのは番号の大きい台。直近が凹むのは偶数、好調なのは奇数
    assert {r["machine_number"] for r in result["a"]} >= {6, 8}
    assert {r["machine_number"] for r in result["b"]} >= {7, 9}
    assert {r["machine_number"] for r in result["a"] + result["b"]} <= {5, 6, 7, 8, 9}
    assert all(r["recent_dev"] < 0 for r in result["a"])
    assert all(r["recent_dev"] > 0 for r in result["b"])
    assert all(r["long_dev"] > 0 for r in result["a"] + result["b"])
    assert result["n_families"] == 1
    assert [r["long_dev"] for r in result["a"]] == sorted((r["long_dev"] for r in result["a"]), reverse=True)


def test_rank_dip_units_requires_enough_units_and_rows(tmp_path, specs):
    with _db(tmp_path / "few.db") as con:
        _seed(con, units=4)
        assert cand.rank_dip_units(con, TARGET, ASOF) == {"a": [], "b": [], "n_families": 0}
    with _db(tmp_path / "short.db") as con:
        _seed(con, days=15)  # 長期の行数が20未満
        assert cand.rank_dip_units(con, TARGET, ASOF)["n_families"] == 0


def test_rank_dip_units_excludes_target_day(tmp_path, specs):
    with _db(tmp_path / "a.db") as con:
        _seed(con)
        before = cand.rank_dip_units(con, TARGET, ASOF)
        for u in range(10):  # 対象日の極端な値は窓に入らない
            con.execute("INSERT INTO machine_detailed_results VALUES (?,?,?,?,?,0)", (TARGET, u, "F0", 4000, 999))
        con.commit()
        assert cand.rank_dip_units(con, TARGET, ASOF) == before


def _generate(tmp_path, monkeypatch, no_freeze=False):
    db_dir = tmp_path / "db"
    db_dir.mkdir(exist_ok=True)
    if not (db_dir / f"{HALL}.db").exists():
        with _db(db_dir / f"{HALL}.db") as con:
            _seed(con, families=5)  # ホールの機種ランキングは5機種以上が条件
    monkeypatch.setattr(cand, "RB_HALLS", (HALL, "ARROW池上店"))
    monkeypatch.setattr(rb, "family_offsets", lambda *_: {f"F{i}": 0.25 for i in range(5)})
    original_dip = ledger.freeze_rb_dip
    original_auto = ledger.freeze_rb_auto
    monkeypatch.setattr(
        cand.prediction_ledger, "freeze_rb_dip", lambda *a: original_dip(*a, pred_dir=tmp_path / "pred")
    )
    monkeypatch.setattr(
        cand.prediction_ledger,
        "freeze_rb_auto",
        lambda h, d, p, e, t: original_auto(h, d, p, e, t, tmp_path / "pred"),
    )
    return cand.generate(TARGET, db_dir, tmp_path / "out", no_freeze=no_freeze)


def test_generate_freezes_a_and_b_as_separate_entries(tmp_path, specs, monkeypatch):
    rows = _generate(tmp_path, monkeypatch)
    assert rows[0]["dip"]["a"] and rows[0]["dip"]["b"]
    assert rows[1]["dip"] is None  # DIP_HALLS 以外(DBなし)
    a = json.loads((tmp_path / "pred" / f"{TARGET}__rakuen__rbdip.json").read_text(encoding="utf-8"))
    b = json.loads((tmp_path / "pred" / f"{TARGET}__rakuen__rbdipctrl.json").read_text(encoding="utf-8"))
    assert a["source"] == "rb_dip" and b["source"] == "rb_dip_ctrl"
    assert a["digest"] == ledger._digest(a) and b["digest"] == ledger._digest(b)
    assert a["picks"]["units"] == sorted(r["machine_number"] for r in rows[0]["dip"]["a"])
    assert b["picks"]["units"] == sorted(r["machine_number"] for r in rows[0]["dip"]["b"])
    assert not set(a["picks"]["units"]) & set(b["picks"]["units"])
    assert a["timing"] in {"pre_open", "same_day", "after"}
    runs = [json.loads(line) for line in (tmp_path / "out" / "RUNS.jsonl").read_text(encoding="utf-8").splitlines()]
    assert runs[0]["dip_a"] == len(rows[0]["dip"]["a"]) and runs[0]["dip_b"] == len(rows[0]["dip"]["b"])
    assert runs[1]["dip_a"] is None
    # 2回目は上書きしない
    before = (tmp_path / "pred" / f"{TARGET}__rakuen__rbdip.json").read_bytes()
    _generate(tmp_path, monkeypatch)
    assert (tmp_path / "pred" / f"{TARGET}__rakuen__rbdip.json").read_bytes() == before


def test_generate_no_freeze_creates_no_dip_entries(tmp_path, specs, monkeypatch):
    _generate(tmp_path, monkeypatch, no_freeze=True)
    assert not (tmp_path / "pred").exists()


def test_freeze_rb_dip_rejects_unknown_kind_and_never_overwrites(tmp_path):
    pred = tmp_path / "pred"
    now = datetime.now(ledger.JST)
    with pytest.raises(ValueError):
        ledger.freeze_rb_dip(HALL, TARGET, {"units": [1]}, {}, now, "rb_other", pred)
    assert ledger.freeze_rb_dip(HALL, TARGET, {"units": [1]}, {"dip": []}, now, "rb_dip", pred) is not None
    assert ledger.freeze_rb_dip(HALL, TARGET, {"units": [1]}, {}, now, "rb_dip", pred) is None
    assert ledger.RB_DIP_SUFFIX == {"rb_dip": "rbdip", "rb_dip_ctrl": "rbdipctrl"}


def test_score_adds_rb_and_rb_s1_but_not_machine(tmp_path, specs, monkeypatch):
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    with _db(db_dir / f"{HALL}.db") as con:
        _seed(con)
        for u in range(10):
            con.execute("INSERT INTO machine_detailed_results VALUES (?,?,?,?,?,0)", (TARGET, u, "F0", 4000, 8 + u))
        con.commit()
    monkeypatch.setattr(ledger, "DB_DIR", db_dir)
    # rb_s1_result は bonus_specs.find_spec 経由で判別機種を引くので、擬似機種 F0 を判別・RB確率の幅つきにする
    fake_spec = {
        "judgeable": True,
        "family_name": "F0",
        "settings": {1: {"rb_probability": 0.002}, 6: {"rb_probability": 0.006}},
    }
    monkeypatch.setattr(
        rb.bonus_specs, "find_spec", lambda name, specs=None: fake_spec if name.startswith("F") else None
    )
    monkeypatch.setattr(rb, "_specs", lambda: {})
    pred = tmp_path / "pred"
    path = ledger.freeze_rb_dip(
        HALL,
        TARGET,
        {"models": [], "avoid_models": [], "units": [8, 9], "jug_units": []},
        {"dip": [], "data_asof": ASOF, "lag_days": 0},
        datetime.now(ledger.JST),
        "rb_dip",
        pred,
    )
    obj = ledger.score(json.loads(path.read_text(encoding="utf-8")))
    assert "rb" in obj["result"] and "rb_s1" in obj["result"]
    assert "rb_machine" not in obj["result"] and "rb_day" not in obj["result"]
    assert obj["result"]["rb_s1"]["units"] is not None


def _pred(source, date, edge, hall=HALL):
    return {
        "hall": hall,
        "target_date": date,
        "timing": "pre_open",
        "source": source,
        "result": {"rb_s1": {"units": {"rb_s1_edge": edge}}, "models": {"edge": 999}},
    }


def test_scoreboard_separates_dip_series_and_computes_difference():
    preds = [
        _pred("rb_dip", "20261026", 0.05),
        _pred("rb_dip_ctrl", "20261026", 0.01),
        _pred("rb_dip", "20261027", 0.03),  # 対照が無い日は差に出ない
        _pred("rb_dip_ctrl", "20261028", 0.02),  # 凹みが無い日も差に出ない
    ]
    rows = scoreboard.build_prediction_rows(preds)
    by_family = {r.family: r for r in rows}
    assert set(by_family) == {"rbdip_units", "rbdip_ctrl_units", "rbdip_diff"}
    assert by_family["rbdip_units"].stat.n_days == 2 and by_family["rbdip_ctrl_units"].stat.n_days == 2
    assert by_family["rbdip_diff"].stat.n_days == 1
    assert by_family["rbdip_diff"].stat.mean == pytest.approx(0.04)


def test_render_dip_line_and_empty_marker():
    row = {
        "hall": HALL,
        "status": "ok",
        "reason": None,
        "data_asof": ASOF,
        "lag_days": 0,
        "candidates": [],
        "avoid": [],
        "units": {},
        "day_flag": None,
        "dip": {"a": [{"family_name": "F0", "machine_number": 8, "long_dev": 0.1, "recent_dev": -0.2}], "b": []},
    }
    text = cand.render_section([row])
    assert "台の補助(凹み戻り、長期が強い台の直近7日の凹み。対照は別に凍結):" in text
    assert "| F0 | 8 | +0.10 | -0.20 |" in text
    row["dip"] = {"a": [], "b": []}
    assert "台の補助(凹み戻り): 該当なし" in cand.render_section([row])
    row["hall"] = "ARROW池上店"
    assert "凹み戻り" not in cand.render_section([row])
