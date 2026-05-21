from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import ndcg_score
from xgboost import XGBRanker

from ml.evaluators.metrics import calculate_hit_at_k
from ml.experiments.store_optimized_pipeline import (
    FORECAST_EXCLUDED_COLUMNS,
    META_COLUMNS,
    StoreOptimizedFeatureBuilder,
)


@dataclass
class FoldResult:
    hit_at_1: float
    hit_at_2: float
    hit_at_3: float
    ndcg_at_2: float
    ndcg_at_3: float
    abstain_coverage: float
    abstain_hit_at_1: float


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Time-adaptive LTR PoC for last_digit")
    p.add_argument("--db-path", required=True)
    p.add_argument("--output", default="db/experiments/tail_ltr_poc_result.json")
    p.add_argument("--n-splits", type=int, default=5)
    p.add_argument("--valid-days", type=int, default=21)
    p.add_argument("--decay-lambda-rank1", type=float, default=2.0)
    p.add_argument("--decay-lambda-topk", type=float, default=2.0)
    p.add_argument("--random-state", type=int, default=42)
    return p


def _add_top2_target(dataset: pd.DataFrame) -> pd.DataFrame:
    df = dataset.copy()
    rank = df.groupby("date", sort=False)["total_diff_coins"].rank(method="first", ascending=False)
    df["is_top_2"] = (rank <= 2).astype(int)
    return df


def _add_regime_and_cluster_features(dataset: pd.DataFrame) -> pd.DataFrame:
    df = dataset.copy()
    df = df.sort_values(["date", "entity_key"]).reset_index(drop=True)

    # Regime proxies (hall-level)
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
    for c in ("hall_avg_diff", "hall_std_diff", "hall_avg_eff", "hall_event_day"):
        daily[f"{c}_roll_7"] = daily[c].shift(1).rolling(7, min_periods=1).mean().fillna(0.0)
        daily[f"{c}_roll_30"] = daily[c].shift(1).rolling(30, min_periods=1).mean().fillna(0.0)
        daily[f"{c}_trend"] = daily[f"{c}_roll_7"] - daily[f"{c}_roll_30"]
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
            ]
        ],
        on="date",
        how="left",
    )
    df["regime_strength_index"] = (
        0.6 * df["hall_avg_eff_roll_7"] + 0.3 * np.tanh(df["hall_avg_diff_roll_7"] / 1000.0) + 0.1 * df["hall_event_day_roll_7"]
    )

    # Tail cluster features
    digit = pd.to_numeric(df["entity_key"], errors="coerce")
    df["tail_is_even"] = (digit % 2 == 0).astype(float).fillna(0.0)
    df["tail_low_group"] = (digit <= 4).astype(float).fillna(0.0)
    df["tail_is_zorome"] = (~digit.notna()).astype(float)
    return df


def _numeric_features(df: pd.DataFrame) -> list[str]:
    excluded = set(META_COLUMNS).union(FORECAST_EXCLUDED_COLUMNS).union({"is_top_2"})
    cols = []
    for c in df.columns:
        if c in excluded:
            continue
        if pd.api.types.is_numeric_dtype(df[c]):
            cols.append(c)
    return cols


def _date_folds(unique_dates: list[pd.Timestamp], n_splits: int, valid_days: int) -> list[tuple[list[pd.Timestamp], list[pd.Timestamp]]]:
    folds: list[tuple[list[pd.Timestamp], list[pd.Timestamp]]] = []
    total = len(unique_dates)
    for i in range(n_splits):
        valid_end = total - (n_splits - 1 - i) * valid_days
        valid_start = max(1, valid_end - valid_days)
        train_dates = unique_dates[:valid_start]
        valid_dates = unique_dates[valid_start:valid_end]
        if not train_dates or not valid_dates:
            continue
        folds.append((train_dates, valid_dates))
    return folds


def _group_sizes(frame: pd.DataFrame) -> list[int]:
    return frame.groupby("date", sort=True).size().tolist()


def _ndcg_at_k(y_true: np.ndarray, y_pred: np.ndarray, group_ids: np.ndarray, k: int) -> float:
    scores: list[float] = []
    for gid in np.unique(group_ids):
        m = group_ids == gid
        yt = y_true[m].astype(float)
        yp = y_pred[m].astype(float)
        if len(yt) == 0:
            continue
        scores.append(float(ndcg_score(yt.reshape(1, -1), yp.reshape(1, -1), k=min(k, len(yt)))))
    return float(np.mean(scores)) if scores else 0.0


