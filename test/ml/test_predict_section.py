from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ml.experiments.walkforward_scoring import predict_section as mod


def _make_bundle() -> mod.PredictionBundle:
    section_summary = pd.DataFrame(
        {
            "section_rank": [1, 2],
            "section": ["501-522", "601-616"],
            "section_score": [0.42, 0.31],
            "section_score_pct": [42.0, 31.0],
            "section_hist_coverage": [1.0, 0.8],
            "section_hist_coverage_pct": [100.0, 80.0],
            "n_machines": [2, 2],
        }
    )
    selected_machines = pd.DataFrame(
        {
            "section": ["501-522", "501-522"],
            "rank_in_section": [1, 2],
            "machine_number": [501, 502],
            "machine_name": ["A", "B"],
            "hist_metric": [0.5, 0.4],
            "hist_metric_pct": [50.0, 40.0],
            "kakuban": [1, 2],
        }
    )
    global_top_machines = pd.DataFrame(
        {
            "section": ["501-522", "601-616"],
            "rank_global_hist": [1, 2],
            "machine_number": [501, 601],
            "machine_name": ["A", "C"],
            "hist_metric": [0.5, 0.3],
            "hist_metric_pct": [50.0, 30.0],
            "kakuban": [1, 3],
        }
    )
    roster = pd.DataFrame({"machine_number": [501, 502]})
    return mod.PredictionBundle(
        target_date=pd.Timestamp("2026-06-25"),
        roster_date=pd.Timestamp("2026-06-25"),
        actual_date_used=True,
        roster=roster,
        section_summary=section_summary,
        selected_machines=selected_machines,
        global_top_machines=global_top_machines,
    )


def test_main_requires_date_when_not_eval(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mod, "_prepare_frame", lambda *args, **kwargs: pd.DataFrame())

    exit_code = mod.main(["--output-dir", str(tmp_path)])

    assert exit_code == 1
    assert not any(tmp_path.iterdir())


def test_main_single_date_writes_csv_and_markdown(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mod, "_prepare_frame", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(mod, "_build_prediction_bundle", lambda *args, **kwargs: _make_bundle())

    exit_code = mod.main(["--date", "20260625", "--output-dir", str(tmp_path)])

    assert exit_code == 0
    assert (tmp_path / "predict_section_20260625.csv").exists()
    assert (tmp_path / "predict_section_20260625_machines.csv").exists()
    report = (tmp_path / "predict_section_20260625.md").read_text(encoding="utf-8")
    assert "Section Prediction: 2026-06-25" in report
    assert "Global Hist Top" in report


def test_main_eval_writes_summary_and_report(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mod, "_prepare_frame", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(
        mod,
        "_evaluate_walkforward",
        lambda *args, **kwargs: (
            pd.DataFrame({"section": ["501-522"], "section_score": [0.4], "section_hit_rate": [0.5]}),
            pd.DataFrame(
                {
                    "top_k": [1],
                    "section_baseline_rate": [0.4],
                    "section_top_rate": [0.5],
                    "section_lift": [1.25],
                    "machine_baseline_rate": [0.3],
                    "selected_machine_rate": [0.35],
                    "selected_machine_lift": [1.167],
                    "global_hist_rate": [0.33],
                    "global_hist_lift": [1.1],
                    "selected_machine_count": [2],
                }
            ),
            pd.DataFrame({"machine_number": [501], "hist_metric": [0.5], "actual_hit_flag": [True]}),
        ),
    )

    exit_code = mod.main(["--eval", "--output-dir", str(tmp_path)])

    assert exit_code == 0
    assert (tmp_path / "predict_section_eval_sections.csv").exists()
    assert (tmp_path / "predict_section_eval_summary.csv").exists()
    assert (tmp_path / "predict_section_eval_machines.csv").exists()
    report = (tmp_path / "evaluation_report.md").read_text(encoding="utf-8")
    assert "Section Prediction Evaluation" in report
