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
from catboost import CatBoostClassifier, CatBoostRanker
from lightgbm import LGBMClassifier, LGBMRanker
from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from ml.evaluators.metrics import calculate_hit_at_k
from ml.last_digit import tail_time_adaptive_ltr_poc_improved as improved
from ml.last_digit.core_ranking import ndcg_at_k
from ml.last_digit.tail_ltr_split_rule_wf import add_simple_features, aggregate_mode, build_base_rows
from ml.last_digit.utils import configure_logging, parse_csv_ints, parse_csv_strs, resolve_db_path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelSpec:
    name: str
    family: str
    kind: str  # ranker | classifier | bandit
    create_fn: Callable[[int], Any]


def _prepare_dataset(*, db_path: Path, a_weight: float, non_a_weight: float) -> pd.DataFrame:
    raw = build_base_rows(db_path=db_path, a_weight=float(a_weight), non_a_weight=float(non_a_weight))
    base = aggregate_mode(raw, mode="floor_atype4").sort_values(["entity_key", "date"]).reset_index(drop=True)
    data = add_simple_features(base)
    return data


def _select_split(data: pd.DataFrame, split_name: str) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]:
    split_cfg = improved.build_fixed_split_configs(data).get(split_name)
    if split_cfg is None:
        raise ValueError(f"Unknown split_name: {split_name}")
    train, valid = improved.split_dataset_by_date_ranges(
        data,
        train_start=split_cfg["train_start"],
        train_end=split_cfg["train_end"],
        valid_start=split_cfg["valid_start"],
        valid_end=split_cfg["valid_end"],
    )
    if train.empty or valid.empty:
        raise ValueError(f"Empty split for {split_name}: train={len(train)} valid={len(valid)}")
    return train, valid, split_cfg


def _clean_numeric_frame(df: pd.DataFrame) -> pd.DataFrame:
    cleaned = df.astype(float).copy()
    cleaned = cleaned.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return cleaned


def _rank_labels_for_top2(df: pd.DataFrame, target_col: str = "is_top_2") -> np.ndarray:
    return df[target_col].astype(int).to_numpy()


def _group_sizes_by_date(df: pd.DataFrame) -> list[int]:
    return (
        pd.to_datetime(df["date"])
        .groupby(pd.to_datetime(df["date"]), sort=False)
        .size()
        .astype(int)
        .tolist()
    )


def _precision_recall_f1_at_k(
    y_true: np.ndarray,
    y_score: np.ndarray,
    group_ids: np.ndarray,
    k: int,
) -> tuple[float, float, float]:
    tp = 0
    fp = 0
    fn = 0
    for gid in pd.Index(group_ids).drop_duplicates():
        idx = np.where(group_ids == gid)[0]
        if len(idx) == 0:
            continue
        local_true = y_true[idx]
        local_score = y_score[idx]
        topk = min(k, len(idx))
        pred_idx_local = np.argsort(-local_score)[:topk]
        pred_bin = np.zeros(len(idx), dtype=int)
        pred_bin[pred_idx_local] = 1
        true_bin = (local_true > 0).astype(int)
        tp += int(np.sum((pred_bin == 1) & (true_bin == 1)))
        fp += int(np.sum((pred_bin == 1) & (true_bin == 0)))
        fn += int(np.sum((pred_bin == 0) & (true_bin == 1)))
    precision = float(tp / max(tp + fp, 1))
    recall = float(tp / max(tp + fn, 1))
    f1 = float((2.0 * precision * recall) / max(precision + recall, 1e-12))
    return precision, recall, f1


def _score_metrics(y_valid: np.ndarray, pred: np.ndarray, valid_dates: np.ndarray) -> dict[str, float]:
    precision, recall, f1 = _precision_recall_f1_at_k(y_valid, pred, valid_dates, k=2)
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "hit_at_2": float(calculate_hit_at_k(y_valid, pred, valid_dates, k=2)),
        "hit_at_3": float(calculate_hit_at_k(y_valid, pred, valid_dates, k=3)),
        "ndcg_at_2": float(ndcg_at_k(y_valid, pred, valid_dates, k=2)),
        "ndcg_at_3": float(ndcg_at_k(y_valid, pred, valid_dates, k=3)),
    }


