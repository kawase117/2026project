from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ml.analysis.kamata7_section_dd_band_eda import (
    _categorize_dd_band,
    _compute_daily_aggregations,
    _compute_dd_band_anova,
    _compute_segment_summary,
    _build_large_summary,
)


def test_categorize_dd_band_priority():
    assert _categorize_dd_band(1) == "event"
    assert _categorize_dd_band(10) == "event"
    assert _categorize_dd_band(15) == "mid"
    assert _categorize_dd_band(25) == "late"
    assert _categorize_dd_band(30) == "event"


def test_daily_pay_rate_aggregation_uses_date_granularity():
    frame = pd.DataFrame(
        {
            "date": ["2026-06-01", "2026-06-01", "2026-06-02", "2026-06-02"],
            "segment": ["2F", "2F", "2F", "2F"],
            "section": ["A", "A", "A", "A"],
            "section_size_group": ["large", "large", "large", "large"],
            "dd": [1, 1, 2, 2],
            "machine_number": [1, 2, 1, 2],
            "games_normalized": [300, 300, 300, 300],
            "diff_coins_normalized": [0, 90, 0, -90],
        }
    )

    daily = _compute_daily_aggregations(frame)

    assert len(daily) == 2
    assert set(daily["dd_band"].tolist()) == {"event", "early"}
    assert daily.loc[daily["date"].eq(pd.Timestamp("2026-06-01")), "pay_rate"].iloc[0] == pytest.approx(105.0)
    assert daily.loc[daily["date"].eq(pd.Timestamp("2026-06-02")), "pay_rate"].iloc[0] == pytest.approx(95.0)


def test_dd_band_anova_groups_by_segment_section_and_band():
    frame = pd.DataFrame(
        {
            "date": [
                "2026-06-01",
                "2026-06-02",
                "2026-06-11",
                "2026-06-12",
            ],
            "segment": ["2F", "2F", "2F", "2F"],
            "section": ["A", "A", "A", "A"],
            "section_size_group": ["large", "large", "large", "large"],
            "dd": [1, 2, 11, 12],
            "dd_band": ["event", "early", "mid", "mid"],
            "pay_rate": [105.0, 101.0, 98.0, 99.0],
        }
    )

    result = _compute_dd_band_anova(frame)

    assert set(result["section_size_group"]) == {"large"}
    assert result.shape[0] == 1
    assert {"f_value", "p_value", "group_mean", "group_std", "event_mean", "early_mean", "mid_mean", "late_mean"}.issubset(result.columns)
    assert result["event_mean"].iloc[0] == pytest.approx(105.0)
    assert result["early_mean"].iloc[0] == pytest.approx(101.0)
    assert result["mid_mean"].iloc[0] == pytest.approx(98.5)


def test_large_summary_shows_late_vs_early_difference():
    frame = pd.DataFrame(
        {
            "date": ["2026-06-02", "2026-06-02", "2026-06-25", "2026-06-25"],
            "segment": ["2F", "2F", "2F", "2F"],
            "section": ["A", "A", "A", "A"],
            "section_size_group": ["large", "large", "large", "large"],
            "dd": [2, 2, 25, 25],
            "machine_number": [1, 2, 1, 2],
            "games_normalized": [300, 300, 300, 300],
            "diff_coins_normalized": [0, 0, 180, 180],
        }
    )

    daily = _compute_daily_aggregations(frame)
    summary = _build_large_summary(daily)
    compare = (
        summary[summary["dd_band"].astype(str).eq("late")][["segment", "pay_rate"]]
        .rename(columns={"pay_rate": "late_pay_rate"})
        .merge(
            summary[summary["dd_band"].astype(str).eq("early")][["segment", "pay_rate"]].rename(columns={"pay_rate": "early_pay_rate"}),
            on="segment",
            how="outer",
        )
    )

    assert compare["late_pay_rate"].iloc[0] - compare["early_pay_rate"].iloc[0] >= 3.0


def test_large_section_summary_contains_expected_columns():
    frame = pd.DataFrame(
        {
            "date": ["2026-06-01", "2026-06-02"],
            "segment": ["2F", "2F"],
            "section": ["A", "A"],
            "section_size_group": ["large", "large"],
            "dd_band": ["event", "late"],
            "games_sum": [300, 300],
            "diff_sum": [0, 300],
            "pay_rate": [100.0, 110.0],
            "n_machines": [2, 2],
        }
    )

    summary = _compute_segment_summary(frame)

    assert not summary.empty
    assert {"segment", "section_size_group", "dd_band", "games_sum", "diff_sum", "pay_rate", "n_machines", "n_days"}.issubset(summary.columns)


def test_daily_aggregation_is_granular_by_section_and_band():
    frame = pd.DataFrame(
        {
            "date": [
                "2026-06-01",
                "2026-06-01",
                "2026-06-02",
                "2026-06-02",
            ],
            "segment": ["2F", "2F", "2F", "2F"],
            "section": ["A", "B", "A", "B"],
            "section_size_group": ["large", "large", "large", "large"],
            "dd": [1, 1, 2, 2],
            "machine_number": [1, 2, 1, 2],
            "games_normalized": [100, 100, 100, 100],
            "diff_coins_normalized": [0, 0, 0, 0],
        }
    )

    daily = _compute_daily_aggregations(frame)

    assert len(daily) == 4
    assert set(daily["section"].tolist()) == {"A", "B"}
    assert set(daily["dd_band"].tolist()) == {"event", "early"}
