from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import norm
from statsmodels.stats.diagnostic import acorr_ljungbox
from statsmodels.stats.multitest import multipletests
from statsmodels.tsa.stattools import acf


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Analyze correction periodicity from correction timeseries CSV.")
    p.add_argument("--input-csv", required=True, help="Input CSV with columns: date, expert_group, last_digit, correction.")
    p.add_argument("--output-prefix", default="db/experiments/correction_periodicity", help="Output prefix.")
    p.add_argument("--max-lag", type=int, default=30, help="Maximum lag for ACF and Ljung-Box.")
    p.add_argument("--min-samples", type=int, default=20, help="Minimum non-NaN samples per series.")
    return p


def runs_test_signs(values: np.ndarray) -> dict[str, float]:
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 2:
        return {"runs_z": np.nan, "runs_p": np.nan, "n_plus": 0, "n_minus": 0, "n_used": int(len(x))}
    signs = np.sign(x)
    signs = signs[signs != 0]
    if len(signs) < 2:
        return {"runs_z": np.nan, "runs_p": np.nan, "n_plus": int((signs > 0).sum()), "n_minus": int((signs < 0).sum()), "n_used": int(len(signs))}
    runs = int(np.sum(np.diff(signs) != 0) + 1)
    n_plus = int((signs > 0).sum())
    n_minus = int((signs < 0).sum())
    if n_plus == 0 or n_minus == 0:
        return {"runs_z": np.nan, "runs_p": np.nan, "n_plus": n_plus, "n_minus": n_minus, "n_used": int(len(signs))}
    n = n_plus + n_minus
    expected_runs = (2.0 * n_plus * n_minus) / n + 1.0
    var_runs = (2.0 * n_plus * n_minus * (2.0 * n_plus * n_minus - n_plus - n_minus)) / (n * n * (n - 1))
    if var_runs <= 0:
        return {"runs_z": np.nan, "runs_p": np.nan, "n_plus": n_plus, "n_minus": n_minus, "n_used": int(len(signs))}
    z = (runs - expected_runs) / np.sqrt(var_runs)
    p = 2.0 * (1.0 - norm.cdf(abs(z)))
    return {"runs_z": float(z), "runs_p": float(p), "n_plus": n_plus, "n_minus": n_minus, "n_used": int(len(signs))}


def analyze_series(df: pd.DataFrame, max_lag: int, min_samples: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    acf_rows: list[dict[str, Any]] = []
    for (expert_group, last_digit), g in df.groupby(["expert_group", "last_digit"], sort=True):
        series = pd.to_numeric(g["correction"], errors="coerce").dropna().to_numpy(dtype=float)
        n = len(series)
        if n < int(min_samples):
            continue
        lag_max = int(min(max_lag, max(1, n - 1)))
        acf_vals = acf(series, nlags=lag_max, fft=False)
        lb = acorr_ljungbox(series, lags=list(range(1, lag_max + 1)), return_df=True)
        lb_p_min = float(lb["lb_pvalue"].min()) if not lb.empty else np.nan
        sig_thr = 1.96 / np.sqrt(n)
        sig_lags = [lag for lag in range(1, len(acf_vals)) if abs(acf_vals[lag]) > sig_thr]
        est_cycle = int(sig_lags[0]) if sig_lags else np.nan
        runs = runs_test_signs(series)
        rows.append(
            {
                "expert_group": expert_group,
                "last_digit": int(last_digit),
                "n_samples": int(n),
                "acf_sig_threshold": float(sig_thr),
                "acf_lag1": float(acf_vals[1]) if len(acf_vals) > 1 else np.nan,
                "acf_lag2": float(acf_vals[2]) if len(acf_vals) > 2 else np.nan,
                "acf_lag3": float(acf_vals[3]) if len(acf_vals) > 3 else np.nan,
                "ljungbox_p_min": lb_p_min,
                "estimated_cycle_lag": est_cycle,
                "runs_z": runs["runs_z"],
                "runs_p": runs["runs_p"],
                "n_plus": runs["n_plus"],
                "n_minus": runs["n_minus"],
            }
        )
        for lag in range(1, len(acf_vals)):
            acf_rows.append(
                {
                    "expert_group": expert_group,
                    "last_digit": int(last_digit),
                    "lag": int(lag),
                    "acf": float(acf_vals[lag]),
                    "significant": int(abs(acf_vals[lag]) > sig_thr),
                }
            )
    summary = pd.DataFrame(rows)
    if not summary.empty:
        lb_mask = summary["ljungbox_p_min"].notna()
        summary["ljungbox_fdr_bh"] = np.nan
        if lb_mask.any():
            _, p_adj, _, _ = multipletests(summary.loc[lb_mask, "ljungbox_p_min"].to_numpy(dtype=float), method="fdr_bh")
            summary.loc[lb_mask, "ljungbox_fdr_bh"] = p_adj
        runs_mask = summary["runs_p"].notna()
        summary["runs_fdr_bh"] = np.nan
        if runs_mask.any():
            _, p_adj, _, _ = multipletests(summary.loc[runs_mask, "runs_p"].to_numpy(dtype=float), method="fdr_bh")
            summary.loc[runs_mask, "runs_fdr_bh"] = p_adj
        summary["periodicity_flag"] = (
            (summary["ljungbox_fdr_bh"] < 0.05) | (summary["runs_fdr_bh"] < 0.05)
        ).astype(int)
    return summary, pd.DataFrame(acf_rows)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    inp = Path(args.input_csv)
    if not inp.exists():
        raise FileNotFoundError(f"Input CSV not found: {inp}")
    df = pd.read_csv(inp)
    need = {"date", "expert_group", "last_digit", "correction"}
    missing = need - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["expert_group", "last_digit", "date"]).reset_index(drop=True)

    summary, acf_table = analyze_series(df, max_lag=int(args.max_lag), min_samples=int(args.min_samples))
    out_base = Path(args.output_prefix)
    out_base.parent.mkdir(parents=True, exist_ok=True)
    summary_path = out_base.with_name(out_base.name + "_summary.csv")
    acf_path = out_base.with_name(out_base.name + "_acf.csv")
    summary.to_csv(summary_path, index=False, encoding="utf-8")
    acf_table.to_csv(acf_path, index=False, encoding="utf-8")

    n_series = int(len(summary))
    n_periodic = int(summary["periodicity_flag"].sum()) if n_series > 0 and "periodicity_flag" in summary.columns else 0
    print(f"Analyzed series: {n_series}")
    print(f"Periodicity-flagged series: {n_periodic}")
    print(f"Summary: {summary_path}")
    print(f"ACF table: {acf_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

