from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from xgboost import XGBRanker

from ml.evaluators.metrics import calculate_hit_at_k
from ml.last_digit.dataset_bridge import build_last_digit_dataset
from ml.last_digit import core_features as features_core
from ml.last_digit import core_ranking as ranking_core
from ml.last_digit.utils import NDCG_RANDOM_STATE_OFFSET

logger = logging.getLogger(__name__)

REGIME_1_START = "2025-07-07"
REGIME_1_END = "2025-10-31"
REGIME_2_START = "2025-11-01"
REGIME_2_END = "2025-12-31"
REGIME_3_START = "2026-01-01"
OPENING_EARLY_END = "2025-08-31"
REGIME_2_HALF_END = "2025-11-30"
METRIC_KEYS = (
    "hit_at_1",
    "hit_at_2",
    "hit_at_3",
    "ndcg_at_2",
    "ndcg_at_3",
    "spearman",
    "abstain_coverage",
    "abstain_hit_at_1",
)


# ============================================================================
# Configuration Classes
# ============================================================================


@dataclass
class CalibrationConfig:
    """Temperature scaling and blending configuration."""
    temperature_candidates: tuple[float, ...] = (0.5, 0.8, 1.0, 1.3, 1.8, 2.5)
    blend_weights: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0)
    abstain_quantiles: tuple[float, ...] = (0.2, 0.4, 0.6)


@dataclass
class RegimeFeatureConfig:
    """Regime detection and clustering feature weights."""
    efficiency_weight: float = 0.6
    diff_weight: float = 0.3
    event_weight: float = 0.1


@dataclass
class TwoStageConfig:
    """Two-stage reranking configuration for top-k targets."""
    enable_top3: bool = False
    candidate_factor: int = 2


@dataclass
class FoldResult:
    """Single fold evaluation result."""
    hit_at_1: float
    hit_at_2: float
    hit_at_3: float
    ndcg_at_2: float
    ndcg_at_3: float
    spearman: float
    abstain_coverage: float
    abstain_hit_at_1: float
    blend_weight: float = 0.5
    abstain_quantile: float = 0.4


# ============================================================================
# Feature Engineering
# ============================================================================


def add_top2_target(dataset: pd.DataFrame) -> pd.DataFrame:
    """Add is_top_2 binary target."""
    return features_core.add_top2_target(dataset)


def add_regime_and_cluster_features(
    dataset: pd.DataFrame, config: RegimeFeatureConfig | None = None
) -> pd.DataFrame:
    """Add regime proxies and tail cluster features."""
    return features_core.add_regime_and_cluster_features(dataset, config)



def get_numeric_features(df: pd.DataFrame) -> list[str]:
    """Extract numeric feature columns."""
    return features_core.get_numeric_features(df)


# ============================================================================
# Time-Series Folding
# ============================================================================


def create_date_folds(
    unique_dates: list[pd.Timestamp], n_splits: int, valid_days: int
) -> list[tuple[list[pd.Timestamp], list[pd.Timestamp]]]:
    """Create temporal cross-validation folds."""
    return features_core.create_date_folds(unique_dates, n_splits, valid_days)


# ============================================================================
# Scoring & Metrics
# ============================================================================


def sigmoid(x: np.ndarray, temperature: float) -> np.ndarray:
    """Temperature-scaled sigmoid."""
    return ranking_core.sigmoid(x, temperature)


def ndcg_at_k(y_true: np.ndarray, y_pred: np.ndarray, group_ids: np.ndarray, k: int) -> float:
    """Compute NDCG@k per group, return mean."""
    return ranking_core.ndcg_at_k(y_true, y_pred, group_ids, k)


def spearman_by_group(y_true: np.ndarray, y_pred: np.ndarray, group_ids: np.ndarray) -> float:
    """Compute mean Spearman correlation across groups, skipping undefined groups."""
    return ranking_core.spearman_by_group(y_true, y_pred, group_ids)


def find_best_temperature(
    y: np.ndarray, raw: np.ndarray, groups: np.ndarray, candidates: tuple[float, ...]
) -> float:
    """Grid search for best temperature scaling."""
    return ranking_core.find_best_temperature(y, raw, groups, candidates)


def evaluate_with_abstain(
    y: np.ndarray, score: np.ndarray, dates: np.ndarray, abstain_quantile: float = 0.4
) -> tuple[float, float]:
    """Evaluate hit@1 with abstention threshold selection."""
    return ranking_core.evaluate_with_abstain(y, score, dates, abstain_quantile)


def two_stage_candidate_rerank(
    *,
    stage1_score: np.ndarray,
    stage2_score: np.ndarray,
    group_ids: np.ndarray,
    top_k: int,
    candidate_factor: int,
) -> np.ndarray:
    """Filter by stage1 top-M candidates and rerank by stage2 scores."""
    if top_k <= 0:
        return stage2_score
    factor = max(1, int(candidate_factor))
    output = np.full(len(stage2_score), -1e9, dtype=float)
    unique_groups = pd.Index(group_ids).drop_duplicates()
    for gid in unique_groups:
        group_idx = np.where(group_ids == gid)[0]
        if len(group_idx) == 0:
            continue
        candidate_size = min(len(group_idx), max(top_k, top_k * factor))
        local_stage1 = stage1_score[group_idx]
        top_local = np.argsort(-local_stage1)[:candidate_size]
        keep_idx = group_idx[top_local]
        output[keep_idx] = stage2_score[keep_idx]
    return output