def _sigmoid(x: np.ndarray, t: float) -> np.ndarray:
    z = np.clip(x / max(t, 1e-6), -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-z))


def _best_temperature(y: np.ndarray, raw: np.ndarray, groups: np.ndarray) -> float:
    candidates = [0.5, 0.8, 1.0, 1.3, 1.8, 2.5]
    best_t = 1.0
    best_score = -1.0
    for t in candidates:
        p = _sigmoid(raw, t)
        score = _ndcg_at_k(y, p, groups, k=2)
        if score > best_score:
            best_score = score
            best_t = t
    return float(best_t)


def _random_baseline(y_true: np.ndarray, group_ids: np.ndarray, rng: np.random.Generator) -> dict[str, float]:
    trials = 200
    rows = []
    for _ in range(trials):
        random_scores = rng.random(len(y_true))
        rows.append(
            {
                "hit_at_1": calculate_hit_at_k(y_true, random_scores, group_ids, k=1),
                "hit_at_2": calculate_hit_at_k(y_true, random_scores, group_ids, k=2),
                "hit_at_3": calculate_hit_at_k(y_true, random_scores, group_ids, k=3),
                "ndcg_at_2": _ndcg_at_k(y_true, random_scores, group_ids, k=2),
                "ndcg_at_3": _ndcg_at_k(y_true, random_scores, group_ids, k=3),
            }
        )
    return {k: float(np.mean([r[k] for r in rows])) for k in rows[0].keys()}


def _eval_with_abstain(y: np.ndarray, score: np.ndarray, dates: np.ndarray, abstain_quantile: float = 0.4) -> tuple[float, float]:
    tmp = pd.DataFrame({"y": y, "score": score, "date": dates})
    margins = (
        tmp.sort_values(["date", "score"], ascending=[True, False])
        .groupby("date", sort=False)["score"]
        .apply(lambda s: float(s.iloc[0] - s.iloc[1]) if len(s) >= 2 else 0.0)
    )
    th = float(np.quantile(margins.to_numpy(), abstain_quantile))
    keep_dates = margins[margins >= th].index
    kept = tmp[tmp["date"].isin(keep_dates)]
    if kept.empty:
        return 0.0, 0.0
    cov = float(len(keep_dates) / tmp["date"].nunique())
    h1 = calculate_hit_at_k(kept["y"].to_numpy(), kept["score"].to_numpy(), kept["date"].to_numpy(), 1)
    return cov, float(h1)


def _select_blend_and_abstain(
    *,
    target: str,
    y_cal: np.ndarray,
    cal_pair: np.ndarray,
    cal_ndcg: np.ndarray,
    cal_dates: np.ndarray,
) -> tuple[float, float]:
    def _score_fn(tgt: str, y: np.ndarray, pred: np.ndarray, d: np.ndarray, abst_h1: float) -> float:
        hit1 = calculate_hit_at_k(y, pred, d, k=1)
        hit3 = calculate_hit_at_k(y, pred, d, k=3)
        nd2 = _ndcg_at_k(y, pred, d, k=2)
        nd3 = _ndcg_at_k(y, pred, d, k=3)
        if tgt == "is_rank_1":
            return 0.8 * hit1 + 0.2 * abst_h1
        if tgt == "is_top_2":
            return 0.6 * nd2 + 0.4 * hit1
        return 0.6 * hit3 + 0.4 * nd3

    best_w = 0.5
    best_q = 0.4
    best_score = -1.0
    for w in (0.0, 0.25, 0.5, 0.75, 1.0):
        pred = w * cal_pair + (1.0 - w) * cal_ndcg
        for q in (0.2, 0.4, 0.6):
            _, abst_h1 = _eval_with_abstain(y_cal, pred, cal_dates, abstain_quantile=q)
            score = _score_fn(target, y_cal, pred, cal_dates, abst_h1)
            if score > best_score:
                best_score = score
                best_w = w
                best_q = q
    return float(best_w), float(best_q)


