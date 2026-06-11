from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.last_digit.mitoya_segmentation import EXPERTS_MITOYA, aggregate_mode_mitoya, build_base_rows_mitoya
from ml.last_digit.tail_ltr_mitoya_wf import add_mitoya_bucket_features, specific_dd_from_date


def _load_base_module():
    module_name = "ml.last_digit._tail_ltr_mitoya_nextday_base"
    module = sys.modules.get(module_name)
    if module is not None:
        return module

    module_path = Path(__file__).with_name("tail_ltr_split_rule_nextday_gpu.py")
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load base module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_BASE = _load_base_module()
_BASE.EXPERT_ORDER = list(EXPERTS_MITOYA)

EXPERT_ORDER = list(EXPERTS_MITOYA)
Candidate = _BASE.Candidate
DECISION_BY_BUCKET = {
    "x_day": "adopt",
    "others": "exclude",
}


def _set_default(parser: argparse.ArgumentParser, option_string: str, value: Any) -> None:
    for action in parser._actions:
        if option_string in action.option_strings:
            action.default = value
            return
    raise ValueError(f"Parser action not found: {option_string}")


def build_parser() -> argparse.ArgumentParser:
    parser = _BASE.build_parser()
    parser.description = "GPU next-day forecast for Mitoya atype3 experts"
    _set_default(parser, "--output-prefix", "db/experiments/mitoya_nextday")
    _set_default(parser, "--db-glob", "みとや大森町店.db")
    _set_default(parser, "--a-weight", 1.0)
    _set_default(parser, "--non-a-weight", 1.0)
    _set_default(parser, "--reliability-history-path", "db/experiments/mitoya_nextday_reliability_history.csv")
    parser.add_argument(
        "--sunday-q-override",
        type=float,
        default=0.65,
        help="Override q-grid with a single threshold when the target bucket is Sunday.",
    )
    parser.add_argument(
        "--compare-mode",
        action="store_true",
        help="Run the same next-day forecast for multiple seeds and emit a seed-agreement report.",
    )
    parser.add_argument(
        "--compare-seeds",
        type=str,
        default="42,77,303",
        help="Comma-separated seed list used when --compare-mode is enabled.",
    )
    return parser


def _prepare_split_dataset(
    *,
    db_path: str,
    db_glob: str,
    a_weight: float,
    non_a_weight: float,
    enable_digit_lag_bundle: bool = False,
    target_date: str = "",
) -> tuple[pd.DataFrame, pd.Timestamp, pd.Timestamp]:
    resolved_db = _BASE.resolve_db_path(str(db_path), pattern=str(db_glob))
    raw = build_base_rows_mitoya(db_path=resolved_db, a_weight=float(a_weight), non_a_weight=float(non_a_weight))
    base = aggregate_mode_mitoya(raw, mode="atype3").sort_values(["group_key", "date", "last_digit"]).reset_index(drop=True)
    base_dates = pd.to_datetime(base["date"])
    base["date"] = base_dates
    target_ts = pd.Timestamp(str(target_date)) if str(target_date).strip() else None
    if target_ts is not None:
        hist_mask = base_dates < target_ts
        if not hist_mask.any():
            raise ValueError(f"No history exists before target_date={target_ts.date()}")
        base = base.loc[hist_mask].copy().reset_index(drop=True)
        base_dates = pd.to_datetime(base["date"])
        next_date = target_ts
    else:
        next_date = base_dates.max() + pd.Timedelta(days=1)
    source_latest = base_dates.max()

    tpl = base.loc[base_dates == source_latest].copy()
    tpl["date"] = next_date
    for col in ("total_diff_coins", "total_diff_coins_focus", "avg_diff_coins", "win_rate", "efficiency", "efficiency_focus"):
        if col in tpl.columns:
            tpl[col] = 0.0
    for target_col in ("is_rank_1", "is_top_2", "is_top_3", "is_worst_1", "is_worst_3"):
        if target_col in tpl.columns:
            tpl[target_col] = 0
    ext = pd.concat([base, tpl], ignore_index=True, sort=False)
    ext = add_mitoya_bucket_features(ext, include_specific_dd=False)
    return ext, source_latest, next_date