# ============================================================================
# Model Training
# ============================================================================


def fit_ranker(
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    train_dates: pd.Series,
    *,
    objective: str,
    random_state: int,
    decay_lambda: float | None = None,
    model_params: dict[str, Any] | None = None,
) -> XGBRanker:
    """Fit XGBRanker with optional time-decay weighting."""
    return ranking_core.fit_ranker(
        X_train=X_train,
        y_train=y_train,
        train_dates=train_dates,
        objective=objective,
        random_state=random_state,
        decay_lambda=decay_lambda,
        model_params=model_params,
    )


# ============================================================================
# Calibration & Blending
# ============================================================================


def select_blend_and_abstain(
    *,
    target: str,
    y_cal: np.ndarray,
    cal_pair: np.ndarray,
    cal_ndcg: np.ndarray,
    cal_dates: np.ndarray,
    config: CalibrationConfig,
) -> tuple[float, float]:
    """Grid search for optimal blend weight and abstention quantile."""
    best_w = 0.5
    best_q = 0.4
    best_score = -1.0

    for w in config.blend_weights:
        pred = w * cal_pair + (1.0 - w) * cal_ndcg
        for q in config.abstain_quantiles:
            _, abst_h1 = evaluate_with_abstain(y_cal, pred, cal_dates, abstain_quantile=q)
            score = _calibration_score(target, y_cal, pred, cal_dates, abst_h1)
            if score > best_score:
                best_score = score
                best_w = w
                best_q = q

    return float(best_w), float(best_q)


def _calibration_score(target: str, y: np.ndarray, pred: np.ndarray, dates: np.ndarray, abst_h1: float) -> float:
    hit1 = calculate_hit_at_k(y, pred, dates, k=1)
    hit3 = calculate_hit_at_k(y, pred, dates, k=3)
    nd2 = ndcg_at_k(y, pred, dates, k=2)
    nd3 = ndcg_at_k(y, pred, dates, k=3)

    if target == "is_rank_1":
        return 0.8 * hit1 + 0.2 * abst_h1
    if target == "is_top_2":
        return 0.6 * nd2 + 0.4 * hit1
    return 0.6 * hit3 + 0.4 * nd3


def _choose_blend_weight(
    *,
    target: str,
    y_cal: np.ndarray,
    cal_pair: np.ndarray,
    cal_ndcg: np.ndarray,
    cal_dates: np.ndarray,
    config: CalibrationConfig,
) -> float:
    best_w = 0.5
    best_score = -1.0
    for w in config.blend_weights:
        pred = w * cal_pair + (1.0 - w) * cal_ndcg
        score = _calibration_score(target, y_cal, pred, cal_dates, abst_h1=0.0)
        if score > best_score:
            best_score = score
            best_w = w
    return float(best_w)


def _choose_abstain_quantile(
    *,
    target: str,
    y_cal: np.ndarray,
    pred: np.ndarray,
    cal_dates: np.ndarray,
    config: CalibrationConfig,
) -> float:
    best_q = 0.4
    best_score = -1.0
    for q in config.abstain_quantiles:
        _, abst_h1 = evaluate_with_abstain(y_cal, pred, cal_dates, abstain_quantile=q)
        score = _calibration_score(target, y_cal, pred, cal_dates, abst_h1)
        if score > best_score:
            best_score = score
            best_q = q
    return float(best_q)


def _split_calibration_by_date(cal_df: pd.DataFrame, *, min_unique_dates: int = 4) -> tuple[pd.DataFrame, pd.DataFrame]:
    unique_dates = pd.Index(pd.to_datetime(cal_df["date"]).drop_duplicates().sort_values())
    if len(unique_dates) < min_unique_dates:
        logger.warning(
            "Calibration split fallback: unique_dates=%d (<%d), reusing same set for blend/threshold",
            len(unique_dates),
            min_unique_dates,
        )
        return cal_df, cal_df

    split_idx = len(unique_dates) // 2
    if split_idx <= 0 or split_idx >= len(unique_dates):
        logger.warning("Calibration split fallback: invalid split_idx=%d", split_idx)
        return cal_df, cal_df

    blend_days = set(unique_dates[:split_idx])
    threshold_days = set(unique_dates[split_idx:])
    cal_blend = cal_df[cal_df["date"].isin(blend_days)].copy()
    cal_threshold = cal_df[cal_df["date"].isin(threshold_days)].copy()
    if cal_blend.empty or cal_threshold.empty:
        logger.warning("Calibration split fallback: empty partition (blend=%d, threshold=%d)", len(cal_blend), len(cal_threshold))
        return cal_df, cal_df
    return cal_blend, cal_threshold


# ============================================================================
# Baseline
# ============================================================================


