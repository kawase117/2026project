from __future__ import annotations

from pathlib import Path

import pandas as pd


def _section_allocation_frame() -> pd.DataFrame:
    dates = [f"202607{day:02d}" for day in range(1, 13)]
    rows: list[dict[str, object]] = []
    for idx, date in enumerate(dates):
        rows.append(
            {
                "hall": "H",
                "date": date,
                "axis": "section",
                "axis_value": "A",
                "excess_vs_hall_day": 10.0 + (idx % 2),
                "games_share": 0.5,
            }
        )
        b_value = (-8.0 if idx % 2 == 0 else -9.0) if idx < 6 else (-0.2 if idx % 2 == 0 else 0.2)
        rows.append(
            {
                "hall": "H",
                "date": date,
                "axis": "section",
                "axis_value": "B",
                "excess_vs_hall_day": b_value,
                "games_share": 0.5,
            }
        )
        c_value = (8.0 if idx % 2 == 0 else 9.0) if idx < 6 else (-2.0 if idx % 2 == 0 else -3.0)
        rows.append(
            {
                "hall": "H",
                "date": date,
                "axis": "section",
                "axis_value": "C",
                "excess_vs_hall_day": c_value,
                "games_share": 0.5,
            }
        )
    return pd.DataFrame(rows)


def _source_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for day in range(1, 13):
        date = f"202607{day:02d}"
        rows.extend(
            [
                {
                    "hall": "H",
                    "date": date,
                    "machine_number": 1001,
                    "machine_name": "juggler-a",
                    "machine_category": "juggler",
                    "section": "A",
                    "games": 700,
                },
                {
                    "hall": "H",
                    "date": date,
                    "machine_number": 1002,
                    "machine_name": "at-a",
                    "machine_category": "at_smart",
                    "section": "A",
                    "games": 300,
                },
                {
                    "hall": "H",
                    "date": date,
                    "machine_number": 2001,
                    "machine_name": "other-b",
                    "machine_category": "other",
                    "section": "B",
                    "games": 500,
                },
                {
                    "hall": "H",
                    "date": date,
                    "machine_number": 2002,
                    "machine_name": "bt-b",
                    "machine_category": "bt",
                    "section": "B",
                    "games": 500,
                },
            ]
        )
    return pd.DataFrame(rows)


def test_splithalf_verdicts_and_category_notes_are_complete() -> None:
    from eda import hall_budget_allocation_splithalf_check as analysis

    summary = analysis.build_splithalf_summary("H", _section_allocation_frame(), _source_frame(), t_threshold=0.5)

    by_axis = summary.set_index("axis_value")

    assert by_axis.loc["A", "verdict"] == "stable"
    assert by_axis.loc["A", "category_note"] == "dominated_by_juggler"
    assert by_axis.loc["B", "verdict"] == "weak_in_one_half"
    assert by_axis.loc["B", "category_note"] == "dominated_by_bt+other"
    assert by_axis.loc["C", "verdict"] == "sign_flip"
    assert set(summary["verdict"]) == {"stable", "weak_in_one_half", "sign_flip"}
    assert summary["category_note"].notna().all()
    assert summary["n_days_first"].tolist() == [6, 6, 6]
    assert summary["n_days_second"].tolist() == [6, 6, 6]


def test_markdown_renderer_does_not_require_pandas_to_markdown() -> None:
    from eda import hall_budget_allocation_splithalf_check as analysis

    summary = analysis.build_splithalf_summary("H", _section_allocation_frame(), _source_frame(), t_threshold=0.5)
    report = analysis.build_markdown_report("H", summary)

    assert "# H Split-half Section Stability" in report
    assert "| axis_value |" in report
    assert "dominated_by_juggler" in report
    assert "to_markdown" not in report


def test_main_writes_summary_and_reports(tmp_path: Path, monkeypatch) -> None:
    from eda import hall_budget_allocation_splithalf_check as analysis

    raw = pd.DataFrame({"date": ["20260701"], "machine_number": [1], "machine_name": ["x"], "diff": [1], "games": [1]})
    original_build_summary = analysis.build_splithalf_summary

    monkeypatch.setattr(analysis, "TARGET_HALLS", ["H"])
    monkeypatch.setattr(analysis, "HALL_DBS", {"H": "fake.db"})
    monkeypatch.setattr(
        analysis,
        "build_splithalf_summary",
        lambda hall, allocation, source_frame, t_threshold: original_build_summary(
            hall, allocation, source_frame, t_threshold=0.5
        ),
    )
    monkeypatch.setattr(analysis, "load_hall_df", lambda hall: raw)
    monkeypatch.setattr(analysis, "prepare_plan_source_frame", lambda frame, hall, min_games: _source_frame())
    monkeypatch.setattr(analysis, "build_plan_allocation_by_axis", lambda frame: _section_allocation_frame())

    exit_code = analysis.main(["--halls", "H", "--output-root", str(tmp_path)])

    assert exit_code == 0
    summary_path = tmp_path / "summary_splithalf.csv"
    report_path = tmp_path / "H_splithalf_report.md"
    assert summary_path.exists()
    assert report_path.exists()
    written = pd.read_csv(summary_path)
    assert written["hall"].tolist() == ["H", "H", "H"]
    assert written["category_note"].notna().all()
