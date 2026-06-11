from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
from catboost import CatBoostRanker, Pool
from lightgbm import LGBMRanker
from tqdm import tqdm
from xgboost import XGBRanker

from ml.last_digit.core_ranking import fit_ranker, ndcg_at_k, spearman_by_group
from ml.last_digit.hall_day_strength_audit import add_strength_targets, load_daily_hall
from ml.last_digit.utils import configure_logging, parse_csv_ints, parse_csv_strs

logger = logging.getLogger(__name__)

DEFAULT_STORES_CSV = Path("db/experiments/hall_day_strength_audit_20260601/stores.csv")
DEFAULT_SELECTION_START = "2025-07-07"
DEFAULT_SELECTION_END = "2025-12-31"
DEFAULT_HOLDOUT_START = "2026-01-01"
DEFAULT_HOLDOUT_END = "2026-05-30"
DEFAULT_TARGET_THRESHOLDS = (0, 100, 200, 300)
DEFAULT_MODELS = ("xgb_ranker", "lgbm_ranker", "catboost_ranker")

BASE_FEATURE_COLS = [
    "weekday",
    "dd",
    "mm",
    "is_any_event",
    "is_zorome_day",
    "is_strong_zorome_day",
    "is_day_7x",
    "is_day_1x",
    "lag1_avg_diff",
    "lag2_avg_diff",
    "lag7_avg_diff",
    "ewm7_avg_diff",
    "ewm28_avg_diff",
    "trend_gap_7_28",
    "delta_lag1",
    "vol14_avg_diff",
    "lag1_avg_games",
    "roll7_games",
    "roll7_win_rate",
    "roll7_total_machines",
    "rel_rank_ewm28",
    "rel_rank_ewm28_norm",
    "rel_z_ewm28",
]

EXCLUDE_FEATURE_COLS = {
    "date",
    "store",
    "avg_diff_per_machine",
    "avg_games_per_machine",
    "total_machines",
    "win_rate",
    "is_ge_0",
    "is_ge_100",
    "is_ge_200",
    "is_ge_300",
}


@dataclass(frozen=True)
class RankerSpec:
    name: str
    backend: str
    fit_predict: Callable[[pd.DataFrame, pd.DataFrame, list[str], int], tuple[np.ndarray, str]]


def build_backend_params(model_name: str, *, use_gpu: bool, gpu_backend: str = "cuda") -> dict[str, Any]:
    model_name = str(model_name).lower()
    if model_name == "xgb_ranker":
        return {"tree_method": "hist", "device": "cuda" if use_gpu else "cpu"}
    if model_name == "lgbm_ranker":
        return {"device_type": "gpu" if use_gpu else "cpu"}
    if model_name == "catboost_ranker":
        return {"task_type": "GPU" if use_gpu else "CPU", "devices": "0" if use_gpu else None}
    raise ValueError(f"Unknown model family: {model_name}")


def _resolve_repo_path(raw_path: str | Path) -> Path:
    p = Path(raw_path)
    return p if p.is_absolute() else (Path.cwd() / p)


def _load_store_meta(stores_csv: str | Path) -> pd.DataFrame:
    p = _resolve_repo_path(stores_csv)
    if not p.exists():
        raise FileNotFoundError(f"Missing stores csv: {p}")
    df = pd.read_csv(p)
    required = {"store", "db_path"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"stores csv missing columns: {sorted(missing)}")
    out = df.copy()
    out["db_path"] = out["db_path"].map(lambda x: str(_resolve_repo_path(x)))
    return out


def _load_store_frames(stores_csv: str | Path, *, thresholds: tuple[int, ...] = DEFAULT_TARGET_THRESHOLDS) -> dict[str, pd.DataFrame]:
    meta = _load_store_meta(stores_csv)
    store_to_df: dict[str, pd.DataFrame] = {}
    for row in tqdm(meta.itertuples(index=False), total=len(meta), desc="load halls", leave=False):
        db_path = Path(str(row.db_path))
        df = load_daily_hall(db_path)
        df = add_strength_targets(df, thresholds=thresholds)
        df["store"] = str(row.store)
        store_to_df[str(row.store)] = df
    return store_to_df


