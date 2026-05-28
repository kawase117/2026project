import sys
from pathlib import Path

import pandas as pd
import pandas.testing as pdt


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LAST_DIGIT_DIR = (
    PROJECT_ROOT
    / "db"
    / "experiments"
    / "マルハンメガシティ2000-蒲田7_exp"
    / "last_digit"
)
sys.path.insert(0, str(LAST_DIGIT_DIR))

from phase10_antipattern_features import ANTI_PATTERN_FEATURES, compute_antipattern_features


def test_same_weekday_rolling_rank_sum_uses_only_prior_occurrences():
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-05", "2026-01-12", "2026-01-19", "2026-01-26"]),
            "last_digit": ["1", "1", "1", "1"],
            "digit_rank": [5, 1, 3, 1],
            "is_rank_1": [0, 1, 0, 1],
            "total_diff_coins": [100, 200, -50, 300],
            "total_games": [1000, 1200, 1100, 1300],
        }
    )

    result = compute_antipattern_features(df)

    assert result["same_weekday_rolling_rank_sum_3"].tolist() == [0.0, 5.0, 6.0, 9.0]


def test_first_observation_per_digit_has_no_history_signal():
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-12", "2026-01-13"]),
            "last_digit": ["1", "2", "1", "2"],
            "digit_rank": [5, 2, 1, 4],
            "is_rank_1": [0, 0, 1, 0],
            "total_diff_coins": [100, 50, 200, -10],
            "total_games": [1000, 900, 1200, 950],
        }
    )

    result = compute_antipattern_features(df)

    first_rows = result.groupby("last_digit", sort=False).head(1)
    days_since_features = {
        "days_since_last_worst1",
        "days_since_last_worst3",
        "days_since_last_worst5",
    }
    for feature_name in ANTI_PATTERN_FEATURES:
        if feature_name in days_since_features:
            assert (first_rows[feature_name] == 365.0).all(), feature_name
        else:
            assert (first_rows[feature_name] == 0).all(), feature_name


def test_past_rows_do_not_change_when_future_rows_are_appended():
    prefix = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-05", "2026-01-12", "2026-01-19", "2026-01-26"]),
            "last_digit": ["1", "1", "1", "1"],
            "digit_rank": [5, 1, 3, 1],
            "is_rank_1": [0, 1, 0, 1],
            "total_diff_coins": [100, 200, -50, 300],
            "total_games": [1000, 1200, 1100, 1300],
        }
    )
    future_rows = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-02", "2026-02-09"]),
            "last_digit": ["1", "1"],
            "digit_rank": [10, 1],
            "is_rank_1": [0, 1],
            "total_diff_coins": [20, 500],
            "total_games": [950, 1400],
        }
    )

    result_prefix = compute_antipattern_features(prefix)
    result_full = compute_antipattern_features(pd.concat([prefix, future_rows], ignore_index=True))

    pdt.assert_frame_equal(
        result_prefix[ANTI_PATTERN_FEATURES].reset_index(drop=True),
        result_full.loc[: len(prefix) - 1, ANTI_PATTERN_FEATURES].reset_index(drop=True),
    )


def test_worst1_days_since_and_streak_use_only_past_rows():
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]),
            "last_digit": ["1", "1", "1", "1"],
            "digit_rank": [10, 10, 9, 10],
            "is_rank_1": [0, 0, 0, 0],
            "total_diff_coins": [-100, -200, -300, -50],
            "total_games": [1000, 900, 800, 700],
        }
    )

    result = compute_antipattern_features(df)

    assert result["days_since_last_worst1"].tolist() == [365.0, 1.0, 1.0, 1.0]
    assert result["worst1_streak"].tolist() == [0.0, 1.0, 2.0, 3.0]
