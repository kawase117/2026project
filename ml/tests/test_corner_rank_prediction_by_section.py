from __future__ import annotations

import pandas as pd

from ml.prediction.corner_rank_prediction_by_section import (
    add_corner_prediction_features,
    assign_corner_top_targets,
    build_feature_columns,
    build_parser,
    build_walk_forward_folds,
    build_window_ablation_feature_columns,
    evaluate_prediction_frame,
    summarize_ablation_metrics,
    summarize_window_ablation_results,
)


def test_assign_corner_top_targets_marks_top_30_percent_as_positive() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2026-06-04"] * 10,
            "section": ["501-522"] * 10,
            "machine_number": list(range(501, 511)),
            "machine_name": [f"M{i}" for i in range(10)],
            "last_digit": ["0"] * 10,
            "games_normalized": [120] * 10,
            "diff_coins_normalized": [5000, 3000, 1500, 500, -200, -800, -1200, -1500, -2000, -2500],
            "rank_from_aisle": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            "is_corner": [1] + [0] * 9,
            "machine_type": ["jug"] * 10,
        }
    )

    out = assign_corner_top_targets(raw)
    corner_row = out.loc[out["is_corner"].eq(1)].iloc[0]

    assert corner_row["target_corner_top_flag"] == 1
    assert int(out["target_corner_top_flag"].sum()) == 3


def test_add_corner_prediction_features_uses_shifted_history() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2026-06-04", "2026-06-05", "2026-06-07"],
            "section": ["501-522"] * 3,
            "machine_number": [501, 501, 501],
            "machine_name": ["M0", "M0", "M0"],
            "last_digit": ["0"] * 3,
            "games_normalized": [120] * 3,
            "diff_coins_normalized": [10.0, 20.0, 30.0],
            "rank_from_aisle": [1, 1, 1],
            "is_corner": [1, 1, 1],
            "machine_type": ["jug"] * 3,
        }
    )

    out = add_corner_prediction_features(assign_corner_top_targets(raw)).sort_values("date").reset_index(drop=True)

    assert pd.isna(out.loc[0, "corner_rolling7_mean"])
    assert out.loc[1, "corner_rolling7_mean"] == 10.0
    assert out.loc[2, "prev_xday_corner_top_flag"] == 1
    assert pd.isna(out.loc[0, "corner_expanding_all_mean"])
    assert out.loc[1, "corner_expanding_all_mean"] == 10.0


def test_build_walk_forward_folds_respects_window_sizes() -> None:
    dates = pd.date_range("2026-01-01", periods=8, freq="D")

    folds = build_walk_forward_folds(dates, train_days=3, val_days=2, step_days=2)

    assert len(folds) == 3
    assert folds[0].train_dates == tuple(dates[:3])
    assert folds[0].val_dates == tuple(dates[3:5])
    assert folds[1].train_dates == tuple(dates[2:5])
    assert folds[1].val_dates == tuple(dates[5:7])
    assert folds[2].train_dates == tuple(dates[4:7])
    assert folds[2].val_dates == tuple(dates[7:8])


def test_evaluate_prediction_frame_returns_classification_metrics() -> None:
    frame = pd.DataFrame(
        {
            "date": ["2026-06-04"] * 4,
            "section": ["501-522"] * 4,
            "target_corner_top_flag": [1, 1, 1, 0],
            "pred_corner_top_prob": [0.9, 0.8, 0.7, 0.1],
        }
    )

    out = evaluate_prediction_frame(frame)

    assert out["auc"] == 1.0
    assert out["precision"] == 1.0
    assert out["recall"] == 1.0
    assert out["f1"] == 1.0


def test_parser_exposes_corner_defaults() -> None:
    parser = build_parser()
    args = parser.parse_args([])

    assert args.train_days == 72
    assert args.val_days == 30
    assert args.step_days == 30
    assert args.xday_only is False
    assert args.feature_scenario == "all_days"
    assert args.ablation is False
    assert args.window_ablation is False
    assert args.output_dir == "data/corner_rank_prediction_by_section"


def test_build_feature_columns_switches_between_ablation_modes() -> None:
    all_days = build_feature_columns("all_days")
    xday_only = build_feature_columns("xday_only")
    hybrid = build_feature_columns("hybrid")

    assert "corner_rolling7_all_mean" in all_days
    assert "corner_rolling30_all_mean" in all_days
    assert "corner_rolling7_xday_mean" not in all_days

    assert "corner_rolling7_xday_mean" in xday_only
    assert "corner_rolling7_all_mean" not in xday_only

    assert "corner_rolling7_all_mean" in hybrid
    assert "corner_rolling7_xday_mean" in hybrid
    assert len(hybrid) > len(all_days)


def test_build_window_ablation_feature_columns_switches_between_windows() -> None:
    rolling7 = build_window_ablation_feature_columns("xday_7mean")
    rolling30 = build_window_ablation_feature_columns("xday_rolling30_mean")
    rolling90 = build_window_ablation_feature_columns("xday_90mean")
    expanding_xday = build_window_ablation_feature_columns("xday_expanding_mean")
    expanding_all = build_window_ablation_feature_columns("all_days_expanding_mean")

    assert "xday_roll7_mean" in rolling7
    assert "xday_expanding_mean" not in rolling7

    assert "xday_roll30_mean" in rolling30
    assert "xday_roll7_mean" not in rolling30

    assert "xday_roll90_mean" in rolling90
    assert "xday_roll30_mean" not in rolling90

    assert "xday_expanding_mean" in expanding_xday
    assert "all_days_expanding_mean" not in expanding_xday

    assert "all_days_expanding_mean" in expanding_all
    assert "xday_expanding_mean" not in expanding_all


