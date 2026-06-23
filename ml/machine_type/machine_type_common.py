from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.exceptions import NotFittedError
from sklearn.linear_model import SGDClassifier
from xgboost import XGBClassifier, XGBRanker
from xgboost.core import XGBoostError

from ml.evaluators.metrics import calculate_hit_at_k, optimize_binary_threshold
from ml.last_digit.core_ranking import fit_ranker as _fit_ltr_ranker

TARGET_COLUMNS = ("is_rank_1", "is_top_2", "is_top_3", "is_top_5")
TARGET_TO_PRIOR_RATE_COLUMN = {
    "is_rank_1": "prior_rank1_rate",
    "is_top_2": "prior_top2_rate",
    "is_top_3": "prior_top3_rate",
    "is_top_5": "prior_top5_rate",
}
REPORTS_DIR = Path("ml/machine_type/reports")
LEFT_CENSOR_GRACE_DAYS = 30
META_COLUMNS = {"date", "entity_key", "machine_name", *TARGET_COLUMNS}
FORECAST_EXCLUDED_COLUMNS = {
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
    "rank_pct",
}
REALIZED_VALUE_COLUMNS = (
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
)

_XGB_AUTO_BACKEND_CACHE: str | None = None


@dataclass(slots=True)
class TrainedTargetModel:
    target: str
    threshold: float
    model: Any
    feature_columns: list[str]
    model_type: str
    backend_used: str


@dataclass(slots=True)
class SegmentedTargetModels:
    target: str
    global_model: TrainedTargetModel
    segment_models: dict[str, TrainedTargetModel]
    segment_mode: str


@dataclass(slots=True)
class TrainedLtrModel:
    model: XGBRanker
    feature_columns: list[str]
    objective: str
    backend_used: str  # For compatibility with existing reporting framework


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


def _safe_spearman(x: pd.Series, y: pd.Series) -> tuple[float, int]:
    from scipy.stats import spearmanr

    work = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(work) < 2:
        return (float("nan"), int(len(work)))
    if work["x"].nunique(dropna=True) < 2 or work["y"].nunique(dropna=True) < 2:
        return (float("nan"), int(len(work)))
    rho = spearmanr(work["x"].to_numpy(dtype=float), work["y"].to_numpy(dtype=float)).correlation
    return (float(rho), int(len(work)))


def build_machine_name_correlation_summary(
    df: pd.DataFrame,
    feature_cols: Iterable[str],
    target_col: str,
    *,
    group_col: str = "machine_name",
    min_n: int = 10,
) -> pd.DataFrame:
    if group_col not in df.columns:
        raise KeyError(f"missing group_col: {group_col}")
    rows = []
    for feature in feature_cols:
        per_group: list[float] = []
        for _, group in df.groupby(group_col, sort=True):
            rho, n = _safe_spearman(group[feature], group[target_col])
            if np.isfinite(rho) and n >= int(min_n):
                per_group.append(float(rho))
        if per_group:
            series = pd.Series(per_group, dtype=float)
            rows.append(
                {
                    "feature": feature,
                    "target": target_col,
                    "group_col": group_col,
                    "min_n": int(min_n),
                    "n_groups": int(series.size),
                    "mean_rho": float(series.mean()),
                    "median_rho": float(series.median()),
                    "std_rho": float(series.std(ddof=0)) if series.size > 1 else 0.0,
                    "min_rho": float(series.min()),
                    "max_rho": float(series.max()),
                }
            )
        else:
            rows.append(
                {
                    "feature": feature,
                    "target": target_col,
                    "group_col": group_col,
                    "min_n": int(min_n),
                    "n_groups": 0,
                    "mean_rho": float("nan"),
                    "median_rho": float("nan"),
                    "std_rho": float("nan"),
                    "min_rho": float("nan"),
                    "max_rho": float("nan"),
                }
            )
    return pd.DataFrame(rows)


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


def load_daily_hall_summary_slim(db_path: Path) -> pd.DataFrame:
    con = sqlite3.connect(db_path)
    try:
        summary_columns = _table_columns(con, "daily_hall_summary")
        select_columns = [col for col in ("date", "win_rate", "avg_diff_per_machine") if col in summary_columns]
        if "date" not in select_columns:
            select_columns.insert(0, "date")
        df = pd.read_sql_query(
            f"""
            SELECT
                {", ".join(f"d.{col}" for col in select_columns)}
            FROM daily_hall_summary d
            ORDER BY d.date
            """,
            con,
        )
    finally:
        con.close()
    if df.empty:
        raise ValueError("daily_hall_summary returned no rows")
    for column in ("win_rate", "avg_diff_per_machine"):
        if column not in df.columns:
            df[column] = 0.0
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


