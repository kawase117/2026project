from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from ml.corner_section.mitoya_corner_section_analysis import main, resolve_mitoya_db_path


def _create_tables(db_path: Path) -> None:
    con = sqlite3.connect(db_path)
    try:
        con.executescript(
            """
            CREATE TABLE machine_detailed_results (
                date TEXT,
                machine_number INTEGER,
                machine_name TEXT,
                diff_coins_normalized INTEGER,
                machine_rank_in_type INTEGER,
                games_normalized INTEGER
            );
            CREATE TABLE machine_layout (
                machine_number INTEGER,
                rank_from_min INTEGER,
                section TEXT
            );
            CREATE TABLE machine_master (
                machine_name_normalized TEXT,
                jug_flag INTEGER,
                hana_flag INTEGER,
                oki_flag INTEGER,
                bt_flag INTEGER
            );
            CREATE TABLE daily_hall_summary (
                date TEXT,
                avg_diff_per_machine INTEGER
            );
            """
        )
        con.commit()
    finally:
        con.close()


def _seed_analysis_db(db_path: Path) -> None:
    _create_tables(db_path)
    con = sqlite3.connect(db_path)
    try:
        pd.DataFrame(
            [
                {"machine_number": 101, "rank_from_min": 1, "section": "501-522"},
                {"machine_number": 102, "rank_from_min": 2, "section": "501-522"},
                {"machine_number": 103, "rank_from_min": 1, "section": "523-546"},
                {"machine_number": 104, "rank_from_min": 3, "section": "523-546"},
            ]
        ).to_sql("machine_layout", con, if_exists="append", index=False)
        pd.DataFrame(
            [
                {"machine_name_normalized": "JugOverlap", "jug_flag": 1, "hana_flag": 0, "oki_flag": 0, "bt_flag": 1},
                {"machine_name_normalized": "BtOnly", "jug_flag": 0, "hana_flag": 0, "oki_flag": 0, "bt_flag": 1},
                {"machine_name_normalized": "OkiBt", "jug_flag": 0, "hana_flag": 0, "oki_flag": 1, "bt_flag": 1},
                {"machine_name_normalized": "Other", "jug_flag": 0, "hana_flag": 0, "oki_flag": 0, "bt_flag": 0},
                {"machine_name_normalized": "NoLayout", "jug_flag": 0, "hana_flag": 1, "oki_flag": 0, "bt_flag": 0},
            ]
        ).to_sql("machine_master", con, if_exists="append", index=False)
        pd.DataFrame(
            [
                {"date": "20250106", "avg_diff_per_machine": 100},
                {"date": "20250107", "avg_diff_per_machine": 50},
                {"date": "20250202", "avg_diff_per_machine": 30},
                {"date": "20250108", "avg_diff_per_machine": -10},
            ]
        ).to_sql("daily_hall_summary", con, if_exists="append", index=False)
        pd.DataFrame(
            [
                {"date": "20250106", "machine_number": 101, "machine_name": "JugOverlap", "diff_coins_normalized": 100, "machine_rank_in_type": 1, "games_normalized": 1000},
                {"date": "20250106", "machine_number": 102, "machine_name": "BtOnly", "diff_coins_normalized": -20, "machine_rank_in_type": 2, "games_normalized": 900},
                {"date": "20250106", "machine_number": 103, "machine_name": "OkiBt", "diff_coins_normalized": 50, "machine_rank_in_type": 1, "games_normalized": 800},
                {"date": "20250106", "machine_number": 104, "machine_name": "Other", "diff_coins_normalized": 10, "machine_rank_in_type": 3, "games_normalized": 700},
                {"date": "20250106", "machine_number": 105, "machine_name": "NoLayout", "diff_coins_normalized": 999, "machine_rank_in_type": 1, "games_normalized": 600},
                {"date": "20250107", "machine_number": 101, "machine_name": "JugOverlap", "diff_coins_normalized": -10, "machine_rank_in_type": 2, "games_normalized": 1000},
                {"date": "20250107", "machine_number": 102, "machine_name": "BtOnly", "diff_coins_normalized": 20, "machine_rank_in_type": 1, "games_normalized": 900},
                {"date": "20250107", "machine_number": 103, "machine_name": "OkiBt", "diff_coins_normalized": 0, "machine_rank_in_type": 2, "games_normalized": 800},
                {"date": "20250107", "machine_number": 104, "machine_name": "Other", "diff_coins_normalized": 5, "machine_rank_in_type": 1, "games_normalized": 700},
                {"date": "20250202", "machine_number": 101, "machine_name": "JugOverlap", "diff_coins_normalized": 40, "machine_rank_in_type": 1, "games_normalized": 1000},
                {"date": "20250202", "machine_number": 102, "machine_name": "BtOnly", "diff_coins_normalized": -5, "machine_rank_in_type": 2, "games_normalized": 900},
                {"date": "20250202", "machine_number": 103, "machine_name": "OkiBt", "diff_coins_normalized": 15, "machine_rank_in_type": 1, "games_normalized": 800},
                {"date": "20250202", "machine_number": 104, "machine_name": "Other", "diff_coins_normalized": -10, "machine_rank_in_type": 3, "games_normalized": 700},
                {"date": "20250108", "machine_number": 101, "machine_name": "JugOverlap", "diff_coins_normalized": 500, "machine_rank_in_type": 1, "games_normalized": 1000},
            ]
        ).to_sql("machine_detailed_results", con, if_exists="append", index=False)
        con.commit()
    finally:
        con.close()


