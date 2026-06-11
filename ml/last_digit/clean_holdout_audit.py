from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.last_digit import tail_time_adaptive_ltr_poc_improved as improved
from ml.last_digit.audit_metrics import summarize_holdout
from ml.last_digit.post_rerank import build_confidence_band, choose_operational_pick, mark_avoid_candidates
from ml.last_digit.tail_ltr_split_rule_nextday_gpu import (
    EXPERT_ORDER,
    _gpu_model_params,
    _predict_for_date,
    _prepare_split_dataset,
    _score_day_from_rank_df,
    _should_use_2fn_weekday_patch,
    _should_use_digit_lag_bundle,
    _target_topk_k,
)
from ml.last_digit.tail_ltr_split_rule_wf import Candidate, parse_csv_floats, parse_csv_strs
from ml.last_digit.utils import configure_logging


@dataclass
class CandidateEval:
    candidate: Candidate
    n_days: int
    precision_mean: float
    hit_at_2_mean: float


FEATURE_PROFILE_CHOICES = ("all_clean", "lag_roll", "prior_calendar", "hall_digit")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Clean holdout audit (2025 selection -> 2026 holdout).")
    p.add_argument("--output-prefix", default="db/experiments/clean_holdout_audit")
    p.add_argument("--db-path", default="", help="DB path (recommended).")
    p.add_argument("--db-glob", default="*7.db", help="Used when --db-path is empty.")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--selection-start", default="2025-07-07")
    p.add_argument("--selection-end", default="2025-12-31")
    p.add_argument("--holdout-start", default="2026-01-01")
    p.add_argument("--holdout-end", default="2026-05-30")
    p.add_argument("--windows-wed", default="full_2025")
    p.add_argument("--lambdas-wed", default="0.75,1.0,1.25")
    p.add_argument("--q-grid-wed", default="0.0,0.1,0.2,0.3,0.4")
    p.add_argument("--windows-nonwed", default="recent_60d,full_2025")
    p.add_argument("--lambdas-nonwed", default="0.75,1.0,1.25")
    p.add_argument("--q-grid-nonwed", default="0.0,0.1,0.2,0.3,0.4,0.5,0.6")
    p.add_argument("--min-train-days-wed", type=int, default=12)
    p.add_argument("--min-train-days-wed-recent60", type=int, default=8)
    p.add_argument("--min-train-days-nonwed", type=int, default=42)
    p.add_argument("--a-weight", type=float, default=0.4)
    p.add_argument("--non-a-weight", type=float, default=1.3)
    p.add_argument("--gpu-backend", choices=["cuda", "gpu_hist"], default="cuda")
    p.add_argument(
        "--model",
        choices=["xgb_ranker_ndcg", "xgb_ranker_pairwise", "catboost_ranker_pairlogit", "lgbm_ranker_lambdarank"],
        default="xgb_ranker_ndcg",
    )
    p.add_argument(
        "--target-label",
        choices=("is_top_2", "is_rank_1", "is_top_3", "is_worst_1"),
        default="is_top_2",
    )
    p.add_argument("--model-extra-json", default="")
    p.add_argument("--binary-mode", choices=["off", "multiply", "filter"], default="off")
    p.add_argument("--binary-threshold", type=float, default=0.5)
    p.add_argument("--binary-c", type=float, default=0.1)
    p.add_argument("--binary-max-iter", type=int, default=1000)
    p.add_argument("--enable-digit-lag-bundle", action="store_true")
    p.add_argument("--digit-lag-bundle-experts", default="")
    p.add_argument("--enable-2fn-weekday-patch", action="store_true")
    p.add_argument(
        "--feature-profile",
        choices=FEATURE_PROFILE_CHOICES,
        default="all_clean",
        help="Feature subset profile used for ablation.",
    )
    p.add_argument("--log-level", default="INFO")
    return p


def _candidate_pool(windows_csv: str, lambdas_csv: str) -> list[Candidate]:
    return [Candidate(w, l) for w in parse_csv_strs(windows_csv) for l in parse_csv_floats(lambdas_csv)]


