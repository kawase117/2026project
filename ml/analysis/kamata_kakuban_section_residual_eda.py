from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kruskal

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.analysis.kamata_corner_mirror_analysis import infer_hall_name, _read_machine_master_flags


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_1 = PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田1.db"
DEFAULT_DB_7 = PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田7.db"
DEFAULT_COORDS_1 = PROJECT_ROOT / "Heatmap" / "2F_floor_coordinates_kamata1.csv"
DEFAULT_COORDS_7_2F = PROJECT_ROOT / "Heatmap" / "2F_floor_coordinates_kamata7.csv"
DEFAULT_COORDS_7_3F = PROJECT_ROOT / "Heatmap" / "3F_floor_coordinates_kamata7.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "ml" / "analysis" / "results" / "kamata_kakuban_section_residual_eda"
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "report.md"
DEFAULT_MIN_GAMES_ANALYSIS = 400
DEFAULT_MIN_SECTION_SIZE = 3

WEEKDAY_ORDER = {
    "mon": 0,
    "monday": 0,
    "月": 0,
    "月曜": 0,
    "mon曜日": 0,
    "tue": 1,
    "tuesday": 1,
    "火": 1,
    "火曜": 1,
    "wed": 2,
    "wednesday": 2,
    "水": 2,
    "水曜": 2,
    "thu": 3,
    "thursday": 3,
    "木": 3,
    "木曜": 3,
    "fri": 4,
    "friday": 4,
    "金": 4,
    "金曜": 4,
    "sat": 5,
    "saturday": 5,
    "土": 5,
    "土曜": 5,
    "sun": 6,
    "sunday": 6,
    "日": 6,
    "日曜": 6,
}


@dataclass(frozen=True)
class SegmentSpec:
    hall_slug: str
    hall_name: str
    floor: str
    db_path: Path
    coords_path: Path


def build_segment_key(*, hall_slug: str, floor: str, is_a_type: bool) -> str:
    return f"{hall_slug}_{floor}_{'A' if is_a_type else 'N'}"


def _read_machine_detailed_results(db_path: Path) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        frame = pd.read_sql_query(
            """
            SELECT
                date,
                machine_number,
                machine_name,
                diff_coins_normalized,
                games_normalized
            FROM machine_detailed_results
            """,
            conn,
        )
    if frame.empty:
        raise ValueError(f"machine_detailed_results returned no rows in {db_path}")
    return frame


def _read_daily_hall_summary(db_path: Path) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        cols = pd.read_sql_query("PRAGMA table_info(daily_hall_summary)", conn)["name"].tolist()
        select_cols = ["date"]
        for column in ("is_event_day", "day_of_week"):
            if column in cols:
                select_cols.append(column)
        query = f"SELECT {', '.join(select_cols)} FROM daily_hall_summary"
        frame = pd.read_sql_query(query, conn)
    if frame.empty:
        return pd.DataFrame(columns=["date", "is_event_day", "day_of_week"])
    return frame


def _read_coordinates_with_section_fallback(coords_path: Path, *, hall_name: str, floor: str) -> pd.DataFrame:
    coords = pd.read_csv(coords_path)
    required = {"hall_name", "floor", "machine_number", "X", "Y", "section"}
    missing = required - set(coords.columns)
    if missing:
        raise ValueError(f"Missing coordinate columns in {coords_path}: {sorted(missing)}")

    coords = coords[(coords["hall_name"] == hall_name) & (coords["floor"] == floor)].copy()
    if coords.empty:
        raise ValueError(f"No coordinates found for hall={hall_name!r}, floor={floor!r}")
    if coords["machine_number"].duplicated().any():
        dupes = sorted(coords.loc[coords["machine_number"].duplicated(), "machine_number"].unique().tolist())
        raise ValueError(f"Duplicate machine_number values in {coords_path}: {dupes}")

    if "rank_from_min" not in coords.columns or "rank_from_max" not in coords.columns:
        coords["machine_number"] = pd.to_numeric(coords["machine_number"], errors="coerce")
        coords["section"] = coords["section"].fillna("unknown").astype(str)
        coords["rank_from_min"] = coords.groupby("section", dropna=False)["machine_number"].transform(
            lambda s: s.rank(method="first", ascending=True)
        )
        coords["rank_from_max"] = coords.groupby("section", dropna=False)["machine_number"].transform(
            lambda s: s.rank(method="first", ascending=False)
        )

    for column in ("machine_number", "X", "Y", "rank_from_min", "rank_from_max"):
        coords[column] = pd.to_numeric(coords[column], errors="coerce")
    coords = coords.dropna(subset=["machine_number", "X", "Y"]).copy()
    coords["machine_number"] = coords["machine_number"].astype(int)
    coords["section"] = coords["section"].fillna("unknown").astype(str)
    return coords


