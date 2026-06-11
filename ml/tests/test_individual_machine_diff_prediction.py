from __future__ import annotations

from pathlib import Path

import pandas as pd

from ml.prediction.individual_machine_diff_prediction import (
    build_feature_columns,
    build_walk_forward_folds,
    evaluate_prediction_frame,
    FoldResult,
    load_corner_prediction_frame,
    merge_corner_predictions,
    run_pipeline,
)


def test_build_feature_columns_appends_corner_probability_last() -> None:
    baseline = build_feature_columns()
    with_corner = build_feature_columns(include_corner=True)

    assert len(baseline) == 36
    assert len(with_corner) == 37
    assert with_corner[:-1] == baseline
    assert with_corner[-1] == "pred_corner_top_prob"


def test_merge_corner_predictions_aggregates_corner_rows_per_section_day() -> None:
    machine_frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-04", "2026-06-04"]),
            "section": ["501-522", "501-522"],
            "machine_number": [501, 502],
            "target_diff_positive": [1, 0],
        }
    )
    corner_frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-04", "2026-06-04", "2026-06-04"]),
            "section": ["501-522", "501-522", "523-539"],
            "machine_number": [501, 502, 523],
            "is_corner": [1, 0, 1],
            "pred_corner_top_prob": [0.8, 0.2, 0.6],
        }
    )

    merged = merge_corner_predictions(machine_frame, corner_frame)

    assert merged["pred_corner_top_prob"].tolist() == [0.8, 0.8]


def test_merge_corner_predictions_uses_neutral_value_when_missing() -> None:
    machine_frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-04"]),
            "section": ["501-522"],
            "machine_number": [501],
            "target_diff_positive": [1],
        }
    )
    corner_frame = pd.DataFrame(
        columns=["date", "section", "machine_number", "is_corner", "pred_corner_top_prob"]
    )

    merged = merge_corner_predictions(machine_frame, corner_frame)

    assert merged.loc[0, "pred_corner_top_prob"] == 0.5


def test_load_corner_prediction_frame_normalizes_and_keeps_required_columns(tmp_path: Path) -> None:
    csv_path = tmp_path / "corner_rank_prediction_by_section_validation.csv"
    csv_path.write_text(
        "date,machine_number,section,is_corner,pred_corner_top_prob\n"
        "20260604,501,501-522,1,0.75\n",
        encoding="utf-8",
    )

    loaded = load_corner_prediction_frame(tmp_path)

    assert list(loaded.columns) == ["date", "machine_number", "section", "is_corner", "pred_corner_top_prob"]
    assert loaded.loc[0, "date"] == pd.Timestamp("2026-06-04")
    assert loaded.loc[0, "machine_number"] == 501
    assert loaded.loc[0, "pred_corner_top_prob"] == 0.75


def test_evaluate_prediction_frame_returns_classification_metrics() -> None:
    frame = pd.DataFrame(
        {
            "target_diff_positive": [1, 1, 0, 0],
            "pred_baseline_prob": [0.9, 0.8, 0.2, 0.1],
            "pred_with_corner_prob": [0.9, 0.8, 0.2, 0.1],
        }
    )

    metrics = evaluate_prediction_frame(frame, prob_column="pred_with_corner_prob")

    assert metrics["auc"] == 1.0
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert metrics["f1"] == 1.0


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


