from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from . import machine_type_monthly_check as monthly_check


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lightweight alpha sensitivity sweep for machine-type reliability")
    parser.add_argument("--db-path", default="", help="SQLite DB path. Empty means auto-detect db/*7.db")
    parser.add_argument("--alphas", default="1,3,5,10", help="Comma-separated alpha values")
    parser.add_argument("--eval-days", type=int, default=60, help="Number of recent dates used for each alpha")
    parser.add_argument("--model-type", choices=["sgd", "xgb"], default="xgb", help="Model type per target")
    parser.add_argument(
        "--gpu-backend",
        choices=["auto", "cpu", "cuda", "gpu_hist"],
        default="auto",
        help="GPU backend for xgb. Ignored for sgd.",
    )
    parser.add_argument(
        "--segment-mode",
        choices=["global", "floor2", "type2", "floor_type4"],
        default="global",
        help="Specialization mode with global fallback",
    )
    parser.add_argument(
        "--segment-blend-weight",
        type=float,
        default=1.0,
        help="Blend weight for segment model score vs global score (1.0=segment only, 0.0=global only)",
    )
    parser.add_argument(
        "--prior-blend-weight",
        type=float,
        default=0.0,
        help="Blend model probability with prior target rate features (0.0=model only, 1.0=prior only)",
    )
    parser.add_argument(
        "--feature-list-path",
        default="",
        help="Optional path to newline-separated feature names to whitelist",
    )
    parser.add_argument("--min-segment-days", type=int, default=21, help="Minimum unique dates per segment model")
    parser.add_argument("--min-segment-rows", type=int, default=300, help="Minimum rows per segment model")
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument(
        "--output-prefix",
        default="ml/machine_type/reports/machine_type_alpha_sensitivity_light",
        help="Output prefix for alpha sensitivity artifacts",
    )
    return parser


def _parse_alphas(raw: str) -> list[float]:
    values: list[float] = []
    for token in (raw or "").split(","):
        token = token.strip()
        if not token:
            continue
        values.append(float(token))
    if not values:
        raise ValueError("No alpha values provided")
    return values


def run_alpha_sweep(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    for alpha in _parse_alphas(args.alphas):
        sub_args = argparse.Namespace(
            db_path=args.db_path,
            alpha=float(alpha),
            eval_days=int(args.eval_days),
            output_prefix="",
            random_state=int(args.random_state),
            model_type=str(args.model_type),
            gpu_backend=str(args.gpu_backend),
            segment_mode=str(args.segment_mode),
            segment_blend_weight=float(args.segment_blend_weight),
            prior_blend_weight=float(args.prior_blend_weight),
            min_segment_days=int(args.min_segment_days),
            min_segment_rows=int(args.min_segment_rows),
            feature_list_path=str(args.feature_list_path),
        )
        daily, _monthly = monthly_check.build_reliability_tables(sub_args)
        agg = (
            daily.groupby(["target", "is_thursday"], sort=True)
            .agg(
                f1=("f1", "mean"),
                precision=("precision", "mean"),
                recall=("recall", "mean"),
                hit_at_1=("hit_at_1", "mean"),
                hit_at_2=("hit_at_2", "mean"),
                hit_at_3=("hit_at_3", "mean"),
                hit_at_5=("hit_at_5", "mean"),
                known_coverage=("known_coverage", "mean"),
                n_days=("date", "nunique"),
            )
            .reset_index()
        )
        agg["alpha"] = float(alpha)
        agg["model_type"] = str(args.model_type)
        agg["gpu_backend"] = str(args.gpu_backend)
        agg["segment_mode"] = str(args.segment_mode)
        agg["segment_blend_weight"] = float(args.segment_blend_weight)
        agg["prior_blend_weight"] = float(args.prior_blend_weight)
        rows.extend(agg.to_dict(orient="records"))

    detailed = pd.DataFrame(rows).sort_values(["target", "is_thursday", "alpha"]).reset_index(drop=True)
    best = (
        detailed.sort_values(["target", "is_thursday", "f1"], ascending=[True, True, False])
        .groupby(["target", "is_thursday"], as_index=False)
        .head(1)
        .sort_values(["target", "is_thursday"])
        .reset_index(drop=True)
    )
    return detailed, best


def main() -> int:
    args = build_parser().parse_args()
    detailed, best = run_alpha_sweep(args)
    prefix = Path(args.output_prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    detailed_path = prefix.with_suffix(".csv")
    best_path = prefix.with_name(prefix.name + "_best.csv")
    detailed.to_csv(detailed_path, index=False, encoding="utf-8-sig")
    best.to_csv(best_path, index=False, encoding="utf-8-sig")
    print(f"Saved: {detailed_path}")
    print(f"Saved: {best_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
