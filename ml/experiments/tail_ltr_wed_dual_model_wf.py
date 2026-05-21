from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.experiments import tail_ltr_profit_ops as ops
from ml.experiments import tail_time_adaptive_ltr_poc_improved as improved
from ml.experiments.tail_ltr_full_walkforward_ops import (
    bootstrap_ci,
    build_train_window,
    topk_day_table,
    train_and_predict_fold,
)


@dataclass
class Candidate:
    window_name: str
    decay_lambda: float


def parse_csv_ints(raw: str) -> list[int]:
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def parse_csv_floats(raw: str) -> list[float]:
    return [float(x.strip()) for x in raw.split(",") if x.strip()]


def _entropy_from_counts(counts: pd.Series) -> float:
    total = float(counts.sum())
    if total <= 0.0:
        return 0.0
    p = counts.to_numpy(dtype=float) / total
    p = p[p > 0]
    if p.size == 0:
        return 0.0
    return float(-(p * np.log(p)).sum())


def add_wednesday_specific_features(dataset: pd.DataFrame) -> pd.DataFrame:
    """
    Add Wednesday-specific tail features using only past information.

    Features:
    - tail_wed_win_rate_recent_8w
    - tail_gap_since_last_wed_hit
    - tail_wed_rotation_pos
    - tail_entropy_wed_recent
    """
    df = dataset.copy()
    df["_date"] = pd.to_datetime(df["date"])
    df["tail_wed_win_rate_recent_8w"] = 0.0
    df["tail_gap_since_last_wed_hit"] = 999.0
    df["tail_wed_rotation_pos"] = 0.0
    df["tail_entropy_wed_recent"] = 0.0

    # canonical per-tail daily frame for Wednesday history calculation
    base = (
        df[["_date", "last_digit", "is_top_2"]]
        .drop_duplicates(subset=["_date", "last_digit"])
        .copy()
    )
    base["is_wed"] = base["_date"].dt.day_name().eq("Wednesday")
    base = base.sort_values(["last_digit", "_date"]).reset_index(drop=True)

    # 1) tail_wed_win_rate_recent_8w (56 days lookback, Wednesdays only)
    rates = []
    for tail, g in base.groupby("last_digit", sort=False):
        hist = g[["is_top_2", "is_wed", "_date"]].copy()
        vals = []
        for i in range(len(hist)):
            d = hist.iloc[i]["_date"]
            past = hist.iloc[:i]
            past = past[past["is_wed"] & (past["_date"] >= d - pd.Timedelta(days=56))]
            vals.append(float(past["is_top_2"].mean()) if len(past) else 0.0)
        rates.extend(vals)
    base["tail_wed_win_rate_recent_8w"] = rates

    # 2) tail_gap_since_last_wed_hit (days since previous Wednesday hit for same tail)
    gaps = []
    for tail, g in base.groupby("last_digit", sort=False):
        last_hit_date: pd.Timestamp | None = None
        for _, row in g.iterrows():
            d = row["_date"]
            if last_hit_date is None:
                gaps.append(999.0)
            else:
                gaps.append(float((d - last_hit_date).days))
            if bool(row["is_wed"]) and int(row["is_top_2"]) == 1:
                last_hit_date = d
    base["tail_gap_since_last_wed_hit"] = gaps

    # 3) tail_wed_rotation_pos (distance from last Wednesday winning tails)
    # Map tails to circular 0-9; zorome(11) -> 0 for circular proxy.
    tail_map = (
        base[["last_digit"]]
        .drop_duplicates()
        .assign(tail_num=lambda x: pd.to_numeric(x["last_digit"], errors="coerce").fillna(0).astype(int))
    )
    tail_num_map = dict(zip(tail_map["last_digit"], tail_map["tail_num"].map(lambda v: int(v % 10))))

    # Build previous Wednesday winner set by date (from entire table, past only).
    day_win = (
        base[base["is_wed"]]
        .groupby("_date", sort=True)
        .apply(lambda g: list(g.loc[g["is_top_2"] == 1, "last_digit"]))
    )
    wed_dates = list(day_win.index)
    prev_wins_by_date: dict[pd.Timestamp, list[Any]] = {}
    prev_list: list[Any] = []
    for d in wed_dates:
        prev_wins_by_date[d] = list(prev_list)
        cur = day_win.loc[d]
        if len(cur) > 0:
            prev_list = cur

    rot_rows = []
    for _, row in base.iterrows():
        d = row["_date"]
        tail = row["last_digit"]
        # previous Wednesday date available before current date
        prev_dates = [wd for wd in wed_dates if wd < d]
        if not prev_dates:
            rot_rows.append(0.0)
            continue
        last_wd = prev_dates[-1]
        prev_tails = prev_wins_by_date.get(last_wd, [])
        if not prev_tails:
            rot_rows.append(0.0)
            continue
        cur_num = tail_num_map.get(tail, 0)
        dists = []
        for pt in prev_tails:
            p_num = tail_num_map.get(pt, 0)
            diff = abs(cur_num - p_num)
            dists.append(min(diff, 10 - diff))
        rot_rows.append(float(min(dists)) if dists else 0.0)
    base["tail_wed_rotation_pos"] = rot_rows

    # 4) tail_entropy_wed_recent (entropy of winners in trailing 8 Wednesdays)
    entropy_by_date: dict[pd.Timestamp, float] = {}
    for d in wed_dates:
        past_wed = [wd for wd in wed_dates if wd < d][-8:]
        hist_tails: list[Any] = []
        for wd in past_wed:
            hist_tails.extend(day_win.loc[wd])
        if not hist_tails:
            entropy_by_date[d] = 0.0
        else:
            counts = pd.Series(hist_tails).value_counts()
            entropy_by_date[d] = _entropy_from_counts(counts)

    # for non-Wednesday dates, inherit latest previous Wednesday entropy
    all_dates = sorted(base["_date"].unique())
    ent_any_date: dict[pd.Timestamp, float] = {}
    cur_ent = 0.0
    wed_set = set(wed_dates)
    for d in all_dates:
        if d in wed_set:
            cur_ent = entropy_by_date.get(d, cur_ent)
        ent_any_date[d] = cur_ent
    base["tail_entropy_wed_recent"] = base["_date"].map(ent_any_date).fillna(0.0).astype(float)

    merge_cols = [
        "_date",
        "last_digit",
        "tail_wed_win_rate_recent_8w",
        "tail_gap_since_last_wed_hit",
        "tail_wed_rotation_pos",
        "tail_entropy_wed_recent",
    ]
    df = df.merge(base[merge_cols], on=["_date", "last_digit"], how="left", suffixes=("", "_new"))
    for c in [
        "tail_wed_win_rate_recent_8w",
        "tail_gap_since_last_wed_hit",
        "tail_wed_rotation_pos",
        "tail_entropy_wed_recent",
    ]:
        if f"{c}_new" in df.columns:
            df[c] = df[f"{c}_new"].fillna(df[c] if c in df.columns else 0.0).astype(float)
            df = df.drop(columns=[f"{c}_new"])
    df = df.drop(columns=["_date"])
    return df


