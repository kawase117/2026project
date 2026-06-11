from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from ml.corner_section.mitoya_corner_drift import main


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


def _seed_drift_db(db_path: Path) -> None:
    _create_tables(db_path)
    con = sqlite3.connect(db_path)
    try:
        layout_rows = []
        machine_rows = []
        for base, start in [(1, 1), (645, 645), (692, 692)]:
            for offset in range(5):
                machine_number = start + offset
                layout_rows.append(
                    {
                        "machine_number": machine_number,
                        "rank_from_min": offset + 1,
                        "rank_from_max": 5 - offset,
                        "rank_from_aisle": offset + 1,
                        "is_reversed_section": 0,
                        "section": "501-522",
                    }
                )
                machine_rows.append(
                    {
                        "machine_name_normalized": f"M{machine_number}",
                        "jug_flag": 1 if machine_number == 645 else 0,
                        "hana_flag": 0,
                        "oki_flag": 0,
                        "bt_flag": 0,
                    }
                )
        pd.DataFrame(
            layout_rows
        ).to_sql("machine_layout", con, if_exists="append", index=False)
        pd.DataFrame(
            machine_rows
        ).to_sql("machine_master", con, if_exists="append", index=False)
        dates = pd.date_range("2025-01-01", periods=200, freq="D")
        pd.DataFrame(
            [{"date": d.strftime("%Y%m%d"), "avg_diff_per_machine": 100} for d in dates]
        ).to_sql("daily_hall_summary", con, if_exists="append", index=False)
        rows = []
        for d in dates:
            for machine_number in [1, 2, 3, 4, 5, 645, 646, 647, 648, 649, 692, 693, 694, 695, 696]:
                rank = ((machine_number - 1) % 5) + 1
                rows.append(
                    {
                        "date": d.strftime("%Y%m%d"),
                        "machine_number": machine_number,
                        "machine_name": f"M{machine_number}",
                        "diff_coins_normalized": 120 - rank * 20 + (machine_number // 100),
                        "machine_rank_in_type": rank,
                        "games_normalized": 5000 - rank * 200 + (machine_number // 100) * 10,
                    }
                )
        pd.DataFrame(rows).to_sql("machine_detailed_results", con, if_exists="append", index=False)
        con.commit()
    finally:
        con.close()


def test_drift_main_writes_comparable_timeseries(tmp_path: Path) -> None:
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    db_path = db_dir / "mitoya.db"
    _seed_drift_db(db_path)

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
    csv_path = out_dir / "corner_drift_timeseries.csv"
    assert csv_path.exists()
    df = pd.read_csv(csv_path)
    assert set(df["corner_metric"].unique()) == {"rank_from_min", "rank_from_aisle", "physical_corner"}
    assert set(df["island"].unique()) == {"all", "main_jug", "bari", "main_mix"}
    assert {"window_end", "window_start", "rank1_avg_diff", "rank5_avg_diff", "gradient_diff"}.issubset(df.columns)
    assert df["gradient_diff"].notna().any()
