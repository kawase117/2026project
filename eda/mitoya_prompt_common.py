from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from eda.core import load_hall_df

DB_PATH = Path(__file__).resolve().parents[1] / "db" / "みとや大森町店.db"
RESULTS_DIR = Path(__file__).resolve().parents[1] / "eda" / "results"
X_DDS = {4, 7, 14, 17, 24, 27}
EVENT_CATEGORY_ORDER = ["X_DDS", "ゾロ目日", "強ゾロ目", "月末", "非イベント日"]
WEEKDAY_ORDER = ["月", "火", "水", "木", "金", "土", "日"]
DEBUT_PHASE_ORDER = ["pre_existing", "debut", "growth", "mature"]
MITOYA_MAIN_SECTIONS = [
    "501-522",
    "523-539",
    "540-556",
    "557-573",
    "574-590",
    "591-607",
    "608-623",
]
MITOYA_ALL_SECTIONS = [
    "501-522",
    "523-539",
    "540-556",
    "557-573",
    "574-590",
    "591-607",
    "608-623",
    "624-640",
    "641-657",
    "658-674",
    "675-691",
    "692-700",
    "701-711",
    "712-722",
    "723-733",
    "734-744",
    "745-755",
    "805-815",
]


def connect_mitoya_db() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def render_markdown_table(df: pd.DataFrame, columns: Iterable[str] | None = None) -> str:
    frame = df.copy()
    if columns is not None:
        frame = frame.loc[:, list(columns)]
    if frame.empty:
        return "_no rows_"

    headers = list(frame.columns)
    rows = [headers]
    for _, row in frame.iterrows():
        rendered = []
        for col in headers:
            value = row[col]
            if value is None:
                rendered.append("")
            elif isinstance(value, (float, np.floating)):
                if np.isnan(value):
                    rendered.append("")
                else:
                    rendered.append(f"{float(value):.3f}" if abs(float(value)) < 100 else f"{float(value):.2f}")
            elif pd.isna(value):
                rendered.append("")
            else:
                rendered.append(str(value))
        rows.append(rendered)

    widths = [max(len(str(row[i])) for row in rows) for i in range(len(headers))]
    lines = []
    lines.append("| " + " | ".join(str(headers[i]).ljust(widths[i]) for i in range(len(headers))) + " |")
    lines.append("| " + " | ".join("-" * widths[i] for i in range(len(headers))) + " |")
    for row in rows[1:]:
        lines.append("| " + " | ".join(str(row[i]).ljust(widths[i]) for i in range(len(headers))) + " |")
    return "\n".join(lines)


def section_sort_key(section: object) -> tuple[int, str]:
    text = "" if section is None or pd.isna(section) else str(section)
    prefix = text.split("_y", 1)[0]
    try:
        return int(prefix.split("-", 1)[0]), text
    except Exception:
        return 10_000, text


def load_machine_layout() -> pd.DataFrame:
    with connect_mitoya_db() as conn:
        layout = pd.read_sql_query(
            """
            SELECT
                machine_number,
                section,
                x,
                y,
                rank_from_min,
                rank_from_max,
                rank_from_aisle,
                is_reversed_section
            FROM machine_layout
            """,
            conn,
        )
    return layout


def load_mitoya_frame(*, join_layout: bool = True) -> pd.DataFrame:
    df = load_hall_df("みとや")
    if join_layout:
        layout = load_machine_layout()
        df = df.merge(layout, on="machine_number", how="left")
    return df


