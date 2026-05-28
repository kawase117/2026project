from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr, ttest_ind
from statsmodels.stats.multitest import multipletests

# Fix import path for absolute module imports when run as main script
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ml.last_digit import zorome_strategy_simulation as zsim


def _is_zorome_machine(machine_number: int) -> bool:
    tail2 = abs(int(machine_number)) % 100
    return (tail2 // 10) == (tail2 % 10)


def _apply_fdr(df: pd.DataFrame, p_col: str = "p_value_raw", out_col: str = "p_value_fdr") -> pd.DataFrame:
    out = df.copy()
    out[out_col] = np.nan
    if out.empty or p_col not in out.columns:
        return out
    mask = pd.to_numeric(out[p_col], errors="coerce").notna()
    if not mask.any():
        return out
    pvals = pd.to_numeric(out.loc[mask, p_col], errors="coerce").to_numpy(dtype=float)
    _rej, p_adj, _a, _b = multipletests(pvals, method="fdr_bh")
    out.loc[mask, out_col] = p_adj
    return out


def _weekday_order() -> list[str]:
    return ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def build_machine_correction_table(df: pd.DataFrame, weekday: str | None = None) -> pd.DataFrame:
    work = df.copy()
    if weekday is not None:
        work = work[work["weekday"] == str(weekday)].copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "machine_number",
                "last_digit",
                "group_key",
                "weekday",
                "zorome_avg",
                "nonzorome_avg",
                "correction",
                "n_zorome",
                "n_nonzorome",
                "t_stat",
                "p_value_raw",
                "p_value_fdr",
            ]
        )

    work["is_zorome_machine"] = work["machine_number"].astype(int).map(_is_zorome_machine).astype(int)
    target_machines = sorted(work.loc[work["is_zorome_machine"] == 1, "machine_number"].astype(int).unique().tolist())
    rows: list[dict[str, Any]] = []
    for mnum in target_machines:
        mrows = work[work["machine_number"].astype(int) == int(mnum)].copy()
        if mrows.empty:
            continue
        last_digit = int(pd.to_numeric(mrows["last_digit"], errors="coerce").iloc[0])
        group_key = str(mrows["group_key"].iloc[0])
        zvals = pd.to_numeric(mrows.loc[mrows["is_zorome"] == 1, "diff_coins_normalized"], errors="coerce").dropna().to_numpy(dtype=float)
        peers = work[
            (work["group_key"].astype(str) == group_key)
            & (pd.to_numeric(work["last_digit"], errors="coerce") == last_digit)
            & (work["is_zorome"] == 0)
            & (work["machine_number"].astype(int) != int(mnum))
        ].copy()
        nzvals = pd.to_numeric(peers["diff_coins_normalized"], errors="coerce").dropna().to_numpy(dtype=float)

        z_mean = float(np.mean(zvals)) if len(zvals) > 0 else np.nan
        nz_mean = float(np.mean(nzvals)) if len(nzvals) > 0 else np.nan
        corr = (z_mean - nz_mean) if (np.isfinite(z_mean) and np.isfinite(nz_mean)) else np.nan

        if len(zvals) >= 2 and len(nzvals) >= 2:
            t_stat, p_raw = ttest_ind(zvals, nzvals, equal_var=False, nan_policy="omit")
            t_stat = float(t_stat) if np.isfinite(t_stat) else np.nan
            p_raw = float(p_raw) if np.isfinite(p_raw) else np.nan
        else:
            t_stat, p_raw = np.nan, np.nan

        rows.append(
            {
                "machine_number": int(mnum),
                "last_digit": int(last_digit),
                "group_key": group_key,
                "weekday": "all" if weekday is None else str(weekday),
                "zorome_avg": z_mean,
                "nonzorome_avg": nz_mean,
                "correction": corr,
                "n_zorome": int(len(zvals)),
                "n_nonzorome": int(len(nzvals)),
                "t_stat": t_stat,
                "p_value_raw": p_raw,
            }
        )
    out = pd.DataFrame(rows)
    out = _apply_fdr(out, p_col="p_value_raw", out_col="p_value_fdr")
    if out.empty:
        return out
    return out.sort_values(["weekday", "correction"], ascending=[True, False]).reset_index(drop=True)


