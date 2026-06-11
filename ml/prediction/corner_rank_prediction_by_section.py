from __future__ import annotations

import argparse
import sqlite3
import sys
from itertools import combinations
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd
from scipy.stats import ttest_rel
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score

from ml.last_digit.utils import resolve_db_path


try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = ROOT / "data" / "corner_rank_prediction_by_section"
DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CATBOOST_PARAMS = {
    "iterations": 500,
    "learning_rate": 0.05,
    "depth": 5,
    "loss_function": "Logloss",
    "eval_metric": "AUC",
    "task_type": "GPU",
    "devices": "0",
    "random_seed": 42,
    "verbose": False,
    "early_stopping_rounds": 50,
    "class_weights": [1.0, 1.5],
    "allow_writing_files": False,
}

MIN_GAMES = 100
NEW_MANAGER_DATE = pd.Timestamp("2026-05-01")
FEATURE_SCENARIOS = ("all_days", "xday_only", "hybrid")
ABLATION_OUTPUT_PREFIX = "corner_rank_prediction_by_section_ablation"
WINDOW_ABLATION_SCENARIOS = (
    "xday_7mean",
    "xday_rolling30_mean",
    "xday_90mean",
    "xday_expanding_mean",
    "all_days_expanding_mean",
)
WINDOW_ABLATION_BASELINE = "xday_7mean"
WINDOW_ABLATION_FALLBACK = "xday_expanding_mean"
WINDOW_ABLATION_OUTPUT_PREFIX = "corner_rank_prediction_by_section_window_ablation"
WINDOW_ABLATION_NOTES = {
    "xday_7mean": "baseline: xday rolling 7",
    "xday_rolling30_mean": "xday rolling 30 mean",
    "xday_90mean": "xday rolling 90 mean",
    "xday_expanding_mean": "xday expanding mean",
    "all_days_expanding_mean": "all-days expanding mean",
}


@dataclass(frozen=True)
class WalkForwardFold:
    fold_id: int
    train_dates: tuple[pd.Timestamp, ...]
    val_dates: tuple[pd.Timestamp, ...]


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


def _mode_or_default(values: pd.Series, default: str) -> str:
    series = values.dropna()
    if series.empty:
        return default
    out = series.astype(str).mode(dropna=True)
    if out.empty:
        return default
    return str(out.iloc[0])


def _series_or_default(frame: pd.DataFrame, column: str, default: object) -> pd.Series:
    if column in frame.columns:
        return frame[column]
    if isinstance(default, pd.Series):
        return default.reindex(frame.index)
    if isinstance(default, pd.Index):
        return pd.Series(default, index=frame.index)
    if isinstance(default, (list, tuple, np.ndarray)):
        if len(default) == len(frame):
            return pd.Series(default, index=frame.index)
    return pd.Series([default] * len(frame), index=frame.index)


def _fallback_section(machine_number: object) -> str:
    if pd.isna(machine_number):
        return "unknown"
    number = int(machine_number)
    return f"{number}-{number}"


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
    return _fallback_section(machine_number)


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


def _is_x_day(value: object) -> bool:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return False
    return int(ts.day) % 10 in {4, 7}


def _window_ablation_base_features() -> list[str]:
    return [
        "dd",
        "is_dd4",
        "is_dd7",
        "is_dd14",
        "is_dd17",
        "is_dd24",
        "is_dd27",
        "dd_mod10",
        "weekday_num",
        "month",
        "is_new_manager",
        "is_xday",
        "prev_xday_corner_top_flag",
        "corner_position_ratio",
        "dd_strength_for_section",
        "section",
        "machine_type",
    ]


def build_window_ablation_feature_columns(feature_scenario: str) -> list[str]:
    base_features = _window_ablation_base_features()
    scenario_features = {
        "xday_7mean": ["xday_roll7_mean"],
        "xday_rolling30_mean": ["xday_roll30_mean"],
        "xday_90mean": ["xday_roll90_mean"],
        "xday_expanding_mean": ["xday_expanding_mean"],
        "all_days_expanding_mean": ["all_days_expanding_mean"],
    }
    if feature_scenario not in scenario_features:
        raise ValueError(f"Unsupported window ablation scenario: {feature_scenario}")
    return base_features + scenario_features[feature_scenario]


