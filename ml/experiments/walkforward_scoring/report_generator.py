from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _table(df: pd.DataFrame, *, limit: int = 30) -> str:
    if df.empty:
        return "No rows."
    return "```text\n" + df.head(limit).to_string(index=False) + "\n```"


def _variant_comparison(summary: pd.DataFrame) -> str:
    lines = ["## Variant Comparison", ""]
    if summary.empty:
        return "\n".join(lines + ["No data."])

    all_rows = summary[summary["event_type"] == "all"].copy()
    if all_rows.empty:
        return "\n".join(lines + ["No 'all' rows in summary."])

    for window in sorted(all_rows["window"].unique()):
        w_rows = all_rows[all_rows["window"] == window].sort_values("lift@50", ascending=False)
        lines.append(f"### Window {window} days")
        lines.append("")
        cols = ["variant", "lift@50", "avg_diff_vs_other", "win_rate", "payout_rate", "hit@50", "n_test_days"]
        available = [c for c in cols if c in w_rows.columns]
        lines.append(_table(w_rows[available], limit=10))
        lines.append("")

        best = w_rows.iloc[0]
        worst = w_rows.iloc[-1]
        lines.append(f"- **Best**: {best['variant']} (lift@50={best['lift@50']:.3f}, avg_diff_vs_other={best.get('avg_diff_vs_other', 0):.0f})")
        lines.append(f"- **Worst**: {worst['variant']} (lift@50={worst['lift@50']:.3f})")
        lines.append("")

    return "\n".join(lines)


def _event_split(summary: pd.DataFrame) -> str:
    lines = ["## Event vs Non-Event", ""]
    if summary.empty:
        return "\n".join(lines + ["No data."])

    for window in sorted(summary["window"].unique()):
        w_rows = summary[summary["window"] == window]
        event = w_rows[w_rows["event_type"] == "event"]
        non_event = w_rows[w_rows["event_type"] == "non_event"]
        if event.empty and non_event.empty:
            continue
        lines.append(f"### Window {window} days")
        lines.append("")
        cols = ["variant", "event_type", "lift@50", "avg_diff_vs_other", "win_rate", "n_test_days"]
        available = [c for c in cols if c in w_rows.columns]
        combined = pd.concat([event, non_event]).sort_values(["variant", "event_type"])
        lines.append(_table(combined[available], limit=20))
        lines.append("")

    return "\n".join(lines)


def _a_segment_history(daily_results: pd.DataFrame) -> str:
    lines = ["## A-Segment History Coverage", ""]
    if daily_results.empty or "a_seg_hist_coverage" not in daily_results.columns:
        return "\n".join(lines + ["No data."])

    cols = ["variant", "window", "split_period", "a_seg_hist_coverage", "a_seg_fallback_count", "n_machines_scored"]
    available = [c for c in cols if c in daily_results.columns]
    grouped = (
        daily_results.groupby([c for c in ["variant", "window", "split_period"] if c in daily_results.columns], as_index=False)
        .agg(
            a_seg_hist_coverage=("a_seg_hist_coverage", "mean"),
            a_seg_fallback_count=("a_seg_fallback_count", "mean"),
            n_machines_scored=("n_machines_scored", "mean"),
        )
        .sort_values([c for c in ["window", "variant", "split_period"] if c in daily_results.columns])
    )
    lines.append(_table(grouped[available] if available else grouped))
    lines.append("")
    return "\n".join(lines)


def _split_verification(daily_results: pd.DataFrame) -> str:
    lines = ["## Front/Back Split Verification", ""]
    if daily_results.empty or "split_period" not in daily_results.columns:
        return "\n".join(lines + ["No data."])

    grouped = (
        daily_results.groupby([c for c in ["window", "split_period"] if c in daily_results.columns], as_index=False)
        .agg(
            avg_diff_vs_other=("avg_diff_vs_other", "mean"),
            lift50=("lift@50", "mean"),
            a_seg_hist_coverage=("a_seg_hist_coverage", "mean") if "a_seg_hist_coverage" in daily_results.columns else ("lift@50", "mean"),
            a_seg_fallback_count=("a_seg_fallback_count", "mean") if "a_seg_fallback_count" in daily_results.columns else ("lift@50", "mean"),
            n_test_days=("test_date", "nunique"),
        )
        .sort_values([c for c in ["window", "split_period"] if c in daily_results.columns])
    )
    lines.append(_table(grouped))
    lines.append("")
    return "\n".join(lines)