def _add_leakage_safe_hall_features(hall_df: pd.DataFrame) -> pd.DataFrame:
    out = hall_df.sort_values("date").copy()
    avg_diff = pd.to_numeric(out["avg_diff_per_machine"], errors="coerce").fillna(0.0)
    avg_games = pd.to_numeric(out["avg_games_per_machine"], errors="coerce").fillna(0.0)
    win_rate = pd.to_numeric(out["win_rate"], errors="coerce").fillna(0.0)
    total_machines = pd.to_numeric(out["total_machines"], errors="coerce").fillna(0.0)

    out["lag1_avg_diff"] = avg_diff.shift(1)
    out["lag2_avg_diff"] = avg_diff.shift(2)
    out["lag7_avg_diff"] = avg_diff.shift(7)
    out["ewm7_avg_diff"] = avg_diff.shift(1).ewm(span=7, adjust=False, min_periods=3).mean()
    out["ewm28_avg_diff"] = avg_diff.shift(1).ewm(span=28, adjust=False, min_periods=7).mean()
    out["trend_gap_7_28"] = out["ewm7_avg_diff"] - out["ewm28_avg_diff"]
    out["delta_lag1"] = out["lag1_avg_diff"] - out["lag2_avg_diff"]
    out["vol14_avg_diff"] = avg_diff.shift(1).rolling(14, min_periods=5).std()
    out["lag1_avg_games"] = avg_games.shift(1)
    out["roll7_games"] = avg_games.shift(1).rolling(7, min_periods=3).mean()
    out["roll7_win_rate"] = win_rate.shift(1).rolling(7, min_periods=3).mean()
    out["roll7_total_machines"] = total_machines.shift(1).rolling(7, min_periods=3).mean()

    out["weekday_sin"] = np.sin(2.0 * np.pi * pd.to_numeric(out["weekday"], errors="coerce").fillna(0.0) / 7.0)
    out["weekday_cos"] = np.cos(2.0 * np.pi * pd.to_numeric(out["weekday"], errors="coerce").fillna(0.0) / 7.0)
    out["dd_sin"] = np.sin(2.0 * np.pi * pd.to_numeric(out["dd"], errors="coerce").fillna(0.0) / 31.0)
    out["dd_cos"] = np.cos(2.0 * np.pi * pd.to_numeric(out["dd"], errors="coerce").fillna(0.0) / 31.0)
    return out