def check_temporal_stability(df: pd.DataFrame) -> pd.DataFrame:
    dates = sorted(pd.to_datetime(df["date"]).drop_duplicates().tolist())
    if len(dates) < 4:
        return pd.DataFrame(
            columns=[
                "machine_number",
                "last_digit",
                "correction_first_half",
                "correction_second_half",
                "sign_consistent",
                "rank_corr",
                "rank_corr_p",
            ]
        )
    split_idx = len(dates) // 2
    first_dates = set(dates[:split_idx])
    second_dates = set(dates[split_idx:])

    first = build_machine_correction_table(df[df["date"].isin(first_dates)].copy(), weekday=None)[["machine_number", "last_digit", "correction"]].rename(
        columns={"correction": "correction_first_half"}
    )
    second = build_machine_correction_table(df[df["date"].isin(second_dates)].copy(), weekday=None)[["machine_number", "last_digit", "correction"]].rename(
        columns={"correction": "correction_second_half"}
    )
    merged = first.merge(second, on=["machine_number", "last_digit"], how="outer")

    def _consistent(a: float, b: float) -> bool:
        if not np.isfinite(a) or not np.isfinite(b):
            return False
        if a == 0.0 and b == 0.0:
            return True
        if a == 0.0 or b == 0.0:
            return False
        return np.sign(a) == np.sign(b)

    merged["sign_consistent"] = [
        _consistent(float(a) if np.isfinite(a) else np.nan, float(b) if np.isfinite(b) else np.nan)
        for a, b in zip(
            pd.to_numeric(merged["correction_first_half"], errors="coerce").to_numpy(dtype=float),
            pd.to_numeric(merged["correction_second_half"], errors="coerce").to_numpy(dtype=float),
        )
    ]

    valid = merged[
        pd.to_numeric(merged["correction_first_half"], errors="coerce").notna()
        & pd.to_numeric(merged["correction_second_half"], errors="coerce").notna()
    ].copy()
    if len(valid) >= 3:
        r, p = spearmanr(
            pd.to_numeric(valid["correction_first_half"], errors="coerce").to_numpy(dtype=float),
            pd.to_numeric(valid["correction_second_half"], errors="coerce").to_numpy(dtype=float),
        )
        r = float(r) if np.isfinite(r) else np.nan
        p = float(p) if np.isfinite(p) else np.nan
    else:
        r, p = np.nan, np.nan
    merged["rank_corr"] = r
    merged["rank_corr_p"] = p
    return merged.sort_values(["machine_number"]).reset_index(drop=True)


def compare_correction_granularity(machine_table: pd.DataFrame, digit_table: pd.DataFrame) -> pd.DataFrame:
    mt = machine_table.copy()
    dt = digit_table.copy()
    if mt.empty:
        return pd.DataFrame(
            columns=[
                "last_digit",
                "digit_correction",
                "machine_correction_max",
                "machine_correction_min",
                "machine_correction_std",
                "n_zorome_machines",
            ]
        )
    mt = mt[mt["weekday"].astype(str) == "all"].copy()
    g = (
        mt.groupby("last_digit", sort=True)
        .agg(
            machine_correction_max=("correction", "max"),
            machine_correction_min=("correction", "min"),
            machine_correction_std=("correction", "std"),
            n_zorome_machines=("machine_number", "nunique"),
        )
        .reset_index()
    )
    if dt.empty:
        g["digit_correction"] = np.nan
        return g
    dt2 = dt[["last_digit", "digit_correction"]].copy()
    dt2 = dt2.drop_duplicates(subset=["last_digit"])
    out = g.merge(dt2, on="last_digit", how="left")
    return out[
        [
            "last_digit",
            "digit_correction",
            "machine_correction_max",
            "machine_correction_min",
            "machine_correction_std",
            "n_zorome_machines",
        ]
    ].sort_values("last_digit").reset_index(drop=True)