def compute_random_baseline(
    y_true: np.ndarray, group_ids: np.ndarray, rng: np.random.Generator, trials: int = 200
) -> dict[str, float]:
    """Compute random baseline via multiple random scores."""
    rows = []
    for _ in range(trials):
        random_scores = rng.random(len(y_true))
        rows.append(
            {
                "hit_at_1": calculate_hit_at_k(y_true, random_scores, group_ids, k=1),
                "hit_at_2": calculate_hit_at_k(y_true, random_scores, group_ids, k=2),
                "hit_at_3": calculate_hit_at_k(y_true, random_scores, group_ids, k=3),
                "ndcg_at_2": ndcg_at_k(y_true, random_scores, group_ids, k=2),
                "ndcg_at_3": ndcg_at_k(y_true, random_scores, group_ids, k=3),
                "spearman": spearman_by_group(y_true, random_scores, group_ids),
            }
        )
    result = {k: float(np.mean([r[k] for r in rows])) for k in rows[0].keys()}
    result["abstain_coverage"] = 0.0
    result["abstain_hit_at_1"] = 0.0
    return result


def zero_metrics() -> dict[str, float]:
    """Standard zero-filled metric dictionary."""
    return {key: 0.0 for key in METRIC_KEYS}


def metrics_from_fold_result(result: FoldResult) -> dict[str, float]:
    """Convert a fold result dataclass into a metrics dictionary."""
    return {
        "hit_at_1": float(result.hit_at_1),
        "hit_at_2": float(result.hit_at_2),
        "hit_at_3": float(result.hit_at_3),
        "ndcg_at_2": float(result.ndcg_at_2),
        "ndcg_at_3": float(result.ndcg_at_3),
        "spearman": float(result.spearman),
        "abstain_coverage": float(result.abstain_coverage),
        "abstain_hit_at_1": float(result.abstain_hit_at_1),
    }


def build_fixed_split_configs(dataset: pd.DataFrame) -> dict[str, dict[str, str]]:
    """Return named fixed regime splits using the dataset's latest available date."""
    latest_ts = pd.to_datetime(dataset["date"]).max()
    latest_date = latest_ts.strftime("%Y-%m-%d")
    regime_3_start_ts = pd.Timestamp(REGIME_3_START)
    recent_90_start = max(regime_3_start_ts, latest_ts - pd.Timedelta(days=89)).strftime("%Y-%m-%d")
    recent_60_start = max(regime_3_start_ts, latest_ts - pd.Timedelta(days=59)).strftime("%Y-%m-%d")
    return {
        "regime_fixed_split": {
            "train_start": REGIME_1_START,
            "train_end": REGIME_1_END,
            "valid_start": REGIME_2_START,
            "valid_end": REGIME_2_END,
        },
        "regime_3_fixed_split": {
            "train_start": REGIME_1_START,
            "train_end": REGIME_2_END,
            "valid_start": REGIME_3_START,
            "valid_end": latest_date,
        },
        "recent_90d_standard": {
            "train_start": REGIME_1_START,
            "train_end": REGIME_2_END,
            "valid_start": recent_90_start,
            "valid_end": latest_date,
        },
        "recent_60d_standard": {
            "train_start": REGIME_1_START,
            "train_end": REGIME_2_END,
            "valid_start": recent_60_start,
            "valid_end": latest_date,
        },
    }