def load_machine_name_daily_segments(db_path: Path) -> pd.DataFrame:
    con = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(
            """
            SELECT
                m.date,
                m.machine_name,
                m.machine_number,
                COALESCE(mm.jug_flag, 0) AS jug_flag,
                COALESCE(mm.hana_flag, 0) AS hana_flag,
                COALESCE(mm.oki_flag, 0) AS oki_flag,
                COALESCE(mm.bt_flag, 0) AS bt_flag
            FROM machine_detailed_results m
            LEFT JOIN machine_master mm
              ON m.machine_name = mm.machine_name_normalized
            """,
            con,
        )
    finally:
        con.close()
    if df.empty:
        return pd.DataFrame(columns=["date", "machine_name", "floor_bucket", "atype_bucket"])

    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["date", "machine_name"]).copy()
    floor_head = df["machine_number"].astype(str).str[0]
    df["floor_bucket"] = np.where(floor_head == "2", "2F", np.where(floor_head == "3", "3F", "UNK"))
    df["atype_bucket"] = np.where(
        (df["jug_flag"].astype(int) == 1)
        | (df["hana_flag"].astype(int) == 1)
        | (df["bt_flag"].astype(int) == 1),
        "A",
        "N",
    )
    counts = (
        df.groupby(["date", "machine_name", "floor_bucket", "atype_bucket"], sort=True)
        .size()
        .reset_index(name="n")
        .sort_values(["date", "machine_name", "n", "floor_bucket", "atype_bucket"], ascending=[True, True, False, True, True])
    )
    dominant = counts.groupby(["date", "machine_name"], sort=False).head(1).copy()
    return dominant[["date", "machine_name", "floor_bucket", "atype_bucket"]].reset_index(drop=True)


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


def attach_machine_master_flags(base_df: pd.DataFrame, machine_master_df: pd.DataFrame) -> pd.DataFrame:
    out = base_df.copy()
    if machine_master_df.empty:
        out["jug_flag"] = 0
        out["hana_flag"] = 0
        out["oki_flag"] = 0
        out["bt_flag"] = 0
    else:
        ref = machine_master_df.copy()
        ref["machine_name"] = ref["machine_name_normalized"].astype(str)
        for col in ("jug_flag", "hana_flag", "oki_flag", "bt_flag"):
            if col not in ref.columns:
                ref[col] = 0
        out = out.merge(
            ref[["machine_name", "jug_flag", "hana_flag", "oki_flag", "bt_flag"]].drop_duplicates(),
            on="machine_name",
            how="left",
        )
        for col in ("jug_flag", "hana_flag", "oki_flag", "bt_flag"):
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int)
    out["is_a_type"] = (
        (out["jug_flag"] == 1) | (out["hana_flag"] == 1) | (out["bt_flag"] == 1)
    ).astype(int)
    return out


def attach_daily_segments(base_df: pd.DataFrame, daily_segments_df: pd.DataFrame) -> pd.DataFrame:
    out = base_df.copy()
    if daily_segments_df.empty:
        fallback_atype = pd.Series(
            np.where(out.get("is_a_type", pd.Series(np.zeros(len(out), dtype=int), index=out.index)).astype(int) == 1, "A", "N"),
            index=out.index,
            dtype="object",
        )
        out["floor_bucket"] = "UNK"
        out["atype_bucket"] = fallback_atype
    else:
        seg = daily_segments_df.copy()
        seg["machine_name"] = seg["machine_name"].astype(str)
        out = out.merge(
            seg[["date", "machine_name", "floor_bucket", "atype_bucket"]],
            on=["date", "machine_name"],
            how="left",
        )
        fallback_atype = pd.Series(
            np.where(out.get("is_a_type", pd.Series(np.zeros(len(out), dtype=int), index=out.index)).astype(int) == 1, "A", "N"),
            index=out.index,
            dtype="object",
        )
        out["floor_bucket"] = out["floor_bucket"].fillna("UNK")
        out["atype_bucket"] = out["atype_bucket"].fillna(fallback_atype)
    out["segment_floor2"] = out["floor_bucket"].astype(str)
    out["segment_type2"] = out["atype_bucket"].astype(str)
    out["segment_floor_type4"] = out["segment_floor2"] + "_" + out["segment_type2"]
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
        if "is_left_censored" in prepared.columns:
            report["left_censored_machine_count"] = int(
                prepared.loc[prepared["is_left_censored"].eq(1), "machine_name"].nunique()
            )
        if "new_machine_flag_effective" in prepared.columns:
            report["effective_new_machine_rows"] = int(prepared["new_machine_flag_effective"].sum())
        if "segment_floor2" in prepared.columns:
            report["segment_floor2_counts"] = {
                str(k): int(v) for k, v in prepared["segment_floor2"].value_counts(dropna=False).to_dict().items()
            }
        if "segment_floor_type4" in prepared.columns:
            report["segment_floor_type4_counts"] = {
                str(k): int(v) for k, v in prepared["segment_floor_type4"].value_counts(dropna=False).to_dict().items()
            }

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


