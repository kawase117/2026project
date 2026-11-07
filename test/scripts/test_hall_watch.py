"""要注目日の通知は日付で必ず出て、推しとして抜き出されない。"""

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import hall_watch  # noqa: E402
from backtest import prediction_ledger  # noqa: E402


def make_db(directory: Path) -> None:
    conn = sqlite3.connect(directory / "みとや大森町店.db")
    conn.execute("CREATE TABLE machine_detailed_results (date TEXT, machine_name TEXT, diff_coins_normalized INT)")
    rows = [
        ("20261027", "うみねこのなく頃に2", 2500),
        ("20261027", "うみねこのなく頃に2", 2656),
        ("20261027", "獣王", 1000),
        ("20261027", "獣王", -200),
        ("20261026", "獣王", 9999),
        ("20261107", "獣王", 8888),
    ]
    conn.executemany("INSERT INTO machine_detailed_results VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()


def test_silent_on_other_days(tmp_path):
    make_db(tmp_path)
    assert hall_watch.watch_note("20261106", tmp_path) == ""
    assert hall_watch.watch_note("20261108", tmp_path) == ""


def test_alerts_on_each_seventh_day(tmp_path):
    make_db(tmp_path)
    for day in ("20261107", "20261117", "20261127"):
        assert "要注目: みとやの7のつく日" in hall_watch.watch_note(day, tmp_path)


def test_history_uses_past_seventh_days_only(tmp_path):
    make_db(tmp_path)
    note = hall_watch.watch_note("20261107", tmp_path)
    assert "| 10/27 |" in note
    assert "2/2台勝ち、平均 +2578" in note
    assert "1/2台勝ち、平均 +400" in note
    assert "9999" not in note and "8888" not in note


def test_still_alerts_without_database(tmp_path):
    note = hall_watch.watch_note("20261107", tmp_path)
    assert "要注目: みとやの7のつく日" in note
    assert "読めなかった" in note


def test_note_is_not_frozen_as_a_pick(tmp_path):
    make_db(tmp_path)
    md = "# 2026-11-07 予測\n\n%s\n\n## みとや\n\n判断: マイジャグラーⅥ(基準のまま)。\n" % hall_watch.watch_note(
        "20261107", tmp_path
    )
    specs = prediction_ledger.extract(md, "20261107")
    models = [m for spec in specs for m in spec["picks"]["models"]]
    assert "獣王" not in models
    assert "うみねこのなく頃に2" not in models
