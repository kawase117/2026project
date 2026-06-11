"""
Stage 1: Hall-level signal existence tests (all 9 halls)
Stage 2: Baseline comparison (random / hist-best / weekday-fixed / current model)

Purpose
-------
Determine whether the current ML approach (chosen_avg_diff=123) beats
simple baselines, and whether there are any detectable calendar/temporal
signals per hall at the hall-selection level (NOT tail/machine-level).

Codex pre-check corrections applied:
  #1  Run random/hist-best/weekday baselines before concluding vs random
  #2  Use hall-level targets (>=100/200/300, daily rank) not LTR experts
  #3  Power analysis: "no signal" vs "undetectable" distinction

Outputs (--output-root)
-----------------------
  hall_signal_tests_raw.csv       -- raw p-values per hall x test
  hall_power_analysis.csv         -- MDE per hall x threshold
  signal_judgment_table.csv       -- SIGNAL_DETECTED / UNDETECTABLE / NO_SIGNAL
  baseline_comparison.csv         -- 5 strategies compared on holdout
  run_summary.json                -- key numbers for quick review
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import binomtest, norm, spearmanr


THRESHOLDS = (100, 200, 300)
LAGS = (1, 2, 3, 7)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Stage 1+2: Hall-level signal existence + baseline comparison."
    )
    p.add_argument("--db-dir", default="db")
    p.add_argument("--db-glob", default="*.db")
    p.add_argument("--exclude-db", default="integrated.db",
                   help="Comma-separated DB filenames to skip.")
    p.add_argument("--selection-start", default="2025-07-07")
    p.add_argument("--selection-end", default="2025-12-31")
    p.add_argument("--holdout-start", default="2026-01-01")
    p.add_argument("--holdout-end", default="2026-05-30")
    p.add_argument("--topk-dd", type=int, default=5,
                   help="Top-k DD values (day-of-month) for calendar rule.")
    p.add_argument("--min-dd-days", type=int, default=6,
                   help="Min observations per DD to be included in topk.")
    p.add_argument("--seed", type=int, default=20260602)
    p.add_argument("--n-random-reps", type=int, default=2000,
                   help="Monte Carlo repetitions for random baseline.")
    p.add_argument(
        "--current-model-plan",
        default=(
            "db/experiments/hall_practical_strategy_followup_20260602"
            "/allhall_daily_decision_plan.csv"
        ),
        help="Path to existing model's decision plan CSV.",
    )
    p.add_argument("--output-root",
                   default="db/experiments/hall_signal_baseline_20260602")
    return p


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_hall_daily(db_path: Path) -> pd.DataFrame:
    """Load daily_hall_summary for a single hall DB."""
    con = sqlite3.connect(str(db_path))
    q = """
    SELECT
        date,
        avg_diff_per_machine,
        avg_games_per_machine,
        total_machines,
        win_rate,
        COALESCE(is_any_event, 0) AS is_any_event
    FROM daily_hall_summary
    ORDER BY date
    """
    df = pd.read_sql_query(q, con)
    con.close()
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
    df = df[df["date"].notna()].copy()
    for col in ("avg_diff_per_machine", "avg_games_per_machine",
                "total_machines", "win_rate"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    df["is_any_event"] = (
        pd.to_numeric(df["is_any_event"], errors="coerce").fillna(0).astype(int)
    )
    df["weekday"] = df["date"].dt.weekday.astype(int)  # 0=Mon, 6=Sun
    df["dd"] = df["date"].dt.day.astype(int)
    df["mm"] = df["date"].dt.month.astype(int)
    df["is_zorome_day"] = df["dd"].isin([11, 22]).astype(int)
    df["is_strong_zorome_day"] = (df["dd"] == df["mm"]).astype(int)
    df["store"] = db_path.stem
    return df.sort_values("date").reset_index(drop=True)


def load_all_halls(db_dir: Path, glob: str, exclude: set[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for db_path in sorted(db_dir.glob(glob)):
        if db_path.name in exclude:
            continue
        try:
            df = _load_hall_daily(db_path)
            if not df.empty:
                frames.append(df)
                print(f"  loaded {db_path.name}  ({len(df)} rows)")
        except Exception as exc:
            print(f"  WARN: {db_path.name}: {exc}")
    if not frames:
        raise RuntimeError("No hall data loaded — check --db-dir and --db-glob.")
    panel = pd.concat(frames, ignore_index=True).sort_values(["date", "store"])
    return panel


def add_daily_rank(panel: pd.DataFrame) -> pd.DataFrame:
    """Add daily_rank (1=highest diff that day) among all halls."""
    p = panel.copy()
    p["daily_rank"] = (
        p.groupby("date", sort=False)["avg_diff_per_machine"]
        .rank(method="min", ascending=False)
        .astype(int)
    )
    p["n_halls_that_day"] = p.groupby("date", sort=False)["store"].transform("count")
    return p


# ---------------------------------------------------------------------------
# Stage 1 helpers
# ---------------------------------------------------------------------------

def _spearman_rho_pval(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 5:
        return float("nan"), float("nan")
    rho, pv = spearmanr(x[mask], y[mask])
    return float(rho), float(pv)


def _mde_binary(n: int, p0: float, alpha: float = 0.05,
                power: float = 0.80) -> float:
    """Minimum detectable absolute effect for one-sided binomial test."""
    if n <= 0 or not (0.0 < p0 < 1.0):
        return float("nan")
    z_alpha = norm.ppf(1.0 - alpha)
    z_beta = norm.ppf(power)
    se0 = np.sqrt(p0 * (1.0 - p0) / n)
    return float((z_alpha + z_beta) * se0)


# ---------------------------------------------------------------------------
# Stage 1: Signal tests per hall
# ---------------------------------------------------------------------------

def _test_rank_autocorr(hall_sel: pd.DataFrame) -> list[dict[str, Any]]:
    """Spearman autocorrelation of daily hall rank at various lags."""
    rows: list[dict[str, Any]] = []
    ranks = hall_sel.sort_values("date")["daily_rank"].values.astype(float)
    for lag in LAGS:
        if len(ranks) <= lag:
            continue
        rho, pv = _spearman_rho_pval(ranks[:-lag], ranks[lag:])
        rows.append({
            "test_type": f"rank_autocorr_lag{lag}",
            "lag": lag,
            "rule": None,
            "threshold": None,
            "rho": rho,
            "n_rule_days": int(len(ranks) - lag),
            "base_rate": float("nan"),
            "precision": float("nan"),
            "lift": float("nan"),
            "p_value": pv,
        })
    return rows


def _test_calendar_precision(
    hall_sel: pd.DataFrame,
    topk_dd: int,
    min_dd_days: int,
) -> list[dict[str, Any]]:
    """
    For each calendar rule x threshold, one-sided binomial test:
    H0: precision == base_rate  (rule has no lift)
    H1: precision > base_rate   (rule selects high-diff days)
    Uses selection period only to avoid holdout peek.
    """
    rows: list[dict[str, Any]] = []

    # Calendar rule metadata from selection period only
    wday_mean = hall_sel.groupby("weekday")["avg_diff_per_machine"].mean()
    best_weekday = int(wday_mean.idxmax()) if not wday_mean.empty else -1

    dd_stats = (
        hall_sel.groupby("dd")["avg_diff_per_machine"]
        .agg(["mean", "count"])
        .reset_index()
    )
    topk_dd_vals: list[int] = (
        dd_stats[dd_stats["count"] >= min_dd_days]
        .sort_values("mean", ascending=False)
        .head(topk_dd)["dd"]
        .astype(int)
        .tolist()
    )

    rule_masks: dict[str, pd.Series] = {
        "best_weekday": (hall_sel["weekday"] == best_weekday),
        "dd_topk": hall_sel["dd"].isin(topk_dd_vals),
        "zorome_day": (hall_sel["is_zorome_day"] == 1),
        "strong_zorome": (hall_sel["is_strong_zorome_day"] == 1),
        "event_only": (hall_sel["is_any_event"] == 1),
    }

    for thr in THRESHOLDS:
        target = (hall_sel["avg_diff_per_machine"] >= thr).astype(int)
        base_rate = float(target.mean())
        n_total = len(target)

        for rule_name, mask in rule_masks.items():
            n_rule = int(mask.sum())
            if n_rule < 3:
                rows.append({
                    "test_type": f"cal_prec_{rule_name}_ge{thr}",
                    "lag": None,
                    "rule": rule_name,
                    "threshold": thr,
                    "rho": float("nan"),
                    "n_rule_days": n_rule,
                    "base_rate": base_rate,
                    "precision": float("nan"),
                    "lift": float("nan"),
                    "p_value": float("nan"),
                })
                continue

            n_hit = int(target[mask].sum())
            prec = n_hit / n_rule
            try:
                pv = binomtest(
                    n_hit, n_rule, p=base_rate, alternative="greater"
                ).pvalue
            except Exception:
                pv = float("nan")

            rows.append({
                "test_type": f"cal_prec_{rule_name}_ge{thr}",
                "lag": None,
                "rule": rule_name,
                "threshold": thr,
                "rho": float("nan"),
                "n_rule_days": n_rule,
                "base_rate": base_rate,
                "precision": prec,
                "lift": prec - base_rate,
                "p_value": pv,
            })
    return rows


def run_all_signal_tests(
    panel_sel: pd.DataFrame,
    topk_dd: int,
    min_dd_days: int,
) -> pd.DataFrame:
    """Run signal tests for every hall. Returns raw results (no Bonferroni)."""
    all_rows: list[dict[str, Any]] = []
    for store, g in panel_sel.groupby("store"):
        g = g.sort_values("date").reset_index(drop=True)
        for row in _test_rank_autocorr(g):
            row["store"] = store
            all_rows.append(row)
        for row in _test_calendar_precision(
            g, topk_dd=topk_dd, min_dd_days=min_dd_days
        ):
            row["store"] = store
            all_rows.append(row)
    return pd.DataFrame(all_rows)


def apply_bonferroni_per_hall(
    signal_df: pd.DataFrame, alpha: float = 0.05
) -> pd.DataFrame:
    """Bonferroni correction within each hall independently."""
    frames: list[pd.DataFrame] = []
    for store, g in signal_df.groupby("store"):
        g = g.copy()
        n_tests = int(g["p_value"].notna().sum())
        bonf_thr = alpha / max(n_tests, 1)
        g["n_tests_hall"] = n_tests
        g["bonf_threshold"] = bonf_thr
        g["p_bonferroni"] = (g["p_value"] * n_tests).clip(upper=1.0)
        g["is_significant_bonf"] = (g["p_bonferroni"] < alpha).astype(int)
        frames.append(g)
    return pd.concat(frames, ignore_index=True)


def compute_power_analysis(
    panel_sel: pd.DataFrame, n_holdout: int
) -> pd.DataFrame:
    """MDE per hall x threshold (for binary hit-rate tests)."""
    rows: list[dict[str, Any]] = []
    for store, g in panel_sel.groupby("store"):
        for thr in THRESHOLDS:
            base_rate = float((g["avg_diff_per_machine"] >= thr).mean())
            mde = _mde_binary(n_holdout, base_rate)
            rows.append({
                "store": store,
                "threshold": thr,
                "base_rate_sel": base_rate,
                "n_sel_days": len(g),
                "n_holdout_days": n_holdout,
                "mde_abs": mde,
                "note": (
                    "underpowered (MDE>15%)"
                    if (np.isfinite(mde) and mde > 0.15)
                    else "powered"
                ),
            })
    return pd.DataFrame(rows)


def build_judgment_table(
    signal_df: pd.DataFrame, power_df: pd.DataFrame
) -> pd.DataFrame:
    """Final SIGNAL_DETECTED / UNDETECTABLE / NO_SIGNAL per hall."""
    sig_counts = (
        signal_df[signal_df["is_significant_bonf"] == 1]
        .groupby("store").size()
        .reset_index(name="n_significant_bonf")
    )
    total_counts = (
        signal_df.groupby("store").size()
        .reset_index(name="n_total_tests")
    )
    best_p = (
        signal_df.groupby("store")["p_bonferroni"].min()
        .reset_index(name="best_p_bonferroni")
    )
    avg_mde = (
        power_df.groupby("store")["mde_abs"].mean()
        .reset_index(name="avg_mde_abs")
    )

    j = (
        total_counts
        .merge(sig_counts, on="store", how="left")
        .merge(best_p, on="store", how="left")
        .merge(avg_mde, on="store", how="left")
    )
    j["n_significant_bonf"] = j["n_significant_bonf"].fillna(0).astype(int)

    def _judge(row: pd.Series) -> str:
        if row["n_significant_bonf"] > 0:
            return "SIGNAL_DETECTED"
        if pd.notna(row["avg_mde_abs"]) and row["avg_mde_abs"] > 0.15:
            return "UNDETECTABLE (low power)"
        return "NO_SIGNAL"

    j["judgment"] = j.apply(_judge, axis=1)
    return j.sort_values("best_p_bonferroni").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Stage 2: Baselines
# ---------------------------------------------------------------------------

def _diff_stats(diffs: np.ndarray) -> dict[str, float]:
    diffs = np.asarray(diffs, dtype=float)
    diffs = diffs[np.isfinite(diffs)]
    if diffs.size == 0:
        return {
            "chosen_avg_diff_mean": float("nan"),
            "chosen_avg_diff_std": float("nan"),
            "chosen_hit_ge_100_rate": float("nan"),
            "chosen_hit_ge_200_rate": float("nan"),
            "chosen_hit_ge_300_rate": float("nan"),
        }
    return {
        "chosen_avg_diff_mean": float(np.mean(diffs)),
        "chosen_avg_diff_std": float(np.std(diffs)),
        "chosen_hit_ge_100_rate": float(np.mean(diffs >= 100)),
        "chosen_hit_ge_200_rate": float(np.mean(diffs >= 200)),
        "chosen_hit_ge_300_rate": float(np.mean(diffs >= 300)),
    }


def baseline_oracle(panel_ho: pd.DataFrame) -> dict[str, Any]:
    daily_max = (
        panel_ho.groupby("date")["avg_diff_per_machine"].max().values
    )
    return {"strategy": "oracle", "n_days": len(daily_max),
            **_diff_stats(daily_max)}


def baseline_random(
    panel_ho: pd.DataFrame, *, seed: int, n_reps: int
) -> dict[str, Any]:
    """Vectorised Monte Carlo: pick random hall each day n_reps times."""
    stores = sorted(panel_ho["store"].unique())
    dates = sorted(panel_ho["date"].unique())
    n_days, n_stores = len(dates), len(stores)

    pivot = (
        panel_ho
        .pivot(index="date", columns="store", values="avg_diff_per_machine")
        .reindex(index=dates, columns=stores)
    )
    matrix = pivot.values  # (n_days, n_stores)

    rng = np.random.default_rng(seed)
    choices = rng.integers(0, n_stores, size=(n_reps, n_days))
    row_idx = np.arange(n_days)[None, :]
    selected = matrix[row_idx, choices]  # (n_reps, n_days)

    rep_means = np.nanmean(selected, axis=1)
    all_flat = selected.ravel()
    return {
        "strategy": "random",
        "n_days": n_days,
        "n_reps": n_reps,
        "chosen_avg_diff_mean": float(np.nanmean(rep_means)),
        "chosen_avg_diff_std": float(np.nanstd(rep_means)),
        "chosen_hit_ge_100_rate": float(np.nanmean(all_flat >= 100)),
        "chosen_hit_ge_200_rate": float(np.nanmean(all_flat >= 200)),
        "chosen_hit_ge_300_rate": float(np.nanmean(all_flat >= 300)),
    }


def baseline_historical_best_fixed(
    panel_sel: pd.DataFrame, panel_ho: pd.DataFrame
) -> dict[str, Any]:
    """Always pick the hall with highest mean diff in selection period."""
    hall_avg = panel_sel.groupby("store")["avg_diff_per_machine"].mean()
    best_hall = str(hall_avg.idxmax())
    diffs = panel_ho[panel_ho["store"] == best_hall][
        "avg_diff_per_machine"
    ].values
    return {
        "strategy": "historical_best_fixed",
        "best_hall": best_hall,
        "n_days": len(diffs),
        **_diff_stats(diffs),
    }


def baseline_weekday_fixed(
    panel_sel: pd.DataFrame, panel_ho: pd.DataFrame
) -> dict[str, Any]:
    """For each weekday, pick hall with best selection-period avg on that day."""
    wday_avg = (
        panel_sel.groupby(["weekday", "store"])["avg_diff_per_machine"]
        .mean()
        .reset_index()
    )
    best_per_wday: dict[int, str] = (
        wday_avg.sort_values("avg_diff_per_machine", ascending=False)
        .drop_duplicates("weekday")
        .set_index("weekday")["store"]
        .to_dict()
    )

    dates = sorted(panel_ho["date"].unique())
    diffs: list[float] = []
    for date in dates:
        day_df = panel_ho[panel_ho["date"] == date]
        if day_df.empty:
            continue
        wday = int(day_df.iloc[0]["weekday"])
        chosen = best_per_wday.get(wday)
        if chosen is None:
            continue
        match = day_df[day_df["store"] == chosen]
        if match.empty:
            continue
        diffs.append(float(match.iloc[0]["avg_diff_per_machine"]))

    return {
        "strategy": "weekday_fixed",
        "best_hall_per_weekday": str(
            {k: v for k, v in sorted(best_per_wday.items())}
        ),
        "n_days": len(diffs),
        **_diff_stats(np.array(diffs)),
    }


def load_current_model(
    plan_path: Path, panel_ho: pd.DataFrame
) -> dict[str, Any]:
    """Load chosen_actual_avg_diff from allhall_daily_decision_plan.csv."""
    if not plan_path.exists():
        return {"strategy": "current_model",
                "error": f"not found: {plan_path}"}
    plan = pd.read_csv(plan_path, encoding="utf-8-sig")
    plan["date"] = pd.to_datetime(plan["date"], errors="coerce")
    plan = plan[plan["date"].notna()].copy()
    ho_dates = set(panel_ho["date"].unique())
    plan = plan[plan["date"].isin(ho_dates)]
    if plan.empty:
        return {"strategy": "current_model", "error": "no holdout rows"}
    diffs = pd.to_numeric(
        plan["chosen_actual_avg_diff_per_machine"], errors="coerce"
    ).values
    return {"strategy": "current_model", "n_days": len(plan),
            **_diff_stats(diffs)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = build_parser().parse_args()

    db_dir = Path(args.db_dir)
    exclude = {x.strip() for x in args.exclude_db.split(",") if x.strip()}
    out_dir = Path(args.output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- Load panel ----
    print("=== Loading hall data ===")
    panel = load_all_halls(db_dir, args.db_glob, exclude)
    panel = add_daily_rank(panel)

    sel_start = pd.Timestamp(args.selection_start)
    sel_end = pd.Timestamp(args.selection_end)
    ho_start = pd.Timestamp(args.holdout_start)
    ho_end = pd.Timestamp(args.holdout_end)

    panel_sel = panel[
        (panel["date"] >= sel_start) & (panel["date"] <= sel_end)
    ].copy()
    panel_ho = panel[
        (panel["date"] >= ho_start) & (panel["date"] <= ho_end)
    ].copy()

    n_halls = panel_sel["store"].nunique()
    n_sel = panel_sel["date"].nunique()
    n_ho = panel_ho["date"].nunique()
    print(f"\n  halls={n_halls}  selection={n_sel}d  holdout={n_ho}d\n")

    # ---- Stage 1 ----
    print("=== Stage 1: Signal existence tests ===")
    signal_raw = run_all_signal_tests(
        panel_sel, args.topk_dd, args.min_dd_days
    )
    signal_df = apply_bonferroni_per_hall(signal_raw)
    power_df = compute_power_analysis(panel_sel, n_ho)
    judgment_df = build_judgment_table(signal_df, power_df)

    signal_df.to_csv(out_dir / "hall_signal_tests_raw.csv",
                     index=False, encoding="utf-8-sig")
    power_df.to_csv(out_dir / "hall_power_analysis.csv",
                    index=False, encoding="utf-8-sig")
    judgment_df.to_csv(out_dir / "signal_judgment_table.csv",
                       index=False, encoding="utf-8-sig")

    n_sig = int(signal_df["is_significant_bonf"].sum())
    n_halls_sig = int(
        (judgment_df["judgment"] == "SIGNAL_DETECTED").sum()
    )
    print(f"  Significant tests (Bonf corrected): {n_sig}/{len(signal_df)}")
    print(f"  Halls with detected signal: {n_halls_sig}/{n_halls}\n")
    print(judgment_df[
        ["store", "n_significant_bonf", "best_p_bonferroni",
         "avg_mde_abs", "judgment"]
    ].to_string(index=False))

    # ---- Stage 2 ----
    print("\n=== Stage 2: Baseline comparison (holdout) ===")
    oracle = baseline_oracle(panel_ho)
    random_bl = baseline_random(
        panel_ho, seed=args.seed, n_reps=args.n_random_reps
    )
    hist_best = baseline_historical_best_fixed(panel_sel, panel_ho)
    weekday_bl = baseline_weekday_fixed(panel_sel, panel_ho)
    current = load_current_model(Path(args.current_model_plan), panel_ho)

    baselines: list[dict[str, Any]] = [
        oracle, random_bl, hist_best, weekday_bl, current
    ]
    col_order = [
        "strategy", "n_days", "chosen_avg_diff_mean", "chosen_avg_diff_std",
        "chosen_hit_ge_100_rate", "chosen_hit_ge_200_rate",
        "chosen_hit_ge_300_rate", "best_hall", "best_hall_per_weekday",
        "n_reps", "error",
    ]
    baseline_df = pd.DataFrame(baselines)
    existing = [c for c in col_order if c in baseline_df.columns]
    extra = [c for c in baseline_df.columns if c not in existing]
    baseline_df = baseline_df[existing + extra]
    baseline_df.to_csv(out_dir / "baseline_comparison.csv",
                       index=False, encoding="utf-8-sig")

    disp = ["strategy", "chosen_avg_diff_mean",
            "chosen_hit_ge_100_rate", "chosen_hit_ge_200_rate",
            "chosen_hit_ge_300_rate"]
    print(baseline_df[disp].to_string(index=False))

    # ---- run_summary.json ----
    summary: dict[str, Any] = {
        "n_halls": n_halls,
        "n_sel_days": n_sel,
        "n_ho_days": n_ho,
        "selection_start": args.selection_start,
        "selection_end": args.selection_end,
        "holdout_start": args.holdout_start,
        "holdout_end": args.holdout_end,
        "stage1": {
            "n_tests_total": len(signal_df),
            "n_significant_bonf": n_sig,
            "n_halls_with_signal": n_halls_sig,
            "judgment": judgment_df[
                ["store", "judgment", "n_significant_bonf",
                 "best_p_bonferroni"]
            ].to_dict(orient="records"),
        },
        "stage2": {
            b["strategy"]: {k: v for k, v in b.items() if k != "strategy"}
            for b in baselines
        },
    }
    with open(out_dir / "run_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

    print(f"\nOutputs: {out_dir}/")


if __name__ == "__main__":
    main()