def filter_by_weekday(df: pd.DataFrame, *, is_wed: bool) -> pd.DataFrame:
    d = pd.to_datetime(df["date"]).dt.day_name().eq("Wednesday")
    return df.loc[d if is_wed else ~d].copy()


def eval_candidate(
    *,
    dataset: pd.DataFrame,
    all_features: list[str],
    seed: int,
    candidate: Candidate,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    q_grid: list[float],
    train_is_wed: bool,
    test_is_wed: bool,
    min_train_days: int,
) -> dict[str, Any] | None:
    dts = pd.to_datetime(dataset["date"])
    tr_start, tr_end = build_train_window(candidate.window_name, test_start)
    train_mask = (dts >= tr_start) & (dts <= tr_end)
    test_mask = (dts >= test_start) & (dts <= test_end)
    train_df = dataset.loc[train_mask].copy()
    test_df = dataset.loc[test_mask].copy()

    train_df = filter_by_weekday(train_df, is_wed=train_is_wed)
    test_df = filter_by_weekday(test_df, is_wed=test_is_wed)
    if train_df["date"].nunique() < min_train_days or test_df.empty:
        return None

    features = ops.select_features(train_df, all_features, "is_top_2", "all")
    cal_df, tst_df, choice = train_and_predict_fold(
        train_df=train_df,
        test_df=test_df,
        target="is_top_2",
        features=features,
        decay_lambda=candidate.decay_lambda,
        random_state=seed,
        model_params={},
        temperature_candidates=improved.CalibrationConfig().temperature_candidates,
        blend_weights=improved.CalibrationConfig().blend_weights,
        q_grid=q_grid,
        k=2,
    )

    cal_day = topk_day_table(cal_df, "pred", k=2)
    tst_day = topk_day_table(tst_df, "pred", k=2)
    cal_keep = cal_day["margin"] >= choice["threshold"]
    tst_keep = tst_day["margin"] >= choice["threshold"]
    cal_ex = np.where(cal_keep.to_numpy(), cal_day["excess"].to_numpy(), 0.0)
    tst_ex = np.where(tst_keep.to_numpy(), tst_day["excess"].to_numpy(), 0.0)

    tst_day = tst_day.copy()
    tst_day["excess_played"] = tst_ex
    tst_day["model_q"] = float(choice["q"])
    tst_day["model_threshold"] = float(choice["threshold"])

    return {
        "candidate": candidate,
        "choice": choice,
        "cal_score": float(np.mean(cal_ex)),
        "test_day": tst_day,
    }


