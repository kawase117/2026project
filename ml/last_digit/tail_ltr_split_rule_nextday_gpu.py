from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.last_digit import tail_ltr_profit_ops as ops
from ml.last_digit import tail_time_adaptive_ltr_poc_improved as improved
from ml.last_digit.tail_ltr_full_walkforward_ops import topk_day_table, train_and_predict_fold
from ml.last_digit.metrics_ops import score_top2_prediction_day
from ml.last_digit.tail_ltr_split_rule_wf import (
    Candidate,
    add_simple_features,
    aggregate_mode,
    build_base_rows,
    parse_csv_floats,
    parse_csv_strs,
    resolve_db_path,
)
from ml.last_digit.binary_positive_classifier import fit_binary, predict_binary
from ml.last_digit.ceiling_effect import analyze_ceiling_effect
from ml.last_digit.ceiling_effect.stats import StatsConfig
from ml.last_digit.post_rerank import (
    build_confidence_band,
    choose_operational_pick,
    mark_avoid_candidates,
)
from ml.last_digit.utils import configure_logging
from ml.last_digit.nextday_zorome_report import fetch_latest_zorome_by_digit


EXPERT_ORDER = ["2F_N", "3F_N", "3F_A", "2F_A"]
logger = logging.getLogger(__name__)
TARGET_CHOICES = ("is_top_2", "is_rank_1", "is_top_3", "is_worst_1")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="GPU next-day forecast for floor_atype4 split experts")
    p.add_argument("--output-prefix", default="db/experiments/tail_ltr_split4_nextday_prediction_gpu")
    p.add_argument("--db-path", default="", help="DB path (optional)")
    p.add_argument("--db-glob", default="*7.db", help="DB auto-detect glob pattern used when --db-path is empty")
    p.add_argument(
        "--target-date",
        default="",
        help="Optional target prediction date in YYYY-MM-DD. "
        "When set, only history strictly before this date is used and the run reproduces that day's next-day forecast.",
    )
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--windows-wed", default="full_2025")
    p.add_argument("--lambdas-wed", default="0.75,1.0,1.25")
    p.add_argument("--q-grid-wed", default="0.0,0.1,0.2,0.3,0.4")
    p.add_argument("--windows-nonwed", default="recent_60d,full_2025")
    p.add_argument("--lambdas-nonwed", default="0.75,1.0,1.25")
    p.add_argument("--q-grid-nonwed", default="0.0,0.1,0.2,0.3,0.4,0.5,0.6")
    p.add_argument("--min-train-days-wed", type=int, default=12)
    p.add_argument(
        "--min-train-days-wed-recent60",
        type=int,
        default=8,
        help="Override minimum train days for Wednesday when window=recent_60d.",
    )
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
        "--model",
        choices=[
            "xgb_ranker_ndcg",
            "xgb_ranker_pairwise",
            "catboost_ranker_pairlogit",
            "lgbm_ranker_lambdarank",
        ],
        default="xgb_ranker_ndcg",
        help="Ranker model used inside fold training.",
    )
    p.add_argument(
        "--target-label",
        choices=TARGET_CHOICES,
        default="is_top_2",
        help="Training target label for the ranker.",
    )
    p.add_argument(
        "--model-extra-json",
        default="",
        help="Optional JSON object for model-specific params. "
        "Example: '{\"iterations\":300,\"depth\":6}' or '{\"task_type\":\"GPU\",\"devices\":\"0\"}'.",
    )
    p.add_argument(
        "--reliability-history-path",
        default="db/experiments/tail_ltr_split4_reliability_history.csv",
        help="Persistent history CSV used to compute daily/monthly reliability metrics.",
    )
    p.add_argument(
        "--reliability-exclude-experts",
        default="",
        help="Comma-separated experts excluded from reliability reports.",
    )
    p.add_argument(
        "--enable-test-period-report",
        action="store_true",
        help="Compute direct daily/monthly metrics over fixed test period (regime_3_fixed_split) in one run.",
    )
    p.add_argument(
        "--test-period-split-name",
        default="recent_90d_standard",
        help="Split name from build_fixed_split_configs(dataset).",
    )
    p.add_argument("--log-level", default="INFO", help="Logging level (DEBUG/INFO/WARNING/ERROR)")
    p.add_argument(
        "--binary-mode",
        choices=["off", "multiply", "filter"],
        default="off",
        help="Binary classifier integration mode.",
    )
    p.add_argument("--binary-threshold", type=float, default=0.5, help="Threshold used when --binary-mode=filter.")
    p.add_argument("--binary-c", type=float, default=0.1, help="LogisticRegression regularization parameter C.")
    p.add_argument("--binary-max-iter", type=int, default=1000, help="LogisticRegression max_iter.")
    p.add_argument(
        "--enable-digit-lag-bundle",
        action="store_true",
        help="Enable optional lag1/lag5/lag7 digit diff feature bundle (v2.1 candidate).",
    )
    p.add_argument(
        "--digit-lag-bundle-experts",
        default="",
        help="Comma-separated experts to apply digit lag bundle to. Empty means all experts when enabled.",
    )
    p.add_argument(
        "--enable-2fn-weekday-patch",
        action="store_true",
        help="Enable 2F_N-only weekday interaction patch features.",
    )
    p.add_argument(
        "--enable-ceiling-effect-report",
        action="store_true",
        help="Run KPI-centric ceiling-effect evaluation after test-period report generation.",
    )
    p.add_argument(
        "--ceiling-baseline-topk",
        default="",
        help="Optional baseline *_testperiod_topk.csv for ceiling-effect significance tests.",
    )
    p.add_argument(
        "--ceiling-output-dir",
        default="",
        help="Optional output dir for ceiling-effect artifacts. Default: <output-prefix>_ceiling_effect",
    )
    p.add_argument(
        "--ceiling-catastrophic-threshold",
        type=float,
        default=15000.0,
        help="Loss threshold for catastrophic-rate KPI in ceiling-effect report.",
    )
    p.add_argument(
        "--ceiling-n-boot",
        type=int,
        default=12000,
        help="Bootstrap iterations used by ceiling-effect significance tests.",
    )
    p.add_argument(
        "--ceiling-seed",
        type=int,
        default=20260520,
        help="Bootstrap seed used by ceiling-effect significance tests.",
    )
    p.add_argument(
        "--ceiling-min-paired",
        type=int,
        default=10,
        help="Min paired rows for Wilcoxon in ceiling-effect significance tests.",
    )
    p.add_argument(
        "--ceiling-min-unpaired",
        type=int,
        default=5,
        help="Min rows per side for Mann-Whitney fallback in ceiling-effect significance tests.",
    )
    return p


