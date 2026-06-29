from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from ml.experiments.walkforward_scoring.config import DEFAULT_DB_PATH
from ml.experiments.walkforward_scoring.scoring_model import classify_seg, load_coords_bundle

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_ROOT = PROJECT_ROOT / "eda" / "results" / "granularity_shift_experiments"
DEFAULT_OUTPUT_DIR = RESULTS_ROOT
DEFAULT_MIN_GAMES = 1500
DEFAULT_HISTORY_DAYS = 90
DEFAULT_SECTION_TOP_KS = (1, 3, 5)
DEFAULT_WEEK_TOP_KS = (1, 3, 5)
DEFAULT_SECTION_THRESHOLDS = (30.0, 35.0, 40.0, 45.0)
DEFAULT_WEEK_THRESHOLDS = (100.0, 101.0, 102.0, 103.0)
DEFAULT_SECTION_EVAL_DAYS = 60
DEFAULT_WEEK_EVAL_WEEKS = 12


def resolve_db_path(db_path: str | Path | None = None) -> Path:
    if db_path is not None:
        return Path(db_path)
    if DEFAULT_DB_PATH.exists() and DEFAULT_DB_PATH.stat().st_size > 0:
        return DEFAULT_DB_PATH
    candidates = sorted(
        (PROJECT_ROOT / "db").glob("*蒲田7*.db"),
        key=lambda path: path.stat().st_size if path.exists() else 0,
        reverse=True,
    )
    return candidates[0] if candidates else DEFAULT_DB_PATH


def _debut_phase_label(days_since_debut: object, pre_existing: bool) -> str:
    if pre_existing:
        return "pre_existing"
    if pd.isna(days_since_debut):
        return "unknown"
    days = int(days_since_debut)
    if days <= 14:
        return "1-14日"
    if days <= 60:
        return "15-60日"
    if days <= 180:
        return "61-180日"
    return "181日+"


def format_markdown_table(frame: pd.DataFrame, *, float_digits: int = 3) -> str:
    if frame.empty:
        return "No rows."
    work = frame.copy()
    columns = [str(col) for col in work.columns]
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join(["---"] * len(columns)) + " |"
    rows: list[str] = []
    for _, row in work.iterrows():
        values: list[str] = []
        for col in work.columns:
            value = row[col]
            if pd.isna(value):
                values.append("")
            elif isinstance(value, (float, np.floating)):
                values.append(f"{float(value):.{float_digits}f}")
            else:
                values.append(str(value))
        rows.append("| " + " | ".join(values) + " |")
    return "\n".join([header, separator, *rows])


def safe_spearman(x: pd.Series, y: pd.Series) -> tuple[float, float]:
    valid = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(valid) < 2:
        return float("nan"), float("nan")
    rho, p_value = spearmanr(valid["x"], valid["y"])
    return float(rho), float(p_value)


def qcut_extreme_delta(frame: pd.DataFrame, feature_col: str, target_col: str) -> dict[str, object]:
    valid = frame[[feature_col, target_col]].dropna()
    if valid.empty:
        return {
            "feature": feature_col,
            "n": 0,
            "n_bins": 0,
            "d0_mean": float("nan"),
            "d9_mean": float("nan"),
            "delta_pp": float("nan"),
        }
    try:
        bins = pd.qcut(valid[feature_col], 10, labels=False, duplicates="drop")
    except Exception:
        return {
            "feature": feature_col,
            "n": int(len(valid)),
            "n_bins": 0,
            "d0_mean": float("nan"),
            "d9_mean": float("nan"),
            "delta_pp": float("nan"),
        }
    if bins.isna().all():
        return {
            "feature": feature_col,
            "n": int(len(valid)),
            "n_bins": 0,
            "d0_mean": float("nan"),
            "d9_mean": float("nan"),
            "delta_pp": float("nan"),
        }
    valid = valid.assign(_bin=bins)
    grouped = valid.groupby("_bin", dropna=False)[target_col].mean().sort_index()
    if grouped.empty:
        return {
            "feature": feature_col,
            "n": int(len(valid)),
            "n_bins": 0,
            "d0_mean": float("nan"),
            "d9_mean": float("nan"),
            "delta_pp": float("nan"),
        }
    first = float(grouped.iloc[0])
    last = float(grouped.iloc[-1])
    return {
        "feature": feature_col,
        "n": int(len(valid)),
        "n_bins": int(len(grouped)),
        "d0_mean": first,
        "d9_mean": last,
        "delta_pp": last - first,
    }


