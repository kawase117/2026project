from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pandas as pd

from ml.last_digit.mitoya_dd_section_digit import (
    build_dd_section_digit_detail,
    build_dd_section_digit_ranking,
    build_dd_section_digit_tables,
    dd_group_for_date,
    extract_dd,
    is_x_day,
    main,
)


def test_dd_extraction() -> None:
    assert extract_dd("20250704") == 4
    assert extract_dd("20251127") == 27


def test_xday_filter() -> None:
    for day in [4, 7, 14, 17, 24, 27]:
        assert is_x_day(f"2025-07-{day:02d}") is True
    for day in [1, 5, 8, 10, 21]:
        assert is_x_day(f"2025-07-{day:02d}") is False


def test_dd_group_assignment() -> None:
    for day in [4, 14, 24]:
        assert dd_group_for_date(f"2025-07-{day:02d}") == "4-group"
    for day in [7, 17, 27]:
        assert dd_group_for_date(f"2025-07-{day:02d}") == "7-group"


def test_deviation_dd_calculation() -> None:
    raw = pd.DataFrame(
        [
            {"date": "2025-07-04", "machine_number": 501, "last_digit": "2", "diff_coins_normalized": 100, "games_normalized": 100},
            {"date": "2025-07-04", "machine_number": 502, "last_digit": "2", "diff_coins_normalized": 200, "games_normalized": 100},
            {"date": "2025-07-04", "machine_number": 503, "last_digit": "2", "diff_coins_normalized": 300, "games_normalized": 100},
            {"date": "2025-07-14", "machine_number": 501, "last_digit": "2", "diff_coins_normalized": 300, "games_normalized": 100},
            {"date": "2025-07-14", "machine_number": 502, "last_digit": "2", "diff_coins_normalized": 400, "games_normalized": 100},
            {"date": "2025-07-14", "machine_number": 503, "last_digit": "2", "diff_coins_normalized": 500, "games_normalized": 100},
            {"date": "2025-07-07", "machine_number": 501, "last_digit": "2", "diff_coins_normalized": 50, "games_normalized": 100},
            {"date": "2025-07-07", "machine_number": 502, "last_digit": "2", "diff_coins_normalized": 150, "games_normalized": 100},
            {"date": "2025-07-07", "machine_number": 503, "last_digit": "2", "diff_coins_normalized": 250, "games_normalized": 100},
        ]
    )
    detail, _, _ = build_dd_section_digit_tables(raw)
    row4 = detail.loc[detail["dd"].eq(4)].iloc[0]
    row7 = detail.loc[detail["dd"].eq(7)].iloc[0]
    assert row4["global_mean"] == 250.0
    assert row4["dd_mean"] == 200.0
    assert row4["deviation_dd"] == -50.0
    assert row7["dd_mean"] == 150.0
    assert row7["deviation_dd"] == -100.0


def test_dd_spread_calculation() -> None:
    detail = pd.DataFrame(
        [
            {"island": "AT島", "section": "A", "last_digit": "1", "dd": 4, "dd_mean": 500.0, "global_mean": 0.0, "deviation_dd": 500.0, "n_records": 5},
            {"island": "AT島", "section": "A", "last_digit": "1", "dd": 14, "dd_mean": 100.0, "global_mean": 0.0, "deviation_dd": 100.0, "n_records": 5},
            {"island": "AT島", "section": "A", "last_digit": "1", "dd": 24, "dd_mean": -200.0, "global_mean": 0.0, "deviation_dd": -200.0, "n_records": 5},
            {"island": "AT島", "section": "A", "last_digit": "2", "dd": 4, "dd_mean": 999.0, "global_mean": 0.0, "deviation_dd": 999.0, "n_records": 4},
        ]
    )
    ranking = build_dd_section_digit_ranking(detail)
    row = ranking.loc[(ranking["island"].eq("AT島")) & (ranking["section"].eq("A")) & (ranking["last_digit"].eq("1"))].iloc[0]
    assert row["best_deviation"] == 500.0
    assert row["worst_deviation"] == -200.0
    assert row["dd_spread"] == 700.0
    assert ranking["last_digit"].eq("2").sum() == 0


def test_min_records_filter() -> None:
    raw = pd.DataFrame(
        [
            {"date": "2025-07-04", "machine_number": 501, "last_digit": "1", "diff_coins_normalized": 100, "games_normalized": 100},
            {"date": "2025-07-04", "machine_number": 502, "last_digit": "1", "diff_coins_normalized": 200, "games_normalized": 100},
        ]
    )
    detail, group, ranking = build_dd_section_digit_tables(raw)
    assert detail.empty
    assert group.empty
    assert ranking.empty


def test_output_files_created() -> None:
    tmp_path = Path(tempfile.mkdtemp(prefix="mitoya_dd_section_digit_"))
    db_path = tmp_path / "mitoya.db"
    rows = []
    for date in ["20250704", "20250714", "20250724", "20250707", "20250717", "20250727"]:
        for machine_number, last_digit, diff in [
            (501, "1", 100),
            (502, "2", 90),
            (503, "3", 80),
            (504, "4", 70),
        ]:
            rows.append(
                {
                    "date": date,
                    "machine_number": machine_number,
                    "last_digit": last_digit,
                    "diff_coins_normalized": diff,
                    "games_normalized": 100,
                }
            )
    with sqlite3.connect(db_path) as con:
        pd.DataFrame(rows).to_sql("machine_detailed_results", con, index=False, if_exists="replace")

    out_dir = tmp_path / "results"
    rc = main(["--db-path", str(db_path), "--output-dir", str(out_dir)])
    assert rc == 0
    assert (out_dir / "mitoya_dd_section_digit_detail.csv").exists()
    assert (out_dir / "mitoya_dd_section_digit_group.csv").exists()
    assert (out_dir / "mitoya_dd_section_digit_ranking.csv").exists()
