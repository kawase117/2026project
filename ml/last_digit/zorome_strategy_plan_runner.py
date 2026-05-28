from __future__ import annotations

import argparse
import json
import math
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

from ml.last_digit import zorome_strategy_simulation as zsim
from ml.last_digit.analyze_correction_periodicity import run_periodicity_analysis
from ml.last_digit.tail_ltr_split_rule_nextday_gpu import _prepare_split_dataset
from ml.last_digit.utils import configure_logging


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Phase-based zorome strategy evaluator (A/B/C + D/E/F + periodicity).")
    p.add_argument("--db-path", required=True, help="SQLite DB path.")
    p.add_argument("--output-dir", default="db/experiments/zorome_strategy_plan", help="Output directory.")
    p.add_argument("--eval-window-days", type=int, default=61, help="Evaluation window length in days.")
    p.add_argument("--train-windows", default="60,90,120,180,full", help="Correction train windows for Phase1.")
    p.add_argument("--n-iter", type=int, default=500, help="Bootstrap sample size for daily simulation output.")
    p.add_argument("--seed", type=int, default=20260527, help="Random seed.")
    p.add_argument("--topn-digits", type=int, default=3, help="Top-N digits from selected expert for D/E/F.")
    p.add_argument("--min-zorome-train-n", type=int, default=5, help="Min zorome samples for correction.")
    p.add_argument("--min-nonzorome-train-n", type=int, default=10, help="Min non-zorome samples for correction.")
    p.add_argument("--log-level", default="INFO", help="Logging level.")
    return p


def _parse_windows(raw: str) -> list[int | None]:
    out: list[int | None] = []
    for token in [t.strip() for t in str(raw).split(",") if t.strip()]:
        if token.lower() == "full":
            out.append(None)
        else:
            out.append(int(token))
    return out


def _window_name(window: int | None) -> str:
    return "full" if window is None else f"{int(window)}d"


def _slice_train_for_window(df_train: pd.DataFrame, window: int | None, sim_start: pd.Timestamp) -> pd.DataFrame:
    if window is None:
        return df_train.copy()
    start = sim_start - pd.Timedelta(days=int(window))
    return df_train[df_train["date"] >= start].copy()


def _progress(prefix: str, idx: int, total: int, started_at: float) -> None:
    elapsed = time.time() - started_at
    done = max(idx, 1)
    speed = elapsed / done
    remain = max(total - done, 0) * speed
    print(f"{prefix} {idx}/{total} elapsed={elapsed:.1f}s remaining={remain:.1f}s")


def _cohens_d_paired(a: np.ndarray, b: np.ndarray) -> float:
    d = np.asarray(b, dtype=float) - np.asarray(a, dtype=float)
    d = d[np.isfinite(d)]
    if len(d) < 2:
        return float("nan")
    std = float(np.std(d, ddof=1))
    if std <= 0:
        return float("nan")
    return float(np.mean(d) / std)


def _wilcoxon_paired(a: np.ndarray, b: np.ndarray) -> float:
    diff = np.asarray(b, dtype=float) - np.asarray(a, dtype=float)
    diff = diff[np.isfinite(diff)]
    diff = diff[np.abs(diff) > 0]
    if len(diff) == 0:
        return float("nan")
    try:
        _stat, p = wilcoxon(diff, zero_method="wilcox", alternative="two-sided")
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


