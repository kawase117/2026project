from __future__ import annotations

from pathlib import Path

import pandas as pd


def _summary_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"hall": "H", "axis_value": "A", "t_full": 6.0, "verdict": "stable"},
            {"hall": "H", "axis_value": "B", "t_full": 5.0, "verdict": "stable"},
            {"hall": "H", "axis_value": "C", "t_full": 5.0, "verdict": "stable"},
            {"hall": "H", "axis_value": "D", "t_full": 4.0, "verdict": "weak_in_one_half"},
        ]
    )


def _source_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = [f"202607{day:02d}" for day in range(1, 7)]
    for idx, date in enumerate(dates):
        for machine_number in [101, 102]:
            rows.append(
                {
                    "hall": "H",
                    "date": date,
                    "machine_number": machine_number,
                    "machine_name": "old_a" if idx < 3 else "new_a",
                    "section": "A",
                    "diff": 100 + machine_number,
                    "games": 1000,
                }
            )
        rows.extend(
            [
                {
                    "hall": "H",
                    "date": date,
                    "machine_number": 201,
                    "machine_name": "b_swap" if idx >= 3 else "b_old",
                    "section": "B",
                    "diff": 300 if idx in {0, 2, 4} else -300,
                    "games": 1000,
                },
                {
                    "hall": "H",
                    "date": date,
                    "machine_number": 202,
                    "machine_name": "b_stay",
                    "section": "B",
                    "diff": 300 if idx in {0, 2, 4} else -300,
                    "games": 100,
                },
                {
                    "hall": "H",
                    "date": date,
                    "machine_number": 203,
                    "machine_name": "b_stay_2",
                    "section": "B",
                    "diff": 300 if idx in {0, 2, 4} else -300,
                    "games": 100,
                },
            ]
        )
        for machine_number in [301, 302]:
            rows.append(
                {
                    "hall": "H",
                    "date": date,
                    "machine_number": machine_number,
                    "machine_name": "old_c" if idx < 3 else "new_c",
                    "section": "C",
                    "diff": 100,
                    "games": 1000,
                }
            )
    return pd.DataFrame(rows)


def _allocation_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for idx, date in enumerate([f"202607{day:02d}" for day in range(1, 7)]):
        rows.extend(
            [
                {
                    "hall": "H",
                    "date": date,
                    "axis": "section",
                    "axis_value": "A",
                    "excess_vs_hall_day": 5.0 + (idx % 2),
                },
                {
                    "hall": "H",
                    "date": date,
                    "axis": "section",
                    "axis_value": "B",
                    "excess_vs_hall_day": 4.0 + (idx % 2),
                },
                {
                    "hall": "H",
                    "date": date,
                    "axis": "section",
                    "axis_value": "C",
                    "excess_vs_hall_day": 4.0 if idx < 3 else -4.0,
                },
            ]
        )
    return pd.DataFrame(rows)


def test_load_stable_targets_filters_summary_file(tmp_path: Path) -> None:
    from eda import hall_budget_allocation_machine_swap_check as analysis

    path = tmp_path / "summary_splithalf.csv"
    _summary_frame().to_csv(path, index=False, encoding="utf-8")

    targets = analysis.load_stable_targets(path, halls=["H"])

    assert targets["axis_value"].tolist() == ["A", "B", "C"]
    assert targets["t_full_original"].tolist() == [6.0, 5.0, 5.0]


def test_machine_residual_summary_classifies_identity_and_survival() -> None:
    from eda import hall_budget_allocation_machine_swap_check as analysis

    targets = analysis.load_stable_targets_from_frame(_summary_frame(), halls=["H"])
    residual = analysis.build_machine_residual_summary("H", targets, _source_frame())
    by_axis = residual.set_index("axis_value")

    assert by_axis.loc["A", "residual_verdict"] == "explained_by_machine_identity"
    assert by_axis.loc["B", "residual_verdict"] == "explained_by_machine_identity"
    assert analysis._residual_verdict(5.0, 3.0) == "band_effect_survives_residualization"
    assert analysis._residual_verdict(5.0, 1.5) == "explained_by_machine_identity"
    assert analysis._residual_verdict(3.0, 1.8) == "partially_explained"
    assert residual["t_full_residual"].notna().all()


def test_machine_residual_centering_uses_games_weighted_machine_mean() -> None:
    from eda import hall_budget_allocation_machine_swap_check as analysis

    source = pd.DataFrame(
        [
            {
                "hall": "H",
                "date": "20260701",
                "machine_number": 401,
                "machine_name": "weighted",
                "section": "W",
                "diff": 100,
                "games": 1000,
            },
            {
                "hall": "H",
                "date": "20260702",
                "machine_number": 401,
                "machine_name": "weighted",
                "section": "W",
                "diff": 0,
                "games": 100,
            },
            {
                "hall": "H",
                "date": "20260703",
                "machine_number": 401,
                "machine_name": "weighted",
                "section": "W",
                "diff": 0,
                "games": 100,
            },
            {
                "hall": "H",
                "date": "20260701",
                "machine_number": 402,
                "machine_name": "weighted2",
                "section": "W",
                "diff": 0,
                "games": 100,
            },
            {
                "hall": "H",
                "date": "20260702",
                "machine_number": 402,
                "machine_name": "weighted2",
                "section": "W",
                "diff": 50,
                "games": 500,
            },
            {
                "hall": "H",
                "date": "20260703",
                "machine_number": 402,
                "machine_name": "weighted2",
                "section": "W",
                "diff": 0,
                "games": 100,
            },
        ]
    )

    residuals = analysis._with_machine_weighted_residuals(source, "W")
    weighted_sum_by_machine = (
        (residuals["machine_residual"] * residuals["games"]).groupby(residuals["machine_number"]).sum()
    )

    assert weighted_sum_by_machine.abs().max() < 1e-9
    assert round(
        float(residuals.loc[residuals["machine_number"].eq(401), "machine_weighted_mean_rate"].iloc[0]), 6
    ) == round(100 / 1200 * 100, 6)


def test_machine_swap_summary_detects_majority_swap_and_no_clear() -> None:
    from eda import hall_budget_allocation_machine_swap_check as analysis

    targets = analysis.load_stable_targets_from_frame(_summary_frame(), halls=["H"])
    swap = analysis.build_machine_swap_summary("H", targets, _source_frame(), _allocation_frame())
    by_axis = swap.set_index("axis_value")

    assert by_axis.loc["A", "swap_date"] == "20260704"
    assert by_axis.loc["A", "swap_verdict"] == "persists_across_swap"
    assert by_axis.loc["B", "swap_verdict"] == "no_clear_swap_in_window"
    assert by_axis.loc["C", "swap_verdict"] == "reverses_after_swap"
    assert swap.isna().sum().sum() == 0


def test_report_includes_machine_names_before_and_after_swap() -> None:
    from eda import hall_budget_allocation_machine_swap_check as analysis

    targets = analysis.load_stable_targets_from_frame(_summary_frame(), halls=["H"])
    residual = analysis.build_machine_residual_summary("H", targets, _source_frame())
    swap = analysis.build_machine_swap_summary("H", targets, _source_frame(), _allocation_frame())
    history = analysis.build_machine_history_summary("H", targets, _source_frame(), swap)
    report = analysis.build_hall_report("H", residual, swap, history)

    assert "| machine_names_before | machine_names_after |" in report
    assert "old_a" in report
    assert "new_a" in report
    assert "to_markdown" not in report
