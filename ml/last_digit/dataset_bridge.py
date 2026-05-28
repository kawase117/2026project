from __future__ import annotations

import sqlite3
from calendar import monthrange
from pathlib import Path

import numpy as np
import pandas as pd

from ml.last_digit.utils import (
    FORECAST_EXCLUDED_COLUMNS as UTIL_FORECAST_EXCLUDED_COLUMNS,
    META_COLUMNS as UTIL_META_COLUMNS,
    TARGET_COLUMNS as UTIL_TARGET_COLUMNS,
)

WINDOWS = (7, 14, 28)
# Backward-compatible aliases (canonical definitions live in utils.py).
TARGET_COLUMNS = UTIL_TARGET_COLUMNS
META_COLUMNS = UTIL_META_COLUMNS
FORECAST_EXCLUDED_COLUMNS = UTIL_FORECAST_EXCLUDED_COLUMNS


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row[1]) for row in rows}


def _infer_store_id(db_path: Path) -> str:
    stem = Path(db_path).stem
    return stem if stem.endswith("_exp") else f"{stem}_exp"


def _event_group_for_date(current_date: pd.Timestamp) -> int:
    day = current_date.day
    if day in {1, 11, 21}:
        return 1
    if day in {7, 17, 27}:
        return 2
    if day == monthrange(current_date.year, current_date.month)[1]:
        return 3
    return 0


def _days_to_next_event_any(current_date: pd.Timestamp) -> float:
    if _event_group_for_date(current_date) > 0:
        return 0.0
    for offset in range(1, 33):
        candidate = current_date + pd.Timedelta(days=offset)
        if _event_group_for_date(candidate) > 0:
            return float(offset)
    return 365.0


def _days_since_last_event_any(current_date: pd.Timestamp) -> float:
    if _event_group_for_date(current_date) > 0:
        return 0.0
    for offset in range(1, 33):
        candidate = current_date - pd.Timedelta(days=offset)
        if _event_group_for_date(candidate) > 0:
            return float(offset)
    return 365.0


def _is_event_week(current_date: pd.Timestamp) -> int:
    for offset in range(-3, 4):
        candidate = current_date + pd.Timedelta(days=offset)
        if _event_group_for_date(candidate) > 0:
            return 1
    return 0


def _days_since_last_positive(dates: pd.Series, flags: pd.Series) -> list[float]:
    last_positive: pd.Timestamp | None = None
    values: list[float] = []
    for current_date, flag in zip(dates, flags, strict=False):
        if last_positive is None:
            values.append(365.0)
        else:
            values.append(float((current_date - last_positive).days))
        if int(flag) == 1:
            last_positive = current_date
    return values


def _prior_mean_transform(series: pd.Series) -> pd.Series:
    values = series.astype(float)
    prior_sum = values.cumsum() - values
    prior_count = pd.Series(np.arange(len(values)), index=values.index, dtype=float)
    return pd.Series(
        np.divide(
            prior_sum,
            prior_count,
            out=np.zeros(len(values), dtype=float),
            where=prior_count.to_numpy() > 0,
        ),
        index=values.index,
    )


def _consecutive_suppression_score(flags: pd.Series) -> pd.Series:
    values = flags.astype(int).to_numpy()
    scores = np.zeros(len(values), dtype=float)
    consecutive_3_count = 0
    expected_rate = 0.1**3
    for idx in range(len(values)):
        if idx >= 3:
            actual_rate = consecutive_3_count / max(idx - 2, 1)
            scores[idx] = ((expected_rate - actual_rate) / expected_rate) * 100.0
        if idx >= 2 and values[idx - 2] == 1 and values[idx - 1] == 1 and values[idx] == 1:
            consecutive_3_count += 1
    return pd.Series(scores, index=flags.index, dtype=float)


def _fixed_cut_bin(series: pd.Series, bins: list[float]) -> pd.Series:
    if series.empty:
        return pd.Series(dtype=int)
    values = series.fillna(0.0).astype(float)
    clipped = values.clip(lower=bins[0], upper=bins[-1])
    return pd.cut(
        clipped,
        bins=bins,
        labels=False,
        include_lowest=True,
        right=True,
    ).fillna(0).astype(int)


def _signed_fixed_width_bin(
    series: pd.Series,
    *,
    width: float,
    clip_min: int = -8,
    clip_max: int = 8,
) -> pd.Series:
    if series.empty:
        return pd.Series(dtype=int)
    values = series.fillna(0.0).astype(float).to_numpy()
    buckets = np.floor_divide(values, width).astype(int)
    buckets = np.clip(buckets, clip_min, clip_max)
    return pd.Series(buckets, index=series.index, dtype=int)


