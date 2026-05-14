"""Feature engineering pipeline for store-optimized models."""

from __future__ import annotations

import sqlite3
from calendar import monthrange
from contextlib import closing
from math import ceil
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.experiments._pipeline_config import WINDOWS, FoldWindow


class StoreOptimizedFeatureBuilder:
    def build_store_dataset(self, db_path: Path, grouping: str) -> pd.DataFrame:
        store_id = _infer_store_id(db_path)
        with closing(sqlite3.connect(db_path)) as conn:
            df = self._load_grouping_frame(conn, grouping)

        df["store_id"] = store_id
        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
        df = df.sort_values(["entity_key", "date"]).reset_index(drop=True)
        df = self._compute_rank_targets(df)
        df = self._add_common_features(df)
        df = self._add_temporal_group_features(df)
        df = self._add_phase2_features(df, grouping=grouping)
        df = self._add_forecast_safe_binning_and_interactions(df, grouping=grouping)
        df = self._add_value_bins(df)
        df = self._drop_internal_columns(df)
        df = df.sort_values(["date", "entity_key"]).reset_index(drop=True)
        return df

    def build_store_forecast_dataset(self, db_path: Path, grouping: str) -> pd.DataFrame:
        store_id = _infer_store_id(db_path)
        with closing(sqlite3.connect(db_path)) as conn:
            df = self._load_grouping_frame(conn, grouping)

        df["store_id"] = store_id
        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
        df = df.sort_values(["entity_key", "date"]).reset_index(drop=True)
        df = self._compute_rank_targets(df)
        df = self._append_next_day_placeholder_rows(df)
        df = self._add_common_features(df)
        df = self._add_temporal_group_features(df)
        df = self._add_phase2_features(df, grouping=grouping)
        df = self._add_forecast_safe_binning_and_interactions(df, grouping=grouping)
        df = self._add_value_bins(df)
        df = self._drop_internal_columns(df)
        target_date = df["date"].max()
        return df.loc[df["date"] == target_date].sort_values(["date", "entity_key"]).reset_index(drop=True)

    def _load_grouping_frame(self, conn: sqlite3.Connection, grouping: str) -> pd.DataFrame:
        if grouping == "machine_type":
            return self._load_machine_type(conn)
        if grouping == "last_digit":
            return self._load_last_digit(conn)
        if grouping == "machine_number_position":
            return self._load_machine_number_position(conn)
        raise ValueError(f"Unsupported grouping: {grouping}")

    def _load_machine_type(self, conn: sqlite3.Connection) -> pd.DataFrame:
        machine_type_columns = _table_columns(conn, "daily_machine_type_summary")
        has_win_rate = "win_rate" in machine_type_columns
        win_rate_select = ",\n                d.win_rate" if has_win_rate else ""
        df = pd.read_sql_query(
            f"""
            SELECT
                d.date,
                d.machine_name,
                d.machine_count,
                d.total_games,
                d.avg_games,
                d.total_diff_coins,
                d.avg_diff_coins{win_rate_select},
                m.jug_flag,
                m.hana_flag,
                m.oki_flag,
                m.bt_flag
            FROM daily_machine_type_summary d
            LEFT JOIN machine_master m
                ON d.machine_name = m.machine_name_normalized
            ORDER BY d.date, d.machine_name
            """,
            conn,
        )
        if df.empty:
            raise ValueError("daily_machine_type_summary returned no rows")

        df["entity_key"] = df["machine_name"].astype(str)
        df["machine_type"] = df.apply(_derive_machine_family, axis=1)
        if "win_rate" not in df.columns:
            df["win_rate"] = 0.0
        df["efficiency"] = (df["total_diff_coins"] / df["total_games"].replace(0, np.nan)).fillna(0.0)
        return df[
            [
                "date",
                "entity_key",
                "machine_name",
                "machine_type",
                "machine_count",
                "total_games",
                "avg_games",
                "total_diff_coins",
                "avg_diff_coins",
                "win_rate",
                "efficiency",
            ]
        ]

    def _load_last_digit(self, conn: sqlite3.Connection) -> pd.DataFrame:
        df = pd.read_sql_query(
            """
            SELECT
                date,
                last_digit,
                machine_count,
                total_games,
                avg_games,
                total_diff_coins,
                avg_diff_coins,
                win_rate,
                high_profit_rate
            FROM last_digit_summary_all
            ORDER BY date, last_digit
            """,
            conn,
        )
        if df.empty:
            raise ValueError("last_digit_summary_all returned no rows")

        df["entity_key"] = df["last_digit"].astype(str)
        df["efficiency"] = (df["total_diff_coins"] / df["total_games"].replace(0, np.nan)).fillna(0.0)
        return df[
            [
                "date",
                "entity_key",
                "last_digit",
                "machine_count",
                "total_games",
                "avg_games",
                "total_diff_coins",
                "avg_diff_coins",
                "win_rate",
                "high_profit_rate",
                "efficiency",
            ]
        ]

    def _load_machine_number_position(self, conn: sqlite3.Connection) -> pd.DataFrame:
        df = pd.read_sql_query(
            """
            SELECT
                date,
                machine_number,
                machine_name,
                last_digit,
                is_zorome,
                games_normalized,
                diff_coins_normalized
            FROM machine_detailed_results
            ORDER BY date, machine_number
            """,
            conn,
        )
        if df.empty:
            raise ValueError("machine_detailed_results returned no rows")

        unique_numbers = np.sort(df["machine_number"].unique())
        position_map = {number: idx for idx, number in enumerate(unique_numbers)}
        max_index = max(len(unique_numbers) - 1, 1)

        df["entity_key"] = df["machine_number"].astype(str)
        df["position_index"] = df["machine_number"].map(position_map).astype(float)
        df["position_percentile"] = df["position_index"] / max_index
        df["top10_flag"] = (df["position_index"] < 10).astype(int)
        df["top30_flag"] = (df["position_index"] < 30).astype(int)
        df["top100_flag"] = (df["position_index"] < 100).astype(int)
        df["edge_flag"] = ((df["position_percentile"] <= 0.10) | (df["position_percentile"] >= 0.90)).astype(int)
        df["center_flag"] = df["position_percentile"].between(0.40, 0.60).astype(int)
        df["machine_count"] = 1
        df["total_games"] = df["games_normalized"]
        df["avg_games"] = df["games_normalized"].astype(float)
        df["total_diff_coins"] = df["diff_coins_normalized"]
        df["avg_diff_coins"] = df["diff_coins_normalized"].astype(float)
        df["efficiency"] = (df["total_diff_coins"] / df["total_games"].replace(0, np.nan)).fillna(0.0)
        return df[
            [
                "date",
                "entity_key",
                "machine_name",
                "last_digit",
                "is_zorome",
                "machine_count",
                "total_games",
                "avg_games",
                "total_diff_coins",
                "avg_diff_coins",
                "efficiency",
                "top10_flag",
                "top30_flag",
                "top100_flag",
                "position_percentile",
                "edge_flag",
                "center_flag",
            ]
        ]

    def _compute_rank_targets(self, df: pd.DataFrame) -> pd.DataFrame:
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

    def _add_common_features(self, df: pd.DataFrame) -> pd.DataFrame:
        enriched = df.copy()
        enriched["day_of_week"] = enriched["date"].dt.dayofweek
        enriched["day_of_month"] = enriched["date"].dt.day
        enriched["month_progress"] = (enriched["day_of_month"] - 1) / enriched["date"].dt.daysinmonth
        enriched["is_month_end_event"] = (
            enriched["day_of_month"] == enriched["date"].dt.daysinmonth
        ).astype(int)
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
        enriched["days_since_last_event_any"] = enriched["date"].map(
            lambda current_date: event_features[current_date]["days_since_last_event_any"]
        )
        enriched["days_to_next_event_any"] = enriched["date"].map(
            lambda current_date: event_features[current_date]["days_to_next_event_any"]
        )
        enriched["is_event_week"] = enriched["date"].map(
            lambda current_date: event_features[current_date]["is_event_week"]
        )
        enriched["event_signed_distance_any"] = (
            enriched["days_since_last_event_any"] - enriched["days_to_next_event_any"]
        )
        enriched["event_distance_abs_any"] = np.minimum(
            enriched["days_since_last_event_any"],
            enriched["days_to_next_event_any"],
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

    def _add_temporal_group_features(self, df: pd.DataFrame) -> pd.DataFrame:
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

        groups = []
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
            group["same_day_of_month_rank1_gap"] = (
                group["same_day_of_month_rank1_rate"] - group["prior_rank1_rate"]
            )

            for _, weekday_group in group.groupby("day_of_week", sort=False):
                weekday_index = weekday_group.index
                group.loc[weekday_index, "days_since_last_rank1_same_weekday"] = _days_since_last_positive(
                    weekday_group["date"],
                    weekday_group["is_rank_1"],
                )
            for _, month_day_group in group.groupby("day_of_month", sort=False):
                month_day_index = month_day_group.index
                group.loc[month_day_index, "days_since_last_rank1_same_day_of_month"] = _days_since_last_positive(
                    month_day_group["date"],
                    month_day_group["is_rank_1"],
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

    def _add_value_bins(self, df: pd.DataFrame) -> pd.DataFrame:
        enriched = df.copy()
        for column in ("total_games", "avg_games", "total_diff_coins", "avg_diff_coins", "efficiency"):
            enriched[f"{column}_bin"] = _quantile_bin(enriched[column])
        return enriched

    def _append_next_day_placeholder_rows(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df

        next_date = pd.Timestamp(df["date"].max()) + pd.Timedelta(days=1)
        placeholder_rows: list[dict[str, Any]] = []
        reset_columns = [
            "total_games",
            "avg_games",
            "total_diff_coins",
            "avg_diff_coins",
            "win_rate",
            "high_profit_rate",
            "efficiency",
            "is_rank_1",
            "is_top_3",
            "is_top_5",
            "_tmp_best_rank",
            "_tmp_worst_rank",
            "_tmp_is_worst1",
            "_tmp_is_worst3",
            "_tmp_is_worst5",
        ]

        for _, group in df.groupby("entity_key", sort=False):
            row = group.sort_values("date").iloc[-1].to_dict()
            row["date"] = next_date
            for column in reset_columns:
                if column in row:
                    row[column] = 0.0
            placeholder_rows.append(row)

        placeholder_df = pd.DataFrame(placeholder_rows)
        combined = pd.concat([df, placeholder_df], ignore_index=True, sort=False)
        return combined.sort_values(["entity_key", "date"]).reset_index(drop=True)

    def _add_forecast_safe_binning_and_interactions(self, df: pd.DataFrame, grouping: str) -> pd.DataFrame:
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
            "dow_machine_name_rank1_rate",
        ):
            if column in enriched.columns:
                enriched[f"{column}_level_bin"] = _fixed_cut_bin(
                    enriched[column],
                    bins=[-0.001, 0.0, 0.02, 0.05, 0.10, 0.20, 0.35, 0.50, 1.0],
                )

        if {"lag_1_diff", "rolling_avg_diff_7d"} <= set(enriched.columns):
            enriched["lag_1_diff_minus_rolling_avg_diff_7d"] = (
                enriched["lag_1_diff"] - enriched["rolling_avg_diff_7d"]
            )
            enriched["lag_1_diff_to_rolling_avg_diff_7d_ratio"] = _safe_ratio(
                enriched["lag_1_diff"],
                enriched["rolling_avg_diff_7d"],
            )

        if {"lag_1_diff", "rolling_avg_diff_14d"} <= set(enriched.columns):
            enriched["lag_1_diff_minus_rolling_avg_diff_14d"] = (
                enriched["lag_1_diff"] - enriched["rolling_avg_diff_14d"]
            )

        if {"lag_1_games", "rolling_avg_games_7d"} <= set(enriched.columns):
            enriched["lag_1_games_minus_rolling_avg_games_7d"] = (
                enriched["lag_1_games"] - enriched["rolling_avg_games_7d"]
            )
            enriched["lag_1_games_to_rolling_avg_games_7d_ratio"] = _safe_ratio(
                enriched["lag_1_games"],
                enriched["rolling_avg_games_7d"],
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
                enriched["days_since_last_rank1_same_weekday"]
                - enriched["days_since_last_rank1_same_day_of_month"]
            )

        return enriched

    def _add_phase2_features(self, df: pd.DataFrame, grouping: str) -> pd.DataFrame:
        enriched = df.copy()

        for column in ("prior_worst1_rate", "prior_worst3_rate", "prior_worst5_rate"):
            enriched[column] = 0.0

        if grouping == "last_digit":
            for column in (
                "dow_lastdigit_rank1_rate",
                "same_weekday_rolling_rank_sum_3",
                "weekday_digit_bias",
                "anti_pattern_rank1_rate",
                "weekday_non_consecutive_rank1_rate",
                "consecutive_suppression_score",
            ):
                enriched[column] = 0.0

        if "machine_name" in enriched.columns:
            enriched["dow_machine_name_rank1_rate"] = 0.0

        groups = []
        for _, group in enriched.groupby("entity_key", sort=False):
            group = group.sort_values("date").copy()

            group["prior_worst1_rate"] = group["_tmp_is_worst1"].shift(1).expanding(min_periods=1).mean().fillna(0.0)
            group["prior_worst3_rate"] = group["_tmp_is_worst3"].shift(1).expanding(min_periods=1).mean().fillna(0.0)
            group["prior_worst5_rate"] = group["_tmp_is_worst5"].shift(1).expanding(min_periods=1).mean().fillna(0.0)

            if grouping == "last_digit":
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

                weekday_prior_sum = (
                    group.groupby("day_of_week", sort=False)["_tmp_best_rank"].cumsum() - group["_tmp_best_rank"]
                )
                weekday_prior_count = group.groupby("day_of_week", sort=False).cumcount()
                weekday_prior_mean = np.divide(
                    weekday_prior_sum,
                    weekday_prior_count,
                    out=np.zeros(len(group), dtype=float),
                    where=weekday_prior_count.to_numpy() > 0,
                )
                group["weekday_digit_bias"] = np.where(
                    (overall_prior_count.to_numpy() > 0) & (weekday_prior_count.to_numpy() > 0),
                    weekday_prior_mean - overall_prior_mean,
                    0.0,
                )

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
                    pd.Series(eligible_non_consecutive, index=group.index)
                    .groupby(group["day_of_week"], sort=False)
                    .cumsum()
                    - eligible_non_consecutive
                )
                prior_weekday_non_consecutive_success = (
                    pd.Series(success_non_consecutive, index=group.index)
                    .groupby(group["day_of_week"], sort=False)
                    .cumsum()
                    - success_non_consecutive
                )
                group["weekday_non_consecutive_rank1_rate"] = np.where(
                    (is_prev_rank1.to_numpy() == 0) & (prior_weekday_non_consecutive_count.to_numpy() > 0),
                    prior_weekday_non_consecutive_success / prior_weekday_non_consecutive_count,
                    0.0,
                )

                group["consecutive_suppression_score"] = _consecutive_suppression_score(group["is_rank_1"])

            groups.append(group)

        enriched = pd.concat(groups, ignore_index=True)

        if grouping == "last_digit":
            enriched["dow_lastdigit_rank1_rate"] = (
                enriched.groupby(["last_digit", "day_of_week"], sort=False)["is_rank_1"]
                .transform(_prior_mean_transform)
                .fillna(0.0)
            )

        if "machine_name" in enriched.columns:
            enriched["dow_machine_name_rank1_rate"] = (
                enriched.groupby(["machine_name", "day_of_week"], sort=False)["is_rank_1"]
                .transform(_prior_mean_transform)
                .fillna(0.0)
            )

        return enriched

    def _drop_internal_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.drop(
            columns=[
                column
                for column in (
                    "_tmp_best_rank",
                    "_tmp_worst_rank",
                    "_tmp_is_worst1",
                    "_tmp_is_worst3",
                    "_tmp_is_worst5",
                )
                if column in df.columns
            ]
        )



def _infer_store_id(db_path: Path) -> str:
    stem = Path(db_path).stem
    return stem if stem.endswith("_exp") else f"{stem}_exp"


def _derive_machine_family(row: pd.Series) -> str:
    if row.get("jug_flag") == 1:
        return "jug"
    if row.get("hana_flag") == 1:
        return "hana"
    if row.get("oki_flag") == 1:
        return "oki"
    if row.get("bt_flag") == 1:
        return "bt"
    return "other"


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


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row[1]) for row in rows}


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


