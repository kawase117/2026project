"""Tests for hall_multitest_signal_baseline.py (Stage 1+2)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _make_panel(
    stores: list[str],
    n_days: int,
    seed: int = 42,
    diff_means: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Build a synthetic panel: date x store with avg_diff_per_machine."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2025-07-07", periods=n_days, freq="D")
    rows = []
    for store in stores:
        mean = (diff_means or {}).get(store, 0.0)
        diffs = rng.normal(mean, 80.0, size=n_days)
        for i, date in enumerate(dates):
            rows.append(
                {
                    "date": date,
                    "store": store,
                    "avg_diff_per_machine": float(diffs[i]),
                    "avg_games_per_machine": 500.0,
                    "total_machines": 100,
                    "win_rate": 0.5,
                    "is_any_event": 0,
                    "weekday": date.weekday(),
                    "dd": date.day,
                    "mm": date.month,
                    "is_zorome_day": int(date.day in [11, 22]),
                    "is_strong_zorome_day": int(date.day == date.month),
                }
            )
    return pd.DataFrame(rows).sort_values(["date", "store"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# add_daily_rank
# ---------------------------------------------------------------------------

def test_add_daily_rank_assigns_1_to_best() -> None:
    from ml.last_digit.hall_multitest_signal_baseline import add_daily_rank

    panel = _make_panel(["A", "B", "C"], n_days=10)
    ranked = add_daily_rank(panel)

    for date, g in ranked.groupby("date"):
        best_store = (
            g.sort_values("avg_diff_per_machine", ascending=False)
            .iloc[0]["store"]
        )
        rank1_store = g[g["daily_rank"] == 1].iloc[0]["store"]
        assert best_store == rank1_store, (
            f"date={date}: best={best_store} but rank1={rank1_store}"
        )


def test_add_daily_rank_n_halls_matches_store_count() -> None:
    from ml.last_digit.hall_multitest_signal_baseline import add_daily_rank

    panel = _make_panel(["X", "Y"], n_days=5)
    ranked = add_daily_rank(panel)
    assert (ranked["n_halls_that_day"] == 2).all()


# ---------------------------------------------------------------------------
# Stage 1: signal tests
# ---------------------------------------------------------------------------

def test_rank_autocorr_returns_row_for_each_lag() -> None:
    from ml.last_digit.hall_multitest_signal_baseline import (
        _test_rank_autocorr,
        add_daily_rank,
        LAGS,
    )

    panel = _make_panel(["A", "B", "C"], n_days=60)
    ranked = add_daily_rank(panel)
    hall_a = ranked[ranked["store"] == "A"].reset_index(drop=True)
    rows = _test_rank_autocorr(hall_a)
    lag_vals = {r["lag"] for r in rows}
    for lag in LAGS:
        assert lag in lag_vals, f"lag={lag} missing from autocorr output"


def test_calendar_precision_returns_rows_for_each_threshold() -> None:
    from ml.last_digit.hall_multitest_signal_baseline import (
        _test_calendar_precision,
        add_daily_rank,
        THRESHOLDS,
    )

    panel = _make_panel(["A", "B"], n_days=180)
    ranked = add_daily_rank(panel)
    hall_a = ranked[ranked["store"] == "A"].reset_index(drop=True)
    rows = _test_calendar_precision(hall_a, topk_dd=5, min_dd_days=3)
    thresholds_found = {r["threshold"] for r in rows}
    for thr in THRESHOLDS:
        assert thr in thresholds_found


def test_bonferroni_p_bounded_and_scaled_correctly() -> None:
    from ml.last_digit.hall_multitest_signal_baseline import (
        apply_bonferroni_per_hall,
    )

    signal_df = pd.DataFrame(
        [
            {"store": "A", "test_type": "t1", "p_value": 0.01},
            {"store": "A", "test_type": "t2", "p_value": 0.03},
            {"store": "A", "test_type": "t3", "p_value": float("nan")},
            {"store": "B", "test_type": "t1", "p_value": 0.001},
        ]
    )
    result = apply_bonferroni_per_hall(signal_df)

    valid = result["p_bonferroni"].dropna()
    assert (valid >= 0.0).all() and (valid <= 1.0).all()

    # Hall A: 2 valid tests → p_bonferroni = p_raw * 2
    row_a = result[
        (result["store"] == "A") & (result["test_type"] == "t1")
    ].iloc[0]
    assert abs(row_a["p_bonferroni"] - min(0.01 * 2, 1.0)) < 1e-9


# ---------------------------------------------------------------------------
# Stage 2: baselines
# ---------------------------------------------------------------------------

def test_baseline_oracle_ge_any_single_hall_mean() -> None:
    from ml.last_digit.hall_multitest_signal_baseline import baseline_oracle

    panel = _make_panel(["A", "B", "C"], n_days=30)
    result = baseline_oracle(panel)
    hall_means = panel.groupby("store")["avg_diff_per_machine"].mean()
    # Oracle picks the best hall each day, so its mean must be >= any hall mean
    assert result["chosen_avg_diff_mean"] >= hall_means.max() - 1e-6


def test_baseline_random_mean_close_to_grand_mean() -> None:
    from ml.last_digit.hall_multitest_signal_baseline import baseline_random

    panel = _make_panel(["A", "B", "C"], n_days=50)
    grand_mean = panel["avg_diff_per_machine"].mean()
    result = baseline_random(panel, seed=42, n_reps=500)
    assert abs(result["chosen_avg_diff_mean"] - grand_mean) < 20.0


def test_baseline_historical_best_picks_highest_avg_hall() -> None:
    from ml.last_digit.hall_multitest_signal_baseline import (
        baseline_historical_best_fixed,
    )

    sel = _make_panel(
        ["A", "B", "C"], n_days=100,
        diff_means={"A": 200, "B": 50, "C": 0},
    )
    ho = _make_panel(
        ["A", "B", "C"], n_days=20, seed=99,
        diff_means={"A": 200, "B": 50, "C": 0},
    )
    result = baseline_historical_best_fixed(sel, ho)
    assert result["best_hall"] == "A"


def test_baseline_weekday_fixed_n_days_equals_holdout_days() -> None:
    from ml.last_digit.hall_multitest_signal_baseline import baseline_weekday_fixed

    sel = _make_panel(["A", "B"], n_days=90)
    ho = _make_panel(["A", "B"], n_days=28, seed=77)
    result = baseline_weekday_fixed(sel, ho)
    assert result["n_days"] == ho["date"].nunique()


def test_oracle_ge_hist_best_ge_on_synthetic() -> None:
    """Oracle diff must be >= hist-best, which must be >= random (on average)."""
    from ml.last_digit.hall_multitest_signal_baseline import (
        baseline_oracle,
        baseline_historical_best_fixed,
        baseline_weekday_fixed,
    )

    sel = _make_panel(
        ["A", "B", "C"], n_days=100,
        diff_means={"A": 150, "B": 80, "C": 30},
    )
    ho = _make_panel(
        ["A", "B", "C"], n_days=50, seed=55,
        diff_means={"A": 150, "B": 80, "C": 30},
    )

    oracle_val = baseline_oracle(ho)["chosen_avg_diff_mean"]
    hist_val = baseline_historical_best_fixed(sel, ho)["chosen_avg_diff_mean"]
    wday_val = baseline_weekday_fixed(sel, ho)["chosen_avg_diff_mean"]

    assert oracle_val >= hist_val - 1e-6, (
        f"oracle={oracle_val:.2f} < hist_best={hist_val:.2f}"
    )
    assert oracle_val >= wday_val - 1e-6, (
        f"oracle={oracle_val:.2f} < weekday={wday_val:.2f}"
    )
