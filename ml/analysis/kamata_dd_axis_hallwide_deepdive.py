from __future__ import annotations

import argparse
import calendar
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ml.analysis.kamata_dd_axis_deepdive import GROUP_ORDER, _compare_metric_with_halves, _event_group_mask
from ml.analysis.kamata_weekday_event_axis_deepdive import (
    _attach_fdr,
    _ensure_dir,
    _fmt,
    _md_table,
    _mwu,
    _split_frame_by_date_half,
    _write_csv,
    _write_text,
)
from ml.analysis.kamata_weekday_event_axis_eda import DEFAULT_COORDS_7_2F, DEFAULT_DB_7, infer_hall_name
from ml.analysis.kamata_weekday_event_axis_payoutrate_deepdive import compute_payoutrate_pct


if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = PROJECT_ROOT / "tmp" / "kamata_dd_hallwide_eda_deepdive"
TARGET_HALL_NAME = "kamata7"
_INFERRED_HALL_NAME = infer_hall_name(DEFAULT_COORDS_7_2F, floor="2F")
THRESHOLDS = (100.0, 104.0, 110.0)


def _ensure_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _dd_group_label(date: pd.Timestamp) -> str:
    day = int(date.day)
    month_end = int(calendar.monthrange(date.year, date.month)[1])
    if day == month_end:
        return "month_end_actual"
    if day == date.month:
        return "strong_zorome_mmdd"
    if day in {11, 22}:
        return "zorome_11_22"
    if day in {1, 11, 21, 31}:
        return "event_1"
    if day in {7, 17, 27}:
        return "event_7"
    return "other"


def _load_daily_hall_summary_frame(*, db_path: Path = DEFAULT_DB_7) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        frame = pd.read_sql_query(
            """
            SELECT
                date,
                total_machines,
                avg_games_per_machine,
                avg_diff_per_machine,
                win_rate
            FROM daily_hall_summary
            ORDER BY date
            """,
            conn,
        )
    if frame.empty:
        raise ValueError(f"daily_hall_summary returned no rows in {db_path}")
    return frame


