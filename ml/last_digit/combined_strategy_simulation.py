from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

# Fix import path for absolute module imports when run as main script
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ml.last_digit import zorome_strategy_simulation as zsim
from ml.last_digit.tail_ltr_split_rule_nextday_gpu import (
    _gpu_model_params,
    _prepare_split_dataset,
)


def _is_zorome_machine(machine_number: int) -> bool:
    tail2 = abs(int(machine_number)) % 100
    return (tail2 // 10) == (tail2 % 10)


def _build_day_prediction_table(df_day_preds: pd.DataFrame) -> pd.DataFrame:
    if df_day_preds.empty:
        return pd.DataFrame()
    work = df_day_preds.copy()
    work["rank"] = work.groupby("expert", sort=False)["pred"].rank(ascending=False, method="first").astype(int)
    return work


def get_combined_rank(df_ml_predictions: pd.DataFrame) -> pd.DataFrame:
    req = {"expert", "last_digit", "rank"}
    if df_ml_predictions.empty or not req.issubset(df_ml_predictions.columns):
        return pd.DataFrame(columns=["last_digit", "combined_score", "combined_rank"])
    grouped = (
        df_ml_predictions.groupby("last_digit", sort=True)
        .agg(combined_score=("rank", "mean"), n_experts=("expert", "nunique"))
        .reset_index()
    )
    grouped["combined_rank"] = grouped["combined_score"].rank(ascending=True, method="first").astype(int)
    return grouped.sort_values("combined_rank").reset_index(drop=True)


def _choose_machine_value(pool: pd.DataFrame, rng: np.random.Generator) -> float:
    vals = pool["diff_coins_normalized"].to_numpy(dtype=float)
    if len(vals) == 0:
        return float("nan")
    return float(rng.choice(vals))


def simulate_combined_strategy(
    df_results: pd.DataFrame,
    df_ml_predictions: pd.DataFrame,
    correction_table: pd.DataFrame,
    weekday: str,
    strategy: str,
    n_iter: int = 500,
    seed: int | None = None,
) -> float:
    if df_results.empty or df_ml_predictions.empty:
        return float("nan")

    combined = get_combined_rank(df_ml_predictions)
    if combined.empty:
        return float("nan")

    combined_top = combined.sort_values("combined_rank")
    combined_top1_digit = int(combined_top.iloc[0]["last_digit"])
    combined_top3 = set(int(x) for x in combined_top.head(3)["last_digit"].tolist())

    high_conf = zsim.select_highest_confidence_expert(df_ml_predictions)
    use_fallback_x = True
    target_digit_yz: int | None = None
    target_expert: str | None = None
    target_corr = float("nan")
    if high_conf is not None:
        target_expert, high_digit, _conf = high_conf
        high_digit = int(high_digit)
        if high_digit in combined_top3:
            use_fallback_x = False
            target_digit_yz = high_digit
            target_corr = zsim._lookup_correction(correction_table, weekday=weekday, expert=str(target_expert), digit=high_digit)

    rng = np.random.default_rng(seed)
    n = max(1, int(n_iter))
    samples: list[float] = []

    for _ in range(n):
        if strategy == "X" or use_fallback_x:
            pool_x = df_results[df_results["last_digit"] == combined_top1_digit].copy()
            v = _choose_machine_value(pool_x, rng)
            samples.append(v)
            continue

        if target_digit_yz is None:
            pool_x = df_results[df_results["last_digit"] == combined_top1_digit].copy()
            v = _choose_machine_value(pool_x, rng)
            samples.append(v)
            continue

        pool_target = df_results[df_results["last_digit"] == int(target_digit_yz)].copy()
        if pool_target.empty:
            pool_x = df_results[df_results["last_digit"] == combined_top1_digit].copy()
            v = _choose_machine_value(pool_x, rng)
            samples.append(v)
            continue

        pool_target["is_zorome_machine"] = pool_target["machine_number"].astype(int).map(_is_zorome_machine).astype(int)
        pool_z = pool_target[pool_target["is_zorome_machine"] == 1].copy()
        pool_nz = pool_target[pool_target["is_zorome_machine"] == 0].copy()
        if pool_nz.empty:
            pool_nz = pool_target

        if strategy == "Y":
            if np.isfinite(target_corr) and target_corr > 0 and not pool_z.empty:
                chosen = pool_z
            else:
                chosen = pool_nz
        elif strategy == "Z":
            chosen = pool_nz
        else:
            raise ValueError(f"Unsupported strategy: {strategy}")

        v = _choose_machine_value(chosen, rng)
        samples.append(v)

    arr = np.asarray(samples, dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return float("nan")
    return float(arr.mean())


def _filter_correction_for_day(df_ml_predictions: pd.DataFrame, correction_table: pd.DataFrame, weekday: str) -> float:
    pick = zsim.select_highest_confidence_expert(df_ml_predictions)
    if pick is None:
        return float("nan")
    expert, target_digit, _conf = pick
    return zsim._lookup_correction(correction_table, weekday=weekday, expert=str(expert), digit=int(target_digit))


def _paired_cohens_d(a: np.ndarray, b: np.ndarray) -> float:
    d = np.asarray(b, dtype=float) - np.asarray(a, dtype=float)
    d = d[np.isfinite(d)]
    if len(d) < 2:
        return float("nan")
    sd = float(np.std(d, ddof=1))
    if sd <= 0:
        return float("nan")
    return float(np.mean(d) / sd)


def _wilcoxon_paired(a: np.ndarray, b: np.ndarray) -> float:
    diff = np.asarray(b, dtype=float) - np.asarray(a, dtype=float)
    diff = diff[np.isfinite(diff)]
    diff = diff[np.abs(diff) > 0]
    if len(diff) == 0:
        return float("nan")
    try:
        _stat, p = wilcoxon(diff, alternative="two-sided", zero_method="wilcox")
        return float(p)
    except ValueError:
        return float("nan")


def _holm_adjust(named_pvalues: dict[str, float]) -> dict[str, float]:
    valid = [(k, float(v)) for k, v in named_pvalues.items() if np.isfinite(v)]
    if not valid:
        return {k: float("nan") for k in named_pvalues}
    valid.sort(key=lambda x: x[1])
    m = len(valid)
    adjusted: dict[str, float] = {}
    running_max = 0.0
    for i, (name, pval) in enumerate(valid, start=1):
        adj = min(1.0, (m - i + 1) * pval)
        running_max = max(running_max, adj)
        adjusted[name] = running_max
    out = {k: float("nan") for k in named_pvalues}
    out.update(adjusted)
    return out


def _strategy_stats(values: np.ndarray) -> dict[str, float]:
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return {
            "mean_diff_per_calendar_day": float("nan"),
            "median_diff": float("nan"),
            "win_rate": float("nan"),
            "total_diff": float("nan"),
        }
    return {
        "mean_diff_per_calendar_day": float(np.mean(x)),
        "median_diff": float(np.median(x)),
        "win_rate": float(np.mean(x > 0)),
        "total_diff": float(np.sum(x)),
    }


def _compute_daily_base(
    db_path: str,
    sim_start: str,
    sim_end: str,
    train_window_days: int = 120,
    n_iter: int = 500,
    seed: int = 20260527,
) -> pd.DataFrame:
    db_path_obj = Path(db_path)
    if not db_path_obj.exists():
        raise FileNotFoundError(f"DB not found: {db_path_obj}")

    machine_df = zsim.load_machine_level_data(db_path_obj)
    sim_start_ts = pd.to_datetime(sim_start)
    sim_end_ts = pd.to_datetime(sim_end)
    test_df = machine_df[(machine_df["date"] >= sim_start_ts) & (machine_df["date"] <= sim_end_ts)].copy()
    if test_df.empty:
        raise ValueError("No machine rows in requested simulation range.")

    parser = zsim.build_parser()
    args = parser.parse_args(["--db-path", str(db_path_obj)])
    model_params = _gpu_model_params(args.gpu_backend)
    split_data, _source_latest, _target_date = _prepare_split_dataset(
        db_path=str(db_path_obj),
        db_glob=args.db_glob,
        a_weight=float(args.a_weight),
        non_a_weight=float(args.non_a_weight),
        enable_digit_lag_bundle=bool(args.enable_digit_lag_bundle),
    )

    eval_dates = sorted(pd.to_datetime(test_df["date"]).drop_duplicates().tolist())
    preds = zsim.generate_test_predictions(split_data, eval_dates, args, model_params)
    if not preds.empty:
        preds["date"] = pd.to_datetime(preds["date"])

    daily_rows: list[dict[str, Any]] = []
    for i, dt in enumerate(eval_dates):
        day_results = test_df[test_df["date"] == dt].copy()
        day_preds = preds[preds["date"] == dt].copy() if not preds.empty else pd.DataFrame()
        weekday = dt.day_name()

        if day_preds.empty:
            daily_rows.append(
                {
                    "date": dt.strftime("%Y-%m-%d"),
                    "weekday": weekday,
                    "filter_correction": np.nan,
                    "ret_X": np.nan,
                    "ret_Y": np.nan,
                    "ret_Z": np.nan,
                    "status": "no_ml_prediction",
                }
            )
            continue

        corr_end = dt - pd.Timedelta(days=1)
        corr_start = corr_end - pd.Timedelta(days=int(train_window_days) - 1)
        train_slice = machine_df[(machine_df["date"] >= corr_start) & (machine_df["date"] <= corr_end)].copy()
        correction_table = zsim.compute_zorome_correction_table(
            train_slice,
            min_zorome_n=int(zsim.MIN_ZOROME_TRAIN_N),
            min_nonzorome_n=int(zsim.MIN_NONZOROME_TRAIN_N),
        )

        filter_corr = _filter_correction_for_day(day_preds, correction_table, weekday=weekday)
        seed_base = int(seed) + int(i) * 1000
        ret_x = simulate_combined_strategy(day_results, day_preds, correction_table, weekday, "X", n_iter=n_iter, seed=seed_base + 1)
        ret_y = simulate_combined_strategy(day_results, day_preds, correction_table, weekday, "Y", n_iter=n_iter, seed=seed_base + 2)
        ret_z = simulate_combined_strategy(day_results, day_preds, correction_table, weekday, "Z", n_iter=n_iter, seed=seed_base + 3)
        daily_rows.append(
            {
                "date": dt.strftime("%Y-%m-%d"),
                "weekday": weekday,
                "filter_correction": filter_corr,
                "ret_X": ret_x,
                "ret_Y": ret_y,
                "ret_Z": ret_z,
                "status": "ok",
            }
        )

    return pd.DataFrame(daily_rows)


def _summarize_thresholded_daily(
    daily_base: pd.DataFrame,
    sim_start: str,
    sim_end: str,
    train_window_days: int,
    correction_threshold: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily_df = daily_base.copy()
    threshold = float(correction_threshold)
    mask_ok = daily_df["status"].eq("ok")
    mask_corr = pd.to_numeric(daily_df["filter_correction"], errors="coerce").abs().ge(threshold)
    mask_corr = mask_corr & pd.to_numeric(daily_df["filter_correction"], errors="coerce").notna()
    skip_mask = mask_ok & (~mask_corr)
    daily_df.loc[skip_mask, ["ret_X", "ret_Y", "ret_Z"]] = np.nan
    daily_df.loc[skip_mask, "status"] = "threshold_skip"

    daily_ok = daily_df[daily_df["status"] == "ok"].copy()
    x = pd.to_numeric(daily_ok["ret_X"], errors="coerce").to_numpy(dtype=float)
    y = pd.to_numeric(daily_ok["ret_Y"], errors="coerce").to_numpy(dtype=float)
    z = pd.to_numeric(daily_ok["ret_Z"], errors="coerce").to_numpy(dtype=float)

    stats_x = _strategy_stats(x)
    stats_y = _strategy_stats(y)
    stats_z = _strategy_stats(z)
    pvals = {
        "Y_vs_X": _wilcoxon_paired(x, y),
        "Z_vs_X": _wilcoxon_paired(x, z),
        "Y_vs_Z": _wilcoxon_paired(z, y),
    }
    pvals_holm = _holm_adjust(pvals)
    d_yx = _paired_cohens_d(x, y)
    d_zx = _paired_cohens_d(x, z)
    d_yz = _paired_cohens_d(z, y)

    summary = pd.DataFrame(
        [
            {
                "sim_start": pd.to_datetime(sim_start).strftime("%Y-%m-%d"),
                "sim_end": pd.to_datetime(sim_end).strftime("%Y-%m-%d"),
                "train_window_days": int(train_window_days),
                "correction_threshold": float(correction_threshold),
                "n_days_total": int(len(daily_df)),
                "n_days_valid": int(len(daily_ok)),
                "coverage": float(len(daily_ok) / len(daily_df)) if len(daily_df) > 0 else np.nan,
                "X_mean_diff_per_calendar_day": stats_x["mean_diff_per_calendar_day"],
                "X_median_diff": stats_x["median_diff"],
                "X_win_rate": stats_x["win_rate"],
                "X_total_diff": stats_x["total_diff"],
                "Y_mean_diff_per_calendar_day": stats_y["mean_diff_per_calendar_day"],
                "Y_median_diff": stats_y["median_diff"],
                "Y_win_rate": stats_y["win_rate"],
                "Y_total_diff": stats_y["total_diff"],
                "Z_mean_diff_per_calendar_day": stats_z["mean_diff_per_calendar_day"],
                "Z_median_diff": stats_z["median_diff"],
                "Z_win_rate": stats_z["win_rate"],
                "Z_total_diff": stats_z["total_diff"],
                "Diff_Y_minus_X": stats_y["mean_diff_per_calendar_day"] - stats_x["mean_diff_per_calendar_day"],
                "Diff_Z_minus_X": stats_z["mean_diff_per_calendar_day"] - stats_x["mean_diff_per_calendar_day"],
                "Diff_Y_minus_Z": stats_y["mean_diff_per_calendar_day"] - stats_z["mean_diff_per_calendar_day"],
                "wilcoxon_p_Y_vs_X": pvals["Y_vs_X"],
                "wilcoxon_p_Z_vs_X": pvals["Z_vs_X"],
                "wilcoxon_p_Y_vs_Z": pvals["Y_vs_Z"],
                "holm_p_Y_vs_X": pvals_holm["Y_vs_X"],
                "holm_p_Z_vs_X": pvals_holm["Z_vs_X"],
                "holm_p_Y_vs_Z": pvals_holm["Y_vs_Z"],
                "cohens_d_Y_vs_X": d_yx,
                "cohens_d_Z_vs_X": d_zx,
                "cohens_d_Y_vs_Z": d_yz,
            }
        ]
    )
    return daily_df, summary


def run_combined_simulation(
    db_path: str,
    sim_start: str,
    sim_end: str,
    train_window_days: int = 120,
    n_iter: int = 500,
    seed: int = 20260527,
    correction_threshold: float = 0.0,
) -> dict[str, Any]:
    daily_base = _compute_daily_base(
        db_path=db_path,
        sim_start=sim_start,
        sim_end=sim_end,
        train_window_days=train_window_days,
        n_iter=n_iter,
        seed=seed,
    )
    daily_df, summary = _summarize_thresholded_daily(
        daily_base=daily_base,
        sim_start=sim_start,
        sim_end=sim_end,
        train_window_days=train_window_days,
        correction_threshold=correction_threshold,
    )
    return {"daily": daily_df, "summary": summary}


def sweep_correction_threshold(
    db_path: str,
    sim_start: str,
    sim_end: str,
    train_window_days: int = 120,
    n_iter: int = 500,
    seed: int = 20260527,
    threshold_values: list[float] | None = None,
) -> pd.DataFrame:
    if threshold_values is None:
        threshold_values = [0, 50, 100, 150, 200, 300, 400]
    daily_base = _compute_daily_base(
        db_path=db_path,
        sim_start=sim_start,
        sim_end=sim_end,
        train_window_days=train_window_days,
        n_iter=n_iter,
        seed=seed,
    )
    rows: list[dict[str, Any]] = []
    for thr in threshold_values:
        daily_df, summary = _summarize_thresholded_daily(
            daily_base=daily_base,
            sim_start=sim_start,
            sim_end=sim_end,
            train_window_days=train_window_days,
            correction_threshold=float(thr),
        )
        s = summary.iloc[0]
        rows.append(
            {
                "threshold": float(thr),
                "n_days_participated": int(s["n_days_valid"]),
                "coverage": float(s["coverage"]),
                "X_mean": float(s["X_mean_diff_per_calendar_day"]) if np.isfinite(s["X_mean_diff_per_calendar_day"]) else np.nan,
                "Y_mean": float(s["Y_mean_diff_per_calendar_day"]) if np.isfinite(s["Y_mean_diff_per_calendar_day"]) else np.nan,
                "diff_YX": float(s["Diff_Y_minus_X"]) if np.isfinite(s["Diff_Y_minus_X"]) else np.nan,
                "cohens_d_YX": float(s["cohens_d_Y_vs_X"]) if np.isfinite(s["cohens_d_Y_vs_X"]) else np.nan,
                "wilcoxon_p_YX": float(s["wilcoxon_p_Y_vs_X"]) if np.isfinite(s["wilcoxon_p_Y_vs_X"]) else np.nan,
                "X_winrate": float(s["X_win_rate"]) if np.isfinite(s["X_win_rate"]) else np.nan,
                "Y_winrate": float(s["Y_win_rate"]) if np.isfinite(s["Y_win_rate"]) else np.nan,
            }
        )
    return pd.DataFrame(rows)


def _print_summary(summary_row: pd.Series) -> None:
    print("=== Combined Strategy Simulation ===")
    print(f"Period: {summary_row['sim_start']} - {summary_row['sim_end']}")
    if "correction_threshold" in summary_row:
        print(f"Correction threshold: {summary_row['correction_threshold']}")
    if "coverage" in summary_row:
        print(f"Coverage: {100.0 * float(summary_row['coverage']):.1f}%")
    print(
        "Strategy X (simple last-digit): "
        f"mean {summary_row['X_mean_diff_per_calendar_day']:.1f} /machine, "
        f"win-rate {100.0 * summary_row['X_win_rate']:.1f}%"
    )
    print(
        "Strategy Y (combined ML+zorome): "
        f"mean {summary_row['Y_mean_diff_per_calendar_day']:.1f} /machine, "
        f"win-rate {100.0 * summary_row['Y_win_rate']:.1f}%"
    )
    print(
        "Strategy Z (zorome-avoid): "
        f"mean {summary_row['Z_mean_diff_per_calendar_day']:.1f} /machine, "
        f"win-rate {100.0 * summary_row['Z_win_rate']:.1f}%"
    )
    print(f"Diff Y-X: {summary_row['Diff_Y_minus_X']:+.1f} /machine")
    print("Wilcoxon p-values (Holm-adjusted):")
    print(f"  Y vs X: {summary_row['holm_p_Y_vs_X']:.4f}" if np.isfinite(summary_row["holm_p_Y_vs_X"]) else "  Y vs X: NA")
    print(f"  Z vs X: {summary_row['holm_p_Z_vs_X']:.4f}" if np.isfinite(summary_row["holm_p_Z_vs_X"]) else "  Z vs X: NA")
    print(f"  Y vs Z: {summary_row['holm_p_Y_vs_Z']:.4f}" if np.isfinite(summary_row["holm_p_Y_vs_Z"]) else "  Y vs Z: NA")
    print(
        f"Cohen's d (Y-X): {summary_row['cohens_d_Y_vs_X']:.4f}"
        if np.isfinite(summary_row["cohens_d_Y_vs_X"])
        else "Cohen's d (Y-X): NA"
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Combined strategy simulator: ML last-digit + zorome correction.")
    p.add_argument("--db-path", required=True, help="SQLite DB path.")
    p.add_argument("--sim-start", required=True, help="Simulation start date (YYYY-MM-DD).")
    p.add_argument("--sim-end", required=True, help="Simulation end date (YYYY-MM-DD).")
    p.add_argument("--train-window", type=int, default=120, help="Training window days for correction (default: 120).")
    p.add_argument("--n-iter", type=int, default=500, help="Monte Carlo iterations per day.")
    p.add_argument("--seed", type=int, default=20260527, help="Random seed.")
    p.add_argument("--correction-threshold", type=float, default=0.0, help="Skip days with |correction| below this value.")
    p.add_argument("--sweep-thresholds", default="", help="Comma-separated thresholds for sweep, e.g. '0,50,100,150,200,300,400'.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if str(args.sweep_thresholds).strip():
        thresholds = [float(x.strip()) for x in str(args.sweep_thresholds).split(",") if x.strip()]
        sweep_df = sweep_correction_threshold(
            db_path=args.db_path,
            sim_start=args.sim_start,
            sim_end=args.sim_end,
            train_window_days=int(args.train_window),
            n_iter=int(args.n_iter),
            seed=int(args.seed),
            threshold_values=thresholds,
        )
        out_dir = Path("db/experiments")
        out_dir.mkdir(parents=True, exist_ok=True)
        sweep_path = out_dir / "combined_sim_threshold_sweep.csv"
        sweep_df.to_csv(sweep_path, index=False, encoding="utf-8")
        print("=== Threshold Sweep Results ===")
        print(sweep_df.to_string(index=False))
        print(f"Sweep CSV: {sweep_path}")
        return 0

    out = run_combined_simulation(
        db_path=args.db_path,
        sim_start=args.sim_start,
        sim_end=args.sim_end,
        train_window_days=int(args.train_window),
        n_iter=int(args.n_iter),
        seed=int(args.seed),
        correction_threshold=float(args.correction_threshold),
    )
    daily: pd.DataFrame = out["daily"]
    summary: pd.DataFrame = out["summary"]

    start_s = pd.to_datetime(args.sim_start).strftime("%Y%m%d")
    end_s = pd.to_datetime(args.sim_end).strftime("%Y%m%d")
    out_dir = Path("db/experiments")
    out_dir.mkdir(parents=True, exist_ok=True)
    daily_path = out_dir / f"combined_sim_{start_s}_{end_s}_daily.csv"
    summary_path = out_dir / f"combined_sim_{start_s}_{end_s}_summary.csv"
    daily.to_csv(daily_path, index=False, encoding="utf-8")
    summary.to_csv(summary_path, index=False, encoding="utf-8")

    _print_summary(summary.iloc[0])
    print(f"Daily CSV: {daily_path}")
    print(f"Summary CSV: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
