from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.last_digit import tail_time_adaptive_ltr_poc_improved as improved
from ml.last_digit.model_zoo_benchmark import _clean_numeric_frame, _prepare_dataset, _select_split
from ml.last_digit.utils import configure_logging, resolve_db_path


def _normalize_split_name(name: str) -> str:
    if name == "split4":
        return "regime_3_fixed_split"
    return name


def recommend(
    ranker_scores: np.ndarray,
    lr_proba: np.ndarray,
    labels: np.ndarray,
    tails: np.ndarray,
    *,
    lr_threshold: float = 0.50,
) -> dict[str, Any] | None:
    if ranker_scores.size == 0 or lr_proba.size == 0:
        return None
    if float(np.max(lr_proba)) < float(lr_threshold):
        return None

    best_idx = int(np.argmax(ranker_scores))
    top2_idx = np.argsort(-ranker_scores)[: min(2, ranker_scores.size)]
    recommended_tail = str(tails[best_idx])
    confidence = float(lr_proba[best_idx])
    hit1 = int(labels[best_idx] > 0)
    hit2 = int(np.any(labels[top2_idx] > 0))
    return {
        "recommended_tail": recommended_tail,
        "confidence": confidence,
        "hit_at_1": hit1,
        "hit_at_2": hit2,
    }


def _aggregate_day_rows(day_df: pd.DataFrame) -> pd.DataFrame:
    work = day_df.copy()
    work["last_digit"] = work["last_digit"].astype(str)
    grouped = (
        work.groupby("last_digit", sort=False)
        .agg(
            ranker_score=("ranker_score", "mean"),
            lr_proba=("lr_proba", "mean"),
            label=("label", "max"),
        )
        .reset_index()
    )
    return grouped


def _evaluate_thresholds(valid_scored: pd.DataFrame, thresholds: list[float]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    dates = sorted(pd.to_datetime(valid_scored["date"]).unique())
    n_total = len(dates)

    for th in thresholds:
        n_abstain = 0
        n_reco = 0
        hit1_vals: list[float] = []
        hit2_vals: list[float] = []
        confidence_vals: list[float] = []

        for dt in dates:
            day_rows = valid_scored[pd.to_datetime(valid_scored["date"]) == dt].copy()
            day_agg = _aggregate_day_rows(day_rows)
            rec = recommend(
                ranker_scores=day_agg["ranker_score"].to_numpy(dtype=float),
                lr_proba=day_agg["lr_proba"].to_numpy(dtype=float),
                labels=day_agg["label"].to_numpy(dtype=int),
                tails=day_agg["last_digit"].to_numpy(),
                lr_threshold=float(th),
            )
            if rec is None:
                n_abstain += 1
                continue
            n_reco += 1
            hit1_vals.append(float(rec["hit_at_1"]))
            hit2_vals.append(float(rec["hit_at_2"]))
            confidence_vals.append(float(rec["confidence"]))

        out.append(
            {
                "threshold": float(th),
                "total_days": int(n_total),
                "abstain_days": int(n_abstain),
                "recommended_days": int(n_reco),
                "abstain_ratio": float(n_abstain / max(n_total, 1)),
                "hit_at_1_on_recommended_days": float(np.mean(hit1_vals)) if hit1_vals else 0.0,
                "hit_at_2_on_recommended_days": float(np.mean(hit2_vals)) if hit2_vals else 0.0,
                "mean_confidence_on_recommended_days": float(np.mean(confidence_vals)) if confidence_vals else 0.0,
            }
        )
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Combined Ranker x LogisticRegression abstain-rule evaluation")
    p.add_argument("--db-path", default="", help="Optional DB path")
    p.add_argument("--db-glob", default="*7.db")
    p.add_argument("--split-name", default="split4", help="split4 alias maps to regime_3_fixed_split")
    p.add_argument("--target", default="is_top_2")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--a-weight", type=float, default=0.4)
    p.add_argument("--non-a-weight", type=float, default=1.3)
    p.add_argument("--lr-thresholds", default="0.3,0.4,0.5,0.6")
    p.add_argument("--output", default="ml/experiments/combined_ranker_lr_results.json")
    p.add_argument("--log-level", default="INFO")
    return p


def main() -> int:
    args = build_parser().parse_args()
    configure_logging(args.log_level)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    split_name = _normalize_split_name(str(args.split_name))
    db_path = resolve_db_path(args.db_path, pattern=args.db_glob)

    data = _prepare_dataset(db_path=db_path, a_weight=float(args.a_weight), non_a_weight=float(args.non_a_weight))
    train, valid, split_cfg = _select_split(data, split_name)
    features = improved.get_numeric_features(data)
    features = [f for f in features if f != str(args.target)]

    x_train = _clean_numeric_frame(train[features])
    x_valid = _clean_numeric_frame(valid[features])
    y_train = train[str(args.target)].astype(int).to_numpy()
    y_valid = valid[str(args.target)].astype(int).to_numpy()

    ranker = improved.fit_ranker(
        x_train,
        y_train,
        train["date"],
        objective="rank:ndcg",
        random_state=int(args.seed) + 7,
        decay_lambda=None,
        model_params={"tree_method": "hist", "device": "cuda"},
    )
    ranker_scores = np.asarray(ranker.predict(x_valid), dtype=float)

    lr = Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=1500, random_state=int(args.seed))),
        ]
    )
    lr.fit(x_train, y_train)
    lr_prob = np.asarray(lr.predict_proba(x_valid)[:, 1], dtype=float)

    valid_scored = valid[["date", "last_digit"]].copy()
    valid_scored["label"] = y_valid.astype(int)
    valid_scored["ranker_score"] = ranker_scores
    valid_scored["lr_proba"] = lr_prob

    thresholds = [float(x.strip()) for x in str(args.lr_thresholds).split(",") if x.strip()]
    threshold_results = _evaluate_thresholds(valid_scored, thresholds)

    payload = {
        "config": vars(args),
        "resolved_split_name": split_name,
        "split_cfg": split_cfg,
        "train_rows": int(len(train)),
        "valid_rows": int(len(valid)),
        "threshold_results": threshold_results,
    }

    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved: {out_path}")
    for row in threshold_results:
        print(
            f"th={row['threshold']:.2f} abstain={row['abstain_days']}/{row['total_days']} "
            f"hit@1={row['hit_at_1_on_recommended_days']:.4f} "
            f"hit@2={row['hit_at_2_on_recommended_days']:.4f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
