from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score

from ml.last_digit.utils import resolve_db_path
from ml.prediction.corner_rank_prediction_by_section import WalkForwardFold, build_walk_forward_folds


try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = ROOT / "data" / "individual_machine_diff_prediction"
DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MIN_GAMES = 100
NEW_MANAGER_DATE = pd.Timestamp("2026-05-01")
CORNER_FEATURE = "pred_corner_top_prob"

CATBOOST_PARAMS = {
    "iterations": 500,
    "learning_rate": 0.05,
    "depth": 6,
    "loss_function": "Logloss",
    "eval_metric": "AUC",
    "task_type": "GPU",
    "devices": "0",
    "random_seed": 42,
    "verbose": 50,
    "early_stopping_rounds": 50,
    "class_weights": [1.0, 1.2],
    "allow_writing_files": False,
}

BASE_FEATURES = [
    "dd",
    "weekday_num",
    "month",
    "week_of_year",
    "is_sunday",
    "is_weekend",
    "is_dd7",
    "dd_mod5",
    "dd_mod10",
    "last_digit_num",
    "x",
    "y",
    "rank_from_min",
    "rank_from_max",
    "rank_from_aisle",
    "is_corner",
    "is_far_corner",
    "is_near_corner",
    "is_reversed_section",
    "position_ratio",
    "is_new_manager",
    "jug_flag",
    "hana_flag",
    "oki_flag",
    "bt_flag",
    "machine_roll7_diff",
    "machine_roll30_diff",
    "seat_roll7_diff",
    "seat_roll30_diff",
    "model_weekday_roll",
    "seat_dd_roll",
    "machine_avg_diff_wf",
    "machine_plus_rate_wf",
    "machine_sample_n_wf",
    "machine_xday_avg_wf",
    "games_normalized",
]


@dataclass(frozen=True)
class FoldResult:
    fold_id: int
    predictions: pd.DataFrame
    feature_importance: pd.DataFrame


def print_section(title: str) -> None:
    print(f"\n{'=' * 80}")
    print(f"  {title}")
    print(f"{'=' * 80}")


def _table_exists(con: sqlite3.Connection, table_name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _derive_machine_type(row: pd.Series) -> str:
    if int(row.get("jug_flag", 0) or 0) == 1:
        return "jug"
    if int(row.get("hana_flag", 0) or 0) == 1:
        return "hana"
    if int(row.get("oki_flag", 0) or 0) == 1:
        return "oki"
    if int(row.get("bt_flag", 0) or 0) == 1:
        return "bt"
    return "other"


def _normalize_section_label(
    section: object,
    section_min: object = None,
    section_max: object = None,
    machine_number: object = None,
) -> str:
    section_text = "" if pd.isna(section) else str(section).strip()
    if section_text and section_text.lower() != "unknown":
        return section_text
    if not pd.isna(section_min) and not pd.isna(section_max):
        return f"{int(section_min)}-{int(section_max)}"
    if pd.isna(machine_number):
        return "unknown"
    return f"{int(machine_number)}-{int(machine_number)}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare individual-machine diff models with and without corner features.")
    parser.add_argument("--db-path", default="db/みとや大森町店.db", help="Path to the SQLite DB.")
    parser.add_argument(
        "--db-glob",
        default="*みとや大森町店*.db",
        help="Glob used when --db-path is missing or unavailable.",
    )
    parser.add_argument(
        "--corner-pred-dir",
        default="data/corner_rank_prediction_by_section",
        help="Directory containing precomputed corner predictions.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/individual_machine_diff_prediction",
        help="Directory for validation, metrics, and feature importance outputs.",
    )
    parser.add_argument("--train-days", type=int, default=72, help="Walk-forward training window.")
    parser.add_argument("--val-days", type=int, default=30, help="Walk-forward validation window.")
    parser.add_argument("--step-days", type=int, default=30, help="Walk-forward step size.")
    parser.add_argument("--min-games", type=int, default=MIN_GAMES, help="Minimum games per raw row.")
    parser.add_argument("--include-non-xday", dest="xday_only", action="store_false", help="Use all days instead of x_day only.")
    parser.set_defaults(xday_only=True)
    parser.add_argument("--task-type", default="GPU", choices=["GPU", "CPU"], help="CatBoost task type.")
    parser.add_argument("--devices", default="0", help="CatBoost device string.")
    parser.add_argument("--section-filter", default="", help="Comma-separated section filter.")
    return parser