def _is_prior_calendar_feature(name: str) -> bool:
    return (
        name in {"weekday", "weekday_sin", "weekday_cos", "is_wed"}
        or name in {"is_event_day", "is_zorome_day", "is_strong_zorome_day", "is_day_7x", "is_day_1x", "is_wed_nonevent", "is_wed_event"}
        or name.startswith("dd_")
        or name.startswith("prior_")
        or name.startswith("days_since_")
        or name.startswith("weekday_")
        or name.startswith("wed_x_")
    )


def _is_hall_digit_feature(name: str) -> bool:
    return "hall_digit_diff" in name or name.endswith("_digit_diff")


def _is_lag_roll_feature(name: str) -> bool:
    return name.startswith("lag") or name.startswith("roll")


def _select_profile_features(all_features: list[str], profile: str) -> list[str]:
    if profile == "all_clean":
        return list(all_features)
    if profile == "lag_roll":
        return [f for f in all_features if _is_lag_roll_feature(f)]
    if profile == "prior_calendar":
        return [f for f in all_features if _is_prior_calendar_feature(f)]
    if profile == "hall_digit":
        return [f for f in all_features if _is_hall_digit_feature(f)]
    raise ValueError(f"Unknown feature profile: {profile}")


def _apply_feature_profile(ds: pd.DataFrame, profile: str) -> pd.DataFrame:
    if profile == "all_clean":
        return ds
    all_features = improved.get_numeric_features(ds)
    selected = set(_select_profile_features(all_features, profile))
    required_keep = {"machine_count"}
    drop_cols = [c for c in all_features if c not in selected and c not in required_keep]
    if not drop_cols:
        return ds
    return ds.drop(columns=drop_cols, errors="ignore")


def _date_range_dates(ds: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, is_wed: bool) -> list[pd.Timestamp]:
    dts = sorted(pd.to_datetime(ds["date"]).unique())
    out = [d for d in dts if start <= d <= end]
    if is_wed:
        out = [d for d in out if d.day_name() == "Wednesday"]
    else:
        out = [d for d in out if d.day_name() != "Wednesday"]
    return out


def _evaluate_candidate_on_dates(
    *,
    ds: pd.DataFrame,
    dates: list[pd.Timestamp],
    cand: Candidate,
    q_grid: list[float],
    seed: int,
    train_is_wed: bool,
    min_train_days: int,
    min_train_days_wed_recent60: int,
    model_params: dict[str, Any],
    model_name: str,
    binary_mode: str,
    binary_threshold: float,
    binary_c: float,
    binary_max_iter: int,
    target_label: str,
    target_topk_k: int,
    use_digit_lag_bundle: bool,
    use_2fn_weekday_patch: bool,
) -> CandidateEval | None:
    precisions: list[float] = []
    hit2s: list[float] = []
    for dt in dates:
        picked = _predict_for_date(
            df_expert=ds,
            pred_date=dt,
            candidates=[cand],
            q_grid=q_grid,
            seed=seed,
            train_is_wed=train_is_wed,
            min_train_days=min_train_days,
            min_train_days_wed_recent60=min_train_days_wed_recent60,
            model_params=model_params,
            model_name=model_name,
            binary_mode=binary_mode,
            binary_threshold=binary_threshold,
            binary_c=binary_c,
            binary_max_iter=binary_max_iter,
            target_label=target_label,
            target_topk_k=target_topk_k,
            use_digit_lag_bundle=use_digit_lag_bundle,
            use_2fn_weekday_patch=use_2fn_weekday_patch,
        )
        if picked is None:
            continue
        _, _, rank_df, _ = picked
        rec = _score_day_from_rank_df(dt=dt, expert=str(ds["group_key"].iloc[0]), rank_df=rank_df)
        precisions.append(float(rec["precision"]))
        hit2s.append(float(rec["hit_at_2"]))
    if not precisions:
        return None
    return CandidateEval(
        candidate=cand,
        n_days=len(precisions),
        precision_mean=float(np.mean(precisions)),
        hit_at_2_mean=float(np.mean(hit2s)),
    )


