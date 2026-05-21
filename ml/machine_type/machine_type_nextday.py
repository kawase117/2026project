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
    parser.add_argument(
        "--output-prefix",
        default="ml/machine_type/reports/machine_type_nextday_prediction",
        help="Output prefix for prediction artifacts",
    )
    parser.add_argument("--random-state", type=int, default=42)
    return parser


def build_nextday_prediction(args: argparse.Namespace) -> dict[str, Any]:
    db_path = common.resolve_db_path(args.db_path)
    raw = common.load_daily_machine_type_summary(db_path)
    master = common.load_machine_master(db_path)
    base = common.prepare_machine_type_base_frame(raw)
    audit = common.build_audit_report(raw, prepared_df=base, machine_master_df=master)
    ranked = common.add_shrunk_rank_targets(base, alpha=args.alpha)
    with_placeholder, pred_date = common.add_nextday_placeholder_rows(ranked)
    featured = common.add_machine_type_features(with_placeholder)

    train_df = featured.loc[featured["date"] < pred_date].copy()
    pred_df = featured.loc[featured["date"] == pred_date].copy()
    if train_df.empty or pred_df.empty:
        raise ValueError("Not enough data to train/predict next day")

    feature_columns = common.get_feature_columns(featured)
    models = {
        target: common.train_target_model(
            train_df,
            target=target,
            feature_columns=feature_columns,
            random_state=int(args.random_state),
        )
        for target in common.TARGET_COLUMNS
    }

    X_pred = pred_df[feature_columns].fillna(0.0).to_numpy(dtype=float)
    for target, trained in models.items():
        pred_df[f"proba_{target}"] = common.predict_proba(trained.model, X_pred)
        pred_df[f"threshold_{target}"] = trained.threshold

    pred_df["ensemble_score"] = (
        pred_df["proba_is_rank_1"] * 1.0
        + pred_df["proba_is_top_2"] * 0.8
        + pred_df["proba_is_top_3"] * 0.6
        + pred_df["proba_is_top_5"] * 0.4
    )
    pred_df["nextday_rank"] = pred_df["ensemble_score"].rank(method="first", ascending=False).astype(int)

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

    summary = {
        "db_path": str(db_path),
        "prediction_date": str(pred_date.date()),
        "alpha": float(args.alpha),
        "random_state": int(args.random_state),
        "feature_count": int(len(feature_columns)),
        "target_thresholds": {target: float(model.threshold) for target, model in models.items()},
        "audit_report": audit,
        "top10_machine_names": pred_df.head(10)["machine_name"].astype(str).tolist(),
    }

    return {"summary": summary, "predictions": pred_df}


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

