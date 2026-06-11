from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import pandas as pd

from ml.prediction import individual_machine_diff_prediction_by_section as mod


def test_build_parser_defaults_match_expected_section_flow() -> None:
    parser = mod.build_parser()
    args = parser.parse_args([])

    assert args.db_path == "db/みとや大森町店.db"
    assert args.db_glob == "*みとや大森町店*.db"
    assert args.corner_pred_dir == "data/corner_rank_prediction_by_section"
    assert args.output_dir == "data/individual_machine_diff_prediction_by_section"
    assert args.xday_only is True


def test_load_corner_prediction_frame_for_section_uses_xday_rolling30_mean(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_load_corner_prediction_frame(corner_pred_dir, *, scenario=None):
        captured["corner_pred_dir"] = corner_pred_dir
        captured["scenario"] = scenario
        return pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-04"]),
                "machine_number": [501],
                "section": ["501-522"],
                "is_corner": [1],
                "pred_corner_top_prob": [0.75],
            }
        )

    monkeypatch.setattr(mod, "load_corner_prediction_frame", fake_load_corner_prediction_frame)

    frame = mod._load_corner_prediction_frame_for_section(tmp_path)

    assert captured["scenario"] == mod.CORNER_SCENARIO
    assert list(frame.columns) == ["date", "machine_number", "section", "is_corner", "pred_corner_top_prob"]
    assert frame.loc[0, "pred_corner_top_prob"] == 0.75


def test_load_corner_prediction_frame_prefers_window_ablation_sibling_dir(tmp_path: Path) -> None:
    corner_dir = tmp_path / "corner_rank_prediction_by_section"
    window_dir = tmp_path / "corner_rank_prediction_by_section_window_ablation"
    corner_dir.mkdir()
    window_dir.mkdir()

    (corner_dir / "corner_rank_prediction_by_section_validation.csv").write_text(
        "date,machine_number,section,is_corner,pred_corner_top_prob\n"
        "20260604,501,501-522,1,0.10\n",
        encoding="utf-8",
    )
    (window_dir / "corner_rank_prediction_by_section_window_ablation_validation.csv").write_text(
        "scenario,date,machine_number,section,is_corner,pred_corner_top_prob\n"
        "xday_rolling30_mean,20260604,501,501-522,1,0.90\n",
        encoding="utf-8",
    )

    loaded = mod.load_corner_prediction_frame(corner_dir, scenario=mod.CORNER_SCENARIO)

    assert loaded.loc[0, "pred_corner_top_prob"] == 0.90


def test_summarize_section_metrics_returns_baseline_and_with_corner_rows() -> None:
    predictions = pd.DataFrame(
        {
            "section": ["501-522", "501-522", "501-522", "501-522"],
            "machine_number": [501, 502, 503, 504],
            "date": pd.to_datetime(["2026-06-04", "2026-06-04", "2026-06-05", "2026-06-05"]),
            "target_diff_positive": [1, 0, 1, 0],
            "pred_baseline": [0.9, 0.2, 0.8, 0.1],
            "pred_with_corner": [0.95, 0.15, 0.85, 0.05],
        }
    )

    metrics = mod.summarize_section_metrics(predictions)

    assert list(metrics["model_type"]) == ["baseline", "with_corner"]
    assert metrics.loc[1, "delta_auc"] >= 0
    assert metrics.loc[0, "n_machines"] == 4
    assert metrics.loc[0, "n_rows"] == 4


def test_summarize_feature_importance_ranks_within_each_model_type() -> None:
    feature_importance = pd.DataFrame(
        {
            "section": ["501-522", "501-522", "501-522", "501-522"],
            "model_type": ["with_corner", "with_corner", "baseline", "baseline"],
            "fold_id": [0, 0, 0, 0],
            "feature": ["pred_corner_top_prob", "games_normalized", "games_normalized", "x"],
            "importance": [2.0, 1.0, 1.5, 0.5],
            "rank": [1, 2, 1, 2],
        }
    )

    summary = mod.summarize_feature_importance(feature_importance)
    with_corner = summary[summary["model_type"] == "with_corner"]

    assert list(with_corner["feature_name"]) == ["pred_corner_top_prob", "games_normalized"]
    assert list(with_corner["rank"]) == [1, 2]


def test_run_pipeline_emits_section_level_outputs(monkeypatch, tmp_path: Path) -> None:
    dataset = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-04", "2026-06-05", "2026-06-04", "2026-06-05"]),
            "machine_number": [501, 502, 601, 602],
            "machine_name": ["A", "B", "C", "D"],
            "section": ["501-522", "501-522", "601-616", "601-616"],
            "last_digit": ["1", "2", "3", "4"],
            "target_diff_positive": [1, 0, 0, 1],
            "is_xday": [1, 1, 1, 1],
            "pred_corner_top_prob": [0.8, 0.8, 0.6, 0.6],
            "machine_type": ["jug", "jug", "hana", "hana"],
        }
    )

    fold = SimpleNamespace(
        fold_id=0,
        train_dates=(pd.Timestamp("2026-06-04"),),
        val_dates=(pd.Timestamp("2026-06-05"),),
    )

    monkeypatch.setattr(mod, "_build_section_dataset", lambda *args, **kwargs: dataset.copy())
    monkeypatch.setattr(mod, "build_walk_forward_folds", lambda dates, train_days, val_days, step_days: [fold])

    def fake_run_section_fold(train_df, val_df, *, section, fold_id, task_type, devices):
        predictions = val_df.copy()
        predictions["pred_baseline"] = 0.55
        predictions["pred_with_corner"] = 0.65
        predictions["fold_id"] = fold_id
        predictions["section_model_id"] = f"{section}_fold{fold_id}"
        feature_importance = pd.DataFrame(
            {
                "section": [section, section],
                "model_type": ["with_corner", "with_corner"],
                "fold_id": [fold_id, fold_id],
                "feature": ["pred_corner_top_prob", "games_normalized"],
                "importance": [2.0, 1.0],
                "rank": [1, 2],
            }
        )
        return mod.SectionFoldResult(section=section, fold_id=fold_id, predictions=predictions, feature_importance=feature_importance)

    monkeypatch.setattr(mod, "_run_section_fold", fake_run_section_fold)

    pred_df, metrics_df, importance_df = mod.run_pipeline(
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

    assert not pred_df.empty
    assert list(pred_df.columns) == [
        "date",
        "machine_number",
        "section",
        "last_digit",
        "target_diff_positive",
        "pred_baseline",
        "pred_with_corner",
        "pred_corner_top_prob",
        "fold_id",
        "section_model_id",
    ]
    assert set(metrics_df["model_type"]) == {"baseline", "with_corner"}
    assert not importance_df.empty
