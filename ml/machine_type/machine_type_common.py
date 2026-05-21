from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.exceptions import NotFittedError
from sklearn.linear_model import SGDClassifier

from ml.evaluators.metrics import calculate_hit_at_k, optimize_binary_threshold

TARGET_COLUMNS = ("is_rank_1", "is_top_2", "is_top_3", "is_top_5")
REPORTS_DIR = Path("ml/machine_type/reports")


@dataclass(slots=True)
class TrainedTargetModel:
    target: str
    threshold: float
    model: Any
    feature_columns: list[str]


def resolve_db_path(raw_path: str = "") -> Path:
    if raw_path:
        db_path = Path(raw_path)
        if not db_path.exists():
            raise FileNotFoundError(f"DB not found: {db_path}")
        return db_path
    candidates = sorted(Path("db").glob("*7.db"))
    if not candidates:
        raise FileNotFoundError("No '*7.db' found under db/")
    return candidates[0]


def ensure_reports_dir() -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return REPORTS_DIR


def write_json_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_daily_machine_type_summary(db_path: Path) -> pd.DataFrame:
    con = sqlite3.connect(db_path)
    try:
        summary_columns = _table_columns(con, "daily_machine_type_summary")
        has_win_rate = "win_rate" in summary_columns
        win_rate_select = ", d.win_rate" if has_win_rate else ""
        df = pd.read_sql_query(
            f"""
            SELECT
                d.date,
                d.machine_name,
                d.machine_count,
                d.total_games,
                d.avg_games,
                d.total_diff_coins,
                d.avg_diff_coins{win_rate_select}
            FROM daily_machine_type_summary d
            ORDER BY d.date, d.machine_name
            """,
            con,
        )
    finally:
        con.close()
    if df.empty:
        raise ValueError("daily_machine_type_summary returned no rows")
    if "win_rate" not in df.columns:
        df["win_rate"] = 0.0
    return df


def load_machine_master(db_path: Path) -> pd.DataFrame:
    con = sqlite3.connect(db_path)
    try:
        columns = _table_columns(con, "machine_master")
        if "machine_name_normalized" not in columns:
            return pd.DataFrame(columns=["machine_name_normalized"])
        select_columns = [col for col in ("machine_name_normalized", "jug_flag", "hana_flag", "oki_flag", "bt_flag") if col in columns]
        df = pd.read_sql_query(
            f"SELECT {', '.join(select_columns)} FROM machine_master",
            con,
        )
    finally:
        con.close()
    return df


def prepare_machine_type_base_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], format="%Y%m%d", errors="coerce")
    out = out.dropna(subset=["date", "machine_name"]).copy()
    numeric_cols = [
        "machine_count",
        "total_games",
        "avg_games",
        "total_diff_coins",
        "avg_diff_coins",
        "win_rate",
    ]
    for column in numeric_cols:
        if column not in out.columns:
            out[column] = 0.0
        out[column] = pd.to_numeric(out[column], errors="coerce").fillna(0.0)
    out["machine_count"] = out["machine_count"].clip(lower=0.0)
    out["efficiency"] = np.divide(
        out["total_diff_coins"],
        out["total_games"],
        out=np.zeros(len(out), dtype=float),
        where=out["total_games"].to_numpy(dtype=float) != 0.0,
    )
    out["entity_key"] = out["machine_name"].astype(str)
    out = out.sort_values(["machine_name", "date"]).reset_index(drop=True)
    return out


def build_audit_report(raw_df: pd.DataFrame, prepared_df: pd.DataFrame | None = None, machine_master_df: pd.DataFrame | None = None) -> dict[str, Any]:
    work = raw_df.copy()
    duplicate_rows = int(work.duplicated(subset=["date", "machine_name"]).sum()) if {"date", "machine_name"} <= set(work.columns) else 0
    parsed_dates = pd.to_datetime(work.get("date"), format="%Y%m%d", errors="coerce") if "date" in work.columns else pd.Series(dtype="datetime64[ns]")
    missing_machine_count = int(work["machine_count"].isna().sum()) if "machine_count" in work.columns else 0
    missing_avg_diff = int(work["avg_diff_coins"].isna().sum()) if "avg_diff_coins" in work.columns else 0
    missing_total_games = int(work["total_games"].isna().sum()) if "total_games" in work.columns else 0

    report: dict[str, Any] = {
        "row_count": int(len(work)),
        "duplicate_date_machine_name_rows": duplicate_rows,
        "missing_machine_count_rows": missing_machine_count,
        "missing_avg_diff_rows": missing_avg_diff,
        "missing_total_games_rows": missing_total_games,
        "date_parse_failed_rows": int(parsed_dates.isna().sum()),
    }

    if not parsed_dates.empty and parsed_dates.notna().any():
        report["min_date"] = str(parsed_dates.min().date())
        report["max_date"] = str(parsed_dates.max().date())

    if prepared_df is not None and not prepared_df.empty:
        prepared = prepared_df.sort_values(["machine_name", "date"]).copy()
        prepared["count_delta_1d"] = prepared.groupby("machine_name", sort=False)["machine_count"].diff().fillna(0.0)
        report["unique_machine_names"] = int(prepared["machine_name"].nunique())
        report["new_machine_rows"] = int(prepared.groupby("machine_name", sort=False).cumcount().eq(0).sum())
        report["count_increase_rows"] = int((prepared["count_delta_1d"] > 0).sum())
        report["count_decrease_rows"] = int((prepared["count_delta_1d"] < 0).sum())

    if machine_master_df is not None and not machine_master_df.empty and prepared_df is not None and not prepared_df.empty:
        ref = machine_master_df.copy()
        if "machine_name_normalized" in ref.columns:
            joined = prepared_df.merge(
                ref[["machine_name_normalized"]].drop_duplicates(),
                how="left",
                left_on="machine_name",
                right_on="machine_name_normalized",
            )
            miss = joined["machine_name_normalized"].isna().mean()
            report["machine_master_join_miss_rate"] = float(miss)

    return report


