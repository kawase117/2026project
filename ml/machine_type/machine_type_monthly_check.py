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
    parser.add_argument(
        "--eval-days",
        type=int,
        default=60,
        help="Number of most-recent historical dates to evaluate with expanding train windows",
    )
    parser.add_argument(
        "--output-prefix",
        default="ml/machine_type/reports/machine_type_reliability",
        help="Output prefix for reliability artifacts",
    )
    parser.add_argument("--random-state", type=int, default=42)
    return parser


def _evaluate_single_date(
    featured_df: pd.DataFrame,
    *,
    pred_date: pd.Timestamp,
    random_state: int,
) -> list[dict[str, Any]]:
    train_df = featured_df.loc[featured_df["date"] < pred_date].copy()
    day_df = featured_df.loc[featured_df["date"] == pred_date].copy()
    if train_df.empty or day_df.empty:
        return []
    feature_columns = common.get_feature_columns(featured_df)
    rows: list[dict[str, Any]] = []
    for target in common.TARGET_COLUMNS:
        trained = common.train_target_model(
            train_df,
            target=target,
            feature_columns=feature_columns,
            random_state=random_state,
        )
        proba = common.predict_proba(
            trained.model,
            day_df[trained.feature_columns].fillna(0.0).to_numpy(dtype=float),
        )
        score_col = f"score_{target}"
        work = day_df.copy()
        work[score_col] = proba
        metrics = common.evaluate_prediction_day(
            work,
            target=target,
            score_col=score_col,
            threshold=trained.threshold,
        )
        metrics.update(
            {
                "date": pred_date.strftime("%Y-%m-%d"),
                "month": pred_date.strftime("%Y-%m"),
                "day_of_week": pred_date.day_name(),
                "is_thursday": int(pred_date.dayofweek == 3),
                "threshold": float(trained.threshold),
                "entity_count": int(len(day_df)),
                "skip_rate": float(0.0),
            }
        )
        rows.append(metrics)
    return rows


def build_reliability_tables(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame]:
    db_path = common.resolve_db_path(args.db_path)
    raw = common.load_daily_machine_type_summary(db_path)
    base = common.prepare_machine_type_base_frame(raw)
    ranked = common.add_shrunk_rank_targets(base, alpha=args.alpha)
    featured = common.add_machine_type_features(ranked)
    unique_dates = sorted(pd.to_datetime(featured["date"].unique()))
    if len(unique_dates) < 2:
        raise ValueError("Not enough dates for reliability check")
    eval_dates = unique_dates[-max(int(args.eval_days), 1):]
    rows: list[dict[str, Any]] = []
    for pred_date in eval_dates:
        rows.extend(
            _evaluate_single_date(
                featured,
                pred_date=pd.Timestamp(pred_date),
                random_state=int(args.random_state),
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
            skip_rate=("skip_rate", "mean"),
            n_days=("date", "nunique"),
        )
        .reset_index()
    )
    return daily, monthly


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

