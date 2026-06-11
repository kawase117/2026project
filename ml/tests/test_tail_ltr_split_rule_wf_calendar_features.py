from __future__ import annotations

import pandas as pd

from ml.last_digit.tail_ltr_split_rule_wf import add_simple_features


def test_add_simple_features_adds_calendar_features() -> None:
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-11", "2026-07-07", "2026-05-27"]),
            "entity_key": ["2F_N|1", "2F_N|1", "2F_N|1"],
            "total_diff_coins": [1.0, 2.0, 3.0],
            "total_diff_coins_focus": [1.0, 2.0, 3.0],
            "total_games": [100.0, 100.0, 100.0],
            "efficiency": [0.01, 0.02, 0.03],
            "efficiency_focus": [0.01, 0.02, 0.03],
            "win_rate": [0.1, 0.2, 0.3],
            "is_top_2": [0, 1, 0],
            "is_event_day": [1, 0, 0],
        }
    )

    out = add_simple_features(df)

    expected_cols = {
        "dd_value",
        "dd_sin",
        "dd_cos",
        "is_zorome_day",
        "is_strong_zorome_day",
        "is_day_7x",
        "is_day_1x",
        "is_wed_nonevent",
        "is_wed_event",
    }
    for col in expected_cols:
        assert col in out.columns

    row_111 = out.loc[out["date"] == pd.Timestamp("2026-01-11")].iloc[0]
    assert int(row_111["is_zorome_day"]) == 1
    assert int(row_111["is_strong_zorome_day"]) == 0
    assert int(row_111["is_day_1x"]) == 1

    row_707 = out.loc[out["date"] == pd.Timestamp("2026-07-07")].iloc[0]
    assert int(row_707["is_strong_zorome_day"]) == 1
    assert int(row_707["is_day_7x"]) == 1

