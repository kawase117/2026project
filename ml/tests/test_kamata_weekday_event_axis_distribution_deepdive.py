from __future__ import annotations

import pandas as pd

from ml.analysis.kamata_weekday_event_axis_distribution_deepdive import (
    _compare_metric_with_halves,
    _daily_weekday_frame,
    _raw_weekday_distribution_summary,
)


def test_daily_weekday_frame_builds_band_metrics() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-01", "2026-06-01", "2026-06-02", "2026-06-02"]),
            "weekday_label": ["Sun", "Sun", "Wed", "Wed"],
            "machine_number": [1, 2, 1, 2],
            "payoutrate_pct": [101.0, 103.0, 100.0, 106.0],
        }
    )

    daily = _daily_weekday_frame(frame)

    sun = daily.loc[daily["weekday_label"].eq("Sun")].iloc[0]
    wed = daily.loc[daily["weekday_label"].eq("Wed")].iloc[0]

    assert sun["mean_payoutrate_pct"] == 102.0
    assert sun["share_100_104"] == 1.0
    assert sun["share_104_plus"] == 0.0
    assert sun["daily_hit_100"] == 1.0
    assert wed["share_100_104"] == 0.5
    assert wed["share_104_plus"] == 0.5
    assert wed["shape_balance"] == 0.0


def test_raw_weekday_distribution_summary_orders_broad_shallow_first() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2026-06-01",
                    "2026-06-01",
                    "2026-06-02",
                    "2026-06-02",
                    "2026-06-03",
                    "2026-06-03",
                ]
            ),
            "weekday_label": ["Sun", "Sun", "Wed", "Wed", "Thu", "Thu"],
            "machine_number": [1, 2, 1, 2, 1, 2],
            "payoutrate_pct": [101.0, 103.0, 100.0, 106.0, 94.0, 96.0],
        }
    )

    summary, filtered = _raw_weekday_distribution_summary(frame, min_rows=1)

    assert len(filtered) == 6
    assert summary.iloc[0]["weekday_label"] == "Sun"
    sun = summary.loc[summary["weekday_label"].eq("Sun")].iloc[0]
    wed = summary.loc[summary["weekday_label"].eq("Wed")].iloc[0]

    assert sun["p50"] == 102.0
    assert sun["share_100_104"] == 1.0
    assert sun["share_104_plus"] == 0.0
    assert sun["shape_balance"] == 1.0
    assert wed["p50"] == 103.0
    assert wed["share_100_104"] == 0.5
    assert wed["share_104_plus"] == 0.5


def test_compare_metric_with_halves_marks_consistent_shape_signal_stable() -> None:
    dates = pd.date_range("2026-06-01", periods=20, freq="D")
    weekdays = ["Sun" if idx % 2 == 0 else "Thu" for idx in range(len(dates))]
    daily = pd.DataFrame(
        {
            "date": dates,
            "weekday_label": weekdays,
            "value": [1.0 if weekday == "Sun" else 0.0 for weekday in weekdays],
            "n_machines": [1] * len(dates),
        }
    )

    compare = _compare_metric_with_halves(daily, label_col="weekday_label", value_col="value")

    sun = compare.loc[compare["weekday_label"].eq("Sun")].iloc[0]
    thu = compare.loc[compare["weekday_label"].eq("Thu")].iloc[0]

    assert bool(sun["stable"]) is True
    assert bool(thu["stable"]) is True
    assert sun["direction"] == "cell_higher"
    assert thu["direction"] == "cell_lower"
