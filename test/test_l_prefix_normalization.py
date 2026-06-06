import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "database"))

from batch_incremental_updater import normalize_l_prefix_in_db
from json_processor import normalize_machine_name


def test_l_prefix_stripped():
    assert normalize_machine_name("Lバイオハザード5") == "バイオハザード5"
    assert normalize_machine_name("L荒野のコトブキ飛行隊") == "荒野のコトブキ飛行隊"


def test_lb_prefix_preserved():
    # LBで始まる正式機種名は変更しない
    assert normalize_machine_name("LBニューパルサー") == "LBニューパルサー"
    assert normalize_machine_name("LB SHAKE BONUS TRIGGER") == "LB SHAKE BONUS TRIGGER"


def test_non_l_unchanged():
    assert normalize_machine_name("マイジャグラーV") == "マイジャグラーV"
    assert normalize_machine_name("スマスロ北斗の拳") == "スマスロ北斗の拳"


def test_l_prefix_db_cleanup():
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "sample.db")
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("CREATE TABLE machine_detailed_results (machine_name TEXT)")
            conn.execute(
                """
                CREATE TABLE machine_master (
                    machine_name_normalized TEXT PRIMARY KEY,
                    updated_at TEXT
                )
                """
            )
            conn.executemany(
                "INSERT INTO machine_detailed_results VALUES (?)",
                [
                    ("L荒野のコトブキ飛行隊",),
                    ("荒野のコトブキ飛行隊",),
                    ("LBニューパルサー",),
                ],
            )
            conn.executemany(
                "INSERT INTO machine_master VALUES (?, ?)",
                [
                    ("L荒野のコトブキ飛行隊", "old"),
                    ("荒野のコトブキ飛行隊", "new"),
                    ("LBニューパルサー", "keep"),
                ],
            )

            stats = normalize_l_prefix_in_db(conn)

            assert stats["detail_updates"] == 1
            assert stats["master_deleted"] == 1
            assert stats["master_renamed"] == 0

            detail_rows = conn.execute(
                "SELECT machine_name FROM machine_detailed_results ORDER BY machine_name"
            ).fetchall()
            assert detail_rows == [
                ("LBニューパルサー",),
                ("荒野のコトブキ飛行隊",),
                ("荒野のコトブキ飛行隊",),
            ]

            master_rows = conn.execute(
                "SELECT machine_name_normalized FROM machine_master ORDER BY machine_name_normalized"
            ).fetchall()
            assert master_rows == [
                ("LBニューパルサー",),
                ("荒野のコトブキ飛行隊",),
            ]
        finally:
            conn.close()