def _positive_fixed_width_bin(
    series: pd.Series,
    *,
    width: float,
    clip_max: int = 12,
) -> pd.Series:
    if series.empty:
        return pd.Series(dtype=int)
    values = series.fillna(0.0).clip(lower=0.0).astype(float).to_numpy()
    buckets = np.floor_divide(values, width).astype(int)
    buckets = np.clip(buckets, 0, clip_max)
    return pd.Series(buckets, index=series.index, dtype=int)


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    num = numerator.fillna(0.0).astype(float).to_numpy()
    den = denominator.fillna(0.0).astype(float).to_numpy()
    ratio = np.divide(
        num,
        den,
        out=np.zeros(len(num), dtype=float),
        where=np.abs(den) > 1e-6,
    )
    ratio = np.clip(ratio, -10.0, 10.0)
    return pd.Series(ratio, index=numerator.index, dtype=float)


def _load_last_digit_frame(conn: sqlite3.Connection) -> pd.DataFrame:
    cols = _table_columns(conn, "last_digit_summary_all")
    if not cols:
        raise ValueError("Table not found or empty schema: last_digit_summary_all")
    required = [
        "date",
        "last_digit",
        "machine_count",
        "total_games",
        "avg_games",
        "total_diff_coins",
        "avg_diff_coins",
    ]
    missing = [c for c in required if c not in cols]
    if missing:
        raise ValueError(f"Missing required columns in last_digit_summary_all: {missing}")

    optional = [c for c in ("win_rate", "high_profit_rate") if c in cols]
    select_cols = required + optional
    query = f"SELECT {', '.join(select_cols)} FROM last_digit_summary_all ORDER BY date, last_digit"
    df = pd.read_sql_query(query, conn)
    if df.empty:
        raise ValueError("last_digit_summary_all returned no rows")
    if "win_rate" not in df.columns:
        df["win_rate"] = 0.0
    if "high_profit_rate" not in df.columns:
        df["high_profit_rate"] = 0.0
    return df


def _compute_rank_targets(df: pd.DataFrame) -> pd.DataFrame:
    ranked = df.copy()
    ranked["rank_diff"] = ranked.groupby("date")["total_diff_coins"].rank(method="first", ascending=False)
    ranked["_tmp_best_rank"] = ranked["rank_diff"].astype(float)
    ranked["_tmp_worst_rank"] = ranked.groupby("date")["total_diff_coins"].rank(method="first", ascending=True)
    ranked["is_rank_1"] = (ranked["rank_diff"] == 1).astype(int)
    ranked["is_top_3"] = (ranked["rank_diff"] <= 3).astype(int)
    ranked["is_top_5"] = (ranked["rank_diff"] <= 5).astype(int)
    ranked["_tmp_is_worst1"] = (ranked["_tmp_worst_rank"] == 1).astype(int)
    ranked["_tmp_is_worst3"] = (ranked["_tmp_worst_rank"] <= 3).astype(int)
    ranked["_tmp_is_worst5"] = (ranked["_tmp_worst_rank"] <= 5).astype(int)
    return ranked.drop(columns=["rank_diff"])


def _add_common_features(df: pd.DataFrame) -> pd.DataFrame:
    enriched = df.copy()
    enriched["day_of_week"] = enriched["date"].dt.dayofweek
    enriched["day_of_month"] = enriched["date"].dt.day
    enriched["month_progress"] = (enriched["day_of_month"] - 1) / enriched["date"].dt.daysinmonth
    enriched["is_month_end_event"] = (enriched["day_of_month"] == enriched["date"].dt.daysinmonth).astype(int)
    enriched["event_group"] = enriched["date"].map(_event_group_for_date).astype(int)
    enriched["is_event_day"] = (enriched["event_group"] > 0).astype(int)

    unique_dates = pd.Index(enriched["date"].drop_duplicates().sort_values())
    event_features = {
        current_date: {
            "days_since_last_event_any": _days_since_last_event_any(current_date),
            "days_to_next_event_any": _days_to_next_event_any(current_date),
            "is_event_week": _is_event_week(current_date),
        }
        for current_date in unique_dates
    }
    enriched["days_since_last_event_any"] = enriched["date"].map(lambda d: event_features[d]["days_since_last_event_any"])
    enriched["days_to_next_event_any"] = enriched["date"].map(lambda d: event_features[d]["days_to_next_event_any"])
    enriched["is_event_week"] = enriched["date"].map(lambda d: event_features[d]["is_event_week"])
    enriched["event_signed_distance_any"] = enriched["days_since_last_event_any"] - enriched["days_to_next_event_any"]
    enriched["event_distance_abs_any"] = np.minimum(
        enriched["days_since_last_event_any"], enriched["days_to_next_event_any"]
    )
    enriched["event_distance_decay_3"] = np.exp(-enriched["event_distance_abs_any"] / 3.0)
    enriched["event_distance_decay_7"] = np.exp(-enriched["event_distance_abs_any"] / 7.0)
    enriched["event_phase_after_event"] = (
        enriched["days_since_last_event_any"] <= enriched["days_to_next_event_any"]
    ).astype(int)
    enriched["event_phase_before_event"] = (
        enriched["days_to_next_event_any"] < enriched["days_since_last_event_any"]
    ).astype(int)
    enriched["event_proximity_score"] = 1.0 / (enriched["days_to_next_event_any"] + 1.0)
    return enriched