def test_run_pipeline_uses_shared_folds_and_emits_dual_model_outputs(monkeypatch, tmp_path: Path) -> None:
    from ml.prediction import individual_machine_diff_prediction as mod

    base_frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-04", "2026-06-04", "2026-06-05", "2026-06-05"]),
            "machine_number": [501, 502, 501, 502],
            "machine_name": ["A", "B", "A", "B"],
            "section": ["501-522", "501-522", "501-522", "501-522"],
            "last_digit": ["1", "2", "1", "2"],
            "target_diff_positive": [1, 0, 0, 1],
            "is_xday": [1, 1, 1, 1],
            "pred_corner_top_prob": [0.8, 0.8, 0.6, 0.6],
            "dd": [4, 4, 5, 5],
            "weekday_num": [3, 3, 4, 4],
            "month": [6, 6, 6, 6],
            "week_of_year": [23, 23, 23, 23],
            "is_sunday": [0, 0, 0, 0],
            "is_weekend": [0, 0, 0, 0],
            "is_dd7": [0, 0, 0, 0],
            "dd_mod5": [4, 4, 0, 0],
            "dd_mod10": [4, 4, 5, 5],
            "last_digit_num": [1, 2, 1, 2],
            "x": [1, 2, 1, 2],
            "y": [1, 1, 1, 1],
            "rank_from_min": [1, 2, 1, 2],
            "rank_from_max": [2, 1, 2, 1],
            "rank_from_aisle": [1, 2, 1, 2],
            "is_corner": [1, 0, 1, 0],
            "is_far_corner": [0, 1, 0, 1],
            "is_near_corner": [1, 1, 1, 1],
            "is_reversed_section": [0, 0, 0, 0],
            "position_ratio": [0.5, 0.5, 0.5, 0.5],
            "is_new_manager": [0, 0, 0, 0],
            "jug_flag": [1, 1, 1, 1],
            "hana_flag": [0, 0, 0, 0],
            "oki_flag": [0, 0, 0, 0],
            "bt_flag": [0, 0, 0, 0],
            "machine_roll7_diff": [0.1, 0.2, 0.3, 0.4],
            "machine_roll30_diff": [0.1, 0.2, 0.3, 0.4],
            "seat_roll7_diff": [0.1, 0.2, 0.3, 0.4],
            "seat_roll30_diff": [0.1, 0.2, 0.3, 0.4],
            "model_weekday_roll": [0.1, 0.2, 0.3, 0.4],
            "seat_dd_roll": [0.1, 0.2, 0.3, 0.4],
            "machine_avg_diff_wf": [0.1, 0.2, 0.3, 0.4],
            "machine_plus_rate_wf": [0.1, 0.2, 0.3, 0.4],
            "machine_sample_n_wf": [1, 2, 3, 4],
            "machine_xday_avg_wf": [0.1, 0.2, 0.3, 0.4],
            "games_normalized": [120, 130, 140, 150],
        }
    )

    corner_frame = base_frame[["date", "machine_number", "section", "pred_corner_top_prob", "is_corner"]].copy()
    fold_calls: list[int] = []

    monkeypatch.setattr(mod, "load_raw_machine_rows", lambda *args, **kwargs: base_frame.copy())
    monkeypatch.setattr(mod, "build_machine_feature_frame", lambda frame: frame.copy())
    monkeypatch.setattr(mod, "load_corner_prediction_frame", lambda *args, **kwargs: corner_frame.copy())
    monkeypatch.setattr(mod, "merge_corner_predictions", lambda machine_frame, corner_frame: machine_frame.copy())
    monkeypatch.setattr(
        mod,
        "build_walk_forward_folds",
        lambda dates, train_days, val_days, step_days: [
            mod.WalkForwardFold(fold_id=1, train_dates=(pd.Timestamp("2026-06-04"),), val_dates=(pd.Timestamp("2026-06-05"),)),
            mod.WalkForwardFold(fold_id=2, train_dates=(pd.Timestamp("2026-06-05"),), val_dates=(pd.Timestamp("2026-06-04"),)),
        ],
    )

    def fake_run_fold(train_df, val_df, *, fold_id, task_type, devices):
        fold_calls.append(fold_id)
        predictions = val_df.copy()
        predictions["pred_baseline_prob"] = 0.6
        predictions["pred_with_corner_prob"] = 0.7
        predictions["pred_baseline_flag"] = 1
        predictions["pred_with_corner_flag"] = 1
        predictions["fold_id"] = fold_id
        importance = pd.DataFrame(
            {
                "fold_id": [fold_id, fold_id],
                "feature": ["pred_corner_top_prob", "games_normalized"],
                "importance": [2.0, 1.0],
                "rank": [1, 2],
            }
        )
        return FoldResult(fold_id=fold_id, predictions=predictions, feature_importance=importance)

    monkeypatch.setattr(mod, "_run_fold", fake_run_fold)

    pred_df, metrics_df, importance_df = run_pipeline(
        Path("ignored.db"),
        corner_pred_dir=tmp_path,
        output_dir=tmp_path,
        train_days=1,
        val_days=1,
        step_days=1,
        min_games=100,
        xday_only=True,
        task_type="CPU",
        devices="",
    )

    assert fold_calls == [1, 2]
    assert set(pred_df.columns) == {
        "date",
        "machine_number",
        "section",
        "last_digit",
        "target_diff_positive",
        "pred_baseline_prob",
        "pred_with_corner_prob",
        "pred_corner_top_prob",
        "fold_id",
    }
    assert list(metrics_df["model_type"]) == ["baseline", "with_corner", "improvement"]
    assert not importance_df.empty
    assert importance_df.iloc[0]["feature"] == "pred_corner_top_prob"