def add_shrunk_rank_targets(df: pd.DataFrame, *, alpha: float) -> pd.DataFrame:
    ranked = df.copy()
    safe_alpha = max(float(alpha), 1e-6)
    ranked["daily_global_avg_diff"] = ranked.groupby("date", sort=False)["avg_diff_coins"].transform("mean")
    ranked["shrunk_avg_diff"] = (
        (ranked["machine_count"] / (ranked["machine_count"] + safe_alpha)) * ranked["avg_diff_coins"]
        + (safe_alpha / (ranked["machine_count"] + safe_alpha)) * ranked["daily_global_avg_diff"]
    )
    ranked["raw_avg_rank"] = ranked.groupby("date", sort=False)["avg_diff_coins"].rank(method="first", ascending=False)
    ranked["shrunk_rank"] = ranked.groupby("date", sort=False)["shrunk_avg_diff"].rank(method="first", ascending=False)
    ranked["is_rank_1"] = (ranked["shrunk_rank"] <= 1).astype(int)
    ranked["is_top_2"] = (ranked["shrunk_rank"] <= 2).astype(int)
    ranked["is_top_3"] = (ranked["shrunk_rank"] <= 3).astype(int)
    ranked["is_top_5"] = (ranked["shrunk_rank"] <= 5).astype(int)
    return ranked


def add_nextday_placeholder_rows(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Timestamp]:
    base = df.copy()
    if base.empty:
        raise ValueError("Cannot create next-day placeholders from empty dataframe")
    next_date = pd.Timestamp(base["date"].max()) + pd.Timedelta(days=1)
    placeholders = []
    reset_columns = [
        "total_games",
        "avg_games",
        "total_diff_coins",
        "avg_diff_coins",
        "win_rate",
        "efficiency",
        "daily_global_avg_diff",
        "shrunk_avg_diff",
        "raw_avg_rank",
        "shrunk_rank",
        *TARGET_COLUMNS,
    ]
    for _, group in base.groupby("machine_name", sort=False):
        row = group.sort_values("date").iloc[-1].to_dict()
        row["date"] = next_date
        for col in reset_columns:
            if col in row:
                row[col] = 0.0
        placeholders.append(row)
    combined = pd.concat([base, pd.DataFrame(placeholders)], ignore_index=True, sort=False)
    combined = combined.sort_values(["machine_name", "date"]).reset_index(drop=True)
    return combined, next_date


