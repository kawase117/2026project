from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

from ml.last_digit.utils import resolve_db_path
from ml.prediction.corner_rank_prediction_by_section import build_walk_forward_folds
from ml.prediction.individual_machine_diff_prediction import (
    _compute_metrics,
    _fit_catboost_model,
    _prepare_model_frame,
    build_feature_columns,
    build_machine_feature_frame,
    load_raw_machine_rows,
    print_section,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = ROOT / "data" / "individual_machine_diff_prediction_by_section_final"
DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MIN_GAMES = 100
FINAL_NOTES = "baseline-only (36 features)"


@dataclass(frozen=True)
class SectionFoldResult:
    section: str
    fold_id: int
    predictions: pd.DataFrame


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train section-specific individual-machine diff models without corner features."
    )
    parser.add_argument("--db-path", default="db/縺ｿ縺ｨ繧・､ｧ譽ｮ逕ｺ蠎・db", help="Path to the SQLite DB.")
    parser.add_argument(
        "--db-glob",
        default="*縺ｿ縺ｨ繧・､ｧ譽ｮ逕ｺ蠎・.db",
        help="Glob used when --db-path is missing or unavailable.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/individual_machine_diff_prediction_by_section_final",
        help="Directory for validation and metrics outputs.",
    )
    parser.add_argument("--train-days", type=int, default=72, help="Walk-forward training window.")
    parser.add_argument("--val-days", type=int, default=30, help="Walk-forward validation window.")
    parser.add_argument("--step-days", type=int, default=30, help="Walk-forward step size.")
    parser.add_argument("--min-games", type=int, default=MIN_GAMES, help="Minimum games per raw row.")
    parser.add_argument(
        "--include-non-xday",
        dest="xday_only",
        action="store_false",
        help="Use all days instead of x_day only.",
    )
    parser.set_defaults(xday_only=True)
    parser.add_argument("--task-type", default="GPU", choices=["GPU", "CPU"], help="CatBoost task type.")
    parser.add_argument("--devices", default="0", help="CatBoost device string.")
    parser.add_argument("--section-filter", default="", help="Comma-separated section filter.")
    return parser


def build_section_feature_columns() -> list[str]:
    return build_feature_columns(include_corner=False)


def _build_section_dataset(
    db_path: Path,
    *,
    min_games: int,
    xday_only: bool,
    section_filter: Iterable[str] | None = None,
) -> pd.DataFrame:
    raw = load_raw_machine_rows(db_path, min_games=min_games)
    if raw.empty:
        return pd.DataFrame()

    machine_frame = build_machine_feature_frame(raw)
    if xday_only:
        machine_frame = machine_frame[machine_frame["is_xday"].eq(1)].copy()

    if section_filter:
        section_filter_set = {str(value).strip() for value in section_filter if str(value).strip()}
        machine_frame = machine_frame[machine_frame["section"].isin(section_filter_set)].copy()

    return machine_frame.reset_index(drop=True)


def _run_section_fold(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    *,
    section: str,
    fold_id: int,
    task_type: str,
    devices: str,
) -> SectionFoldResult | None:
    features = build_section_feature_columns()

    if train_df.empty or val_df.empty:
        return None
    if train_df["target_diff_positive"].nunique(dropna=True) < 2:
        return None

    model, _, _ = _fit_catboost_model(
        train_df,
        val_df,
        features=features,
        task_type=task_type,
        devices=devices,
    )
    val_frame = _prepare_model_frame(val_df, features)

    out = val_df.copy()
    out["pred_diff_positive"] = model.predict_proba(val_frame[features])[:, 1]
    out["fold_id"] = fold_id
    out["section_model_id"] = f"{section}_fold{fold_id}"
    return SectionFoldResult(section=section, fold_id=fold_id, predictions=out)


def _compute_section_metrics(frame: pd.DataFrame) -> dict[str, float]:
    metrics = _compute_metrics(frame, prob_column="pred_diff_positive")
    return {
        "auc": metrics["auc"],
        "precision": metrics["precision"],
        "recall": metrics["recall"],
        "f1": metrics["f1"],
        "n_rows": metrics["n_validation_rows"],
        "n_dates": metrics["n_validation_dates"],
    }


def summarize_section_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame(
            columns=["section", "auc", "precision", "recall", "f1", "n_machines", "n_rows", "n_dates", "notes"]
        )

    rows: list[dict[str, object]] = []
    section_metrics: list[dict[str, object]] = []
    for section, grp in predictions.groupby("section", sort=True):
        metrics = _compute_section_metrics(grp)
        n_machines = int(grp["machine_number"].nunique()) if "machine_number" in grp.columns else 0
        n_rows = int(len(grp))
        row = {
            "section": section,
            "auc": metrics["auc"],
            "precision": metrics["precision"],
            "recall": metrics["recall"],
            "f1": metrics["f1"],
            "n_machines": n_machines,
            "n_rows": n_rows,
            "n_dates": metrics["n_dates"],
            "notes": FINAL_NOTES,
        }
        rows.append(row)
        section_metrics.append(row)

    overall_metrics = _compute_section_metrics(predictions)
    rows.append(
        {
            "section": "ALL",
            "auc": float(pd.Series([row["auc"] for row in section_metrics], dtype="float64").mean()),
            "precision": overall_metrics["precision"],
            "recall": overall_metrics["recall"],
            "f1": overall_metrics["f1"],
            "n_machines": int(predictions["machine_number"].nunique()) if "machine_number" in predictions.columns else 0,
            "n_rows": int(len(predictions)),
            "n_dates": int(predictions["date"].nunique()),
            "notes": "overall summary",
        }
    )

    return pd.DataFrame(rows).sort_values(["section"], ascending=[True]).reset_index(drop=True)


