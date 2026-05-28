from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

from . import machine_type_common as common


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Monthly reliability check for machine-type predictions")
    parser.add_argument("--db-path", default="", help="SQLite DB path. Empty means auto-detect db/*7.db")
    parser.add_argument("--alpha", type=float, default=5.0, help="Shrinkage alpha for rank label generation")
    parser.add_argument("--model-type", choices=["sgd", "xgb", "ltr"], default="xgb", help="Model type: sgd/xgb=binary classifier per target, ltr=XGBRanker (rank:ndcg) with shared ranking score")
    parser.add_argument("--ltr-decay-lambda", type=float, default=0.3, help="Exponential time-decay lambda for LTR (0.0 = no decay). Ignored for sgd/xgb.")
    parser.add_argument("--ltr-objective", choices=["rank:ndcg", "rank:pairwise"], default="rank:ndcg", help="XGBRanker objective. Ignored for sgd/xgb.")
    parser.add_argument(
        "--gpu-backend",
        choices=["auto", "cpu", "cuda", "gpu_hist"],
        default="auto",
        help="GPU backend for xgb. Ignored for sgd.",
    )
    parser.add_argument(
        "--segment-mode",
        choices=["global", "floor2", "type2", "floor_type4"],
        default="global",
        help="Specialization mode with global fallback",
    )
    parser.add_argument(
        "--segment-blend-weight",
        type=float,
        default=1.0,
        help="Blend weight for segment model score vs global score (1.0=segment only, 0.0=global only)",
    )
    parser.add_argument(
        "--prior-blend-weight",
        type=float,
        default=0.0,
        help="Blend model probability with prior target rate features (0.0=model only, 1.0=prior only)",
    )
    parser.add_argument("--min-segment-days", type=int, default=21, help="Minimum unique dates per segment model")
    parser.add_argument("--min-segment-rows", type=int, default=300, help="Minimum rows per segment model")
    parser.add_argument(
        "--eval-days",
        type=int,
        default=60,
        help="Number of most-recent historical dates to evaluate with expanding train windows",
    )
    parser.add_argument(
        "--eval-offset-days",
        type=int,
        default=0,
        help="Skip this many most-recent dates before taking eval-days window (for split-batch evaluation)",
    )
    parser.add_argument(
        "--threshold-split-thursday",
        action="store_true",
        help="Use separate optimized thresholds for Thursday vs non-Thursday based on train data (sgd/xgb only)",
    )
    parser.add_argument(
        "--output-prefix",
        default="ml/machine_type/reports/machine_type_reliability",
        help="Output prefix for reliability artifacts",
    )
    parser.add_argument(
        "--feature-list-path",
        default="",
        help="Optional path to newline-separated feature names to whitelist",
    )
    parser.add_argument("--random-state", type=int, default=42)
    return parser


