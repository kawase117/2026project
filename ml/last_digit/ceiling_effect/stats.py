from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd
from scipy import stats

from ml.last_digit.utils import cohens_d, interpret_cohens_d
from .stratifiers import default_evaluators


@dataclass
class StatsConfig:
    n_boot: int = 12000
    seed: int = 20260520
    min_paired_for_wilcoxon: int = 10
    min_unpaired_for_mwu: int = 5


def _safe_mean(values: np.ndarray) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return float("nan")
    return float(arr.mean())


def _bootstrap_delta_ci_paired(
    cur: np.ndarray,
    base: np.ndarray,
    *,
    n_boot: int,
    seed: int,
) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    c = np.asarray(cur, dtype=float)
    b = np.asarray(base, dtype=float)
    mask = np.isfinite(c) & np.isfinite(b)
    c = c[mask]
    b = b[mask]
    if len(c) == 0:
        return float("nan"), float("nan")
    idx = np.arange(len(c))
    deltas = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        s = rng.choice(idx, size=len(idx), replace=True)
        deltas[i] = float(np.mean(c[s] - b[s]))
    return float(np.quantile(deltas, 0.025)), float(np.quantile(deltas, 0.975))


def _bootstrap_delta_ci_unpaired(
    cur: np.ndarray,
    base: np.ndarray,
    *,
    n_boot: int,
    seed: int,
) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    c = np.asarray(cur, dtype=float)
    b = np.asarray(base, dtype=float)
    c = c[np.isfinite(c)]
    b = b[np.isfinite(b)]
    if len(c) == 0 or len(b) == 0:
        return float("nan"), float("nan")
    c_idx = np.arange(len(c))
    b_idx = np.arange(len(b))
    deltas = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        cs = rng.choice(c_idx, size=len(c_idx), replace=True)
        bs = rng.choice(b_idx, size=len(b_idx), replace=True)
        deltas[i] = float(np.mean(c[cs]) - np.mean(b[bs]))
    return float(np.quantile(deltas, 0.025)), float(np.quantile(deltas, 0.975))


def _benjamini_hochberg(p_values: np.ndarray) -> np.ndarray:
    n = len(p_values)
    if n == 0:
        return np.array([], dtype=float)
    order = np.argsort(p_values)
    sorted_p = p_values[order]
    adj = np.empty(n, dtype=float)
    prev = 1.0
    for i in range(n - 1, -1, -1):
        rank = i + 1
        val = sorted_p[i] * n / rank
        prev = min(prev, val)
        adj[i] = min(prev, 1.0)
    out = np.empty(n, dtype=float)
    out[order] = adj
    return out


def _metric_series(df: pd.DataFrame, metric: str) -> np.ndarray:
    if metric == "rank2_rescue_on_miss1":
        sub = df[df["top1_match"] == 0]
        return pd.to_numeric(sub["top2_match"], errors="coerce").to_numpy(dtype=float)
    if metric == "critical_miss_rate":
        return (df["loss_scenario"] == "critical_miss").astype(float).to_numpy(dtype=float)
    return pd.to_numeric(df[metric], errors="coerce").to_numpy(dtype=float)


def _paired_frame(cur_sub: pd.DataFrame, base_sub: pd.DataFrame, metric: str) -> pd.DataFrame:
    if metric == "rank2_rescue_on_miss1":
        c = cur_sub[["date", "expert", "top1_match", "top2_match"]].copy()
        b = base_sub[["date", "expert", "top1_match", "top2_match"]].copy()
        return c.merge(b, on=["date", "expert"], suffixes=("_cur", "_base"))
    if metric == "critical_miss_rate":
        c = cur_sub[["date", "expert", "loss_scenario"]].copy()
        b = base_sub[["date", "expert", "loss_scenario"]].copy()
        c["critical_miss_rate"] = (c["loss_scenario"] == "critical_miss").astype(float)
        b["critical_miss_rate"] = (b["loss_scenario"] == "critical_miss").astype(float)
        return c[["date", "expert", "critical_miss_rate"]].merge(
            b[["date", "expert", "critical_miss_rate"]],
            on=["date", "expert"],
            suffixes=("_cur", "_base"),
        )
    c = cur_sub[["date", "expert", metric, "top1_match", "top2_match"]].copy()
    b = base_sub[["date", "expert", metric, "top1_match", "top2_match"]].copy()
    return c.merge(b, on=["date", "expert"], suffixes=("_cur", "_base"))


