"""Paired significance tests for walk-forward model comparison.

Implements the testing framework from:
  document/plans/2026-06-23-significance-test-unit-and-quantity-spec.md

Unit of analysis = test_date (not individual machines).
Pairing key = (segment, test_date).
Three test families:
  1. Additive (avg_diff_vs_other): paired bootstrap + Wilcoxon signed-rank
  2. Win/loss: sign test (binomial, H0: p=0.5)
  3. Pooled ratio (hit_t / expected_t): bootstrap of pooled ratio

Usage:
  python -m ml.experiments.walkforward_scoring.significance_test \
      --input ml/experiments/walkforward_scoring/results_v9_threshold/segment_daily_results.csv \
      --baseline v6a_hit_an \
      --output ml/experiments/walkforward_scoring/results_v9_threshold/significance_results.csv
"""

from __future__ import annotations

import argparse
import itertools
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Paired significance tests for model variants.")
    p.add_argument(
        "--input",
        default="ml/experiments/walkforward_scoring/results_v9_threshold/segment_daily_results.csv",
    )
    p.add_argument("--baseline", default="v6a_hit_an", help="Baseline variant name")
    p.add_argument(
        "--output",
        default="ml/experiments/walkforward_scoring/results_v9_threshold/significance_results.csv",
    )
    p.add_argument("--selection", default="top50", help="Filter by selection column (top50/bottom50)")
    p.add_argument("--n-boot", type=int, default=10000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--alpha", type=float, default=0.05)
    return p


# ---------------------------------------------------------------------------
# Step 1: ACF check
# ---------------------------------------------------------------------------


def compute_acf(series: np.ndarray, max_lag: int = 3) -> list[float]:
    """Autocorrelation for lags 1..max_lag (Pearson)."""
    n = len(series)
    if n < max_lag + 2:
        return [np.nan] * max_lag
    mean = series.mean()
    var = ((series - mean) ** 2).sum()
    if var == 0:
        return [0.0] * max_lag
    acfs = []
    for lag in range(1, max_lag + 1):
        cov = ((series[:-lag] - mean) * (series[lag:] - mean)).sum()
        acfs.append(float(cov / var))
    return acfs


def acf_check(diffs: np.ndarray, max_lag: int = 3) -> dict:
    """Check serial correlation and recommend bootstrap type."""
    acfs = compute_acf(diffs, max_lag)
    n = len(diffs)
    threshold = 2.0 / np.sqrt(n) if n > 0 else np.inf
    significant = any(abs(a) > threshold for a in acfs if not np.isnan(a))
    return {
        "acf_lag1": acfs[0] if len(acfs) > 0 else np.nan,
        "acf_lag2": acfs[1] if len(acfs) > 1 else np.nan,
        "acf_lag3": acfs[2] if len(acfs) > 2 else np.nan,
        "acf_threshold": threshold,
        "serial_correlation_detected": significant,
        "recommended_bootstrap": "block" if significant else "iid",
    }


# ---------------------------------------------------------------------------
# Step 2: Paired bootstrap for additive metrics
# ---------------------------------------------------------------------------


def paired_bootstrap_ci(
    diffs: np.ndarray,
    *,
    n_boot: int = 10000,
    seed: int = 42,
    block: bool = False,
    block_size: int = 5,
) -> dict:
    """Bootstrap CI for mean of paired differences.

    If block=True, uses moving-block bootstrap to handle serial correlation.
    """
    n = len(diffs)
    if n == 0:
        return {"mean_diff": 0.0, "ci_lower": 0.0, "ci_upper": 0.0, "se": 0.0}
    rng = np.random.default_rng(seed)

    if block and n > block_size:
        n_blocks = max(1, n // block_size)
        total_len = n_blocks * block_size
        means = np.empty(n_boot)
        for i in range(n_boot):
            starts = rng.integers(0, n - block_size + 1, size=n_blocks)
            sample = np.concatenate([diffs[s : s + block_size] for s in starts])[:total_len]
            means[i] = sample.mean()
    else:
        idx = rng.integers(0, n, size=(n_boot, n))
        means = diffs[idx].mean(axis=1)

    ci_lo, ci_hi = np.quantile(means, [0.025, 0.975])
    return {
        "mean_diff": float(diffs.mean()),
        "ci_lower": float(ci_lo),
        "ci_upper": float(ci_hi),
        "se": float(means.std()),
    }


# ---------------------------------------------------------------------------
# Step 3: Leave-one-day-out sensitivity
# ---------------------------------------------------------------------------


def leave_one_out_sensitivity(diffs: np.ndarray) -> dict:
    """Check if any single day drives the result."""
    n = len(diffs)
    if n < 3:
        return {"loo_min_mean": np.nan, "loo_max_mean": np.nan, "loo_sign_flips": 0, "loo_fragile": True}
    overall_sign = np.sign(diffs.mean())
    total = np.sum(diffs)
    loo_means = np.array([(total - diffs[i]) / (n - 1) for i in range(n)])
    sign_flips = int(np.sum(np.sign(loo_means) != overall_sign))
    return {
        "loo_min_mean": float(loo_means.min()),
        "loo_max_mean": float(loo_means.max()),
        "loo_sign_flips": sign_flips,
        "loo_fragile": sign_flips > 0,
    }


# ---------------------------------------------------------------------------
# Step 4: Win/loss sign test
# ---------------------------------------------------------------------------


def win_loss_test(diffs: np.ndarray) -> dict:
    """Binomial sign test: H0 = variant wins 50% of days."""
    n = len(diffs)
    wins = int(np.sum(diffs > 0))
    losses = int(np.sum(diffs < 0))
    ties = n - wins - losses
    effective_n = wins + losses
    if effective_n == 0:
        return {"wins": 0, "losses": 0, "ties": ties, "win_pct": 50.0, "p_value_sign": 1.0}
    p_val = float(stats.binomtest(wins, effective_n, 0.5).pvalue)
    return {
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "win_pct": round(100.0 * wins / effective_n, 1),
        "p_value_sign": p_val,
    }


# ---------------------------------------------------------------------------
# Step 5: Wilcoxon signed-rank test
# ---------------------------------------------------------------------------


def wilcoxon_test(diffs: np.ndarray) -> dict:
    """Wilcoxon signed-rank test on paired differences."""
    nonzero = diffs[diffs != 0]
    if len(nonzero) < 10:
        return {"p_value_wilcoxon": np.nan, "wilcoxon_statistic": np.nan}
    stat, p_val = stats.wilcoxon(nonzero, alternative="two-sided")
    return {"p_value_wilcoxon": float(p_val), "wilcoxon_statistic": float(stat)}


# ---------------------------------------------------------------------------
# Step 6: Pooled ratio bootstrap (for hit_t / expected_t)
# ---------------------------------------------------------------------------


def pooled_ratio_bootstrap(
    hits_a: np.ndarray,
    expected_a: np.ndarray,
    hits_b: np.ndarray,
    expected_b: np.ndarray,
    *,
    n_boot: int = 10000,
    seed: int = 42,
) -> dict:
    """Bootstrap CI for difference in pooled lift = sum(hit)/sum(expected)."""
    n = len(hits_a)
    if n == 0:
        return {"pooled_lift_diff": 0.0, "ci_lower": 0.0, "ci_upper": 0.0, "p_value_ratio": 1.0}
    rng = np.random.default_rng(seed)

    def pooled_lift_diff(idx: np.ndarray) -> float:
        ea = expected_a[idx].sum()
        eb = expected_b[idx].sum()
        la = hits_a[idx].sum() / ea if ea > 0 else 0.0
        lb = hits_b[idx].sum() / eb if eb > 0 else 0.0
        return la - lb

    observed = pooled_lift_diff(np.arange(n))
    boot_diffs = np.array([pooled_lift_diff(rng.integers(0, n, size=n)) for _ in range(n_boot)])
    ci_lo, ci_hi = np.quantile(boot_diffs, [0.025, 0.975])
    p_val = float(np.mean(boot_diffs <= 0)) if observed > 0 else float(np.mean(boot_diffs >= 0))
    p_val = min(2 * p_val, 1.0)
    return {
        "pooled_lift_diff": float(observed),
        "ci_lower": float(ci_lo),
        "ci_upper": float(ci_hi),
        "p_value_ratio": p_val,
    }


# ---------------------------------------------------------------------------
# BH FDR correction
# ---------------------------------------------------------------------------


def benjamini_hochberg(p_values: list[float], alpha: float = 0.05) -> list[float]:
    """Return BH-adjusted q-values."""
    n = len(p_values)
    if n == 0:
        return []
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    q_values = [0.0] * n
    for rank, (orig_idx, p) in enumerate(indexed, 1):
        q_values[orig_idx] = min(p * n / rank, 1.0)
    # enforce monotonicity (descending rank order)
    for i in range(n - 2, -1, -1):
        sorted_idx = indexed[i][0]
        next_idx = indexed[i + 1][0]
        if q_values[sorted_idx] > q_values[next_idx]:
            q_values[sorted_idx] = q_values[next_idx]
    return q_values


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


def run_tests(
    df: pd.DataFrame,
    baseline: str,
    *,
    n_boot: int = 10000,
    seed: int = 42,
    alpha: float = 0.05,
) -> pd.DataFrame:
    variants = sorted(v for v in df["variant"].unique() if v != baseline)
    segments = sorted(df["segment"].unique())
    event_types = sorted(df["event_type"].unique())

    results = []

    for variant, segment, event_type in itertools.product(variants, segments, event_types):
        base = df[(df["variant"] == baseline) & (df["segment"] == segment) & (df["event_type"] == event_type)]
        comp = df[(df["variant"] == variant) & (df["segment"] == segment) & (df["event_type"] == event_type)]

        merged = base.merge(comp, on=["test_date", "window"], suffixes=("_base", "_comp"))
        if merged.empty:
            continue

        merged = merged.sort_values("test_date").reset_index(drop=True)
        n_days = len(merged)

        row = {
            "baseline": baseline,
            "variant": variant,
            "segment": segment,
            "event_type": event_type,
            "n_days": n_days,
        }

        # --- ACF check on avg_diff_vs_other ---
        diff_additive = (merged["avg_diff_vs_other_comp"] - merged["avg_diff_vs_other_base"]).to_numpy(dtype=float)
        acf_info = acf_check(diff_additive)
        row.update({f"acf_{k}": v for k, v in acf_info.items()})
        use_block = acf_info["serial_correlation_detected"]

        # --- Additive: avg_diff_vs_other ---
        boot = paired_bootstrap_ci(diff_additive, n_boot=n_boot, seed=seed, block=use_block)
        row["additive_mean_diff"] = boot["mean_diff"]
        row["additive_ci_lower"] = boot["ci_lower"]
        row["additive_ci_upper"] = boot["ci_upper"]
        row["additive_se"] = boot["se"]

        wilc = wilcoxon_test(diff_additive)
        row["p_value_wilcoxon"] = wilc["p_value_wilcoxon"]

        loo = leave_one_out_sensitivity(diff_additive)
        row.update(loo)

        # --- Win/loss: who had higher avg_diff_vs_other each day ---
        wl = win_loss_test(diff_additive)
        row.update(wl)

        # --- Additive: payout_rate (weighted) ---
        payout_base_col = "payout_rate_base"
        payout_comp_col = "payout_rate_comp"
        if payout_base_col in merged.columns and payout_comp_col in merged.columns:
            diff_payout = (merged[payout_comp_col] - merged[payout_base_col]).to_numpy(dtype=float)
            diff_payout = diff_payout[~np.isnan(diff_payout)]
            if len(diff_payout) >= 3:
                boot_p = paired_bootstrap_ci(diff_payout, n_boot=n_boot, seed=seed, block=use_block)
                row["payout_mean_diff"] = boot_p["mean_diff"]
                row["payout_ci_lower"] = boot_p["ci_lower"]
                row["payout_ci_upper"] = boot_p["ci_upper"]
                wilc_p = wilcoxon_test(diff_payout)
                row["p_value_wilcoxon_payout"] = wilc_p["p_value_wilcoxon"]

        # --- Pooled ratio for hit_t thresholds ---
        for threshold in [2500, 3500, 4500]:
            hit_col = f"hit_t{threshold}"
            lift_col = f"lift_t{threshold}"
            hit_base_col = f"{hit_col}_base"
            hit_comp_col = f"{hit_col}_comp"
            lift_base_col = f"{lift_col}_base"
            lift_comp_col = f"{lift_col}_comp"

            if hit_base_col in merged.columns and lift_base_col in merged.columns:
                hits_b = merged[hit_base_col].to_numpy(dtype=float)
                lifts_b = merged[lift_base_col].to_numpy(dtype=float)
                hits_c = merged[hit_comp_col].to_numpy(dtype=float)
                lifts_c = merged[lift_comp_col].to_numpy(dtype=float)

                with np.errstate(divide="ignore", invalid="ignore"):
                    exp_b = np.where(lifts_b > 0, hits_b / lifts_b, 0.0)
                    exp_c = np.where(lifts_c > 0, hits_c / lifts_c, 0.0)
                exp_b = np.nan_to_num(exp_b, nan=0.0)
                exp_c = np.nan_to_num(exp_c, nan=0.0)

                pr = pooled_ratio_bootstrap(hits_c, exp_c, hits_b, exp_b, n_boot=n_boot, seed=seed)
                row[f"lift_t{threshold}_pooled_diff"] = pr["pooled_lift_diff"]
                row[f"lift_t{threshold}_ci_lower"] = pr["ci_lower"]
                row[f"lift_t{threshold}_ci_upper"] = pr["ci_upper"]
                row[f"lift_t{threshold}_p_value"] = pr["p_value_ratio"]

        results.append(row)

    result_df = pd.DataFrame(results)

    # --- BH correction across all p-values ---
    p_cols = [c for c in result_df.columns if c.startswith("p_value_") or c.endswith("_p_value")]
    for col in p_cols:
        vals = result_df[col].tolist()
        valid_mask = [not (np.isnan(v) if isinstance(v, float) else False) for v in vals]
        valid_ps = [v for v, m in zip(vals, valid_mask) if m]
        if valid_ps:
            q_vals = benjamini_hochberg(valid_ps, alpha)
            q_col = col.replace("p_value", "q_value")
            result_df[q_col] = np.nan
            q_idx = 0
            for i, m in enumerate(valid_mask):
                if m:
                    result_df.loc[result_df.index[i], q_col] = q_vals[q_idx]
                    q_idx += 1

    return result_df


# ---------------------------------------------------------------------------
# vs Random: each model independently tested against chance
# ---------------------------------------------------------------------------


def run_vs_random(
    df: pd.DataFrame,
    *,
    n_boot: int = 10000,
    seed: int = 42,
    alpha: float = 0.05,
) -> pd.DataFrame:
    """Test each variant × segment × event_type against random baseline.

    H0: avg_diff_vs_other = 0 (model picks no better than remaining machines).
    """
    variants = sorted(df["variant"].unique())
    segments = sorted(df["segment"].unique())
    event_types = sorted(df["event_type"].unique())

    results = []
    for variant, segment, event_type in itertools.product(variants, segments, event_types):
        sub = df[(df["variant"] == variant) & (df["segment"] == segment) & (df["event_type"] == event_type)]
        vals = sub["avg_diff_vs_other"].to_numpy(dtype=float)
        n = len(vals)
        if n == 0:
            continue

        mean_val = float(vals.mean())
        wins = int(np.sum(vals > 0))
        losses = int(np.sum(vals < 0))
        eff_n = wins + losses
        win_pct = round(100.0 * wins / eff_n, 1) if eff_n > 0 else 50.0

        # Wilcoxon signed-rank (H0: median = 0)
        nonzero = vals[vals != 0]
        if len(nonzero) >= 10:
            stat_w, p_w = stats.wilcoxon(nonzero, alternative="two-sided")
        else:
            stat_w, p_w = np.nan, np.nan

        # Sign test (H0: P(win) = 0.5)
        p_sign = float(stats.binomtest(wins, eff_n, 0.5).pvalue) if eff_n > 0 else 1.0

        # Bootstrap CI for mean
        boot = paired_bootstrap_ci(vals, n_boot=n_boot, seed=seed)

        # LOO sensitivity
        loo = leave_one_out_sensitivity(vals)

        # Verdict
        if p_w < 0.01 and mean_val > 0:
            verdict = "USEFUL"
        elif p_w < 0.05 and mean_val > 0:
            verdict = "maybe"
        elif p_w < 0.01 and mean_val < 0:
            verdict = "WORSE"
        elif p_w < 0.05 and mean_val < 0:
            verdict = "bad?"
        else:
            verdict = "ns"

        row = {
            "variant": variant,
            "segment": segment,
            "event_type": event_type,
            "n_days": n,
            "mean_vs_other": mean_val,
            "ci_lower": boot["ci_lower"],
            "ci_upper": boot["ci_upper"],
            "se": boot["se"],
            "wins": wins,
            "losses": losses,
            "win_pct": win_pct,
            "p_value_wilcoxon": p_w,
            "p_value_sign": p_sign,
            "verdict": verdict,
        }
        row.update(loo)
        results.append(row)

    result_df = pd.DataFrame(results)

    # BH correction
    p_cols = [c for c in result_df.columns if c.startswith("p_value_")]
    for col in p_cols:
        vals_list = result_df[col].tolist()
        valid_mask = [not (np.isnan(v) if isinstance(v, float) else False) for v in vals_list]
        valid_ps = [v for v, m in zip(vals_list, valid_mask) if m]
        if valid_ps:
            q_vals = benjamini_hochberg(valid_ps, alpha)
            q_col = col.replace("p_value", "q_value")
            result_df[q_col] = np.nan
            q_idx = 0
            for i, m in enumerate(valid_mask):
                if m:
                    result_df.loc[result_df.index[i], q_col] = q_vals[q_idx]
                    q_idx += 1

    return result_df


def format_vs_random_summary(df: pd.DataFrame) -> str:
    """Human-readable summary of vs-random results."""
    lines = ["=" * 80, "MODEL vs RANDOM - PRACTICAL USEFULNESS", "=" * 80, ""]

    for variant, vgrp in df.groupby("variant"):
        lines.append(f"=== {variant} ===")
        for event_type in ["non_event", "event"]:
            egrp = vgrp[vgrp["event_type"] == event_type]
            if egrp.empty:
                continue
            lines.append(f"  [{event_type}] (n={egrp.iloc[0]['n_days']})")
            for _, r in egrp.iterrows():
                fragile = " [FRAGILE]" if r.get("loo_fragile", False) else ""
                lines.append(
                    f"    {r['segment']:8s} | "
                    f"mean={r['mean_vs_other']:+7.0f} "
                    f"[{r['ci_lower']:+.0f}, {r['ci_upper']:+.0f}] | "
                    f"win {r['wins']}/{r['n_days']} ({r['win_pct']:.0f}%) | "
                    f"p={r['p_value_wilcoxon']:.4f} | "
                    f"{r['verdict']}{fragile}"
                )
            lines.append("")
        lines.append("")

    return "\n".join(lines)


def format_summary(df: pd.DataFrame) -> str:
    """Human-readable summary of test results."""
    lines = ["=" * 80, "SIGNIFICANCE TEST RESULTS", "=" * 80, ""]

    for (variant, event_type), grp in df.groupby(["variant", "event_type"]):
        lines.append(f"--- {variant} vs {grp.iloc[0]['baseline']} | {event_type} ---")
        for _, r in grp.iterrows():
            seg = r["segment"]
            sig_add = "***" if r.get("p_value_wilcoxon", 1) < 0.05 else ""
            sig_win = "***" if r.get("p_value_sign", 1) < 0.05 else ""
            fragile = " [FRAGILE]" if r.get("loo_fragile", False) else ""

            payout_str = ""
            if "payout_mean_diff" in r and not (
                isinstance(r["payout_mean_diff"], float) and np.isnan(r["payout_mean_diff"])
            ):
                sig_pay = "***" if r.get("p_value_wilcoxon_payout", 1) < 0.05 else ""
                payout_str = f" | pay={r['payout_mean_diff']:+.3f}%{sig_pay}"
            lines.append(
                f"  {seg:8s} | "
                f"diff={r['additive_mean_diff']:+.0f} "
                f"[{r['additive_ci_lower']:+.0f}, {r['additive_ci_upper']:+.0f}]{sig_add}{fragile} | "
                f"win {r['wins']}/{r['n_days']} ({r['win_pct']:.0f}%){sig_win} | "
                f"ACF1={r.get('acf_acf_lag1', 0):.2f}{payout_str}"
            )
        lines.append("")

    event_rows = df[df["event_type"] == "event"]
    if not event_rows.empty:
        min_n = event_rows["n_days"].min()
        if min_n < 30:
            lines.append(f"WARNING: event subset has only {min_n} days -- insufficient for reliable inference.")
            lines.append("  Event-day results should be treated as QUALITATIVE only.")
            lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    input_path = Path(args.input)
    output_path = Path(args.output)

    df = pd.read_csv(input_path)
    if "selection" in df.columns:
        df = df[df["selection"] == args.selection].copy()
        print(f"Filtered to selection={args.selection}")
    print(f"Loaded {len(df)} rows from {input_path}")
    print(f"Variants: {df['variant'].unique().tolist()}")
    print(f"Baseline: {args.baseline}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # --- Model vs Model (pairwise) ---
    result_df = run_tests(df, args.baseline, n_boot=args.n_boot, seed=args.seed, alpha=args.alpha)
    result_df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"\nPairwise results saved to {output_path}")

    summary = format_summary(result_df)
    print(summary)
    output_path.with_suffix(".txt").write_text(summary, encoding="utf-8")

    # --- Model vs Random (practical usefulness) ---
    vs_random_df = run_vs_random(df, n_boot=args.n_boot, seed=args.seed, alpha=args.alpha)
    vs_random_path = output_path.with_name("vs_random_results.csv")
    vs_random_df.to_csv(vs_random_path, index=False, encoding="utf-8-sig")
    print(f"vs-Random results saved to {vs_random_path}")

    vs_random_summary = format_vs_random_summary(vs_random_df)
    print(vs_random_summary)
    vs_random_path.with_suffix(".txt").write_text(vs_random_summary, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