def add_machine_type_features(df: pd.DataFrame) -> pd.DataFrame:
    featured = df.copy()
    featured["day_of_week"] = featured["date"].dt.dayofweek
    featured["day_of_month"] = featured["date"].dt.day
    featured["month_progress"] = (featured["day_of_month"] - 1) / featured["date"].dt.daysinmonth
    featured["is_thursday"] = (featured["day_of_week"] == 3).astype(int)
    featured["is_month_end_event"] = (featured["day_of_month"] == featured["date"].dt.daysinmonth).astype(int)
    groups: list[pd.DataFrame] = []
    for _, group in featured.groupby("machine_name", sort=False):
        g = group.sort_values("date").copy()
        g["lag_1_avg_diff_coins"] = g["avg_diff_coins"].shift(1).fillna(0.0)
        g["lag_7_avg_diff_coins"] = g["avg_diff_coins"].shift(7).fillna(0.0)
        g["lag_14_avg_diff_coins"] = g["avg_diff_coins"].shift(14).fillna(0.0)
        g["lag_21_avg_diff_coins"] = g["avg_diff_coins"].shift(21).fillna(0.0)
        g["lag_1_total_games"] = g["total_games"].shift(1).fillna(0.0)
        g["lag_7_total_games"] = g["total_games"].shift(7).fillna(0.0)
        g["lag_14_total_games"] = g["total_games"].shift(14).fillna(0.0)
        g["lag_21_total_games"] = g["total_games"].shift(21).fillna(0.0)
        g["lag_1_efficiency"] = g["efficiency"].shift(1).fillna(0.0)
        g["lag_7_efficiency"] = g["efficiency"].shift(7).fillna(0.0)
        g["lag_14_efficiency"] = g["efficiency"].shift(14).fillna(0.0)
        g["lag_21_efficiency"] = g["efficiency"].shift(21).fillna(0.0)
        g["rolling_avg_diff_7d"] = g["avg_diff_coins"].shift(1).rolling(window=7, min_periods=1).mean().fillna(0.0)
        g["rolling_avg_diff_14d"] = g["avg_diff_coins"].shift(1).rolling(window=14, min_periods=1).mean().fillna(0.0)
        g["rolling_avg_diff_28d"] = g["avg_diff_coins"].shift(1).rolling(window=28, min_periods=1).mean().fillna(0.0)
        g["rolling_avg_games_7d"] = g["avg_games"].shift(1).rolling(window=7, min_periods=1).mean().fillna(0.0)
        g["rolling_avg_games_14d"] = g["avg_games"].shift(1).rolling(window=14, min_periods=1).mean().fillna(0.0)
        g["rolling_avg_games_28d"] = g["avg_games"].shift(1).rolling(window=28, min_periods=1).mean().fillna(0.0)
        g["rolling_avg_efficiency_7d"] = g["efficiency"].shift(1).rolling(window=7, min_periods=1).mean().fillna(0.0)
        g["rolling_avg_efficiency_14d"] = g["efficiency"].shift(1).rolling(window=14, min_periods=1).mean().fillna(0.0)
        g["rolling_avg_efficiency_28d"] = g["efficiency"].shift(1).rolling(window=28, min_periods=1).mean().fillna(0.0)

        g["prior_rank1_rate"] = g["is_rank_1"].shift(1).expanding(min_periods=1).mean().fillna(0.0)
        g["prior_top2_rate"] = g["is_top_2"].shift(1).expanding(min_periods=1).mean().fillna(0.0)
        g["prior_top3_rate"] = g["is_top_3"].shift(1).expanding(min_periods=1).mean().fillna(0.0)
        g["prior_top5_rate"] = g["is_top_5"].shift(1).expanding(min_periods=1).mean().fillna(0.0)
        g["days_since_last_rank1"] = _days_since_last_positive(g["is_rank_1"])
        g["days_since_last_top2"] = _days_since_last_positive(g["is_top_2"])
        g["days_since_last_top3"] = _days_since_last_positive(g["is_top_3"])
        g["days_since_last_top5"] = _days_since_last_positive(g["is_top_5"])
        g["days_since_first_seen"] = np.arange(len(g), dtype=float)

        g["count_delta_1d"] = g["machine_count"].diff().fillna(0.0)
        g["count_delta_7d"] = g["machine_count"].diff(7).fillna(0.0)
        g["count_increase_flag"] = (g["count_delta_1d"] > 0).astype(int)
        g["count_decrease_flag"] = (g["count_delta_1d"] < 0).astype(int)
        g["days_since_last_count_increase"] = _days_since_last_positive(g["count_increase_flag"])
        g["days_since_last_count_decrease"] = _days_since_last_positive(g["count_decrease_flag"])
        g["count_delta_1d_bin"] = _signed_fixed_width_bin(g["count_delta_1d"], width=1.0)
        g["count_delta_7d_bin"] = _signed_fixed_width_bin(g["count_delta_7d"], width=2.0)
        g["days_since_first_seen_bin"] = _fixed_cut_bin(g["days_since_first_seen"], bins=[-0.1, 0.0, 1.0, 3.0, 7.0, 14.0, 30.0, 90.0, 366.0])

        g["same_weekday_rank1_rate"] = (
            g.groupby("day_of_week", sort=False)["is_rank_1"]
            .transform(_prior_mean_transform)
            .fillna(0.0)
        )
        g["same_weekday_top3_rate"] = (
            g.groupby("day_of_week", sort=False)["is_top_3"]
            .transform(_prior_mean_transform)
            .fillna(0.0)
        )
        g["same_weekday_rolling_rank_sum_3"] = (
            g.groupby("day_of_week", sort=False)["shrunk_rank"]
            .transform(lambda s: s.shift(1).rolling(window=3, min_periods=1).sum())
            .fillna(0.0)
        )
        groups.append(g)

    out = pd.concat(groups, ignore_index=True)
    out["event_group"] = out["day_of_month"].map(_event_group_for_day).astype(int)
    out["is_event_day"] = (out["event_group"] > 0).astype(int)
    return out