class LinUCBBandit:
    def __init__(self, alpha: float = 0.8, reg_lambda: float = 1.0):
        self.alpha = float(alpha)
        self.reg_lambda = float(reg_lambda)
        self.a_inv: dict[str, np.ndarray] = {}
        self.b_vec: dict[str, np.ndarray] = {}

    def _ensure_action(self, action: str, dim: int) -> None:
        if action in self.a_inv:
            return
        self.a_inv[action] = np.eye(dim, dtype=float) / self.reg_lambda
        self.b_vec[action] = np.zeros(dim, dtype=float)

    def fit(self, x_train: np.ndarray, y_train: np.ndarray, actions: np.ndarray) -> None:
        dim = int(x_train.shape[1])
        for x, y, a in zip(x_train, y_train, actions, strict=False):
            action = str(a)
            self._ensure_action(action, dim)
            a_inv = self.a_inv[action]
            b = self.b_vec[action]
            x_col = x.reshape(-1, 1)
            # Sherman-Morrison update for inverse covariance.
            denom = 1.0 + float((x_col.T @ a_inv @ x_col).item())
            if denom <= 0.0:
                denom = 1e-6
            a_inv_new = a_inv - (a_inv @ x_col @ x_col.T @ a_inv) / denom
            self.a_inv[action] = a_inv_new
            self.b_vec[action] = b + y * x

    def predict(self, x_valid: np.ndarray, actions: np.ndarray) -> np.ndarray:
        dim = int(x_valid.shape[1])
        scores = np.zeros(len(x_valid), dtype=float)
        for i, (x, a) in enumerate(zip(x_valid, actions, strict=False)):
            action = str(a)
            self._ensure_action(action, dim)
            a_inv = self.a_inv[action]
            theta = a_inv @ self.b_vec[action]
            exploit = float(theta @ x)
            explore = float(np.sqrt(max(x @ a_inv @ x, 0.0)))
            scores[i] = exploit + self.alpha * explore
        return scores