def add_window_ablation_features(ranked: pd.DataFrame) -> pd.DataFrame:
    if ranked.empty:
        return ranked.copy()

    work = ranked.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.normalize()
    work = work.dropna(subset=["date", "section", "machine_number", "diff_coins_normalized"]).copy()
    if work.empty:
        return work.reset_index(drop=True)

    work["section"] = work["section"].astype(str).str.strip()
    work["machine_type"] = _series_or_default(work, "machine_type", "other").fillna("other").astype(str).str.strip()
    work["is_xday"] = work["date"].map(_is_x_day).astype(int)
    work = work.sort_values(["section", "date", "machine_number"]).reset_index(drop=True)

    work["all_days_expanding_mean"] = work.groupby("section")["diff_coins_normalized"].transform(
        lambda s: s.shift(1).expanding(min_periods=1).mean()
    )

    xday = work[work["is_xday"].eq(1)].copy()
    if not xday.empty:
        xday = xday.sort_values(["section", "date", "machine_number"]).reset_index(drop=True)
        grouped = xday.groupby("section")["diff_coins_normalized"]
        xday["xday_roll7_mean"] = grouped.transform(lambda s: s.shift(1).rolling(7, min_periods=1).mean())
        xday["xday_roll30_mean"] = grouped.transform(lambda s: s.shift(1).rolling(30, min_periods=1).mean())
        xday["xday_roll90_mean"] = grouped.transform(lambda s: s.shift(1).rolling(90, min_periods=1).mean())
        xday["xday_expanding_mean"] = grouped.transform(lambda s: s.shift(1).expanding(min_periods=1).mean())
        work = work.merge(
            xday[
                [
                    "date",
                    "section",
                    "machine_number",
                    "xday_roll7_mean",
                    "xday_roll30_mean",
                    "xday_roll90_mean",
                    "xday_expanding_mean",
                ]
            ],
            on=["date", "section", "machine_number"],
            how="left",
        )
    else:
        for col in [
            "xday_roll7_mean",
            "xday_roll30_mean",
            "xday_roll90_mean",
            "xday_expanding_mean",
        ]:
            work[col] = np.nan

    return work.reset_index(drop=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Corner top-30% prediction by section.")
    parser.add_argument("--db-path", default="db/みとや大森町店.db", help="Path to the SQLite DB.")
    parser.add_argument(
        "--db-glob",
        default="*みとや大森町店*.db",
        help="Glob used when --db-path is omitted or unavailable.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/corner_rank_prediction_by_section",
        help="Directory for prediction outputs.",
    )
    parser.add_argument("--train-days", type=int, default=72, help="Walk-forward training window.")
    parser.add_argument("--val-days", type=int, default=30, help="Walk-forward validation window.")
    parser.add_argument("--step-days", type=int, default=30, help="Walk-forward step size.")
    parser.add_argument("--min-games", type=int, default=MIN_GAMES, help="Minimum games per raw machine row.")
    parser.add_argument("--xday-only", action="store_true", default=False, help="Train only on x_day rows.")
    parser.add_argument(
        "--feature-scenario",
        default="all_days",
        choices=list(FEATURE_SCENARIOS),
        help="Feature ablation scenario for single-run mode.",
    )
    parser.add_argument("--ablation", action="store_true", help="Run all feature scenarios and write comparison CSVs.")
    parser.add_argument(
        "--window-ablation",
        action="store_true",
        help="Run the xday/all-days window ablation and write comparison CSVs.",
    )
    parser.add_argument("--task-type", default="GPU", choices=["GPU", "CPU"], help="CatBoost task type.")
    parser.add_argument("--devices", default="0", help="CatBoost GPU devices string.")
    parser.add_argument("--section-filter", default="", help="Comma-separated section filter.")
    return parser


def load_raw_rows(db_path: Path, min_games: int = MIN_GAMES) -> pd.DataFrame:
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
            pd.read_sql_query(
                """
                SELECT
                  machine_number,
                  section,
                  section_min,
                  section_max,
                  rank_from_min,
                  rank_from_max,
                  rank_from_aisle,
                  is_reversed_section
                FROM machine_layout
                """,
                con,
            )
            if _table_exists(con, "machine_layout")
            else pd.DataFrame(
                columns=[
                    "machine_number",
                    "section",
                    "section_min",
                    "section_max",
                    "rank_from_min",
                    "rank_from_max",
                    "rank_from_aisle",
                    "is_reversed_section",
                ]
            )
        )
        master = (
            pd.read_sql_query(
                """
                SELECT
                  machine_name_normalized,
                  jug_flag,
                  hana_flag,
                  oki_flag,
                  bt_flag
                FROM machine_master
                """,
                con,
            )
            if _table_exists(con, "machine_master")
            else pd.DataFrame(
                columns=["machine_name_normalized", "jug_flag", "hana_flag", "oki_flag", "bt_flag"]
            )
        )

    if raw.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "machine_number",
                "machine_name",
                "last_digit",
                "games_normalized",
                "diff_coins_normalized",
                "section",
                "rank_from_min",
                "rank_from_max",
                "rank_from_aisle",
                "is_reversed_section",
                "machine_type",
            ]
        )

    work = raw.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work["last_digit"] = work["last_digit"].astype(str).str.strip()
    work = work.dropna(
        subset=["date", "machine_number", "machine_name", "games_normalized", "diff_coins_normalized"]
    ).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work = work[work["games_normalized"] >= int(min_games)].copy()

    if not layout.empty:
        layout = layout.copy()
        layout["machine_number"] = pd.to_numeric(layout["machine_number"], errors="coerce")
        for col in ("section_min", "section_max", "rank_from_min", "rank_from_max", "rank_from_aisle"):
            layout[col] = pd.to_numeric(layout[col], errors="coerce")
        for col in ("section", "is_reversed_section"):
            if col not in layout.columns:
                layout[col] = np.nan
        work = work.merge(layout, on="machine_number", how="left")
    else:
        work["section"] = np.nan
        work["section_min"] = np.nan
        work["section_max"] = np.nan
        work["rank_from_min"] = np.nan
        work["rank_from_max"] = np.nan
        work["rank_from_aisle"] = np.nan
        work["is_reversed_section"] = 0

    if not master.empty:
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
        work["section"] = ""
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
    work["date"] = work["date"].dt.normalize()
    return work.reset_index(drop=True)


