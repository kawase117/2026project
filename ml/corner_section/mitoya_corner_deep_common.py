from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.corner_section.mitoya_corner_section_analysis import resolve_mitoya_db_path

CORNER_METRICS = ("rank_from_min", "rank_from_aisle", "physical_corner")
WEEKDAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DD_GROUP_ORDER = ["4系", "7系", "5系", "その他"]
ISLAND_ORDER = ["all", "main_jug", "bari", "main_mix"]
RANK_BUCKETS = [1, 2, 3, 4, 5]


def load_corner_frame(db_path: Path) -> pd.DataFrame:
    query = """
    SELECT
        m.date,
        m.machine_number,
        m.machine_name,
        m.diff_coins_normalized,
        m.machine_rank_in_type,
        m.games_normalized,
        ml.rank_from_min,
        ml.rank_from_max,
        ml.rank_from_aisle,
        ml.is_reversed_section,
        ml.section,
        COALESCE(mm.jug_flag, 0) AS jug_flag,
        COALESCE(mm.hana_flag, 0) AS hana_flag,
        COALESCE(mm.oki_flag, 0) AS oki_flag,
        COALESCE(mm.bt_flag, 0) AS bt_flag,
        COALESCE(dh.avg_diff_per_machine, 0) AS avg_diff_per_machine,
        STRFTIME('%w', SUBSTR(m.date,1,4) || '-' || SUBSTR(m.date,5,2) || '-' || SUBSTR(m.date,7,2)) AS weekday_num
    FROM machine_detailed_results m
    LEFT JOIN machine_layout ml
      ON m.machine_number = ml.machine_number
    LEFT JOIN machine_master mm
      ON m.machine_name = mm.machine_name_normalized
    INNER JOIN daily_hall_summary dh
      ON m.date = dh.date
     AND COALESCE(dh.avg_diff_per_machine, 0) > 0
    """
    con = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(query, con)
    finally:
        con.close()
    if df.empty:
        raise ValueError(f"No rows loaded from {db_path}")
    return df


def assign_island(machine_number: int | float | str) -> str:
    try:
        n = int(machine_number)
    except (TypeError, ValueError):
        return "unknown"
    if 641 <= n <= 691:
        return "main_jug"
    if n >= 692:
        return "bari"
    return "main_mix"