def _normalize_day_label(value: object) -> tuple[int | None, str]:
    if pd.isna(value):
        return None, ""
    if isinstance(value, (int, np.integer)) and 0 <= int(value) <= 6:
        return int(value), str(value)
    text = str(value).strip()
    key = text.lower()
    if key in WEEKDAY_ORDER:
        return WEEKDAY_ORDER[key], text
    if text in WEEKDAY_ORDER:
        return WEEKDAY_ORDER[text], text
    return None, text


def _section_size_group(section_size: float | int | pd.Series) -> str:
    size = pd.to_numeric(section_size, errors="coerce")
    if pd.isna(size):
        return "unknown"
    if int(size) <= 8:
        return "small"
    if int(size) <= 14:
        return "medium"
    return "large"


def _bh_adjust(p_values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(p_values, errors="coerce")
    out = pd.Series(np.nan, index=p_values.index, dtype=float)
    valid = numeric.dropna()
    if valid.empty:
        return out
    order = valid.sort_values().index.tolist()
    sorted_p = valid.loc[order].to_numpy(dtype=float)
    n = len(sorted_p)
    adjusted = sorted_p * n / np.arange(1, n + 1)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    adjusted = np.clip(adjusted, 0.0, 1.0)
    out.loc[order] = adjusted
    return out


def _kruskal_pvalue(groups: list[pd.Series]) -> float:
    clean = [pd.to_numeric(group, errors="coerce").dropna().astype(float) for group in groups if len(group.dropna()) > 0]
    if len(clean) < 2:
        return float("nan")
    if any(len(group) < 2 for group in clean):
        return float("nan")
    try:
        return float(kruskal(*clean).pvalue)
    except ValueError:
        return float("nan")


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def _df_to_markdown(df: pd.DataFrame) -> str:
    if df.empty:
        return "No significant rows."
    frame = df.copy()
    columns = [str(col) for col in frame.columns.tolist()]
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join(["---"] * len(columns)) + " |"
    rows = []
    for _, row in frame.iterrows():
        values = []
        for col in frame.columns:
            value = row[col]
            values.append("" if pd.isna(value) else str(value))
        rows.append("| " + " | ".join(values) + " |")
    return "\n".join([header, separator, *rows])


def _build_report(summary: dict[str, pd.DataFrame], segment_meta: pd.DataFrame) -> str:
    lines = [
        "# Kamata kakuban section residual EDA report",
        "",
        "Section residual = `diff_coins_normalized - section_mean`.",
        "The section mean is computed from raw section-day rows before the `games_normalized >= 400` analysis filter.",
        "Rows from section-days with fewer than 3 machines are excluded from residual analysis by setting the residual to NaN.",
        "",
        "## 1. 分析設計の概要",
        "",
        "This run removes section-level quality first, then re-tests kakuban effects on the residuals.",
        "Analysis is performed on the expanded min/max kakuban view so both sides of each section are visible.",
        "",
        "## 2. Segment coverage",
        "",
    ]
    lines.append(_df_to_markdown(segment_meta))
    lines.append("")

    for title, key in [
        ("3. Analysis A: 角番 × 残差", "analysis_a"),
        ("4. Analysis B: 角番 × イベント日 × 残差", "analysis_b"),
        ("5. Analysis C: 角番 × 曜日 × 残差", "analysis_c"),
        ("6. セクションサイズ別層別結果", "section_size"),
    ]:
        lines.append(f"## {title}")
        frame = summary.get(key, pd.DataFrame())
        if frame.empty:
            lines.append("No significant rows.")
            lines.append("")
            continue
        lines.append(_df_to_markdown(frame))
        lines.append("")

    lines.append("## 7. 結論")
    conclusion = summary.get("conclusion", pd.DataFrame())
    if conclusion.empty:
        lines.append("No residual signal survived the section adjustment at q < 0.05.")
    else:
        lines.append(_df_to_markdown(conclusion))
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _summarize_section_sizes(coords: pd.DataFrame) -> pd.DataFrame:
    section_sizes = (
        coords.groupby("section", as_index=False)
        .agg(section_size=("machine_number", "nunique"))
        .assign(section_size_group=lambda df: df["section_size"].map(_section_size_group))
    )
    return section_sizes


def _prepare_segment_frame(
    spec: SegmentSpec,
    *,
    min_games: int = DEFAULT_MIN_GAMES_ANALYSIS,
    min_section_size: int = DEFAULT_MIN_SECTION_SIZE,
) -> pd.DataFrame:
    raw = _read_machine_detailed_results(spec.db_path)
    coords = _read_coordinates_with_section_fallback(spec.coords_path, hall_name=spec.hall_name, floor=spec.floor)
    daily = _read_daily_hall_summary(spec.db_path)
    section_sizes = _summarize_section_sizes(coords)

    raw["date"] = pd.to_datetime(raw["date"], format="%Y%m%d", errors="coerce")
    raw["machine_number"] = pd.to_numeric(raw["machine_number"], errors="coerce")
    raw["diff_coins_normalized"] = pd.to_numeric(raw["diff_coins_normalized"], errors="coerce")
    raw["games_normalized"] = pd.to_numeric(raw["games_normalized"], errors="coerce")
    raw = raw.dropna(subset=["date", "machine_number", "diff_coins_normalized", "games_normalized"]).copy()
    raw["machine_number"] = raw["machine_number"].astype(int)
    raw["date"] = raw["date"].dt.normalize()

    machine_master = _read_machine_master_flags(spec.db_path)
    coords = coords.copy()
    coords["section"] = coords["section"].fillna("unknown").astype(str)
    coords["rank_from_min"] = pd.to_numeric(coords["rank_from_min"], errors="coerce")
    coords["rank_from_max"] = pd.to_numeric(coords["rank_from_max"], errors="coerce")
    coords["section_size"] = coords["section"].map(section_sizes.set_index("section")["section_size"])
    coords["section_size_group"] = coords["section"].map(section_sizes.set_index("section")["section_size_group"])

    merged = raw.merge(coords, on="machine_number", how="inner", validate="many_to_one")
    if merged.empty:
        raise ValueError(f"No rows remained after joining {spec.db_path.name} and {spec.coords_path.name}")

    if not machine_master.empty:
        merged = merged.merge(
            machine_master,
            left_on="machine_name",
            right_on="machine_name_normalized",
            how="left",
            validate="many_to_one",
        )
    else:
        merged["machine_name_normalized"] = merged["machine_name"]
        merged["jug_flag"] = 0
        merged["hana_flag"] = 0
        merged["bt_flag"] = 0

    for column in ("jug_flag", "hana_flag", "bt_flag"):
        merged[column] = pd.to_numeric(merged[column], errors="coerce").fillna(0).astype(int)
    is_a = (merged["jug_flag"] == 1) | (merged["hana_flag"] == 1)
    if spec.floor == "2F":
        is_a = is_a | (merged["bt_flag"] == 1)
    merged["machine_type_segment"] = np.where(is_a, "A", "N")

    if not daily.empty:
        daily["date"] = pd.to_datetime(daily["date"], format="%Y%m%d", errors="coerce")
        daily = daily.dropna(subset=["date"]).copy()
        daily["date"] = daily["date"].dt.normalize()
        daily = daily.drop_duplicates(subset=["date"])
        merged = merged.merge(daily, on="date", how="left", validate="many_to_one")
    else:
        merged["is_event_day"] = pd.NA
        merged["day_of_week"] = pd.NA

    if "is_event_day" in merged.columns:
        merged["is_event_day"] = pd.to_numeric(merged["is_event_day"], errors="coerce")
    else:
        merged["is_event_day"] = pd.NA
    if "day_of_week" not in merged.columns:
        merged["day_of_week"] = pd.NA
    merged["section"] = merged["section"].fillna("unknown").astype(str)
    merged["section_size"] = pd.to_numeric(merged["section_size"], errors="coerce")
    merged["section_size_group"] = merged["section_size"].map(_section_size_group)

    section_counts = (
        merged.groupby(["date", "section"], as_index=False)
        .agg(section_n=("machine_number", "size"), section_mean=("diff_coins_normalized", "mean"))
    )
    section_counts.loc[section_counts["section_n"] < min_section_size, "section_mean"] = np.nan

    merged = merged.merge(section_counts, on=["date", "section"], how="left", validate="many_to_one")
    merged["section_mean"] = pd.to_numeric(merged["section_mean"], errors="coerce")
    merged["residual"] = merged["diff_coins_normalized"] - merged["section_mean"]
    merged["section_n"] = pd.to_numeric(merged["section_n"], errors="coerce")

    merged["games_normalized"] = pd.to_numeric(merged["games_normalized"], errors="coerce")
    merged["residual_eligible"] = merged["residual"].notna() & merged["games_normalized"].ge(min_games)

    merged["kakuban_min"] = pd.to_numeric(merged["rank_from_min"], errors="coerce").astype("Int64")
    merged["kakuban_max"] = pd.to_numeric(merged["rank_from_max"], errors="coerce").astype("Int64")
    return merged


def _expand_dual_kakuban(frame: pd.DataFrame) -> pd.DataFrame:
    part_min = frame.copy()
    part_min["kakuban_side"] = "min"
    part_min["kakuban"] = part_min["kakuban_min"]
    part_max = frame.copy()
    part_max["kakuban_side"] = "max"
    part_max["kakuban"] = part_max["kakuban_max"]
    expanded = pd.concat([part_min, part_max], ignore_index=True)
    expanded["kakuban"] = pd.to_numeric(expanded["kakuban"], errors="coerce").astype("Int64")
    return expanded


def _build_analysis_a(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame[frame["residual_eligible"]].copy()
    work = _expand_dual_kakuban(work).dropna(subset=["kakuban", "residual"]).copy()
    if work.empty:
        return pd.DataFrame(columns=["kakuban", "mean_residual", "median_residual", "n", "kruskal_p", "kruskal_q"])

    rows: list[dict[str, object]] = []
    for kakuban_value, kakuban_df in work.groupby("kakuban", sort=True):
        own = kakuban_df["residual"].astype(float)
        rest = work.loc[~work["kakuban"].eq(kakuban_value), "residual"].astype(float)
        p_value = _kruskal_pvalue([own, rest])
        rows.append(
            {
                "kakuban": int(kakuban_value),
                "mean_residual": float(own.mean()),
                "median_residual": float(own.median()),
                "n": int(len(own)),
                "kruskal_p": p_value,
            }
        )

    out = pd.DataFrame(rows)
    out["kruskal_q"] = _bh_adjust(out["kruskal_p"])
    out = out.sort_values(["kruskal_q", "kakuban"], na_position="last").reset_index(drop=True)
    return out


def _build_analysis_b(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame[frame["residual_eligible"]].copy()
    work = _expand_dual_kakuban(work).dropna(subset=["kakuban", "residual", "is_event_day"]).copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "kakuban",
                "event_mean_residual",
                "non_event_mean_residual",
                "event_delta_residual",
                "event_n",
                "non_event_n",
                "kruskal_p",
                "kruskal_q",
            ]
        )

    work["is_event_day"] = pd.to_numeric(work["is_event_day"], errors="coerce")
    rows: list[dict[str, object]] = []
    for kakuban_value, kakuban_df in work.groupby("kakuban", sort=True):
        event_vals = kakuban_df.loc[kakuban_df["is_event_day"].eq(1), "residual"].astype(float)
        non_event_vals = kakuban_df.loc[kakuban_df["is_event_day"].eq(0), "residual"].astype(float)
        p_value = _kruskal_pvalue([event_vals, non_event_vals])
        event_mean = float(event_vals.mean()) if len(event_vals) else np.nan
        non_event_mean = float(non_event_vals.mean()) if len(non_event_vals) else np.nan
        rows.append(
            {
                "kakuban": int(kakuban_value),
                "event_mean_residual": event_mean,
                "non_event_mean_residual": non_event_mean,
                "event_delta_residual": event_mean - non_event_mean if np.isfinite(event_mean) and np.isfinite(non_event_mean) else np.nan,
                "event_n": int(len(event_vals)),
                "non_event_n": int(len(non_event_vals)),
                "kruskal_p": p_value,
            }
        )

    out = pd.DataFrame(rows)
    out["kruskal_q"] = _bh_adjust(out["kruskal_p"])
    out = out.sort_values(["kruskal_q", "kakuban"], na_position="last").reset_index(drop=True)
    return out


def _weekday_mean_columns(work: pd.DataFrame) -> tuple[list[str], pd.DataFrame]:
    working = work.copy()
    working["weekday_sort"], working["weekday_label"] = zip(*working["day_of_week"].map(_normalize_day_label))
    working = working[working["weekday_sort"].notna() & working["weekday_label"].ne("")].copy()
    if working.empty:
        return [], working
    order = (
        working[["weekday_sort", "weekday_label"]]
        .drop_duplicates()
        .sort_values(["weekday_sort", "weekday_label"], na_position="last")
        ["weekday_label"]
        .tolist()
    )
    return order, working


def _build_analysis_c(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame[frame["residual_eligible"] & frame["is_event_day"].eq(0)].copy()
    work = _expand_dual_kakuban(work).dropna(subset=["kakuban", "residual", "day_of_week"]).copy()
    if work.empty:
        return pd.DataFrame(columns=["kakuban", "weekday_spread", "top_weekday", "bottom_weekday", "kruskal_p", "kruskal_q"])

    weekday_order, work = _weekday_mean_columns(work)
    if not weekday_order:
        return pd.DataFrame(columns=["kakuban", "weekday_spread", "top_weekday", "bottom_weekday", "kruskal_p", "kruskal_q"])

    rows: list[dict[str, object]] = []
    for kakuban_value, kakuban_df in work.groupby("kakuban", sort=True):
        row: dict[str, object] = {"kakuban": int(kakuban_value)}
        groups: list[pd.Series] = []
        weekday_means: list[tuple[str, float]] = []
        for weekday_label in weekday_order:
            values = kakuban_df.loc[kakuban_df["weekday_label"].eq(weekday_label), "residual"].astype(float)
            row[f"weekday_mean_{weekday_label}"] = float(values.mean()) if len(values) else np.nan
            if len(values):
                groups.append(values)
                weekday_means.append((weekday_label, float(values.mean())))
        p_value = _kruskal_pvalue(groups)
        if weekday_means:
            ordered = sorted(weekday_means, key=lambda item: item[1], reverse=True)
            top_weekday, top_value = ordered[0]
            bottom_weekday, bottom_value = ordered[-1]
            spread = top_value - bottom_value
        else:
            top_weekday = ""
            bottom_weekday = ""
            spread = np.nan
        row.update(
            {
                "weekday_spread": spread,
                "top_weekday": top_weekday,
                "bottom_weekday": bottom_weekday,
                "kruskal_p": p_value,
            }
        )
        rows.append(row)

    out = pd.DataFrame(rows)
    out["kruskal_q"] = _bh_adjust(out["kruskal_p"])
    out = out.sort_values(["kruskal_q", "kakuban"], na_position="last").reset_index(drop=True)
    return out


def _build_section_size_analysis_b(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame[frame["residual_eligible"]].copy()
    work = _expand_dual_kakuban(work).dropna(subset=["kakuban", "residual", "section_size_group", "is_event_day"]).copy()
    work["is_event_day"] = pd.to_numeric(work["is_event_day"], errors="coerce")
    work = work[work["section_size_group"].isin(["small", "medium", "large"])].copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "section_size_group",
                "kakuban",
                "event_mean_residual",
                "non_event_mean_residual",
                "event_delta_residual",
                "event_n",
                "non_event_n",
                "kruskal_p",
                "kruskal_q",
            ]
        )

    rows: list[dict[str, object]] = []
    for section_size_group in ["small", "medium", "large"]:
        block = work[work["section_size_group"].eq(section_size_group)].copy()
        for kakuban_value, kakuban_df in block.groupby("kakuban", sort=True):
            event_vals = kakuban_df.loc[kakuban_df["is_event_day"].eq(1), "residual"].astype(float)
            non_event_vals = kakuban_df.loc[kakuban_df["is_event_day"].eq(0), "residual"].astype(float)
            p_value = _kruskal_pvalue([event_vals, non_event_vals])
            event_mean = float(event_vals.mean()) if len(event_vals) else np.nan
            non_event_mean = float(non_event_vals.mean()) if len(non_event_vals) else np.nan
            rows.append(
                {
                    "section_size_group": section_size_group,
                    "kakuban": int(kakuban_value),
                    "event_mean_residual": event_mean,
                    "non_event_mean_residual": non_event_mean,
                    "event_delta_residual": event_mean - non_event_mean if np.isfinite(event_mean) and np.isfinite(non_event_mean) else np.nan,
                    "event_n": int(len(event_vals)),
                    "non_event_n": int(len(non_event_vals)),
                    "kruskal_p": p_value,
                }
            )

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["kruskal_q"] = np.nan
    for section_size_group, group_df in out.groupby("section_size_group"):
        out.loc[group_df.index, "kruskal_q"] = _bh_adjust(group_df["kruskal_p"])
    out = out.sort_values(["section_size_group", "kruskal_q", "kakuban"], na_position="last").reset_index(drop=True)
    return out


def _significant_rows(df: pd.DataFrame, *, q_col: str = "kruskal_q") -> pd.DataFrame:
    if df.empty or q_col not in df.columns:
        return df.iloc[0:0].copy()
    return df[pd.to_numeric(df[q_col], errors="coerce").lt(0.05)].copy()


def _safe_sort(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    available = [column for column in columns if column in df.columns]
    if len(available) != len(columns):
        return df.copy()
    return df.sort_values(columns, na_position="last").reset_index(drop=True)


def _empty_like(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame({column: pd.Series(dtype=frame[column].dtype if column in frame.columns else "object") for column in columns})


def _build_conclusion(
    *,
    analysis_a: pd.DataFrame,
    analysis_b: pd.DataFrame,
    analysis_c: pd.DataFrame,
    section_size: pd.DataFrame,
) -> pd.DataFrame:
    rows = []
    for name, frame in [
        ("Analysis A", analysis_a),
        ("Analysis B", analysis_b),
        ("Analysis C", analysis_c),
        ("Section size B", section_size),
    ]:
        sig = _significant_rows(frame)
        rows.append(
            {
                "analysis": name,
                "significant_rows": int(len(sig)),
                "smallest_q": float(pd.to_numeric(sig["kruskal_q"], errors="coerce").min()) if not sig.empty else np.nan,
                "interpretation": "residual effect survives" if not sig.empty else "signal disappears after section adjustment",
            }
        )
    return pd.DataFrame(rows)


def run_analysis(*, specs: list[SegmentSpec], output_dir: Path, report_path: Path) -> dict[str, pd.DataFrame]:
    output_dir.mkdir(parents=True, exist_ok=True)

    all_a: list[pd.DataFrame] = []
    all_b: list[pd.DataFrame] = []
    all_c: list[pd.DataFrame] = []
    all_section_b: list[pd.DataFrame] = []
    segment_meta_rows: list[dict[str, object]] = []

    for spec in specs:
        frame = _prepare_segment_frame(spec)
        for is_a_type in (True, False):
            segment_label = "A" if is_a_type else "N"
            segment_key = build_segment_key(hall_slug=spec.hall_slug, floor=spec.floor, is_a_type=is_a_type)
            type_frame = frame[frame["machine_type_segment"].eq(segment_label)].copy()

            segment_meta_rows.append(
                {
                    "hall": spec.hall_slug,
                    "floor": spec.floor,
                    "segment": segment_key,
                    "hall_name": spec.hall_name,
                    "db": spec.db_path.name,
                    "coords": spec.coords_path.name,
                    "rows": int(len(type_frame)),
                    "dates": int(pd.Index(type_frame["date"].dropna().unique()).size),
                    "sections": int(type_frame["section"].nunique()),
                }
            )

            if type_frame.empty:
                a_table = _empty_like(pd.DataFrame(), ["kakuban", "mean_residual", "median_residual", "n", "kruskal_p", "kruskal_q"])
                b_table = _empty_like(
                    pd.DataFrame(),
                    [
                        "kakuban",
                        "event_mean_residual",
                        "non_event_mean_residual",
                        "event_delta_residual",
                        "event_n",
                        "non_event_n",
                        "kruskal_p",
                        "kruskal_q",
                    ],
                )
                c_table = _empty_like(
                    pd.DataFrame(),
                    ["kakuban", "weekday_spread", "top_weekday", "bottom_weekday", "kruskal_p", "kruskal_q"],
                )
                section_b_table = _empty_like(
                    pd.DataFrame(),
                    [
                        "section_size_group",
                        "kakuban",
                        "event_mean_residual",
                        "non_event_mean_residual",
                        "event_delta_residual",
                        "event_n",
                        "non_event_n",
                        "kruskal_p",
                        "kruskal_q",
                    ],
                )
            else:
                a_table = _build_analysis_a(type_frame)
                b_table = _build_analysis_b(type_frame)
                c_table = _build_analysis_c(type_frame)
                section_b_table = _build_section_size_analysis_b(type_frame)

            out_prefix = f"{spec.hall_slug}_{spec.floor}_{segment_label}"
            _write_csv(a_table, output_dir / f"{out_prefix}_kakuban_residual_all.csv")
            _write_csv(b_table, output_dir / f"{out_prefix}_kakuban_event_residual.csv")
            _write_csv(c_table, output_dir / f"{out_prefix}_kakuban_weekday_residual.csv")
            _write_csv(section_b_table, output_dir / f"{out_prefix}_kakuban_event_by_section_size.csv")

            if not a_table.empty:
                all_a.append(a_table.assign(segment=segment_key, hall=spec.hall_slug, floor=spec.floor, analysis="A"))
            if not b_table.empty:
                all_b.append(b_table.assign(segment=segment_key, hall=spec.hall_slug, floor=spec.floor, analysis="B"))
            if not c_table.empty:
                all_c.append(c_table.assign(segment=segment_key, hall=spec.hall_slug, floor=spec.floor, analysis="C"))
            if not section_b_table.empty:
                all_section_b.append(
                    section_b_table.assign(segment=segment_key, hall=spec.hall_slug, floor=spec.floor, analysis="B_section")
                )

    analysis_a = pd.concat(all_a, ignore_index=True) if all_a else pd.DataFrame()
    analysis_b = pd.concat(all_b, ignore_index=True) if all_b else pd.DataFrame()
    analysis_c = pd.concat(all_c, ignore_index=True) if all_c else pd.DataFrame()
    section_size = pd.concat(all_section_b, ignore_index=True) if all_section_b else pd.DataFrame()

    significant_a = _significant_rows(analysis_a)
    significant_b = _significant_rows(analysis_b)
    significant_c = _significant_rows(analysis_c)
    significant_section = _significant_rows(section_size)
    conclusion = _build_conclusion(
        analysis_a=analysis_a,
        analysis_b=analysis_b,
        analysis_c=analysis_c,
        section_size=section_size,
    )

    report_sections = {
        "analysis_a": _safe_sort(significant_a, ["segment", "kruskal_q", "kakuban"]),
        "analysis_b": _safe_sort(significant_b, ["segment", "kruskal_q", "kakuban"]),
        "analysis_c": _safe_sort(significant_c, ["segment", "kruskal_q", "kakuban"]),
        "section_size": _safe_sort(significant_section, ["segment", "section_size_group", "kruskal_q", "kakuban"]),
        "conclusion": conclusion,
    }
    report = _build_report(report_sections, pd.DataFrame(segment_meta_rows))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    return {
        "analysis_a": analysis_a,
        "analysis_b": analysis_b,
        "analysis_c": analysis_c,
        "section_size": section_size,
        "significant_a": significant_a,
        "significant_b": significant_b,
        "significant_c": significant_c,
        "significant_section_size": significant_section,
        "conclusion": conclusion,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kamata kakuban section residual EDA.")
    parser.add_argument("--db1", type=Path, default=DEFAULT_DB_1)
    parser.add_argument("--db7", type=Path, default=DEFAULT_DB_7)
    parser.add_argument("--coords1", type=Path, default=DEFAULT_COORDS_1)
    parser.add_argument("--coords7-2f", dest="coords7_2f", type=Path, default=DEFAULT_COORDS_7_2F)
    parser.add_argument("--coords7-3f", dest="coords7_3f", type=Path, default=DEFAULT_COORDS_7_3F)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    specs = [
        SegmentSpec(
            hall_slug="kamata1",
            hall_name=infer_hall_name(args.coords1, floor="2F"),
            floor="2F",
            db_path=args.db1,
            coords_path=args.coords1,
        ),
        SegmentSpec(
            hall_slug="kamata7",
            hall_name=infer_hall_name(args.coords7_2f, floor="2F"),
            floor="2F",
            db_path=args.db7,
            coords_path=args.coords7_2f,
        ),
        SegmentSpec(
            hall_slug="kamata7",
            hall_name=infer_hall_name(args.coords7_3f, floor="3F"),
            floor="3F",
            db_path=args.db7,
            coords_path=args.coords7_3f,
        ),
    ]
    run_analysis(specs=specs, output_dir=args.output_dir, report_path=args.report_path)
    print(args.output_dir)
    print(args.report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