def test_resolve_mitoya_db_path_falls_back_when_index_hint_is_not_a_db(tmp_path: Path) -> None:
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    (db_dir / "ARROW池上店.db").write_bytes(b"")
    (db_dir / "experiments").mkdir()
    (db_dir / "integrated.db").write_bytes(b"")
    (db_dir / "kamata7.db").write_bytes(b"")
    (db_dir / "mitoya.db").write_bytes(b"")
    (db_dir / "poco_analysis.db").write_bytes(b"")
    (db_dir / "schema_notes.md").write_text("note", encoding="utf-8")
    (db_dir / "working_copies").mkdir()
    (db_dir / "みとやスロス.db").write_bytes(b"")
    _seed_analysis_db(db_dir / "みとや大森町店.db")

    resolved = resolve_mitoya_db_path(db_dir=db_dir)

    assert resolved.name == "みとや大森町店.db"


def test_main_writes_expected_csvs_and_filters_to_hall_plus_days(tmp_path: Path, capsys) -> None:
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    (db_dir / "ARROW池上店.db").write_bytes(b"")
    (db_dir / "experiments").mkdir()
    (db_dir / "integrated.db").write_bytes(b"")
    (db_dir / "kamata7.db").write_bytes(b"")
    (db_dir / "mitoya.db").write_bytes(b"")
    (db_dir / "poco_analysis.db").write_bytes(b"")
    (db_dir / "schema_notes.md").write_text("note", encoding="utf-8")
    (db_dir / "working_copies").mkdir()
    (db_dir / "みとやスロス.db").write_bytes(b"")
    _seed_analysis_db(db_dir / "みとや大森町店.db")

    out_dir = tmp_path / "data" / "mitoya_corner_section_analysis"

    exit_code = main(["--db-dir", str(db_dir), "--output-dir", str(out_dir)])

    assert exit_code == 0
    expected_files = {
        "corner_all.csv",
        "corner_by_type.csv",
        "section_all.csv",
        "section_by_type.csv",
        "corner_by_dd.csv",
        "corner_by_weekday.csv",
        "corner_by_mmdd.csv",
        "section_by_dd.csv",
        "section_by_weekday.csv",
        "section_by_mmdd.csv",
    }
    assert {path.name for path in out_dir.iterdir()} == expected_files

    corner_all = pd.read_csv(out_dir / "corner_all.csv")
    rank1 = corner_all.loc[corner_all["rank_from_min"].eq(1)].iloc[0]
    assert rank1["sample_n"] == 6
    assert rank1["avg_diff"] == 32.5
    assert round(float(rank1["plus_rate"]), 6) == round(4.0 / 6.0, 6)
    assert 999 not in corner_all["avg_diff"].tolist()

    by_type = pd.read_csv(out_dir / "corner_by_type.csv")
    rank1_jug = by_type.loc[by_type["machine_type"].eq("jug") & by_type["rank_from_min"].eq(1)].iloc[0]
    rank1_oki = by_type.loc[by_type["machine_type"].eq("oki") & by_type["rank_from_min"].eq(1)].iloc[0]
    assert rank1_jug["sample_n"] == 3
    assert rank1_oki["sample_n"] == 3

    weekday = pd.read_csv(out_dir / "corner_by_weekday.csv")
    assert weekday["day_of_week"].drop_duplicates().tolist() == ["Mon", "Tue", "Sun"]

    captured = capsys.readouterr()
    assert "=== みとや 角番・列 分析サマリー ===" in captured.out
