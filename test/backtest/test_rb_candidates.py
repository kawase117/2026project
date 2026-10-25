"""RB自動候補の窓・凍結・採点の一時DBテスト。"""

import json
import sqlite3
from datetime import datetime, timedelta

import pytest

from backtest import prediction_ledger as ledger, prediction_rb as rb, rb_candidates as cand, scoreboard


def _db(path):
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE machine_detailed_results (date TEXT, machine_number INT, machine_name TEXT, "
        "games_normalized REAL, rb_count REAL, diff_coins_normalized REAL)"
    )
    return con


def _seed(con, end="20261024", families=5):
    last = datetime.strptime(end, "%Y%m%d")
    for age in range(169, -1, -1):
        date = (last - timedelta(days=age)).strftime("%Y%m%d")
        for family in range(families):
            for unit in range(5):
                con.execute(
                    "INSERT INTO machine_detailed_results VALUES (?,?,?,?,?,?)",
                    (date, family * 100 + unit, f"F{family}", 4000, 8 + 2 * family + (unit == 0) * 2, 100),
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


def test_offsets_exclude_uncomparable_and_future(tmp_path, specs):
    with _db(tmp_path / "a.db") as con:
        for i in range(100):
            con.execute("INSERT INTO machine_detailed_results VALUES (?,?,?,?,?,0)", ("20261024", i, "F0", 4000, 8))
        con.execute("INSERT INTO machine_detailed_results VALUES (?,?,?,?,?,0)", ("20261025", 500, "F0", 4000, 1000))
        con.commit()
    with _db(tmp_path / "b.db") as con:
        for i in range(100):
            con.execute("INSERT INTO machine_detailed_results VALUES (?,?,?,?,?,0)", ("20261024", i, "F0", 4000, 16))
        for i in range(99):
            con.execute("INSERT INTO machine_detailed_results VALUES (?,?,?,?,?,0)", ("20261024", i, "F1", 4000, 12))
        con.commit()
    offsets = rb.family_offsets(tmp_path, "20261025")
    assert offsets["F0"] == pytest.approx(0.25)
    assert "F1" not in offsets


def test_rank_and_generate_freeze(tmp_path, specs, monkeypatch):
    hall = "みとや大森町店"
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    with _db(db_dir / f"{hall}.db") as con:
        _seed(con)
        offsets = {f"F{i}": 0.25 for i in range(5)}
        rank = cand.rank_machines(con, "20261025", "20261024", offsets)
        assert rank["status"] == "ok"
        assert len(rank["candidates"]) == len(rank["avoid"]) == 1
        assert rank["candidates"][0]["family_name"] == "F4"
        assert rank["avoid"][0]["family_name"] == "F0"
        assert rank["candidates"][0]["n_w"] == 450
        assert rank["candidates"][0]["n_lr"] == 400
        assert cand.rank_machines(con, "20261025", "20261024", offsets)["status"] == "ok"
        assert len(cand.rank_units(con, "20261025", "20261024", ["F4"])["F4"]) == 1
        assert cand.day_flag(con, "20261025", "20261024") is not None
        assert cand.rank_machines(con, "20261025", "20261024", offsets)["candidates"][0]["machine_names"] == ["F4"]
        con.execute("INSERT INTO machine_detailed_results VALUES ('20261025', 999, 'F0', 4000, 1000, 0)")
        assert cand.rank_machines(con, "20261025", "20261024", offsets)["candidates"][0]["family_name"] == "F4"
    monkeypatch.setattr(cand, "RB_HALLS", (hall, "missing"))
    monkeypatch.setattr(rb, "family_offsets", lambda *_: offsets)
    original_freeze = ledger.freeze_rb_auto
    monkeypatch.setattr(
        cand.prediction_ledger,
        "freeze_rb_auto",
        lambda h, d, p, e, t: original_freeze(h, d, p, e, t, tmp_path / "pred"),
    )
    out = tmp_path / "out"
    rows = cand.generate("20261025", db_dir, out, no_freeze=True)
    assert rows[0]["status"] == "ok" and rows[1]["reason"] == "db_missing"
    assert not (tmp_path / "pred").exists()
    assert len((out / "RUNS.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    cand.generate("20261025", db_dir, out)
    saved = next((tmp_path / "pred").glob("*rbauto.json"))
    obj = json.loads(saved.read_text(encoding="utf-8"))
    assert obj["source"] == "rb_auto" and obj["digest"] == ledger._digest(obj)
    assert obj["picks"]["models"] == ["F4"]
    before = saved.read_bytes()
    cand.generate("20261025", db_dir, out)
    assert saved.read_bytes() == before


def test_machine_edges_scoreboard_and_exclusions(tmp_path, specs):
    with _db(tmp_path / "a.db") as con:
        _seed(con)
        for family in range(5):
            for unit in range(3):
                con.execute(
                    "INSERT INTO machine_detailed_results VALUES ('20261025',?,?,?,?,?)",
                    (family * 100 + unit, f"F{family}", 4000, 8 + family * 2, 100),
                )
        con.execute("INSERT INTO machine_detailed_results VALUES ('20261025',999,'OTHER',4000,8,0)")
        con.commit()
        offsets = {f"F{i}": 0.25 for i in range(5)}
        result = rb.rb_machine_result(con, {"models": ["F4"], "avoid_models": ["F0"]}, "20261025", offsets)
        assert result["n_eligible"] == 5
        assert result["top"]["adj"] == pytest.approx(0.25)
        assert result["top"]["edge"] > 0
        assert result["bottom"]["edge"] < 0
        assert result["excluded"]["not_judgeable"] == ["OTHER"]
        empty = rb.rb_machine_result(con, {"models": [], "avoid_models": []}, "20261025", offsets)
        assert empty["top"] is None and empty["bottom"] is None
    pred = {
        "hall": "x",
        "target_date": "20261025",
        "timing": "pre_open",
        "source": "rb_auto",
        "result": {
            "rb_machine": result,
            "rb_s1": {"units": {"rb_s1_edge": 0.1}},
            "models": {"edge": 500},
            "rb": {"models": {"rb_edge": 0.2}},
        },
    }
    rows = scoreboard.build_prediction_rows([pred])
    assert {r.family for r in rows} == {"rbm_top", "rbm_bottom", "rbauto_units"}
    assert next(r for r in rows if r.family == "rbm_bottom").stat.mean > 0


def test_score_rescore_and_extract_isolation(tmp_path, specs, monkeypatch):
    hall = "みとや大森町店"
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    with _db(db_dir / f"{hall}.db") as con:
        _seed(con)
        for family in range(5):
            for unit in range(3):
                con.execute(
                    "INSERT INTO machine_detailed_results VALUES ('20261025',?,?,?,?,?)",
                    (family * 100 + unit, f"F{family}", 4000, 8 + family * 2, 100),
                )
        con.commit()
    monkeypatch.setattr(ledger, "DB_DIR", db_dir)
    monkeypatch.setattr(ledger, "family_offsets", lambda *_: {f"F{i}": 0.25 for i in range(5)})
    picks = {"models": ["F4"], "avoid_models": ["F0"], "units": [400], "jug_units": []}
    pred_dir = tmp_path / "pred"
    path = ledger.freeze_rb_auto(
        hall,
        "20261025",
        picks,
        {"day_flag": {"flag": "強め"}, "data_asof": "20261024", "lag_days": 0},
        datetime(2026, 10, 25, 9, tzinfo=ledger.JST),
        pred_dir,
    )
    assert path.stem.endswith("__rbauto")
    obj = ledger.score(json.loads(path.read_text(encoding="utf-8")))
    assert obj["result"]["rb_machine"]["top"]["edge"] > 0
    assert obj["result"]["rb_day"]["flag"] == {"flag": "強め"}
    old_rb = obj["result"]["rb"]
    old_diff = obj["result"]["models"]
    del obj["result"]["rb_machine"]
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    assert len(ledger.rescore_rb(pred_dir)) == 1
    rescored = json.loads(path.read_text(encoding="utf-8"))
    assert rescored["result"]["rb_machine"]["top"]["edge"] > 0
    assert rescored["result"]["rb"] == old_rb
    assert rescored["result"]["models"] == old_diff
    assert ledger.rescore_rb(pred_dir) == []
    monkeypatch.setattr(ledger, "roster", lambda h, d: ("20261024", {"F4": {400}}) if h == hall else (None, {}))
    md = "## みとや大森町店\n判断: F4。\n\n" + cand.render_section(
        [
            {
                "hall": hall,
                "status": "ok",
                "reason": None,
                "data_asof": "20261024",
                "lag_days": 0,
                "candidates": [{"family_name": "F4", "units": 3, "adj90": 0.1, "z90": 0.5, "z7": 0.6}],
                "avoid": [],
                "units": {},
                "day_flag": None,
            }
        ]
    )
    extracted = ledger.extract(md, "20261025")
    assert len(extracted) == 1 and extracted[0]["picks"]["models"] == ["F4"]


def test_score_keeps_existing_results_when_machine_metric_fails(tmp_path, specs, monkeypatch):
    hall = "みとや大森町店"
    with _db(tmp_path / f"{hall}.db") as con:
        _seed(con)
        con.execute("INSERT INTO machine_detailed_results VALUES ('20261025',400,'F4',4000,16,100)")
        con.commit()
    monkeypatch.setattr(ledger, "DB_DIR", tmp_path)
    monkeypatch.setattr(ledger, "rb_machine_result", lambda *_: (_ for _ in ()).throw(ValueError("metric failed")))
    picks = {"models": ["F4"], "avoid_models": [], "units": [400], "jug_units": []}
    path = ledger.freeze_rb_auto(
        hall,
        "20261025",
        picks,
        {"data_asof": "20261024", "lag_days": 0},
        datetime(2026, 10, 25, 9, tzinfo=ledger.JST),
        tmp_path / "pred",
    )
    result = ledger.score(json.loads(path.read_text(encoding="utf-8")))["result"]
    assert result["models"] is not None and result["rb"] is not None and result["rb_s1"] is not None
    assert result["rb_machine"] is None and result["rb_machine_error"] == "metric failed"
    assert "rb_day" in result