def _build_model_specs(include_deep: bool, include_rl: bool) -> list[ModelSpec]:
    specs: list[ModelSpec] = [
        ModelSpec(
            name="xgb_classifier",
            family="xgboost",
            kind="classifier",
            create_fn=lambda seed: XGBClassifier(
                n_estimators=250,
                learning_rate=0.05,
                max_depth=4,
                subsample=0.9,
                colsample_bytree=0.9,
                random_state=seed,
                tree_method="hist",
                device="cuda",
                verbosity=0,
            ),
        ),
        ModelSpec(
            name="catboost_classifier",
            family="catboost",
            kind="classifier",
            create_fn=lambda seed: CatBoostClassifier(
                loss_function="Logloss",
                eval_metric="AUC",
                depth=6,
                learning_rate=0.05,
                iterations=350,
                random_seed=seed,
                verbose=False,
            ),
        ),
        ModelSpec(
            name="lgbm_classifier",
            family="lightgbm",
            kind="classifier",
            create_fn=lambda seed: LGBMClassifier(
                n_estimators=300,
                learning_rate=0.05,
                num_leaves=63,
                subsample=0.9,
                colsample_bytree=0.9,
                random_state=seed,
                verbosity=-1,
            ),
        ),
        ModelSpec(
            name="random_forest",
            family="sklearn",
            kind="classifier",
            create_fn=lambda seed: RandomForestClassifier(
                n_estimators=450,
                max_depth=12,
                min_samples_leaf=2,
                n_jobs=-1,
                random_state=seed,
            ),
        ),
        ModelSpec(
            name="extra_trees",
            family="sklearn",
            kind="classifier",
            create_fn=lambda seed: ExtraTreesClassifier(
                n_estimators=550,
                max_depth=14,
                min_samples_leaf=2,
                n_jobs=-1,
                random_state=seed,
            ),
        ),
        ModelSpec(
            name="logistic_regression",
            family="sklearn",
            kind="classifier",
            create_fn=lambda seed: Pipeline(
                steps=[
                    ("scaler", StandardScaler()),
                    ("clf", LogisticRegression(max_iter=1200, random_state=seed)),
                ]
            ),
        ),
        ModelSpec(
            name="xgb_ranker_pairwise",
            family="xgboost",
            kind="ranker",
            create_fn=lambda seed: {
                "impl": "xgb",
                "objective": "rank:pairwise",
                "seed": seed,
            },
        ),
        ModelSpec(
            name="xgb_ranker_ndcg",
            family="xgboost",
            kind="ranker",
            create_fn=lambda seed: {
                "impl": "xgb",
                "objective": "rank:ndcg",
                "seed": seed,
            },
        ),
        ModelSpec(
            name="catboost_ranker_yeti",
            family="catboost",
            kind="ranker",
            create_fn=lambda seed: CatBoostRanker(
                loss_function="YetiRankPairwise",
                eval_metric="NDCG:top=3",
                depth=6,
                learning_rate=0.05,
                iterations=350,
                random_seed=seed,
                verbose=False,
            ),
        ),
        ModelSpec(
            name="catboost_ranker_pairlogit",
            family="catboost",
            kind="ranker",
            create_fn=lambda seed: CatBoostRanker(
                loss_function="PairLogitPairwise",
                eval_metric="NDCG:top=3",
                depth=6,
                learning_rate=0.05,
                iterations=350,
                random_seed=seed,
                verbose=False,
            ),
        ),
        ModelSpec(
            name="lgbm_ranker_lambdarank",
            family="lightgbm",
            kind="ranker",
            create_fn=lambda seed: LGBMRanker(
                objective="lambdarank",
                metric="ndcg",
                n_estimators=320,
                learning_rate=0.05,
                num_leaves=63,
                subsample=0.9,
                colsample_bytree=0.9,
                random_state=seed,
                verbosity=-1,
            ),
        ),
    ]

    if include_deep:
        specs.append(
            ModelSpec(
                name="mlp_classifier_deep",
                family="deep_sklearn",
                kind="classifier",
                create_fn=lambda seed: Pipeline(
                    steps=[
                        ("scaler", StandardScaler()),
                        (
                            "mlp",
                            MLPClassifier(
                                hidden_layer_sizes=(256, 128, 64),
                                activation="relu",
                                alpha=1e-4,
                                learning_rate_init=1e-3,
                                max_iter=300,
                                random_state=seed,
                            ),
                        ),
                    ]
                ),
            )
        )

    if include_rl:
        specs.append(
            ModelSpec(
                name="linucb_contextual_bandit",
                family="bandit",
                kind="bandit",
                create_fn=lambda seed: LinUCBBandit(alpha=0.9, reg_lambda=1.0),
            )
        )
    return specs


def _train_predict_ranker(
    spec: ModelSpec,
    spec_obj: Any,
    x_train: pd.DataFrame,
    y_train: np.ndarray,
    d_train: pd.Series,
    x_valid: pd.DataFrame,
) -> np.ndarray:
    if spec.name.startswith("xgb_ranker_"):
        model = improved.fit_ranker(
            x_train,
            y_train,
            d_train,
            objective=str(spec_obj["objective"]),
            random_state=int(spec_obj["seed"]),
            decay_lambda=None,
            model_params={"tree_method": "hist", "device": "cuda"},
        )
        return model.predict(x_valid)

    if spec.name.startswith("catboost_ranker_"):
        train_qid = pd.to_datetime(d_train).astype(str).to_numpy()
        spec_obj.fit(x_train, y_train, group_id=train_qid)
        return spec_obj.predict(x_valid)

    if spec.name == "lgbm_ranker_lambdarank":
        spec_obj.fit(x_train, y_train, group=_group_sizes_by_date(pd.DataFrame({"date": d_train})))
        return spec_obj.predict(x_valid)

    raise ValueError(f"Unsupported ranker spec: {spec.name}")


