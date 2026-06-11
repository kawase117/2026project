from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd


def _weighted_mean(df: pd.DataFrame, value_col: str, weight_col: str) -> float:
    if df.empty:
        return 0.0
    weights = pd.to_numeric(df[weight_col], errors="coerce").fillna(0.0)
    values = pd.to_numeric(df[value_col], errors="coerce").fillna(0.0)
    total = float(weights.sum())
    if total <= 0:
        return 0.0
    return float((values * weights).sum() / total)


def build_operational_summary(
    rebucket_df: pd.DataFrame,
    sunday_sweep_df: pd.DataFrame,
    *,
    sunday_q: float = 0.65,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    detail = rebucket_df.copy()
    sunday_row = sunday_sweep_df.loc[sunday_sweep_df["q_override"].eq(sunday_q)].copy()
    if sunday_row.empty:
        raise ValueError(f"Sunday q_override={sunday_q} not found in sweep results.")

    replace_cols = ["mean_diff", "hit_at_2", "played_rate", "n_days"]
    for col in replace_cols:
        detail.loc[detail["bucket"].eq("Sunday"), col] = float(sunday_row.iloc[0][col])

    decision_map = {
        "4day": "adopt",
        "Sunday": "adopt",
        "weekend": "adopt",
        "weakday": "monitor",
        "neutral": "exclude",
    }
    rationale_map = {
        "4day": "positive mean with bootstrap lower bound above zero",
        "Sunday": f"use Sunday q={sunday_q:.2f} override to reduce over-trading",
        "weekend": "positive mean and strongest non-4day bucket",
        "weakday": "positive but modest edge; keep live monitoring only",
        "neutral": "negative mean with weak hit rate; do not play",
    }
    detail["decision"] = detail["bucket"].map(decision_map).fillna("review")
    detail["rationale"] = detail["bucket"].map(rationale_map).fillna("")

    active = detail.loc[detail["decision"].eq("adopt")].copy()
    overall = {
        "sunday_q_override": float(sunday_q),
        "active_bucket_count": int(len(active)),
        "active_n_days": int(pd.to_numeric(active["n_days"], errors="coerce").fillna(0).sum()),
        "active_mean_diff": _weighted_mean(active, "mean_diff", "n_days"),
        "active_hit_at_2": _weighted_mean(active, "hit_at_2", "n_days"),
        "active_played_rate": _weighted_mean(active, "played_rate", "n_days"),
        "monitor_bucket_count": int(detail["decision"].eq("monitor").sum()),
        "exclude_bucket_count": int(detail["decision"].eq("exclude").sum()),
    }
    return detail, overall


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build operational-rule summary for Mitoya last-digit strategy.")
    parser.add_argument("--rebucket", default="db/experiments/mitoya_rebucket_summary.csv")
    parser.add_argument("--sunday-sweep", default="db/experiments/mitoya_sunday_threshold_sweep.csv")
    parser.add_argument("--output-csv", default="db/experiments/mitoya_operational_rule_summary.csv")
    parser.add_argument("--output-md", default="db/experiments/mitoya_operational_rule_summary.md")
    parser.add_argument("--sunday-q", type=float, default=0.65)
    return parser


def _render_markdown(detail: pd.DataFrame, overall: dict[str, Any]) -> str:
    lines = [
        "# Mitoya Operational Rule Summary",
        "",
        f"- Sunday q override: `{overall['sunday_q_override']:.2f}`",
        f"- Active buckets: `{overall['active_bucket_count']}`",
        f"- Active n_days: `{overall['active_n_days']}`",
        f"- Active weighted mean_diff: `{overall['active_mean_diff']:.2f}`",
        f"- Active weighted Hit@2: `{overall['active_hit_at_2']:.3f}`",
        f"- Active weighted played_rate: `{overall['active_played_rate']:.3f}`",
        "",
        "| bucket | decision | n_days | mean_diff | hit_at_2 | played_rate | rationale |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for _, row in detail.iterrows():
        lines.append(
            f"| {row['bucket']} | {row['decision']} | {int(row['n_days'])} | "
            f"{float(row['mean_diff']):.2f} | {float(row['hit_at_2']):.3f} | "
            f"{float(row['played_rate']):.3f} | {row['rationale']} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rebucket_df = pd.read_csv(args.rebucket)
    sunday_sweep_df = pd.read_csv(args.sunday_sweep)
    detail, overall = build_operational_summary(rebucket_df, sunday_sweep_df, sunday_q=float(args.sunday_q))

    out_df = detail.copy()
    for key, value in overall.items():
        out_df[key] = value

    output_csv = Path(args.output_csv)
    output_md = Path(args.output_md)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    output_md.write_text(_render_markdown(detail, overall), encoding="utf-8")
    print(output_csv)
    print(output_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
