from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from . import machine_type_common as common
from . import machine_type_monthly_check as monthly_check


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Feature importance and selection experiment for machine_type")
    p.add_argument("--db-path", default="", help="SQLite DB path. Empty means auto-detect db/*7.db")
    p.add_argument("--alpha", type=float, default=0.5)
    p.add_argument("--eval-days-tune", type=int, default=14)
    p.add_argument("--eval-days-final", type=int, default=30)
    p.add_argument("--model-type", choices=["sgd", "xgb"], default="sgd")
    p.add_argument("--gpu-backend", choices=["auto", "cpu", "cuda", "gpu_hist"], default="cpu")
    p.add_argument("--segment-mode", choices=["global", "floor2", "type2", "floor_type4"], default="floor2")
    p.add_argument("--segment-blend-weight", type=float, default=0.5)
    p.add_argument("--prior-blend-weight", type=float, default=0.0)
    p.add_argument("--min-segment-days", type=int, default=14)
    p.add_argument("--min-segment-rows", type=int, default=120)
    p.add_argument("--random-state", type=int, default=42)
    p.add_argument("--output-prefix", default="ml/machine_type/reports/machine_type_feature_select")
    return p


def run(args: argparse.Namespace) -> dict[str, object]:
    db_path = common.resolve_db_path(args.db_path)
    raw = common.load_daily_machine_type_summary(db_path)
    master = common.load_machine_master(db_path)
    seg_daily = common.load_machine_name_daily_segments(db_path)
    base = common.prepare_machine_type_base_frame(raw)
    base = common.attach_machine_master_flags(base, master)
    base = common.attach_daily_segments(base, seg_daily)
    ranked = common.add_shrunk_rank_targets(base, alpha=float(args.alpha))
    featured = common.add_machine_type_features(ranked)
    all_features = common.get_feature_columns(featured)

    importance_df = _compute_sgd_importance(
        featured_df=featured,
        feature_columns=all_features,
        eval_days_tune=int(args.eval_days_tune),
        random_state=int(args.random_state),
    )
    importance_df = importance_df.sort_values("mean_importance", ascending=False).reset_index(drop=True)

    out_prefix = Path(args.output_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    importance_path = out_prefix.with_name(out_prefix.name + "_importance.csv")
    importance_df.to_csv(importance_path, index=False, encoding="utf-8-sig")

    candidate_sets = _build_feature_candidates(importance_df["feature"].tolist())
    candidate_rows: list[dict[str, object]] = []
    keep_files: list[Path] = []
    for name, cols in candidate_sets:
        keep_path = out_prefix.with_name(f"{out_prefix.name}_keep_{name}.txt")
        keep_path.write_text("\n".join(cols) + "\n", encoding="utf-8")
        keep_files.append(keep_path)
        tune_daily, _ = monthly_check.build_reliability_tables(
            argparse.Namespace(
                db_path=str(db_path),
                alpha=float(args.alpha),
                model_type=str(args.model_type),
                gpu_backend=str(args.gpu_backend),
                segment_mode=str(args.segment_mode),
                segment_blend_weight=float(args.segment_blend_weight),
                prior_blend_weight=float(args.prior_blend_weight),
                min_segment_days=int(args.min_segment_days),
                min_segment_rows=int(args.min_segment_rows),
                eval_days=int(args.eval_days_tune),
                output_prefix="",
                feature_list_path=str(keep_path),
                random_state=int(args.random_state),
            )
        )
        score = _selection_score(tune_daily)
        candidate_rows.append(
            {
                "candidate": name,
                "feature_count": len(cols),
                "tune_score": score,
                "tune_mean_hit_at_3": float(
                    tune_daily[tune_daily["target"].isin(["is_top_2", "is_top_3", "is_top_5"])]["hit_at_3"].mean()
                ),
                "tune_mean_f1": float(
                    tune_daily[tune_daily["target"].isin(["is_top_2", "is_top_3", "is_top_5"])]["f1"].mean()
                ),
            }
        )

    candidate_df = pd.DataFrame(candidate_rows).sort_values("tune_score", ascending=False).reset_index(drop=True)
    candidate_path = out_prefix.with_name(out_prefix.name + "_candidates.csv")
    candidate_df.to_csv(candidate_path, index=False, encoding="utf-8-sig")

    best_name = str(candidate_df.iloc[0]["candidate"])
    best_keep = out_prefix.with_name(f"{out_prefix.name}_keep_{best_name}.txt")
    final_daily, final_monthly = monthly_check.build_reliability_tables(
        argparse.Namespace(
            db_path=str(db_path),
            alpha=float(args.alpha),
            model_type=str(args.model_type),
            gpu_backend=str(args.gpu_backend),
            segment_mode=str(args.segment_mode),
            segment_blend_weight=float(args.segment_blend_weight),
            prior_blend_weight=float(args.prior_blend_weight),
            min_segment_days=int(args.min_segment_days),
            min_segment_rows=int(args.min_segment_rows),
            eval_days=int(args.eval_days_final),
            output_prefix="",
            feature_list_path=str(best_keep),
            random_state=int(args.random_state),
        )
    )
    final_daily_path = out_prefix.with_name(out_prefix.name + "_best_final_daily.csv")
    final_monthly_path = out_prefix.with_name(out_prefix.name + "_best_final_monthly.csv")
    final_daily.to_csv(final_daily_path, index=False, encoding="utf-8-sig")
    final_monthly.to_csv(final_monthly_path, index=False, encoding="utf-8-sig")

    for p in keep_files:
        if p.name != best_keep.name:
            # keep only best list to avoid clutter
            p.unlink(missing_ok=True)

    summary = {
        "importance_path": str(importance_path),
        "candidate_path": str(candidate_path),
        "best_feature_list_path": str(best_keep),
        "best_candidate": best_name,
        "best_tune_score": float(candidate_df.iloc[0]["tune_score"]),
        "best_feature_count": int(candidate_df.iloc[0]["feature_count"]),
        "final_daily_path": str(final_daily_path),
        "final_monthly_path": str(final_monthly_path),
    }
    return summary


def _compute_sgd_importance(
    *,
    featured_df: pd.DataFrame,
    feature_columns: list[str],
    eval_days_tune: int,
    random_state: int,
) -> pd.DataFrame:
    unique_dates = sorted(pd.to_datetime(featured_df["date"].unique()))
    if len(unique_dates) <= eval_days_tune:
        cutoff = unique_dates[-1]
    else:
        cutoff = unique_dates[-eval_days_tune]
    train_df = featured_df.loc[featured_df["date"] < cutoff].copy()
    if train_df.empty:
        train_df = featured_df.copy()

    target_cols = ["is_top_2", "is_top_3", "is_top_5"]
    imp_map: dict[str, dict[str, float]] = {}
    for target in target_cols:
        model = common.train_target_model(
            train_df,
            target=target,
            feature_columns=feature_columns,
            random_state=random_state,
            model_type="sgd",
            gpu_backend="cpu",
        )
        coef = getattr(model.model, "coef_", None)
        if coef is None:
            vals = np.zeros(len(feature_columns), dtype=float)
        else:
            vals = np.abs(np.asarray(coef, dtype=float).reshape(-1))
        norm = float(np.sum(vals))
        if norm > 0:
            vals = vals / norm
        for f, v in zip(feature_columns, vals, strict=False):
            imp_map.setdefault(f, {})
            imp_map[f][target] = float(v)

    rows: list[dict[str, object]] = []
    for f in feature_columns:
        top2 = imp_map.get(f, {}).get("is_top_2", 0.0)
        top3 = imp_map.get(f, {}).get("is_top_3", 0.0)
        top5 = imp_map.get(f, {}).get("is_top_5", 0.0)
        rows.append(
            {
                "feature": f,
                "importance_top2": top2,
                "importance_top3": top3,
                "importance_top5": top5,
                "mean_importance": float((top2 + top3 + top5) / 3.0),
            }
        )
    return pd.DataFrame(rows)


def _build_feature_candidates(sorted_features: list[str]) -> list[tuple[str, list[str]]]:
    top20 = sorted_features[:20]
    top30 = sorted_features[:30]
    top40 = sorted_features[:40]
    forced = [
        "prior_top2_rate",
        "prior_top3_rate",
        "prior_top5_rate",
        "same_weekday_top2_rate",
        "same_weekday_top3_rate",
        "same_weekday_top5_rate",
        "days_since_last_top2",
        "days_since_last_top3",
        "days_since_last_top5",
        "count_delta_1d",
        "count_delta_3d",
        "count_delta_7d",
        "rolling_std_diff_7d",
        "rolling_std_efficiency_7d",
    ]
    top30_plus = list(dict.fromkeys(top30 + [f for f in forced if f in sorted_features]))
    return [
        ("all", sorted_features),
        ("top20", top20),
        ("top30", top30),
        ("top40", top40),
        ("top30_plus_forced", top30_plus),
    ]


def _selection_score(daily_df: pd.DataFrame) -> float:
    subset = daily_df[daily_df["target"].isin(["is_top_2", "is_top_3", "is_top_5"])].copy()
    return float((subset["hit_at_3"].mean() * 0.6) + (subset["f1"].mean() * 0.4))


def main() -> int:
    args = build_parser().parse_args()
    summary = run(args)
    print("Best candidate:", summary["best_candidate"])
    print("Best tune score:", summary["best_tune_score"])
    print("Feature count:", summary["best_feature_count"])
    print("Final daily:", summary["final_daily_path"])
    print("Final monthly:", summary["final_monthly_path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