def build_backtest_frame_for_pred_date(
    ranked_df: pd.DataFrame,
    *,
    pred_date: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    pred_ts = pd.Timestamp(pred_date)
    history = ranked_df.loc[ranked_df["date"] < pred_ts].copy()
    truth = ranked_df.loc[ranked_df["date"] == pred_ts].copy()
    if history.empty or truth.empty:
        return pd.DataFrame(), pd.DataFrame(), {"truth_entities": int(len(truth["machine_name"].unique())) if not truth.empty else 0, "known_entities": 0, "unseen_entities": 0}

    latest_history = (
        history.sort_values(["machine_name", "date"])
        .groupby("machine_name", sort=False)
        .tail(1)
        .copy()
    )
    placeholders = latest_history.copy()
    placeholders["date"] = pred_ts
    for col in REALIZED_VALUE_COLUMNS:
        if col in placeholders.columns:
            placeholders[col] = 0.0

    synthetic = pd.concat([history, placeholders], ignore_index=True, sort=False)
    synthetic = synthetic.sort_values(["machine_name", "date"]).reset_index(drop=True)
    synthetic_featured = add_machine_type_features(synthetic)
    pred_rows = synthetic_featured.loc[synthetic_featured["date"] == pred_ts].copy()

    known_machine_names = set(pred_rows["machine_name"].astype(str).tolist())
    truth_known = truth.loc[truth["machine_name"].astype(str).isin(known_machine_names)].copy()
    if truth_known.empty:
        return pd.DataFrame(), pd.DataFrame(), {"truth_entities": int(truth["machine_name"].nunique()), "known_entities": 0, "unseen_entities": int(truth["machine_name"].nunique())}

    pred_rows = pred_rows.loc[pred_rows["machine_name"].astype(str).isin(set(truth_known["machine_name"].astype(str)))].copy()
    pred_rows = pred_rows.sort_values("machine_name").reset_index(drop=True)
    truth_known = truth_known.sort_values("machine_name").reset_index(drop=True)
    unseen_entities = int(truth["machine_name"].nunique() - truth_known["machine_name"].nunique())
    coverage = {
        "truth_entities": int(truth["machine_name"].nunique()),
        "known_entities": int(truth_known["machine_name"].nunique()),
        "unseen_entities": unseen_entities,
    }
    return synthetic_featured, truth_known, coverage


def add_machine_type_features(df: pd.DataFrame, *, left_censor_grace_days: int = LEFT_CENSOR_GRACE_DAYS) -> pd.DataFrame:
    featured = df.copy()
    featured["day_of_week"] = featured["date"].dt.dayofweek
    featured["day_of_month"] = featured["date"].dt.day
    featured["month_progress"] = (featured["day_of_month"] - 1) / featured["date"].dt.daysinmonth
    featured["is_thursday"] = (featured["day_of_week"] == 3).astype(int)
    featured["is_month_end_event"] = (featured["day_of_month"] == featured["date"].dt.daysinmonth).astype(int)
    floor2 = featured["segment_floor2"].astype(str) if "segment_floor2" in featured.columns else pd.Series(["UNK"] * len(featured), index=featured.index)
    type2 = featured["segment_type2"].astype(str) if "segment_type2" in featured.columns else pd.Series(["N"] * len(featured), index=featured.index)
    featured["floor_is_2f"] = (floor2 == "2F").astype(int)
    featured["floor_is_3f"] = (floor2 == "3F").astype(int)
    featured["atype_is_a"] = (type2 == "A").astype(int)
    featured["atype_is_n"] = (type2 == "N").astype(int)
    min_date = pd.Timestamp(featured["date"].min())
    cutoff_date = min_date + pd.Timedelta(days=max(int(left_censor_grace_days), 0))
    first_seen = featured.groupby("machine_name", sort=False)["date"].transform("min")
    featured["is_left_censored"] = (first_seen <= cutoff_date).astype(int)
    groups: list[pd.DataFrame] = []
    for _, group in featured.groupby("machine_name", sort=False):
        g = group.sort_values("date").copy()
        g["lag_1_avg_diff_coins"] = g["avg_diff_coins"].shift(1).fillna(0.0)
        g["lag_7_avg_diff_coins"] = g["avg_diff_coins"].shift(7).fillna(0.0)
        g["lag_14_avg_diff_coins"] = g["avg_diff_coins"].shift(14).fillna(0.0)
        g["lag_21_avg_diff_coins"] = g["avg_diff_coins"].shift(21).fillna(0.0)
        g["lag_3_avg_diff_coins"] = g["avg_diff_coins"].shift(3).fillna(0.0)
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
        g["rolling_std_diff_7d"] = g["avg_diff_coins"].shift(1).rolling(window=7, min_periods=2).std().fillna(0.0)
        g["rolling_std_diff_14d"] = g["avg_diff_coins"].shift(1).rolling(window=14, min_periods=2).std().fillna(0.0)
        g["rolling_std_efficiency_7d"] = g["efficiency"].shift(1).rolling(window=7, min_periods=2).std().fillna(0.0)
        g["rolling_std_efficiency_14d"] = g["efficiency"].shift(1).rolling(window=14, min_periods=2).std().fillna(0.0)
        g["rolling_avg_games_7d"] = g["avg_games"].shift(1).rolling(window=7, min_periods=1).mean().fillna(0.0)
        g["rolling_avg_games_14d"] = g["avg_games"].shift(1).rolling(window=14, min_periods=1).mean().fillna(0.0)
        g["rolling_avg_games_28d"] = g["avg_games"].shift(1).rolling(window=28, min_periods=1).mean().fillna(0.0)
        g["rolling_avg_efficiency_7d"] = g["efficiency"].shift(1).rolling(window=7, min_periods=1).mean().fillna(0.0)
        g["rolling_avg_efficiency_14d"] = g["efficiency"].shift(1).rolling(window=14, min_periods=1).mean().fillna(0.0)
        g["rolling_avg_efficiency_28d"] = g["efficiency"].shift(1).rolling(window=28, min_periods=1).mean().fillna(0.0)
        g["ewm_avg_diff_7d"] = g["avg_diff_coins"].shift(1).ewm(span=7, adjust=False, min_periods=1).mean().fillna(0.0)
        g["ewm_avg_diff_21d"] = g["avg_diff_coins"].shift(1).ewm(span=21, adjust=False, min_periods=1).mean().fillna(0.0)
        g["ewm_diff_momentum_7v21"] = g["ewm_avg_diff_7d"] - g["ewm_avg_diff_21d"]
        g["ewm_efficiency_7d"] = g["efficiency"].shift(1).ewm(span=7, adjust=False, min_periods=1).mean().fillna(0.0)
        g["ewm_efficiency_21d"] = g["efficiency"].shift(1).ewm(span=21, adjust=False, min_periods=1).mean().fillna(0.0)
        g["ewm_efficiency_momentum_7v21"] = g["ewm_efficiency_7d"] - g["ewm_efficiency_21d"]

        g["prior_rank1_rate"] = g["is_rank_1"].shift(1).expanding(min_periods=1).mean().fillna(0.0)
        g["prior_top2_rate"] = g["is_top_2"].shift(1).expanding(min_periods=1).mean().fillna(0.0)
        g["prior_top3_rate"] = g["is_top_3"].shift(1).expanding(min_periods=1).mean().fillna(0.0)
        g["prior_top5_rate"] = g["is_top_5"].shift(1).expanding(min_periods=1).mean().fillna(0.0)
        for short_name, target_col in (
            ("rank1", "is_rank_1"),
            ("top2", "is_top_2"),
            ("top3", "is_top_3"),
            ("top5", "is_top_5"),
        ):
            shifted = g[target_col].shift(1)
            wins = shifted.expanding(min_periods=1).sum().fillna(0.0)
            trials = shifted.expanding(min_periods=1).count().fillna(0.0)
            g[f"prior_{short_name}_rate_smooth"] = (wins + 1.0) / (trials + 2.0)
            g[f"prior_{short_name}_confidence"] = trials / (trials + 10.0)
        g["days_since_last_rank1"] = _days_since_last_positive_calendar(g["date"], g["is_rank_1"])
        g["days_since_last_top2"] = _days_since_last_positive_calendar(g["date"], g["is_top_2"])
        g["days_since_last_top3"] = _days_since_last_positive_calendar(g["date"], g["is_top_3"])
        g["days_since_last_top5"] = _days_since_last_positive_calendar(g["date"], g["is_top_5"])
        g["days_since_first_seen"] = np.arange(len(g), dtype=float)
        g["days_since_first_seen_raw"] = g["days_since_first_seen"]
        g["new_machine_flag_raw"] = (g["days_since_first_seen"] == 0.0).astype(int)
        g["new_machine_flag_effective"] = (
            (g["days_since_first_seen"] == 0.0) & (g["is_left_censored"] == 0)
        ).astype(int)
        g["days_since_first_seen_effective"] = np.where(
            g["is_left_censored"] == 1,
            np.nan,
            g["days_since_first_seen"],
        )

        g["count_delta_1d"] = g["machine_count"].diff().fillna(0.0)
        g["count_delta_3d"] = g["machine_count"].diff(3).fillna(0.0)
        g["count_delta_7d"] = g["machine_count"].diff(7).fillna(0.0)
        g["count_delta_14d"] = g["machine_count"].diff(14).fillna(0.0)
        g["count_increase_flag"] = (g["count_delta_1d"] > 0).astype(int)
        g["count_decrease_flag"] = (g["count_delta_1d"] < 0).astype(int)
        g["days_since_last_count_increase"] = _days_since_last_positive_calendar(g["date"], g["count_increase_flag"])
        g["days_since_last_count_decrease"] = _days_since_last_positive_calendar(g["date"], g["count_decrease_flag"])
        g["count_delta_1d_bin"] = _signed_fixed_width_bin(g["count_delta_1d"], width=1.0)
        g["count_delta_7d_bin"] = _signed_fixed_width_bin(g["count_delta_7d"], width=2.0)
        g["days_since_first_seen_bin"] = _fixed_cut_bin(g["days_since_first_seen"], bins=[-0.1, 0.0, 1.0, 3.0, 7.0, 14.0, 30.0, 90.0, 366.0])
        g.loc[g["is_left_censored"] == 1, "days_since_first_seen_bin"] = -1

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
        g["same_weekday_top2_rate"] = (
            g.groupby("day_of_week", sort=False)["is_top_2"]
            .transform(_prior_mean_transform)
            .fillna(0.0)
        )
        g["same_weekday_top5_rate"] = (
            g.groupby("day_of_week", sort=False)["is_top_5"]
            .transform(_prior_mean_transform)
            .fillna(0.0)
        )
        g["same_weekday_rolling_rank_sum_3"] = (
            g.groupby("day_of_week", sort=False)["shrunk_rank"]
            .transform(lambda s: s.shift(1).rolling(window=3, min_periods=1).sum())
            .fillna(0.0)
        )
        g["diff_delta_1_vs_7"] = g["lag_1_avg_diff_coins"] - g["lag_7_avg_diff_coins"]
        g["diff_delta_1_vs_14"] = g["lag_1_avg_diff_coins"] - g["lag_14_avg_diff_coins"]
        g["eff_delta_1_vs_7"] = g["lag_1_efficiency"] - g["lag_7_efficiency"]
        g["eff_delta_1_vs_14"] = g["lag_1_efficiency"] - g["lag_14_efficiency"]
        groups.append(g)

    out = pd.concat(groups, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"], errors="coerce")

    # Cross-sectional normalization from prior-only lag features.
    cross_cols = (
        "lag_1_avg_diff_coins",
        "lag_7_avg_diff_coins",
        "rolling_avg_diff_7d",
        "rolling_avg_diff_14d",
        "lag_1_efficiency",
        "rolling_avg_efficiency_7d",
        # Additional windows and EWM for richer cross-sectional signals.
        "lag_3_avg_diff_coins",
        "lag_14_avg_diff_coins",
        "rolling_avg_diff_28d",
        "rolling_avg_efficiency_14d",
        "rolling_avg_efficiency_28d",
        "ewm_avg_diff_7d",
        "ewm_avg_diff_21d",
        "ewm_efficiency_7d",
        "rolling_avg_games_7d",
        "rolling_avg_games_14d",
    )
    cross_features: dict[str, pd.Series] = {}
    for col in cross_cols:
        if col not in out.columns:
            continue
        day_mean = out.groupby("date", sort=False)[col].transform("mean")
        day_std = out.groupby("date", sort=False)[col].transform("std").replace(0.0, np.nan).fillna(1.0)
        cross_features[f"{col}_vs_mean"] = out[col] - day_mean
        cross_features[f"{col}_zscore"] = (out[col] - day_mean) / day_std
        cross_features[f"{col}_rank_pct"] = out.groupby("date", sort=False)[col].rank(method="average", pct=True)
    if cross_features:
        out = pd.concat([out, pd.DataFrame(cross_features, index=out.index)], axis=1)

    # Hall-level context from lag values.
    daily_ctx = (
        out.groupby("date", sort=False)
        .agg(
            hall_avg_diff_yesterday=("lag_1_avg_diff_coins", "mean"),
            hall_total_games_yesterday=("lag_1_total_games", "sum"),
            hall_avg_efficiency_yesterday=("lag_1_efficiency", "mean"),
            hall_machine_type_count=("machine_name", "nunique"),
            hall_diff_spread_yesterday=("lag_1_avg_diff_coins", lambda x: float(x.max() - x.min()) if len(x) else 0.0),
        )
        .reset_index()
    )
    out = out.merge(daily_ctx, on="date", how="left")

    # Rank-based trend features (use shifted history only).
    daily_entity_count = out.groupby("date", sort=False)["machine_name"].transform("nunique").clip(lower=1).astype(float)
    out["rank_pct"] = (out["shrunk_rank"] / daily_entity_count).clip(lower=0.0, upper=1.0)
    trend_groups: list[pd.DataFrame] = []
    for _, group in out.groupby("machine_name", sort=False):
        g = group.sort_values("date").copy()
        shifted_rank_pct = g["rank_pct"].shift(1)
        g["prior_avg_rank_pct"] = shifted_rank_pct.expanding(min_periods=1).mean().fillna(0.5)
        g["rank_pct_std_14d"] = shifted_rank_pct.rolling(window=14, min_periods=3).std().fillna(0.0)
        g["rank_pct_rolling_7d"] = shifted_rank_pct.rolling(window=7, min_periods=1).mean().fillna(0.5)
        g["rank_pct_rolling_28d"] = shifted_rank_pct.rolling(window=28, min_periods=1).mean().fillna(0.5)
        g["rank_pct_trend_7vs28"] = g["rank_pct_rolling_7d"] - g["rank_pct_rolling_28d"]
        g["same_weekday_avg_rank_pct"] = (
            g.groupby("day_of_week", sort=False)["rank_pct"]
            .transform(_prior_mean_transform)
            .fillna(0.5)
        )
        g["ewm_rank_7d"] = shifted_rank_pct.ewm(span=7, adjust=False, min_periods=1).mean().fillna(0.5)
        g["ewm_rank_30d"] = shifted_rank_pct.ewm(span=30, adjust=False, min_periods=1).mean().fillna(0.5)
        g["ewm_rank_momentum_7v30"] = g["ewm_rank_7d"] - g["ewm_rank_30d"]
        g["rank_pct_avg_1m"] = shifted_rank_pct.rolling(window=30, min_periods=5).mean()
        g["rank_pct_avg_2m"] = g["rank_pct"].shift(31).rolling(window=30, min_periods=5).mean()
        g["rank_pct_avg_3m"] = g["rank_pct"].shift(61).rolling(window=30, min_periods=5).mean()
        g["rank_trend_1m_available"] = (g["rank_pct_avg_1m"].notna() & g["rank_pct_avg_2m"].notna()).astype(int)
        g["rank_trend_2m_available"] = (g["rank_pct_avg_2m"].notna() & g["rank_pct_avg_3m"].notna()).astype(int)
        g["rank_trend_1m_vs_2m"] = (g["rank_pct_avg_1m"] - g["rank_pct_avg_2m"]).fillna(0.0)
        g["rank_trend_2m_vs_3m"] = (g["rank_pct_avg_2m"] - g["rank_pct_avg_3m"]).fillna(0.0)
        g["rank_trend_acceleration"] = g["rank_trend_1m_vs_2m"] - g["rank_trend_2m_vs_3m"]
        g["rank_pct_avg_1m"] = g["rank_pct_avg_1m"].fillna(0.5)
        g["rank_pct_avg_2m"] = g["rank_pct_avg_2m"].fillna(0.5)
        g["rank_pct_avg_3m"] = g["rank_pct_avg_3m"].fillna(0.5)
        trend_groups.append(g)
    out = pd.concat(trend_groups, ignore_index=True)

    out["event_group"] = out["day_of_month"].map(_event_group_for_day).astype(int)
    out["is_event_day"] = (out["event_group"] > 0).astype(int)
    return out


def get_feature_columns(df: pd.DataFrame) -> list[str]:
    excluded = set(META_COLUMNS).union(FORECAST_EXCLUDED_COLUMNS)
    numeric = [
        col for col in df.columns
        if col not in excluded
        and pd.api.types.is_numeric_dtype(df[col])
    ]
    return sorted(numeric)


def resolve_segment_column(segment_mode: str) -> str:
    mode = str(segment_mode).strip().lower()
    if mode == "global":
        return ""
    if mode == "floor2":
        return "segment_floor2"
    if mode == "type2":
        return "segment_type2"
    if mode == "floor_type4":
        return "segment_floor_type4"
    raise ValueError(f"Unsupported segment_mode: {segment_mode}")


def train_segmented_target_models(
    train_df: pd.DataFrame,
    *,
    target: str,
    feature_columns: list[str],
    random_state: int,
    model_type: str,
    gpu_backend: str,
    segment_mode: str,
    min_segment_days: int,
    min_segment_rows: int,
) -> SegmentedTargetModels:
    global_model = train_target_model(
        train_df,
        target=target,
        feature_columns=feature_columns,
        random_state=random_state,
        model_type=model_type,
        gpu_backend=gpu_backend,
    )
    segment_col = resolve_segment_column(segment_mode)
    segment_models: dict[str, TrainedTargetModel] = {}
    if segment_col:
        for seg_value, g in train_df.groupby(segment_col, sort=True):
            seg_key = str(seg_value)
            if g["date"].nunique() < int(min_segment_days) or len(g) < int(min_segment_rows):
                continue
            y = g[target].to_numpy(dtype=int)
            if len(np.unique(y)) < 2:
                continue
            try:
                seg_model = train_target_model(
                    g,
                    target=target,
                    feature_columns=feature_columns,
                    random_state=random_state,
                    model_type=model_type,
                    gpu_backend=gpu_backend,
                )
                segment_models[seg_key] = seg_model
            except Exception:
                continue
    return SegmentedTargetModels(
        target=target,
        global_model=global_model,
        segment_models=segment_models,
        segment_mode=str(segment_mode),
    )


def predict_segmented_proba(
    pred_df: pd.DataFrame,
    *,
    trained: SegmentedTargetModels,
    segment_blend_weight: float = 1.0,
) -> tuple[np.ndarray, np.ndarray]:
    work_df = pred_df.reset_index(drop=True).copy()
    segment_col = resolve_segment_column(trained.segment_mode)
    feature_columns = trained.global_model.feature_columns
    out = np.zeros(len(work_df), dtype=float)
    used_segment = np.zeros(len(work_df), dtype=int)
    blend = min(max(float(segment_blend_weight), 0.0), 1.0)
    if not segment_col:
        X = work_df[feature_columns].fillna(0.0).to_numpy(dtype=float)
        out[:] = predict_proba(trained.global_model.model, X)
        return out, used_segment

    for seg_value, idx in work_df.groupby(segment_col, sort=False).groups.items():
        seg_key = str(seg_value)
        row_idx = list(idx)
        rows = work_df.iloc[row_idx]
        global_model = trained.global_model
        global_scores = predict_proba(global_model.model, rows[feature_columns].fillna(0.0).to_numpy(dtype=float))
        model = trained.segment_models.get(seg_key)
        if model is None:
            out[row_idx] = global_scores
            used_segment[row_idx] = 0
            continue
        X = rows[feature_columns].fillna(0.0).to_numpy(dtype=float)
        seg_scores = predict_proba(model.model, X)
        out[row_idx] = (blend * seg_scores) + ((1.0 - blend) * global_scores)
        used_segment[row_idx] = 1
    return out, used_segment


def train_target_model(
    train_df: pd.DataFrame,
    *,
    target: str,
    feature_columns: list[str],
    random_state: int = 42,
    model_type: str = "sgd",
    gpu_backend: str = "auto",
) -> TrainedTargetModel:
    if target not in TARGET_COLUMNS:
        raise ValueError(f"Unsupported target: {target}")
    if train_df.empty:
        raise ValueError("train_df is empty")
    fit_df, cal_df = _split_fit_and_calibration(train_df, target=target)
    X_fit = fit_df[feature_columns].fillna(0.0).to_numpy(dtype=float)
    y_fit = fit_df[target].to_numpy(dtype=int)
    requested_model_type = str(model_type).strip().lower()
    requested_backend = str(gpu_backend).strip().lower()
    if requested_model_type == "sgd":
        model = SGDClassifier(
            loss="log_loss",
            penalty="l2",
            alpha=1e-4,
            max_iter=2000,
            tol=1e-3,
            random_state=random_state,
            class_weight="balanced",
        )
        model.fit(X_fit, y_fit)
        backend_used = "cpu"
    elif requested_model_type == "xgb":
        model, backend_used = _fit_xgb_classifier(
            X_fit,
            y_fit,
            random_state=random_state,
            gpu_backend=requested_backend,
        )
    else:
        raise ValueError(f"Unsupported model_type: {model_type}")
    X_cal = cal_df[feature_columns].fillna(0.0).to_numpy(dtype=float)
    y_cal = cal_df[target].to_numpy(dtype=int)
    cal_proba = predict_proba(model, X_cal)
    threshold_stats = optimize_binary_threshold(y_cal, cal_proba)
    return TrainedTargetModel(
        target=target,
        threshold=float(threshold_stats["best_threshold"]),
        model=model,
        feature_columns=list(feature_columns),
        model_type=requested_model_type,
        backend_used=backend_used,
    )


def predict_proba(model: Any, X: np.ndarray) -> np.ndarray:
    try:
        proba = model.predict_proba(X)
    except NotFittedError:
        raise
    if proba.shape[1] == 1:
        return np.zeros(X.shape[0], dtype=float)
    return proba[:, 1]


def train_ltr_model(
    train_df: pd.DataFrame,
    *,
    feature_columns: list[str],
    random_state: int,
    decay_lambda: float | None = None,
    objective: str = "rank:ndcg",
) -> TrainedLtrModel:
    """Train an XGBRanker grouped by date (all machine types on the same day form one group).

    Precondition: train_df must have been processed by add_machine_type_features() so that
    rank_pct (0=best, 1=worst) is present. shrunk_rank is used as a fallback.
    Rows are sorted by [date, machine_name] internally before fitting.
    """
    if train_df.empty:
        raise ValueError("train_df is empty")
    sorted_df = train_df.sort_values(["date", "machine_name"]).reset_index(drop=True)
    ltr_relevance = _build_ltr_relevance_labels(sorted_df)
    X_train = sorted_df[feature_columns].fillna(0.0)
    y_train = ltr_relevance.to_numpy(dtype=int)
    ranker = _fit_ltr_ranker(
        X_train,
        y_train,
        sorted_df["date"],
        objective=objective,
        random_state=random_state,
        decay_lambda=decay_lambda,
    )
    return TrainedLtrModel(
        model=ranker,
        feature_columns=list(feature_columns),
        objective=objective,
        backend_used="cpu",
    )


def predict_ltr_scores(
    pred_df: pd.DataFrame,
    *,
    trained: TrainedLtrModel,
) -> np.ndarray:
    """Return raw LTR scores (higher = better ranked machine type)."""
    X = pred_df[trained.feature_columns].fillna(0.0).to_numpy(dtype=float)
    return trained.model.predict(X)


def _build_ltr_relevance_labels(df: pd.DataFrame) -> pd.Series:
    """Build integer relevance labels per day for XGBRanker.

    Higher label means more relevant. Labels are in [0, 4].
    """
    work = df.copy()
    if "shrunk_rank" not in work.columns:
        raise ValueError("shrunk_rank is required for LTR relevance labels")
    # 0(best)..1(worst)
    entity_count = work.groupby("date", sort=False)["machine_name"].transform("nunique").clip(lower=1).astype(float)
    rank_pct = (work["shrunk_rank"].astype(float) / entity_count).clip(lower=0.0, upper=1.0)
    # Discrete gain labels. Integer is required by xgboost ranking objectives.
    labels = pd.Series(0, index=work.index, dtype=int)
    labels = labels.mask(rank_pct <= 0.20, 4)
    labels = labels.mask((rank_pct > 0.20) & (rank_pct <= 0.40), 3)
    labels = labels.mask((rank_pct > 0.40) & (rank_pct <= 0.60), 2)
    labels = labels.mask((rank_pct > 0.60) & (rank_pct <= 0.80), 1)
    # Keep worst bucket as 0.
    return labels.astype(int)


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


def blend_with_prior_rate(
    df: pd.DataFrame,
    *,
    target: str,
    proba: np.ndarray,
    prior_blend_weight: float,
) -> np.ndarray:
    weight = min(max(float(prior_blend_weight), 0.0), 1.0)
    if weight <= 0.0:
        return np.asarray(proba, dtype=float)
    prior_col = TARGET_TO_PRIOR_RATE_COLUMN.get(str(target), "")
    if not prior_col or prior_col not in df.columns:
        return np.asarray(proba, dtype=float)
    prior = pd.to_numeric(df[prior_col], errors="coerce").fillna(0.0).clip(0.0, 1.0).to_numpy(dtype=float)
    score = np.asarray(proba, dtype=float)
    return ((1.0 - weight) * score) + (weight * prior)


def _table_columns(con: sqlite3.Connection, table_name: str) -> set[str]:
    rows = con.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row[1]) for row in rows}