def _compute_test(
    cur_sub: pd.DataFrame,
    base_sub: pd.DataFrame,
    metric: str,
    cfg: StatsConfig,
) -> dict[str, float | str | int | bool]:
    paired = _paired_frame(cur_sub, base_sub, metric)
    cur_arr = _metric_series(cur_sub, metric)
    base_arr = _metric_series(base_sub, metric)

    test_type = "mannwhitneyu"
    p_value = float("nan")
    n_paired = 0 if metric == "rank2_rescue_on_miss1" else int(len(paired))

    if n_paired >= cfg.min_paired_for_wilcoxon:
        a = pd.to_numeric(paired[f"{metric}_cur"], errors="coerce").to_numpy(dtype=float)
        b = pd.to_numeric(paired[f"{metric}_base"], errors="coerce").to_numpy(dtype=float)
        mask = np.isfinite(a) & np.isfinite(b)
        a = a[mask]
        b = b[mask]
        if len(a) >= cfg.min_paired_for_wilcoxon and not np.allclose(a - b, 0.0):
            test_type = "wilcoxon"
            p_value = float(stats.wilcoxon(a, b, alternative="two-sided", zero_method="wilcox").pvalue)
            ci_low, ci_high = _bootstrap_delta_ci_paired(a, b, n_boot=cfg.n_boot, seed=cfg.seed)
        else:
            ci_low, ci_high = _bootstrap_delta_ci_unpaired(cur_arr, base_arr, n_boot=cfg.n_boot, seed=cfg.seed)
    else:
        ci_low, ci_high = _bootstrap_delta_ci_unpaired(cur_arr, base_arr, n_boot=cfg.n_boot, seed=cfg.seed)

    if (not np.isfinite(p_value)) and (len(cur_arr) >= cfg.min_unpaired_for_mwu and len(base_arr) >= cfg.min_unpaired_for_mwu):
        test_type = "mannwhitneyu"
        try:
            p_value = float(stats.mannwhitneyu(cur_arr, base_arr, alternative="two-sided").pvalue)
        except Exception:
            p_value = float("nan")

    mean_cur = _safe_mean(cur_arr)
    mean_base = _safe_mean(base_arr)
    delta = float(mean_cur - mean_base) if np.isfinite(mean_cur) and np.isfinite(mean_base) else float("nan")
    d = cohens_d(cur_arr, base_arr)
    return {
        "metric": metric,
        "test_type": test_type,
        "n_current": int(np.isfinite(cur_arr).sum()),
        "n_baseline": int(np.isfinite(base_arr).sum()),
        "n_paired": int(n_paired),
        "mean_current": mean_cur,
        "mean_baseline": mean_base,
        "delta_mean": delta,
        "ci_low": float(ci_low),
        "ci_high": float(ci_high),
        "p_value": float(p_value),
        "cohens_d": float(d),
        "cohens_d_label": interpret_cohens_d(d),
    }


def compute_condition_significance(
    current_loss_df: pd.DataFrame,
    baseline_loss_df: pd.DataFrame,
    *,
    config: StatsConfig | None = None,
    metrics: list[str] | None = None,
) -> pd.DataFrame:
    cfg = config or StatsConfig()
    metric_list = metrics or ["hit_at_2", "loss_value", "critical_miss_rate"]

    rows: list[dict] = []
    for evaluator in default_evaluators():
        cur_groups = evaluator.stratify(current_loss_df)
        base_groups = evaluator.stratify(baseline_loss_df)
        difficulties = sorted(set(cur_groups.keys()) | set(base_groups.keys()))
        for difficulty in difficulties:
            cur_sub = cur_groups.get(difficulty, pd.DataFrame()).copy()
            base_sub = base_groups.get(difficulty, pd.DataFrame()).copy()
            if cur_sub.empty or base_sub.empty:
                continue
            for metric in metric_list:
                row = _compute_test(cur_sub, base_sub, metric, cfg)
                row["condition"] = evaluator.condition_name
                row["difficulty"] = difficulty
                rows.append(row)

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    pvals = pd.to_numeric(out["p_value"], errors="coerce").to_numpy(dtype=float)
    finite_mask = np.isfinite(pvals)
    adj_bonf = np.full(len(out), np.nan, dtype=float)
    adj_bh = np.full(len(out), np.nan, dtype=float)
    if finite_mask.any():
        valid = pvals[finite_mask]
        adj_bonf_vals = np.minimum(valid * len(valid), 1.0)
        adj_bh_vals = _benjamini_hochberg(valid)
        adj_bonf[finite_mask] = adj_bonf_vals
        adj_bh[finite_mask] = adj_bh_vals
    out["p_value_adj_bonferroni"] = adj_bonf
    out["p_value_adj_bh"] = adj_bh
    out["sig_raw_0_05"] = out["p_value"] <= 0.05
    out["sig_bh_0_05"] = out["p_value_adj_bh"] <= 0.05
    out["sig_bonf_0_05"] = out["p_value_adj_bonferroni"] <= 0.05
    return out.sort_values(["condition", "difficulty", "metric"]).reset_index(drop=True)


