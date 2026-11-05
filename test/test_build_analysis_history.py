"""1ホールのDBが壊れていても、他のホールの履歴蓄積を止めない。

2026-10-16〜11-05、BIGディッパー戸越銀座店のDBに machine_layout_history が無いため
build_analysis_history が毎朝そこで落ち、順番が後ろの全ホールの角番ピーク・並び箇所数が
10/14 で止まっていた。朝の実行は個々の段の失敗で落とさないので、ログを読むまで気づかなかった。
"""

from __future__ import annotations

import sqlite3
import sys

from database import analysis_store as store
from database import build_analysis_history as bah
from database.migrate_machine_layout_history import CREATE_SQL as MACHINE_LAYOUT_HISTORY_SQL


def _make_hall(path, with_layout_history=True):
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE machine_detailed_results ("
        "date TEXT, machine_number INTEGER, machine_name TEXT, "
        "diff_coins_normalized INTEGER, games_normalized INTEGER)"
    )
    con.executemany(
        "INSERT INTO machine_detailed_results VALUES ('20261104', ?, '機種A', 2500, 8000)",
        [(n,) for n in range(1001, 1005)],
    )
    if with_layout_history:
        con.execute(MACHINE_LAYOUT_HISTORY_SQL)
    con.commit()
    con.close()


def _narabi_needs_layout(con):
    con.execute("SELECT COUNT(*) FROM machine_layout_history").fetchone()
    return [{"segment": "", "item": "count", "value_num": 0, "n": 4}]


def _run(tmp_path, monkeypatch):
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    _make_hall(db_dir / "A正常.db")
    _make_hall(db_dir / "B壊れ.db", with_layout_history=False)
    _make_hall(db_dir / "C正常.db")

    calls = []
    results = tmp_path / "results.db"
    real_connect = sqlite3.connect
    monkeypatch.setattr(store, "connect", lambda: real_connect(results))
    monkeypatch.setattr(store, "register_definition", lambda *a, **k: a[1])
    monkeypatch.setattr(store, "put_values", lambda st, hall, date, d, rows: calls.append((hall, d)) or len(rows))
    monkeypatch.setattr(bah, "DB_DIR", db_dir)
    monkeypatch.setattr(bah, "narabi_rows", lambda con, date: _narabi_needs_layout(con))
    monkeypatch.setattr(sys, "argv", ["build_analysis_history.py", "--since", "20261101"])
    return bah.main(), calls


def test_broken_hall_does_not_stop_later_halls(tmp_path, monkeypatch):
    _code, calls = _run(tmp_path, monkeypatch)
    halls = {hall for hall, _d in calls}
    assert "A正常" in halls and "C正常" in halls and "B壊れ" not in halls


def test_broken_hall_is_reported_by_name_and_exit_code(tmp_path, monkeypatch, capsys):
    code, _calls = _run(tmp_path, monkeypatch)
    assert code == 1
    assert "B壊れ" in capsys.readouterr().out
