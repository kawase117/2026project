from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from ml.corner_section.mitoya_corner_composite import main


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
                rank_from_max INTEGER,
                rank_from_aisle INTEGER,
                is_reversed_section INTEGER,
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


def _seed_composite_db(db_path: Path) -> None:
    _create_tables(db_path)
    con = sqlite3.connect(db_path)
    try:
        machine_numbers = [1, 2, 3, 4, 5, 645, 646, 647, 648, 649, 692, 693, 694, 695, 696]
        layout_rows = []
        master_rows = []
        for machine_number in machine_numbers:
            rank = ((machine_number - 1) % 5) + 1
            layout_rows.append(
                {
                    "machine_number": machine_number,
                    "rank_from_min": rank,
                    "rank_from_max": 6 - rank,
                    "rank_from_aisle": rank,
                    "is_reversed_section": 0,
                    "section": "574-590" if machine_number < 645 else "641-657",
                }
            )
            master_rows.append(
                {
                    "machine_name_normalized": f"M{machine_number}",
                    "jug_flag": 1 if machine_number == 645 else 0,
                    "hana_flag": 1 if machine_number == 648 else 0,
                    "oki_flag": 1 if machine_number == 692 else 0,
                    "bt_flag": 1 if machine_number == 5 else 0,
                }
            )
        pd.DataFrame(
            layout_rows
        ).to_sql("machine_layout", con, if_exists="append", index=False)
        pd.DataFrame(
            master_rows
        ).to_sql("machine_master", con, if_exists="append", index=False)
        pd.DataFrame(
            [
                {"date": "20250504", "avg_diff_per_machine": 120},
                {"date": "20250505", "avg_diff_per_machine": 80},
                {"date": "20250507", "avg_diff_per_machine": 90},
                {"date": "20250512", "avg_diff_per_machine": 60},
                {"date": "20250514", "avg_diff_per_machine": -5},
            ]
        ).to_sql("daily_hall_summary", con, if_exists="append", index=False)
        pd.DataFrame(
            [
                {
                    "date": date,
                    "machine_number": machine_number,
                    "machine_name": f"M{machine_number}",
                    "diff_coins_normalized": 300 - (((machine_number - 1) % 5) * 40) + offset * 5,
                    "machine_rank_in_type": ((machine_number - 1) % 5) + 1,
                    "games_normalized": 5000 - (((machine_number - 1) % 5) * 300) + offset * 10,
                }
                for offset, date in enumerate(["20250504", "20250505", "20250507", "20250512"])
                for machine_number in machine_numbers
            ]
        ).to_sql("machine_detailed_results", con, if_exists="append", index=False)
        con.commit()
    finally:
        con.close()


def test_composite_main_writes_comparable_table(tmp_path: Path) -> None:
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    db_path = db_dir / "mitoya.db"
    _seed_composite_db(db_path)

    out_dir = tmp_path / "data" / "mitoya_corner_deep"
    exit_code = main(
        [
            "--db-path",
            str(db_path),
            "--output-dir",
            str(out_dir),
        ]
    )

    assert exit_code == 0
    csv_path = out_dir / "corner_composite.csv"
    assert csv_path.exists()
    df = pd.read_csv(csv_path)
    assert set(df["corner_metric"].unique()) == {"rank_from_min", "rank_from_aisle", "physical_corner"}
    assert set(df["island"].unique()) == {"all", "main_jug", "bari", "main_mix"}
    assert {"dd_group", "day_of_week", "rank", "avg_games", "avg_diff", "sample_n"}.issubset(df.columns)
    assert "その他" in set(df["dd_group"].astype(str))
