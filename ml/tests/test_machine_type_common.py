import pandas as pd
import pytest

from ml.machine_type import machine_type_common as common


def _sample_daily_machine_type_summary() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"date": "20260101", "machine_name": "A", "machine_count": 1, "total_games": 1000, "avg_games": 1000.0, "total_diff_coins": 10000, "avg_diff_coins": 10000.0, "win_rate": 0.8},
            {"date": "20260101", "machine_name": "B", "machine_count": 40, "total_games": 40000, "avg_games": 1000.0, "total_diff_coins": 60000, "avg_diff_coins": 1500.0, "win_rate": 0.6},
            {"date": "20260102", "machine_name": "A", "machine_count": 1, "total_games": 1200, "avg_games": 1200.0, "total_diff_coins": 5000, "avg_diff_coins": 5000.0, "win_rate": 0.7},
            {"date": "20260102", "machine_name": "B", "machine_count": 42, "total_games": 42000, "avg_games": 1000.0, "total_diff_coins": 63000, "avg_diff_coins": 1500.0, "win_rate": 0.6},
            {"date": "20260109", "machine_name": "A", "machine_count": 1, "total_games": 800, "avg_games": 800.0, "total_diff_coins": -2000, "avg_diff_coins": -2000.0, "win_rate": 0.3},
            {"date": "20260109", "machine_name": "B", "machine_count": 41, "total_games": 41000, "avg_games": 1000.0, "total_diff_coins": 40000, "avg_diff_coins": 975.6, "win_rate": 0.55},
        ]
    )


def test_build_shrunk_labels_contains_expected_targets() -> None:
    df = common.prepare_machine_type_base_frame(_sample_daily_machine_type_summary())
    ranked = common.add_shrunk_rank_targets(df, alpha=5.0)
    day1 = ranked.loc[ranked["date"].eq(pd.Timestamp("2026-01-01"))].sort_values("shrunk_rank")
    assert day1.iloc[0]["machine_name"] == "A"
    assert {"raw_avg_rank", "shrunk_rank", "shrunk_avg_diff", "is_top_2", "is_top_3", "is_top_5"} <= set(day1.columns)


def test_lag_features_use_prior_only_history() -> None:
    df = common.prepare_machine_type_base_frame(_sample_daily_machine_type_summary())
    ranked = common.add_shrunk_rank_targets(df, alpha=5.0)
    featured = common.add_machine_type_features(ranked)
    row = featured.loc[(featured["machine_name"] == "A") & (featured["date"] == pd.Timestamp("2026-01-02"))].iloc[0]
    assert row["lag_1_avg_diff_coins"] == pytest.approx(10000.0)
    assert row["rolling_avg_diff_7d"] == pytest.approx(10000.0)


def test_count_change_and_new_machine_recency_features() -> None:
    df = common.prepare_machine_type_base_frame(_sample_daily_machine_type_summary())
    ranked = common.add_shrunk_rank_targets(df, alpha=5.0)
    featured = common.add_machine_type_features(ranked)
    row = featured.loc[(featured["machine_name"] == "B") & (featured["date"] == pd.Timestamp("2026-01-02"))].iloc[0]
    assert row["days_since_first_seen"] == 1.0
    assert row["count_delta_1d"] == 2.0
    assert row["count_increase_flag"] == 1
    assert row["days_since_last_count_increase"] >= 0.0


def test_feature_columns_include_operational_history_fields() -> None:
    df = common.prepare_machine_type_base_frame(_sample_daily_machine_type_summary())
    ranked = common.add_shrunk_rank_targets(df, alpha=5.0)
    featured = common.add_machine_type_features(ranked)
    required = {
        "lag_1_avg_diff_coins",
        "rolling_avg_diff_7d",
        "prior_top3_rate",
        "days_since_last_top3",
        "same_weekday_rank1_rate",
        "days_since_first_seen",
        "days_since_last_count_increase",
        "days_since_last_count_decrease",
        "count_delta_7d",
        "is_thursday",
    }
    assert required <= set(featured.columns)


def test_build_audit_report_summarizes_duplicates_and_missing_values() -> None:
    df = _sample_daily_machine_type_summary()
    df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    df.loc[0, "machine_count"] = None
    prepared = common.prepare_machine_type_base_frame(df)
    report = common.build_audit_report(df, prepared_df=prepared)
    assert report["row_count"] == 7
    assert report["duplicate_date_machine_name_rows"] == 1
    assert report["missing_machine_count_rows"] == 1

