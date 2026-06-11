from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import f_oneway, ttest_ind

from ml.last_digit.tail_ltr_split_rule_wf import resolve_db_path


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Hall-level timing signal check (selection -> holdout).")
    p.add_argument("--db-path", default="", help="DB path override. Empty uses resolve_db_path.")
    p.add_argument("--db-glob", default="*7.db")
    p.add_argument("--selection-start", default="2025-07-07")
    p.add_argument("--selection-end", default="2025-12-31")
    p.add_argument("--holdout-start", default="2026-01-01")
    p.add_argument("--holdout-end", default="2026-05-30")
    p.add_argument("--topk-dd", type=int, default=5, help="Top-k DD used in dd_topk rule.")
    p.add_argument("--min-dd-days", type=int, default=6, help="Minimum selection samples for DD in dd_topk rule.")
    p.add_argument("--bootstrap-n", type=int, default=4000)
    p.add_argument("--seed", type=int, default=20260601)
    p.add_argument("--output-prefix", default="db/experiments/hall_timing_signal_check")
    return p


def _bootstrap_mean_ci(values: np.ndarray, *, n_boot: int, seed: int, alpha: float = 0.05) -> tuple[float, float]:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    boots = np.empty(n_boot, dtype=float)
    n = arr.size
    for i in range(n_boot):
        sample = arr[rng.integers(0, n, size=n)]
        boots[i] = float(np.mean(sample))
    lo = float(np.quantile(boots, alpha / 2.0))
    hi = float(np.quantile(boots, 1.0 - alpha / 2.0))
    return lo, hi


def _eta_squared_oneway(groups: list[np.ndarray]) -> float:
    valid = [g[np.isfinite(g)] for g in groups if len(g) > 0]
    if len(valid) < 2:
        return float("nan")
    all_vals = np.concatenate(valid)
    grand = float(np.mean(all_vals))
    ss_between = float(sum(len(g) * (float(np.mean(g)) - grand) ** 2 for g in valid))
    ss_total = float(np.sum((all_vals - grand) ** 2))
    if ss_total <= 0.0:
        return float("nan")
    return ss_between / ss_total


def _load_daily_hall(db_path: Path) -> pd.DataFrame:
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
        raise ValueError("daily_hall_summary is empty")

    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
    df = df[df["date"].notna()].copy()
    df["avg_diff_per_machine"] = pd.to_numeric(df["avg_diff_per_machine"], errors="coerce").fillna(0.0)
    df["avg_games_per_machine"] = pd.to_numeric(df["avg_games_per_machine"], errors="coerce").fillna(0.0)
    df["total_machines"] = pd.to_numeric(df["total_machines"], errors="coerce").fillna(0.0)
    df["win_rate"] = pd.to_numeric(df["win_rate"], errors="coerce").fillna(0.0)
    df["is_any_event"] = pd.to_numeric(df["is_any_event"], errors="coerce").fillna(0).astype(int)

    df["weekday"] = df["date"].dt.weekday.astype(int)
    df["dd"] = df["date"].dt.day.astype(int)
    df["mm"] = df["date"].dt.month.astype(int)
    df["is_positive_day"] = (df["avg_diff_per_machine"] > 0.0).astype(int)
    df["is_zorome_day"] = df["dd"].isin([11, 22]).astype(int)
    df["is_strong_zorome_day"] = (df["dd"] == df["mm"]).astype(int)
    df["is_day_7x"] = df["dd"].isin([7, 17, 27]).astype(int)
    df["is_day_1x"] = df["dd"].isin([1, 11, 21, 31]).astype(int)
    return df.sort_values("date").reset_index(drop=True)


def _split(df: pd.DataFrame, args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame]:
    selection_start = pd.Timestamp(str(args.selection_start))
    selection_end = pd.Timestamp(str(args.selection_end))
    holdout_start = pd.Timestamp(str(args.holdout_start))
    holdout_end = min(pd.Timestamp(str(args.holdout_end)), pd.to_datetime(df["date"]).max())

    sel = df[(df["date"] >= selection_start) & (df["date"] <= selection_end)].copy()
    ho = df[(df["date"] >= holdout_start) & (df["date"] <= holdout_end)].copy()
    if sel.empty or ho.empty:
        raise ValueError("selection/holdout split produced empty frame")
    return sel, ho


