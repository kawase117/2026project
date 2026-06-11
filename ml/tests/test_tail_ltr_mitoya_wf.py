from __future__ import annotations

import pandas as pd

from ml.last_digit.tail_ltr_mitoya_wf import (
    add_bucket_observation_counts,
    add_strong_zorome_observation_counts,
    build_parser,
    classify_mitoya_day_bucket,
    classify_positive_combined_day_bucket,
    parse_position_bucket_overrides,
    should_use_position_features,
    summarize_bucketed_days,
)


def test_classify_mitoya_day_bucket_prioritizes_x_day_over_strong_zorome() -> None:
    assert classify_mitoya_day_bucket(pd.Timestamp("2026-06-14"), is_strong_zorome=False) == "x_day"
    assert classify_mitoya_day_bucket(pd.Timestamp("2026-06-17"), is_strong_zorome=False) == "x_day"
    assert classify_mitoya_day_bucket(pd.Timestamp("2026-04-04"), is_strong_zorome=True) == "x_day"
    assert classify_mitoya_day_bucket(pd.Timestamp("2026-04-04"), is_strong_zorome=False) == "x_day"
    assert classify_mitoya_day_bucket(pd.Timestamp("2026-11-11"), is_strong_zorome=True) == "strong_zorome"
    assert classify_mitoya_day_bucket(pd.Timestamp("2026-11-11"), is_strong_zorome=False) == "strong_zorome"
    assert classify_mitoya_day_bucket(pd.Timestamp("2026-06-02"), is_strong_zorome=False) == "others"


def test_classify_mitoya_day_bucket_marks_month_day_strong_zorome() -> None:
    assert classify_mitoya_day_bucket(pd.Timestamp("2026-02-02")) == "strong_zorome"
    assert classify_mitoya_day_bucket(pd.Timestamp("2026-03-03")) == "strong_zorome"
    assert classify_mitoya_day_bucket(pd.Timestamp("2026-05-05")) == "strong_zorome"


def test_classify_mitoya_day_bucket_marks_dd_30_and_dd_11() -> None:
    assert classify_mitoya_day_bucket(pd.Timestamp("2026-01-30")) == "month_end_30"
    assert classify_mitoya_day_bucket(pd.Timestamp("2026-01-11")) == "dd_11"


def test_classify_positive_combined_day_bucket_includes_special_days() -> None:
    assert classify_positive_combined_day_bucket(pd.Timestamp("2026-01-30")) == "positive_day"
    assert classify_positive_combined_day_bucket(pd.Timestamp("2026-01-11")) == "positive_day"
    assert classify_positive_combined_day_bucket(pd.Timestamp("2026-02-02")) == "positive_day"
    assert classify_positive_combined_day_bucket(pd.Timestamp("2026-02-03")) == "others"


def test_parser_exposes_three_bucket_cli_options() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "--min-train-days-x-day",
            "8",
            "--min-train-days-strong-zorome",
            "10",
            "--min-train-days-month-end-30",
            "11",
            "--min-train-days-dd-11",
            "12",
            "--min-train-days-others",
            "30",
            "--q-grid-strong-zorome-override",
            "0.55",
            "--position-buckets",
            "x_day,others",
        ]
    )

    assert args.min_train_days_x_day == 8
    assert args.min_train_days_strong_zorome == 10
    assert args.min_train_days_month_end_30 == 11
    assert args.min_train_days_dd_11 == 12
    assert args.min_train_days_others == 30
    assert args.q_grid_strong_zorome_override == 0.55
    assert args.position_buckets == "x_day,others"
    assert args.a_weight == 1.0
    assert args.non_a_weight == 1.0
    assert args.non_a_gate_weight == 1.0
    assert args.use_position_features is False
    assert args.output_json == ""


def test_parser_defaults_strong_zorome_min_train_days_to_five() -> None:
    parser = build_parser()
    args = parser.parse_args([])

    assert args.min_train_days_strong_zorome == 5
    assert args.min_train_days_month_end_30 == 5
    assert args.min_train_days_dd_11 == 5
    assert args.position_buckets == ""
    assert args.use_position_features is False


def test_summarize_bucketed_days_returns_expected_sections() -> None:
    df = pd.DataFrame(
        {
            "date": ["2026-06-04", "2026-06-07", "2026-06-08"],
            "weekday": ["Thursday", "Sunday", "Friday"],
            "day_bucket": ["x_day", "x_day", "others"],
            "excess": [100.0, 50.0, -10.0],
            "hit_at_1": [1.0, 0.0, 0.0],
            "hit_at_2": [1.0, 1.0, 0.0],
        }
    )

    out = summarize_bucketed_days(
        df,
        n_boot=10,
        bucket_order=("x_day", "strong_zorome", "month_end_30", "dd_11", "others"),
        summary_key_by_bucket={
            "x_day": "x_day_only",
            "strong_zorome": "strong_zorome_days",
            "month_end_30": "month_end_30_days",
            "dd_11": "dd_11_days",
            "others": "others_days",
        },
    )

    assert set(out) == {"overall", "x_day_only", "strong_zorome_days", "month_end_30_days", "dd_11_days", "others_days"}
    assert out["x_day_only"]["n_days"] == 2
    assert out["strong_zorome_days"]["n_days"] == 0
    assert out["month_end_30_days"]["n_days"] == 0
    assert out["dd_11_days"]["n_days"] == 0
    assert out["others_days"]["n_days"] == 1
    assert out["overall"]["hit_at_1"] == 1.0 / 3.0
    assert out["overall"]["hit_at_2"] == 2.0 / 3.0
    assert out["x_day_only"]["hit_at_2"] == 1.0


def test_add_strong_zorome_observation_counts_attaches_integer_fields() -> None:
    summary = {"strong_zorome_days": {"n_days": 16, "mean": 82.27}}

    out = add_strong_zorome_observation_counts(
        summary,
        total_dates=21,
        holdout_dates=16,
    )

    bucket = out["strong_zorome_days"]
    assert bucket["observed_dates_total"] == 21
    assert bucket["observed_dates_holdout"] == 16
    assert isinstance(bucket["observed_dates_total"], int)
    assert isinstance(bucket["observed_dates_holdout"], int)


def test_add_bucket_observation_counts_attaches_integer_fields() -> None:
    summary = {"month_end_30_days": {"n_days": 3, "mean": 12.5}}

    out = add_bucket_observation_counts(
        summary,
        bucket_key="month_end_30_days",
        total_dates=14,
        holdout_dates=3,
    )

    bucket = out["month_end_30_days"]
    assert bucket["observed_dates_total"] == 14
    assert bucket["observed_dates_holdout"] == 3
    assert isinstance(bucket["observed_dates_total"], int)
    assert isinstance(bucket["observed_dates_holdout"], int)


def test_should_use_position_features() -> None:
    assert should_use_position_features("x_day", True) is True
    assert should_use_position_features("strong_zorome", True) is False
    assert should_use_position_features("x_day", False) is False
    assert should_use_position_features("unknown_bucket", True) is False


def test_should_use_position_features_override() -> None:
    overrides = {"strong_zorome"}
    assert should_use_position_features("strong_zorome", True, overrides) is True
    assert should_use_position_features("month_end_30", True, overrides) is False


def test_parse_position_bucket_overrides_parses_comma_separated_list() -> None:
    assert parse_position_bucket_overrides("x_day,others") == {"x_day", "others"}
    assert parse_position_bucket_overrides("") == set()