def _evaluate_single_date(
    ranked_df: pd.DataFrame,
    *,
    pred_date: pd.Timestamp,
    random_state: int,
    model_type: str,
    gpu_backend: str,
    segment_mode: str,
    segment_blend_weight: float,
    prior_blend_weight: float,
    min_segment_days: int,
    min_segment_rows: int,
    feature_whitelist: set[str] | None,
    ltr_decay_lambda: float = 0.3,
    ltr_objective: str = "rank:ndcg",
    threshold_split_thursday: bool = False,
) -> list[dict[str, Any]]:
    synthetic_featured, truth_day, coverage = common.build_backtest_frame_for_pred_date(
        ranked_df,
        pred_date=pred_date,
    )
    if synthetic_featured.empty or truth_day.empty:
        return []
    train_df = synthetic_featured.loc[synthetic_featured["date"] < pred_date].copy()
    pred_features = synthetic_featured.loc[synthetic_featured["date"] == pred_date].copy()
    if train_df.empty or pred_features.empty:
        return []
    feature_columns = common.get_feature_columns(synthetic_featured)
    if feature_whitelist is not None:
        filtered = [c for c in feature_columns if c in feature_whitelist]
        if filtered:
            feature_columns = filtered
    truth_cols = ["machine_name", *common.TARGET_COLUMNS]
    day_df = pred_features.drop(columns=list(common.TARGET_COLUMNS), errors="ignore").merge(
        truth_day[truth_cols],
        on="machine_name",
        how="inner",
    )
    if day_df.empty:
        return []
    rows: list[dict[str, Any]] = []

    if str(model_type).strip().lower() == "ltr":
        # LTR path: single XGBRanker trained on all targets combined via rank_pct.
        # The same ranking score is evaluated against each binary target for Hit@K comparison.
        decay = float(ltr_decay_lambda) if float(ltr_decay_lambda) > 0.0 else None
        trained_ltr = common.train_ltr_model(
            train_df,
            feature_columns=feature_columns,
            random_state=random_state,
            decay_lambda=decay,
            objective=str(ltr_objective),
        )
        ltr_scores = common.predict_ltr_scores(day_df, trained=trained_ltr)
        for target in common.TARGET_COLUMNS:
            score_col = f"score_{target}"
            work = day_df.copy()
            work[score_col] = ltr_scores
            # threshold=0.5 is a placeholder; only Hit@K metrics are meaningful for LTR.
            metrics = common.evaluate_prediction_day(
                work,
                target=target,
                score_col=score_col,
                threshold=0.5,
            )
            metrics.update(
                {
                    "date": pred_date.strftime("%Y-%m-%d"),
                    "month": pred_date.strftime("%Y-%m"),
                    "day_of_week": pred_date.day_name(),
                    "is_thursday": int(pred_date.dayofweek == 3),
                    "threshold": 0.5,
                    "entity_count": int(len(day_df)),
                    "truth_entity_count": int(coverage["truth_entities"]),
                    "known_entity_count": int(coverage["known_entities"]),
                    "unseen_entity_count": int(coverage["unseen_entities"]),
                    "known_coverage": float(coverage["known_entities"] / max(coverage["truth_entities"], 1)),
                    "skip_rate": float(0.0),
                    "model_type": "ltr",
                    "backend_used": str(trained_ltr.backend_used),
                    "segment_mode": "global",
                    "segment_blend_weight": float(0.0),
                    "prior_blend_weight": float(0.0),
                    "segment_models_used": 0,
                    "segment_prediction_rows": 0,
                }
            )
            rows.append(metrics)
    else:
        for target in common.TARGET_COLUMNS:
            trained = common.train_segmented_target_models(
                train_df,
                target=target,
                feature_columns=feature_columns,
                random_state=random_state,
                model_type=model_type,
                gpu_backend=gpu_backend,
                segment_mode=segment_mode,
                min_segment_days=min_segment_days,
                min_segment_rows=min_segment_rows,
            )
            proba, used_segment = common.predict_segmented_proba(
                day_df,
                trained=trained,
                segment_blend_weight=segment_blend_weight,
            )
            proba = common.blend_with_prior_rate(
                day_df,
                target=target,
                proba=proba,
                prior_blend_weight=prior_blend_weight,
            )
            threshold = float(trained.global_model.threshold)
            threshold_source = "global_threshold"
            if bool(threshold_split_thursday):
                train_scores, _ = common.predict_segmented_proba(
                    train_df,
                    trained=trained,
                    segment_blend_weight=segment_blend_weight,
                )
                train_scores = common.blend_with_prior_rate(
                    train_df,
                    target=target,
                    proba=train_scores,
                    prior_blend_weight=prior_blend_weight,
                )
                train_work = train_df[["is_thursday", target]].copy()
                train_work["score"] = train_scores
                thursday = int(pred_date.dayofweek == 3)
                threshold = _optimize_threshold_for_is_thursday(
                    train_work,
                    target=target,
                    use_thursday=thursday,
                    fallback=threshold,
                )
                threshold_source = f"thursday_split_{thursday}"
            score_col = f"score_{target}"
            work = day_df.copy()
            work[score_col] = proba
            metrics = common.evaluate_prediction_day(
                work,
                target=target,
                score_col=score_col,
                threshold=threshold,
            )
            metrics.update(
                {
                    "date": pred_date.strftime("%Y-%m-%d"),
                    "month": pred_date.strftime("%Y-%m"),
                    "day_of_week": pred_date.day_name(),
                    "is_thursday": int(pred_date.dayofweek == 3),
                    "threshold": float(threshold),
                    "threshold_source": threshold_source,
                    "entity_count": int(len(day_df)),
                    "truth_entity_count": int(coverage["truth_entities"]),
                    "known_entity_count": int(coverage["known_entities"]),
                    "unseen_entity_count": int(coverage["unseen_entities"]),
                    "known_coverage": float(coverage["known_entities"] / max(coverage["truth_entities"], 1)),
                    "skip_rate": float(0.0),
                    "model_type": str(trained.global_model.model_type),
                    "backend_used": str(trained.global_model.backend_used),
                    "segment_mode": str(segment_mode),
                    "segment_blend_weight": float(segment_blend_weight),
                    "prior_blend_weight": float(prior_blend_weight),
                    "segment_models_used": int(len(trained.segment_models)),
                    "segment_prediction_rows": int(used_segment.sum()),
                }
            )
            rows.append(metrics)
    return rows


