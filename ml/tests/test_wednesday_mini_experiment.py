import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEDNESDAY_DIR = (
    PROJECT_ROOT
    / "db"
    / "experiments"
    / "マルハンメガシティ2000-蒲田7_sandbox_exp"
    / "last_digit"
)
sys.path.insert(0, str(WEDNESDAY_DIR))

from wednesday_mini_experiment import (  # noqa: E402
    build_subgroup_diagnostics,
    drop_constant_features,
    filter_wednesday_rows,
    select_forecast_safe_feature_columns,
    split_by_last_unique_dates,
)


def test_filter_wednesday_rows_can_optionally_exclude_event_days() -> None:
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2026-05-04",  # Monday
                    "2026-05-06",  # Wednesday event day
                    "2026-05-13",  # Wednesday non-event
                    "2026-05-14",  # Thursday
                ]
            ),
            "day_of_week": [0, 2, 2, 3],
            "is_event_day": [0, 1, 0, 0],
        }
    )

    wed_only = filter_wednesday_rows(df)
    wed_non_event = filter_wednesday_rows(df, exclude_event_days=True)

    assert wed_only["day_of_week"].tolist() == [2, 2]
    assert wed_only["is_event_day"].tolist() == [1, 0]
    assert wed_non_event["date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-05-13"]


def test_split_by_last_unique_dates_uses_tail_dates_as_holdout() -> None:
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2026-01-01",
                    "2026-01-01",
                    "2026-01-08",
                    "2026-01-08",
                    "2026-01-15",
                    "2026-01-15",
                ]
            )
        }
    )

    train_idx, test_idx = split_by_last_unique_dates(df, test_date_count=1)

    assert train_idx.tolist() == [True, True, True, True, False, False]
    assert test_idx.tolist() == [False, False, False, False, True, True]


def test_drop_constant_features_removes_only_constant_columns() -> None:
    train_df = pd.DataFrame(
        {
            "day_of_week": [2, 2, 2],
            "is_event_day": [0, 1, 0],
            "lag_1_diff": [1.0, 2.0, 3.0],
            "constant_col": [7, 7, 7],
        }
    )
    test_df = pd.DataFrame(
        {
            "day_of_week": [2, 2],
            "is_event_day": [1, 0],
            "lag_1_diff": [4.0, 5.0],
            "constant_col": [7, 7],
        }
    )

    filtered_train, filtered_test, kept_features = drop_constant_features(
        train_df,
        test_df,
        ["day_of_week", "is_event_day", "lag_1_diff", "constant_col"],
    )

    assert kept_features == ["is_event_day", "lag_1_diff"]
    assert list(filtered_train.columns) == ["is_event_day", "lag_1_diff"]
    assert list(filtered_test.columns) == ["is_event_day", "lag_1_diff"]


def test_select_forecast_safe_feature_columns_excludes_leaky_columns() -> None:
    df = pd.DataFrame(
        columns=[
            "date",
            "entity_key",
            "last_digit",
            "machine_count",
            "day_of_week",
            "day_of_month",
            "month_progress",
            "is_month_end_event",
            "event_group",
            "is_event_day",
            "days_since_last_event_any",
            "days_to_next_event_any",
            "is_event_week",
            "event_proximity_score",
            "lag_1_diff",
            "rolling_avg_diff_7d",
            "days_since_last_rank1",
            "prior_top3_rate",
            "same_weekday_lag_1_diff",
            "same_day_of_month_rolling_avg_diff_3",
            "win_rate",
            "total_diff_coins",
            "efficiency",
            "dow_lastdigit_rank1_rate",
            "weekday_digit_bias",
            "anti_pattern_rank1_rate",
            "same_weekday_top3_rate",
            "same_day_of_month_top3_gap",
            "same_weekday_rolling_rank_sum_3",
            "lag_1_diff_minus_rolling_avg_diff_7d",
            "total_games_bin",
        ]
    )

    selected = select_forecast_safe_feature_columns(df)

    assert selected == [
        "machine_count",
        "day_of_week",
        "day_of_month",
        "month_progress",
        "is_month_end_event",
        "event_group",
        "is_event_day",
        "days_since_last_event_any",
        "days_to_next_event_any",
        "is_event_week",
        "event_proximity_score",
        "lag_1_diff",
        "rolling_avg_diff_7d",
        "days_since_last_rank1",
        "prior_top3_rate",
        "same_weekday_lag_1_diff",
        "same_day_of_month_rolling_avg_diff_3",
        "lag_1_diff_minus_rolling_avg_diff_7d",
    ]


def test_build_subgroup_diagnostics_reports_event_and_non_event_slices() -> None:
    diagnostics = build_subgroup_diagnostics(
        y_true=[0, 1, 0, 1],
        y_pred_proba=[0.1, 0.9, 0.2, 0.8],
        event_mask=[1, 1, 0, 0],
    )

    assert diagnostics["all"]["auc"] == 1.0
    assert diagnostics["event"]["precision"] == 1.0
    assert diagnostics["non_event"]["recall"] == 1.0
