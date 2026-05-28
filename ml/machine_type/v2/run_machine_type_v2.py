from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import time
import unicodedata
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.metrics import roc_auc_score

from ml.evaluators.metrics import calculate_hit_at_k
from ml.machine_type import machine_type_common as common

SEGMENT_KEYS = ("2F", "3F")
LAYER1_FEATURES = (
    "weekday_prior_top1_rate",
    "prior_top1_rate",
    "day_of_month",
    "day_of_week_num",
    "is_weekend",
    "lag1_rank_pct",
)
MACHINE_TYPE_TO_CODE = {"AT系": 0, "A型": 1, "BT": 2}
DEFAULT_FEATURE_PROFILE = "baseline6"
DEFAULT_TARGET_POLICY = "default"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Machine type v2 two-layer pipeline")
    p.add_argument("--db-path", default="", help="SQLite DB path. Empty means auto-detect db/*7.db")
    p.add_argument("--output-dir", default="ml/machine_type/v2/output", help="Output directory")
    p.add_argument("--alpha", type=float, default=5.0, help="Shrinkage alpha for rank labels")
    p.add_argument("--min-train-days", type=int, default=120, help="Minimum train days for layer1")
    p.add_argument("--eval-days", type=int, default=30, help="Most recent days to evaluate")
    p.add_argument(
        "--eval-offset-days",
        type=int,
        default=0,
        help="Skip this many most recent days before evaluating (for tune/holdout separation)",
    )
    p.add_argument("--step-days", type=int, default=1, help="Stride for walk-forward eval dates")
    p.add_argument("--rolling-prior-window", type=int, default=90, help="Rolling window for prior rates")
    p.add_argument("--layer0-threshold", type=float, default=0.5, help="Layer0 decision threshold")
    p.add_argument(
        "--layer0-winrate-threshold",
        type=float,
        default=80.0,
        help="Label threshold for is_kisyuzen: win_rate >= threshold",
    )
    p.add_argument(
        "--feature-profile",
        choices=["baseline6", "rich_all", "rich_no_ranktrend"],
        default=DEFAULT_FEATURE_PROFILE,
        help="Layer1 feature profile",
    )
    p.add_argument(
        "--target-policy",
        choices=["default", "2fn_top5"],
        default=DEFAULT_TARGET_POLICY,
        help="Layer1 target policy by segment",
    )
    p.add_argument(
        "--min-machine-history-days",
        type=int,
        default=60,
        help="Layer1学習対象に含める機種の最低履歴日数。"
        "最新日に稼働中かつこの日数以上のデータがある機種のみ使用。"
        "0を指定するとフィルターなし（従来動作）。",
    )
    p.add_argument(
        "--combined-lambda",
        type=float,
        default=0.5,
        help="Weight for layer0 probability in final score: layer1*(1+lambda*layer0)",
    )
    p.add_argument(
        "--games-feature-mode",
        choices=["none", "vs_seg", "vs_seg_and_trend"],
        default="none",
        help="Layer1に回転数派生特徴量を追加するモード",
    )
    p.add_argument("--random-state", type=int, default=42)
    return p


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_auc(y_true: np.ndarray, y_score: np.ndarray) -> float | None:
    if y_true.size == 0:
        return None
    if np.unique(y_true).size < 2:
        return None
    return float(roc_auc_score(y_true, y_score))


def _normalize_machine_name(value: Any) -> str:
    if pd.isna(value):
        return ""
    s = unicodedata.normalize("NFKC", str(value))
    s = s.strip().lower()
    s = re.sub(r"\s+", "", s)
    return s


def _daily_hit_at_k(
    pred_df: pd.DataFrame,
    *,
    score_col: str,
    label_col: str,
    k: int,
) -> float:
    if pred_df.empty:
        return 0.0
    hits: list[int] = []
    for _, group in pred_df.groupby("date", sort=True):
        if group.empty:
            continue
        topk = group.nlargest(min(int(k), len(group)), score_col)
        hit = int((topk[label_col].astype(int) == 1).any())
        hits.append(hit)
    if not hits:
        return 0.0
    return float(np.mean(hits))


def _prob_hit_random(y_true_group: np.ndarray, k: int) -> float:
    n = int(y_true_group.size)
    m = int(np.sum(y_true_group))
    if n <= 0 or k <= 0 or m <= 0:
        return 0.0
    kk = min(int(k), n)
    total = math.comb(n, kk)
    if total <= 0:
        return 0.0
    if n - m < kk:
        return 1.0
    miss = math.comb(n - m, kk)
    return float(1.0 - (miss / total))


def _classify_machine_type(jug_flag: Any, hana_flag: Any, bt_flag: Any) -> str:
    jug = int(pd.to_numeric(jug_flag, errors="coerce") or 0)
    hana = int(pd.to_numeric(hana_flag, errors="coerce") or 0)
    bt = int(pd.to_numeric(bt_flag, errors="coerce") or 0)
    if jug == 1 or hana == 1:
        return "A型"
    if bt == 1:
        return "BT"
    return "AT系"


