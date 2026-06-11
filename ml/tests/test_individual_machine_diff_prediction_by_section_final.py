from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from ml.prediction import individual_machine_diff_prediction_by_section_final as mod


def test_build_parser_defaults_match_final_section_flow() -> None:
    parser = mod.build_parser()
    args = parser.parse_args([])

    assert args.output_dir == "data/individual_machine_diff_prediction_by_section_final"
    assert args.xday_only is True
    assert args.task_type == "GPU"


def test_run_pipeline_emits_baseline_only_outputs(monkeypatch, tmp_path: Path) -> None:
    dataset = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-04", "2026-06-05", "2026-06-04", "2026-06-05"]),
            "machine_number": [501, 502, 601, 602],
            "machine_name": ["A", "B", "C", "D"],
            "section": ["501-522", "501-522", "601-616", "601-616"],
            "last_digit": ["1", "2", "3", "4"],
            "target_diff_positive": [1, 0, 0, 1],
            "is_xday": [1, 1, 1, 1],
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
        predictions["pred_diff_positive"] = 0.55
        predictions["fold_id"] = fold_id
        predictions["section_model_id"] = f"{section}_fold{fold_id}"
        return mod.SectionFoldResult(section=section, fold_id=fold_id, predictions=predictions)

    monkeypatch.setattr(mod, "_run_section_fold", fake_run_section_fold)

    pred_df, metrics_df = mod.run_pipeline(
        Path("ignored.db"),
        output_dir=tmp_path,
        train_days=1,
        val_days=1,
        step_days=1,
        min_games=100,
        xday_only=True,
        task_type="CPU",
        devices="",
    )

    assert list(pred_df.columns) == [
        "date",
        "machine_number",
        "section",
        "last_digit",
        "target_diff_positive",
        "pred_diff_positive",
        "fold_id",
    ]
    assert "pred_corner_top_prob" not in pred_df.columns
    assert set(metrics_df.columns) == {"section", "auc", "precision", "recall", "f1", "n_machines", "n_rows", "n_dates", "notes"}
