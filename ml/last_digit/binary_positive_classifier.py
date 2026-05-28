from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from xgboost import XGBClassifier


BINARY_FEATURE_CANDIDATES = [
    "lag1_total_diff_coins_focus",
    "lag7_total_diff_coins_focus",
    "lag14_total_diff_coins_focus",
    "roll7_total_diff_coins_focus",
    "roll14_total_diff_coins_focus",
    "roll28_total_diff_coins_focus",
    "lag1_total_diff_coins",
    "lag7_total_diff_coins",
    "lag14_total_diff_coins",
    "roll7_total_diff_coins",
    "roll14_total_diff_coins",
    "roll28_total_diff_coins",
    "total_diff_coins_deficit",
    "weekday",
    "weekday_sin",
    "weekday_cos",
    "is_wed",
    "prior_top2_rate",
    "days_since_last_top2",
    "weekday_prior_top2_rate",
    "prior_mean_diff",
]


def _resolve_binary_target(df: pd.DataFrame) -> pd.Series:
    if "total_diff_coins_focus" in df.columns:
        z = pd.to_numeric(df["total_diff_coins_focus"], errors="coerce").fillna(0.0)
        return (z > 0.0).astype(int)
    if "total_diff_coins" in df.columns:
        z = pd.to_numeric(df["total_diff_coins"], errors="coerce").fillna(0.0)
        return (z > 0.0).astype(int)
    return pd.Series(np.zeros(len(df), dtype=int), index=df.index)


def _resolve_binary_features(df: pd.DataFrame, requested: list[str] | None = None) -> list[str]:
    candidates = requested if requested is not None else BINARY_FEATURE_CANDIDATES
    return [c for c in candidates if c in df.columns]


def _subset_by_expert(df: pd.DataFrame, expert: str) -> pd.DataFrame:
    if "group_key" in df.columns:
        return df[df["group_key"].astype(str) == str(expert)].copy()
    return df.copy()


def _prepare_binary_matrix(
    df: pd.DataFrame,
    *,
    features: list[str],
    encoded_columns: list[str] | None = None,
) -> pd.DataFrame:
    x = df[features].copy()
    object_cols = []
    for col in features:
        if x[col].dtype.kind in ("O", "U", "S"):
            x[col] = x[col].fillna("__NA__").astype(str)
            object_cols.append(col)
        else:
            x[col] = pd.to_numeric(x[col], errors="coerce").fillna(0.0)
    x = pd.get_dummies(x, columns=object_cols, dummy_na=False)
    if encoded_columns is not None:
        x = x.reindex(columns=encoded_columns, fill_value=0.0)
    return x.astype(float)


BinaryModels = dict[str, XGBClassifier | None]
BinaryFeatureMap = dict[str, list[str]]


def fit_binary(
    train_df: pd.DataFrame,
    *,
    expert: str,
    models: BinaryModels | None = None,
    feature_map: BinaryFeatureMap | None = None,
    features: list[str] | None = None,
    c: float = 0.1,
    max_iter: int = 1000,
    random_state: int = 42,
) -> tuple[BinaryModels, BinaryFeatureMap]:
    _ = c
    _ = max_iter
    models = models or {}
    feature_map = feature_map or {}

    ds = _subset_by_expert(train_df, expert)
    use_features = _resolve_binary_features(ds, features)
    feature_map[str(expert)] = use_features
    if ds.empty or not use_features:
        models[str(expert)] = None
        return models, feature_map

    x = _prepare_binary_matrix(ds, features=use_features)
    y = _resolve_binary_target(ds).to_numpy(dtype=int)
    if len(np.unique(y)) < 2:
        models[str(expert)] = None
        return models, feature_map

    clf = XGBClassifier(
        n_estimators=100,
        max_depth=3,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        eval_metric="logloss",
        random_state=int(random_state),
        verbosity=0,
    )
    clf.fit(x, y)
    clf._binary_encoded_columns = list(x.columns)  # type: ignore[attr-defined]
    models[str(expert)] = clf
    return models, feature_map


def predict_binary(
    test_df: pd.DataFrame,
    *,
    expert: str,
    models: BinaryModels,
    feature_map: BinaryFeatureMap,
) -> np.ndarray:
    model = models.get(str(expert))
    features = feature_map.get(str(expert), [])
    if model is None or not features:
        return np.full(len(test_df), 0.5, dtype=float)

    ds = _subset_by_expert(test_df, expert)
    encoded_columns = getattr(model, "_binary_encoded_columns", None)
    x = _prepare_binary_matrix(ds, features=features, encoded_columns=encoded_columns)
    prob = model.predict_proba(x)[:, 1]
    return np.asarray(prob, dtype=float)
