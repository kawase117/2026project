from __future__ import annotations

import pandas as pd

from ml.prediction.tail_rank_prediction_by_section import (
    add_tail_prediction_features,
    assign_tail_rank_targets,
    build_walk_forward_folds,
    evaluate_prediction_frame,
    build_parser,
)


def test_assign_tail_rank_targets_ranks_digits_within_section_day() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2026-06-04"] * 4,
            "section": ["501-522"] * 4,
            "last_digit": ["0", "1", "2", "3"],
            "diff_coins_normalized": [100.0, 50.0, 75.0, 25.0],
            "machine_number": [501, 502, 503, 504],
            "machine_name": ["A", "B", "C", "D"],
            "games_normalized": [120, 120, 120, 120],
            "machine_type": ["jug", "jug", "jug", "jug"],
        }
    )

    out = assign_tail_rank_targets(raw)

    target = out.sort_values("target_tail_rank_by_section").reset_index(drop=True)
    assert list(target["last_digit"]) == ["0", "2", "1", "3"]
    assert list(target["target_tail_rank_by_section"]) == [1, 2, 3, 4]
    assert list(target["target_tail_score_by_section"]) == [1.0, 0.85, 0.7, 0.55]


def test_add_tail_prediction_features_uses_previous_xday_history_only() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2026-06-04", "2026-06-05", "2026-06-07"],
            "section": ["501-522"] * 3,
            "last_digit": ["2"] * 3,
            "diff_coins_normalized": [10.0, 20.0, 30.0],
            "machine_number": [501, 501, 501],
            "machine_name": ["A", "A", "A"],
            "games_normalized": [120, 120, 120],
            "machine_type": ["jug", "jug", "jug"],
        }
    )

    out = add_tail_prediction_features(assign_tail_rank_targets(raw))
    out = out.sort_values("date").reset_index(drop=True)

    assert pd.isna(out.loc[0, "prev_xday_section_digit_rank"])
    assert out.loc[1, "prev_xday_section_digit_rank"] == 1
    assert out.loc[2, "prev_xday_section_digit_rank"] == 1
    assert out.loc[2, "section_digit_rolling7_mean"] == 15.0
    assert out.loc[2, "section_digit_trend"] == 0.0


def test_build_walk_forward_folds_respects_train_and_val_days() -> None:
    dates = pd.date_range("2026-01-01", periods=8, freq="D")

    folds = build_walk_forward_folds(dates, train_days=3, val_days=2, step_days=2)

    assert len(folds) == 3
    assert folds[0].train_dates == tuple(dates[:3])
    assert folds[0].val_dates == tuple(dates[3:5])
    assert folds[1].train_dates == tuple(dates[2:5])
    assert folds[1].val_dates == tuple(dates[5:7])
    assert folds[2].train_dates == tuple(dates[4:7])
    assert folds[2].val_dates == tuple(dates[7:8])


def test_evaluate_prediction_frame_returns_perfect_scores_for_perfect_ranking() -> None:
    frame = pd.DataFrame(
        {
            "date": ["2026-06-04"] * 4,
            "section": ["501-522"] * 4,
            "last_digit": ["0", "1", "2", "3"],
            "target_tail_rank_by_section": [1, 2, 3, 4],
            "target_tail_score_by_section": [1.0, 0.85, 0.7, 0.55],
            "pred_tail_score": [0.9, 0.8, 0.7, 0.6],
            "pred_tail_rank": [1, 2, 3, 4],
        }
    )

    summary = evaluate_prediction_frame(frame)

    assert summary["spearman"] == 1.0
    assert summary["rank_accuracy"] == 1.0
    assert summary["precision_at_3"] == 1.0
    assert summary["mae_rank"] == 0.0


def test_parser_exposes_section_walkforward_defaults() -> None:
    parser = build_parser()
    args = parser.parse_args([])

    assert args.train_days == 72
    assert args.val_days == 30
    assert args.step_days == 30
    assert args.xday_only is True
    assert args.output_dir == "data/tail_rank_prediction_by_section"
