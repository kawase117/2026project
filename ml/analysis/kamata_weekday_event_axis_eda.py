from __future__ import annotations

import argparse
import calendar
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kruskal
from statsmodels.stats.multitest import fdrcorrection

from ml.analysis.kamata_corner_mirror_analysis import (
    _read_coordinates,
    _read_machine_master_flags,
    infer_hall_name,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_1 = PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田1.db"
DEFAULT_DB_7 = PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田7.db"
DEFAULT_COORDS_1 = PROJECT_ROOT / "Heatmap" / "2F_floor_coordinates_kamata1.csv"
DEFAULT_COORDS_7_2F = PROJECT_ROOT / "Heatmap" / "2F_floor_coordinates_kamata7.csv"
DEFAULT_COORDS_7_3F = PROJECT_ROOT / "Heatmap" / "3F_floor_coordinates_kamata7.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "ml" / "analysis" / "results" / "kamata_weekday_event_axis_eda"
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "kamata_weekday_event_axis_eda_report.md"

EVENT_DAYS = {1, 7, 11, 17, 21, 27, 30}
WEEKDAY_LABELS = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
AXIS_ORDER = {"tail": 0, "kakuban": 1, "section": 2}
REPRO_COMPARE_SUFFIX = "weekday_with_without_event_compare_repro"


@dataclass(frozen=True)
class SegmentSpec:
    hall_slug: str
    hall_name: str
    floor: str
    db_path: Path
    coords_path: Path


def is_kamata_event_day(date: pd.Timestamp | str) -> bool:
    ts = pd.Timestamp(date)
    return int(ts.day) in EVENT_DAYS or int(ts.day) == int(calendar.monthrange(ts.year, ts.month)[1])


def build_segment_key(*, hall_slug: str, floor: str, is_a_type: bool) -> str:
    return f"{hall_slug}_{floor}_{'A' if is_a_type else 'N'}"


def classify_tail_axis(*, machine_number: int, is_zorome: int | bool) -> str:
    if int(is_zorome) == 1:
        return "ゾロ目"
    return str(int(machine_number) % 10)


def _read_machine_detailed_results(db_path: Path) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        cols = pd.read_sql_query("PRAGMA table_info(machine_detailed_results)", conn)["name"].tolist()
        select_cols = [
            "date",
            "machine_number",
            "machine_name",
            "diff_coins_normalized",
            "games_normalized",
        ]
        if "is_zorome" in cols:
            select_cols.append("is_zorome")
            query = f"SELECT {', '.join(select_cols)} FROM machine_detailed_results"
        else:
            query = """
                SELECT
                    date,
                    machine_number,
                    machine_name,
                    diff_coins_normalized,
                    games_normalized,
                    0 AS is_zorome
                FROM machine_detailed_results
            """
        frame = pd.read_sql_query(query, conn)
    if frame.empty:
        raise ValueError(f"machine_detailed_results returned no rows in {db_path}")
    return frame


def _build_segment_frame(spec: SegmentSpec) -> pd.DataFrame:
    raw = _read_machine_detailed_results(spec.db_path)
    coords = _read_coordinates(spec.coords_path, hall_name=spec.hall_name, floor=spec.floor)
    master = _read_machine_master_flags(spec.db_path)

    raw["date"] = pd.to_datetime(raw["date"], format="%Y%m%d", errors="coerce")
    raw["machine_number"] = pd.to_numeric(raw["machine_number"], errors="coerce")
    raw["machine_name"] = raw["machine_name"].astype(str)
    raw["diff_coins_normalized"] = pd.to_numeric(raw["diff_coins_normalized"], errors="coerce")
    raw["games_normalized"] = pd.to_numeric(raw["games_normalized"], errors="coerce")
    raw["is_zorome"] = pd.to_numeric(raw["is_zorome"], errors="coerce").fillna(0).astype(int)
    raw = raw.dropna(subset=["date", "machine_number", "machine_name", "diff_coins_normalized", "games_normalized"]).copy()
    raw["machine_number"] = raw["machine_number"].astype(int)
    raw["date"] = raw["date"].dt.normalize()

    merged = raw.merge(coords, on="machine_number", how="inner", validate="many_to_one")
    if merged.empty:
        raise ValueError(f"No rows remained after joining {spec.db_path.name} and {spec.coords_path.name}")

    if not master.empty:
        merged = merged.merge(
            master,
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

    for col in ("jug_flag", "hana_flag", "bt_flag"):
        merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0).astype(int)

    merged["is_a_type"] = ((merged["jug_flag"] == 1) | (merged["bt_flag"] == 1)).astype(int)
    merged["weekday"] = merged["date"].dt.dayofweek.astype(int)
    merged["weekday_label"] = merged["weekday"].map(WEEKDAY_LABELS)
    merged["is_event_day"] = merged["date"].map(is_kamata_event_day).astype(int)
    merged["tail_axis"] = np.where(merged["is_zorome"].eq(1), "ゾロ目", (merged["machine_number"] % 10).astype(int).astype(str))
    merged["kakuban_min"] = pd.to_numeric(merged["rank_from_min"], errors="coerce").astype("Int64")
    merged["kakuban_max"] = pd.to_numeric(merged["rank_from_max"], errors="coerce").astype("Int64")
    merged["section"] = merged["section"].fillna("unknown").astype(str)
    merged["segment_key"] = spec.hall_slug + "_" + spec.floor + "_" + np.where(merged["is_a_type"].eq(1), "A", "N")
    return merged


def _expand_dual_kakuban(frame: pd.DataFrame) -> pd.DataFrame:
    """各台-日行をkakuban_min/kakuban_maxで2行に展開し、'kakuban'列を生成する。"""
    part_min = frame.copy()
    part_min["kakuban"] = part_min["kakuban_min"]
    part_max = frame.copy()
    part_max["kakuban"] = part_max["kakuban_max"]
    return pd.concat([part_min, part_max], ignore_index=True)


def _summarize_daily_cells(frame: pd.DataFrame, *, axis_col: str, subgroup_cols: tuple[str, ...]) -> pd.DataFrame:
    work = frame.copy()
    work["mean_diff"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work["mean_games"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    work["win_flag"] = (work["mean_diff"] > 0).astype(float)

    group_cols = ["date", axis_col, *subgroup_cols]
    daily = (
        work.groupby(group_cols, as_index=False)
        .agg(
            mean_diff=("mean_diff", "mean"),
            win_rate=("win_flag", "mean"),
            mean_games=("mean_games", "mean"),
            n_machines=("machine_number", "size"),
        )
        .copy()
    )
    return daily


def apply_min_date_filter(frame: pd.DataFrame, *, axis_col: str, subgroup_col: str, min_dates: int) -> pd.DataFrame:
    if frame.empty:
        out = frame.copy()
        out["n_dates"] = pd.Series(dtype=int)
        return out

    work = frame.copy()
    counts = work.groupby([axis_col, subgroup_col])["date"].transform("nunique")
    work["n_dates"] = counts.astype(int)
    return work[work["n_dates"] >= int(min_dates)].copy()


def _kruskal_from_groups(groups: list[pd.Series]) -> float:
    clean_groups = [pd.to_numeric(g, errors="coerce").dropna().astype(float) for g in groups if len(g.dropna()) > 0]
    if len(clean_groups) < 2:
        return float("nan")
    if any(len(g) < 2 for g in clean_groups):
        return float("nan")
    try:
        return float(kruskal(*clean_groups).pvalue)
    except ValueError:
        return float("nan")


def _attach_fdr(summary: pd.DataFrame, *, p_col: str, q_col: str) -> pd.DataFrame:
    out = summary.copy()
    out[q_col] = np.nan
    valid = pd.to_numeric(out[p_col], errors="coerce").notna()
    if valid.any():
        _reject, qvals = fdrcorrection(pd.to_numeric(out.loc[valid, p_col], errors="coerce").to_numpy(dtype=float))
        out.loc[valid, q_col] = qvals
    return out


def _weekday_spread(cell_summary: pd.DataFrame) -> tuple[float, str, str]:
    if cell_summary.empty:
        return float("nan"), "", ""
    ordered = cell_summary.sort_values(["mean_diff", "weekday"], ascending=[False, True]).reset_index(drop=True)
    top = ordered.iloc[0]
    bottom = ordered.iloc[-1]
    spread = float(top["mean_diff"] - bottom["mean_diff"])
    return spread, str(top["weekday"]), str(bottom["weekday"])


def _build_event_summary(daily: pd.DataFrame, *, axis_col: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    filtered = apply_min_date_filter(daily, axis_col=axis_col, subgroup_col="is_event_day", min_dates=10)
    if filtered.empty:
        empty = pd.DataFrame(columns=[axis_col, "is_event_day", "mean_diff", "win_rate", "mean_games", "n_dates", "n_machines"])
        stats = pd.DataFrame(columns=[axis_col, "event_mean_diff", "non_event_mean_diff", "event_minus_non_event", "kruskal_p"])
        return empty, stats

    cell_summary = (
        filtered.groupby([axis_col, "is_event_day"], as_index=False)
        .agg(
            mean_diff=("mean_diff", "mean"),
            win_rate=("win_rate", "mean"),
            mean_games=("mean_games", "mean"),
            n_dates=("n_dates", "max"),
            n_machines=("n_machines", "sum"),
        )
        .copy()
    )

    stat_rows: list[dict[str, object]] = []
    for axis_value, axis_df in filtered.groupby(axis_col, sort=False):
        event_vals = axis_df.loc[axis_df["is_event_day"].eq(1), "mean_diff"]
        non_event_vals = axis_df.loc[axis_df["is_event_day"].eq(0), "mean_diff"]
        p_value = _kruskal_from_groups([event_vals, non_event_vals])
        event_mean = float(event_vals.mean()) if len(event_vals) else np.nan
        non_event_mean = float(non_event_vals.mean()) if len(non_event_vals) else np.nan
        stat_rows.append(
            {
                axis_col: axis_value,
                "event_mean_diff": event_mean,
                "non_event_mean_diff": non_event_mean,
                "event_minus_non_event": event_mean - non_event_mean if np.isfinite(event_mean) and np.isfinite(non_event_mean) else np.nan,
                "kruskal_p": p_value,
            }
        )

    stats = pd.DataFrame(stat_rows)
    stats = _attach_fdr(stats, p_col="kruskal_p", q_col="kruskal_q")
    event = cell_summary.merge(stats, on=axis_col, how="left", validate="many_to_one")
    event["analysis_type"] = "event"
    return event, stats


def _build_weekday_summary(daily: pd.DataFrame, *, axis_col: str, exclude_event_days: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = daily.copy()
    if exclude_event_days:
        work = work[work["is_event_day"].eq(0)].copy()
    filtered = apply_min_date_filter(work, axis_col=axis_col, subgroup_col="weekday", min_dates=10)
    if filtered.empty:
        empty = pd.DataFrame(columns=[axis_col, "weekday", "weekday_label", "mean_diff", "win_rate", "mean_games", "n_dates", "n_machines"])
        stats = pd.DataFrame(columns=[axis_col, "weekday_spread", "top_weekday", "bottom_weekday", "kruskal_p"])
        return empty, stats

    cell_summary = (
        filtered.groupby([axis_col, "weekday"], as_index=False)
        .agg(
            mean_diff=("mean_diff", "mean"),
            win_rate=("win_rate", "mean"),
            mean_games=("mean_games", "mean"),
            n_dates=("n_dates", "max"),
            n_machines=("n_machines", "sum"),
        )
        .copy()
    )
    cell_summary["weekday_label"] = cell_summary["weekday"].map(WEEKDAY_LABELS)

    stat_rows: list[dict[str, object]] = []
    for axis_value, axis_df in filtered.groupby(axis_col, sort=False):
        groups = [axis_df.loc[axis_df["weekday"].eq(weekday), "mean_diff"] for weekday in sorted(axis_df["weekday"].dropna().unique().tolist())]
        p_value = _kruskal_from_groups(groups)
        spread, top_weekday, bottom_weekday = _weekday_spread(
            cell_summary[cell_summary[axis_col].eq(axis_value)][["weekday", "mean_diff"]]
        )
        stat_rows.append(
            {
                axis_col: axis_value,
                "weekday_spread": spread,
                "top_weekday": top_weekday,
                "bottom_weekday": bottom_weekday,
                "kruskal_p": p_value,
            }
        )

    stats = pd.DataFrame(stat_rows)
    stats = _attach_fdr(stats, p_col="kruskal_p", q_col="kruskal_q")
    weekday = cell_summary.merge(stats, on=axis_col, how="left", validate="many_to_one")
    weekday["analysis_type"] = "weekday_no_event" if exclude_event_days else "weekday_all"
    return weekday, stats


def _build_weekday_compare(full_stats: pd.DataFrame, no_event_stats: pd.DataFrame, *, axis_col: str) -> pd.DataFrame:
    full = full_stats[[axis_col, "weekday_spread", "kruskal_p", "kruskal_q"]].copy()
    full = full.rename(
        columns={
            "weekday_spread": "weekday_spread_with_event",
            "kruskal_p": "kruskal_p_with_event",
            "kruskal_q": "kruskal_q_with_event",
        }
    )
    no_event = no_event_stats[[axis_col, "weekday_spread", "kruskal_p", "kruskal_q"]].copy()
    no_event = no_event.rename(
        columns={
            "weekday_spread": "weekday_spread_without_event",
            "kruskal_p": "kruskal_p_without_event",
            "kruskal_q": "kruskal_q_without_event",
        }
    )
    compare = full.merge(no_event, on=axis_col, how="outer", validate="one_to_one")

    def _judge(row: pd.Series) -> str:
        q_full = pd.to_numeric(row.get("kruskal_q_with_event"), errors="coerce")
        q_no = pd.to_numeric(row.get("kruskal_q_without_event"), errors="coerce")
        spread_full = pd.to_numeric(row.get("weekday_spread_with_event"), errors="coerce")
        spread_no = pd.to_numeric(row.get("weekday_spread_without_event"), errors="coerce")
        if pd.isna(q_full) and pd.isna(q_no):
            return "insufficient"
        if pd.notna(q_full) and (pd.isna(q_no) or q_full < q_no):
            if pd.notna(spread_full) and (pd.isna(spread_no) or spread_full >= spread_no):
                return "with_event_stronger"
        if pd.notna(q_no) and (pd.isna(q_full) or q_no < q_full):
            if pd.notna(spread_no) and (pd.isna(spread_full) or spread_no >= spread_full):
                return "without_event_stronger"
        if pd.notna(spread_full) and pd.notna(spread_no):
            if spread_full > spread_no and (pd.isna(q_no) or (pd.notna(q_full) and q_full <= q_no)):
                return "with_event_stronger"
            if spread_no > spread_full and (pd.isna(q_full) or (pd.notna(q_no) and q_no <= q_full)):
                return "without_event_stronger"
        return "tie_or_mixed"

    compare["judgement"] = compare.apply(_judge, axis=1)
    return compare


def _split_frame_by_date_half(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp | None]:
    if frame.empty or "date" not in frame.columns:
        return frame.copy(), frame.copy(), None

    dates = pd.Index(pd.to_datetime(frame["date"], errors="coerce").dropna().sort_values().unique())
    if len(dates) == 0:
        return frame.iloc[0:0].copy(), frame.iloc[0:0].copy(), None

    split_index = max(1, len(dates) // 2)
    first_dates = dates[:split_index]
    second_dates = dates[split_index:]
    first_half = frame[frame["date"].isin(first_dates)].copy()
    second_half = frame[frame["date"].isin(second_dates)].copy()
    cutoff = pd.Timestamp(first_dates[-1]) if len(first_dates) else None
    return first_half, second_half, cutoff


def _build_weekday_compare_row(frame: pd.DataFrame, *, axis_col: str, axis_value: object) -> dict[str, object] | None:
    axis_frame = frame[frame[axis_col].eq(axis_value)].copy()
    if axis_frame.empty:
        return None

    daily = _summarize_daily_cells(axis_frame, axis_col=axis_col, subgroup_cols=("weekday", "is_event_day"))
    _, weekday_all_stats = _build_weekday_summary(daily, axis_col=axis_col, exclude_event_days=False)
    _, weekday_no_event_stats = _build_weekday_summary(daily, axis_col=axis_col, exclude_event_days=True)
    compare = _build_weekday_compare(weekday_all_stats, weekday_no_event_stats, axis_col=axis_col)
    if compare.empty:
        return None

    row = compare.iloc[0].to_dict()
    row["n_dates"] = int(axis_frame["date"].nunique())
    row["period_start"] = pd.Timestamp(axis_frame["date"].min())
    row["period_end"] = pd.Timestamp(axis_frame["date"].max())
    row["axis_value"] = axis_value
    return row


def _build_weekday_reproducibility_summary(
    *,
    segment_frame: pd.DataFrame,
    axis_col: str,
    compare_targets: pd.DataFrame,
) -> pd.DataFrame:
    if compare_targets.empty:
        return pd.DataFrame(
            columns=[
                axis_col,
                "axis_value",
                "full_judgement",
                "full_kruskal_q_with_event",
                "full_kruskal_q_without_event",
                "first_half_judgement",
                "first_half_kruskal_q_with_event",
                "first_half_kruskal_q_without_event",
                "first_half_weekday_spread_with_event",
                "first_half_weekday_spread_without_event",
                "first_half_n_dates",
                "second_half_judgement",
                "second_half_kruskal_q_with_event",
                "second_half_kruskal_q_without_event",
                "second_half_weekday_spread_with_event",
                "second_half_weekday_spread_without_event",
                "second_half_n_dates",
                "same_judgement_as_full_first_half",
                "same_judgement_as_full_second_half",
                "same_judgement_both_halves",
                "same_direction_both_halves",
                "repro_status",
            ]
        )

    rows: list[dict[str, object]] = []
    for _, target in compare_targets.iterrows():
        axis_value = target[axis_col]
        axis_frame = segment_frame[segment_frame[axis_col].eq(axis_value)].copy()
        first_half, second_half, cutoff = _split_frame_by_date_half(axis_frame)
        first_row = _build_weekday_compare_row(first_half, axis_col=axis_col, axis_value=axis_value)
        second_row = _build_weekday_compare_row(second_half, axis_col=axis_col, axis_value=axis_value)

        full_judgement = str(target.get("judgement", ""))
        first_judgement = str(first_row.get("judgement", "")) if first_row else ""
        second_judgement = str(second_row.get("judgement", "")) if second_row else ""

        rows.append(
            {
                axis_col: axis_value,
                "axis_value": axis_value,
                "full_judgement": full_judgement,
                "full_kruskal_q_with_event": target.get("kruskal_q_with_event"),
                "full_kruskal_q_without_event": target.get("kruskal_q_without_event"),
                "full_weekday_spread_with_event": target.get("weekday_spread_with_event"),
                "full_weekday_spread_without_event": target.get("weekday_spread_without_event"),
                "cutoff_date": cutoff,
                "first_half_judgement": first_judgement,
                "first_half_kruskal_q_with_event": first_row.get("kruskal_q_with_event") if first_row else np.nan,
                "first_half_kruskal_q_without_event": first_row.get("kruskal_q_without_event") if first_row else np.nan,
                "first_half_weekday_spread_with_event": first_row.get("weekday_spread_with_event") if first_row else np.nan,
                "first_half_weekday_spread_without_event": first_row.get("weekday_spread_without_event") if first_row else np.nan,
                "first_half_n_dates": first_row.get("n_dates") if first_row else 0,
                "first_half_start_date": first_row.get("period_start") if first_row else pd.NaT,
                "first_half_end_date": first_row.get("period_end") if first_row else pd.NaT,
                "second_half_judgement": second_judgement,
                "second_half_kruskal_q_with_event": second_row.get("kruskal_q_with_event") if second_row else np.nan,
                "second_half_kruskal_q_without_event": second_row.get("kruskal_q_without_event") if second_row else np.nan,
                "second_half_weekday_spread_with_event": second_row.get("weekday_spread_with_event") if second_row else np.nan,
                "second_half_weekday_spread_without_event": second_row.get("weekday_spread_without_event") if second_row else np.nan,
                "second_half_n_dates": second_row.get("n_dates") if second_row else 0,
                "second_half_start_date": second_row.get("period_start") if second_row else pd.NaT,
                "second_half_end_date": second_row.get("period_end") if second_row else pd.NaT,
                "same_judgement_as_full_first_half": bool(first_judgement and first_judgement == full_judgement),
                "same_judgement_as_full_second_half": bool(second_judgement and second_judgement == full_judgement),
                "same_judgement_both_halves": bool(first_judgement and second_judgement and first_judgement == second_judgement),
                "same_direction_both_halves": bool(
                    first_judgement == "without_event_stronger" and second_judgement == "without_event_stronger"
                ),
                "repro_status": (
                    "stable_without_event_stronger"
                    if first_judgement == "without_event_stronger" and second_judgement == "without_event_stronger"
                    else "stable_full_judgement"
                    if first_judgement and second_judgement and first_judgement == second_judgement == full_judgement
                    else "mixed"
                ),
            }
        )

    summary = pd.DataFrame(rows)
    if summary.empty:
        return summary

    summary["target_priority"] = np.where(
        summary["repro_status"].eq("stable_without_event_stronger"),
        0,
        np.where(summary["same_judgement_both_halves"], 1, 2),
    )
    summary = summary.sort_values(
        ["target_priority", "same_direction_both_halves", "first_half_n_dates", axis_col],
        ascending=[True, False, False, True],
        na_position="last",
    ).drop(columns=["target_priority"])
    return summary.reset_index(drop=True)


def _sort_axis_values(values: pd.Series, axis_name: str) -> pd.Series:
    if axis_name == "tail":
        tail_order = {"ゾロ目": -1}
        order = pd.to_numeric(values, errors="coerce").fillna(99).astype(int)
        mapped = values.astype(str).map(tail_order).fillna(order)
        return pd.Series(mapped, index=values.index).astype(float)
    if axis_name == "kakuban":
        return pd.to_numeric(values, errors="coerce").fillna(9999)
    return values.astype(str).map(lambda s: s)


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def _df_to_markdown(df: pd.DataFrame) -> str:
    if df.empty:
        return "No significant rows."
    work = df.copy()
    columns = [str(col) for col in work.columns.tolist()]
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join(["---"] * len(columns)) + " |"
    body_rows = []
    for _, row in work.iterrows():
        values = []
        for col in work.columns:
            value = row[col]
            values.append("" if pd.isna(value) else str(value))
        body_rows.append("| " + " | ".join(values) + " |")
    return "\n".join([header, separator, *body_rows])


def _build_report(sections: list[dict[str, pd.DataFrame]]) -> str:
    lines = [
        "# Kamata weekday / event axis EDA report",
        "",
        "FDR significant rows only (`q < 0.05`).",
        "",
    ]
    for section in sections:
        title = section["title"]
        frame = section["frame"]
        lines.append(f"## {title}")
        if frame.empty:
            lines.append("No significant rows.")
            lines.append("")
            continue
        lines.append(_df_to_markdown(frame))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def run_analysis(*, specs: list[SegmentSpec], output_dir: Path, report_path: Path) -> dict[str, pd.DataFrame]:
    output_dir.mkdir(parents=True, exist_ok=True)
    all_event: list[pd.DataFrame] = []
    all_weekday: list[pd.DataFrame] = []
    all_weekday_no_event: list[pd.DataFrame] = []
    all_compare: list[pd.DataFrame] = []
    all_repro: list[pd.DataFrame] = []
    report_sections: list[dict[str, pd.DataFrame]] = []

    for spec in specs:
        frame = _build_segment_frame(spec)
        for is_a_type in (1, 0):
            segment_frame = frame[frame["is_a_type"].eq(is_a_type)].copy()
            if segment_frame.empty:
                continue
            segment_label = "A" if is_a_type == 1 else "N"
            segment_key = build_segment_key(hall_slug=spec.hall_slug, floor=spec.floor, is_a_type=bool(is_a_type))
            for axis_name, axis_col in [("tail", "tail_axis"), ("kakuban", "kakuban"), ("section", "section")]:
                if axis_name == "kakuban":
                    ordered_frame = _expand_dual_kakuban(segment_frame)
                else:
                    ordered_frame = segment_frame.copy()
                if axis_name == "tail":
                    ordered_frame[axis_col] = ordered_frame[axis_col].astype(str)
                elif axis_name == "section":
                    ordered_frame[axis_col] = ordered_frame[axis_col].astype(str)
                else:
                    ordered_frame[axis_col] = pd.to_numeric(ordered_frame[axis_col], errors="coerce").astype("Int64")

                daily = _summarize_daily_cells(ordered_frame, axis_col=axis_col, subgroup_cols=("is_event_day",))
                event_table, event_stats = _build_event_summary(daily, axis_col=axis_col)
                weekday_all_daily = _summarize_daily_cells(ordered_frame, axis_col=axis_col, subgroup_cols=("weekday", "is_event_day"))
                weekday_all_table, weekday_all_stats = _build_weekday_summary(
                    weekday_all_daily,
                    axis_col=axis_col,
                    exclude_event_days=False,
                )
                weekday_no_event_table, weekday_no_event_stats = _build_weekday_summary(
                    weekday_all_daily,
                    axis_col=axis_col,
                    exclude_event_days=True,
                )
                compare_table = _build_weekday_compare(weekday_all_stats, weekday_no_event_stats, axis_col=axis_col)
                compare_targets = compare_table[
                    compare_table["judgement"].eq("without_event_stronger")
                    & pd.to_numeric(compare_table["kruskal_q_without_event"], errors="coerce").lt(0.05)
                ].copy()
                repro_table = _build_weekday_reproducibility_summary(
                    segment_frame=ordered_frame,
                    axis_col=axis_col,
                    compare_targets=compare_targets,
                )

                for table, suffix in [
                    (event_table, "event"),
                    (weekday_all_table, "weekday"),
                    (compare_table, "weekday_with_without_event_compare"),
                    (repro_table, REPRO_COMPARE_SUFFIX),
                ]:
                    out_path = output_dir / f"{spec.hall_slug}_{spec.floor}_{segment_label}_{axis_name}_{suffix}.csv"
                    if suffix == "event":
                        _write_csv(
                            table.sort_values(["kruskal_q", axis_col], na_position="last")
                            .assign(axis_name=axis_name, hall=spec.hall_slug, floor=spec.floor, segment=segment_key)
                            .reset_index(drop=True),
                            out_path,
                        )
                    elif suffix == "weekday":
                        _write_csv(
                            table.sort_values(["kruskal_q", axis_col, "weekday"], na_position="last")
                            .assign(axis_name=axis_name, hall=spec.hall_slug, floor=spec.floor, segment=segment_key)
                            .reset_index(drop=True),
                            out_path,
                        )
                    elif suffix == REPRO_COMPARE_SUFFIX:
                        _write_csv(
                            table.sort_values(
                                ["same_direction_both_halves", "same_judgement_both_halves", "first_half_n_dates", axis_col],
                                ascending=[False, False, False, True],
                                na_position="last",
                            )
                            .assign(axis_name=axis_name, hall=spec.hall_slug, floor=spec.floor, segment=segment_key)
                            .reset_index(drop=True),
                            out_path,
                        )
                    else:
                        _write_csv(
                            table.sort_values([f"kruskal_q_with_event", axis_col], na_position="last")
                            .assign(axis_name=axis_name, hall=spec.hall_slug, floor=spec.floor, segment=segment_key)
                            .reset_index(drop=True),
                            out_path,
                        )

                all_event.append(
                    event_table.assign(
                        axis_name=axis_name,
                        hall=spec.hall_slug,
                        floor=spec.floor,
                        segment=segment_key,
                    )
                )
                all_weekday.append(
                    weekday_all_table.assign(
                        axis_name=axis_name,
                        hall=spec.hall_slug,
                        floor=spec.floor,
                        segment=segment_key,
                    )
                )
                all_weekday_no_event.append(
                    weekday_no_event_table.assign(
                        axis_name=axis_name,
                        hall=spec.hall_slug,
                        floor=spec.floor,
                        segment=segment_key,
                    )
                )
                all_compare.append(
                    compare_table.assign(
                        axis_name=axis_name,
                        hall=spec.hall_slug,
                        floor=spec.floor,
                        segment=segment_key,
                    )
                )
                if not repro_table.empty:
                    all_repro.append(
                        repro_table.assign(
                            axis_name=axis_name,
                            hall=spec.hall_slug,
                            floor=spec.floor,
                            segment=segment_key,
                        )
                    )

    event_all = pd.concat(all_event, ignore_index=True) if all_event else pd.DataFrame()
    weekday_all = pd.concat(all_weekday, ignore_index=True) if all_weekday else pd.DataFrame()
    weekday_no_event_all = pd.concat(all_weekday_no_event, ignore_index=True) if all_weekday_no_event else pd.DataFrame()
    compare_all = pd.concat(all_compare, ignore_index=True) if all_compare else pd.DataFrame()
    repro_all = pd.concat(all_repro, ignore_index=True) if all_repro else pd.DataFrame()

    significant_frames = []
    if not event_all.empty and "kruskal_q" in event_all.columns:
        significant_frames.append(
            event_all[pd.to_numeric(event_all["kruskal_q"], errors="coerce") < 0.05].copy().assign(analysis="event")
        )
    if not weekday_all.empty and "kruskal_q" in weekday_all.columns:
        significant_frames.append(
            weekday_all[pd.to_numeric(weekday_all["kruskal_q"], errors="coerce") < 0.05].copy().assign(analysis="weekday_all")
        )
    if not weekday_no_event_all.empty and "kruskal_q" in weekday_no_event_all.columns:
        significant_frames.append(
            weekday_no_event_all[pd.to_numeric(weekday_no_event_all["kruskal_q"], errors="coerce") < 0.05]
            .copy()
            .assign(analysis="weekday_no_event")
        )
    significant = pd.concat(significant_frames, ignore_index=True) if significant_frames else pd.DataFrame()
    if not significant.empty:
        significant = significant.sort_values(
            ["analysis", "hall", "floor", "segment", "axis_name", "kruskal_q"],
            na_position="last",
        ).reset_index(drop=True)

    compare_sig = pd.DataFrame()
    if not compare_all.empty:
        compare_sig = compare_all[
            compare_all["judgement"].isin(["with_event_stronger", "without_event_stronger"])
        ].copy()
    repro_sig = pd.DataFrame()
    if not repro_all.empty:
        repro_sig = repro_all[repro_all["repro_status"].eq("stable_without_event_stronger")].copy()

    report_sections.extend(
        [
            {"title": "Significant event-day rows", "frame": significant[significant["analysis"].eq("event")] if not significant.empty else pd.DataFrame()},
            {"title": "Significant weekday rows (all data)", "frame": significant[significant["analysis"].eq("weekday_all")] if not significant.empty else pd.DataFrame()},
            {"title": "Significant weekday rows (event excluded)", "frame": significant[significant["analysis"].eq("weekday_no_event")] if not significant.empty else pd.DataFrame()},
            {"title": "Weekday with/without event comparison", "frame": compare_sig},
            {"title": "Reproducibility check across half periods", "frame": repro_sig},
        ]
    )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_build_report(report_sections), encoding="utf-8")

    return {
        "event": event_all,
        "weekday_all": weekday_all,
        "weekday_no_event": weekday_no_event_all,
        "compare": compare_all,
        "repro": repro_all,
        "significant": significant,
        "compare_significant": compare_sig,
        "repro_significant": repro_sig,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kamata weekday and event axis EDA.")
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
