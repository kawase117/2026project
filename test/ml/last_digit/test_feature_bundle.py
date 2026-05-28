import pandas as pd

from ml.last_digit.tail_ltr_split_rule_wf import add_simple_features


def _base_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "entity_key": ["3F_A|1", "3F_A|1"],
            "total_diff_coins": [100.0, 200.0],
            "total_diff_coins_focus": [80.0, 160.0],
            "total_games": [10.0, 20.0],
            "efficiency": [10.0, 10.0],
            "efficiency_focus": [8.0, 8.0],
            "win_rate": [0.5, 0.6],
            "is_top_2": [1, 0],
            "lag1_hall_digit_diff": [11.0, 22.0],
            "lag5_hall_digit_diff": [15.0, 25.0],
            "lag7_hall_digit_diff": [17.0, 27.0],
        }
    )


def test_digit_lag_bundle_is_disabled_by_default():
    out = add_simple_features(_base_df())
    assert "lag1_digit_diff" not in out.columns
    assert "lag5_digit_diff" not in out.columns
    assert "lag7_digit_diff" not in out.columns


def test_digit_lag_bundle_adds_expected_columns_when_enabled():
    out = add_simple_features(_base_df(), enable_digit_lag_bundle=True)
    assert list(out["lag1_digit_diff"]) == [11.0, 22.0]
    assert list(out["lag5_digit_diff"]) == [15.0, 25.0]
    assert list(out["lag7_digit_diff"]) == [17.0, 27.0]

