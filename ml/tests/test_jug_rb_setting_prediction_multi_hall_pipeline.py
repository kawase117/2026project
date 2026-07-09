from __future__ import annotations

from pathlib import Path

import pandas as pd


def test_multi_hall_registry_includes_expected_halls() -> None:
    from ml.experiments.jug_rb_setting_prediction import multi_hall_pipeline as mh

    assert len(mh.HALL_SPECS) == 9
    assert [spec.hall_slug for spec in mh.HALL_SPECS] == [
        "kamata7",
        "kamata1",
        "arrow",
        "lategap",
        "mitoya",
        "rakuen",
        "hiroki",
        "zashiti",
        "kintoki",
    ]


def test_multi_hall_main_writes_summary_files(tmp_path: Path, monkeypatch) -> None:
    from ml.experiments.jug_rb_setting_prediction import multi_hall_pipeline as mh

    rows = [
        {
            "hall": "kamata7",
            "hall_slug": "kamata7",
            "db_path": "db0",
            "n_stage1_catalog": 2,
            "n_stage1_unknown": 0,
            "n_stage2_rows": 10,
            "n_stage3_rows": 10,
            "n_eval_days": 3,
            "B1R_minus_B0_mean": 0.08,
            "ci_lower": -0.01,
            "ci_upper": 0.19,
            "verdict": "neutral",
            "alloc_weekday_gap": 0.10,
            "alloc_event_gap": 0.06,
            "alloc_kakuban1_mean": 0.50,
            "alloc_family_gap_mean": 0.01,
        },
        {
            "hall": "kamata1",
            "hall_slug": "kamata1",
            "db_path": "db1",
            "n_stage1_catalog": 2,
            "n_stage1_unknown": 0,
            "n_stage2_rows": 10,
            "n_stage3_rows": 10,
            "n_eval_days": 3,
            "B1R_minus_B0_mean": 0.12,
            "ci_lower": 0.01,
            "ci_upper": 0.23,
            "verdict": "positive",
            "alloc_weekday_gap": 0.11,
            "alloc_event_gap": 0.07,
            "alloc_kakuban1_mean": 0.52,
            "alloc_family_gap_mean": 0.03,
        },
        {
            "hall": "arrow",
            "hall_slug": "arrow",
            "db_path": "db2",
            "n_stage1_catalog": 2,
            "n_stage1_unknown": 0,
            "n_stage2_rows": 10,
            "n_stage3_rows": 10,
            "n_eval_days": 3,
            "B1R_minus_B0_mean": -0.04,
            "ci_lower": -0.10,
            "ci_upper": 0.02,
            "verdict": "neutral",
            "alloc_weekday_gap": 0.09,
            "alloc_event_gap": 0.05,
            "alloc_kakuban1_mean": 0.48,
            "alloc_family_gap_mean": 0.02,
        },
    ]

    def fake_run_hall_pipeline(spec: mh.HallSpec) -> dict[str, object]:
        return next(row for row in rows if row["hall_slug"] == spec.hall_slug)

    monkeypatch.setattr(mh, "run_hall_pipeline", fake_run_hall_pipeline)

    output_root = tmp_path / "multi"
    exit_code = mh.main(
        ["--output-root", str(output_root), "--hall", "kamata7", "--hall", "kamata1", "--hall", "arrow"]
    )

    assert exit_code == 0
    csv_path = output_root / "multi_hall_summary.csv"
    md_path = output_root / "multi_hall_summary.md"
    assert csv_path.exists()
    assert md_path.exists()
    summary = pd.read_csv(csv_path)
    assert list(summary["hall_slug"]) == ["kamata7", "kamata1", "arrow"]
    md_text = md_path.read_text(encoding="utf-8")
    assert "Multi Hall Summary" in md_text
    assert "N/A" in md_text