def test_summarize_window_ablation_results_returns_requested_shapes() -> None:
    predictions = {
        "xday_7mean": pd.DataFrame(
            {
                "date": ["2026-06-04", "2026-06-05"] * 2,
                "fold_id": [1, 1, 2, 2],
                "section": ["501-522"] * 4,
                "target_corner_top_flag": [1, 0, 1, 0],
                "pred_corner_top_prob": [0.9, 0.1, 0.8, 0.2],
                "pred_corner_top_flag": [1, 0, 1, 0],
            }
        ),
        "xday_rolling30_mean": pd.DataFrame(
            {
                "date": ["2026-06-04", "2026-06-05"] * 2,
                "fold_id": [1, 1, 2, 2],
                "section": ["501-522"] * 4,
                "target_corner_top_flag": [1, 0, 1, 0],
                "pred_corner_top_prob": [0.88, 0.12, 0.78, 0.22],
                "pred_corner_top_flag": [1, 0, 1, 0],
            }
        ),
        "xday_90mean": pd.DataFrame(
            {
                "date": ["2026-06-04", "2026-06-05"] * 2,
                "fold_id": [1, 1, 2, 2],
                "section": ["501-522"] * 4,
                "target_corner_top_flag": [1, 0, 1, 0],
                "pred_corner_top_prob": [0.82, 0.18, 0.72, 0.28],
                "pred_corner_top_flag": [1, 0, 1, 0],
            }
        ),
        "xday_expanding_mean": pd.DataFrame(
            {
                "date": ["2026-06-04", "2026-06-05"] * 2,
                "fold_id": [1, 1, 2, 2],
                "section": ["501-522"] * 4,
                "target_corner_top_flag": [1, 0, 1, 0],
                "pred_corner_top_prob": [0.85, 0.15, 0.75, 0.25],
                "pred_corner_top_flag": [1, 0, 1, 0],
            }
        ),
        "all_days_expanding_mean": pd.DataFrame(
            {
                "date": ["2026-06-04", "2026-06-05"] * 2,
                "fold_id": [1, 1, 2, 2],
                "section": ["501-522"] * 4,
                "target_corner_top_flag": [1, 0, 1, 0],
                "pred_corner_top_prob": [0.78, 0.22, 0.68, 0.32],
                "pred_corner_top_flag": [1, 0, 1, 0],
            }
        ),
    }

    metrics, pairwise = summarize_window_ablation_results(predictions)

    assert list(metrics["scenario"]) == [
        "xday_7mean",
        "xday_rolling30_mean",
        "xday_90mean",
        "xday_expanding_mean",
        "all_days_expanding_mean",
    ]
    assert set(metrics.columns) == {
        "scenario",
        "AUC",
        "Precision",
        "Recall",
        "F1",
        "mean_delta_vs_baseline",
        "p_value",
        "fold_auc_std",
        "n_folds",
        "n_validation_rows",
        "n_validation_dates",
        "n_sections",
        "positive_rate",
        "notes",
    }
    assert pd.isna(metrics.loc[metrics["scenario"].eq("xday_7mean"), "p_value"]).all()
    assert set(pairwise.columns) == {"scenario_a", "scenario_b", "mean_delta_b_minus_a", "t_stat", "p_value", "n_folds"}
    assert len(pairwise) == 10


def test_summarize_ablation_metrics_returns_wide_comparison_table() -> None:
    predictions = {
        "all_days": pd.DataFrame(
            {
                "date": ["2026-06-04"] * 4,
                "section": ["501-522"] * 4,
                "target_corner_top_flag": [1, 1, 1, 0],
                "pred_corner_top_prob": [0.9, 0.8, 0.7, 0.1],
                "pred_corner_top_flag": [1, 1, 1, 0],
            }
        ),
        "xday_only": pd.DataFrame(
            {
                "date": ["2026-06-04"] * 4,
                "section": ["501-522"] * 4,
                "target_corner_top_flag": [1, 0, 0, 0],
                "pred_corner_top_prob": [0.9, 0.8, 0.7, 0.1],
                "pred_corner_top_flag": [1, 1, 1, 0],
            }
        ),
        "hybrid": pd.DataFrame(
            {
                "date": ["2026-06-04"] * 4,
                "section": ["501-522"] * 4,
                "target_corner_top_flag": [1, 1, 0, 0],
                "pred_corner_top_prob": [0.9, 0.8, 0.2, 0.1],
                "pred_corner_top_flag": [1, 1, 0, 0],
            }
        ),
    }

    metrics = summarize_ablation_metrics(predictions)

    assert list(metrics["metric"]) == [
        "auc",
        "precision",
        "recall",
        "f1",
        "n_validation_rows",
        "n_validation_dates",
        "n_sections",
        "positive_rate",
    ]
    assert set(metrics.columns) == {"metric", "all_days", "xday_only", "hybrid"}
