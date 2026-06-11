from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.last_digit.expert_segmentation import compute_is_a_type_flag
from ml.feature_engineering import SECTION_RANK
from ml.last_digit.tail_ltr_split_rule_wf import normalize_last_digit

EXPERTS_MITOYA = ("N", "A", "BT")
SECTION_UNKNOWN = "unknown"


def add_mitoya_position_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add section and physical_corner columns for Mitoya-specific downstream features."""
    work = df.copy()

    if "section" not in work.columns:
        work["section"] = SECTION_UNKNOWN
    work["section"] = work["section"].fillna(SECTION_UNKNOWN).astype(str)
    work["section_rank"] = pd.to_numeric(work["section"].map(SECTION_RANK), errors="coerce").fillna(0).astype(int)
    work["is_strong_section"] = work["section_rank"].between(1, 5).astype(int)

    if "rank_from_min" in work.columns:
        rank_from_min_source = work["rank_from_min"]
    else:
        rank_from_min_source = pd.Series([-1] * len(work), index=work.index)
    if "rank_from_max" in work.columns:
        rank_from_max_source = work["rank_from_max"]
    else:
        rank_from_max_source = pd.Series([-1] * len(work), index=work.index)

    rank_from_min = pd.to_numeric(rank_from_min_source, errors="coerce").fillna(-1)
    rank_from_max = pd.to_numeric(rank_from_max_source, errors="coerce").fillna(-1)
    valid = (rank_from_min > 0) & (rank_from_max > 0)

    work["physical_corner"] = -1
    work.loc[valid, "physical_corner"] = np.minimum(rank_from_min[valid], rank_from_max[valid]).astype(int)
    work["physical_corner_valid"] = (work["physical_corner"] > 0).astype(int)
    return work


def _is_positive_day(ts: pd.Timestamp) -> bool:
    day = int(pd.Timestamp(ts).day)
    return (day % 10 in {4, 7}) or (pd.Timestamp(ts).month == pd.Timestamp(ts).day) or (day in {11, 30})


def add_atype3_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    みとや用の3セグメント列を追加する。

    `bt_flag` が最優先なので、A判定を先に入れてから BT で上書きする。
    """
    work = df.copy()
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work = work[work["machine_number"].notna()].copy()
    work["machine_number"] = work["machine_number"].astype(int)

    jug_flag = pd.to_numeric(work.get("jug_flag", 0), errors="coerce").fillna(0).astype(int)
    hana_flag = pd.to_numeric(work.get("hana_flag", 0), errors="coerce").fillna(0).astype(int)
    oki_flag = pd.to_numeric(work.get("oki_flag", 0), errors="coerce").fillna(0).astype(int)
    bt_flag = pd.to_numeric(work.get("bt_flag", 0), errors="coerce").fillna(0).astype(int)

    work["is_a_type"] = compute_is_a_type_flag(work).astype(int)
    work["atype_bucket"] = "N"
    work.loc[(jug_flag == 1) | (hana_flag == 1) | (oki_flag == 1), "atype_bucket"] = "A"
    work.loc[bt_flag == 1, "atype_bucket"] = "BT"
    work["expert"] = work["atype_bucket"]
    return work


def classify_positive_combined_bucket(value: pd.Timestamp) -> str:
    return "positive_day" if _is_positive_day(value) else "others"


def build_base_rows_mitoya(*, db_path: Path, a_weight: float, non_a_weight: float) -> pd.DataFrame:
    con = sqlite3.connect(str(db_path))
    q = """
    SELECT
      m.date,
      m.machine_number,
      m.machine_name,
      m.last_digit,
      m.games_normalized,
      m.diff_coins_normalized,
      COALESCE(ml.section, 'unknown') AS section,
      COALESCE(ml.rank_from_min, -1) AS rank_from_min,
      COALESCE(ml.rank_from_max, -1) AS rank_from_max,
      COALESCE(mm.jug_flag, 0) AS jug_flag,
      COALESCE(mm.hana_flag, 0) AS hana_flag,
      COALESCE(mm.oki_flag, 0) AS oki_flag,
      COALESCE(mm.bt_flag, 0) AS bt_flag,
      COALESCE(dh.is_any_event, 0) AS is_event_day,
      COALESCE(dh.is_strong_zorome, 0) AS is_strong_zorome
    FROM machine_detailed_results m
    LEFT JOIN machine_layout ml
      ON m.machine_number = ml.machine_number
    LEFT JOIN machine_master mm
      ON m.machine_name = mm.machine_name_normalized
    LEFT JOIN daily_hall_summary dh
      ON m.date = dh.date
    """
    df = pd.read_sql_query(q, con)
    con.close()
    if df.empty:
        raise ValueError("No rows from machine_detailed_results")

    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["last_digit"] = df["last_digit"].map(normalize_last_digit)
    df = add_atype3_columns(df)
    df = add_mitoya_position_columns(df)
    df["row_weight"] = np.where(df["is_a_type"] == 1, float(a_weight), float(non_a_weight))
    df["diff_focus"] = pd.to_numeric(df["diff_coins_normalized"], errors="coerce").fillna(0.0) * df["row_weight"]
    df["win_flag"] = (pd.to_numeric(df["diff_coins_normalized"], errors="coerce").fillna(0.0) > 0).astype(float)
    return df


