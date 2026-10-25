"""予測台帳の設定1比RB採点を、一時DBで検証する。"""

import json
import math
import sqlite3

import pytest

from backtest import bonus_specs, prediction_ledger as ledger, prediction_rb, scoreboard
from scripts import morning_facts


DAY = "20261025"
HALL = "楽園蒲田店"
JUG = "マイジャグラーV"
AT = "スマスロ北斗の拳"


def _db(path):
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE machine_detailed_results (date TEXT, machine_number INTEGER, "
        "machine_name TEXT, games_normalized REAL, rb_count REAL, bb_count REAL, "
        "diff_coins_normalized REAL)"
    )
    return con


def _add(con, day, number, name=JUG, games=4000, rb=12, diff=0):
    con.execute(
        "INSERT INTO machine_detailed_results VALUES (?, ?, ?, ?, ?, 0, ?)", (day, number, name, games, rb, diff)
    )


def _seed(con, history=100, history_rb=12):
    for number in range(history):
        _add(con, "20261024", 1000 + number, rb=history_rb)
    for number, rb in ((101, 20), (102, 16), (103, 10), (104, 12)):
        _add(con, DAY, number, rb=rb, diff=100)
    con.commit()


def _picks():
    return {"models": [JUG], "avoid_models": [JUG], "units": [101, 102], "jug_units": [103]}


def _p_floor():
    spec = bonus_specs.find_spec(JUG, bonus_specs.load_specs())
    return min(v["rb_probability"] for v in spec["settings"].values() if v["rb_probability"])


def _object():
    obj = {
        "prediction_id": "x",
        "hall": HALL,
        "target_date": DAY,
        "picks": _picks(),
        "frozen_at": "2026-10-25T09:00:00+09:00",
        "timing": "pre_open",
        "result": None,
    }
    obj["digest"] = ledger._digest(obj)
    return obj


def test_s1_math_comparator_and_model_information(tmp_path):
    with _db(tmp_path / "test.db") as con:
        _seed(con)
        result = prediction_rb.rb_s1_result(con, _picks(), DAY)
        all_picked = prediction_rb.rb_s1_result(con, {**_picks(), "units": [101, 102, 103, 104]}, DAY)
    p = _p_floor()
    units = result["units"]
    assert units["n_machines"] == 2
    assert units["games"] == 8000
    assert units["rb_obs"] == 36
    assert units["rb_exp_s1"] == pytest.approx(8000 * p)
    assert units["s1_ratio"] == pytest.approx(36 / (8000 * p))
    assert units["z"] == pytest.approx((36 - 8000 * p) / math.sqrt(8000 * p))
    assert units["rb_s1_edge"] == pytest.approx(14 / (8000 * p))
    assert units["n_compared_machines"] == 1
    assert units["no_comparator"] == []
    assert result["jug_units"]["rb_s1_edge"] == pytest.approx(10 / (4000 * p) - 48 / (12000 * p))
    for kind in ("models", "avoid_models"):
        assert result[kind]["s1_ratio"] == pytest.approx(58 / (16000 * p))
        assert result[kind]["z"] == pytest.approx((58 - 16000 * p) / math.sqrt(16000 * p))
        assert result[kind]["rb_s1_edge"] is None
        assert "no_comparator" not in result[kind]
    assert all_picked["units"]["rb_s1_edge"] is None
    assert all_picked["units"]["no_comparator"] == [JUG]


def test_s1_history_gate_exclusions_and_no_target_leak(tmp_path):
    with _db(tmp_path / "test.db") as con:
        _seed(con, history=99)
        assert prediction_rb.rb_s1_result(con, _picks(), DAY)["excluded"]["history_short"] == [JUG]
        _add(con, DAY, 105, rb=1000)
        _add(con, "20261026", 106, rb=1000)
        assert prediction_rb.rb_s1_result(con, _picks(), DAY)["excluded"]["history_short"] == [JUG]
        _add(con, "20261024", 2000)
        _add(con, DAY, 301, AT)
        _add(con, DAY, 302, games=2999)
        valid = prediction_rb.rb_s1_result(con, _picks(), DAY)
        assert valid["excluded"]["history_short"] == []
        assert valid["excluded"]["not_judgeable"] == [AT]
        assert valid["excluded"]["low_games"] == 1
        assert valid["units"] is not None
    with _db(tmp_path / "bad.db") as con:
        _seed(con, history_rb=4)
        bad = prediction_rb.rb_s1_result(con, _picks(), DAY)
    assert bad["excluded"]["out_of_range"] == [f"{JUG}(1/1000)"]
    assert bad["units"] is None


