from __future__ import annotations

import math

import pandas as pd
import pytest

from eda import kamata7_machinename_q5_backtest as backtest


def _make_period_frame(include_q5_in_test: bool = True) -> pd.DataFrame:
    train_dates = [
        "20250107",
        "20250207",
        "20250307",
    ]
    test_dates = [
        "20250407",
        "20250408",
        "20250417",
    ]
    train_specs = {
        "A": {"machine_number": 1001, "diffs": [10, 10, 10]},
        "B": {"machine_number": 1002, "diffs": [20, 20, 20]},
        "C": {"machine_number": 3001, "diffs": [30, 30, 30]},
        "D": {"machine_number": 3002, "diffs": [40, 40, 40]},
        "E": {"machine_number": 3003, "diffs": [50, 50, 50]},
    }
    test_specs = {
        "A": {"machine_number": 1001, "date": test_dates[0], "diff": -100},
        "B": {"machine_number": 1002, "date": test_dates[0], "diff": 0},
        "C": {"machine_number": 3001, "date": test_dates[1], "diff": 50},
        "D": {"machine_number": 3002, "date": test_dates[2], "diff": 100},
        "E": {"machine_number": 3003, "date": test_dates[2], "diff": 200},
    }
    rows: list[dict[str, object]] = []
    for machine_name, spec in train_specs.items():
        for date, diff in zip(train_dates, spec["diffs"], strict=True):
            rows.append(
                {
                    "date": date,
                    "machine_number": spec["machine_number"],
                    "machine_name": machine_name,
                    "diff_coins_normalized": diff,
                    "games_normalized": 1000,
                }
            )
    for machine_name, spec in test_specs.items():
        if machine_name == "E" and not include_q5_in_test:
            continue
        rows.append(
            {
                "date": spec["date"],
                "machine_number": spec["machine_number"],
                "machine_name": machine_name,
                "diff_coins_normalized": spec["diff"],
                "games_normalized": 1000,
            }
        )
    return pd.DataFrame(rows)


def test_build_outputs_summarizes_q5_q1_all_and_xday_overlay() -> None:
    outputs = backtest.build_backtest_outputs(_make_period_frame())

    summary = outputs["period_summary"]
    assert len(summary) == 1
    row = summary.iloc[0]

    assert row["period_train"] == 0
    assert row["period_test"] == 1
    assert row["Q5_avg_diff"] == pytest.approx(200.0)
    assert row["Q5_payout_rate"] == pytest.approx((3000 + 200) / 3000 * 100)
    assert row["Q5_win_rate"] == pytest.approx(1.0)
    assert row["Q5_n_machine_days"] == 1
    assert row["Q1_avg_diff"] == pytest.approx(-100.0)
    assert row["Q1_payout_rate"] == pytest.approx((3000 - 100) / 3000 * 100)
    assert row["Q1_win_rate"] == pytest.approx(0.0)
    assert row["Q1_n_machine_days"] == 1
    assert row["All_avg_diff"] == pytest.approx(50.0)
    assert row["All_payout_rate"] == pytest.approx((15000 + 250) / 15000 * 100)
    assert row["All_win_rate"] == pytest.approx(3 / 5)
    assert row["All_n_machine_days"] == 5
    assert row["Q5_vs_All_diff"] == pytest.approx(150.0)
    assert row["Q5_vs_Q1_diff"] == pytest.approx(300.0)

    floor_2f = outputs["period_summary_2F"].iloc[0]
    assert floor_2f["All_avg_diff"] == pytest.approx(-50.0)
    assert floor_2f["All_n_machine_days"] == 2

    floor_3f = outputs["period_summary_3F"].iloc[0]
    assert floor_3f["All_avg_diff"] == pytest.approx((50 + 100 + 200) / 3)
    assert floor_3f["All_n_machine_days"] == 3

    xday = outputs["xday7_overlay"].iloc[0]
    assert xday["n_xday_dates"] == 2
    assert xday["All_avg_diff"] == pytest.approx(50.0)
    assert xday["All_n_machine_days"] == 4
    assert xday["Q5_avg_diff"] == pytest.approx(200.0)

    picked = outputs["q5_machinenames_per_period"]
    assert set(picked["machine_name"]) == {"A", "E"}
    assert set(picked["quintile"]) == {1, 5}


def test_build_outputs_skips_pair_when_q5_machinename_disappears() -> None:
    outputs = backtest.build_backtest_outputs(_make_period_frame(include_q5_in_test=False))

    row = outputs["period_summary"].iloc[0]
    assert row["period_train"] == 0
    assert row["period_test"] == 1
    assert math.isnan(row["Q5_avg_diff"])
    assert math.isnan(row["Q1_avg_diff"])
    assert math.isnan(row["All_avg_diff"])
    assert math.isnan(row["Q5_vs_All_diff"])
    assert math.isnan(row["Q5_vs_Q1_diff"])

    xday = outputs["xday7_overlay"].iloc[0]
    assert xday["n_xday_dates"] == 2
    assert math.isnan(xday["All_avg_diff"])

