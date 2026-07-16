"""Generic hall theory engine for dashboard verification pages."""

from __future__ import annotations

import calendar
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from dashboard.utils.daily_report import add_hit104_flag

ROOT_DIR = Path(__file__).resolve().parents[2]
HALL_CONFIG_DIR = ROOT_DIR / "dashboard" / "config" / "hall_configs"
THEORY_REGISTRY_DIR = ROOT_DIR / "document" / "theory_registry"
DEFAULT_HALL_KEY = "kamata7"
THEORY_MIN_SAMPLE = 5


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        return {}
    return data


def _available_yaml_keys(directory: Path) -> list[str]:
    if not directory.exists():
        return []
    return sorted(path.stem for path in directory.glob("*.yaml"))


def _default_config() -> dict[str, Any]:
    config = load_hall_config(DEFAULT_HALL_KEY)
    return config if config else {}


@lru_cache(maxsize=None)
def load_hall_config(hall_key: str) -> dict[str, Any]:
    path = HALL_CONFIG_DIR / f"{hall_key}.yaml"
    if not path.exists():
        return {}
    data = _read_yaml(path)
    data.setdefault("hall", hall_key)
    data.setdefault("display_name", hall_key)
    data.setdefault("aliases", [])
    data.setdefault("floors", [])
    data.setdefault("family_keywords", {})
    data.setdefault("event_day", {})
    data.setdefault("cooling_zones", [])
    data.setdefault("durable_machine_numbers", [])
    data.setdefault("segment_scheme", {})
    data.setdefault("warnings", [])
    return data


@lru_cache(maxsize=None)
def load_theory_registry(hall_key: str) -> dict[str, Any]:
    path = THEORY_REGISTRY_DIR / f"{hall_key}.yaml"
    if not path.exists():
        return {"hall": hall_key, "claims": []}
    data = _read_yaml(path)
    data.setdefault("hall", hall_key)
    claims = data.get("claims", [])
    data["claims"] = claims if isinstance(claims, list) else []
    return data


def resolve_hall_key(hall_name: object = None, db_path: object = None) -> str:
    """Resolve a configured hall key from the current Streamlit state."""

    candidates: list[str] = []
    for value in [hall_name, db_path]:
        if value is None:
            continue
        candidates.append(str(value))

    text = " ".join(candidates).strip()
    if not text:
        return DEFAULT_HALL_KEY

    text_lower = text.lower()
    for hall_key in _available_yaml_keys(HALL_CONFIG_DIR):
        config = load_hall_config(hall_key)
        aliases = [hall_key, config.get("display_name", ""), *config.get("aliases", [])]
        for alias in aliases:
            alias_text = str(alias).strip()
            if not alias_text:
                continue
            if alias_text in text or alias_text.lower() in text_lower:
                return hall_key
    if "蒲田1" in text or "kamata1" in text_lower:
        return "kamata1"
    if "蒲田7" in text or "kamata7" in text_lower:
        return "kamata7"
    return DEFAULT_HALL_KEY


def _coerce_machine_number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").astype("Int64")


def _contains_any(text: str, keywords: list[str] | tuple[str, ...]) -> bool:
    return any(keyword and keyword in text for keyword in keywords)


def infer_floor(machine_number: object, hall_config: dict[str, Any] | None = None) -> str:
    """Infer the floor label from a machine number."""

    config = hall_config or _default_config()
    value = pd.to_numeric(pd.Series([machine_number]), errors="coerce").iloc[0]
    if pd.isna(value):
        return "不明"

    number = int(value)
    for floor in config.get("floors", []):
        start = floor.get("min_machine_number")
        end = floor.get("max_machine_number")
        label = floor.get("label", "不明")
        if start is None or end is None:
            continue
        if int(start) <= number <= int(end):
            return str(label)

    if 2000 <= number < 3000:
        return "2F"
    if 3000 <= number < 4000:
        return "3F"
    return "不明"