def _train_predict_classifier(spec_obj: Any, x_train: pd.DataFrame, y_train: np.ndarray, x_valid: pd.DataFrame) -> np.ndarray:
    spec_obj.fit(x_train, y_train)
    if hasattr(spec_obj, "predict_proba"):
        pred_proba = spec_obj.predict_proba(x_valid)
        if pred_proba.ndim == 2 and pred_proba.shape[1] >= 2:
            return pred_proba[:, 1]
        return pred_proba.reshape(-1)
    if hasattr(spec_obj, "decision_function"):
        return np.asarray(spec_obj.decision_function(x_valid), dtype=float)
    return np.asarray(spec_obj.predict(x_valid), dtype=float)


def _train_predict_bandit(
    spec_obj: LinUCBBandit,
    x_train: pd.DataFrame,
    y_train: np.ndarray,
    act_train: np.ndarray,
    x_valid: pd.DataFrame,
    act_valid: np.ndarray,
) -> np.ndarray:
    xtr = np.asarray(x_train, dtype=float)
    xva = np.asarray(x_valid, dtype=float)
    spec_obj.fit(xtr, y_train.astype(float), act_train.astype(str))
    return spec_obj.predict(xva, act_valid.astype(str))


def _evaluate_one(
    *,
    spec: ModelSpec,
    seed: int,
    train: pd.DataFrame,
    valid: pd.DataFrame,
    features: list[str],
    target: str,
) -> dict[str, Any]:
    start = time.perf_counter()
    x_train = _clean_numeric_frame(train[features])
    x_valid = _clean_numeric_frame(valid[features])
    y_train = _rank_labels_for_top2(train, target)
    y_valid = _rank_labels_for_top2(valid, target)
    d_train = pd.to_datetime(train["date"])
    d_valid = pd.to_datetime(valid["date"]).to_numpy()
    act_train = train["entity_key"].astype(str).to_numpy()
    act_valid = valid["entity_key"].astype(str).to_numpy()

    obj = spec.create_fn(seed)
    if spec.kind == "ranker":
        pred = _train_predict_ranker(spec, obj, x_train, y_train, d_train, x_valid)
    elif spec.kind == "classifier":
        pred = _train_predict_classifier(obj, x_train, y_train, x_valid)
    elif spec.kind == "bandit":
        pred = _train_predict_bandit(obj, x_train, y_train, act_train, x_valid, act_valid)
    else:
        raise ValueError(f"Unknown spec.kind: {spec.kind}")

    pred = np.asarray(pred, dtype=float)
    metrics = _score_metrics(y_valid, pred, d_valid)
    elapsed = float(time.perf_counter() - start)
    return {
        "model": spec.name,
        "family": spec.family,
        "kind": spec.kind,
        "seed": int(seed),
        "elapsed_sec": elapsed,
        **metrics,
    }


