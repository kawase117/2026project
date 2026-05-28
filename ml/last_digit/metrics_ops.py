from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ml.evaluators.metrics import calculate_f1, calculate_precision, calculate_recall


def score_top2_prediction_day(
    *,
    dt: pd.Timestamp,
    expert: str,
    rank_df: pd.DataFrame,
) -> dict[str, Any]:
    z = rank_df.copy()
    z["pred"] = pd.to_numeric(z["pred"], errors="coerce").fillna(0.0)
    z["actual_raw_diff"] = pd.to_numeric(z["actual_raw_diff"], errors="coerce").fillna(0.0)
    z["pred_rank"] = z["pred"].rank(method="first", ascending=False).astype(int)
    z["true_rank"] = z["actual_raw_diff"].rank(method="first", ascending=False).astype(int)
    z["y_pred"] = (z["pred_rank"] <= 2).astype(int)
    z["y_true"] = (z["true_rank"] <= 2).astype(int)
    y_true = z["y_true"].to_numpy(dtype=int)
    y_pred = z["y_pred"].to_numpy(dtype=int)
    pred_top2 = set(z.loc[z["pred_rank"] <= 2, "last_digit"].astype(str).tolist())
    pred_top3 = set(z.loc[z["pred_rank"] <= 3, "last_digit"].astype(str).tolist())
    true_top2 = set(z.loc[z["true_rank"] <= 2, "last_digit"].astype(str).tolist())
    span = float(z["pred"].max() - z["pred"].min()) if len(z) else 0.0
    return {
        "date": dt.strftime("%Y-%m-%d"),
        "month": dt.strftime("%Y-%m"),
        "weekday": dt.day_name(),
        "expert": str(expert),
        "precision": float(calculate_precision(y_true, y_pred)),
        "recall": float(calculate_recall(y_true, y_pred)),
        "f1": float(calculate_f1(y_true, y_pred)),
        "hit_at_2": float(len(pred_top2 & true_top2) > 0),
        "hit_at_3": float(len(pred_top3 & true_top2) > 0),
        "pred_span": span,
        "n_items": int(len(z)),
    }