def aggregate_mode_mitoya(raw: pd.DataFrame, *, mode: str) -> pd.DataFrame:
    df = raw.copy()
    dates = pd.to_datetime(df["date"])
    if mode == "atype3":
        df["group_key"] = df["atype_bucket"]
    elif mode == "N_only":
        df = df[df["atype_bucket"].eq("N")].copy()
        df["group_key"] = "N"
    elif mode == "positive_combined":
        positive_mask = dates.dt.day.mod(10).isin([4, 7]) | (dates.dt.month.eq(dates.dt.day)) | dates.dt.day.isin([11, 30])
        df["group_key"] = np.where(positive_mask, "positive_day", "others")
    else:
        raise ValueError(f"Unsupported mode: {mode}")

    df["entity_key"] = df["group_key"] + "|" + df["last_digit"].astype(str)
    for col, default in (
        ("section_rank", 0),
        ("is_strong_section", 0),
        ("physical_corner", -1),
    ):
        if col not in df.columns:
            df[col] = default
    agg = (
        df.groupby(["date", "group_key", "entity_key", "last_digit"], sort=True)
        .agg(
            machine_count=("machine_number", "count"),
            total_games=("games_normalized", "sum"),
            avg_games=("games_normalized", "mean"),
            total_diff_coins=("diff_coins_normalized", "sum"),
            total_diff_coins_focus=("diff_focus", "sum"),
            avg_diff_coins=("diff_coins_normalized", "mean"),
            win_rate=("win_flag", "mean"),
            is_event_day=("is_event_day", "max"),
            non_a_ratio=("is_a_type", lambda s: float((1.0 - s.astype(float)).mean())),
            mean_section_rank=("section_rank", lambda s: float(pd.to_numeric(s, errors="coerce").fillna(0).mean())),
            mean_physical_corner=(
                "physical_corner",
                lambda s: float(
                    pd.to_numeric(s, errors="coerce").fillna(0).where(pd.to_numeric(s, errors="coerce").fillna(0) > 0).mean()
                )
                if (pd.to_numeric(s, errors="coerce").fillna(0) > 0).any()
                else 0.0,
            ),
            pct_strong_section=("is_strong_section", lambda s: float(pd.to_numeric(s, errors="coerce").fillna(0).mean())),
        )
        .reset_index()
    )
    agg["efficiency"] = (agg["total_diff_coins"] / agg["total_games"].replace(0, np.nan)).fillna(0.0)
    agg["efficiency_focus"] = (agg["total_diff_coins_focus"] / agg["total_games"].replace(0, np.nan)).fillna(0.0)
    agg = agg.sort_values(["entity_key", "date"]).reset_index(drop=True)

    digit_lags = [1, 2, 5, 6, 7, 14, 15]
    hall_digit_daily = (
        agg.groupby(["date", "last_digit"], sort=True)["total_diff_coins"]
        .mean()
        .reset_index()
        .rename(columns={"total_diff_coins": "hall_digit_mean_diff"})
        .sort_values(["last_digit", "date"])
        .reset_index(drop=True)
    )
    for lag in digit_lags:
        hall_digit_daily[f"lag{lag}_hall_digit_diff"] = (
            hall_digit_daily.groupby("last_digit", sort=False)["hall_digit_mean_diff"]
            .shift(lag)
            .fillna(0.0)
        )
    lag_cols = [f"lag{lag}_hall_digit_diff" for lag in digit_lags]
    agg["last_digit"] = agg["last_digit"].astype(str)
    hall_digit_daily["last_digit"] = hall_digit_daily["last_digit"].astype(str)
    # Intentionally exclude `hall_digit_mean_diff` (same-day unshifted value) from merge.
    # Only lagged versions (lag_cols) are safe to use as features — leakage prevention.
    agg = agg.merge(
        hall_digit_daily[["date", "last_digit", *lag_cols]],
        on=["date", "last_digit"],
        how="left",
    )
    for col in lag_cols:
        agg[col] = pd.to_numeric(agg[col], errors="coerce").fillna(0.0)

    rk_desc = agg.groupby(["date", "group_key"], sort=False)["total_diff_coins"].rank(method="first", ascending=False)
    rk_asc = agg.groupby(["date", "group_key"], sort=False)["total_diff_coins"].rank(method="first", ascending=True)
    agg["is_rank_1"] = (rk_desc == 1).astype(int)
    agg["is_top_2"] = (rk_desc <= 2).astype(int)
    agg["is_top_3"] = (rk_desc <= 3).astype(int)
    agg["is_worst_1"] = (rk_asc == 1).astype(int)
    agg["is_worst_3"] = (rk_asc <= 3).astype(int)
    return agg
