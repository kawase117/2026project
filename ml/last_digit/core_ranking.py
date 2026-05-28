from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import ndcg_score
from xgboost import XGBRanker

from ml.evaluators.metrics import calculate_hit_at_k


def sigmoid(x: np.ndarray, temperature: float) -> np.ndarray:
    z = np.clip(x / max(temperature, 1e-6), -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-z))


def ndcg_at_k(y_true: np.ndarray, y_pred: np.ndarray, group_ids: np.ndarray, k: int) -> float:
    scores: list[float] = []
    for gid in np.unique(group_ids):
        m = group_ids == gid
        yt = y_true[m].astype(float)
        yp = y_pred[m].astype(float)
        if len(yt) > 0:
            scores.append(float(ndcg_score(yt.reshape(1, -1), yp.reshape(1, -1), k=min(k, len(yt)))))
    return float(np.mean(scores)) if scores else 0.0


def spearman_by_group(y_true: np.ndarray, y_pred: np.ndarray, group_ids: np.ndarray) -> float:
    scores: list[float] = []
    for gid in np.unique(group_ids):
        mask = group_ids == gid
        yt = pd.Series(y_true[mask], dtype=float)
        yp = pd.Series(y_pred[mask], dtype=float)
        if len(yt) < 2:
            continue
        corr = yt.corr(yp, method="spearman")
        if pd.notna(corr):
            scores.append(float(corr))
    return float(np.mean(scores)) if scores else 0.0


def find_best_temperature(
    y: np.ndarray,
    raw: np.ndarray,
    groups: np.ndarray,
    candidates: tuple[float, ...],
) -> float:
    best_t = 1.0
    best_score = -1.0
    for t in candidates:
        p = sigmoid(raw, t)
        score = ndcg_at_k(y, p, groups, k=2)
        if score > best_score:
            best_score = score
            best_t = t
    return float(best_t)


def evaluate_with_abstain(
    y: np.ndarray,
    score: np.ndarray,
    dates: np.ndarray,
    abstain_quantile: float = 0.4,
) -> tuple[float, float]:
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
    # Precondition: callers must align X_train/y_train rows with train_dates
    # (typically sorted by ["date", "entity_key"]). Group construction relies on this order.
    train_dates_ts = pd.to_datetime(train_dates)
    group_sizes = train_dates_ts.groupby(train_dates_ts, sort=False).size()
    if int(group_sizes.sum()) != len(X_train):
        raise ValueError(
            f"group size mismatch: sum(group_sizes)={int(group_sizes.sum())}, rows={len(X_train)}"
        )
    sample_weight = None
    if decay_lambda is not None:
        unique_dates = pd.Index(group_sizes.index)
        max_date = unique_dates.max()
        day_age = (max_date - unique_dates).days.astype(float)
        max_day = max(float(day_age.max()), 1.0) if len(day_age) else 1.0
        # XGBoost ranking expects one weight per query group when `group=` is supplied.
        sample_weight = np.exp(-decay_lambda * day_age / max_day).to_numpy(dtype=float)

    params: dict[str, Any] = {
        "objective": objective,
        "n_estimators": 150,
        "learning_rate": 0.05,
        "max_depth": 4,
        "subsample": 0.9,
        "colsample_bytree": 0.9,
        "random_state": random_state,
        "verbosity": 0,
    }
    if model_params:
        params.update(model_params)

    ranker = XGBRanker(**params)
    ranker.fit(
        X_train,
        y_train,
        group=group_sizes.tolist(),
        sample_weight=sample_weight,
    )
    return ranker
