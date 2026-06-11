from __future__ import annotations

import pandas as pd

from ml.last_digit.mitoya_dd_last_digit_cross_analysis import build_dd_last_digit_cross


def test_build_dd_last_digit_cross_uses_daily_means_and_a_counts() -> None:
    raw = pd.DataFrame(
        {
            "date": [
                "2026-01-04",
                "2026-01-04",
                "2026-02-04",
                "2026-02-04",
                "2026-01-30",
            ],
            "last_digit": ["4", "4", "4", "5", "4"],
            "diff_coins_normalized": [10.0, 30.0, 20.0, 40.0, 100.0],
            "is_a_type": [1, 0, 1, 1, 0],
        }
    )

    cross, summary = build_dd_last_digit_cross(raw)

    row = cross.loc[(cross["dd"].eq(4)) & (cross["last_digit"].eq("4"))].iloc[0]
    assert row["mean_diff"] == 20.0
    assert row["n_dates"] == 2
    assert row["n_machines"] == 3
    assert row["n_A_machines"] == 2

    dd30_row = cross.loc[(cross["dd"].eq(30)) & (cross["last_digit"].eq("4"))].iloc[0]
    assert dd30_row["mean_diff"] == 100.0
    assert dd30_row["n_dates"] == 1
    assert dd30_row["n_machines"] == 1
    assert dd30_row["n_A_machines"] == 0

    assert set(summary.columns) >= {"dd", "n_dates", "mean_diff_top3", "mean_diff_bottom3", "dd_spread"}


def test_build_dd_last_digit_cross_computes_dd_spread_from_top3_and_bottom3() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2026-01-07"] * 10,
            "last_digit": [str(d) for d in range(10)],
            "diff_coins_normalized": [float(d) for d in range(10)],
            "is_a_type": [1 if d % 2 == 0 else 0 for d in range(10)],
        }
    )

    cross, summary = build_dd_last_digit_cross(raw)

    assert len(cross) == 10
    dd_row = summary.loc[summary["dd"].eq(7)].iloc[0]
    assert dd_row["mean_diff_top3"] == 8.0
    assert dd_row["mean_diff_bottom3"] == 1.0
    assert dd_row["dd_spread"] == 7.0
    assert dd_row["n_dates"] == 1