def _fit_ranker(
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    train_dates: pd.Series,
    *,
    objective: str,
    random_state: int,
    decay_lambda: float | None,
) -> XGBRanker:
    ranker = XGBRanker(
        objective=objective,
        n_estimators=150,
        learning_rate=0.05,
        max_depth=4,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=random_state,
    )
    sample_weight = None
    if decay_lambda is not None:
        max_date = train_dates.max()
        day_age = (max_date - train_dates.groupby(train_dates, sort=True).first().index).days.astype(float)
        max_day = max(float(day_age.max()), 1.0)
        sample_weight = np.exp(-decay_lambda * day_age / max_day).to_numpy()

    ranker.fit(
        X_train,
        y_train,
        group=train_dates.value_counts(sort=False).sort_index().tolist(),
        sample_weight=sample_weight,
    )
    return ranker


def _evaluate_mode(
    dataset: pd.DataFrame,
    *,
    target: str,
    features: list[str],
    n_splits: int,
    valid_days: int,
    random_state: int,
    decay_lambda: float | None,
) -> dict[str, Any]:
    unique_dates = sorted(pd.to_datetime(dataset["date"].unique()))
    folds = _date_folds(unique_dates, n_splits=n_splits, valid_days=valid_days)
    rng = np.random.default_rng(random_state)
    fold_results: list[FoldResult] = []
    random_fold_results: list[FoldResult] = []

    for train_dates, valid_dates in folds:
        train = dataset[dataset["date"].isin(train_dates)].sort_values(["date", "entity_key"]).reset_index(drop=True)
        valid = dataset[dataset["date"].isin(valid_dates)].sort_values(["date", "entity_key"]).reset_index(drop=True)

        # tiny calibration split from train tail
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

        # pairwise + listwise
        rank1_decay = decay_lambda
        if decay_lambda is not None:
            # allow fallback when decay hurts on calibration
            pair_tmp_none = _fit_ranker(
                X_fit,
                y_fit,
                fit_df["date"],
                objective="rank:pairwise",
                random_state=random_state,
                decay_lambda=None,
            )
            pair_tmp_decay = _fit_ranker(
                X_fit,
                y_fit,
                fit_df["date"],
                objective="rank:pairwise",
                random_state=random_state + 17,
                decay_lambda=decay_lambda,
            )
            cal_none = _sigmoid(pair_tmp_none.predict(X_cal), 1.0)
            cal_decay = _sigmoid(pair_tmp_decay.predict(X_cal), 1.0)
            cal_dates_np = cal_df["date"].to_numpy()
            if target == "is_rank_1":
                s_none = calculate_hit_at_k(y_cal, cal_none, cal_dates_np, 1)
                s_decay = calculate_hit_at_k(y_cal, cal_decay, cal_dates_np, 1)
            elif target == "is_top_2":
                s_none = _ndcg_at_k(y_cal, cal_none, cal_dates_np, 2)
                s_decay = _ndcg_at_k(y_cal, cal_decay, cal_dates_np, 2)
            else:
                s_none = calculate_hit_at_k(y_cal, cal_none, cal_dates_np, 3)
                s_decay = calculate_hit_at_k(y_cal, cal_decay, cal_dates_np, 3)
            rank1_decay = decay_lambda if s_decay >= s_none else None

        pair = _fit_ranker(
            X_fit,
            y_fit,
            fit_df["date"],
            objective="rank:pairwise",
            random_state=random_state,
            decay_lambda=rank1_decay,
        )
        ndcg = _fit_ranker(
            X_fit,
            y_fit,
            fit_df["date"],
            objective="rank:ndcg",
            random_state=random_state + 7,
            decay_lambda=rank1_decay if target == "is_rank_1" else decay_lambda,
        )

        raw_cal_pair = pair.predict(X_cal)
        raw_cal_ndcg = ndcg.predict(X_cal)
        raw_val_pair = pair.predict(X_valid)
        raw_val_ndcg = ndcg.predict(X_valid)

        # calibration
        t_pair = _best_temperature(y_cal, raw_cal_pair, cal_df["date"].to_numpy())
        t_ndcg = _best_temperature(y_cal, raw_cal_ndcg, cal_df["date"].to_numpy())
        cal_pair = _sigmoid(raw_val_pair, t_pair)
        cal_ndcg = _sigmoid(raw_val_ndcg, t_ndcg)

        # target-specific blend + abstain threshold selected on calibration split
        cal_pair_prob = _sigmoid(raw_cal_pair, t_pair)
        cal_ndcg_prob = _sigmoid(raw_cal_ndcg, t_ndcg)
        w_pair, abst_q = _select_blend_and_abstain(
            target=target,
            y_cal=y_cal,
            cal_pair=cal_pair_prob,
            cal_ndcg=cal_ndcg_prob,
            cal_dates=cal_df["date"].to_numpy(),
        )
        pred = w_pair * cal_pair + (1.0 - w_pair) * cal_ndcg

        cov, abst_h1 = _eval_with_abstain(y_valid, pred, valid["date"].to_numpy(), abstain_quantile=abst_q)
        fold_results.append(
            FoldResult(
                hit_at_1=calculate_hit_at_k(y_valid, pred, valid["date"].to_numpy(), k=1),
                hit_at_2=calculate_hit_at_k(y_valid, pred, valid["date"].to_numpy(), k=2),
                hit_at_3=calculate_hit_at_k(y_valid, pred, valid["date"].to_numpy(), k=3),
                ndcg_at_2=_ndcg_at_k(y_valid, pred, valid["date"].to_numpy(), k=2),
                ndcg_at_3=_ndcg_at_k(y_valid, pred, valid["date"].to_numpy(), k=3),
                abstain_coverage=cov,
                abstain_hit_at_1=abst_h1,
            )
        )

        rb = _random_baseline(y_valid, valid["date"].to_numpy(), rng)
        random_fold_results.append(
            FoldResult(
                hit_at_1=rb["hit_at_1"],
                hit_at_2=rb["hit_at_2"],
                hit_at_3=rb["hit_at_3"],
                ndcg_at_2=rb["ndcg_at_2"],
                ndcg_at_3=rb["ndcg_at_3"],
                abstain_coverage=0.0,
                abstain_hit_at_1=0.0,
            )
        )

    def _agg(rows: list[FoldResult]) -> dict[str, float]:
        return {
            "hit_at_1": float(np.mean([r.hit_at_1 for r in rows])) if rows else 0.0,
            "hit_at_2": float(np.mean([r.hit_at_2 for r in rows])) if rows else 0.0,
            "hit_at_3": float(np.mean([r.hit_at_3 for r in rows])) if rows else 0.0,
            "ndcg_at_2": float(np.mean([r.ndcg_at_2 for r in rows])) if rows else 0.0,
            "ndcg_at_3": float(np.mean([r.ndcg_at_3 for r in rows])) if rows else 0.0,
            "abstain_coverage": float(np.mean([r.abstain_coverage for r in rows])) if rows else 0.0,
            "abstain_hit_at_1": float(np.mean([r.abstain_hit_at_1 for r in rows])) if rows else 0.0,
        }

    metrics = _agg(fold_results)
    random_metrics = _agg(random_fold_results)
    lift = {k: (metrics[k] - random_metrics.get(k, 0.0)) for k in metrics.keys() if k in random_metrics}
    return {
        "target": target,
        "metrics": metrics,
        "random_baseline": random_metrics,
        "lift_vs_random": lift,
        "n_folds": len(fold_results),
    }


