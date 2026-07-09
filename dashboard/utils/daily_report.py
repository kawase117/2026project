"""Helpers for the single-day hall report page."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd


HIT104_THRESHOLD = 104.0
MIN_GROUP_SIZE_FOR_RANKING = 3
DEFAULT_GROUP_MIN_SIZE = 1
GROUP_SUMMARY_COLUMNS = [
    "n",
    "avg_diff",
    "avg_games",
    "avg_payout_rate",
    "win_rate",
    "hit104_count",
    "hit104_rate",
]


def has_table(db_path: str | Path, table_name: str) -> bool:
    """Return True when ``table_name`` exists in the SQLite database."""

    path = Path(db_path)
    if not path.exists():
        return False

    with sqlite3.connect(str(path)) as con:
        row = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
            (table_name,),
        ).fetchone()
    return row is not None


def load_optional_table(db_path: str | Path, table_name: str) -> pd.DataFrame:
    """Load a table if present, otherwise return an empty DataFrame."""

    path = Path(db_path)
    if not path.exists() or not has_table(path, table_name):
        return pd.DataFrame()

    with sqlite3.connect(str(path)) as con:
        return pd.read_sql_query(f"SELECT * FROM {table_name}", con)


def compute_payout_rate(df: pd.DataFrame) -> pd.Series:
    """
    Estimate payout rate using a fixed 3 yen per game approximation.

    The repo does not store the exact bet count for every machine type, so this is
    a documented approximation rather than a machine-accurate value.
    """

    games = pd.to_numeric(df["games_normalized"], errors="coerce")
    diff = pd.to_numeric(df["diff_coins_normalized"], errors="coerce")
    bet = games * 3.0
    payout = bet + diff
    rate = (payout / bet) * 100.0
    rate = rate.where((bet > 0) & bet.notna())
    return rate


def add_hit104_flag(df: pd.DataFrame) -> pd.DataFrame:
    """Attach payout rate and a 104%+ hit flag."""

    work = df.copy()
    work["payout_rate"] = compute_payout_rate(work)
    hit104 = pd.Series(pd.NA, index=work.index, dtype="Int64")
    valid = work["payout_rate"].notna()
    hit104.loc[valid] = (work.loc[valid, "payout_rate"] >= HIT104_THRESHOLD).astype("Int64")
    work["hit104"] = hit104
    return work


def _build_group_summary_frame(work: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    """Aggregate a frame by one or more group columns without applying size filters."""

    if work.empty or any(column not in work.columns for column in group_columns):
        return pd.DataFrame(columns=[*group_columns, *GROUP_SUMMARY_COLUMNS])

    summary = add_hit104_flag(work)
    for column in group_columns:
        summary[column] = summary[column].fillna("unknown")

    grouped_size = summary.groupby(group_columns, dropna=False, sort=True).size()
    grouped = (
        summary.groupby(group_columns, dropna=False, sort=True)
        .agg(
            avg_diff=("diff_coins_normalized", "mean"),
            avg_games=("games_normalized", "mean"),
            avg_payout_rate=("payout_rate", "mean"),
            win_rate=("diff_coins_normalized", lambda s: float(pd.to_numeric(s, errors="coerce").gt(0).mean())),
            hit104_count=("hit104", lambda s: int(pd.to_numeric(s, errors="coerce").fillna(0).sum())),
            hit104_rate=(
                "hit104",
                lambda s: float(pd.to_numeric(s, errors="coerce").dropna().mean()) if s.notna().any() else np.nan,
            ),
        )
        .reset_index()
    )
    grouped["n"] = grouped_size.to_numpy()
    return grouped.loc[:, [*group_columns, *GROUP_SUMMARY_COLUMNS]]


def summarize_group_performance(
    df: pd.DataFrame,
    group_column: str,
    *,
    min_group_size: int = DEFAULT_GROUP_MIN_SIZE,
    sort_by: str = "hit104_rate",
    ascending: bool = False,
) -> pd.DataFrame:
    """Aggregate a day-level frame by one category and drop undersized groups."""

    grouped = _build_group_summary_frame(df, [group_column])

    grouped = grouped[grouped["n"] >= int(min_group_size)].copy()
    if grouped.empty:
        return grouped.reindex(
            columns=[
                group_column,
                "n",
                "avg_diff",
                "avg_games",
                "avg_payout_rate",
                "win_rate",
                "hit104_count",
                "hit104_rate",
            ]
        )

    grouped = grouped.sort_values(
        [sort_by, "avg_diff", "n", group_column],
        ascending=[ascending, False, False, True],
        kind="mergesort",
    )
    return grouped.reset_index(drop=True)


def filter_search_query(df: pd.DataFrame, query: str) -> pd.DataFrame:
    """Filter rows by machine number or machine name substring."""

    if df.empty:
        return df

    text = str(query).strip()
    if not text:
        return df

    work = df.copy()
    machine_numbers = work.get("machine_number", pd.Series(index=work.index, dtype="object")).astype(str)
    machine_names = work.get("machine_name", pd.Series(index=work.index, dtype="object")).astype(str)
    mask = machine_numbers.str.contains(text, case=False, na=False, regex=False) | machine_names.str.contains(
        text, case=False, na=False, regex=False
    )
    return work.loc[mask].reset_index(drop=True)


def _empty_layout_frame() -> pd.DataFrame:
    return pd.DataFrame()


def build_layout_summary(
    daily_frame: pd.DataFrame,
    layout_frame: pd.DataFrame,
    *,
    group_column: str,
    min_group_size: int = DEFAULT_GROUP_MIN_SIZE,
    sort_by: str = "hit104_rate",
    ascending: bool = False,
) -> pd.DataFrame:
    """Join layout data and aggregate by rank_from_min or section."""

    if daily_frame.empty or layout_frame.empty or group_column not in layout_frame.columns:
        return _empty_layout_frame()

    work = daily_frame.merge(layout_frame, on="machine_number", how="inner")
    if work.empty or group_column not in work.columns:
        return _empty_layout_frame()
    return summarize_group_performance(
        work, group_column, min_group_size=min_group_size, sort_by=sort_by, ascending=ascending
    )


def build_segment_summary(
    daily_frame: pd.DataFrame,
    master_frame: pd.DataFrame,
    *,
    min_group_size: int = DEFAULT_GROUP_MIN_SIZE,
    sort_by: str = "hit104_rate",
    ascending: bool = False,
) -> pd.DataFrame:
    """Join machine master flags and aggregate into the shared segment buckets."""

    if daily_frame.empty or master_frame.empty:
        return _empty_layout_frame()

    required = {"machine_name_normalized", "jug_flag", "hana_flag", "oki_flag", "bt_flag"}
    if not required.issubset(master_frame.columns):
        return _empty_layout_frame()

    master = master_frame.loc[:, ["machine_name_normalized", "jug_flag", "hana_flag", "oki_flag", "bt_flag"]].copy()
    work = daily_frame.merge(master, left_on="machine_name", right_on="machine_name_normalized", how="inner")
    if work.empty:
        return _empty_layout_frame()

    jug_flag = pd.to_numeric(work["jug_flag"], errors="coerce").fillna(0).astype(int)
    hana_flag = pd.to_numeric(work["hana_flag"], errors="coerce").fillna(0).astype(int)
    oki_flag = pd.to_numeric(work["oki_flag"], errors="coerce").fillna(0).astype(int)
    bt_flag = pd.to_numeric(work["bt_flag"], errors="coerce").fillna(0).astype(int)
    work["segment"] = np.select(
        [
            jug_flag.eq(1),
            hana_flag.eq(1),
            oki_flag.eq(1),
            bt_flag.eq(1),
        ],
        ["jug", "hana", "oki", "bt"],
        default="other",
    )
    return summarize_group_performance(
        work, "segment", min_group_size=min_group_size, sort_by=sort_by, ascending=ascending
    )


def format_rate_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a display copy with *_rate columns shown as percentages."""

    if frame.empty:
        return frame.copy()

    work = frame.copy()
    for column in work.columns:
        if column in {"avg_payout_rate", "payout_rate"}:
            numeric = pd.to_numeric(work[column], errors="coerce")
            work[column] = numeric.map(lambda value: "" if pd.isna(value) else f"{value:.1f}%")
        elif column.endswith("_rate"):
            numeric = pd.to_numeric(work[column], errors="coerce")
            work[column] = numeric.map(lambda value: "" if pd.isna(value) else f"{value * 100:.1f}%")
        elif column in {"avg_diff", "avg_games", "hit104_count", "n"}:
            numeric = pd.to_numeric(work[column], errors="coerce")
            if column in {"avg_diff", "avg_games"}:
                work[column] = numeric.map(lambda value: "" if pd.isna(value) else f"{value:.0f}")
            else:
                work[column] = numeric.map(lambda value: "" if pd.isna(value) else f"{int(value)}")
    return work


