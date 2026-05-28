from __future__ import annotations

import pandas as pd


def build_confidence_band(pred_span: float) -> str:
    """
    Map top1-top2 prediction span into a coarse confidence band.

    Thresholds are intentionally provisional and are validated offline before
    any ranking-active logic is introduced.
    """
    if pred_span < 0.001:
        return "undefined"
    if pred_span >= 0.30:
        return "high"
    if pred_span >= 0.10:
        return "medium"
    return "low"


def mark_avoid_candidates(rank_df: pd.DataFrame, avoid_k: int = 3) -> pd.DataFrame:
    """
    Flag the bottom avoid_k rows by ascending pred without changing the ranking.

    rank_df is expected to be one day x one expert worth of rows.
    """
    out = rank_df.copy()
    out["is_avoid_candidate"] = 0
    if avoid_k > 0 and len(out) > avoid_k:
        avoid_idx = out.sort_values("pred", ascending=True).head(avoid_k).index
        out.loc[avoid_idx, "is_avoid_candidate"] = 1
    return out


def choose_operational_pick(
    *,
    top1_tail: str,
    top2_tail: str,
    confidence_band: str,
) -> tuple[str, str]:
    """
    Output-only operational routing.

    Rule:
    - default: choose top1
    - if confidence is undefined and top2 exists: choose top2
    """
    if confidence_band == "undefined" and str(top2_tail) != "":
        return str(top2_tail), "top2_on_undefined"
    return str(top1_tail), "top1_default"
