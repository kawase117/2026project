from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pandas as pd

from ml.last_digit.mitoya_xday_lag1_cycle import (
    build_xday_daily_rankings,
    build_xday_lag1_cycle_tables,
    classify_dd_group_transition,
    dd_group_for_date,
    is_x_day,
    main,
)


def test_xday_date_sequence() -> None:
    rows = []
    for date in ["2026-01-17", "2026-01-04", "2026-01-14"]:
        for idx in range(3):
            rows.append(
                {
                    "date": date,
                    "machine_number": 501 + idx,
                    "last_digit": "1",
                    "diff_coins_normalized": 10 + idx,
                    "games_normalized": 100,
                }
            )
    raw = pd.DataFrame(
        rows
    )
    ranks = build_xday_daily_rankings(raw)
    assert [ts.day for ts in ranks["date"].tolist()] == [4, 14, 17]


def test_digit_rank_within_island() -> None:
    rows = []
    for digit, diff in [("1", 100), ("2", 90), ("3", 80), ("4", 70)]:
        for idx in range(3):
            rows.append(
                {
                    "date": "2026-01-04",
                    "machine_number": 501 + len(rows),
                    "last_digit": digit,
                    "diff_coins_normalized": diff - idx,
                    "games_normalized": 100,
                }
            )
    raw = pd.DataFrame(
        rows
    )
    ranks = build_xday_daily_rankings(raw)
    rank_map = dict(zip(ranks["last_digit"], ranks["rank"]))
    assert rank_map["1"] == 1
    assert rank_map["2"] == 2
    assert rank_map["3"] == 3
    assert rank_map["4"] == 4


def test_continuation_rate_calculation() -> None:
    rows = []
    dates = ["2026-01-04", "2026-01-14", "2026-01-24", "2026-02-04", "2026-02-14", "2026-02-24"]
    for date in dates:
        diffs = {
            "1": 1000.0,
            "2": 900.0,
            "3": 800.0,
            "4": 700.0,
            "5": 600.0,
            "6": 500.0,
            "7": 400.0,
            "8": 300.0,
            "9": 200.0,
            "10": 100.0,
        }
        for digit, diff in diffs.items():
            for rep in range(3):
                rows.append(
                    {
                        "date": date,
                        "machine_number": 501 + (int(digit) - 1) * 3 + rep,
                        "last_digit": digit,
                        "diff_coins_normalized": diff - rep,
                        "games_normalized": 100,
                    }
                )
    raw = pd.DataFrame(
        rows
    )
    cont, _, _ = build_xday_lag1_cycle_tables(raw)
    row = cont.loc[(cont["island"].eq("AT島")) & (cont["last_digit"].eq("1"))].iloc[0]
    assert row["continuation_rate"] == 1.0
    assert row["n_pairs"] == 5


def test_recovery_rate_calculation() -> None:
    rows = []
    dates = ["2026-01-04", "2026-01-14", "2026-01-24", "2026-02-04", "2026-02-14", "2026-02-24"]
    for idx, date in enumerate(dates):
        if idx % 2 == 0:
            diffs = {
                "1": 1000.0,
                "2": 900.0,
                "4": 800.0,
                "5": 700.0,
                "6": 600.0,
                "7": 500.0,
                "8": 400.0,
                "9": 300.0,
                "10": 200.0,
                "3": 100.0,
            }
        else:
            diffs = {
                "3": 1000.0,
                "1": 900.0,
                "2": 800.0,
                "4": 700.0,
                "5": 600.0,
                "6": 500.0,
                "7": 400.0,
                "8": 300.0,
                "9": 200.0,
                "10": 100.0,
            }
        for digit, diff in diffs.items():
            for rep in range(3):
                rows.append(
                    {
                        "date": date,
                        "machine_number": 601 + (int(digit) - 1) * 3 + rep,
                        "last_digit": digit,
                        "diff_coins_normalized": diff - rep,
                        "games_normalized": 100,
                    }
                )
    raw = pd.DataFrame(
        rows
    )
    cont, _, _ = build_xday_lag1_cycle_tables(raw)
    row = cont.loc[(cont["island"].eq("AT島")) & (cont["last_digit"].eq("3"))].iloc[0]
    assert row["recovery_rate"] == 1.0


def test_min_pairs_filter() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2026-01-04", "2026-01-14"],
            "machine_number": [501, 501],
            "last_digit": ["1", "1"],
            "diff_coins_normalized": [100, 200],
            "games_normalized": [100, 100],
        }
    )
    cont, _, dd_group = build_xday_lag1_cycle_tables(raw)
    assert cont.empty
    assert dd_group.empty


def test_dd_group_classification() -> None:
    assert dd_group_for_date("2026-01-04") == "4系"
    assert dd_group_for_date("2026-01-14") == "4系"
    assert dd_group_for_date("2026-01-24") == "4系"
    assert classify_dd_group_transition("2026-01-04", "2026-01-14") == "intra"
    assert classify_dd_group_transition("2026-01-04", "2026-01-07") == "inter"


def test_output_files_created() -> None:
    tmp_path = Path(tempfile.mkdtemp(prefix="mitoya_xday_lag1_"))
    db_path = tmp_path / "mitoya.db"
    rows = []
    for date in ["20260104", "20260114", "20260124", "20260127", "20260204", "20260214"]:
        for machine_number, last_digit, diff in [
            (501, "1", 100),
            (502, "2", 90),
            (503, "3", 80),
            (504, "4", 70),
            (505, "5", 60),
            (506, "6", 50),
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
    assert (out_dir / "mitoya_xday_lag1_continuation.csv").exists()
    assert (out_dir / "mitoya_xday_lag1_streak.csv").exists()
    assert (out_dir / "mitoya_xday_lag1_by_dd_group.csv").exists()