def _strategy_metrics_fixed(series: np.ndarray) -> dict[str, float]:
    x = np.asarray(series, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return {"mean_diff": float("nan"), "win_rate": float("nan"), "median_diff": float("nan"), "coverage": 0.0}
    return {
        "mean_diff": float(np.mean(x)),
        "win_rate": float(np.mean(x > 0)),
        "median_diff": float(np.median(x)),
        "coverage": 1.0,
    }


def _max_drawdown(values: np.ndarray) -> float:
    if values.size == 0:
        return float("nan")
    cum = np.cumsum(values.astype(float))
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    return float(np.max(dd)) if dd.size else float("nan")


def _sortino_ratio(values: np.ndarray) -> float:
    if values.size == 0:
        return float("nan")
    downside = values[values < 0]
    if downside.size == 0:
        return float("nan")
    downside_std = float(np.std(downside, ddof=1)) if downside.size >= 2 else float(np.std(downside, ddof=0))
    if downside_std <= 0:
        return float("nan")
    mean_ret = float(np.mean(values))
    return float((mean_ret / downside_std) * math.sqrt(365.0))


def _correction_diag(df_corr: pd.DataFrame) -> dict[str, float]:
    if df_corr.empty:
        return {
            "n_rows": 0,
            "fill_rate": 0.0,
            "mean_abs_correction": float("nan"),
            "median_abs_correction": float("nan"),
            "avg_n_zorome": float("nan"),
            "avg_n_nonzorome": float("nan"),
        }
    corr = pd.to_numeric(df_corr["correction"], errors="coerce")
    abs_corr = corr.abs()
    return {
        "n_rows": int(len(df_corr)),
        "fill_rate": float(np.mean(corr.notna())),
        "mean_abs_correction": float(np.nanmean(abs_corr)),
        "median_abs_correction": float(np.nanmedian(abs_corr)),
        "avg_n_zorome": float(pd.to_numeric(df_corr["n_zorome"], errors="coerce").mean()),
        "avg_n_nonzorome": float(pd.to_numeric(df_corr["n_nonzorome"], errors="coerce").mean()),
    }


def _lookup_correction(df_corr: pd.DataFrame, weekday: str, expert: str, digit: int) -> float:
    row = df_corr[
        (df_corr["weekday"] == weekday)
        & (df_corr["group_key"].astype(str) == str(expert))
        & (pd.to_numeric(df_corr["last_digit"], errors="coerce") == int(digit))
    ]
    if row.empty:
        return float("nan")
    v = pd.to_numeric(row["correction"], errors="coerce").iloc[0]
    return float(v) if np.isfinite(v) else float("nan")


def _eligible_digits_for_strategy(
    ranked_digits: list[int],
    corrections: dict[int, float],
    strategy: str,
) -> list[int]:
    out: list[int] = []
    for d in ranked_digits:
        c = corrections.get(int(d), float("nan"))
        if strategy == "D":
            if np.isfinite(c) and c > 0:
                out.append(int(d))
        elif strategy == "E":
            if np.isfinite(c) and c >= 0:
                out.append(int(d))
        elif strategy == "F":
            if np.isfinite(c) and c <= 0:
                out.append(int(d))
    return out


def _simulate_participation_day(
    *,
    date: pd.Timestamp,
    day_m: pd.DataFrame,
    day_p: pd.DataFrame,
    corr: pd.DataFrame,
    topn_digits: int,
    rng: np.random.Generator,
) -> dict[str, Any]:
    base = {
        "date": date,
        "weekday": date.day_name(),
        "selected_expert": None,
        "participated_D": 0,
        "participated_E": 0,
        "participated_F": 0,
        "diff_D": 0.0,
        "diff_E": 0.0,
        "diff_F": 0.0,
    }
    pick = zsim.select_highest_confidence_expert(day_p)
    if pick is None:
        return base

    expert = str(pick[0])
    base["selected_expert"] = expert
    pred_rows = day_p[(day_p["expert"].astype(str) == expert) & (day_p["status"].astype(str) == "ok")].copy()
    if pred_rows.empty:
        return base
    ranked_digits = pred_rows.sort_values("pred", ascending=False)["last_digit"].astype(int).head(max(int(topn_digits), 1)).tolist()
    corrections = {int(d): _lookup_correction(corr, base["weekday"], expert, int(d)) for d in ranked_digits}

    for strategy in ("D", "E", "F"):
        eligible = _eligible_digits_for_strategy(ranked_digits, corrections, strategy)
        if not eligible:
            continue
        digit = int(rng.choice(np.asarray(eligible, dtype=int)))
        pool = day_m[(day_m["group_key"].astype(str) == expert) & (pd.to_numeric(day_m["last_digit"], errors="coerce") == digit)]
        if pool.empty:
            continue
        diff_vals = pd.to_numeric(pool["diff_coins_normalized"], errors="coerce").dropna().to_numpy(dtype=float)
        if diff_vals.size == 0:
            continue
        sampled = float(rng.choice(diff_vals))
        base[f"participated_{strategy}"] = 1
        base[f"diff_{strategy}"] = sampled
    return base


def _summarize_participation(df_part: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    total_days = int(len(df_part))
    for strategy in ("D", "E", "F"):
        p = pd.to_numeric(df_part[f"participated_{strategy}"], errors="coerce").fillna(0).astype(int).to_numpy(dtype=int)
        x = pd.to_numeric(df_part[f"diff_{strategy}"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        mask = p == 1
        per_bet = x[mask]
        wins_per_day = np.where(mask & (x > 0), 1, 0)
        out[strategy] = {
            "mean_diff_per_bet": float(np.mean(per_bet)) if per_bet.size else float("nan"),
            "win_rate_per_bet": float(np.mean(per_bet > 0)) if per_bet.size else float("nan"),
            "n_days_participated": int(mask.sum()),
            "mean_diff_per_calendar_day": float(np.mean(x)) if x.size else float("nan"),
            "effective_win_rate": float(np.sum(wins_per_day) / total_days) if total_days > 0 else float("nan"),
            "coverage": float(mask.sum() / total_days) if total_days > 0 else 0.0,
            "median_diff_per_bet": float(np.median(per_bet)) if per_bet.size else float("nan"),
            "max_drawdown": _max_drawdown(x),
            "sortino_ratio": _sortino_ratio(x),
        }
    return out


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_ready(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_ready(v) for v in value]
    if isinstance(value, (np.floating, np.integer)):
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _phase1_window_sweep(
    *,
    df_train_global: pd.DataFrame,
    df_test: pd.DataFrame,
    preds: pd.DataFrame,
    windows: list[int | None],
    sim_start: pd.Timestamp,
    n_iter: int,
    min_zorome_train_n: int,
    min_nonzorome_train_n: int,
    rng_seed: int,
) -> tuple[dict[str, Any], str]:
    results: dict[str, Any] = {}
    start = time.time()
    for i, window in enumerate(windows, start=1):
        _progress("[Phase1]", i, len(windows), start)
        train_slice = _slice_train_for_window(df_train_global, window, sim_start)
        corr = zsim.compute_zorome_correction_table(
            train_slice,
            min_zorome_n=int(min_zorome_train_n),
            min_nonzorome_n=int(min_nonzorome_train_n),
        )
        rng = np.random.default_rng(int(rng_seed) + i)
        daily: list[dict[str, Any]] = []
        dates = sorted(pd.to_datetime(df_test["date"]).drop_duplicates().tolist())
        for j, dt in enumerate(dates, start=1):
            if j == 1 or j % 10 == 0 or j == len(dates):
                _progress(f"[Phase1:{_window_name(window)}]", j, len(dates), start)
            day_m = df_test[df_test["date"] == dt].copy()
            day_p = preds[preds["date"] == dt].copy()
            daily.append(
                zsim.simulate_one_day(
                    date=dt,
                    df_machines=day_m,
                    df_preds_day=day_p,
                    correction_table=corr,
                    n_iter=int(n_iter),
                    rng=rng,
                )
            )
        ddf = pd.DataFrame(daily)
        ok = ddf[ddf["status"] == "ok"].copy()
        a = pd.to_numeric(ok["strategy_A_mean"], errors="coerce").to_numpy(dtype=float)
        b = pd.to_numeric(ok["strategy_B_mean"], errors="coerce").to_numpy(dtype=float)
        c = pd.to_numeric(ok["strategy_C_mean"], errors="coerce").to_numpy(dtype=float)
        pvals = {"B_vs_A": _wilcoxon_paired(a, b), "C_vs_A": _wilcoxon_paired(a, c), "B_vs_C": _wilcoxon_paired(c, b)}
        padj = _holm_adjust(pvals)
        key = _window_name(window)
        results[key] = {
            "window_days": (None if window is None else int(window)),
            "n_days": int(len(ok)),
            "correction_diagnostics": _correction_diag(corr),
            "strategy_A": _strategy_metrics_fixed(a),
            "strategy_B": _strategy_metrics_fixed(b),
            "strategy_C": _strategy_metrics_fixed(c),
            "comparisons": {
                "B_minus_A_mean_diff": float(np.nanmean(b - a)) if len(ok) else float("nan"),
                "C_minus_A_mean_diff": float(np.nanmean(c - a)) if len(ok) else float("nan"),
                "B_minus_C_mean_diff": float(np.nanmean(b - c)) if len(ok) else float("nan"),
                "cohens_d_B_vs_A": _cohens_d_paired(a, b),
                "cohens_d_C_vs_A": _cohens_d_paired(a, c),
                "cohens_d_B_vs_C": _cohens_d_paired(c, b),
                "wilcoxon_p_B_vs_A": pvals["B_vs_A"],
                "wilcoxon_p_C_vs_A": pvals["C_vs_A"],
                "wilcoxon_p_B_vs_C": pvals["B_vs_C"],
                "holm_p_B_vs_A": padj["B_vs_A"],
                "holm_p_C_vs_A": padj["C_vs_A"],
                "holm_p_B_vs_C": padj["B_vs_C"],
            },
        }
    best = max(results.items(), key=lambda kv: (kv[1]["comparisons"]["B_minus_A_mean_diff"] if kv[1]["comparisons"]["B_minus_A_mean_diff"] is not None else -1e18))[0]
    return results, best


def _phase2_participation(
    *,
    df_test: pd.DataFrame,
    preds: pd.DataFrame,
    corr: pd.DataFrame,
    topn_digits: int,
    rng_seed: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    dates = sorted(pd.to_datetime(df_test["date"]).drop_duplicates().tolist())
    rng = np.random.default_rng(int(rng_seed))
    rows: list[dict[str, Any]] = []
    start = time.time()
    for i, dt in enumerate(dates, start=1):
        if i == 1 or i % 10 == 0 or i == len(dates):
            _progress("[Phase2]", i, len(dates), start)
        day_m = df_test[df_test["date"] == dt].copy()
        day_p = preds[preds["date"] == dt].copy()
        rows.append(
            _simulate_participation_day(
                date=dt,
                day_m=day_m,
                day_p=day_p,
                corr=corr,
                topn_digits=int(topn_digits),
                rng=rng,
            )
        )
    out = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    summary = _summarize_participation(out)
    return out, summary


def _build_corr_timeseries_from_phase1_daily(phase1_daily: pd.DataFrame) -> pd.DataFrame:
    keep_cols = ["date", "weekday", "target_digit", "expert_used", "zorome_correction"]
    df = phase1_daily[keep_cols].copy()
    df = df.rename(
        columns={
            "target_digit": "last_digit",
            "expert_used": "expert_group",
            "zorome_correction": "correction",
        }
    )
    df["sign"] = np.where(
        pd.to_numeric(df["correction"], errors="coerce") > 0,
        "+",
        np.where(pd.to_numeric(df["correction"], errors="coerce") < 0, "-", "0"),
    )
    return df


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_ready(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _load_machine_name_mismatch_rate(db_path: Path, preds: pd.DataFrame) -> float:
    if preds.empty:
        return float("nan")
    con = sqlite3.connect(str(db_path))
    q = """
    SELECT date, machine_name, CAST(last_digit AS INTEGER) AS last_digit,
           CASE
             WHEN machine_number BETWEEN 2000 AND 2999 THEN '2F_N'
             WHEN machine_number BETWEEN 3000 AND 3999 THEN '3F_N'
             WHEN machine_number BETWEEN 4000 AND 4999 THEN '3F_A'
             WHEN machine_number BETWEEN 1000 AND 1999 THEN '2F_A'
             ELSE NULL
           END AS group_key
    FROM machine_detailed_results
    WHERE games_normalized > 0
    """
    try:
        df = pd.read_sql_query(q, con)
    finally:
        con.close()
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
    df["last_digit"] = pd.to_numeric(df["last_digit"], errors="coerce")
    d = df.dropna(subset=["date", "last_digit", "group_key"]).copy()
    keys = d[["date", "group_key", "last_digit"]].drop_duplicates()
    pkeys = preds[["date", "expert", "last_digit"]].rename(columns={"expert": "group_key"}).copy()
    merged = pkeys.merge(keys, on=["date", "group_key", "last_digit"], how="left", indicator=True)
    miss = float(np.mean(merged["_merge"] != "both")) if len(merged) else float("nan")
    return miss


def main() -> int:
    args = build_parser().parse_args()
    configure_logging(str(args.log_level))

    db_path = Path(str(args.db_path))
    out_dir = Path(str(args.output_dir))
    out_dir.mkdir(parents=True, exist_ok=True)

    # Reuse predictor defaults from existing simulation parser.
    pred_args = zsim.build_parser().parse_args(["--db-path", str(db_path)])
    pred_args.seed = int(args.seed)
    pred_args.min_zorome_train_n = int(args.min_zorome_train_n)
    pred_args.min_nonzorome_train_n = int(args.min_nonzorome_train_n)

    df_m = zsim.load_machine_level_data(db_path)
    sim_start, sim_end = zsim.define_window(df_m, window_days=int(args.eval_window_days))
    df_train_global = df_m[df_m["date"] < sim_start].copy()
    df_test = df_m[(df_m["date"] >= sim_start) & (df_m["date"] <= sim_end)].copy()
    if df_test.empty:
        raise ValueError("No rows in evaluation window.")

    split_data, source_latest, target_date = _prepare_split_dataset(
        db_path=str(db_path),
        db_glob=str(pred_args.db_glob),
        a_weight=float(pred_args.a_weight),
        non_a_weight=float(pred_args.non_a_weight),
        enable_digit_lag_bundle=bool(pred_args.enable_digit_lag_bundle),
    )
    test_dates = sorted(pd.to_datetime(df_test["date"]).drop_duplicates().tolist())
    model_params = zsim._parse_model_params(pred_args)
    preds = zsim.generate_test_predictions(
        data=split_data,
        test_dates=test_dates,
        args=pred_args,
        model_params=model_params,
    )

    windows = _parse_windows(str(args.train_windows))
    phase1_results, best_window_key = _phase1_window_sweep(
        df_train_global=df_train_global,
        df_test=df_test,
        preds=preds,
        windows=windows,
        sim_start=sim_start,
        n_iter=int(args.n_iter),
        min_zorome_train_n=int(args.min_zorome_train_n),
        min_nonzorome_train_n=int(args.min_nonzorome_train_n),
        rng_seed=int(args.seed),
    )

    best_window = None if best_window_key == "full" else int(best_window_key.replace("d", ""))
    corr_best = zsim.compute_zorome_correction_table(
        _slice_train_for_window(df_train_global, best_window, sim_start),
        min_zorome_n=int(args.min_zorome_train_n),
        min_nonzorome_n=int(args.min_nonzorome_train_n),
    )

    # Build a daily Phase1 dataframe for selected best window (needed for periodicity input).
    rng = np.random.default_rng(int(args.seed) + 999)
    phase1_daily_rows: list[dict[str, Any]] = []
    for dt in test_dates:
        phase1_daily_rows.append(
            zsim.simulate_one_day(
                date=dt,
                df_machines=df_test[df_test["date"] == dt].copy(),
                df_preds_day=preds[preds["date"] == dt].copy(),
                correction_table=corr_best,
                n_iter=int(args.n_iter),
                rng=rng,
            )
        )
    phase1_daily = pd.DataFrame(phase1_daily_rows).sort_values("date").reset_index(drop=True)

    phase2_daily, phase2_summary = _phase2_participation(
        df_test=df_test,
        preds=preds,
        corr=corr_best,
        topn_digits=int(args.topn_digits),
        rng_seed=int(args.seed) + 4242,
    )

    corr_ts = _build_corr_timeseries_from_phase1_daily(phase1_daily)
    corr_ts_path = out_dir / "phase3_correction_timeseries.csv"
    corr_ts.to_csv(corr_ts_path, index=False, encoding="utf-8")
    periodic_json = out_dir / "phase3_periodicity_report.json"
    periodic_acf_csv = out_dir / "phase3_periodicity_acf.csv"
    run_periodicity_analysis(
        input_csv=corr_ts_path,
        output_json=periodic_json,
        output_acf_csv=periodic_acf_csv,
        max_lag=30,
    )

    phase1_daily.to_csv(out_dir / "phase1_daily_best_window.csv", index=False, encoding="utf-8")
    phase2_daily.to_csv(out_dir / "phase2_participation_daily.csv", index=False, encoding="utf-8")
    corr_best.to_csv(out_dir / "phase1_best_window_correction_table.csv", index=False, encoding="utf-8")

    summary = {
        "generated_at": datetime.now().isoformat(),
        "db_path": str(db_path),
        "sim_period": {"start": sim_start.strftime("%Y-%m-%d"), "end": sim_end.strftime("%Y-%m-%d")},
        "source_latest_date": source_latest.strftime("%Y-%m-%d"),
        "target_date": target_date.strftime("%Y-%m-%d"),
        "windows_tested": [_window_name(w) for w in windows],
        "phase1_best_window": best_window_key,
        "phase1": phase1_results,
        "phase2": phase2_summary,
        "diagnostics": {
            "pred_key_miss_rate": _load_machine_name_mismatch_rate(db_path, preds),
            "n_eval_days": int(len(test_dates)),
            "n_eval_machine_rows": int(len(df_test)),
        },
        "artifacts": {
            "phase1_daily_best_window_csv": str(out_dir / "phase1_daily_best_window.csv"),
            "phase2_daily_csv": str(out_dir / "phase2_participation_daily.csv"),
            "phase3_correction_timeseries_csv": str(corr_ts_path),
            "phase3_periodicity_json": str(periodic_json),
            "phase3_periodicity_acf_csv": str(periodic_acf_csv),
        },
    }
    _write_json(out_dir / "phase_summary.json", summary)
    print(json.dumps(_json_ready(summary), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