def assign_corner_top_targets(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "machine_number",
                "machine_name",
                "section",
                "diff_coins_normalized",
                "games_normalized",
                "target_corner_top_flag",
            ]
        )

    work = raw.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.normalize()
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    work["section"] = _series_or_default(work, "section", "unknown").fillna("unknown").astype(str)
    work["machine_name"] = _series_or_default(work, "machine_name", "unknown").fillna("unknown").astype(str)
    work["rank_from_aisle"] = pd.to_numeric(_series_or_default(work, "rank_from_aisle", 0), errors="coerce").fillna(0).astype(int)
    is_corner_default = (work["rank_from_aisle"] == 1).astype(int)
    work["is_corner"] = pd.to_numeric(_series_or_default(work, "is_corner", is_corner_default), errors="coerce").fillna(0).astype(int)
    work["machine_type"] = _series_or_default(work, "machine_type", "other").fillna("other").astype(str)
    work = work.dropna(subset=["date", "machine_number", "section", "diff_coins_normalized", "games_normalized"]).copy()

    work["dd"] = work["date"].dt.day.astype(int)
    work["weekday_num"] = work["date"].dt.dayofweek.astype(int)
    work["month"] = work["date"].dt.month.astype(int)
    work["dd_mod10"] = work["dd"] % 10
    work["is_dd4"] = (work["dd"] == 4).astype(int)
    work["is_dd7"] = (work["dd"] == 7).astype(int)
    work["is_dd14"] = (work["dd"] == 14).astype(int)
    work["is_dd17"] = (work["dd"] == 17).astype(int)
    work["is_dd24"] = (work["dd"] == 24).astype(int)
    work["is_dd27"] = (work["dd"] == 27).astype(int)
    work["is_xday"] = work["dd_mod10"].isin([4, 7]).astype(int)
    work["is_new_manager"] = (work["date"] >= NEW_MANAGER_DATE).astype(int)

    section_group = work.groupby(["date", "section"], sort=False)
    work["section_day_machine_count"] = section_group["machine_number"].transform("size")
    work["section_day_rank"] = section_group["diff_coins_normalized"].rank(method="first", ascending=False)
    work["section_day_top_n"] = np.ceil(work["section_day_machine_count"] * 0.3).astype(int).clip(lower=1)
    work["target_corner_top_flag"] = (work["section_day_rank"] <= work["section_day_top_n"]).astype(int)

    section_day = (
        section_group.agg(section_day_mean_diff=("diff_coins_normalized", "mean"))
        .reset_index()
    )
    section_day["dd"] = section_day["date"].dt.day.astype(int)
    section_day = section_day.sort_values(["section", "dd", "date"]).reset_index(drop=True)
    section_day["dd_strength_for_section"] = section_day.groupby(["section", "dd"])["section_day_mean_diff"].transform(
        lambda s: s.shift(1).expanding(min_periods=1).mean()
    )
    work = work.merge(
        section_day[["date", "section", "dd_strength_for_section"]],
        on=["date", "section"],
        how="left",
    )

    return work.reset_index(drop=True)


def add_corner_prediction_features(ranked: pd.DataFrame) -> pd.DataFrame:
    if ranked.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "section",
                "machine_number",
                "machine_name",
                "target_corner_top_flag",
                "pred_corner_top_prob",
            ]
        )

    work = ranked.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.normalize()
    work = work.dropna(subset=["date", "section", "machine_number", "target_corner_top_flag"]).copy()
    work["section"] = work["section"].astype(str).str.strip()
    work["machine_type"] = _series_or_default(work, "machine_type", "other").fillna("other").astype(str).str.strip()

    if "is_corner" not in work.columns:
        work["is_corner"] = (pd.to_numeric(work.get("rank_from_aisle", 0), errors="coerce").fillna(0).astype(int) == 1).astype(int)
    else:
        work["is_corner"] = pd.to_numeric(work["is_corner"], errors="coerce").fillna(0).astype(int)

    work["rank_from_aisle"] = pd.to_numeric(work.get("rank_from_aisle", 0), errors="coerce").fillna(0).astype(int)
    work = work[work["is_corner"].eq(1)].copy()
    if work.empty:
        return work.reset_index(drop=True)

    work["section_max_aisle"] = work.groupby("section")["rank_from_aisle"].transform("max")
    work["corner_position_ratio"] = (
        work["rank_from_aisle"] / work["section_max_aisle"].replace(0, np.nan)
    ).fillna(0.0)

    work = work.sort_values(["section", "date", "machine_number"]).reset_index(drop=True)
    group_cols = ["section"]
    work["corner_rolling7_all_mean"] = work.groupby(group_cols)["diff_coins_normalized"].transform(
        lambda s: s.shift(1).rolling(7, min_periods=1).mean()
    )
    work["corner_rolling30_all_mean"] = work.groupby(group_cols)["diff_coins_normalized"].transform(
        lambda s: s.shift(1).rolling(30, min_periods=1).mean()
    )
    work["corner_trend_all"] = work["corner_rolling7_all_mean"] - work["corner_rolling30_all_mean"]
    work["corner_expanding_all_mean"] = work.groupby(group_cols)["diff_coins_normalized"].transform(
        lambda s: s.shift(1).expanding(min_periods=1).mean()
    )

    xday_corner = work[work["is_xday"].eq(1)].sort_values(["section", "date", "machine_number"]).copy()
    xday_corner["corner_rolling7_xday_mean"] = xday_corner.groupby("section")["diff_coins_normalized"].transform(
        lambda s: s.shift(1).rolling(7, min_periods=1).mean()
    )
    xday_corner["corner_rolling30_xday_mean"] = xday_corner.groupby("section")["diff_coins_normalized"].transform(
        lambda s: s.shift(1).rolling(30, min_periods=1).mean()
    )
    xday_corner["corner_trend_xday"] = xday_corner["corner_rolling7_xday_mean"] - xday_corner["corner_rolling30_xday_mean"]
    xday_corner["corner_expanding_xday_mean"] = xday_corner.groupby("section")["diff_coins_normalized"].transform(
        lambda s: s.shift(1).expanding(min_periods=1).mean()
    )
    work = work.merge(
        xday_corner[
            [
                "date",
                "section",
                "corner_rolling7_xday_mean",
                "corner_rolling30_xday_mean",
                "corner_trend_xday",
                "corner_expanding_xday_mean",
            ]
        ],
        on=["date", "section"],
        how="left",
    )

    work["corner_rolling7_mean"] = work["corner_rolling7_all_mean"]
    work["corner_rolling30_mean"] = work["corner_rolling30_all_mean"]
    work["corner_trend"] = work["corner_trend_all"]
    work["_xday_flag"] = work["target_corner_top_flag"].where(work["is_xday"].eq(1))
    work["prev_xday_corner_top_flag"] = work.groupby(group_cols)["_xday_flag"].transform(lambda s: s.shift(1).ffill())
    work = work.drop(columns=["_xday_flag"])

    return work.reset_index(drop=True)