def _component_summary(component_analysis: pd.DataFrame) -> str:
    lines = ["## Component Lift Summary", ""]
    if component_analysis.empty:
        return "\n".join(lines + ["No data."])

    agg = (
        component_analysis.groupby(["component", "window"], dropna=False)
        .agg(
            avg_lift50=("lift@50", "mean"),
            std_lift50=("lift@50", "std"),
            avg_diff=("avg_diff", "mean"),
            n=("lift@50", "count"),
        )
        .reset_index()
        .sort_values(["window", "avg_lift50"], ascending=[True, False])
    )
    agg["std_lift50"] = agg["std_lift50"].fillna(0)

    for window in sorted(agg["window"].unique()):
        w = agg[agg["window"] == window]
        lines.append(f"### Window {window} days")
        lines.append("")
        lines.append(_table(w[["component", "avg_lift50", "std_lift50", "avg_diff", "n"]]))
        lines.append("")

        above1 = w[w["avg_lift50"] > 1.0]["component"].tolist()
        below1 = w[w["avg_lift50"] < 1.0]["component"].tolist()
        if above1:
            lines.append(f"- Positive lift: {', '.join(above1)}")
        if below1:
            lines.append(f"- Below random: {', '.join(below1)}")
        lines.append("")

    return "\n".join(lines)


def _window_comparison(summary: pd.DataFrame) -> str:
    lines = ["## Window Size Comparison", ""]
    if summary.empty:
        return "\n".join(lines + ["No data."])

    all_rows = summary[summary["event_type"] == "all"].copy()
    if all_rows.empty:
        return "\n".join(lines + ["No data."])

    pivot = all_rows.groupby("window").agg(
        avg_lift50=("lift@50", "mean"),
        avg_diff_vs_other=("avg_diff_vs_other", "mean"),
        avg_win_rate=("win_rate", "mean"),
    ).reset_index().sort_values("window")

    lines.append(_table(pivot))
    lines.append("")

    if len(pivot) >= 2:
        best_w = pivot.loc[pivot["avg_lift50"].idxmax(), "window"]
        lines.append(f"- Best window: **{int(best_w)} days** by average lift@50")
        lines.append("")

    return "\n".join(lines)


def _weight_recommendation(weight_optimization: pd.DataFrame) -> str:
    lines = ["## Weight Recommendation", ""]
    if weight_optimization.empty:
        return "\n".join(lines + ["No weight optimization data."])

    selected = weight_optimization[weight_optimization.get("selected", pd.Series(False)) == True]
    if selected.empty:
        lines.append("No selected weights found.")
        return "\n".join(lines)

    cols = ["window", "w1", "w2", "w3", "w4", "w5", "w6", "avg_lift50", "avg_hit50", "n_days"]
    available = [c for c in cols if c in selected.columns]
    lines.append(_table(selected[available].drop_duplicates()))
    lines.append("")
    lines.append("Weights: w1=C1(seg*ssg*kakuban), w2=C2(theory), w3=C3(DD*kakuban), w4=C4(dow*kakuban), w5=C5(last_digit), w6=C6(zorome)")
    lines.append("")

    return "\n".join(lines)


def _kakuban_fix_impact(summary: pd.DataFrame) -> str:
    lines = ["## Kakuban Fix Impact (v3 -> v4)", ""]
    if summary.empty:
        return "\n".join(lines + ["No data."])

    all_rows = summary[summary["event_type"] == "all"].copy()
    for window in sorted(all_rows["window"].unique()):
        w = all_rows[all_rows["window"] == window]
        v3 = w[w["variant"] == "v3_hist_payout"]
        v4 = w[w["variant"] == "v4_kakuban_fix"]
        if v3.empty or v4.empty:
            continue
        lift_diff = float(v4["lift@50"].iloc[0]) - float(v3["lift@50"].iloc[0])
        diff_diff = float(v4["avg_diff_vs_other"].iloc[0]) - float(v3["avg_diff_vs_other"].iloc[0])
        lines.append(f"### Window {window} days")
        lines.append(f"- lift@50 change: {lift_diff:+.3f}")
        lines.append(f"- avg_diff_vs_other change: {diff_diff:+.0f}")
        lines.append("")

    return "\n".join(lines)


def build_report(
    *,
    summary: pd.DataFrame,
    daily_results: pd.DataFrame,
    component_analysis: pd.DataFrame,
    weight_optimization: pd.DataFrame,
    correlation_matrix: pd.DataFrame,
    extra_checks: dict[str, Any],
    output_dir: Path,
) -> str:
    n_test_days = daily_results["test_date"].nunique() if not daily_results.empty else 0
    n_variants = daily_results["variant"].nunique() if not daily_results.empty else 0

    lines: list[str] = [
        "# Walk-Forward Scoring Backtest Report",
        "",
        f"Output: `{output_dir.as_posix()}`",
        f"Test days: {n_test_days}, Variants: {n_variants}",
        "",
        _variant_comparison(summary),
        "",
        _event_split(summary),
        "",
        _a_segment_history(daily_results),
        "",
        _split_verification(daily_results),
        "",
        _component_summary(component_analysis),
        "",
        _window_comparison(summary),
        "",
        _weight_recommendation(weight_optimization),
        "",
        _kakuban_fix_impact(summary),
        "",
        "## Correlation Matrix",
        "",
        _table(correlation_matrix),
        "",
        "## Raw Summary Table",
        "",
        _table(summary.sort_values(["window", "variant", "event_type"])),
        "",
    ]

    for title, frame in extra_checks.items():
        lines.extend(
            [
                f"## {title}",
                "",
                _table(frame),
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"