def _quantile_bin(series: pd.Series, n_bins: int = 5) -> pd.Series:
    if series.empty:
        return pd.Series(dtype=int)
    ranked = series.fillna(series.median() if not series.dropna().empty else 0.0).rank(method="first")
    return pd.qcut(ranked, q=n_bins, labels=False, duplicates="drop").astype(int)


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


def _categorical_columns_for_grouping(grouping: str, merge_mode: str) -> list[str]:
    columns = ["entity_key"]
    if merge_mode == "pooled_store_aware":
        columns.append("store_id")
    if grouping == "machine_type":
        columns.extend(["machine_name", "machine_type"])
    elif grouping == "last_digit":
        columns.append("last_digit")
    elif grouping == "machine_number_position":
        columns.extend(["machine_name", "last_digit", "is_zorome"])
    return columns


def _numeric_feature_columns(df: pd.DataFrame, categorical_columns: list[str]) -> list[str]:
    excluded = META_COLUMNS.union(categorical_columns)
    return [
        column
        for column in df.columns
        if column not in excluded and pd.api.types.is_numeric_dtype(df[column])
    ]


def _format_html_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6f}"
    if value is None:
        return "-"
    return str(value)


def _build_feature_catalog_payload(*, store_id: str, grouping: str, dataset: pd.DataFrame) -> dict[str, Any]:
    entries = []
    for column in dataset.columns:
        section = _feature_catalog_section(column)
        entries.append(
            {
                "name": column,
                "section": section,
                "description": _feature_description(column, grouping=grouping),
                "dtype": str(dataset[column].dtype),
            }
        )

    section_counts = {
        section: sum(1 for entry in entries if entry["section"] == section)
        for section in FEATURE_CATALOG_SECTION_ORDER
        if any(entry["section"] == section for entry in entries)
    }
    payload = {
        "store_id": store_id,
        "grouping": grouping,
        "generated_automatically": True,
        "feature_count": len(entries),
        "section_counts": section_counts,
        "entries": entries,
    }
    if grouping == "machine_number_position":
        payload["planned_entries"] = [
            {"name": name, "description": description}
            for name, description in PLANNED_MACHINE_NUMBER_FEATURES
        ]
    return payload


