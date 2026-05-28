from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from . import machine_type_monthly_check as monthly_check


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run monthly_check in split batches and aggregate outputs")
    p.add_argument("--db-path", default="")
    p.add_argument("--alpha", type=float, default=5.0)
    p.add_argument("--model-type", choices=["sgd", "xgb", "ltr"], default="xgb")
    p.add_argument("--ltr-decay-lambda", type=float, default=0.3)
    p.add_argument("--ltr-objective", choices=["rank:ndcg", "rank:pairwise"], default="rank:ndcg")
    p.add_argument("--gpu-backend", choices=["auto", "cpu", "cuda", "gpu_hist"], default="auto")
    p.add_argument("--segment-mode", choices=["global", "floor2", "type2", "floor_type4"], default="global")
    p.add_argument("--segment-blend-weight", type=float, default=1.0)
    p.add_argument("--prior-blend-weight", type=float, default=0.0)
    p.add_argument("--min-segment-days", type=int, default=21)
    p.add_argument("--min-segment-rows", type=int, default=300)
    p.add_argument("--feature-list-path", default="")
    p.add_argument("--threshold-split-thursday", action="store_true")
    p.add_argument("--random-state", type=int, default=42)
    p.add_argument("--eval-days-total", type=int, default=60)
    p.add_argument("--batch-size", type=int, default=20)
    p.add_argument("--output-prefix", default="ml/machine_type/reports/machine_type_reliability_split")
    return p


def run(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame]:
    total = max(int(args.eval_days_total), 1)
    batch = max(int(args.batch_size), 1)
    n_batches = (total + batch - 1) // batch
    daily_parts: list[pd.DataFrame] = []
    monthly_parts: list[pd.DataFrame] = []

    for i in range(n_batches):
        offset = total - (i + 1) * batch
        if offset < 0:
            offset = 0
        eval_days = min(batch, total - i * batch)
        sub = argparse.Namespace(
            db_path=args.db_path,
            alpha=float(args.alpha),
            model_type=str(args.model_type),
            ltr_decay_lambda=float(args.ltr_decay_lambda),
            ltr_objective=str(args.ltr_objective),
            gpu_backend=str(args.gpu_backend),
            segment_mode=str(args.segment_mode),
            segment_blend_weight=float(args.segment_blend_weight),
            prior_blend_weight=float(args.prior_blend_weight),
            min_segment_days=int(args.min_segment_days),
            min_segment_rows=int(args.min_segment_rows),
            eval_days=int(eval_days),
            eval_offset_days=int(offset),
            output_prefix="",
            feature_list_path=str(args.feature_list_path),
            threshold_split_thursday=bool(args.threshold_split_thursday),
            random_state=int(args.random_state),
        )
        print(f"[batch {i+1}/{n_batches}] eval_days={eval_days} eval_offset_days={offset}")
        daily, monthly = monthly_check.build_reliability_tables(sub)
        daily_parts.append(daily)
        monthly_parts.append(monthly)

    all_daily = pd.concat(daily_parts, ignore_index=True).drop_duplicates(
        subset=["date", "target", "model_type", "segment_mode", "prior_blend_weight", "segment_blend_weight"],
        keep="last",
    )
    all_daily = all_daily.sort_values(["date", "target"]).reset_index(drop=True)
    all_monthly = (
        all_daily.groupby(["month", "target", "is_thursday"], sort=True)
        .agg(
            precision=("precision", "mean"),
            recall=("recall", "mean"),
            f1=("f1", "mean"),
            hit_at_1=("hit_at_1", "mean"),
            hit_at_2=("hit_at_2", "mean"),
            hit_at_3=("hit_at_3", "mean"),
            hit_at_5=("hit_at_5", "mean"),
            predicted_count=("predicted_count", "mean"),
            base_rate=("base_rate", "mean"),
            truth_entity_count=("truth_entity_count", "mean"),
            known_entity_count=("known_entity_count", "mean"),
            unseen_entity_count=("unseen_entity_count", "mean"),
            known_coverage=("known_coverage", "mean"),
            skip_rate=("skip_rate", "mean"),
            n_days=("date", "nunique"),
            backend_used=("backend_used", lambda s: ",".join(sorted(set(map(str, s))))),
            segment_mode=("segment_mode", lambda s: ",".join(sorted(set(map(str, s))))),
            segment_blend_weight=("segment_blend_weight", "mean"),
            prior_blend_weight=("prior_blend_weight", "mean"),
            segment_models_used=("segment_models_used", "mean"),
            segment_prediction_rows=("segment_prediction_rows", "mean"),
        )
        .reset_index()
    )
    return all_daily, all_monthly


def main() -> int:
    args = build_parser().parse_args()
    daily, monthly = run(args)
    prefix = Path(args.output_prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    daily_path = prefix.with_name(prefix.name + "_daily.csv")
    monthly_path = prefix.with_name(prefix.name + "_monthly.csv")
    daily.to_csv(daily_path, index=False, encoding="utf-8-sig")
    monthly.to_csv(monthly_path, index=False, encoding="utf-8-sig")
    print(f"Saved: {daily_path}")
    print(f"Saved: {monthly_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