def infer_lr(layout: pd.DataFrame, hall_config: dict[str, Any] | None = None) -> pd.Series:
    """Infer L/R inside each section using the section median X coordinate."""

    config = hall_config or _default_config()
    out = pd.Series("不明", index=layout.index, dtype="string")
    if not config.get("use_lr", True):
        return out
    if layout.empty or "section" not in layout.columns:
        return out

    x_column = "x" if "x" in layout.columns else "X" if "X" in layout.columns else None
    if x_column is None:
        return out

    x = pd.to_numeric(layout[x_column], errors="coerce")
    section_nunique = x.groupby(layout["section"]).transform("nunique")
    section_median_x = x.groupby(layout["section"]).transform("median")
    floor_median_x = x.median()
    valid = x.notna() & section_median_x.notna()
    vertical = valid & (section_nunique == 1)
    normal = valid & ~vertical
    out.loc[normal & (x <= section_median_x)] = "L"
    out.loc[normal & (x > section_median_x)] = "R"
    out.loc[vertical & (x <= floor_median_x)] = "L"
    out.loc[vertical & (x > floor_median_x)] = "R"
    return out


def classify_setting_family(machine_name: object, hall_config: dict[str, Any] | None = None) -> str:
    """Classify the machine family used by hall-specific segment logic."""

    config = hall_config or _default_config()
    text = "" if machine_name is None else str(machine_name)
    family_keywords = config.get("family_keywords", {})
    a_keywords = family_keywords.get("A", [])
    if _contains_any(text, a_keywords):
        return "A"
    return "N"


def _classify_theory_segment_vectorized(frame: pd.DataFrame, hall_config: dict[str, Any]) -> pd.Series:
    """Vectorized equivalent of classify_theory_segment for whole-frame use.

    Row-wise DataFrame.apply(axis=1) plus a per-row pd.Series construction inside
    classify_theory_segment measured ~5x slower than the legacy hardcoded version
    on the full kamata7 history (260k rows, ~90s vs ~18s). This mask-based version
    avoids both per-row costs.
    """

    segment_scheme = hall_config.get("segment_scheme", {})
    definitions = segment_scheme.get("definitions", [])
    outside = str(segment_scheme.get("outside", "対象外"))

    result = pd.Series(outside, index=frame.index, dtype="object")
    matched = pd.Series(False, index=frame.index)
    for rule in definitions:
        conditions = rule.get("conditions", {})
        if not conditions:
            continue
        mask = pd.Series(True, index=frame.index)
        for field, expected in conditions.items():
            if field not in frame.columns:
                mask = pd.Series(False, index=frame.index)
                break
            if isinstance(expected, list):
                mask &= frame[field].isin(expected)
            else:
                mask &= frame[field].eq(expected)
        apply_mask = mask & ~matched
        result.loc[apply_mask] = str(rule.get("name", "不明"))
        matched |= mask
    return result


def _segment_labels_from_config(hall_config: dict[str, Any] | None = None) -> dict[str, str]:
    config = hall_config or _default_config()
    scheme = config.get("segment_scheme", {})
    labels = scheme.get("labels", {})
    fallback = scheme.get("outside", "対象外")
    out = {str(key): str(value) for key, value in labels.items()}
    out.setdefault(fallback, str(labels.get(fallback, fallback)))
    out.setdefault("不明", "不明")
    return out


def prepare_layout_segments(layout: pd.DataFrame, hall_config: dict[str, Any] | None = None) -> pd.DataFrame:
    """Attach floor, L/R, hanaban/kakuban and section-size fields needed by theory summaries."""

    config = hall_config or _default_config()
    if layout.empty or "machine_number" not in layout.columns:
        return pd.DataFrame()

    work = layout.copy()
    work["machine_number"] = _coerce_machine_number(work["machine_number"])
    work = work.dropna(subset=["machine_number"]).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work["floor"] = work["machine_number"].map(lambda value: infer_floor(value, config))
    work["lr"] = infer_lr(work, config)

    if {"section_min", "section_max"}.issubset(work.columns):
        section_min = pd.to_numeric(work["section_min"], errors="coerce")
        section_max = pd.to_numeric(work["section_max"], errors="coerce")
        work["section_size"] = (section_max - section_min + 1).astype("Int64")
    elif "section" in work.columns:
        work["section_size"] = work.groupby("section")["machine_number"].transform("nunique").astype("Int64")
    else:
        work["section_size"] = pd.NA

    if {"rank_from_min", "rank_from_max"}.issubset(work.columns):
        rank_from_min = pd.to_numeric(work["rank_from_min"], errors="coerce")
        rank_from_max = pd.to_numeric(work["rank_from_max"], errors="coerce")
        if config.get("hanaban_rule", "min_rank") == "min_rank":
            work["hanaban"] = pd.concat([rank_from_min, rank_from_max], axis=1).min(axis=1).astype("Int64")
        else:
            work["hanaban"] = rank_from_min.astype("Int64")
    elif "rank_from_min" in work.columns:
        work["hanaban"] = pd.to_numeric(work["rank_from_min"], errors="coerce").astype("Int64")
    else:
        work["hanaban"] = pd.NA

    if config.get("has_aisle") and "rank_from_aisle" in work.columns:
        work["kakuban"] = pd.to_numeric(work["rank_from_aisle"], errors="coerce").astype("Int64")
    else:
        work["kakuban"] = pd.NA
    return work


