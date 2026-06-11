from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def span_band(span: float) -> str:
    x = float(span)
    if not np.isfinite(x):
        return "unknown"
    if x < 0.01:
        return "<0.01"
    if x < 0.10:
        return "0.01-0.1"
    if x < 0.30:
        return "0.1-0.3"
    return ">=0.3"


def with_audit_columns(topk_df: pd.DataFrame) -> pd.DataFrame:
    if topk_df.empty:
        return topk_df.copy()
    out = topk_df.copy()
    out["pred_span_top12"] = pd.to_numeric(out.get("pred_span_top12"), errors="coerce")
    out["top1_actual_raw_diff"] = pd.to_numeric(out.get("top1_actual_raw_diff"), errors="coerce")
    out["top2_actual_raw_diff"] = pd.to_numeric(out.get("top2_actual_raw_diff"), errors="coerce")
    out["operational_pick_actual_raw_diff"] = pd.to_numeric(
        out.get("operational_pick_actual_raw_diff"), errors="coerce"
    )
    out["hit_at_2"] = pd.to_numeric(out.get("hit_at_2"), errors="coerce")
    out["precision"] = pd.to_numeric(out.get("precision"), errors="coerce")
    out["exact_top1_hit"] = pd.to_numeric(out.get("exact_top1_hit"), errors="coerce")
    out["top1_minus_top2_actual"] = out["top1_actual_raw_diff"] - out["top2_actual_raw_diff"]
    out["span_band"] = out["pred_span_top12"].apply(span_band)
    return out


def summarize_holdout(topk_df: pd.DataFrame, daily_df: pd.DataFrame) -> dict[str, Any]:
    topk = with_audit_columns(topk_df)
    daily = daily_df.copy()
    if not daily.empty:
        for col in ("precision", "hit_at_2", "hit_at_3"):
            daily[col] = pd.to_numeric(daily.get(col), errors="coerce")

    overall: list[dict[str, Any]] = []
    if not topk.empty:
        for expert, g in topk.groupby("expert", sort=True):
            overall.append(
                {
                    "expert": str(expert),
                    "n_days": int(g["date"].nunique()) if "date" in g.columns else int(len(g)),
                    "hit_at_2_mean": float(g["hit_at_2"].mean()),
                    "precision_mean": float(g["precision"].mean()),
                    "exact_top1_accuracy": float(g["exact_top1_hit"].mean()),
                    "operational_pick_actual_raw_diff_median": float(g["operational_pick_actual_raw_diff"].median()),
                }
            )

    span_rows: list[dict[str, Any]] = []
    if not topk.empty:
        for (expert, band), g in topk.groupby(["expert", "span_band"], sort=True):
            span_rows.append(
                {
                    "expert": str(expert),
                    "span_band": str(band),
                    "n": int(len(g)),
                    "hit_at_2_mean": float(g["hit_at_2"].mean()),
                    "precision_mean": float(g["precision"].mean()),
                    "exact_top1_accuracy": float(g["exact_top1_hit"].mean()),
                    "top1_minus_top2_actual_q25": float(g["top1_minus_top2_actual"].quantile(0.25)),
                    "top1_minus_top2_actual_median": float(g["top1_minus_top2_actual"].median()),
                    "top1_minus_top2_actual_q75": float(g["top1_minus_top2_actual"].quantile(0.75)),
                    "operational_pick_actual_raw_diff_median": float(g["operational_pick_actual_raw_diff"].median()),
                }
            )

    daily_overall = {}
    if not daily.empty:
        ok = daily[daily.get("status", "ok") == "ok"].copy()
        if not ok.empty:
            daily_overall = {
                "n_days": int(ok["date"].nunique()) if "date" in ok.columns else int(len(ok)),
                "hit_at_2_mean": float(ok["hit_at_2"].mean()),
                "hit_at_3_mean": float(ok["hit_at_3"].mean()),
                "precision_mean": float(ok["precision"].mean()),
            }

    return {
        "overall_by_expert": overall,
        "span_band_by_expert": span_rows,
        "daily_overall": daily_overall,
    }
