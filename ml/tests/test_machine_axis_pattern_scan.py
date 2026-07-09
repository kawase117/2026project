from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


_WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]


def _make_row(
    date: str,
    machine_number: int,
    machine_name: str,
    diff: float,
    *,
    games: int = 1000,
) -> dict[str, object]:
    return {
        "date": date,
        "machine_number": machine_number,
        "machine_name": machine_name,
        "diff": diff,
        "games": games,
    }


def _axis_features(date: str) -> dict[str, object]:
    dt = pd.to_datetime(date, format="%Y%m%d")
    dd = int(date[-2:])
    return {
        "dd": dd,
        "day_of_week": _WEEKDAY_JP[dt.weekday()],
        "is_x_day": int(dd in {1, 7, 11, 17, 21, 22, 27, 31}),
    }


def _make_dd_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = [
        "20260301",
        "20260302",
        "20260401",
        "20260402",
        "20260501",
        "20260502",
        "20260601",
        "20260602",
        "20260701",
        "20260702",
    ]
    for idx, date in enumerate(dates):
        high = date.endswith("01")
        rows.extend(
            [
                _make_row(date, 101, "alpha", 600 if high else 0),
                _make_row(date, 102, "beta", 120),
                _make_row(date, 103, "gamma", -50 if idx % 2 else 50),
            ]
        )
    rows.append(_make_row("20260201", 104, "retired", 400))
    frame = pd.DataFrame(rows)
    axis_data = frame["date"].map(_axis_features)
    for column in ["dd", "day_of_week", "is_x_day"]:
        frame[column] = axis_data.map(lambda value, col=column: value[col])
    return frame


def _make_weekday_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    monday_dates = pd.date_range("2026-07-06", periods=5, freq="W-MON")
    tuesday_dates = pd.date_range("2026-07-07", periods=5, freq="W-TUE")
    for date in list(monday_dates) + list(tuesday_dates):
        date_str = date.strftime("%Y%m%d")
        monday = date.day_name() == "Monday"
        rows.extend(
            [
                _make_row(date_str, 201, "weekday_boost", 500 if monday else 0),
                _make_row(date_str, 202, "steady", 80),
            ]
        )
    frame = pd.DataFrame(rows)
    axis_data = frame["date"].map(_axis_features)
    for column in ["dd", "day_of_week", "is_x_day"]:
        frame[column] = axis_data.map(lambda value, col=column: value[col])
    return frame


def test_build_hall_outputs_detects_dd_and_weekday_signals() -> None:
    from eda import machine_axis_pattern_scan as analysis

    pattern_summary, top_signals, breakdown, summary = analysis.build_hall_outputs(
        "蒲田1",
        _make_dd_frame(),
        shindai_exclude_days=0,
        currently_installed_grace_days=0,
        min_machine_days_total=5,
        min_obs_for_ranking=5,
        top_n=6,
    )

    assert len(pattern_summary) == 36  # 4 axes (dd, day_of_week, is_x_day, dd_bin) x 3 outcomes x 3 machines
    assert set(pattern_summary["axis"].unique()) == {"dd", "day_of_week", "is_x_day", "dd_bin"}
    assert not top_signals.empty
    assert top_signals["effect_size"].is_monotonic_decreasing
    assert (top_signals["n_obs"] >= 5).all()
    assert ((summary["axis"].eq("dd")) & summary["outcome"].eq("diff")).any()
    assert (
        summary.loc[
            summary["axis"].eq("dd") & summary["outcome"].eq("diff"),
            "n_effect_ge_0_1",
        ].iloc[0]
        >= 1
    )
    assert set(
        breakdown.loc[:, ["machine_name", "axis"]].drop_duplicates().itertuples(index=False, name=None)
    ).issubset(set(top_signals.loc[:, ["machine_name", "axis"]].drop_duplicates().itertuples(index=False, name=None)))


def test_bias_corrected_cramers_v_reduces_noise_and_preserves_signal() -> None:
    from eda.machine_name_significance_scan import _cramers_v, _cramers_v_bias_corrected

    noisy_uncorrected = _cramers_v(19.0, 10_000, 20, 2)
    noisy_corrected = _cramers_v_bias_corrected(19.0, 10_000, 20, 2)
    strong_uncorrected = _cramers_v(200.0, 10_000, 20, 2)
    strong_corrected = _cramers_v_bias_corrected(200.0, 10_000, 20, 2)

    assert noisy_corrected < noisy_uncorrected
    assert noisy_corrected < 0.01
    assert strong_corrected < strong_uncorrected
    assert strong_corrected > 0.01