def _days_since_last_positive(flags: pd.Series) -> pd.Series:
    # Backward-compatible wrapper (legacy callers). Prefer _days_since_last_positive_calendar.
    dummy_dates = pd.Series(pd.date_range("2000-01-01", periods=len(flags), freq="D"), index=flags.index)
    return _days_since_last_positive_calendar(dummy_dates, flags)


def _days_since_last_positive_calendar(dates: pd.Series, flags: pd.Series) -> pd.Series:
    out: list[float] = []
    last_positive: pd.Timestamp | None = None
    date_series = pd.to_datetime(dates, errors="coerce")
    flag_series = flags.astype(int)
    for current_date, flag in zip(date_series, flag_series, strict=False):
        if pd.isna(current_date):
            out.append(365.0 if last_positive is None else 0.0)
            continue
        out.append(365.0 if last_positive is None else float((pd.Timestamp(current_date) - last_positive).days))
        if flag == 1:
            last_positive = pd.Timestamp(current_date)
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


def _calendar_shift_window_mean(
    dates: pd.Series,
    values: pd.Series,
    *,
    lag_days: int,
    window_days: int,
) -> pd.Series:
    date_vals = pd.to_datetime(dates, errors="coerce")
    value_vals = pd.to_numeric(values, errors="coerce")
    out = np.full(len(value_vals), np.nan, dtype=float)
    lag = pd.Timedelta(days=max(int(lag_days), 0))
    width = max(int(window_days), 1)
    for i, current_date in enumerate(date_vals):
        if pd.isna(current_date):
            continue
        end = pd.Timestamp(current_date) - lag
        start = end - pd.Timedelta(days=width - 1)
        mask = (date_vals >= start) & (date_vals <= end)
        if not mask.any():
            continue
        segment = value_vals.loc[mask]
        if segment.notna().any():
            out[i] = float(segment.mean(skipna=True))
    return pd.Series(out, index=values.index, dtype=float)