def _select_best_candidate(
    *,
    ds: pd.DataFrame,
    dates: list[pd.Timestamp],
    candidates: list[Candidate],
    q_grid: list[float],
    seed: int,
    train_is_wed: bool,
    min_train_days: int,
    min_train_days_wed_recent60: int,
    model_params: dict[str, Any],
    model_name: str,
    binary_mode: str,
    binary_threshold: float,
    binary_c: float,
    binary_max_iter: int,
    target_label: str,
    target_topk_k: int,
    use_digit_lag_bundle: bool,
    use_2fn_weekday_patch: bool,
) -> CandidateEval | None:
    evals: list[CandidateEval] = []
    for cand in candidates:
        ev = _evaluate_candidate_on_dates(
            ds=ds,
            dates=dates,
            cand=cand,
            q_grid=q_grid,
            seed=seed,
            train_is_wed=train_is_wed,
            min_train_days=min_train_days,
            min_train_days_wed_recent60=min_train_days_wed_recent60,
            model_params=model_params,
            model_name=model_name,
            binary_mode=binary_mode,
            binary_threshold=binary_threshold,
            binary_c=binary_c,
            binary_max_iter=binary_max_iter,
            target_label=target_label,
            target_topk_k=target_topk_k,
            use_digit_lag_bundle=use_digit_lag_bundle,
            use_2fn_weekday_patch=use_2fn_weekday_patch,
        )
        if ev is not None:
            evals.append(ev)
    if not evals:
        return None
    return sorted(evals, key=lambda x: (x.precision_mean, x.hit_at_2_mean, x.n_days), reverse=True)[0]


def _to_topk_record(
    *,
    dt: pd.Timestamp,
    expert: str,
    cand: Candidate,
    rank_df: pd.DataFrame,
    rec: dict[str, Any],
) -> dict[str, Any]:
    ranked = rank_df.sort_values("rank").reset_index(drop=True)
    ranked_with_avoid = mark_avoid_candidates(ranked, avoid_k=3)
    top1 = ranked.iloc[0] if len(ranked) >= 1 else None
    top2 = ranked.iloc[1] if len(ranked) >= 2 else None
    pred_span_top12 = float(top1["pred"] - top2["pred"]) if (top1 is not None and top2 is not None) else np.nan
    confidence_band = build_confidence_band(pred_span_top12 if np.isfinite(pred_span_top12) else 0.0)
    op_tail, op_source = choose_operational_pick(
        top1_tail=(str(top1["last_digit"]) if top1 is not None else ""),
        top2_tail=(str(top2["last_digit"]) if top2 is not None else ""),
        confidence_band=confidence_band,
    )
    if top1 is not None and op_tail == str(top1["last_digit"]):
        op_pred = float(top1["pred"])
        op_actual = float(top1["actual_raw_diff"])
    elif top2 is not None and op_tail == str(top2["last_digit"]):
        op_pred = float(top2["pred"])
        op_actual = float(top2["actual_raw_diff"])
    else:
        op_pred = np.nan
        op_actual = np.nan

    actual_rank = ranked.sort_values("actual_raw_diff", ascending=False).reset_index(drop=True)
    actual_top1_tail = str(actual_rank.iloc[0]["last_digit"]) if len(actual_rank) >= 1 else ""
    actual_top2_set = set(actual_rank.head(2)["last_digit"].astype(str).tolist())
    top1_tail = str(top1["last_digit"]) if top1 is not None else ""
    top2_tail = str(top2["last_digit"]) if top2 is not None else ""

    top1_machine_count = (
        float(pd.to_numeric(top1.get("machine_count", np.nan), errors="coerce")) if top1 is not None else np.nan
    )
    top1_avg_diff_per_machine = (
        float(top1["actual_raw_diff"]) / top1_machine_count
        if top1 is not None and np.isfinite(top1_machine_count) and top1_machine_count > 0.0
        else np.nan
    )
    top1_is_avoid = (
        int(
            ranked_with_avoid.loc[
                ranked_with_avoid["last_digit"].astype(str) == top1_tail,
                "is_avoid_candidate",
            ].iloc[0]
        )
        if top1 is not None
        else 0
    )
    top2_is_avoid = (
        int(
            ranked_with_avoid.loc[
                ranked_with_avoid["last_digit"].astype(str) == top2_tail,
                "is_avoid_candidate",
            ].iloc[0]
        )
        if top2 is not None
        else 0
    )

    return {
        "date": dt.strftime("%Y-%m-%d"),
        "month": dt.strftime("%Y-%m"),
        "weekday": dt.day_name(),
        "expert": expert,
        "window": cand.window_name,
        "lambda": float(cand.decay_lambda),
        "top1_tail": top1_tail,
        "top1_pred": (float(top1["pred"]) if top1 is not None else np.nan),
        "top1_actual_raw_diff": (float(top1["actual_raw_diff"]) if top1 is not None else np.nan),
        "top1_machine_count": top1_machine_count,
        "top1_avg_diff_per_machine": top1_avg_diff_per_machine,
        "top2_tail": top2_tail,
        "top2_pred": (float(top2["pred"]) if top2 is not None else np.nan),
        "top2_actual_raw_diff": (float(top2["actual_raw_diff"]) if top2 is not None else np.nan),
        "pred_span_top12": pred_span_top12,
        "confidence_band": confidence_band,
        "operational_pick_tail": op_tail,
        "operational_pick_source": op_source,
        "operational_pick_pred": op_pred,
        "operational_pick_actual_raw_diff": op_actual,
        "operational_pick_in_actual_top2": int(op_tail in actual_top2_set) if op_tail else 0,
        "top1_is_avoid": top1_is_avoid,
        "top2_is_avoid": top2_is_avoid,
        "actual_top1_tail": actual_top1_tail,
        "exact_top1_hit": int(top1_tail == actual_top1_tail) if top1_tail else 0,
        "precision": float(rec.get("precision", np.nan)),
        "hit_at_2": float(rec.get("hit_at_2", np.nan)),
        "hit_at_3": float(rec.get("hit_at_3", np.nan)),
    }