def build_feature_columns(*, include_corner: bool = False) -> list[str]:
    features = list(BASE_FEATURES)
    if include_corner:
        features.append(CORNER_FEATURE)
    return features


def _empty_machine_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "date",
            "machine_number",
            "machine_name",
            "last_digit",
            "games_normalized",
            "diff_coins_normalized",
            "section",
            "x",
            "y",
            "rank_from_min",
            "rank_from_max",
            "rank_from_aisle",
            "is_reversed_section",
            "jug_flag",
            "hana_flag",
            "oki_flag",
            "bt_flag",
            "machine_type",
        ]
    )


def load_raw_machine_rows(db_path: Path, min_games: int = MIN_GAMES) -> pd.DataFrame:
    with sqlite3.connect(str(db_path)) as con:
        raw = pd.read_sql_query(
            """
            SELECT
              m.date,
              m.machine_number,
              m.machine_name,
              m.last_digit,
              m.games_normalized,
              m.diff_coins_normalized
            FROM machine_detailed_results m
            ORDER BY m.date, m.machine_number
            """,
            con,
        )
        layout = (
            pd.read_sql_query("SELECT * FROM machine_layout", con)
            if _table_exists(con, "machine_layout")
            else pd.DataFrame()
        )
        master = (
            pd.read_sql_query("SELECT * FROM machine_master", con)
            if _table_exists(con, "machine_master")
            else pd.DataFrame()
        )

    if raw.empty:
        return _empty_machine_frame()

    work = raw.copy()
    work["date"] = pd.to_datetime(work["date"].astype(str), errors="coerce")
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work["last_digit"] = work["last_digit"].astype(str).str.strip()
    work = work.dropna(
        subset=["date", "machine_number", "machine_name", "games_normalized", "diff_coins_normalized"]
    ).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work = work[work["games_normalized"] >= int(min_games)].copy()
    work = work[work["last_digit"].str.fullmatch(r"[0-9]")].copy()

    if not layout.empty:
        layout = layout.copy()
        if "machine_number" in layout.columns:
            layout["machine_number"] = pd.to_numeric(layout["machine_number"], errors="coerce")
        for col in ["x", "y", "section_min", "section_max", "rank_from_min", "rank_from_max", "rank_from_aisle"]:
            if col in layout.columns:
                layout[col] = pd.to_numeric(layout[col], errors="coerce")
        if "is_reversed_section" in layout.columns:
            layout["is_reversed_section"] = pd.to_numeric(layout["is_reversed_section"], errors="coerce").fillna(0).astype(int)
        else:
            layout["is_reversed_section"] = 0
        work = work.merge(layout, on="machine_number", how="left")
    else:
        for col in ["x", "y", "section", "section_min", "section_max", "rank_from_min", "rank_from_max", "rank_from_aisle"]:
            work[col] = np.nan
        work["is_reversed_section"] = 0

    if not master.empty:
        master = master.copy()
        if "machine_name_normalized" in master.columns:
            master = master.rename(columns={"machine_name_normalized": "machine_name"})
        work = work.merge(master, on="machine_name", how="left")
    else:
        for col in ["jug_flag", "hana_flag", "oki_flag", "bt_flag"]:
            work[col] = 0

    for col in ["jug_flag", "hana_flag", "oki_flag", "bt_flag"]:
        if col not in work.columns:
            work[col] = 0
        work[col] = pd.to_numeric(work[col], errors="coerce").fillna(0).astype(int)

    if "section" not in work.columns:
        work["section"] = np.nan
    work["section"] = work.apply(
        lambda row: _normalize_section_label(
            row.get("section"),
            row.get("section_min"),
            row.get("section_max"),
            row.get("machine_number"),
        ),
        axis=1,
    )
    work["machine_type"] = work.apply(_derive_machine_type, axis=1)
    work = work[work["section"].ne("unknown")].copy()
    return work.reset_index(drop=True)


