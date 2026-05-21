from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.experiments import tail_ltr_profit_ops as ops
from ml.experiments import tail_time_adaptive_ltr_poc_improved as improved
from ml.evaluators.metrics import calculate_f1, calculate_precision, calculate_recall
from ml.experiments.tail_ltr_full_walkforward_ops import topk_day_table, train_and_predict_fold
from ml.experiments.tail_ltr_split_rule_wf import (
    Candidate,
    add_simple_features,
    aggregate_mode,
    build_base_rows,
    parse_csv_floats,
    parse_csv_strs,
    resolve_db_path,
)


EXPERT_ORDER = ["2F_N", "3F_N", "3F_A", "2F_A"]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="GPU next-day forecast for floor_atype4 split experts")
    p.add_argument("--output-prefix", default="db/experiments/tail_ltr_split4_nextday_prediction_gpu")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--windows-wed", default="full_2025")
    p.add_argument("--lambdas-wed", default="0.75,1.0,1.25")
    p.add_argument("--q-grid-wed", default="0.0,0.1,0.2,0.3,0.4")
    p.add_argument("--windows-nonwed", default="recent_60d,full_2025")
    p.add_argument("--lambdas-nonwed", default="0.75,1.0,1.25")
    p.add_argument("--q-grid-nonwed", default="0.0,0.1,0.2,0.3,0.4,0.5,0.6")
    p.add_argument("--min-train-days-wed", type=int, default=12)
    p.add_argument("--min-train-days-nonwed", type=int, default=42)
    p.add_argument("--a-weight", type=float, default=0.4)
    p.add_argument("--non-a-weight", type=float, default=1.3)
    p.add_argument(
        "--combine-min-pred-span",
        type=float,
        default=1e-12,
        help="Exclude an expert from combined ranking when (max(pred)-min(pred)) is below this threshold.",
    )
    p.add_argument(
        "--gpu-backend",
        choices=["cuda", "gpu_hist"],
        default="cuda",
        help="GPU backend mode: 'cuda' (tree_method=hist+device=cuda) or 'gpu_hist' (legacy)",
    )
    p.add_argument(
        "--reliability-history-path",
        default="db/experiments/tail_ltr_split4_reliability_history.csv",
        help="Persistent history CSV used to compute daily/monthly reliability metrics.",
    )
    p.add_argument(
        "--reliability-exclude-experts",
        default="2F_A",
        help="Comma-separated experts excluded from reliability reports.",
    )
    p.add_argument(
        "--enable-test-period-report",
        action="store_true",
        help="Compute direct daily/monthly metrics over fixed test period (regime_3_fixed_split) in one run.",
    )
    p.add_argument(
        "--test-period-split-name",
        default="regime_3_fixed_split",
        help="Split name from build_fixed_split_configs(dataset).",
    )
    return p


def _gpu_model_params(backend: str) -> dict[str, Any]:
    if backend == "gpu_hist":
        return {"tree_method": "gpu_hist"}
    return {"tree_method": "hist", "device": "cuda"}


def _prepare_split_dataset(*, a_weight: float, non_a_weight: float) -> tuple[pd.DataFrame, pd.Timestamp, pd.Timestamp]:
    raw = build_base_rows(db_path=resolve_db_path(), a_weight=float(a_weight), non_a_weight=float(non_a_weight))
    base = aggregate_mode(raw, mode="floor_atype4").sort_values(["entity_key", "date"]).reset_index(drop=True)
    source_latest = pd.to_datetime(base["date"]).max()
    next_date = source_latest + pd.Timedelta(days=1)

    tpl = base[base["date"] == source_latest].copy()
    tpl["date"] = next_date
    for col in ("total_diff_coins", "total_diff_coins_focus", "avg_diff_coins", "win_rate", "efficiency", "efficiency_focus"):
        tpl[col] = 0.0
    tpl["is_top_2"] = 0
    ext = pd.concat([base, tpl], ignore_index=True, sort=False)
    ext = add_simple_features(ext)
    return ext, source_latest, next_date


