"""予測台帳RB採点の境界と既存採点との共存。"""

import json
import math
import sqlite3
from datetime import datetime, timedelta

import pytest

from backtest import prediction_ledger as pl
from backtest import prediction_rb, scoreboard
from scripts import morning_facts

DAY = "20261020"
HALL = "楽園蒲田店"
JUG = "マイジャグラーV"
OTHER = "アイムジャグラーEX"
AT = "スマスロ北斗の拳"


def _db(path):
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE machine_detailed_results (date TEXT, machine_number INT, machine_name TEXT, "
        "games_normalized REAL, rb_count REAL, bb_count REAL, diff_coins_normalized REAL)"
    )
    return con


def _insert(con, day, number, name, games, rb, diff=0):
    con.execute(
        "INSERT INTO machine_detailed_results VALUES (?, ?, ?, ?, ?, 0, ?)", (day, number, name, games, rb, diff)
    )


def _seed(con):
    start = datetime.strptime(DAY, "%Y%m%d") - timedelta(days=60)
    for i in range(20):
        _insert(con, (start + timedelta(days=i)).strftime("%Y%m%d"), 101, JUG, 3000, 10)
        if i < 19:
            _insert(con, (start + timedelta(days=i)).strftime("%Y%m%d"), 201, OTHER, 3000, 10)
    _insert(con, (start - timedelta(days=1)).strftime("%Y%m%d"), 101, JUG, 3000, 1000)
    _insert(con, DAY, 101, JUG, 3000, 20, 100)
    _insert(con, DAY, 102, JUG, 3000, 10, -100)
    _insert(con, DAY, 103, JUG, 2999, 100)
    _insert(con, DAY, 104, JUG, None, 100)
    _insert(con, DAY, 105, JUG, 3000, None)
    _insert(con, DAY, 201, OTHER, 3000, 10)
    _insert(con, DAY, 301, AT, 3000, 10)
    con.commit()


def _picks():
    return {"models": [JUG, OTHER, AT], "avoid_models": [JUG], "units": [101, 201, 301], "jug_units": [102]}


def test_rb_math_dates_and_exclusions(tmp_path):
    with _db(tmp_path / "test.db") as con:
        _seed(con)
        rb = prediction_rb.rb_result(con, _picks(), DAY)
    assert rb["day_rb_ratio"] == pytest.approx(1.5)
    assert rb["models"]["rb_obs"] == 30
    assert rb["models"]["rb_exp"] == pytest.approx(20)
    assert rb["models"]["rb_ratio"] == pytest.approx(1.5)
    assert rb["models"]["z"] == pytest.approx(10 / math.sqrt(20))
    assert rb["units"]["rb_ratio"] == pytest.approx(2)
    assert rb["units"]["rb_edge"] == pytest.approx(0.5)
    assert rb["jug_units"]["rb_edge"] == pytest.approx(-0.5)
    assert rb["excluded"] == {"low_games": 3, "no_baseline": [OTHER], "not_judgeable": [AT]}


def test_baseline_does_not_include_target_or_day_61(tmp_path):
    with _db(tmp_path / "test.db") as con:
        _seed(con)
        before = prediction_rb.rb_result(con, _picks(), DAY)
        _insert(con, DAY, 106, JUG, 3000, 1000)
        after = prediction_rb.rb_result(con, _picks(), DAY)
    assert before["models"]["rb_exp"] == pytest.approx(20)
    assert after["models"]["rb_exp"] == pytest.approx(30)
    assert after["models"]["rb_obs"] == 1030


def _object():
    obj = {
        "prediction_id": "x",
        "hall": HALL,
        "target_date": DAY,
        "picks": _picks(),
        "frozen_at": "2026-10-20T09:00:00+09:00",
        "timing": "pre_open",
        "result": None,
    }
    obj["digest"] = pl._digest(obj)
    return obj