def test_score_and_rescore_keep_existing_fields(tmp_path, monkeypatch):
    with _db(tmp_path / f"{HALL}.db") as con:
        _seed(con)
    monkeypatch.setattr(ledger, "DB_DIR", tmp_path)
    scored = ledger.score(_object())
    assert scored["result"]["day_mean"] == 100
    assert scored["result"]["rb"] is not None
    assert scored["result"]["rb_s1"]["units"]["rb_s1_edge"] is not None
    old_rb = scored["result"]["rb"]
    monkeypatch.setattr(ledger, "rb_s1_result", lambda *args: (_ for _ in ()).throw(ValueError("S1 fail")))
    failed = ledger.score(_object())
    assert failed["result"]["rb"] == old_rb
    assert failed["result"]["models"] == scored["result"]["models"]
    assert failed["result"]["rb_s1"] is None
    assert failed["result"]["rb_s1_error"] == "S1 fail"
    monkeypatch.setattr(ledger, "rb_s1_result", prediction_rb.rb_s1_result)
    monkeypatch.setattr(ledger, "rb_result", lambda *args: (_ for _ in ()).throw(ValueError("RB fail")))
    rb_failed = ledger.score(_object())
    assert rb_failed["result"]["rb"] is None
    assert rb_failed["result"]["rb_s1"] == scored["result"]["rb_s1"]
    monkeypatch.setattr(ledger, "rb_result", prediction_rb.rb_result)
    monkeypatch.setattr(ledger, "_ro", lambda hall: sqlite3.connect(tmp_path / f"{HALL}.db"))

    pred = tmp_path / "pred"
    pred.mkdir()
    for suffix, result in (
        ("rakuen", {"models": {"edge": 1}, "rb": old_rb}),
        ("mitoya", {"models": {"edge": 2}}),
        ("kamata1", {"models": {"edge": 3}, "rb_s1": scored["result"]["rb_s1"]}),
    ):
        obj = _object()
        obj["result"] = result
        (pred / f"{DAY}__{suffix}.json").write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    messages = ledger.rescore_rb(pred)
    assert len(messages) == 3
    for suffix in ("rakuen", "mitoya", "kamata1"):
        path = pred / f"{DAY}__{suffix}.json"
        written = json.loads(path.read_text(encoding="utf-8"))
        assert written["result"]["rb_s1"] is not None
        assert written["result"]["rb"] == old_rb
        assert written["result"]["models"]["edge"] == {"rakuen": 1, "mitoya": 2, "kamata1": 3}[suffix]
        assert written["picks"] == _picks()
        assert written["digest"] == _object()["digest"]
    before = {p.name: p.read_bytes() for p in pred.iterdir()}
    assert ledger.rescore_rb(pred) == []
    assert {p.name: p.read_bytes() for p in pred.iterdir()} == before


def test_scoreboard_and_morning_s1_are_optional(tmp_path):
    with _db(tmp_path / "test.db") as con:
        _seed(con)
        s1 = prediction_rb.rb_s1_result(con, _picks(), DAY)
    obj = _object()
    obj["result"] = {"models": {"edge": 1}, "day_mean": 0, "universe_size": 4}
    original = {r.family for r in scoreboard.build_prediction_rows([obj])}
    assert original == {"pred_models"}
    pred = tmp_path / "pred"
    pred.mkdir()
    path = pred / f"{DAY}__rakuen.json"
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    old_lines = morning_facts.ledger_lines(pred, "rakuen", DAY)
    obj["result"]["rb_s1"] = s1
    families = {r.family for r in scoreboard.build_prediction_rows([obj])}
    assert families == {"pred_models", "rb1_units", "rb1_jug_units"}
    revised = {**obj, "revision_of": "x", "revision": "rev1"}
    assert "rb1_units[rev1]" in {r.family for r in scoreboard.build_prediction_rows([revised])}
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    new_lines = morning_facts.ledger_lines(pred, "rakuen", DAY)
    assert len(new_lines) == len(old_lines) + 1
    assert new_lines[-1].startswith("RB(設定1比): units ")
    assert "jug_units " in new_lines[-1] and "差+" in new_lines[-1]
