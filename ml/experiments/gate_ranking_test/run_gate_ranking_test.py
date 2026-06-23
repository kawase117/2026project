from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from ml.experiments.gate_analysis.run_gate_analysis import build_segment_daily_counts, is_event_day
from ml.experiments.walkforward_scoring.config import (
    DEFAULT_DB_PATH as WALKFORWARD_DEFAULT_DB_PATH,
    PROJECT_ROOT,
    build_variant_configs,
)
from ml.experiments.walkforward_scoring.scoring_model import ScoreContext, build_score_context, classify_seg, score_day

try:
    from catboost import CatBoostClassifier, Pool

    HAS_CATBOOST = True
except ImportError:  # pragma: no cover - exercised in environments without CatBoost
    CatBoostClassifier = None  # type: ignore[assignment]
    Pool = None  # type: ignore[assignment]
    HAS_CATBOOST = False

GATE_V6B_RULE_ID = "gate_v6b_rule"
GATE_ML_SHADOW_ID = "gate_ml_shadow"
SERIES_ORDER = ("nogate_v6a", "gate_v6a", "gate_random", GATE_V6B_RULE_ID, GATE_ML_SHADOW_ID)
SUMMARY_COLUMNS = [
    "series_id",
    "event_type",
    "precision_at_10",
    "precision_at_15",
    "lift_at_10",
    "lift_at_15",
    "avg_payout_at_10",
    "avg_payout_at_15",
    "n_test_days",
    "n_days_active_lt_10",
]
DAILY_COLUMNS = [
    "test_date",
    "series_id",
    "dd",
    "dow",
    "is_event",
    "event_type",
    "n_total_machines",
    "n_active_machines",
    "n_active_segments",
    "active_segments",
    "precision_at_10",
    "precision_at_15",
    "lift_at_10",
    "lift_at_15",
    "avg_payout_at_10",
    "avg_payout_at_15",
    "split_period",
    "n_days_active_lt_10",
    "ml_auc",
]
SPLIT_COLUMNS = [
    "series_id",
    "split_period",
    "precision_at_10",
    "precision_at_15",
    "lift_at_10",
    "avg_payout_at_10",
    "n_test_days",
    "n_days_active_lt_10",
]
V6A_VARIANT_ID = "v6a_hit_an"
EVALUATION_MIN_GAMES = 400
ML_HISTORY_DAYS = 80
ML_RECENT_DAYS = 10
ML_MIN_TRAIN_ROWS = 100
ML_FEATURES = [
    "c1",
    "c2",
    "c3",
    "c4",
    "c5",
    "c6",
    "hist_diff",
    "hist_payout",
    "hist_hit_an",
    "hist_winrate",
    "seg_relative_hist_top20",
    "seg_relative_rank_payout",
    "machine_type",
    "rolling_diff_7d",
    "rolling_diff_14d",
    "rolling_diff_28d",
    "is_event",
]
CAT_FEATURES = ["machine_type"]


def resolve_default_db_path() -> Path:
    db_dir = PROJECT_ROOT / "db"
    candidates = [path for path in db_dir.glob("*闥ｲ逕ｰ7*.db") if path.is_file() and path.stat().st_size > 0]
    if candidates:
        return sorted(candidates, key=lambda path: path.stat().st_size, reverse=True)[0]
    return WALKFORWARD_DEFAULT_DB_PATH


DEFAULT_DB_PATH = resolve_default_db_path()