def build_window_sweep_configs(*, valid_start: str) -> dict[str, dict[str, str]]:
    """Return train-window candidates that end before the validation period starts."""
    valid_start_ts = pd.Timestamp(valid_start)
    recent_90_start = (valid_start_ts - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
    recent_60_start = (valid_start_ts - pd.Timedelta(days=60)).strftime("%Y-%m-%d")
    candidates = {
        "opening_early": {"train_start": REGIME_1_START, "train_end": OPENING_EARLY_END},
        "regime1_full": {"train_start": REGIME_1_START, "train_end": REGIME_1_END},
        "opening_plus_half_transition": {"train_start": REGIME_1_START, "train_end": REGIME_2_HALF_END},
        "full_2025": {"train_start": REGIME_1_START, "train_end": REGIME_2_END},
        "regime2_only": {"train_start": REGIME_2_START, "train_end": REGIME_2_END},
        "recent_90d": {"train_start": recent_90_start, "train_end": (valid_start_ts - pd.Timedelta(days=1)).strftime("%Y-%m-%d")},
        "recent_60d": {"train_start": recent_60_start, "train_end": (valid_start_ts - pd.Timedelta(days=1)).strftime("%Y-%m-%d")},
    }
    filtered: dict[str, dict[str, str]] = {}
    seen_ranges: set[tuple[str, str]] = set()
    for name, config in candidates.items():
        train_start_ts = pd.Timestamp(config["train_start"])
        train_end_ts = pd.Timestamp(config["train_end"])
        if train_end_ts >= valid_start_ts or train_start_ts > train_end_ts:
            continue
        train_range = (config["train_start"], config["train_end"])
        if train_range in seen_ranges:
            continue
        filtered[name] = config
        seen_ranges.add(train_range)
    return filtered


def split_dataset_by_date_ranges(
    dataset: pd.DataFrame,
    *,
    train_start: str,
    train_end: str,
    valid_start: str,
    valid_end: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split a dataset by inclusive date ranges."""
    dates = pd.to_datetime(dataset["date"])
    train_mask = (dates >= pd.Timestamp(train_start)) & (dates <= pd.Timestamp(train_end))
    valid_mask = (dates >= pd.Timestamp(valid_start)) & (dates <= pd.Timestamp(valid_end))
    sort_cols = ["date", "entity_key"] if "entity_key" in dataset.columns else ["date"]
    train = dataset.loc[train_mask].sort_values(sort_cols).reset_index(drop=True)
    valid = dataset.loc[valid_mask].sort_values(sort_cols).reset_index(drop=True)
    return train, valid


def evaluate_train_valid_split(
    train: pd.DataFrame,
    valid: pd.DataFrame,
    *,
    target: str,
    features: list[str],
    random_state: int,
    decay_lambda: float | None,
    calibration_config: CalibrationConfig,
    rng: np.random.Generator,
    two_stage_config: TwoStageConfig | None = None,
) -> tuple[FoldResult, dict[str, float]]:
    """Evaluate one explicit train/validation split."""
    train_dates = sorted(pd.to_datetime(train["date"].unique()))
    if two_stage_config is None:
        two_stage_config = TwoStageConfig()

    calib_cut = max(1, int(len(train_dates) * 0.85))
    fit_days = set(train_dates[:calib_cut])
    cal_days = set(train_dates[calib_cut:])
    fit_df = train[train["date"].isin(fit_days)] if cal_days else train
    cal_df = train[train["date"].isin(cal_days)] if cal_days else train.tail(min(200, len(train)))

    X_fit = fit_df[features].astype(float)
    y_fit = fit_df[target].astype(int).to_numpy()
    X_cal = cal_df[features].astype(float)
    y_cal = cal_df[target].astype(int).to_numpy()
    X_valid = valid[features].astype(float)
    y_valid = valid[target].astype(int).to_numpy()

    rank1_decay = decay_lambda
    if decay_lambda is not None:
        pair_no_decay = fit_ranker(
            X_fit, y_fit, fit_df["date"],
            objective="rank:pairwise", random_state=random_state, decay_lambda=None,
        )
        pair_with_decay = fit_ranker(
            X_fit, y_fit, fit_df["date"],
            objective="rank:pairwise", random_state=random_state + 17, decay_lambda=decay_lambda,
        )

        cal_no_decay = sigmoid(pair_no_decay.predict(X_cal), 1.0)
        cal_with_decay = sigmoid(pair_with_decay.predict(X_cal), 1.0)
        cal_dates_np = cal_df["date"].to_numpy()

        metric_no_decay = (
            calculate_hit_at_k(y_cal, cal_no_decay, cal_dates_np, 1) if target == "is_rank_1"
            else ndcg_at_k(y_cal, cal_no_decay, cal_dates_np, 2) if target == "is_top_2"
            else calculate_hit_at_k(y_cal, cal_no_decay, cal_dates_np, 3)
        )
        metric_with_decay = (
            calculate_hit_at_k(y_cal, cal_with_decay, cal_dates_np, 1) if target == "is_rank_1"
            else ndcg_at_k(y_cal, cal_with_decay, cal_dates_np, 2) if target == "is_top_2"
            else calculate_hit_at_k(y_cal, cal_with_decay, cal_dates_np, 3)
        )
        rank1_decay = decay_lambda if metric_with_decay >= metric_no_decay else None

    pair = fit_ranker(
        X_fit, y_fit, fit_df["date"],
        objective="rank:pairwise", random_state=random_state, decay_lambda=rank1_decay,
    )
    ndcg = fit_ranker(
        X_fit, y_fit, fit_df["date"],
        objective="rank:ndcg", random_state=random_state + NDCG_RANDOM_STATE_OFFSET,
        decay_lambda=rank1_decay if target == "is_rank_1" else decay_lambda,
    )

    cal_blend_df, cal_threshold_df = _split_calibration_by_date(cal_df)
    X_cal_blend = cal_blend_df[features].astype(float)
    y_cal_blend = cal_blend_df[target].astype(int).to_numpy()
    dates_cal_blend = cal_blend_df["date"].to_numpy()

    X_cal_threshold = cal_threshold_df[features].astype(float)
    y_cal_threshold = cal_threshold_df[target].astype(int).to_numpy()
    dates_cal_threshold = cal_threshold_df["date"].to_numpy()

    raw_cal_pair = pair.predict(X_cal_blend)
    raw_cal_ndcg = ndcg.predict(X_cal_blend)
    raw_val_pair = pair.predict(X_valid)
    raw_val_ndcg = ndcg.predict(X_valid)

    t_pair = find_best_temperature(y_cal_blend, raw_cal_pair, dates_cal_blend, calibration_config.temperature_candidates)
    t_ndcg = find_best_temperature(y_cal_blend, raw_cal_ndcg, dates_cal_blend, calibration_config.temperature_candidates)

    cal_pair = sigmoid(raw_val_pair, t_pair)
    cal_ndcg = sigmoid(raw_val_ndcg, t_ndcg)

    cal_pair_prob = sigmoid(raw_cal_pair, t_pair)
    cal_ndcg_prob = sigmoid(raw_cal_ndcg, t_ndcg)
    w_pair = _choose_blend_weight(
        target=target,
        y_cal=y_cal_blend,
        cal_pair=cal_pair_prob,
        cal_ndcg=cal_ndcg_prob,
        cal_dates=dates_cal_blend,
        config=calibration_config,
    )
    raw_threshold_pair = pair.predict(X_cal_threshold)
    raw_threshold_ndcg = ndcg.predict(X_cal_threshold)
    threshold_pair = sigmoid(raw_threshold_pair, t_pair)
    threshold_ndcg = sigmoid(raw_threshold_ndcg, t_ndcg)
    threshold_pred = w_pair * threshold_pair + (1.0 - w_pair) * threshold_ndcg
    abst_q = _choose_abstain_quantile(
        target=target,
        y_cal=y_cal_threshold,
        pred=threshold_pred,
        cal_dates=dates_cal_threshold,
        config=calibration_config,
    )
    pred = w_pair * cal_pair + (1.0 - w_pair) * cal_ndcg

    valid_dates_np = valid["date"].to_numpy()
    if target == "is_top_3" and two_stage_config.enable_top3:
        pred = two_stage_candidate_rerank(
            stage1_score=cal_pair,
            stage2_score=pred,
            group_ids=valid_dates_np,
            top_k=3,
            candidate_factor=two_stage_config.candidate_factor,
        )
    cov, abst_h1 = evaluate_with_abstain(y_valid, pred, valid_dates_np, abstain_quantile=abst_q)
    fold_result = FoldResult(
        hit_at_1=calculate_hit_at_k(y_valid, pred, valid_dates_np, k=1),
        hit_at_2=calculate_hit_at_k(y_valid, pred, valid_dates_np, k=2),
        hit_at_3=calculate_hit_at_k(y_valid, pred, valid_dates_np, k=3),
        ndcg_at_2=ndcg_at_k(y_valid, pred, valid_dates_np, k=2),
        ndcg_at_3=ndcg_at_k(y_valid, pred, valid_dates_np, k=3),
        spearman=spearman_by_group(y_valid, pred, valid_dates_np),
        abstain_coverage=cov,
        abstain_hit_at_1=abst_h1,
        blend_weight=w_pair,
        abstain_quantile=abst_q,
    )
    return fold_result, compute_random_baseline(y_valid, valid_dates_np, rng)


# ============================================================================
# Evaluation Pipeline
# ============================================================================


def evaluate_mode(
    dataset: pd.DataFrame,
    *,
    target: str,
    features: list[str],
    n_splits: int,
    valid_days: int,
    random_state: int,
    decay_lambda: float | None = None,
    calibration_config: CalibrationConfig | None = None,
    two_stage_config: TwoStageConfig | None = None,
) -> dict[str, Any]:
    """Evaluate single target with optional time-decay."""
    if calibration_config is None:
        calibration_config = CalibrationConfig()

    unique_dates = sorted(pd.to_datetime(dataset["date"].unique()))
    folds = create_date_folds(unique_dates, n_splits=n_splits, valid_days=valid_days)
    rng = np.random.default_rng(random_state)
    fold_results: list[FoldResult] = []
    random_fold_results: list[dict[str, float]] = []

    for fold_id, (train_dates, valid_dates) in enumerate(folds):
        logger.debug(f"{target} fold {fold_id + 1}/{len(folds)}")

        train = dataset[dataset["date"].isin(train_dates)].sort_values(["date", "entity_key"]).reset_index(drop=True)
        valid = dataset[dataset["date"].isin(valid_dates)].sort_values(["date", "entity_key"]).reset_index(drop=True)
        fold_result, random_result = evaluate_train_valid_split(
            train,
            valid,
            target=target,
            features=features,
            random_state=random_state,
            decay_lambda=decay_lambda,
            calibration_config=calibration_config,
            two_stage_config=two_stage_config,
            rng=rng,
        )
        fold_results.append(fold_result)
        random_fold_results.append(random_result)

    def aggregate(rows: list[FoldResult]) -> dict[str, float]:
        if not rows:
            return zero_metrics()
        return {key: float(np.mean([metrics_from_fold_result(r)[key] for r in rows])) for key in METRIC_KEYS}

    def aggregate_std(rows: list[FoldResult]) -> dict[str, float]:
        if not rows:
            return zero_metrics()
        return {key: float(np.std([metrics_from_fold_result(r)[key] for r in rows])) for key in METRIC_KEYS}

    def aggregate_dict(rows: list[dict[str, float]]) -> dict[str, float]:
        if not rows:
            return zero_metrics()
        return {k: float(np.mean([r[k] for r in rows])) for k in rows[0].keys()}

    metrics = aggregate(fold_results)
    metrics_std = aggregate_std(fold_results)
    random_metrics = aggregate_dict(random_fold_results)
    lift = {k: (metrics[k] - random_metrics.get(k, 0.0)) for k in metrics.keys() if k in random_metrics}

    return {
        "target": target,
        "metrics": metrics,
        "metrics_std": metrics_std,
        "random_baseline": random_metrics,
        "lift_vs_random": lift,
        "n_folds": len(fold_results),
    }


def evaluate_fixed_split(
    dataset: pd.DataFrame,
    *,
    target: str,
    features: list[str],
    random_state: int,
    decay_lambda: float | None = None,
    calibration_config: CalibrationConfig | None = None,
    two_stage_config: TwoStageConfig | None = None,
    train_start: str,
    train_end: str,
    valid_start: str,
    valid_end: str,
) -> dict[str, Any]:
    """Evaluate one fixed train/validation regime split."""
    if calibration_config is None:
        calibration_config = CalibrationConfig()

    train, valid = split_dataset_by_date_ranges(
        dataset,
        train_start=train_start,
        train_end=train_end,
        valid_start=valid_start,
        valid_end=valid_end,
    )
    split_summary = {
        "train_start": train_start,
        "train_end": train_end,
        "valid_start": valid_start,
        "valid_end": valid_end,
        "train_rows": int(len(train)),
        "valid_rows": int(len(valid)),
        "train_days": int(train["date"].nunique()) if not train.empty else 0,
        "valid_days": int(valid["date"].nunique()) if not valid.empty else 0,
    }

    if train.empty or valid.empty:
        metrics = zero_metrics()
        return {
            "target": target,
            "metrics": metrics,
            "metrics_std": metrics.copy(),
            "random_baseline": metrics.copy(),
            "lift_vs_random": metrics.copy(),
            "n_folds": 0,
            "split_summary": split_summary,
        }

    rng = np.random.default_rng(random_state)
    fold_result, random_result = evaluate_train_valid_split(
        train,
        valid,
        target=target,
        features=features,
        random_state=random_state,
        decay_lambda=decay_lambda,
        calibration_config=calibration_config,
        two_stage_config=two_stage_config,
        rng=rng,
    )
    metrics = metrics_from_fold_result(fold_result)
    lift = {k: (metrics[k] - random_result.get(k, 0.0)) for k in metrics.keys()}
    return {
        "target": target,
        "metrics": metrics,
        "metrics_std": zero_metrics(),
        "random_baseline": random_result,
        "lift_vs_random": lift,
        "n_folds": 1,
        "split_summary": split_summary,
    }


def parse_lambda_sweep_values(raw: str | None) -> list[float]:
    """Parse comma-separated lambda values for sweep execution."""
    if raw is None or not raw.strip():
        return []
    return [float(token.strip()) for token in raw.split(",") if token.strip()]


def parse_target_values(raw: str | None) -> list[str]:
    """Parse comma-separated target names."""
    if raw is None or not raw.strip():
        return []
    return [token.strip() for token in raw.split(",") if token.strip()]


def selection_metric_for_target(target: str) -> str:
    """Return the primary comparison metric for each target."""
    if target == "is_rank_1":
        return "hit_at_1"
    if target == "is_top_2":
        return "hit_at_2"
    return "hit_at_3"


def run_lambda_sweep(
    dataset: pd.DataFrame,
    *,
    target: str,
    features: list[str],
    n_splits: int,
    valid_days: int,
    random_state: int,
    calibration_config: CalibrationConfig,
    lambda_values: list[float],
    two_stage_config: TwoStageConfig | None = None,
) -> dict[str, Any]:
    """Evaluate multiple decay lambdas and select the best one for the target."""
    selection_metric = selection_metric_for_target(target)
    candidates: list[dict[str, Any]] = []

    for lambda_value in lambda_values:
        evaluation = evaluate_mode(
            dataset,
            target=target,
            features=features,
            n_splits=n_splits,
            valid_days=valid_days,
            random_state=random_state,
            decay_lambda=lambda_value,
            calibration_config=calibration_config,
            two_stage_config=two_stage_config,
        )
        candidates.append(
            {
                "lambda": float(lambda_value),
                **evaluation,
            }
        )

    if not candidates:
        return {
            "selection_metric": selection_metric,
            "candidates": [],
            "best_lambda": None,
            "best_score": None,
        }

    best_candidate = max(candidates, key=lambda row: row["metrics"].get(selection_metric, float("-inf")))
    return {
        "selection_metric": selection_metric,
        "candidates": candidates,
        "best_lambda": float(best_candidate["lambda"]),
        "best_score": float(best_candidate["metrics"][selection_metric]),
    }


def run_fixed_lambda_sweep(
    dataset: pd.DataFrame,
    *,
    target: str,
    features: list[str],
    random_state: int,
    calibration_config: CalibrationConfig,
    lambda_values: list[float],
    two_stage_config: TwoStageConfig | None = None,
    train_start: str,
    train_end: str,
    valid_start: str,
    valid_end: str,
) -> dict[str, Any]:
    """Evaluate multiple lambdas on one fixed regime split."""
    selection_metric = selection_metric_for_target(target)
    candidates: list[dict[str, Any]] = []

    for lambda_value in lambda_values:
        evaluation = evaluate_fixed_split(
            dataset,
            target=target,
            features=features,
            random_state=random_state,
            decay_lambda=lambda_value,
            calibration_config=calibration_config,
            two_stage_config=two_stage_config,
            train_start=train_start,
            train_end=train_end,
            valid_start=valid_start,
            valid_end=valid_end,
        )
        candidates.append({"lambda": float(lambda_value), **evaluation})

    if not candidates:
        return {
            "selection_metric": selection_metric,
            "candidates": [],
            "best_lambda": None,
            "best_score": None,
        }

    best_candidate = max(candidates, key=lambda row: row["metrics"].get(selection_metric, float("-inf")))
    return {
        "selection_metric": selection_metric,
        "candidates": candidates,
        "best_lambda": float(best_candidate["lambda"]),
        "best_score": float(best_candidate["metrics"][selection_metric]),
    }


def run_fixed_window_sweep(
    dataset: pd.DataFrame,
    *,
    target: str,
    features: list[str],
    random_state: int,
    decay_lambda: float | None,
    calibration_config: CalibrationConfig,
    two_stage_config: TwoStageConfig | None = None,
    train_windows: dict[str, dict[str, str]],
    valid_start: str,
    valid_end: str,
) -> dict[str, Any]:
    """Evaluate multiple train windows for one fixed validation period."""
    selection_metric = selection_metric_for_target(target)
    candidates: list[dict[str, Any]] = []

    for window_name, train_window in train_windows.items():
        evaluation = evaluate_fixed_split(
            dataset,
            target=target,
            features=features,
            random_state=random_state,
            decay_lambda=decay_lambda,
            calibration_config=calibration_config,
            two_stage_config=two_stage_config,
            train_start=train_window["train_start"],
            train_end=train_window["train_end"],
            valid_start=valid_start,
            valid_end=valid_end,
        )
        candidates.append(
            {
                "window_name": window_name,
                "train_start": train_window["train_start"],
                "train_end": train_window["train_end"],
                **evaluation,
            }
        )

    if not candidates:
        return {
            "selection_metric": selection_metric,
            "candidates": [],
            "best_window": None,
            "best_score": None,
        }

    best_candidate = max(candidates, key=lambda row: row["metrics"].get(selection_metric, float("-inf")))
    return {
        "selection_metric": selection_metric,
        "candidates": candidates,
        "best_window": str(best_candidate["window_name"]),
        "best_score": float(best_candidate["metrics"][selection_metric]),
    }


# ============================================================================
# Main
# ============================================================================


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Improved Time-adaptive LTR PoC for last_digit")
    p.add_argument("--db-path", required=True, help="Path to database")
    p.add_argument("--output", default="db/experiments/tail_ltr_poc_result.json", help="Output JSON path")
    p.add_argument("--n-splits", type=int, default=5, help="Number of temporal folds")
    p.add_argument("--valid-days", type=int, default=21, help="Days per validation fold")
    p.add_argument("--decay-lambda-rank1", type=float, default=2.0, help="Time-decay λ for Rank1")
    p.add_argument("--decay-lambda-topk", type=float, default=2.0, help="Time-decay λ for TOP-K")
    p.add_argument(
        "--decay-lambda-sweep-rank1",
        default="1.0,1.5,2.0,2.5",
        help="Comma-separated λ values to sweep for Rank1",
    )
    p.add_argument(
        "--decay-lambda-sweep-topk",
        default="1.0,1.5,2.0,2.5",
        help="Comma-separated λ values to sweep for TOP-K targets",
    )
    p.add_argument(
        "--targets",
        default="is_rank_1,is_top_2,is_top_3",
        help="Comma-separated targets to evaluate",
    )
    p.add_argument("--enable-window-sweep", action="store_true", help="Evaluate multiple train windows on fixed splits")
    p.add_argument("--window-sweep-only", action="store_true", help="Skip standard evaluations and run only fixed window sweeps")
    p.add_argument("--enable-two-stage-top3", action="store_true", help="Enable two-stage rerank for is_top_3")
    p.add_argument("--two-stage-candidate-factor", type=int, default=2, help="Top3 stage-1 candidate size factor")
    p.add_argument("--random-state", type=int, default=42, help="Random seed")
    p.add_argument("--verbose", action="store_true", help="Verbose logging")
    return p


def main() -> int:
    args = build_parser().parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )

    db_path = Path(args.db_path)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"Loading data from {db_path}")
    dataset = build_last_digit_dataset(db_path=db_path)
    dataset = add_top2_target(dataset)
    dataset = add_regime_and_cluster_features(dataset)
    features = get_numeric_features(dataset)

    logger.info(f"Dataset: {len(dataset)} rows, {len(features)} features")

    calibration_config = CalibrationConfig()
    two_stage_config = TwoStageConfig(
        enable_top3=bool(args.enable_two_stage_top3),
        candidate_factor=max(1, int(args.two_stage_candidate_factor)),
    )
    lambda_sweep_rank1 = parse_lambda_sweep_values(args.decay_lambda_sweep_rank1)
    lambda_sweep_topk = parse_lambda_sweep_values(args.decay_lambda_sweep_topk)
    targets = parse_target_values(args.targets)
    fixed_split_configs = build_fixed_split_configs(dataset)
    result: dict[str, Any] = {
        "db_path": str(db_path),
        "n_rows": int(len(dataset)),
        "n_features": int(len(features)),
        "features_sample": features[:30],
        "uniform": {},
        "time_decay": {},
        "lambda_sweep": {},
        "config": {
            "n_splits": args.n_splits,
            "valid_days": args.valid_days,
            "decay_lambda_rank1": args.decay_lambda_rank1,
            "decay_lambda_topk": args.decay_lambda_topk,
            "decay_lambda_sweep_rank1": lambda_sweep_rank1,
            "decay_lambda_sweep_topk": lambda_sweep_topk,
            "targets": targets,
            "enable_window_sweep": bool(args.enable_window_sweep),
            "window_sweep_only": bool(args.window_sweep_only),
            "enable_two_stage_top3": bool(two_stage_config.enable_top3),
            "two_stage_candidate_factor": int(two_stage_config.candidate_factor),
            "random_state": args.random_state,
            "calibration": asdict(calibration_config),
        },
    }
    for split_name, split_config in fixed_split_configs.items():
        result[split_name] = {
            **split_config,
            "uniform": {},
            "time_decay": {},
            "lambda_sweep": {},
        }
        if args.enable_window_sweep:
            result[split_name]["window_sweep"] = {
                "train_windows": build_window_sweep_configs(valid_start=split_config["valid_start"]),
                "uniform": {},
                "time_decay": {},
            }

    for target in targets:
        logger.info(f"Evaluating {target}...")
        lam = args.decay_lambda_rank1 if target == "is_rank_1" else args.decay_lambda_topk
        sweep_values = lambda_sweep_rank1 if target == "is_rank_1" else lambda_sweep_topk

        if not args.window_sweep_only:
            result["uniform"][target] = evaluate_mode(
                dataset,
                target=target,
                features=features,
                n_splits=args.n_splits,
                valid_days=args.valid_days,
                random_state=args.random_state,
                decay_lambda=None,
                calibration_config=calibration_config,
                two_stage_config=two_stage_config,
            )
            result["time_decay"][target] = evaluate_mode(
                dataset,
                target=target,
                features=features,
                n_splits=args.n_splits,
                valid_days=args.valid_days,
                random_state=args.random_state,
                decay_lambda=lam,
                calibration_config=calibration_config,
                two_stage_config=two_stage_config,
            )
            result["lambda_sweep"][target] = run_lambda_sweep(
                dataset,
                target=target,
                features=features,
                n_splits=args.n_splits,
                valid_days=args.valid_days,
                random_state=args.random_state,
                calibration_config=calibration_config,
                lambda_values=sweep_values,
                two_stage_config=two_stage_config,
            )
        for split_name, split_config in fixed_split_configs.items():
            if not args.window_sweep_only:
                result[split_name]["uniform"][target] = evaluate_fixed_split(
                    dataset,
                    target=target,
                    features=features,
                    random_state=args.random_state,
                    decay_lambda=None,
                    calibration_config=calibration_config,
                    two_stage_config=two_stage_config,
                    train_start=split_config["train_start"],
                    train_end=split_config["train_end"],
                    valid_start=split_config["valid_start"],
                    valid_end=split_config["valid_end"],
                )
                result[split_name]["time_decay"][target] = evaluate_fixed_split(
                    dataset,
                    target=target,
                    features=features,
                    random_state=args.random_state,
                    decay_lambda=lam,
                    calibration_config=calibration_config,
                    two_stage_config=two_stage_config,
                    train_start=split_config["train_start"],
                    train_end=split_config["train_end"],
                    valid_start=split_config["valid_start"],
                    valid_end=split_config["valid_end"],
                )
                result[split_name]["lambda_sweep"][target] = run_fixed_lambda_sweep(
                    dataset,
                    target=target,
                    features=features,
                    random_state=args.random_state,
                    calibration_config=calibration_config,
                    lambda_values=sweep_values,
                    two_stage_config=two_stage_config,
                    train_start=split_config["train_start"],
                    train_end=split_config["train_end"],
                    valid_start=split_config["valid_start"],
                    valid_end=split_config["valid_end"],
                )
            if args.enable_window_sweep:
                train_windows = result[split_name]["window_sweep"]["train_windows"]
                result[split_name]["window_sweep"]["uniform"][target] = run_fixed_window_sweep(
                    dataset,
                    target=target,
                    features=features,
                    random_state=args.random_state,
                    decay_lambda=None,
                    calibration_config=calibration_config,
                    two_stage_config=two_stage_config,
                    train_windows=train_windows,
                    valid_start=split_config["valid_start"],
                    valid_end=split_config["valid_end"],
                )
                result[split_name]["window_sweep"]["time_decay"][target] = run_fixed_window_sweep(
                    dataset,
                    target=target,
                    features=features,
                    random_state=args.random_state,
                    decay_lambda=lam,
                    calibration_config=calibration_config,
                    two_stage_config=two_stage_config,
                    train_windows=train_windows,
                    valid_start=split_config["valid_start"],
                    valid_end=split_config["valid_end"],
                )

    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Results written to {out_path}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