def resolve_target_bucket_context(args: argparse.Namespace, target_date: pd.Timestamp) -> dict[str, Any]:
    target_ts = pd.Timestamp(target_date)
    target_weekday = target_ts.day_name()
    target_is_wed = target_weekday == "Wednesday"
    specific_dd = specific_dd_from_date(target_ts)
    day_bucket = "x_day" if specific_dd is not None else "others"
    active_q = _BASE.parse_csv_floats(args.q_grid_wed if target_is_wed else args.q_grid_nonwed)
    active_cands = [
        Candidate(w, l)
        for w in _BASE.parse_csv_strs(args.windows_wed if target_is_wed else args.windows_nonwed)
        for l in _BASE.parse_csv_floats(args.lambdas_wed if target_is_wed else args.lambdas_nonwed)
    ]
    active_min_days = int(args.min_train_days_wed if target_is_wed else args.min_train_days_nonwed)
    return {
        "target_weekday": target_weekday,
        "target_is_wed": target_is_wed,
        "specific_dd": specific_dd,
        "day_bucket": day_bucket,
        "decision": DECISION_BY_BUCKET[day_bucket],
        "active_q": active_q,
        "active_cands": active_cands,
        "active_min_days": active_min_days,
        "sunday_q_override_applied": False,
    }

