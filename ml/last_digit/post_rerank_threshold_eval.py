#!/usr/bin/env python3
"""
3-way confidence band threshold comparison evaluator.

Usage:
  python -m ml.last_digit.post_rerank_threshold_eval
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')


CONFIGS: dict[str, dict[str, float | None]] = {
    "current": {
        "undefined": None,
        "low_max": 0.10,
        "medium_max": 0.30,
    },
    "case_A": {
        "undefined": 0.001,
        "low_max": 0.10,
        "medium_max": 0.30,
    },
    "case_B": {
        "undefined": 0.001,
        "low_max": 0.15,
        "medium_max": 0.30,
    },
}

MISS_RECORDS = {
    ("2026-01-04", "3F_A"),
    ("2026-01-11", "3F_N"),
    ("2026-05-21", "3F_A"),
}


def _resolve_input_path() -> Path:
    base = Path("db/experiments/model_comparison")
    if base.exists():
        cands = sorted(base.glob("*v2*withinexpert*topk*.csv"))
        if cands:
            return cands[0]

    fallback1 = Path("ml/last_digit/reports/digit_lag_v2_withinexpert_xgb_ranker_ndcg_testperiod_topk.csv")
    if fallback1.exists():
        return fallback1

    fallback2 = Path("db/experiments/model_comparison/tail_ltr_xgb_ndcg_xgb_ranker_ndcg_testperiod_topk.csv")
    if fallback2.exists():
        return fallback2

    raise FileNotFoundError("No suitable topk CSV found.")


def _pick_expert_col(df: pd.DataFrame) -> str:
    if "group_key" in df.columns:
        return "group_key"
    if "expert" in df.columns:
        return "expert"
    raise KeyError("Neither 'group_key' nor 'expert' column exists in input CSV.")


def _assign_band(span: float, cfg: dict[str, float | None]) -> str:
    u = cfg["undefined"]
    low_max = float(cfg["low_max"])
    med_max = float(cfg["medium_max"])
    if u is not None and span < float(u):
        return "undefined"
    if span < low_max:
        return "low"
    if span < med_max:
        return "medium"
    return "high"


def _band_order(name: str) -> list[str]:
    if CONFIGS[name]["undefined"] is None:
        return ["high", "medium", "low"]
    return ["high", "medium", "low", "undefined"]


def _summarize(df: pd.DataFrame, cfg_name: str) -> dict[str, Any]:
    cfg = CONFIGS[cfg_name]
    work = df.copy()
    work["band"] = work["pred_span_top12"].apply(lambda x: _assign_band(float(x), cfg))

    band_rows: dict[str, dict[str, Any]] = {}
    for band in _band_order(cfg_name):
        sub = work[work["band"] == band]
        count = int(len(sub))
        miss_count = int(sub["is_miss"].sum()) if count else 0
        miss_rate = (100.0 * miss_count / count) if count else None
        band_rows[band] = {
            "count": count,
            "miss_count": miss_count,
            "miss_rate": miss_rate,
        }

    miss_details = []
    for d, e in sorted(MISS_RECORDS):
        row = work[(work["date_str"] == d) & (work["expert"] == e)]
        if row.empty:
            miss_details.append({"date": d, "expert": e, "span": None, "band": "NOT_FOUND"})
            continue
        r = row.iloc[0]
        miss_details.append(
            {
                "date": d,
                "expert": e,
                "span": float(r["pred_span_top12"]),
                "band": str(r["band"]),
            }
        )

    return {
        "cfg_name": cfg_name,
        "bands": band_rows,
        "total": int(len(work)),
        "total_miss": int(work["is_miss"].sum()),
        "miss_details": miss_details,
    }


def _fmt_band(row: dict[str, Any] | None) -> str:
    if row is None:
        return "N=---  ----"
    count = row["count"]
    miss_count = row["miss_count"]
    miss_rate = row["miss_rate"]
    if miss_rate is None:
        return f"N={count:<3d}  miss={miss_count}(---)"
    return f"N={count:<3d}  miss={miss_count}({miss_rate:4.1f}%)"


def main() -> int:
    input_path = _resolve_input_path()
    df = pd.read_csv(input_path, encoding="utf-8-sig")

    expert_col = _pick_expert_col(df)
    required = {"date", expert_col, "pred_span_top12"}
    missing = required - set(df.columns)
    if missing:
        raise KeyError(f"Missing required columns: {sorted(missing)}")

    work = df[["date", expert_col, "pred_span_top12"]].copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work["expert"] = work[expert_col].astype(str)
    work["pred_span_top12"] = pd.to_numeric(work["pred_span_top12"], errors="coerce")
    work = work.dropna(subset=["date", "pred_span_top12"]).copy()
    work["date_str"] = work["date"].dt.strftime("%Y-%m-%d")
    # If duplicated per (date, expert), use top span
    work = (
        work.groupby(["date_str", "expert"], as_index=False)["pred_span_top12"]
        .max()
        .sort_values(["date_str", "expert"])
        .reset_index(drop=True)
    )
    work["is_miss"] = work.apply(lambda r: 1 if (r["date_str"], r["expert"]) in MISS_RECORDS else 0, axis=1)

    res_current = _summarize(work, "current")
    res_a = _summarize(work, "case_A")
    res_b = _summarize(work, "case_B")

    print(f"Input: {input_path.as_posix()}")
    print(f"Resolved records (date,expert): {len(work)}")
    print("=== Confidence Band Threshold Comparison (v2 walk-forward) ===")
    print("         | current             | case_A              | case_B              |")
    print("         | (low<0.10)          | (undef<0.001,       | (undef<0.001,       |")
    print("         |                     |  low<0.10)          |  low<0.15)          |")
    print("---------+---------------------+---------------------+---------------------+")

    for band in ["high", "medium", "low", "undefined"]:
        c = res_current["bands"].get(band)
        a = res_a["bands"].get(band)
        b = res_b["bands"].get(band)
        print(
            f"{band:<8}| {_fmt_band(c):<20}| {_fmt_band(a):<20}| {_fmt_band(b):<20}|"
        )

    print("---------+---------------------+---------------------+---------------------+")
    print(
        f"TOTAL    | {res_current['total']:<6d} miss={res_current['total_miss']:<3d} | "
        f"{res_a['total']:<6d} miss={res_a['total_miss']:<3d} | "
        f"{res_b['total']:<6d} miss={res_b['total_miss']:<3d} |"
    )

    miss_map = {
        "current": {(x["date"], x["expert"]): x for x in res_current["miss_details"]},
        "case_A": {(x["date"], x["expert"]): x for x in res_a["miss_details"]},
        "case_B": {(x["date"], x["expert"]): x for x in res_b["miss_details"]},
    }
    print("=== 3件の miss 日の band 割り当て ===")
    print("date        expert  span        current   case_A    case_B")
    for d, e in sorted(MISS_RECORDS):
        rc = miss_map["current"][(d, e)]
        ra = miss_map["case_A"][(d, e)]
        rb = miss_map["case_B"][(d, e)]
        span = rc["span"]
        span_text = "None" if span is None else f"{span:.6f}"
        print(f"{d}  {e:<5}  {span_text:<10}  {rc['band']:<8}  {ra['band']:<8}  {rb['band']:<8}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
