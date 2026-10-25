"""新規ホールDBにも machine_layout_history が作られる（2026-10-25）。

座標CSVが無いヒロキ蒲田西口店・MAX蒲田店のDBにはこのテーブルが無く、
backtest.run_backtest.load_frame の LEFT JOIN が「no such table」で落ちて
announce の dbmax / baserate が使えなかった。空のままでよいので作っておく。
"""

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "database"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import db_setup  # noqa: E402
from database.migrate_machine_layout_history import CREATE_SQL  # noqa: E402


def _columns(con, table):
    return [(r[1], r[2], r[3], r[5]) for r in con.execute(f"PRAGMA table_info({table})")]


def test_new_hall_db_gets_empty_layout_history(tmp_path):
    db_setup.create_database("テスト新ホール", db_dir=str(tmp_path))
    con = sqlite3.connect(tmp_path / "db" / "テスト新ホール.db")
    try:
        assert con.execute("SELECT COUNT(*) FROM machine_layout_history").fetchone()[0] == 0
    finally:
        con.close()


def test_layout_history_ddl_matches_migration_module(tmp_path):
    db_setup.create_database("テスト新ホール", db_dir=str(tmp_path))
    con = sqlite3.connect(tmp_path / "db" / "テスト新ホール.db")
    try:
        ref = sqlite3.connect(":memory:")
        ref.execute(CREATE_SQL)
        assert _columns(con, "machine_layout_history") == _columns(ref, "machine_layout_history")
    finally:
        con.close()


def test_load_frame_style_join_works_with_empty_history(tmp_path):
    """load_frame と同じ結合。履歴が空でも行は落ちず、位置だけが NULL になる。"""
    db_setup.create_database("テスト新ホール", db_dir=str(tmp_path))
    con = sqlite3.connect(tmp_path / "db" / "テスト新ホール.db")
    try:
        con.execute(
            "INSERT INTO machine_detailed_results (date, machine_name, machine_number, last_digit) "
            "VALUES ('20261024', 'テスト機', 101, '1')"
        )
        rows = con.execute(
            """
            SELECT r.machine_number, l.section, l.rank_from_aisle
            FROM machine_detailed_results r
            LEFT JOIN machine_layout_history l
                   ON r.machine_number = l.machine_number
                  AND r.date >= l.valid_from
                  AND (l.valid_to IS NULL OR r.date <= l.valid_to)
            """
        ).fetchall()
    finally:
        con.close()
    assert rows == [(101, None, None)]
