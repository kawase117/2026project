from __future__ import annotations

import copy
import json
import logging
import pickle
import sqlite3
import warnings
from calendar import monthrange
from contextlib import closing
from math import ceil
from dataclasses import asdict, dataclass, field
from html import escape
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import optuna
import pandas as pd
from catboost import CatBoostClassifier
from lightgbm import LGBMClassifier
from sklearn.feature_selection import RFECV
from sklearn.inspection import permutation_importance
from sklearn.model_selection import StratifiedKFold
from xgboost import XGBClassifier

from ml.evaluators.metrics import calculate_hit_at_k, evaluate_model
from ml.experiments.result_format import render_html_page, write_json, write_text


logger = logging.getLogger(__name__)

WINDOWS = (7, 14, 28)
TARGET_COLUMNS = ("is_rank_1", "is_top_3", "is_top_5")
META_COLUMNS = {"store_id", "entity_key", "date", *TARGET_COLUMNS}
FORECAST_EXCLUDED_COLUMNS = {
    "total_games",
    "avg_games",
    "total_diff_coins",
    "avg_diff_coins",
    "win_rate",
    "high_profit_rate",
    "efficiency",
    "total_games_bin",
    "avg_games_bin",
    "total_diff_coins_bin",
    "avg_diff_coins_bin",
    "efficiency_bin",
}
ABLATION_WORST_FEATURE_KEYWORDS = (
    "worst",
)
ABLATION_WORST_RECENCY_PREFIXES = (
    "days_since_last_worst",
)
ABLATION_WORST_STREAK_PREFIXES = (
    "worst1_streak",
    "worst3_streak",
    "worst5_streak",
)
ABLATION_WORST_RATE_KEYWORDS = (
    "worst",
    "after_event",
    "same_weekday_worst",
    "same_day_of_month_worst",
    "prior_worst",
)
ABLATION_MOMVOL_FEATURE_PREFIXES = (
    "rolling_std_",
    "ewm_",
    "diff_zscore_",
)
ABLATION_SAME_DAY_OF_MONTH_PREFIXES = (
    "same_day_of_month_",
)
ABLATION_SAME_WEEKDAY_PREFIXES = (
    "same_weekday_",
)
ABLATION_RANK1_SPECIAL_PREFIXES = (
    "prior_rank1_rate",
    "same_weekday_rank1_rate",
    "same_day_of_month_rank1_rate",
    "same_weekday_rank1_gap",
    "same_day_of_month_rank1_gap",
    "days_since_last_rank1_same_weekday",
    "days_since_last_rank1_same_day_of_month",
    "rank1_streak_prev",
    "rank1_rebound_score",
    "rank1_streak_x_event_decay_3",
    "rank1_rotation_context_gap",
    "rank1_same_cycle_recency_gap",
)
ABLATION_EVENT_DISTANCE_REDESIGN_COLUMNS = (
    "event_signed_distance_any",
    "event_distance_abs_any",
    "event_distance_decay_3",
    "event_distance_decay_7",
    "event_phase_after_event",
    "event_phase_before_event",
)
ABLATION_EVENT_FEATURE_COLUMNS = (
    "is_event_day",
    "is_event_week",
    "is_month_end_event",
    "event_group",
    "days_since_last_event_any",
    "days_to_next_event_any",
    "event_signed_distance_any",
    "event_distance_abs_any",
    "event_distance_decay_3",
    "event_distance_decay_7",
    "event_phase_after_event",
    "event_phase_before_event",
    "event_proximity_score",
)
FEATURE_CATALOG_SECTION_ORDER = (
    "meta",
    "target",
    "categorical",
    "calendar",
    "event",
    "lag",
    "rolling",
    "same_weekday",
    "same_day_of_month",
    "anti_pattern",
    "binning",
    "interaction",
    "other",
)
PLANNED_MACHINE_NUMBER_FEATURES = [
    ("corner_distance", "角台からの距離。"),
    ("corner_flag", "角台かどうか。"),
    ("block_id", "島やブロックの識別子。"),
    ("zone_id", "店内ゾーン識別子。"),
    ("adjacent_high_signal_count", "隣接台の強い履歴シグナル数。"),
    ("left_right_edge_type", "左端・右端・中央などの位置タイプ。"),
    ("same_last_digit_position_bias", "末尾番号と位置の組み合わせ癖。"),
    ("position_weekday_bias", "位置と曜日の相互作用による偏り。"),
    ("machine_number_non_consecutive_rate", "台番号単位の非連続 Rank1 率。"),
    ("prior_worst_streak_length", "低調履歴の連続長。"),
    ("local_cluster_rank_rate", "近傍クラスター単位の Rank 発生率。"),
]


@dataclass(slots=True)
class PipelineConfig:
    db_paths: list[Path]
    groupings: list[str] = field(
        default_factory=lambda: ["machine_type", "last_digit", "machine_number_position"]
    )
    targets: list[str] = field(default_factory=lambda: list(TARGET_COLUMNS))
    base_cv: str = "expanding"
    compare_cv: list[str] = field(default_factory=lambda: ["sliding"])
    models: list[str] = field(default_factory=lambda: ["lgbm", "xgb", "catboost"])
    merge_modes: list[str] = field(default_factory=lambda: ["single_store"])
    optuna_enabled: bool = False
    optuna_trials: int = 10
    optuna_top_k_models: int = 1
    lift_penalty_weight: float = 0.25
    lift_floor_rank1: float = 1.0
    lift_floor_top3: float = 1.10
    lift_floor_top5: float = 1.05
    n_splits: int = 5
    train_window_size: int | None = None
    valid_window_size: int | None = None
    random_state: int = 42
    feature_selection_enabled: bool = True
    feature_selection_selector_model: str = "lgbm"
    feature_selection_strategy: str = "rfecv_boruta"
    feature_selection_top_k: int | None = None
    feature_selection_min_features: int = 6
    feature_selection_keep_ratio: float = 0.6
    feature_selection_rfecv_cv_splits: int = 3
    feature_selection_permutation_repeats: int = 3
    feature_selection_shadow_quantile: float = 1.0
    forecast_mode: bool = False
    feature_ablation_mode: str = "none"

    def __post_init__(self) -> None:
        self.db_paths = [Path(path) for path in self.db_paths]


@dataclass(slots=True)
class DatasetSpec:
    store_id: str
    db_path: Path
    grouping: str
    target: str
    feature_version: str = "v1"
    cv_mode: str = "expanding"


@dataclass(slots=True)
class FoldWindow:
    fold_index: int
    train_indices: np.ndarray
    valid_indices: np.ndarray
    train_start_date: pd.Timestamp
    train_end_date: pd.Timestamp
    valid_start_date: pd.Timestamp
    valid_end_date: pd.Timestamp


@dataclass(slots=True)
class FoldEvaluation:
    fold_index: int
    auc: float
    pr_auc: float
    brier_score: float
    accuracy: float
    precision: float
    recall: float
    f1: float
    base_rate: float
    precision_lift_at_0_5: float
    optimized_precision_lift: float
    zero_recall_penalty: float
    lift_penalty: float
    objective_score: float
    best_threshold: float
    threshold_optimized_precision: float
    threshold_optimized_recall: float
    threshold_optimized_f1: float
    hit_at_1: float
    hit_at_3: float
    selection_score: float
    seen_category_rate: float
    new_machine_rate: float
    train_rows: int
    valid_rows: int
    train_start_date: str
    train_end_date: str
    valid_start_date: str
    valid_end_date: str


@dataclass(slots=True)
class FoldTargetEncoder:
    columns: list[str]
    global_mean_: float = 0.0
    mappings_: dict[str, dict[Any, float]] = field(default_factory=dict)

    def fit(self, df: pd.DataFrame, target_column: str) -> "FoldTargetEncoder":
        if df.empty:
            self.global_mean_ = 0.0
            self.mappings_ = {column: {} for column in self.columns}
            return self

        self.global_mean_ = float(df[target_column].mean())
        self.mappings_ = {}
        for column in self.columns:
            grouped = df.groupby(column, dropna=False)[target_column].mean()
            self.mappings_[column] = grouped.to_dict()
        return self

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        transformed = df.copy()
        for column in self.columns:
            mapping = self.mappings_.get(column, {})
            transformed[f"te_{column}"] = transformed[column].map(mapping).fillna(self.global_mean_)
        return transformed