def build_top_rank_table(
    daily_frame: pd.DataFrame,
    *,
    group_column: str,
    sort_by: str,
    min_group_size: int = DEFAULT_GROUP_MIN_SIZE,
    ascending: bool = False,
) -> pd.DataFrame:
    """Build a ranked summary for the daily page top5 sections."""

    return summarize_group_performance(
        daily_frame,
        group_column,
        min_group_size=min_group_size,
        sort_by=sort_by,
        ascending=ascending,
    )


def build_visual_group_frames(
    daily_frame: pd.DataFrame,
    *,
    layout_frame: pd.DataFrame,
    master_frame: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Build chart-ready daily group summaries for reusable visual sections."""

    frames: dict[str, pd.DataFrame] = {
        "machine_name": summarize_group_performance(daily_frame, "machine_name"),
        "last_digit": summarize_group_performance(daily_frame, "last_digit"),
    }

    if not layout_frame.empty:
        if "rank_from_min" in layout_frame.columns:
            frames["rank_from_min"] = build_layout_summary(
                daily_frame,
                layout_frame,
                group_column="rank_from_min",
            )
        if "section" in layout_frame.columns:
            frames["section"] = build_layout_summary(
                daily_frame,
                layout_frame,
                group_column="section",
            )

    if not master_frame.empty:
        segment_frame = build_segment_summary(daily_frame, master_frame)
        if not segment_frame.empty:
            frames["segment"] = segment_frame

    return {key: value for key, value in frames.items() if not value.empty}


def build_daily_scatter_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the numeric columns needed for daily scatter plots."""

    work = add_hit104_flag(frame)
    columns = [
        "machine_number",
        "machine_name",
        "games_normalized",
        "diff_coins_normalized",
        "payout_rate",
        "hit104",
    ]
    available = [column for column in columns if column in work.columns]
    return work.loc[:, available].reset_index(drop=True)


def build_kpi_trend_frame(
    hall_summary: pd.DataFrame,
    target_date: pd.Timestamp,
    *,
    window_days: int = 30,
) -> pd.DataFrame:
    """Return a rolling KPI trend window ending on target_date."""

    required = {"date", "avg_diff_per_machine", "win_rate", "avg_games_per_machine"}
    if hall_summary.empty or not required.issubset(hall_summary.columns):
        return pd.DataFrame(columns=["date", "avg_diff_per_machine", "win_rate", "avg_games_per_machine"])

    work = hall_summary.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    target_ts = pd.Timestamp(target_date)
    start_ts = target_ts - pd.Timedelta(days=max(int(window_days) - 1, 0))
    window = work.loc[
        (work["date"] >= start_ts) & (work["date"] <= target_ts),
        [
            "date",
            "avg_diff_per_machine",
            "win_rate",
            "avg_games_per_machine",
        ],
    ].copy()
    window = window.dropna(subset=["date"]).sort_values("date", kind="mergesort").reset_index(drop=True)
    if window.empty or not (window["date"] == target_ts).any():
        return pd.DataFrame(columns=["date", "avg_diff_per_machine", "win_rate", "avg_games_per_machine"])
    return window


def compute_diff_distribution_stats(frame: pd.DataFrame) -> dict[str, float]:
    """Return mean, median, and count for diff_coins_normalized."""

    if frame.empty or "diff_coins_normalized" not in frame.columns:
        return {"mean": float("nan"), "median": float("nan"), "n": 0}

    diff = pd.to_numeric(frame["diff_coins_normalized"], errors="coerce").dropna()
    if diff.empty:
        return {"mean": float("nan"), "median": float("nan"), "n": 0}

    return {
        "mean": float(diff.mean()),
        "median": float(diff.median()),
        "n": int(diff.shape[0]),
    }


def build_kakuban_section_pivot(
    daily_frame: pd.DataFrame,
    layout_frame: pd.DataFrame,
    *,
    min_group_size: int = DEFAULT_GROUP_MIN_SIZE,
) -> pd.DataFrame:
    """Return a tidy rank_from_min x section summary for the visual heatmap."""

    required = {"machine_number", "rank_from_min", "section"}
    if daily_frame.empty or layout_frame.empty or not required.issubset(layout_frame.columns):
        return pd.DataFrame(columns=["rank_from_min", "section", "n", "avg_diff", "win_rate", "hit104_rate"])

    work = daily_frame.merge(
        layout_frame.loc[:, ["machine_number", "rank_from_min", "section"]], on="machine_number", how="inner"
    )
    if work.empty:
        return pd.DataFrame(columns=["rank_from_min", "section", "n", "avg_diff", "win_rate", "hit104_rate"])

    grouped = _build_group_summary_frame(work, ["rank_from_min", "section"])
    if grouped.empty:
        return pd.DataFrame(
            columns=["rank_from_min", "section", "machine_name", "n", "avg_diff", "win_rate", "hit104_rate"]
        )

    if "machine_name" in work.columns:

        def _join_unique_names(series: pd.Series) -> str:
            values = [str(value) for value in series.dropna().tolist() if str(value).strip()]
            return " / ".join(dict.fromkeys(values))

        names = (
            work.groupby(["rank_from_min", "section"], dropna=False, sort=True)["machine_name"]
            .agg(_join_unique_names)
            .reset_index()
        )
        grouped = grouped.merge(names, on=["rank_from_min", "section"], how="left")
    else:
        grouped["machine_name"] = ""

    grouped = grouped.loc[
        :, ["rank_from_min", "section", "machine_name", "n", "avg_diff", "win_rate", "hit104_rate"]
    ].copy()
    undersized = grouped["n"] < int(min_group_size)
    grouped.loc[undersized, ["avg_diff", "win_rate", "hit104_rate"]] = np.nan
    return grouped.reset_index(drop=True)


def build_daily_highlight_summary(frame: pd.DataFrame, *, machine_label: str) -> str:
    """Generate a compact text summary from the strongest machine-name group."""

    grouped = summarize_group_performance(frame, "machine_name")
    if grouped.empty:
        return f"{machine_label}: no standout machine group found."

    top = grouped.iloc[0]
    avg_diff = float(top["avg_diff"]) if pd.notna(top["avg_diff"]) else np.nan
    win_rate = float(top["win_rate"]) if pd.notna(top["win_rate"]) else np.nan
    hit104_rate = float(top["hit104_rate"]) if pd.notna(top["hit104_rate"]) else np.nan

    return (
        f"{machine_label}: top group {top['machine_name']} "
        f"avg_diff={avg_diff:.0f}, "
        f"win_rate={win_rate * 100:.1f}%, "
        f"hit104_rate={hit104_rate * 100:.1f}%."
    )
