"""Pipeline configuration and data classes."""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


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
ABLATION_WORST_FEATURE_KEYWORDS = ("worst",)
ABLATION_WORST_RECENCY_PREFIXES = ("days_since_last_worst",)
ABLATION_WORST_STREAK_PREFIXES = ("worst1_streak", "worst3_streak", "worst5_streak")
ABLATION_WORST_RATE_KEYWORDS = (
    "worst",
    "after_event",
    "same_weekday_worst",
    "same_day_of_month_worst",
    "prior_worst",
)
ABLATION_MOMVOL_FEATURE_PREFIXES = ("rolling_std_", "ewm_", "diff_zscore_")
ABLATION_SAME_DAY_OF_MONTH_PREFIXES = ("same_day_of_month_",)
ABLATION_SAME_WEEKDAY_PREFIXES = ("same_weekday_",)
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
    groupings: list[str] = field(default_factory=lambda: ["machine_type", "last_digit", "machine_number_position"])
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