def _selection_tests(sel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    flag_rows: list[dict[str, Any]] = []
    flags = [
        "is_any_event",
        "is_zorome_day",
        "is_strong_zorome_day",
        "is_day_7x",
        "is_day_1x",
    ]
    for f in flags:
        a = sel[sel[f] == 1]["avg_diff_per_machine"].to_numpy(dtype=float)
        b = sel[sel[f] == 0]["avg_diff_per_machine"].to_numpy(dtype=float)
        if len(a) < 2 or len(b) < 2:
            t_stat, p_val = np.nan, np.nan
        else:
            t_stat, p_val = ttest_ind(a, b, equal_var=False, nan_policy="omit")
        flag_rows.append(
            {
                "feature": f,
                "n_on": int(len(a)),
                "n_off": int(len(b)),
                "mean_on": float(np.nanmean(a)) if len(a) else np.nan,
                "mean_off": float(np.nanmean(b)) if len(b) else np.nan,
                "delta_on_minus_off": (float(np.nanmean(a)) - float(np.nanmean(b))) if len(a) and len(b) else np.nan,
                "t_stat": float(t_stat) if np.isfinite(t_stat) else np.nan,
                "p_value": float(p_val) if np.isfinite(p_val) else np.nan,
            }
        )

    cat_rows: list[dict[str, Any]] = []
    for cat in ("weekday", "dd"):
        groups = [g["avg_diff_per_machine"].to_numpy(dtype=float) for _, g in sel.groupby(cat, sort=True) if len(g) >= 2]
        if len(groups) >= 2:
            f_stat, p_val = f_oneway(*groups)
        else:
            f_stat, p_val = np.nan, np.nan
        eta2 = _eta_squared_oneway(groups)
        cat_rows.append(
            {
                "category": cat,
                "n_groups": int(len(groups)),
                "f_stat": float(f_stat) if np.isfinite(f_stat) else np.nan,
                "p_value": float(p_val) if np.isfinite(p_val) else np.nan,
                "eta_squared": float(eta2) if np.isfinite(eta2) else np.nan,
            }
        )

    return pd.DataFrame(flag_rows), pd.DataFrame(cat_rows)


def _build_rules(selection_df: pd.DataFrame, topk_dd: int, min_dd_days: int) -> dict[str, Any]:
    weekday_mean = selection_df.groupby("weekday", sort=True)["avg_diff_per_machine"].mean()
    best_weekday = int(weekday_mean.idxmax())

    dd_stats = (
        selection_df.groupby("dd", sort=True)["avg_diff_per_machine"]
        .agg(["mean", "count"])
        .reset_index()
    )
    dd_valid = dd_stats[dd_stats["count"] >= int(min_dd_days)].copy()
    dd_topk = (
        dd_valid.sort_values(["mean", "dd"], ascending=[False, True])
        .head(int(topk_dd))["dd"]
        .astype(int)
        .tolist()
    )

    return {
        "best_weekday": best_weekday,
        "dd_topk": dd_topk,
    }


def _apply_rule(df: pd.DataFrame, rule: str, rule_meta: dict[str, Any]) -> pd.Series:
    if rule == "all_days":
        return pd.Series(np.ones(len(df), dtype=int), index=df.index)
    if rule == "event_only":
        return (df["is_any_event"] == 1).astype(int)
    if rule == "strong_zorome_only":
        return (df["is_strong_zorome_day"] == 1).astype(int)
    if rule == "zorome_only":
        return (df["is_zorome_day"] == 1).astype(int)
    if rule == "day_7x_only":
        return (df["is_day_7x"] == 1).astype(int)
    if rule == "day_1x_only":
        return (df["is_day_1x"] == 1).astype(int)
    if rule == "best_weekday_only":
        return (df["weekday"] == int(rule_meta["best_weekday"])).astype(int)
    if rule == "dd_topk_only":
        return df["dd"].isin(list(rule_meta["dd_topk"])).astype(int)
    raise ValueError(f"Unknown rule: {rule}")


def _evaluate_rules(
    holdout_df: pd.DataFrame,
    rule_meta: dict[str, Any],
    bootstrap_n: int,
    seed: int,
) -> pd.DataFrame:
    rules = (
        "all_days",
        "event_only",
        "strong_zorome_only",
        "zorome_only",
        "day_7x_only",
        "day_1x_only",
        "best_weekday_only",
        "dd_topk_only",
    )
    base_mean = float(holdout_df["avg_diff_per_machine"].mean())
    base_pos = float(holdout_df["is_positive_day"].mean())

    rows: list[dict[str, Any]] = []
    for i, r in enumerate(rules):
        play = _apply_rule(holdout_df, r, rule_meta)
        picked = holdout_df[play == 1].copy()
        y = picked["avg_diff_per_machine"].to_numpy(dtype=float)
        pos = picked["is_positive_day"].to_numpy(dtype=float)
        mean_val = float(np.nanmean(y)) if len(y) else np.nan
        pos_val = float(np.nanmean(pos)) if len(pos) else np.nan
        lo, hi = _bootstrap_mean_ci(y, n_boot=bootstrap_n, seed=seed + 100 * (i + 1))
        rows.append(
            {
                "rule": r,
                "n_play_days": int(len(picked)),
                "play_rate": float(len(picked) / len(holdout_df)),
                "avg_diff_mean": mean_val,
                "avg_diff_ci_low": lo,
                "avg_diff_ci_high": hi,
                "avg_diff_lift_vs_all": (mean_val - base_mean) if np.isfinite(mean_val) else np.nan,
                "positive_day_rate": pos_val,
                "positive_rate_lift_vs_all": (pos_val - base_pos) if np.isfinite(pos_val) else np.nan,
                "total_diff_sum": float(np.nansum(y)) if len(y) else 0.0,
            }
        )
    return pd.DataFrame(rows).sort_values("avg_diff_mean", ascending=False).reset_index(drop=True)


def main() -> int:
    args = build_parser().parse_args()
    out_prefix = Path(str(args.output_prefix))
    out_prefix.parent.mkdir(parents=True, exist_ok=True)

    db_path = resolve_db_path(str(args.db_path), pattern=str(args.db_glob))
    df = _load_daily_hall(db_path)
    selection_df, holdout_df = _split(df, args)
    flag_tests, cat_tests = _selection_tests(selection_df)
    rule_meta = _build_rules(selection_df, topk_dd=int(args.topk_dd), min_dd_days=int(args.min_dd_days))
    rule_eval = _evaluate_rules(
        holdout_df,
        rule_meta=rule_meta,
        bootstrap_n=int(args.bootstrap_n),
        seed=int(args.seed),
    )

    out_flag = out_prefix.with_name(out_prefix.name + "_selection_flag_tests.csv")
    out_cat = out_prefix.with_name(out_prefix.name + "_selection_category_tests.csv")
    out_rules = out_prefix.with_name(out_prefix.name + "_holdout_rule_eval.csv")
    out_json = out_prefix.with_name(out_prefix.name + "_summary.json")

    flag_tests.to_csv(out_flag, index=False, encoding="utf-8-sig")
    cat_tests.to_csv(out_cat, index=False, encoding="utf-8-sig")
    rule_eval.to_csv(out_rules, index=False, encoding="utf-8-sig")

    summary = {
        "db_path": str(db_path),
        "selection_range": {
            "start": str(pd.to_datetime(selection_df["date"]).min().date()),
            "end": str(pd.to_datetime(selection_df["date"]).max().date()),
            "n_days": int(selection_df["date"].nunique()),
        },
        "holdout_range": {
            "start": str(pd.to_datetime(holdout_df["date"]).min().date()),
            "end": str(pd.to_datetime(holdout_df["date"]).max().date()),
            "n_days": int(holdout_df["date"].nunique()),
            "all_days_avg_diff": float(holdout_df["avg_diff_per_machine"].mean()),
            "all_days_positive_rate": float(holdout_df["is_positive_day"].mean()),
        },
        "rule_meta": rule_meta,
        "outputs": {
            "selection_flag_tests": str(out_flag),
            "selection_category_tests": str(out_cat),
            "holdout_rule_eval": str(out_rules),
        },
    }
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[OK] saved: {out_flag}")
    print(f"[OK] saved: {out_cat}")
    print(f"[OK] saved: {out_rules}")
    print(f"[OK] saved: {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