def build_feature_columns(feature_scenario: str) -> list[str]:
    base_features = [
        "dd",
        "is_dd4",
        "is_dd7",
        "is_dd14",
        "is_dd17",
        "is_dd24",
        "is_dd27",
        "dd_mod10",
        "weekday_num",
        "month",
        "is_new_manager",
        "is_xday",
        "prev_xday_corner_top_flag",
        "corner_position_ratio",
        "dd_strength_for_section",
        "section",
        "machine_type",
    ]
    all_days_features = [
        "corner_rolling7_all_mean",
        "corner_rolling30_all_mean",
        "corner_trend_all",
    ]
    xday_features = [
        "corner_rolling7_xday_mean",
        "corner_rolling30_xday_mean",
        "corner_trend_xday",
    ]

    if feature_scenario == "all_days":
        return base_features + all_days_features
    if feature_scenario == "xday_only":
        return base_features + xday_features
    if feature_scenario == "hybrid":
        return base_features + all_days_features + xday_features
    raise ValueError(f"Unsupported feature_scenario: {feature_scenario}")


def build_walk_forward_folds(
    dates: Sequence[pd.Timestamp],
    *,
    train_days: int,
    val_days: int,
    step_days: int,
) -> list[WalkForwardFold]:
    ordered = tuple(pd.Timestamp(d).normalize() for d in dates)
    if train_days <= 0 or val_days <= 0 or step_days <= 0:
        raise ValueError("train_days, val_days, and step_days must be positive.")
    if len(ordered) < train_days + 1:
        return []

    folds: list[WalkForwardFold] = []
    fold_id = 1
    start = train_days
    while start < len(ordered):
        train_slice = ordered[start - train_days : start]
        val_slice = ordered[start : min(start + val_days, len(ordered))]
        if not val_slice:
            break
        folds.append(
            WalkForwardFold(
                fold_id=fold_id,
                train_dates=tuple(train_slice),
                val_dates=tuple(val_slice),
            )
        )
        fold_id += 1
        start += step_days
    return folds


def _prepare_model_frame(frame: pd.DataFrame, features: list[str], cat_features: list[str]) -> pd.DataFrame:
    work = frame.copy()
    for col in features:
        if col in cat_features:
            work[col] = work[col].fillna("unknown").astype(str)
        else:
            work[col] = pd.to_numeric(work[col], errors="coerce")
    return work


def _get_catboost_classes():
    try:
        from catboost import CatBoostClassifier, Pool
    except ImportError as exc:  # pragma: no cover - runtime dependency guard
        raise RuntimeError("catboost is required to train the model.") from exc
    return CatBoostClassifier, Pool


def _fit_catboost_model(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    *,
    features: list[str],
    cat_features: list[str],
    task_type: str,
    devices: str,
) -> tuple[object, object]:
    CatBoostClassifier, Pool = _get_catboost_classes()
    tr = _prepare_model_frame(train_df, features, cat_features)
    va = _prepare_model_frame(val_df, features, cat_features)
    cat_indices = [features.index(name) for name in cat_features]
    train_pool = Pool(tr[features], label=train_df["target_corner_top_flag"], cat_features=cat_indices)
    val_pool = Pool(va[features], label=val_df["target_corner_top_flag"], cat_features=cat_indices)
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
    return model, val_pool


def collect_fold_auc_by_id(predictions: pd.DataFrame) -> dict[int, float]:
    if predictions.empty or "fold_id" not in predictions.columns:
        return {}

    fold_aucs: dict[int, float] = {}
    for fold_id, grp in predictions.groupby("fold_id", sort=True):
        try:
            fold_key = int(fold_id)
        except Exception:
            continue
        fold_aucs[fold_key] = float(_compute_classification_metrics(grp)["auc"])
    return fold_aucs


def paired_ttest_fold_aucs(
    fold_auc_a: dict[int, float],
    fold_auc_b: dict[int, float],
) -> tuple[float, float, list[int]]:
    common_folds = sorted(set(fold_auc_a) & set(fold_auc_b))
    paired_a: list[float] = []
    paired_b: list[float] = []
    valid_folds: list[int] = []
    for fold_id in common_folds:
        a_val = fold_auc_a.get(fold_id)
        b_val = fold_auc_b.get(fold_id)
        if pd.isna(a_val) or pd.isna(b_val):
            continue
        paired_a.append(float(a_val))
        paired_b.append(float(b_val))
        valid_folds.append(fold_id)

    if len(valid_folds) < 2:
        return float("nan"), float("nan"), valid_folds

    test = ttest_rel(paired_a, paired_b, nan_policy="omit")
    return float(test.statistic), float(test.pvalue), valid_folds