def generate_summary_report(sig_df: pd.DataFrame) -> str:
    """Generate human-readable summary of significant findings from condition_significance.csv."""
    if sig_df.empty:
        return "No significance results to summarize."

    lines = ["=" * 70, "CEILING EFFECT EVALUATION: CONDITION SIGNIFICANCE SUMMARY", "=" * 70, ""]

    # Significant improvements (BH-adjusted, delta > 0)
    improvements = sig_df[sig_df["sig_bh_0_05"] & (sig_df["delta_mean"] > 0)].sort_values(
        "delta_mean", ascending=False
    )
    if not improvements.empty:
        lines.append("✓ SIGNIFICANT IMPROVEMENTS (BH p < 0.05):")
        for _, row in improvements.iterrows():
            lines.append(
                f"  [{row['condition']:20s} / {row['difficulty']:15s}] {row['metric']:25s}: "
                f"Δ = {row['delta_mean']:+.4f} (CI [{row['ci_low']:+.4f}, {row['ci_high']:+.4f}]), "
                f"Cohen's d = {row['cohens_d']:.3f} ({row['cohens_d_label']})"
            )
        lines.append("")

    # Significant degradations (BH-adjusted, delta < 0)
    degradations = sig_df[sig_df["sig_bh_0_05"] & (sig_df["delta_mean"] < 0)].sort_values(
        "delta_mean", ascending=True
    )
    if not degradations.empty:
        lines.append("✗ SIGNIFICANT DEGRADATIONS (BH p < 0.05):")
        for _, row in degradations.iterrows():
            lines.append(
                f"  [{row['condition']:20s} / {row['difficulty']:15s}] {row['metric']:25s}: "
                f"Δ = {row['delta_mean']:+.4f} (CI [{row['ci_low']:+.4f}, {row['ci_high']:+.4f}]), "
                f"Cohen's d = {row['cohens_d']:.3f} ({row['cohens_d_label']})"
            )
        lines.append("")

    # Trends (raw sig but not after correction)
    trends = sig_df[sig_df["sig_raw_0_05"] & ~sig_df["sig_bh_0_05"]].sort_values(
        "p_value", ascending=True
    )
    if not trends.empty:
        lines.append("~ TRENDS (raw p < 0.05, not BH-significant):")
        for _, row in trends.head(5).iterrows():  # Top 5 only
            lines.append(
                f"  [{row['condition']:20s} / {row['difficulty']:15s}] {row['metric']:25s}: "
                f"Δ = {row['delta_mean']:+.4f}, p = {row['p_value']:.4f}, p_BH = {row['p_value_adj_bh']:.4f}"
            )
        if len(trends) > 5:
            lines.append(f"  ... and {len(trends) - 5} more trend(s)")
        lines.append("")

    # Summary statistics
    lines.append("SUMMARY:")
    lines.append(f"  Total condition-difficulty-metric combinations tested: {len(sig_df)}")
    lines.append(f"  Significant improvements (BH): {len(improvements)}")
    lines.append(f"  Significant degradations (BH): {len(degradations)}")
    lines.append(f"  Trends (raw < 0.05): {len(trends)}")
    lines.append(f"  Tests with p < 0.05 (raw): {(sig_df['sig_raw_0_05']).sum()}")

    # Average effect sizes
    valid_d = sig_df["cohens_d"].dropna()
    if not valid_d.empty:
        lines.append(f"  Average Cohen's d: {valid_d.mean():.3f}")

    lines.append("=" * 70)
    return "\n".join(lines)
