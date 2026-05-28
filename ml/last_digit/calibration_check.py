from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.frozen import FrozenEstimator
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


def compute_ece(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    n = max(len(y_true), 1)
    for i in range(n_bins):
        lo = bins[i]
        hi = bins[i + 1]
        if i < n_bins - 1:
            mask = (y_prob >= lo) & (y_prob < hi)
        else:
            mask = (y_prob >= lo) & (y_prob <= hi)
        if not np.any(mask):
            continue
        acc = float(np.mean(y_true[mask]))
        conf = float(np.mean(y_prob[mask]))
        w = float(np.sum(mask) / n)
        ece += w * abs(acc - conf)
    return float(ece)


def _threshold_hit_rates(y_true: np.ndarray, y_prob: np.ndarray, thresholds: list[float]) -> list[dict[str, float]]:
    out: list[dict[str, float]] = []
    y_true = np.asarray(y_true, dtype=int)
    y_prob = np.asarray(y_prob, dtype=float)
    for th in thresholds:
        mask = y_prob >= float(th)
        n_sel = int(np.sum(mask))
        hit_rate = float(np.mean(y_true[mask])) if n_sel > 0 else 0.0
        out.append(
            {
                "threshold": float(th),
                "selected_rows": n_sel,
                "selected_ratio": float(n_sel / max(len(y_true), 1)),
                "hit_rate": hit_rate,
            }
        )
    return out


def _evaluate_probs(
    *,
    name: str,
    y_true: np.ndarray,
    y_prob: np.ndarray,
    n_bins: int,
    thresholds: list[float],
) -> dict[str, Any]:
    frac_pos, mean_pred = calibration_curve(y_true, y_prob, n_bins=n_bins, strategy="uniform")
    ece = compute_ece(y_true, y_prob, n_bins=n_bins)
    th_rates = _threshold_hit_rates(y_true, y_prob, thresholds)
    return {
        "model": name,
        "ece": float(ece),
        "calibration_curve": {
            "bin_centers": [float(x) for x in mean_pred.tolist()],
            "fraction_of_positives": [float(x) for x in frac_pos.tolist()],
        },
        "threshold_hit_rates": th_rates,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Calibration check for LR and CatBoost on last_digit split4/regime3")
    p.add_argument("--db-path", default="", help="Optional DB path")
    p.add_argument("--db-glob", default="*7.db")
    p.add_argument("--split-name", default="split4", help="split4 alias is mapped to regime_3_fixed_split")
    p.add_argument("--target", default="is_top_2")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--n-bins", type=int, default=10)
    p.add_argument("--thresholds", default="0.3,0.5,0.7")
    p.add_argument("--a-weight", type=float, default=0.4)
    p.add_argument("--non-a-weight", type=float, default=1.3)
    p.add_argument("--output", default="ml/experiments/calibration_check_results.json")
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

    lr = Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=1500, random_state=int(args.seed))),
        ]
    )
    lr.fit(x_train, y_train)
    lr_prob = np.asarray(lr.predict_proba(x_valid)[:, 1], dtype=float)

    cat = CatBoostClassifier(
        loss_function="Logloss",
        eval_metric="AUC",
        depth=6,
        learning_rate=0.05,
        iterations=350,
        random_seed=int(args.seed),
        verbose=False,
    )
    cat.fit(x_train, y_train)
    cat_prob_raw = np.asarray(cat.predict_proba(x_valid)[:, 1], dtype=float)

    # Prefit-style calibration on valid (sklearn>=1.8 uses FrozenEstimator instead of cv='prefit').
    cal = CalibratedClassifierCV(FrozenEstimator(cat), method="sigmoid", cv=None)
    cal.fit(x_valid, y_valid)
    cat_prob_cal = np.asarray(cal.predict_proba(x_valid)[:, 1], dtype=float)

    thresholds = [float(x.strip()) for x in str(args.thresholds).split(",") if x.strip()]
    results = {
        "config": vars(args),
        "resolved_split_name": split_name,
        "split_cfg": split_cfg,
        "train_rows": int(len(train)),
        "valid_rows": int(len(valid)),
        "models": [
            _evaluate_probs(
                name="logistic_regression",
                y_true=y_valid,
                y_prob=lr_prob,
                n_bins=int(args.n_bins),
                thresholds=thresholds,
            ),
            _evaluate_probs(
                name="catboost_classifier_raw",
                y_true=y_valid,
                y_prob=cat_prob_raw,
                n_bins=int(args.n_bins),
                thresholds=thresholds,
            ),
            _evaluate_probs(
                name="catboost_classifier_sigmoid_calibrated_prefit",
                y_true=y_valid,
                y_prob=cat_prob_cal,
                n_bins=int(args.n_bins),
                thresholds=thresholds,
            ),
        ],
    }

    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved: {out_path}")
    for model in results["models"]:
        print(f"[{model['model']}] ECE={model['ece']:.6f}")
        for row in model["threshold_hit_rates"]:
            print(
                f"  th={row['threshold']:.2f} selected={row['selected_rows']} "
                f"ratio={row['selected_ratio']:.4f} hit_rate={row['hit_rate']:.4f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