def select_window_ablation_scenario(summary_df: pd.DataFrame) -> tuple[str, str]:
    if summary_df.empty:
        return WINDOW_ABLATION_FALLBACK, f"有意差なし。{WINDOW_ABLATION_FALLBACK} で統一（最もシンプル）"

    if "scenario" not in summary_df.columns:
        raise ValueError("summary_df must include a scenario column.")
    baseline_row = summary_df[summary_df["scenario"].eq(WINDOW_ABLATION_BASELINE)]
    if baseline_row.empty:
        raise ValueError(f"Missing baseline scenario: {WINDOW_ABLATION_BASELINE}")

    eligible = summary_df[
        summary_df["scenario"].ne(WINDOW_ABLATION_BASELINE)
        & summary_df["p_value"].lt(0.05)
        & summary_df["mean_delta_vs_baseline"].gt(0)
    ].copy()
    if not eligible.empty:
        chosen = eligible.sort_values(["AUC", "mean_delta_vs_baseline"], ascending=[False, False]).iloc[0]
        scenario = str(chosen["scenario"])
        return scenario, f"有意差あり。{scenario} を採用"

    return WINDOW_ABLATION_FALLBACK, f"有意差なし。{WINDOW_ABLATION_FALLBACK} で統一（最もシンプル）"