def _add_temporal_group_features(df: pd.DataFrame) -> pd.DataFrame:
    enriched = df.copy()
    for column in (
        "lag_1_diff",
        "lag_7_diff",
        "lag_14_diff",
        "lag_21_diff",
        "lag_1_games",
        "lag_7_games",
        "lag_14_games",
        "lag_21_games",
        "days_since_last_rank1",
        "days_since_last_top3",
        "days_since_last_top5",
        "prior_top3_rate",
        "prior_top5_rate",
        "prior_rank1_rate",
        "same_weekday_top3_rate",
        "same_day_of_month_top3_gap",
        "same_weekday_rank1_rate",
        "same_day_of_month_rank1_rate",
        "same_weekday_rank1_gap",
        "same_day_of_month_rank1_gap",
        "days_since_last_rank1_same_weekday",
        "days_since_last_rank1_same_day_of_month",
        "rank1_streak_prev",
        "rank1_rebound_score",
    ):
        enriched[column] = 0.0
    same_weekday_columns = [
        *(f"same_weekday_lag_{lag}_diff" for lag in (1, 2, 3)),
        *(f"same_weekday_lag_{lag}_games" for lag in (1, 2, 3)),
        *(f"same_weekday_lag_{lag}_efficiency" for lag in (1, 2, 3)),
        "same_weekday_rolling_avg_diff_3",
        "same_weekday_rolling_avg_games_3",
        "same_weekday_rolling_avg_efficiency_3",
        "same_day_of_month_lag_1_diff",
        "same_day_of_month_lag_1_games",
        "same_day_of_month_lag_2_diff",
        "same_day_of_month_lag_2_games",
        "same_day_of_month_rolling_avg_diff_3",
        "same_day_of_month_rolling_avg_games_3",
    ]
    for column in same_weekday_columns:
        enriched[column] = 0.0
    for window in WINDOWS:
        enriched[f"rolling_avg_diff_{window}d"] = 0.0
        enriched[f"rolling_avg_games_{window}d"] = 0.0
        enriched[f"rolling_avg_efficiency_{window}d"] = 0.0

    groups: list[pd.DataFrame] = []
    for _, group in enriched.groupby("entity_key", sort=False):
        group = group.sort_values("date").copy()
        group["lag_1_diff"] = group["total_diff_coins"].shift(1).fillna(0.0)
        group["lag_7_diff"] = group["total_diff_coins"].shift(7).fillna(0.0)
        group["lag_14_diff"] = group["total_diff_coins"].shift(14).fillna(0.0)
        group["lag_21_diff"] = group["total_diff_coins"].shift(21).fillna(0.0)
        group["lag_1_games"] = group["total_games"].shift(1).fillna(0.0)
        group["lag_7_games"] = group["total_games"].shift(7).fillna(0.0)
        group["lag_14_games"] = group["total_games"].shift(14).fillna(0.0)
        group["lag_21_games"] = group["total_games"].shift(21).fillna(0.0)
        for window in WINDOWS:
            group[f"rolling_avg_diff_{window}d"] = (
                group["total_diff_coins"].rolling(window=window, min_periods=1).mean().shift(1).fillna(0.0)
            )
            group[f"rolling_avg_games_{window}d"] = (
                group["total_games"].rolling(window=window, min_periods=1).mean().shift(1).fillna(0.0)
            )
            group[f"rolling_avg_efficiency_{window}d"] = (
                group["efficiency"].rolling(window=window, min_periods=1).mean().shift(1).fillna(0.0)
            )

        for _, weekday_group in group.groupby("day_of_week", sort=False):
            weekday_index = weekday_group.index
            weekday_diff = weekday_group["total_diff_coins"]
            weekday_games = weekday_group["total_games"]
            weekday_efficiency = weekday_group["efficiency"]
            for lag in (1, 2, 3):
                group.loc[weekday_index, f"same_weekday_lag_{lag}_diff"] = weekday_diff.shift(lag).fillna(0.0)
                group.loc[weekday_index, f"same_weekday_lag_{lag}_games"] = weekday_games.shift(lag).fillna(0.0)
                group.loc[weekday_index, f"same_weekday_lag_{lag}_efficiency"] = (
                    weekday_efficiency.shift(lag).fillna(0.0)
                )
            group.loc[weekday_index, "same_weekday_rolling_avg_diff_3"] = (
                weekday_diff.shift(1).rolling(window=3, min_periods=1).mean().fillna(0.0)
            )
            group.loc[weekday_index, "same_weekday_rolling_avg_games_3"] = (
                weekday_games.shift(1).rolling(window=3, min_periods=1).mean().fillna(0.0)
            )
            group.loc[weekday_index, "same_weekday_rolling_avg_efficiency_3"] = (
                weekday_efficiency.shift(1).rolling(window=3, min_periods=1).mean().fillna(0.0)
            )

        for _, month_day_group in group.groupby("day_of_month", sort=False):
            month_day_index = month_day_group.index
            month_day_diff = month_day_group["total_diff_coins"]
            month_day_games = month_day_group["total_games"]
            group.loc[month_day_index, "same_day_of_month_lag_1_diff"] = month_day_diff.shift(1).fillna(0.0)
            group.loc[month_day_index, "same_day_of_month_lag_1_games"] = month_day_games.shift(1).fillna(0.0)
            group.loc[month_day_index, "same_day_of_month_lag_2_diff"] = month_day_diff.shift(2).fillna(0.0)
            group.loc[month_day_index, "same_day_of_month_lag_2_games"] = month_day_games.shift(2).fillna(0.0)
            group.loc[month_day_index, "same_day_of_month_rolling_avg_diff_3"] = (
                month_day_diff.shift(1).rolling(window=3, min_periods=1).mean().fillna(0.0)
            )
            group.loc[month_day_index, "same_day_of_month_rolling_avg_games_3"] = (
                month_day_games.shift(1).rolling(window=3, min_periods=1).mean().fillna(0.0)
            )

        group["days_since_last_rank1"] = _days_since_last_positive(group["date"], group["is_rank_1"])
        group["days_since_last_top3"] = _days_since_last_positive(group["date"], group["is_top_3"])
        group["days_since_last_top5"] = _days_since_last_positive(group["date"], group["is_top_5"])
        group["prior_rank1_rate"] = group["is_rank_1"].shift(1).expanding(min_periods=1).mean().fillna(0.0)
        group["prior_top3_rate"] = group["is_top_3"].shift(1).expanding(min_periods=1).mean().fillna(0.0)
        group["prior_top5_rate"] = group["is_top_5"].shift(1).expanding(min_periods=1).mean().fillna(0.0)
        group["same_weekday_top3_rate"] = (
            group.groupby("day_of_week", sort=False)["is_top_3"].transform(_prior_mean_transform).fillna(0.0)
        )
        group["same_weekday_rank1_rate"] = (
            group.groupby("day_of_week", sort=False)["is_rank_1"].transform(_prior_mean_transform).fillna(0.0)
        )
        same_day_of_month_top3_rate = (
            group.groupby("day_of_month", sort=False)["is_top_3"].transform(_prior_mean_transform).fillna(0.0)
        )
        same_day_of_month_rank1_rate = (
            group.groupby("day_of_month", sort=False)["is_rank_1"].transform(_prior_mean_transform).fillna(0.0)
        )
        group["same_day_of_month_top3_gap"] = same_day_of_month_top3_rate - group["prior_top3_rate"]
        group["same_day_of_month_rank1_rate"] = same_day_of_month_rank1_rate
        group["same_weekday_rank1_gap"] = group["same_weekday_rank1_rate"] - group["prior_rank1_rate"]
        group["same_day_of_month_rank1_gap"] = group["same_day_of_month_rank1_rate"] - group["prior_rank1_rate"]

        for _, weekday_group in group.groupby("day_of_week", sort=False):
            weekday_index = weekday_group.index
            group.loc[weekday_index, "days_since_last_rank1_same_weekday"] = _days_since_last_positive(
                weekday_group["date"], weekday_group["is_rank_1"]
            )
        for _, month_day_group in group.groupby("day_of_month", sort=False):
            month_day_index = month_day_group.index
            group.loc[month_day_index, "days_since_last_rank1_same_day_of_month"] = _days_since_last_positive(
                month_day_group["date"], month_day_group["is_rank_1"]
            )

        rank1_streak_prev: list[float] = []
        streak = 0
        for flag in group["is_rank_1"].astype(int).tolist():
            rank1_streak_prev.append(float(streak))
            streak = streak + 1 if flag == 1 else 0
        group["rank1_streak_prev"] = rank1_streak_prev
        group["rank1_rebound_score"] = (
            np.log1p(group["days_since_last_rank1"])
            * (1.0 - np.minimum(group["prior_rank1_rate"], 1.0))
            * (1.0 + group["same_weekday_rank1_rate"])
        )
        groups.append(group)
    return pd.concat(groups, ignore_index=True)