def _render_feature_catalog_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Feature Catalog",
        "",
        f"- Store: `{payload['store_id']}`",
        f"- Grouping: `{payload['grouping']}`",
        f"- Feature Count: `{payload['feature_count']}`",
        "- 自動生成: `true`",
        "",
        "実際に生成されたデータセット列から自動生成した特徴量一覧です。",
        "",
    ]

    entries = payload["entries"]
    for section in FEATURE_CATALOG_SECTION_ORDER:
        section_entries = [entry for entry in entries if entry["section"] == section]
        if not section_entries:
            continue
        lines.append(f"## {_feature_catalog_section_title(section)}")
        lines.append("")
        for entry in section_entries:
            lines.append(f"- `{entry['name']}`: {entry['description']} dtype=`{entry['dtype']}`")
        lines.append("")

    planned_entries = payload.get("planned_entries") or []
    if planned_entries:
        lines.append("## Machine Number Position Planned")
        lines.append("")
        for entry in planned_entries:
            lines.append(f"- `{entry['name']}`: {entry['description']}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_overview_feature_catalog_markdown(overview: dict[str, Any]) -> str:
    lines = [
        "# Store Optimized Pipeline Feature Catalog",
        "",
        "- 自動生成: `true`",
        "",
        "各 grouping で実際に生成された列を集約した特徴量一覧です。",
        "",
    ]
    seen_groupings: set[str] = set()
    for store in overview.get("stores", []):
        for grouping_summary in store.get("groupings", []):
            grouping = grouping_summary.get("grouping")
            feature_catalog = grouping_summary.get("feature_catalog")
            if not grouping or not feature_catalog or grouping in seen_groupings:
                continue
            seen_groupings.add(grouping)
            lines.append(f"## Grouping: {grouping}")
            lines.append("")
            lines.append(
                f"- Store Example: `{feature_catalog.get('store_id', grouping_summary.get('store_id', '-'))}`"
            )
            lines.append(f"- Feature Count: `{feature_catalog.get('feature_count', 0)}`")
            lines.append("")
            for entry in feature_catalog.get("entries", []):
                lines.append(f"- `{entry['name']}`: {entry['description']}")
            planned_entries = feature_catalog.get("planned_entries") or []
            if planned_entries:
                lines.append("")
                lines.append("### Planned")
                lines.append("")
                for entry in planned_entries:
                    lines.append(f"- `{entry['name']}`: {entry['description']}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _build_feature_importance_payload(summary_payload: dict[str, Any]) -> dict[str, Any]:
    run_entries = []
    for run in summary_payload.get("runs", []):
        selection = run.get("feature_selection") or {}
        if not selection:
            continue
        run_entries.append(
            {
                "target": run.get("target"),
                "model": run.get("model"),
                "merge_mode": run.get("merge_mode"),
                "cv_mode": run.get("cv_mode"),
                "selection_metric": run.get("selection_metric"),
                "selection_score": run.get("selection_score"),
                "mean_hit_at_1": run.get("mean_hit_at_1"),
                "mean_hit_at_3": run.get("mean_hit_at_3"),
                "mean_threshold_optimized_precision": run.get("mean_threshold_optimized_precision"),
                "mean_threshold_optimized_recall": run.get("mean_threshold_optimized_recall"),
                "mean_threshold_optimized_f1": run.get("mean_threshold_optimized_f1"),
                "mean_base_rate": run.get("mean_base_rate"),
                "mean_precision_lift_at_0_5": run.get("mean_precision_lift_at_0_5"),
                "mean_optimized_precision_lift": run.get("mean_optimized_precision_lift"),
                "mean_auc": run.get("mean_auc"),
                "mean_pr_auc": run.get("mean_pr_auc"),
                "mean_zero_recall_penalty": run.get("mean_zero_recall_penalty"),
                "mean_lift_penalty": run.get("mean_lift_penalty"),
                "mean_objective_score": run.get("mean_objective_score"),
                "selector_model": selection.get("selector_model"),
                "selector_strategy": selection.get("selector_strategy"),
                "stable_features": selection.get("stable_features", []),
                "consensus_features": selection.get("consensus_features", []),
                "selected_features": selection.get("selected_features", []),
                "top_features": selection.get("top_features", []),
                "top_features_by_permutation": selection.get("top_features_by_permutation", []),
            }
        )
    return {
        "store_id": summary_payload.get("store_id"),
        "grouping": summary_payload.get("grouping"),
        "runs": run_entries,
    }


def _render_feature_importance_markdown(
    *,
    store_id: str,
    grouping: str,
    feature_importance_payload: dict[str, Any],
) -> str:
    lines = [
        "# Feature Importance Report",
        "",
        f"- Store: `{store_id}`",
        f"- Grouping: `{grouping}`",
        "",
    ]
    for run in feature_importance_payload.get("runs", []):
        lines.append(
            "## "
            + f"{run['target']} / {run['model']} / {run['merge_mode']} / {run['cv_mode']}"
        )
        lines.append("")
        lines.append(f"- Selection Metric: `{run.get('selection_metric')}`")
        lines.append(f"- Selection Score: `{_format_html_value(run.get('selection_score'))}`")
        lines.append(f"- Mean Hit@1: `{_format_html_value(run.get('mean_hit_at_1'))}`")
        lines.append(f"- Mean Hit@3: `{_format_html_value(run.get('mean_hit_at_3'))}`")
        lines.append(f"- Mean Opt F1: `{_format_html_value(run.get('mean_threshold_optimized_f1'))}`")
        lines.append(f"- Mean Opt Recall: `{_format_html_value(run.get('mean_threshold_optimized_recall'))}`")
        lines.append(f"- Mean Opt Precision: `{_format_html_value(run.get('mean_threshold_optimized_precision'))}`")
        lines.append(f"- Mean Base Rate: `{_format_html_value(run.get('mean_base_rate'))}`")
        lines.append(f"- Mean Lift@0.5: `{_format_html_value(run.get('mean_precision_lift_at_0_5'))}`")
        lines.append(f"- Mean Opt Lift: `{_format_html_value(run.get('mean_optimized_precision_lift'))}`")
        lines.append(f"- Mean Objective Score: `{_format_html_value(run.get('mean_objective_score'))}`")
        lines.append(f"- Mean AUC: `{_format_html_value(run.get('mean_auc'))}`")
        lines.append(f"- Mean PR-AUC: `{_format_html_value(run.get('mean_pr_auc'))}`")
        lines.append(f"- Mean Zero Recall Penalty: `{_format_html_value(run.get('mean_zero_recall_penalty'))}`")
        lines.append(f"- Mean Lift Penalty: `{_format_html_value(run.get('mean_lift_penalty'))}`")
        lines.append(f"- Selector: `{run.get('selector_model')}`")
        lines.append(f"- Strategy: `{run.get('selector_strategy')}`")
        lines.append("")
        lines.append("### Stable Features")
        lines.append("")
        stable = run.get("stable_features") or run.get("selected_features") or []
        for feature in stable[:20]:
            lines.append(f"- `{feature}`")
        if not stable:
            lines.append("- None")
        lines.append("")
        lines.append("### Permutation Importance")
        lines.append("")
        for item in (run.get("top_features_by_permutation") or [])[:15]:
            lines.append(
                f"- `{item['feature']}`: permutation=`{item['mean_permutation_importance']:.6f}` model=`{item['mean_model_importance']:.6f}` selected_in_folds=`{item['selected_in_folds']}`"
            )
        if not run.get("top_features_by_permutation"):
            lines.append("- None")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _flatten_forecast_rows(forecast_payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for prediction in forecast_payload.get("predictions", []):
        for item in prediction.get("rows", []):
            row = {
                "store_id": forecast_payload.get("store_id"),
                "grouping": forecast_payload.get("grouping"),
                "source_latest_date": forecast_payload.get("source_latest_date"),
                "target_date": forecast_payload.get("target_date"),
                "target": prediction.get("target"),
                "model": prediction.get("model"),
                "merge_mode": prediction.get("merge_mode"),
                "cv_mode": prediction.get("cv_mode"),
                "selection_metric": prediction.get("selection_metric"),
                "selection_score": prediction.get("selection_score"),
                "mean_hit_at_1": prediction.get("mean_hit_at_1"),
                "mean_hit_at_3": prediction.get("mean_hit_at_3"),
                "mean_threshold_optimized_precision": prediction.get("mean_threshold_optimized_precision"),
                "mean_threshold_optimized_recall": prediction.get("mean_threshold_optimized_recall"),
                "mean_threshold_optimized_f1": prediction.get("mean_threshold_optimized_f1"),
                "mean_base_rate": prediction.get("mean_base_rate"),
                "mean_precision_lift_at_0_5": prediction.get("mean_precision_lift_at_0_5"),
                "mean_optimized_precision_lift": prediction.get("mean_optimized_precision_lift"),
                "mean_auc": prediction.get("mean_auc"),
                "mean_pr_auc": prediction.get("mean_pr_auc"),
                "mean_lift_penalty": prediction.get("mean_lift_penalty"),
                "mean_objective_score": prediction.get("mean_objective_score"),
            }
            row.update(item)
            rows.append(row)
    return rows


def _feature_catalog_section(column: str) -> str:
    if column in {"store_id", "entity_key", "date"}:
        return "meta"
    if column in TARGET_COLUMNS:
        return "target"
    if column in {"machine_name", "machine_type", "last_digit", "is_zorome"}:
        return "categorical"
    if column.startswith("event_") or column in {
        "is_event_day",
        "is_month_end_event",
        "days_since_last_event_any",
        "days_to_next_event_any",
        "is_event_week",
    }:
        return "event"
    if column.startswith("same_weekday_"):
        return "same_weekday"
    if column.startswith("same_day_of_month_"):
        return "same_day_of_month"
    if column.endswith("_bin"):
        return "binning"
    if "_x_" in column or "_minus_" in column or column.endswith("_ratio") or column.endswith("_gap"):
        return "interaction"
    if "anti_pattern" in column or "suppression" in column or "weekday_digit_bias" == column:
        return "anti_pattern"
    if (
        column.startswith("prior_worst")
        or column.startswith("prior_top")
        or column.endswith("_rank1_rate")
        or column == "same_weekday_top3_rate"
        or "rolling_rank_sum" in column
    ):
        return "anti_pattern"
    if column.startswith("rolling_"):
        return "rolling"
    if column.startswith("lag_") or column in {"days_since_last_rank1", "days_since_last_top3", "days_since_last_top5"}:
        return "lag"
    if column in {"day_of_week", "day_of_month", "month_progress"}:
        return "calendar"
    return "other"


def _feature_catalog_section_title(section: str) -> str:
    titles = {
        "meta": "Meta",
        "target": "Targets",
        "categorical": "Grouping Keys",
        "calendar": "Calendar",
        "event": "Event",
        "lag": "Lag",
        "rolling": "Rolling",
        "same_weekday": "Same Weekday",
        "same_day_of_month": "Same Day Of Month",
        "anti_pattern": "Anti Pattern",
        "binning": "Binning",
        "interaction": "Interaction",
        "other": "Other",
    }
    return titles.get(section, section.title())


def _feature_description(column: str, *, grouping: str) -> str:
    explicit = {
        "store_id": "店舗識別子。",
        "entity_key": "grouping ごとの学習単位キー。",
        "date": "営業日。",
        "is_rank_1": "当日の差枚順位が 1 位かどうか。",
        "is_top_3": "当日の差枚順位が 3 位以内かどうか。",
        "is_top_5": "当日の差枚順位が 5 位以内かどうか。",
        "machine_name": "機種名。",
        "machine_type": "機種ファミリー分類。",
        "last_digit": "末尾番号。",
        "is_zorome": "ゾロ目台かどうか。",
        "machine_count": "集計対象の台数。",
        "total_games": "総ゲーム数。",
        "avg_games": "平均ゲーム数。",
        "total_diff_coins": "総差枚。",
        "avg_diff_coins": "平均差枚。",
        "win_rate": "勝率。",
        "high_profit_rate": "高差枚率。",
        "efficiency": "差枚をゲーム数で割った効率指標。",
        "day_of_week": "曜日。",
        "day_of_month": "月内の日付。",
        "month_progress": "月初から月末までの進み具合。",
        "is_month_end_event": "月末イベント日かどうか。",
        "event_group": "イベント群。1 は 1/11/21、2 は 7/17/27、3 は月末。",
        "is_event_day": "イベント日かどうか。",
        "days_since_last_event_any": "直近イベントからの経過日数。",
        "days_to_next_event_any": "次イベントまでの日数。",
        "is_event_week": "イベント前後 3 日圏内かどうか。",
        "event_proximity_score": "次イベントが近いほど大きいスコア。",
        "days_since_last_rank1": "直近 Rank1 からの経過日数。",
        "top10_flag": "位置 index が上位 10 台以内か。",
        "top30_flag": "位置 index が上位 30 台以内か。",
        "top100_flag": "位置 index が上位 100 台以内か。",
        "position_percentile": "並び順の相対位置。",
        "edge_flag": "端寄りかどうか。",
        "center_flag": "中央寄りかどうか。",
        "dow_lastdigit_rank1_rate": "同じ末尾番号と同じ曜日における過去 Rank1 率。",
        "dow_machine_name_rank1_rate": "同じ機種名と同じ曜日における過去 Rank1 率。",
        "same_weekday_rolling_rank_sum_3": "同じ曜日の直近 3 回分の順位合計。",
        "weekday_digit_bias": "同曜日平均順位と全曜日平均順位の差。",
        "anti_pattern_rank1_rate": "前回 Rank1 ではなかった回に限定した過去 Rank1 率。",
        "weekday_non_consecutive_rank1_rate": "同曜日かつ前回 Rank1 ではない回に限定した過去 Rank1 率。",
        "consecutive_suppression_score": "3 連続 Rank1 が期待値より抑制されている度合い。",
        "prior_worst1_rate": "過去に Worst1 だった割合。",
        "prior_worst3_rate": "過去に Worst3 だった割合。",
        "prior_worst5_rate": "過去に Worst5 だった割合。",
    }
    if column in explicit:
        return explicit[column]
    if column == "days_since_last_top3":
        return "直近 Top3 からの経過日数。"
    if column == "days_since_last_top5":
        return "直近 Top5 からの経過日数。"
    if column == "prior_top3_rate":
        return "過去に Top3 だった割合。"
    if column == "prior_top5_rate":
        return "過去に Top5 だった割合。"
    if column == "same_weekday_top3_rate":
        return "同曜日における過去 Top3 率。"
    if column == "same_day_of_month_top3_gap":
        return "同日DD Top3 率と全期間 Top3 率の差。"
    if column.startswith("lag_"):
        _, lag, metric = column.split("_", 2)
        metric_label = "差枚" if metric == "diff" else "ゲーム数" if metric == "games" else metric
        return f"{lag} 回前の {metric_label}。"
    if column.startswith("rolling_avg_"):
        _, _, metric, window = column.split("_", 3)
        metric_label = "差枚" if metric == "diff" else "ゲーム数" if metric == "games" else "効率" if metric == "efficiency" else metric
        return f"直近 {window} の {metric_label} 移動平均。"
    if column.startswith("same_weekday_lag_"):
        _, _, _, lag, metric = column.split("_", 4)
        return f"同じ曜日で {lag} 回前の {metric}。"
    if column.startswith("same_weekday_rolling_avg_"):
        suffix = column.removeprefix("same_weekday_rolling_avg_")
        metric, window = suffix.rsplit("_", 1)
        return f"同じ曜日の直近 {window} 回における {metric} の平均。"
    if column.startswith("same_day_of_month_lag_"):
        suffix = column.removeprefix("same_day_of_month_lag_")
        lag, metric = suffix.split("_", 1)
        return f"同じ日付 DD で {lag} 回前の {metric}。"
    if column.startswith("same_day_of_month_rolling_avg_"):
        suffix = column.removeprefix("same_day_of_month_rolling_avg_")
        metric, window = suffix.rsplit("_", 1)
        return f"同じ日付 DD の直近 {window} 回における {metric} の平均。"
    if "_minus_" in column:
        return "過去特徴同士の差分。"
    if column.endswith("_ratio"):
        return "過去特徴同士の比率。"
    if column.endswith("_gap"):
        return "過去特徴同士のギャップ。"
    if "_x_" in column:
        return "過去特徴同士の交互作用。"
    if column.endswith("_bin"):
        base = column.removesuffix("_bin")
        return f"{base} を離散化した bin 特徴。"
    return f"`{grouping}` データセットから自動検出した特徴量。"


def _extract_named_importances(model: Any, feature_columns: list[str]) -> dict[str, float]:
    importances = getattr(model, "feature_importances_", None)
    if importances is None:
        importances = np.ones(len(feature_columns), dtype=float)
    return {
        feature: float(importance)
        for feature, importance in zip(feature_columns, importances, strict=False)
    }