def _build_hallwide_frame(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.normalize()
    work = work[work["date"].notna()].copy()
    work["total_machines"] = _ensure_numeric(work["total_machines"])
    work["avg_games_per_machine"] = _ensure_numeric(work["avg_games_per_machine"])
    work["avg_diff_per_machine"] = _ensure_numeric(work["avg_diff_per_machine"])
    work["win_rate"] = _ensure_numeric(work["win_rate"])
    work["payoutrate_pct"] = [
        compute_payoutrate_pct(diff, games)
        for diff, games in zip(work["avg_diff_per_machine"], work["avg_games_per_machine"], strict=False)
    ]
    work["dd"] = work["date"].dt.day.astype("Int64")
    work["mm"] = work["date"].dt.month.astype("Int64")
    work["dd_date_count"] = work["date"].dt.days_in_month.astype("Int64")
    work["is_event_7"] = work["dd"].isin([7, 17, 27]).astype(int)
    work["is_event_1"] = work["dd"].isin([1, 11, 21, 31]).astype(int)
    work["is_zorome_11_22"] = work["dd"].isin([11, 22]).astype(int)
    work["is_strong_zorome_mmdd"] = work["dd"].eq(work["mm"]).astype(int)
    work["is_month_end_actual"] = work["dd"].eq(work["dd_date_count"]).astype(int)
    work["is_all_event"] = (
        work["is_event_7"].eq(1)
        | work["is_event_1"].eq(1)
        | work["is_zorome_11_22"].eq(1)
        | work["is_strong_zorome_mmdd"].eq(1)
        | work["is_month_end_actual"].eq(1)
    ).astype(int)
    work["dd_group"] = work["date"].map(_dd_group_label)
    work["mean_excess_pct"] = work["payoutrate_pct"] - 100.0
    work["hit_100"] = (work["payoutrate_pct"] > 100.0).astype(float)
    work["hit_104"] = (work["payoutrate_pct"] > 104.0).astype(float)
    work["hit_110"] = (work["payoutrate_pct"] > 110.0).astype(float)
    work["entity_n_dates"] = int(work["date"].nunique())
    work["n_machines"] = work["total_machines"]
    return work.sort_values("date").reset_index(drop=True)


def _daily_summary(frame: pd.DataFrame, *, min_entity_dates: int = 1) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily = _build_hallwide_frame(frame)
    if daily.empty:
        empty = pd.DataFrame(
            columns=[
                "dd",
                "dd_label",
                "hit_rate_100",
                "hit_rate_104",
                "hit_rate_110",
                "mean_excess_pct",
                "median_payoutrate_pct",
                "cell_n_dates",
                "entity_n_dates",
                "n_machines",
            ]
        )
        return empty, daily

    entity_n_dates = int(daily["entity_n_dates"].iloc[0])
    if entity_n_dates < int(min_entity_dates):
        empty = pd.DataFrame(
            columns=[
                "dd",
                "dd_label",
                "hit_rate_100",
                "hit_rate_104",
                "hit_rate_110",
                "mean_excess_pct",
                "median_payoutrate_pct",
                "cell_n_dates",
                "entity_n_dates",
                "n_machines",
            ]
        )
        return empty, daily

    summary = (
        daily.groupby("dd", as_index=False)
        .agg(
            hit_rate_100=("hit_100", "mean"),
            hit_rate_104=("hit_104", "mean"),
            hit_rate_110=("hit_110", "mean"),
            mean_excess_pct=("mean_excess_pct", "mean"),
            median_payoutrate_pct=("payoutrate_pct", "median"),
            cell_n_dates=("date", "nunique"),
            entity_n_dates=("entity_n_dates", "max"),
            n_machines=("n_machines", "mean"),
        )
        .copy()
    )
    summary["dd"] = pd.to_numeric(summary["dd"], errors="coerce").astype("Int64")
    summary["dd_label"] = summary["dd"].map(lambda value: f"{int(value)}日" if pd.notna(value) else "")
    summary = summary.sort_values(
        ["hit_rate_104", "hit_rate_110", "hit_rate_100", "mean_excess_pct", "dd"],
        ascending=[False, False, False, False, True],
        na_position="last",
    ).reset_index(drop=True)
    summary.insert(0, "rank", np.arange(1, len(summary) + 1))
    return summary, daily


def _group_daily_frame(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for group_label in GROUP_ORDER:
        mask = _event_group_mask(frame["date"], group_label)
        subset = frame[mask].copy()
        if subset.empty:
            continue
        subset["group_label"] = group_label
        rows.append(subset)
    if not rows:
        return pd.DataFrame(
            columns=[
                "date",
                "group_label",
                "payoutrate_pct",
                "mean_excess_pct",
                "hit_100",
                "hit_104",
                "hit_110",
                "n_machines",
                "entity_n_dates",
            ]
        )
    return pd.concat(rows, ignore_index=True)


def _group_summary(frame: pd.DataFrame, *, min_entity_dates: int = 1) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    base_daily = _build_hallwide_frame(frame)
    daily = _group_daily_frame(base_daily)
    if daily.empty:
        empty_summary = pd.DataFrame(
            columns=[
                "group_label",
                "hit_rate_100",
                "hit_rate_104",
                "hit_rate_110",
                "mean_excess_pct",
                "median_payoutrate_pct",
                "cell_n_dates",
                "entity_n_dates",
                "n_machines",
            ]
        )
        return empty_summary, pd.DataFrame(), daily

    entity_n_dates = int(pd.to_numeric(daily["entity_n_dates"], errors="coerce").dropna().max())
    if entity_n_dates < int(min_entity_dates):
        empty_summary = pd.DataFrame(
            columns=[
                "group_label",
                "hit_rate_100",
                "hit_rate_104",
                "hit_rate_110",
                "mean_excess_pct",
                "median_payoutrate_pct",
                "cell_n_dates",
                "entity_n_dates",
                "n_machines",
            ]
        )
        return empty_summary, pd.DataFrame(), daily

    summary = (
        daily.groupby("group_label", as_index=False)
        .agg(
            hit_rate_100=("hit_100", "mean"),
            hit_rate_104=("hit_104", "mean"),
            hit_rate_110=("hit_110", "mean"),
            mean_excess_pct=("mean_excess_pct", "mean"),
            median_payoutrate_pct=("payoutrate_pct", "median"),
            cell_n_dates=("date", "nunique"),
            entity_n_dates=("entity_n_dates", "max"),
            n_machines=("n_machines", "mean"),
        )
        .copy()
    )
    summary["group_label"] = pd.Categorical(summary["group_label"], categories=GROUP_ORDER, ordered=True)
    summary = summary.sort_values(
        ["hit_rate_104", "hit_rate_110", "hit_rate_100", "mean_excess_pct", "group_label"],
        ascending=[False, False, False, False, True],
        na_position="last",
    ).reset_index(drop=True)
    summary["group_label"] = summary["group_label"].astype(str)
    summary.insert(0, "rank", np.arange(1, len(summary) + 1))

    compare_rows: list[pd.DataFrame] = []
    compare_labels = [label for label in GROUP_ORDER if label in {"event_7", "event_1", "zorome_11_22", "strong_zorome_mmdd", "month_end_actual", "all_event"}]
    for group_label in compare_labels:
        temp = base_daily.copy()
        temp["group_label"] = np.where(_event_group_mask(temp["date"], group_label), group_label, "non_event")
        compare_frame = _compare_metric_with_halves(temp, label_col="group_label")
        row = compare_frame[compare_frame["group_label"].astype(str).eq(group_label)].copy()
        if not row.empty:
            compare_rows.append(row)

    compare = pd.concat(compare_rows, ignore_index=True) if compare_rows else pd.DataFrame()
    if not compare.empty:
        compare = _attach_fdr(compare, p_col="p_value", q_col="q_value")
        compare["full_sig"] = pd.to_numeric(compare["q_value"], errors="coerce").lt(0.05)
        compare["first_half_sig"] = pd.to_numeric(compare.get("first_half_q_value"), errors="coerce").lt(0.05)
        compare["second_half_sig"] = pd.to_numeric(compare.get("second_half_q_value"), errors="coerce").lt(0.05)
        compare["same_direction"] = (
            compare["direction"].astype(str).eq(compare.get("first_half_direction").astype(str))
            & compare["direction"].astype(str).eq(compare.get("second_half_direction").astype(str))
        )
        compare["stable"] = compare["full_sig"] & compare["first_half_sig"] & compare["second_half_sig"] & compare["same_direction"]
        compare = compare.sort_values(["q_value", "p_value", "group_label"], na_position="last").reset_index(drop=True)
    return summary, compare, daily


def run_branch_a(frame: pd.DataFrame | None = None, *, output_root: Path = OUTPUT_ROOT) -> dict[str, object]:
    branch_dir = _ensure_dir(output_root / "branch_a")
    source = _load_daily_hall_summary_frame() if frame is None else frame.copy()
    work = _build_hallwide_frame(source)
    if work.empty:
        raise ValueError("No rows matched kamata7 daily_hall_summary")

    dd_summary, dd_daily = _daily_summary(work, min_entity_dates=1)
    dd_compare = _compare_metric_with_halves(dd_daily, label_col="dd")
    dd_group_summary, dd_group_compare, dd_group_daily = _group_summary(work, min_entity_dates=1)

    _write_csv(dd_summary, branch_dir / "dd_summary.csv")
    _write_csv(dd_daily, branch_dir / "hall_daily_summary.csv")
    _write_csv(dd_compare, branch_dir / "dd_compare.csv")
    _write_csv(dd_group_summary, branch_dir / "dd_group_summary.csv")
    _write_csv(dd_group_daily, branch_dir / "dd_group_daily.csv")
    _write_csv(dd_group_compare, branch_dir / "dd_group_compare.csv")

    stable_dd = dd_compare[dd_compare["stable"].eq(True)].copy()
    stable_group = dd_group_compare[dd_group_compare["stable"].eq(True)].copy()

    report = [
        "# Branch A",
        "",
        f"Target: {TARGET_HALL_NAME} hallwide daily_hall_summary.",
        "",
        "Event mapping:",
        "- `event_7` -> DD in {7, 17, 27}",
        "- `event_1` -> DD in {1, 11, 21, 31}",
        "- `zorome_11_22` -> DD in {11, 22}",
        "- `strong_zorome_mmdd` -> DD == MM",
        "- `month_end_actual` -> actual month end",
        "- `all_event` -> union of the five event groups above, compared against non-event days",
        "",
        "## DD summary",
        _md_table(dd_summary),
        "",
        "## DD split-half compare",
        _md_table(dd_compare),
        "",
        "## Event-group summary",
        _md_table(dd_group_summary),
        "",
        "## Event-group split-half compare",
        _md_table(dd_group_compare),
        "",
        f"Stable DD rows: {len(stable_dd)}.",
        f"Stable group rows: {len(stable_group)}.",
        "",
        "Conclusion: DD/event-day law is present only if stable rows survive split-half FDR checks at hall-wide scale.",
        "",
    ]
    _write_text(branch_dir / "report.md", "\n".join(report))

    return {
        "dd_summary": dd_summary,
        "dd_compare": dd_compare,
        "dd_group_summary": dd_group_summary,
        "dd_group_compare": dd_group_compare,
        "stable_count": int(len(stable_dd) + len(stable_group)),
        "report_path": branch_dir / "report.md",
        "output_root": branch_dir,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kamata DD hallwide deep dive")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_7)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    frame = _load_daily_hall_summary_frame(db_path=args.db_path)
    run_branch_a(frame, output_root=args.output_root)


if __name__ == "__main__":
    main()