def threshold_lift_by_date(
    frame: pd.DataFrame,
    *,
    score_col: str,
    target_col: str,
    date_col: str,
    thresholds: tuple[float, ...],
    top_ks: tuple[int, ...],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    valid = frame[[score_col, target_col, date_col]].dropna().copy()
    if valid.empty:
        return pd.DataFrame(
            columns=[
                "threshold",
                "top_k",
                "baseline_rate",
                "selected_rate",
                "lift",
                "selected_n",
                "baseline_n",
            ]
        )
    valid = valid.sort_values([date_col, score_col], ascending=[True, False]).copy()
    for threshold in thresholds:
        binary = valid[target_col].ge(threshold)
        baseline_rate = float(binary.mean()) if len(binary) else float("nan")
        for top_k in top_ks:
            selected_idx = valid.groupby(date_col, sort=False).head(top_k).index
            selected = binary.loc[selected_idx]
            selected_rate = float(selected.mean()) if len(selected) else float("nan")
            lift = float("nan")
            if pd.notna(baseline_rate) and baseline_rate > 0 and pd.notna(selected_rate):
                lift = selected_rate / baseline_rate
            rows.append(
                {
                    "threshold": threshold,
                    "top_k": top_k,
                    "baseline_rate": baseline_rate,
                    "selected_rate": selected_rate,
                    "lift": lift,
                    "selected_n": int(len(selected)),
                    "baseline_n": int(len(binary)),
                }
            )
    return pd.DataFrame(rows)


def load_base_frame(
    db_path: str | Path | None = None,
    *,
    min_games: int = DEFAULT_MIN_GAMES,
    history_days: int = DEFAULT_HISTORY_DAYS,
) -> pd.DataFrame:
    resolved_db_path = resolve_db_path(db_path)
    with sqlite3.connect(resolved_db_path) as conn:
        raw = pd.read_sql_query(
            """
            SELECT
                date,
                machine_number,
                machine_name,
                games_normalized,
                diff_coins_normalized
            FROM machine_detailed_results
            """,
            conn,
        )
    if raw.empty:
        raise ValueError(f"machine_detailed_results returned no rows in {resolved_db_path}")

    work = raw.copy()
    work["date"] = work["date"].astype(str)
    work["date_dt"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work = work.dropna(subset=["date_dt", "machine_number", "machine_name", "games_normalized", "diff_coins_normalized"]).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work = work[work["machine_number"].ne(2026)].copy()
    work["mmdd"] = work["date"].str[4:8]
    work = work[work["mmdd"].ne("0707")].copy()
    work = work[work["games_normalized"] >= min_games].copy()
    if work.empty:
        raise ValueError("No rows remained after applying date and games filters")

    coords = load_coords_bundle()
    coord_cols = [
        "machine_number",
        "floor",
        "section",
        "section_min",
        "section_max",
        "rank_from_min",
        "rank_from_max",
        "section_size",
        "section_size_group",
        "lr",
    ]
    work = work.merge(coords[coord_cols], on="machine_number", how="inner", validate="m:1")
    if work.empty:
        raise ValueError("No rows remained after joining coordinates")

    work["seg"] = work["machine_name"].map(classify_seg)
    work["segment"] = work["floor"].astype(str) + "_" + work["lr"].astype(str) + "_" + work["seg"].astype(str)
    denom = work["games_normalized"] * 3
    work["payout_rate"] = ((denom + work["diff_coins_normalized"]) / denom) * 100
    work["hit104"] = work["payout_rate"] >= 104.0

    db_start = pd.Timestamp(work["date_dt"].min())
    debut_dt = work.groupby("machine_name", dropna=False)["date_dt"].transform("min")
    work["debut_date"] = debut_dt.dt.strftime("%Y%m%d")
    work["debut_days_since"] = (work["date_dt"] - debut_dt).dt.days
    work["pre_existing"] = debut_dt.eq(db_start)
    work["debut_phase"] = [
        _debut_phase_label(days, pre_existing)
        for days, pre_existing in zip(work["debut_days_since"], work["pre_existing"], strict=True)
    ]
    work["debut_phase"] = work["debut_phase"].astype("string")

    work = work.sort_values(["machine_number", "date_dt"]).reset_index(drop=True)
    history_frames: list[pd.DataFrame] = []
    for _, group in work.groupby("machine_number", sort=False):
        series = group.set_index("date_dt")["hit104"].astype(float).sort_index()
        hist_metric = series.rolling(f"{history_days}D", closed="left", min_periods=1).mean()
        hist_df = group.loc[:, ["date_dt"]].copy()
        hist_df["hist_metric"] = hist_metric.to_numpy()
        hist_df["row_index"] = group.index.to_numpy()
        history_frames.append(hist_df)
    history = pd.concat(history_frames, ignore_index=True).sort_values("row_index")
    work["hist_metric"] = history["hist_metric"].to_numpy()
    return work.reset_index(drop=True)


def section_daily_aggregates(frame: pd.DataFrame, *, history_days: int = DEFAULT_HISTORY_DAYS) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    daily = (
        frame.groupby(["date_dt", "date", "floor", "section"], dropna=False)
        .agg(
            section_avg_payout=("payout_rate", "mean"),
            section_hit_rate=("hit104", "mean"),
            section_machine_count=("machine_number", "nunique"),
            section_total_games=("games_normalized", "sum"),
            section_avg_hist=("hist_metric", "mean"),
            section_debut_ratio=("debut_phase", lambda s: float((s == "1-14日").mean())),
        )
        .reset_index()
        .sort_values(["section", "date_dt"])
        .reset_index(drop=True)
    )
    if daily.empty:
        return daily

    hist_frames: list[pd.DataFrame] = []
    for _, group in daily.groupby("section", sort=False):
        series = group.set_index("date_dt")["section_hit_rate"].astype(float).sort_index()
        hist_rate = series.rolling(f"{history_days}D", closed="left", min_periods=1).mean()
        prev_day = series.shift(1)
        hist_df = group.loc[:, ["date_dt"]].copy()
        hist_df["hist_section_hit_rate"] = hist_rate.to_numpy()
        hist_df["prev_day_section_hot"] = prev_day.to_numpy()
        hist_df["row_index"] = group.index.to_numpy()
        hist_frames.append(hist_df)
    hist = pd.concat(hist_frames, ignore_index=True).sort_values("row_index")
    daily["hist_section_hit_rate"] = hist["hist_section_hit_rate"].to_numpy()
    daily["prev_day_section_hot"] = hist["prev_day_section_hot"].to_numpy()
    return daily


def weekly_machine_aggregates(frame: pd.DataFrame, *, history_days: int = DEFAULT_HISTORY_DAYS) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    work = frame.copy()
    work["week_start"] = work["date_dt"] - pd.to_timedelta(work["date_dt"].dt.dayofweek, unit="D")
    week_rows: list[dict[str, object]] = []
    grouped = work.groupby(["machine_number", "machine_name", "week_start"], sort=False)
    for (machine_number, machine_name, week_start), group in grouped:
        active_days = int(group["date_dt"].dt.normalize().nunique())
        if active_days < 3:
            continue
        week_avg_payout = float(group["payout_rate"].mean())
        week_positive_days = int((group["diff_coins_normalized"] > 0).sum())
        week_rows.append(
            {
                "machine_number": machine_number,
                "machine_name": machine_name,
                "week_start": pd.Timestamp(week_start),
                "week_end": pd.Timestamp(week_start) + pd.Timedelta(days=6),
                "week_avg_payout": week_avg_payout,
                "week_positive_days": week_positive_days,
                "week_active_days": active_days,
            }
        )

    weekly = pd.DataFrame(week_rows)
    if weekly.empty:
        return weekly

    machine_meta = (
        frame.drop_duplicates("machine_number")
        .loc[:, ["machine_number", "section", "segment", "machine_name", "debut_date"]]
        .copy()
    )
    weekly = weekly.merge(machine_meta, on=["machine_number", "machine_name"], how="left", validate="m:1")
    weekly["debut_date"] = pd.to_datetime(weekly["debut_date"], format="%Y%m%d", errors="coerce")
    weekly["debut_days_since"] = (weekly["week_start"] - weekly["debut_date"]).dt.days
    db_start = pd.Timestamp(frame["date_dt"].min())
    weekly["pre_existing"] = weekly["debut_date"].eq(db_start)
    weekly["debut_phase"] = [
        _debut_phase_label(days, pre_existing)
        for days, pre_existing in zip(weekly["debut_days_since"], weekly["pre_existing"], strict=True)
    ]
    weekly["debut_phase"] = weekly["debut_phase"].astype("string")

    weekly = weekly.sort_values(["machine_number", "week_start"]).reset_index(drop=True)
    weekly["hist_ref_dt"] = weekly["week_start"] - pd.Timedelta(days=1)
    hist_frames: list[pd.DataFrame] = []
    daily_hist = frame.loc[:, ["machine_number", "date_dt", "hist_metric"]].sort_values("date_dt").reset_index(drop=True)
    for machine_number, group in weekly.groupby("machine_number", sort=False):
        left = group.sort_values("hist_ref_dt").copy()
        right = daily_hist[daily_hist["machine_number"] == machine_number].sort_values("date_dt")
        if right.empty:
            left["hist_metric"] = np.nan
        else:
            merged = pd.merge_asof(
                left,
                right,
                left_on="hist_ref_dt",
                right_on="date_dt",
                direction="backward",
                allow_exact_matches=True,
            )
            left["hist_metric"] = merged["hist_metric"].to_numpy()
        hist_frames.append(left)
    weekly = pd.concat(hist_frames, ignore_index=True).sort_values(["machine_number", "week_start"]).reset_index(drop=True)
    weekly["prev_week_avg_payout"] = weekly.groupby("machine_number", dropna=False)["week_avg_payout"].shift(1)
    weekly["prev_week_positive_days"] = weekly.groupby("machine_number", dropna=False)["week_positive_days"].shift(1)
    return weekly
