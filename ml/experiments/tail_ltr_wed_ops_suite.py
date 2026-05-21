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
from ml.experiments.store_optimized_pipeline import StoreOptimizedFeatureBuilder
from ml.experiments.tail_ltr_full_walkforward_ops import bootstrap_ci, build_train_window, train_and_predict_fold
from ml.experiments.tail_ltr_wed_dual_model_wf import Candidate, add_wednesday_specific_features, eval_candidate, summarize


def parse_csv_ints(raw: str) -> list[int]:
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def parse_csv_floats(raw: str) -> list[float]:
    return [float(x.strip()) for x in raw.split(",") if x.strip()]


def parse_csv_strs(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


def load_base_dataset(*, disable_wed_features: bool = False) -> pd.DataFrame:
    dataset, _ = ops.load_dataset(ops.resolve_db_path(""))
    if not disable_wed_features:
        dataset = add_wednesday_specific_features(dataset)
    return dataset.sort_values("date").reset_index(drop=True)


def valid_dates_from_dataset(
    dataset: pd.DataFrame,
    *,
    valid_start: str | None = None,
    valid_end: str | None = None,
) -> list[pd.Timestamp]:
    split_cfg = improved.build_fixed_split_configs(dataset)["regime_3_fixed_split"]
    start = pd.Timestamp(valid_start) if valid_start else pd.Timestamp(split_cfg["valid_start"])
    end = pd.Timestamp(valid_end) if valid_end else pd.Timestamp(split_cfg["valid_end"])
    d = sorted(pd.to_datetime(dataset["date"].unique()))
    return [x for x in d if start <= x <= end]


@dataclass
class PolicyConfig:
    seeds: list[int]
    test_days: int
    warmup_days: int
    min_train_days_wed: int
    min_train_days_nonwed: int
    q_grid_wed: list[float]
    q_grid_nonwed: list[float]
    candidates_wed: list[Candidate]
    candidates_nonwed: list[Candidate]


def _pick_best_eval(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return sorted(rows, key=lambda x: x["cal_score"], reverse=True)[0]


def run_dual_policy(
    dataset: pd.DataFrame,
    valid_dates: list[pd.Timestamp],
    cfg: PolicyConfig,
    *,
    cadence: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    all_features = improved.get_numeric_features(dataset)
    day_rows: list[dict[str, Any]] = []
    fold_rows: list[dict[str, Any]] = []

    for seed in cfg.seeds:
        idx = max(0, cfg.warmup_days)
        fold = 0
        month_cache: dict[str, tuple[Candidate, Candidate]] = {}
        while idx < len(valid_dates):
            test_start = valid_dates[idx]
            test_block = valid_dates[idx : idx + cfg.test_days]
            if not test_block:
                break
            test_end = test_block[-1]
            month_key = f"{test_start.year:04d}-{test_start.month:02d}"

            # candidate selection
            if cadence == "month" and month_key in month_cache:
                wed_cand, non_cand = month_cache[month_key]
                wed_evals: list[dict[str, Any]] = []
                non_evals: list[dict[str, Any]] = []
                r_w = eval_candidate(
                    dataset=dataset,
                    all_features=all_features,
                    seed=seed,
                    candidate=wed_cand,
                    test_start=test_start,
                    test_end=test_end,
                    q_grid=cfg.q_grid_wed,
                    train_is_wed=True,
                    test_is_wed=True,
                    min_train_days=cfg.min_train_days_wed,
                )
                if r_w is not None:
                    wed_evals.append(r_w)
                r_n = eval_candidate(
                    dataset=dataset,
                    all_features=all_features,
                    seed=seed,
                    candidate=non_cand,
                    test_start=test_start,
                    test_end=test_end,
                    q_grid=cfg.q_grid_nonwed,
                    train_is_wed=False,
                    test_is_wed=False,
                    min_train_days=cfg.min_train_days_nonwed,
                )
                if r_n is not None:
                    non_evals.append(r_n)
            else:
                wed_evals = []
                for cand in cfg.candidates_wed:
                    r = eval_candidate(
                        dataset=dataset,
                        all_features=all_features,
                        seed=seed,
                        candidate=cand,
                        test_start=test_start,
                        test_end=test_end,
                        q_grid=cfg.q_grid_wed,
                        train_is_wed=True,
                        test_is_wed=True,
                        min_train_days=cfg.min_train_days_wed,
                    )
                    if r is not None:
                        wed_evals.append(r)

                non_evals = []
                for cand in cfg.candidates_nonwed:
                    r = eval_candidate(
                        dataset=dataset,
                        all_features=all_features,
                        seed=seed,
                        candidate=cand,
                        test_start=test_start,
                        test_end=test_end,
                        q_grid=cfg.q_grid_nonwed,
                        train_is_wed=False,
                        test_is_wed=False,
                        min_train_days=cfg.min_train_days_nonwed,
                    )
                    if r is not None:
                        non_evals.append(r)

            best_wed = _pick_best_eval(wed_evals)
            best_non = _pick_best_eval(non_evals)
            if best_wed is None or best_non is None:
                idx += cfg.test_days
                continue
            if cadence == "month" and month_key not in month_cache:
                month_cache[month_key] = (best_wed["candidate"], best_non["candidate"])

            test_day = pd.concat([best_wed["test_day"], best_non["test_day"]], ignore_index=True).sort_values("date")
            test_day["weekday"] = pd.to_datetime(test_day["date"]).dt.day_name()
            test_day["selected_model"] = np.where(
                test_day["weekday"].eq("Wednesday"),
                f"{best_wed['candidate'].window_name}|{best_wed['candidate'].decay_lambda}",
                f"{best_non['candidate'].window_name}|{best_non['candidate'].decay_lambda}",
            )
            test_day["selected_q"] = np.where(
                test_day["weekday"].eq("Wednesday"),
                float(best_wed["choice"]["q"]),
                float(best_non["choice"]["q"]),
            )
            for _, r in test_day.iterrows():
                day_rows.append(
                    {
                        "cadence": cadence,
                        "seed": seed,
                        "fold": fold,
                        "date": str(r["date"]),
                        "weekday": r["weekday"],
                        "selected_model": r["selected_model"],
                        "selected_q": float(r["selected_q"]),
                        "excess": float(r["excess_played"]),
                    }
                )

            fold_rows.append(
                {
                    "cadence": cadence,
                    "seed": seed,
                    "fold": fold,
                    "month_key": month_key,
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
            idx += cfg.test_days

    day_df = pd.DataFrame(day_rows)
    if not day_df.empty:
        day_df = day_df.sort_values(["seed", "date"])
    fold_df = pd.DataFrame(fold_rows)

    arr = day_df["excess"].to_numpy(dtype=float) if not day_df.empty else np.array([], dtype=float)
    wed_arr = day_df.loc[day_df["weekday"].eq("Wednesday"), "excess"].to_numpy(dtype=float) if not day_df.empty else np.array([], dtype=float)
    non_arr = day_df.loc[~day_df["weekday"].eq("Wednesday"), "excess"].to_numpy(dtype=float) if not day_df.empty else np.array([], dtype=float)
    summary = {
        "overall": {**summarize(arr), **bootstrap_ci(arr, n_boot=10000, seed=20260526)},
        "wednesday_only": {**summarize(wed_arr), **bootstrap_ci(wed_arr, n_boot=10000, seed=20260526)},
        "non_wednesday": {**summarize(non_arr), **bootstrap_ci(non_arr, n_boot=10000, seed=20260526)},
    }
    return day_df, fold_df, summary


def cmd_compare_cadence(args: argparse.Namespace) -> int:
    dataset = load_base_dataset(disable_wed_features=args.disable_wed_features)
    valid_dates = valid_dates_from_dataset(dataset, valid_start=args.valid_start or None, valid_end=args.valid_end or None)
    cfg = PolicyConfig(
        seeds=parse_csv_ints(args.seeds),
        test_days=args.test_days,
        warmup_days=args.warmup_days,
        min_train_days_wed=args.min_train_days_wed,
        min_train_days_nonwed=args.min_train_days_nonwed,
        q_grid_wed=parse_csv_floats(args.q_grid_wed),
        q_grid_nonwed=parse_csv_floats(args.q_grid_nonwed),
        candidates_wed=[Candidate(w, l) for w in parse_csv_strs(args.windows_wed) for l in parse_csv_floats(args.lambdas_wed)],
        candidates_nonwed=[Candidate(w, l) for w in parse_csv_strs(args.windows_nonwed) for l in parse_csv_floats(args.lambdas_nonwed)],
    )

    out_prefix = Path(args.output_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)

    fold_day, fold_folds, fold_summary = run_dual_policy(dataset, valid_dates, cfg, cadence="fold")
    month_day, month_folds, month_summary = run_dual_policy(dataset, valid_dates, cfg, cadence="month")

    all_days = pd.concat([fold_day, month_day], ignore_index=True)
    all_folds = pd.concat([fold_folds, month_folds], ignore_index=True)
    all_days.to_csv(out_prefix.with_name(out_prefix.name + "_days.csv"), index=False, encoding="utf-8-sig")
    all_folds.to_csv(out_prefix.with_name(out_prefix.name + "_folds.csv"), index=False, encoding="utf-8-sig")

    payload = {
        "config": {
            "seeds": cfg.seeds,
            "test_days": cfg.test_days,
            "warmup_days": cfg.warmup_days,
            "min_train_days_wed": cfg.min_train_days_wed,
            "min_train_days_nonwed": cfg.min_train_days_nonwed,
            "windows_wed": parse_csv_strs(args.windows_wed),
            "lambdas_wed": parse_csv_floats(args.lambdas_wed),
            "q_grid_wed": cfg.q_grid_wed,
            "windows_nonwed": parse_csv_strs(args.windows_nonwed),
            "lambdas_nonwed": parse_csv_floats(args.lambdas_nonwed),
            "q_grid_nonwed": cfg.q_grid_nonwed,
            "valid_start": str(valid_dates[0].date()) if valid_dates else "",
            "valid_end": str(valid_dates[-1].date()) if valid_dates else "",
            "disable_wed_features": bool(args.disable_wed_features),
        },
        "fold_cadence": fold_summary,
        "monthly_cadence": month_summary,
        "diff_monthly_minus_fold": {
            "overall_mean": float(month_summary["overall"]["mean"] - fold_summary["overall"]["mean"]),
            "wednesday_mean": float(month_summary["wednesday_only"]["mean"] - fold_summary["wednesday_only"]["mean"]),
            "non_wednesday_mean": float(month_summary["non_wednesday"]["mean"] - fold_summary["non_wednesday"]["mean"]),
        },
    }
    out_json = out_prefix.with_suffix(".json")
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Saved:", out_json)
    print(json.dumps({"fold": fold_summary["overall"], "monthly": month_summary["overall"]}, ensure_ascii=False, indent=2))
    return 0


def cmd_drift_report(args: argparse.Namespace) -> int:
    in_csv = Path(args.input_days_csv)
    df = pd.read_csv(in_csv)
    if df.empty:
        raise ValueError(f"Empty days csv: {in_csv}")
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["seed", "date"]).reset_index(drop=True)

    win = int(args.window_days)
    # daily aggregate across seeds
    d = df.groupby("date", sort=True).agg(
        mean_excess=("excess", "mean"),
        std_excess=("excess", "std"),
        n=("excess", "size"),
    ).reset_index()
    d["std_excess"] = d["std_excess"].fillna(0.0)
    d["rolling_mean_excess"] = d["mean_excess"].rolling(win, min_periods=max(7, win // 2)).mean()
    d["rolling_std_excess"] = d["mean_excess"].rolling(win, min_periods=max(7, win // 2)).std().fillna(0.0)
    d["rolling_se"] = d["rolling_std_excess"] / np.sqrt(win)
    d["rolling_ci_low"] = d["rolling_mean_excess"] - 1.96 * d["rolling_se"]
    d["alert_mean_negative"] = d["rolling_mean_excess"] < 0.0
    d["alert_ci_negative"] = d["rolling_ci_low"] < 0.0

    baseline_days = int(args.baseline_days)
    base = d.head(min(baseline_days, len(d)))
    base_mean = float(base["mean_excess"].mean()) if not base.empty else 0.0
    base_std = float(base["mean_excess"].std(ddof=0)) if not base.empty else 1.0
    if base_std <= 1e-9:
        base_std = 1.0
    d["z_vs_baseline"] = (d["mean_excess"] - base_mean) / base_std
    d["alert_z_drop"] = d["z_vs_baseline"] <= float(args.z_drop_threshold)

    model_mix = (
        df.groupby(["date", "selected_model"], sort=True).size().rename("cnt").reset_index()
    )
    pivot = model_mix.pivot(index="date", columns="selected_model", values="cnt").fillna(0.0)
    pivot = pivot.div(pivot.sum(axis=1), axis=0).reset_index()
    drift_csv = Path(args.output_prefix).with_name(Path(args.output_prefix).name + "_daily.csv")
    mix_csv = Path(args.output_prefix).with_name(Path(args.output_prefix).name + "_model_mix.csv")
    out_json = Path(args.output_prefix).with_suffix(".json")

    d.to_csv(drift_csv, index=False, encoding="utf-8-sig")
    pivot.to_csv(mix_csv, index=False, encoding="utf-8-sig")

    recent = d.tail(win)
    summary = {
        "input_days_csv": str(in_csv),
        "window_days": win,
        "baseline_days": baseline_days,
        "baseline_mean_excess": base_mean,
        "baseline_std_excess": base_std,
        "recent_mean_excess": float(recent["mean_excess"].mean()) if not recent.empty else 0.0,
        "recent_alert_mean_negative_days": int(recent["alert_mean_negative"].sum()) if not recent.empty else 0,
        "recent_alert_ci_negative_days": int(recent["alert_ci_negative"].sum()) if not recent.empty else 0,
        "recent_alert_z_drop_days": int(recent["alert_z_drop"].sum()) if not recent.empty else 0,
        "last_day": str(d["date"].max().date()),
        "last_day_mean_excess": float(d.iloc[-1]["mean_excess"]),
        "last_day_rolling_mean_excess": float(d.iloc[-1]["rolling_mean_excess"]) if pd.notna(d.iloc[-1]["rolling_mean_excess"]) else 0.0,
        "last_day_rolling_ci_low": float(d.iloc[-1]["rolling_ci_low"]) if pd.notna(d.iloc[-1]["rolling_ci_low"]) else 0.0,
    }
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Saved:", out_json)
    print("Saved:", drift_csv)
    print("Saved:", mix_csv)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def cmd_forecast_nextday(args: argparse.Namespace) -> int:
    db_path = ops.resolve_db_path("")
    hist, _ = ops.load_dataset(db_path)
    hist = hist.sort_values("date").reset_index(drop=True)

    fb = StoreOptimizedFeatureBuilder()
    fc = fb.build_store_forecast_dataset(db_path=db_path, grouping="last_digit").copy()
    fc = improved.add_regime_and_cluster_features(fc)

    # align schema
    for c in hist.columns:
        if c not in fc.columns:
            fc[c] = 0 if c == "is_top_2" else np.nan
    for c in fc.columns:
        if c not in hist.columns:
            hist[c] = np.nan
    hist = hist[sorted(hist.columns)]
    fc = fc[hist.columns]

    combo = pd.concat([hist, fc], ignore_index=True, sort=False)
    combo = add_wednesday_specific_features(combo)
    next_date = pd.to_datetime(fc["date"]).max()
    next_df = combo[pd.to_datetime(combo["date"]) == next_date].copy()
    weekday = next_date.day_name()

    seed = int(args.seed)
    q_grid_wed = parse_csv_floats(args.q_grid_wed)
    q_grid_non = parse_csv_floats(args.q_grid_nonwed)
    cands_wed = [Candidate(w, l) for w in parse_csv_strs(args.windows_wed) for l in parse_csv_floats(args.lambdas_wed)]
    cands_non = [Candidate(w, l) for w in parse_csv_strs(args.windows_nonwed) for l in parse_csv_floats(args.lambdas_nonwed)]
    all_features = improved.get_numeric_features(combo)

    if weekday == "Wednesday":
        active = cands_wed
        q_grid = q_grid_wed
        train_is_wed = True
    else:
        active = cands_non
        q_grid = q_grid_non
        train_is_wed = False

    rows: list[tuple[float, Candidate, dict[str, float], pd.DataFrame]] = []
    for cand in active:
        r = eval_candidate(
            dataset=combo,
            all_features=all_features,
            seed=seed,
            candidate=cand,
            test_start=next_date,
            test_end=next_date,
            q_grid=q_grid,
            train_is_wed=train_is_wed,
            test_is_wed=train_is_wed,
            min_train_days=int(args.min_train_days_wed if train_is_wed else args.min_train_days_nonwed),
        )
        if r is None:
            continue
        test_day = r["test_day"].copy()
        score = float(r["cal_score"])
        rows.append((score, r["candidate"], r["choice"], test_day))

    if not rows:
        raise RuntimeError("No valid candidate produced next-day prediction.")
    score, cand, choice, _ = sorted(rows, key=lambda x: x[0], reverse=True)[0]

    # retrain/predict for ranking table
    train_start, train_end = build_train_window(cand.window_name, next_date)
    train = combo[(pd.to_datetime(combo["date"]) >= train_start) & (pd.to_datetime(combo["date"]) <= train_end)].copy()
    # weekday filter consistent with selected branch
    if train_is_wed:
        train = train[pd.to_datetime(train["date"]).dt.day_name().eq("Wednesday")]
    else:
        train = train[pd.to_datetime(train["date"]).dt.day_name() != "Wednesday"]

    feats = ops.select_features(train, improved.get_numeric_features(train), "is_top_2", "all")
    feats = [f for f in feats if f in next_df.columns]
    cal_pred, test_pred, choice2 = train_and_predict_fold(
        train_df=train,
        test_df=next_df,
        target="is_top_2",
        features=feats,
        decay_lambda=cand.decay_lambda,
        random_state=seed,
        model_params={},
        temperature_candidates=improved.CalibrationConfig().temperature_candidates,
        blend_weights=improved.CalibrationConfig().blend_weights,
        q_grid=q_grid,
        k=2,
    )
    _ = cal_pred
    pred = test_pred.copy()
    pred["last_digit"] = next_df["last_digit"].values
    pred = pred.sort_values("pred", ascending=False).reset_index(drop=True)
    out_rank = pred[["last_digit", "pred"]].copy()
    out_rank["rank"] = np.arange(1, len(out_rank) + 1)
    out_rank = out_rank[["rank", "last_digit", "pred"]]

    out_prefix = Path(args.output_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    out_csv = out_prefix.with_suffix(".csv")
    out_json = out_prefix.with_suffix(".json")
    out_rank.to_csv(out_csv, index=False, encoding="utf-8-sig")
    payload = {
        "db_path": str(db_path),
        "source_latest_date": str(pd.to_datetime(hist["date"]).max().date()),
        "target_date": str(next_date.date()),
        "target_weekday": weekday,
        "selected_branch": "Wednesday" if train_is_wed else "Non-Wednesday",
        "selected_candidate": {
            "window": cand.window_name,
            "lambda": cand.decay_lambda,
            "seed": seed,
            "q_from_eval": float(choice["q"]),
            "q_from_final_refit": float(choice2["q"]),
            "threshold": float(choice2["threshold"]),
            "blend_weight": float(choice2["blend_weight"]),
            "cal_score": float(score),
        },
        "top2_prediction": out_rank.head(2).to_dict(orient="records"),
        "full_ranking": out_rank.to_dict(orient="records"),
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Saved:", out_json)
    print("Saved:", out_csv)
    print(json.dumps({"target_date": payload["target_date"], "top2": payload["top2_prediction"]}, ensure_ascii=False, indent=2))
    return 0


def cmd_monthly_update_check(args: argparse.Namespace) -> int:
    dataset = load_base_dataset(disable_wed_features=args.disable_wed_features)
    all_dates = sorted(pd.to_datetime(dataset["date"].unique()))
    if not all_dates:
        raise RuntimeError("No dates found in dataset.")

    run_date = pd.Timestamp(args.run_date) if args.run_date else pd.Timestamp.now().normalize()
    latest_data_date = all_dates[-1]
    period_end = min(run_date - pd.Timedelta(days=1), latest_data_date)
    period_start = period_end - pd.Timedelta(days=int(args.eval_days) - 1)
    valid_dates = [d for d in all_dates if period_start <= d <= period_end]
    if len(valid_dates) < max(14, int(args.eval_days // 2)):
        raise RuntimeError(
            f"Not enough evaluation dates in [{period_start.date()}, {period_end.date()}]: {len(valid_dates)} days."
        )

    seeds = parse_csv_ints(args.seeds)

    inc_cfg = PolicyConfig(
        seeds=seeds,
        test_days=args.test_days,
        warmup_days=0,
        min_train_days_wed=args.min_train_days_wed,
        min_train_days_nonwed=args.min_train_days_nonwed,
        q_grid_wed=parse_csv_floats(args.inc_q_grid_wed),
        q_grid_nonwed=parse_csv_floats(args.inc_q_grid_nonwed),
        candidates_wed=[
            Candidate(w, l)
            for w in parse_csv_strs(args.inc_windows_wed)
            for l in parse_csv_floats(args.inc_lambdas_wed)
        ],
        candidates_nonwed=[
            Candidate(w, l)
            for w in parse_csv_strs(args.inc_windows_nonwed)
            for l in parse_csv_floats(args.inc_lambdas_nonwed)
        ],
    )
    ch_cfg = PolicyConfig(
        seeds=seeds,
        test_days=args.test_days,
        warmup_days=0,
        min_train_days_wed=args.min_train_days_wed,
        min_train_days_nonwed=args.min_train_days_nonwed,
        q_grid_wed=parse_csv_floats(args.ch_q_grid_wed),
        q_grid_nonwed=parse_csv_floats(args.ch_q_grid_nonwed),
        candidates_wed=[
            Candidate(w, l)
            for w in parse_csv_strs(args.ch_windows_wed)
            for l in parse_csv_floats(args.ch_lambdas_wed)
        ],
        candidates_nonwed=[
            Candidate(w, l)
            for w in parse_csv_strs(args.ch_windows_nonwed)
            for l in parse_csv_floats(args.ch_lambdas_nonwed)
        ],
    )

    inc_days, inc_folds, inc_summary = run_dual_policy(dataset, valid_dates, inc_cfg, cadence=args.inc_cadence)
    ch_days, ch_folds, ch_summary = run_dual_policy(dataset, valid_dates, ch_cfg, cadence=args.ch_cadence)

    inc = inc_summary["overall"]
    ch = ch_summary["overall"]
    mean_gain = float(ch["mean"] - inc["mean"])
    degrade_flag = bool((inc["ci_low"] < float(args.degrade_ci_low)) or (inc["p_gt_0"] < float(args.degrade_p_gt0)))
    improve_flag = bool(
        (mean_gain >= float(args.min_mean_gain_for_update))
        and (ch["p_gt_0"] >= float(args.min_challenger_p_gt0))
        and (ch["ci_low"] >= inc["ci_low"])
    )
    if degrade_flag:
        needs_update = bool(ch["mean"] >= inc["mean"])
        reason = "incumbent_degraded"
    else:
        needs_update = improve_flag
        reason = "challenger_improves_enough" if needs_update else "insufficient_gain"

    out_prefix = Path(args.output_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    inc_days.to_csv(out_prefix.with_name(out_prefix.name + "_incumbent_days.csv"), index=False, encoding="utf-8-sig")
    ch_days.to_csv(out_prefix.with_name(out_prefix.name + "_challenger_days.csv"), index=False, encoding="utf-8-sig")
    inc_folds.to_csv(out_prefix.with_name(out_prefix.name + "_incumbent_folds.csv"), index=False, encoding="utf-8-sig")
    ch_folds.to_csv(out_prefix.with_name(out_prefix.name + "_challenger_folds.csv"), index=False, encoding="utf-8-sig")

    payload = {
        "run_date": str(run_date.date()),
        "latest_data_date": str(latest_data_date.date()),
        "evaluation_period": {"start": str(period_start.date()), "end": str(period_end.date()), "n_days": len(valid_dates)},
        "thresholds": {
            "min_mean_gain_for_update": float(args.min_mean_gain_for_update),
            "min_challenger_p_gt0": float(args.min_challenger_p_gt0),
            "degrade_ci_low": float(args.degrade_ci_low),
            "degrade_p_gt0": float(args.degrade_p_gt0),
        },
        "incumbent": {"cadence": args.inc_cadence, "summary": inc_summary},
        "challenger": {"cadence": args.ch_cadence, "summary": ch_summary},
        "comparison": {
            "mean_gain_challenger_minus_incumbent": mean_gain,
            "degrade_flag": degrade_flag,
            "improve_flag": improve_flag,
        },
        "decision": {
            "needs_model_update": bool(needs_update),
            "reason": reason,
            "recommended_action": "train_and_promote_challenger" if needs_update else "keep_incumbent",
        },
    }
    out_json = out_prefix.with_suffix(".json")
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Saved:", out_json)
    print(
        json.dumps(
            {
                "decision": payload["decision"],
                "mean_incumbent": inc["mean"],
                "mean_challenger": ch["mean"],
                "mean_gain": mean_gain,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Operational suite for Wednesday/non-Wednesday tail LTR")
    sub = p.add_subparsers(dest="command", required=True)

    p1 = sub.add_parser("compare-cadence", help="Compare fold-cadence vs monthly-cadence selection")
    p1.add_argument("--output-prefix", default="db/experiments/tail_ltr_wed_cadence_compare")
    p1.add_argument("--seeds", default="42,77,123,202,303,404,505,606")
    p1.add_argument("--test-days", type=int, default=14)
    p1.add_argument("--warmup-days", type=int, default=56)
    p1.add_argument("--min-train-days-wed", type=int, default=12)
    p1.add_argument("--min-train-days-nonwed", type=int, default=42)
    p1.add_argument("--windows-wed", default="full_2025")
    p1.add_argument("--lambdas-wed", default="0.75,1.0,1.25")
    p1.add_argument("--q-grid-wed", default="0.0,0.1,0.2,0.3,0.4")
    p1.add_argument("--windows-nonwed", default="recent_60d,full_2025")
    p1.add_argument("--lambdas-nonwed", default="0.75,1.0,1.25")
    p1.add_argument("--q-grid-nonwed", default="0.0,0.1,0.2,0.3,0.4,0.5,0.6")
    p1.add_argument("--valid-start", default="")
    p1.add_argument("--valid-end", default="")
    p1.add_argument("--disable-wed-features", action="store_true")

    p2 = sub.add_parser("drift-report", help="Compute rolling drift/alert report from days CSV")
    p2.add_argument("--input-days-csv", required=True)
    p2.add_argument("--output-prefix", default="db/experiments/tail_ltr_wed_drift_report")
    p2.add_argument("--window-days", type=int, default=28)
    p2.add_argument("--baseline-days", type=int, default=56)
    p2.add_argument("--z-drop-threshold", type=float, default=-1.0)

    p3 = sub.add_parser("forecast-nextday", help="Run next-day Top2 prediction with current best branch")
    p3.add_argument("--output-prefix", default="db/experiments/tail_ltr_nextday_prediction_latest")
    p3.add_argument("--seed", type=int, default=42)
    p3.add_argument("--windows-wed", default="full_2025")
    p3.add_argument("--lambdas-wed", default="0.75,1.0,1.25")
    p3.add_argument("--q-grid-wed", default="0.0,0.1,0.2,0.3,0.4")
    p3.add_argument("--windows-nonwed", default="recent_60d,full_2025")
    p3.add_argument("--lambdas-nonwed", default="0.75,1.0,1.25")
    p3.add_argument("--q-grid-nonwed", default="0.0,0.1,0.2,0.3,0.4,0.5,0.6")
    p3.add_argument("--min-train-days-wed", type=int, default=12)
    p3.add_argument("--min-train-days-nonwed", type=int, default=42)

    p4 = sub.add_parser("monthly-update-check", help="Monthly update necessity check (run on day 1)")
    p4.add_argument("--output-prefix", default="db/experiments/tail_ltr_monthly_update_check")
    p4.add_argument("--run-date", default="", help="Override run date (YYYY-MM-DD). Default: today")
    p4.add_argument("--eval-days", type=int, default=56, help="Lookback evaluation days ending at run_date-1")
    p4.add_argument("--seeds", default="42,77,123,202,303,404,505,606")
    p4.add_argument("--test-days", type=int, default=14)
    p4.add_argument("--min-train-days-wed", type=int, default=12)
    p4.add_argument("--min-train-days-nonwed", type=int, default=42)
    p4.add_argument("--disable-wed-features", action="store_true")

    p4.add_argument("--inc-cadence", choices=["fold", "month"], default="fold")
    p4.add_argument("--inc-windows-wed", default="full_2025")
    p4.add_argument("--inc-lambdas-wed", default="0.75,1.0,1.25")
    p4.add_argument("--inc-q-grid-wed", default="0.0,0.1,0.2,0.3,0.4")
    p4.add_argument("--inc-windows-nonwed", default="recent_60d,full_2025")
    p4.add_argument("--inc-lambdas-nonwed", default="0.75,1.0,1.25")
    p4.add_argument("--inc-q-grid-nonwed", default="0.0,0.1,0.2,0.3,0.4,0.5,0.6")

    p4.add_argument("--ch-cadence", choices=["fold", "month"], default="fold")
    p4.add_argument("--ch-windows-wed", default="full_2025,recent_60d")
    p4.add_argument("--ch-lambdas-wed", default="0.5,0.75,1.0,1.25,1.5")
    p4.add_argument("--ch-q-grid-wed", default="0.0,0.1,0.2,0.3,0.4,0.5")
    p4.add_argument("--ch-windows-nonwed", default="recent_60d,full_2025,regime2_only")
    p4.add_argument("--ch-lambdas-nonwed", default="0.5,0.75,1.0,1.25,1.5")
    p4.add_argument("--ch-q-grid-nonwed", default="0.0,0.1,0.2,0.3,0.4,0.5,0.6")

    p4.add_argument("--min-mean-gain-for-update", type=float, default=5.0)
    p4.add_argument("--min-challenger-p-gt0", type=float, default=0.95)
    p4.add_argument("--degrade-ci-low", type=float, default=0.0)
    p4.add_argument("--degrade-p-gt0", type=float, default=0.90)

    return p


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "compare-cadence":
        return cmd_compare_cadence(args)
    if args.command == "drift-report":
        return cmd_drift_report(args)
    if args.command == "forecast-nextday":
        return cmd_forecast_nextday(args)
    if args.command == "monthly-update-check":
        return cmd_monthly_update_check(args)
    raise ValueError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