def _build_digit_level_correction_table(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for digit, g in df.groupby("last_digit", sort=True):
        z = pd.to_numeric(g.loc[g["is_zorome"] == 1, "diff_coins_normalized"], errors="coerce").dropna().to_numpy(dtype=float)
        nz = pd.to_numeric(g.loc[g["is_zorome"] == 0, "diff_coins_normalized"], errors="coerce").dropna().to_numpy(dtype=float)
        z_mean = float(np.mean(z)) if len(z) > 0 else np.nan
        nz_mean = float(np.mean(nz)) if len(nz) > 0 else np.nan
        corr = (z_mean - nz_mean) if (np.isfinite(z_mean) and np.isfinite(nz_mean)) else np.nan
        rows.append({"last_digit": int(digit), "digit_correction": corr, "n_zorome_rows": len(z), "n_nonzorome_rows": len(nz)})
    return pd.DataFrame(rows).sort_values("last_digit").reset_index(drop=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Machine-level correction analysis for zorome effect.")
    p.add_argument("--db-path", required=True, help="SQLite DB path.")
    p.add_argument("--output-dir", required=True, help="Output directory.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db_path = Path(args.db_path)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = zsim.load_machine_level_data(db_path)
    dates = sorted(pd.to_datetime(df["date"]).drop_duplicates().tolist())
    zorome_machines = sorted(df.loc[df["machine_number"].astype(int).map(_is_zorome_machine), "machine_number"].astype(int).unique().tolist())

    all_week = build_machine_correction_table(df, weekday=None)
    all_path = out_dir / "machine_correction_all_weekdays.csv"
    all_week.to_csv(all_path, index=False, encoding="utf-8")

    by_week_rows: list[pd.DataFrame] = []
    for wd in _weekday_order():
        by_week_rows.append(build_machine_correction_table(df, weekday=wd))
    by_week = pd.concat(by_week_rows, ignore_index=True) if by_week_rows else pd.DataFrame()
    by_week = _apply_fdr(by_week, p_col="p_value_raw", out_col="p_value_fdr")
    by_week_path = out_dir / "machine_correction_by_weekday.csv"
    by_week.to_csv(by_week_path, index=False, encoding="utf-8")

    stability = check_temporal_stability(df)
    stability_path = out_dir / "machine_correction_stability.csv"
    stability.to_csv(stability_path, index=False, encoding="utf-8")

    digit_table = _build_digit_level_correction_table(df)
    granularity = compare_correction_granularity(all_week, digit_table)
    granularity_path = out_dir / "machine_vs_digit_granularity.csv"
    granularity.to_csv(granularity_path, index=False, encoding="utf-8")

    sig = all_week[pd.to_numeric(all_week["p_value_fdr"], errors="coerce") < 0.05].copy()
    sig_pos = sig[pd.to_numeric(sig["correction"], errors="coerce") > 0]
    sig_neg = sig[pd.to_numeric(sig["correction"], errors="coerce") < 0]
    top5 = all_week.sort_values("correction", ascending=False).head(5)
    bot5 = all_week.sort_values("correction", ascending=True).head(5)

    print("=== Machine-Level Correction Analysis ===")
    print(f"DB: {db_path.name}")
    print(f"Total zorome machines: {len(zorome_machines)}")
    print(f"Total days: {len(dates)}")
    print("--- Analysis 1: All weekdays ---")
    print(f"FDR significant (p_fdr < 0.05): {len(sig)} / {len(all_week)}")
    print(f"  positive correction: {len(sig_pos)} machines")
    print(f"  negative correction: {len(sig_neg)} machines")
    print("Top5 zorome machines:")
    for _, r in top5.iterrows():
        print(f"  {int(r['machine_number'])}: correction={float(r['correction']):+.2f}, p_fdr={r['p_value_fdr']}")
    print("Bottom5 zorome machines:")
    for _, r in bot5.iterrows():
        print(f"  {int(r['machine_number'])}: correction={float(r['correction']):+.2f}, p_fdr={r['p_value_fdr']}")
    print("--- Analysis 2: Temporal stability ---")
    consistent = int(stability["sign_consistent"].fillna(False).astype(bool).sum()) if not stability.empty else 0
    total_stability = int(len(stability))
    pct = (100.0 * consistent / total_stability) if total_stability > 0 else np.nan
    rank_corr = float(stability["rank_corr"].iloc[0]) if not stability.empty else np.nan
    rank_corr_p = float(stability["rank_corr_p"].iloc[0]) if not stability.empty else np.nan
    print(f"Sign-consistent machines: {consistent} / {total_stability} ({pct:.1f}%)" if np.isfinite(pct) else "Sign-consistent machines: NA")
    print(f"Spearman correlation (first vs second half): r={rank_corr}, p={rank_corr_p}")
    print("--- Analysis 3: In-digit variability ---")
    gv = granularity.sort_values("machine_correction_std", ascending=False).head(5)
    for _, r in gv.iterrows():
        print(f"  digit {int(r['last_digit'])}: std={float(r['machine_correction_std']):.2f}")
    print(f"Output: {all_path}")
    print(f"Output: {by_week_path}")
    print(f"Output: {stability_path}")
    print(f"Output: {granularity_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