def _add_phase2_features(df: pd.DataFrame) -> pd.DataFrame:
    enriched = df.copy()
    for column in (
        "prior_worst1_rate",
        "prior_worst3_rate",
        "prior_worst5_rate",
        "dow_entity_rank1_rate",
        "dow_lastdigit_rank1_rate",
        "same_weekday_rolling_rank_sum_3",
        "weekday_entity_bias",
        "weekday_digit_bias",
        "anti_pattern_rank1_rate",
        "weekday_non_consecutive_rank1_rate",
        "consecutive_suppression_score",
        "last_digit_historical_rank1_rate",
        "last_digit_historical_rank3_rate",
        "last_digit_historical_rank5_rate",
        "last_digit_historical_avg_diff",
        "last_digit_historical_avg_efficiency",
        "last_digit_historical_worst_rate",
        "last_digit_top3_rate_by_digit",
        "last_digit_worst3_rate_by_digit",
        "last_digit_rank1_rate_vs_global_avg",
        "last_digit_rank1_rate_percentile",
        "last_digit_efficiency_ratio_to_avg",
        "last_digit_consecutive_days",
        "last_digit_gap_since_last_appearance",
        "last_digit_recency_boost",
        "last_digit_weekday_interaction_rank1_rate_7d",
        "last_digit_weekday_trend",
        "last_digit_rank1_market_share",
        "last_digit_performance_spread",
        "last_digit_spread_vs_global_avg",
        "last_digit_top3_worst3_ratio",
        "last_digit_high_performance_rate",
        "last_digit_low_performance_rate",
        "last_digit_top3_concentration",
        "last_digit_rank1_dominance_score",
        "last_digit_consistency_score",
    ):
        enriched[column] = 0.0

    groups: list[pd.DataFrame] = []
    for _, group in enriched.groupby("entity_key", sort=False):
        group = group.sort_values("date").copy()
        group["prior_worst1_rate"] = group["_tmp_is_worst1"].shift(1).expanding(min_periods=1).mean().fillna(0.0)
        group["prior_worst3_rate"] = group["_tmp_is_worst3"].shift(1).expanding(min_periods=1).mean().fillna(0.0)
        group["prior_worst5_rate"] = group["_tmp_is_worst5"].shift(1).expanding(min_periods=1).mean().fillna(0.0)

        group["same_weekday_rolling_rank_sum_3"] = (
            group.groupby("day_of_week", sort=False)["_tmp_best_rank"]
            .transform(lambda s: s.shift(1).rolling(window=3, min_periods=1).sum())
            .fillna(0.0)
        )
        overall_prior_sum = group["_tmp_best_rank"].cumsum() - group["_tmp_best_rank"]
        overall_prior_count = pd.Series(np.arange(len(group)), index=group.index, dtype=float)
        overall_prior_mean = np.divide(
            overall_prior_sum,
            overall_prior_count,
            out=np.zeros(len(group), dtype=float),
            where=overall_prior_count.to_numpy() > 0,
        )
        weekday_prior_sum = group.groupby("day_of_week", sort=False)["_tmp_best_rank"].cumsum() - group["_tmp_best_rank"]
        weekday_prior_count = group.groupby("day_of_week", sort=False).cumcount()
        weekday_prior_mean = np.divide(
            weekday_prior_sum,
            weekday_prior_count,
            out=np.zeros(len(group), dtype=float),
            where=weekday_prior_count.to_numpy() > 0,
        )
        group["weekday_entity_bias"] = np.where(
            (overall_prior_count.to_numpy() > 0) & (weekday_prior_count.to_numpy() > 0),
            weekday_prior_mean - overall_prior_mean,
            0.0,
        )
        group["weekday_digit_bias"] = group["weekday_entity_bias"]

        is_prev_rank1 = group["is_rank_1"].shift(1).fillna(0).astype(int)
        eligible_non_consecutive = (is_prev_rank1 == 0).astype(int)
        success_non_consecutive = eligible_non_consecutive * group["is_rank_1"]
        prior_non_consecutive_count = eligible_non_consecutive.cumsum() - eligible_non_consecutive
        prior_non_consecutive_success = success_non_consecutive.cumsum() - success_non_consecutive
        group["anti_pattern_rank1_rate"] = np.where(
            (is_prev_rank1.to_numpy() == 0) & (prior_non_consecutive_count.to_numpy() > 0),
            prior_non_consecutive_success / prior_non_consecutive_count,
            0.0,
        )

        prior_weekday_non_consecutive_count = (
            pd.Series(eligible_non_consecutive, index=group.index).groupby(group["day_of_week"], sort=False).cumsum()
            - eligible_non_consecutive
        )
        prior_weekday_non_consecutive_success = (
            pd.Series(success_non_consecutive, index=group.index).groupby(group["day_of_week"], sort=False).cumsum()
            - success_non_consecutive
        )
        group["weekday_non_consecutive_rank1_rate"] = np.where(
            (is_prev_rank1.to_numpy() == 0) & (prior_weekday_non_consecutive_count.to_numpy() > 0),
            prior_weekday_non_consecutive_success / prior_weekday_non_consecutive_count,
            0.0,
        )
        group["consecutive_suppression_score"] = _consecutive_suppression_score(group["is_rank_1"])

        group["last_digit_historical_avg_diff"] = (
            group["total_diff_coins"].shift(1).expanding(min_periods=1).mean().fillna(0.0)
        )
        group["last_digit_historical_avg_efficiency"] = (
            group["efficiency"].shift(1).expanding(min_periods=1).mean().fillna(0.0)
        )
        group["last_digit_weekday_interaction_rank1_rate_7d"] = (
            group.groupby("day_of_week", sort=False)["is_rank_1"]
            .transform(lambda s: s.shift(1).rolling(window=7, min_periods=1).mean())
            .fillna(0.0)
        )
        group["last_digit_consistency_score"] = (
            group["is_top_3"].shift(1).rolling(window=30, min_periods=1).mean().fillna(0.0)
        )
        groups.append(group)

    enriched = pd.concat(groups, ignore_index=True)
    enriched["dow_entity_rank1_rate"] = (
        enriched.groupby(["entity_key", "day_of_week"], sort=False)["is_rank_1"]
        .transform(_prior_mean_transform)
        .fillna(0.0)
    )
    enriched["dow_lastdigit_rank1_rate"] = enriched["dow_entity_rank1_rate"].copy()
    enriched["last_digit_historical_rank1_rate"] = enriched["prior_rank1_rate"]
    enriched["last_digit_historical_rank3_rate"] = enriched["prior_top3_rate"]
    enriched["last_digit_historical_rank5_rate"] = enriched["prior_top5_rate"]
    enriched["last_digit_historical_worst_rate"] = enriched["prior_worst1_rate"]
    enriched["last_digit_top3_rate_by_digit"] = enriched["prior_top3_rate"]
    enriched["last_digit_worst3_rate_by_digit"] = enriched["prior_worst3_rate"]

    daily = (
        enriched.groupby("date", sort=True)
        .agg(rank1_count=("is_rank_1", "sum"), avg_efficiency=("efficiency", "mean"))
        .reset_index()
    )
    daily["global_prior_rank1_rate"] = daily["rank1_count"].shift(1).expanding(min_periods=1).mean().fillna(0.0)
    daily["global_prior_efficiency"] = daily["avg_efficiency"].shift(1).expanding(min_periods=1).mean().fillna(0.0)
    enriched = enriched.merge(
        daily[["date", "global_prior_rank1_rate", "global_prior_efficiency"]],
        on="date",
        how="left",
    )
    enriched["global_prior_rank1_rate"] = enriched["global_prior_rank1_rate"].fillna(0.0)
    enriched["global_prior_efficiency"] = enriched["global_prior_efficiency"].fillna(0.0)
    enriched["last_digit_rank1_rate_vs_global_avg"] = (
        enriched["last_digit_historical_rank1_rate"] - enriched["global_prior_rank1_rate"]
    )
    enriched["last_digit_efficiency_ratio_to_avg"] = _safe_ratio(
        enriched["last_digit_historical_avg_efficiency"],
        enriched["global_prior_efficiency"],
    )
    enriched["last_digit_rank1_rate_percentile"] = (
        enriched.groupby("date", sort=False)["last_digit_historical_rank1_rate"].rank(method="average", pct=True).fillna(0.0)
    )
    enriched["last_digit_consecutive_days"] = enriched["rank1_streak_prev"]
    enriched["last_digit_gap_since_last_appearance"] = enriched["days_since_last_rank1"]
    enriched["last_digit_recency_boost"] = np.exp(-enriched["last_digit_gap_since_last_appearance"] / 7.0)
    enriched["last_digit_weekday_trend"] = enriched["same_weekday_rank1_gap"]
    enriched["last_digit_high_performance_rate"] = (
        enriched["last_digit_historical_rank1_rate"]
        + 0.7 * enriched["last_digit_historical_rank3_rate"]
        + 0.5 * enriched["last_digit_historical_rank5_rate"]
    ) / 3.0
    enriched["last_digit_low_performance_rate"] = (
        enriched["prior_worst1_rate"] + 0.7 * enriched["prior_worst3_rate"] + 0.5 * enriched["prior_worst5_rate"]
    ) / 3.0
    enriched["last_digit_top3_concentration"] = (
        enriched["last_digit_historical_rank1_rate"] + enriched["last_digit_historical_rank3_rate"]
    ) / 2.0
    enriched["last_digit_performance_spread"] = (
        enriched["last_digit_historical_rank1_rate"]
        + enriched["last_digit_historical_rank3_rate"]
        + enriched["last_digit_historical_rank5_rate"]
        - enriched["prior_worst1_rate"]
        - enriched["prior_worst3_rate"]
        - enriched["prior_worst5_rate"]
    )
    enriched["last_digit_top3_worst3_ratio"] = _safe_ratio(
        enriched["last_digit_top3_rate_by_digit"],
        enriched["last_digit_worst3_rate_by_digit"],
    )
    enriched["last_digit_rank1_market_share"] = enriched["last_digit_historical_rank1_rate"]
    top_share = enriched.groupby("date", sort=False)["last_digit_rank1_market_share"].transform("max")
    enriched["last_digit_rank1_dominance_score"] = _safe_ratio(
        enriched["last_digit_rank1_market_share"],
        top_share,
    )
    global_spread = enriched.groupby("date", sort=False)["last_digit_performance_spread"].transform("mean").fillna(0.0)
    enriched["last_digit_spread_vs_global_avg"] = enriched["last_digit_performance_spread"] - global_spread
    return enriched.drop(columns=["global_prior_rank1_rate", "global_prior_efficiency"])


