from __future__ import annotations

import pandas as pd

from ml.machine_type.exploratory import run_machine_weekday_event_eda as weekday_eda


def _make_weekday_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "hall_id": ["hall_a", "hall_a", "hall_a", "hall_a"],
            "machine_name": ["m1", "m1", "m2", "m2"],
            "date": pd.to_datetime(["2026-01-11", "2026-01-22", "2026-01-12", "2026-01-13"]),
            "machine_count": [2, 2, 2, 2],
            "total_games": [100, 110, 120, 130],
            "avg_games": [50, 55, 60, 65],
            "total_diff_coins": [10, 20, 30, 40],
            "avg_diff_coins": [5, 10, 15, 20],
            "win_rate": [0.5, 0.6, 0.7, 0.8],
            "efficiency": [0.10, 0.18, 0.25, 0.31],
            "is_top_3": [0, 1, 0, 1],
        }
    )


def test_add_machine_weekday_event_features_uses_date_based_weekday_and_zorome_day() -> None:
    frame = _make_weekday_frame()

    out = weekday_eda.add_machine_weekday_event_features(frame)

    jan_11 = out.loc[out["date"] == pd.Timestamp("2026-01-11")].iloc[0]
    jan_12 = out.loc[out["date"] == pd.Timestamp("2026-01-12")].iloc[0]

    assert jan_11["day_of_week"] == 6
    assert jan_11["is_zorome_day"] == 1
    assert jan_11["event_group"] == 1
    assert jan_12["is_zorome_day"] == 0


def test_build_interaction_extremes_reports_top_and_bottom_pairs() -> None:
    frame = _make_weekday_frame()
    out = weekday_eda.add_machine_weekday_event_features(frame)

    table = weekday_eda.build_interaction_extremes(out, group_cols=["machine_name", "day_of_week"], min_n=1)

    assert set(table["interaction_type"].unique()) == {"top", "bottom"}
    assert {"machine_name", "day_of_week", "interaction_delta", "n", "interaction_type"} <= set(table.columns)

