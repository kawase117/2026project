from __future__ import annotations

import pandas as pd


def test_window_result_requires_window1_effect_for_consistency(monkeypatch) -> None:
    from eda import machine_dd_recent_window_scan as analysis

    window0_breakdown = pd.DataFrame(
        {
            "axis_level": list(range(1, 11)),
            "n": [9] * 10,
            "plus_rate": [10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
            "hit104_rate": [10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
        }
    )
    window1_breakdown = pd.DataFrame(
        {
            "axis_level": list(range(1, 11)),
            "n": [9] * 10,
            "plus_rate": [11, 21, 31, 41, 51, 61, 71, 81, 91, 101],
            "hit104_rate": [11, 21, 31, 41, 51, 61, 71, 81, 91, 101],
        }
    )

    def fake_scan_binary_outcome(window_frame, *, axis, outcome_col):
        if window_frame["date_ts"].max() >= pd.Timestamp("2026-05-01"):
            return {"p_value": 0.01, "effect_size": 0.2}
        return {"p_value": 0.02, "effect_size": 0.0}

    def fake_axis_breakdown(hall, machine_name, window_frame, *, axis, outcome):
        return window0_breakdown if window_frame["window_tag"].iloc[0] == "recent" else window1_breakdown

    monkeypatch.setattr(analysis, "_scan_binary_outcome", fake_scan_binary_outcome)
    monkeypatch.setattr(analysis, "_axis_breakdown", fake_axis_breakdown)

    frame = pd.DataFrame(
        {
            "date": ["20260630"] * 10 + ["20260401"] * 10,
            "date_ts": pd.to_datetime(["2026-06-30"] * 10 + ["2026-04-01"] * 10),
            "machine_name": ["stable"] * 20,
            "window_tag": ["recent"] * 10 + ["prior"] * 10,
        }
    )

    row = analysis._window_result(
        "蒲田7",
        "stable",
        "plus",
        frame,
        window_days=90,
        min_machine_days_per_window=1,
        min_cell_n_for_dd=1,
        min_common_dd_levels=10,
    )

    assert row["recent_significant"] is True
    assert row["consistent_with_prior_window"] is False
    assert "window1_effect<0.05" in row["note"]
    assert row["window0_top_dd"] == 10
    assert row["window1_top_dd"] == 10


def test_build_hall_outputs_uses_dd_column_names(monkeypatch) -> None:
    from eda import machine_dd_recent_window_scan as analysis

    def fake_prepare_frame(raw, *, shindai_exclude_days):
        return raw.copy()

    def fake_apply_currently_installed_filter(frame, *, grace_days):
        return frame.copy()

    def fake_scan_binary_outcome(window_frame, *, axis, outcome_col):
        return {"p_value": 0.01, "effect_size": 0.2}

    def fake_axis_breakdown(hall, machine_name, window_frame, *, axis, outcome):
        return pd.DataFrame(
            {
                "axis_level": list(range(1, 11)),
                "n": [9] * 10,
                "plus_rate": [10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
                "hit104_rate": [10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
            }
        )

    monkeypatch.setattr(analysis, "_prepare_frame", fake_prepare_frame)
    monkeypatch.setattr(analysis, "_apply_currently_installed_filter", fake_apply_currently_installed_filter)
    monkeypatch.setattr(analysis, "_scan_binary_outcome", fake_scan_binary_outcome)
    monkeypatch.setattr(analysis, "_axis_breakdown", fake_axis_breakdown)

    raw = pd.DataFrame(
        {
            "date": ["20260630", "20260401"],
            "machine_name": ["stable", "stable"],
            "machine_number": [1, 1],
            "dd": [30, 1],
            "plus": [1, 1],
            "hit104": [1, 1],
            "diff": [100, 100],
            "games": [1000, 1000],
        }
    )

    result = analysis.build_hall_outputs(
        "蒲田7",
        raw,
        shindai_exclude_days=0,
        currently_installed_grace_days=0,
        window_days=90,
        min_machine_days_per_window=1,
        min_cell_n_for_dd=1,
        min_common_dd_levels=10,
    )

    assert "window0_top_dd" in result.columns
    assert "window1_top_dd" in result.columns
    assert result.loc[0, "hall"] == "蒲田7"
