"""
Ceiling-effect evaluator (MVP: phase 1-2).

Usage:
  python -m ml.last_digit.ceiling_effect_eval ^
    --input ml/last_digit/reports/digit_lag_v2r_current_xgb_ranker_ndcg_testperiod_topk.csv ^
    --output-dir ml/last_digit/exploratory/kamata7_only/ceiling_effect_v2r
"""

from __future__ import annotations

import argparse

from ml.last_digit.ceiling_effect import analyze_ceiling_effect
from ml.last_digit.ceiling_effect.stats import StatsConfig


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="*_testperiod_topk.csv")
    parser.add_argument("--output-dir", required=True, help="Output directory for analysis artifacts")
    parser.add_argument("--baseline", default="", help="Optional baseline *_testperiod_topk.csv for significance tests.")
    parser.add_argument("--n-boot", type=int, default=12000, help="Bootstrap iterations for CI when --baseline is set.")
    parser.add_argument("--seed", type=int, default=20260520, help="Bootstrap seed.")
    parser.add_argument("--min-paired", type=int, default=10, help="Min paired rows for Wilcoxon.")
    parser.add_argument("--min-unpaired", type=int, default=5, help="Min rows per side for Mann-Whitney.")
    args = parser.parse_args()

    baseline = str(args.baseline).strip() or None
    cfg = StatsConfig(
        n_boot=int(args.n_boot),
        seed=int(args.seed),
        min_paired_for_wilcoxon=int(args.min_paired),
        min_unpaired_for_mwu=int(args.min_unpaired),
    )
    outputs = analyze_ceiling_effect(
        input_topk_csv=args.input,
        output_dir=args.output_dir,
        baseline_topk_csv=baseline,
        stats_config=cfg,
    )
    for name, path in outputs.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
