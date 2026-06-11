from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pandas as pd

from ml.last_digit.mitoya_section_digit_xday import (
    assign_island,
    build_section_digit_xday_tables,
    is_x_day,
    main,
)


def test_island_assignment() -> None:
    assert assign_island(501) == "AT島"
    assert assign_island(641) == "ジャグラー島"
    assert assign_island(700) == "バラエティ島"


def test_xday_filter() -> None:
    for day in [4, 7, 14, 17, 24, 27]:
        assert is_x_day(day) is True
    for day in [1, 3, 8]:
        assert is_x_day(day) is False


def test_deviation_calculation() -> None:
    raw = pd.DataFrame(
        {
            "date": [
                "2026-01-04",
                "2026-01-14",
                "2026-01-24",
                "2026-01-07",
                "2026-01-17",
                "2026-01-05",
            ],
            "machine_number": [501, 501, 501, 501, 501, 501],
            "last_digit": ["4", "4", "4", "4", "4", "4"],
            "diff_coins_normalized": [10, 20, 30, 40, 50, 60],
            "games_normalized": [100, 120, 110, 100, 110, 130],
            "section": ["501-522"] * 6,
        }
    )

    allperiod, byperiod = build_section_digit_xday_tables(raw)

    row = allperiod.iloc[0]
    assert row["xday_mean"] == 30.0
    assert row["global_mean"] == 35.0
    assert row["deviation"] == -5.0
    assert row["n_xday_records"] == 5
    assert row["n_global_records"] == 6

    period_row = byperiod.loc[byperiod["period"].eq("旧店長2026前半")]
    assert period_row.empty is False


def test_min_records_filter() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2026-01-04", "2026-01-14", "2026-01-24", "2026-01-05"],
            "machine_number": [501, 501, 501, 501],
            "last_digit": ["4", "4", "4", "4"],
            "diff_coins_normalized": [10, 20, 30, 40],
            "games_normalized": [100, 100, 100, 100],
            "section": ["501-522"] * 4,
        }
    )

    allperiod, byperiod = build_section_digit_xday_tables(raw)
    assert allperiod.empty
    assert byperiod.empty


def test_output_files_created() -> None:
    tmp_path = Path(tempfile.mkdtemp(prefix="mitoya_section_digit_xday_"))
    db_path = tmp_path / "mitoya.db"
    with sqlite3.connect(db_path) as con:
        pd.DataFrame(
            {
                "date": ["20260104", "20260104", "20260114", "20260114", "20260504", "20260504"],
                "machine_number": [501, 502, 501, 502, 501, 502],
                "last_digit": ["4", "7", "4", "7", "4", "7"],
                "diff_coins_normalized": [10, 20, 30, 40, 50, 60],
                "games_normalized": [100, 110, 120, 130, 140, 150],
            }
        ).to_sql("machine_detailed_results", con, index=False, if_exists="replace")
        pd.DataFrame(
            {
                "machine_number": [501, 502],
                "section": ["501-522", "501-522"],
                "section_min": [501, 501],
                "section_max": [522, 522],
            }
        ).to_sql("machine_layout", con, index=False, if_exists="replace")

    out_dir = tmp_path / "results"
    rc = main(["--db-path", str(db_path), "--output-dir", str(out_dir)])
    assert rc == 0
    assert (out_dir / "mitoya_section_digit_xday_allperiod.csv").exists()
    assert (out_dir / "mitoya_section_digit_xday_byperiod.csv").exists()