class ExpandingWindowSplitter:
    def __init__(self, n_splits: int = 5, valid_window_size: int | None = None) -> None:
        self.n_splits = n_splits
        self.valid_window_size = valid_window_size

    def split(self, df: pd.DataFrame, date_column: str = "date") -> Iterable[FoldWindow]:
        df_sorted = df.sort_values(date_column).reset_index(drop=True)
        dates = pd.to_datetime(df_sorted[date_column])
        unique_dates = pd.Index(np.sort(dates.unique()))
        if len(unique_dates) < self.n_splits + 2:
            raise ValueError("Not enough unique dates for expanding-window split")

        valid_size = self.valid_window_size or max(1, len(unique_dates) // (self.n_splits + 1))
        train_size = len(unique_dates) - (valid_size * self.n_splits)
        if train_size < 1:
            raise ValueError("Initial expanding-window train size is too small")

        for fold_index in range(self.n_splits):
            train_dates = unique_dates[: train_size + (fold_index * valid_size)]
            valid_start = train_size + (fold_index * valid_size)
            valid_end = valid_start + valid_size
            valid_dates = unique_dates[valid_start:valid_end]
            train_mask = dates.isin(train_dates)
            valid_mask = dates.isin(valid_dates)
            yield FoldWindow(
                fold_index=fold_index,
                train_indices=np.flatnonzero(train_mask.to_numpy()),
                valid_indices=np.flatnonzero(valid_mask.to_numpy()),
                train_start_date=pd.Timestamp(train_dates.min()),
                train_end_date=pd.Timestamp(train_dates.max()),
                valid_start_date=pd.Timestamp(valid_dates.min()),
                valid_end_date=pd.Timestamp(valid_dates.max()),
            )


class SlidingWindowSplitter:
    def __init__(
        self,
        n_splits: int = 5,
        train_window_size: int | None = None,
        valid_window_size: int | None = None,
    ) -> None:
        self.n_splits = n_splits
        self.train_window_size = train_window_size
        self.valid_window_size = valid_window_size

    def split(self, df: pd.DataFrame, date_column: str = "date") -> Iterable[FoldWindow]:
        df_sorted = df.sort_values(date_column).reset_index(drop=True)
        dates = pd.to_datetime(df_sorted[date_column])
        unique_dates = pd.Index(np.sort(dates.unique()))
        if len(unique_dates) < self.n_splits + 2:
            raise ValueError("Not enough unique dates for sliding-window split")

        valid_size = self.valid_window_size or max(1, len(unique_dates) // (self.n_splits + 2))
        train_size = self.train_window_size or max(valid_size + 1, len(unique_dates) - (valid_size * self.n_splits))
        total_required = train_size + (valid_size * self.n_splits)
        if total_required > len(unique_dates):
            raise ValueError("Sliding-window train/valid sizes exceed available dates")

        for fold_index in range(self.n_splits):
            train_start = fold_index * valid_size
            train_end = train_start + train_size
            valid_end = train_end + valid_size
            train_dates = unique_dates[train_start:train_end]
            valid_dates = unique_dates[train_end:valid_end]
            train_mask = dates.isin(train_dates)
            valid_mask = dates.isin(valid_dates)
            yield FoldWindow(
                fold_index=fold_index,
                train_indices=np.flatnonzero(train_mask.to_numpy()),
                valid_indices=np.flatnonzero(valid_mask.to_numpy()),
                train_start_date=pd.Timestamp(train_dates.min()),
                train_end_date=pd.Timestamp(train_dates.max()),
                valid_start_date=pd.Timestamp(valid_dates.min()),
                valid_end_date=pd.Timestamp(valid_dates.max()),
            )


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


class StoreOptimizedTrainingEngine:
    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self.feature_builder = StoreOptimizedFeatureBuilder()
        self._feature_selection_cache: dict[tuple[Any, ...], dict[str, Any]] = {}

    def run(self, output_root: Path) -> dict[str, Any]:
        output_root = Path(output_root)
        output_root.mkdir(parents=True, exist_ok=True)

        datasets_by_grouping: dict[str, dict[str, pd.DataFrame]] = {
            grouping: {} for grouping in self.config.groupings
        }
        forecast_datasets_by_grouping: dict[str, dict[str, pd.DataFrame]] = {
            grouping: {} for grouping in self.config.groupings
        }
        for db_path in self.config.db_paths:
            for grouping in self.config.groupings:
                dataset = self.feature_builder.build_store_dataset(db_path=db_path, grouping=grouping)
                datasets_by_grouping[grouping][dataset["store_id"].iat[0]] = dataset
                if self.config.forecast_mode:
                    forecast_dataset = self.feature_builder.build_store_forecast_dataset(
                        db_path=db_path,
                        grouping=grouping,
                    )
                    forecast_datasets_by_grouping[grouping][forecast_dataset["store_id"].iat[0]] = forecast_dataset

        all_store_summaries: list[dict[str, Any]] = []
        for db_path in self.config.db_paths:
            store_id = _infer_store_id(db_path)
            store_summary = {"store_id": store_id, "groupings": [], "errors": []}
            for grouping in self.config.groupings:
                try:
                    grouping_summary = self._run_grouping(
                        store_id=store_id,
                        grouping=grouping,
                        store_df=datasets_by_grouping[grouping][store_id],
                        pooled_df=pd.concat(datasets_by_grouping[grouping].values(), ignore_index=True),
                        forecast_df=forecast_datasets_by_grouping[grouping].get(store_id),
                        output_root=output_root,
                    )
                    store_summary["groupings"].append(grouping_summary)
                except Exception as exc:  # pragma: no cover - defensive branch
                    store_summary["errors"].append({"grouping": grouping, "error": str(exc)})
            all_store_summaries.append(store_summary)

        return {"stores": all_store_summaries}

    def _run_grouping(
        self,
        store_id: str,
        grouping: str,
        store_df: pd.DataFrame,
        pooled_df: pd.DataFrame,
        forecast_df: pd.DataFrame | None,
        output_root: Path,
    ) -> dict[str, Any]:
        pipeline_dir = output_root / store_id / grouping / "pipeline"
        features_dir = pipeline_dir / "features"
        cv_dir = pipeline_dir / "cv_runs"
        optuna_dir = pipeline_dir / "optuna"
        models_dir = pipeline_dir / "models"
        feature_selection_dir = pipeline_dir / "feature_selection"
        reports_dir = pipeline_dir / "reports"
        for path in (features_dir, cv_dir, optuna_dir, models_dir, feature_selection_dir, reports_dir):
            path.mkdir(parents=True, exist_ok=True)

        store_df.to_csv(features_dir / f"{store_id}_{grouping}_single_store.csv", index=False)
        pooled_df.to_csv(features_dir / f"{grouping}_pooled_store_aware.csv", index=False)

        leaderboard_rows: list[dict[str, Any]] = []
        summary_runs: list[dict[str, Any]] = []
        best_by_target: dict[str, dict[str, Any]] = {}
        deployable_models_by_target: dict[str, dict[str, Any]] = {}

        for target in self.config.targets:
            if target not in store_df.columns:
                continue

            evaluations: list[dict[str, Any]] = []
            for merge_mode in self.config.merge_modes:
                candidate_df = store_df if merge_mode == "single_store" else pooled_df
                cv_modes = [self.config.base_cv, *self.config.compare_cv]
                for cv_mode in cv_modes:
                    model_rows = []
                    for model_name in self.config.models:
                        result = self._evaluate_model(
                            target_store_id=store_id,
                            grouping=grouping,
                            target=target,
                            merge_mode=merge_mode,
                            cv_mode=cv_mode,
                            candidate_df=candidate_df,
                            target_df=store_df,
                            model_name=model_name,
                            params=self._default_model_params(model_name),
                        )
                        if result is None:
                            continue
                        model_rows.append(result)
                        leaderboard_rows.append(
                            {
                                "target": target,
                                "merge_mode": merge_mode,
                                "cv_mode": cv_mode,
                                "model": model_name,
                                "selection_metric": result["selection_metric"],
                                "selection_score": result["selection_score"],
                                "mean_hit_at_1": result["mean_hit_at_1"],
                                "mean_hit_at_3": result["mean_hit_at_3"],
                                "mean_threshold_optimized_precision": result["mean_threshold_optimized_precision"],
                                "mean_threshold_optimized_recall": result["mean_threshold_optimized_recall"],
                                "mean_threshold_optimized_f1": result["mean_threshold_optimized_f1"],
                                "mean_base_rate": result["mean_base_rate"],
                                "mean_precision_lift_at_0_5": result["mean_precision_lift_at_0_5"],
                                "mean_optimized_precision_lift": result["mean_optimized_precision_lift"],
                                "mean_auc": result["mean_auc"],
                                "mean_pr_auc": result["mean_pr_auc"],
                                "mean_zero_recall_penalty": result["mean_zero_recall_penalty"],
                                "mean_lift_penalty": result["mean_lift_penalty"],
                                "mean_objective_score": result["mean_objective_score"],
                                "fold_count": len(result["folds"]),
                            }
                        )
                        summary_runs.append(result)
                        write_json(
                            cv_dir / f"{target}__{merge_mode}__{cv_mode}__{model_name}.json",
                            result,
                        )
                        if result.get("feature_selection"):
                            write_json(
                                feature_selection_dir / f"{target}__{merge_mode}__{cv_mode}__{model_name}.json",
                                result["feature_selection"],
                            )

                    model_rows.sort(key=lambda row: self._model_sort_key(row, target), reverse=True)
                    evaluations.extend(model_rows)
                    if cv_mode == self.config.base_cv and model_rows:
                        for row in model_rows[: max(1, self.config.optuna_top_k_models)]:
                            final_params = row["params"]
                            if self.config.optuna_enabled:
                                tuned = self._run_optuna(
                                    target_store_id=store_id,
                                    grouping=grouping,
                                    target=target,
                                    merge_mode=merge_mode,
                                    candidate_df=candidate_df,
                                    target_df=store_df,
                                    model_name=row["model"],
                                )
                                write_json(
                                    optuna_dir / f"{target}__{merge_mode}__{row['model']}.json",
                                    tuned,
                                )
                                final_params = tuned.get("best_params") or row["params"]

                            artifact = self._train_final_model(
                                candidate_df=candidate_df,
                                model_name=row["model"],
                                target=target,
                                grouping=grouping,
                                merge_mode=merge_mode,
                                params=final_params,
                            )
                            model_path = models_dir / f"{target}__{merge_mode}__{row['model']}.pkl"
                            with open(model_path, "wb") as f:
                                pickle.dump(artifact, f)

                            current_best = deployable_models_by_target.get(target)
                            if current_best is None or self._model_sort_key(row, target) > self._model_sort_key(current_best, target):
                                deployable_models_by_target[target] = {
                                    "artifact": artifact,
                                    "model_path": str(model_path),
                                    "model": row["model"],
                                    "merge_mode": merge_mode,
                                    "cv_mode": cv_mode,
                                    "selection_metric": row["selection_metric"],
                                    "selection_score": row["selection_score"],
                                    "mean_hit_at_1": row["mean_hit_at_1"],
                                    "mean_hit_at_3": row["mean_hit_at_3"],
                                    "mean_threshold_optimized_precision": row["mean_threshold_optimized_precision"],
                                    "mean_threshold_optimized_recall": row["mean_threshold_optimized_recall"],
                                    "mean_threshold_optimized_f1": row["mean_threshold_optimized_f1"],
                                    "mean_base_rate": row["mean_base_rate"],
                                    "mean_precision_lift_at_0_5": row["mean_precision_lift_at_0_5"],
                                    "mean_optimized_precision_lift": row["mean_optimized_precision_lift"],
                                    "mean_auc": row["mean_auc"],
                                    "mean_pr_auc": row["mean_pr_auc"],
                                    "mean_lift_penalty": row["mean_lift_penalty"],
                                    "mean_objective_score": row["mean_objective_score"],
                                    "params": final_params,
                                }

            if evaluations:
                evaluations.sort(key=lambda row: self._model_sort_key(row, target), reverse=True)
                best_by_target[target] = {
                    "model": evaluations[0]["model"],
                    "merge_mode": evaluations[0]["merge_mode"],
                    "cv_mode": evaluations[0]["cv_mode"],
                    "selection_metric": evaluations[0]["selection_metric"],
                    "selection_score": evaluations[0]["selection_score"],
                    "mean_hit_at_1": evaluations[0]["mean_hit_at_1"],
                    "mean_hit_at_3": evaluations[0]["mean_hit_at_3"],
                    "mean_threshold_optimized_precision": evaluations[0]["mean_threshold_optimized_precision"],
                    "mean_threshold_optimized_recall": evaluations[0]["mean_threshold_optimized_recall"],
                    "mean_threshold_optimized_f1": evaluations[0]["mean_threshold_optimized_f1"],
                    "mean_base_rate": evaluations[0]["mean_base_rate"],
                    "mean_precision_lift_at_0_5": evaluations[0]["mean_precision_lift_at_0_5"],
                    "mean_optimized_precision_lift": evaluations[0]["mean_optimized_precision_lift"],
                    "mean_auc": evaluations[0]["mean_auc"],
                    "mean_pr_auc": evaluations[0]["mean_pr_auc"],
                    "mean_lift_penalty": evaluations[0]["mean_lift_penalty"],
                    "mean_objective_score": evaluations[0]["mean_objective_score"],
                }

        leaderboard_df = pd.DataFrame(leaderboard_rows)
        if not leaderboard_df.empty:
            leaderboard_df.to_csv(reports_dir / "leaderboard.csv", index=False)
        else:
            pd.DataFrame(
                columns=[
                    "target",
                    "merge_mode",
                    "cv_mode",
                    "model",
                    "selection_metric",
                    "selection_score",
                    "mean_hit_at_1",
                    "mean_hit_at_3",
                    "mean_threshold_optimized_precision",
                    "mean_threshold_optimized_recall",
                    "mean_threshold_optimized_f1",
                    "mean_base_rate",
                    "mean_precision_lift_at_0_5",
                    "mean_optimized_precision_lift",
                    "mean_auc",
                    "mean_pr_auc",
                    "mean_zero_recall_penalty",
                    "mean_lift_penalty",
                    "mean_objective_score",
                ]
            ).to_csv(reports_dir / "leaderboard.csv", index=False)

        summary_payload = {
            "store_id": store_id,
            "grouping": grouping,
            "config": {
                "models": self.config.models,
                "merge_modes": self.config.merge_modes,
                "base_cv": self.config.base_cv,
                "compare_cv": self.config.compare_cv,
                "optuna_enabled": self.config.optuna_enabled,
                "feature_selection_enabled": self.config.feature_selection_enabled,
                "feature_selection_selector_model": self.config.feature_selection_selector_model,
                "feature_selection_strategy": self.config.feature_selection_strategy,
                "forecast_mode": self.config.forecast_mode,
                "lift_penalty_weight": self.config.lift_penalty_weight,
                "lift_floor_rank1": self.config.lift_floor_rank1,
                "lift_floor_top3": self.config.lift_floor_top3,
                "lift_floor_top5": self.config.lift_floor_top5,
            },
            "runs": summary_runs,
            "best_by_target": best_by_target,
        }
        if self.config.forecast_mode and forecast_df is not None and deployable_models_by_target:
            forecast_payload = self._build_next_day_forecast_payload(
                store_id=store_id,
                grouping=grouping,
                forecast_df=forecast_df,
                deployable_models_by_target=deployable_models_by_target,
            )
            summary_payload["next_day_forecast"] = {
                "target_date": forecast_payload["target_date"],
                "prediction_count": len(forecast_payload["predictions"]),
            }
            write_json(reports_dir / "next_day_forecast.json", forecast_payload)
            pd.DataFrame(_flatten_forecast_rows(forecast_payload)).to_csv(
                reports_dir / "next_day_forecast.csv",
                index=False,
            )
            write_text(
                reports_dir / "next_day_forecast.html",
                self._render_next_day_forecast_html(forecast_payload),
            )
        feature_catalog_payload = _build_feature_catalog_payload(
            store_id=store_id,
            grouping=grouping,
            dataset=store_df,
        )
        summary_payload["feature_catalog"] = feature_catalog_payload
        write_json(reports_dir / "summary.json", summary_payload)
        write_text(
            reports_dir / "summary.html",
            self._render_grouping_summary_html(
                store_id=store_id,
                grouping=grouping,
                summary_payload=summary_payload,
                leaderboard_df=leaderboard_df,
            ),
        )
        write_text(
            reports_dir / "feature_catalog.md",
            _render_feature_catalog_markdown(feature_catalog_payload),
        )
        feature_importance_payload = _build_feature_importance_payload(summary_payload)
        write_json(reports_dir / "feature_importance.json", feature_importance_payload)
        write_text(
            reports_dir / "feature_importance.md",
            _render_feature_importance_markdown(
                store_id=store_id,
                grouping=grouping,
                feature_importance_payload=feature_importance_payload,
            ),
        )
        return summary_payload

    def _evaluate_model(
        self,
        target_store_id: str,
        grouping: str,
        target: str,
        merge_mode: str,
        cv_mode: str,
        candidate_df: pd.DataFrame,
        target_df: pd.DataFrame,
        model_name: str,
        params: dict[str, Any],
    ) -> dict[str, Any] | None:
        folds = self._select_splitter(cv_mode).split(target_df, date_column="date")
        fold_results: list[dict[str, Any]] = []
        selection_summaries: list[dict[str, Any]] = []

        for fold in folds:
            train_frame = candidate_df[
                (candidate_df["date"] >= fold.train_start_date) & (candidate_df["date"] <= fold.train_end_date)
            ].copy()
            valid_frame = target_df.iloc[fold.valid_indices].copy()
            if train_frame.empty or valid_frame.empty:
                continue
            if train_frame[target].nunique() < 2 or valid_frame[target].nunique() < 2:
                continue

            artifact = self._fit_model_for_fold(
                train_frame=train_frame,
                valid_frame=valid_frame,
                target=target,
                grouping=grouping,
                merge_mode=merge_mode,
                model_name=model_name,
                params=params,
            )
            y_true = valid_frame[target].to_numpy()
            y_pred_proba = artifact["predict_proba"]
            y_pred = (y_pred_proba >= 0.5).astype(int)
            lift_floor = self._lift_floor_for_target(target)
            metrics = evaluate_model(
                y_true,
                y_pred_proba,
                y_pred,
                lift_floor=lift_floor,
                lift_penalty_weight=self.config.lift_penalty_weight,
            )
            hit_at_1 = calculate_hit_at_k(y_true, y_pred_proba, valid_frame["date"].to_numpy(), k=1)
            hit_at_3 = calculate_hit_at_k(y_true, y_pred_proba, valid_frame["date"].to_numpy(), k=3)
            selection_score = hit_at_1 if target == "is_rank_1" else hit_at_3
            seen_category_rate = float(valid_frame["entity_key"].isin(set(train_frame["entity_key"])).mean())
            selection_summaries.append(artifact["selection_summary"])
            fold_result = FoldEvaluation(
                fold_index=fold.fold_index,
                auc=float(metrics["auc"]),
                pr_auc=float(metrics["pr_auc"]),
                brier_score=float(metrics["brier_score"]),
                accuracy=float(metrics["accuracy"]),
                precision=float(metrics["precision"]),
                recall=float(metrics["recall"]),
                f1=float(metrics["f1"]),
                base_rate=float(metrics["base_rate"]),
                precision_lift_at_0_5=float(metrics["precision_lift_at_0_5"]),
                optimized_precision_lift=float(metrics["optimized_precision_lift"]),
                zero_recall_penalty=float(metrics["zero_recall_penalty"]),
                lift_penalty=float(metrics["lift_penalty"]),
                objective_score=float(metrics["objective_score"]),
                best_threshold=float(metrics["best_threshold"]),
                threshold_optimized_precision=float(metrics["optimized_precision"]),
                threshold_optimized_recall=float(metrics["optimized_recall"]),
                threshold_optimized_f1=float(metrics["optimized_f1"]),
                hit_at_1=float(hit_at_1),
                hit_at_3=float(hit_at_3),
                selection_score=float(selection_score),
                seen_category_rate=seen_category_rate,
                new_machine_rate=1.0 - seen_category_rate,
                train_rows=len(train_frame),
                valid_rows=len(valid_frame),
                train_start_date=fold.train_start_date.strftime("%Y-%m-%d"),
                train_end_date=fold.train_end_date.strftime("%Y-%m-%d"),
                valid_start_date=fold.valid_start_date.strftime("%Y-%m-%d"),
                valid_end_date=fold.valid_end_date.strftime("%Y-%m-%d"),
            )
            fold_results.append(asdict(fold_result))

        if not fold_results:
            return None

        aucs = [fold["auc"] for fold in fold_results]
        pr_aucs = [fold["pr_auc"] for fold in fold_results]
        zero_recall_penalties = [fold["zero_recall_penalty"] for fold in fold_results]
        lift_penalties = [fold["lift_penalty"] for fold in fold_results]
        base_rates = [fold["base_rate"] for fold in fold_results]
        precision_lifts_at_0_5 = [fold["precision_lift_at_0_5"] for fold in fold_results]
        optimized_precision_lifts = [fold["optimized_precision_lift"] for fold in fold_results]
        objective_scores = [fold["objective_score"] for fold in fold_results]
        best_thresholds = [fold["best_threshold"] for fold in fold_results]
        optimized_precisions = [fold["threshold_optimized_precision"] for fold in fold_results]
        optimized_recalls = [fold["threshold_optimized_recall"] for fold in fold_results]
        optimized_f1s = [fold["threshold_optimized_f1"] for fold in fold_results]
        hit_at_1_values = [fold["hit_at_1"] for fold in fold_results]
        hit_at_3_values = [fold["hit_at_3"] for fold in fold_results]
        selection_scores = [fold["selection_score"] for fold in fold_results]
        return {
            "target_store_id": target_store_id,
            "grouping": grouping,
            "target": target,
            "merge_mode": merge_mode,
            "cv_mode": cv_mode,
            "model": model_name,
            "params": params,
            "mean_auc": float(np.mean(aucs)),
            "mean_pr_auc": float(np.mean(pr_aucs)),
            "mean_zero_recall_penalty": float(np.mean(zero_recall_penalties)),
            "mean_objective_score": float(np.mean(objective_scores)),
            "mean_best_threshold": float(np.mean(best_thresholds)),
            "mean_threshold_optimized_precision": float(np.mean(optimized_precisions)),
            "mean_threshold_optimized_recall": float(np.mean(optimized_recalls)),
            "mean_threshold_optimized_f1": float(np.mean(optimized_f1s)),
            "mean_base_rate": float(np.mean(base_rates)),
            "mean_precision_lift_at_0_5": float(np.mean(precision_lifts_at_0_5)),
            "mean_optimized_precision_lift": float(np.mean(optimized_precision_lifts)),
            "mean_hit_at_1": float(np.mean(hit_at_1_values)),
            "mean_hit_at_3": float(np.mean(hit_at_3_values)),
            "mean_lift_penalty": float(np.mean(lift_penalties)),
            "selection_metric": self._selection_metric_name(target),
            "selection_score": float(np.mean(selection_scores)),
            "std_auc": float(np.std(aucs)),
            "folds": fold_results,
            "feature_selection": self._aggregate_feature_selection(selection_summaries),
        }

    def _fit_model_for_fold(
        self,
        train_frame: pd.DataFrame,
        valid_frame: pd.DataFrame,
        target: str,
        grouping: str,
        merge_mode: str,
        model_name: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        categorical_columns = _categorical_columns_for_grouping(grouping, merge_mode)
        available_cat_cols = [column for column in categorical_columns if column in train_frame.columns]
        numeric_columns = self._numeric_feature_columns(train_frame, available_cat_cols)
        encoder = FoldTargetEncoder(columns=available_cat_cols).fit(train_frame, target)
        train_encoded = encoder.transform(train_frame)
        valid_encoded = encoder.transform(valid_frame)
        encoded_columns = [f"te_{column}" for column in available_cat_cols]
        base_model_columns = numeric_columns + encoded_columns
        selection_cache_key = (
            "fold",
            grouping,
            merge_mode,
            target,
            train_frame["date"].min().strftime("%Y-%m-%d"),
            train_frame["date"].max().strftime("%Y-%m-%d"),
            len(train_frame),
            tuple(base_model_columns),
        )
        selection_summary = self._select_feature_columns(
            train_matrix=train_encoded[base_model_columns],
            y_train=train_frame[target],
            feature_columns=base_model_columns,
            cache_key=selection_cache_key,
        )
        selected_model_columns = selection_summary["selected_features"]

        if model_name == "catboost":
            train_data = train_encoded[selected_model_columns + available_cat_cols].copy()
            valid_data = valid_encoded[selected_model_columns + available_cat_cols].copy()
            model = self._build_model(model_name, params)
            model.fit(train_data, train_frame[target], cat_features=available_cat_cols, verbose=False)
            predict_proba = model.predict_proba(valid_data)[:, 1]
            return {
                "model": model,
                "predict_proba": predict_proba,
                "encoder": encoder,
                "numeric_columns": numeric_columns,
                "encoded_columns": encoded_columns,
                "selection_summary": selection_summary,
            }

        train_matrix = train_encoded[selected_model_columns]
        valid_matrix = valid_encoded[selected_model_columns]
        model = self._build_model(model_name, params)
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="X does not have valid feature names, but LGBMClassifier was fitted with feature names",
                category=UserWarning,
            )
            model.fit(train_matrix, train_frame[target])
            predict_proba = model.predict_proba(valid_matrix)[:, 1]
        return {
            "model": model,
            "predict_proba": predict_proba,
            "encoder": encoder,
            "numeric_columns": numeric_columns,
            "encoded_columns": encoded_columns,
            "selection_summary": selection_summary,
        }

    def _train_final_model(
        self,
        candidate_df: pd.DataFrame,
        model_name: str,
        target: str,
        grouping: str,
        merge_mode: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        categorical_columns = _categorical_columns_for_grouping(grouping, merge_mode)
        available_cat_cols = [column for column in categorical_columns if column in candidate_df.columns]
        numeric_columns = self._numeric_feature_columns(candidate_df, available_cat_cols)
        encoder = FoldTargetEncoder(columns=available_cat_cols).fit(candidate_df, target)
        encoded = encoder.transform(candidate_df)
        encoded_columns = [f"te_{column}" for column in available_cat_cols]
        base_model_columns = numeric_columns + encoded_columns
        selection_cache_key = (
            "final",
            grouping,
            merge_mode,
            target,
            candidate_df["date"].min().strftime("%Y-%m-%d"),
            candidate_df["date"].max().strftime("%Y-%m-%d"),
            len(candidate_df),
            tuple(base_model_columns),
        )
        selection_summary = self._select_feature_columns(
            train_matrix=encoded[base_model_columns],
            y_train=candidate_df[target],
            feature_columns=base_model_columns,
            cache_key=selection_cache_key,
        )
        selected_model_columns = selection_summary["selected_features"]

        artifact: dict[str, Any] = {
            "model_name": model_name,
            "params": params,
            "target": target,
            "grouping": grouping,
            "merge_mode": merge_mode,
            "numeric_columns": numeric_columns,
            "categorical_columns": available_cat_cols,
            "feature_selection": selection_summary,
        }

        if model_name == "catboost":
            train_data = encoded[selected_model_columns + available_cat_cols].copy()
            model = self._build_model(model_name, params)
            model.fit(train_data, candidate_df[target], cat_features=available_cat_cols, verbose=False)
            artifact["model"] = model
            artifact["encoder"] = encoder
            artifact["selected_model_columns"] = selected_model_columns
            return artifact

        model = self._build_model(model_name, params)
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="X does not have valid feature names, but LGBMClassifier was fitted with feature names",
                category=UserWarning,
            )
            model.fit(encoded[selected_model_columns], candidate_df[target])
        artifact["model"] = model
        artifact["encoder"] = encoder
        artifact["encoded_columns"] = encoded_columns
        artifact["selected_model_columns"] = selected_model_columns
        return artifact

    def _run_optuna(
        self,
        target_store_id: str,
        grouping: str,
        target: str,
        merge_mode: str,
        candidate_df: pd.DataFrame,
        target_df: pd.DataFrame,
        model_name: str,
    ) -> dict[str, Any]:
        def objective(trial: optuna.Trial) -> float:
            params = self._suggest_params(model_name, trial)
            result = self._evaluate_model(
                target_store_id=target_store_id,
                grouping=grouping,
                target=target,
                merge_mode=merge_mode,
                cv_mode=self.config.base_cv,
                candidate_df=candidate_df,
                target_df=target_df,
                model_name=model_name,
                params=params,
            )
            if result is None:
                return 0.0
            return result["mean_objective_score"]

        sampler = optuna.samplers.TPESampler(seed=self.config.random_state)
        study = optuna.create_study(direction="maximize", sampler=sampler)
        study.optimize(objective, n_trials=self.config.optuna_trials, show_progress_bar=False)
        return {
            "target": target,
            "merge_mode": merge_mode,
            "model": model_name,
            "best_value": float(study.best_value),
            "best_params": study.best_params,
            "trials": [
                {
                    "number": trial.number,
                    "value": None if trial.value is None else float(trial.value),
                    "params": trial.params,
                }
                for trial in study.trials
            ],
        }

    def _select_splitter(self, cv_mode: str) -> ExpandingWindowSplitter | SlidingWindowSplitter:
        if cv_mode == "expanding":
            return ExpandingWindowSplitter(
                n_splits=self.config.n_splits,
                valid_window_size=self.config.valid_window_size,
            )
        if cv_mode == "sliding":
            return SlidingWindowSplitter(
                n_splits=self.config.n_splits,
                train_window_size=self.config.train_window_size,
                valid_window_size=self.config.valid_window_size,
            )
        raise ValueError(f"Unsupported cv_mode: {cv_mode}")

    def _selection_metric_name(self, target: str) -> str:
        return "hit_at_1" if target == "is_rank_1" else "hit_at_3"

    def _lift_floor_for_target(self, target: str) -> float:
        if target == "is_rank_1":
            return self.config.lift_floor_rank1
        if target == "is_top_3":
            return self.config.lift_floor_top3
        if target == "is_top_5":
            return self.config.lift_floor_top5
        return 1.0

    def _model_sort_key(self, result: dict[str, Any], target: str) -> tuple[float, float, float, float]:
        return (
            float(result["selection_score"]),
            float(result["mean_threshold_optimized_f1"]),
            float(result["mean_objective_score"]),
            float(result["mean_auc"]),
        )

    def _numeric_feature_columns(self, df: pd.DataFrame, categorical_columns: list[str]) -> list[str]:
        numeric_columns = _numeric_feature_columns(df, categorical_columns)
        if not self.config.forecast_mode:
            filtered = numeric_columns
        else:
            filtered = [column for column in numeric_columns if column not in FORECAST_EXCLUDED_COLUMNS]
        return self._apply_feature_ablation(filtered)

    def _apply_feature_ablation(self, columns: list[str]) -> list[str]:
        mode = self.config.feature_ablation_mode
        if mode == "none":
            return columns

        def is_worst_feature(name: str) -> bool:
            lower = name.lower()
            return any(keyword in lower for keyword in ABLATION_WORST_FEATURE_KEYWORDS)

        def is_momvol_feature(name: str) -> bool:
            lower = name.lower()
            return any(lower.startswith(prefix) for prefix in ABLATION_MOMVOL_FEATURE_PREFIXES)

        def is_same_day_of_month_feature(name: str) -> bool:
            lower = name.lower()
            return any(lower.startswith(prefix) for prefix in ABLATION_SAME_DAY_OF_MONTH_PREFIXES)

        def is_same_weekday_feature(name: str) -> bool:
            lower = name.lower()
            return any(lower.startswith(prefix) for prefix in ABLATION_SAME_WEEKDAY_PREFIXES)

        def is_event_feature(name: str) -> bool:
            return name in ABLATION_EVENT_FEATURE_COLUMNS

        def is_rank1_special_feature(name: str) -> bool:
            lower = name.lower()
            return any(lower.startswith(prefix) for prefix in ABLATION_RANK1_SPECIAL_PREFIXES)

        def is_event_distance_redesign_feature(name: str) -> bool:
            return name in ABLATION_EVENT_DISTANCE_REDESIGN_COLUMNS

        def is_worst_recency_feature(name: str) -> bool:
            lower = name.lower()
            return any(lower.startswith(prefix) for prefix in ABLATION_WORST_RECENCY_PREFIXES)

        def is_worst_streak_feature(name: str) -> bool:
            lower = name.lower()
            return any(lower.startswith(prefix) for prefix in ABLATION_WORST_STREAK_PREFIXES)

        def is_worst_rate_feature(name: str) -> bool:
            lower = name.lower()
            if is_worst_recency_feature(name) or is_worst_streak_feature(name):
                return False
            return any(keyword in lower for keyword in ABLATION_WORST_RATE_KEYWORDS)

        if mode == "worst_off":
            return [column for column in columns if not is_worst_feature(column)]
        if mode == "momvol_off":
            return [column for column in columns if not is_momvol_feature(column)]
        if mode == "both_off":
            return [
                column
                for column in columns
                if not is_worst_feature(column) and not is_momvol_feature(column)
            ]
        if mode == "worst_rate_off":
            return [column for column in columns if not is_worst_rate_feature(column)]
        if mode == "worst_streak_off":
            return [column for column in columns if not is_worst_streak_feature(column)]
        if mode == "worst_only_recency":
            return [
                column
                for column in columns
                if not is_worst_feature(column) or is_worst_recency_feature(column)
            ]
        if mode == "same_day_of_month_off":
            return [column for column in columns if not is_same_day_of_month_feature(column)]
        if mode == "worst_rate_off_same_day_of_month_off":
            return [
                column
                for column in columns
                if not is_worst_rate_feature(column) and not is_same_day_of_month_feature(column)
            ]
        if mode == "same_weekday_off":
            return [column for column in columns if not is_same_weekday_feature(column)]
        if mode == "worst_rate_off_same_weekday_off":
            return [
                column
                for column in columns
                if not is_worst_rate_feature(column) and not is_same_weekday_feature(column)
            ]
        if mode == "event_off":
            return [column for column in columns if not is_event_feature(column)]
        if mode == "worst_rate_off_event_off":
            return [
                column
                for column in columns
                if not is_worst_rate_feature(column) and not is_event_feature(column)
            ]
        if mode == "rank1_special_off":
            return [column for column in columns if not is_rank1_special_feature(column)]
        if mode == "event_distance_redesign_off":
            return [column for column in columns if not is_event_distance_redesign_feature(column)]
        if mode == "rank1_special_off_event_distance_redesign_off":
            return [
                column
                for column in columns
                if not is_rank1_special_feature(column) and not is_event_distance_redesign_feature(column)
            ]
        raise ValueError(f"Unknown feature_ablation_mode: {mode}")

    def _build_model(self, model_name: str, params: dict[str, Any]) -> Any:
        if model_name == "lgbm":
            return LGBMClassifier(random_state=self.config.random_state, verbosity=-1, **params)
        if model_name == "xgb":
            return XGBClassifier(
                random_state=self.config.random_state,
                eval_metric="logloss",
                verbosity=0,
                **params,
            )
        if model_name == "catboost":
            return CatBoostClassifier(
                random_seed=self.config.random_state,
                verbose=False,
                allow_writing_files=False,
                **params,
            )
        raise ValueError(f"Unsupported model: {model_name}")

    def _default_model_params(self, model_name: str) -> dict[str, Any]:
        if model_name == "lgbm":
            return {"n_estimators": 60, "learning_rate": 0.05, "max_depth": 4, "num_leaves": 31}
        if model_name == "xgb":
            return {"n_estimators": 60, "learning_rate": 0.05, "max_depth": 4, "subsample": 0.9, "colsample_bytree": 0.9}
        if model_name == "catboost":
            return {"iterations": 60, "learning_rate": 0.05, "depth": 4, "l2_leaf_reg": 3.0}
        raise ValueError(f"Unsupported model: {model_name}")

    def _suggest_params(self, model_name: str, trial: optuna.Trial) -> dict[str, Any]:
        if model_name == "lgbm":
            return {
                "n_estimators": trial.suggest_int("n_estimators", 40, 90),
                "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.10),
                "max_depth": trial.suggest_int("max_depth", 3, 6),
                "num_leaves": trial.suggest_int("num_leaves", 15, 63),
            }
        if model_name == "xgb":
            return {
                "n_estimators": trial.suggest_int("n_estimators", 40, 90),
                "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.10),
                "max_depth": trial.suggest_int("max_depth", 3, 6),
                "subsample": trial.suggest_float("subsample", 0.7, 1.0),
                "colsample_bytree": trial.suggest_float("colsample_bytree", 0.7, 1.0),
            }
        if model_name == "catboost":
            return {
                "iterations": trial.suggest_int("iterations", 40, 90),
                "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.10),
                "depth": trial.suggest_int("depth", 3, 6),
                "l2_leaf_reg": trial.suggest_float("l2_leaf_reg", 1.0, 5.0),
            }
        raise ValueError(f"Unsupported model: {model_name}")

    def _select_feature_columns(
        self,
        train_matrix: pd.DataFrame,
        y_train: pd.Series,
        feature_columns: list[str],
        cache_key: tuple[Any, ...] | None = None,
    ) -> dict[str, Any]:
        if not self.config.feature_selection_enabled or not feature_columns:
            return {
                "selector_model": self.config.feature_selection_selector_model,
                "selector_strategy": self.config.feature_selection_strategy,
                "selected_features": feature_columns,
                "dropped_features": [],
                "feature_importances": {},
                "permutation_importances": {},
            }

        if cache_key is not None and cache_key in self._feature_selection_cache:
            return copy.deepcopy(self._feature_selection_cache[cache_key])

        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="X does not have valid feature names, but LGBMClassifier was fitted with feature names",
                category=UserWarning,
            )
            selector = self._build_selector_model()
            selector.fit(train_matrix[feature_columns], y_train)
            base_importances = _extract_named_importances(selector, feature_columns)

            keep_count = self.config.feature_selection_top_k
            if keep_count is None:
                keep_count = ceil(len(feature_columns) * self.config.feature_selection_keep_ratio)
            keep_count = max(1, min(len(feature_columns), max(self.config.feature_selection_min_features, keep_count)))

            base_ranking = sorted(
                base_importances.items(),
                key=lambda item: (float(item[1]), item[0]),
                reverse=True,
            )
            fallback_features = [name for name, _ in base_ranking[:keep_count]]

            strategy = self.config.feature_selection_strategy
            boruta_selected = feature_columns
            rfecv_selected = feature_columns
            rfecv_ranking: dict[str, int] = {feature: 1 for feature in feature_columns}
            rfecv_scores: list[float] = []
            shadow_threshold = 0.0

            if strategy == "importance":
                selected_features = fallback_features
            elif strategy == "rfecv_boruta":
                boruta_summary = self._run_boruta_like_selection(
                    train_matrix=train_matrix,
                    y_train=y_train,
                    feature_columns=feature_columns,
                )
                boruta_selected = boruta_summary["selected_features"]
                shadow_threshold = boruta_summary["shadow_threshold"]
                rfecv_summary = self._run_rfecv_selection(
                    train_matrix=train_matrix,
                    y_train=y_train,
                    feature_columns=boruta_selected or fallback_features,
                )
                rfecv_selected = rfecv_summary["selected_features"]
                rfecv_ranking = rfecv_summary["ranking"]
                rfecv_scores = rfecv_summary["cv_scores"]
                selected_features = rfecv_selected or boruta_selected or fallback_features
            else:
                raise ValueError(f"Unsupported feature selection strategy: {strategy}")

            permutation_importances = self._compute_permutation_importances(
                train_matrix=train_matrix,
                y_train=y_train,
                feature_columns=feature_columns,
            )
        dropped_features = [name for name in feature_columns if name not in selected_features]

        feature_scorecard = []
        for feature in feature_columns:
            feature_scorecard.append(
                {
                    "feature": feature,
                    "model_importance": float(base_importances.get(feature, 0.0)),
                    "permutation_importance": float(permutation_importances.get(feature, 0.0)),
                    "selected": feature in selected_features,
                    "boruta_like_selected": feature in boruta_selected,
                    "rfecv_selected": feature in rfecv_selected,
                    "rfecv_rank": int(rfecv_ranking.get(feature, 999)),
                }
            )
        feature_scorecard.sort(
            key=lambda item: (
                not item["selected"],
                -item["permutation_importance"],
                -item["model_importance"],
                item["rfecv_rank"],
                item["feature"],
            )
        )

        summary = {
            "selector_model": self.config.feature_selection_selector_model,
            "selector_strategy": strategy,
            "selected_features": selected_features,
            "dropped_features": dropped_features,
            "feature_importances": base_importances,
            "permutation_importances": permutation_importances,
            "boruta_like_features": boruta_selected,
            "rfecv_selected_features": rfecv_selected,
            "rfecv_ranking": rfecv_ranking,
            "rfecv_cv_scores": rfecv_scores,
            "shadow_threshold": float(shadow_threshold),
            "feature_scorecard": feature_scorecard,
        }
        if cache_key is not None:
            self._feature_selection_cache[cache_key] = copy.deepcopy(summary)
        return summary

    def _aggregate_feature_selection(self, selection_summaries: list[dict[str, Any]]) -> dict[str, Any]:
        if not selection_summaries:
            return {}

        frequency: dict[str, int] = {}
        selector_model = selection_summaries[0].get("selector_model")
        selector_strategy = selection_summaries[0].get("selector_strategy")
        model_importance_totals: dict[str, float] = {}
        permutation_totals: dict[str, float] = {}
        boruta_frequency: dict[str, int] = {}
        rfecv_frequency: dict[str, int] = {}
        latest_importances = selection_summaries[-1].get("feature_importances", {})
        latest_permutation_importances = selection_summaries[-1].get("permutation_importances", {})
        for selection in selection_summaries:
            for feature in selection.get("selected_features", []):
                frequency[feature] = frequency.get(feature, 0) + 1
            for feature, value in selection.get("feature_importances", {}).items():
                model_importance_totals[feature] = model_importance_totals.get(feature, 0.0) + float(value)
            for feature, value in selection.get("permutation_importances", {}).items():
                permutation_totals[feature] = permutation_totals.get(feature, 0.0) + float(value)
            for feature in selection.get("boruta_like_features", []):
                boruta_frequency[feature] = boruta_frequency.get(feature, 0) + 1
            for feature in selection.get("rfecv_selected_features", []):
                rfecv_frequency[feature] = rfecv_frequency.get(feature, 0) + 1

        ordered_frequency = sorted(frequency.items(), key=lambda item: (-item[1], item[0]))
        stable_features = [
            feature
            for feature, count in ordered_frequency
            if count == len(selection_summaries)
        ]
        consensus_features = [
            feature
            for feature, count in ordered_frequency
            if count >= ceil(len(selection_summaries) / 2)
        ]
        mean_model_importances = {
            feature: value / len(selection_summaries)
            for feature, value in model_importance_totals.items()
        }
        mean_permutation_importances = {
            feature: value / len(selection_summaries)
            for feature, value in permutation_totals.items()
        }
        top_features = sorted(
            (
                {
                    "feature": feature,
                    "selected_in_folds": count,
                    "mean_model_importance": float(mean_model_importances.get(feature, 0.0)),
                    "mean_permutation_importance": float(mean_permutation_importances.get(feature, 0.0)),
                    "boruta_selected_in_folds": boruta_frequency.get(feature, 0),
                    "rfecv_selected_in_folds": rfecv_frequency.get(feature, 0),
                }
                for feature, count in ordered_frequency
            ),
            key=lambda item: (
                -item["selected_in_folds"],
                -item["mean_permutation_importance"],
                -item["mean_model_importance"],
                item["feature"],
            ),
        )
        return {
            "selector_model": selector_model,
            "selector_strategy": selector_strategy,
            "fold_count": len(selection_summaries),
            "selected_features": selection_summaries[-1].get("selected_features", []),
            "boruta_like_features": selection_summaries[-1].get("boruta_like_features", []),
            "rfecv_selected_features": selection_summaries[-1].get("rfecv_selected_features", []),
            "stable_features": stable_features,
            "consensus_features": consensus_features,
            "feature_frequency": [
                {"feature": feature, "selected_in_folds": count}
                for feature, count in ordered_frequency
            ],
            "latest_feature_importances": latest_importances,
            "permutation_importances": latest_permutation_importances,
            "mean_model_importances": mean_model_importances,
            "mean_permutation_importances": mean_permutation_importances,
            "top_features": top_features[:20],
            "top_features_by_permutation": sorted(
                top_features,
                key=lambda item: (
                    -item["mean_permutation_importance"],
                    -item["mean_model_importance"],
                    -item["selected_in_folds"],
                    item["feature"],
                ),
            )[:20],
        }

    def _build_selector_model(self) -> Any:
        selector_model = self.config.feature_selection_selector_model
        if selector_model == "lgbm":
            return LGBMClassifier(
                random_state=self.config.random_state,
                verbosity=-1,
                n_estimators=50,
                learning_rate=0.05,
                max_depth=3,
                num_leaves=15,
            )
        if selector_model == "xgb":
            return XGBClassifier(
                random_state=self.config.random_state,
                eval_metric="logloss",
                verbosity=0,
                n_estimators=50,
                learning_rate=0.05,
                max_depth=3,
                subsample=0.9,
                colsample_bytree=0.9,
            )
        raise ValueError(f"Unsupported feature selection selector model: {selector_model}")

    def _run_boruta_like_selection(
        self,
        *,
        train_matrix: pd.DataFrame,
        y_train: pd.Series,
        feature_columns: list[str],
    ) -> dict[str, Any]:
        if len(feature_columns) <= self.config.feature_selection_min_features:
            return {"selected_features": feature_columns, "shadow_threshold": 0.0}

        selector = self._build_selector_model()
        rng = np.random.default_rng(self.config.random_state)
        shadow_matrix = pd.DataFrame(index=train_matrix.index)
        shadow_columns = []
        for column in feature_columns:
            shadow_name = f"shadow__{column}"
            shadow_columns.append(shadow_name)
            shadow_matrix[shadow_name] = rng.permutation(train_matrix[column].to_numpy())

        combined = pd.concat([train_matrix[feature_columns], shadow_matrix], axis=1)
        selector.fit(combined.to_numpy(), y_train.to_numpy())
        importances = _extract_named_importances(selector, combined.columns.tolist())
        shadow_values = [float(importances.get(column, 0.0)) for column in shadow_columns]
        shadow_threshold = float(np.quantile(shadow_values, self.config.feature_selection_shadow_quantile)) if shadow_values else 0.0
        selected_features = [
            column
            for column in feature_columns
            if float(importances.get(column, 0.0)) > shadow_threshold
        ]
        if len(selected_features) < min(self.config.feature_selection_min_features, len(feature_columns)):
            base_importances = _extract_named_importances(self._fit_selector(train_matrix[feature_columns], y_train), feature_columns)
            fallback_ranking = sorted(base_importances.items(), key=lambda item: (float(item[1]), item[0]), reverse=True)
            keep_count = min(
                len(feature_columns),
                max(self.config.feature_selection_min_features, self.config.feature_selection_top_k or self.config.feature_selection_min_features),
            )
            selected_features = [name for name, _ in fallback_ranking[:keep_count]]

        return {
            "selected_features": selected_features,
            "shadow_threshold": shadow_threshold,
        }

    def _run_rfecv_selection(
        self,
        *,
        train_matrix: pd.DataFrame,
        y_train: pd.Series,
        feature_columns: list[str],
    ) -> dict[str, Any]:
        if len(feature_columns) <= self.config.feature_selection_min_features:
            return {
                "selected_features": feature_columns,
                "ranking": {feature: 1 for feature in feature_columns},
                "cv_scores": [],
            }

        class_counts = y_train.value_counts()
        min_class_count = int(class_counts.min()) if not class_counts.empty else 0
        cv_splits = min(self.config.feature_selection_rfecv_cv_splits, max(2, min_class_count))
        if cv_splits < 2:
            return {
                "selected_features": feature_columns,
                "ranking": {feature: 1 for feature in feature_columns},
                "cv_scores": [],
            }

        selector = self._build_selector_model()
        cv_splitter = list(self._make_date_aware_cv(train_matrix["date"], n_splits=cv_splits))
        rfecv = RFECV(
            estimator=selector,
            step=max(1, len(feature_columns) // 5),
            cv=cv_splitter,
            scoring="roc_auc",
            min_features_to_select=min(self.config.feature_selection_min_features, len(feature_columns)),
        )
        rfecv.fit(train_matrix[feature_columns].to_numpy(), y_train.to_numpy())
        selected_features = [
            feature
            for feature, keep in zip(feature_columns, rfecv.support_, strict=True)
            if bool(keep)
        ]
        ranking = {
            feature: int(rank)
            for feature, rank in zip(feature_columns, rfecv.ranking_, strict=True)
        }
        cv_scores = [
            float(score)
            for score in rfecv.cv_results_.get("mean_test_score", [])
            if score is not None
        ]
        return {
            "selected_features": selected_features or feature_columns,
            "ranking": ranking,
            "cv_scores": cv_scores,
        }

    def _compute_permutation_importances(
        self,
        *,
        train_matrix: pd.DataFrame,
        y_train: pd.Series,
        feature_columns: list[str],
    ) -> dict[str, float]:
        if not feature_columns:
            return {}
        if y_train.nunique() < 2:
            return {feature: 0.0 for feature in feature_columns}

        selector = self._fit_selector(train_matrix[feature_columns], y_train)
        try:
            result = permutation_importance(
                selector,
                train_matrix[feature_columns].to_numpy(),
                y_train.to_numpy(),
                scoring="roc_auc",
                n_repeats=self.config.feature_selection_permutation_repeats,
                random_state=self.config.random_state,
            )
            return {
                feature: float(importance)
                for feature, importance in zip(feature_columns, result.importances_mean, strict=False)
            }
        except ValueError as e:
            logger.warning(
                "permutation_importance failed for %d features: %s – filling with 0.0",
                len(feature_columns),
                e,
            )
            return {feature: 0.0 for feature in feature_columns}
        except Exception as e:
            logger.error(
                "unexpected error computing permutation_importance for %d features: %s",
                len(feature_columns),
                e,
            )
            raise

    def _fit_selector(self, train_matrix: pd.DataFrame, y_train: pd.Series) -> Any:
        selector = self._build_selector_model()
        selector.fit(train_matrix.to_numpy(), y_train.to_numpy())
        return selector

    def _make_date_aware_cv(self, dates: pd.Series, n_splits: int) -> Iterable[tuple[np.ndarray, np.ndarray]]:
        unique_dates = np.sort(dates.unique())
        if len(unique_dates) < n_splits + 1:
            logger.warning(
                "not enough unique dates (%d) for %d inner CV splits; using StratifiedKFold fallback",
                len(unique_dates),
                n_splits,
            )
            skf = StratifiedKFold(n_splits=min(n_splits, 2), shuffle=False)
            for train_idx, valid_idx in skf.split(dates, np.ones(len(dates))):
                yield train_idx, valid_idx
            return

        fold_size = max(1, len(unique_dates) // (n_splits + 1))
        for i in range(n_splits):
            valid_start = fold_size * (i + 1)
            valid_end = min(valid_start + fold_size, len(unique_dates))
            train_mask = np.isin(dates.to_numpy(), unique_dates[:valid_start])
            valid_mask = np.isin(dates.to_numpy(), unique_dates[valid_start:valid_end])
            train_idx = np.flatnonzero(train_mask)
            valid_idx = np.flatnonzero(valid_mask)
            if len(train_idx) > 0 and len(valid_idx) > 0:
                yield train_idx, valid_idx

    def _predict_with_artifact(
        self,
        *,
        forecast_df: pd.DataFrame,
        artifact: dict[str, Any],
    ) -> np.ndarray:
        encoded = artifact["encoder"].transform(forecast_df.copy())
        selected_model_columns = artifact["selected_model_columns"]
        if artifact["model_name"] == "catboost":
            categorical_columns = artifact["categorical_columns"]
            predict_frame = encoded[selected_model_columns + categorical_columns].copy()
            return artifact["model"].predict_proba(predict_frame)[:, 1]
        predict_frame = encoded[selected_model_columns]
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="X does not have valid feature names, but LGBMClassifier was fitted with feature names",
                category=UserWarning,
            )
            return artifact["model"].predict_proba(predict_frame)[:, 1]

    def _build_next_day_forecast_payload(
        self,
        *,
        store_id: str,
        grouping: str,
        forecast_df: pd.DataFrame,
        deployable_models_by_target: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        target_date = pd.Timestamp(forecast_df["date"].max()).strftime("%Y-%m-%d")
        source_latest_date = (
            pd.Timestamp(forecast_df["date"].max()) - pd.Timedelta(days=1)
        ).strftime("%Y-%m-%d")
        predictions = []

        for target, model_info in sorted(deployable_models_by_target.items()):
            probabilities = self._predict_with_artifact(
                forecast_df=forecast_df,
                artifact=model_info["artifact"],
            )
            rows = []
            for row, probability in zip(forecast_df.itertuples(index=False), probabilities, strict=False):
                payload = {
                    "entity_key": str(row.entity_key),
                    "date": pd.Timestamp(row.date).strftime("%Y-%m-%d"),
                    "probability": float(probability),
                }
                for column in ("machine_name", "machine_type", "last_digit", "is_zorome"):
                    if hasattr(row, column):
                        payload[column] = getattr(row, column)
                rows.append(payload)
            rows.sort(key=lambda item: (-item["probability"], item["entity_key"]))
            predictions.append(
                {
                    "target": target,
                    "model": model_info["model"],
                    "merge_mode": model_info["merge_mode"],
                    "cv_mode": model_info["cv_mode"],
                    "selection_metric": model_info["selection_metric"],
                    "selection_score": float(model_info["selection_score"]),
                    "mean_hit_at_1": float(model_info["mean_hit_at_1"]),
                    "mean_hit_at_3": float(model_info["mean_hit_at_3"]),
                    "mean_threshold_optimized_precision": float(model_info["mean_threshold_optimized_precision"]),
                    "mean_threshold_optimized_recall": float(model_info["mean_threshold_optimized_recall"]),
                    "mean_threshold_optimized_f1": float(model_info["mean_threshold_optimized_f1"]),
                    "mean_base_rate": float(model_info["mean_base_rate"]),
                    "mean_precision_lift_at_0_5": float(model_info["mean_precision_lift_at_0_5"]),
                    "mean_optimized_precision_lift": float(model_info["mean_optimized_precision_lift"]),
                    "mean_auc": float(model_info["mean_auc"]),
                    "mean_pr_auc": float(model_info["mean_pr_auc"]),
                    "mean_lift_penalty": float(model_info["mean_lift_penalty"]),
                    "mean_objective_score": float(model_info["mean_objective_score"]),
                    "rows": rows,
                }
            )

        return {
            "store_id": store_id,
            "grouping": grouping,
            "source_latest_date": source_latest_date,
            "target_date": target_date,
            "predictions": predictions,
        }

    def _render_next_day_forecast_html(self, forecast_payload: dict[str, Any]) -> str:
        sections = []
        for prediction in forecast_payload.get("predictions", []):
            rows_html = "".join(
                f"<tr><td>{escape(str(row.get('entity_key')))}</td>"
                f"<td>{escape(_format_html_value(row.get('probability')))}</td>"
                f"<td>{escape(str(row.get('machine_name', row.get('machine_type', row.get('last_digit', '-')))))}</td></tr>"
                for row in prediction.get("rows", [])
            )
            sections.append(
                f"""
                <section>
                  <h2>{escape(str(prediction['target']))} / {escape(str(prediction['model']))}</h2>
                  <p>Merge Mode: {escape(str(prediction['merge_mode']))} | Selection: {escape(str(prediction['selection_metric']))}={escape(_format_html_value(prediction['selection_score']))} | Hit@1: {escape(_format_html_value(prediction['mean_hit_at_1']))} | Hit@3: {escape(_format_html_value(prediction['mean_hit_at_3']))} | Opt F1: {escape(_format_html_value(prediction['mean_threshold_optimized_f1']))} | Objective: {escape(_format_html_value(prediction['mean_objective_score']))} | AUC: {escape(_format_html_value(prediction['mean_auc']))} | PR-AUC: {escape(_format_html_value(prediction['mean_pr_auc']))}</p>
                  <table>
                    <tr><th>Entity</th><th>Probability</th><th>Label</th></tr>
                    {rows_html}
                  </table>
                </section>
                """
            )

        body = f"""
        <section class="hero">
          <p class="eyebrow">Store Optimized Pipeline</p>
          <h1>{escape(str(forecast_payload['store_id']))} / {escape(str(forecast_payload['grouping']))}</h1>
          <p class="lede">Next-day forecast generated from historical features only.</p>
          <p>Source latest date: {escape(str(forecast_payload['source_latest_date']))}</p>
          <p>Target date: {escape(str(forecast_payload['target_date']))}</p>
        </section>
        {''.join(sections)}
        """
        return render_html_page(
            title=f"{forecast_payload['store_id']} / {forecast_payload['grouping']} forecast",
            body=body,
        )

    def _render_grouping_summary_html(
        self,
        *,
        store_id: str,
        grouping: str,
        summary_payload: dict[str, Any],
        leaderboard_df: pd.DataFrame,
    ) -> str:
        best_rows = "".join(
            f"<tr><th>{target}</th><td>{escape(str(best.get('model', '-')))}</td>"
            f"<td>{escape(str(best.get('merge_mode', '-')))}</td>"
            f"<td>{escape(str(best.get('cv_mode', '-')))}</td>"
            f"<td>{escape(str(best.get('selection_metric', '-')))}</td>"
            f"<td>{escape(_format_html_value(best.get('selection_score')))}</td>"
            f"<td>{escape(_format_html_value(best.get('mean_hit_at_1')))}</td>"
            f"<td>{escape(_format_html_value(best.get('mean_hit_at_3')))}</td>"
            f"<td>{escape(_format_html_value(best.get('mean_threshold_optimized_f1')))}</td>"
            f"<td>{escape(_format_html_value(best.get('mean_threshold_optimized_recall')))}</td>"
            f"<td>{escape(_format_html_value(best.get('mean_threshold_optimized_precision')))}</td>"
            f"<td>{escape(_format_html_value(best.get('mean_objective_score')))}</td>"
            f"<td>{escape(_format_html_value(best.get('mean_auc')))}</td>"
            f"<td>{escape(_format_html_value(best.get('mean_pr_auc')))}</td></tr>"
            for target, best in summary_payload.get("best_by_target", {}).items()
        ) or "<tr><th>No data</th><td colspan='12'>-</td></tr>"

        leaderboard_rows = "".join(
            f"<tr><td>{escape(str(row.target))}</td><td>{escape(str(row.merge_mode))}</td>"
            f"<td>{escape(str(row.cv_mode))}</td><td>{escape(str(row.model))}</td>"
            f"<td>{escape(str(row.selection_metric))}</td>"
            f"<td>{escape(_format_html_value(row.selection_score))}</td>"
            f"<td>{escape(_format_html_value(row.mean_hit_at_1))}</td>"
            f"<td>{escape(_format_html_value(row.mean_hit_at_3))}</td>"
            f"<td>{escape(_format_html_value(row.mean_threshold_optimized_f1))}</td>"
            f"<td>{escape(_format_html_value(row.mean_threshold_optimized_recall))}</td>"
            f"<td>{escape(_format_html_value(row.mean_threshold_optimized_precision))}</td>"
            f"<td>{escape(_format_html_value(row.mean_objective_score))}</td>"
            f"<td>{escape(_format_html_value(row.mean_auc))}</td>"
            f"<td>{escape(_format_html_value(row.mean_pr_auc))}</td>"
            f"<td>{escape(_format_html_value(row.mean_zero_recall_penalty))}</td></tr>"
            for row in leaderboard_df.itertuples(index=False)
        ) or "<tr><td colspan='15'>No evaluations</td></tr>"

        selection_cards = []
        importance_cards = []
        for run in summary_payload.get("runs", []):
            selection = run.get("feature_selection") or {}
            stable = selection.get("stable_features") or selection.get("selected_features") or []
            if not stable:
                continue
            card = (
                f"<section><h2>{escape(str(run['target']))} / {escape(str(run['model']))} / "
                f"{escape(str(run['merge_mode']))} / {escape(str(run['cv_mode']))}</h2>"
                f"<p>Selected Features: {escape(', '.join(stable[:12]))}</p></section>"
            )
            selection_cards.append(card)

            top_importance_rows = selection.get("top_features_by_permutation") or selection.get("top_features") or []
            if top_importance_rows:
                importance_cards.append(
                    "<section><h2>"
                    + escape(str(run["target"]))
                    + " / "
                    + escape(str(run["model"]))
                    + " / "
                    + escape(str(run["merge_mode"]))
                    + " / "
                    + escape(str(run["cv_mode"]))
                    + "</h2><p>Feature Importance: "
                    + escape(", ".join(item["feature"] for item in top_importance_rows[:8]))
                    + "</p></section>"
                )

        body = f"""
        <section class="hero">
          <p class="eyebrow">Store Optimized Pipeline</p>
          <h1>{escape(store_id)} / {escape(grouping)}</h1>
          <p class="lede">Human-facing overview of best model configurations, comparison leaderboard, and automatically selected features.</p>
        </section>

        <section>
          <h2>Best Configuration</h2>
          <table>
            <tr><th>Target</th><th>Model</th><th>Merge Mode</th><th>CV</th><th>Metric</th><th>Score</th><th>Hit@1</th><th>Hit@3</th><th>Opt F1</th><th>Opt Recall</th><th>Opt Precision</th><th>Objective</th><th>AUC</th><th>PR-AUC</th></tr>
            {best_rows}
          </table>
        </section>

        <section>
          <h2>Leaderboard</h2>
          <table>
            <tr><th>Target</th><th>Merge Mode</th><th>CV</th><th>Model</th><th>Metric</th><th>Score</th><th>Hit@1</th><th>Hit@3</th><th>Opt F1</th><th>Opt Recall</th><th>Opt Precision</th><th>Objective</th><th>AUC</th><th>PR-AUC</th><th>Zero Recall Penalty</th></tr>
            {leaderboard_rows}
          </table>
        </section>

        <section>
          <h2>Feature Importance</h2>
          {''.join(importance_cards) or '<p>No feature-importance summaries available.</p>'}
        </section>

        {''.join(selection_cards)}
        """
        return render_html_page(title=f"{store_id} / {grouping}", body=body)


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
