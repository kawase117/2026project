from __future__ import annotations

import pandas as pd

from ml.last_digit.clean_holdout_audit import _apply_feature_profile


def _base_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "group_key": ["2F_N", "2F_N"],
            "entity_key": ["2F_N|1", "2F_N|1"],
            "last_digit": ["1", "1"],
            "is_top_2": [0, 1],
            "total_diff_coins": [100.0, 200.0],
            "machine_count": [10, 10],
            "lag1_total_diff_coins": [0.0, 100.0],
            "roll7_total_diff_coins": [0.0, 100.0],
            "prior_top2_rate": [0.0, 0.1],
            "weekday": [3, 4],
            "weekday_sin": [0.1, 0.2],
            "weekday_cos": [0.9, 0.8],
            "lag1_hall_digit_diff": [0.0, 10.0],
            "lag1_digit_diff": [0.0, 5.0],
        }
    )


def test_apply_feature_profile_lag_roll_keeps_lag_roll_only() -> None:
    out = _apply_feature_profile(_base_df(), "lag_roll")
    assert "machine_count" in out.columns
    assert "lag1_total_diff_coins" in out.columns
    assert "roll7_total_diff_coins" in out.columns
    assert "prior_top2_rate" not in out.columns
    assert "weekday" not in out.columns


def test_apply_feature_profile_prior_calendar_keeps_prior_and_weekday() -> None:
    out = _apply_feature_profile(_base_df(), "prior_calendar")
    assert "machine_count" in out.columns
    assert "prior_top2_rate" in out.columns
    assert "weekday" in out.columns
    assert "weekday_sin" in out.columns
    assert "lag1_total_diff_coins" not in out.columns


def test_apply_feature_profile_hall_digit_keeps_hall_digit_bundle() -> None:
    out = _apply_feature_profile(_base_df(), "hall_digit")
    assert "machine_count" in out.columns
    assert "lag1_hall_digit_diff" in out.columns
    assert "lag1_digit_diff" in out.columns
    assert "prior_top2_rate" not in out.columns
    assert "weekday" not in out.columns