def _add_cross_hall_features(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel.copy()
    grp = out.groupby("date", sort=False)["ewm28_avg_diff"]
    out["rel_rank_ewm28"] = grp.rank(method="average", ascending=False)
    n_store = grp.transform("count")
    out["rel_rank_ewm28_norm"] = np.where(n_store > 1, (out["rel_rank_ewm28"] - 1.0) / (n_store - 1.0), 0.0)
    mu = grp.transform("mean")
    sigma = grp.transform("std")
    out["rel_z_ewm28"] = np.where(sigma > 0, (out["ewm28_avg_diff"] - mu) / sigma, 0.0)
    return out


def build_hall_panel(store_to_hall_df: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for store, hall_df in store_to_hall_df.items():
        one = _add_leakage_safe_hall_features(add_strength_targets(hall_df, thresholds=DEFAULT_TARGET_THRESHOLDS))
        one["store"] = str(store)
        rows.append(one)
    if not rows:
        return pd.DataFrame()
    panel = pd.concat(rows, axis=0, ignore_index=True)
    panel = _add_cross_hall_features(panel)
    panel = panel.sort_values(["date", "store"]).reset_index(drop=True)
    return panel


def _feature_frame_from_panel(panel_df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    frame = panel_df.copy()
    if "store" not in frame.columns:
        raise ValueError("panel_df must contain store")
    store_dummies = pd.get_dummies(frame["store"], prefix="store", dtype=float)
    frame = pd.concat([frame, store_dummies], axis=1)
    feature_cols = [c for c in BASE_FEATURE_COLS if c in frame.columns]
    feature_cols.extend(list(store_dummies.columns))
    feature_cols = [c for c in feature_cols if c not in EXCLUDE_FEATURE_COLS]
    return frame, feature_cols


def _clean_numeric_frame(df: pd.DataFrame) -> pd.DataFrame:
    cleaned = df.astype(float).copy()
    cleaned = cleaned.replace([np.inf, -np.inf], np.nan)
    return cleaned


def _group_sizes_by_date(df: pd.DataFrame) -> list[int]:
    dates = pd.to_datetime(df["date"])
    return dates.groupby(dates, sort=False).size().astype(int).tolist()


def _rank_labels_within_date(df: pd.DataFrame) -> np.ndarray:
    y = pd.to_numeric(df["avg_diff_per_machine"], errors="coerce").fillna(0.0)
    dates = pd.to_datetime(df["date"])
    ranks = y.groupby(dates, sort=False).rank(method="first", ascending=True) - 1.0
    return ranks.to_numpy(dtype=float)


def _safe_spearman_rank_corr(x: pd.Series, y: pd.Series) -> float:
    corr = pd.Series(x, dtype=float).corr(pd.Series(y, dtype=float), method="spearman")
    return float(corr) if pd.notna(corr) else 0.0


def _fit_predict_xgb_ranker(
    train_df: pd.DataFrame,
    valid_df: pd.DataFrame,
    feature_cols: list[str],
    *,
    seed: int,
    use_gpu: bool,
    gpu_backend: str,
    model_params: dict[str, Any] | None = None,
) -> tuple[np.ndarray, str]:
    if train_df.empty or valid_df.empty:
        return np.array([], dtype=float), "baseline"
    train_dates = pd.to_datetime(train_df["date"])
    y_train = _rank_labels_within_date(train_df)
    if len(train_df) < 8 or train_df["date"].nunique() < 2:
        base = float(np.mean(y_train)) if len(y_train) else 0.0
        return np.full(len(valid_df), base, dtype=float), "baseline"

    x_train = _clean_numeric_frame(train_df[feature_cols]).fillna(train_df[feature_cols].median(numeric_only=True).fillna(0.0))
    x_valid = _clean_numeric_frame(valid_df[feature_cols]).fillna(train_df[feature_cols].median(numeric_only=True).fillna(0.0))
    params = {
        "objective": "rank:pairwise",
        "n_estimators": 120,
        "learning_rate": 0.05,
        "max_depth": 4,
        "subsample": 0.9,
        "colsample_bytree": 0.9,
        "random_state": seed,
        "verbosity": 0,
    }
    params.update(build_backend_params("xgb_ranker", use_gpu=use_gpu, gpu_backend=gpu_backend))
    if model_params:
        params.update(model_params)
    try:
        model = fit_ranker(
            x_train,
            y_train,
            train_dates,
            objective="rank:pairwise",
            random_state=seed,
            model_params=params,
        )
        return np.asarray(model.predict(x_valid), dtype=float), ("gpu" if use_gpu else "cpu")
    except Exception as exc:
        if not use_gpu:
            raise
        logger.warning("XGBRanker GPU fit failed, retrying on CPU: %s", exc)
        cpu_params = dict(params)
        cpu_params.update(build_backend_params("xgb_ranker", use_gpu=False, gpu_backend=gpu_backend))
        model = fit_ranker(
            x_train,
            y_train,
            train_dates,
            objective="rank:pairwise",
            random_state=seed,
            model_params=cpu_params,
        )
        return np.asarray(model.predict(x_valid), dtype=float), "cpu_fallback"


def _fit_predict_lgbm_ranker(
    train_df: pd.DataFrame,
    valid_df: pd.DataFrame,
    feature_cols: list[str],
    *,
    seed: int,
    use_gpu: bool,
    gpu_backend: str,
    model_params: dict[str, Any] | None = None,
) -> tuple[np.ndarray, str]:
    if train_df.empty or valid_df.empty:
        return np.array([], dtype=float), "baseline"
    y_train = _rank_labels_within_date(train_df)
    if len(train_df) < 8 or train_df["date"].nunique() < 2:
        base = float(np.mean(y_train)) if len(y_train) else 0.0
        return np.full(len(valid_df), base, dtype=float), "baseline"
    x_train = _clean_numeric_frame(train_df[feature_cols]).fillna(train_df[feature_cols].median(numeric_only=True).fillna(0.0))
    x_valid = _clean_numeric_frame(valid_df[feature_cols]).fillna(train_df[feature_cols].median(numeric_only=True).fillna(0.0))
    params: dict[str, Any] = {
        "objective": "lambdarank",
        "metric": "ndcg",
        "n_estimators": 150,
        "learning_rate": 0.05,
        "num_leaves": 31,
        "subsample": 0.9,
        "colsample_bytree": 0.9,
        "random_state": seed,
        "verbosity": -1,
    }
    params.update(build_backend_params("lgbm_ranker", use_gpu=use_gpu, gpu_backend=gpu_backend))
    if model_params:
        params.update(model_params)
    group = _group_sizes_by_date(train_df)
    try:
        model = LGBMRanker(**params)
        model.fit(x_train, y_train, group=group)
        return np.asarray(model.predict(x_valid), dtype=float), ("gpu" if use_gpu else "cpu")
    except Exception as exc:
        if not use_gpu:
            raise
        logger.warning("LGBMRanker GPU fit failed, retrying on CPU: %s", exc)
        cpu_params = dict(params)
        cpu_params.update(build_backend_params("lgbm_ranker", use_gpu=False, gpu_backend=gpu_backend))
        model = LGBMRanker(**cpu_params)
        model.fit(x_train, y_train, group=group)
        return np.asarray(model.predict(x_valid), dtype=float), "cpu_fallback"


def _fit_predict_catboost_ranker(
    train_df: pd.DataFrame,
    valid_df: pd.DataFrame,
    feature_cols: list[str],
    *,
    seed: int,
    use_gpu: bool,
    gpu_backend: str,
    model_params: dict[str, Any] | None = None,
) -> tuple[np.ndarray, str]:
    if train_df.empty or valid_df.empty:
        return np.array([], dtype=float), "baseline"
    y_train = _rank_labels_within_date(train_df)
    if len(train_df) < 8 or train_df["date"].nunique() < 2:
        base = float(np.mean(y_train)) if len(y_train) else 0.0
        return np.full(len(valid_df), base, dtype=float), "baseline"
    x_train = _clean_numeric_frame(train_df[feature_cols]).fillna(train_df[feature_cols].median(numeric_only=True).fillna(0.0))
    x_valid = _clean_numeric_frame(valid_df[feature_cols]).fillna(train_df[feature_cols].median(numeric_only=True).fillna(0.0))
    params: dict[str, Any] = {
        "loss_function": "YetiRankPairwise",
        "eval_metric": "NDCG:top=3",
        "depth": 6,
        "learning_rate": 0.05,
        "iterations": 180,
        "random_seed": seed,
        "verbose": False,
    }
    params.update(build_backend_params("catboost_ranker", use_gpu=use_gpu, gpu_backend=gpu_backend))
    if model_params:
        params.update(model_params)
    train_pool = Pool(
        x_train,
        label=y_train,
        group_id=pd.to_datetime(train_df["date"]).dt.strftime("%Y%m%d").to_numpy(),
    )
    valid_pool = Pool(x_valid)
    try:
        model = CatBoostRanker(**params)
        model.fit(train_pool)
        return np.asarray(model.predict(valid_pool), dtype=float), ("gpu" if use_gpu else "cpu")
    except Exception as exc:
        if not use_gpu:
            raise
        logger.warning("CatBoostRanker GPU fit failed, retrying on CPU: %s", exc)
        cpu_params = dict(params)
        cpu_params.update(build_backend_params("catboost_ranker", use_gpu=False, gpu_backend=gpu_backend))
        model = CatBoostRanker(**cpu_params)
        model.fit(train_pool)
        return np.asarray(model.predict(valid_pool), dtype=float), "cpu_fallback"


def build_model_specs(*, use_gpu: bool, gpu_backend: str, grid_profile: str = "none") -> list[RankerSpec]:
    grid_profile = str(grid_profile).lower()
    variant_map: dict[str, list[tuple[str, dict[str, Any]]]] = {
        "none": [
            ("xgb_ranker", {}),
            ("lgbm_ranker", {}),
            ("catboost_ranker", {}),
        ],
        "small": [
            ("xgb_ranker_md3", {"max_depth": 3}),
            ("xgb_ranker_md4", {"max_depth": 4}),
            ("lgbm_ranker_leaves31", {"num_leaves": 31}),
            ("lgbm_ranker_leaves63", {"num_leaves": 63}),
            ("catboost_ranker_depth4", {"depth": 4}),
            ("catboost_ranker_depth6", {"depth": 6}),
        ],
    }
    if grid_profile not in variant_map:
        raise ValueError(f"Unknown grid_profile: {grid_profile}")

    specs: list[RankerSpec] = []
    for name, extra_params in variant_map[grid_profile]:
        if name.startswith("xgb_ranker"):
            specs.append(
                RankerSpec(
                    name=name,
                    backend="xgboost",
                    fit_predict=lambda train_df, valid_df, feature_cols, seed, extra_params=extra_params: _fit_predict_xgb_ranker(
                        train_df,
                        valid_df,
                        feature_cols,
                        seed=seed,
                        use_gpu=use_gpu,
                        gpu_backend=gpu_backend,
                        model_params=extra_params,
                    ),
                )
            )
        elif name.startswith("lgbm_ranker"):
            specs.append(
                RankerSpec(
                    name=name,
                    backend="lightgbm",
                    fit_predict=lambda train_df, valid_df, feature_cols, seed, extra_params=extra_params: _fit_predict_lgbm_ranker(
                        train_df,
                        valid_df,
                        feature_cols,
                        seed=seed,
                        use_gpu=use_gpu,
                        gpu_backend=gpu_backend,
                        model_params=extra_params,
                    ),
                )
            )
        elif name.startswith("catboost_ranker"):
            specs.append(
                RankerSpec(
                    name=name,
                    backend="catboost",
                    fit_predict=lambda train_df, valid_df, feature_cols, seed, extra_params=extra_params: _fit_predict_catboost_ranker(
                        train_df,
                        valid_df,
                        feature_cols,
                        seed=seed,
                        use_gpu=use_gpu,
                        gpu_backend=gpu_backend,
                        model_params=extra_params,
                    ),
                )
            )
        else:
            raise ValueError(f"Unsupported spec name: {name}")
    return specs


def _select_split(panel_df: pd.DataFrame, *, selection_start: str, selection_end: str, holdout_start: str, holdout_end: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    sel_start = pd.Timestamp(str(selection_start))
    sel_end = pd.Timestamp(str(selection_end))
    ho_start = pd.Timestamp(str(holdout_start))
    ho_end = pd.Timestamp(str(holdout_end))
    panel = panel_df.copy()
    panel["date"] = pd.to_datetime(panel["date"])
    train = panel[(panel["date"] >= sel_start) & (panel["date"] <= sel_end)].copy()
    valid = panel[(panel["date"] >= ho_start) & (panel["date"] <= ho_end)].copy()
    if train.empty or valid.empty:
        raise ValueError(f"empty split: train={len(train)} valid={len(valid)}")
    return train, valid


def _score_daily_predictions(pred_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    for (model, seed, backend_used, date), g in pred_df.groupby(["model", "seed", "backend_used", "date"], sort=True):
        tmp = g.sort_values(["pred_score", "store"], ascending=[False, True]).copy()
        oracle = tmp.sort_values(["actual_avg_diff_per_machine", "store"], ascending=[False, True]).iloc[0]
        picked = tmp.iloc[0]
        pred_top2 = tmp.head(min(2, len(tmp)))["store"].astype(str).tolist()
        rows.append(
            {
                "model": model,
                "seed": int(seed),
                "backend_used": backend_used,
                "date": str(date),
                "picked_store": str(picked["store"]),
                "oracle_store": str(oracle["store"]),
                "picked_actual_avg_diff_per_machine": float(picked["actual_avg_diff_per_machine"]),
                "oracle_actual_avg_diff_per_machine": float(oracle["actual_avg_diff_per_machine"]),
                "top1_hit": int(str(picked["store"]) == str(oracle["store"])),
                "top2_inclusion": int(str(oracle["store"]) in pred_top2),
                "spearman_daily_rho": _safe_spearman_rank_corr(
                    tmp["pred_score"].rank(method="first", ascending=False),
                    tmp["actual_avg_diff_per_machine"].rank(method="first", ascending=False),
                ),
                "regret_vs_oracle": float(max(0.0, float(oracle["actual_avg_diff_per_machine"]) - float(picked["actual_avg_diff_per_machine"]))),
                "pred_top2_stores": ",".join(pred_top2),
                "elapsed_sec": float(tmp["elapsed_sec"].iloc[0]) if "elapsed_sec" in tmp.columns else np.nan,
            }
        )
    daily = pd.DataFrame(rows)
    if daily.empty:
        return daily, pd.DataFrame()
    summary = (
        daily.groupby(["model"], as_index=False)
        .agg(
            n_days=("date", "count"),
            chosen_avg_diff_mean=("picked_actual_avg_diff_per_machine", "mean"),
            oracle_avg_diff_mean=("oracle_actual_avg_diff_per_machine", "mean"),
            top1_hit_rate=("top1_hit", "mean"),
            top2_inclusion_rate=("top2_inclusion", "mean"),
            spearman_daily_mean=("spearman_daily_rho", "mean"),
            regret_mean=("regret_vs_oracle", "mean"),
            regret_sum=("regret_vs_oracle", "sum"),
            elapsed_sec_mean=("elapsed_sec", "mean"),
        )
        .sort_values(["chosen_avg_diff_mean", "spearman_daily_mean"], ascending=[False, False])
        .reset_index(drop=True)
    )
    return daily, summary


def evaluate_model_zoo(
    *,
    panel_df: pd.DataFrame,
    selection_start: str,
    selection_end: str,
    holdout_start: str,
    holdout_end: str,
    models: tuple[str, ...] = DEFAULT_MODELS,
    seeds: tuple[int, ...] = (42,),
    use_gpu: bool = False,
    gpu_backend: str = "cuda",
    grid_profile: str = "none",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if panel_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    panel = panel_df.copy()
    panel["date"] = pd.to_datetime(panel["date"])
    panel, feature_cols = _feature_frame_from_panel(panel)
    train_df, valid_df = _select_split(
        panel,
        selection_start=selection_start,
        selection_end=selection_end,
        holdout_start=holdout_start,
        holdout_end=holdout_end,
    )
    selected = [
        s
        for s in build_model_specs(use_gpu=use_gpu, gpu_backend=gpu_backend, grid_profile=grid_profile)
        if any(s.name == wanted or s.name.startswith(wanted) for wanted in set(models))
    ]
    if not selected:
        raise ValueError("No models selected for evaluation")

    logger.info(
        "Hall GPU model zoo: train_rows=%d valid_rows=%d train_days=%d valid_days=%d features=%d models=%d seeds=%d",
        len(train_df),
        len(valid_df),
        train_df["date"].nunique(),
        valid_df["date"].nunique(),
        len(feature_cols),
        len(selected),
        len(seeds),
    )

    detailed_rows: list[pd.DataFrame] = []
    for spec in tqdm(selected, desc="models", leave=False):
        for seed in tqdm(seeds, desc=f"{spec.name} seeds", leave=False):
            t0 = time.time()
            pred, backend_used = spec.fit_predict(train_df, valid_df, feature_cols, seed)
            elapsed = time.time() - t0
            if elapsed > 30.0:
                print(f"WARNING: {spec.name} seed={seed} took {elapsed:.1f}s - possible hang")
            tmp = valid_df[["date", "store", "avg_diff_per_machine"]].copy()
            tmp["model"] = spec.name
            tmp["seed"] = int(seed)
            tmp["backend_used"] = backend_used
            tmp["pred_score"] = np.asarray(pred, dtype=float)
            tmp["elapsed_sec"] = float(elapsed)
            tmp = tmp.rename(columns={"avg_diff_per_machine": "actual_avg_diff_per_machine"})
            detailed_rows.append(tmp)

    pred_df = pd.concat(detailed_rows, axis=0, ignore_index=True)
    daily_df, summary_df = _score_daily_predictions(pred_df)
    summary_df["backend_requested"] = "gpu" if use_gpu else "cpu"
    summary_df["gpu_backend"] = gpu_backend
    summary_df["models_requested"] = ",".join(models)
    summary_df["seeds"] = ",".join(str(s) for s in seeds)
    return summary_df, daily_df


def compare_model_zoo_backends(
    *,
    panel_df: pd.DataFrame,
    selection_start: str,
    selection_end: str,
    holdout_start: str,
    holdout_end: str,
    models: tuple[str, ...] = DEFAULT_MODELS,
    seeds: tuple[int, ...] = (42,),
    grid_profile: str = "none",
    gpu_backend: str = "cuda",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[pd.DataFrame] = []
    summaries: list[pd.DataFrame] = []
    for backend_requested, use_gpu in (("cpu", False), ("gpu", True)):
        summary_df, _ = evaluate_model_zoo(
            panel_df=panel_df,
            selection_start=selection_start,
            selection_end=selection_end,
            holdout_start=holdout_start,
            holdout_end=holdout_end,
            models=models,
            seeds=seeds,
            use_gpu=use_gpu,
            gpu_backend=gpu_backend,
            grid_profile=grid_profile,
        )
        summary_df = summary_df.copy()
        summary_df["backend_requested"] = backend_requested
        rows.append(summary_df)
        summaries.append(summary_df)
    combined = pd.concat(rows, axis=0, ignore_index=True) if rows else pd.DataFrame()
    if combined.empty:
        return combined, pd.DataFrame()
    wide = (
        combined.pivot_table(
            index="model",
            columns="backend_requested",
            values=[
                "chosen_avg_diff_mean",
                "spearman_daily_mean",
                "top1_hit_rate",
                "top2_inclusion_rate",
                "regret_mean",
                "elapsed_sec_mean",
            ],
            aggfunc="first",
        )
        .sort_index(axis=1)
        .reset_index()
    )
    wide.columns = [
        "_".join([str(x) for x in col if str(x) != ""]).strip("_") if isinstance(col, tuple) else str(col)
        for col in wide.columns.to_flat_index()
    ]
    for metric in ("chosen_avg_diff_mean", "spearman_daily_mean", "top1_hit_rate", "top2_inclusion_rate", "regret_mean", "elapsed_sec_mean"):
        cpu_col = f"{metric}_cpu"
        gpu_col = f"{metric}_gpu"
        if cpu_col in wide.columns and gpu_col in wide.columns:
            wide[f"{metric}_delta_gpu_minus_cpu"] = pd.to_numeric(wide[gpu_col], errors="coerce") - pd.to_numeric(wide[cpu_col], errors="coerce")
    return wide, combined


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Hall GPU/LTR model zoo benchmark")
    p.add_argument("--stores-csv", default=str(DEFAULT_STORES_CSV))
    p.add_argument("--selection-start", default=DEFAULT_SELECTION_START)
    p.add_argument("--selection-end", default=DEFAULT_SELECTION_END)
    p.add_argument("--holdout-start", default=DEFAULT_HOLDOUT_START)
    p.add_argument("--holdout-end", default=DEFAULT_HOLDOUT_END)
    p.add_argument("--models", default=",".join(DEFAULT_MODELS))
    p.add_argument("--seeds", default="42")
    p.add_argument("--use-gpu", action="store_true", help="Enable GPU learners when available")
    p.add_argument("--gpu-backend", choices=["cuda", "gpu_hist"], default="cuda")
    p.add_argument("--grid-profile", choices=["none", "small"], default="none")
    p.add_argument("--output-prefix", default="ml/hall_rank/reports/hall_gpu_model_zoo")
    p.add_argument("--log-level", default="INFO")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.log_level)

    stores_csv = _resolve_repo_path(args.stores_csv)
    out_prefix = _resolve_repo_path(args.output_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)

    models = tuple(parse_csv_strs(args.models)) if str(args.models).strip() else DEFAULT_MODELS
    seeds = tuple(parse_csv_ints(args.seeds))

    store_frames = _load_store_frames(stores_csv)
    panel = build_hall_panel(store_frames)
    summary_df, daily_df = evaluate_model_zoo(
        panel_df=panel,
        selection_start=args.selection_start,
        selection_end=args.selection_end,
        holdout_start=args.holdout_start,
        holdout_end=args.holdout_end,
        models=models,
        seeds=seeds,
        use_gpu=bool(args.use_gpu),
        gpu_backend=str(args.gpu_backend),
        grid_profile=str(args.grid_profile),
    )

    summary_path = out_prefix.with_name(out_prefix.name + "_summary.csv")
    detailed_path = out_prefix.with_name(out_prefix.name + "_detailed.csv")
    json_path = out_prefix.with_suffix(".json")
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")
    daily_df.to_csv(detailed_path, index=False, encoding="utf-8-sig")
    payload = {
        "config": {
            "stores_csv": str(stores_csv),
            "selection_start": args.selection_start,
            "selection_end": args.selection_end,
            "holdout_start": args.holdout_start,
            "holdout_end": args.holdout_end,
            "models": list(models),
            "seeds": list(seeds),
            "use_gpu": bool(args.use_gpu),
            "gpu_backend": str(args.gpu_backend),
            "grid_profile": str(args.grid_profile),
        },
        "summary": summary_df.to_dict(orient="records"),
        "backend": {
            "requested": "gpu" if bool(args.use_gpu) else "cpu",
            "gpu_backend": str(args.gpu_backend),
        },
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Wrote %s / %s / %s", summary_path, detailed_path, json_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
