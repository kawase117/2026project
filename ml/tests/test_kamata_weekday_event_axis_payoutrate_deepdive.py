from __future__ import annotations

import pandas as pd

from ml.analysis.kamata_weekday_event_axis_payoutrate_deepdive import (
    _compare_with_halves,
    compute_payoutrate_pct,
    summarize_threshold_rates,
)


def test_compute_payoutrate_pct_uses_diff_coins_and_games() -> None:
    assert compute_payoutrate_pct(0, 100) == 100.0
    assert compute_payoutrate_pct(300, 100) == 200.0
    assert compute_payoutrate_pct(-150, 100) == 50.0
    assert pd.isna(compute_payoutrate_pct(1, 0))


def test_summarize_threshold_rates_counts_day_level_hits_for_each_threshold() -> None:
    daily = pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2026-06-01",
                    "2026-06-02",
                    "2026-06-03",
                    "2026-06-04",
                ]
            ),
            "weekday": ["Sun", "Sun", "Thu", "Thu"],
            "payoutrate_pct": [101.0, 105.0, 111.0, 99.0],
            "n_machines": [1, 1, 1, 1],
        }
    )

    summary, filtered = summarize_threshold_rates(
        daily,
        cell_cols=["weekday"],
        min_dates=2,
        thresholds=(100.0, 104.0, 110.0),
    )

    assert filtered["weekday"].tolist() == ["Sun", "Sun", "Thu", "Thu"]
    sun = summary.loc[summary["weekday"].eq("Sun")].iloc[0]
    thu = summary.loc[summary["weekday"].eq("Thu")].iloc[0]

    assert sun["hit_rate_100"] == 1.0
    assert sun["hit_rate_104"] == 0.5
    assert sun["hit_rate_110"] == 0.0
    assert thu["hit_rate_100"] == 0.5
    assert thu["hit_rate_104"] == 0.5
    assert thu["hit_rate_110"] == 0.5


def test_compare_with_halves_marks_consistent_hit_rate_signal_stable() -> None:
    dates = pd.date_range("2026-06-01", periods=20, freq="D")
    weekdays = ["Sun" if idx % 2 == 0 else "Thu" for idx in range(len(dates))]
    hit_104 = [1 if weekday == "Sun" else 0 for weekday in weekdays]
    mean_payoutrate = [108.0 if weekday == "Sun" else 96.0 for weekday in weekdays]
    mean_excess = [value - 100.0 for value in mean_payoutrate]

    daily = pd.DataFrame(
        {
            "date": dates,
            "weekday": weekdays,
            "hit_104": hit_104,
            "hit_100": hit_104,
            "hit_110": [0] * len(dates),
            "mean_payoutrate_pct": mean_payoutrate,
            "mean_excess_pct": mean_excess,
            "n_machines": [1] * len(dates),
        }
    )

    compare = _compare_with_halves(daily, label_col="weekday", rate_col="hit_104")

    sun = compare.loc[compare["weekday"].eq("Sun")].iloc[0]
    thu = compare.loc[compare["weekday"].eq("Thu")].iloc[0]

    assert bool(sun["stable"]) is True
    assert bool(thu["stable"]) is True
    assert sun["direction"] == "cell_higher"
    assert thu["direction"] == "cell_lower"
