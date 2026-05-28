from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import machine_type_common as common


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Next-day machine-type prediction")
    parser.add_argument("--db-path", default="", help="SQLite DB path. Empty means auto-detect db/*7.db")
    parser.add_argument("--alpha", type=float, default=5.0, help="Shrinkage alpha for rank label generation")
    parser.add_argument("--model-type", choices=["sgd", "xgb"], default="xgb", help="Model type per target")
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
    parser.add_argument("--min-segment-days", type=int, default=21, help="Minimum unique dates per segment model")
    parser.add_argument("--min-segment-rows", type=int, default=300, help="Minimum rows per segment model")
    parser.add_argument("--recommend-k", type=int, default=3, help="Number of recommended picks to mark")
    parser.add_argument(
        "--enforce-floor-diversity",
        action="store_true",
        help="If enabled, force at least one recommendation from 2F and 3F when possible",
    )
    parser.add_argument(
        "--min-confidence-margin",
        type=float,
        default=0.0,
        help="If top1-top2 ensemble score margin is below this value, summary marks skip_suggested=1",
    )
    parser.add_argument(
        "--prior-blend-weight",
        type=float,
        default=0.0,
        help="Blend model probability with prior target rate features (0.0=model only, 1.0=prior only)",
    )
    parser.add_argument(
        "--output-prefix",
        default="ml/machine_type/reports/machine_type_nextday_prediction",
        help="Output prefix for prediction artifacts",
    )
    parser.add_argument(
        "--feature-list-path",
        default="",
        help="Optional path to newline-separated feature names to whitelist",
    )
    parser.add_argument("--random-state", type=int, default=42)
    return parser