def _aggregate_results(df: pd.DataFrame) -> pd.DataFrame:
    metric_cols = ["precision", "recall", "f1", "hit_at_2", "hit_at_3", "ndcg_at_2", "ndcg_at_3", "elapsed_sec"]
    grouped = df.groupby(["model", "family", "kind"], as_index=False)[metric_cols].agg(["mean", "std"])
    grouped.columns = [
        "_".join(col).strip("_") if isinstance(col, tuple) else str(col)
        for col in grouped.columns.to_flat_index()
    ]
    grouped = grouped.rename(
        columns={
            "model_": "model",
            "family_": "family",
            "kind_": "kind",
        }
    )
    grouped = grouped.sort_values(["hit_at_2_mean", "ndcg_at_2_mean"], ascending=False).reset_index(drop=True)
    return grouped


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Model zoo benchmark for last-digit top2 prediction")
    p.add_argument("--output-prefix", default="ml/last_digit/reports/model_zoo_benchmark")
    p.add_argument("--db-path", default="", help="Optional DB path")
    p.add_argument("--db-glob", default="*7.db", help="DB glob used when --db-path is empty")
    p.add_argument("--split-name", default="regime_3_fixed_split")
    p.add_argument("--target", default="is_top_2")
    p.add_argument("--seeds", default="42,77,123,202,303,404,505,606")
    p.add_argument("--a-weight", type=float, default=0.4)
    p.add_argument("--non-a-weight", type=float, default=1.3)
    p.add_argument("--include-deep", action="store_true", help="Include MLP deep-style baseline")
    p.add_argument("--include-rl", action="store_true", help="Include LinUCB contextual bandit baseline")
    p.add_argument("--models", default="", help="Optional model filter (comma-separated names)")
    p.add_argument("--log-level", default="INFO")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.log_level)

    out_prefix = Path(args.output_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    db_path = resolve_db_path(args.db_path, pattern=args.db_glob)
    seeds = parse_csv_ints(args.seeds)

    logger.info("Preparing dataset from %s", db_path)
    data = _prepare_dataset(db_path=db_path, a_weight=float(args.a_weight), non_a_weight=float(args.non_a_weight))
    train, valid, split_cfg = _select_split(data, str(args.split_name))
    features = improved.get_numeric_features(data)
    features = [f for f in features if f != str(args.target)]
    logger.info(
        "Split=%s train_rows=%d valid_rows=%d train_days=%d valid_days=%d features=%d",
        args.split_name,
        len(train),
        len(valid),
        train["date"].nunique(),
        valid["date"].nunique(),
        len(features),
    )

    specs = _build_model_specs(include_deep=bool(args.include_deep), include_rl=bool(args.include_rl))
    if args.models:
        wanted = set(parse_csv_strs(args.models))
        specs = [s for s in specs if s.name in wanted]
        if not specs:
            raise ValueError(f"No models selected by --models={args.models}")

    rows: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for spec in specs:
        for seed in seeds:
            try:
                logger.info("Running model=%s seed=%d", spec.name, seed)
                row = _evaluate_one(
                    spec=spec,
                    seed=seed,
                    train=train,
                    valid=valid,
                    features=features,
                    target=str(args.target),
                )
                rows.append(row)
            except Exception as exc:
                logger.exception("Model failed: %s seed=%d", spec.name, seed)
                failed.append({"model": spec.name, "seed": str(seed), "error": f"{type(exc).__name__}: {exc}"})

    detailed = pd.DataFrame(rows)
    summary = _aggregate_results(detailed) if not detailed.empty else pd.DataFrame()

    detailed_csv = out_prefix.with_name(out_prefix.name + "_detailed.csv")
    summary_csv = out_prefix.with_name(out_prefix.name + "_summary.csv")
    result_json = out_prefix.with_suffix(".json")

    if not detailed.empty:
        detailed.to_csv(detailed_csv, index=False, encoding="utf-8-sig")
    if not summary.empty:
        summary.to_csv(summary_csv, index=False, encoding="utf-8-sig")

    payload = {
        "config": vars(args),
        "db_path": str(db_path),
        "split": split_cfg,
        "train_rows": int(len(train)),
        "valid_rows": int(len(valid)),
        "train_days": int(train["date"].nunique()),
        "valid_days": int(valid["date"].nunique()),
        "features_count": int(len(features)),
        "models_attempted": [s.name for s in specs],
        "completed_runs": int(len(rows)),
        "failed_runs": failed,
        "top_models_by_hit_at_2": (
            summary[["model", "hit_at_2_mean", "ndcg_at_2_mean", "f1_mean", "elapsed_sec_mean"]]
            .head(10)
            .to_dict(orient="records")
            if not summary.empty
            else []
        ),
        "artifacts": {
            "detailed_csv": str(detailed_csv) if detailed_csv.exists() else "",
            "summary_csv": str(summary_csv) if summary_csv.exists() else "",
        },
    }
    result_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info("Saved: %s", result_json)
    if detailed_csv.exists():
        logger.info("Saved: %s", detailed_csv)
    if summary_csv.exists():
        logger.info("Saved: %s", summary_csv)
    if not summary.empty:
        logger.info("\n%s", summary.head(10).to_string(index=False))
    if failed:
        logger.warning("Some model runs failed: %d", len(failed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
