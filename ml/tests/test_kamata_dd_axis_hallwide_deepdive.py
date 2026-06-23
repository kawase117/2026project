from __future__ import annotations

from pathlib import Path

import pandas as pd

from ml.analysis.kamata_dd_axis_hallwide_deepdive import (
    _build_hallwide_frame,
    _daily_summary,
    _group_summary,
    run_branch_a,
)


def _synthetic_hallwide_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = pd.date_range("2026-01-01", "2026-12-31", freq="D")
    for date in dates:
        day = int(date.day)
        month = int(date.month)
        month_end = int(date.days_in_month)
        is_event = (
            day in {7, 17, 27}
            or day in {1, 11, 21, 31}
            or day in {11, 22}
            or day == month
            or day == month_end
        )
        diff = 400 if is_event else -150
        rows.append(
            {
                "date": date,
                "total_machines": 715,
                "avg_games_per_machine": 1000,
                "avg_diff_per_machine": diff,
                "win_rate": 65 if is_event else 35,
            }
        )
    return pd.DataFrame(rows)


def test_build_hallwide_frame_adds_required_columns() -> None:
    frame = _synthetic_hallwide_frame().head(4).copy()

    built = _build_hallwide_frame(frame)

    assert {"date", "dd", "payoutrate_pct", "dd_group", "is_event_7", "is_event_1", "is_zorome_11_22", "is_strong_zorome_mmdd", "is_month_end_actual", "is_all_event"} <= set(built.columns)
    assert built["dd"].tolist() == [1, 2, 3, 4]


def test_daily_summary_ranks_event_days_and_counts_dates() -> None:
    built = _build_hallwide_frame(_synthetic_hallwide_frame())

    summary, daily = _daily_summary(built, min_entity_dates=1)

    assert {"dd", "hit_rate_100", "hit_rate_104", "hit_rate_110", "mean_excess_pct", "median_payoutrate_pct", "cell_n_dates", "entity_n_dates", "n_machines"} <= set(summary.columns)
    dd1 = summary.loc[summary["dd"].eq(1)].iloc[0]
    assert int(dd1["cell_n_dates"]) == 12
    assert int(dd1["entity_n_dates"]) == 365
    assert int(dd1["n_machines"]) == 715
    assert "dd" in daily.columns


def test_group_summary_includes_expected_groups() -> None:
    built = _build_hallwide_frame(_synthetic_hallwide_frame())

    summary, compare, daily = _group_summary(built, min_entity_dates=1)

    assert {"group_label", "cell_n_dates", "entity_n_dates", "n_machines"} <= set(summary.columns)
    assert {"p_value", "q_value", "stable"} <= set(compare.columns)
    assert {"event_7", "event_1", "zorome_11_22", "strong_zorome_mmdd", "month_end_actual", "all_event"} <= set(compare["group_label"].astype(str))
    strong = summary.loc[summary["group_label"].astype(str).eq("strong_zorome_mmdd")].iloc[0]
    assert int(strong["cell_n_dates"]) == 12
    assert "group_label" in daily.columns


def test_group_compare_marks_all_event_stable() -> None:
    built = _build_hallwide_frame(_synthetic_hallwide_frame())

    _, compare, _ = _group_summary(built, min_entity_dates=1)

    all_event = compare.loc[compare["group_label"].astype(str).eq("all_event")].iloc[0]
    assert int(all_event["cell_n"]) + int(all_event["rest_n"]) == 365
    assert bool(all_event["stable"]) is True
    assert all_event["direction"] == "cell_higher"


def test_group_compare_uses_full_day_rest_for_individual_event_groups() -> None:
    built = _build_hallwide_frame(_synthetic_hallwide_frame())

    _, compare, _ = _group_summary(built, min_entity_dates=1)

    for group_label in ["event_7", "event_1", "zorome_11_22", "strong_zorome_mmdd", "month_end_actual"]:
        row = compare.loc[compare["group_label"].astype(str).eq(group_label)].iloc[0]
        assert int(row["cell_n"]) + int(row["rest_n"]) == 365


def test_branch_a_writes_reports_and_csvs(tmp_path: Path) -> None:
    result = run_branch_a(_synthetic_hallwide_frame(), output_root=tmp_path)

    assert (tmp_path / "branch_a" / "dd_summary.csv").exists()
    assert (tmp_path / "branch_a" / "dd_group_summary.csv").exists()
    assert (tmp_path / "branch_a" / "dd_compare.csv").exists()
    assert (tmp_path / "branch_a" / "dd_group_compare.csv").exists()
    assert (tmp_path / "branch_a" / "report.md").exists()
    assert result["stable_count"] >= 1