def is_event_day_series(dates: pd.Series, hall_config: dict[str, Any] | None = None) -> pd.Series:
    """Return the hall-specific event-day flag used by the dashboard."""

    config = hall_config or _default_config()
    event_day = config.get("event_day", {})
    digits = set(event_day.get("digits", []))
    parsed = pd.to_datetime(dates, errors="coerce")
    dd = parsed.dt.day
    is_event = dd.isin(digits)
    if event_day.get("use_month_end", True):
        month_end = parsed.map(
            lambda value: calendar.monthrange(value.year, value.month)[1] if pd.notna(value) else np.nan
        )
        is_event = is_event | dd.eq(month_end)
    if event_day.get("use_strong_mmdd", True):
        is_event = is_event | parsed.dt.month.eq(parsed.dt.day)
    return is_event.fillna(False)


def classify_event_kind(date_value: object, hall_config: dict[str, Any] | None = None) -> str:
    """Classify a date into a DD/event-family label."""

    config = hall_config or _default_config()
    parsed = pd.to_datetime(date_value, errors="coerce")
    if pd.isna(parsed):
        return "不明"

    event_day = config.get("event_day", {})
    digits = set(event_day.get("digits", []))
    dd = int(parsed.day)
    if dd in digits:
        return f"DD{dd}"

    month_end = calendar.monthrange(parsed.year, parsed.month)[1]
    if dd == month_end:
        return "月末"

    if parsed.month == parsed.day:
        return f"{parsed.month:02d}/{parsed.day:02d}ゾロ"

    return "その他"


def classify_cooling_zone(machine_number: object, hall_config: dict[str, Any] | None = None) -> str:
    """Classify known cooling-zone ranges."""

    config = hall_config or _default_config()
    value = pd.to_numeric(pd.Series([machine_number]), errors="coerce").iloc[0]
    if pd.isna(value):
        return "unknown"

    number = int(value)
    for zone in config.get("cooling_zones", []):
        for start, end in zone.get("ranges", []):
            if int(start) <= number <= int(end):
                return str(zone.get("name", "unknown"))
    return "outside"


