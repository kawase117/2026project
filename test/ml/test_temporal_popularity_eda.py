from __future__ import annotations

import pandas as pd
import pytest

from ml.machine_type.exploratory import run_temporal_popularity_eda as temporal_eda


def _base_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "hall_id": ["hall_a", "hall_a", "hall_a", "hall_a", "hall_b", "hall_b"],
            "machine_name": ["m1", "m1", "m1", "m1", "m1", "m1"],
            "date": pd.to_datetime(
                [
                    "2026-01-01",
                    "2026-01-02",
                    "2026-01-04",
                    "2026-03-01",
                    "2026-01-01",
                    "2026-01-02",
                ]
            ),
            "machine_count": [2, 2, 2, 2, 3, 3],
            "total_games": [100, 120, 140, 300, 50, 60],
            "avg_games": [50, 60, 70, 150, 25, 30],
            "total_diff_coins": [10, 20, 30, 90, 5, 6],
            "avg_diff_coins": [10, 20, 30, 90, 5, 6],
            "win_rate": [0.5, 0.6, 0.7, 0.9, 0.4, 0.5],
            "efficiency": [0.10, 0.1666666667, 0.2142857143, 0.30, 0.10, 0.10],
            "is_top_3": [0, 1, 1, 1, 0, 0],
        }
    )


def test_add_temporal_lag_features_uses_calendar_shift_and_keeps_gap_na() -> None:
    frame = _base_rows().loc[:3].copy()

    out = temporal_eda.add_temporal_lag_features(frame)

    row_by_date = out.set_index("date")

    assert pd.isna(row_by_date.loc[pd.Timestamp("2026-01-01"), "lag1_efficiency"])
    assert row_by_date.loc[pd.Timestamp("2026-01-02"), "lag1_efficiency"] == pytest.approx(0.10)
    assert row_by_date.loc[pd.Timestamp("2026-01-02"), "lag1_total_diff_coins"] == pytest.approx(10.0)
    assert row_by_date.loc[pd.Timestamp("2026-01-02"), "lag1_is_top_3"] == 0

    assert row_by_date.loc[pd.Timestamp("2026-01-04"), "lag1_efficiency"] is pd.NA or pd.isna(
        row_by_date.loc[pd.Timestamp("2026-01-04"), "lag1_efficiency"]
    )
    assert pd.isna(row_by_date.loc[pd.Timestamp("2026-01-04"), "lag2_efficiency"])
    assert pd.isna(row_by_date.loc[pd.Timestamp("2026-01-04"), "lag1_total_diff_coins"])


def test_add_temporal_lag_features_separates_halls_with_same_machine_name() -> None:
    frame = _base_rows().loc[[0, 1, 5]].copy()

    out = temporal_eda.add_temporal_lag_features(frame)
    hall_b_day2 = out.loc[(out["hall_id"] == "hall_b") & (out["date"] == pd.Timestamp("2026-01-02"))].iloc[0]

    assert pd.isna(hall_b_day2["lag1_efficiency"])
    assert pd.isna(hall_b_day2["lag1_total_diff_coins"])
    assert hall_b_day2["entity_key"] == "hall_b::m1"


def test_add_monthly_popularity_features_uses_previous_calendar_month_and_two_month_lag() -> None:
    frame = _base_rows().loc[[0, 1, 2, 3]].copy()

    out = temporal_eda.add_monthly_popularity_features(frame)

    march = out.loc[out["date"] == pd.Timestamp("2026-03-01")].iloc[0]
    january = out.loc[out["date"] == pd.Timestamp("2026-01-01")].iloc[0]

    assert pd.isna(january["prev_month_total_games"])
    assert pd.isna(january["prev2_month_total_games"])

    assert pd.isna(march["prev_month_total_games"])
    assert pd.isna(march["prev_month_avg_efficiency"])
    assert march["prev2_month_total_games"] == pytest.approx(360.0)
    assert march["prev2_month_avg_efficiency"] == pytest.approx((0.10 + 0.1666666667 + 0.2142857143) / 3.0)
