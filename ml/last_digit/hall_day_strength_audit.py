from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DEFAULT_THRESHOLDS = (0, 100, 200, 300)
DEFAULT_RULES = (
    "all_days",
    "event_only",
    "strong_zorome_only",
    "zorome_only",
    "day_7x_only",
    "day_1x_only",
    "best_weekday_only",
    "dd_topk_only",
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Audit hall-level day-selection strength across multiple thresholds.")
    p.add_argument("--db-dir", default="db")
    p.add_argument("--db-glob", default="*.db")
    p.add_argument("--exclude-db", default="integrated.db", help="Comma-separated DB names to exclude.")
    p.add_argument("--selection-start", default="2025-07-07")
    p.add_argument("--selection-end", default="2025-12-31")
    p.add_argument("--holdout-start", default="2026-01-01")
    p.add_argument("--holdout-end", default="2026-05-30")
    p.add_argument("--thresholds", default="0,100,200,300")
    p.add_argument("--topk-dd", type=int, default=5)
    p.add_argument("--min-dd-days", type=int, default=6)
    p.add_argument("--output-root", default="db/experiments/hall_day_strength_audit_20260601")
    return p


def _parse_csv_strs(raw: str) -> list[str]:
    return [x.strip() for x in str(raw).split(",") if x.strip()]


def _parse_csv_ints(raw: str) -> list[int]:
    out: list[int] = []
    for x in str(raw).split(","):
        s = x.strip()
        if s:
            out.append(int(s))
    return out


def load_daily_hall(db_path: Path) -> pd.DataFrame:
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
        raise ValueError(f"{db_path.name}: daily_hall_summary is empty")

    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
    df = df[df["date"].notna()].copy()
    for col in ("avg_diff_per_machine", "avg_games_per_machine", "total_machines", "win_rate"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    df["is_any_event"] = pd.to_numeric(df["is_any_event"], errors="coerce").fillna(0).astype(int)
    df["weekday"] = df["date"].dt.weekday.astype(int)
    df["dd"] = df["date"].dt.day.astype(int)
    df["mm"] = df["date"].dt.month.astype(int)
    df["is_zorome_day"] = df["dd"].isin([11, 22]).astype(int)
    df["is_strong_zorome_day"] = (df["dd"] == df["mm"]).astype(int)
    df["is_day_7x"] = df["dd"].isin([7, 17, 27]).astype(int)
    df["is_day_1x"] = df["dd"].isin([1, 11, 21, 31]).astype(int)
    return df.sort_values("date").reset_index(drop=True)


def add_strength_targets(df: pd.DataFrame, thresholds: list[int] | tuple[int, ...] = DEFAULT_THRESHOLDS) -> pd.DataFrame:
    out = df.copy()
    vals = pd.to_numeric(out["avg_diff_per_machine"], errors="coerce").fillna(0.0)
    for thr in thresholds:
        out[f"is_ge_{int(thr)}"] = (vals >= float(thr)).astype(int)
    return out


def split_ranges(
    df: pd.DataFrame,
    *,
    selection_start: str,
    selection_end: str,
    holdout_start: str,
    holdout_end: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    sel_start = pd.Timestamp(str(selection_start))
    sel_end = pd.Timestamp(str(selection_end))
    ho_start = pd.Timestamp(str(holdout_start))
    ho_end = min(pd.Timestamp(str(holdout_end)), pd.to_datetime(df["date"]).max())
    sel = df[(df["date"] >= sel_start) & (df["date"] <= sel_end)].copy()
    ho = df[(df["date"] >= ho_start) & (df["date"] <= ho_end)].copy()
    if sel.empty or ho.empty:
        raise ValueError("selection/holdout split produced empty frame")
    return sel, ho


def build_rule_meta(selection_df: pd.DataFrame, topk_dd: int, min_dd_days: int) -> dict[str, Any]:
    weekday_mean = selection_df.groupby("weekday", sort=True)["avg_diff_per_machine"].mean()
    best_weekday = int(weekday_mean.idxmax())
    dd_stats = selection_df.groupby("dd", sort=True)["avg_diff_per_machine"].agg(["mean", "count"]).reset_index()
    dd_topk = (
        dd_stats[dd_stats["count"] >= int(min_dd_days)]
        .sort_values(["mean", "dd"], ascending=[False, True])
        .head(int(topk_dd))["dd"]
        .astype(int)
        .tolist()
    )
    return {
        "best_weekday": best_weekday,
        "dd_topk": dd_topk,
    }


def apply_rule(df: pd.DataFrame, rule: str, rule_meta: dict[str, Any]) -> pd.Series:
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


def evaluate_target_rules(
    holdout_df: pd.DataFrame,
    *,
    rule_meta: dict[str, Any],
    target_col: str,
    rules: tuple[str, ...] = DEFAULT_RULES,
) -> pd.DataFrame:
    base_rate = float(pd.to_numeric(holdout_df[target_col], errors="coerce").mean())
    base_mean = float(pd.to_numeric(holdout_df["avg_diff_per_machine"], errors="coerce").mean())
    rows: list[dict[str, Any]] = []
    for rule_name in rules:
        play = apply_rule(holdout_df, rule_name, rule_meta)
        picked = holdout_df[play == 1].copy()
        y = pd.to_numeric(picked[target_col], errors="coerce")
        diff = pd.to_numeric(picked["avg_diff_per_machine"], errors="coerce")
        success_rate = float(y.mean()) if len(y) else np.nan
        diff_mean = float(diff.mean()) if len(diff) else np.nan
        rows.append(
            {
                "rule": rule_name,
                "target_col": target_col,
                "n_play_days": int(len(picked)),
                "play_rate": float(len(picked) / len(holdout_df)) if len(holdout_df) else np.nan,
                "base_rate_all": base_rate,
                "success_rate": success_rate,
                "success_rate_lift_vs_all": (success_rate - base_rate) if np.isfinite(success_rate) else np.nan,
                "avg_diff_mean": diff_mean,
                "avg_diff_lift_vs_all": (diff_mean - base_mean) if np.isfinite(diff_mean) else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values(["success_rate_lift_vs_all", "avg_diff_lift_vs_all"], ascending=[False, False]).reset_index(drop=True)


def summarize_selection_flags(selection_df: pd.DataFrame, target_cols: list[str]) -> pd.DataFrame:
    flags = ["is_any_event", "is_zorome_day", "is_strong_zorome_day", "is_day_7x", "is_day_1x"]
    rows: list[dict[str, Any]] = []
    for target_col in target_cols:
        base_rate = float(pd.to_numeric(selection_df[target_col], errors="coerce").mean())
        for feature in flags:
            on = selection_df[selection_df[feature] == 1]
            off = selection_df[selection_df[feature] == 0]
            on_rate = float(pd.to_numeric(on[target_col], errors="coerce").mean()) if len(on) else np.nan
            off_rate = float(pd.to_numeric(off[target_col], errors="coerce").mean()) if len(off) else np.nan
            rows.append(
                {
                    "target_col": target_col,
                    "feature": feature,
                    "n_on": int(len(on)),
                    "n_off": int(len(off)),
                    "base_rate_all": base_rate,
                    "success_rate_on": on_rate,
                    "success_rate_off": off_rate,
                    "lift_on_minus_all": (on_rate - base_rate) if np.isfinite(on_rate) else np.nan,
                    "lift_on_minus_off": (on_rate - off_rate) if np.isfinite(on_rate) and np.isfinite(off_rate) else np.nan,
                }
            )
    return pd.DataFrame(rows).sort_values(["target_col", "lift_on_minus_all"], ascending=[True, False]).reset_index(drop=True)


def summarize_selection_categories(selection_df: pd.DataFrame, target_cols: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for target_col in target_cols:
        base_rate = float(pd.to_numeric(selection_df[target_col], errors="coerce").mean())
        for category in ("weekday", "dd"):
            grp = (
                selection_df.groupby(category, sort=True)[target_col]
                .agg(["mean", "count"])
                .reset_index()
                .rename(columns={"mean": "success_rate", "count": "n_days"})
            )
            if grp.empty:
                continue
            best = grp.sort_values(["success_rate", category], ascending=[False, True]).iloc[0]
            rows.append(
                {
                    "target_col": target_col,
                    "category": category,
                    "base_rate_all": base_rate,
                    "best_value": int(best[category]),
                    "best_success_rate": float(best["success_rate"]),
                    "best_n_days": int(best["n_days"]),
                    "lift_best_vs_all": float(best["success_rate"] - base_rate),
                }
            )
    return pd.DataFrame(rows).sort_values(["target_col", "lift_best_vs_all"], ascending=[True, False]).reset_index(drop=True)


def run_store_audit(
    *,
    db_path: Path,
    thresholds: list[int],
    selection_start: str,
    selection_end: str,
    holdout_start: str,
    holdout_end: str,
    topk_dd: int,
    min_dd_days: int,
    out_dir: Path,
) -> dict[str, Any]:
    hall = add_strength_targets(load_daily_hall(db_path), thresholds=thresholds)
    selection_df, holdout_df = split_ranges(
        hall,
        selection_start=selection_start,
        selection_end=selection_end,
        holdout_start=holdout_start,
        holdout_end=holdout_end,
    )
    rule_meta = build_rule_meta(selection_df, topk_dd=topk_dd, min_dd_days=min_dd_days)
    target_cols = [f"is_ge_{int(x)}" for x in thresholds]

    flag_summary = summarize_selection_flags(selection_df, target_cols)
    cat_summary = summarize_selection_categories(selection_df, target_cols)

    rule_frames: list[pd.DataFrame] = []
    best_rows: list[dict[str, Any]] = []
    for thr in thresholds:
        target_col = f"is_ge_{int(thr)}"
        rule_eval = evaluate_target_rules(holdout_df, rule_meta=rule_meta, target_col=target_col)
        rule_eval.insert(0, "threshold", int(thr))
        rule_frames.append(rule_eval)
        non_all = rule_eval[rule_eval["rule"].astype(str) != "all_days"].copy()
        if not non_all.empty:
            best = non_all.sort_values(["success_rate_lift_vs_all", "avg_diff_lift_vs_all"], ascending=[False, False]).iloc[0]
            best_rows.append(
                {
                    "threshold": int(thr),
                    "target_col": target_col,
                    "base_rate_all": float(best["base_rate_all"]),
                    "best_rule": str(best["rule"]),
                    "best_success_rate": float(best["success_rate"]),
                    "best_success_rate_lift_vs_all": float(best["success_rate_lift_vs_all"]),
                    "best_avg_diff_mean": float(best["avg_diff_mean"]),
                    "best_avg_diff_lift_vs_all": float(best["avg_diff_lift_vs_all"]),
                    "best_play_rate": float(best["play_rate"]),
                    "best_n_play_days": int(best["n_play_days"]),
                }
            )
    rule_eval_all = pd.concat(rule_frames, ignore_index=True) if rule_frames else pd.DataFrame()
    best_rules = pd.DataFrame(best_rows)

    out_dir.mkdir(parents=True, exist_ok=True)
    flag_path = out_dir / "selection_threshold_flag_summary.csv"
    cat_path = out_dir / "selection_threshold_category_summary.csv"
    rule_path = out_dir / "holdout_threshold_rule_eval.csv"
    best_path = out_dir / "holdout_threshold_best_rules.csv"
    summary_path = out_dir / "summary.json"
    flag_summary.to_csv(flag_path, index=False, encoding="utf-8-sig")
    cat_summary.to_csv(cat_path, index=False, encoding="utf-8-sig")
    rule_eval_all.to_csv(rule_path, index=False, encoding="utf-8-sig")
    best_rules.to_csv(best_path, index=False, encoding="utf-8-sig")

    summary = {
        "db_path": str(db_path),
        "selection_days": int(selection_df["date"].nunique()),
        "holdout_days": int(holdout_df["date"].nunique()),
        "thresholds": [int(x) for x in thresholds],
        "rule_meta": rule_meta,
        "outputs": {
            "selection_flag_summary": str(flag_path),
            "selection_category_summary": str(cat_path),
            "holdout_rule_eval": str(rule_path),
            "holdout_best_rules": str(best_path),
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary["summary_json"] = str(summary_path)
    return summary


def main() -> int:
    args = build_parser().parse_args()
    db_dir = Path(str(args.db_dir))
    out_root = Path(str(args.output_root))
    out_root.mkdir(parents=True, exist_ok=True)
    thresholds = sorted(set(_parse_csv_ints(args.thresholds)))
    excluded = set(_parse_csv_strs(args.exclude_db))
    db_files = sorted([p for p in db_dir.glob(str(args.db_glob)) if p.name not in excluded])
    if not db_files:
        raise FileNotFoundError(f"No DB files matched in {db_dir} with glob={args.db_glob}")

    meta_rows: list[dict[str, Any]] = []
    best_frames: list[pd.DataFrame] = []
    rule_frames: list[pd.DataFrame] = []
    for db_path in db_files:
        store = db_path.stem
        store_dir = out_root / store
        summary = run_store_audit(
            db_path=db_path,
            thresholds=thresholds,
            selection_start=str(args.selection_start),
            selection_end=str(args.selection_end),
            holdout_start=str(args.holdout_start),
            holdout_end=str(args.holdout_end),
            topk_dd=int(args.topk_dd),
            min_dd_days=int(args.min_dd_days),
            out_dir=store_dir,
        )
        meta_rows.append(
            {
                "store": store,
                "db_path": str(db_path),
                "selection_days": int(summary["selection_days"]),
                "holdout_days": int(summary["holdout_days"]),
                "summary_json": str(summary["summary_json"]),
            }
        )
        best_path = store_dir / "holdout_threshold_best_rules.csv"
        if best_path.exists():
            best_df = pd.read_csv(best_path, encoding="utf-8-sig")
            if not best_df.empty:
                best_df.insert(0, "store", store)
                best_frames.append(best_df)
        rule_path = store_dir / "holdout_threshold_rule_eval.csv"
        if rule_path.exists():
            rule_df = pd.read_csv(rule_path, encoding="utf-8-sig")
            if not rule_df.empty:
                rule_df.insert(0, "store", store)
                rule_frames.append(rule_df)

    meta_df = pd.DataFrame(meta_rows)
    best_all = pd.concat(best_frames, ignore_index=True) if best_frames else pd.DataFrame()
    rule_all = pd.concat(rule_frames, ignore_index=True) if rule_frames else pd.DataFrame()

    meta_csv = out_root / "stores.csv"
    best_csv = out_root / "store_threshold_best_rules.csv"
    rule_csv = out_root / "store_threshold_rule_eval.csv"
    summary_json = out_root / "run_summary.json"
    meta_df.to_csv(meta_csv, index=False, encoding="utf-8-sig")
    best_all.to_csv(best_csv, index=False, encoding="utf-8-sig")
    rule_all.to_csv(rule_csv, index=False, encoding="utf-8-sig")
    summary_json.write_text(
        json.dumps(
            {
                "output_root": str(out_root),
                "db_count": int(len(db_files)),
                "thresholds": [int(x) for x in thresholds],
                "stores_csv": str(meta_csv),
                "store_threshold_best_rules_csv": str(best_csv),
                "store_threshold_rule_eval_csv": str(rule_csv),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"[OK] saved: {meta_csv}")
    print(f"[OK] saved: {best_csv}")
    print(f"[OK] saved: {rule_csv}")
    print(f"[OK] saved: {summary_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