def build_machine_feature_frame(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=["date", "machine_number", "section", "target_diff_positive", *BASE_FEATURES])

    work = raw.copy()
    work["date"] = pd.to_datetime(work["date"].astype(str), errors="coerce").dt.normalize()
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work["last_digit"] = work["last_digit"].astype(str).str.strip()
    work = work.dropna(
        subset=["date", "machine_number", "machine_name", "games_normalized", "diff_coins_normalized", "section"]
    ).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work["date"] = work["date"].dt.normalize()
    work["last_digit_num"] = pd.to_numeric(work["last_digit"], errors="coerce").fillna(-1).astype(int)

    work["dd"] = work["date"].dt.day.astype(int)
    work["weekday_num"] = work["date"].dt.dayofweek.astype(int)
    work["month"] = work["date"].dt.month.astype(int)
    work["week_of_year"] = work["date"].dt.isocalendar().week.astype(int)
    work["is_sunday"] = (work["weekday_num"] == 6).astype(int)
    work["is_weekend"] = (work["weekday_num"] >= 5).astype(int)
    work["is_dd7"] = (work["dd"] == 7).astype(int)
    work["dd_mod5"] = work["dd"] % 5
    work["dd_mod10"] = work["dd"] % 10
    work["is_xday"] = work["dd_mod10"].isin([4, 7]).astype(int)
    work["is_new_manager"] = (work["date"] >= NEW_MANAGER_DATE).astype(int)

    work = work.sort_values(["machine_name", "date", "machine_number"]).reset_index(drop=True)
    work["machine_roll7_diff"] = work.groupby("machine_name")["diff_coins_normalized"].transform(
        lambda s: s.shift(1).rolling(7, min_periods=1).mean()
    )
    work["machine_roll30_diff"] = work.groupby("machine_name")["diff_coins_normalized"].transform(
        lambda s: s.shift(1).rolling(30, min_periods=5).mean()
    )

    work = work.sort_values(["machine_number", "date"]).reset_index(drop=True)
    work["seat_roll7_diff"] = work.groupby("machine_number")["diff_coins_normalized"].transform(
        lambda s: s.shift(1).rolling(7, min_periods=1).mean()
    )
    work["seat_roll30_diff"] = work.groupby("machine_number")["diff_coins_normalized"].transform(
        lambda s: s.shift(1).rolling(30, min_periods=5).mean()
    )

    work = work.sort_values(["machine_name", "weekday_num", "date"]).reset_index(drop=True)
    work["model_weekday_roll"] = work.groupby(["machine_name", "weekday_num"])["diff_coins_normalized"].transform(
        lambda s: s.shift(1).expanding(min_periods=1).mean()
    )

    work = work.sort_values(["machine_number", "dd", "date"]).reset_index(drop=True)
    work["seat_dd_roll"] = work.groupby(["machine_number", "dd"])["diff_coins_normalized"].transform(
        lambda s: s.shift(1).expanding(min_periods=1).mean()
    )

    work = work.sort_values(["machine_name", "date"]).reset_index(drop=True)
    work["machine_avg_diff_wf"] = work.groupby("machine_name")["diff_coins_normalized"].transform(
        lambda s: s.shift(1).expanding(min_periods=1).mean()
    )
    work["machine_plus_rate_wf"] = work.groupby("machine_name")["diff_coins_normalized"].transform(
        lambda s: (s.shift(1) > 0).expanding(min_periods=1).mean()
    )
    work["machine_sample_n_wf"] = work.groupby("machine_name")["diff_coins_normalized"].transform(
        lambda s: s.shift(1).expanding(min_periods=1).count()
    )

    xday_machine = work[work["is_xday"].eq(1)].sort_values(["machine_name", "date"]).copy()
    if not xday_machine.empty:
        xday_machine["machine_xday_avg_wf"] = xday_machine.groupby("machine_name")["diff_coins_normalized"].transform(
            lambda s: s.shift(1).expanding(min_periods=1).mean()
        )
        work = work.merge(
            xday_machine[["date", "machine_number", "machine_xday_avg_wf"]],
            on=["date", "machine_number"],
            how="left",
        )
    else:
        work["machine_xday_avg_wf"] = np.nan

    work = work.sort_values(["machine_name", "date", "machine_number"]).reset_index(drop=True)
    work["machine_xday_avg_wf"] = work.groupby("machine_name")["machine_xday_avg_wf"].transform(lambda s: s.ffill())
    work["is_corner"] = (pd.to_numeric(work["rank_from_aisle"], errors="coerce").fillna(0).astype(int) == 1).astype(int)
    section_max_aisle = work.groupby("section")["rank_from_aisle"].transform("max")
    work["is_far_corner"] = (pd.to_numeric(work["rank_from_aisle"], errors="coerce").fillna(0).astype(int) == section_max_aisle.fillna(0).astype(int)).astype(int)
    work["is_near_corner"] = (pd.to_numeric(work["rank_from_aisle"], errors="coerce").fillna(0).astype(int) <= 2).astype(int)
    work["position_ratio"] = (
        pd.to_numeric(work["rank_from_min"], errors="coerce") / pd.to_numeric(work["rank_from_max"], errors="coerce").replace(0, np.nan)
    ).fillna(0.0)

    work["target_diff_positive"] = (pd.to_numeric(work["diff_coins_normalized"], errors="coerce") >= 0).astype(int)

    for col in BASE_FEATURES:
        if col not in work.columns:
            work[col] = np.nan

    for col in BASE_FEATURES:
        work[col] = pd.to_numeric(work[col], errors="coerce").fillna(0)

    return work.reset_index(drop=True)


