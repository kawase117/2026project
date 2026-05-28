import json
from pathlib import Path

import pandas as pd
import pytest


def test_load_prediction_history_filters_2fn_and_marks_hard_miss(tmp_path: Path) -> None:
    from ml.experiments import signal_accuracy_2fn as analysis

    csv_path = tmp_path / "topk.csv"
    pd.DataFrame(
        [
            {"date": "2026-01-01", "expert": "2F_N", "top1_tail": "8", "hit_at_2": 1.0},
            {"date": "2026-01-02", "expert": "2F_N", "top1_tail": "5", "hit_at_2": 0.0},
            {"date": "2026-01-02", "expert": "3F_N", "top1_tail": "9", "hit_at_2": 0.0},
        ]
    ).to_csv(csv_path, index=False, encoding="utf-8")

    df_pred, pred_map = analysis.load_prediction_history(csv_path, expert="2F_N")

    assert df_pred["date"].tolist() == ["20260101", "20260102"]
    assert pred_map["20260101"]["hard_miss"] is False
    assert pred_map["20260102"]["top1_tail"] == "5"
    assert pred_map["20260102"]["hard_miss"] is True


def test_signal_accuracy_build_daily_rows_marks_match_and_top2() -> None:
    from ml.experiments import signal_accuracy_2fn as analysis

    df_dates = pd.DataFrame(
        [
            {"date": "20260101", "day_of_week": "木"},
            {"date": "20260102", "day_of_week": "金"},
        ]
    )
    df_hokuto = pd.DataFrame(
        [
            {"date": "20260101", "machine_number": 2258, "last_digit": "8", "diff_coins_normalized": 1200, "games_normalized": 4000},
            {"date": "20260101", "machine_number": 2257, "last_digit": "7", "diff_coins_normalized": 900, "games_normalized": 4200},
            {"date": "20260102", "machine_number": 2251, "last_digit": "1", "diff_coins_normalized": 500, "games_normalized": 2500},
        ]
    )
    df_other = pd.DataFrame(
        [
            {"date": "20260101", "last_digit": "8", "diff_coins_normalized": 300},
            {"date": "20260101", "last_digit": "8", "diff_coins_normalized": 250},
            {"date": "20260101", "last_digit": "7", "diff_coins_normalized": 250},
            {"date": "20260102", "last_digit": "9", "diff_coins_normalized": 400},
        ]
    )
    pred_map = {
        "20260101": {"top1_tail": "8", "hit_at_2": 1.0, "hard_miss": False},
        "20260102": {"top1_tail": "9", "hit_at_2": 0.0, "hard_miss": True},
    }

    rows = analysis.build_daily_rows(
        df_dates=df_dates,
        df_hokuto=df_hokuto,
        df_other=df_other,
        pred_map=pred_map,
        min_games=3000,
    )

    assert rows[0]["hokuto_best_digit"] == "8"
    assert rows[0]["best_2fn_digit"] == "8"
    assert rows[0]["actual_rank1_digit"] == "8"
    assert rows[0]["is_match"] is True
    assert rows[0]["is_top2_match"] is True
    assert rows[0]["exact_hit"] is True
    assert rows[0]["exact_miss"] is False
    assert rows[1]["hokuto_best_digit"] is None
    assert rows[1]["hard_miss"] is True


def test_signal_accuracy_weekday_summary_includes_exact_hit_rate() -> None:
    from ml.experiments import signal_accuracy_2fn as analysis

    daily_df = pd.DataFrame(
        [
            {"day_of_week": "月", "hokuto_best_digit": "1", "is_match": True, "is_top2_match": True, "has_pred": True, "exact_hit": True},
            {"day_of_week": "月", "hokuto_best_digit": "2", "is_match": False, "is_top2_match": True, "has_pred": True, "exact_hit": False},
            {"day_of_week": "火", "hokuto_best_digit": "3", "is_match": False, "is_top2_match": False, "has_pred": False, "exact_hit": pd.NA},
        ]
    )

    summary = analysis.build_weekday_summary_frame(daily_df, n_digits=10)

    monday = summary.loc[summary["day_of_week"] == "月"].iloc[0]
    assert monday["n_signal_days"] == 2
    assert monday["hit_rate"] == pytest.approx(0.5)
    assert monday["exact_hit_rate_on_pred_days"] == pytest.approx(0.5)
    assert monday["pred_days"] == 2


def test_hokuto_and_monkey_signal_tails_apply_correct_thresholds() -> None:
    from ml.experiments import signal_multi_tail_2fn as analysis

    df_hokuto_day = pd.DataFrame(
        [
            {"last_digit": "7", "diff_coins_normalized": 250, "games_normalized": 3200, "rb_probability_decimal": 0.0010},
            {"last_digit": "1", "diff_coins_normalized": 100, "games_normalized": 3500, "rb_probability_decimal": (1 / 250)},
            {"last_digit": "5", "diff_coins_normalized": 500, "games_normalized": 2900, "rb_probability_decimal": 0.0100},
        ]
    )
    df_monkey_day = pd.DataFrame(
        [
            {"last_digit": "7", "diff_coins_normalized": 100, "games_normalized": 3100, "rb_probability_decimal": (1 / 200)},
            {"last_digit": "7", "diff_coins_normalized": 150, "games_normalized": 3600, "rb_probability_decimal": (1 / 220)},
            {"last_digit": "2", "diff_coins_normalized": 300, "games_normalized": 3100, "rb_probability_decimal": (1 / 500)},
            {"last_digit": "2", "diff_coins_normalized": 50, "games_normalized": 2000, "rb_probability_decimal": (1 / 100)},
        ]
    )

    hokuto = analysis.get_hokuto_signal_tails(
        df_hokuto_day,
        min_games=3000,
        diff_threshold=200.0,
        rb_threshold=(1 / 300),
    )
    monkey = analysis.get_monkey_signal_tails(
        df_monkey_day,
        min_games=3000,
        diff_threshold=200.0,
        rb_threshold=(1 / 300),
    )

    assert hokuto == {"1", "7"}
    assert monkey == {"2", "7"}


