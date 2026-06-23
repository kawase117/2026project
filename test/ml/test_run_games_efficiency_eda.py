from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.machine_type import machine_type_common as common
from ml.machine_type.exploratory import run_games_efficiency_eda as games_eda


def _make_games_frame() -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=31, freq="D")
    rows: list[dict[str, object]] = []
    for idx, date in enumerate(dates, start=1):
        rows.append(
            {
                "hall_id": "hall_a",
                "machine_name": "m1",
                "date": date,
                "machine_count": 3,
                "total_games": float(idx * 100),
                "avg_games": float(idx),
                "total_diff_coins": float(idx * 10),
                "avg_diff_coins": float(idx * 10 / 3.0),
                "win_rate": 0.5,
                "efficiency": float(idx * 10 / (idx * 100)),
                "is_top_3": 1 if idx >= 20 else 0,
            }
        )
    return pd.DataFrame(rows)


def test_add_games_efficiency_features_uses_previous_30_days_and_lag1() -> None:
    frame = _make_games_frame()

    out = games_eda.add_games_efficiency_features(frame)

    day_31 = out.loc[out["date"] == pd.Timestamp("2026-01-31")].iloc[0]
    prior_avg = pd.Series(np.arange(1, 31), dtype=float).mean()
    prior_std = pd.Series(np.arange(1, 31), dtype=float).std(ddof=1)
    expected_z = (31.0 - prior_avg) / prior_std

    assert day_31["games_zscore"] == pytest.approx(expected_z)
    assert out.loc[out["date"] == pd.Timestamp("2026-01-30"), "lag1_games_zscore"].iloc[0] == pytest.approx(
        out.loc[out["date"] == pd.Timestamp("2026-01-29"), "games_zscore"].iloc[0]
    )


def test_build_machine_name_correlation_summary_aggregates_within_machine() -> None:
    frame = pd.DataFrame(
        {
            "machine_name": ["m1"] * 10 + ["m2"] * 10,
            "games_zscore": list(range(10)) + list(range(10, 0, -1)),
            "is_top_3": list(range(10)) + list(range(10)),
        }
    )

    summary = common.build_machine_name_correlation_summary(frame, ["games_zscore"], "is_top_3")

    assert summary.loc[0, "feature"] == "games_zscore"
    assert summary.loc[0, "target"] == "is_top_3"
    assert summary.loc[0, "n_groups"] == 2
    assert summary.loc[0, "mean_rho"] == pytest.approx(0.0, abs=1e-12)