def load_corner_prediction_frame(corner_pred_dir: str | Path, *, scenario: str | None = None) -> pd.DataFrame:
    path = Path(corner_pred_dir)
    if path.is_file():
        candidates = [path]
    else:
        sibling_window_dir = path.parent / "corner_rank_prediction_by_section_window_ablation"
        candidates = [
            path / "corner_rank_prediction_by_section_window_ablation_validation.csv",
            sibling_window_dir / "corner_rank_prediction_by_section_window_ablation_validation.csv",
            path / "corner_rank_prediction_by_section_validation.csv",
            path / "corner_rank_prediction_by_section_ablation_validation.csv",
        ]
        candidates.extend(sorted(path.glob("*validation.csv")))
        candidates.extend(sorted(path.glob("*.csv")))

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen or not candidate.exists() or not candidate.is_file():
            continue
        seen.add(candidate)
        frame = pd.read_csv(candidate)
        required = {"date", "machine_number", "section", "pred_corner_top_prob"}
        if not required.issubset(frame.columns):
            continue
        out = frame.copy()
        if scenario is not None:
            if "scenario" not in out.columns:
                continue
            out["scenario"] = out["scenario"].astype(str).str.strip()
            out = out[out["scenario"].eq(str(scenario).strip())].copy()
            if out.empty:
                continue
        out["date"] = pd.to_datetime(out["date"].astype(str), errors="coerce").dt.normalize()
        out["machine_number"] = pd.to_numeric(out["machine_number"], errors="coerce")
        out["section"] = out["section"].astype(str).str.strip()
        if "is_corner" not in out.columns:
            out["is_corner"] = 1
        out["is_corner"] = pd.to_numeric(out["is_corner"], errors="coerce").fillna(0).astype(int)
        out["pred_corner_top_prob"] = pd.to_numeric(out["pred_corner_top_prob"], errors="coerce")
        out = out.dropna(subset=["date", "machine_number", "section", "pred_corner_top_prob"]).copy()
        out["machine_number"] = out["machine_number"].astype(int)
        return out[["date", "machine_number", "section", "is_corner", "pred_corner_top_prob"]].reset_index(drop=True)

    raise FileNotFoundError(f"No corner prediction CSV with required columns found in {path}")