def get_feature_columns(df: pd.DataFrame) -> list[str]:
    excluded = {
        "date",
        "entity_key",
        "machine_name",
        "daily_global_avg_diff",
        "shrunk_avg_diff",
        "raw_avg_rank",
        "shrunk_rank",
        *TARGET_COLUMNS,
    }
    numeric = [
        col for col in df.columns
        if col not in excluded and pd.api.types.is_numeric_dtype(df[col])
    ]
    return sorted(numeric)


def train_target_model(train_df: pd.DataFrame, *, target: str, feature_columns: list[str], random_state: int = 42) -> TrainedTargetModel:
    if target not in TARGET_COLUMNS:
        raise ValueError(f"Unsupported target: {target}")
    if train_df.empty:
        raise ValueError("train_df is empty")
    X = train_df[feature_columns].fillna(0.0).to_numpy(dtype=float)
    y = train_df[target].to_numpy(dtype=int)
    model = SGDClassifier(
        loss="log_loss",
        penalty="l2",
        alpha=1e-4,
        max_iter=2000,
        tol=1e-3,
        random_state=random_state,
        class_weight="balanced",
    )
    model.fit(X, y)
    train_proba = predict_proba(model, X)
    threshold_stats = optimize_binary_threshold(y, train_proba)
    return TrainedTargetModel(
        target=target,
        threshold=float(threshold_stats["best_threshold"]),
        model=model,
        feature_columns=list(feature_columns),
    )


def predict_proba(model: Any, X: np.ndarray) -> np.ndarray:
    try:
        proba = model.predict_proba(X)
    except NotFittedError:
        raise
    if proba.shape[1] == 1:
        return np.zeros(X.shape[0], dtype=float)
    return proba[:, 1]


def evaluate_prediction_day(day_df: pd.DataFrame, *, target: str, score_col: str, threshold: float) -> dict[str, Any]:
    y_true = day_df[target].to_numpy(dtype=int)
    scores = day_df[score_col].to_numpy(dtype=float)
    y_pred = (scores >= threshold).astype(int)
    group_ids = day_df["date"].to_numpy()
    precision = float(np.sum((y_pred == 1) & (y_true == 1)) / max(np.sum(y_pred == 1), 1))
    recall = float(np.sum((y_pred == 1) & (y_true == 1)) / max(np.sum(y_true == 1), 1))
    f1 = 0.0 if precision + recall == 0.0 else float(2 * precision * recall / (precision + recall))
    return {
        "target": target,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "hit_at_1": float(calculate_hit_at_k(y_true, scores, group_ids, 1)),
        "hit_at_2": float(calculate_hit_at_k(y_true, scores, group_ids, 2)),
        "hit_at_3": float(calculate_hit_at_k(y_true, scores, group_ids, 3)),
        "hit_at_5": float(calculate_hit_at_k(y_true, scores, group_ids, 5)),
        "predicted_count": int(np.sum(y_pred == 1)),
        "base_rate": float(np.mean(y_true)),
    }


def _table_columns(con: sqlite3.Connection, table_name: str) -> set[str]:
    rows = con.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row[1]) for row in rows}


def _days_since_last_positive(flags: pd.Series) -> pd.Series:
    out: list[float] = []
    last_idx: int | None = None
    for i, value in enumerate(flags.astype(int).tolist()):
        out.append(999.0 if last_idx is None else float(i - last_idx))
        if value == 1:
            last_idx = i
    return pd.Series(out, index=flags.index, dtype=float)


def _signed_fixed_width_bin(series: pd.Series, width: float) -> pd.Series:
    safe = pd.to_numeric(series, errors="coerce").fillna(0.0).to_numpy(dtype=float)
    width = max(width, 1e-9)
    return pd.Series(np.floor(safe / width).astype(int), index=series.index)


def _fixed_cut_bin(series: pd.Series, bins: list[float]) -> pd.Series:
    safe = pd.to_numeric(series, errors="coerce").fillna(0.0)
    return pd.cut(safe, bins=bins, labels=False, include_lowest=True).fillna(0).astype(int)


def _prior_mean_transform(series: pd.Series) -> pd.Series:
    shifted = series.shift(1)
    return shifted.expanding(min_periods=1).mean()


def _event_group_for_day(day_of_month: int) -> int:
    if day_of_month in {1, 11, 21}:
        return 1
    if day_of_month in {7, 17, 27}:
        return 2
    return 3 if day_of_month >= 28 else 0