def _add_forecast_safe_binning_and_interactions(df: pd.DataFrame) -> pd.DataFrame:
    enriched = df.copy()
    signed_bin_specs = {
        "lag_1_diff": 500.0,
        "lag_7_diff": 500.0,
        "lag_14_diff": 500.0,
        "lag_21_diff": 500.0,
        "rolling_avg_diff_7d": 500.0,
        "rolling_avg_diff_14d": 500.0,
        "rolling_avg_diff_28d": 500.0,
        "same_day_of_month_lag_1_diff": 500.0,
        "same_day_of_month_lag_2_diff": 500.0,
        "same_weekday_lag_1_diff": 500.0,
        "same_weekday_lag_2_diff": 500.0,
        "weekday_digit_bias": 1.0,
    }
    for column, width in signed_bin_specs.items():
        if column in enriched.columns:
            enriched[f"{column}_signed_bin"] = _signed_fixed_width_bin(enriched[column], width=width)

    positive_bin_specs = {
        "lag_1_games": 500.0,
        "lag_7_games": 500.0,
        "lag_14_games": 500.0,
        "lag_21_games": 500.0,
        "rolling_avg_games_7d": 500.0,
        "rolling_avg_games_14d": 500.0,
        "rolling_avg_games_28d": 500.0,
    }
    for column, width in positive_bin_specs.items():
        if column in enriched.columns:
            enriched[f"{column}_level_bin"] = _positive_fixed_width_bin(enriched[column], width=width)

    if "days_since_last_rank1" in enriched.columns:
        enriched["days_since_last_rank1_age_bin"] = _fixed_cut_bin(
            enriched["days_since_last_rank1"],
            bins=[-0.1, 0.0, 1.0, 3.0, 7.0, 14.0, 30.0, 90.0, 366.0],
        )
    if "days_since_last_top3" in enriched.columns:
        enriched["days_since_last_top3_age_bin"] = _fixed_cut_bin(
            enriched["days_since_last_top3"],
            bins=[-0.1, 0.0, 1.0, 3.0, 7.0, 14.0, 30.0, 90.0, 366.0],
        )
    if "days_since_last_top5" in enriched.columns:
        enriched["days_since_last_top5_age_bin"] = _fixed_cut_bin(
            enriched["days_since_last_top5"],
            bins=[-0.1, 0.0, 1.0, 3.0, 7.0, 14.0, 30.0, 90.0, 366.0],
        )

    for column in (
        "prior_worst1_rate",
        "prior_worst3_rate",
        "prior_worst5_rate",
        "prior_top3_rate",
        "prior_top5_rate",
        "same_weekday_top3_rate",
        "anti_pattern_rank1_rate",
        "weekday_non_consecutive_rank1_rate",
        "dow_lastdigit_rank1_rate",
    ):
        if column in enriched.columns:
            enriched[f"{column}_level_bin"] = _fixed_cut_bin(
                enriched[column],
                bins=[-0.001, 0.0, 0.02, 0.05, 0.10, 0.20, 0.35, 0.50, 1.0],
            )

    if {"lag_1_diff", "rolling_avg_diff_7d"} <= set(enriched.columns):
        enriched["lag_1_diff_minus_rolling_avg_diff_7d"] = enriched["lag_1_diff"] - enriched["rolling_avg_diff_7d"]
        enriched["lag_1_diff_to_rolling_avg_diff_7d_ratio"] = _safe_ratio(
            enriched["lag_1_diff"], enriched["rolling_avg_diff_7d"]
        )
    if {"lag_1_diff", "rolling_avg_diff_14d"} <= set(enriched.columns):
        enriched["lag_1_diff_minus_rolling_avg_diff_14d"] = (
            enriched["lag_1_diff"] - enriched["rolling_avg_diff_14d"]
        )
    if {"lag_1_games", "rolling_avg_games_7d"} <= set(enriched.columns):
        enriched["lag_1_games_minus_rolling_avg_games_7d"] = enriched["lag_1_games"] - enriched["rolling_avg_games_7d"]
        enriched["lag_1_games_to_rolling_avg_games_7d_ratio"] = _safe_ratio(
            enriched["lag_1_games"], enriched["rolling_avg_games_7d"]
        )
    if {"lag_1_games", "rolling_avg_games_14d"} <= set(enriched.columns):
        enriched["lag_1_games_minus_rolling_avg_games_14d"] = (
            enriched["lag_1_games"] - enriched["rolling_avg_games_14d"]
        )
    if {"same_day_of_month_lag_1_diff", "same_day_of_month_lag_2_diff"} <= set(enriched.columns):
        enriched["same_day_of_month_diff_gap"] = (
            enriched["same_day_of_month_lag_1_diff"] - enriched["same_day_of_month_lag_2_diff"]
        )
    if {"same_weekday_lag_1_diff", "same_weekday_lag_2_diff"} <= set(enriched.columns):
        enriched["same_weekday_diff_gap"] = (
            enriched["same_weekday_lag_1_diff"] - enriched["same_weekday_lag_2_diff"]
        )
    if {"weekday_digit_bias", "days_since_last_rank1"} <= set(enriched.columns):
        enriched["weekday_bias_x_days_since_rank1"] = (
            enriched["weekday_digit_bias"] * np.log1p(enriched["days_since_last_rank1"])
        )
    if {"anti_pattern_rank1_rate", "weekday_non_consecutive_rank1_rate"} <= set(enriched.columns):
        enriched["anti_pattern_x_weekday_non_consecutive"] = (
            enriched["anti_pattern_rank1_rate"] * enriched["weekday_non_consecutive_rank1_rate"]
        )
    if {"dow_lastdigit_rank1_rate", "anti_pattern_rank1_rate"} <= set(enriched.columns):
        enriched["dow_lastdigit_x_anti_pattern"] = (
            enriched["dow_lastdigit_rank1_rate"] * enriched["anti_pattern_rank1_rate"]
        )
    if {"days_since_last_rank1", "event_proximity_score"} <= set(enriched.columns):
        enriched["days_since_rank1_x_event_proximity"] = (
            np.log1p(enriched["days_since_last_rank1"]) * enriched["event_proximity_score"]
        )
    if {"rank1_streak_prev", "event_distance_decay_3"} <= set(enriched.columns):
        enriched["rank1_streak_x_event_decay_3"] = (
            np.log1p(enriched["rank1_streak_prev"]) * enriched["event_distance_decay_3"]
        )
    if {"same_weekday_rank1_gap", "same_day_of_month_rank1_gap"} <= set(enriched.columns):
        enriched["rank1_rotation_context_gap"] = (
            enriched["same_weekday_rank1_gap"] - enriched["same_day_of_month_rank1_gap"]
        )
    if {"days_since_last_rank1_same_weekday", "days_since_last_rank1_same_day_of_month"} <= set(enriched.columns):
        enriched["rank1_same_cycle_recency_gap"] = (
            enriched["days_since_last_rank1_same_weekday"] - enriched["days_since_last_rank1_same_day_of_month"]
        )
    return enriched


def _drop_internal_columns(df: pd.DataFrame) -> pd.DataFrame:
    return df.drop(
        columns=[
            c
            for c in ("_tmp_best_rank", "_tmp_worst_rank", "_tmp_is_worst1", "_tmp_is_worst3", "_tmp_is_worst5")
            if c in df.columns
        ]
    )


def build_last_digit_dataset(db_path: Path) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        df = _load_last_digit_frame(conn)
    df["store_id"] = _infer_store_id(db_path)
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["entity_key"] = df["last_digit"].astype(str)
    df = df.sort_values(["entity_key", "date"]).reset_index(drop=True)
    df["efficiency"] = (df["total_diff_coins"] / df["total_games"].replace(0, np.nan)).fillna(0.0)
    df = _compute_rank_targets(df)
    df = _add_common_features(df)
    df = _add_temporal_group_features(df)
    df = _add_phase2_features(df)
    df = _add_forecast_safe_binning_and_interactions(df)
    df = _drop_internal_columns(df)
    return df.sort_values(["date", "entity_key"]).reset_index(drop=True)