def load_layer0_kisyuzen_frame(
    db_path: Path,
    *,
    rolling_prior_window: int,
    winrate_threshold: float,
) -> pd.DataFrame:
    con = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(
            """
            SELECT
                mdr.machine_name AS machine_name,
                mdr.date AS date,
                COUNT(*) AS n_machines,
                ROUND(
                    100.0 * SUM(CASE WHEN CAST(mdr.diff_coins_normalized AS REAL) > 0 THEN 1 ELSE 0 END) / COUNT(*),
                    1
                ) AS win_rate,
                AVG(CAST(mdr.diff_coins_normalized AS REAL)) AS avg_diff,
                COALESCE(mm.jug_flag, 0) AS jug_flag,
                COALESCE(mm.hana_flag, 0) AS hana_flag,
                COALESCE(mm.bt_flag, 0) AS bt_flag
            FROM machine_detailed_results mdr
            LEFT JOIN machine_master mm
              ON mdr.machine_name = mm.machine_name_normalized
            GROUP BY mdr.machine_name, mdr.date
            HAVING COUNT(*) >= 3
            ORDER BY mdr.machine_name, mdr.date
            """,
            con,
        )
    finally:
        con.close()
    if df.empty:
        raise ValueError("layer0 source query returned no rows")
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["date", "machine_name"]).copy()
    df["n_machines"] = pd.to_numeric(df["n_machines"], errors="coerce").fillna(0).astype(int)
    df["win_rate"] = pd.to_numeric(df["win_rate"], errors="coerce").fillna(0.0)
    df["avg_diff"] = pd.to_numeric(df["avg_diff"], errors="coerce").fillna(0.0)
    for col in ("jug_flag", "hana_flag", "bt_flag"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    df["machine_type"] = df.apply(
        lambda r: _classify_machine_type(r["jug_flag"], r["hana_flag"], r["bt_flag"]),
        axis=1,
    )
    df["machine_type_encoded"] = df["machine_type"].map(MACHINE_TYPE_TO_CODE).fillna(-1).astype(int)
    df["is_kisyuzen"] = (df["win_rate"] >= float(winrate_threshold)).astype(int)
    df["day_of_month"] = df["date"].dt.day.astype(int)
    df["day_of_week_num"] = df["date"].dt.dayofweek.astype(int)
    df["is_weekend"] = df["day_of_week_num"].isin([5, 6]).astype(int)
    df = df.sort_values(["machine_name", "date"]).reset_index(drop=True)

    g = df.groupby("machine_name", sort=False)
    df["lag1_win_rate"] = g["win_rate"].shift(1)
    df["lag7_win_rate"] = g["win_rate"].shift(7)
    df["roll7_win_rate"] = g["win_rate"].transform(
        lambda x: x.rolling(7, min_periods=2).mean().shift(1)
    )
    df["prior_kisyuzen_rate"] = g["is_kisyuzen"].transform(
        lambda x: x.rolling(max(int(rolling_prior_window), 1), min_periods=10).mean().shift(1)
    )
    return df


def run_layer0_walkforward(
    frame: pd.DataFrame,
    *,
    eval_days: int,
    eval_offset_days: int,
    random_state: int,
    layer0_threshold: float,
) -> tuple[dict[str, Any], pd.DataFrame]:
    feature_cols = [
        "day_of_month",
        "day_of_week_num",
        "is_weekend",
        "machine_type_encoded",
        "lag1_win_rate",
        "lag7_win_rate",
        "roll7_win_rate",
        "prior_kisyuzen_rate",
    ]
    work = frame.copy().sort_values(["date", "machine_name"]).reset_index(drop=True)
    unique_dates = np.array(sorted(work["date"].dropna().unique()))
    if unique_dates.size <= 2:
        return (
            {
                "error": "not_enough_dates",
                "layer0": {
                    "auc": None,
                    "hit_at_1": None,
                    "hit_at_2": None,
                    "hit_at_3": None,
                    "random_baseline_hit_at_1": None,
                    "random_baseline_hit_at_2": None,
                    "random_baseline_hit_at_3": None,
                    "lift_at_1": None,
                    "lift_at_2": None,
                    "lift_at_3": None,
                    "kisyuzen_base_rate": None,
                    "n_eval_days": 0,
                    "threshold": float(layer0_threshold),
                },
            },
            pd.DataFrame(columns=["date", "machine_name", "layer0_proba", "is_kisyuzen"]),
        )

    safe_offset = max(int(eval_offset_days), 0)
    end_idx = int(unique_dates.size) - safe_offset
    if end_idx <= 1:
        return (
            {
                "error": "eval_offset_too_large",
                "layer0": {
                    "auc": None,
                    "hit_at_1": None,
                    "hit_at_2": None,
                    "hit_at_3": None,
                    "random_baseline_hit_at_1": None,
                    "random_baseline_hit_at_2": None,
                    "random_baseline_hit_at_3": None,
                    "lift_at_1": None,
                    "lift_at_2": None,
                    "lift_at_3": None,
                    "kisyuzen_base_rate": None,
                    "n_eval_days": 0,
                    "threshold": float(layer0_threshold),
                },
            },
            pd.DataFrame(columns=["date", "machine_name", "layer0_proba", "is_kisyuzen"]),
        )
    start_idx = max(1, end_idx - max(int(eval_days), 1))
    eval_dates = unique_dates[start_idx:end_idx]
    rows: list[dict[str, Any]] = []
    for pred_date in eval_dates:
        tr = work.loc[work["date"] < pred_date].copy()
        te = work.loc[work["date"] == pred_date].copy()
        if tr.empty or te.empty:
            continue

        tr = tr.dropna(subset=["is_kisyuzen"]).copy()
        te = te.dropna(subset=["is_kisyuzen"]).copy()
        if tr.empty or te.empty:
            continue

        if tr["is_kisyuzen"].nunique() < 2:
            prior = float(np.mean(tr["is_kisyuzen"].to_numpy(dtype=int)))
            proba_te = np.full(len(te), prior, dtype=float)
        else:
            model = CatBoostClassifier(
                iterations=300,
                depth=3,
                learning_rate=0.05,
                loss_function="Logloss",
                eval_metric="AUC",
                random_seed=int(random_state),
                allow_writing_files=False,
                verbose=False,
            )
            x_tr = tr[feature_cols].fillna(0.0).to_numpy(dtype=float)
            y_tr = tr["is_kisyuzen"].to_numpy(dtype=int)
            x_te = te[feature_cols].fillna(0.0).to_numpy(dtype=float)
            model.fit(x_tr, y_tr)
            proba_te = model.predict_proba(x_te)[:, 1]

        for (_, row), p in zip(te.iterrows(), proba_te, strict=False):
            rows.append(
                {
                    "date": pd.Timestamp(row["date"]).strftime("%Y-%m-%d"),
                    "machine_name": str(row["machine_name"]),
                    "machine_name_norm": _normalize_machine_name(row["machine_name"]),
                    "is_kisyuzen": int(row["is_kisyuzen"]),
                    "layer0_proba": float(p),
                }
            )

    pred_df = pd.DataFrame(rows)
    if pred_df.empty:
        return (
            {
                "error": "no_eval_rows",
                "layer0": {
                    "auc": None,
                    "hit_at_1": None,
                    "hit_at_2": None,
                    "hit_at_3": None,
                    "random_baseline_hit_at_1": None,
                    "random_baseline_hit_at_2": None,
                    "random_baseline_hit_at_3": None,
                    "lift_at_1": None,
                    "lift_at_2": None,
                    "lift_at_3": None,
                    "kisyuzen_base_rate": None,
                    "n_eval_days": 0,
                    "threshold": float(layer0_threshold),
                },
            },
            pd.DataFrame(columns=["date", "machine_name", "layer0_proba", "is_kisyuzen"]),
        )

    y_true = pred_df["is_kisyuzen"].to_numpy(dtype=int)
    y_score = pred_df["layer0_proba"].to_numpy(dtype=float)
    base_rate = float(np.mean(y_true))
    hit_at_1 = _daily_hit_at_k(pred_df, score_col="layer0_proba", label_col="is_kisyuzen", k=1)
    hit_at_2 = _daily_hit_at_k(pred_df, score_col="layer0_proba", label_col="is_kisyuzen", k=2)
    hit_at_3 = _daily_hit_at_k(pred_df, score_col="layer0_proba", label_col="is_kisyuzen", k=3)
    rb1 = float(1.0 - ((1.0 - base_rate) ** 1))
    rb2 = float(1.0 - ((1.0 - base_rate) ** 2))
    rb3 = float(1.0 - ((1.0 - base_rate) ** 3))
    result = {
        "layer0": {
            "auc": _safe_auc(y_true, y_score),
            "hit_at_1": round(hit_at_1, 4),
            "hit_at_2": round(hit_at_2, 4),
            "hit_at_3": round(hit_at_3, 4),
            "random_baseline_hit_at_1": round(rb1, 4),
            "random_baseline_hit_at_2": round(rb2, 4),
            "random_baseline_hit_at_3": round(rb3, 4),
            "lift_at_1": round(hit_at_1 / rb1, 4) if rb1 > 0 else None,
            "lift_at_2": round(hit_at_2 / rb2, 4) if rb2 > 0 else None,
            "lift_at_3": round(hit_at_3 / rb3, 4) if rb3 > 0 else None,
            "kisyuzen_base_rate": base_rate,
            "n_eval_days": int(pred_df["date"].nunique()),
            "n_eval_rows": int(len(pred_df)),
            "threshold": float(layer0_threshold),
            "eval_period": {
                "start": str(pred_df["date"].min()),
                "end": str(pred_df["date"].max()),
            },
        }
    }
    return result, pred_df


def prepare_layer1_frame(
    db_path: Path,
    *,
    alpha: float,
    rolling_prior_window: int,
    min_machine_history_days: int = 60,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    warnings: list[str] = []
    raw = common.load_daily_machine_type_summary(db_path)
    if int(min_machine_history_days) > 0:
        latest_date = raw["date"].max()
        active_machines = set(raw.loc[raw["date"] == latest_date, "machine_name"].tolist())
        machine_day_counts = raw.groupby("machine_name")["date"].nunique()
        qualified = set(machine_day_counts[machine_day_counts >= int(min_machine_history_days)].index.tolist())
        target_machines = active_machines & qualified
        raw = raw[raw["machine_name"].isin(target_machines)].copy()
        warnings.append(
            f"active_filter: {len(target_machines)} machines retained "
            f"(active={len(active_machines)}, "
            f"qualified_by_history={len(qualified)}, "
            f"original={machine_day_counts.shape[0]})"
        )
    master = common.load_machine_master(db_path)
    segment_daily = common.load_machine_name_daily_segments(db_path)
    base = common.prepare_machine_type_base_frame(raw)
    base = common.attach_machine_master_flags(base, master)
    base = common.attach_daily_segments(base, segment_daily)
    ranked = common.add_shrunk_rank_targets(base, alpha=float(alpha))
    featured = common.add_machine_type_features(ranked)

    base_feature_cols = common.get_feature_columns(featured)
    work = featured.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work = work.dropna(subset=["date", "machine_name"]).copy()
    work["day_of_month"] = work["date"].dt.day.astype(int)
    work["day_of_week_num"] = work["date"].dt.dayofweek.astype(int)
    work["is_weekend"] = work["day_of_week_num"].isin([5, 6]).astype(int)
    work["segment_key"] = work["segment_floor2"].astype(str)
    unknown_count = int((~work["segment_key"].isin(SEGMENT_KEYS)).sum())
    if unknown_count > 0:
        warnings.append(f"{unknown_count} rows are outside target segments and were dropped")
    work = work.loc[work["segment_key"].isin(SEGMENT_KEYS)].copy()
    if work.empty:
        return work, warnings, base_feature_cols

    work["segment_rank"] = work.groupby(["date", "segment_key"], sort=False)["shrunk_avg_diff"].rank(
        method="first",
        ascending=False,
    )
    seg_n = work.groupby(["date", "segment_key"], sort=False)["machine_name"].transform("nunique").clip(lower=1)
    work["segment_rank_pct"] = np.where(seg_n > 1, (work["segment_rank"] - 1.0) / (seg_n - 1.0), 0.0)
    work["is_rank_1_segment"] = (work["segment_rank"] == 1).astype(int)
    work["is_top3_in_segment"] = (work["segment_rank"] <= 3).astype(int)
    work["is_top5_in_segment"] = (work["segment_rank"] <= 5).astype(int)
    work = work.sort_values(["segment_key", "machine_name", "date"]).reset_index(drop=True)

    out_parts: list[pd.DataFrame] = []
    for (_, _), g in work.groupby(["segment_key", "machine_name"], sort=False):
        h = g.sort_values("date").copy()
        h["lag1_segment_rank_pct"] = h["segment_rank_pct"].shift(1)
        h["prior_segment_top1_rate"] = (
            h["is_rank_1_segment"]
            .rolling(window=max(int(rolling_prior_window), 1), min_periods=10)
            .mean()
            .shift(1)
        )
        h["weekday_segment_top1_rate"] = (
            h.groupby("day_of_week_num", sort=False)["is_rank_1_segment"]
            .transform(lambda s: s.shift(1).expanding(min_periods=1).mean())
        )
        # Keep backward-compatible aliases for baseline6 profile.
        h["lag1_rank_pct"] = h["lag1_segment_rank_pct"]
        h["prior_top1_rate"] = h["prior_segment_top1_rate"]
        h["weekday_prior_top1_rate"] = h["weekday_segment_top1_rate"]
        out_parts.append(h)
    out = pd.concat(out_parts, ignore_index=True)
    out["games_roll7_shift1"] = (
        out.groupby(["segment_key", "machine_name"], sort=False)["avg_games"]
        .transform(lambda x: x.rolling(7, min_periods=2).mean().shift(1))
    )
    out["games_roll28_shift1"] = (
        out.groupby(["segment_key", "machine_name"], sort=False)["avg_games"]
        .transform(lambda x: x.rolling(28, min_periods=7).mean().shift(1))
    )
    out["segment_games_roll7_mean"] = out.groupby(["date", "segment_key"], sort=False)["games_roll7_shift1"].transform(
        "mean"
    )
    out["games_vs_segment_mean_7d"] = np.where(
        pd.to_numeric(out["segment_games_roll7_mean"], errors="coerce").fillna(0.0) > 0.0,
        pd.to_numeric(out["games_roll7_shift1"], errors="coerce").fillna(0.0)
        / pd.to_numeric(out["segment_games_roll7_mean"], errors="coerce").fillna(0.0),
        1.0,
    )
    out["games_trend_7v28"] = np.where(
        pd.to_numeric(out["games_roll28_shift1"], errors="coerce").fillna(0.0) > 0.0,
        pd.to_numeric(out["games_roll7_shift1"], errors="coerce").fillna(0.0)
        / pd.to_numeric(out["games_roll28_shift1"], errors="coerce").fillna(0.0),
        1.0,
    )
    out["machine_name_norm"] = out["machine_name"].map(_normalize_machine_name)
    for col in (
        "lag1_segment_rank_pct",
        "prior_segment_top1_rate",
        "weekday_segment_top1_rate",
        "lag1_rank_pct",
        "prior_top1_rate",
        "weekday_prior_top1_rate",
        "games_roll7_shift1",
        "games_roll28_shift1",
        "segment_games_roll7_mean",
        "games_vs_segment_mean_7d",
        "games_trend_7v28",
    ):
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    return out, warnings, base_feature_cols


def _summarize_target_predictions(pred_df: pd.DataFrame, *, target_col: str) -> dict[str, Any]:
    if pred_df.empty:
        return {
            "auc": None,
            "hit_at_1": None,
            "hit_at_3": None,
            "hit_at_5": None,
            "random_baseline": None,
            "lift": None,
            "n_eval_days": 0,
            "n_rows": 0,
            "base_rate": None,
        }
    y_true = pred_df[target_col].to_numpy(dtype=int)
    y_score = pred_df["proba"].to_numpy(dtype=float)
    g = pred_df["date"].astype(str).to_numpy()
    hit_at_1 = float(calculate_hit_at_k(y_true, y_score, g, 1))
    hit_at_3 = float(calculate_hit_at_k(y_true, y_score, g, 3))
    hit_at_5 = float(calculate_hit_at_k(y_true, y_score, g, 5))

    rb_by_k: dict[int, float] = {}
    for k in (1, 3, 5):
        probs = [_prob_hit_random(d[target_col].to_numpy(dtype=int), k) for _, d in pred_df.groupby("date", sort=True)]
        rb_by_k[k] = float(np.mean(probs)) if probs else 0.0

    lift_by_k: dict[int, float | None] = {}
    for k, hit in ((1, hit_at_1), (3, hit_at_3), (5, hit_at_5)):
        rb = rb_by_k[k]
        lift_by_k[k] = None if rb <= 0.0 else float(hit / rb)

    primary_k = 3 if target_col == "is_top3_in_segment" else 5
    return {
        "auc": _safe_auc(y_true, y_score),
        "hit_at_1": hit_at_1,
        "hit_at_3": hit_at_3,
        "hit_at_5": hit_at_5,
        "random_baseline": rb_by_k[primary_k],
        "lift": lift_by_k[primary_k],
        "random_baseline_at_1": rb_by_k[1],
        "random_baseline_at_3": rb_by_k[3],
        "random_baseline_at_5": rb_by_k[5],
        "lift_at_1": lift_by_k[1],
        "lift_at_3": lift_by_k[3],
        "lift_at_5": lift_by_k[5],
        "n_eval_days": int(pred_df["date"].nunique()),
        "n_rows": int(len(pred_df)),
        "base_rate": float(np.mean(y_true)),
        "eval_period": {
            "start": str(pred_df["date"].min()),
            "end": str(pred_df["date"].max()),
        },
    }


def _target_pairs_for_segment(segment_key: str, target_policy: str) -> list[tuple[str, str]]:
    # LTR + 2-floor segmentation uses a single top3 objective.
    _ = segment_key
    _ = target_policy
    return [("is_top3_in_segment", "target_is_top3")]


def _layer1_feature_cols_for_profile(
    segment_df: pd.DataFrame,
    *,
    base_feature_cols: list[str],
    feature_profile: str,
    games_feature_mode: str = "none",
) -> list[str]:
    profile = str(feature_profile).strip().lower()
    games_mode = str(games_feature_mode).strip().lower()
    segment_specific = [
        "lag1_segment_rank_pct",
        "prior_segment_top1_rate",
        "weekday_segment_top1_rate",
    ]
    blocked = {
        # Labels/derived outcomes for current date (leakage).
        "is_rank_1_segment",
        "is_top3_in_segment",
        "is_top5_in_segment",
        "segment_rank",
        "segment_rank_pct",
        "is_rank_1",
        "is_top_2",
        "is_top_3",
        "is_top_5",
        # Identifiers.
        "machine_type_encoded",
        # Keep games features opt-in for controlled ablation.
        "games_roll7_shift1",
        "games_roll28_shift1",
        "segment_games_roll7_mean",
        "games_vs_segment_mean_7d",
        "games_trend_7v28",
    }
    if profile == "baseline6":
        base = [c for c in LAYER1_FEATURES if c in segment_df.columns]
        if games_mode in {"vs_seg", "vs_seg_and_trend"} and "games_vs_segment_mean_7d" in segment_df.columns:
            base.append("games_vs_segment_mean_7d")
        if games_mode == "vs_seg_and_trend" and "games_trend_7v28" in segment_df.columns:
            base.append("games_trend_7v28")
        return base

    cols = [c for c in base_feature_cols if c in segment_df.columns and c not in blocked]
    cols.extend([c for c in segment_specific if c in segment_df.columns])
    # Preserve order and uniqueness.
    seen: set[str] = set()
    ordered = []
    for c in cols:
        if c in seen:
            continue
        seen.add(c)
        ordered.append(c)
    if profile == "rich_no_ranktrend":
        ordered = [c for c in ordered if "rank_trend" not in c and "rank_pct_avg_" not in c]
    return ordered


def run_layer1_segment_walkforward(
    segment_df: pd.DataFrame,
    *,
    segment_key: str,
    base_feature_cols: list[str],
    feature_profile: str,
    target_policy: str,
    games_feature_mode: str,
    min_train_days: int,
    eval_days: int,
    eval_offset_days: int,
    step_days: int,
    random_state: int,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, list[str]]:
    warnings: list[str] = []
    target_pairs = _target_pairs_for_segment(segment_key, target_policy)
    seg = segment_df.copy().sort_values(["date", "machine_name"]).reset_index(drop=True)
    unique_machine_names = int(seg["machine_name"].nunique())
    if unique_machine_names < 10:
        warnings.append(f"{segment_key}: skipped because unique machines < 10 ({unique_machine_names})")
        return (
            {
                "segment": segment_key,
                "status": "skipped",
                "reason": "too_few_machines",
                "unique_machines": unique_machine_names,
            },
            pd.DataFrame(),
            pd.DataFrame(),
            warnings,
        )

    all_dates = np.array(sorted(seg["date"].dropna().unique()))
    if all_dates.size <= max(int(min_train_days), 1):
        warnings.append(f"{segment_key}: skipped because not enough dates")
        return (
            {
                "segment": segment_key,
                "status": "skipped",
                "reason": "not_enough_dates",
                "unique_machines": unique_machine_names,
                "n_dates": int(all_dates.size),
            },
            pd.DataFrame(),
            pd.DataFrame(),
            warnings,
        )

    safe_offset = max(int(eval_offset_days), 0)
    end_idx = int(all_dates.size) - safe_offset
    if end_idx <= int(min_train_days):
        warnings.append(f"{segment_key}: skipped because eval_offset_days is too large")
        return (
            {
                "segment": segment_key,
                "status": "skipped",
                "reason": "eval_offset_too_large",
                "unique_machines": unique_machine_names,
                "n_dates": int(all_dates.size),
            },
            pd.DataFrame(),
            pd.DataFrame(),
            warnings,
        )
    start_idx = max(int(min_train_days), end_idx - max(int(eval_days), 1))
    eval_dates = all_dates[start_idx:end_idx: max(int(step_days), 1)]
    if eval_dates.size == 0:
        eval_dates = all_dates[start_idx:]
    if eval_dates.size == 0:
        warnings.append(f"{segment_key}: skipped because eval_dates is empty")
        return (
            {
                "segment": segment_key,
                "status": "skipped",
                "reason": "empty_eval_dates",
                "unique_machines": unique_machine_names,
            },
            pd.DataFrame(),
            pd.DataFrame(),
            warnings,
        )

    pred_records: list[dict[str, Any]] = []
    importance_records: list[dict[str, Any]] = []
    feature_cols = _layer1_feature_cols_for_profile(
        seg,
        base_feature_cols=base_feature_cols,
        feature_profile=feature_profile,
        games_feature_mode=games_feature_mode,
    )
    if not feature_cols:
        warnings.append(f"{segment_key}: no feature columns after feature_profile={feature_profile}")
        return (
            {
                "segment": segment_key,
                "status": "skipped",
                "reason": "no_features",
                "unique_machines": unique_machine_names,
            },
            pd.DataFrame(),
            pd.DataFrame(),
            warnings,
        )
    total_steps = max(int(len(target_pairs) * len(eval_dates)), 1)
    step_no = 0
    started_at = time.time()
    for target_col, target_name in target_pairs:
        for pred_date in eval_dates:
            step_no += 1
            tr = seg.loc[seg["date"] < pred_date].dropna(subset=feature_cols + [target_col]).copy()
            te = seg.loc[seg["date"] == pred_date].dropna(subset=feature_cols + [target_col]).copy()
            if tr.empty or te.empty:
                continue
            if tr["date"].nunique() < int(min_train_days):
                continue
            if tr[target_col].nunique() < 2:
                continue
            tr_ltr = tr.copy()
            # Use segment-level rank as relevance source for LTR labels.
            tr_ltr["shrunk_rank"] = pd.to_numeric(tr_ltr["segment_rank"], errors="coerce").fillna(9999.0)
            trained_ltr = common.train_ltr_model(
                tr_ltr.sort_values(["date", "machine_name"]).copy(),
                feature_columns=feature_cols,
                random_state=int(random_state),
                decay_lambda=0.3,
                objective="rank:ndcg",
            )
            ltr_scores = common.predict_ltr_scores(
                te.sort_values(["date", "machine_name"]).copy(),
                trained=trained_ltr,
            )

            imps = trained_ltr.model.feature_importances_
            for col, imp in zip(feature_cols, imps, strict=False):
                importance_records.append(
                    {
                        "segment": segment_key,
                        "target": target_name,
                        "date": pd.Timestamp(pred_date).strftime("%Y-%m-%d"),
                        "feature": col,
                        "importance": float(imp),
                    }
                )

            for (_, row), score in zip(te.iterrows(), ltr_scores, strict=False):
                pred_records.append(
                    {
                        "segment": segment_key,
                        "target": target_name,
                        "date": pd.Timestamp(row["date"]).strftime("%Y-%m-%d"),
                        "machine_name": str(row["machine_name"]),
                        "machine_name_norm": _normalize_machine_name(row["machine_name"]),
                        "is_top3_in_segment": int(row["is_top3_in_segment"]),
                        "is_top5_in_segment": int(row["is_top5_in_segment"]),
                        "ltr_score": float(score),
                        "proba": float(score),
                    }
                )
            if (step_no % 10 == 0) or (step_no == total_steps):
                elapsed = time.time() - started_at
                per_step = elapsed / max(step_no, 1)
                remain = per_step * max(total_steps - step_no, 0)
                print(
                    f"[layer1 {segment_key}] {step_no}/{total_steps} "
                    f"elapsed={elapsed:.1f}s remaining={remain:.1f}s",
                    flush=True,
                )

    pred_df = pd.DataFrame(pred_records)
    imp_df = pd.DataFrame(importance_records)
    result_payload: dict[str, Any] = {
        "segment": segment_key,
        "status": "ok",
        "model_type": "xgb_ranker_ndcg",
        "feature_profile": str(feature_profile),
        "games_feature_mode": str(games_feature_mode),
        "target_policy": str(target_policy),
        "unique_machines": unique_machine_names,
        "n_source_rows": int(len(seg)),
        "n_source_dates": int(all_dates.size),
        "requested_eval_dates": int(eval_dates.size),
        "features": feature_cols,
    }
    for target_col, target_name in target_pairs:
        sub = pred_df.loc[pred_df["target"].eq(target_name)].copy() if not pred_df.empty else pd.DataFrame()
        result_payload[target_name] = _summarize_target_predictions(sub, target_col=target_col)
    return result_payload, pred_df, imp_df, warnings


def build_combined_recommendation(
    layer1_top3_df: pd.DataFrame,
    layer0_pred_df: pd.DataFrame,
    *,
    lam: float,
) -> dict[str, Any]:
    if layer1_top3_df.empty:
        return {
            "description": f"layer1_proba * (1 + {float(lam)} * layer0_proba) で算出",
            "lambda": float(lam),
            "top3_combined_hit_at_1": None,
            "top3_combined_hit_at_3": None,
            "n_eval_days": 0,
        }
    base = layer1_top3_df.copy()
    base["date"] = base["date"].astype(str)
    if "machine_name_norm" not in base.columns:
        base["machine_name_norm"] = base["machine_name"].map(_normalize_machine_name)
    l0 = layer0_pred_df.copy()
    l0["date"] = l0["date"].astype(str)
    if "machine_name_norm" not in l0.columns:
        l0["machine_name_norm"] = l0["machine_name"].map(_normalize_machine_name)
    l0 = (
        l0.sort_values(["date", "machine_name", "layer0_proba"], ascending=[True, True, False])
        .drop_duplicates(subset=["date", "machine_name_norm"], keep="first")
        .copy()
    )
    merged = base.merge(
        l0[["date", "machine_name_norm", "layer0_proba"]],
        on=["date", "machine_name_norm"],
        how="left",
    )
    # Backfill by date-average then machine-average to reduce sparse key misses.
    if not l0.empty:
        by_date = (
            l0.groupby("date", sort=False)["layer0_proba"]
            .mean()
            .reset_index()
            .rename(columns={"layer0_proba": "layer0_proba_by_date"})
        )
        by_machine = (
            l0.groupby("machine_name_norm", sort=False)["layer0_proba"]
            .mean()
            .reset_index()
            .rename(columns={"layer0_proba": "layer0_proba_by_machine"})
        )
        merged = merged.merge(by_date, on="date", how="left")
        merged = merged.merge(by_machine, on="machine_name_norm", how="left")
        merged["layer0_proba"] = (
            pd.to_numeric(merged["layer0_proba"], errors="coerce")
            .fillna(pd.to_numeric(merged["layer0_proba_by_date"], errors="coerce"))
            .fillna(pd.to_numeric(merged["layer0_proba_by_machine"], errors="coerce"))
        )
    missing_rate = float(pd.to_numeric(merged["layer0_proba"], errors="coerce").isna().mean()) if len(merged) > 0 else 0.0
    fill_value = float(np.nanmean(l0["layer0_proba"].to_numpy(dtype=float))) if not l0.empty else 0.0
    if np.isnan(fill_value):
        fill_value = 0.0
    merged["layer0_proba"] = pd.to_numeric(merged["layer0_proba"], errors="coerce").fillna(fill_value)
    merged["final_score"] = merged["proba"] * (1.0 + float(lam) * merged["layer0_proba"])

    y_true = merged["is_top3_in_segment"].to_numpy(dtype=int)
    y_score = merged["final_score"].to_numpy(dtype=float)
    group_ids = merged["date"].astype(str).to_numpy()
    hit1 = float(calculate_hit_at_k(y_true, y_score, group_ids, 1))
    hit3 = float(calculate_hit_at_k(y_true, y_score, group_ids, 3))
    return {
        "description": f"layer1_proba * (1 + {float(lam)} * layer0_proba) で算出",
        "lambda": float(lam),
        "top3_combined_hit_at_1": hit1,
        "top3_combined_hit_at_3": hit3,
        "n_eval_days": int(merged["date"].nunique()),
        "n_rows": int(len(merged)),
        "missing_layer0_proba_rate": missing_rate,
    }


def run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    db_path = common.resolve_db_path(str(args.db_path))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Layer 0 (machine_name x date kikata detection)
    layer0_frame = load_layer0_kisyuzen_frame(
        db_path,
        rolling_prior_window=int(args.rolling_prior_window),
        winrate_threshold=float(args.layer0_winrate_threshold),
    )
    layer0_result, layer0_pred_df = run_layer0_walkforward(
        layer0_frame,
        eval_days=int(args.eval_days),
        eval_offset_days=int(args.eval_offset_days),
        random_state=int(args.random_state),
        layer0_threshold=float(args.layer0_threshold),
    )
    _write_json(output_dir / "layer0_walkforward_result.json", layer0_result)

    # Layer 1
    layer1_base, prep_warnings, base_feature_cols = prepare_layer1_frame(
        db_path,
        alpha=float(args.alpha),
        rolling_prior_window=int(args.rolling_prior_window),
        min_machine_history_days=int(args.min_machine_history_days),
    )
    segment_results: dict[str, dict[str, Any]] = {}
    all_preds: list[pd.DataFrame] = []
    all_importances: list[pd.DataFrame] = []
    all_warnings = list(prep_warnings)

    for segment_key in SEGMENT_KEYS:
        seg_df = layer1_base.loc[layer1_base["segment_key"].eq(segment_key)].copy()
        result_payload, pred_df, imp_df, warnings = run_layer1_segment_walkforward(
            seg_df,
            segment_key=segment_key,
            base_feature_cols=base_feature_cols,
            feature_profile=str(args.feature_profile),
            target_policy=str(args.target_policy),
            games_feature_mode=str(args.games_feature_mode),
            min_train_days=int(args.min_train_days),
            eval_days=int(args.eval_days),
            eval_offset_days=int(args.eval_offset_days),
            step_days=int(args.step_days),
            random_state=int(args.random_state),
        )
        segment_results[segment_key] = result_payload
        if not pred_df.empty:
            all_preds.append(pred_df)
        if not imp_df.empty:
            all_importances.append(imp_df)
        all_warnings.extend(warnings)
        _write_json(output_dir / f"layer1_{segment_key}_result.json", result_payload)

    preds = pd.concat(all_preds, ignore_index=True) if all_preds else pd.DataFrame()
    importances = pd.concat(all_importances, ignore_index=True) if all_importances else pd.DataFrame(
        columns=["segment", "target", "date", "feature", "importance"]
    )

    if not importances.empty:
        fi_out = (
            importances.groupby(["segment", "target", "feature"], sort=True)["importance"]
            .agg(["mean", "std", "count"])
            .reset_index()
            .rename(columns={"mean": "importance_mean", "std": "importance_std", "count": "n_models"})
            .sort_values(["segment", "target", "importance_mean"], ascending=[True, True, False])
        )
    else:
        fi_out = pd.DataFrame(columns=["segment", "target", "feature", "importance_mean", "importance_std", "n_models"])
    fi_out.to_csv(output_dir / "feature_importance_per_segment.csv", index=False, encoding="utf-8-sig")

    target_top3: dict[str, Any] = {}
    target_top5: dict[str, Any] = {}
    for segment_key in SEGMENT_KEYS:
        seg_res = segment_results.get(segment_key, {})
        target_top3[segment_key] = seg_res.get("target_is_top3", {})
        target_top5[segment_key] = seg_res.get("target_is_top5", {})

    if not preds.empty:
        c3 = preds.loc[preds["target"].eq("target_is_top3")].copy()
        c5 = preds.loc[preds["target"].eq("target_is_top5")].copy()
        target_top3["combined"] = _summarize_target_predictions(c3, target_col="is_top3_in_segment")
        target_top5["combined"] = _summarize_target_predictions(c5, target_col="is_top5_in_segment")
        combined_reco = build_combined_recommendation(c3, layer0_pred_df, lam=float(args.combined_lambda))
        eval_start = str(preds["date"].min())
        eval_end = str(preds["date"].max())
    else:
        target_top3["combined"] = {}
        target_top5["combined"] = {}
        combined_reco = {
            "description": f"layer1_proba * (1 + {float(args.combined_lambda)} * layer0_proba) で算出",
            "lambda": float(args.combined_lambda),
            "top3_combined_hit_at_1": None,
            "top3_combined_hit_at_3": None,
            "n_eval_days": 0,
        }
        eval_start = ""
        eval_end = ""

    layer0_summary = layer0_result.get("layer0", {})
    combined_result = {
        "db_path": str(db_path),
        "eval_period": {"start": eval_start, "end": eval_end},
        "target_is_top3": target_top3,
        "target_is_top5": target_top5,
        "layer0": {
            "auc": layer0_summary.get("auc"),
            "hit_at_1": layer0_summary.get("hit_at_1"),
            "hit_at_2": layer0_summary.get("hit_at_2"),
            "hit_at_3": layer0_summary.get("hit_at_3"),
            "random_baseline_hit_at_1": layer0_summary.get("random_baseline_hit_at_1"),
            "random_baseline_hit_at_2": layer0_summary.get("random_baseline_hit_at_2"),
            "random_baseline_hit_at_3": layer0_summary.get("random_baseline_hit_at_3"),
            "lift_at_1": layer0_summary.get("lift_at_1"),
            "lift_at_2": layer0_summary.get("lift_at_2"),
            "lift_at_3": layer0_summary.get("lift_at_3"),
            "kisyuzen_base_rate": layer0_summary.get("kisyuzen_base_rate"),
            "n_eval_days": layer0_summary.get("n_eval_days"),
            "n_eval_rows": layer0_summary.get("n_eval_rows"),
            "threshold": layer0_summary.get("threshold"),
            "winrate_threshold": float(args.layer0_winrate_threshold),
        },
        "combined_recommendation": combined_reco,
        "warnings": sorted(set(all_warnings)),
        "config": {
            "min_train_days": int(args.min_train_days),
            "eval_days": int(args.eval_days),
            "eval_offset_days": int(args.eval_offset_days),
            "step_days": int(args.step_days),
            "rolling_prior_window": int(args.rolling_prior_window),
            "alpha": float(args.alpha),
            "layer0_threshold": float(args.layer0_threshold),
            "layer0_winrate_threshold": float(args.layer0_winrate_threshold),
            "combined_lambda": float(args.combined_lambda),
            "feature_profile": str(args.feature_profile),
            "games_feature_mode": str(args.games_feature_mode),
            "target_policy": str(args.target_policy),
            "min_machine_history_days": int(args.min_machine_history_days),
            "random_state": int(args.random_state),
        },
    }
    _write_json(output_dir / "layer1_combined_result.json", combined_result)
    return combined_result


def main() -> int:
    args = build_parser().parse_args()
    result = run_pipeline(args)
    print(f"Saved outputs to: {Path(args.output_dir)}")
    if result.get("warnings"):
        for w in result["warnings"]:
            print(f"WARNING: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
