from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ml.last_digit.utils import FORECAST_EXCLUDED_COLUMNS, META_COLUMNS


def add_top2_target(dataset: pd.DataFrame) -> pd.DataFrame:
    df = dataset.copy()
    rank = df.groupby("date", sort=False)["total_diff_coins"].rank(method="first", ascending=False)
    df["is_top_2"] = (rank <= 2).astype(int)
    return df


def add_regime_and_cluster_features(dataset: pd.DataFrame, config: Any | None = None) -> pd.DataFrame:
    efficiency_weight = float(getattr(config, "efficiency_weight", 0.6))
    diff_weight = float(getattr(config, "diff_weight", 0.3))
    event_weight = float(getattr(config, "event_weight", 0.1))

    df = dataset.copy()
    df = df.sort_values(["date", "entity_key"]).reset_index(drop=True)

    daily = (
        df.groupby("date", sort=True)
        .agg(
            hall_avg_diff=("total_diff_coins", "mean"),
            hall_std_diff=("total_diff_coins", "std"),
            hall_avg_eff=("efficiency", "mean"),
            hall_event_day=("is_event_day", "mean"),
        )
        .fillna(0.0)
        .reset_index()
    )
    event_flag = (daily["hall_event_day"] > 0.0).astype(int)
    daily["hall_event_rate_14"] = event_flag.shift(1).rolling(14, min_periods=1).mean().fillna(0.0)
    daily["hall_event_rate_30"] = event_flag.shift(1).rolling(30, min_periods=1).mean().fillna(0.0)

    days_since_event: list[float] = []
    last_event_idx: int | None = None
    for idx, flag in enumerate(event_flag.to_numpy()):
        if int(flag) == 1:
            last_event_idx = idx
            days_since_event.append(0.0)
        elif last_event_idx is None:
            days_since_event.append(999.0)
        else:
            days_since_event.append(float(idx - last_event_idx))
    daily["hall_days_since_event"] = pd.Series(days_since_event).shift(1).fillna(999.0)

    for col in ("hall_avg_diff", "hall_std_diff", "hall_avg_eff", "hall_event_day"):
        daily[f"{col}_roll_7"] = daily[col].shift(1).rolling(7, min_periods=1).mean().fillna(0.0)
        daily[f"{col}_roll_30"] = daily[col].shift(1).rolling(30, min_periods=1).mean().fillna(0.0)
        daily[f"{col}_trend"] = daily[f"{col}_roll_7"] - daily[f"{col}_roll_30"]

    df = df.merge(
        daily[
            [
                "date",
                "hall_avg_diff_roll_7",
                "hall_std_diff_roll_7",
                "hall_avg_eff_roll_7",
                "hall_event_day_roll_7",
                "hall_avg_diff_trend",
                "hall_avg_eff_trend",
                "hall_event_rate_14",
                "hall_event_rate_30",
                "hall_days_since_event",
            ]
        ],
        on="date",
        how="left",
    )
    df["regime_strength_index"] = (
        efficiency_weight * df["hall_avg_eff_roll_7"]
        + diff_weight * np.tanh(df["hall_avg_diff_roll_7"] / 1000.0)
        + event_weight * df["hall_event_day_roll_7"]
    )

    tail_label = df["entity_key"].astype(str).str.split("|").str[-1]
    tail_digit = pd.to_numeric(tail_label, errors="coerce")
    df["tail_is_even"] = ((tail_digit % 2) == 0).astype(float).fillna(0.0)
    df["tail_low_group"] = (tail_digit <= 4).astype(float).fillna(0.0)
    df["tail_is_zorome"] = (
        tail_label.isin({"11", "ゾロ目", "ｿﾞﾛ目", "ぞろ目"}) | (tail_digit == 11)
    ).astype(float)
    df["weekday"] = pd.to_datetime(df["date"]).dt.weekday.astype(int)
    df["weekday_sin"] = np.sin(2.0 * np.pi * df["weekday"] / 7.0)
    df["weekday_cos"] = np.cos(2.0 * np.pi * df["weekday"] / 7.0)

    df["tail_prior_mean_diff"] = (
        df.groupby("entity_key", sort=False)["total_diff_coins"]
        .transform(lambda s: s.shift(1).expanding(min_periods=1).mean())
        .fillna(0.0)
    )
    df["tail_weekday_prior_mean_diff"] = (
        df.groupby(["entity_key", "weekday"], sort=False)["total_diff_coins"]
        .transform(lambda s: s.shift(1).expanding(min_periods=1).mean())
        .fillna(0.0)
    )
    df["tail_weekday_delta_from_tail_mean"] = df["tail_weekday_prior_mean_diff"] - df["tail_prior_mean_diff"]

    for target in ("is_rank_1", "is_top_2", "is_top_3"):
        if target not in df.columns:
            continue
        target_key = target.removeprefix("is_")
        prior_wins = (
            df.groupby("entity_key", sort=False)[target]
            .transform(lambda s: s.shift(1).cumsum())
            .fillna(0.0)
        )
        prior_samples = (
            df.groupby("entity_key", sort=False)[target]
            .transform(lambda s: s.shift(1).expanding(min_periods=1).count())
            .fillna(0.0)
        )
        prior_rate = (prior_wins + 1.0) / (prior_samples + 2.0)
        df[f"tail_prior_{target_key}_wins"] = prior_wins.astype(float)
        df[f"tail_prior_{target_key}_samples"] = prior_samples.astype(float)
        df[f"tail_prior_{target_key}_win_rate"] = prior_rate.astype(float)
        for threshold_value, threshold_name in ((0.6, "60"), (0.7, "70"), (0.8, "80")):
            flag = (prior_rate >= threshold_value).astype(float)
            confident_flag = ((prior_rate >= threshold_value) & (prior_samples >= 20.0)).astype(float)
            df[f"tail_prior_{target_key}_win_rate_ge_{threshold_name}"] = flag
            df[f"tail_prior_{target_key}_win_rate_ge_{threshold_name}_confident"] = confident_flag

    if "win_rate" in df.columns:
        tail_machine_prior_samples = (
            df.groupby("entity_key", sort=False)["win_rate"]
            .transform(lambda s: s.shift(1).expanding(min_periods=1).count())
            .fillna(0.0)
        )
        tail_machine_prior_mean = (
            df.groupby("entity_key", sort=False)["win_rate"]
            .transform(lambda s: pd.to_numeric(s, errors="coerce").fillna(0.0).shift(1).expanding(min_periods=1).mean())
            .fillna(0.0)
        )
        tail_machine_prior_ewm_7 = (
            df.groupby("entity_key", sort=False)["win_rate"]
            .transform(
                lambda s: pd.to_numeric(s, errors="coerce").fillna(0.0).shift(1).ewm(span=7, adjust=False, min_periods=1).mean()
            )
            .fillna(0.0)
        )
        tail_machine_prior_ewm_21 = (
            df.groupby("entity_key", sort=False)["win_rate"]
            .transform(
                lambda s: pd.to_numeric(s, errors="coerce").fillna(0.0).shift(1).ewm(span=21, adjust=False, min_periods=1).mean()
            )
            .fillna(0.0)
        )
        df["tail_prior_machine_win_rate_samples"] = tail_machine_prior_samples.astype(float)
        df["tail_prior_machine_win_rate_mean"] = tail_machine_prior_mean.astype(float)
        df["tail_prior_machine_win_rate_ewm_7"] = tail_machine_prior_ewm_7.astype(float)
        df["tail_prior_machine_win_rate_ewm_21"] = tail_machine_prior_ewm_21.astype(float)

        for threshold_value, threshold_name in ((0.30, "30"), (0.40, "40"), (0.50, "50")):
            flag = (tail_machine_prior_mean >= threshold_value).astype(float)
            confident_flag = (
                (tail_machine_prior_mean >= threshold_value) & (tail_machine_prior_samples >= 20.0)
            ).astype(float)
            df[f"tail_prior_machine_win_rate_ge_{threshold_name}"] = flag
            df[f"tail_prior_machine_win_rate_ge_{threshold_name}_confident"] = confident_flag

        over_60_flag = (tail_machine_prior_mean >= 0.60).astype(float)
        over_60_confident = ((tail_machine_prior_mean >= 0.60) & (tail_machine_prior_samples >= 20.0)).astype(float)
        df["tail_prior_machine_win_rate_ge_60_over"] = over_60_flag
        df["tail_prior_machine_win_rate_ge_60_over_confident"] = over_60_confident

    return df


def get_numeric_features(df: pd.DataFrame) -> list[str]:
    excluded = set(META_COLUMNS).union(FORECAST_EXCLUDED_COLUMNS).union({"is_top_2"})
    return [c for c in df.columns if c not in excluded and pd.api.types.is_numeric_dtype(df[c])]


def create_date_folds(
    unique_dates: list[pd.Timestamp],
    n_splits: int,
    valid_days: int,
) -> list[tuple[list[pd.Timestamp], list[pd.Timestamp]]]:
    folds: list[tuple[list[pd.Timestamp], list[pd.Timestamp]]] = []
    total = len(unique_dates)
    for i in range(n_splits):
        valid_end = total - (n_splits - 1 - i) * valid_days
        valid_start = max(1, valid_end - valid_days)
        train_dates = unique_dates[:valid_start]
        valid_dates = unique_dates[valid_start:valid_end]
        if train_dates and valid_dates:
            folds.append((train_dates, valid_dates))
    return folds
