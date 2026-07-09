from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eda import mitoya_phase7_shortlist_backtest as backtest
from eda.mitoya_phase7_shortlist_backtest import (
    build_backtest_outputs,
    build_period_summary,
    build_scenario_summary,
    build_section_fixed_summary,
    build_shortlist_period_table,
    build_top_n_sensitivity_table,
)


def _make_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    month_starts = ["2025-01-01", "2025-04-01", "2025-07-01"]
    machine_specs = [
        {"machine_number": 1, "machine_name": "A", "section": "557-573", "base": -50, "rank_from_aisle": 1},
        {"machine_number": 2, "machine_name": "B", "section": "557-573", "base": 10, "rank_from_aisle": 2},
        {"machine_number": 3, "machine_name": "C", "section": "591-607", "base": 30, "rank_from_aisle": 1},
        {"machine_number": 4, "machine_name": "D", "section": "591-607", "base": 80, "rank_from_aisle": 2},
    ]
    for period_idx, start in enumerate(month_starts):
        start_date = pd.Timestamp(start)
        for day_offset in range(30):
            date = start_date + pd.Timedelta(days=day_offset)
            is_xdds = date.day in {4, 7, 14, 17, 24, 27}
            for spec in machine_specs:
                diff = spec["base"] + period_idx * 20
                if spec["machine_name"] in {"B", "D"}:
                    diff += 60 if period_idx < 2 else 10
                rows.append(
                    {
                        "date": date.strftime("%Y%m%d"),
                        "period": period_idx,
                        "machine_number": spec["machine_number"],
                        "machine_name": spec["machine_name"],
                        "section": spec["section"],
                        "diff": diff,
                        "games": 1200,
                        "rank_from_aisle": spec["rank_from_aisle"],
                        "is_xdds": is_xdds,
                    }
                )
    return pd.DataFrame(rows)


def test_build_backtest_outputs_keys() -> None:
    outputs = build_backtest_outputs(_make_frame())
    assert {"period_summary", "xdds_overlay", "shortlist_per_period"} <= set(outputs)


def test_shortlist_period_table_tracks_periods() -> None:
    backtest.SHORTLIST_MIN_N = 0
    shortlist = build_shortlist_period_table(_make_frame(), top_n=2)
    assert {"period_train", "period_test", "section", "machine_name", "rank"} <= set(shortlist.columns)
    assert shortlist.groupby(["period_train", "section"]).size().max() == 2


def test_backtest_prefers_shortlist_over_target_mean() -> None:
    backtest.SHORTLIST_MIN_N = 0
    summary = build_period_summary(_make_frame(), top_n=1)
    assert summary["Shortlist_vs_Target_diff"].mean() > 0


def test_top_n_sensitivity_includes_all_requested_values() -> None:
    backtest.SHORTLIST_MIN_N = 0
    table = build_top_n_sensitivity_table(_make_frame(), top_n_values=(1, 3))
    assert set(table["top_n"]) == {1, 3}
    assert set(table["scope"]) == {"全体", "X_DDS日"}


def test_section_fixed_summary_tracks_each_section() -> None:
    backtest.SHORTLIST_MIN_N = 0
    table = build_section_fixed_summary(_make_frame(), top_n=1)
    assert set(table["section"]) == {"557-573", "591-607"}
    assert set(table["scope"]) == {"全体", "X_DDS日"}


def test_missing_test_window_machine_is_removed_from_shortlist() -> None:
    backtest.SHORTLIST_MIN_N = 0
    frame = _make_frame()
    extra_rows = []
    for period_idx, start in enumerate(["2025-01-01", "2025-04-01"]):
        start_date = pd.Timestamp(start)
        for day_offset in range(29):
            date = start_date + pd.Timedelta(days=day_offset)
            extra_rows.append(
                {
                    "date": date.strftime("%Y%m%d"),
                    "period": period_idx,
                    "machine_number": 5,
                    "machine_name": "E",
                    "section": "557-573",
                    "diff": 500,
                    "games": 1200,
                    "rank_from_aisle": 3,
                    "is_xdds": date.day in {4, 7, 14, 17, 24, 27},
                }
            )
    frame = pd.concat([frame, pd.DataFrame(extra_rows)], ignore_index=True)
    shortlist = build_shortlist_period_table(frame, top_n=2)
    assert "E" not in set(shortlist.loc[shortlist["period_test"] == 1.0, "machine_name"])


def test_scenario_summary_includes_requested_runs() -> None:
    backtest.SHORTLIST_MIN_N = 0
    table = build_scenario_summary(
        _make_frame(),
        scenarios={
            "557-573_only": {"sections": ["557-573"], "xday_only": False},
            "501-522_xdds_only": {"sections": ["501-522"], "xday_only": True},
        },
        top_n=2,
    )
    assert set(table["scenario"]) == {"557-573_only", "501-522_xdds_only"}