def _event_group_for_day(day_of_month: int) -> int:
    if day_of_month in {1, 11, 21}:
        return 1
    if day_of_month in {7, 17, 27}:
        return 2
    return 3 if day_of_month >= 28 else 0


def _split_fit_and_calibration(train_df: pd.DataFrame, *, target: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    if train_df.empty:
        raise ValueError("train_df is empty")
    work = train_df.sort_values(["date", "machine_name"]).copy()
    unique_dates = sorted(pd.to_datetime(work["date"].unique()))
    if len(unique_dates) < 2:
        fit_df = work
        cal_df = work.tail(min(len(work), 200))
    else:
        split_idx = max(1, int(len(unique_dates) * 0.85))
        split_idx = min(split_idx, len(unique_dates) - 1)
        fit_dates = set(unique_dates[:split_idx])
        cal_dates = set(unique_dates[split_idx:])
        fit_df = work.loc[work["date"].isin(fit_dates)].copy()
        cal_df = work.loc[work["date"].isin(cal_dates)].copy()
        if cal_df.empty:
            cal_df = work.tail(min(len(work), 200)).copy()
    # Ensure model-fit target has at least two classes.
    if fit_df[target].nunique() < 2:
        fit_df = work
    # Ensure calibration target has at least two classes when possible.
    if cal_df[target].nunique() < 2:
        if work[target].nunique() >= 2:
            cal_df = work.copy()
        else:
            cal_df = fit_df.copy()
    return fit_df, cal_df


def _fit_xgb_classifier(
    X: np.ndarray,
    y: np.ndarray,
    *,
    random_state: int,
    gpu_backend: str,
) -> tuple[XGBClassifier, str]:
    global _XGB_AUTO_BACKEND_CACHE
    backend = gpu_backend if gpu_backend in {"auto", "cpu", "cuda", "gpu_hist"} else "auto"
    if backend == "cpu":
        cpu_model = _build_xgb_classifier(random_state=random_state, backend="cpu")
        cpu_model.fit(X, y)
        return cpu_model, "cpu"

    if backend == "auto" and _XGB_AUTO_BACKEND_CACHE is not None:
        preferred_backend = _XGB_AUTO_BACKEND_CACHE
    else:
        preferred_backend = "cuda" if backend in {"auto", "cuda"} else "gpu_hist"
    gpu_model = _build_xgb_classifier(random_state=random_state, backend=preferred_backend)
    try:
        gpu_model.fit(X, y)
        if backend == "auto":
            _XGB_AUTO_BACKEND_CACHE = preferred_backend
        return gpu_model, preferred_backend
    except XGBoostError:
        if backend != "auto":
            raise
        cpu_model = _build_xgb_classifier(random_state=random_state, backend="cpu")
        cpu_model.fit(X, y)
        _XGB_AUTO_BACKEND_CACHE = "cpu"
        return cpu_model, "cpu_fallback"


def _build_xgb_classifier(*, random_state: int, backend: str) -> XGBClassifier:
    params: dict[str, Any] = {
        "objective": "binary:logistic",
        "eval_metric": "logloss",
        "n_estimators": 48,
        "learning_rate": 0.1,
        "max_depth": 3,
        "min_child_weight": 2.0,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "reg_lambda": 1.0,
        "random_state": random_state,
        "n_jobs": -1,
        "verbosity": 0,
    }
    if backend == "cpu":
        params["tree_method"] = "hist"
    elif backend == "cuda":
        params["tree_method"] = "hist"
        params["device"] = "cuda"
    elif backend == "gpu_hist":
        params["tree_method"] = "gpu_hist"
    else:
        raise ValueError(f"Unsupported xgb backend: {backend}")
    return XGBClassifier(**params)