def summarize_window_ablation_results(
    predictions_by_scenario: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    pairwise_rows: list[dict[str, object]] = []
    fold_auc_maps = {scenario: collect_fold_auc_by_id(frame) for scenario, frame in predictions_by_scenario.items()}

    baseline_auc_map = fold_auc_maps.get(WINDOW_ABLATION_BASELINE, {})

    for scenario in WINDOW_ABLATION_SCENARIOS:
        frame = predictions_by_scenario.get(scenario, pd.DataFrame())
        fold_aucs = [v for _, v in sorted(fold_auc_maps.get(scenario, {}).items()) if not pd.isna(v)]
        overall = _compute_classification_metrics(frame)
        mean_auc = float(np.mean(fold_aucs)) if fold_aucs else float("nan")
        mean_delta_vs_baseline = float("nan")
        p_value = float("nan")
        if scenario != WINDOW_ABLATION_BASELINE:
            t_stat, p_value, valid_folds = paired_ttest_fold_aucs(baseline_auc_map, fold_auc_maps.get(scenario, {}))
            if valid_folds:
                delta_values = [fold_auc_maps.get(scenario, {})[fid] - baseline_auc_map[fid] for fid in valid_folds]
                mean_delta_vs_baseline = float(np.mean(delta_values))
        else:
            mean_delta_vs_baseline = 0.0
            t_stat = float("nan")
        rows.append(
            {
                "scenario": scenario,
                "AUC": mean_auc,
                "Precision": overall["precision"],
                "Recall": overall["recall"],
                "F1": overall["f1"],
                "mean_delta_vs_baseline": mean_delta_vs_baseline,
                "p_value": p_value,
                "fold_auc_std": float(np.std(fold_aucs, ddof=1)) if len(fold_aucs) > 1 else float("nan"),
                "n_folds": int(len(fold_aucs)),
                "n_validation_rows": int(len(frame)),
                "n_validation_dates": int(frame["date"].nunique()) if not frame.empty else 0,
                "n_sections": int(frame["section"].nunique()) if not frame.empty else 0,
                "positive_rate": float(pd.to_numeric(frame["target_corner_top_flag"], errors="coerce").fillna(0).mean()) if not frame.empty else float("nan"),
                "notes": f"window variant: {WINDOW_ABLATION_NOTES.get(scenario, scenario)}",
            }
        )

    for scenario_a, scenario_b in combinations(WINDOW_ABLATION_SCENARIOS, 2):
        fold_auc_a = fold_auc_maps.get(scenario_a, {})
        fold_auc_b = fold_auc_maps.get(scenario_b, {})
        t_stat, p_val, valid_folds = paired_ttest_fold_aucs(fold_auc_a, fold_auc_b)
        delta_values = [fold_auc_b[fid] - fold_auc_a[fid] for fid in valid_folds]
        pairwise_rows.append(
            {
                "scenario_a": scenario_a,
                "scenario_b": scenario_b,
                "mean_delta_b_minus_a": float(np.mean(delta_values)) if delta_values else float("nan"),
                "t_stat": t_stat,
                "p_value": p_val,
                "n_folds": int(len(valid_folds)),
            }
        )

    return pd.DataFrame(rows), pd.DataFrame(pairwise_rows)


def predict_section_walk_forward(
    section_df: pd.DataFrame,
    *,
    train_days: int,
    val_days: int,
    step_days: int,
    task_type: str,
    devices: str,
    feature_scenario: str = "all_days",
    features: list[str] | None = None,
) -> pd.DataFrame:
    if section_df.empty:
        return pd.DataFrame()

    if features is None:
        features = build_feature_columns(feature_scenario)
    cat_features = ["section", "machine_type"]

    available_features = [name for name in features if name in section_df.columns]
    available_cat_features = [name for name in cat_features if name in available_features]
    dates = tuple(sorted(pd.to_datetime(section_df["date"], errors="coerce").dropna().unique()))
    folds = build_walk_forward_folds(dates, train_days=train_days, val_days=val_days, step_days=step_days)
    if not folds:
        return pd.DataFrame()

    predictions: list[pd.DataFrame] = []
    for fold in folds:
        train_df = section_df[section_df["date"].isin(fold.train_dates)].copy()
        val_df = section_df[section_df["date"].isin(fold.val_dates)].copy()
        if train_df.empty or val_df.empty:
            continue
        if train_df["target_corner_top_flag"].nunique(dropna=True) < 2:
            continue
        model, _ = _fit_catboost_model(
            train_df,
            val_df,
            features=available_features,
            cat_features=available_cat_features,
            task_type=task_type,
            devices=devices,
        )
        val_df = _prepare_model_frame(val_df, available_features, available_cat_features)
        val_df["pred_corner_top_prob"] = model.predict_proba(val_df[available_features])[:, 1]
        val_df["pred_corner_top_flag"] = (val_df["pred_corner_top_prob"] >= 0.5).astype(int)
        val_df["fold_id"] = fold.fold_id
        predictions.append(val_df)

    if not predictions:
        return pd.DataFrame()

    out = pd.concat(predictions, ignore_index=True)
    return out


def _compute_classification_metrics(frame: pd.DataFrame) -> dict[str, float]:
    if frame.empty:
        return {
            "auc": float("nan"),
            "precision": float("nan"),
            "recall": float("nan"),
            "f1": float("nan"),
        }

    y_true = pd.to_numeric(frame["target_corner_top_flag"], errors="coerce").fillna(0).astype(int)
    y_prob = pd.to_numeric(frame["pred_corner_top_prob"], errors="coerce")
    y_pred = pd.to_numeric(frame.get("pred_corner_top_flag", (y_prob >= 0.5).astype(int)), errors="coerce").fillna(0).astype(int)

    metrics = {
        "auc": float("nan"),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
    }
    if y_true.nunique() > 1:
        metrics["auc"] = float(roc_auc_score(y_true, y_prob))
    return metrics


def evaluate_prediction_frame(frame: pd.DataFrame) -> dict[str, float]:
    return _compute_classification_metrics(frame)


def summarize_section_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame(
            columns=[
                "section",
                "n_validation_rows",
                "n_validation_dates",
                "positive_rate",
                "auc",
                "precision",
                "recall",
                "f1",
            ]
        )

    rows = []
    overall = _compute_classification_metrics(predictions)
    rows.append(
        {
            "section": "ALL",
            "n_validation_rows": int(len(predictions)),
            "n_validation_dates": int(predictions["date"].nunique()),
            "positive_rate": float(pd.to_numeric(predictions["target_corner_top_flag"], errors="coerce").fillna(0).mean()),
            **overall,
        }
    )
    for section, grp in predictions.groupby("section", sort=True):
        metrics = _compute_classification_metrics(grp)
        rows.append(
            {
                "section": section,
                "n_validation_rows": int(len(grp)),
                "n_validation_dates": int(grp["date"].nunique()),
                "positive_rate": float(pd.to_numeric(grp["target_corner_top_flag"], errors="coerce").fillna(0).mean()),
                **metrics,
            }
        )
    return pd.DataFrame(rows).sort_values(["section"], ascending=[True]).reset_index(drop=True)


def summarize_overall_metrics(predictions: pd.DataFrame) -> dict[str, float]:
    metrics = _compute_classification_metrics(predictions)
    if predictions.empty:
        return {
            "n_validation_rows": 0,
            "n_validation_dates": 0,
            "n_sections": 0,
            "positive_rate": float("nan"),
            **metrics,
        }
    return {
        "n_validation_rows": int(len(predictions)),
        "n_validation_dates": int(predictions["date"].nunique()),
        "n_sections": int(predictions["section"].nunique()),
        "positive_rate": float(pd.to_numeric(predictions["target_corner_top_flag"], errors="coerce").fillna(0).mean()),
        **metrics,
    }


def summarize_ablation_metrics(predictions_by_scenario: dict[str, pd.DataFrame]) -> pd.DataFrame:
    metric_order = [
        "auc",
        "precision",
        "recall",
        "f1",
        "n_validation_rows",
        "n_validation_dates",
        "n_sections",
        "positive_rate",
    ]
    records = {scenario: summarize_overall_metrics(frame) for scenario, frame in predictions_by_scenario.items()}
    rows = []
    for metric in metric_order:
        row = {"metric": metric}
        for scenario in FEATURE_SCENARIOS:
            row[scenario] = records.get(scenario, {}).get(metric, float("nan"))
        rows.append(row)
    return pd.DataFrame(rows)


def _run_single_scenario(
    db_path: Path,
    *,
    train_days: int,
    val_days: int,
    step_days: int,
    xday_only: bool,
    min_games: int,
    task_type: str,
    devices: str,
    feature_scenario: str,
    section_filter: Iterable[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = load_raw_rows(db_path, min_games=min_games)
    if raw.empty:
        return pd.DataFrame(), pd.DataFrame()

    ranked = assign_corner_top_targets(raw)
    dataset = add_corner_prediction_features(ranked)
    if xday_only:
        dataset = dataset[dataset["is_xday"].eq(1)].copy()
    if section_filter:
        section_filter_set = {str(x).strip() for x in section_filter if str(x).strip()}
        dataset = dataset[dataset["section"].isin(section_filter_set)].copy()
    dataset = dataset.reset_index(drop=True)
    if dataset.empty:
        return pd.DataFrame(), pd.DataFrame()

    predictions: list[pd.DataFrame] = []
    for section, section_df in dataset.groupby("section", sort=True):
        section_pred = predict_section_walk_forward(
            section_df.copy(),
            train_days=train_days,
            val_days=val_days,
            step_days=step_days,
            task_type=task_type,
            devices=devices,
            feature_scenario=feature_scenario,
        )
        if section_pred.empty:
            continue
        predictions.append(section_pred)

    if predictions:
        pred_df = pd.concat(predictions, ignore_index=True)
        pred_df["date"] = pd.to_datetime(pred_df["date"], errors="coerce").dt.strftime("%Y%m%d")
        pred_df = pred_df.sort_values(
            ["section", "date", "pred_corner_top_prob", "machine_number"],
            ascending=[True, True, False, True],
        ).reset_index(drop=True)
    else:
        pred_df = pd.DataFrame()

    metrics_df = summarize_section_metrics(pred_df)
    return pred_df, metrics_df


def _run_window_ablation_single_scenario(
    db_path: Path,
    *,
    train_days: int,
    val_days: int,
    step_days: int,
    min_games: int,
    task_type: str,
    devices: str,
    feature_scenario: str,
    section_filter: Iterable[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = load_raw_rows(db_path, min_games=min_games)
    if raw.empty:
        return pd.DataFrame(), pd.DataFrame()

    ranked = assign_corner_top_targets(raw)
    dataset = add_window_ablation_features(ranked)
    dataset = dataset[dataset["is_xday"].eq(1)].copy()
    if section_filter:
        section_filter_set = {str(x).strip() for x in section_filter if str(x).strip()}
        dataset = dataset[dataset["section"].isin(section_filter_set)].copy()
    dataset = dataset.reset_index(drop=True)
    if dataset.empty:
        return pd.DataFrame(), pd.DataFrame()

    features = build_window_ablation_feature_columns(feature_scenario)

    predictions: list[pd.DataFrame] = []
    for section, section_df in dataset.groupby("section", sort=True):
        section_pred = predict_section_walk_forward(
            section_df.copy(),
            train_days=train_days,
            val_days=val_days,
            step_days=step_days,
            task_type=task_type,
            devices=devices,
            features=features,
        )
        if section_pred.empty:
            continue
        predictions.append(section_pred)

    if predictions:
        pred_df = pd.concat(predictions, ignore_index=True)
        pred_df["date"] = pd.to_datetime(pred_df["date"], errors="coerce").dt.strftime("%Y%m%d")
        pred_df = pred_df.sort_values(
            ["section", "date", "pred_corner_top_prob", "machine_number"],
            ascending=[True, True, False, True],
        ).reset_index(drop=True)
    else:
        pred_df = pd.DataFrame()

    metrics_df = summarize_section_metrics(pred_df)
    return pred_df, metrics_df


def run_window_ablation_pipeline(
    db_path: Path,
    *,
    output_dir: Path,
    train_days: int,
    val_days: int,
    step_days: int,
    min_games: int,
    task_type: str,
    devices: str,
    section_filter: Iterable[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    predictions_by_scenario: dict[str, pd.DataFrame] = {}
    combined_predictions: list[pd.DataFrame] = []
    for scenario in WINDOW_ABLATION_SCENARIOS:
        pred_df, _ = _run_window_ablation_single_scenario(
            db_path,
            train_days=train_days,
            val_days=val_days,
            step_days=step_days,
            min_games=min_games,
            task_type=task_type,
            devices=devices,
            feature_scenario=scenario,
            section_filter=section_filter,
        )
        if pred_df.empty:
            predictions_by_scenario[scenario] = pred_df
            continue
        pred_df = pred_df.copy()
        pred_df["scenario"] = scenario
        predictions_by_scenario[scenario] = pred_df
        combined_predictions.append(pred_df)

    if combined_predictions:
        combined_df = pd.concat(combined_predictions, ignore_index=True)
        combined_df = combined_df.sort_values(
            ["scenario", "section", "date", "pred_corner_top_prob", "machine_number"],
            ascending=[True, True, True, False, True],
        ).reset_index(drop=True)
    else:
        combined_df = pd.DataFrame()

    summary_df, pairwise_df = summarize_window_ablation_results(predictions_by_scenario)

    output_dir.mkdir(parents=True, exist_ok=True)
    pred_path = output_dir / f"{WINDOW_ABLATION_OUTPUT_PREFIX}_validation.csv"
    metrics_path = output_dir / f"{WINDOW_ABLATION_OUTPUT_PREFIX}_metrics.csv"
    pairwise_path = output_dir / f"{WINDOW_ABLATION_OUTPUT_PREFIX}_pairwise.csv"
    combined_df.to_csv(pred_path, index=False)
    summary_df.to_csv(metrics_path, index=False)
    pairwise_df.to_csv(pairwise_path, index=False)
    return combined_df, summary_df, pairwise_df


def run_pipeline(
    db_path: Path,
    *,
    output_dir: Path,
    train_days: int,
    val_days: int,
    step_days: int,
    xday_only: bool,
    min_games: int,
    task_type: str,
    devices: str,
    feature_scenario: str = "all_days",
    section_filter: Iterable[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    pred_df, metrics_df = _run_single_scenario(
        db_path,
        train_days=train_days,
        val_days=val_days,
        step_days=step_days,
        xday_only=xday_only,
        min_games=min_games,
        task_type=task_type,
        devices=devices,
        feature_scenario=feature_scenario,
        section_filter=section_filter,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    pred_path = output_dir / "corner_rank_prediction_by_section_validation.csv"
    metrics_path = output_dir / "corner_rank_prediction_by_section_metrics.csv"
    pred_df.to_csv(pred_path, index=False)
    metrics_df.to_csv(metrics_path, index=False)
    return pred_df, metrics_df


def run_ablation_pipeline(
    db_path: Path,
    *,
    output_dir: Path,
    train_days: int,
    val_days: int,
    step_days: int,
    min_games: int,
    task_type: str,
    devices: str,
    section_filter: Iterable[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    predictions_by_scenario: dict[str, pd.DataFrame] = {}
    combined_predictions: list[pd.DataFrame] = []
    for scenario in FEATURE_SCENARIOS:
        pred_df, _ = _run_single_scenario(
            db_path,
            train_days=train_days,
            val_days=val_days,
            step_days=step_days,
            xday_only=False,
            min_games=min_games,
            task_type=task_type,
            devices=devices,
            feature_scenario=scenario,
            section_filter=section_filter,
        )
        if pred_df.empty:
            predictions_by_scenario[scenario] = pred_df
            continue
        pred_df = pred_df.copy()
        pred_df["scenario"] = scenario
        predictions_by_scenario[scenario] = pred_df
        combined_predictions.append(pred_df)

    if combined_predictions:
        combined_df = pd.concat(combined_predictions, ignore_index=True)
        combined_df = combined_df.sort_values(
            ["scenario", "section", "date", "pred_corner_top_prob", "machine_number"],
            ascending=[True, True, True, False, True],
        ).reset_index(drop=True)
    else:
        combined_df = pd.DataFrame()

    metrics_df = summarize_ablation_metrics({scenario: predictions_by_scenario.get(scenario, pd.DataFrame()) for scenario in FEATURE_SCENARIOS})

    output_dir.mkdir(parents=True, exist_ok=True)
    pred_path = output_dir / f"{ABLATION_OUTPUT_PREFIX}_validation.csv"
    metrics_path = output_dir / f"{ABLATION_OUTPUT_PREFIX}_metrics.csv"
    combined_df.to_csv(pred_path, index=False)
    metrics_df.to_csv(metrics_path, index=False)
    return combined_df, metrics_df


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    section_filter = [x.strip() for x in args.section_filter.split(",") if x.strip()]
    db_path = Path(args.db_path)
    if not db_path.exists():
        db_path = resolve_db_path("", args.db_glob)
    output_dir = Path(args.output_dir)

    print_section("1. Load and prepare dataset")
    print(f"  db_path: {db_path}")
    print(f"  xday_only: {args.xday_only}")
    print(f"  train_days: {args.train_days} / val_days: {args.val_days} / step_days: {args.step_days}")

    if args.window_ablation:
        pred_df, metrics_df, pairwise_df = run_window_ablation_pipeline(
            db_path,
            output_dir=output_dir,
            train_days=args.train_days,
            val_days=args.val_days,
            step_days=args.step_days,
            min_games=args.min_games,
            task_type=args.task_type,
            devices=args.devices,
            section_filter=section_filter,
        )
    elif args.ablation:
        pred_df, metrics_df = run_ablation_pipeline(
            db_path,
            output_dir=output_dir,
            train_days=args.train_days,
            val_days=args.val_days,
            step_days=args.step_days,
            min_games=args.min_games,
            task_type=args.task_type,
            devices=args.devices,
            section_filter=section_filter,
        )
    else:
        pred_df, metrics_df = run_pipeline(
            db_path,
            output_dir=output_dir,
            train_days=args.train_days,
            val_days=args.val_days,
            step_days=args.step_days,
            xday_only=args.xday_only,
            min_games=args.min_games,
            task_type=args.task_type,
            devices=args.devices,
            feature_scenario=args.feature_scenario,
            section_filter=section_filter,
        )

    print_section("2. Validation metrics")
    if metrics_df.empty:
        print("  No validation metrics produced.")
    else:
        print(metrics_df.to_string(index=False))
        if args.window_ablation:
            if not pairwise_df.empty:
                print_section("2b. Pairwise comparisons")
                print(pairwise_df.to_string(index=False))

    print_section("3. Output")
    if pred_df.empty:
        print("  No validation predictions produced.")
    else:
        print(f"  rows: {len(pred_df):,}")
        if "scenario" in pred_df.columns:
            print(f"  scenarios: {pred_df['scenario'].nunique():,}")
            if args.window_ablation:
                print(f"  validation csv: {output_dir / f'{WINDOW_ABLATION_OUTPUT_PREFIX}_validation.csv'}")
                print(f"  metrics csv: {output_dir / f'{WINDOW_ABLATION_OUTPUT_PREFIX}_metrics.csv'}")
                print(f"  pairwise csv: {output_dir / f'{WINDOW_ABLATION_OUTPUT_PREFIX}_pairwise.csv'}")
            else:
                print(f"  validation csv: {output_dir / f'{ABLATION_OUTPUT_PREFIX}_validation.csv'}")
                print(f"  metrics csv: {output_dir / f'{ABLATION_OUTPUT_PREFIX}_metrics.csv'}")
        else:
            print(f"  sections: {pred_df['section'].nunique():,}")
            print(f"  validation csv: {output_dir / 'corner_rank_prediction_by_section_validation.csv'}")
            print(f"  metrics csv: {output_dir / 'corner_rank_prediction_by_section_metrics.csv'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