def _gpu_model_params(backend: str) -> dict[str, Any]:
    if backend == "gpu_hist":
        return {"tree_method": "gpu_hist"}
    return {"tree_method": "hist", "device": "cuda"}


def _prepare_split_dataset(
    *,
    db_path: str,
    db_glob: str,
    a_weight: float,
    non_a_weight: float,
    enable_digit_lag_bundle: bool = False,
    target_date: str = "",
) -> tuple[pd.DataFrame, pd.Timestamp, pd.Timestamp]:
    resolved_db = resolve_db_path(str(db_path), pattern=str(db_glob))
    raw = build_base_rows(db_path=resolved_db, a_weight=float(a_weight), non_a_weight=float(non_a_weight))
    base = aggregate_mode(raw, mode="floor_atype4").sort_values(["entity_key", "date"]).reset_index(drop=True)
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
        tpl[col] = 0.0
    for target_col in ("is_rank_1", "is_top_2", "is_top_3", "is_worst_1", "is_worst_3"):
        if target_col in tpl.columns:
            tpl[target_col] = 0
    ext = pd.concat([base, tpl], ignore_index=True, sort=False)
    ext = add_simple_features(ext, enable_digit_lag_bundle=enable_digit_lag_bundle)
    return ext, source_latest, next_date


def _rank_to_points(rank: int, n: int) -> float:
    return float((n - rank + 1) / n)


def _should_use_digit_lag_bundle(*, enabled: bool, allowed_experts: set[str], expert: str) -> bool:
    if not enabled:
        return False
    if not allowed_experts:
        return True
    return str(expert) in allowed_experts


def _should_use_2fn_weekday_patch(*, enabled: bool, expert: str) -> bool:
    return bool(enabled) and str(expert) == "2F_N"


def _target_topk_k(target_label: str) -> int:
    if target_label == "is_rank_1":
        return 1
    if target_label == "is_top_3":
        return 3
    if target_label == "is_worst_1":
        return 1
    return 2


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
        rows.append(_score_day_from_rank_df(dt=dt, expert=str(expert), rank_df=g))
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
    return score_top2_prediction_day(dt=dt, expert=expert, rank_df=rank_df)