def annotate_ranking_rows(
    rows: list[dict[str, Any]],
    *,
    day_bucket: str,
    decision: str,
    specific_dd: int | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        rec = dict(row)
        rec["day_bucket"] = day_bucket
        rec["decision"] = decision
        rec["specific_dd"] = specific_dd
        out.append(rec)
    return out


def _annotate_expert_outputs(
    expert_outputs: dict[str, Any],
    *,
    day_bucket: str,
    decision: str,
    specific_dd: int | None,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for expert, payload in expert_outputs.items():
        rec = dict(payload)
        ranking = rec.get("ranking")
        if isinstance(ranking, list):
            rec["ranking"] = annotate_ranking_rows(
                ranking,
                day_bucket=day_bucket,
                decision=decision,
                specific_dd=specific_dd,
            )
        rec["day_bucket"] = day_bucket
        rec["decision"] = decision
        rec["specific_dd"] = specific_dd
        out[expert] = rec
    return out


def _annotate_dataframe(
    df: pd.DataFrame,
    *,
    day_bucket: str,
    decision: str,
    specific_dd: int | None,
) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.copy()
    out["day_bucket"] = day_bucket
    out["decision"] = decision
    out["specific_dd"] = specific_dd
    return out


def _extract_top_digits(ranking: pd.DataFrame, *, top_n: int = 3) -> list[str]:
    if ranking.empty or "last_digit" not in ranking.columns:
        return []
    ordered = ranking.sort_values("rank") if "rank" in ranking.columns else ranking
    digits: list[str] = []
    for value in ordered["last_digit"].head(top_n).tolist():
        if pd.isna(value):
            continue
        digits.append(str(value))
    return digits


def _run_target_seed_forecast(
    *,
    seed: int,
    args: argparse.Namespace,
    data: pd.DataFrame,
    source_latest: pd.Timestamp,
    target_date: pd.Timestamp,
    target_ctx: dict[str, Any],
    model_params: dict[str, Any],
    model_name: str,
    target_label: str,
    target_topk_k: int,
    digit_lag_bundle_experts: set[str],
) -> dict[str, Any]:
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
        picked = _BASE._predict_for_date(
            df_expert=ds,
            pred_date=target_date,
            candidates=target_ctx["active_cands"],
            q_grid=target_ctx["active_q"],
            seed=int(seed),
            train_is_wed=bool(target_ctx["target_is_wed"]),
            min_train_days=int(target_ctx["active_min_days"]),
            min_train_days_wed_recent60=int(args.min_train_days_wed_recent60),
            model_params=model_params,
            model_name=model_name,
            binary_mode=str(args.binary_mode),
            binary_threshold=float(args.binary_threshold),
            binary_c=float(args.binary_c),
            binary_max_iter=int(args.binary_max_iter),
            target_label=target_label,
            target_topk_k=target_topk_k,
            use_digit_lag_bundle=_BASE._should_use_digit_lag_bundle(
                enabled=bool(args.enable_digit_lag_bundle),
                allowed_experts=digit_lag_bundle_experts,
                expert=expert,
            ),
            use_2fn_weekday_patch=False,
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
        is_indeterminate, indeterminate_reason = _BASE._is_expert_indeterminate(rank_df, args.combine_min_pred_span)
        used_for_combined = not is_indeterminate
        if used_for_combined:
            n = len(rank_df)
            for row in rank_df.itertuples(index=False):
                key = str(row.last_digit)
                points = _BASE._rank_to_points(int(row.rank), n)
                combined_accumulator[key] = combined_accumulator.get(key, 0.0) + points
            combined_included_experts.append(expert)
        else:
            combined_excluded_experts.append({"expert": expert, "reason": indeterminate_reason})
        sorted_rank_df = rank_df.sort_values("rank")
        top1_pred = float(sorted_rank_df.iloc[0]["pred"]) if len(sorted_rank_df) >= 1 else np.nan
        top2_pred = float(sorted_rank_df.iloc[1]["pred"]) if len(sorted_rank_df) >= 2 else np.nan
        pred_span = float(top1_pred - top2_pred) if (np.isfinite(top1_pred) and np.isfinite(top2_pred)) else np.nan
        confidence_band = _BASE.build_confidence_band(float(pred_span) if np.isfinite(pred_span) else 0.0)
        expert_outputs[expert] = {
            "status": "ok",
            "combined_used": used_for_combined,
            "combined_exclude_reason": indeterminate_reason if is_indeterminate else "",
            "pred_span_top12": float(pred_span) if np.isfinite(pred_span) else None,
            "confidence_band": confidence_band,
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

    if combined_accumulator:
        combined = (
            pd.DataFrame([{"last_digit": key, "combined_score": value} for key, value in combined_accumulator.items()])
            .sort_values("combined_score", ascending=False)
            .reset_index(drop=True)
        )
        combined["rank"] = np.arange(1, len(combined) + 1)
        combined = combined[["rank", "last_digit", "combined_score"]]
    else:
        combined = pd.DataFrame(columns=["rank", "last_digit", "combined_score"])
    combined = _annotate_dataframe(
        combined,
        day_bucket=target_ctx["day_bucket"],
        decision=target_ctx["decision"],
        specific_dd=target_ctx["specific_dd"],
    )

    combined_top_digits = _extract_top_digits(combined, top_n=3)
    expert_top1_digits: dict[str, str | None] = {}
    for expert in EXPERT_ORDER:
        ranking = expert_outputs.get(expert, {}).get("ranking", [])
        top_digit = str(ranking[0]["last_digit"]) if ranking else None
        expert_top1_digits[expert] = top_digit

    return {
        "seed": int(seed),
        "source_latest_date": str(source_latest.date()),
        "target_date": str(target_date.date()),
        "target_weekday": target_ctx["target_weekday"],
        "target_day_bucket": target_ctx["day_bucket"],
        "decision": target_ctx["decision"],
        "specific_dd": target_ctx["specific_dd"],
        "sunday_q_override_applied": bool(target_ctx["sunday_q_override_applied"]),
        "combined": combined,
        "combined_top_digits": combined_top_digits,
        "combined_top1_digit": combined_top_digits[0] if len(combined_top_digits) >= 1 else None,
        "combined_top2_digit": combined_top_digits[1] if len(combined_top_digits) >= 2 else None,
        "combined_top3_digits": combined_top_digits,
        "expert_outputs": expert_outputs,
        "expert_top1_digits": expert_top1_digits,
        "combined_included_experts": combined_included_experts,
        "combined_excluded_experts": combined_excluded_experts,
        "selected_candidates": selected_candidates,
    }


def summarize_seed_agreement(rows: list[dict[str, Any]], *, target_ctx: dict[str, Any]) -> dict[str, Any]:
    valid_digits = [str(row["combined_top1_digit"]) for row in rows if row.get("combined_top1_digit") not in (None, "")]
    counts = Counter(valid_digits)
    if counts:
        consensus_top1_digit, consensus_top1_count = counts.most_common(1)[0]
    else:
        consensus_top1_digit, consensus_top1_count = None, 0
    valid_seed_count = len(valid_digits)
    consensus_top1_ratio = float(consensus_top1_count / valid_seed_count) if valid_seed_count else 0.0
    all_same_top1 = bool(valid_seed_count > 0 and consensus_top1_count == valid_seed_count)
    is_high_confidence = bool(all_same_top1 and valid_seed_count == len(rows) and target_ctx.get("day_bucket") == "x_day")
    return {
        "seed_count": len(rows),
        "valid_seed_count": valid_seed_count,
        "consensus_top1_digit": consensus_top1_digit,
        "consensus_top1_count": int(consensus_top1_count),
        "consensus_top1_ratio": float(consensus_top1_ratio),
        "all_same_top1": all_same_top1,
        "is_high_confidence": is_high_confidence,
        "seed_top1_digits": valid_digits,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _BASE.configure_logging(args.log_level)
    target_label = str(args.target_label)
    target_topk_k = _BASE._target_topk_k(target_label)
    suffix = f"_{args.model}"
    output_prefix = args.output_prefix if args.output_prefix.endswith(suffix) else f"{args.output_prefix}{suffix}"
    out_prefix = Path(output_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    model_name = str(args.model)
    if model_name.startswith("xgb_"):
        model_params = _BASE._gpu_model_params(args.gpu_backend)
    elif model_name == "catboost_ranker_pairlogit":
        model_params = {"task_type": "GPU", "devices": "0"}
    else:
        model_params = {}
    if str(args.model_extra_json).strip():
        extra = json.loads(str(args.model_extra_json))
        if not isinstance(extra, dict):
            raise ValueError("--model-extra-json must be a JSON object")
        model_params.update(extra)
    reliability_exclude = set(_BASE.parse_csv_strs(args.reliability_exclude_experts))
    digit_lag_bundle_experts = set(_BASE.parse_csv_strs(args.digit_lag_bundle_experts))

    data, source_latest, target_date = _prepare_split_dataset(
        db_path=str(args.db_path),
        db_glob=str(args.db_glob),
        a_weight=args.a_weight,
        non_a_weight=args.non_a_weight,
        enable_digit_lag_bundle=bool(args.enable_digit_lag_bundle),
        target_date=str(args.target_date),
    )
    target_ctx = resolve_target_bucket_context(args, target_date)
    if bool(args.compare_mode):
        compare_seed_values = [int(value) for value in _BASE.parse_csv_strs(args.compare_seeds)]
        compare_rows: list[dict[str, Any]] = []
        for compare_seed in compare_seed_values:
            forecast = _run_target_seed_forecast(
                seed=compare_seed,
                args=args,
                data=data,
                source_latest=source_latest,
                target_date=target_date,
                target_ctx=target_ctx,
                model_params=model_params,
                model_name=model_name,
                target_label=target_label,
                target_topk_k=target_topk_k,
                digit_lag_bundle_experts=digit_lag_bundle_experts,
            )
            compare_rows.append(
                {
                    "seed": forecast["seed"],
                    "source_latest_date": forecast["source_latest_date"],
                    "target_date": forecast["target_date"],
                    "target_weekday": forecast["target_weekday"],
                    "target_day_bucket": forecast["target_day_bucket"],
                    "decision": forecast["decision"],
                    "specific_dd": forecast["specific_dd"],
                    "sunday_q_override_applied": forecast["sunday_q_override_applied"],
                    "combined_top1_digit": forecast["combined_top1_digit"],
                    "combined_top2_digit": forecast["combined_top2_digit"],
                    "combined_top3_digits": ",".join(forecast["combined_top3_digits"]),
                    "expert_top1_N": forecast["expert_top1_digits"].get("N"),
                    "expert_top1_A": forecast["expert_top1_digits"].get("A"),
                    "expert_top1_BT": forecast["expert_top1_digits"].get("BT"),
                }
            )
        compare_summary = summarize_seed_agreement(compare_rows, target_ctx=target_ctx)
        compare_df = pd.DataFrame(compare_rows)
        for key, value in compare_summary.items():
            compare_df[key] = value
        compare_payload = {
            "compare_mode": True,
            "compare_seeds": compare_seed_values,
            "model_name": model_name,
            "model_params": model_params,
            "source_latest_date": str(source_latest.date()),
            "target_date": str(target_date.date()),
            "target_weekday": target_ctx["target_weekday"],
            "target_day_bucket": target_ctx["day_bucket"],
            "operational_decision": target_ctx["decision"],
            "compare_summary": compare_summary,
            "compare_rows": compare_rows,
            "notes": "Mitoya next-day seed compare mode uses the same target date across the requested seed list.",
        }
        compare_prefix = out_prefix.with_name(out_prefix.name + "_seed_compare")
        compare_df.to_csv(compare_prefix.with_suffix(".csv"), index=False, encoding="utf-8-sig")
        with compare_prefix.with_suffix(".json").open("w", encoding="utf-8") as f:
            json.dump(compare_payload, f, ensure_ascii=False, indent=2)
        return 0

    single_forecast = _run_target_seed_forecast(
        seed=int(args.seed),
        args=args,
        data=data,
        source_latest=source_latest,
        target_date=target_date,
        target_ctx=target_ctx,
        model_params=model_params,
        model_name=model_name,
        target_label=target_label,
        target_topk_k=target_topk_k,
        digit_lag_bundle_experts=digit_lag_bundle_experts,
    )
    expert_outputs = single_forecast["expert_outputs"]
    combined = single_forecast["combined"]
    combined_included_experts = single_forecast["combined_included_experts"]
    combined_excluded_experts = single_forecast["combined_excluded_experts"]
    selected_candidates = single_forecast["selected_candidates"]

    latest_ctx = resolve_target_bucket_context(args, source_latest)
    latest_test_rows: list[dict[str, Any]] = []
    latest_test_bottom3_rows: list[dict[str, Any]] = []
    latest_test_full_rows: list[dict[str, Any]] = []
    for expert in EXPERT_ORDER:
        cand = selected_candidates.get(expert)
        if cand is None:
            continue
        ds = data[data["group_key"].astype(str) == expert].copy()
        if ds.empty:
            continue
        picked_latest = _BASE._predict_for_date(
            df_expert=ds,
            pred_date=source_latest,
            candidates=[cand],
            q_grid=latest_ctx["active_q"],
            seed=int(args.seed),
            train_is_wed=bool(latest_ctx["target_is_wed"]),
            min_train_days=int(latest_ctx["active_min_days"]),
            min_train_days_wed_recent60=int(args.min_train_days_wed_recent60),
            model_params=model_params,
            model_name=model_name,
            binary_mode=str(args.binary_mode),
            binary_threshold=float(args.binary_threshold),
            binary_c=float(args.binary_c),
            binary_max_iter=int(args.binary_max_iter),
            target_label=target_label,
            target_topk_k=target_topk_k,
            use_digit_lag_bundle=_BASE._should_use_digit_lag_bundle(
                enabled=bool(args.enable_digit_lag_bundle),
                allowed_experts=digit_lag_bundle_experts,
                expert=expert,
            ),
            use_2fn_weekday_patch=False,
        )
        if picked_latest is None and cand.window_name != "full_2025":
            fallback_cands = [Candidate("full_2025", cand.decay_lambda), Candidate("full_2025", 1.0)]
            picked_latest = _BASE._predict_for_date(
                df_expert=ds,
                pred_date=source_latest,
                candidates=fallback_cands,
                q_grid=latest_ctx["active_q"],
                seed=int(args.seed),
                train_is_wed=bool(latest_ctx["target_is_wed"]),
                min_train_days=int(latest_ctx["active_min_days"]),
                min_train_days_wed_recent60=int(args.min_train_days_wed_recent60),
                model_params=model_params,
                model_name=model_name,
                binary_mode=str(args.binary_mode),
                binary_threshold=float(args.binary_threshold),
                binary_c=float(args.binary_c),
                binary_max_iter=int(args.binary_max_iter),
                target_label=target_label,
                target_topk_k=target_topk_k,
                use_digit_lag_bundle=_BASE._should_use_digit_lag_bundle(
                    enabled=bool(args.enable_digit_lag_bundle),
                    allowed_experts=digit_lag_bundle_experts,
                    expert=expert,
                ),
                use_2fn_weekday_patch=False,
            )
        if picked_latest is None:
            continue
        _, _, latest_rank_df, _ = picked_latest
        for rec in latest_rank_df.to_dict(orient="records"):
            row = {
                "date": str(source_latest.date()),
                "expert": expert,
                "last_digit": str(rec["last_digit"]),
                "pred": float(rec["pred"]),
                "actual_raw_diff": float(rec["actual_raw_diff"]),
                "prob_positive": float(rec.get("prob_positive", np.nan)),
                "final_score": float(rec.get("final_score", np.nan)),
                "ltr_pred": float(rec.get("ltr_pred", np.nan)),
            }
            row.update(
                day_bucket=latest_ctx["day_bucket"],
                decision=latest_ctx["decision"],
                specific_dd=latest_ctx["specific_dd"],
            )
            latest_test_full_rows.append(row)
        for rec in latest_rank_df.head(3).to_dict(orient="records"):
            row = {
                "expert": expert,
                "rank": int(rec["rank"]),
                "last_digit": str(rec["last_digit"]),
                "pred": float(rec["pred"]),
                "actual_raw_diff": float(rec["actual_raw_diff"]),
                "prob_positive": float(rec.get("prob_positive", np.nan)),
                "final_score": float(rec.get("final_score", np.nan)),
                "ltr_pred": float(rec.get("ltr_pred", np.nan)),
            }
            row.update(
                day_bucket=latest_ctx["day_bucket"],
                decision=latest_ctx["decision"],
                specific_dd=latest_ctx["specific_dd"],
            )
            latest_test_rows.append(row)
        for rec in latest_rank_df.sort_values("rank", ascending=True).tail(3).to_dict(orient="records"):
            row = {
                "expert": expert,
                "rank": int(rec["rank"]),
                "last_digit": str(rec["last_digit"]),
                "pred": float(rec["pred"]),
                "actual_raw_diff": float(rec["actual_raw_diff"]),
                "prob_positive": float(rec.get("prob_positive", np.nan)),
                "final_score": float(rec.get("final_score", np.nan)),
                "ltr_pred": float(rec.get("ltr_pred", np.nan)),
            }
            row.update(
                day_bucket=latest_ctx["day_bucket"],
                decision=latest_ctx["decision"],
                specific_dd=latest_ctx["specific_dd"],
            )
            latest_test_bottom3_rows.append(row)

    history_path = Path(args.reliability_history_path)
    history_all = _BASE._update_reliability_history(
        history_path=history_path,
        latest_test_full_rows=latest_test_full_rows,
    )
    reliability_daily = _BASE._build_reliability_daily(history_all, reliability_exclude)
    reliability_monthly = _BASE._build_reliability_monthly(reliability_daily)
    reliability_overall = _BASE._build_reliability_overall(reliability_daily)

    cands_wed = [Candidate(w, l) for w in _BASE.parse_csv_strs(args.windows_wed) for l in _BASE.parse_csv_floats(args.lambdas_wed)]
    cands_non = [Candidate(w, l) for w in _BASE.parse_csv_strs(args.windows_nonwed) for l in _BASE.parse_csv_floats(args.lambdas_nonwed)]
    test_period_daily = pd.DataFrame()
    test_period_topk = pd.DataFrame()
    test_period_monthly = pd.DataFrame()
    test_period_overall: list[dict[str, Any]] = []
    test_period_meta: dict[str, str] = {}
    if args.enable_test_period_report:
        test_period_daily, test_period_topk, test_period_meta = _BASE._build_test_period_daily_metrics(
            data=data,
            cands_wed=cands_wed,
            cands_non=cands_non,
            q_wed=_BASE.parse_csv_floats(args.q_grid_wed),
            q_non=_BASE.parse_csv_floats(args.q_grid_nonwed),
            min_days_wed=int(args.min_train_days_wed),
            min_days_wed_recent60=int(args.min_train_days_wed_recent60),
            min_days_nonwed=int(args.min_train_days_nonwed),
            seed=int(args.seed),
            model_params=model_params,
            model_name=model_name,
            binary_mode=str(args.binary_mode),
            binary_threshold=float(args.binary_threshold),
            binary_c=float(args.binary_c),
            binary_max_iter=int(args.binary_max_iter),
            target_label=target_label,
            target_topk_k=target_topk_k,
            split_name=str(args.test_period_split_name),
            exclude_experts=reliability_exclude,
            enable_digit_lag_bundle=bool(args.enable_digit_lag_bundle),
            digit_lag_bundle_experts=digit_lag_bundle_experts,
            enable_2fn_weekday_patch=False,
        )
        if not test_period_daily.empty:
            ok = test_period_daily[test_period_daily["status"] == "ok"].copy()
            test_period_monthly = _BASE._build_reliability_monthly(ok)
            test_period_overall = _BASE._build_reliability_overall(ok)

    expert_outputs = _annotate_expert_outputs(
        expert_outputs,
        day_bucket=target_ctx["day_bucket"],
        decision=target_ctx["decision"],
        specific_dd=target_ctx["specific_dd"],
    )
    payload = {
        "model_device": "gpu",
        "model_name": model_name,
        "target_label": target_label,
        "target_topk_k": int(target_topk_k),
        "model_params": model_params,
        "binary_mode": str(args.binary_mode),
        "binary_threshold": float(args.binary_threshold),
        "binary_c": float(args.binary_c),
        "binary_max_iter": int(args.binary_max_iter),
        "enable_digit_lag_bundle": bool(args.enable_digit_lag_bundle),
        "digit_lag_bundle_experts": sorted(digit_lag_bundle_experts),
        "enable_2fn_weekday_patch": False,
        "objective_mode": "raw",
        "source_latest_date": str(source_latest.date()),
        "target_date": str(target_date.date()),
        "target_weekday": target_ctx["target_weekday"],
        "target_day_bucket": target_ctx["day_bucket"],
        "operational_decision": target_ctx["decision"],
        "sunday_q_override": float(args.sunday_q_override),
        "sunday_q_override_applied": bool(target_ctx["sunday_q_override_applied"]),
        "model_mode": "atype3",
        "combine_method": "equal_weight_rank_points_with_indeterminate_expert_exclusion",
        "combine_min_pred_span": float(args.combine_min_pred_span),
        "combine_experts_included": combined_included_experts,
        "combine_experts_excluded": combined_excluded_experts,
        "expert_predictions": expert_outputs,
        "combined_priority_ranking": combined.to_dict(orient="records") if not combined.empty else [],
        "latest_test_date": str(source_latest.date()),
        "latest_test_weekday": latest_ctx["target_weekday"],
        "latest_test_day_bucket": latest_ctx["day_bucket"],
        "latest_test_decision": latest_ctx["decision"],
        "latest_test_top3_by_expert": latest_test_rows,
        "latest_test_bottom3_by_expert": latest_test_bottom3_rows,
        "reliability_history_path": str(history_path),
        "reliability_excluded_experts": sorted(reliability_exclude),
        "reliability_overall_by_expert": reliability_overall,
        "test_period_report_enabled": bool(args.enable_test_period_report),
        "test_period_config": test_period_meta,
        "test_period_overall_by_expert": test_period_overall,
        "ceiling_effect_report_enabled": bool(args.enable_ceiling_effect_report),
        "notes": "Mitoya next-day wrapper uses atype3 aggregation and operational day-bucket annotations.",
    }

    if args.enable_ceiling_effect_report:
        if target_label.startswith("is_worst_"):
            _BASE.logger.warning("Skip ceiling-effect report for worst target: %s", target_label)
            payload["ceiling_effect_report_status"] = "skipped_worst_target"
        elif test_period_topk.empty:
            _BASE.logger.warning("Skip ceiling-effect report: test period topk is empty.")
            payload["ceiling_effect_report_status"] = "skipped_empty_testperiod_topk"
        else:
            out_period_topk_csv = out_prefix.with_name(out_prefix.name + "_testperiod_topk.csv")
            test_period_topk.to_csv(out_period_topk_csv, index=False, encoding="utf-8-sig")
            ceiling_out_dir = (
                Path(args.ceiling_output_dir)
                if str(args.ceiling_output_dir).strip()
                else out_prefix.with_name(out_prefix.name + "_ceiling_effect")
            )
            baseline_path = str(args.ceiling_baseline_topk).strip() or None
            stats_cfg = _BASE.StatsConfig(
                n_boot=int(args.ceiling_n_boot),
                seed=int(args.ceiling_seed),
                min_paired_for_wilcoxon=int(args.ceiling_min_paired),
                min_unpaired_for_mwu=int(args.ceiling_min_unpaired),
            )
            _BASE.logger.info(
                "Running ceiling-effect KPI report: input=%s baseline=%s output_dir=%s",
                out_period_topk_csv,
                baseline_path or "(none)",
                ceiling_out_dir,
            )
            ceiling_outputs = _BASE.analyze_ceiling_effect(
                input_topk_csv=out_period_topk_csv,
                output_dir=ceiling_out_dir,
                baseline_topk_csv=baseline_path,
                db_path=_BASE.resolve_db_path(str(args.db_path), pattern=str(args.db_glob)),
                stats_config=stats_cfg,
                catastrophic_threshold=float(args.ceiling_catastrophic_threshold),
            )
            payload["ceiling_effect_report_status"] = "ok"
            payload["ceiling_effect_outputs"] = {key: str(value) for key, value in ceiling_outputs.items()}

    try:
        resolved_db = _BASE.resolve_db_path(str(args.db_path), pattern=str(args.db_glob))
        zorome_ref_date, zorome_by_digit = _BASE.fetch_latest_zorome_by_digit(resolved_db)
        zorome_ref_date_expert, zorome_by_expert_digit = _BASE.fetch_latest_zorome_by_expert_digit(resolved_db)
        if zorome_ref_date_expert and zorome_ref_date_expert != zorome_ref_date:
            _BASE.logger.warning(
                "zorome ref date mismatch: by_digit=%s by_expert=%s",
                zorome_ref_date,
                zorome_ref_date_expert,
            )
        forecast_summary = _BASE._build_forecast_summary(
            combined_ranking=payload.get("combined_priority_ranking", []),
            expert_outputs=expert_outputs,
            zorome_by_digit=zorome_by_digit,
            zorome_by_expert_digit=zorome_by_expert_digit,
            top_n=3,
        )
        payload["forecast_summary"] = forecast_summary
        payload["forecast_summary_zorome_ref_date"] = zorome_ref_date
        _BASE._log_forecast_summary(
            forecast_summary,
            target_date=str(target_date.date()),
            target_weekday=target_ctx["target_weekday"],
        )
    except Exception as exc:
        _BASE.logger.warning("forecast_summary generation failed (non-fatal): %s", exc)

    _BASE._save_outputs(
        out_prefix=out_prefix,
        payload=payload,
        combined=combined,
        latest_test_rows=latest_test_rows,
        latest_test_bottom3_rows=latest_test_bottom3_rows,
        latest_test_full_rows=latest_test_full_rows,
        reliability_daily=reliability_daily,
        reliability_monthly=reliability_monthly,
        test_period_daily=test_period_daily,
        test_period_topk=test_period_topk,
        test_period_monthly=test_period_monthly,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
