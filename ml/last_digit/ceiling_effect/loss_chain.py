from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .loaders import ActualRankInfo


@dataclass
class LossScenario:
    scenario: str
    loss_value: float
    chosen_tail: str
    top1_match: int
    top2_match: int
    top3_match: int
    rescue_source: str


def _tail_str(value: Any) -> str:
    s = str(value).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def classify_loss_scenario(
    *,
    pred_top1_tail: str,
    pred_top2_tail: str,
    pred_top3_tail: str | None,
    actual: ActualRankInfo,
) -> LossScenario:
    p1 = _tail_str(pred_top1_tail)
    p2 = _tail_str(pred_top2_tail)
    p3 = _tail_str(pred_top3_tail) if pred_top3_tail is not None else ""

    top2_set = {actual.top1_tail, actual.top2_tail}
    top3_set = {actual.top1_tail, actual.top2_tail, actual.top3_tail}

    top1_match = int(p1 in top2_set)
    top2_match = int(p2 in top2_set)
    top3_match = int(bool(p3) and p3 in top2_set)

    d1 = float(actual.tail_to_diff.get(p1, np.nan))
    d2 = float(actual.tail_to_diff.get(p2, np.nan))
    d3 = float(actual.tail_to_diff.get(p3, np.nan)) if p3 else float("nan")

    if top1_match:
        # penalty-style loss (>=0): how far chosen machine is below actual top1.
        loss = float(actual.top1_diff - d1) if np.isfinite(d1) else float(actual.top1_diff - actual.top3_diff)
        return LossScenario("hit1", max(loss, 0.0), p1, top1_match, top2_match, top3_match, "rank1")
    if top2_match:
        loss = float(actual.top1_diff - d2) if np.isfinite(d2) else float(actual.top1_diff - actual.top3_diff)
        return LossScenario("miss1_hit2", max(loss, 0.0), p2, top1_match, top2_match, top3_match, "rank2")
    if p3 and p3 in top2_set:
        loss = float(actual.top1_diff - d3) if np.isfinite(d3) else float(actual.top1_diff - actual.top3_diff)
        return LossScenario("miss1_miss2_hit3", max(loss, 0.0), p3, top1_match, top2_match, top3_match, "rank3")

    available = [x for x in [d1, d2, d3] if np.isfinite(x)]
    chosen = max(available) if available else actual.top3_diff
    loss = float(actual.top1_diff - chosen)
    return LossScenario("critical_miss", max(loss, 0.0), p1, top1_match, top2_match, top3_match, "none")


def attach_loss_scenarios(
    df: pd.DataFrame,
    actual_rank_map: dict[tuple[pd.Timestamp, str], ActualRankInfo],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for rec in df.to_dict(orient="records"):
        key = (pd.Timestamp(rec["date"]), str(rec["expert"]))
        actual = actual_rank_map.get(key)
        if actual is None:
            continue
        pred_top1_tail = str(rec["top1_tail"])
        scenario = classify_loss_scenario(
            pred_top1_tail=pred_top1_tail,
            pred_top2_tail=str(rec["top2_tail"]),
            pred_top3_tail=(str(rec["top3_tail"]) if "top3_tail" in rec and pd.notna(rec["top3_tail"]) else None),
            actual=actual,
        )
        top1_machine_count = float(actual.tail_to_machine_count.get(_tail_str(pred_top1_tail), np.nan))
        if "top1_actual_raw_diff" in rec and pd.notna(rec["top1_actual_raw_diff"]):
            top1_actual_raw_diff = float(rec["top1_actual_raw_diff"])
        else:
            top1_actual_raw_diff = float(actual.tail_to_diff.get(_tail_str(pred_top1_tail), np.nan))
        if np.isfinite(top1_machine_count) and top1_machine_count > 0.0 and np.isfinite(top1_actual_raw_diff):
            top1_avg_diff_per_machine = float(top1_actual_raw_diff / top1_machine_count)
        else:
            top1_avg_diff_per_machine = float("nan")
        out = dict(rec)
        out.update(
            {
                "actual_top1_tail": actual.top1_tail,
                "actual_top2_tail": actual.top2_tail,
                "actual_top3_tail": actual.top3_tail,
                "actual_top1_diff": actual.top1_diff,
                "actual_top2_diff": actual.top2_diff,
                "actual_top3_diff": actual.top3_diff,
                "actual_top1_machine_count": actual.top1_machine_count,
                "actual_top2_machine_count": actual.top2_machine_count,
                "actual_top3_machine_count": actual.top3_machine_count,
                "top1_machine_count": top1_machine_count,
                "top1_avg_diff_per_machine": top1_avg_diff_per_machine,
                "loss_scenario": scenario.scenario,
                "loss_value": scenario.loss_value,
                "chosen_tail": scenario.chosen_tail,
                "top1_match": scenario.top1_match,
                "top2_match": scenario.top2_match,
                "top3_match": scenario.top3_match,
                "rescue_source": scenario.rescue_source,
            }
        )
        rows.append(out)
    return pd.DataFrame(rows)