def attach_theory_axes(
    machine_frame: pd.DataFrame,
    layout_frame: pd.DataFrame,
    hall_config: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Join machine rows to the theory axes used by the dashboard."""

    config = hall_config or _default_config()
    if machine_frame.empty:
        return pd.DataFrame()

    work = machine_frame.copy()
    work["machine_number"] = _coerce_machine_number(work["machine_number"])
    work = work.dropna(subset=["machine_number"]).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work["date"] = work["date"].astype(str)
    work["date_dt"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
    work["dd"] = work["date_dt"].dt.day.astype("Int64")

    machine_name = work["machine_name"] if "machine_name" in work.columns else pd.Series("", index=work.index)
    work["family"] = machine_name.map(lambda value: classify_setting_family(value, config))

    layout = prepare_layout_segments(layout_frame, config)
    if not layout.empty:
        keep_columns = [
            column
            for column in [
                "machine_number",
                "floor",
                "lr",
                "section",
                "section_min",
                "section_max",
                "section_size",
                "rank_from_min",
                "rank_from_max",
                "rank_from_aisle",
                "hanaban",
                "kakuban",
            ]
            if column in layout.columns
        ]
        work = work.merge(layout.loc[:, keep_columns], on="machine_number", how="left", validate="m:1")
    else:
        work["floor"] = work["machine_number"].map(lambda value: infer_floor(value, config))
        work["lr"] = "不明"
        work["hanaban"] = pd.NA
        work["kakuban"] = pd.NA

    if "hanaban" not in work.columns:
        if "rank_from_min" in work.columns and "rank_from_max" in work.columns:
            rank_from_min = pd.to_numeric(work["rank_from_min"], errors="coerce")
            rank_from_max = pd.to_numeric(work["rank_from_max"], errors="coerce")
            work["hanaban"] = pd.concat([rank_from_min, rank_from_max], axis=1).min(axis=1).astype("Int64")
        elif "rank_from_min" in work.columns:
            work["hanaban"] = pd.to_numeric(work["rank_from_min"], errors="coerce").astype("Int64")
        else:
            work["hanaban"] = pd.NA

    if "kakuban" not in work.columns:
        if config.get("has_aisle") and "rank_from_aisle" in work.columns:
            work["kakuban"] = pd.to_numeric(work["rank_from_aisle"], errors="coerce").astype("Int64")
        else:
            work["kakuban"] = pd.NA

    work["segment"] = _classify_theory_segment_vectorized(work, config)
    work["is_event_day"] = is_event_day_series(work["date_dt"], config)
    work["event_kind"] = work["date_dt"].map(lambda value: classify_event_kind(value, config))
    work["cooling_zone"] = work["machine_number"].map(lambda value: classify_cooling_zone(value, config))
    work["is_durable_machine"] = work["machine_number"].isin(
        {int(value) for value in config.get("durable_machine_numbers", [])}
    )
    return add_hit104_flag(work)


def load_theory_frame(db_path: str | Path) -> pd.DataFrame:
    """Load machine history and attach hall-specific theory axes."""

    path = Path(db_path)
    if not path.exists():
        return pd.DataFrame()

    hall_key = resolve_hall_key(db_path=path)
    config = load_hall_config(hall_key)
    try:
        with sqlite3.connect(str(path)) as con:
            machines = pd.read_sql_query("SELECT * FROM machine_detailed_results", con)
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
            layout = (
                pd.read_sql_query("SELECT * FROM machine_layout", con) if "machine_layout" in tables else pd.DataFrame()
            )
    except sqlite3.Error:
        return pd.DataFrame()
    return attach_theory_axes(machines, layout, config)


def filter_theory_frame(
    frame: pd.DataFrame,
    *,
    start_date: pd.Timestamp | None = None,
    end_date: pd.Timestamp | None = None,
    min_games: int = 0,
) -> pd.DataFrame:
    """Apply the shared dashboard filters before aggregation."""

    if frame.empty:
        return frame

    work = frame.copy()
    if start_date is not None:
        work = work.loc[work["date_dt"] >= pd.Timestamp(start_date)]
    if end_date is not None:
        work = work.loc[work["date_dt"] <= pd.Timestamp(end_date)]
    if min_games > 0 and "games_normalized" in work.columns:
        games = pd.to_numeric(work["games_normalized"], errors="coerce")
        work = work.loc[games >= int(min_games)]
    return work.reset_index(drop=True)


def summarize_by(frame: pd.DataFrame, group_columns: list[str], *, min_n: int = THEORY_MIN_SAMPLE) -> pd.DataFrame:
    """Build the common performance summary for one or more theory axes."""

    if frame.empty or any(column not in frame.columns for column in group_columns):
        return pd.DataFrame()

    work = frame.copy()
    for column in group_columns:
        if pd.api.types.is_numeric_dtype(work[column]):
            continue
        work[column] = work[column].fillna("不明")

    grouped = (
        work.groupby(group_columns, dropna=False)
        .agg(
            n=("machine_number", "size"),
            avg_diff=("diff_coins_normalized", "mean"),
            avg_games=("games_normalized", "mean"),
            win_rate=(
                "diff_coins_normalized",
                lambda s: (
                    float(pd.to_numeric(s, errors="coerce").dropna().gt(0).mean())
                    if pd.to_numeric(s, errors="coerce").notna().any()
                    else np.nan
                ),
            ),
            hit104_rate=(
                "hit104",
                lambda s: float(pd.to_numeric(s, errors="coerce").dropna().mean()) if s.notna().any() else np.nan,
            ),
        )
        .reset_index()
    )
    grouped = grouped.loc[grouped["n"] >= int(min_n)].copy()
    if grouped.empty:
        return grouped
    return grouped.sort_values(
        ["hit104_rate", "avg_diff", "n"], ascending=[False, False, False], kind="mergesort"
    ).reset_index(drop=True)


def build_dd_position_matrix(
    frame: pd.DataFrame, axis_column: str, *, metric: str = "avg_diff", min_n: int = THEORY_MIN_SAMPLE
) -> pd.DataFrame:
    """Return a DD x position-axis matrix for the requested metric."""

    if axis_column not in frame.columns:
        return pd.DataFrame()
    summary = summarize_by(frame, ["dd", axis_column], min_n=min_n)
    if summary.empty or metric not in summary.columns:
        return pd.DataFrame()
    return summary.pivot(index="dd", columns=axis_column, values=metric).sort_index().sort_index(axis=1)


def build_dd_kakuban_matrix(
    frame: pd.DataFrame, *, metric: str = "avg_diff", min_n: int = THEORY_MIN_SAMPLE
) -> pd.DataFrame:
    """Return a DD x kakuban matrix for the requested metric."""

    return build_dd_position_matrix(frame, "kakuban", metric=metric, min_n=min_n)


def build_dd_hanaban_matrix(
    frame: pd.DataFrame, *, metric: str = "avg_diff", min_n: int = THEORY_MIN_SAMPLE
) -> pd.DataFrame:
    """Return a DD x hanaban matrix for the requested metric."""

    return build_dd_position_matrix(frame, "hanaban", metric=metric, min_n=min_n)


def build_daily_event_summary(frame: pd.DataFrame, *, min_n: int = THEORY_MIN_SAMPLE) -> pd.DataFrame:
    """Summarize event days by date and event kind."""

    required = {"date_dt", "is_event_day", "machine_number", "diff_coins_normalized", "games_normalized"}
    if frame.empty or not required.issubset(frame.columns):
        return pd.DataFrame()

    work = frame.loc[frame["is_event_day"].eq(True)].copy()
    if work.empty:
        return pd.DataFrame()

    if "event_kind" not in work.columns:
        work["event_kind"] = work["date_dt"].map(classify_event_kind)
    daily = (
        work.groupby(["date_dt", "event_kind"], dropna=False)
        .agg(
            machine_count=("machine_number", "size"),
            total_diff=("diff_coins_normalized", "sum"),
            avg_diff=("diff_coins_normalized", "mean"),
            avg_games=("games_normalized", "mean"),
            hit104_rate=(
                "hit104",
                lambda s: float(pd.to_numeric(s, errors="coerce").dropna().mean()) if s.notna().any() else np.nan,
            ),
        )
        .reset_index()
    )
    daily = daily.loc[daily["machine_count"] >= int(min_n)].copy()
    if daily.empty:
        return daily

    total_diff_all = float(daily["total_diff"].sum()) if pd.notna(daily["total_diff"]).any() else 0.0
    daily["diff_share"] = daily["total_diff"] / total_diff_all if total_diff_all else np.nan
    daily["weekday"] = pd.to_datetime(daily["date_dt"], errors="coerce").dt.day_name()
    daily["date_label"] = pd.to_datetime(daily["date_dt"], errors="coerce").dt.strftime("%Y-%m-%d")
    return daily.sort_values(["total_diff", "date_dt"], ascending=[False, False], kind="mergesort").reset_index(
        drop=True
    )


def build_event_kind_summary(frame: pd.DataFrame, *, min_n: int = THEORY_MIN_SAMPLE) -> pd.DataFrame:
    """Summarize event days by event kind."""

    daily = build_daily_event_summary(frame, min_n=min_n)
    if daily.empty:
        return daily

    work = daily.copy()
    work["hit104_weighted"] = pd.to_numeric(work["hit104_rate"], errors="coerce").fillna(0) * pd.to_numeric(
        work["machine_count"], errors="coerce"
    ).fillna(0)
    summary = (
        work.groupby("event_kind", dropna=False)
        .agg(
            days=("date_dt", "nunique"),
            machine_count=("machine_count", "sum"),
            total_diff=("total_diff", "sum"),
            hit104_weighted=("hit104_weighted", "sum"),
        )
        .reset_index()
    )
    summary["avg_diff"] = summary["total_diff"] / summary["machine_count"]
    summary["avg_hit104_rate"] = summary["hit104_weighted"] / summary["machine_count"]
    summary = summary.drop(columns=["hit104_weighted"])
    total_diff_all = float(summary["total_diff"].sum()) if pd.notna(summary["total_diff"]).any() else 0.0
    summary["diff_share"] = summary["total_diff"] / total_diff_all if total_diff_all else np.nan
    return summary.sort_values(["total_diff", "days"], ascending=[False, False], kind="mergesort").reset_index(
        drop=True
    )


def build_event_bucket_summary(frame: pd.DataFrame, *, min_n: int = THEORY_MIN_SAMPLE) -> pd.DataFrame:
    """Summarize daily event rows into overlapping calendar buckets."""

    daily = build_daily_event_summary(frame, min_n=min_n)
    if daily.empty:
        return pd.DataFrame(
            columns=[
                "event_bucket",
                "days",
                "machine_count",
                "total_diff",
                "avg_diff",
                "avg_hit104_rate",
                "diff_share",
            ]
        )

    work = daily.copy()
    work["date_dt"] = pd.to_datetime(work["date_dt"], errors="coerce")
    work = work.dropna(subset=["date_dt"]).copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "event_bucket",
                "days",
                "machine_count",
                "total_diff",
                "avg_diff",
                "avg_hit104_rate",
                "diff_share",
            ]
        )

    dd = work["date_dt"].dt.day
    month_end = work["date_dt"].map(
        lambda value: calendar.monthrange(value.year, value.month)[1] if pd.notna(value) else np.nan
    )
    bucket_specs = [
        ("1のつく日", dd.isin({1, 11, 21, 31})),
        ("7のつく日", dd.isin({7, 17, 27})),
        ("ゾロ目の日", dd.isin({11, 22})),
        ("強ゾロ目の日", work["date_dt"].dt.month.eq(dd)),
        ("月末", dd.eq(month_end)),
        ("30日", dd.eq(30)),
    ]

    rows: list[dict[str, object]] = []
    for bucket_name, mask in bucket_specs:
        subset = work.loc[mask].copy()
        if subset.empty:
            continue

        total_diff = float(subset["total_diff"].sum()) if pd.notna(subset["total_diff"]).any() else 0.0
        machine_count = pd.to_numeric(subset["machine_count"], errors="coerce").fillna(0)
        hit104_rate = pd.to_numeric(subset["hit104_rate"], errors="coerce")
        weight_total = float(machine_count.sum())
        hit104_weighted = float((hit104_rate.fillna(0) * machine_count).sum())
        rows.append(
            {
                "event_bucket": bucket_name,
                "days": int(subset["date_dt"].nunique()),
                "machine_count": int(weight_total),
                "total_diff": total_diff,
                "avg_diff": float(total_diff / weight_total) if weight_total else np.nan,
                "avg_hit104_rate": float(hit104_weighted / weight_total) if weight_total else np.nan,
                "diff_share": total_diff,
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "event_bucket",
                "days",
                "machine_count",
                "total_diff",
                "avg_diff",
                "avg_hit104_rate",
                "diff_share",
            ]
        )

    summary = pd.DataFrame(rows)
    total_diff_all = float(summary["total_diff"].sum()) if pd.notna(summary["total_diff"]).any() else 0.0
    summary["diff_share"] = summary["total_diff"] / total_diff_all if total_diff_all else np.nan
    return summary.sort_values(["total_diff", "days"], ascending=[False, False], kind="mergesort").reset_index(
        drop=True
    )