def build_reliability_tables(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame]:
    db_path = common.resolve_db_path(args.db_path)
    raw = common.load_daily_machine_type_summary(db_path)
    master = common.load_machine_master(db_path)
    segment_daily = common.load_machine_name_daily_segments(db_path)
    base = common.prepare_machine_type_base_frame(raw)
    base = common.attach_machine_master_flags(base, master)
    base = common.attach_daily_segments(base, segment_daily)
    ranked = common.add_shrunk_rank_targets(base, alpha=args.alpha)
    feature_whitelist = _load_feature_whitelist(args.feature_list_path)
    unique_dates = sorted(pd.to_datetime(ranked["date"].unique()))
    if len(unique_dates) < 2:
        raise ValueError("Not enough dates for reliability check")
    eval_days = max(int(args.eval_days), 1)
    eval_offset = max(int(getattr(args, "eval_offset_days", 0)), 0)
    if eval_offset >= len(unique_dates):
        raise ValueError(f"eval_offset_days={eval_offset} is too large for {len(unique_dates)} dates")
    end_idx = len(unique_dates) - eval_offset
    start_idx = max(0, end_idx - eval_days)
    eval_dates = unique_dates[start_idx:end_idx]
    if not eval_dates:
        raise ValueError("No eval_dates selected after applying eval-days and eval-offset-days")
    rows: list[dict[str, Any]] = []
    for pred_date in eval_dates:
        rows.extend(
            _evaluate_single_date(
                ranked,
                pred_date=pd.Timestamp(pred_date),
                random_state=int(args.random_state),
                model_type=str(args.model_type),
                gpu_backend=str(args.gpu_backend),
                segment_mode=str(args.segment_mode),
                segment_blend_weight=float(args.segment_blend_weight),
                prior_blend_weight=float(args.prior_blend_weight),
                min_segment_days=int(args.min_segment_days),
                min_segment_rows=int(args.min_segment_rows),
                feature_whitelist=feature_whitelist,
                ltr_decay_lambda=float(args.ltr_decay_lambda),
                ltr_objective=str(args.ltr_objective),
                threshold_split_thursday=bool(getattr(args, "threshold_split_thursday", False)),
            )
        )
    if not rows:
        raise ValueError("No reliability rows generated")
    daily = pd.DataFrame(rows).sort_values(["date", "target"]).reset_index(drop=True)
    monthly = (
        daily.groupby(["month", "target", "is_thursday"], sort=True)
        .agg(
            precision=("precision", "mean"),
            recall=("recall", "mean"),
            f1=("f1", "mean"),
            hit_at_1=("hit_at_1", "mean"),
            hit_at_2=("hit_at_2", "mean"),
            hit_at_3=("hit_at_3", "mean"),
            hit_at_5=("hit_at_5", "mean"),
            predicted_count=("predicted_count", "mean"),
            base_rate=("base_rate", "mean"),
            truth_entity_count=("truth_entity_count", "mean"),
            known_entity_count=("known_entity_count", "mean"),
            unseen_entity_count=("unseen_entity_count", "mean"),
            known_coverage=("known_coverage", "mean"),
            skip_rate=("skip_rate", "mean"),
            n_days=("date", "nunique"),
            backend_used=("backend_used", lambda s: ",".join(sorted(set(map(str, s))))),
            segment_mode=("segment_mode", lambda s: ",".join(sorted(set(map(str, s))))),
            segment_blend_weight=("segment_blend_weight", "mean"),
            prior_blend_weight=("prior_blend_weight", "mean"),
            segment_models_used=("segment_models_used", "mean"),
            segment_prediction_rows=("segment_prediction_rows", "mean"),
        )
        .reset_index()
    )
    return daily, monthly


def _optimize_threshold_for_is_thursday(
    train_df: pd.DataFrame,
    *,
    target: str,
    use_thursday: int,
    fallback: float,
) -> float:
    subset = train_df.loc[train_df["is_thursday"].astype(int).eq(int(use_thursday))].copy()
    if subset.empty or subset[target].nunique() < 2:
        return float(fallback)
    y = subset[target].to_numpy(dtype=int)
    s = subset["score"].to_numpy(dtype=float)
    stats = common.optimize_binary_threshold(y, s)
    return float(stats["best_threshold"])


def _load_feature_whitelist(path: str) -> set[str] | None:
    raw = str(path or "").strip()
    if not raw:
        return None
    p = Path(raw)
    if not p.exists():
        raise FileNotFoundError(f"feature list file not found: {p}")
    cols = [line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not cols:
        return None
    return set(cols)


def main() -> int:
    args = build_parser().parse_args()
    daily, monthly = build_reliability_tables(args)
    prefix = Path(args.output_prefix)
    common.ensure_reports_dir()
    daily_path = prefix.with_name(prefix.name + "_daily.csv")
    monthly_path = prefix.with_name(prefix.name + "_monthly.csv")
    daily.to_csv(daily_path, index=False, encoding="utf-8-sig")
    monthly.to_csv(monthly_path, index=False, encoding="utf-8-sig")
    print(f"Saved: {daily_path}")
    print(f"Saved: {monthly_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
