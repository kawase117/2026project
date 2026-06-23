from __future__ import annotations

import pandas as pd
import pytest

from ml.analysis.kamata7_dd_fullspectrum_eda import (
    DD_RANGE,
    LR_ORDER,
    SECTION_SIZE_ORDER,
    SEGMENT_ORDER,
    SUMMARY_COLUMNS,
    _add_lr_split,
    _aggregate_segments,
    _build_report,
    _build_stats_csv,
    _build_summary_csv,
    _pivot_for_axis,
)


def _make_segment_frame(segment_label: str) -> pd.DataFrame:
    """Synthetic per-machine frame for one floor (mixed A/N machines).

    Two sections, both 'large', spread over DD 1-31 across two months so that
    every DD has at least two daily observations.
    """
    rows = []
    dates_by_dd: dict[int, list[str]] = {}
    for month in ("2026-05", "2026-06"):
        days = 31 if month == "2026-05" else 30
        for dd in range(1, days + 1):
            dates_by_dd.setdefault(dd, []).append(f"{month}-{dd:02d}")

    machine_no = 0
    for dd, date_list in dates_by_dd.items():
        for date in date_list:
            for section, x_values in (("S1", [1.0, 2.0, 8.0, 9.0]), ("S2", [10.0, 11.0, 18.0, 19.0])):
                for i, x in enumerate(x_values):
                    machine_no += 1
                    # Alternate machine type A/N within section.
                    mtype = "A" if i % 2 == 0 else "N"
                    rows.append(
                        {
                            "date": date,
                            "machine_number": machine_no,
                            "section": section,
                            "section_size_group": "large",
                            "rank_from_min": i + 1,
                            "machine_type_segment": mtype,
                            "X": x,
                            "games_normalized": 300,
                            "diff_coins_normalized": 90 if mtype == "A" else -90,
                        }
                    )
    frame = pd.DataFrame(rows)
    frame["dd"] = pd.to_datetime(frame["date"]).dt.day.astype("Int64")
    frame["_label"] = segment_label
    return frame


def _make_segments() -> dict[str, pd.DataFrame]:
    """Build the 4-key segment dict the aggregator expects."""
    base_2f = _make_segment_frame("2F")
    base_3f = _make_segment_frame("3F")
    segments: dict[str, pd.DataFrame] = {}
    for label, base in (("2F", base_2f), ("3F", base_3f)):
        tagged = _add_lr_split(base)
        for code in ("A", "N"):
            segments[f"{label}_{code}"] = tagged[tagged["machine_type_segment"].eq(code)].copy()
    return segments


def test_lr_split_uses_section_x_median():
    frame = pd.DataFrame(
        {
            "section": ["S1", "S1", "S1", "S1"],
            "X": [1.0, 2.0, 8.0, 9.0],
        }
    )
    out = _add_lr_split(frame)
    # median of [1,2,8,9] = 5.0 -> <=5 is L, >5 is R
    assert out["lr"].tolist() == ["L", "L", "R", "R"]


def test_lr_split_handles_missing_x():
    frame = pd.DataFrame({"section": ["S1", "S1"]})
    out = _add_lr_split(frame)
    assert set(out["lr"].tolist()) == {"Unknown"}


def test_aggregation_outputs_all_31_dds():
    cell = _aggregate_segments(_make_segments())
    assert not cell.empty
    dds = sorted(int(d) for d in cell["dd"].dropna().unique())
    assert dds == DD_RANGE
    # All four segments populated in the synthetic data.
    assert set(cell["segment"].unique()) == set(SEGMENT_ORDER)


def test_pay_rate_calculation_matches_formula():
    cell = _aggregate_segments(_make_segments())
    # A machines: diff +90 over 300 games -> ((300*3 + 90)/(300*3))*100 = 110.0
    a_rows = cell[cell["segment"].str.endswith("_A")]
    assert a_rows["pay_rate"].dropna().round(2).eq(110.0).all()
    # N machines: diff -90 -> 90.0
    n_rows = cell[cell["segment"].str.endswith("_N")]
    assert n_rows["pay_rate"].dropna().round(2).eq(90.0).all()