def test_score_and_rb_failure_keep_diff_result(tmp_path, monkeypatch):
    db = tmp_path / f"{HALL}.db"
    with _db(db) as con:
        _seed(con)
    monkeypatch.setattr(pl, "DB_DIR", tmp_path)
    scored = pl.score(_object())
    assert scored["result"]["day_mean"] == 0
    assert scored["result"]["models"]["edge"] == 0
    assert scored["result"]["rb"]["models"]["rb_ratio"] == pytest.approx(1.5)
    monkeypatch.setattr(pl, "rb_result", lambda *args: (_ for _ in ()).throw(sqlite3.OperationalError("RB fail")))
    failed = pl.score(_object())
    assert failed["result"]["models"] == scored["result"]["models"]
    assert failed["result"]["rb"] is None
    assert "RB fail" in failed["result"]["rb_error"]


def test_rescore_only_adds_rb_and_is_idempotent(tmp_path, monkeypatch):
    db = tmp_path / f"{HALL}.db"
    with _db(db) as con:
        _seed(con)
    monkeypatch.setattr(pl, "DB_DIR", tmp_path)
    pred = tmp_path / "pred"
    pred.mkdir()
    obj = _object()
    obj["result"] = {"models": {"edge": 123}, "day_mean": 7}
    path = pred / "20261020__rakuen.json"
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    assert len(pl.rescore_rb(pred)) == 1
    written = json.loads(path.read_text(encoding="utf-8"))
    assert {k: v for k, v in written.items() if k != "result"} == {k: v for k, v in obj.items() if k != "result"}
    assert {k: v for k, v in written["result"].items() if k not in ("rb", "rb_s1", "games", "jug_model")} == obj[
        "result"
    ]
    content = path.read_bytes()
    assert pl.rescore_rb(pred) == []
    assert path.read_bytes() == content


def test_rescore_skips_missing_day(tmp_path, monkeypatch):
    with _db(tmp_path / f"{HALL}.db") as con:
        _insert(con, "20261019", 101, JUG, 3000, 10)
    monkeypatch.setattr(pl, "DB_DIR", tmp_path)
    pred = tmp_path / "pred"
    pred.mkdir()
    obj = _object()
    obj["result"] = {"day_mean": 0}
    path = pred / "20261020__rakuen.json"
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    before = path.read_bytes()
    assert "対象日の行がない" in pl.rescore_rb(pred)[0]
    assert path.read_bytes() == before


def test_scoreboard_and_morning_lines(tmp_path):
    with _db(tmp_path / "test.db") as con:
        _seed(con)
        rb = prediction_rb.rb_result(con, _picks(), DAY)
    rb["avoid_models"] = rb["jug_units"]
    obj = _object()
    obj["result"] = {"models": {"edge": 10}, "rb": rb, "day_mean": 0, "universe_size": 7}
    base = scoreboard.build_prediction_rows([obj])
    assert {r.family for r in base} >= {"pred_models", "rb_models", "rb_avoid_models", "rb_units", "rb_jug_units"}
    avoid = next(r for r in base if r.family == "rb_avoid_models")
    assert avoid.stat.mean == pytest.approx(0.5)
    revised = {**obj, "revision_of": "x", "revision": "rev1"}
    assert any(r.family == "rb_models[rev1]" for r in scoreboard.build_prediction_rows([revised]))
    no_rb = {**obj, "result": {"models": {"edge": 10}, "day_mean": 0, "universe_size": 7}}
    assert {r.family for r in scoreboard.build_prediction_rows([no_rb])} == {"pred_models"}
    pred = tmp_path / "pred"
    pred.mkdir()
    path = pred / "20261020__rakuen.json"
    path.write_text(json.dumps(no_rb, ensure_ascii=False), encoding="utf-8")
    old_lines = morning_facts.ledger_lines(pred, "rakuen", DAY)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    new_lines = morning_facts.ledger_lines(pred, "rakuen", DAY)
    assert len(new_lines) == len(old_lines) + 1
    assert new_lines[-1].startswith("RB: models 1.50倍")