def _rank_to_points(rank: int, n: int) -> float:
    return float((n - rank + 1) / n)


def _is_expert_indeterminate(rank_df: pd.DataFrame, min_pred_span: float) -> tuple[bool, str]:
    if rank_df.empty:
        return True, "empty_ranking"
    preds = pd.to_numeric(rank_df["pred"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    span = float(np.max(preds) - np.min(preds))
    if span <= float(min_pred_span):
        return True, f"flat_prediction_span<= {min_pred_span:g}"
    return False, ""


def _build_reliability_daily(history: pd.DataFrame, exclude_experts: set[str]) -> pd.DataFrame:
    req = {"date", "expert", "last_digit", "pred", "actual_raw_diff"}
    if history.empty or not req.issubset(set(history.columns)):
        return pd.DataFrame()
    work = history.copy()
    work["date"] = pd.to_datetime(work["date"])
    work = work[~work["expert"].astype(str).isin(exclude_experts)].copy()
    if work.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for (dt, expert), g in work.groupby(["date", "expert"], sort=True):
        z = g.copy()
        z["pred_rank"] = z["pred"].rank(method="first", ascending=False).astype(int)
        z["true_rank"] = z["actual_raw_diff"].rank(method="first", ascending=False).astype(int)
        z["y_pred"] = (z["pred_rank"] <= 2).astype(int)
        z["y_true"] = (z["true_rank"] <= 2).astype(int)
        y_true = z["y_true"].to_numpy(dtype=int)
        y_pred = z["y_pred"].to_numpy(dtype=int)
        pred_top2 = set(z.loc[z["pred_rank"] <= 2, "last_digit"].astype(str).tolist())
        pred_top3 = set(z.loc[z["pred_rank"] <= 3, "last_digit"].astype(str).tolist())
        true_top2 = set(z.loc[z["true_rank"] <= 2, "last_digit"].astype(str).tolist())
        rows.append(
            {
                "date": dt.strftime("%Y-%m-%d"),
                "month": dt.strftime("%Y-%m"),
                "weekday": dt.day_name(),
                "expert": str(expert),
                "precision": float(calculate_precision(y_true, y_pred)),
                "recall": float(calculate_recall(y_true, y_pred)),
                "f1": float(calculate_f1(y_true, y_pred)),
                "hit_at_2": float(len(pred_top2 & true_top2) > 0),
                "hit_at_3": float(len(pred_top3 & true_top2) > 0),
                "n_items": int(len(z)),
            }
        )
    return pd.DataFrame(rows).sort_values(["date", "expert"]).reset_index(drop=True)


def _build_reliability_monthly(daily: pd.DataFrame) -> pd.DataFrame:
    if daily.empty:
        return pd.DataFrame()
    grouped = (
        daily.groupby(["month", "expert"], sort=True)
        .agg(
            precision=("precision", "mean"),
            recall=("recall", "mean"),
            f1=("f1", "mean"),
            hit_at_2=("hit_at_2", "mean"),
            hit_at_3=("hit_at_3", "mean"),
            n_days=("date", "nunique"),
        )
        .reset_index()
    )
    return grouped


def _build_reliability_overall(daily: pd.DataFrame) -> list[dict[str, Any]]:
    if daily.empty:
        return []
    return (
        daily.groupby("expert", sort=True)
        .agg(
            precision=("precision", "mean"),
            recall=("recall", "mean"),
            f1=("f1", "mean"),
            hit_at_2=("hit_at_2", "mean"),
            hit_at_3=("hit_at_3", "mean"),
            n_days=("date", "nunique"),
        )
        .reset_index()
        .to_dict(orient="records")
    )


def _score_day_from_rank_df(dt: pd.Timestamp, expert: str, rank_df: pd.DataFrame) -> dict[str, Any]:
    z = rank_df.copy()
    z["pred"] = pd.to_numeric(z["pred"], errors="coerce").fillna(0.0)
    z["actual_raw_diff"] = pd.to_numeric(z["actual_raw_diff"], errors="coerce").fillna(0.0)
    z["pred_rank"] = z["pred"].rank(method="first", ascending=False).astype(int)
    z["true_rank"] = z["actual_raw_diff"].rank(method="first", ascending=False).astype(int)
    z["y_pred"] = (z["pred_rank"] <= 2).astype(int)
    z["y_true"] = (z["true_rank"] <= 2).astype(int)
    y_true = z["y_true"].to_numpy(dtype=int)
    y_pred = z["y_pred"].to_numpy(dtype=int)
    pred_top2 = set(z.loc[z["pred_rank"] <= 2, "last_digit"].astype(str).tolist())
    pred_top3 = set(z.loc[z["pred_rank"] <= 3, "last_digit"].astype(str).tolist())
    true_top2 = set(z.loc[z["true_rank"] <= 2, "last_digit"].astype(str).tolist())
    span = float(z["pred"].max() - z["pred"].min()) if len(z) else 0.0
    return {
        "date": dt.strftime("%Y-%m-%d"),
        "month": dt.strftime("%Y-%m"),
        "weekday": dt.day_name(),
        "expert": str(expert),
        "precision": float(calculate_precision(y_true, y_pred)),
        "recall": float(calculate_recall(y_true, y_pred)),
        "f1": float(calculate_f1(y_true, y_pred)),
        "hit_at_2": float(len(pred_top2 & true_top2) > 0),
        "hit_at_3": float(len(pred_top3 & true_top2) > 0),
        "pred_span": span,
        "n_items": int(len(z)),
    }


def _build_test_period_daily_metrics(
    *,
    data: pd.DataFrame,
    cands_wed: list[Candidate],
    cands_non: list[Candidate],
    q_wed: list[float],
    q_non: list[float],
    min_days_wed: int,
    min_days_nonwed: int,
    seed: int,
    model_params: dict[str, Any],
    split_name: str,
    exclude_experts: set[str],
) -> tuple[pd.DataFrame, dict[str, str]]:
    split_cfgs = improved.build_fixed_split_configs(data)
    if split_name not in split_cfgs:
        raise ValueError(f"Unknown test period split_name: {split_name}. available={sorted(split_cfgs.keys())}")
    cfg = split_cfgs[split_name]
    start = pd.Timestamp(cfg["valid_start"])
    end = pd.Timestamp(cfg["valid_end"])
    valid_dates = sorted(pd.to_datetime(data["date"].unique()))
    valid_dates = [d for d in valid_dates if start <= d <= end]

    rows: list[dict[str, Any]] = []
    for expert in EXPERT_ORDER:
        if expert in exclude_experts:
            continue
        ds = data[data["group_key"].astype(str) == expert].copy()
        if ds.empty:
            continue
        for dt in valid_dates:
            is_wed = dt.day_name() == "Wednesday"
            picked = _predict_for_date(
                df_expert=ds,
                pred_date=dt,
                candidates=(cands_wed if is_wed else cands_non),
                q_grid=(q_wed if is_wed else q_non),
                seed=seed,
                train_is_wed=is_wed,
                min_train_days=(min_days_wed if is_wed else min_days_nonwed),
                model_params=model_params,
            )
            if picked is None:
                rows.append(
                    {
                        "date": dt.strftime("%Y-%m-%d"),
                        "month": dt.strftime("%Y-%m"),
                        "weekday": dt.day_name(),
                        "expert": str(expert),
                        "precision": np.nan,
                        "recall": np.nan,
                        "f1": np.nan,
                        "hit_at_2": np.nan,
                        "hit_at_3": np.nan,
                        "pred_span": np.nan,
                        "n_items": 0,
                        "status": "unavailable",
                    }
                )
                continue
            cand, _choice, rank_df, _score = picked
            rec = _score_day_from_rank_df(dt, expert, rank_df)
            rec["status"] = "ok"
            rec["window"] = cand.window_name
            rec["lambda"] = float(cand.decay_lambda)
            rows.append(rec)

    daily = pd.DataFrame(rows).sort_values(["date", "expert"]).reset_index(drop=True) if rows else pd.DataFrame()
    period_meta = {"valid_start": start.strftime("%Y-%m-%d"), "valid_end": end.strftime("%Y-%m-%d"), "split_name": split_name}
    return daily, period_meta


def _predict_for_date(
    *,
    df_expert: pd.DataFrame,
    pred_date: pd.Timestamp,
    candidates: list[Candidate],
    q_grid: list[float],
    seed: int,
    train_is_wed: bool,
    min_train_days: int,
    model_params: dict[str, Any],
) -> tuple[Candidate, dict[str, float], pd.DataFrame, float] | None:
    rows: list[tuple[float, Candidate, dict[str, float], pd.DataFrame]] = []
    all_features = improved.get_numeric_features(df_expert)
    all_features = [f for f in all_features if f != "is_top_2"]
    dts = pd.to_datetime(df_expert["date"])
    for cand in candidates:
        windows = improved.build_window_sweep_configs(valid_start=pred_date.strftime("%Y-%m-%d"))
        if cand.window_name not in windows:
            continue
        tr_start = pd.Timestamp(windows[cand.window_name]["train_start"])
        tr_end = pd.Timestamp(windows[cand.window_name]["train_end"])
        train = df_expert[(dts >= tr_start) & (dts <= tr_end)].copy()
        test = df_expert[dts == pred_date].copy()
        if train_is_wed:
            train = train[pd.to_datetime(train["date"]).dt.day_name().eq("Wednesday")]
            test = test[pd.to_datetime(test["date"]).dt.day_name().eq("Wednesday")]
        else:
            train = train[~pd.to_datetime(train["date"]).dt.day_name().eq("Wednesday")]
            test = test[~pd.to_datetime(test["date"]).dt.day_name().eq("Wednesday")]
        if train["date"].nunique() < min_train_days or test.empty:
            continue

        train = train.copy()
        test = test.copy()
        feats = ops.select_features(train, all_features, "is_top_2", "all")
        cal_df, test_df, choice = train_and_predict_fold(
            train_df=train,
            test_df=test,
            target="is_top_2",
            features=feats,
            decay_lambda=cand.decay_lambda,
            random_state=seed,
            model_params=model_params,
            temperature_candidates=improved.CalibrationConfig().temperature_candidates,
            blend_weights=improved.CalibrationConfig().blend_weights,
            q_grid=q_grid,
            k=2,
        )
        cal_day = topk_day_table(cal_df, "pred", k=2)
        keep = cal_day["margin"] >= choice["threshold"]
        cal_ex = np.where(keep.to_numpy(), cal_day["excess"].to_numpy(), 0.0)
        score = float(np.mean(cal_ex)) if len(cal_ex) else -1e18

        ranked = test_df.copy().reset_index(drop=True)
        ranked["last_digit"] = test["last_digit"].values
        ranked["actual_raw_diff"] = pd.to_numeric(test["total_diff_coins"], errors="coerce").fillna(0.0).values
        ranked = ranked.sort_values("pred", ascending=False).reset_index(drop=True)
        ranked["rank"] = np.arange(1, len(ranked) + 1)
        ranked = ranked[["rank", "last_digit", "pred", "actual_raw_diff"]]
        rows.append((score, cand, choice, ranked))

    if not rows:
        return None
    score, best_cand, best_choice, best_ranked = sorted(rows, key=lambda x: x[0], reverse=True)[0]
    return best_cand, best_choice, best_ranked, float(score)


def main() -> int:
    args = build_parser().parse_args()
    out_prefix = Path(args.output_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    model_params = _gpu_model_params(args.gpu_backend)
    reliability_exclude = set(parse_csv_strs(args.reliability_exclude_experts))

    data, source_latest, target_date = _prepare_split_dataset(a_weight=args.a_weight, non_a_weight=args.non_a_weight)
    target_weekday = target_date.day_name()
    target_is_wed = target_weekday == "Wednesday"

    cands_wed = [Candidate(w, l) for w in parse_csv_strs(args.windows_wed) for l in parse_csv_floats(args.lambdas_wed)]
    cands_non = [Candidate(w, l) for w in parse_csv_strs(args.windows_nonwed) for l in parse_csv_floats(args.lambdas_nonwed)]
    active_cands = cands_wed if target_is_wed else cands_non
    active_q = parse_csv_floats(args.q_grid_wed if target_is_wed else args.q_grid_nonwed)
    active_min_days = args.min_train_days_wed if target_is_wed else args.min_train_days_nonwed

    expert_outputs: dict[str, Any] = {}
    combined_accumulator: dict[str, float] = {}
    combined_included_experts: list[str] = []
    combined_excluded_experts: list[dict[str, str]] = []
    selected_candidates: dict[str, Candidate] = {}

    for expert in EXPERT_ORDER:
        ds = data[data["group_key"].astype(str) == expert].copy()
        if ds.empty:
            expert_outputs[expert] = {
                "status": "unavailable",
                "reason": "no_rows_for_expert",
                "combined_used": False,
                "selected_candidate": None,
                "ranking": [],
            }
            combined_excluded_experts.append({"expert": expert, "reason": "no_rows_for_expert"})
            continue
        picked = _predict_for_date(
            df_expert=ds,
            pred_date=target_date,
            candidates=active_cands,
            q_grid=active_q,
            seed=int(args.seed),
            train_is_wed=target_is_wed,
            min_train_days=int(active_min_days),
            model_params=model_params,
        )
        if picked is None:
            expert_outputs[expert] = {
                "status": "unavailable",
                "reason": "no_valid_candidate_for_target_date",
                "combined_used": False,
                "selected_candidate": None,
                "ranking": [],
            }
            combined_excluded_experts.append({"expert": expert, "reason": "no_valid_candidate_for_target_date"})
            continue
        cand, choice, rank_df, score = picked
        selected_candidates[expert] = cand
        is_indeterminate, indeterminate_reason = _is_expert_indeterminate(rank_df, args.combine_min_pred_span)
        used_for_combined = not is_indeterminate
        if used_for_combined:
            n = len(rank_df)
            for r in rank_df.itertuples(index=False):
                key = str(r.last_digit)
                points = _rank_to_points(int(r.rank), n)
                combined_accumulator[key] = combined_accumulator.get(key, 0.0) + points
            combined_included_experts.append(expert)
        else:
            combined_excluded_experts.append({"expert": expert, "reason": indeterminate_reason})
        expert_outputs[expert] = {
            "status": "ok",
            "combined_used": used_for_combined,
            "combined_exclude_reason": indeterminate_reason if is_indeterminate else "",
            "selected_candidate": {
                "window": cand.window_name,
                "lambda": cand.decay_lambda,
                "q": float(choice["q"]),
                "threshold": float(choice["threshold"]),
                "blend_weight": float(choice["blend_weight"]),
                "cal_score": float(score),
            },
            "ranking": rank_df.to_dict(orient="records"),
        }

    combined = (
        pd.DataFrame([{"last_digit": k, "combined_score": v} for k, v in combined_accumulator.items()])
        .sort_values("combined_score", ascending=False)
        .reset_index(drop=True)
    )
    if not combined.empty:
        combined["rank"] = np.arange(1, len(combined) + 1)
        combined = combined[["rank", "last_digit", "combined_score"]]

    # Latest-known-date test: predict source_latest using the same selected candidates per expert.
    latest_test_rows: list[dict[str, Any]] = []
    latest_test_full_rows: list[dict[str, Any]] = []
    latest_test_weekday = source_latest.day_name()
    latest_is_wed = latest_test_weekday == "Wednesday"
    latest_q = parse_csv_floats(args.q_grid_wed if latest_is_wed else args.q_grid_nonwed)
    latest_min_days = args.min_train_days_wed if latest_is_wed else args.min_train_days_nonwed
    for expert in EXPERT_ORDER:
        cand = selected_candidates.get(expert)
        if cand is None:
            continue
        ds = data[data["group_key"].astype(str) == expert].copy()
        if ds.empty:
            continue
        picked_latest = _predict_for_date(
            df_expert=ds,
            pred_date=source_latest,
            candidates=[cand],
            q_grid=latest_q,
            seed=int(args.seed),
            train_is_wed=latest_is_wed,
            min_train_days=int(latest_min_days),
            model_params=model_params,
        )
        if picked_latest is None and cand.window_name != "full_2025":
            # Fallback when the primary window (e.g., recent_60d on Wednesday) has insufficient train days.
            fallback_cands = [Candidate("full_2025", cand.decay_lambda), Candidate("full_2025", 1.0)]
            picked_latest = _predict_for_date(
                df_expert=ds,
                pred_date=source_latest,
                candidates=fallback_cands,
                q_grid=latest_q,
                seed=int(args.seed),
                train_is_wed=latest_is_wed,
                min_train_days=int(latest_min_days),
                model_params=model_params,
            )
        if picked_latest is None:
            continue
        _, _, latest_rank_df, _ = picked_latest
        for rec in latest_rank_df.to_dict(orient="records"):
            latest_test_full_rows.append(
                {
                    "date": str(source_latest.date()),
                    "expert": expert,
                    "last_digit": str(rec["last_digit"]),
                    "pred": float(rec["pred"]),
                    "actual_raw_diff": float(rec["actual_raw_diff"]),
                }
            )
        for rec in latest_rank_df.head(3).to_dict(orient="records"):
            latest_test_rows.append(
                {
                    "expert": expert,
                    "rank": int(rec["rank"]),
                    "last_digit": str(rec["last_digit"]),
                    "pred": float(rec["pred"]),
                    "actual_raw_diff": float(rec["actual_raw_diff"]),
                }
            )

    history_path = Path(args.reliability_history_path)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_prev = pd.DataFrame()
    if history_path.exists():
        history_prev = pd.read_csv(history_path, encoding="utf-8-sig")
    history_new = pd.DataFrame(latest_test_full_rows)
    if not history_new.empty:
        history_all = pd.concat([history_prev, history_new], ignore_index=True)
        history_all = history_all.drop_duplicates(subset=["date", "expert", "last_digit"], keep="last")
        history_all = history_all.sort_values(["date", "expert", "last_digit"]).reset_index(drop=True)
        history_all.to_csv(history_path, index=False, encoding="utf-8-sig")
    else:
        history_all = history_prev

    reliability_daily = _build_reliability_daily(history_all, reliability_exclude)
    reliability_monthly = _build_reliability_monthly(reliability_daily)
    reliability_overall = _build_reliability_overall(reliability_daily)

    test_period_daily = pd.DataFrame()
    test_period_monthly = pd.DataFrame()
    test_period_overall: list[dict[str, Any]] = []
    test_period_meta: dict[str, str] = {}
    if args.enable_test_period_report:
        test_period_daily, test_period_meta = _build_test_period_daily_metrics(
            data=data,
            cands_wed=cands_wed,
            cands_non=cands_non,
            q_wed=parse_csv_floats(args.q_grid_wed),
            q_non=parse_csv_floats(args.q_grid_nonwed),
            min_days_wed=int(args.min_train_days_wed),
            min_days_nonwed=int(args.min_train_days_nonwed),
            seed=int(args.seed),
            model_params=model_params,
            split_name=str(args.test_period_split_name),
            exclude_experts=reliability_exclude,
        )
        if not test_period_daily.empty:
            ok = test_period_daily[test_period_daily["status"] == "ok"].copy()
            test_period_monthly = _build_reliability_monthly(ok)
            test_period_overall = _build_reliability_overall(ok)

    payload = {
        "model_device": "gpu",
        "model_params": model_params,
        "objective_mode": "raw",
        "source_latest_date": str(source_latest.date()),
        "target_date": str(target_date.date()),
        "target_weekday": target_weekday,
        "model_mode": "floor_atype4",
        "combine_method": "equal_weight_rank_points_with_indeterminate_expert_exclusion",
        "combine_min_pred_span": float(args.combine_min_pred_span),
        "combine_experts_included": combined_included_experts,
        "combine_experts_excluded": combined_excluded_experts,
        "expert_predictions": expert_outputs,
        "combined_priority_ranking": combined.to_dict(orient="records") if not combined.empty else [],
        "latest_test_date": str(source_latest.date()),
        "latest_test_weekday": latest_test_weekday,
        "latest_test_top3_by_expert": latest_test_rows,
        "reliability_history_path": str(history_path),
        "reliability_excluded_experts": sorted(reliability_exclude),
        "reliability_overall_by_expert": reliability_overall,
        "test_period_report_enabled": bool(args.enable_test_period_report),
        "test_period_config": test_period_meta,
        "test_period_overall_by_expert": test_period_overall,
        "notes": "latest_test_top3_by_expert uses known latest date as one-step holdout style check with selected candidates.",
    }

    out_json = out_prefix.with_suffix(".json")
    out_csv = out_prefix.with_suffix(".csv")
    out_test_csv = out_prefix.with_name(out_prefix.name + "_latest_test_top3.csv")
    out_test_full_csv = out_prefix.with_name(out_prefix.name + "_latest_test_full.csv")
    out_rel_daily_csv = out_prefix.with_name(out_prefix.name + "_reliability_daily.csv")
    out_rel_monthly_csv = out_prefix.with_name(out_prefix.name + "_reliability_monthly.csv")
    out_period_daily_csv = out_prefix.with_name(out_prefix.name + "_testperiod_daily.csv")
    out_period_monthly_csv = out_prefix.with_name(out_prefix.name + "_testperiod_monthly.csv")
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if not combined.empty:
        combined.to_csv(out_csv, index=False, encoding="utf-8-sig")
    if latest_test_rows:
        pd.DataFrame(latest_test_rows).to_csv(out_test_csv, index=False, encoding="utf-8-sig")
    if latest_test_full_rows:
        pd.DataFrame(latest_test_full_rows).to_csv(out_test_full_csv, index=False, encoding="utf-8-sig")
    if not reliability_daily.empty:
        reliability_daily.to_csv(out_rel_daily_csv, index=False, encoding="utf-8-sig")
    if not reliability_monthly.empty:
        reliability_monthly.to_csv(out_rel_monthly_csv, index=False, encoding="utf-8-sig")
    if not test_period_daily.empty:
        test_period_daily.to_csv(out_period_daily_csv, index=False, encoding="utf-8-sig")
    if not test_period_monthly.empty:
        test_period_monthly.to_csv(out_period_monthly_csv, index=False, encoding="utf-8-sig")
    print("Saved:", out_json)
    if not combined.empty:
        print("Saved:", out_csv)
    if latest_test_rows:
        print("Saved:", out_test_csv)
    if latest_test_full_rows:
        print("Saved:", out_test_full_csv)
    if not reliability_daily.empty:
        print("Saved:", out_rel_daily_csv)
    if not reliability_monthly.empty:
        print("Saved:", out_rel_monthly_csv)
    if not test_period_daily.empty:
        print("Saved:", out_period_daily_csv)
    if not test_period_monthly.empty:
        print("Saved:", out_period_monthly_csv)
    if not combined.empty:
        print(combined.head(5).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