def main() -> int:
    args = build_parser().parse_args()
    configure_logging(args.log_level)

    model_name = str(args.model)
    if model_name.startswith("xgb_"):
        model_params = _gpu_model_params(args.gpu_backend)
    elif model_name == "catboost_ranker_pairlogit":
        model_params = {"task_type": "GPU", "devices": "0"}
    else:
        model_params = {}
    if str(args.model_extra_json).strip():
        extra = json.loads(str(args.model_extra_json))
        if not isinstance(extra, dict):
            raise ValueError("--model-extra-json must be a JSON object")
        model_params.update(extra)

    target_label = str(args.target_label)
    target_topk_k = _target_topk_k(target_label)
    digit_lag_bundle_experts = set(parse_csv_strs(args.digit_lag_bundle_experts))

    data, source_latest, _ = _prepare_split_dataset(
        db_path=str(args.db_path),
        db_glob=str(args.db_glob),
        a_weight=float(args.a_weight),
        non_a_weight=float(args.non_a_weight),
        enable_digit_lag_bundle=bool(args.enable_digit_lag_bundle),
        target_date="",
    )
    # Drop the synthetic next-day row added by _prepare_split_dataset.
    data = data[pd.to_datetime(data["date"]) <= source_latest].copy().reset_index(drop=True)

    selection_start = pd.Timestamp(str(args.selection_start))
    selection_end = pd.Timestamp(str(args.selection_end))
    holdout_start = pd.Timestamp(str(args.holdout_start))
    holdout_end = min(pd.Timestamp(str(args.holdout_end)), pd.Timestamp(source_latest))

    cands_wed = _candidate_pool(str(args.windows_wed), str(args.lambdas_wed))
    cands_non = _candidate_pool(str(args.windows_nonwed), str(args.lambdas_nonwed))
    q_wed = parse_csv_floats(args.q_grid_wed)
    q_non = parse_csv_floats(args.q_grid_nonwed)

    selected: dict[str, dict[str, Any]] = {}
    for expert in EXPERT_ORDER:
        ds = data[data["group_key"].astype(str) == expert].copy()
        ds = _apply_feature_profile(ds, str(args.feature_profile))
        if ds.empty:
            selected[expert] = {"status": "unavailable", "reason": "no_rows_for_expert"}
            continue
        use_lag = _should_use_digit_lag_bundle(
            enabled=bool(args.enable_digit_lag_bundle),
            allowed_experts=digit_lag_bundle_experts,
            expert=expert,
        )
        use_patch = _should_use_2fn_weekday_patch(enabled=bool(args.enable_2fn_weekday_patch), expert=expert)

        wed_dates = _date_range_dates(ds, selection_start, selection_end, is_wed=True)
        non_dates = _date_range_dates(ds, selection_start, selection_end, is_wed=False)

        wed_best = _select_best_candidate(
            ds=ds,
            dates=wed_dates,
            candidates=cands_wed,
            q_grid=q_wed,
            seed=int(args.seed),
            train_is_wed=True,
            min_train_days=int(args.min_train_days_wed),
            min_train_days_wed_recent60=int(args.min_train_days_wed_recent60),
            model_params=model_params,
            model_name=model_name,
            binary_mode=str(args.binary_mode),
            binary_threshold=float(args.binary_threshold),
            binary_c=float(args.binary_c),
            binary_max_iter=int(args.binary_max_iter),
            target_label=target_label,
            target_topk_k=target_topk_k,
            use_digit_lag_bundle=use_lag,
            use_2fn_weekday_patch=use_patch,
        )
        non_best = _select_best_candidate(
            ds=ds,
            dates=non_dates,
            candidates=cands_non,
            q_grid=q_non,
            seed=int(args.seed),
            train_is_wed=False,
            min_train_days=int(args.min_train_days_nonwed),
            min_train_days_wed_recent60=int(args.min_train_days_wed_recent60),
            model_params=model_params,
            model_name=model_name,
            binary_mode=str(args.binary_mode),
            binary_threshold=float(args.binary_threshold),
            binary_c=float(args.binary_c),
            binary_max_iter=int(args.binary_max_iter),
            target_label=target_label,
            target_topk_k=target_topk_k,
            use_digit_lag_bundle=use_lag,
            use_2fn_weekday_patch=use_patch,
        )
        selected[expert] = {
            "status": "ok" if (wed_best is not None or non_best is not None) else "unavailable",
            "wed": (
                {
                    "window": wed_best.candidate.window_name,
                    "lambda": float(wed_best.candidate.decay_lambda),
                    "n_days": int(wed_best.n_days),
                    "precision_mean": float(wed_best.precision_mean),
                    "hit_at_2_mean": float(wed_best.hit_at_2_mean),
                }
                if wed_best is not None
                else None
            ),
            "nonwed": (
                {
                    "window": non_best.candidate.window_name,
                    "lambda": float(non_best.candidate.decay_lambda),
                    "n_days": int(non_best.n_days),
                    "precision_mean": float(non_best.precision_mean),
                    "hit_at_2_mean": float(non_best.hit_at_2_mean),
                }
                if non_best is not None
                else None
            ),
        }

    holdout_dates = sorted(pd.to_datetime(data["date"]).unique())
    holdout_dates = [d for d in holdout_dates if holdout_start <= d <= holdout_end]
    daily_rows: list[dict[str, Any]] = []
    topk_rows: list[dict[str, Any]] = []
    for expert in EXPERT_ORDER:
        ds = data[data["group_key"].astype(str) == expert].copy()
        ds = _apply_feature_profile(ds, str(args.feature_profile))
        if ds.empty:
            continue
        use_lag = _should_use_digit_lag_bundle(
            enabled=bool(args.enable_digit_lag_bundle),
            allowed_experts=digit_lag_bundle_experts,
            expert=expert,
        )
        use_patch = _should_use_2fn_weekday_patch(enabled=bool(args.enable_2fn_weekday_patch), expert=expert)
        selected_info = selected.get(expert, {})
        for dt in holdout_dates:
            is_wed = dt.day_name() == "Wednesday"
            regime_key = "wed" if is_wed else "nonwed"
            regime = selected_info.get(regime_key) if isinstance(selected_info, dict) else None
            if regime is None:
                # fallback: use opposite regime if available
                regime = selected_info.get("nonwed" if is_wed else "wed") if isinstance(selected_info, dict) else None
            if regime is None:
                daily_rows.append(
                    {
                        "date": dt.strftime("%Y-%m-%d"),
                        "month": dt.strftime("%Y-%m"),
                        "weekday": dt.day_name(),
                        "expert": expert,
                        "precision": np.nan,
                        "recall": np.nan,
                        "f1": np.nan,
                        "hit_at_2": np.nan,
                        "hit_at_3": np.nan,
                        "pred_span": np.nan,
                        "n_items": 0,
                        "status": "unavailable",
                        "reason": "no_selected_candidate",
                    }
                )
                continue
            cand = Candidate(str(regime["window"]), float(regime["lambda"]))
            picked = _predict_for_date(
                df_expert=ds,
                pred_date=dt,
                candidates=[cand],
                q_grid=(q_wed if is_wed else q_non),
                seed=int(args.seed),
                train_is_wed=is_wed,
                min_train_days=(int(args.min_train_days_wed) if is_wed else int(args.min_train_days_nonwed)),
                min_train_days_wed_recent60=int(args.min_train_days_wed_recent60),
                model_params=model_params,
                model_name=model_name,
                binary_mode=str(args.binary_mode),
                binary_threshold=float(args.binary_threshold),
                binary_c=float(args.binary_c),
                binary_max_iter=int(args.binary_max_iter),
                target_label=target_label,
                target_topk_k=target_topk_k,
                use_digit_lag_bundle=use_lag,
                use_2fn_weekday_patch=use_patch,
            )
            if picked is None:
                daily_rows.append(
                    {
                        "date": dt.strftime("%Y-%m-%d"),
                        "month": dt.strftime("%Y-%m"),
                        "weekday": dt.day_name(),
                        "expert": expert,
                        "precision": np.nan,
                        "recall": np.nan,
                        "f1": np.nan,
                        "hit_at_2": np.nan,
                        "hit_at_3": np.nan,
                        "pred_span": np.nan,
                        "n_items": 0,
                        "status": "unavailable",
                        "reason": "predict_failed",
                    }
                )
                continue
            _, _, rank_df, _ = picked
            rec = _score_day_from_rank_df(dt=dt, expert=expert, rank_df=rank_df)
            rec["status"] = "ok"
            rec["window"] = cand.window_name
            rec["lambda"] = float(cand.decay_lambda)
            daily_rows.append(rec)
            topk_rows.append(_to_topk_record(dt=dt, expert=expert, cand=cand, rank_df=rank_df, rec=rec))

    daily_df = pd.DataFrame(daily_rows).sort_values(["date", "expert"]).reset_index(drop=True) if daily_rows else pd.DataFrame()
    topk_df = pd.DataFrame(topk_rows).sort_values(["date", "expert"]).reset_index(drop=True) if topk_rows else pd.DataFrame()
    summary = summarize_holdout(topk_df=topk_df, daily_df=daily_df)
    summary.update(
        {
            "selection_range": {"start": str(selection_start.date()), "end": str(selection_end.date())},
            "holdout_range": {"start": str(holdout_start.date()), "end": str(holdout_end.date())},
            "source_latest_date": str(source_latest.date()),
            "selected_candidates": selected,
            "model_name": model_name,
            "target_label": target_label,
            "target_topk_k": int(target_topk_k),
            "feature_profile": str(args.feature_profile),
        }
    )

    suffix = f"_{model_name}"
    output_prefix = args.output_prefix if args.output_prefix.endswith(suffix) else f"{args.output_prefix}{suffix}"
    out_prefix = Path(output_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    out_daily = out_prefix.with_name(out_prefix.name + "_holdout_daily.csv")
    out_topk = out_prefix.with_name(out_prefix.name + "_holdout_topk.csv")
    out_selected = out_prefix.with_name(out_prefix.name + "_selected_candidates.json")
    out_summary = out_prefix.with_name(out_prefix.name + "_holdout_audit_summary.json")

    if not daily_df.empty:
        daily_df.to_csv(out_daily, index=False, encoding="utf-8-sig")
    if not topk_df.empty:
        topk_df.to_csv(out_topk, index=False, encoding="utf-8-sig")
    out_selected.write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8")
    out_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[OK] source_latest_date={source_latest.date()}")
    print(f"[OK] selection={selection_start.date()}..{selection_end.date()} holdout={holdout_start.date()}..{holdout_end.date()}")
    print(f"[OK] saved: {out_selected}")
    print(f"[OK] saved: {out_summary}")
    if not daily_df.empty:
        print(f"[OK] saved: {out_daily}")
    if not topk_df.empty:
        print(f"[OK] saved: {out_topk}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