def test_summary_csv_columns_and_types():
    cell = _aggregate_segments(_make_segments())
    summary = _build_summary_csv(cell)
    assert list(summary.columns) == SUMMARY_COLUMNS
    assert not summary.empty
    assert set(summary["lr"].unique()).issubset(set(LR_ORDER) | {"Unknown"})
    assert set(summary["segment"].unique()).issubset(set(SEGMENT_ORDER))
    assert pd.api.types.is_integer_dtype(summary["dd"])
    assert pd.api.types.is_numeric_dtype(summary["games_sum"])
    assert pd.api.types.is_numeric_dtype(summary["pay_rate"])


def test_stats_csv_columns_and_per_dd():
    cell = _aggregate_segments(_make_segments())
    stats_df = _build_stats_csv(cell)
    expected = {
        "dd",
        "mean_pay_rate",
        "std_pay_rate",
        "n_days",
        "small_mean",
        "medium_mean",
        "large_mean",
        "f_value",
        "p_value",
    }
    assert expected.issubset(set(stats_df.columns))
    assert sorted(stats_df["dd"].tolist()) == DD_RANGE


def test_pivot_shapes():
    cell = _aggregate_segments(_make_segments())
    pivot_size = _pivot_for_axis(cell, "section_size_group", SECTION_SIZE_ORDER)
    pivot_lr = _pivot_for_axis(cell[cell["lr"].isin(LR_ORDER)], "lr", LR_ORDER)
    pivot_segment = _pivot_for_axis(cell, "segment", SEGMENT_ORDER)

    assert pivot_size.shape == (len(SECTION_SIZE_ORDER), len(DD_RANGE))  # 3 x 31
    assert pivot_lr.shape == (len(LR_ORDER), len(DD_RANGE))  # 2 x 31
    assert pivot_segment.shape == (len(SEGMENT_ORDER), len(DD_RANGE))  # 4 x 31
    assert list(pivot_size.columns) == DD_RANGE


def test_pivot_preserves_empty_segment_rows():
    # Drop all 2F_A data; its pivot row must still exist (all NaN).
    segments = _make_segments()
    segments["2F_A"] = segments["2F_A"].iloc[0:0]
    cell = _aggregate_segments(segments)
    pivot_segment = _pivot_for_axis(cell, "segment", SEGMENT_ORDER)
    assert "2F_A" in pivot_segment.index
    assert pivot_segment.loc["2F_A"].isna().all()


def test_report_contains_expected_sections():
    cell = _aggregate_segments(_make_segments())
    summary = _build_summary_csv(cell)
    stats_df = _build_stats_csv(cell)
    pivot_size = _pivot_for_axis(cell, "section_size_group", SECTION_SIZE_ORDER)
    pivot_lr = _pivot_for_axis(cell[cell["lr"].isin(LR_ORDER)], "lr", LR_ORDER)
    pivot_segment = _pivot_for_axis(cell, "segment", SEGMENT_ORDER)
    report = _build_report(
        cell=cell,
        summary=summary,
        stats_df=stats_df,
        pivot_size=pivot_size,
        pivot_lr=pivot_lr,
        pivot_segment=pivot_segment,
    )
    assert "# Kamata7 DD Fullspectrum EDA" in report
    assert "DD x section_size" in report
    assert "DD x LR" in report
    assert "DD x segment" in report
    assert "Per-DD stats" in report


def test_empty_input_returns_empty_outputs():
    cell = _aggregate_segments({})
    assert cell.empty
    summary = _build_summary_csv(cell)
    assert list(summary.columns) == SUMMARY_COLUMNS
    assert summary.empty
    stats_df = _build_stats_csv(cell)
    assert stats_df.empty
    pivot = _pivot_for_axis(cell, "segment", SEGMENT_ORDER)
    assert pivot.shape == (len(SEGMENT_ORDER), len(DD_RANGE))
