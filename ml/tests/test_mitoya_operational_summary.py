from __future__ import annotations

import pandas as pd

from ml.last_digit.mitoya_operational_summary import build_operational_summary


def test_build_operational_summary_uses_rule_buckets_and_sunday_override() -> None:
    rebucket = pd.DataFrame(
        [
            {"bucket": "4day", "n_days": 8, "mean_diff": 100.0, "hit_at_1": 0.2, "hit_at_2": 0.6, "played_rate": 0.6},
            {"bucket": "Sunday", "n_days": 12, "mean_diff": -50.0, "hit_at_1": 0.1, "hit_at_2": 0.3, "played_rate": 0.8},
            {"bucket": "weekend", "n_days": 20, "mean_diff": 40.0, "hit_at_1": 0.3, "hit_at_2": 0.5, "played_rate": 0.85},
            {"bucket": "weakday", "n_days": 30, "mean_diff": 10.0, "hit_at_1": 0.25, "hit_at_2": 0.45, "played_rate": 0.75},
            {"bucket": "neutral", "n_days": 10, "mean_diff": -60.0, "hit_at_1": 0.2, "hit_at_2": 0.28, "played_rate": 0.76},
        ]
    )
    sunday = pd.DataFrame(
        [
            {"q_override": 0.55, "mean_diff": -20.0, "hit_at_2": 0.33, "played_rate": 0.60, "n_days": 12},
            {"q_override": 0.65, "mean_diff": 5.0, "hit_at_2": 0.35, "played_rate": 0.53, "n_days": 12},
        ]
    )

    detail, overall = build_operational_summary(rebucket, sunday, sunday_q=0.65)

    assert detail.loc[detail["bucket"].eq("4day"), "decision"].iloc[0] == "adopt"
    assert detail.loc[detail["bucket"].eq("weekend"), "decision"].iloc[0] == "adopt"
    assert detail.loc[detail["bucket"].eq("Sunday"), "mean_diff"].iloc[0] == 5.0
    assert detail.loc[detail["bucket"].eq("Sunday"), "decision"].iloc[0] == "adopt"
    assert detail.loc[detail["bucket"].eq("weakday"), "decision"].iloc[0] == "monitor"
    assert detail.loc[detail["bucket"].eq("neutral"), "decision"].iloc[0] == "exclude"
    assert overall["active_bucket_count"] == 3
    assert overall["active_n_days"] == 40
    assert overall["active_mean_diff"] == (100.0 * 8 + 5.0 * 12 + 40.0 * 20) / 40.0
