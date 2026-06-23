"""Cheap smoke test: does adding hall_id as a feature to the pooled
machine_type model improve hit@3 / AUC for is_top_3?

Pools daily_machine_type_summary across all hall DBs, trains an xgb
classifier for `is_top_3` with and without a `hall_id_enc` feature,
and compares AUC + hit@3 on a fixed holdout window of recent dates.
"""

from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from .. import machine_type_common as common

TARGET = "is_top_3"
N_EVAL_DATES = 30


def build_pooled_frame() -> pd.DataFrame:
    frames = []
    for db_path_str in sorted(glob.glob("db/*.db")):
        db_path = Path(db_path_str)
        if db_path.stat().st_size < 100_000:
            continue
        hall_id = db_path.stem
        try:
            raw = common.load_daily_machine_type_summary(db_path)
            master = common.load_machine_master(db_path)
            segment_daily = common.load_machine_name_daily_segments(db_path)
            base = common.prepare_machine_type_base_frame(raw)
            base = common.attach_machine_master_flags(base, master)
            base = common.attach_daily_segments(base, segment_daily)
            ranked = common.add_shrunk_rank_targets(base, alpha=5.0)
        except Exception as exc:
            print(f"skip {hall_id}: {exc}")
            continue
        ranked["hall_id"] = hall_id
        frames.append(ranked)
    pooled = pd.concat(frames, ignore_index=True)
    pooled["hall_id_enc"] = pd.factorize(pooled["hall_id"])[0].astype(float)
    return pooled


def hit_at_3(day_df: pd.DataFrame, score_col: str) -> float | None:
    truth = day_df.loc[day_df[TARGET] == 1, "machine_name"]
    k = len(truth)
    if k == 0:
        return None
    pred_top = day_df.sort_values(score_col, ascending=False).head(k)["machine_name"]
    return len(set(truth) & set(pred_top)) / k


def run_variant_parts(train_df: pd.DataFrame, test_df: pd.DataFrame, with_hall: bool) -> dict:
    feature_columns = common.get_feature_columns(train_df)
    if not with_hall:
        feature_columns = [c for c in feature_columns if c != "hall_id_enc"]

    train_df = train_df.reset_index(drop=True)
    test_df = test_df.reset_index(drop=True)

    trained = common.train_target_model(
        train_df,
        target=TARGET,
        feature_columns=feature_columns,
        random_state=42,
        model_type="xgb",
        gpu_backend="cpu",
    )
    X = test_df[feature_columns].fillna(0.0).to_numpy(dtype=float)
    proba = common.predict_proba(trained.model, X)
    work = test_df.copy()
    work["score"] = proba

    importances = None
    if hasattr(trained.model, "feature_importances_"):
        importances = dict(zip(feature_columns, trained.model.feature_importances_.tolist()))

    hits = []
    for (_, _), g in work.groupby(["date", "hall_id"]):
        h = hit_at_3(g, "score")
        if h is not None:
            hits.append(h)

    y = work[TARGET].to_numpy(dtype=int)
    score = work["score"].to_numpy(dtype=float)
    auc = roc_auc_score(y, score) if len(np.unique(y)) > 1 else float("nan")
    return {
        "with_hall": with_hall,
        "n_features": len(feature_columns),
        "auc": auc,
        "hit_at_3_mean": float(np.mean(hits)),
        "n_hall_days": len(hits),
        "importances": importances,
        "_work": work,
    }


def main() -> int:
    pooled = build_pooled_frame()
    print(f"pooled rows: {len(pooled)}, halls: {pooled['hall_id'].nunique()}")
    unique_dates = sorted(pd.to_datetime(pooled["date"].unique()))

    n_splits = 3
    window = N_EVAL_DATES
    last_dates = unique_dates[-(n_splits * window):]
    split_points = [pd.Timestamp(last_dates[i * window]) for i in range(n_splits)]
    # bound each test window so splits don't overlap
    bounds = split_points + [pd.Timestamp(unique_dates[-1]) + pd.Timedelta(days=1)]

    for i, split_date in enumerate(split_points):
        end_date = bounds[i + 1]
        test_slice = pooled.loc[(pooled["date"] >= split_date) & (pooled["date"] < end_date)]
        n_dates = test_slice["date"].nunique()
        print(f"--- split {i}: test {split_date.date()} .. <{end_date.date()} ({n_dates} dates) ---")
        results = {}
        for with_hall in (False, True):
            train_part = pooled.loc[pooled["date"] < split_date]
            test_part = test_slice
            result = run_variant_parts(train_part, test_part, with_hall=with_hall)
            results[with_hall] = result
            printable = {k: v for k, v in result.items() if k not in ("importances", "_work")}
            print(printable)
            if with_hall and result["importances"]:
                ranked_imp = sorted(result["importances"].items(), key=lambda kv: kv[1], reverse=True)
                print("  feature importances:", ranked_imp)

        # Decompose AUC gain: is it a per-hall level shift or within-hall re-ranking?
        no_hall_work = results[False]["_work"][["date", "hall_id", "machine_name", "score"]].rename(columns={"score": "score_no_hall"})
        with_hall_work = results[True]["_work"][["date", "hall_id", "machine_name", "score"]].rename(columns={"score": "score_with_hall"})
        merged = no_hall_work.merge(with_hall_work, on=["date", "hall_id", "machine_name"])
        by_hall_level = merged.groupby("hall_id")[["score_no_hall", "score_with_hall"]].mean()
        by_hall_level["delta"] = by_hall_level["score_with_hall"] - by_hall_level["score_no_hall"]
        print("  per-hall mean score shift:")
        print(by_hall_level.round(4))

        # within-hall rank correlation between the two score variants
        from scipy.stats import spearmanr
        corrs = []
        for (_, _), g in merged.groupby(["date", "hall_id"]):
            if len(g) > 2:
                rho, _ = spearmanr(g["score_no_hall"], g["score_with_hall"])
                if not np.isnan(rho):
                    corrs.append(rho)
        print(f"  within-(date,hall) rank correlation (no_hall vs with_hall): mean={np.mean(corrs):.4f}, n={len(corrs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