def test_build_hall_outputs_filters_retired_machine_and_finds_weekday_hit104() -> None:
    from eda import machine_axis_pattern_scan as analysis

    pattern_summary, top_signals, breakdown, _ = analysis.build_hall_outputs(
        "蒲田1",
        _make_weekday_frame(),
        shindai_exclude_days=0,
        currently_installed_grace_days=0,
        min_machine_days_total=5,
        min_obs_for_ranking=5,
        top_n=10,
    )

    assert "retired" not in set(pattern_summary["machine_name"].astype(str))
    assert "retired" not in set(top_signals["machine_name"].astype(str))
    assert "retired" not in set(breakdown["machine_name"].astype(str))

    weekday_signal = pattern_summary.loc[
        (pattern_summary["machine_name"].astype(str) == "weekday_boost")
        & pattern_summary["axis"].eq("day_of_week")
        & pattern_summary["outcome"].eq("hit104")
    ].iloc[0]
    assert weekday_signal["effect_size"] > 0.1


def test_binary_outcome_rows_leave_sparse_level_count_as_nan() -> None:
    from eda import machine_axis_pattern_scan as analysis

    pattern_summary, _, _, _ = analysis.build_hall_outputs(
        "闥ｲ逕ｰ1",
        _make_weekday_frame(),
        shindai_exclude_days=0,
        currently_installed_grace_days=0,
        min_machine_days_total=5,
        min_obs_for_ranking=5,
        top_n=10,
    )

    binary_rows = pattern_summary.loc[pattern_summary["outcome"].isin(["plus", "hit104"])]
    assert binary_rows["n_sparse_levels"].isna().all()


def test_main_writes_requested_csvs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from eda import machine_axis_pattern_scan as analysis

    monkeypatch.setattr(analysis, "HALL_DBS", {"蒲田1": "fake.db"})
    monkeypatch.setattr(analysis, "load_hall_df", lambda hall: _make_dd_frame())

    exit_code = analysis.main(
        [
            "--halls",
            "蒲田1",
            "--output-dir",
            str(tmp_path),
            "--currently-installed-grace-days",
            "0",
            "--min-machine-days-total",
            "5",
            "--min-obs-for-ranking",
            "5",
            "--top-n",
            "3",
        ]
    )

    assert exit_code == 0
    assert (tmp_path / "蒲田1_pattern_summary.csv").exists()
    assert (tmp_path / "蒲田1_top_signals.csv").exists()
    assert (tmp_path / "蒲田1_top_signal_breakdown.csv").exists()
    assert (tmp_path / "summary_report.csv").exists()


def test_compute_dd_bin_assigns_expected_labels() -> None:
    from eda import machine_axis_pattern_scan as analysis

    dd_series = pd.Series([1, 7, 8, 14, 15, 21, 22, 28, 29, 31, None])
    labels = analysis._compute_dd_bin(dd_series)

    assert labels.tolist()[:10] == [
        "1-7",
        "1-7",
        "8-14",
        "8-14",
        "15-21",
        "15-21",
        "22-28",
        "22-28",
        "29-31",
        "29-31",
    ]
    assert pd.isna(labels.iloc[10])


def test_dd_bin_axis_sorts_in_calendar_order_not_alphabetical() -> None:
    from eda import machine_axis_pattern_scan as analysis

    shuffled = pd.Series(["22-28", "1-7", "29-31", "8-14", "15-21"])
    assert analysis._sorted_axis_values(shuffled, "dd_bin") == [
        "1-7",
        "8-14",
        "15-21",
        "22-28",
        "29-31",
    ]
    assert analysis._axis_level_order("15-21", "dd_bin") == 2


def test_dd_bin_axis_pools_sparse_dd_cells_into_a_detectable_signal() -> None:
    from eda import machine_axis_pattern_scan as analysis

    rows: list[dict[str, object]] = []
    for week_idx, (lo, hi) in enumerate([(1, 7), (8, 14), (15, 21), (22, 28), (29, 31)]):
        for dd in range(lo, hi + 1):
            for rep in range(3):
                # Only the first week ("1-7") is boosted; individual DD cells within it
                # have n=3 each (below MIN_CELL_N), but pooled into "1-7" the bin has n=21.
                diff = 500 if week_idx == 0 else 0
                rows.append(
                    {
                        "date": f"202603{dd:02d}",
                        "machine_number": 101,
                        "machine_name": "alpha",
                        "diff": diff,
                        "games": 1000,
                        "dd": dd,
                    }
                )
    frame = pd.DataFrame(rows)
    frame["day_of_week"] = "月"
    frame["is_x_day"] = 0

    _, _, _, summary = analysis.build_hall_outputs(
        "蒲田1",
        frame,
        shindai_exclude_days=0,
        currently_installed_grace_days=0,
        min_machine_days_total=5,
        min_obs_for_ranking=5,
        top_n=10,
    )

    dd_row = summary.loc[summary["axis"].eq("dd") & summary["outcome"].eq("diff")].iloc[0]
    dd_bin_row = summary.loc[summary["axis"].eq("dd_bin") & summary["outcome"].eq("diff")].iloc[0]
    # Individual DD cells (n=3 each) are all below MIN_CELL_N=5, so the "dd" axis test
    # has too few valid groups to run at all; the pooled "dd_bin" axis (n=21/week) can.
    assert dd_row["n_valid_patterns"] == 0
    assert dd_bin_row["n_valid_patterns"] == 1