def prepare_corner_frame(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work = work.dropna(
        subset=["rank_from_min", "rank_from_max", "rank_from_aisle", "section", "date"]
    ).copy()
    for col in [
        "machine_number",
        "rank_from_min",
        "rank_from_max",
        "rank_from_aisle",
        "diff_coins_normalized",
        "machine_rank_in_type",
        "games_normalized",
        "avg_diff_per_machine",
    ]:
        work[col] = pd.to_numeric(work[col], errors="coerce")
    work = work.dropna(subset=["machine_number", "rank_from_min", "rank_from_max", "rank_from_aisle"]).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    for col in ["rank_from_min", "rank_from_max", "rank_from_aisle"]:
        work[col] = work[col].astype(int)
    work["date_dt"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
    work = work.dropna(subset=["date_dt"]).copy()
    weekday_num = pd.to_numeric(work["weekday_num"], errors="coerce").fillna(-1).astype(int)
    weekday_map = {0: "Sun", 1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat"}
    work["day_of_week"] = weekday_num.map(weekday_map).fillna("unknown")
    work["dd"] = work["date_dt"].dt.day.astype(int)
    work["dd_group"] = work["dd"].apply(_dd_group)
    work["physical_corner"] = work[["rank_from_min", "rank_from_max"]].min(axis=1).astype(int)
    work["plus_flag"] = work["diff_coins_normalized"].gt(0).astype(int)
    work["island"] = work["machine_number"].apply(assign_island)
    work["date"] = work["date_dt"].dt.strftime("%Y%m%d")
    return work


def iter_island_frames(df: pd.DataFrame):
    yield "all", df
    for island in ISLAND_ORDER[1:]:
        island_df = df.loc[df["island"].eq(island)].copy()
        if not island_df.empty:
            yield island, island_df


def _dd_group(day: int) -> str:
    if day in {4, 14, 24}:
        return "4系"
    if day in {7, 17, 27}:
        return "7系"
    if day in {5, 15, 25}:
        return "5系"
    return "その他"


def corner_rank_profile(df: pd.DataFrame, metric: str) -> pd.DataFrame:
    work = df.loc[df[metric].isin(RANK_BUCKETS), [metric, "diff_coins_normalized", "games_normalized"]].copy()
    if work.empty:
        return pd.DataFrame(columns=["rank", "avg_diff", "avg_games", "sample_n"])
    profile = (
        work.groupby(metric, sort=True)
        .agg(
            avg_diff=("diff_coins_normalized", "mean"),
            avg_games=("games_normalized", "mean"),
            sample_n=("diff_coins_normalized", "size"),
        )
        .reset_index()
        .rename(columns={metric: "rank"})
    )
    profile["avg_diff"] = profile["avg_diff"].round(0).astype(int)
    profile["avg_games"] = profile["avg_games"].round(0).astype(int)
    profile["sample_n"] = profile["sample_n"].astype(int)
    return profile


def kruskal_summary(
    df: pd.DataFrame,
    *,
    group_col: str,
    value_col: str = "diff_coins_normalized",
    min_group_n: int = 30,
) -> dict[str, float | int | str]:
    work = df.dropna(subset=[group_col, value_col]).copy()
    if work.empty:
        return {
            "n_groups": 0,
            "n_rows": 0,
            "statistic": float("nan"),
            "p_value": float("nan"),
            "epsilon_sq": float("nan"),
            "significant": "No",
        }

    if group_col in CORNER_METRICS:
        work[group_col] = pd.to_numeric(work[group_col], errors="coerce")
        work = work.dropna(subset=[group_col]).copy()
        work[group_col] = work[group_col].astype(int)
    else:
        work[group_col] = work[group_col].astype(str)

    counts = work.groupby(group_col).size()
    valid_groups = counts[counts >= min_group_n].index.tolist()
    filtered = work[work[group_col].isin(valid_groups)].copy()
    n_rows = int(len(filtered))
    n_groups = int(len(valid_groups))
    statistic = float("nan")
    p_value = float("nan")
    if n_groups >= 2:
        samples = [
            filtered.loc[filtered[group_col] == group, value_col].to_numpy(dtype=float)
            for group in valid_groups
        ]
        try:
            statistic, p_value = stats.kruskal(*samples)
        except ValueError:
            statistic, p_value = float("nan"), float("nan")

    epsilon_sq = float("nan")
    if np.isfinite(statistic) and n_groups >= 2 and n_rows > n_groups:
        epsilon_sq = float(max((statistic - n_groups + 1) / (n_rows - n_groups), 0.0))

    return {
        "n_groups": n_groups,
        "n_rows": n_rows,
        "statistic": round(float(statistic), 4) if np.isfinite(statistic) else float("nan"),
        "p_value": float(p_value) if np.isfinite(p_value) else float("nan"),
        "epsilon_sq": round(epsilon_sq, 6) if np.isfinite(epsilon_sq) else float("nan"),
        "significant": "Yes" if np.isfinite(p_value) and p_value < 0.05 else "No",
    }


def build_drift_timeseries(
    df: pd.DataFrame,
    *,
    window_days: int = 180,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    work = df.loc[df["plus_flag"].eq(1)].copy()
    if work.empty:
        return pd.DataFrame()

    work = work.sort_values("date_dt").copy()
    for island, island_work in iter_island_frames(work):
        island_work = island_work.sort_values("date_dt").copy()
        unique_ends = pd.Index(island_work["date_dt"].drop_duplicates().sort_values())
        if unique_ends.empty:
            continue
        min_date = unique_ends.min()
        for metric in CORNER_METRICS:
            metric_work = island_work.dropna(subset=[metric]).copy()
            metric_work[metric] = pd.to_numeric(metric_work[metric], errors="coerce")
            metric_work = metric_work.dropna(subset=[metric]).copy()
            metric_work[metric] = metric_work[metric].astype(int)

            for window_end in unique_ends:
                window_start = window_end - pd.Timedelta(days=window_days - 1)
                if window_start < min_date:
                    continue
                window = metric_work.loc[
                    metric_work["date_dt"].between(window_start, window_end, inclusive="both")
                ].copy()
                if window.empty:
                    continue

                profile = (
                    window.groupby(metric, sort=True)
                    .agg(
                        avg_diff=("diff_coins_normalized", "mean"),
                        avg_games=("games_normalized", "mean"),
                        sample_n=("diff_coins_normalized", "size"),
                    )
                    .reindex(RANK_BUCKETS)
                )
                row: dict[str, object] = {
                    "island": island,
                    "corner_metric": metric,
                    "window_end": window_end.strftime("%Y%m%d"),
                    "window_start": window_start.strftime("%Y%m%d"),
                    "sample_n": int(len(window)),
                }
                for rank in RANK_BUCKETS:
                    if rank in profile.index:
                        row[f"rank{rank}_avg_diff"] = profile.loc[rank, "avg_diff"]
                        row[f"rank{rank}_avg_games"] = profile.loc[rank, "avg_games"]
                        row[f"rank{rank}_sample_n"] = profile.loc[rank, "sample_n"]
                    else:
                        row[f"rank{rank}_avg_diff"] = float("nan")
                        row[f"rank{rank}_avg_games"] = float("nan")
                        row[f"rank{rank}_sample_n"] = 0
                row["gradient_diff"] = row["rank1_avg_diff"] - row["rank5_avg_diff"]
                row["gradient_games"] = row["rank1_avg_games"] - row["rank5_avg_games"]
                rows.append(row)

    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values(["island", "corner_metric", "window_end"]).reset_index(drop=True)