def run_pipeline(
    db_path: Path,
    *,
    output_dir: Path,
    train_days: int,
    val_days: int,
    step_days: int,
    min_games: int,
    xday_only: bool,
    task_type: str,
    devices: str,
    section_filter: Iterable[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    dataset = _build_section_dataset(
        db_path,
        min_games=min_games,
        xday_only=xday_only,
        section_filter=section_filter,
    )
    if dataset.empty:
        return pd.DataFrame(), pd.DataFrame()

    fold_results: list[SectionFoldResult] = []
    for section, section_df in dataset.groupby("section", sort=True):
        dates = tuple(pd.to_datetime(section_df["date"], errors="coerce").dropna().sort_values().unique())
        folds = build_walk_forward_folds(dates, train_days=train_days, val_days=val_days, step_days=step_days)
        for fold in folds:
            train_df = section_df[section_df["date"].isin(fold.train_dates)].copy()
            val_df = section_df[section_df["date"].isin(fold.val_dates)].copy()
            result = _run_section_fold(
                train_df,
                val_df,
                section=section,
                fold_id=fold.fold_id,
                task_type=task_type,
                devices=devices,
            )
            if result is not None and not result.predictions.empty:
                fold_results.append(result)

    if fold_results:
        pred_df = pd.concat([result.predictions for result in fold_results], ignore_index=True)
        pred_df["date"] = pd.to_datetime(pred_df["date"], errors="coerce").dt.strftime("%Y%m%d")
        pred_df = pred_df[
            [
                "date",
                "machine_number",
                "section",
                "last_digit",
                "target_diff_positive",
                "pred_diff_positive",
                "fold_id",
            ]
        ].sort_values(["section", "date", "machine_number", "fold_id"]).reset_index(drop=True)
    else:
        pred_df = pd.DataFrame()

    metrics_df = summarize_section_metrics(pred_df)

    output_dir.mkdir(parents=True, exist_ok=True)
    pred_df.to_csv(output_dir / "individual_machine_diff_prediction_by_section_final_validation.csv", index=False)
    metrics_df.to_csv(output_dir / "individual_machine_diff_prediction_by_section_final_metrics.csv", index=False)
    return pred_df, metrics_df


def summarize_section_groups(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["section", "n_machines", "machine_type_counts"])

    rows = []
    for section, grp in frame.groupby("section", sort=True):
        rows.append(
            {
                "section": section,
                "n_machines": int(grp["machine_number"].nunique()),
                "machine_type_counts": grp["machine_type"].value_counts().to_dict() if "machine_type" in grp.columns else {},
            }
        )
    return pd.DataFrame(rows).sort_values(["section"], ascending=[True]).reset_index(drop=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    section_filter = [value.strip() for value in args.section_filter.split(",") if value.strip()]
    db_path = resolve_db_path(str(args.db_path), pattern=str(args.db_glob))
    output_dir = Path(args.output_dir)

    print_section("1. Load and prepare dataset")
    print(f"  db_path: {db_path}")
    print(f"  xday_only: {args.xday_only}")
    print(f"  train_days: {args.train_days} / val_days: {args.val_days} / step_days: {args.step_days}")

    dataset = _build_section_dataset(
        db_path,
        min_games=args.min_games,
        xday_only=args.xday_only,
        section_filter=section_filter,
    )
    section_summary = summarize_section_groups(dataset)
    if section_summary.empty:
        print("  No section summary available.")
    else:
        print(section_summary.to_string(index=False))

    pred_df, metrics_df = run_pipeline(
        db_path,
        output_dir=output_dir,
        train_days=args.train_days,
        val_days=args.val_days,
        step_days=args.step_days,
        min_games=args.min_games,
        xday_only=args.xday_only,
        task_type=args.task_type,
        devices=args.devices,
        section_filter=section_filter,
    )

    print_section("2. Validation metrics")
    if metrics_df.empty:
        print("  No validation metrics produced.")
    else:
        print(metrics_df.to_string(index=False))

    print_section("3. Output")
    if pred_df.empty:
        print("  No validation predictions produced.")
    else:
        print(f"  rows: {len(pred_df):,}")
        print(f"  validation csv: {output_dir / 'individual_machine_diff_prediction_by_section_final_validation.csv'}")
        print(f"  metrics csv: {output_dir / 'individual_machine_diff_prediction_by_section_final_metrics.csv'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
