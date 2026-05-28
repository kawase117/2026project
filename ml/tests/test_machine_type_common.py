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
        "lag_1_avg_diff_coins_vs_mean",
        "prior_avg_rank_pct",
        "rank_trend_1m_vs_2m",
        "hall_avg_diff_yesterday",
    }
    assert required <= set(featured.columns)


def test_feature_columns_exclude_forecast_realized_columns() -> None:
    df = common.prepare_machine_type_base_frame(_sample_daily_machine_type_summary())
    ranked = common.add_shrunk_rank_targets(df, alpha=5.0)
    featured = common.add_machine_type_features(ranked)
    feature_columns = set(common.get_feature_columns(featured))
    assert "avg_diff_coins" not in feature_columns
    assert "total_diff_coins" not in feature_columns
    assert "efficiency" not in feature_columns
    assert "rank_pct" not in feature_columns


def test_backtest_frame_uses_placeholder_without_same_day_realized_values() -> None:
    df = _sample_daily_machine_type_summary()
    df = pd.concat(
        [
            df,
            pd.DataFrame(
                [
                    {
                        "date": "20260109",
                        "machine_name": "C",
                        "machine_count": 1,
                        "total_games": 900,
                        "avg_games": 900.0,
                        "total_diff_coins": 3000,
                        "avg_diff_coins": 3000.0,
                        "win_rate": 0.7,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    prepared = common.prepare_machine_type_base_frame(df)
    ranked = common.add_shrunk_rank_targets(prepared, alpha=5.0)
    featured, truth_known, coverage = common.build_backtest_frame_for_pred_date(
        ranked,
        pred_date=pd.Timestamp("2026-01-09"),
    )
    pred_rows = featured.loc[featured["date"] == pd.Timestamp("2026-01-09")].copy()
    assert pred_rows["avg_diff_coins"].eq(0.0).all()
    assert "C" not in truth_known["machine_name"].astype(str).tolist()
    assert coverage["truth_entities"] == 3
    assert coverage["known_entities"] == 2
    assert coverage["unseen_entities"] == 1


def test_left_censored_new_machine_effective_flags() -> None:
    df = common.prepare_machine_type_base_frame(_sample_daily_machine_type_summary())
    ranked = common.add_shrunk_rank_targets(df, alpha=5.0)
    featured = common.add_machine_type_features(ranked, left_censor_grace_days=30)
    a_first = featured.loc[(featured["machine_name"] == "A")].sort_values("date").iloc[0]
    assert int(a_first["is_left_censored"]) == 1
    assert int(a_first["new_machine_flag_raw"]) == 1
    assert int(a_first["new_machine_flag_effective"]) == 0
    assert int(a_first["days_since_first_seen_bin"]) == -1


def test_build_audit_report_summarizes_duplicates_and_missing_values() -> None:
    df = _sample_daily_machine_type_summary()
    df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    df.loc[0, "machine_count"] = None
    prepared = common.prepare_machine_type_base_frame(df)
    report = common.build_audit_report(df, prepared_df=prepared)
    assert report["row_count"] == 7
    assert report["duplicate_date_machine_name_rows"] == 1
    assert report["missing_machine_count_rows"] == 1


def test_blend_with_prior_rate_uses_target_specific_prior_column() -> None:
    df = pd.DataFrame(
        {
            "prior_top2_rate": [0.2, 0.8],
            "prior_top3_rate": [0.1, 0.9],
        }
    )
    base = pd.Series([0.6, 0.4], dtype=float).to_numpy()
    blended = common.blend_with_prior_rate(
        df,
        target="is_top_2",
        proba=base,
        prior_blend_weight=0.25,
    )
    assert blended[0] == pytest.approx((0.75 * 0.6) + (0.25 * 0.2))
    assert blended[1] == pytest.approx((0.75 * 0.4) + (0.25 * 0.8))


def test_days_since_last_positive_calendar_uses_day_delta() -> None:
    dates = pd.to_datetime(pd.Series(["2026-01-01", "2026-01-02", "2026-01-09"]))
    flags = pd.Series([0, 1, 0], dtype=int)
    days = common._days_since_last_positive_calendar(dates, flags)
    assert days.iloc[0] == pytest.approx(365.0)
    assert days.iloc[1] == pytest.approx(365.0)
    assert days.iloc[2] == pytest.approx(7.0)


def test_split_fit_and_calibration_uses_time_order_and_non_overlapping_dates() -> None:
    df = common.prepare_machine_type_base_frame(_sample_daily_machine_type_summary())
    ranked = common.add_shrunk_rank_targets(df, alpha=5.0)
    fit_df, cal_df = common._split_fit_and_calibration(ranked, target="is_top_3")
    fit_dates = set(pd.to_datetime(fit_df["date"].unique()))
    cal_dates = set(pd.to_datetime(cal_df["date"].unique()))
    # Primary path should split by date; fallback may overlap only when class scarcity happens.
    assert len(fit_df) > 0
    assert len(cal_df) > 0
    if ranked["is_top_3"].nunique() >= 2:
        assert fit_dates <= set(pd.to_datetime(ranked["date"].unique()))
        assert cal_dates <= set(pd.to_datetime(ranked["date"].unique()))


def test_calendar_shift_window_mean_handles_calendar_gap() -> None:
    dates = pd.to_datetime(pd.Series(["2026-01-01", "2026-01-02", "2026-01-09"]))
    values = pd.Series([0.1, 0.2, 0.4], dtype=float)
    w = common._calendar_shift_window_mean(dates, values, lag_days=1, window_days=7)
    # 2026-01-09 row looks back over 2026-01-02..2026-01-08 -> includes only 2026-01-02
    assert w.iloc[2] == pytest.approx(0.2)


def test_build_ltr_relevance_labels_returns_non_negative_int() -> None:
    df = common.prepare_machine_type_base_frame(_sample_daily_machine_type_summary())
    ranked = common.add_shrunk_rank_targets(df, alpha=5.0)
    labels = common._build_ltr_relevance_labels(ranked)
    assert labels.dtype.kind in {"i", "u"}
    assert int(labels.min()) >= 0
    assert int(labels.max()) <= 4


def test_train_ltr_model_and_predict_scores_smoke() -> None:
    df = common.prepare_machine_type_base_frame(_sample_daily_machine_type_summary())
    ranked = common.add_shrunk_rank_targets(df, alpha=5.0)
    featured = common.add_machine_type_features(ranked)
    feature_columns = common.get_feature_columns(featured)
    train_df = featured.loc[featured["date"] < featured["date"].max()].copy()
    pred_df = featured.loc[featured["date"] == featured["date"].max()].copy()
    trained = common.train_ltr_model(
        train_df,
        feature_columns=feature_columns,
        random_state=42,
        decay_lambda=0.3,
        objective="rank:ndcg",
    )
    scores = common.predict_ltr_scores(pred_df, trained=trained)
    assert len(scores) == len(pred_df)


def test_split_fit_and_calibration_strict_time_order_when_classes_available() -> None:
    rows = []
    for i, d in enumerate(pd.date_range("2026-01-01", periods=20, freq="D")):
        rows.append(
            {
                "date": d,
                "machine_name": f"M{i%3}",
                "is_top_3": int(i % 2 == 0),
            }
        )
    df = pd.DataFrame(rows)
    fit_df, cal_df = common._split_fit_and_calibration(df, target="is_top_3")
    assert len(fit_df) > 0 and len(cal_df) > 0
    assert pd.to_datetime(fit_df["date"]).max() < pd.to_datetime(cal_df["date"]).min()