def _build_test_period_daily_metrics(
    *,
    data: pd.DataFrame,
    cands_wed: list[Candidate],
    cands_non: list[Candidate],
    q_wed: list[float],
    q_non: list[float],
    min_days_wed: int,
    min_days_wed_recent60: int,
    min_days_nonwed: int,
    seed: int,
    model_params: dict[str, Any],
    model_name: str,
    binary_mode: str,
    binary_threshold: float,
    binary_c: float,
    binary_max_iter: int,
    target_label: str,
    target_topk_k: int,
    split_name: str,
    exclude_experts: set[str],
    enable_digit_lag_bundle: bool,
    digit_lag_bundle_experts: set[str],
    enable_2fn_weekday_patch: bool,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]:
    split_cfgs = improved.build_fixed_split_configs(data)
    if split_name not in split_cfgs:
        raise ValueError(f"Unknown test period split_name: {split_name}. available={sorted(split_cfgs.keys())}")
    cfg = split_cfgs[split_name]
    start = pd.Timestamp(cfg["valid_start"])
    end = pd.Timestamp(cfg["valid_end"])
    valid_dates = sorted(pd.to_datetime(data["date"].unique()))
    valid_dates = [d for d in valid_dates if start <= d <= end]

    rows: list[dict[str, Any]] = []
    topk_rows: list[dict[str, Any]] = []
    target_experts: list[str] = []
    for expert in EXPERT_ORDER:
        if expert in exclude_experts:
            continue
        ds = data[data["group_key"].astype(str) == expert]
        if ds.empty:
            continue
        target_experts.append(expert)
    total_steps = len(target_experts) * len(valid_dates)
    step = 0
    t_start = time.monotonic()
    for expert in EXPERT_ORDER:
        if expert in exclude_experts:
            continue
        ds = data[data["group_key"].astype(str) == expert].copy()
        if ds.empty:
            continue
        for dt in valid_dates:
            step += 1
            if total_steps > 0 and (step % 10 == 0 or step == 1):
                elapsed = time.monotonic() - t_start
                eta_sec = (elapsed / step * (total_steps - step)) if step > 0 else 0.0
                logger.info(
                    "progress %d/%d (expert=%s, date=%s) — elapsed %.0fs, ETA %.0fs",
                    step,
                    total_steps,
                    expert,
                    dt.strftime("%Y-%m-%d"),
                    elapsed,
                    eta_sec,
                )
            is_wed = dt.day_name() == "Wednesday"
            picked = _predict_for_date(
                df_expert=ds,
                pred_date=dt,
                candidates=(cands_wed if is_wed else cands_non),
                q_grid=(q_wed if is_wed else q_non),
                seed=seed,
                train_is_wed=is_wed,
                min_train_days=(min_days_wed if is_wed else min_days_nonwed),
                min_train_days_wed_recent60=min_days_wed_recent60,
                model_params=model_params,
                model_name=model_name,
                binary_mode=binary_mode,
                binary_threshold=binary_threshold,
                binary_c=binary_c,
                binary_max_iter=binary_max_iter,
                target_label=target_label,
                target_topk_k=target_topk_k,
                use_digit_lag_bundle=_should_use_digit_lag_bundle(
                    enabled=enable_digit_lag_bundle,
                    allowed_experts=digit_lag_bundle_experts,
                    expert=expert,
                ),
                use_2fn_weekday_patch=_should_use_2fn_weekday_patch(
                    enabled=enable_2fn_weekday_patch,
                    expert=expert,
                ),
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
            ranked = rank_df.sort_values("rank").reset_index(drop=True)
            ranked_with_avoid = mark_avoid_candidates(ranked, avoid_k=3)
            top1 = ranked.iloc[0] if len(ranked) >= 1 else None
            top2 = ranked.iloc[1] if len(ranked) >= 2 else None
            top1_machine_count = (
                float(pd.to_numeric(top1.get("machine_count", np.nan), errors="coerce"))
                if top1 is not None
                else np.nan
            )
            top1_avg_diff_per_machine = (
                float(top1["actual_raw_diff"]) / top1_machine_count
                if top1 is not None and np.isfinite(top1_machine_count) and top1_machine_count > 0.0
                else np.nan
            )
            pred_span_top12 = float(top1["pred"] - top2["pred"]) if (top1 is not None and top2 is not None) else np.nan
            confidence_band = build_confidence_band(pred_span_top12 if np.isfinite(pred_span_top12) else 0.0)
            actual_top2_tails = set(
                ranked.sort_values("actual_raw_diff", ascending=False).head(2)["last_digit"].astype(str).tolist()
            )
            op_tail, op_source = choose_operational_pick(
                top1_tail=(str(top1["last_digit"]) if top1 is not None else ""),
                top2_tail=(str(top2["last_digit"]) if top2 is not None else ""),
                confidence_band=confidence_band,
            )
            if top1 is not None and op_tail == str(top1["last_digit"]):
                op_pred = float(top1["pred"])
                op_actual_raw_diff = float(top1["actual_raw_diff"])
            elif top2 is not None and op_tail == str(top2["last_digit"]):
                op_pred = float(top2["pred"])
                op_actual_raw_diff = float(top2["actual_raw_diff"])
            else:
                op_pred = np.nan
                op_actual_raw_diff = np.nan
            top1_is_avoid = (
                int(
                    ranked_with_avoid.loc[
                        ranked_with_avoid["last_digit"].astype(str) == str(top1["last_digit"]),
                        "is_avoid_candidate",
                    ].iloc[0]
                )
                if top1 is not None
                else 0
            )
            top2_is_avoid = (
                int(
                    ranked_with_avoid.loc[
                        ranked_with_avoid["last_digit"].astype(str) == str(top2["last_digit"]),
                        "is_avoid_candidate",
                    ].iloc[0]
                )
                if top2 is not None
                else 0
            )
            topk_rows.append(
                {
                    "date": dt.strftime("%Y-%m-%d"),
                    "month": dt.strftime("%Y-%m"),
                    "weekday": dt.day_name(),
                    "expert": str(expert),
                    "model": str(model_name),
                    "target_label": str(target_label),
                    "window": str(cand.window_name),
                    "lambda": float(cand.decay_lambda),
                    "top1_tail": (str(top1["last_digit"]) if top1 is not None else ""),
                    "top1_pred": (float(top1["pred"]) if top1 is not None else np.nan),
                    "top1_actual_raw_diff": (float(top1["actual_raw_diff"]) if top1 is not None else np.nan),
                    "top1_machine_count": top1_machine_count,
                    "top1_avg_diff_per_machine": top1_avg_diff_per_machine,
                    "top1_prob_positive": (
                        float(top1.get("prob_positive", np.nan))
                        if top1 is not None
                        else np.nan
                    ),
                    "top1_final_score": (
                        float(top1.get("final_score", np.nan))
                        if top1 is not None
                        else np.nan
                    ),
                    "top2_tail": (str(top2["last_digit"]) if top2 is not None else ""),
                    "top2_pred": (float(top2["pred"]) if top2 is not None else np.nan),
                    "top2_actual_raw_diff": (float(top2["actual_raw_diff"]) if top2 is not None else np.nan),
                    "top2_prob_positive": (
                        float(top2.get("prob_positive", np.nan))
                        if top2 is not None
                        else np.nan
                    ),
                    "top2_final_score": (
                        float(top2.get("final_score", np.nan))
                        if top2 is not None
                        else np.nan
                    ),
                    "pred_span_top12": pred_span_top12,
                    "confidence_band": confidence_band,
                    "operational_pick_tail": op_tail,
                    "operational_pick_source": op_source,
                    "operational_pick_pred": op_pred,
                    "operational_pick_actual_raw_diff": op_actual_raw_diff,
                    "operational_pick_in_actual_top2": int(op_tail in actual_top2_tails) if op_tail != "" else 0,
                    "top1_is_avoid": top1_is_avoid,
                    "top2_is_avoid": top2_is_avoid,
                    "hit_at_2": float(rec.get("hit_at_2", np.nan)),
                    "hit_at_3": float(rec.get("hit_at_3", np.nan)),
                }
            )

    daily = pd.DataFrame(rows).sort_values(["date", "expert"]).reset_index(drop=True) if rows else pd.DataFrame()
    topk = pd.DataFrame(topk_rows).sort_values(["date", "expert"]).reset_index(drop=True) if topk_rows else pd.DataFrame()
    period_meta = {"valid_start": start.strftime("%Y-%m-%d"), "valid_end": end.strftime("%Y-%m-%d"), "split_name": split_name}
    return daily, topk, period_meta


def _predict_for_date(
    *,
    df_expert: pd.DataFrame,
    pred_date: pd.Timestamp,
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
) -> tuple[Candidate, dict[str, float], pd.DataFrame, float] | None:
    rows: list[tuple[float, Candidate, dict[str, float], pd.DataFrame]] = []
    all_features = improved.get_numeric_features(df_expert)
    excluded_targets = {"is_top_2", "is_rank_1", "is_top_3", "is_worst_1", "is_worst_3"}
    all_features = [f for f in all_features if f not in excluded_targets]
    if not use_digit_lag_bundle:
        all_features = [f for f in all_features if f not in {"lag1_digit_diff", "lag5_digit_diff", "lag7_digit_diff"}]
    if not use_2fn_weekday_patch:
        all_features = [f for f in all_features if f not in {"wed_x_weekday_delta", "wed_x_days_since_last_top2"}]
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
        effective_min_days = int(min_train_days)
        if train_is_wed and cand.window_name == "recent_60d":
            effective_min_days = int(min(min_train_days, max(1, min_train_days_wed_recent60)))
        if train["date"].nunique() < effective_min_days or test.empty:
            continue

        train = train.copy()
        test = test.copy()
        feats = ops.select_features(train, all_features, str(target_label), "all")
        try:
            cal_df, test_df, choice = train_and_predict_fold(
                train_df=train,
                test_df=test,
                target=str(target_label),
                features=feats,
                decay_lambda=cand.decay_lambda,
                random_state=seed,
                model_params=model_params,
                temperature_candidates=improved.CalibrationConfig().temperature_candidates,
                blend_weights=improved.CalibrationConfig().blend_weights,
                q_grid=q_grid,
                k=int(target_topk_k),
                model_name=model_name,
            )
        except Exception as exc:
            logger.warning(
                "Skip candidate due to training error: model=%s window=%s lambda=%.4f date=%s reason=%s",
                model_name,
                cand.window_name,
                float(cand.decay_lambda),
                pred_date.strftime("%Y-%m-%d"),
                str(exc),
            )
            continue
        cal_day = topk_day_table(cal_df, "pred", k=int(target_topk_k))
        keep = cal_day["margin"] >= choice["threshold"]
        cal_ex = np.where(keep.to_numpy(), cal_day["excess"].to_numpy(), 0.0)
        score = float(np.mean(cal_ex)) if len(cal_ex) else -1e18

        ranked = test_df.copy()
        expert_name = (
            str(df_expert["group_key"].iloc[0])
            if ("group_key" in df_expert.columns and not df_expert.empty)
            else "unknown"
        )
        if binary_mode == "off":
            ranked["prob_positive"] = np.full(len(ranked), 0.5, dtype=float)
        else:
            binary_models, binary_feature_map = fit_binary(
                train_df=train,
                expert=expert_name,
                c=float(binary_c),
                max_iter=int(binary_max_iter),
                random_state=int(seed),
            )
            prob_positive = predict_binary(
                test,
                expert=expert_name,
                models=binary_models,
                feature_map=binary_feature_map,
            )
            ranked["prob_positive"] = np.asarray(prob_positive, dtype=float)
        ranked["ltr_pred"] = pd.to_numeric(ranked["pred"], errors="coerce").fillna(0.0).astype(float)
        ranked["rank_pct_ltr"] = ranked["ltr_pred"].rank(method="first", pct=True).astype(float)
        ranked["final_score"] = ranked["ltr_pred"].astype(float)
        if binary_mode == "multiply":
            ranked["final_score"] = ranked["rank_pct_ltr"] * ranked["prob_positive"]
            ranked["pred"] = ranked["final_score"]
        elif binary_mode == "filter":
            keep_mask = ranked["prob_positive"] > float(binary_threshold)
            if keep_mask.any():
                ranked = ranked[keep_mask].copy()
            ranked["final_score"] = ranked["ltr_pred"]
            ranked["pred"] = ranked["final_score"]
        else:
            ranked["pred"] = ranked["ltr_pred"]

        source = test[["last_digit", "total_diff_coins"]].copy()
        source["actual_raw_diff"] = pd.to_numeric(source["total_diff_coins"], errors="coerce").fillna(0.0)
        source = source.drop(columns=["total_diff_coins"])
        ranked = ranked.join(source, how="left")
        if ranked["last_digit"].isna().any():
            # Fallback to positional alignment only when index alignment is impossible.
            ranked = ranked.reset_index(drop=True)
            source_pos = source.reset_index(drop=True)
            ranked["last_digit"] = source_pos["last_digit"]
            ranked["actual_raw_diff"] = source_pos["actual_raw_diff"]
        ranked["machine_count"] = pd.to_numeric(ranked.get("machine_count", 0.0), errors="coerce").fillna(0.0)
        ranked = ranked.reset_index(drop=True)
        ranked = ranked.sort_values("pred", ascending=False).reset_index(drop=True)
        ranked["rank"] = np.arange(1, len(ranked) + 1)
        ranked = ranked[
            [
                "rank",
                "last_digit",
                "pred",
                "actual_raw_diff",
                "machine_count",
                "prob_positive",
                "final_score",
                "ltr_pred",
                "rank_pct_ltr",
            ]
        ]
        rows.append((score, cand, choice, ranked))

    if not rows:
        return None
    score, best_cand, best_choice, best_ranked = sorted(rows, key=lambda x: x[0], reverse=True)[0]
    return best_cand, best_choice, best_ranked, float(score)


def _update_reliability_history(
    *,
    history_path: Path,
    latest_test_full_rows: list[dict[str, Any]],
) -> pd.DataFrame:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_prev = pd.DataFrame()
    if history_path.exists():
        history_prev = pd.read_csv(history_path, encoding="utf-8-sig")
    history_new = pd.DataFrame(latest_test_full_rows)
    if history_new.empty:
        return history_prev
    history_all = pd.concat([history_prev, history_new], ignore_index=True)
    history_all = history_all.drop_duplicates(subset=["date", "expert", "last_digit"], keep="last")
    history_all = history_all.sort_values(["date", "expert", "last_digit"]).reset_index(drop=True)
    history_all.to_csv(history_path, index=False, encoding="utf-8-sig")
    return history_all


def _confidence_pct(scores: list[float]) -> list[int]:
    """Min-max normalize scores to 0-100 relative confidence percentages."""
    if not scores:
        return []
    lo, hi = min(scores), max(scores)
    if hi <= lo:
        return [100] * len(scores)
    return [round((s - lo) / (hi - lo) * 100) for s in scores]


def _build_forecast_summary(
    *,
    combined_ranking: list[dict[str, Any]],
    expert_outputs: dict[str, Any],
    zorome_by_digit: dict[str, list],
    zorome_by_expert_digit: dict[str, dict[str, list]] | None = None,
    top_n: int = 3,
) -> dict[str, Any]:
    """Build TOP-N forecast summary with relative confidence and zorome machines."""
    top_combined = combined_ranking[:top_n]
    conf_c_all = _confidence_pct([float(r["combined_score"]) for r in combined_ranking])
    conf_c = conf_c_all[: len(top_combined)]
    combined_rows = []
    for row, conf in zip(top_combined, conf_c):
        digit = str(row["last_digit"])
        combined_rows.append(
            {
                "rank": int(row["rank"]),
                "last_digit": digit,
                "combined_score": float(row["combined_score"]),
                "confidence_pct": conf,
                "zorome_machines": [
                    {"machine_number": int(mn), "machine_name": str(nm)}
                    for mn, nm in zorome_by_digit.get(digit, [])
                ],
            }
        )

    expert_summaries: dict[str, list[dict[str, Any]]] = {}
    for expert in EXPERT_ORDER:
        info = expert_outputs.get(expert, {})
        if info.get("status") != "ok":
            continue
        ranking_all = [r for r in info.get("ranking", []) if "pred" in r]
        ranking = ranking_all[:top_n]
        conf_e_all = _confidence_pct([float(r["pred"]) for r in ranking_all])
        conf_e = conf_e_all[: len(ranking)]
        expert_zorome = (zorome_by_expert_digit or {}).get(str(expert), {})
        expert_rows = []
        for row, conf in zip(ranking, conf_e):
            digit = str(row["last_digit"])
            expert_rows.append(
                {
                    "rank": int(row.get("rank", 0)),
                    "last_digit": digit,
                    "pred": float(row["pred"]),
                    "confidence_pct": conf,
                    "zorome_machines": [
                        {"machine_number": int(mn), "machine_name": str(nm)}
                        for mn, nm in expert_zorome.get(digit, zorome_by_digit.get(digit, []))
                    ],
                }
            )
        expert_summaries[expert] = expert_rows

    return {
        "combined": combined_rows,
        "by_expert": expert_summaries,
        "confidence_scale": "relative_within_group_0_100",
    }


def _format_machine_list(machines: list[dict[str, Any]], max_items: int = 3) -> str:
    if not machines:
        return "なし"
    shown = machines[: max_items]
    text = " / ".join(f"{m['machine_number']} {m['machine_name']}" for m in shown)
    extra = len(machines) - len(shown)
    if extra > 0:
        text += f" / ...(+{extra})"
    return text


def _log_forecast_summary(
    summary: dict[str, Any],
    *,
    target_date: str,
    target_weekday: str,
) -> None:
    """Print human-readable forecast summary with confidence and zorome machines to logger."""
    lines = [
        "",
        f"===== 翌日予測サマリー ({target_date} {target_weekday}) =====",
        "※ 確信度は同一グループ内の相対値 (0-100)",
        "combined順位 TOP3:",
    ]
    for row in summary.get("combined", []):
        machines = row.get("zorome_machines", [])
        machine_str = _format_machine_list(machines)
        lines.append(
            f"  Rank {row['rank']}: 末尾 {row['last_digit']}  相対確信度 {row['confidence_pct']}%"
        )
        lines.append(f"    ゾロ目候補: {machine_str}")
    for expert, rows in summary.get("by_expert", {}).items():
        lines.append(f"{expert} TOP3:")
        for row in rows:
            machines = row.get("zorome_machines", [])
            machine_str = _format_machine_list(machines)
            lines.append(
                f"  Rank {row['rank']}: 末尾 {row['last_digit']}  相対確信度 {row['confidence_pct']}%"
            )
            lines.append(f"    ゾロ目候補: {machine_str}")
    logger.info("\n".join(lines))


def _save_outputs(
    *,
    out_prefix: Path,
    payload: dict[str, Any],
    combined: pd.DataFrame,
    latest_test_rows: list[dict[str, Any]],
    latest_test_bottom3_rows: list[dict[str, Any]],
    latest_test_full_rows: list[dict[str, Any]],
    reliability_daily: pd.DataFrame,
    reliability_monthly: pd.DataFrame,
    test_period_daily: pd.DataFrame,
    test_period_topk: pd.DataFrame,
    test_period_monthly: pd.DataFrame,
) -> None:
    out_json = out_prefix.with_suffix(".json")
    out_csv = out_prefix.with_suffix(".csv")
    out_test_csv = out_prefix.with_name(out_prefix.name + "_latest_test_top3.csv")
    out_test_bottom_csv = out_prefix.with_name(out_prefix.name + "_latest_test_bottom3.csv")
    out_test_full_csv = out_prefix.with_name(out_prefix.name + "_latest_test_full.csv")
    out_rel_daily_csv = out_prefix.with_name(out_prefix.name + "_reliability_daily.csv")
    out_rel_monthly_csv = out_prefix.with_name(out_prefix.name + "_reliability_monthly.csv")
    out_period_daily_csv = out_prefix.with_name(out_prefix.name + "_testperiod_daily.csv")
    out_period_topk_csv = out_prefix.with_name(out_prefix.name + "_testperiod_topk.csv")
    out_period_monthly_csv = out_prefix.with_name(out_prefix.name + "_testperiod_monthly.csv")

    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if not combined.empty:
        combined.to_csv(out_csv, index=False, encoding="utf-8-sig")
    if latest_test_rows:
        pd.DataFrame(latest_test_rows).to_csv(out_test_csv, index=False, encoding="utf-8-sig")
    if latest_test_bottom3_rows:
        pd.DataFrame(latest_test_bottom3_rows).to_csv(out_test_bottom_csv, index=False, encoding="utf-8-sig")
    if latest_test_full_rows:
        pd.DataFrame(latest_test_full_rows).to_csv(out_test_full_csv, index=False, encoding="utf-8-sig")
    if not reliability_daily.empty:
        reliability_daily.to_csv(out_rel_daily_csv, index=False, encoding="utf-8-sig")
    if not reliability_monthly.empty:
        reliability_monthly.to_csv(out_rel_monthly_csv, index=False, encoding="utf-8-sig")
    if not test_period_daily.empty:
        test_period_daily.to_csv(out_period_daily_csv, index=False, encoding="utf-8-sig")
    if not test_period_topk.empty:
        test_period_topk.to_csv(out_period_topk_csv, index=False, encoding="utf-8-sig")
    if not test_period_monthly.empty:
        test_period_monthly.to_csv(out_period_monthly_csv, index=False, encoding="utf-8-sig")

    logger.info("Saved: %s", out_json)
    if not combined.empty:
        logger.info("Saved: %s", out_csv)
    if latest_test_rows:
        logger.info("Saved: %s", out_test_csv)
    if latest_test_bottom3_rows:
        logger.info("Saved: %s", out_test_bottom_csv)
    if latest_test_full_rows:
        logger.info("Saved: %s", out_test_full_csv)
    if not reliability_daily.empty:
        logger.info("Saved: %s", out_rel_daily_csv)
    if not reliability_monthly.empty:
        logger.info("Saved: %s", out_rel_monthly_csv)
    if not test_period_daily.empty:
        logger.info("Saved: %s", out_period_daily_csv)
    if not test_period_topk.empty:
        logger.info("Saved: %s", out_period_topk_csv)
    if not test_period_monthly.empty:
        logger.info("Saved: %s", out_period_monthly_csv)
    if not combined.empty:
        logger.info("\n%s", combined.head(5).to_string(index=False))


def main() -> int:
    args = build_parser().parse_args()
    configure_logging(args.log_level)
    target_label = str(args.target_label)
    target_topk_k = _target_topk_k(target_label)
    suffix = f"_{args.model}"
    output_prefix = args.output_prefix if args.output_prefix.endswith(suffix) else f"{args.output_prefix}{suffix}"
    out_prefix = Path(output_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
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
    reliability_exclude = set(parse_csv_strs(args.reliability_exclude_experts))
    digit_lag_bundle_experts = set(parse_csv_strs(args.digit_lag_bundle_experts))

    data, source_latest, target_date = _prepare_split_dataset(
        db_path=str(args.db_path),
        db_glob=str(args.db_glob),
        a_weight=args.a_weight,
        non_a_weight=args.non_a_weight,
        enable_digit_lag_bundle=bool(args.enable_digit_lag_bundle),
        target_date=str(args.target_date),
    )
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
            min_train_days_wed_recent60=int(args.min_train_days_wed_recent60),
            model_params=model_params,
            model_name=model_name,
            binary_mode=str(args.binary_mode),
            binary_threshold=float(args.binary_threshold),
            binary_c=float(args.binary_c),
            binary_max_iter=int(args.binary_max_iter),
            target_label=target_label,
            target_topk_k=target_topk_k,
            use_digit_lag_bundle=_should_use_digit_lag_bundle(
                enabled=bool(args.enable_digit_lag_bundle),
                allowed_experts=digit_lag_bundle_experts,
                expert=expert,
            ),
            use_2fn_weekday_patch=_should_use_2fn_weekday_patch(
                enabled=bool(args.enable_2fn_weekday_patch),
                expert=expert,
            ),
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

    if combined_accumulator:
        combined = (
            pd.DataFrame([{"last_digit": k, "combined_score": v} for k, v in combined_accumulator.items()])
            .sort_values("combined_score", ascending=False)
            .reset_index(drop=True)
        )
        combined["rank"] = np.arange(1, len(combined) + 1)
        combined = combined[["rank", "last_digit", "combined_score"]]
    else:
        combined = pd.DataFrame(columns=["rank", "last_digit", "combined_score"])

    # Latest-known-date test: predict source_latest using the same selected candidates per expert.
    latest_test_rows: list[dict[str, Any]] = []
    latest_test_bottom3_rows: list[dict[str, Any]] = []
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
            min_train_days_wed_recent60=int(args.min_train_days_wed_recent60),
            model_params=model_params,
            model_name=model_name,
            binary_mode=str(args.binary_mode),
            binary_threshold=float(args.binary_threshold),
            binary_c=float(args.binary_c),
            binary_max_iter=int(args.binary_max_iter),
            target_label=target_label,
            target_topk_k=target_topk_k,
            use_digit_lag_bundle=_should_use_digit_lag_bundle(
                enabled=bool(args.enable_digit_lag_bundle),
                allowed_experts=digit_lag_bundle_experts,
                expert=expert,
            ),
            use_2fn_weekday_patch=_should_use_2fn_weekday_patch(
                enabled=bool(args.enable_2fn_weekday_patch),
                expert=expert,
            ),
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
                min_train_days_wed_recent60=int(args.min_train_days_wed_recent60),
                model_params=model_params,
                model_name=model_name,
                binary_mode=str(args.binary_mode),
                binary_threshold=float(args.binary_threshold),
                binary_c=float(args.binary_c),
                binary_max_iter=int(args.binary_max_iter),
                target_label=target_label,
                target_topk_k=target_topk_k,
                use_digit_lag_bundle=_should_use_digit_lag_bundle(
                    enabled=bool(args.enable_digit_lag_bundle),
                    allowed_experts=digit_lag_bundle_experts,
                    expert=expert,
                ),
                use_2fn_weekday_patch=_should_use_2fn_weekday_patch(
                    enabled=bool(args.enable_2fn_weekday_patch),
                    expert=expert,
                ),
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
                    "prob_positive": float(rec.get("prob_positive", np.nan)),
                    "final_score": float(rec.get("final_score", np.nan)),
                    "ltr_pred": float(rec.get("ltr_pred", np.nan)),
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
                    "prob_positive": float(rec.get("prob_positive", np.nan)),
                    "final_score": float(rec.get("final_score", np.nan)),
                    "ltr_pred": float(rec.get("ltr_pred", np.nan)),
                }
            )
        for rec in latest_rank_df.sort_values("rank", ascending=True).tail(3).to_dict(orient="records"):
            latest_test_bottom3_rows.append(
                {
                    "expert": expert,
                    "rank": int(rec["rank"]),
                    "last_digit": str(rec["last_digit"]),
                    "pred": float(rec["pred"]),
                    "actual_raw_diff": float(rec["actual_raw_diff"]),
                    "prob_positive": float(rec.get("prob_positive", np.nan)),
                    "final_score": float(rec.get("final_score", np.nan)),
                    "ltr_pred": float(rec.get("ltr_pred", np.nan)),
                }
            )

    history_path = Path(args.reliability_history_path)
    history_all = _update_reliability_history(
        history_path=history_path,
        latest_test_full_rows=latest_test_full_rows,
    )

    reliability_daily = _build_reliability_daily(history_all, reliability_exclude)
    reliability_monthly = _build_reliability_monthly(reliability_daily)
    reliability_overall = _build_reliability_overall(reliability_daily)

    test_period_daily = pd.DataFrame()
    test_period_topk = pd.DataFrame()
    test_period_monthly = pd.DataFrame()
    test_period_overall: list[dict[str, Any]] = []
    test_period_meta: dict[str, str] = {}
    if args.enable_test_period_report:
        test_period_daily, test_period_topk, test_period_meta = _build_test_period_daily_metrics(
            data=data,
            cands_wed=cands_wed,
            cands_non=cands_non,
            q_wed=parse_csv_floats(args.q_grid_wed),
            q_non=parse_csv_floats(args.q_grid_nonwed),
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
            enable_2fn_weekday_patch=bool(args.enable_2fn_weekday_patch),
        )
        if not test_period_daily.empty:
            ok = test_period_daily[test_period_daily["status"] == "ok"].copy()
            test_period_monthly = _build_reliability_monthly(ok)
            test_period_overall = _build_reliability_overall(ok)

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
        "enable_2fn_weekday_patch": bool(args.enable_2fn_weekday_patch),
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
        "latest_test_bottom3_by_expert": latest_test_bottom3_rows,
        "reliability_history_path": str(history_path),
        "reliability_excluded_experts": sorted(reliability_exclude),
        "reliability_overall_by_expert": reliability_overall,
        "test_period_report_enabled": bool(args.enable_test_period_report),
        "test_period_config": test_period_meta,
        "test_period_overall_by_expert": test_period_overall,
        "ceiling_effect_report_enabled": bool(args.enable_ceiling_effect_report),
        "notes": "latest_test_top3_by_expert uses known latest date as one-step holdout style check with selected candidates.",
    }

    if args.enable_ceiling_effect_report:
        if target_label.startswith("is_worst_"):
            logger.warning("Skip ceiling-effect report for worst target: %s", target_label)
            payload["ceiling_effect_report_status"] = "skipped_worst_target"
        elif test_period_topk.empty:
            logger.warning("Skip ceiling-effect report: test period topk is empty.")
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
            stats_cfg = StatsConfig(
                n_boot=int(args.ceiling_n_boot),
                seed=int(args.ceiling_seed),
                min_paired_for_wilcoxon=int(args.ceiling_min_paired),
                min_unpaired_for_mwu=int(args.ceiling_min_unpaired),
            )
            logger.info(
                "Running ceiling-effect KPI report: input=%s baseline=%s output_dir=%s",
                out_period_topk_csv,
                baseline_path or "(none)",
                ceiling_out_dir,
            )
            ceiling_outputs = analyze_ceiling_effect(
                input_topk_csv=out_period_topk_csv,
                output_dir=ceiling_out_dir,
                baseline_topk_csv=baseline_path,
                db_path=resolve_db_path(str(args.db_path), pattern=str(args.db_glob)),
                stats_config=stats_cfg,
                catastrophic_threshold=float(args.ceiling_catastrophic_threshold),
            )
            payload["ceiling_effect_report_status"] = "ok"
            payload["ceiling_effect_outputs"] = {k: str(v) for k, v in ceiling_outputs.items()}

    # --- ゾロ目付き確信度サマリーをpayloadに統合 ---
    try:
        _resolved_db = resolve_db_path(str(args.db_path), pattern=str(args.db_glob))
        _zorome_ref_date, _zorome_by_digit = fetch_latest_zorome_by_digit(_resolved_db)
        _zorome_ref_date_expert, _zorome_by_expert_digit = fetch_latest_zorome_by_expert_digit(_resolved_db)
        if _zorome_ref_date_expert and _zorome_ref_date_expert != _zorome_ref_date:
            logger.warning(
                "zorome ref date mismatch: by_digit=%s by_expert=%s",
                _zorome_ref_date,
                _zorome_ref_date_expert,
            )
        _forecast_summary = _build_forecast_summary(
            combined_ranking=payload.get("combined_priority_ranking", []),
            expert_outputs=expert_outputs,
            zorome_by_digit=_zorome_by_digit,
            zorome_by_expert_digit=_zorome_by_expert_digit,
            top_n=3,
        )
        payload["forecast_summary"] = _forecast_summary
        payload["forecast_summary_zorome_ref_date"] = _zorome_ref_date
        _log_forecast_summary(
            _forecast_summary,
            target_date=str(target_date.date()),
            target_weekday=target_weekday,
        )
    except Exception as _exc:
        logger.warning("forecast_summary generation failed (non-fatal): %s", _exc)
    # -----------------------------------------------

    _save_outputs(
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
