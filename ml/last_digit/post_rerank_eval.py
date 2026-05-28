"""
Observation-only evaluator for confidence/avoid signals.

Usage:
  python -m ml.last_digit.post_rerank_eval ^
    --input ml/last_digit/reports/digit_lag_v2_withinexpert_xgb_ranker_ndcg_testperiod_topk.csv ^
    --output ml/last_digit/reports/post_rerank_eval_v2.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from ml.last_digit.ceiling_effect import analyze_ceiling_effect
from ml.last_digit.ceiling_effect.stats import StatsConfig
from ml.last_digit.post_rerank import build_confidence_band


def _band_summary(df: pd.DataFrame) -> list[dict]:
    rows: list[dict] = []
    for band in ["undefined", "high", "medium", "low"]:
        sub = df[df["confidence_band"] == band]
        rows.append(
            {
                "band": band,
                "n_days": len(sub),
                "hit_at_2_mean": round(float(sub["hit_at_2"].mean()), 4) if len(sub) > 0 else None,
                "pct_of_total": round(len(sub) / max(len(df), 1) * 100, 1),
            }
        )
    return rows


def _span_quartile_summary(df: pd.DataFrame) -> list[dict]:
    df = df.copy()
    df["span_quartile"] = pd.qcut(
        df["pred_span_top12"].fillna(0.0),
        q=4,
        labels=["Q1(low)", "Q2", "Q3", "Q4(high)"],
        duplicates="drop",
    )
    rows: list[dict] = []
    for quartile, group in df.groupby("span_quartile", observed=True):
        rows.append(
            {
                "quartile": str(quartile),
                "span_range": [
                    round(float(group["pred_span_top12"].min()), 3),
                    round(float(group["pred_span_top12"].max()), 3),
                ],
                "n_days": len(group),
                "hit_at_2_mean": round(float(group["hit_at_2"].mean()), 4),
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--ceiling-effect",
        action="store_true",
        help="Also run ceiling-effect MVP evaluator and emit condition/loss artifacts.",
    )
    parser.add_argument(
        "--ceiling-output-dir",
        default="",
        help="Output directory for ceiling-effect artifacts. Default: sibling folder of --output.",
    )
    parser.add_argument("--ceiling-baseline-input", default="", help="Optional baseline topk for significance tests.")
    parser.add_argument("--ceiling-n-boot", type=int, default=12000, help="Bootstrap iterations for ceiling stats.")
    args = parser.parse_args()

    df = pd.read_csv(args.input, encoding="utf-8-sig")
    if "pred_span_top12" not in df.columns:
        print("[ERROR] pred_span_top12 column not found in input CSV.")
        return 1

    df["pred_span_top12"] = pd.to_numeric(df["pred_span_top12"], errors="coerce").fillna(0.0)
    df["hit_at_2"] = pd.to_numeric(df["hit_at_2"], errors="coerce").fillna(0.0)
    df["confidence_band"] = df["pred_span_top12"].apply(build_confidence_band)

    result: dict[str, object] = {
        "n_total": len(df),
        "overall_hit_at_2": round(float(df["hit_at_2"].mean()), 4),
        "confidence_band_summary": _band_summary(df),
        "span_quartile_summary": _span_quartile_summary(df),
        "by_expert": [],
    }

    by_expert: list[dict] = []
    for expert, group in df.groupby("expert", sort=True):
        group = group.copy()
        group["confidence_band"] = group["pred_span_top12"].apply(build_confidence_band)
        by_expert.append(
            {
                "expert": str(expert),
                "n_days": len(group),
                "hit_at_2_mean": round(float(group["hit_at_2"].mean()), 4),
                "confidence_band_summary": _band_summary(group),
            }
        )
    result["by_expert"] = by_expert

    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved: {args.output}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.ceiling_effect:
        out_dir = (
            Path(args.ceiling_output_dir)
            if str(args.ceiling_output_dir).strip()
            else (Path(args.output).parent / "ceiling_effect")
        )
        baseline = str(args.ceiling_baseline_input).strip() or None
        outputs = analyze_ceiling_effect(
            input_topk_csv=args.input,
            output_dir=out_dir,
            baseline_topk_csv=baseline,
            stats_config=StatsConfig(n_boot=int(args.ceiling_n_boot)),
        )
        for name, path in outputs.items():
            print(f"Saved ({name}): {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