def summarize(arr: np.ndarray) -> dict[str, float]:
    if arr.size == 0:
        return {"mean": 0.0, "std": 0.0, "n_days": 0}
    return {"mean": float(arr.mean()), "std": float(arr.std(ddof=0)), "n_days": int(arr.size)}


def main() -> int:
    p = argparse.ArgumentParser(description="Wednesday vs non-Wednesday dual-model walk-forward")
    p.add_argument("--output-prefix", default="db/experiments/tail_ltr_wed_dual_model_wf")
    p.add_argument("--seeds", default="42,77,123,202,303,404,505,606")
    p.add_argument("--windows", default="recent_60d,regime2_only,full_2025")
    p.add_argument("--lambdas", default="0.75,1.0,1.25")
    p.add_argument("--q-grid", default="0.0,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8")
    p.add_argument("--windows-wed", default="")
    p.add_argument("--lambdas-wed", default="")
    p.add_argument("--q-grid-wed", default="")
    p.add_argument("--windows-nonwed", default="")
    p.add_argument("--lambdas-nonwed", default="")
    p.add_argument("--q-grid-nonwed", default="")
    p.add_argument("--test-days", type=int, default=14)
    p.add_argument("--warmup-days", type=int, default=56, help="Initial skip days inside validation range before first test fold")
    p.add_argument("--min-train-days-wed", type=int, default=12)
    p.add_argument("--min-train-days-nonwed", type=int, default=42)
    p.add_argument("--valid-start", default="", help="Optional override for validation period start (YYYY-MM-DD)")
    p.add_argument("--valid-end", default="", help="Optional override for validation period end (YYYY-MM-DD)")
    p.add_argument("--disable-wed-features", action="store_true", help="Disable Wednesday-specific engineered features")
    args = p.parse_args()

    out_prefix = Path(args.output_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)

    seeds = parse_csv_ints(args.seeds)
    windows = [w.strip() for w in args.windows.split(",") if w.strip()]
    lambdas = parse_csv_floats(args.lambdas)
    q_grid = parse_csv_floats(args.q_grid)
    windows_wed = [w.strip() for w in args.windows_wed.split(",") if w.strip()] if args.windows_wed.strip() else windows
    lambdas_wed = parse_csv_floats(args.lambdas_wed) if args.lambdas_wed.strip() else lambdas
    q_grid_wed = parse_csv_floats(args.q_grid_wed) if args.q_grid_wed.strip() else q_grid
    windows_nonwed = [w.strip() for w in args.windows_nonwed.split(",") if w.strip()] if args.windows_nonwed.strip() else windows
    lambdas_nonwed = parse_csv_floats(args.lambdas_nonwed) if args.lambdas_nonwed.strip() else lambdas
    q_grid_nonwed = parse_csv_floats(args.q_grid_nonwed) if args.q_grid_nonwed.strip() else q_grid
    candidates_wed = [Candidate(w, l) for w in windows_wed for l in lambdas_wed]
    candidates_nonwed = [Candidate(w, l) for w in windows_nonwed for l in lambdas_nonwed]

    dataset, _ = ops.load_dataset(ops.resolve_db_path(""))
    if not args.disable_wed_features:
        dataset = add_wednesday_specific_features(dataset)
    dataset = dataset.sort_values("date").reset_index(drop=True)
    all_features = improved.get_numeric_features(dataset)
    split_cfg = improved.build_fixed_split_configs(dataset)["regime_3_fixed_split"]
    valid_start = pd.Timestamp(args.valid_start) if args.valid_start.strip() else pd.Timestamp(split_cfg["valid_start"])
    valid_end = pd.Timestamp(args.valid_end) if args.valid_end.strip() else pd.Timestamp(split_cfg["valid_end"])
    valid_dates = sorted(pd.to_datetime(dataset["date"].unique()))
    valid_dates = [d for d in valid_dates if valid_start <= d <= valid_end]

    day_rows: list[dict[str, Any]] = []
    fold_rows: list[dict[str, Any]] = []

    for seed in seeds:
        idx = max(0, args.warmup_days)
        fold = 0
        while idx < len(valid_dates):
            test_start = valid_dates[idx]
            test_block = valid_dates[idx : idx + args.test_days]
            if not test_block:
                break
            test_end = test_block[-1]

            # Wednesday model search
            wed_evals: list[dict[str, Any]] = []
            for cand in candidates_wed:
                r = eval_candidate(
                    dataset=dataset,
                    all_features=all_features,
                    seed=seed,
                    candidate=cand,
                    test_start=test_start,
                    test_end=test_end,
                    q_grid=q_grid_wed,
                    train_is_wed=True,
                    test_is_wed=True,
                    min_train_days=args.min_train_days_wed,
                )
                if r is not None:
                    wed_evals.append(r)

            # Non-Wednesday model search
            non_evals: list[dict[str, Any]] = []
            for cand in candidates_nonwed:
                r = eval_candidate(
                    dataset=dataset,
                    all_features=all_features,
                    seed=seed,
                    candidate=cand,
                    test_start=test_start,
                    test_end=test_end,
                    q_grid=q_grid_nonwed,
                    train_is_wed=False,
                    test_is_wed=False,
                    min_train_days=args.min_train_days_nonwed,
                )
                if r is not None:
                    non_evals.append(r)

            if not wed_evals or not non_evals:
                idx += args.test_days
                continue

            best_wed = sorted(wed_evals, key=lambda x: x["cal_score"], reverse=True)[0]
            best_non = sorted(non_evals, key=lambda x: x["cal_score"], reverse=True)[0]
            test_day = pd.concat([best_wed["test_day"], best_non["test_day"]], ignore_index=True).sort_values("date")
            test_day["weekday"] = pd.to_datetime(test_day["date"]).dt.day_name()
            test_day["selected_model"] = np.where(
                test_day["weekday"].eq("Wednesday"),
                f"{best_wed['candidate'].window_name}|{best_wed['candidate'].decay_lambda}",
                f"{best_non['candidate'].window_name}|{best_non['candidate'].decay_lambda}",
            )
            for _, r in test_day.iterrows():
                day_rows.append(
                    {
                        "seed": seed,
                        "fold": fold,
                        "date": str(r["date"]),
                        "weekday": r["weekday"],
                        "selected_model": r["selected_model"],
                        "excess": float(r["excess_played"]),
                    }
                )

            fold_rows.append(
                {
                    "seed": seed,
                    "fold": fold,
                    "test_start": str(test_start.date()),
                    "test_end": str(test_end.date()),
                    "wed_model": f"{best_wed['candidate'].window_name}|{best_wed['candidate'].decay_lambda}",
                    "wed_q": float(best_wed["choice"]["q"]),
                    "nonwed_model": f"{best_non['candidate'].window_name}|{best_non['candidate'].decay_lambda}",
                    "nonwed_q": float(best_non["choice"]["q"]),
                    "test_mean_excess": float(test_day["excess_played"].mean()),
                }
            )
            fold += 1
            idx += args.test_days

    if day_rows:
        day_df = pd.DataFrame(day_rows).sort_values(["seed", "date"])
    else:
        day_df = pd.DataFrame(columns=["seed", "fold", "date", "weekday", "selected_model", "excess"])
    arr = day_df["excess"].to_numpy(dtype=float) if not day_df.empty else np.array([], dtype=float)
    wed_arr = day_df.loc[day_df["weekday"].eq("Wednesday"), "excess"].to_numpy(dtype=float) if not day_df.empty else np.array([], dtype=float)
    non_arr = day_df.loc[~day_df["weekday"].eq("Wednesday"), "excess"].to_numpy(dtype=float) if not day_df.empty else np.array([], dtype=float)

    summary = {
        "config": {
            "seeds": seeds,
            "windows": windows,
            "lambdas": lambdas,
            "q_grid": q_grid,
            "windows_wed": windows_wed,
            "lambdas_wed": lambdas_wed,
            "q_grid_wed": q_grid_wed,
            "windows_nonwed": windows_nonwed,
            "lambdas_nonwed": lambdas_nonwed,
            "q_grid_nonwed": q_grid_nonwed,
            "test_days": args.test_days,
            "warmup_days": args.warmup_days,
            "min_train_days_wed": args.min_train_days_wed,
            "min_train_days_nonwed": args.min_train_days_nonwed,
            "valid_start": str(valid_start.date()),
            "valid_end": str(valid_end.date()),
            "disable_wed_features": bool(args.disable_wed_features),
        },
        "overall": {**summarize(arr), **bootstrap_ci(arr, n_boot=10000, seed=20260525)},
        "wednesday_only": {**summarize(wed_arr), **bootstrap_ci(wed_arr, n_boot=10000, seed=20260525)},
        "non_wednesday": {**summarize(non_arr), **bootstrap_ci(non_arr, n_boot=10000, seed=20260525)},
    }

    out_json = out_prefix.with_suffix(".json")
    out_days = out_prefix.with_name(out_prefix.name + "_days.csv")
    out_folds = out_prefix.with_name(out_prefix.name + "_folds.csv")
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    day_df.to_csv(out_days, index=False, encoding="utf-8-sig")
    pd.DataFrame(fold_rows).to_csv(out_folds, index=False, encoding="utf-8-sig")

    print("Saved:", out_json)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("Saved:", out_days)
    print("Saved:", out_folds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
