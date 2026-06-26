"""Component-level contribution analysis per segment x event_type.

For each component (c1-c6), answers:
  "If we ranked machines by THIS component alone, how well would we pick winners
   in each segment on event vs non-event days?"

Usage:
  python -m ml.experiments.walkforward_scoring.component_decomposition \
      --input ml/experiments/walkforward_scoring/results_v9_component/scored_pool.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


COMPONENTS = ["c1", "c2", "c3", "c4", "c5", "c6", "composite"]
COMPONENT_LABELS = {
    "c1": "kakuban",
    "c2": "hist",
    "c3": "DD*kakuban",
    "c4": "dow*kakuban",
    "c5": "last_digit",
    "c6": "zorome",
    "composite": "ALL(weighted)",
}


def _summarize_top_n(group: pd.DataFrame, actual: pd.DataFrame, sort_col: str, n: int = 50) -> dict:
    top = group.nlargest(min(n, len(group)), sort_col)
    other = actual[~actual["machine_number"].isin(top["machine_number"])]
    avg_top = float(top["diff_coins_normalized"].mean()) if len(top) else 0.0
    avg_other = float(other["diff_coins_normalized"].mean()) if len(other) else 0.0
    wins = int((top["diff_coins_normalized"] > 0).sum()) if len(top) else 0
    n_top = len(top)
    return {
        "avg_diff": avg_top,
        "avg_diff_other": avg_other,
        "avg_diff_vs_other": avg_top - avg_other,
        "win_rate": round(100.0 * wins / n_top, 1) if n_top else 0.0,
        "n_selected": n_top,
    }


def run_decomposition(scored_pool: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if "event_type" not in scored_pool.columns or scored_pool["event_type"].isna().all():
        from ml.experiments.walkforward_scoring.walk_forward_engine import _is_event_date
        scored_pool["event_type"] = pd.to_datetime(scored_pool["test_date"]).apply(
            lambda d: "event" if _is_event_date(d) else "non_event"
        )

    results = []
    for (segment, event_type, test_date), day_group in scored_pool.groupby(
        ["segment", "event_type", "test_date"]
    ):
        actual = day_group.copy()
        for comp in COMPONENTS:
            if comp not in day_group.columns:
                continue
            metrics = _summarize_top_n(day_group, actual, comp)
            results.append({
                "segment": segment,
                "event_type": event_type,
                "test_date": test_date,
                "component": comp,
                **metrics,
            })

    daily_df = pd.DataFrame(results)

    summary = (
        daily_df.groupby(["segment", "event_type", "component"], as_index=False)
        .agg(
            mean_vs_other=("avg_diff_vs_other", "mean"),
            mean_diff=("avg_diff", "mean"),
            mean_other=("avg_diff_other", "mean"),
            std_vs_other=("avg_diff_vs_other", "std"),
            n_days=("test_date", "nunique"),
        )
    )

    p_values = []
    for _, row in summary.iterrows():
        mask = (
            (daily_df["segment"] == row["segment"])
            & (daily_df["event_type"] == row["event_type"])
            & (daily_df["component"] == row["component"])
        )
        vals = daily_df.loc[mask, "avg_diff_vs_other"].to_numpy(dtype=float)
        nonzero = vals[vals != 0]
        if len(nonzero) >= 10:
            _, p = stats.wilcoxon(nonzero, alternative="two-sided")
        else:
            p = np.nan
        p_values.append(p)
    summary["p_value"] = p_values

    win_rates = []
    for _, row in summary.iterrows():
        mask = (
            (daily_df["segment"] == row["segment"])
            & (daily_df["event_type"] == row["event_type"])
            & (daily_df["component"] == row["component"])
        )
        vals = daily_df.loc[mask, "avg_diff_vs_other"].to_numpy(dtype=float)
        wr = 100.0 * (vals > 0).sum() / len(vals) if len(vals) else 0.0
        win_rates.append(round(wr, 1))
    summary["day_win_pct"] = win_rates

    def verdict(row):
        if np.isnan(row["p_value"]):
            return "ns"
        if row["p_value"] < 0.01 and row["mean_vs_other"] > 0:
            return "USEFUL"
        if row["p_value"] < 0.05 and row["mean_vs_other"] > 0:
            return "maybe"
        if row["p_value"] < 0.01 and row["mean_vs_other"] < 0:
            return "WORSE"
        if row["p_value"] < 0.05 and row["mean_vs_other"] < 0:
            return "bad?"
        return "ns"
    summary["verdict"] = summary.apply(verdict, axis=1)
    summary["label"] = summary["component"].map(COMPONENT_LABELS)

    return summary, daily_df


def format_summary(summary: pd.DataFrame) -> str:
    lines = ["=" * 100, "COMPONENT DECOMPOSITION: which EDA rule works in which segment?", "=" * 100, ""]

    for seg in sorted(summary["segment"].unique()):
        lines.append(f"=== {seg} ===")
        for et in ["non_event", "event"]:
            sub = summary[(summary["segment"] == seg) & (summary["event_type"] == et)]
            if sub.empty:
                continue
            sub = sub.sort_values("mean_vs_other", ascending=False)
            lines.append(f"  [{et}] (n={sub.iloc[0]['n_days']})")
            for _, r in sub.iterrows():
                sig = "***" if r["p_value"] < 0.05 else ""
                lines.append(
                    f"    {r['label']:15s} | "
                    f"vs_other={r['mean_vs_other']:+7.0f}{sig:3s} | "
                    f"win={r['day_win_pct']:4.0f}% | "
                    f"p={r['p_value']:.4f} | "
                    f"{r['verdict']}"
                )
            lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="ml/experiments/walkforward_scoring/results_v9_component/scored_pool.csv")
    p.add_argument("--output", default="ml/experiments/walkforward_scoring/results_v9_component/component_decomposition.csv")
    args = p.parse_args(argv)

    print(f"Loading {args.input}...")
    df = pd.read_csv(args.input)
    print(f"  {len(df)} rows, columns: {[c for c in df.columns if c.startswith('c') or c == 'composite' or c == 'segment']}")

    summary, daily = run_decomposition(df)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(out, index=False, encoding="utf-8-sig")
    daily.to_csv(out.with_name("component_daily.csv"), index=False, encoding="utf-8-sig")
    print(f"Saved to {out}")

    txt = format_summary(summary)
    print(txt)
    out.with_suffix(".txt").write_text(txt, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
