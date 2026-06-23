from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda.mitoya_machinename_q5_backtest import (  # noqa: E402
    X_DDS,
    build_backtest_outputs,
    build_q5_machinename_table,
    build_training_table,
    summarize_pair,
)


def _make_df(n_periods: int = 3, machines: list[str] | None = None) -> pd.DataFrame:
    """
    テスト用 DataFrame: 3期間 × 3機種 × 各30日
    X_DDS日 (DD=4,7,14,17,24,27) はQ5機種のdiffを高めに設定
    """
    _ = n_periods
    machine_names = machines or ["Q1", "Q3", "Q5"]
    specs = {
        "Q1": {"machine_number": 1001, "base": -100},
        "Q3": {"machine_number": 1002, "base": 0},
        "Q5": {"machine_number": 1003, "base": 100},
    }
    rows: list[dict[str, object]] = []
    month_starts = ["2025-01-01", "2025-04-01", "2025-07-01"]
    for period_idx, start in enumerate(month_starts[:n_periods]):
        start_date = pd.Timestamp(start)
        for day_offset in range(30):
            date = start_date + pd.Timedelta(days=day_offset)
            dd = date.day
            xdds_bonus = 80 if dd in X_DDS else 0
            for machine_name in machine_names:
                spec = specs[machine_name]
                diff = spec["base"] + period_idx * 20
                if machine_name == "Q5":
                    diff += xdds_bonus
                rows.append(
                    {
                        "date": date,
                        "machine_number": spec["machine_number"],
                        "machine_name": machine_name,
                        "diff_coins_normalized": diff,
                        "games_normalized": 1000,
                        "period": period_idx,
                        "is_xdds": dd in X_DDS,
                    }
                )
    return pd.DataFrame(rows)


def test_x_dds_constant() -> None:
    assert X_DDS == {4, 7, 14, 17, 24, 27}


def test_build_training_table_quintile() -> None:
    df = _make_df()
    training = build_training_table(df)
    assert training["quintile"].min() >= 1
    assert training["quintile"].max() <= 5


def test_build_backtest_outputs_keys() -> None:
    outputs = build_backtest_outputs(_make_df())
    assert {"period_summary", "xdds_overlay", "q5_machinenames_per_period"} <= set(outputs.keys())
    assert "period_summary_2F" not in outputs
    assert "period_summary_3F" not in outputs


def test_summarize_pair_q5_beats_q1() -> None:
    df = _make_df(n_periods=1)
    training = build_training_table(df)
    test_df = df[df["period"] == 0].copy()
    qmax = training["quintile"].max()
    qmin = training["quintile"].min()
    q5_names = set(training.loc[training["quintile"] == qmax, "machine_name"])
    q1_names = set(training.loc[training["quintile"] == qmin, "machine_name"])
    row = summarize_pair(test_df, q5_names, q1_names, skip_if_missing_q5=False)
    assert row["Q5_avg_diff"] > row["Q1_avg_diff"]
    assert row["Q5_vs_Q1_diff"] > 0