def add_event_category(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()

    date_dt = pd.to_datetime(work.get("date"), format="%Y%m%d", errors="coerce")
    work["date_dt"] = date_dt
    work["dd"] = pd.to_numeric(work.get("dd", date_dt.dt.day), errors="coerce").astype("Int64")
    work["mm"] = date_dt.dt.month.astype("Int64")
    work["is_xdds_day"] = work["dd"].isin(X_DDS).astype(int)
    work["is_zorome_day"] = work["dd"].isin({11, 22}).astype(int)
    work["is_strong_zorome_day"] = (work["dd"] == work["mm"]).fillna(False).astype(int)
    work["is_month_end"] = date_dt.dt.is_month_end.fillna(False).astype(int)
    work["event_category"] = np.select(
        [
            work["is_xdds_day"].eq(1),
            work["is_zorome_day"].eq(1),
            work["is_strong_zorome_day"].eq(1),
            work["is_month_end"].eq(1),
        ],
        ["X_DDS", "ゾロ目日", "強ゾロ目", "月末"],
        default="非イベント日",
    )
    work["event_category"] = pd.Categorical(work["event_category"], categories=EVENT_CATEGORY_ORDER, ordered=True)
    return work


def bucket_rank_from_aisle(rank: object, section_max: object) -> int | float:
    rank_value = pd.to_numeric(pd.Series([rank]), errors="coerce").iloc[0]
    max_value = pd.to_numeric(pd.Series([section_max]), errors="coerce").iloc[0]
    if pd.isna(rank_value) or pd.isna(max_value) or max_value <= 0:
        return float("nan")
    bucket = int(np.ceil(float(rank_value) / float(max_value) * 3.0))
    return max(1, min(bucket, 3))


def compute_top2_share(mean_diffs: pd.Series | pd.DataFrame) -> float:
    if isinstance(mean_diffs, pd.DataFrame):
        if "mean_diff" in mean_diffs.columns:
            series = pd.to_numeric(mean_diffs["mean_diff"], errors="coerce")
        else:
            series = pd.to_numeric(mean_diffs.iloc[:, 0], errors="coerce")
    else:
        series = pd.to_numeric(mean_diffs, errors="coerce")
    series = series.dropna().sort_values(ascending=False)
    if len(series) < 2:
        return float("nan")
    total = float(series.sum())
    if abs(total) < 100:
        return float("nan")
    return float(series.iloc[:2].sum() / abs(total))


def add_debut_phase(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    if "date" not in work.columns or "machine_name" not in work.columns or "machine_number" not in work.columns:
        raise ValueError("df must include date, machine_number, and machine_name")

    work["date_dt"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
    work["_row_order"] = np.arange(len(work))
    name_first_seen = (
        work.sort_values(["machine_name", "date_dt", "machine_number", "_row_order"])
        .groupby("machine_name", sort=False)
        .agg(
            first_seen_date=("date_dt", "first"),
        )
    )
    first_seen_machine_numbers = (
        work.loc[work["date_dt"].isin(name_first_seen["first_seen_date"])]
        .groupby("machine_name", sort=False)["machine_number"]
        .agg(lambda values: frozenset(pd.Series(values).dropna().astype(int).tolist()))
    )
    name_first_seen_map = {
        str(machine_name): {
            "first_seen_date": row["first_seen_date"],
            "initial_machine_numbers": first_seen_machine_numbers.get(machine_name, frozenset()),
        }
        for machine_name, row in name_first_seen.iterrows()
    }
    parts: list[pd.DataFrame] = []

    for machine_number, grp in work.sort_values(["machine_number", "date_dt", "machine_name", "_row_order"]).groupby(
        "machine_number", sort=False
    ):
        group = grp.sort_values(["date_dt", "machine_name", "_row_order"]).copy()
        group["_run_id"] = group["machine_name"].ne(group["machine_name"].shift()).cumsum()
        group["run_start"] = group.groupby("_run_id")["date_dt"].transform("first")
        first_date = group["date_dt"].iloc[0]
        debut_days: list[int | None] = []
        debut_phase: list[str] = []
        is_moved: list[bool] = []
        for _, row in group.iterrows():
            if pd.isna(row["date_dt"]) or pd.isna(row["run_start"]):
                debut_days.append(None)
                debut_phase.append("unknown")
                is_moved.append(False)
                continue
            name_info = name_first_seen_map.get(str(row["machine_name"]))
            moved = False
            if name_info is not None:
                first_seen_date = name_info["first_seen_date"]
                initial_machine_numbers = name_info["initial_machine_numbers"]
                if pd.notna(first_seen_date) and row["date_dt"] > first_seen_date:
                    moved = int(row["machine_number"]) not in {int(value) for value in initial_machine_numbers}
            if moved:
                debut_days.append(None if pd.isna(row["run_start"]) else int((row["date_dt"] - row["run_start"]).days))
                debut_phase.append("moved")
                is_moved.append(True)
                continue
            if row["run_start"] == first_date:
                debut_days.append(None)
                debut_phase.append("pre_existing")
                is_moved.append(False)
                continue
            days = int((row["date_dt"] - row["run_start"]).days)
            debut_days.append(days)
            is_moved.append(False)
            if days <= 30:
                debut_phase.append("debut")
            elif days <= 90:
                debut_phase.append("growth")
            else:
                debut_phase.append("mature")
        group["debut_days"] = pd.Series(debut_days, dtype=object, index=group.index)
        group["debut_phase"] = debut_phase
        group["is_moved"] = is_moved
        parts.append(group)

    out = pd.concat(parts, ignore_index=True)
    out = out.sort_values("_row_order").drop(columns=["_row_order", "_run_id", "run_start"], errors="ignore")
    return out.reset_index(drop=True)


def assign_debut_phase(df: pd.DataFrame) -> pd.DataFrame:
    return add_debut_phase(df)


def kw_epsilon_squared(statistic: float, n_groups: int, n_rows: int) -> float:
    if not np.isfinite(statistic) or n_groups < 2 or n_rows <= n_groups:
        return float("nan")
    return float(max((statistic - n_groups + 1) / (n_rows - n_groups), 0.0))


def ensure_results_dir() -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    return RESULTS_DIR
