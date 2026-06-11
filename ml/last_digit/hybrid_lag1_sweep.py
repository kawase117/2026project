from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any
import os

import pandas as pd


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run hybrid lag1_avg_games sweep without mid-run prompts.")
    p.add_argument("--base-output-root", default="db/experiments/hall_practical_strategy_followup_20260603_hybrid_lag1_sweep")
    p.add_argument("--hybrid-logreg-c", type=float, default=0.1)
    p.add_argument("--common-args", default="")
    return p


def _parse_common_args(raw: str) -> list[str]:
    return [x for x in str(raw).split() if x.strip()]


def _build_variant_specs(*, base_output_root: Path, hybrid_logreg_c: float, common_args: list[str]) -> list[dict[str, Any]]:
    variants = [
        {"name": "baseline", "use_lag1_games": False},
        {"name": "lag1_games", "use_lag1_games": True},
    ]
    out: list[dict[str, Any]] = []
    for variant in variants:
        variant_root = base_output_root / variant["name"]
        args = [
            sys.executable,
            "-m",
            "ml.hall_rank.hall_practical_strategy_analysis",
            "--hybrid-logreg-c-grid",
            str(hybrid_logreg_c),
            "--output-root",
            str(variant_root),
            *common_args,
        ]
        if variant["use_lag1_games"]:
            args.append("--hybrid-use-lag1-games")
        out.append(
            {
                "name": str(variant["name"]),
                "use_lag1_games": bool(variant["use_lag1_games"]),
                "output_root": variant_root,
                "args": args,
            }
        )
    return out


def _load_run_summary(output_root: Path) -> dict[str, Any]:
    p = output_root / "run_summary.json"
    if not p.exists():
        raise FileNotFoundError(f"Missing run_summary.json: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _load_chosen_store_counts(output_root: Path) -> dict[str, int]:
    p = output_root / "hybrid_daily_decision_plan.csv"
    if not p.exists():
        return {}
    df = pd.read_csv(p)
    if "chosen_store" not in df.columns:
        return {}
    counts = df["chosen_store"].value_counts(dropna=False).sort_values(ascending=False)
    return {str(k): int(v) for k, v in counts.items()}


def main() -> int:
    args = build_parser().parse_args()
    base_output_root = Path(str(args.base_output_root))
    common_args = _parse_common_args(str(args.common_args))
    variants = _build_variant_specs(
        base_output_root=base_output_root,
        hybrid_logreg_c=float(args.hybrid_logreg_c),
        common_args=common_args,
    )
    base_output_root.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for spec in variants:
        output_root = Path(spec["output_root"])
        output_root.mkdir(parents=True, exist_ok=True)
        run_summary_path = output_root / "run_summary.json"
        if run_summary_path.exists():
            print(f"[sweep] skipping {spec['name']} (already complete) -> {output_root}")
        else:
            print(f"[sweep] running {spec['name']} -> {output_root}")
            with (
                open(output_root / "stdout.log", "w", encoding="utf-8", errors="replace") as stdout_fh,
                open(output_root / "stderr.log", "w", encoding="utf-8", errors="replace") as stderr_fh,
            ):
                result = subprocess.run(
                    spec["args"],
                    cwd=Path(__file__).resolve().parents[2],
                    stdout=stdout_fh,
                    stderr=stderr_fh,
                    check=False,
                    env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                )
            if result.returncode != 0:
                raise RuntimeError(f"variant {spec['name']} failed with code {result.returncode}")
        summary = _load_run_summary(output_root)
        hybrid_summary = pd.read_csv(output_root / "hybrid_daily_decision_summary.csv").iloc[0].to_dict()
        strategy = pd.read_csv(output_root / "hall_strategy_comparison.csv")
        strategy_row = strategy[strategy["strategy"] == "hybrid"].iloc[0].to_dict()
        rows.append(
            {
                "variant": spec["name"],
                "use_lag1_games": spec["use_lag1_games"],
                "output_root": str(output_root),
                "chosen_avg_diff_mean": float(strategy_row["chosen_avg_diff_mean"]),
                "spearman_daily_mean": float(strategy_row["spearman_daily_mean"]),
                "top1_hit_rate": float(strategy_row["top1_hit_rate"]),
                "top2_inclusion_rate": float(strategy_row["top2_inclusion_rate"]),
                "regret_mean": float(strategy_row["regret_mean"]),
                "chosen_hit_ge_0_rate": float(hybrid_summary["chosen_hit_ge_0_rate"]),
                "chosen_hit_ge_100_rate": float(hybrid_summary["chosen_hit_ge_100_rate"]),
                "chosen_hit_ge_200_rate": float(hybrid_summary["chosen_hit_ge_200_rate"]),
                "chosen_hit_ge_300_rate": float(hybrid_summary["chosen_hit_ge_300_rate"]),
                "selected_logreg_c": float(summary["hybrid_selected_policy"]["logreg_c"]),
                "policy_dd_topk_bonus": float(summary["hybrid_selected_policy"]["dd_topk_bonus"]),
                "policy_share_cap": float(summary["hybrid_selected_policy"]["share_cap"]),
                "chosen_store_counts": json.dumps(_load_chosen_store_counts(output_root), ensure_ascii=False),
            }
        )
        print(
            f"[sweep] {spec['name']} chosen_avg_diff_mean={strategy_row['chosen_avg_diff_mean']:.4f} "
            f"spearman_daily_mean={strategy_row['spearman_daily_mean']:.4f}"
        )

    comparison = pd.DataFrame(rows).sort_values(
        ["chosen_avg_diff_mean", "spearman_daily_mean", "regret_mean"],
        ascending=[False, False, True],
    )
    comparison.to_csv(base_output_root / "hybrid_lag1_games_comparison.csv", index=False, encoding="utf-8-sig")
    (base_output_root / "hybrid_lag1_games_comparison.json").write_text(
        comparison.to_json(orient="records", force_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(comparison.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