def _read_machine_detailed_results(db_path: Path) -> pd.DataFrame:
    with sqlite3.connect(str(db_path)) as conn:
        frame = pd.read_sql_query(
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
            """,
            conn,
        )
    if frame.empty:
        raise ValueError(f"machine_detailed_results returned no rows in {db_path}")
    return frame


def _prepare_source(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["date"] = out["date"].astype(str)
    out["date_dt"] = pd.to_datetime(out["date"], format="%Y%m%d", errors="coerce")
    out["machine_number"] = pd.to_numeric(out["machine_number"], errors="coerce")
    out["games_normalized"] = pd.to_numeric(out["games_normalized"], errors="coerce")
    out["diff_coins_normalized"] = pd.to_numeric(out["diff_coins_normalized"], errors="coerce")
    out = out.dropna(subset=["date_dt", "machine_number", "machine_name", "games_normalized", "diff_coins_normalized"]).copy()
    out["machine_number"] = out["machine_number"].astype(int)
    out = out[out["machine_number"] != 2026].copy()
    out["date"] = out["date_dt"].dt.strftime("%Y%m%d")
    return out.reset_index(drop=True)


def _load_machine_types(db_path: Path) -> pd.DataFrame:
    try:
        with sqlite3.connect(str(db_path)) as conn:
            frame = pd.read_sql_query(
                """
                SELECT
                    machine_name_normalized,
                    COALESCE(jug_flag, 0) AS jug_flag,
                    COALESCE(hana_flag, 0) AS hana_flag,
                    COALESCE(oki_flag, 0) AS oki_flag,
                    COALESCE(bt_flag, 0) AS bt_flag
                FROM machine_master
                """,
                conn,
            )
    except sqlite3.Error:
        return pd.DataFrame(columns=["machine_name", "machine_type"])

    if frame.empty:
        return pd.DataFrame(columns=["machine_name", "machine_type"])

    work = frame.rename(columns={"machine_name_normalized": "machine_name"}).copy()
    for col in ("jug_flag", "hana_flag", "oki_flag", "bt_flag"):
        work[col] = pd.to_numeric(work[col], errors="coerce").fillna(0).astype(int)
    work["machine_type"] = np.select(
        [
            work["jug_flag"].eq(1),
            work["hana_flag"].eq(1),
            work["oki_flag"].eq(1),
            work["bt_flag"].eq(1),
        ],
        ["jug", "hana", "oki", "bt"],
        default="other",
    )
    work["machine_name"] = work["machine_name"].astype(str)
    return work.loc[:, ["machine_name", "machine_type"]].drop_duplicates(subset=["machine_name"], keep="first").reset_index(drop=True)


def _select_test_dates(frame: pd.DataFrame, window_days: int, test_dates: Iterable[pd.Timestamp] | None) -> list[pd.Timestamp]:
    if test_dates is not None:
        return [pd.Timestamp(value).normalize() for value in test_dates]
    dates = sorted(pd.to_datetime(frame["date"], format="%Y%m%d", errors="coerce").dropna().dt.normalize().unique())
    if not dates:
        return []
    earliest = dates[0] + pd.Timedelta(days=int(window_days))
    return [date for date in dates if date >= earliest]


def build_relative_targets(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    if "payout_rate" in work.columns:
        work["payout_rate"] = pd.to_numeric(work["payout_rate"], errors="coerce")
    else:
        work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
        work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
        work = work[work["games_normalized"] >= EVALUATION_MIN_GAMES].copy()
        work["payout_rate"] = ((work["games_normalized"] * 3 + work["diff_coins_normalized"]) / (work["games_normalized"] * 3)) * 100
    if "games_normalized" in work.columns:
        work = work[work["games_normalized"] >= EVALUATION_MIN_GAMES].copy()
    if work.empty:
        work["payout_rate"] = pd.Series(dtype="float64")
        work["top20_threshold"] = pd.Series(dtype="float64")
        work["is_top20"] = pd.Series(dtype="bool")
        return work

    work["top20_threshold"] = work.groupby(["date", "segment"])["payout_rate"].transform(lambda s: float(s.quantile(0.8)))
    work["is_top20"] = work["payout_rate"].ge(work["top20_threshold"])
    return work


def _assign_split_period(daily_results: pd.DataFrame) -> pd.DataFrame:
    if daily_results.empty:
        return daily_results.copy()
    out = daily_results.copy()
    unique_dates = sorted(pd.to_datetime(out["test_date"], errors="coerce").dropna().dt.normalize().unique())
    if not unique_dates:
        out["split_period"] = "front"
        return out
    midpoint = max(1, len(unique_dates) // 2)
    front_dates = {pd.Timestamp(value).strftime("%Y-%m-%d") for value in unique_dates[:midpoint]}
    out["split_period"] = out["test_date"].astype(str).map(lambda value: "front" if value in front_dates else "back")
    return out


def _series_metrics(selected: pd.DataFrame, labeled_pool: pd.DataFrame, *, k: int) -> dict[str, float]:
    if labeled_pool.empty:
        return {f"precision_at_{k}": 0.0, f"lift_at_{k}": 0.0, f"avg_payout_at_{k}": 0.0}
    actual_k = min(k, len(selected))
    if actual_k <= 0:
        return {f"precision_at_{k}": 0.0, f"lift_at_{k}": 0.0, f"avg_payout_at_{k}": 0.0}
    selected = selected.head(actual_k)
    hits = float(selected["is_top20"].sum())
    precision = hits / actual_k
    base_rate = float(labeled_pool["is_top20"].mean())
    lift = precision / base_rate if base_rate else 0.0
    avg_payout = float(selected["payout_rate"].mean()) if actual_k else 0.0
    return {
        f"precision_at_{k}": float(precision),
        f"lift_at_{k}": float(lift),
        f"avg_payout_at_{k}": float(avg_payout),
    }


def _select_series_rows(
    scored: pd.DataFrame,
    *,
    series_id: str,
    active_segments: list[str],
    seed: int,
    score_column: str = "composite",
) -> pd.DataFrame:
    if series_id == "nogate_v6a":
        pool = scored.copy()
    else:
        pool = scored[scored["segment"].isin(active_segments)].copy()

    if series_id == "gate_random" and not pool.empty:
        rng = np.random.default_rng(seed)
        pool = pool.iloc[rng.permutation(len(pool))].reset_index(drop=True)
    else:
        pool = pool.sort_values([score_column, "diff_coins_normalized", "machine_number"], ascending=[False, False, True]).reset_index(drop=True)
    return pool


def _build_v6b_rule_features(train: pd.DataFrame, actual: pd.DataFrame, context: ScoreContext) -> pd.DataFrame:
    feature_columns = ["machine_number", "seg_relative_hist_top20", "seg_relative_rank_payout"]
    if actual.empty:
        return pd.DataFrame(columns=feature_columns)

    actual_index = actual.reset_index(drop=True)[["machine_number"]].copy()
    if train.empty:
        actual_index["seg_relative_hist_top20"] = 0.0
        actual_index["seg_relative_rank_payout"] = 0.5
        return actual_index

    train_work = train.copy()
    train_work["machine_number"] = pd.to_numeric(train_work["machine_number"], errors="coerce")
    train_work["games_normalized"] = pd.to_numeric(train_work["games_normalized"], errors="coerce")
    train_work["diff_coins_normalized"] = pd.to_numeric(train_work["diff_coins_normalized"], errors="coerce")
    train_work = train_work.dropna(subset=["machine_number"]).copy()
    train_work["machine_number"] = train_work["machine_number"].astype(int)
    coords = context.coords[["machine_number", "floor", "lr"]].copy()
    train_work = train_work.merge(coords, on="machine_number", how="left", validate="m:1")
    train_work["segment"] = (
        train_work["floor"].astype(str) + "_" + train_work["lr"].astype(str) + "_" + train_work["machine_name"].map(classify_seg)
    )
    train_work = train_work[train_work["games_normalized"] >= EVALUATION_MIN_GAMES].copy()
    train_work = train_work.dropna(subset=["date", "segment", "machine_number"]).copy()
    if train_work.empty:
        return actual_index

    train_work["payout_rate"] = ((train_work["games_normalized"] * 3 + train_work["diff_coins_normalized"]) / (train_work["games_normalized"] * 3)) * 100

    top20_work = train_work.copy()
    top20_threshold = top20_work.groupby(["date", "segment"])["payout_rate"].transform(lambda s: float(s.quantile(0.8)))
    top20_work["is_top20"] = top20_work["payout_rate"].ge(top20_threshold)
    top20_by_machine = (
        top20_work.groupby("machine_number", as_index=False)
        .agg(seg_relative_hist_top20=("is_top20", "mean"))
    )

    rank_work = train_work.copy()
    rank_work["seg_relative_rank_payout"] = rank_work.groupby(["date", "segment"])["payout_rate"].rank(method="average", ascending=True, pct=True)
    rank_by_machine = (
        rank_work.groupby("machine_number", as_index=False)
        .agg(seg_relative_rank_payout=("seg_relative_rank_payout", "mean"))
    )

    features = actual_index.merge(top20_by_machine, on="machine_number", how="left").merge(rank_by_machine, on="machine_number", how="left", suffixes=("", "_rank"))
    features["seg_relative_hist_top20"] = pd.to_numeric(features["seg_relative_hist_top20"], errors="coerce").fillna(0.0)
    features["seg_relative_rank_payout"] = pd.to_numeric(features["seg_relative_rank_payout"], errors="coerce").fillna(0.5)
    return features[feature_columns]


def _build_v6b_rule_score(train: pd.DataFrame, scored_v6a: pd.DataFrame, context: ScoreContext) -> pd.DataFrame:
    scored = scored_v6a.copy()
    features = _build_v6b_rule_features(train, scored, context)
    scored = scored.merge(features, on="machine_number", how="left", validate="1:1")
    scored["seg_relative_hist_top20"] = pd.to_numeric(scored["seg_relative_hist_top20"], errors="coerce").fillna(0.0)
    scored["seg_relative_rank_payout"] = pd.to_numeric(scored["seg_relative_rank_payout"], errors="coerce").fillna(0.5)
    composite_mean = float(scored["composite"].mean()) if not scored.empty else 0.0
    composite_std = float(scored["composite"].std()) if not scored.empty else 1.0
    if not np.isfinite(composite_mean):
        composite_mean = 0.0
    if not np.isfinite(composite_std) or composite_std < 1e-6:
        composite_std = 1e-6
    f1_scaled = scored["seg_relative_hist_top20"] * composite_std + composite_mean
    f2_scaled = scored["seg_relative_rank_payout"] * composite_std + composite_mean
    scored["composite_v6b_rule"] = scored["composite"] * 0.70 + f1_scaled * 0.20 + f2_scaled * 0.10
    return scored


def _build_rolling_cache(source: pd.DataFrame) -> pd.DataFrame:
    """rolling_diff計算用の軽量テーブルを1回だけ構築する。"""
    cols = ["machine_number", "date_dt", "diff_coins_normalized"]
    work = source[cols].copy()
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    return work.sort_values("date_dt").reset_index(drop=True)


def _calc_rolling_diff(rolling_cache: pd.DataFrame, target_machines: pd.Series, n_days: int, ref_date: pd.Timestamp) -> pd.Series:
    cutoff = ref_date - pd.Timedelta(days=n_days)
    mask = (rolling_cache["date_dt"] >= cutoff) & (rolling_cache["date_dt"] < ref_date)
    recent = rolling_cache.loc[mask]
    if recent.empty:
        return pd.Series(0.0, index=target_machines.index)
    avg_by_machine = recent.groupby("machine_number")["diff_coins_normalized"].mean()
    return target_machines.map(avg_by_machine).fillna(0.0)


def _attach_v2_features(
    scored: pd.DataFrame,
    machine_types: pd.DataFrame,
    rolling_cache: pd.DataFrame,
    ref_date: pd.Timestamp,
    is_event_flag: bool,
) -> pd.DataFrame:
    """v2特徴量を追加。machine_types mergeとrolling_diff計算。"""
    if "machine_type" not in scored.columns:
        scored = scored.merge(machine_types, on="machine_name", how="left")
        scored["machine_type"] = scored["machine_type"].fillna("other").astype(str)
    scored["rolling_diff_7d"] = _calc_rolling_diff(rolling_cache, scored["machine_number"], 7, ref_date)
    scored["rolling_diff_14d"] = _calc_rolling_diff(rolling_cache, scored["machine_number"], 14, ref_date)
    scored["rolling_diff_28d"] = _calc_rolling_diff(rolling_cache, scored["machine_number"], 28, ref_date)
    scored["is_event"] = int(is_event_flag)
    return scored


def _prepare_ml_frame(frame: pd.DataFrame, *, features: list[str], cat_features: list[str]) -> pd.DataFrame:
    work = frame.copy()
    for col in features:
        if col in cat_features:
            work[col] = work[col].fillna("other").astype(str)
        else:
            work[col] = pd.to_numeric(work[col], errors="coerce")
    return work


def _make_catboost_pool(frame: pd.DataFrame, *, label: pd.Series | None = None):
    if Pool is None:
        raise RuntimeError("catboost is required to train the model.")
    prepared = _prepare_ml_frame(frame, features=ML_FEATURES, cat_features=CAT_FEATURES)
    cat_indices = [ML_FEATURES.index(name) for name in CAT_FEATURES]
    if label is None:
        return Pool(prepared[ML_FEATURES], cat_features=cat_indices)
    return Pool(prepared[ML_FEATURES], label=label, cat_features=cat_indices)


def _fit_catboost_model(train_frame: pd.DataFrame, y_train: pd.Series) -> object:
    if CatBoostClassifier is None:
        raise RuntimeError("catboost is required to train the model.")
    train_pool = _make_catboost_pool(train_frame, label=y_train)
    params = dict(
        iterations=200,
        depth=4,
        learning_rate=0.05,
        l2_leaf_reg=5.0,
        random_seed=42,
        verbose=0,
        eval_metric="Logloss",
        auto_class_weights="Balanced",
        task_type="GPU",
        devices="0",
    )
    try:
        model = CatBoostClassifier(**params)
        model.fit(train_pool)
    except Exception:
        cpu_params = {k: v for k, v in params.items() if k not in {"task_type", "devices"}}
        cpu_params["task_type"] = "CPU"
        model = CatBoostClassifier(**cpu_params)
        model.fit(train_pool)
    return model


def _safe_roc_auc(y_true: pd.Series, y_score: pd.Series) -> float:
    aligned = pd.DataFrame(
        {
            "y_true": pd.to_numeric(y_true, errors="coerce"),
            "y_score": pd.to_numeric(y_score, errors="coerce"),
        }
    ).dropna()
    if aligned.empty or aligned["y_true"].nunique() < 2:
        return float("nan")
    try:
        return float(roc_auc_score(aligned["y_true"], aligned["y_score"]))
    except ValueError:
        return float("nan")


def _build_ml_train_data(
    source: pd.DataFrame,
    test_dt: pd.Timestamp,
    window_days: int,
    variant: object,
    context: ScoreContext,
    machine_types: pd.DataFrame,
    rolling_cache: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.Series, int]:
    train_start = test_dt - pd.Timedelta(days=ML_HISTORY_DAYS + ML_RECENT_DAYS)
    train = source[(source["date_dt"] >= train_start) & (source["date_dt"] < test_dt)]
    split_dt = test_dt - pd.Timedelta(days=ML_RECENT_DAYS)
    history = train[train["date_dt"] < split_dt]
    recent = train[train["date_dt"] >= split_dt]
    if history.empty or recent.empty:
        return pd.DataFrame(columns=ML_FEATURES), pd.Series(dtype="int64"), 0

    rows: list[pd.DataFrame] = []
    recent_dates = sorted(pd.to_datetime(recent["date_dt"], errors="coerce").dropna().dt.normalize().unique())
    for day_dt in recent_dates:
        day_dt = pd.Timestamp(day_dt).normalize()
        day_actual = recent[recent["date_dt"].eq(day_dt)]
        if day_actual.empty:
            continue
        scored = score_day(history, day_actual, variant, test_date=day_dt, context=context)
        if scored.empty:
            continue
        scored = scored.merge(_build_v6b_rule_features(history, scored, context), on="machine_number", how="left", validate="1:1")
        scored["seg_relative_hist_top20"] = pd.to_numeric(scored["seg_relative_hist_top20"], errors="coerce").fillna(0.0)
        scored["seg_relative_rank_payout"] = pd.to_numeric(scored["seg_relative_rank_payout"], errors="coerce").fillna(0.5)
        scored = _attach_v2_features(scored, machine_types, rolling_cache, day_dt, bool(is_event_day(day_dt.strftime("%Y%m%d"))))
        labeled = build_relative_targets(scored)
        if labeled.empty:
            continue
        rows.append(labeled[ML_FEATURES + ["is_top20"]].copy())

    if not rows:
        return pd.DataFrame(columns=ML_FEATURES), pd.Series(dtype="int64"), 0

    all_data = pd.concat(rows, ignore_index=True)
    numeric_features = [col for col in ML_FEATURES if col not in CAT_FEATURES]
    all_data[numeric_features] = all_data[numeric_features].apply(pd.to_numeric, errors="coerce")
    all_data[CAT_FEATURES] = all_data[CAT_FEATURES].fillna("other").astype(str)
    X = all_data[ML_FEATURES].copy()
    y = all_data["is_top20"].astype(int)
    return X, y, int(len(all_data))


def _active_test_dates(daily_results: pd.DataFrame) -> set[str]:
    if daily_results.empty:
        return set()
    active_rows = daily_results[(daily_results["series_id"] != "nogate_v6a") & (daily_results["n_active_machines"] > 0)]
    return set(active_rows["test_date"].astype(str).tolist())


def _format_markdown_table(frame: pd.DataFrame, *, float_digits: int = 3) -> str:
    if frame.empty:
        return "No rows."
    cols = [str(col) for col in frame.columns]
    header = "| " + " | ".join(cols) + " |"
    separator = "| " + " | ".join(["---"] * len(cols)) + " |"
    rows: list[str] = []
    for _, row in frame.iterrows():
        values: list[str] = []
        for col in frame.columns:
            value = row[col]
            if pd.isna(value):
                values.append("")
            elif isinstance(value, float):
                values.append(f"{value:.{float_digits}f}")
            else:
                values.append(str(value))
        rows.append("| " + " | ".join(values) + " |")
    return "\n".join([header, separator, *rows])


def _build_summary(daily_results: pd.DataFrame) -> pd.DataFrame:
    if daily_results.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)

    by_group = (
        daily_results.groupby(["series_id", "event_type"], as_index=False)
        .agg(
            precision_at_10=("precision_at_10", "mean"),
            precision_at_15=("precision_at_15", "mean"),
            lift_at_10=("lift_at_10", "mean"),
            lift_at_15=("lift_at_15", "mean"),
            avg_payout_at_10=("avg_payout_at_10", "mean"),
            avg_payout_at_15=("avg_payout_at_15", "mean"),
            n_test_days=("test_date", "nunique"),
            n_days_active_lt_10=("n_days_active_lt_10", "sum"),
        )
        .reset_index(drop=True)
    )

    all_rows = (
        daily_results.groupby(["series_id"], as_index=False)
        .agg(
            precision_at_10=("precision_at_10", "mean"),
            precision_at_15=("precision_at_15", "mean"),
            lift_at_10=("lift_at_10", "mean"),
            lift_at_15=("lift_at_15", "mean"),
            avg_payout_at_10=("avg_payout_at_10", "mean"),
            avg_payout_at_15=("avg_payout_at_15", "mean"),
            n_test_days=("test_date", "nunique"),
            n_days_active_lt_10=("n_days_active_lt_10", "sum"),
        )
        .assign(event_type="all")
        .reset_index(drop=True)
    )

    summary = pd.concat([by_group, all_rows], ignore_index=True)
    summary["series_id"] = pd.Categorical(summary["series_id"], categories=SERIES_ORDER, ordered=True)
    summary = summary.sort_values(["series_id", "event_type"]).reset_index(drop=True)
    return summary[SUMMARY_COLUMNS]


def _build_front_back_split(daily_results: pd.DataFrame) -> pd.DataFrame:
    if daily_results.empty:
        return pd.DataFrame(columns=SPLIT_COLUMNS)
    grouped = (
        daily_results.groupby(["series_id", "split_period"], as_index=False)
        .agg(
            precision_at_10=("precision_at_10", "mean"),
            precision_at_15=("precision_at_15", "mean"),
            lift_at_10=("lift_at_10", "mean"),
            avg_payout_at_10=("avg_payout_at_10", "mean"),
            n_test_days=("test_date", "nunique"),
            n_days_active_lt_10=("n_days_active_lt_10", "sum"),
        )
        .reset_index(drop=True)
    )
    grouped["series_id"] = pd.Categorical(grouped["series_id"], categories=SERIES_ORDER, ordered=True)
    grouped["split_period"] = pd.Categorical(grouped["split_period"], categories=("front", "back"), ordered=True)
    return grouped.sort_values(["series_id", "split_period"]).reset_index(drop=True)[SPLIT_COLUMNS]


def _build_report(
    summary: pd.DataFrame,
    active_daily_results: pd.DataFrame,
    front_back_split: pd.DataFrame,
    *,
    output_dir: Path,
    gate_daily_results: pd.DataFrame,
    ml_enabled: bool,
    ml_fallback_days: int,
) -> str:
    all_precision = active_daily_results.groupby("series_id", as_index=False).agg(precision_at_10=("precision_at_10", "mean"))
    split_precision = active_daily_results.groupby(["series_id", "split_period"], as_index=False).agg(precision_at_10=("precision_at_10", "mean"))

    def _value(series_id: str, split_period: str | None = None) -> float:
        if split_period is None:
            row = all_precision[all_precision["series_id"].eq(series_id)]
        else:
            row = split_precision[(split_precision["series_id"].eq(series_id)) & (split_precision["split_period"].eq(split_period))]
        if row.empty:
            return 0.0
        return float(row["precision_at_10"].iloc[0])

    checks = [
        ("gate_v6a precision@10 > nogate_v6a precision@10 (all)", _value("gate_v6a") > _value("nogate_v6a")),
        ("gate_v6a precision@10 > nogate_v6a precision@10 (front)", _value("gate_v6a", "front") > _value("nogate_v6a", "front")),
        ("gate_v6a precision@10 > nogate_v6a precision@10 (back)", _value("gate_v6a", "back") > _value("nogate_v6a", "back")),
        ("gate_v6a precision@10 > gate_random precision@10", _value("gate_v6a") > _value("gate_random")),
        ("gate_v6b_rule precision@10 > gate_v6a precision@10 (all)", _value(GATE_V6B_RULE_ID) > _value("gate_v6a")),
        ("gate_v6b_rule precision@10 > gate_v6a precision@10 (front)", _value(GATE_V6B_RULE_ID, "front") > _value("gate_v6a", "front")),
        ("gate_v6b_rule precision@10 > gate_v6a precision@10 (back)", _value(GATE_V6B_RULE_ID, "back") > _value("gate_v6a", "back")),
    ]
    if ml_enabled:
        checks.extend(
            [
                ("gate_ml_shadow precision@10 > gate_v6b_rule precision@10 + 0.05 (all)", _value(GATE_ML_SHADOW_ID) > (_value(GATE_V6B_RULE_ID) + 0.05)),
                ("gate_ml_shadow precision@10 > gate_v6b_rule precision@10 (front)", _value(GATE_ML_SHADOW_ID, "front") > _value(GATE_V6B_RULE_ID, "front")),
                ("gate_ml_shadow precision@10 > gate_v6b_rule precision@10 (back)", _value(GATE_ML_SHADOW_ID, "back") > _value(GATE_V6B_RULE_ID, "back")),
                ("gate_ml_shadow precision@10 > gate_random precision@10", _value(GATE_ML_SHADOW_ID) > _value("gate_random")),
            ]
        )
    verdict = "PASS" if all(passed for _, passed in checks) else ("PARTIAL" if any(passed for _, passed in checks) else "FAIL")

    report_lines: list[str] = [
        "# Gate Ranking Connection Test Report",
        "",
        f"Output: `{output_dir.as_posix()}`",
        f"Test days: {active_daily_results['test_date'].nunique() if not active_daily_results.empty else 0}",
        f"CatBoost available: {'yes' if ml_enabled else 'no'}",
        f"ML fallback days: {ml_fallback_days}",
        "",
        "## 1. Series Comparison (Active Days Only)",
        "",
        _format_markdown_table(summary[summary["event_type"] == "all"].copy()),
        "",
        "## 2. Event vs Non-Event",
        "",
        _format_markdown_table(summary[summary["event_type"].isin(["event", "non_event"])].copy()),
        "",
        "## 3. Front/Back Stability",
        "",
        _format_markdown_table(front_back_split.copy()),
        "",
        "## 4. Gate Coverage",
        "",
        _format_markdown_table(
            gate_daily_results.groupby("series_id", as_index=False)
            .agg(
                n_active_machines=("n_active_machines", "mean"),
                n_days_active_lt_10=("n_days_active_lt_10", "sum"),
                n_test_days=("test_date", "nunique"),
            )
            .reset_index(drop=True)
        ),
        "",
        "## 5. ML Shadow vs Rule-Based",
        "",
    ]

    if ml_enabled:
        ml_frame = active_daily_results[active_daily_results["series_id"].isin([GATE_V6B_RULE_ID, GATE_ML_SHADOW_ID])].copy()
        ml_precision = ml_frame.groupby("series_id", as_index=False).agg(precision_at_10=("precision_at_10", "mean"))
        ml_split = ml_frame.groupby(["series_id", "split_period"], as_index=False).agg(precision_at_10=("precision_at_10", "mean"))
        ml_auc_mean = float(ml_frame.loc[ml_frame["series_id"].eq(GATE_ML_SHADOW_ID), "ml_auc"].dropna().mean())

        def _ml_value(series_id: str, split_period: str | None = None) -> float:
            if split_period is None:
                row = ml_precision[ml_precision["series_id"].eq(series_id)]
            else:
                row = ml_split[(ml_split["series_id"].eq(series_id)) & (ml_split["split_period"].eq(split_period))]
            if row.empty:
                return float("nan")
            return float(row["precision_at_10"].iloc[0])

        report_lines.extend(
            [
                "| metric | gate_v6b_rule | gate_ml_shadow | delta |",
                "|--------|---------------|----------------|-------|",
                f"| p@10 (all) | {_ml_value(GATE_V6B_RULE_ID):.3f} | {_ml_value(GATE_ML_SHADOW_ID):.3f} | {(_ml_value(GATE_ML_SHADOW_ID) - _ml_value(GATE_V6B_RULE_ID)):.3f} |",
                f"| p@10 (front) | {_ml_value(GATE_V6B_RULE_ID, 'front'):.3f} | {_ml_value(GATE_ML_SHADOW_ID, 'front'):.3f} | {(_ml_value(GATE_ML_SHADOW_ID, 'front') - _ml_value(GATE_V6B_RULE_ID, 'front')):.3f} |",
                f"| p@10 (back) | {_ml_value(GATE_V6B_RULE_ID, 'back'):.3f} | {_ml_value(GATE_ML_SHADOW_ID, 'back'):.3f} | {(_ml_value(GATE_ML_SHADOW_ID, 'back') - _ml_value(GATE_V6B_RULE_ID, 'back')):.3f} |",
                f"| AUC (all) | N/A | {ml_auc_mean:.3f} | N/A |",
                "",
                "## 6. Segment-Level Detail",
                "",
                _format_markdown_table(
                    active_daily_results.assign(active_segments=active_daily_results["active_segments"].fillna("").astype(str))
                    .groupby(["series_id", "active_segments"], as_index=False)
                    .agg(
                        precision_at_10=("precision_at_10", "mean"),
                        precision_at_15=("precision_at_15", "mean"),
                        lift_at_10=("lift_at_10", "mean"),
                        n_test_days=("test_date", "nunique"),
                    )
                    .reset_index(drop=True)
                ),
                "",
                "## 7. Pass/Fail Judgment",
                "",
            ]
        )
    else:
        report_lines.extend(
            [
                "CatBoost is unavailable in this environment, so gate_ml_shadow was skipped.",
                "",
                "## 6. Segment-Level Detail",
                "",
                _format_markdown_table(
                    active_daily_results.assign(active_segments=active_daily_results["active_segments"].fillna("").astype(str))
                    .groupby(["series_id", "active_segments"], as_index=False)
                    .agg(
                        precision_at_10=("precision_at_10", "mean"),
                        precision_at_15=("precision_at_15", "mean"),
                        lift_at_10=("lift_at_10", "mean"),
                        n_test_days=("test_date", "nunique"),
                    )
                    .reset_index(drop=True)
                ),
                "",
                "## 7. Pass/Fail Judgment",
                "",
            ]
        )
    for label, passed in checks:
        report_lines.append(f"- [{'x' if passed else ' '}] {label}")
    report_lines.extend(["", f"Overall verdict: PASS / FAIL / PARTIAL -> **{verdict}**", ""])
    return "\n".join(report_lines)


def run_gate_ranking_test(
    *,
    db_path: Path | None = None,
    output_dir: Path,
    window_days: int = 90,
    max_days: int | None = None,
    test_dates: Iterable[pd.Timestamp] | None = None,
    seed: int = 0,
    df: pd.DataFrame | None = None,
    segment_daily_counts: pd.DataFrame | None = None,
    context: ScoreContext | None = None,
) -> dict[str, pd.DataFrame | str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    context = context or build_score_context()
    source = _prepare_source(df if df is not None else _read_machine_detailed_results(db_path or DEFAULT_DB_PATH))
    machine_types = _load_machine_types(db_path or DEFAULT_DB_PATH) if HAS_CATBOOST else pd.DataFrame(columns=["machine_name", "machine_type"])
    rolling_cache = _build_rolling_cache(source)
    selected_test_dates = _select_test_dates(source, window_days, test_dates)
    if max_days is not None:
        if max_days < 0:
            raise ValueError("--max-days must be non-negative")
        selected_test_dates = selected_test_dates[:max_days]
    if segment_daily_counts is None:
        segment_daily_counts = build_segment_daily_counts(db_path or DEFAULT_DB_PATH)

    variant_cfg = build_variant_configs()[V6A_VARIANT_ID]
    active_series_order = SERIES_ORDER if HAS_CATBOOST else tuple(series_id for series_id in SERIES_ORDER if series_id != GATE_ML_SHADOW_ID)
    daily_rows: list[dict[str, object]] = []
    total = len(selected_test_dates)
    started_at = time.perf_counter()
    ml_fallback_days = 0

    for index, test_date in enumerate(selected_test_dates, start=1):
        test_dt = pd.Timestamp(test_date).normalize()
        train = source[(source["date_dt"] < test_dt) & (source["date_dt"] >= (test_dt - pd.Timedelta(days=int(window_days))))].copy()
        actual = source[source["date_dt"].eq(test_dt)].copy()
        if train.empty or actual.empty:
            continue
        scored = score_day(train, actual, variant_cfg, test_date=test_dt, context=context)
        labeled = build_relative_targets(scored)
        if labeled.empty:
            continue

        gate_rows = segment_daily_counts[segment_daily_counts["date"].astype(str).eq(test_dt.strftime("%Y%m%d"))].copy()
        active_segments = gate_rows[gate_rows["eligible_for_gate"] & gate_rows["gate_positive"]]["segment"].astype(str).tolist()
        active_segments = list(dict.fromkeys(active_segments))
        active_pool = scored[scored["segment"].isin(active_segments)].copy()
        is_event = bool(is_event_day(test_dt.strftime("%Y%m%d")))
        event_type = "event" if is_event else "non_event"
        dd = int(test_dt.day)
        dow = test_dt.day_name()[:3]
        active_segments_text = ",".join(active_segments)
        n_active_machines = int(len(active_pool))
        n_active_segments = int(len(active_segments))
        n_days_active_lt_10 = int(n_active_machines < 10) if n_active_segments > 0 else 0
        total_machines = int(len(labeled))
        scored_v6b = _build_v6b_rule_score(train, scored, context)

        series_rows = {
            "nogate_v6a": _select_series_rows(scored, series_id="nogate_v6a", active_segments=active_segments, seed=seed),
            "gate_v6a": _select_series_rows(scored, series_id="gate_v6a", active_segments=active_segments, seed=seed),
            "gate_random": _select_series_rows(scored, series_id="gate_random", active_segments=active_segments, seed=seed + int(test_dt.strftime("%Y%m%d"))),
            GATE_V6B_RULE_ID: _select_series_rows(
                scored_v6b,
                series_id=GATE_V6B_RULE_ID,
                active_segments=active_segments,
                seed=seed,
                score_column="composite_v6b_rule",
            ),
        }
        ml_auc = float("nan")
        ml_train_samples = 0

        if HAS_CATBOOST:
            X_train, y_train, ml_train_samples = _build_ml_train_data(source, test_dt, window_days, variant_cfg, context, machine_types, rolling_cache)
            if ml_train_samples >= ML_MIN_TRAIN_ROWS:
                try:
                    model = _fit_catboost_model(X_train, y_train)
                    scored_ml = _attach_v2_features(scored_v6b.copy(), machine_types, rolling_cache, test_dt, is_event)
                    X_test = _make_catboost_pool(scored_ml)
                    scored_ml["ml_prob"] = model.predict_proba(X_test)[:, 1]
                    active_eval = scored_ml[scored_ml["segment"].isin(active_segments)].merge(
                        labeled[["date", "segment", "machine_number", "is_top20", "payout_rate", "top20_threshold"]],
                        on=["date", "segment", "machine_number"],
                        how="left",
                        validate="1:1",
                    )
                    ml_auc = _safe_roc_auc(active_eval["is_top20"], active_eval["ml_prob"])
                except Exception:
                    ml_fallback_days += 1
                    scored_ml = _attach_v2_features(scored_v6b.copy(), machine_types, rolling_cache, test_dt, is_event)
                    scored_ml["ml_prob"] = scored_ml["composite_v6b_rule"]
                    ml_auc = float("nan")
            else:
                ml_fallback_days += 1
                scored_ml = _attach_v2_features(scored_v6b.copy(), machine_types, rolling_cache, test_dt, is_event)
                scored_ml["ml_prob"] = scored_ml["composite_v6b_rule"]
            series_rows[GATE_ML_SHADOW_ID] = _select_series_rows(
                scored_ml,
                series_id=GATE_ML_SHADOW_ID,
                active_segments=active_segments,
                seed=seed,
                score_column="ml_prob",
            )

        for series_id in active_series_order:
            selected = series_rows[series_id].merge(
                labeled[["date", "segment", "machine_number", "is_top20", "payout_rate", "top20_threshold"]],
                on=["date", "segment", "machine_number"],
                how="left",
                validate="1:1",
            )
            metrics_10 = _series_metrics(selected, labeled, k=10)
            metrics_15 = _series_metrics(selected, labeled, k=15)
            daily_rows.append(
                {
                    "test_date": test_dt.strftime("%Y-%m-%d"),
                    "series_id": series_id,
                    "dd": dd,
                    "dow": dow,
                    "is_event": is_event,
                    "event_type": event_type,
                    "n_total_machines": total_machines,
                    "n_active_machines": n_active_machines if series_id != "nogate_v6a" else total_machines,
                    "n_active_segments": n_active_segments if series_id != "nogate_v6a" else int(labeled["segment"].nunique()),
                    "active_segments": active_segments_text if series_id != "nogate_v6a" else ",".join(sorted(labeled["segment"].astype(str).unique())),
                    "precision_at_10": metrics_10["precision_at_10"],
                    "precision_at_15": metrics_15["precision_at_15"],
                    "lift_at_10": metrics_10["lift_at_10"],
                    "lift_at_15": metrics_15["lift_at_15"],
                    "avg_payout_at_10": metrics_10["avg_payout_at_10"],
                    "avg_payout_at_15": metrics_15["avg_payout_at_15"],
                    "split_period": "",
                    "n_days_active_lt_10": n_days_active_lt_10 if series_id != "nogate_v6a" else 0,
                    "ml_auc": ml_auc if series_id == GATE_ML_SHADOW_ID else np.nan,
                }
            )

        if total and index % 10 == 0:
            elapsed = time.perf_counter() - started_at
            remaining = max(0.0, (elapsed / index) * (total - index)) if index else 0.0
            print(
                f"[Progress] {index}/{total} ({index * 100 // total}%) elapsed={elapsed:.1f}s remaining≈{remaining:.1f}s train_samples={ml_train_samples}",
                file=sys.stderr,
                flush=True,
            )

    daily_results = pd.DataFrame(daily_rows, columns=DAILY_COLUMNS)
    daily_results = _assign_split_period(daily_results)
    active_test_dates = _active_test_dates(daily_results)
    active_daily_results = daily_results[daily_results["test_date"].isin(active_test_dates)].copy()
    summary = _build_summary(active_daily_results)
    front_back_split = _build_front_back_split(active_daily_results)
    report_text = _build_report(
        summary,
        active_daily_results,
        front_back_split,
        output_dir=output_dir,
        gate_daily_results=daily_results,
        ml_enabled=HAS_CATBOOST,
        ml_fallback_days=ml_fallback_days,
    )

    summary.to_csv(output_dir / "summary.csv", index=False, encoding="utf-8-sig")
    daily_results.to_csv(output_dir / "daily_results.csv", index=False, encoding="utf-8-sig")
    front_back_split.to_csv(output_dir / "front_back_split.csv", index=False, encoding="utf-8-sig")
    (output_dir / "report.md").write_text(report_text, encoding="utf-8")

    return {
        "summary": summary,
        "daily_results": daily_results,
        "front_back_split": front_back_split,
        "report": report_text,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate ranking connection test")
    parser.add_argument("--db-path", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "ml" / "experiments" / "gate_ranking_test" / "results_v2")
    parser.add_argument("--window-days", type=int, default=90)
    parser.add_argument("--max-days", type=int, default=None)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    result = run_gate_ranking_test(
        db_path=args.db_path,
        output_dir=args.output_dir,
        window_days=args.window_days,
        max_days=args.max_days,
        seed=args.seed,
    )
    print(result["report"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