def build_nextday_prediction(args: argparse.Namespace) -> dict[str, Any]:
    db_path = common.resolve_db_path(args.db_path)
    raw = common.load_daily_machine_type_summary(db_path)
    master = common.load_machine_master(db_path)
    segment_daily = common.load_machine_name_daily_segments(db_path)
    base = common.prepare_machine_type_base_frame(raw)
    base = common.attach_machine_master_flags(base, master)
    base = common.attach_daily_segments(base, segment_daily)
    audit = common.build_audit_report(raw, prepared_df=base, machine_master_df=master)
    ranked = common.add_shrunk_rank_targets(base, alpha=args.alpha)
    with_placeholder, pred_date = common.add_nextday_placeholder_rows(ranked)
    featured = common.add_machine_type_features(with_placeholder)

    train_df = featured.loc[featured["date"] < pred_date].copy()
    pred_df = featured.loc[featured["date"] == pred_date].copy()
    if train_df.empty or pred_df.empty:
        raise ValueError("Not enough data to train/predict next day")

    feature_columns = common.get_feature_columns(featured)
    feature_whitelist = _load_feature_whitelist(args.feature_list_path)
    if feature_whitelist is not None:
        filtered = [c for c in feature_columns if c in feature_whitelist]
        if filtered:
            feature_columns = filtered
    models = {
        target: common.train_segmented_target_models(
            train_df,
            target=target,
            feature_columns=feature_columns,
            random_state=int(args.random_state),
            model_type=str(args.model_type),
            gpu_backend=str(args.gpu_backend),
            segment_mode=str(args.segment_mode),
            min_segment_days=int(args.min_segment_days),
            min_segment_rows=int(args.min_segment_rows),
        )
        for target in common.TARGET_COLUMNS
    }

    segment_usage: dict[str, int] = {}
    for target, trained in models.items():
        proba, used_segment = common.predict_segmented_proba(
            pred_df,
            trained=trained,
            segment_blend_weight=float(args.segment_blend_weight),
        )
        proba = common.blend_with_prior_rate(
            pred_df,
            target=target,
            proba=proba,
            prior_blend_weight=float(args.prior_blend_weight),
        )
        pred_df[f"proba_{target}"] = proba
        pred_df[f"threshold_{target}"] = trained.global_model.threshold
        segment_usage[target] = int(used_segment.sum())

    pred_df["ensemble_score"] = (
        pred_df["proba_is_rank_1"] * 1.0
        + pred_df["proba_is_top_2"] * 0.8
        + pred_df["proba_is_top_3"] * 0.6
        + pred_df["proba_is_top_5"] * 0.4
    )
    pred_df["nextday_rank"] = pred_df["ensemble_score"].rank(method="first", ascending=False).astype(int)
    pred_df["recommended_pick"] = 0
    pred_df["recommended_pick_rank"] = 0

    reference = (
        ranked.sort_values(["machine_name", "date"])
        .groupby("machine_name", sort=False)
        .tail(1)[["machine_name", "raw_avg_rank", "shrunk_rank", "avg_diff_coins", "shrunk_avg_diff"]]
        .rename(
            columns={
                "raw_avg_rank": "previous_day_raw_avg_rank",
                "shrunk_rank": "previous_day_shrunk_rank",
                "avg_diff_coins": "previous_day_avg_diff_coins",
                "shrunk_avg_diff": "previous_day_shrunk_avg_diff",
            }
        )
    )
    pred_df = pred_df.merge(reference, on="machine_name", how="left")
    pred_df = pred_df.sort_values(["nextday_rank", "machine_name"]).reset_index(drop=True)
    top1 = float(pred_df.iloc[0]["ensemble_score"]) if len(pred_df) >= 1 else 0.0
    top2 = float(pred_df.iloc[1]["ensemble_score"]) if len(pred_df) >= 2 else top1
    confidence_margin = float(top1 - top2)
    skip_suggested = int(confidence_margin < float(args.min_confidence_margin))

    selected_idx = _select_recommended_indices(
        pred_df,
        k=max(int(args.recommend_k), 1),
        enforce_floor_diversity=bool(args.enforce_floor_diversity),
    )
    for rank_idx, ridx in enumerate(selected_idx, start=1):
        pred_df.loc[ridx, "recommended_pick"] = 1
        pred_df.loc[ridx, "recommended_pick_rank"] = rank_idx

    summary = {
        "db_path": str(db_path),
        "prediction_date": str(pred_date.date()),
        "alpha": float(args.alpha),
        "random_state": int(args.random_state),
        "model_type": str(args.model_type),
        "gpu_backend": str(args.gpu_backend),
        "segment_mode": str(args.segment_mode),
        "segment_blend_weight": float(args.segment_blend_weight),
        "prior_blend_weight": float(args.prior_blend_weight),
        "min_segment_days": int(args.min_segment_days),
        "min_segment_rows": int(args.min_segment_rows),
        "backend_used_by_target": {target: model.global_model.backend_used for target, model in models.items()},
        "segment_models_by_target": {target: int(len(model.segment_models)) for target, model in models.items()},
        "segment_prediction_rows_by_target": segment_usage,
        "recommend_k": int(max(int(args.recommend_k), 1)),
        "enforce_floor_diversity": bool(args.enforce_floor_diversity),
        "min_confidence_margin": float(args.min_confidence_margin),
        "confidence_margin_top1_top2": confidence_margin,
        "skip_suggested": skip_suggested,
        "feature_count": int(len(feature_columns)),
        "target_thresholds": {target: float(model.global_model.threshold) for target, model in models.items()},
        "audit_report": audit,
        "top10_machine_names": pred_df.head(10)["machine_name"].astype(str).tolist(),
        "recommended_machine_names": pred_df.loc[pred_df["recommended_pick"].eq(1), "machine_name"].astype(str).tolist(),
    }

    return {"summary": summary, "predictions": pred_df}


def _select_recommended_indices(df: pd.DataFrame, *, k: int, enforce_floor_diversity: bool) -> list[int]:
    ranked = df.sort_values("nextday_rank").copy()
    if ranked.empty:
        return []
    if not enforce_floor_diversity or "segment_floor2" not in ranked.columns:
        return ranked.head(k).index.tolist()
    selected: list[int] = []
    used: set[int] = set()
    for floor in ("2F", "3F"):
        sub = ranked.loc[ranked["segment_floor2"].astype(str).eq(floor)]
        if sub.empty:
            continue
        idx = int(sub.iloc[0].name)
        if idx not in used:
            selected.append(idx)
            used.add(idx)
    for idx in ranked.index.tolist():
        if len(selected) >= k:
            break
        if int(idx) in used:
            continue
        selected.append(int(idx))
        used.add(int(idx))
    return selected[:k]


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
    payload = build_nextday_prediction(args)
    prefix = Path(args.output_prefix)
    common.ensure_reports_dir()
    pred_df = payload["predictions"]
    summary = payload["summary"]

    json_path = prefix.with_suffix(".json")
    csv_path = prefix.with_suffix(".csv")
    audit_path = prefix.with_name(prefix.name + "_audit_report.json")
    pred_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    common.write_json_report(json_path, summary)
    common.write_json_report(audit_path, summary["audit_report"])
    print(f"Saved: {csv_path}")
    print(f"Saved: {json_path}")
    print(f"Saved: {audit_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
