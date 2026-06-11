from __future__ import annotations

import argparse
import itertools
import json
import sqlite3
import time
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
try:
    from xgboost import XGBClassifier, XGBRegressor
except Exception:  # pragma: no cover - keep module importable if xgboost is unavailable.
    XGBClassifier = None  # type: ignore[assignment]
    XGBRegressor = None  # type: ignore[assignment]
try:
    from tqdm import tqdm
except Exception:  # pragma: no cover - tqdm should exist, but keep fallback safe.
    def tqdm(iterable, **kwargs):  # type: ignore[override]
        return iterable

from ml.last_digit.hall_day_strength_audit import (
    DEFAULT_RULES,
    add_strength_targets,
    apply_rule,
    build_rule_meta,
    evaluate_target_rules,
    load_daily_hall,
    split_ranges,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Practical hall strategy follow-up: candidate filtering, target analysis, rolling, and overlap.")
    p.add_argument("--db-dir", default="db")
    p.add_argument("--strength-root", default="db/experiments/hall_day_strength_audit_20260601")
    p.add_argument("--required-thresholds", default="200,300")
    p.add_argument("--min-lift", type=float, default=0.2)
    p.add_argument("--min-play-days", type=int, default=5)
    p.add_argument("--selection-start", default="2025-07-07")
    p.add_argument("--selection-end", default="2025-12-31")
    p.add_argument("--holdout-start", default="2026-01-01")
    p.add_argument("--holdout-end", default="2026-05-30")
    p.add_argument("--kamata7-db-glob", default="*蒲田7.db")
    p.add_argument("--rolling-window-days", type=int, default=120)
    p.add_argument("--ml-min-edge", type=float, default=0.08)
    p.add_argument("--allhall-opt-edge-grid", default="0.00,0.04,0.08,0.12,0.16,0.20")
    p.add_argument("--allhall-opt-weight-grid", default="1,1,1;1,1.5,2;1,2,3;1,1,2")
    p.add_argument("--allhall-opt-warmup-days", type=int, default=90)
    p.add_argument("--allhall-no-signal-judgment-csv", default="")
    p.add_argument("--allhall-opt-no-signal-penalty-grid", default="0,10,20,30")
    p.add_argument("--allhall-opt-dd-topk-bonus-grid", default="0,10,20,30")
    p.add_argument("--allhall-opt-strong-zorome-bonus-grid", default="0,10,20,30")
    p.add_argument("--allhall-opt-share-cap-grid", default="0.40,0.50,0.60,0.70,0.80")
    p.add_argument("--allhall-opt-share-penalty-scale", type=float, default=250.0)
    p.add_argument("--allhall-opt-objective", default="avg_diff", choices=["regret", "avg_diff"])
    p.add_argument("--allhall-dd-topk-k", type=int, default=5)
    p.add_argument("--allhall-dd-topk-min-days", type=int, default=6)
    p.add_argument("--hybrid-logreg-c-grid", default="0.01,0.05,0.1,0.5,1.0,5.0")
    p.add_argument("--hybrid-use-lag1-games", action="store_true")
    p.add_argument("--hybrid-use-lag1-games-grid", default="")
    p.add_argument("--use-gpu", action="store_true", help="Enable GPU learners when available")
    p.add_argument("--gpu-backend", choices=["cuda", "gpu_hist"], default="cuda")
    p.add_argument("--output-root", default="db/experiments/hall_rank/hall_practical_strategy_followup_20260601")
    return p


def _parse_csv_ints(raw: str) -> list[int]:
    out: list[int] = []
    for x in str(raw).split(","):
        s = x.strip()
        if s:
            out.append(int(s))
    return out


def _parse_csv_floats(raw: str) -> list[float]:
    out: list[float] = []
    for x in str(raw).split(","):
        s = x.strip()
        if s:
            out.append(float(s))
    return out


def _parse_csv_bools(raw: str) -> list[bool]:
    out: list[bool] = []
    for x in str(raw).split(","):
        s = x.strip().lower()
        if not s:
            continue
        if s in {"1", "true", "t", "yes", "y"}:
            out.append(True)
        elif s in {"0", "false", "f", "no", "n"}:
            out.append(False)
    return out


def _parse_weight_grid(raw: str) -> list[tuple[float, float, float]]:
    out: list[tuple[float, float, float]] = []
    for part in str(raw).split(";"):
        s = part.strip()
        if not s:
            continue
        vals = [float(x.strip()) for x in s.split(",") if x.strip()]
        if len(vals) != 3:
            continue
        out.append((vals[0], vals[1], vals[2]))
    if not out:
        out = [(1.0, 1.0, 1.0)]
    return out


def build_model_params(*, use_gpu: bool, gpu_backend: str) -> dict[str, Any]:
    if not use_gpu:
        return {"device": "cpu"}
    if gpu_backend == "cuda":
        return {"tree_method": "hist", "device": "cuda"}
    return {"tree_method": "gpu_hist"}


def make_binary_model(*, c: float, use_gpu: bool, gpu_backend: str) -> Any:
    # GPU明示指定 かつ XGBoost利用可能 の場合のみ XGBClassifier を使う。
    # それ以外は LogisticRegression(C=c) を使う（hybrid baseline の動作を保つ）。
    if not use_gpu or XGBClassifier is None:
        return LogisticRegression(max_iter=500, class_weight="balanced", solver="lbfgs", C=float(c), random_state=42)
    params = build_model_params(use_gpu=True, gpu_backend=gpu_backend)
    return XGBClassifier(
        n_estimators=300,
        learning_rate=0.05,
        max_depth=4,
        subsample=0.9,
        colsample_bytree=0.9,
        reg_alpha=0.0,
        reg_lambda=1.0,
        objective="binary:logistic",
        eval_metric="logloss",
        random_state=42,
        **params,
    )


def make_regressor(*, use_gpu: bool, gpu_backend: str) -> Any:
    # GPU明示指定 かつ XGBoost利用可能 の場合のみ XGBRegressor を使う。
    if not use_gpu or XGBRegressor is None:
        return HistGradientBoostingRegressor(
            loss="squared_error",
            learning_rate=0.05,
            max_depth=4,
            max_iter=300,
            random_state=42,
        )
    params = build_model_params(use_gpu=True, gpu_backend=gpu_backend)
    return XGBRegressor(
        n_estimators=300,
        learning_rate=0.05,
        max_depth=4,
        subsample=0.9,
        colsample_bytree=0.9,
        objective="reg:squarederror",
        random_state=42,
        **params,
    )


def build_policy_grid(
    *,
    use_gpu: bool,
    edge_grid: list[float] | None = None,
    weight_grid: list[tuple[float, float, float]] | None = None,
    no_signal_penalty_grid: list[float] | None = None,
    dd_topk_bonus_grid: list[float] | None = None,
    strong_zorome_bonus_grid: list[float] | None = None,
    share_cap_grid: list[float] | None = None,
) -> list[dict[str, Any]]:
    resolved_edge_grid = edge_grid if edge_grid is not None else ([0.0, 0.08, 0.16] if use_gpu else [0.0, 0.04, 0.08, 0.12, 0.16, 0.2])
    resolved_weight_grid = weight_grid if weight_grid is not None else (
        [(1.0, 1.0, 1.0), (1.0, 1.5, 2.0), (1.0, 2.0, 3.0)]
        if use_gpu
        else [(1.0, 1.0, 1.0), (1.0, 1.5, 2.0), (1.0, 2.0, 3.0), (1.0, 1.0, 2.0)]
    )
    resolved_no_signal_penalty_grid = no_signal_penalty_grid if no_signal_penalty_grid is not None else [0.0, 10.0, 20.0, 30.0]
    resolved_dd_topk_bonus_grid = dd_topk_bonus_grid if dd_topk_bonus_grid is not None else [0.0, 10.0, 20.0, 30.0]
    resolved_strong_zorome_bonus_grid = strong_zorome_bonus_grid if strong_zorome_bonus_grid is not None else [0.0, 10.0, 20.0, 30.0]
    resolved_share_cap_grid = share_cap_grid if share_cap_grid is not None else [0.4, 0.5, 0.6, 0.7, 0.8]

    out: list[dict[str, Any]] = []
    for edge, weights, no_signal_penalty, dd_topk_bonus, strong_zorome_bonus, share_cap in itertools.product(
        resolved_edge_grid,
        resolved_weight_grid,
        resolved_no_signal_penalty_grid,
        resolved_dd_topk_bonus_grid,
        resolved_strong_zorome_bonus_grid,
        resolved_share_cap_grid,
    ):
        out.append(
            {
                "edge": float(edge),
                "weights": (float(weights[0]), float(weights[1]), float(weights[2])),
                "no_signal_penalty": float(no_signal_penalty),
                "dd_topk_bonus": float(dd_topk_bonus),
                "strong_zorome_bonus": float(strong_zorome_bonus),
                "share_cap": float(share_cap),
            }
        )
    return out


def _load_no_signal_stores(judgment_csv: str) -> set[str]:
    p = Path(str(judgment_csv))
    if not p.exists():
        return set()
    df = pd.read_csv(p, encoding="utf-8-sig")
    if "store" not in df.columns or "judgment" not in df.columns:
        return set()
    out = (
        df[df["judgment"].astype(str).str.upper() == "NO_SIGNAL"]["store"]
        .astype(str)
        .str.strip()
        .tolist()
    )
    return set(out)


def _load_hall_judgment_map(judgment_csv: str) -> dict[str, str]:
    p = Path(str(judgment_csv))
    if not p.exists():
        return {}
    df = pd.read_csv(p, encoding="utf-8-sig")
    if "store" not in df.columns or "judgment" not in df.columns:
        return {}
    out: dict[str, str] = {}
    for _, row in df.iterrows():
        store = str(row.get("store", "")).strip()
        judgment = str(row.get("judgment", "")).strip().upper()
        if store:
            out[store] = judgment
    return out


def _load_store_meta(strength_root: Path) -> pd.DataFrame:
    p = strength_root / "stores.csv"
    if not p.exists():
        raise FileNotFoundError(f"Missing stores.csv: {p}")
    df = pd.read_csv(p, encoding="utf-8-sig")
    if "store" not in df.columns or "db_path" not in df.columns:
        raise ValueError("stores.csv must contain store and db_path")
    return df


def _load_best_rules(strength_root: Path) -> pd.DataFrame:
    p = strength_root / "store_threshold_best_rules.csv"
    if not p.exists():
        raise FileNotFoundError(f"Missing store_threshold_best_rules.csv: {p}")
    df = pd.read_csv(p, encoding="utf-8-sig")
    if "store" not in df.columns or "threshold" not in df.columns:
        raise ValueError("store_threshold_best_rules.csv missing required columns")
    df["threshold"] = pd.to_numeric(df["threshold"], errors="coerce").astype("Int64")
    return df


def pick_practical_candidates(
    *,
    best_df: pd.DataFrame,
    required_thresholds: list[int],
    min_lift: float,
    min_play_days: int,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    req = [int(x) for x in required_thresholds]
    for store, g0 in best_df.groupby("store", sort=False):
        ok = True
        lifts: list[float] = []
        plays: list[int] = []
        for thr in req:
            g = g0[g0["threshold"].astype(int) == int(thr)]
            if g.empty:
                ok = False
                break
            row = g.iloc[0]
            lift = float(row["best_success_rate_lift_vs_all"])
            n_play = int(row["best_n_play_days"])
            if not np.isfinite(lift) or lift < float(min_lift) or n_play < int(min_play_days):
                ok = False
                break
            lifts.append(lift)
            plays.append(n_play)
        if not ok:
            continue
        rows.append(
            {
                "store": str(store),
                "required_thresholds": ",".join(str(x) for x in req),
                "min_lift_observed": float(min(lifts)),
                "avg_lift_observed": float(np.mean(lifts)),
                "min_play_days_observed": int(min(plays)),
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["min_lift_observed", "avg_lift_observed"], ascending=[False, False]).reset_index(drop=True)


def compute_overlap_distribution(signals_df: pd.DataFrame) -> pd.DataFrame:
    if signals_df.empty:
        return pd.DataFrame(columns=["n_halls_signaled", "n_days", "day_share"])
    d = (
        signals_df.groupby("date", sort=True)["store"]
        .nunique()
        .reset_index(name="n_halls_signaled")
    )
    out = d.groupby("n_halls_signaled", sort=True).size().reset_index(name="n_days")
    out["day_share"] = out["n_days"] / float(d["date"].nunique())
    return out.sort_values("n_halls_signaled").reset_index(drop=True)


def _load_machine_with_type(db_path: Path) -> pd.DataFrame:
    con = sqlite3.connect(str(db_path))
    q = """
    SELECT
      m.date,
      m.machine_number,
      m.last_digit,
      m.diff_coins_normalized,
      COALESCE(mm.jug_flag, 0) AS jug_flag,
      COALESCE(mm.hana_flag, 0) AS hana_flag,
      COALESCE(mm.oki_flag, 0) AS oki_flag,
      COALESCE(mm.bt_flag, 0) AS bt_flag
    FROM machine_detailed_results m
    LEFT JOIN machine_master mm
      ON m.machine_name = mm.machine_name_normalized
    """
    df = pd.read_sql_query(q, con)
    con.close()
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
    df = df[df["date"].notna()].copy()
    df["diff_coins_normalized"] = pd.to_numeric(df["diff_coins_normalized"], errors="coerce").fillna(0.0)
    df["machine_number"] = pd.to_numeric(df["machine_number"], errors="coerce")
    df = df[df["machine_number"].notna()].copy()
    df["is_a_type"] = (
        (pd.to_numeric(df["jug_flag"], errors="coerce").fillna(0).astype(int) == 1)
        | (pd.to_numeric(df["hana_flag"], errors="coerce").fillna(0).astype(int) == 1)
        | (pd.to_numeric(df["oki_flag"], errors="coerce").fillna(0).astype(int) == 1)
        | (pd.to_numeric(df["bt_flag"], errors="coerce").fillna(0).astype(int) == 1)
    ).astype(int)
    df["segment"] = np.where(df["is_a_type"] == 1, "A", "N")
    df["last_digit"] = df["last_digit"].astype(str)
    return df


def _segment_tail_recommendation_for_rule_days(
    *,
    machine_df: pd.DataFrame,
    sel_days: set[pd.Timestamp],
    ho_days: set[pd.Timestamp],
) -> dict[str, Any]:
    if machine_df.empty or not sel_days or not ho_days:
        return {
            "recommended_segment": "",
            "recommended_tail": "",
            "n_sel_rule_days": int(len(sel_days)),
            "n_ho_rule_days": int(len(ho_days)),
            "holdout_segment_win_rate": np.nan,
            "holdout_tail_rank1_within_segment_rate": np.nan,
            "holdout_avg_diff_for_tail_in_segment": np.nan,
        }

    sel = machine_df[machine_df["date"].isin(list(sel_days))].copy()
    ho = machine_df[machine_df["date"].isin(list(ho_days))].copy()
    if sel.empty or ho.empty:
        return {
            "recommended_segment": "",
            "recommended_tail": "",
            "n_sel_rule_days": int(len(sel_days)),
            "n_ho_rule_days": int(len(ho_days)),
            "holdout_segment_win_rate": np.nan,
            "holdout_tail_rank1_within_segment_rate": np.nan,
            "holdout_avg_diff_for_tail_in_segment": np.nan,
        }

    seg_sel = (
        sel.groupby(["date", "segment"], sort=True)["diff_coins_normalized"]
        .sum()
        .reset_index()
    )
    seg_mean = seg_sel.groupby("segment", sort=True)["diff_coins_normalized"].mean().sort_values(ascending=False)
    if seg_mean.empty:
        return {
            "recommended_segment": "",
            "recommended_tail": "",
            "n_sel_rule_days": int(len(sel_days)),
            "n_ho_rule_days": int(len(ho_days)),
            "holdout_segment_win_rate": np.nan,
            "holdout_tail_rank1_within_segment_rate": np.nan,
            "holdout_avg_diff_for_tail_in_segment": np.nan,
        }
    rec_seg = str(seg_mean.index[0])

    tail_sel = (
        sel[sel["segment"] == rec_seg]
        .groupby(["date", "last_digit"], sort=True)["diff_coins_normalized"]
        .sum()
        .reset_index()
    )
    tail_mean = tail_sel.groupby("last_digit", sort=True)["diff_coins_normalized"].mean().sort_values(ascending=False)
    if tail_mean.empty:
        rec_tail = ""
    else:
        rec_tail = str(tail_mean.index[0])

    seg_ho = (
        ho.groupby(["date", "segment"], sort=True)["diff_coins_normalized"]
        .sum()
        .reset_index()
    )
    seg_ho["seg_rank"] = seg_ho.groupby("date", sort=False)["diff_coins_normalized"].rank(method="first", ascending=False)
    seg_win_rate = float(
        seg_ho[seg_ho["segment"] == rec_seg]["seg_rank"].eq(1).mean()
    ) if (seg_ho["segment"] == rec_seg).any() else np.nan

    tail_ho = (
        ho[ho["segment"] == rec_seg]
        .groupby(["date", "last_digit"], sort=True)["diff_coins_normalized"]
        .sum()
        .reset_index()
    )
    if not tail_ho.empty and rec_tail != "":
        tail_ho["tail_rank"] = tail_ho.groupby("date", sort=False)["diff_coins_normalized"].rank(method="first", ascending=False)
        tail_rank1_rate = float(
            tail_ho[tail_ho["last_digit"] == rec_tail]["tail_rank"].eq(1).mean()
        ) if (tail_ho["last_digit"] == rec_tail).any() else np.nan
        tail_avg = float(
            tail_ho[tail_ho["last_digit"] == rec_tail]["diff_coins_normalized"].mean()
        ) if (tail_ho["last_digit"] == rec_tail).any() else np.nan
    else:
        tail_rank1_rate = np.nan
        tail_avg = np.nan

    return {
        "recommended_segment": rec_seg,
        "recommended_tail": rec_tail,
        "n_sel_rule_days": int(len(sel_days)),
        "n_ho_rule_days": int(len(ho_days)),
        "holdout_segment_win_rate": seg_win_rate,
        "holdout_tail_rank1_within_segment_rate": tail_rank1_rate,
        "holdout_avg_diff_for_tail_in_segment": tail_avg,
    }


def _resolve_kamata7_db(db_dir: Path, pattern: str) -> Path:
    hits = sorted(db_dir.glob(pattern))
    if not hits:
        raise FileNotFoundError(f"Could not resolve Kamata7 DB with pattern={pattern} in {db_dir}")
    return hits[0]


def _add_timing_features(hall_df: pd.DataFrame) -> pd.DataFrame:
    out = hall_df.sort_values("date").copy()
    avg_diff = pd.to_numeric(out["avg_diff_per_machine"], errors="coerce").fillna(0.0)
    avg_games = pd.to_numeric(out["avg_games_per_machine"], errors="coerce").fillna(0.0)
    win_rate = pd.to_numeric(out["win_rate"], errors="coerce").fillna(0.0)
    total_machines = pd.to_numeric(out["total_machines"], errors="coerce").fillna(0.0)

    # Leakage-safe time features: all shifted by 1 day or more.
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

    out["weekday_sin"] = np.sin(2.0 * np.pi * out["weekday"].astype(float) / 7.0)
    out["weekday_cos"] = np.cos(2.0 * np.pi * out["weekday"].astype(float) / 7.0)
    out["dd_sin"] = np.sin(2.0 * np.pi * out["dd"].astype(float) / 31.0)
    out["dd_cos"] = np.cos(2.0 * np.pi * out["dd"].astype(float) / 31.0)
    return out


def _add_cross_hall_relative_features(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel.copy()
    grp = out.groupby("date", sort=False)["ewm28_avg_diff"]
    out["rel_rank_ewm28"] = grp.rank(method="average", ascending=False)
    n_store = grp.transform("count")
    out["rel_rank_ewm28_norm"] = np.where(n_store > 1, (out["rel_rank_ewm28"] - 1.0) / (n_store - 1.0), 0.0)
    mu = grp.transform("mean")
    sigma = grp.transform("std")
    out["rel_z_ewm28"] = np.where(sigma > 0, (out["ewm28_avg_diff"] - mu) / sigma, 0.0)
    return out


def _predict_binary_probabilities(
    train_x: pd.DataFrame,
    train_y: pd.Series,
    test_x: pd.DataFrame,
    *,
    c: float = 1.0,
    use_gpu: bool = False,
    gpu_backend: str = "cuda",
) -> np.ndarray:
    if test_x.empty:
        return np.array([], dtype=float)

    y = pd.to_numeric(train_y, errors="coerce").fillna(0).astype(int)
    if len(y) < 20:
        base = float(y.mean()) if len(y) else 0.5
        return np.full(len(test_x), base, dtype=float)
    if y.nunique() < 2:
        return np.full(len(test_x), float(y.iloc[0]), dtype=float)

    med = train_x.median(numeric_only=True).fillna(0.0)
    x_tr = train_x.fillna(med)
    x_te = test_x.fillna(med)
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=ConvergenceWarning)
            clf = make_binary_model(c=float(c), use_gpu=use_gpu, gpu_backend=gpu_backend)
            clf.fit(x_tr, y)
        proba = clf.predict_proba(x_te)[:, 1]
        return np.asarray(proba, dtype=float)
    except Exception:
        if use_gpu:
            return _predict_binary_probabilities(
                train_x=train_x,
                train_y=train_y,
                test_x=test_x,
                c=c,
                use_gpu=False,
                gpu_backend=gpu_backend,
            )
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=ConvergenceWarning)
                clf = LogisticRegression(max_iter=500, class_weight="balanced", solver="lbfgs", C=float(c), random_state=42)
                clf.fit(x_tr, y)
            proba = clf.predict_proba(x_te)[:, 1]
            return np.asarray(proba, dtype=float)
        except Exception:
            base = float(y.mean())
            return np.full(len(test_x), base, dtype=float)


def _predict_rank_scores(
    train_x: pd.DataFrame,
    train_y: pd.Series,
    test_x: pd.DataFrame,
    *,
    use_gpu: bool = False,
    gpu_backend: str = "cuda",
) -> np.ndarray:
    if test_x.empty:
        return np.array([], dtype=float)
    y = pd.to_numeric(train_y, errors="coerce").fillna(0.0)
    if len(y) < 30:
        base = float(y.mean()) if len(y) else 0.0
        return np.full(len(test_x), base, dtype=float)

    med = train_x.median(numeric_only=True).fillna(0.0)
    x_tr = train_x.fillna(med)
    x_te = test_x.fillna(med)
    try:
        model = make_regressor(use_gpu=use_gpu, gpu_backend=gpu_backend)
        model.fit(x_tr, y)
        pred = model.predict(x_te)
        return np.asarray(pred, dtype=float)
    except Exception:
        if use_gpu:
            return _predict_rank_scores(
                train_x=train_x,
                train_y=train_y,
                test_x=test_x,
                use_gpu=False,
                gpu_backend=gpu_backend,
            )
        try:
            model = HistGradientBoostingRegressor(
                loss="squared_error",
                learning_rate=0.05,
                max_depth=4,
                max_iter=300,
                random_state=42,
            )
            model.fit(x_tr, y)
            pred = model.predict(x_te)
            return np.asarray(pred, dtype=float)
        except Exception:
            base = float(y.mean())
            return np.full(len(test_x), base, dtype=float)


def _build_multihall_panel(
    *,
    store_to_hall_df: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for store, hall_df in store_to_hall_df.items():
        one = _add_timing_features(hall_df)
        one["store"] = str(store)
        rows.append(one)
    if not rows:
        return pd.DataFrame()
    panel = pd.concat(rows, axis=0, ignore_index=True)
    panel = _add_cross_hall_relative_features(panel)
    return panel.sort_values(["date", "store"]).reset_index(drop=True)


def _build_signal_feature_map(
    *,
    train_df: pd.DataFrame,
    topk_dd: int,
    min_dd_days: int,
) -> dict[str, int]:
    if train_df.empty:
        return {}
    dd_stats = (
        train_df.assign(
            dd=pd.to_numeric(train_df["dd"], errors="coerce"),
            avg_diff_per_machine=pd.to_numeric(train_df["avg_diff_per_machine"], errors="coerce"),
        )
        .dropna(subset=["dd"])
        .groupby("dd", sort=False)["avg_diff_per_machine"]
        .agg(["mean", "count"])
        .reset_index()
    )
    dd_stats = dd_stats[dd_stats["count"] >= max(1, int(min_dd_days))]
    dd_vals = (
        dd_stats.sort_values("mean", ascending=False)
        .head(max(1, int(topk_dd)))["dd"]
        .astype(int)
        .tolist()
    )
    return {int(x): 1 for x in dd_vals}


def _hall_specific_feature_cols() -> list[str]:
    return [
        "weekday",
        "weekday_sin",
        "weekday_cos",
        "dd_sin",
        "dd_cos",
        "is_any_event",
        "is_zorome_day",
        "is_strong_zorome_day",
        "is_dd_topk_train",
    ]


def _build_hall_specific_prediction_table(
    *,
    panel_df: pd.DataFrame,
    hall_judgments: dict[str, str],
    selection_start: str,
    eval_start: str,
    eval_end: str,
    dd_topk_k: int,
    dd_topk_min_days: int,
    use_gpu: bool = False,
    gpu_backend: str = "cuda",
) -> pd.DataFrame:
    if panel_df.empty:
        return pd.DataFrame()

    panel = panel_df.copy()
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel.sort_values(["date", "store"]).reset_index(drop=True)
    h_start = pd.Timestamp(str(eval_start))
    h_end = pd.Timestamp(str(eval_end))
    s_start = pd.Timestamp(str(selection_start))
    thresholds = [0, 100, 200, 300]
    feature_cols = _hall_specific_feature_cols()
    for col in feature_cols:
        if col not in panel.columns:
            panel[col] = np.nan

    out_rows: list[dict[str, Any]] = []
    holdout_dates = sorted(panel[(panel["date"] >= h_start) & (panel["date"] <= h_end)]["date"].drop_duplicates().tolist())
    for cur in tqdm(holdout_dates, desc="per-hall walk-forward", leave=False):
        day_start = time.time()
        day_panel = panel[(panel["date"] == cur)].copy()
        for store, day_df in tqdm(day_panel.groupby("store", sort=False), desc=f"{pd.Timestamp(cur).date()} halls", leave=False):
            train = panel[(panel["store"] == store) & (panel["date"] >= s_start) & (panel["date"] < cur)].copy()
            test = day_df.copy()
            if train.empty or test.empty:
                continue
            print(f"[{store}] train_n={len(train)} val_n={len(test)} date={pd.Timestamp(cur).date()}")
            t0 = time.time()
            hall_class = str(hall_judgments.get(str(store), "SIGNAL_DETECTED")).upper()
            dd_topk_map = _build_signal_feature_map(
                train_df=train,
                topk_dd=int(dd_topk_k),
                min_dd_days=int(dd_topk_min_days),
            )
            test = test.copy()
            test["is_dd_topk_train"] = test["dd"].astype(int).isin(dd_topk_map.keys()).astype(int)
            base_rates = {
                thr: float(pd.to_numeric(train[f"is_ge_{thr}"], errors="coerce").mean()) if f"is_ge_{thr}" in train.columns else 0.5
                for thr in thresholds
            }
            if hall_class == "SIGNAL_DETECTED":
                probs = {}
                for thr in thresholds:
                    target_col = f"is_ge_{thr}"
                    if target_col not in train.columns:
                        probs[thr] = np.full(len(test), base_rates[thr], dtype=float)
                        continue
                    probs[thr] = _predict_binary_probabilities(
                        train_x=train[feature_cols],
                        train_y=train[target_col],
                        test_x=test[feature_cols],
                        use_gpu=use_gpu,
                        gpu_backend=gpu_backend,
                    )
            else:
                probs = {thr: np.full(len(test), base_rates[thr], dtype=float) for thr in thresholds}
            elapsed = time.time() - t0
            if elapsed > 30.0:
                print(f"WARNING: per-hall {store} on {pd.Timestamp(cur).date()} took {elapsed:.1f}s — possible hang")

            for idx, r in test.reset_index(drop=True).iterrows():
                out_rows.append(
                    {
                        "date": pd.Timestamp(cur).strftime("%Y-%m-%d"),
                        "store": str(store),
                        "signal_class": hall_class,
                        "dd": int(pd.to_numeric(r.get("dd", np.nan), errors="coerce")) if pd.notna(pd.to_numeric(r.get("dd", np.nan), errors="coerce")) else -1,
                        "is_dd_topk_train": int(r["is_dd_topk_train"]),
                        "base_rate_ge_0_train": float(base_rates[0]),
                        "base_rate_ge_100_train": float(base_rates[100]),
                        "p_ge_0": float(probs[0][idx]),
                        "p_ge_100": float(probs[100][idx]),
                        "p_ge_200": float(probs[200][idx]),
                        "p_ge_300": float(probs[300][idx]),
                        "actual_avg_diff_per_machine": float(r["avg_diff_per_machine"]),
                        "actual_hit_ge_0": int(r["is_ge_0"]),
                        "actual_hit_ge_100": int(r["is_ge_100"]),
                        "actual_hit_ge_200": int(r["is_ge_200"]),
                        "actual_hit_ge_300": int(r["is_ge_300"]),
                    }
                )
        day_elapsed = time.time() - day_start
        if day_elapsed > 30.0:
            print(f"WARNING: per-hall day {pd.Timestamp(cur).date()} took {day_elapsed:.1f}s — possible hang")

    return pd.DataFrame(out_rows)


def _apply_hall_selection_policy(
    *,
    pred_df: pd.DataFrame,
    weights: tuple[float, float, float],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if pred_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for d, g in pred_df.groupby("date", sort=True):
        tmp = g.copy()
        p0 = pd.to_numeric(tmp["p_ge_0"], errors="coerce").to_numpy() if "p_ge_0" in tmp.columns else np.ones(len(tmp), dtype=float)
        tmp["score"] = _expected_strength_score(
            pd.to_numeric(tmp["p_ge_100"], errors="coerce").to_numpy(),
            pd.to_numeric(tmp["p_ge_200"], errors="coerce").to_numpy(),
            pd.to_numeric(tmp["p_ge_300"], errors="coerce").to_numpy(),
            p0,
            weights=weights,
        )
        tmp = tmp.sort_values(["score", "p_ge_100"], ascending=[False, False])
        picked = tmp.iloc[0]
        oracle = tmp.sort_values("actual_avg_diff_per_machine", ascending=False).iloc[0]
        pred_top2 = tmp.head(min(2, len(tmp)))["store"].astype(str).tolist()
        pred_top1 = str(picked["store"])
        oracle_store = str(oracle["store"])
        rows.append(
            {
                "date": str(d),
                "picked_store": pred_top1,
                "picked_signal_class": str(picked["signal_class"]),
                "picked_score": float(picked["score"]),
                "picked_actual_avg_diff_per_machine": float(picked["actual_avg_diff_per_machine"]),
                "oracle_store": oracle_store,
                "oracle_signal_class": str(oracle["signal_class"]),
                "oracle_actual_avg_diff_per_machine": float(oracle["actual_avg_diff_per_machine"]),
                "top1_hit": int(pred_top1 == oracle_store),
                "top2_inclusion": int(oracle_store in pred_top2),
                "spearman_daily_rho": _safe_spearman_rank_corr(
                    tmp["score"].rank(method="first", ascending=False),
                    tmp["actual_avg_diff_per_machine"].rank(method="first", ascending=False),
                ),
                "regret_vs_oracle": float(max(0.0, float(oracle["actual_avg_diff_per_machine"]) - float(picked["actual_avg_diff_per_machine"]))),
                "chosen_vs_oracle_diff_gap": float(float(picked["actual_avg_diff_per_machine"]) - float(oracle["actual_avg_diff_per_machine"])),
                "pred_top2_stores": ",".join(pred_top2),
                "policy_w100": float(weights[0]),
                "policy_w200": float(weights[1]),
                "policy_w300": float(weights[2]),
            }
        )

    daily = pd.DataFrame(rows)
    if daily.empty:
        return daily, pd.DataFrame()
    summary = pd.DataFrame(
        [
            {
                "n_days": int(len(daily)),
                "chosen_avg_diff_mean": float(pd.to_numeric(daily["picked_actual_avg_diff_per_machine"], errors="coerce").mean()),
                "oracle_avg_diff_mean": float(pd.to_numeric(daily["oracle_actual_avg_diff_per_machine"], errors="coerce").mean()),
                "top1_hit_rate": float(pd.to_numeric(daily["top1_hit"], errors="coerce").mean()),
                "top2_inclusion_rate": float(pd.to_numeric(daily["top2_inclusion"], errors="coerce").mean()),
                "spearman_daily_mean": float(pd.to_numeric(daily["spearman_daily_rho"], errors="coerce").mean()),
                "regret_mean": float(pd.to_numeric(daily["regret_vs_oracle"], errors="coerce").mean()),
                "regret_sum": float(pd.to_numeric(daily["regret_vs_oracle"], errors="coerce").sum()),
                "avg_diff_gap_chosen_minus_oracle": float(pd.to_numeric(daily["chosen_vs_oracle_diff_gap"], errors="coerce").mean()),
            }
        ]
    )
    return daily, summary


def _build_hall_accuracy_audit(
    *,
    daily_df: pd.DataFrame,
    hall_judgments: dict[str, str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if daily_df.empty:
        return pd.DataFrame(), pd.DataFrame()
    d = daily_df.copy()
    d["picked_is_no_signal"] = d["picked_store"].astype(str).map(lambda s: str(hall_judgments.get(s, "")).upper() == "NO_SIGNAL").astype(int)
    d["oracle_is_no_signal"] = d["oracle_store"].astype(str).map(lambda s: str(hall_judgments.get(s, "")).upper() == "NO_SIGNAL").astype(int)
    overall = pd.DataFrame(
        [
            {
                "n_days": int(len(d)),
                "top1_hit_rate": float(pd.to_numeric(d["top1_hit"], errors="coerce").mean()),
                "top2_inclusion_rate": float(pd.to_numeric(d["top2_inclusion"], errors="coerce").mean()),
                "spearman_daily_mean": float(pd.to_numeric(d["spearman_daily_rho"], errors="coerce").mean()),
                "regret_mean": float(pd.to_numeric(d["regret_vs_oracle"], errors="coerce").mean()),
                "regret_sum": float(pd.to_numeric(d["regret_vs_oracle"], errors="coerce").sum()),
                "chosen_avg_diff_mean": float(pd.to_numeric(d["picked_actual_avg_diff_per_machine"], errors="coerce").mean()),
            }
        ]
    )
    by_class_rows: list[dict[str, Any]] = []
    for class_name, mask in [
        ("picked_signal", d["picked_is_no_signal"] == 0),
        ("picked_no_signal", d["picked_is_no_signal"] == 1),
        ("oracle_signal", d["oracle_is_no_signal"] == 0),
        ("oracle_no_signal", d["oracle_is_no_signal"] == 1),
    ]:
        sub = d[mask].copy()
        if sub.empty:
            continue
        by_class_rows.append(
            {
                "class": class_name,
                "n_days": int(len(sub)),
                "top1_hit_rate": float(pd.to_numeric(sub["top1_hit"], errors="coerce").mean()),
                "top2_inclusion_rate": float(pd.to_numeric(sub["top2_inclusion"], errors="coerce").mean()),
                "spearman_daily_mean": float(pd.to_numeric(sub["spearman_daily_rho"], errors="coerce").mean()),
                "regret_mean": float(pd.to_numeric(sub["regret_vs_oracle"], errors="coerce").mean()),
                "regret_sum": float(pd.to_numeric(sub["regret_vs_oracle"], errors="coerce").sum()),
                "chosen_avg_diff_mean": float(pd.to_numeric(sub["picked_actual_avg_diff_per_machine"], errors="coerce").mean()),
            }
        )
    return overall, pd.DataFrame(by_class_rows)


def _optimize_hall_specific_weights(
    *,
    pred_df_tune: pd.DataFrame,
    weight_grid: list[tuple[float, float, float]],
    objective: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    if pred_df_tune.empty:
        return {"weights": (1.0, 1.0, 1.0)}, pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for w in tqdm(weight_grid, desc="per-hall weight grid", leave=False):
        t0 = time.time()
        daily, summary = _apply_hall_selection_policy(pred_df=pred_df_tune, weights=w)
        if summary.empty:
            continue
        s = summary.iloc[0].to_dict()
        rows.append(
            {
                "w100": float(w[0]),
                "w200": float(w[1]),
                "w300": float(w[2]),
                "n_days": int(s["n_days"]),
                "chosen_avg_diff_mean": float(s["chosen_avg_diff_mean"]),
                "oracle_avg_diff_mean": float(s["oracle_avg_diff_mean"]),
                "top1_hit_rate": float(s["top1_hit_rate"]),
                "top2_inclusion_rate": float(s["top2_inclusion_rate"]),
                "spearman_daily_mean": float(s["spearman_daily_mean"]),
                "regret_mean": float(s["regret_mean"]),
                "regret_sum": float(s["regret_sum"]),
                "avg_diff_gap_chosen_minus_oracle": float(s["avg_diff_gap_chosen_minus_oracle"]),
            }
        )
        elapsed = time.time() - t0
        if elapsed > 30.0:
            print(f"WARNING: per-hall weights {w} took {elapsed:.1f}s — possible hang")

    table = pd.DataFrame(rows)
    if table.empty:
        return {"weights": (1.0, 1.0, 1.0)}, table

    if str(objective).lower() == "regret":
        table = table.sort_values(
            ["regret_mean", "chosen_avg_diff_mean", "top1_hit_rate", "spearman_daily_mean"],
            ascending=[True, False, False, False],
        ).reset_index(drop=True)
    else:
        table = table.sort_values(
            ["chosen_avg_diff_mean", "top1_hit_rate", "top2_inclusion_rate", "regret_mean"],
            ascending=[False, False, False, True],
        ).reset_index(drop=True)
    best = table.iloc[0]
    return {
        "weights": (float(best["w100"]), float(best["w200"]), float(best["w300"])),
    }, table


def _build_strategy_comparison_table(strategy_summaries: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for strategy_name, summary_df in strategy_summaries.items():
        if summary_df.empty:
            continue
        s = summary_df.iloc[0].to_dict()
        rows.append(
            {
                "strategy": str(strategy_name),
                "n_days": int(s.get("n_days", s.get("n_days_with_at_least_one_signal", 0))),
                "chosen_avg_diff_mean": float(s.get("chosen_avg_diff_mean", s.get("picked_avg_diff_per_machine_mean", np.nan))),
                "oracle_avg_diff_mean": float(s.get("oracle_avg_diff_mean", s.get("oracle_avg_diff_per_machine_mean", np.nan))),
                "top1_hit_rate": float(s.get("top1_hit_rate", s.get("hit_at_1_rate", np.nan))),
                "top2_inclusion_rate": float(s.get("top2_inclusion_rate", s.get("hit_at_2_rate", np.nan))),
                "spearman_daily_mean": float(s.get("spearman_daily_mean", np.nan)),
                "regret_mean": float(s.get("regret_mean", np.nan)),
                "regret_sum": float(s.get("regret_sum", np.nan)),
            }
        )
    table = pd.DataFrame(rows)
    if table.empty:
        return table
    table["rank_by_chosen_avg_diff"] = table["chosen_avg_diff_mean"].rank(method="dense", ascending=False).astype(int)
    table["rank_by_regret"] = table["regret_mean"].rank(method="dense", ascending=True).astype(int)
    table = table.sort_values(
        ["chosen_avg_diff_mean", "top1_hit_rate", "top2_inclusion_rate", "regret_mean"],
        ascending=[False, False, False, True],
    ).reset_index(drop=True)
    return table


def _run_multihall_timing_ml(
    *,
    panel_df: pd.DataFrame,
    candidate_stores: list[str],
    thresholds: list[int],
    selection_start: str,
    holdout_start: str,
    holdout_end: str,
    ml_min_edge: float,
    use_gpu: bool = False,
    gpu_backend: str = "cuda",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if panel_df.empty or not candidate_stores:
        return pd.DataFrame(), pd.DataFrame()

    feature_cols = [
        "lag1_avg_diff",
        "lag2_avg_diff",
        "lag7_avg_diff",
        "ewm7_avg_diff",
        "ewm28_avg_diff",
        "trend_gap_7_28",
        "delta_lag1",
        "vol14_avg_diff",
        "roll7_games",
        "roll7_win_rate",
        "roll7_total_machines",
        "weekday",
        "dd",
        "is_any_event",
        "is_zorome_day",
        "is_strong_zorome_day",
        "is_day_7x",
        "is_day_1x",
        "weekday_sin",
        "weekday_cos",
        "dd_sin",
        "dd_cos",
        "rel_rank_ewm28_norm",
        "rel_z_ewm28",
    ]
    for col in feature_cols:
        if col not in panel_df.columns:
            panel_df[col] = np.nan

    out_rows: list[dict[str, Any]] = []
    h_start = pd.Timestamp(str(holdout_start))
    h_end = pd.Timestamp(str(holdout_end))
    s_start = pd.Timestamp(str(selection_start))

    panel = panel_df.copy()
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel.sort_values(["date", "store"]).reset_index(drop=True)

    holdout_dates = sorted(panel[(panel["date"] >= h_start) & (panel["date"] <= h_end)]["date"].drop_duplicates().tolist())
    for cur in holdout_dates:
        train = panel[(panel["date"] >= s_start) & (panel["date"] < cur)].copy()
        test = panel[(panel["date"] == cur) & (panel["store"].isin(candidate_stores))].copy()
        if train.empty or test.empty:
            continue
        for thr in thresholds:
            target_col = f"is_ge_{int(thr)}"
            if target_col not in train.columns or target_col not in test.columns:
                continue
            base_rate = float(pd.to_numeric(train[target_col], errors="coerce").mean()) if len(train) else 0.5
            proba = _predict_binary_probabilities(
                train_x=train[feature_cols],
                train_y=train[target_col],
                test_x=test[feature_cols],
                use_gpu=use_gpu,
                gpu_backend=gpu_backend,
            )
            tmp = test.copy()
            tmp["pred_proba"] = proba
            tmp["actual_hit"] = pd.to_numeric(tmp[target_col], errors="coerce").fillna(0).astype(int)
            tmp["pred_play"] = (tmp["pred_proba"] >= (base_rate + float(ml_min_edge))).astype(int)
            playable = tmp[tmp["pred_play"] == 1].copy()
            if playable.empty:
                continue
            playable = playable.sort_values(["pred_proba", "ewm28_avg_diff"], ascending=[False, False])
            picked = playable.iloc[0]
            oracle = tmp.sort_values("avg_diff_per_machine", ascending=False).iloc[0]
            out_rows.append(
                {
                    "date": pd.Timestamp(cur).strftime("%Y-%m-%d"),
                    "threshold": int(thr),
                    "n_candidate_halls_today": int(tmp["store"].nunique()),
                    "n_halls_pred_play_today": int(playable["store"].nunique()),
                    "train_base_rate": base_rate,
                    "picked_store": str(picked["store"]),
                    "picked_pred_proba": float(picked["pred_proba"]),
                    "picked_actual_avg_diff_per_machine": float(picked["avg_diff_per_machine"]),
                    "picked_target_hit": int(picked["actual_hit"]),
                    "oracle_store": str(oracle["store"]),
                    "oracle_actual_avg_diff_per_machine": float(oracle["avg_diff_per_machine"]),
                    "oracle_target_hit": int(oracle["actual_hit"]),
                    "picked_vs_oracle_diff_gap": float(picked["avg_diff_per_machine"] - oracle["avg_diff_per_machine"]),
                }
            )

    daily = pd.DataFrame(out_rows)
    if daily.empty:
        return daily, pd.DataFrame()

    summary_rows: list[dict[str, Any]] = []
    for thr, g in daily.groupby("threshold", sort=True):
        summary_rows.append(
            {
                "threshold": int(thr),
                "n_days_with_at_least_one_signal": int(len(g)),
                "picked_avg_diff_per_machine_mean": float(pd.to_numeric(g["picked_actual_avg_diff_per_machine"], errors="coerce").mean()),
                "oracle_avg_diff_per_machine_mean": float(pd.to_numeric(g["oracle_actual_avg_diff_per_machine"], errors="coerce").mean()),
                "picked_target_hit_rate": float(pd.to_numeric(g["picked_target_hit"], errors="coerce").mean()),
                "oracle_target_hit_rate": float(pd.to_numeric(g["oracle_target_hit"], errors="coerce").mean()),
                "avg_diff_gap_picked_minus_oracle": float(pd.to_numeric(g["picked_vs_oracle_diff_gap"], errors="coerce").mean()),
            }
        )
    summary = pd.DataFrame(summary_rows).sort_values("threshold").reset_index(drop=True)
    return daily, summary


def _rolling_kamata7_rules(
    *,
    hall_df: pd.DataFrame,
    thresholds: list[int],
    selection_start: str,
    holdout_start: str,
    holdout_end: str,
    window_days: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rules = tuple(r for r in DEFAULT_RULES if r != "all_days")
    out_rows: list[dict[str, Any]] = []
    h_start = pd.Timestamp(str(holdout_start))
    h_end = min(pd.Timestamp(str(holdout_end)), pd.to_datetime(hall_df["date"]).max())
    s_start = pd.Timestamp(str(selection_start))

    for dt in sorted(pd.to_datetime(hall_df["date"]).unique()):
        cur = pd.Timestamp(dt)
        if cur < h_start or cur > h_end:
            continue
        train_end = cur - pd.Timedelta(days=1)
        train_start = max(s_start, train_end - pd.Timedelta(days=max(1, int(window_days) - 1)))
        train = hall_df[(hall_df["date"] >= train_start) & (hall_df["date"] <= train_end)].copy()
        day = hall_df[hall_df["date"] == cur].copy()
        if train.empty or day.empty:
            continue
        meta = build_rule_meta(train, topk_dd=5, min_dd_days=6)
        for thr in thresholds:
            target_col = f"is_ge_{int(thr)}"
            eval_train = evaluate_target_rules(train, rule_meta=meta, target_col=target_col, rules=rules)
            if eval_train.empty:
                continue
            best = eval_train.sort_values(["success_rate_lift_vs_all", "avg_diff_lift_vs_all"], ascending=[False, False]).iloc[0]
            best_rule = str(best["rule"])
            play = int(apply_rule(day, best_rule, meta).iloc[0])
            y = int(pd.to_numeric(day[target_col], errors="coerce").fillna(0).iloc[0])
            out_rows.append(
                {
                    "date": cur.strftime("%Y-%m-%d"),
                    "threshold": int(thr),
                    "target_col": target_col,
                    "window_start": train_start.strftime("%Y-%m-%d"),
                    "window_end": train_end.strftime("%Y-%m-%d"),
                    "chosen_rule": best_rule,
                    "train_base_rate": float(best["base_rate_all"]),
                    "train_rule_success_rate": float(best["success_rate"]),
                    "train_rule_lift": float(best["success_rate_lift_vs_all"]),
                    "pred_play": play,
                    "actual_hit": y,
                    "pred_and_hit": int(play == 1 and y == 1),
                }
            )
    daily = pd.DataFrame(out_rows)
    if daily.empty:
        return daily, pd.DataFrame()
    summary_rows: list[dict[str, Any]] = []
    for thr, g in daily.groupby("threshold", sort=True):
        play = g[g["pred_play"] == 1]
        base_rate = float(g["actual_hit"].mean())
        play_hit = float(play["actual_hit"].mean()) if len(play) else np.nan
        summary_rows.append(
            {
                "threshold": int(thr),
                "n_days": int(len(g)),
                "play_days": int(len(play)),
                "play_rate": float(len(play) / len(g)),
                "base_rate": base_rate,
                "hit_rate_on_play_days": play_hit,
                "lift_on_play_days": (play_hit - base_rate) if np.isfinite(play_hit) else np.nan,
            }
        )
    summary = pd.DataFrame(summary_rows).sort_values("threshold").reset_index(drop=True)
    return daily, summary


def _run_multihall_rank_model(
    *,
    panel_df: pd.DataFrame,
    candidate_stores: list[str],
    selection_start: str,
    holdout_start: str,
    holdout_end: str,
    use_gpu: bool = False,
    gpu_backend: str = "cuda",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if panel_df.empty or not candidate_stores:
        return pd.DataFrame(), pd.DataFrame()

    feature_cols = [
        "lag1_avg_diff",
        "lag2_avg_diff",
        "lag7_avg_diff",
        "ewm7_avg_diff",
        "ewm28_avg_diff",
        "trend_gap_7_28",
        "delta_lag1",
        "vol14_avg_diff",
        "roll7_games",
        "roll7_win_rate",
        "roll7_total_machines",
        "weekday",
        "dd",
        "is_any_event",
        "is_zorome_day",
        "is_strong_zorome_day",
        "is_day_7x",
        "is_day_1x",
        "weekday_sin",
        "weekday_cos",
        "dd_sin",
        "dd_cos",
        "rel_rank_ewm28_norm",
        "rel_z_ewm28",
    ]
    for col in feature_cols:
        if col not in panel_df.columns:
            panel_df[col] = np.nan

    out_rows: list[dict[str, Any]] = []
    h_start = pd.Timestamp(str(holdout_start))
    h_end = pd.Timestamp(str(holdout_end))
    s_start = pd.Timestamp(str(selection_start))

    panel = panel_df.copy()
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel.sort_values(["date", "store"]).reset_index(drop=True)
    holdout_dates = sorted(panel[(panel["date"] >= h_start) & (panel["date"] <= h_end)]["date"].drop_duplicates().tolist())

    for cur in holdout_dates:
        train = panel[(panel["date"] >= s_start) & (panel["date"] < cur)].copy()
        test = panel[(panel["date"] == cur) & (panel["store"].isin(candidate_stores))].copy()
        if train.empty or test.empty:
            continue
        pred = _predict_rank_scores(
            train_x=train[feature_cols],
            train_y=train["avg_diff_per_machine"],
            test_x=test[feature_cols],
            use_gpu=use_gpu,
            gpu_backend=gpu_backend,
        )
        tmp = test.copy()
        tmp["pred_rank_score"] = pred
        tmp = tmp.sort_values(["pred_rank_score", "ewm28_avg_diff"], ascending=[False, False])
        picked = tmp.iloc[0]
        oracle = tmp.sort_values("avg_diff_per_machine", ascending=False).iloc[0]
        pred_top2 = tmp.head(min(2, len(tmp)))["store"].astype(str).tolist()
        oracle_store = str(oracle["store"])
        hit_at_1 = int(str(picked["store"]) == oracle_store)
        hit_at_2 = int(oracle_store in pred_top2)
        out_rows.append(
            {
                "date": pd.Timestamp(cur).strftime("%Y-%m-%d"),
                "n_candidate_halls_today": int(tmp["store"].nunique()),
                "picked_store": str(picked["store"]),
                "picked_pred_rank_score": float(picked["pred_rank_score"]),
                "picked_actual_avg_diff_per_machine": float(picked["avg_diff_per_machine"]),
                "oracle_store": oracle_store,
                "oracle_actual_avg_diff_per_machine": float(oracle["avg_diff_per_machine"]),
                "picked_vs_oracle_diff_gap": float(picked["avg_diff_per_machine"] - oracle["avg_diff_per_machine"]),
                "hit_at_1": hit_at_1,
                "hit_at_2": hit_at_2,
                "pred_top2_stores": ",".join(pred_top2),
            }
        )
    daily = pd.DataFrame(out_rows)
    if daily.empty:
        return daily, pd.DataFrame()
    summary = pd.DataFrame(
        [
            {
                "n_days_with_at_least_one_signal": int(len(daily)),
                "picked_avg_diff_per_machine_mean": float(pd.to_numeric(daily["picked_actual_avg_diff_per_machine"], errors="coerce").mean()),
                "oracle_avg_diff_per_machine_mean": float(pd.to_numeric(daily["oracle_actual_avg_diff_per_machine"], errors="coerce").mean()),
                "avg_diff_gap_picked_minus_oracle": float(pd.to_numeric(daily["picked_vs_oracle_diff_gap"], errors="coerce").mean()),
                "hit_at_1_rate": float(pd.to_numeric(daily["hit_at_1"], errors="coerce").mean()),
                "hit_at_2_rate": float(pd.to_numeric(daily["hit_at_2"], errors="coerce").mean()),
            }
        ]
    )
    return daily, summary


def _expected_strength_score(
    p100: np.ndarray,
    p200: np.ndarray,
    p300: np.ndarray,
    p0: np.ndarray | None = None,
    weights: tuple[float, float, float] | None = None,
) -> np.ndarray:
    del weights
    p100_arr = np.asarray(p100, dtype=float)
    p200_arr = np.asarray(p200, dtype=float)
    p300_arr = np.asarray(p300, dtype=float)
    if p0 is None:
        p0_arr = np.ones_like(p100_arr, dtype=float)
    else:
        p0_arr = np.asarray(p0, dtype=float)
    return (
        -100.0 * (1.0 - p0_arr)
        + 50.0 * (p0_arr - p100_arr)
        + 150.0 * (p100_arr - p200_arr)
        + 250.0 * (p200_arr - p300_arr)
        + 350.0 * p300_arr
    )


def _safe_spearman_rank_corr(pred_rank: pd.Series, actual_rank: pd.Series) -> float:
    a = pd.to_numeric(pred_rank, errors="coerce")
    b = pd.to_numeric(actual_rank, errors="coerce")
    if a.isna().all() or b.isna().all():
        return float("nan")
    if a.nunique(dropna=True) <= 1 or b.nunique(dropna=True) <= 1:
        return float("nan")
    v = a.corr(b, method="spearman")
    return float(v) if pd.notna(v) else float("nan")


def _projected_share_penalty(
    *,
    chosen_counts: dict[str, int],
    day_index: int,
    candidate_store: str,
    share_cap: float,
    share_penalty_scale: float,
) -> float:
    if float(share_cap) >= 1.0 or float(share_penalty_scale) <= 0.0:
        return 0.0
    next_count = int(chosen_counts.get(str(candidate_store), 0) + 1)
    projected_share = float(next_count / max(1, day_index))
    excess = max(0.0, projected_share - float(share_cap))
    return float(excess * float(share_penalty_scale))


def _compute_dd_topk_map_from_train(
    *,
    train_df: pd.DataFrame,
    topk: int,
    min_days: int,
) -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    if train_df.empty:
        return out
    src = train_df.copy()
    src["dd"] = pd.to_numeric(src["dd"], errors="coerce")
    src["avg_diff_per_machine"] = pd.to_numeric(src["avg_diff_per_machine"], errors="coerce")
    src = src[src["dd"].notna()].copy()
    if src.empty:
        return out
    for store, g in src.groupby("store", sort=False):
        dd_stats = (
            g.groupby("dd", sort=False)["avg_diff_per_machine"]
            .agg(["mean", "count"])
            .reset_index()
        )
        dd_stats = dd_stats[dd_stats["count"] >= max(1, int(min_days))]
        if dd_stats.empty:
            out[str(store)] = set()
            continue
        top = (
            dd_stats.sort_values("mean", ascending=False)
            .head(max(1, int(topk)))["dd"]
            .astype(int)
            .tolist()
        )
        out[str(store)] = set(top)
    return out


def _add_leakage_safe_dd_topk_feature(
    panel_df: pd.DataFrame,
    *,
    topk: int,
    min_days: int,
) -> pd.DataFrame:
    if panel_df.empty:
        return panel_df.copy()

    panel = panel_df.copy()
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel.sort_values(["store", "date"]).reset_index(drop=True)
    panel["is_dd_topk_train"] = 0
    for store, g in panel.groupby("store", sort=False):
        idxs = list(g.index)
        history_parts: list[pd.DataFrame] = []
        for idx in idxs:
            if history_parts:
                hist = pd.concat(history_parts, axis=0, ignore_index=True)
                dd_map = _compute_dd_topk_map_from_train(train_df=hist, topk=int(topk), min_days=int(min_days))
                dd_raw = pd.to_numeric(panel.at[idx, "dd"], errors="coerce")
                dd_now = int(dd_raw) if pd.notna(dd_raw) else -1
                panel.at[idx, "is_dd_topk_train"] = int(dd_now in dd_map.get(str(store), set()))
            history_parts.append(panel.loc[[idx]].copy())
    return panel.sort_values(["date", "store"]).reset_index(drop=True)


def _build_hybrid_feature_columns(*, include_lag1_avg_games: bool = False) -> list[str]:
    cols = [
        "lag1_avg_diff",
        "lag2_avg_diff",
        "lag7_avg_diff",
        "ewm7_avg_diff",
        "ewm28_avg_diff",
        "trend_gap_7_28",
        "delta_lag1",
        "vol14_avg_diff",
        "roll7_games",
        "roll7_win_rate",
        "roll7_total_machines",
        "weekday",
        "dd",
        "is_any_event",
        "is_zorome_day",
        "is_strong_zorome_day",
        "is_day_7x",
        "is_day_1x",
        "weekday_sin",
        "weekday_cos",
        "dd_sin",
        "dd_cos",
        "rel_rank_ewm28_norm",
        "rel_z_ewm28",
        "is_dd_topk_train",
    ]
    if include_lag1_avg_games:
        cols.insert(8, "lag1_avg_games")
    return cols


def _build_hybrid_design_matrices(
    train: pd.DataFrame,
    test: pd.DataFrame,
    *,
    hall_judgments: dict[str, str],
    include_lag1_avg_games: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    base_cols = _build_hybrid_feature_columns(include_lag1_avg_games=include_lag1_avg_games)
    all_stores = sorted(set(train["store"].astype(str).tolist()) | set(test["store"].astype(str).tolist()))
    signal_stores = {
        str(store)
        for store, judgment in hall_judgments.items()
        if str(judgment).upper() == "SIGNAL_DETECTED"
    }
    train_aug = train.copy()
    test_aug = test.copy()
    for col in base_cols:
        if col not in train_aug.columns:
            train_aug[col] = np.nan
        if col not in test_aug.columns:
            test_aug[col] = np.nan

    train_dummies = pd.get_dummies(train_aug["store"].astype(str), prefix="hall", drop_first=True)
    test_dummies = pd.get_dummies(test_aug["store"].astype(str), prefix="hall", drop_first=True)
    dummy_cols = sorted(set(train_dummies.columns).union(set(test_dummies.columns)))
    train_dummies = train_dummies.reindex(columns=dummy_cols, fill_value=0)
    test_dummies = test_dummies.reindex(columns=dummy_cols, fill_value=0)

    interaction_cols: list[str] = []
    signal_cols = ["is_dd_topk_train", "is_strong_zorome_day", "is_zorome_day", "is_any_event"]
    for hall_col in dummy_cols:
        store_name = hall_col.replace("hall_", "", 1)
        if store_name not in signal_stores:
            continue
        for sig in signal_cols:
            col_name = f"{hall_col}__x__{sig}"
            train_aug[col_name] = pd.to_numeric(train_aug[sig], errors="coerce").fillna(0.0) * train_dummies[hall_col]
            test_aug[col_name] = pd.to_numeric(test_aug[sig], errors="coerce").fillna(0.0) * test_dummies[hall_col]
            interaction_cols.append(col_name)

    train_aug = pd.concat([train_aug, train_dummies], axis=1)
    test_aug = pd.concat([test_aug, test_dummies], axis=1)

    feature_cols = base_cols + dummy_cols + interaction_cols
    for col in feature_cols:
        if col not in train_aug.columns:
            train_aug[col] = np.nan
        if col not in test_aug.columns:
            test_aug[col] = np.nan
    return train_aug, test_aug, feature_cols


def _build_allhall_prediction_table(
    *,
    panel_df: pd.DataFrame,
    selection_start: str,
    eval_start: str,
    eval_end: str,
    dd_topk_k: int,
    dd_topk_min_days: int,
    use_gpu: bool = False,
    gpu_backend: str = "cuda",
) -> pd.DataFrame:
    if panel_df.empty:
        return pd.DataFrame()

    feature_cols = [
        "lag1_avg_diff",
        "lag2_avg_diff",
        "lag7_avg_diff",
        "ewm7_avg_diff",
        "ewm28_avg_diff",
        "trend_gap_7_28",
        "delta_lag1",
        "vol14_avg_diff",
        "roll7_games",
        "roll7_win_rate",
        "roll7_total_machines",
        "weekday",
        "dd",
        "is_any_event",
        "is_zorome_day",
        "is_strong_zorome_day",
        "is_day_7x",
        "is_day_1x",
        "weekday_sin",
        "weekday_cos",
        "dd_sin",
        "dd_cos",
        "rel_rank_ewm28_norm",
        "rel_z_ewm28",
    ]
    for col in feature_cols:
        if col not in panel_df.columns:
            panel_df[col] = np.nan

    panel = panel_df.copy()
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel.sort_values(["date", "store"]).reset_index(drop=True)

    h_start = pd.Timestamp(str(eval_start))
    h_end = pd.Timestamp(str(eval_end))
    s_start = pd.Timestamp(str(selection_start))
    out_rows: list[dict[str, Any]] = []
    holdout_dates = sorted(panel[(panel["date"] >= h_start) & (panel["date"] <= h_end)]["date"].drop_duplicates().tolist())

    for cur in tqdm(holdout_dates, desc="pooled walk-forward", leave=False):
        train = panel[(panel["date"] >= s_start) & (panel["date"] < cur)].copy()
        test = panel[panel["date"] == cur].copy()
        if train.empty or test.empty:
            continue
        t0 = time.time()
        print(f"[pooled] {pd.Timestamp(cur).date()} train_n={len(train)} val_n={len(test)}")
        dd_topk_map = _compute_dd_topk_map_from_train(
            train_df=train,
            topk=int(dd_topk_k),
            min_days=int(dd_topk_min_days),
        )
        p0 = _predict_binary_probabilities(train[feature_cols], train["is_ge_0"], test[feature_cols], use_gpu=use_gpu, gpu_backend=gpu_backend)
        p100 = _predict_binary_probabilities(train[feature_cols], train["is_ge_100"], test[feature_cols], use_gpu=use_gpu, gpu_backend=gpu_backend)
        p200 = _predict_binary_probabilities(train[feature_cols], train["is_ge_200"], test[feature_cols], use_gpu=use_gpu, gpu_backend=gpu_backend)
        p300 = _predict_binary_probabilities(train[feature_cols], train["is_ge_300"], test[feature_cols], use_gpu=use_gpu, gpu_backend=gpu_backend)
        base0 = float(pd.to_numeric(train["is_ge_0"], errors="coerce").mean())
        base100 = float(pd.to_numeric(train["is_ge_100"], errors="coerce").mean())
        elapsed = time.time() - t0
        if elapsed > 30.0:
            print(f"WARNING: pooled day {pd.Timestamp(cur).date()} took {elapsed:.1f}s — possible hang")

        tmp = test.copy()
        tmp["p_ge_0"] = p0
        tmp["p_ge_100"] = p100
        tmp["p_ge_200"] = p200
        tmp["p_ge_300"] = p300
        for _, r in tmp.iterrows():
            store = str(r["store"])
            dd_raw = pd.to_numeric(r.get("dd", np.nan), errors="coerce")
            dd_now = int(dd_raw) if pd.notna(dd_raw) else -1
            out_rows.append(
                {
                    "date": pd.Timestamp(cur).strftime("%Y-%m-%d"),
                    "store": store,
                    "n_halls_today": int(len(tmp)),
                    "dd": dd_now,
                    "is_strong_zorome_day": int(pd.to_numeric(r.get("is_strong_zorome_day", 0), errors="coerce")),
                    "is_dd_topk_train": int(dd_now in dd_topk_map.get(store, set())),
                    "base_rate_ge_0_train": base0,
                    "base_rate_ge_100_train": base100,
                    "p_ge_0": float(r["p_ge_0"]),
                    "p_ge_100": float(r["p_ge_100"]),
                    "p_ge_200": float(r["p_ge_200"]),
                    "p_ge_300": float(r["p_ge_300"]),
                    "actual_avg_diff_per_machine": float(r["avg_diff_per_machine"]),
                    "actual_hit_ge_0": int(r["is_ge_0"]),
                }
            )

    return pd.DataFrame(out_rows)


def _build_hybrid_prediction_table(
    *,
    panel_df: pd.DataFrame,
    hall_judgments: dict[str, str],
    selection_start: str,
    eval_start: str,
    eval_end: str,
    dd_topk_k: int,
    dd_topk_min_days: int,
    logreg_c: float,
    include_lag1_avg_games: bool = False,
    use_gpu: bool = False,
    gpu_backend: str = "cuda",
) -> pd.DataFrame:
    if panel_df.empty:
        return pd.DataFrame()

    panel = panel_df.copy()
    panel["date"] = pd.to_datetime(panel["date"])
    panel = _add_leakage_safe_dd_topk_feature(panel, topk=int(dd_topk_k), min_days=int(dd_topk_min_days))
    panel = panel.sort_values(["date", "store"]).reset_index(drop=True)

    h_start = pd.Timestamp(str(eval_start))
    h_end = pd.Timestamp(str(eval_end))
    s_start = pd.Timestamp(str(selection_start))
    out_rows: list[dict[str, Any]] = []
    holdout_dates = sorted(panel[(panel["date"] >= h_start) & (panel["date"] <= h_end)]["date"].drop_duplicates().tolist())

    for cur in tqdm(holdout_dates, desc="hybrid walk-forward", leave=False):
        train = panel[(panel["date"] >= s_start) & (panel["date"] < cur)].copy()
        test = panel[panel["date"] == cur].copy()
        if train.empty or test.empty:
            continue
        t0 = time.time()
        print(f"[hybrid] {pd.Timestamp(cur).date()} train_n={len(train)} val_n={len(test)}")
        train_aug, test_aug, feature_cols = _build_hybrid_design_matrices(
            train,
            test,
            hall_judgments=hall_judgments,
            include_lag1_avg_games=include_lag1_avg_games,
        )
        p0 = _predict_binary_probabilities(train_aug[feature_cols], train_aug["is_ge_0"], test_aug[feature_cols], c=float(logreg_c), use_gpu=use_gpu, gpu_backend=gpu_backend)
        p100 = _predict_binary_probabilities(train_aug[feature_cols], train_aug["is_ge_100"], test_aug[feature_cols], c=float(logreg_c), use_gpu=use_gpu, gpu_backend=gpu_backend)
        p200 = _predict_binary_probabilities(train_aug[feature_cols], train_aug["is_ge_200"], test_aug[feature_cols], c=float(logreg_c), use_gpu=use_gpu, gpu_backend=gpu_backend)
        p300 = _predict_binary_probabilities(train_aug[feature_cols], train_aug["is_ge_300"], test_aug[feature_cols], c=float(logreg_c), use_gpu=use_gpu, gpu_backend=gpu_backend)
        elapsed = time.time() - t0
        if elapsed > 30.0:
            print(f"WARNING: hybrid day {pd.Timestamp(cur).date()} took {elapsed:.1f}s — possible hang")

        tmp = test.copy()
        tmp["p_ge_0"] = p0
        tmp["p_ge_100"] = p100
        tmp["p_ge_200"] = p200
        tmp["p_ge_300"] = p300
        for _, r in tmp.iterrows():
            store = str(r["store"])
            dd_raw = pd.to_numeric(r.get("dd", np.nan), errors="coerce")
            dd_now = int(dd_raw) if pd.notna(dd_raw) else -1
            out_rows.append(
                {
                    "date": pd.Timestamp(cur).strftime("%Y-%m-%d"),
                    "store": store,
                    "signal_class": str(hall_judgments.get(store, "SIGNAL_DETECTED")).upper(),
                    "dd": dd_now,
                    "is_dd_topk_train": int(pd.to_numeric(r.get("is_dd_topk_train", 0), errors="coerce")),
                    "base_rate_ge_0_train": float(pd.to_numeric(train["is_ge_0"], errors="coerce").mean()),
                    "base_rate_ge_100_train": float(pd.to_numeric(train["is_ge_100"], errors="coerce").mean()),
                    "p_ge_0": float(r["p_ge_0"]),
                    "p_ge_100": float(r["p_ge_100"]),
                    "p_ge_200": float(r["p_ge_200"]),
                    "p_ge_300": float(r["p_ge_300"]),
                    "actual_avg_diff_per_machine": float(r["avg_diff_per_machine"]),
                    "actual_hit_ge_0": int(r["is_ge_0"]),
                    "actual_hit_ge_100": int(r["is_ge_100"]),
                    "actual_hit_ge_200": int(r["is_ge_200"]),
                    "actual_hit_ge_300": int(r["is_ge_300"]),
                }
            )

    return pd.DataFrame(out_rows)


def _optimize_hybrid_c_and_policy(
    *,
    pred_tables_by_c: dict[float, pd.DataFrame],
    edge_grid: list[float],
    weight_grid: list[tuple[float, float, float]],
    no_signal_stores: set[str],
    no_signal_penalty_grid: list[float],
    dd_topk_bonus_grid: list[float],
    strong_zorome_bonus_grid: list[float],
    share_cap_grid: list[float],
    share_penalty_scale: float,
    objective: str,
    policy_grid: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], pd.DataFrame]:
    if not pred_tables_by_c:
        return {
            "logreg_c": 1.0,
            "edge": 0.08,
            "weights": (1.0, 1.0, 1.0),
            "no_signal_penalty": 0.0,
            "dd_topk_bonus": 0.0,
            "strong_zorome_bonus": 0.0,
            "share_cap": 0.6,
            "share_penalty_scale": float(share_penalty_scale),
        }, pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for logreg_c in tqdm(sorted(pred_tables_by_c.keys()), desc="hybrid C grid", leave=False):
        t0 = time.time()
        pred_df_tune = pred_tables_by_c.get(float(logreg_c), pd.DataFrame())
        if pred_df_tune.empty:
            continue
        best_policy, policy_table = _optimize_allhall_policy(
            pred_df_tune=pred_df_tune,
            edge_grid=edge_grid,
            weight_grid=weight_grid,
            no_signal_stores=no_signal_stores,
            no_signal_penalty_grid=no_signal_penalty_grid,
            dd_topk_bonus_grid=dd_topk_bonus_grid,
            strong_zorome_bonus_grid=strong_zorome_bonus_grid,
            share_cap_grid=share_cap_grid,
            share_penalty_scale=share_penalty_scale,
            objective=objective,
            policy_grid=policy_grid,
        )
        if policy_table.empty:
            continue
        best_row = policy_table.iloc[0].to_dict()
        rows.append(
            {
                "logreg_c": float(logreg_c),
                "edge": float(best_row["edge"]),
                "w100": float(best_row["w100"]),
                "w200": float(best_row["w200"]),
                "w300": float(best_row["w300"]),
                "no_signal_penalty": float(best_row["no_signal_penalty"]),
                "dd_topk_bonus": float(best_row["dd_topk_bonus"]),
                "strong_zorome_bonus": float(best_row["strong_zorome_bonus"]),
                "share_cap": float(best_row["share_cap"]),
                "share_penalty_scale": float(best_row["share_penalty_scale"]),
                "max_chosen_store_share": float(best_row["max_chosen_store_share"]),
                "n_days": int(best_row["n_days"]),
                "chosen_avg_diff_mean": float(best_row["chosen_avg_diff_mean"]),
                "chosen_hit_ge_100_rate": float(best_row["chosen_hit_ge_100_rate"]),
                "chosen_hit_ge_200_rate": float(best_row["chosen_hit_ge_200_rate"]),
                "chosen_hit_ge_300_rate": float(best_row["chosen_hit_ge_300_rate"]),
                "top1_hit_rate": float(best_row["top1_hit_rate"]),
                "top2_inclusion_rate": float(best_row["top2_inclusion_rate"]),
                "spearman_daily_mean": float(best_row["spearman_daily_mean"]),
                "regret_mean": float(best_row["regret_mean"]),
                "regret_sum": float(best_row["regret_sum"]),
                "avg_diff_gap_chosen_minus_oracle": float(best_row["avg_diff_gap_chosen_minus_oracle"]),
            }
        )
        elapsed = time.time() - t0
        if elapsed > 30.0:
            print(f"WARNING: hybrid C={logreg_c} took {elapsed:.1f}s - possible hang")

    table = pd.DataFrame(rows)
    if table.empty:
        return {
            "logreg_c": 1.0,
            "edge": 0.08,
            "weights": (1.0, 1.0, 1.0),
            "no_signal_penalty": 0.0,
            "dd_topk_bonus": 0.0,
            "strong_zorome_bonus": 0.0,
            "share_cap": 0.6,
            "share_penalty_scale": float(share_penalty_scale),
        }, table

    if str(objective).lower() == "regret":
        table = table.sort_values(
            [
                "regret_mean",
                "chosen_hit_ge_100_rate",
                "chosen_avg_diff_mean",
                "top1_hit_rate",
                "spearman_daily_mean",
            ],
            ascending=[True, False, False, False, False],
        ).reset_index(drop=True)
    else:
        table = table.sort_values(
            [
                "chosen_avg_diff_mean",
                "chosen_hit_ge_200_rate",
                "chosen_hit_ge_100_rate",
                "regret_mean",
                "top1_hit_rate",
            ],
            ascending=[False, False, False, True, False],
        ).reset_index(drop=True)

    best = table.iloc[0]
    return {
        "logreg_c": float(best["logreg_c"]),
        "edge": float(best["edge"]),
        "weights": (float(best["w100"]), float(best["w200"]), float(best["w300"])),
        "no_signal_penalty": float(best["no_signal_penalty"]),
        "dd_topk_bonus": float(best["dd_topk_bonus"]),
        "strong_zorome_bonus": float(best["strong_zorome_bonus"]),
        "share_cap": float(best["share_cap"]),
        "share_penalty_scale": float(best["share_penalty_scale"]),
    }, table


def _apply_allhall_policy(
    *,
    pred_df: pd.DataFrame,
    ml_min_edge: float,
    weights: tuple[float, float, float],
    no_signal_stores: set[str],
    no_signal_penalty: float,
    dd_topk_bonus: float,
    strong_zorome_bonus: float,
    share_cap: float,
    share_penalty_scale: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if pred_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    rows: list[dict[str, Any]] = []
    chosen_counts: dict[str, int] = {}
    day_index = 0
    for d, g in pred_df.groupby("date", sort=True):
        day_index += 1
        tmp = g.copy()
        p0 = pd.to_numeric(tmp["p_ge_0"], errors="coerce").to_numpy() if "p_ge_0" in tmp.columns else np.ones(len(tmp), dtype=float)
        tmp["expected_score"] = _expected_strength_score(
            pd.to_numeric(tmp["p_ge_100"], errors="coerce").to_numpy(),
            pd.to_numeric(tmp["p_ge_200"], errors="coerce").to_numpy(),
            pd.to_numeric(tmp["p_ge_300"], errors="coerce").to_numpy(),
            p0,
            weights=weights,
        )
        if no_signal_stores:
            tmp["is_no_signal_store"] = tmp["store"].astype(str).isin(no_signal_stores).astype(int)
        else:
            tmp["is_no_signal_store"] = 0
        tmp["expected_score_adjusted"] = pd.to_numeric(tmp["expected_score"], errors="coerce")
        if float(no_signal_penalty) != 0.0:
            tmp["expected_score_adjusted"] = (
                pd.to_numeric(tmp["expected_score_adjusted"], errors="coerce")
                - float(no_signal_penalty) * pd.to_numeric(tmp["is_no_signal_store"], errors="coerce").fillna(0.0)
            )
        if float(dd_topk_bonus) != 0.0 and "is_dd_topk_train" in tmp.columns:
            tmp["expected_score_adjusted"] = (
                pd.to_numeric(tmp["expected_score_adjusted"], errors="coerce")
                + float(dd_topk_bonus) * pd.to_numeric(tmp["is_dd_topk_train"], errors="coerce").fillna(0.0)
            )
        if float(strong_zorome_bonus) != 0.0 and "is_strong_zorome_day" in tmp.columns:
            tmp["expected_score_adjusted"] = (
                pd.to_numeric(tmp["expected_score_adjusted"], errors="coerce")
                + float(strong_zorome_bonus) * pd.to_numeric(tmp["is_strong_zorome_day"], errors="coerce").fillna(0.0)
            )
        base100 = float(pd.to_numeric(tmp["base_rate_ge_100_train"], errors="coerce").iloc[0])
        tmp["pred_play"] = (pd.to_numeric(tmp["p_ge_100"], errors="coerce") >= (base100 + float(ml_min_edge))).astype(int)
        tmp = tmp.sort_values(["expected_score_adjusted", "expected_score", "p_ge_100"], ascending=[False, False, False])
        pred_top2 = tmp.head(min(2, len(tmp)))["store"].astype(str).tolist()
        pred_top1_store = str(tmp.iloc[0]["store"])
        oracle = tmp.sort_values("actual_avg_diff_per_machine", ascending=False).iloc[0]
        oracle_store = str(oracle["store"])
        top1_hit = int(pred_top1_store == oracle_store)
        hit_at_2 = int(oracle_store in pred_top2)
        by_store = tmp.sort_values("store").copy()
        by_store["pred_rank_pos"] = by_store["expected_score_adjusted"].rank(method="min", ascending=False)
        by_store["actual_rank_pos"] = by_store["actual_avg_diff_per_machine"].rank(method="min", ascending=False)
        spearman_daily_rho = _safe_spearman_rank_corr(by_store["pred_rank_pos"], by_store["actual_rank_pos"])

        playable = tmp[tmp["pred_play"] == 1].copy()
        if playable.empty:
            candidates = tmp.sort_values(["expected_score_adjusted", "expected_score", "p_ge_100"], ascending=[False, False, False])
            chosen_by_play_rule = 0
        else:
            candidates = playable.sort_values(["expected_score_adjusted", "expected_score", "p_ge_100"], ascending=[False, False, False])
            chosen_by_play_rule = 1
        chosen = candidates.iloc[0]
        if not candidates.empty:
            picked = None
            for _, cand in candidates.iterrows():
                s = str(cand["store"])
                share_penalty = _projected_share_penalty(
                    chosen_counts=chosen_counts,
                    day_index=day_index,
                    candidate_store=s,
                    share_cap=float(share_cap),
                    share_penalty_scale=float(share_penalty_scale),
                )
                cand_score = float(pd.to_numeric(cand["expected_score_adjusted"], errors="coerce")) - share_penalty
                if picked is None:
                    picked = cand.copy()
                    picked["share_penalty"] = share_penalty
                    picked["final_score"] = cand_score
                    continue
                best_score = float(pd.to_numeric(picked["final_score"], errors="coerce"))
                if cand_score > best_score:
                    picked = cand.copy()
                    picked["share_penalty"] = share_penalty
                    picked["final_score"] = cand_score
            if picked is not None:
                chosen = picked

        actual = float(chosen["actual_avg_diff_per_machine"])
        chosen_store = str(chosen["store"])
        chosen_counts[chosen_store] = int(chosen_counts.get(chosen_store, 0) + 1)
        regret = float(max(0.0, float(oracle["actual_avg_diff_per_machine"]) - actual))
        rows.append(
            {
                "date": str(d),
                "n_halls_today": int(len(tmp)),
                "base_rate_ge_100_train": base100,
                "chosen_by_play_rule": chosen_by_play_rule,
                "chosen_store": chosen_store,
                "chosen_expected_score": float(chosen["expected_score"]),
                "chosen_expected_score_adjusted": float(chosen["expected_score_adjusted"]),
                "chosen_share_penalty": float(pd.to_numeric(chosen.get("share_penalty", 0.0), errors="coerce")),
                "chosen_final_score": float(pd.to_numeric(chosen.get("final_score", chosen["expected_score_adjusted"]), errors="coerce")),
                "chosen_p_ge_100": float(chosen["p_ge_100"]),
                "chosen_p_ge_200": float(chosen["p_ge_200"]),
                "chosen_p_ge_300": float(chosen["p_ge_300"]),
                "chosen_is_no_signal_store": int(pd.to_numeric(chosen.get("is_no_signal_store", 0), errors="coerce")),
                "chosen_is_dd_topk_train": int(pd.to_numeric(chosen.get("is_dd_topk_train", 0), errors="coerce")),
                "chosen_is_strong_zorome_day": int(pd.to_numeric(chosen.get("is_strong_zorome_day", 0), errors="coerce")),
                "chosen_actual_avg_diff_per_machine": actual,
                "chosen_hit_ge_0": int(actual >= 0.0),
                "chosen_hit_ge_100": int(actual >= 100.0),
                "chosen_hit_ge_200": int(actual >= 200.0),
                "chosen_hit_ge_300": int(actual >= 300.0),
                "oracle_store": oracle_store,
                "oracle_actual_avg_diff_per_machine": float(oracle["actual_avg_diff_per_machine"]),
                "pred_top1_store": pred_top1_store,
                "top1_hit": top1_hit,
                "oracle_hit_ge_100": int(float(oracle["actual_avg_diff_per_machine"]) >= 100.0),
                "oracle_hit_ge_200": int(float(oracle["actual_avg_diff_per_machine"]) >= 200.0),
                "oracle_hit_ge_300": int(float(oracle["actual_avg_diff_per_machine"]) >= 300.0),
                "hit_at_2_oracle_in_pred_top2": hit_at_2,
                "spearman_daily_rho": spearman_daily_rho,
                "regret_vs_oracle": regret,
                "pred_top2_stores": ",".join(pred_top2),
                "chosen_vs_oracle_diff_gap": float(actual - float(oracle["actual_avg_diff_per_machine"])),
                "policy_edge": float(ml_min_edge),
                "policy_w100": float(weights[0]),
                "policy_w200": float(weights[1]),
                "policy_w300": float(weights[2]),
                "policy_no_signal_penalty": float(no_signal_penalty),
                "policy_dd_topk_bonus": float(dd_topk_bonus),
                "policy_strong_zorome_bonus": float(strong_zorome_bonus),
                "policy_share_cap": float(share_cap),
                "policy_share_penalty_scale": float(share_penalty_scale),
            }
        )

    daily = pd.DataFrame(rows)
    if daily.empty:
        return daily, pd.DataFrame()
    summary = pd.DataFrame(
        [
            {
                "n_days": int(len(daily)),
                "play_rule_trigger_rate": float(pd.to_numeric(daily["chosen_by_play_rule"], errors="coerce").mean()),
                "chosen_hit_ge_0_rate": float(pd.to_numeric(daily["chosen_hit_ge_0"], errors="coerce").mean()),
                "chosen_hit_ge_100_rate": float(pd.to_numeric(daily["chosen_hit_ge_100"], errors="coerce").mean()),
                "chosen_hit_ge_200_rate": float(pd.to_numeric(daily["chosen_hit_ge_200"], errors="coerce").mean()),
                "chosen_hit_ge_300_rate": float(pd.to_numeric(daily["chosen_hit_ge_300"], errors="coerce").mean()),
                "chosen_avg_diff_mean": float(pd.to_numeric(daily["chosen_actual_avg_diff_per_machine"], errors="coerce").mean()),
                "top1_hit_rate": float(pd.to_numeric(daily["top1_hit"], errors="coerce").mean()),
                "top2_inclusion_rate": float(pd.to_numeric(daily["hit_at_2_oracle_in_pred_top2"], errors="coerce").mean()),
                "spearman_daily_mean": float(pd.to_numeric(daily["spearman_daily_rho"], errors="coerce").mean()),
                "regret_sum": float(pd.to_numeric(daily["regret_vs_oracle"], errors="coerce").sum()),
                "regret_mean": float(pd.to_numeric(daily["regret_vs_oracle"], errors="coerce").mean()),
                "oracle_avg_diff_mean": float(pd.to_numeric(daily["oracle_actual_avg_diff_per_machine"], errors="coerce").mean()),
                "avg_diff_gap_chosen_minus_oracle": float(pd.to_numeric(daily["chosen_vs_oracle_diff_gap"], errors="coerce").mean()),
                "hit_at_2_oracle_in_pred_top2_rate": float(pd.to_numeric(daily["hit_at_2_oracle_in_pred_top2"], errors="coerce").mean()),
                "policy_edge": float(ml_min_edge),
                "policy_w100": float(weights[0]),
                "policy_w200": float(weights[1]),
                "policy_w300": float(weights[2]),
                "policy_no_signal_penalty": float(no_signal_penalty),
                "policy_dd_topk_bonus": float(dd_topk_bonus),
                "policy_strong_zorome_bonus": float(strong_zorome_bonus),
                "policy_share_cap": float(share_cap),
                "policy_share_penalty_scale": float(share_penalty_scale),
            }
        ]
    )
    return daily, summary


def _optimize_allhall_policy(
    *,
    pred_df_tune: pd.DataFrame,
    edge_grid: list[float],
    weight_grid: list[tuple[float, float, float]],
    no_signal_stores: set[str],
    no_signal_penalty_grid: list[float],
    dd_topk_bonus_grid: list[float],
    strong_zorome_bonus_grid: list[float],
    share_cap_grid: list[float],
    share_penalty_scale: float,
    objective: str,
    policy_grid: list[dict[str, Any]] | None = None,
    use_gpu: bool = False,
) -> tuple[dict[str, Any], pd.DataFrame]:
    if pred_df_tune.empty:
        return {
            "edge": 0.08,
            "weights": (1.0, 1.0, 1.0),
            "no_signal_penalty": 0.0,
            "dd_topk_bonus": 0.0,
            "strong_zorome_bonus": 0.0,
            "share_cap": 0.6,
            "share_penalty_scale": float(share_penalty_scale),
        }, pd.DataFrame()

    rows: list[dict[str, Any]] = []
    combos = policy_grid
    if combos is None:
        combos = build_policy_grid(
            use_gpu=use_gpu,
            edge_grid=edge_grid,
            weight_grid=weight_grid,
            no_signal_penalty_grid=no_signal_penalty_grid,
            dd_topk_bonus_grid=dd_topk_bonus_grid,
            strong_zorome_bonus_grid=strong_zorome_bonus_grid,
            share_cap_grid=share_cap_grid,
        )
    for combo in tqdm(combos, desc="allhall policy grid", leave=False):
        edge = float(combo["edge"])
        w = tuple(combo["weights"])
        no_signal_penalty = float(combo["no_signal_penalty"])
        dd_topk_bonus = float(combo["dd_topk_bonus"])
        strong_zorome_bonus = float(combo["strong_zorome_bonus"])
        share_cap = float(combo["share_cap"])
        t0 = time.time()
        daily, summary = _apply_allhall_policy(
            pred_df=pred_df_tune,
            ml_min_edge=edge,
            weights=w,
            no_signal_stores=no_signal_stores,
            no_signal_penalty=no_signal_penalty,
            dd_topk_bonus=dd_topk_bonus,
            strong_zorome_bonus=strong_zorome_bonus,
            share_cap=share_cap,
            share_penalty_scale=float(share_penalty_scale),
        )
        if summary.empty:
            continue
        chosen_share = (
            daily["chosen_store"].astype(str).value_counts(normalize=True, dropna=False).max()
            if not daily.empty
            else 1.0
        )
        s = summary.iloc[0].to_dict()
        rows.append(
            {
                "edge": float(edge),
                "w100": float(w[0]),
                "w200": float(w[1]),
                "w300": float(w[2]),
                "no_signal_penalty": float(no_signal_penalty),
                "dd_topk_bonus": float(dd_topk_bonus),
                "strong_zorome_bonus": float(strong_zorome_bonus),
                "share_cap": float(share_cap),
                "share_penalty_scale": float(share_penalty_scale),
                "max_chosen_store_share": float(chosen_share),
                "n_days": int(s["n_days"]),
                "chosen_avg_diff_mean": float(s["chosen_avg_diff_mean"]),
                "chosen_hit_ge_100_rate": float(s["chosen_hit_ge_100_rate"]),
                "chosen_hit_ge_200_rate": float(s["chosen_hit_ge_200_rate"]),
                "chosen_hit_ge_300_rate": float(s["chosen_hit_ge_300_rate"]),
                "top1_hit_rate": float(s["top1_hit_rate"]),
                "top2_inclusion_rate": float(s["top2_inclusion_rate"]),
                "spearman_daily_mean": float(s["spearman_daily_mean"]),
                "regret_mean": float(s["regret_mean"]),
                "regret_sum": float(s["regret_sum"]),
                "hit_at_2_oracle_in_pred_top2_rate": float(s["hit_at_2_oracle_in_pred_top2_rate"]),
                "avg_diff_gap_chosen_minus_oracle": float(s["avg_diff_gap_chosen_minus_oracle"]),
            }
        )
        elapsed = time.time() - t0
        if elapsed > 30.0:
            print(f"WARNING: allhall policy combo edge={edge} weights={w} took {elapsed:.1f}s — possible hang")
    table = pd.DataFrame(rows)
    if table.empty:
        return {
            "edge": 0.08,
            "weights": (1.0, 1.0, 1.0),
            "no_signal_penalty": 0.0,
            "dd_topk_bonus": 0.0,
            "strong_zorome_bonus": 0.0,
            "share_cap": 0.6,
            "share_penalty_scale": float(share_penalty_scale),
        }, table
    if str(objective).lower() == "regret":
        table = table.sort_values(
            [
                "regret_mean",
                "chosen_hit_ge_100_rate",
                "chosen_avg_diff_mean",
                "top1_hit_rate",
                "spearman_daily_mean",
            ],
            ascending=[True, False, False, False, False],
        ).reset_index(drop=True)
    else:
        table = table.sort_values(
            [
                "chosen_avg_diff_mean",
                "chosen_hit_ge_200_rate",
                "chosen_hit_ge_100_rate",
                "regret_mean",
                "top1_hit_rate",
            ],
            ascending=[False, False, False, True, False],
        ).reset_index(drop=True)
    best = table.iloc[0]
    return {
        "edge": float(best["edge"]),
        "weights": (float(best["w100"]), float(best["w200"]), float(best["w300"])),
        "no_signal_penalty": float(best["no_signal_penalty"]),
        "dd_topk_bonus": float(best["dd_topk_bonus"]),
        "strong_zorome_bonus": float(best["strong_zorome_bonus"]),
        "share_cap": float(best["share_cap"]),
        "share_penalty_scale": float(best["share_penalty_scale"]),
    }, table


def _build_allhall_accuracy_audit(
    *,
    daily_df: pd.DataFrame,
    no_signal_stores: set[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if daily_df.empty:
        return pd.DataFrame(), pd.DataFrame()
    d = daily_df.copy()
    d["oracle_store_is_no_signal"] = d["oracle_store"].astype(str).isin(no_signal_stores).astype(int)
    d["chosen_store_is_no_signal"] = d["chosen_store"].astype(str).isin(no_signal_stores).astype(int)
    d["pred_top1_store_is_no_signal"] = d["pred_top1_store"].astype(str).isin(no_signal_stores).astype(int)
    overall = pd.DataFrame(
        [
            {
                "n_days": int(len(d)),
                "top1_hit_rate": float(pd.to_numeric(d["top1_hit"], errors="coerce").mean()),
                "top2_inclusion_rate": float(pd.to_numeric(d["hit_at_2_oracle_in_pred_top2"], errors="coerce").mean()),
                "spearman_daily_mean": float(pd.to_numeric(d["spearman_daily_rho"], errors="coerce").mean()),
                "regret_mean": float(pd.to_numeric(d["regret_vs_oracle"], errors="coerce").mean()),
                "regret_sum": float(pd.to_numeric(d["regret_vs_oracle"], errors="coerce").sum()),
                "chosen_avg_diff_mean": float(pd.to_numeric(d["chosen_actual_avg_diff_per_machine"], errors="coerce").mean()),
            }
        ]
    )
    by_class_rows: list[dict[str, Any]] = []
    for cls_name, mask in [
        ("oracle_signal_detected", d["oracle_store_is_no_signal"] == 0),
        ("oracle_no_signal", d["oracle_store_is_no_signal"] == 1),
        ("chosen_signal_detected", d["chosen_store_is_no_signal"] == 0),
        ("chosen_no_signal", d["chosen_store_is_no_signal"] == 1),
    ]:
        sub = d[mask].copy()
        if sub.empty:
            continue
        by_class_rows.append(
            {
                "class": cls_name,
                "n_days": int(len(sub)),
                "top1_hit_rate": float(pd.to_numeric(sub["top1_hit"], errors="coerce").mean()),
                "top2_inclusion_rate": float(pd.to_numeric(sub["hit_at_2_oracle_in_pred_top2"], errors="coerce").mean()),
                "spearman_daily_mean": float(pd.to_numeric(sub["spearman_daily_rho"], errors="coerce").mean()),
                "regret_mean": float(pd.to_numeric(sub["regret_vs_oracle"], errors="coerce").mean()),
                "regret_sum": float(pd.to_numeric(sub["regret_vs_oracle"], errors="coerce").sum()),
                "chosen_avg_diff_mean": float(pd.to_numeric(sub["chosen_actual_avg_diff_per_machine"], errors="coerce").mean()),
            }
        )
    return overall, pd.DataFrame(by_class_rows)


def _rolling_kamata7_trend_model(
    *,
    hall_df: pd.DataFrame,
    thresholds: list[int],
    selection_start: str,
    holdout_start: str,
    holdout_end: str,
    ml_min_edge: float,
    use_gpu: bool = False,
    gpu_backend: str = "cuda",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    feat = _add_timing_features(hall_df)
    feat = feat.sort_values("date").reset_index(drop=True)
    feature_cols = [
        "lag1_avg_diff",
        "lag2_avg_diff",
        "lag7_avg_diff",
        "ewm7_avg_diff",
        "ewm28_avg_diff",
        "trend_gap_7_28",
        "delta_lag1",
        "vol14_avg_diff",
        "roll7_games",
        "roll7_win_rate",
        "roll7_total_machines",
        "weekday",
        "dd",
        "is_any_event",
        "is_zorome_day",
        "is_strong_zorome_day",
        "is_day_7x",
        "is_day_1x",
        "weekday_sin",
        "weekday_cos",
        "dd_sin",
        "dd_cos",
    ]
    out_rows: list[dict[str, Any]] = []
    h_start = pd.Timestamp(str(holdout_start))
    h_end = pd.Timestamp(str(holdout_end))
    s_start = pd.Timestamp(str(selection_start))

    for cur in sorted(pd.to_datetime(feat["date"]).drop_duplicates().tolist()):
        cur = pd.Timestamp(cur)
        if cur < h_start or cur > h_end:
            continue
        train = feat[(feat["date"] >= s_start) & (feat["date"] < cur)].copy()
        day = feat[feat["date"] == cur].copy()
        if train.empty or day.empty:
            continue
        for thr in thresholds:
            target_col = f"is_ge_{int(thr)}"
            if target_col not in train.columns or target_col not in day.columns:
                continue
            proba = _predict_binary_probabilities(
                train_x=train[feature_cols],
                train_y=train[target_col],
                test_x=day[feature_cols],
                use_gpu=use_gpu,
                gpu_backend=gpu_backend,
            )
            p = float(proba[0]) if len(proba) else 0.0
            y = int(pd.to_numeric(day[target_col], errors="coerce").fillna(0).iloc[0])
            base = float(pd.to_numeric(train[target_col], errors="coerce").mean()) if len(train) else 0.5
            pred_play = int(p >= (base + float(ml_min_edge)))
            out_rows.append(
                {
                    "date": cur.strftime("%Y-%m-%d"),
                    "threshold": int(thr),
                    "target_col": target_col,
                    "pred_proba": p,
                    "train_base_rate": base,
                    "pred_play": pred_play,
                    "actual_hit": y,
                    "pred_and_hit": int(pred_play == 1 and y == 1),
                }
            )
    daily = pd.DataFrame(out_rows)
    if daily.empty:
        return daily, pd.DataFrame()
    summary_rows: list[dict[str, Any]] = []
    for thr, g in daily.groupby("threshold", sort=True):
        play = g[g["pred_play"] == 1]
        base_rate = float(g["actual_hit"].mean())
        play_hit = float(play["actual_hit"].mean()) if len(play) else np.nan
        summary_rows.append(
            {
                "threshold": int(thr),
                "n_days": int(len(g)),
                "play_days": int(len(play)),
                "play_rate": float(len(play) / len(g)),
                "base_rate": base_rate,
                "hit_rate_on_play_days": play_hit,
                "lift_on_play_days": (play_hit - base_rate) if np.isfinite(play_hit) else np.nan,
            }
        )
    summary = pd.DataFrame(summary_rows).sort_values("threshold").reset_index(drop=True)
    return daily, summary


def main() -> int:
    args = build_parser().parse_args()
    out_root = Path(str(args.output_root))
    out_root.mkdir(parents=True, exist_ok=True)
    strength_root = Path(str(args.strength_root))
    thresholds = _parse_csv_ints(args.required_thresholds)

    store_meta = _load_store_meta(strength_root)
    best_df = _load_best_rules(strength_root)
    candidates = pick_practical_candidates(
        best_df=best_df,
        required_thresholds=thresholds,
        min_lift=float(args.min_lift),
        min_play_days=int(args.min_play_days),
    )

    candidate_csv = out_root / "candidate_stores_200_300.csv"
    candidates.to_csv(candidate_csv, index=False, encoding="utf-8-sig")

    signal_rows: list[dict[str, Any]] = []
    segtail_rows: list[dict[str, Any]] = []
    relative_rows: list[dict[str, Any]] = []

    stores_to_run = candidates["store"].astype(str).tolist() if not candidates.empty else []
    store_to_hall_df: dict[str, pd.DataFrame] = {}
    all_store_to_hall_df: dict[str, pd.DataFrame] = {}
    all_strength_thresholds = [0, 100, 200, 300]
    for _, r in tqdm(store_meta.iterrows(), total=len(store_meta), desc="load all halls", leave=False):
        store_name = str(r["store"])
        db_path = Path(str(r["db_path"]))
        try:
            hall_all = add_strength_targets(load_daily_hall(db_path), thresholds=all_strength_thresholds)
        except Exception:
            continue
        all_store_to_hall_df[store_name] = hall_all

    for store in tqdm(stores_to_run, desc="candidate halls", leave=False):
        db_row = store_meta[store_meta["store"].astype(str) == store]
        if db_row.empty:
            continue
        db_path = Path(str(db_row.iloc[0]["db_path"]))
        hall_raw = add_strength_targets(load_daily_hall(db_path), thresholds=thresholds)
        store_to_hall_df[str(store)] = hall_raw.copy()
        sel, ho = split_ranges(
            hall_raw,
            selection_start=str(args.selection_start),
            selection_end=str(args.selection_end),
            holdout_start=str(args.holdout_start),
            holdout_end=str(args.holdout_end),
        )
        rule_meta = build_rule_meta(sel, topk_dd=5, min_dd_days=6)
        machine = _load_machine_with_type(db_path)

        store_best = best_df[(best_df["store"].astype(str) == store) & (best_df["threshold"].isin(thresholds))].copy()
        for _, br in store_best.iterrows():
            thr = int(br["threshold"])
            rule = str(br["best_rule"])
            sel_days = set(sel[apply_rule(sel, rule, rule_meta) == 1]["date"].tolist())
            ho_mask = apply_rule(ho, rule, rule_meta) == 1
            ho_rule_df = ho[ho_mask].copy()
            ho_days = set(ho_rule_df["date"].tolist())

            for d in sorted(ho_days):
                one = ho_rule_df[ho_rule_df["date"] == d].iloc[0]
                signal_rows.append(
                    {
                        "date": pd.Timestamp(d).strftime("%Y-%m-%d"),
                        "store": store,
                        "threshold": int(thr),
                        "rule": rule,
                        "actual_avg_diff_per_machine": float(one["avg_diff_per_machine"]),
                        "target_hit": int(one[f"is_ge_{thr}"]),
                        "best_success_rate_lift_vs_all": float(br["best_success_rate_lift_vs_all"]),
                        "best_avg_diff_lift_vs_all": float(br["best_avg_diff_lift_vs_all"]),
                    }
                )

            segtail = _segment_tail_recommendation_for_rule_days(
                machine_df=machine,
                sel_days=sel_days,
                ho_days=ho_days,
            )
            segtail_rows.append(
                {
                    "store": store,
                    "threshold": int(thr),
                    "rule": rule,
                    "best_success_rate_lift_vs_all": float(br["best_success_rate_lift_vs_all"]),
                    "best_avg_diff_lift_vs_all": float(br["best_avg_diff_lift_vs_all"]),
                    **segtail,
                }
            )

    signal_df = pd.DataFrame(signal_rows)
    segtail_df = pd.DataFrame(segtail_rows)

    overlap_threshold_rows: list[dict[str, Any]] = []
    unique_rows: list[dict[str, Any]] = []
    if not signal_df.empty:
        for thr, g in signal_df.groupby("threshold", sort=True):
            d = compute_overlap_distribution(g[["date", "store"]].drop_duplicates())
            for _, r in d.iterrows():
                overlap_threshold_rows.append(
                    {
                        "scope": f"threshold_{int(thr)}",
                        "n_halls_signaled": int(r["n_halls_signaled"]),
                        "n_days": int(r["n_days"]),
                        "day_share": float(r["day_share"]),
                    }
                )
            counts = g.groupby("date", sort=True)["store"].nunique().reset_index(name="n_halls")
            g2 = g.merge(counts, on="date", how="left")
            only = g2[g2["n_halls"] == 1]
            for store, gs in g.groupby("store", sort=False):
                n_signal = int(gs["date"].nunique())
                n_unique = int(only[only["store"] == store]["date"].nunique())
                unique_rows.append(
                    {
                        "threshold": int(thr),
                        "store": str(store),
                        "signal_days": n_signal,
                        "unique_non_overlap_days": n_unique,
                        "unique_day_ratio": (float(n_unique / n_signal) if n_signal > 0 else np.nan),
                    }
                )
        d_all = compute_overlap_distribution(signal_df[["date", "store"]].drop_duplicates())
        for _, r in d_all.iterrows():
            overlap_threshold_rows.append(
                {
                    "scope": "union_all_thresholds",
                    "n_halls_signaled": int(r["n_halls_signaled"]),
                    "n_days": int(r["n_days"]),
                    "day_share": float(r["day_share"]),
                }
            )

        # Relative comparison: among halls signaled on same date+threshold, pick highest expected lift.
        for (date, thr), g in signal_df.groupby(["date", "threshold"], sort=True):
            if g.empty:
                continue
            g = g.copy().sort_values(["best_success_rate_lift_vs_all", "best_avg_diff_lift_vs_all"], ascending=[False, False])
            picked = g.iloc[0]
            oracle = g.sort_values("actual_avg_diff_per_machine", ascending=False).iloc[0]
            relative_rows.append(
                {
                    "date": str(date),
                    "threshold": int(thr),
                    "n_candidate_halls_today": int(g["store"].nunique()),
                    "picked_store": str(picked["store"]),
                    "picked_actual_avg_diff_per_machine": float(picked["actual_avg_diff_per_machine"]),
                    "picked_target_hit": int(picked["target_hit"]),
                    "oracle_store": str(oracle["store"]),
                    "oracle_actual_avg_diff_per_machine": float(oracle["actual_avg_diff_per_machine"]),
                    "oracle_target_hit": int(oracle["target_hit"]),
                    "picked_vs_oracle_diff_gap": float(picked["actual_avg_diff_per_machine"] - oracle["actual_avg_diff_per_machine"]),
                }
            )

    overlap_df = pd.DataFrame(overlap_threshold_rows)
    unique_df = pd.DataFrame(unique_rows)
    relative_df = pd.DataFrame(relative_rows)
    relative_summary_rows: list[dict[str, Any]] = []
    if not relative_df.empty:
        for thr, g in relative_df.groupby("threshold", sort=True):
            relative_summary_rows.append(
                {
                    "threshold": int(thr),
                    "n_days_with_at_least_one_signal": int(len(g)),
                    "picked_avg_diff_per_machine_mean": float(pd.to_numeric(g["picked_actual_avg_diff_per_machine"], errors="coerce").mean()),
                    "oracle_avg_diff_per_machine_mean": float(pd.to_numeric(g["oracle_actual_avg_diff_per_machine"], errors="coerce").mean()),
                    "picked_target_hit_rate": float(pd.to_numeric(g["picked_target_hit"], errors="coerce").mean()),
                    "oracle_target_hit_rate": float(pd.to_numeric(g["oracle_target_hit"], errors="coerce").mean()),
                    "avg_diff_gap_picked_minus_oracle": float(pd.to_numeric(g["picked_vs_oracle_diff_gap"], errors="coerce").mean()),
                }
            )
    relative_summary = pd.DataFrame(relative_summary_rows)

    panel_df = _build_multihall_panel(store_to_hall_df=store_to_hall_df)
    relative_ml_df, relative_ml_summary = _run_multihall_timing_ml(
        panel_df=panel_df,
        candidate_stores=stores_to_run,
        thresholds=thresholds,
        selection_start=str(args.selection_start),
        holdout_start=str(args.holdout_start),
        holdout_end=str(args.holdout_end),
        ml_min_edge=float(args.ml_min_edge),
        use_gpu=bool(args.use_gpu),
        gpu_backend=str(args.gpu_backend),
    )
    relative_rank_df, relative_rank_summary = _run_multihall_rank_model(
        panel_df=panel_df,
        candidate_stores=stores_to_run,
        selection_start=str(args.selection_start),
        holdout_start=str(args.holdout_start),
        holdout_end=str(args.holdout_end),
        use_gpu=bool(args.use_gpu),
        gpu_backend=str(args.gpu_backend),
    )
    panel_all_df = _build_multihall_panel(store_to_hall_df=all_store_to_hall_df)
    hall_judgments: dict[str, str] = {}
    if str(args.allhall_no_signal_judgment_csv).strip():
        hall_judgments = _load_hall_judgment_map(str(args.allhall_no_signal_judgment_csv).strip())
    no_signal_stores: set[str] = {
        str(store)
        for store, judgment in hall_judgments.items()
        if str(judgment).upper() == "NO_SIGNAL"
    }
    tune_start_ts = pd.Timestamp(str(args.selection_start)) + pd.Timedelta(days=max(1, int(args.allhall_opt_warmup_days)))
    pred_tune_df = _build_allhall_prediction_table(
        panel_df=panel_all_df,
        selection_start=str(args.selection_start),
        eval_start=tune_start_ts.strftime("%Y-%m-%d"),
        eval_end=str(args.selection_end),
        dd_topk_k=int(args.allhall_dd_topk_k),
        dd_topk_min_days=int(args.allhall_dd_topk_min_days),
        use_gpu=bool(args.use_gpu),
        gpu_backend=str(args.gpu_backend),
    )
    edge_grid = _parse_csv_floats(str(args.allhall_opt_edge_grid))
    weight_grid = _parse_weight_grid(str(args.allhall_opt_weight_grid))
    no_signal_penalty_grid = _parse_csv_floats(str(args.allhall_opt_no_signal_penalty_grid))
    dd_topk_bonus_grid = _parse_csv_floats(str(args.allhall_opt_dd_topk_bonus_grid))
    strong_zorome_bonus_grid = _parse_csv_floats(str(args.allhall_opt_strong_zorome_bonus_grid))
    share_cap_grid = _parse_csv_floats(str(args.allhall_opt_share_cap_grid))
    share_penalty_scale = float(args.allhall_opt_share_penalty_scale)
    policy_grid = build_policy_grid(
        use_gpu=bool(args.use_gpu),
        edge_grid=None if args.use_gpu else edge_grid,
        weight_grid=None if args.use_gpu else weight_grid,
        no_signal_penalty_grid=no_signal_penalty_grid,
        dd_topk_bonus_grid=dd_topk_bonus_grid,
        strong_zorome_bonus_grid=strong_zorome_bonus_grid,
        share_cap_grid=share_cap_grid,
    )
    edge_grid_used = sorted({float(combo["edge"]) for combo in policy_grid})
    weight_grid_used = sorted({tuple(combo["weights"]) for combo in policy_grid})
    best_policy, opt_table = _optimize_allhall_policy(
        pred_df_tune=pred_tune_df,
        edge_grid=edge_grid,
        weight_grid=weight_grid,
        no_signal_stores=no_signal_stores,
        no_signal_penalty_grid=no_signal_penalty_grid,
        dd_topk_bonus_grid=dd_topk_bonus_grid,
        strong_zorome_bonus_grid=strong_zorome_bonus_grid,
        objective=str(args.allhall_opt_objective),
        share_cap_grid=share_cap_grid,
        share_penalty_scale=share_penalty_scale,
        policy_grid=policy_grid,
        use_gpu=bool(args.use_gpu),
    )
    pred_holdout_df = _build_allhall_prediction_table(
        panel_df=panel_all_df,
        selection_start=str(args.selection_start),
        eval_start=str(args.holdout_start),
        eval_end=str(args.holdout_end),
        dd_topk_k=int(args.allhall_dd_topk_k),
        dd_topk_min_days=int(args.allhall_dd_topk_min_days),
        use_gpu=bool(args.use_gpu),
        gpu_backend=str(args.gpu_backend),
    )
    allhall_daily_df, allhall_summary = _apply_allhall_policy(
        pred_df=pred_holdout_df,
        ml_min_edge=float(best_policy["edge"]),
        weights=tuple(best_policy["weights"]),
        no_signal_stores=no_signal_stores,
        no_signal_penalty=float(best_policy["no_signal_penalty"]),
        dd_topk_bonus=float(best_policy["dd_topk_bonus"]),
        strong_zorome_bonus=float(best_policy["strong_zorome_bonus"]),
        share_cap=float(best_policy["share_cap"]),
        share_penalty_scale=float(best_policy["share_penalty_scale"]),
    )
    allhall_audit_overall, allhall_audit_by_class = _build_allhall_accuracy_audit(
        daily_df=allhall_daily_df,
        no_signal_stores=no_signal_stores,
    )

    per_hall_pred_tune_df = _build_hall_specific_prediction_table(
        panel_df=panel_all_df,
        hall_judgments=hall_judgments,
        selection_start=str(args.selection_start),
        eval_start=tune_start_ts.strftime("%Y-%m-%d"),
        eval_end=str(args.selection_end),
        dd_topk_k=int(args.allhall_dd_topk_k),
        dd_topk_min_days=int(args.allhall_dd_topk_min_days),
        use_gpu=bool(args.use_gpu),
        gpu_backend=str(args.gpu_backend),
    )
    per_hall_best_policy, per_hall_opt_table = _optimize_hall_specific_weights(
        pred_df_tune=per_hall_pred_tune_df,
        weight_grid=weight_grid_used,
        objective=str(args.allhall_opt_objective),
    )
    per_hall_pred_holdout_df = _build_hall_specific_prediction_table(
        panel_df=panel_all_df,
        hall_judgments=hall_judgments,
        selection_start=str(args.selection_start),
        eval_start=str(args.holdout_start),
        eval_end=str(args.holdout_end),
        dd_topk_k=int(args.allhall_dd_topk_k),
        dd_topk_min_days=int(args.allhall_dd_topk_min_days),
        use_gpu=bool(args.use_gpu),
        gpu_backend=str(args.gpu_backend),
    )
    per_hall_daily_df, per_hall_summary = _apply_hall_selection_policy(
        pred_df=per_hall_pred_holdout_df,
        weights=tuple(per_hall_best_policy["weights"]),
    )
    per_hall_audit_overall, per_hall_audit_by_class = _build_hall_accuracy_audit(
        daily_df=per_hall_daily_df,
        hall_judgments=hall_judgments,
    )

    hybrid_c_grid = _parse_csv_floats(str(args.hybrid_logreg_c_grid))
    if not hybrid_c_grid:
        hybrid_c_grid = [1.0]
    hybrid_pred_tune_tables_by_c: dict[float, pd.DataFrame] = {}
    for logreg_c in tqdm(hybrid_c_grid, desc="hybrid C prediction tables", leave=False):
        t0 = time.time()
        hybrid_pred_tune_tables_by_c[float(logreg_c)] = _build_hybrid_prediction_table(
            panel_df=panel_all_df,
            hall_judgments=hall_judgments,
            selection_start=str(args.selection_start),
            eval_start=tune_start_ts.strftime("%Y-%m-%d"),
            eval_end=str(args.selection_end),
            dd_topk_k=int(args.allhall_dd_topk_k),
            dd_topk_min_days=int(args.allhall_dd_topk_min_days),
            logreg_c=float(logreg_c),
            include_lag1_avg_games=bool(args.hybrid_use_lag1_games),
            use_gpu=bool(args.use_gpu),
            gpu_backend=str(args.gpu_backend),
        )
        elapsed = time.time() - t0
        if elapsed > 30.0:
            print(f"WARNING: hybrid tune table C={logreg_c} took {elapsed:.1f}s — possible hang")

    hybrid_best_policy, hybrid_opt_table = _optimize_hybrid_c_and_policy(
        pred_tables_by_c=hybrid_pred_tune_tables_by_c,
        edge_grid=edge_grid,
        weight_grid=weight_grid,
        no_signal_stores=no_signal_stores,
        no_signal_penalty_grid=no_signal_penalty_grid,
        dd_topk_bonus_grid=dd_topk_bonus_grid,
        strong_zorome_bonus_grid=strong_zorome_bonus_grid,
        share_cap_grid=share_cap_grid,
        share_penalty_scale=share_penalty_scale,
        objective=str(args.allhall_opt_objective),
        policy_grid=policy_grid,
    )
    hybrid_selected_c = float(hybrid_best_policy["logreg_c"])
    hybrid_pred_tune_df = hybrid_pred_tune_tables_by_c.get(hybrid_selected_c, pd.DataFrame())
    if hybrid_pred_tune_df.empty and hybrid_pred_tune_tables_by_c:
        nearest_c = min(hybrid_pred_tune_tables_by_c.keys(), key=lambda c: abs(float(c) - hybrid_selected_c))
        hybrid_pred_tune_df = hybrid_pred_tune_tables_by_c[nearest_c]
    if hybrid_pred_tune_df.empty and not hybrid_pred_tune_tables_by_c:
        hybrid_pred_tune_df = _build_hybrid_prediction_table(
            panel_df=panel_all_df,
            hall_judgments=hall_judgments,
            selection_start=str(args.selection_start),
            eval_start=tune_start_ts.strftime("%Y-%m-%d"),
            eval_end=str(args.selection_end),
            dd_topk_k=int(args.allhall_dd_topk_k),
            dd_topk_min_days=int(args.allhall_dd_topk_min_days),
            logreg_c=hybrid_selected_c,
            include_lag1_avg_games=bool(args.hybrid_use_lag1_games),
            use_gpu=bool(args.use_gpu),
            gpu_backend=str(args.gpu_backend),
        )
    hybrid_pred_holdout_df = _build_hybrid_prediction_table(
        panel_df=panel_all_df,
        hall_judgments=hall_judgments,
        selection_start=str(args.selection_start),
        eval_start=str(args.holdout_start),
        eval_end=str(args.holdout_end),
        dd_topk_k=int(args.allhall_dd_topk_k),
        dd_topk_min_days=int(args.allhall_dd_topk_min_days),
        logreg_c=hybrid_selected_c,
        include_lag1_avg_games=bool(args.hybrid_use_lag1_games),
        use_gpu=bool(args.use_gpu),
        gpu_backend=str(args.gpu_backend),
    )
    hybrid_daily_df, hybrid_summary = _apply_allhall_policy(
        pred_df=hybrid_pred_holdout_df,
        ml_min_edge=float(hybrid_best_policy["edge"]),
        weights=tuple(hybrid_best_policy["weights"]),
        no_signal_stores=no_signal_stores,
        no_signal_penalty=float(hybrid_best_policy["no_signal_penalty"]),
        dd_topk_bonus=float(hybrid_best_policy["dd_topk_bonus"]),
        strong_zorome_bonus=float(hybrid_best_policy["strong_zorome_bonus"]),
        share_cap=float(hybrid_best_policy["share_cap"]),
        share_penalty_scale=float(hybrid_best_policy["share_penalty_scale"]),
    )
    hybrid_audit_overall, hybrid_audit_by_class = _build_allhall_accuracy_audit(
        daily_df=hybrid_daily_df,
        no_signal_stores=no_signal_stores,
    )

    hall_strategy_comparison = _build_strategy_comparison_table(
        {
            "pooled": allhall_summary,
            "per_hall": per_hall_summary,
            "hybrid": hybrid_summary,
        }
    )

    pairwise_rows: list[dict[str, Any]] = []
    portfolio_rows: list[dict[str, Any]] = []
    if not signal_df.empty:
        for scope, g_scope in [("union_all_thresholds", signal_df)] + [
            (f"threshold_{int(t)}", signal_df[signal_df["threshold"] == t].copy())
            for t in sorted(signal_df["threshold"].drop_duplicates().tolist())
        ]:
            if g_scope.empty:
                continue
            store_days: dict[str, set[str]] = {
                str(s): set(gs["date"].astype(str).unique().tolist())
                for s, gs in g_scope.groupby("store", sort=False)
            }
            stores = sorted(store_days.keys())
            for a, b in itertools.combinations(stores, 2):
                da = store_days[a]
                db = store_days[b]
                inter = len(da & db)
                union = len(da | db)
                pairwise_rows.append(
                    {
                        "scope": scope,
                        "store_a": a,
                        "store_b": b,
                        "days_a": int(len(da)),
                        "days_b": int(len(db)),
                        "overlap_days": int(inter),
                        "union_days": int(union),
                        "jaccard": (float(inter / union) if union > 0 else np.nan),
                    }
                )
            for r in range(1, len(stores) + 1):
                for subset in itertools.combinations(stores, r):
                    sub = g_scope[g_scope["store"].isin(list(subset))].copy()
                    d = sub.groupby("date", sort=True)["store"].nunique().reset_index(name="n_halls")
                    union_days = int(len(d))
                    if union_days == 0:
                        continue
                    overlap_days = int((d["n_halls"] >= 2).sum())
                    unique_days = int((d["n_halls"] == 1).sum())
                    portfolio_rows.append(
                        {
                            "scope": scope,
                            "subset_size": int(r),
                            "stores": ",".join(subset),
                            "union_days": union_days,
                            "overlap_days": overlap_days,
                            "unique_days": unique_days,
                            "overlap_ratio": float(overlap_days / union_days),
                            "unique_ratio": float(unique_days / union_days),
                        }
                    )
    pairwise_df = pd.DataFrame(pairwise_rows)
    portfolio_df = pd.DataFrame(portfolio_rows)

    signal_csv = out_root / "candidate_signal_days.csv"
    segtail_csv = out_root / "candidate_segment_tail_recommendations.csv"
    overlap_csv = out_root / "candidate_overlap_distribution.csv"
    unique_csv = out_root / "candidate_unique_nonoverlap_days.csv"
    relative_csv = out_root / "candidate_relative_daily.csv"
    relative_summary_csv = out_root / "candidate_relative_summary.csv"
    relative_ml_csv = out_root / "candidate_relative_ml_daily.csv"
    relative_ml_summary_csv = out_root / "candidate_relative_ml_summary.csv"
    relative_rank_csv = out_root / "candidate_relative_rank_daily.csv"
    relative_rank_summary_csv = out_root / "candidate_relative_rank_summary.csv"
    allhall_daily_csv = out_root / "allhall_daily_decision_plan.csv"
    allhall_summary_csv = out_root / "allhall_daily_decision_summary.csv"
    allhall_opt_table_csv = out_root / "allhall_policy_optimization_table.csv"
    allhall_tune_pred_csv = out_root / "allhall_tune_prediction_table.csv"
    allhall_holdout_pred_csv = out_root / "allhall_holdout_prediction_table.csv"
    allhall_audit_overall_csv = out_root / "allhall_prediction_accuracy_audit.csv"
    allhall_audit_by_class_csv = out_root / "allhall_prediction_accuracy_by_signal_class.csv"
    per_hall_daily_csv = out_root / "per_hall_daily_decision_plan.csv"
    per_hall_summary_csv = out_root / "per_hall_daily_decision_summary.csv"
    per_hall_opt_table_csv = out_root / "per_hall_policy_optimization_table.csv"
    per_hall_tune_pred_csv = out_root / "per_hall_tune_prediction_table.csv"
    per_hall_holdout_pred_csv = out_root / "per_hall_holdout_prediction_table.csv"
    per_hall_audit_overall_csv = out_root / "per_hall_prediction_accuracy_audit.csv"
    per_hall_audit_by_class_csv = out_root / "per_hall_prediction_accuracy_by_signal_class.csv"
    hybrid_daily_csv = out_root / "hybrid_daily_decision_plan.csv"
    hybrid_summary_csv = out_root / "hybrid_daily_decision_summary.csv"
    hybrid_c_opt_table_csv = out_root / "hybrid_c_optimization_table.csv"
    hybrid_opt_table_csv = out_root / "hybrid_policy_optimization_table.csv"
    hybrid_tune_pred_csv = out_root / "hybrid_tune_prediction_table.csv"
    hybrid_holdout_pred_csv = out_root / "hybrid_holdout_prediction_table.csv"
    hybrid_audit_overall_csv = out_root / "hybrid_prediction_accuracy_audit.csv"
    hybrid_audit_by_class_csv = out_root / "hybrid_prediction_accuracy_by_signal_class.csv"
    hall_strategy_comparison_csv = out_root / "hall_strategy_comparison.csv"
    pairwise_csv = out_root / "candidate_pairwise_overlap.csv"
    portfolio_csv = out_root / "candidate_portfolio_coverage.csv"
    signal_df.to_csv(signal_csv, index=False, encoding="utf-8-sig")
    segtail_df.to_csv(segtail_csv, index=False, encoding="utf-8-sig")
    overlap_df.to_csv(overlap_csv, index=False, encoding="utf-8-sig")
    unique_df.to_csv(unique_csv, index=False, encoding="utf-8-sig")
    relative_df.to_csv(relative_csv, index=False, encoding="utf-8-sig")
    relative_summary.to_csv(relative_summary_csv, index=False, encoding="utf-8-sig")
    relative_ml_df.to_csv(relative_ml_csv, index=False, encoding="utf-8-sig")
    relative_ml_summary.to_csv(relative_ml_summary_csv, index=False, encoding="utf-8-sig")
    relative_rank_df.to_csv(relative_rank_csv, index=False, encoding="utf-8-sig")
    relative_rank_summary.to_csv(relative_rank_summary_csv, index=False, encoding="utf-8-sig")
    allhall_daily_df.to_csv(allhall_daily_csv, index=False, encoding="utf-8-sig")
    allhall_summary.to_csv(allhall_summary_csv, index=False, encoding="utf-8-sig")
    opt_table.to_csv(allhall_opt_table_csv, index=False, encoding="utf-8-sig")
    pred_tune_df.to_csv(allhall_tune_pred_csv, index=False, encoding="utf-8-sig")
    pred_holdout_df.to_csv(allhall_holdout_pred_csv, index=False, encoding="utf-8-sig")
    allhall_audit_overall.to_csv(allhall_audit_overall_csv, index=False, encoding="utf-8-sig")
    allhall_audit_by_class.to_csv(allhall_audit_by_class_csv, index=False, encoding="utf-8-sig")
    per_hall_daily_df.to_csv(per_hall_daily_csv, index=False, encoding="utf-8-sig")
    per_hall_summary.to_csv(per_hall_summary_csv, index=False, encoding="utf-8-sig")
    per_hall_opt_table.to_csv(per_hall_opt_table_csv, index=False, encoding="utf-8-sig")
    per_hall_pred_tune_df.to_csv(per_hall_tune_pred_csv, index=False, encoding="utf-8-sig")
    per_hall_pred_holdout_df.to_csv(per_hall_holdout_pred_csv, index=False, encoding="utf-8-sig")
    per_hall_audit_overall.to_csv(per_hall_audit_overall_csv, index=False, encoding="utf-8-sig")
    per_hall_audit_by_class.to_csv(per_hall_audit_by_class_csv, index=False, encoding="utf-8-sig")
    hybrid_daily_df.to_csv(hybrid_daily_csv, index=False, encoding="utf-8-sig")
    hybrid_summary.to_csv(hybrid_summary_csv, index=False, encoding="utf-8-sig")
    hybrid_opt_table.to_csv(hybrid_c_opt_table_csv, index=False, encoding="utf-8-sig")
    hybrid_opt_table.to_csv(hybrid_opt_table_csv, index=False, encoding="utf-8-sig")
    hybrid_pred_tune_df.to_csv(hybrid_tune_pred_csv, index=False, encoding="utf-8-sig")
    hybrid_pred_holdout_df.to_csv(hybrid_holdout_pred_csv, index=False, encoding="utf-8-sig")
    hybrid_audit_overall.to_csv(hybrid_audit_overall_csv, index=False, encoding="utf-8-sig")
    hybrid_audit_by_class.to_csv(hybrid_audit_by_class_csv, index=False, encoding="utf-8-sig")
    hall_strategy_comparison.to_csv(hall_strategy_comparison_csv, index=False, encoding="utf-8-sig")
    pairwise_df.to_csv(pairwise_csv, index=False, encoding="utf-8-sig")
    portfolio_df.to_csv(portfolio_csv, index=False, encoding="utf-8-sig")

    # Kamata7 rolling tracking
    db_dir = Path(str(args.db_dir))
    kamata7_db = _resolve_kamata7_db(db_dir, str(args.kamata7_db_glob))
    km_hall = add_strength_targets(load_daily_hall(kamata7_db), thresholds=[0, 100, 200, 300])
    rolling_daily, rolling_summary = _rolling_kamata7_rules(
        hall_df=km_hall,
        thresholds=[0, 100, 200, 300],
        selection_start=str(args.selection_start),
        holdout_start=str(args.holdout_start),
        holdout_end=str(args.holdout_end),
        window_days=int(args.rolling_window_days),
    )
    rolling_daily_csv = out_root / "kamata7_rolling_daily.csv"
    rolling_summary_csv = out_root / "kamata7_rolling_summary.csv"
    rolling_rule_monthly_csv = out_root / "kamata7_rolling_rule_monthly.csv"
    rolling_daily.to_csv(rolling_daily_csv, index=False, encoding="utf-8-sig")
    rolling_summary.to_csv(rolling_summary_csv, index=False, encoding="utf-8-sig")
    if not rolling_daily.empty:
        tmp = rolling_daily.copy()
        tmp["month"] = pd.to_datetime(tmp["date"]).dt.strftime("%Y-%m")
        monthly = (
            tmp.groupby(["threshold", "month", "chosen_rule"], sort=True)
            .size()
            .reset_index(name="n_days")
            .sort_values(["threshold", "month", "n_days"], ascending=[True, True, False])
        )
    else:
        monthly = pd.DataFrame()
    monthly.to_csv(rolling_rule_monthly_csv, index=False, encoding="utf-8-sig")

    trend_daily, trend_summary = _rolling_kamata7_trend_model(
        hall_df=km_hall,
        thresholds=[0, 100, 200, 300],
        selection_start=str(args.selection_start),
        holdout_start=str(args.holdout_start),
        holdout_end=str(args.holdout_end),
        ml_min_edge=float(args.ml_min_edge),
        use_gpu=bool(args.use_gpu),
        gpu_backend=str(args.gpu_backend),
    )
    trend_daily_csv = out_root / "kamata7_trend_daily.csv"
    trend_summary_csv = out_root / "kamata7_trend_summary.csv"
    trend_daily.to_csv(trend_daily_csv, index=False, encoding="utf-8-sig")
    trend_summary.to_csv(trend_summary_csv, index=False, encoding="utf-8-sig")

    summary = {
        "strength_root": str(strength_root),
        "required_thresholds": thresholds,
        "min_lift": float(args.min_lift),
        "min_play_days": int(args.min_play_days),
        "ml_min_edge": float(args.ml_min_edge),
        "use_gpu": bool(args.use_gpu),
        "gpu_backend": str(args.gpu_backend),
        "allhall_opt_warmup_days": int(args.allhall_opt_warmup_days),
        "allhall_opt_edge_grid": edge_grid_used,
        "allhall_opt_weight_grid": [list(x) for x in weight_grid_used],
        "allhall_opt_no_signal_penalty_grid": no_signal_penalty_grid,
        "allhall_opt_dd_topk_bonus_grid": dd_topk_bonus_grid,
        "allhall_opt_strong_zorome_bonus_grid": strong_zorome_bonus_grid,
        "allhall_opt_share_cap_grid": share_cap_grid,
        "allhall_opt_share_penalty_scale": share_penalty_scale,
        "allhall_opt_objective": str(args.allhall_opt_objective),
        "hybrid_logreg_c_grid": hybrid_c_grid,
        "hybrid_use_lag1_games": bool(args.hybrid_use_lag1_games),
        "allhall_dd_topk_k": int(args.allhall_dd_topk_k),
        "allhall_dd_topk_min_days": int(args.allhall_dd_topk_min_days),
        "allhall_no_signal_judgment_csv": str(args.allhall_no_signal_judgment_csv),
        "hall_judgments_loaded": int(len(hall_judgments)),
        "allhall_no_signal_stores_loaded": sorted(list(no_signal_stores)),
        "allhall_selected_policy": {
            "edge": float(best_policy["edge"]),
            "weights": [float(x) for x in best_policy["weights"]],
            "no_signal_penalty": float(best_policy["no_signal_penalty"]),
            "dd_topk_bonus": float(best_policy["dd_topk_bonus"]),
            "strong_zorome_bonus": float(best_policy["strong_zorome_bonus"]),
            "share_cap": float(best_policy["share_cap"]),
            "share_penalty_scale": float(best_policy["share_penalty_scale"]),
        },
        "per_hall_selected_policy": {
            "weights": [float(x) for x in per_hall_best_policy["weights"]],
        },
        "hybrid_selected_policy": {
            "logreg_c": float(hybrid_best_policy["logreg_c"]),
            "edge": float(hybrid_best_policy["edge"]),
            "weights": [float(x) for x in hybrid_best_policy["weights"]],
            "no_signal_penalty": float(hybrid_best_policy["no_signal_penalty"]),
            "dd_topk_bonus": float(hybrid_best_policy["dd_topk_bonus"]),
            "strong_zorome_bonus": float(hybrid_best_policy["strong_zorome_bonus"]),
            "share_cap": float(hybrid_best_policy["share_cap"]),
            "share_penalty_scale": float(hybrid_best_policy["share_penalty_scale"]),
        },
        "candidate_count": int(len(candidates)),
        "outputs": {
            "candidate_stores": str(candidate_csv),
            "candidate_signal_days": str(signal_csv),
            "candidate_segment_tail_recommendations": str(segtail_csv),
            "candidate_overlap_distribution": str(overlap_csv),
            "candidate_unique_nonoverlap_days": str(unique_csv),
            "candidate_relative_daily": str(relative_csv),
            "candidate_relative_summary": str(relative_summary_csv),
            "candidate_relative_ml_daily": str(relative_ml_csv),
            "candidate_relative_ml_summary": str(relative_ml_summary_csv),
            "candidate_relative_rank_daily": str(relative_rank_csv),
            "candidate_relative_rank_summary": str(relative_rank_summary_csv),
            "allhall_daily_decision_plan": str(allhall_daily_csv),
            "allhall_daily_decision_summary": str(allhall_summary_csv),
            "allhall_policy_optimization_table": str(allhall_opt_table_csv),
            "allhall_tune_prediction_table": str(allhall_tune_pred_csv),
            "allhall_holdout_prediction_table": str(allhall_holdout_pred_csv),
            "allhall_prediction_accuracy_audit": str(allhall_audit_overall_csv),
            "allhall_prediction_accuracy_by_signal_class": str(allhall_audit_by_class_csv),
            "per_hall_daily_decision_plan": str(per_hall_daily_csv),
            "per_hall_daily_decision_summary": str(per_hall_summary_csv),
            "per_hall_policy_optimization_table": str(per_hall_opt_table_csv),
            "per_hall_tune_prediction_table": str(per_hall_tune_pred_csv),
            "per_hall_holdout_prediction_table": str(per_hall_holdout_pred_csv),
            "per_hall_prediction_accuracy_audit": str(per_hall_audit_overall_csv),
            "per_hall_prediction_accuracy_by_signal_class": str(per_hall_audit_by_class_csv),
            "hybrid_daily_decision_plan": str(hybrid_daily_csv),
            "hybrid_daily_decision_summary": str(hybrid_summary_csv),
            "hybrid_c_optimization_table": str(hybrid_c_opt_table_csv),
            "hybrid_policy_optimization_table": str(hybrid_opt_table_csv),
            "hybrid_tune_prediction_table": str(hybrid_tune_pred_csv),
            "hybrid_holdout_prediction_table": str(hybrid_holdout_pred_csv),
            "hybrid_prediction_accuracy_audit": str(hybrid_audit_overall_csv),
            "hybrid_prediction_accuracy_by_signal_class": str(hybrid_audit_by_class_csv),
            "hall_strategy_comparison": str(hall_strategy_comparison_csv),
            "candidate_pairwise_overlap": str(pairwise_csv),
            "candidate_portfolio_coverage": str(portfolio_csv),
            "kamata7_rolling_daily": str(rolling_daily_csv),
            "kamata7_rolling_summary": str(rolling_summary_csv),
            "kamata7_rolling_rule_monthly": str(rolling_rule_monthly_csv),
            "kamata7_trend_daily": str(trend_daily_csv),
            "kamata7_trend_summary": str(trend_summary_csv),
        },
    }
    summary_path = out_root / "run_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[OK] saved: {candidate_csv}")
    print(f"[OK] saved: {signal_csv}")
    print(f"[OK] saved: {segtail_csv}")
    print(f"[OK] saved: {overlap_csv}")
    print(f"[OK] saved: {unique_csv}")
    print(f"[OK] saved: {relative_csv}")
    print(f"[OK] saved: {relative_summary_csv}")
    print(f"[OK] saved: {relative_ml_csv}")
    print(f"[OK] saved: {relative_ml_summary_csv}")
    print(f"[OK] saved: {relative_rank_csv}")
    print(f"[OK] saved: {relative_rank_summary_csv}")
    print(f"[OK] saved: {allhall_daily_csv}")
    print(f"[OK] saved: {allhall_summary_csv}")
    print(f"[OK] saved: {allhall_opt_table_csv}")
    print(f"[OK] saved: {allhall_tune_pred_csv}")
    print(f"[OK] saved: {allhall_holdout_pred_csv}")
    print(f"[OK] saved: {allhall_audit_overall_csv}")
    print(f"[OK] saved: {allhall_audit_by_class_csv}")
    print(f"[OK] saved: {per_hall_daily_csv}")
    print(f"[OK] saved: {per_hall_summary_csv}")
    print(f"[OK] saved: {per_hall_opt_table_csv}")
    print(f"[OK] saved: {per_hall_tune_pred_csv}")
    print(f"[OK] saved: {per_hall_holdout_pred_csv}")
    print(f"[OK] saved: {per_hall_audit_overall_csv}")
    print(f"[OK] saved: {per_hall_audit_by_class_csv}")
    print(f"[OK] saved: {hybrid_daily_csv}")
    print(f"[OK] saved: {hybrid_summary_csv}")
    print(f"[OK] saved: {hybrid_c_opt_table_csv}")
    print(f"[OK] saved: {hybrid_opt_table_csv}")
    print(f"[OK] saved: {hybrid_tune_pred_csv}")
    print(f"[OK] saved: {hybrid_holdout_pred_csv}")
    print(f"[OK] saved: {hybrid_audit_overall_csv}")
    print(f"[OK] saved: {hybrid_audit_by_class_csv}")
    print(f"[OK] saved: {hall_strategy_comparison_csv}")
    print(f"[OK] saved: {pairwise_csv}")
    print(f"[OK] saved: {portfolio_csv}")
    print(f"[OK] saved: {rolling_daily_csv}")
    print(f"[OK] saved: {rolling_summary_csv}")
    print(f"[OK] saved: {rolling_rule_monthly_csv}")
    print(f"[OK] saved: {trend_daily_csv}")
    print(f"[OK] saved: {trend_summary_csv}")
    print(f"[OK] saved: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