def merge_corner_predictions(machine_frame: pd.DataFrame, corner_frame: pd.DataFrame) -> pd.DataFrame:
    work = machine_frame.copy()
    work["date"] = pd.to_datetime(work["date"].astype(str), errors="coerce").dt.normalize()
    work["section"] = work["section"].astype(str).str.strip()
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work = work.dropna(subset=["date", "section", "machine_number"]).copy()
    work["machine_number"] = work["machine_number"].astype(int)

    if corner_frame.empty:
        work[CORNER_FEATURE] = 0.5
        return work.reset_index(drop=True)

    corner = corner_frame.copy()
    corner["date"] = pd.to_datetime(corner["date"].astype(str), errors="coerce").dt.normalize()
    corner["section"] = corner["section"].astype(str).str.strip()
    corner["pred_corner_top_prob"] = pd.to_numeric(corner["pred_corner_top_prob"], errors="coerce")
    if "is_corner" in corner.columns:
        corner = corner[pd.to_numeric(corner["is_corner"], errors="coerce").fillna(0).astype(int).eq(1)].copy()
    corner = corner.dropna(subset=["date", "section", "pred_corner_top_prob"]).copy()

    aggregated = (
        corner.groupby(["date", "section"], as_index=False)
        .agg(pred_corner_top_prob=(CORNER_FEATURE, "mean"))
    )

    merged = work.merge(aggregated, on=["date", "section"], how="left")
    merged[CORNER_FEATURE] = pd.to_numeric(merged[CORNER_FEATURE], errors="coerce").fillna(0.5)
    return merged.reset_index(drop=True)


def _get_catboost_classes():
    try:
        from catboost import CatBoostClassifier, Pool
    except ImportError as exc:  # pragma: no cover - runtime dependency guard
        raise RuntimeError("catboost is required to train the model.") from exc
    return CatBoostClassifier, Pool