def test_multi_tail_daily_rows_capture_union_and_avg_map() -> None:
    from ml.experiments import signal_multi_tail_2fn as analysis

    df_dates = pd.DataFrame([{"date": "20260101", "day_of_week": "木"}])
    df_hokuto = pd.DataFrame(
        [
            {"date": "20260101", "last_digit": "7", "diff_coins_normalized": 250, "games_normalized": 3300, "rb_probability_decimal": 0.0010},
        ]
    )
    df_monkey = pd.DataFrame(
        [
            {"date": "20260101", "last_digit": "2", "diff_coins_normalized": 300, "games_normalized": 3400, "rb_probability_decimal": 0.0010},
            {"date": "20260101", "last_digit": "2", "diff_coins_normalized": 200, "games_normalized": 3500, "rb_probability_decimal": 0.0010},
        ]
    )
    df_other = pd.DataFrame(
        [
            {"date": "20260101", "last_digit": "7", "diff_coins_normalized": 200},
            {"date": "20260101", "last_digit": "2", "diff_coins_normalized": 500},
            {"date": "20260101", "last_digit": "9", "diff_coins_normalized": 100},
        ]
    )

    rows = analysis.build_multi_tail_daily_rows(
        df_dates=df_dates,
        df_hokuto=df_hokuto,
        df_monkey=df_monkey,
        df_other=df_other,
        diff_threshold=200.0,
        rb_threshold=(1 / 300),
        min_games=3000,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["signal_tails"] == "2,7"
    assert row["best_2fn_digit"] == "2"
    assert row["is_match"] is True
    assert row["category"] == "multi"
    avg_map = json.loads(row["signal_tail_2fn_avgs"])
    assert avg_map == {"2": 500.0, "7": 200.0}


def test_quantile_signal_mode_reduces_to_top_tail_per_metric() -> None:
    from ml.experiments import signal_multi_tail_2fn as analysis

    agg = pd.DataFrame(
        [
            {"last_digit": "1", "avg_diff": 100.0, "avg_rb": 0.0010},
            {"last_digit": "2", "avg_diff": 250.0, "avg_rb": 0.0020},
            {"last_digit": "3", "avg_diff": 400.0, "avg_rb": 0.0050},
        ]
    )

    tails = analysis.select_signal_tails(
        agg,
        signal_mode="quantile",
        diff_threshold=200.0,
        rb_threshold=(1 / 300),
        diff_quantile=0.8,
        rb_quantile=0.8,
    )

    assert tails == {"3"}


def test_signal_source_controls_tail_selection() -> None:
    from ml.experiments import signal_multi_tail_2fn as analysis

    agg = pd.DataFrame(
        [
            {"last_digit": "1", "avg_diff": 250.0, "avg_rb": 0.0010},
            {"last_digit": "2", "avg_diff": 100.0, "avg_rb": (1 / 200)},
            {"last_digit": "3", "avg_diff": 300.0, "avg_rb": (1 / 250)},
        ]
    )

    diff_only = analysis.select_signal_tails(
        agg,
        signal_mode="fixed",
        signal_source="diff",
        diff_threshold=200.0,
        rb_threshold=(1 / 300),
        diff_quantile=0.8,
        rb_quantile=0.8,
    )
    rb_only = analysis.select_signal_tails(
        agg,
        signal_mode="fixed",
        signal_source="rb",
        diff_threshold=200.0,
        rb_threshold=(1 / 300),
        diff_quantile=0.8,
        rb_quantile=0.8,
    )
    either = analysis.select_signal_tails(
        agg,
        signal_mode="fixed",
        signal_source="or",
        diff_threshold=200.0,
        rb_threshold=(1 / 300),
        diff_quantile=0.8,
        rb_quantile=0.8,
    )

    assert diff_only == {"1", "3"}
    assert rb_only == {"2", "3"}
    assert either == {"1", "2", "3"}


def test_quantile_sweep_payload_contains_requested_quantiles() -> None:
    from ml.experiments import signal_multi_tail_2fn as analysis

    rows_by_quantile = {
        0.8: [{"category": "multi", "is_match": True, "n_signal_tails": 4}],
        0.9: [{"category": "single", "is_match": False, "n_signal_tails": 1}],
        0.95: [{"category": "no_signal", "is_match": False, "n_signal_tails": 0}],
    }

    payload = analysis.build_sweep_payload(
        rows_by_quantile=rows_by_quantile,
        signal_source="diff",
        sweep_quantiles=[0.8, 0.9, 0.95],
    )

    assert payload["signal_source"] == "diff"
    assert payload["signal_mode"] == "quantile"
    assert payload["sweep_quantiles"] == [0.8, 0.9, 0.95]
    assert payload["results"]["0.80"]["multi_signal_hit_rate"] == pytest.approx(1.0)
    assert payload["results"]["0.90"]["day_counts"]["single"] == 1
    assert payload["results"]["0.95"]["day_counts"]["no_signal"] == 1