def main() -> int:
    args = _build_parser().parse_args()
    db_path = Path(args.db_path)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    builder = StoreOptimizedFeatureBuilder()
    dataset = builder.build_store_dataset(db_path=db_path, grouping="last_digit")
    dataset = _add_top2_target(dataset)
    dataset = _add_regime_and_cluster_features(dataset)
    features = _numeric_features(dataset)

    result: dict[str, Any] = {
        "db_path": str(db_path),
        "n_rows": int(len(dataset)),
        "n_features": int(len(features)),
        "features_sample": features[:30],
        "uniform": {},
        "time_decay": {},
        "config": {
            "n_splits": args.n_splits,
            "valid_days": args.valid_days,
            "decay_lambda_rank1": args.decay_lambda_rank1,
            "decay_lambda_topk": args.decay_lambda_topk,
            "random_state": args.random_state,
        },
    }

    for target in ("is_rank_1", "is_top_2", "is_top_3"):
        lam = args.decay_lambda_rank1 if target == "is_rank_1" else args.decay_lambda_topk
        result["uniform"][target] = _evaluate_mode(
            dataset,
            target=target,
            features=features,
            n_splits=args.n_splits,
            valid_days=args.valid_days,
            random_state=args.random_state,
            decay_lambda=None,
        )
        result["time_decay"][target] = _evaluate_mode(
            dataset,
            target=target,
            features=features,
            n_splits=args.n_splits,
            valid_days=args.valid_days,
            random_state=args.random_state,
            decay_lambda=lam,
        )

    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