def _prepare_model_frame(frame: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    work = frame.copy()
    for col in features:
        work[col] = pd.to_numeric(work[col], errors="coerce")
    return work


def _fit_catboost_model(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    *,
    features: list[str],
    task_type: str,
    devices: str,
) -> tuple[object, object, object]:
    CatBoostClassifier, Pool = _get_catboost_classes()
    train_frame = _prepare_model_frame(train_df, features)
    val_frame = _prepare_model_frame(val_df, features)
    train_pool = Pool(train_frame[features], label=train_df["target_diff_positive"])
    val_pool = Pool(val_frame[features], label=val_df["target_diff_positive"])

    params = dict(CATBOOST_PARAMS)
    params["task_type"] = task_type
    params["devices"] = devices

    try:
        model = CatBoostClassifier(**params)
        model.fit(train_pool, eval_set=val_pool, use_best_model=True)
    except Exception:
        if task_type != "GPU":
            raise
        cpu_params = {k: v for k, v in params.items() if k not in {"task_type", "devices"}}
        cpu_params["task_type"] = "CPU"
        model = CatBoostClassifier(**cpu_params)
        model.fit(train_pool, eval_set=val_pool, use_best_model=True)

    return model, train_pool, val_pool


def _extract_feature_importance(model: object, train_pool: object, features: list[str], *, fold_id: int) -> pd.DataFrame:
    try:
        importances = model.get_feature_importance(train_pool, type="PredictionValuesChange")
    except Exception:
        importances = model.get_feature_importance()

    rows = []
    for feature, importance in zip(features, importances, strict=False):
        rows.append(
            {
                "fold_id": fold_id,
                "feature": feature,
                "importance": float(importance),
            }
        )
    frame = pd.DataFrame(rows)
    frame["rank"] = frame["importance"].rank(method="dense", ascending=False).astype(int)
    return frame.sort_values(["fold_id", "rank", "feature"]).reset_index(drop=True)


def _compute_metrics(frame: pd.DataFrame, *, prob_column: str) -> dict[str, float]:
    if frame.empty:
        return {
            "auc": float("nan"),
            "precision": float("nan"),
            "recall": float("nan"),
            "f1": float("nan"),
            "n_validation_rows": 0,
            "n_validation_dates": 0,
            "positive_rate": float("nan"),
        }

    y_true = pd.to_numeric(frame["target_diff_positive"], errors="coerce").fillna(0).astype(int)
    y_prob = pd.to_numeric(frame[prob_column], errors="coerce").fillna(0.0)
    y_pred = (y_prob >= 0.5).astype(int)

    metrics = {
        "auc": float("nan"),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "n_validation_rows": int(len(frame)),
        "n_validation_dates": int(frame["date"].nunique()) if "date" in frame.columns else 0,
        "positive_rate": float(y_true.mean()),
    }
    if y_true.nunique() > 1:
        metrics["auc"] = float(roc_auc_score(y_true, y_prob))
    return metrics


def evaluate_prediction_frame(frame: pd.DataFrame, *, prob_column: str) -> dict[str, float]:
    return _compute_metrics(frame, prob_column=prob_column)


def _run_fold(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    *,
    fold_id: int,
    task_type: str,
    devices: str,
) -> FoldResult | None:
    baseline_features = build_feature_columns(include_corner=False)
    corner_features = build_feature_columns(include_corner=True)

    if train_df["target_diff_positive"].nunique(dropna=True) < 2:
        return None
    if val_df.empty:
        return None

    baseline_model, baseline_train_pool, _ = _fit_catboost_model(
        train_df,
        val_df,
        features=baseline_features,
        task_type=task_type,
        devices=devices,
    )
    corner_model, corner_train_pool, _ = _fit_catboost_model(
        train_df,
        val_df,
        features=corner_features,
        task_type=task_type,
        devices=devices,
    )

    val_base = _prepare_model_frame(val_df, baseline_features)
    val_corner = _prepare_model_frame(val_df, corner_features)

    out = val_df.copy()
    out["pred_baseline_prob"] = baseline_model.predict_proba(val_base[baseline_features])[:, 1]
    out["pred_with_corner_prob"] = corner_model.predict_proba(val_corner[corner_features])[:, 1]
    out["pred_baseline_flag"] = (out["pred_baseline_prob"] >= 0.5).astype(int)
    out["pred_with_corner_flag"] = (out["pred_with_corner_prob"] >= 0.5).astype(int)
    out["fold_id"] = fold_id

    importance = _extract_feature_importance(corner_model, corner_train_pool, corner_features, fold_id=fold_id)
    return FoldResult(fold_id=fold_id, predictions=out, feature_importance=importance)


def _summarize_feature_importance(feature_importance: pd.DataFrame) -> pd.DataFrame:
    if feature_importance.empty:
        return pd.DataFrame(columns=["feature", "mean_importance", "std_importance", "fold_count", "rank"])

    summary = (
        feature_importance.groupby("feature", as_index=False)
        .agg(
            mean_importance=("importance", "mean"),
            std_importance=("importance", "std"),
            fold_count=("fold_id", "nunique"),
        )
        .fillna({"std_importance": 0.0})
    )
    summary = summary.sort_values(["mean_importance", "feature"], ascending=[False, True]).reset_index(drop=True)
    summary["rank"] = np.arange(1, len(summary) + 1)
    return summary


def _build_metrics_table(predictions: pd.DataFrame) -> pd.DataFrame:
    baseline = _compute_metrics(predictions, prob_column="pred_baseline_prob")
    with_corner = _compute_metrics(predictions, prob_column="pred_with_corner_prob")

    delta = {
        "auc": with_corner["auc"] - baseline["auc"] if pd.notna(with_corner["auc"]) and pd.notna(baseline["auc"]) else float("nan"),
        "precision": with_corner["precision"] - baseline["precision"],
        "recall": with_corner["recall"] - baseline["recall"],
        "f1": with_corner["f1"] - baseline["f1"],
        "n_validation_rows": int(predictions.shape[0]),
        "n_validation_dates": int(predictions["date"].nunique()) if not predictions.empty and "date" in predictions.columns else 0,
        "positive_rate": float(pd.to_numeric(predictions["target_diff_positive"], errors="coerce").fillna(0).mean()) if not predictions.empty else float("nan"),
    }

    rows = [
        {
            "model_type": "baseline",
            **baseline,
            "feature_count": len(build_feature_columns(include_corner=False)),
            "notes": "baseline 36 features",
            "delta_auc": float("nan"),
            "delta_precision": float("nan"),
            "delta_recall": float("nan"),
            "delta_f1": float("nan"),
        },
        {
            "model_type": "with_corner",
            **with_corner,
            "feature_count": len(build_feature_columns(include_corner=True)),
            "notes": "baseline 36 + pred_corner_top_prob",
            "delta_auc": delta["auc"],
            "delta_precision": delta["precision"],
            "delta_recall": delta["recall"],
            "delta_f1": delta["f1"],
        },
        {
            "model_type": "improvement",
            "auc": delta["auc"],
            "precision": delta["precision"],
            "recall": delta["recall"],
            "f1": delta["f1"],
            "n_validation_rows": delta["n_validation_rows"],
            "n_validation_dates": delta["n_validation_dates"],
            "positive_rate": delta["positive_rate"],
            "feature_count": 1,
            "notes": "with_corner - baseline",
            "delta_auc": delta["auc"],
            "delta_precision": delta["precision"],
            "delta_recall": delta["recall"],
            "delta_f1": delta["f1"],
        },
    ]
    return pd.DataFrame(rows)


def run_pipeline(
    db_path: Path,
    *,
    corner_pred_dir: str | Path,
    output_dir: Path,
    train_days: int,
    val_days: int,
    step_days: int,
    min_games: int,
    xday_only: bool,
    task_type: str,
    devices: str,
    section_filter: Iterable[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    raw = load_raw_machine_rows(db_path, min_games=min_games)
    if raw.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    machine_frame = build_machine_feature_frame(raw)
    corner_frame = load_corner_prediction_frame(corner_pred_dir)
    machine_frame = merge_corner_predictions(machine_frame, corner_frame)

    if xday_only:
        machine_frame = machine_frame[machine_frame["is_xday"].eq(1)].copy()
    if section_filter:
        section_filter_set = {str(value).strip() for value in section_filter if str(value).strip()}
        machine_frame = machine_frame[machine_frame["section"].isin(section_filter_set)].copy()

    machine_frame = machine_frame.reset_index(drop=True)
    if machine_frame.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    dates = tuple(sorted(pd.to_datetime(machine_frame["date"], errors="coerce").dropna().unique()))
    folds = build_walk_forward_folds(dates, train_days=train_days, val_days=val_days, step_days=step_days)
    if not folds:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    fold_results: list[FoldResult] = []
    for fold in folds:
        train_df = machine_frame[machine_frame["date"].isin(fold.train_dates)].copy()
        val_df = machine_frame[machine_frame["date"].isin(fold.val_dates)].copy()
        if train_df.empty or val_df.empty:
            continue
        result = _run_fold(
            train_df,
            val_df,
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
                "pred_baseline_prob",
                "pred_with_corner_prob",
                CORNER_FEATURE,
                "fold_id",
            ]
        ].sort_values(["date", "section", "machine_number", "fold_id"]).reset_index(drop=True)
        feature_importance = pd.concat([result.feature_importance for result in fold_results], ignore_index=True)
    else:
        pred_df = pd.DataFrame()
        feature_importance = pd.DataFrame()

    metrics_df = _build_metrics_table(pred_df)
    importance_df = _summarize_feature_importance(feature_importance)

    output_dir.mkdir(parents=True, exist_ok=True)
    pred_path = output_dir / "individual_machine_diff_plus_validation.csv"
    metrics_path = output_dir / "individual_machine_diff_plus_metrics.csv"
    importance_path = output_dir / "individual_machine_diff_plus_feature_importance.csv"
    pred_df.to_csv(pred_path, index=False)
    metrics_df.to_csv(metrics_path, index=False)
    importance_df.to_csv(importance_path, index=False)
    return pred_df, metrics_df, importance_df


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    section_filter = [value.strip() for value in args.section_filter.split(",") if value.strip()]
    db_path = Path(args.db_path)
    if not db_path.exists():
        db_path = resolve_db_path("", args.db_glob)
    output_dir = Path(args.output_dir)

    print_section("1. Load and prepare dataset")
    print(f"  db_path: {db_path}")
    print(f"  corner_pred_dir: {args.corner_pred_dir}")
    print(f"  xday_only: {args.xday_only}")
    print(f"  train_days: {args.train_days} / val_days: {args.val_days} / step_days: {args.step_days}")

    pred_df, metrics_df, importance_df = run_pipeline(
        db_path,
        corner_pred_dir=args.corner_pred_dir,
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

    print_section("3. Feature importance")
    if importance_df.empty:
        print("  No feature importance produced.")
    else:
        print(importance_df.head(10).to_string(index=False))

    print_section("4. Output")
    if pred_df.empty:
        print("  No validation predictions produced.")
    else:
        print(f"  rows: {len(pred_df):,}")
        print(f"  validation csv: {output_dir / 'individual_machine_diff_plus_validation.csv'}")
        print(f"  metrics csv: {output_dir / 'individual_machine_diff_plus_metrics.csv'}")
        print(f"  feature importance csv: {output_dir / 'individual_machine_diff_plus_feature_importance.csv'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
