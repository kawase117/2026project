from __future__ import annotations

import argparse
import calendar
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ml.analysis.kamata_weekday_event_axis_deepdive import _attach_fdr, _ensure_dir, _fmt, _md_table, _mwu, _split_frame_by_date_half, _write_csv, _write_text
from ml.analysis.kamata_weekday_event_axis_eda import (
    DEFAULT_COORDS_1,
    DEFAULT_COORDS_7_2F,
    DEFAULT_COORDS_7_3F,
    DEFAULT_DB_1,
    DEFAULT_DB_7,
    infer_hall_name,
)
from ml.analysis.kamata_weekday_event_axis_payoutrate_deepdive import (
    SegmentSpec,
    _build_segment_frame,
    compute_payoutrate_pct,
)


if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = PROJECT_ROOT / "tmp" / "kamata_dd_axis_eda_deepdive"
TARGET_SECTION = "2179-2186"
TARGET_MACHINE_NUMBERS = tuple(range(2179, 2187))
TARGET_HALL_SLUG = "kamata7"
TARGET_FLOOR = "2F"

GROUP_ORDER = [
    "event_7",
    "event_1",
    "zorome_11_22",
    "strong_zorome_mmdd",
    "month_end_actual",
    "all_event",
]

def _ensure_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _event_group_mask(date_series: pd.Series, group_label: str) -> pd.Series:
    dates = pd.to_datetime(date_series, errors="coerce")
    day = dates.dt.day
    month = dates.dt.month
    month_end = dates.dt.days_in_month
    if group_label == "event_7":
        return day.isin([7, 17, 27])
    if group_label == "event_1":
        return day.isin([1, 11, 21, 31])
    if group_label == "zorome_11_22":
        return day.isin([11, 22])
    if group_label == "strong_zorome_mmdd":
        return day.eq(month)
    if group_label == "month_end_actual":
        return day.eq(month_end)
    if group_label == "all_event":
        return (
            day.isin([7, 17, 27])
            | day.isin([1, 11, 21, 31])
            | day.isin([11, 22])
            | day.eq(month)
            | day.eq(month_end)
        )
    raise KeyError(group_label)


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


def _build_dd_frame(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.normalize()
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce").astype("Int64")
    work["machine_name"] = work["machine_name"].astype(str)
    if "section" in work.columns:
        work["section"] = work["section"].astype(str)
    work["diff_coins_normalized"] = _ensure_numeric(work["diff_coins_normalized"])
    work["games_normalized"] = _ensure_numeric(work["games_normalized"])
    work["payoutrate_pct"] = [
        compute_payoutrate_pct(diff, games)
        for diff, games in zip(work["diff_coins_normalized"], work["games_normalized"], strict=False)
    ]
    work["dd"] = work["date"].dt.day.astype("Int64")
    work["dd_date_count"] = work["date"].dt.days_in_month.astype("Int64")
    work["is_event_7"] = work["dd"].isin([7, 17, 27]).astype(int)
    work["is_event_1"] = work["dd"].isin([1, 11, 21, 31]).astype(int)
    work["is_zorome_11_22"] = work["dd"].isin([11, 22]).astype(int)
    work["is_strong_zorome_mmdd"] = work["dd"].eq(work["date"].dt.month).astype(int)
    work["is_month_end_actual"] = work["dd"].eq(work["dd_date_count"]).astype(int)
    work["is_all_event"] = (
        work["is_event_7"].eq(1)
        | work["is_event_1"].eq(1)
        | work["is_zorome_11_22"].eq(1)
        | work["is_strong_zorome_mmdd"].eq(1)
        | work["is_month_end_actual"].eq(1)
    ).astype(int)
    work["dd_group"] = work["date"].map(_dd_group_label)
    return work


def _section_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    work = frame.copy()
    if "section" in work.columns:
        work = work[work["section"].astype(str).eq(TARGET_SECTION)].copy()
    if "machine_number" in work.columns:
        machine_number = pd.to_numeric(work["machine_number"], errors="coerce")
        work = work[machine_number.between(TARGET_MACHINE_NUMBERS[0], TARGET_MACHINE_NUMBERS[-1])].copy()
    return work


def _daily_dd_frame(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["payoutrate_pct"] = _ensure_numeric(work["payoutrate_pct"])
    work["hit_100"] = (work["payoutrate_pct"] > 100.0).astype(float)
    work["hit_104"] = (work["payoutrate_pct"] > 104.0).astype(float)
    daily = (
        work.groupby(["date", "dd"], as_index=False)
        .agg(
            mean_payoutrate_pct=("payoutrate_pct", "mean"),
            median_payoutrate_pct=("payoutrate_pct", "median"),
            mean_excess_pct=("payoutrate_pct", lambda s: float(pd.to_numeric(s, errors="coerce").mean() - 100.0)),
            n_machines=("machine_number", "size"),
        )
        .copy()
    )
    daily["hit_100"] = (daily["mean_payoutrate_pct"] > 100.0).astype(float)
    daily["hit_104"] = (daily["mean_payoutrate_pct"] > 104.0).astype(float)
    daily["entity_n_dates"] = int(work["date"].nunique())
    daily["dd"] = pd.to_numeric(daily["dd"], errors="coerce").astype("Int64")
    return daily


def _compare_metric_with_halves(daily: pd.DataFrame, *, label_col: str, rate_col: str = "hit_104") -> pd.DataFrame:
    work = daily.copy()
    work[rate_col] = pd.to_numeric(work[rate_col], errors="coerce")
    if label_col == "group_label":
        labels = [label for label in GROUP_ORDER if label in work[label_col].astype(str).unique().tolist()]
        label_values = labels
    else:
        labels = sorted(
            work[label_col].dropna().unique().tolist(),
            key=lambda x: pd.to_numeric(pd.Series([x]), errors="coerce").fillna(999999).iloc[0],
        )
        label_values = labels

    def _label_mask(frame: pd.DataFrame, label: object) -> pd.Series:
        if label_col == "group_label":
            return frame[label_col].astype(str).eq(str(label))
        left = pd.to_numeric(frame[label_col], errors="coerce")
        right = pd.to_numeric(pd.Series([label]), errors="coerce").iloc[0]
        return left.eq(right)

    rows: list[dict[str, object]] = []
    for label in label_values:
        label_mask = _label_mask(work, label)
        cell = work.loc[label_mask, rate_col].dropna().astype(float)
        rest = work.loc[~label_mask, rate_col].dropna().astype(float)
        p_value = _mwu(cell, rest)
        cell_rate = float(cell.mean()) if len(cell) else np.nan
        rest_rate = float(rest.mean()) if len(rest) else np.nan
        delta = cell_rate - rest_rate if np.isfinite(cell_rate) and np.isfinite(rest_rate) else np.nan
        rows.append(
            {
                label_col: label,
                "cell_rate": cell_rate,
                "rest_rate": rest_rate,
                "delta": delta,
                "cell_n": int(len(cell)),
                "rest_n": int(len(rest)),
                "p_value": p_value,
                "direction": "cell_higher" if np.isfinite(delta) and delta > 0 else "cell_lower" if np.isfinite(delta) and delta < 0 else "tie_or_nan",
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out = _attach_fdr(out, p_col="p_value", q_col="q_value")

    first_half, second_half, cutoff = _split_frame_by_date_half(work)
    half_frames: list[pd.DataFrame] = []
    for prefix, half in [("first_half", first_half), ("second_half", second_half)]:
        if half.empty:
            continue
        half_rows: list[dict[str, object]] = []
        for label in labels:
            label_mask = _label_mask(half, label)
            cell = half.loc[label_mask, rate_col].dropna().astype(float)
            rest = half.loc[~label_mask, rate_col].dropna().astype(float)
            p_value = _mwu(cell, rest)
            cell_rate = float(cell.mean()) if len(cell) else np.nan
            rest_rate = float(rest.mean()) if len(rest) else np.nan
            delta = cell_rate - rest_rate if np.isfinite(cell_rate) and np.isfinite(rest_rate) else np.nan
            half_rows.append(
                {
                    label_col: label,
                    f"{prefix}_cell_rate": cell_rate,
                    f"{prefix}_rest_rate": rest_rate,
                    f"{prefix}_delta": delta,
                    f"{prefix}_cell_n": int(len(cell)),
                    f"{prefix}_rest_n": int(len(rest)),
                    f"{prefix}_p_value": p_value,
                    f"{prefix}_direction": "cell_higher" if np.isfinite(delta) and delta > 0 else "cell_lower" if np.isfinite(delta) and delta < 0 else "tie_or_nan",
                }
            )
        half_frame = pd.DataFrame(half_rows)
        half_frame = _attach_fdr(half_frame, p_col=f"{prefix}_p_value", q_col=f"{prefix}_q_value")
        half_frames.append(half_frame)

    stability = out.copy()
    if half_frames:
        merged = half_frames[0]
        for extra in half_frames[1:]:
            merged = merged.merge(extra, on=label_col, how="outer", validate="one_to_one")
        stability = stability.merge(merged, on=label_col, how="left", validate="one_to_one")

    stability["full_sig"] = pd.to_numeric(stability["q_value"], errors="coerce").lt(0.05)
    stability["first_half_sig"] = pd.to_numeric(stability.get("first_half_q_value"), errors="coerce").lt(0.05)
    stability["second_half_sig"] = pd.to_numeric(stability.get("second_half_q_value"), errors="coerce").lt(0.05)
    stability["same_direction"] = (
        stability["direction"].astype(str).eq(stability.get("first_half_direction").astype(str))
        & stability["direction"].astype(str).eq(stability.get("second_half_direction").astype(str))
    )
    stability["stable"] = stability["full_sig"] & stability["first_half_sig"] & stability["second_half_sig"] & stability["same_direction"]
    stability["split_half_cutoff"] = cutoff
    if label_col != "group_label":
        stability[label_col] = pd.to_numeric(stability[label_col], errors="coerce").astype("Int64")
        sort_cols = ["q_value", "p_value", label_col]
    else:
        sort_cols = ["q_value", "p_value", label_col]
    return stability.sort_values(sort_cols, na_position="last").reset_index(drop=True)


def _dd_compare_with_halves(daily: pd.DataFrame, *, label_col: str, rate_col: str = "hit_104") -> pd.DataFrame:
    return _compare_metric_with_halves(daily, label_col=label_col, rate_col=rate_col)


def _dd_summary(frame: pd.DataFrame, *, min_entity_dates: int = 1) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily = _daily_dd_frame(frame)
    if daily.empty:
        empty = pd.DataFrame(
            columns=[
                "dd",
                "dd_label",
                "hit_rate_100",
                "hit_rate_104",
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
            mean_excess_pct=("mean_excess_pct", "mean"),
            median_payoutrate_pct=("mean_payoutrate_pct", "median"),
            cell_n_dates=("date", "nunique"),
            entity_n_dates=("entity_n_dates", "max"),
            n_machines=("n_machines", "sum"),
        )
        .copy()
    )
    summary["dd"] = pd.to_numeric(summary["dd"], errors="coerce").astype("Int64")
    summary["dd_label"] = summary["dd"].map(lambda value: f"{int(value)}日" if pd.notna(value) else "")
    summary = summary.sort_values(["hit_rate_104", "hit_rate_100", "mean_excess_pct", "dd"], ascending=[False, False, False, True], na_position="last").reset_index(drop=True)
    summary.insert(0, "rank", np.arange(1, len(summary) + 1))
    return summary, daily


def _group_daily_frame(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for group_label in GROUP_ORDER:
        mask = _event_group_mask(frame["date"], group_label)
        subset = frame[mask].copy()
        if subset.empty:
            continue
        daily = _daily_dd_frame(subset)
        daily["group_label"] = group_label
        rows.append(daily)
    if not rows:
        return pd.DataFrame(columns=["date", "dd", "group_label", "mean_payoutrate_pct", "median_payoutrate_pct", "mean_excess_pct", "hit_100", "hit_104", "n_machines", "entity_n_dates"])
    return pd.concat(rows, ignore_index=True)


def _dd_group_summary(frame: pd.DataFrame, *, min_entity_dates: int = 1) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    daily = _group_daily_frame(frame)
    if daily.empty:
        empty_summary = pd.DataFrame(
            columns=[
                "group_label",
                "hit_rate_100",
                "hit_rate_104",
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
            mean_excess_pct=("mean_excess_pct", "mean"),
            median_payoutrate_pct=("mean_payoutrate_pct", "median"),
            cell_n_dates=("date", "nunique"),
            entity_n_dates=("entity_n_dates", "max"),
            n_machines=("n_machines", "sum"),
        )
        .copy()
    )
    summary["group_label"] = pd.Categorical(summary["group_label"], categories=GROUP_ORDER, ordered=True)
    summary = summary.sort_values(["hit_rate_104", "hit_rate_100", "mean_excess_pct", "group_label"], ascending=[False, False, False, True], na_position="last").reset_index(drop=True)
    summary["group_label"] = summary["group_label"].astype(str)
    summary.insert(0, "rank", np.arange(1, len(summary) + 1))

    compare = _compare_metric_with_halves(daily[daily["group_label"].astype(str).ne("all_event")], label_col="group_label")
    base_daily = _daily_dd_frame(frame)
    all_event_daily = base_daily.copy()
    all_event_daily["group_label"] = np.where(_event_group_mask(all_event_daily["date"], "all_event"), "all_event", "non_event")
    all_event_compare = _compare_metric_with_halves(all_event_daily, label_col="group_label")
    all_event_row = all_event_compare[all_event_compare["group_label"].astype(str).eq("all_event")].copy()
    if not all_event_row.empty:
        compare = pd.concat([compare[compare["group_label"].astype(str).ne("all_event")], all_event_row], ignore_index=True)
        compare = _attach_fdr(compare, p_col="p_value", q_col="q_value")
        compare["full_sig"] = pd.to_numeric(compare["q_value"], errors="coerce").lt(0.05)
        compare["first_half_sig"] = pd.to_numeric(compare.get("first_half_q_value"), errors="coerce").lt(0.05)
        compare["second_half_sig"] = pd.to_numeric(compare.get("second_half_q_value"), errors="coerce").lt(0.05)
        compare["same_direction"] = (
            compare["direction"].astype(str).eq(compare.get("first_half_direction").astype(str))
            & compare["direction"].astype(str).eq(compare.get("second_half_direction").astype(str))
        )
        compare["stable"] = compare["full_sig"] & compare["first_half_sig"] & compare["second_half_sig"] & compare["same_direction"]
        compare["split_half_cutoff"] = all_event_row["split_half_cutoff"].iloc[0]
        compare = compare.sort_values(["q_value", "p_value", "group_label"], na_position="last").reset_index(drop=True)
    return summary, compare, daily


def _load_target_frame(*, db_path: Path = DEFAULT_DB_7, coords_path: Path = DEFAULT_COORDS_7_2F) -> pd.DataFrame:
    spec = SegmentSpec(
        hall_slug=TARGET_HALL_SLUG,
        hall_name=infer_hall_name(coords_path, floor=TARGET_FLOOR),
        floor=TARGET_FLOOR,
        db_path=db_path,
        coords_path=coords_path,
    )
    return _build_segment_frame(spec).copy()


def run_branch_a(frame: pd.DataFrame | None = None, *, output_root: Path = OUTPUT_ROOT) -> dict[str, object]:
    branch_dir = _ensure_dir(output_root / "branch_a")
    source = _load_target_frame() if frame is None else frame.copy()
    work = _build_dd_frame(source)
    work = _section_frame(work)
    if work.empty:
        raise ValueError("No rows matched kamata7 2F section 2179-2186")

    dd_summary, dd_daily = _dd_summary(work, min_entity_dates=1)
    dd_compare = _compare_metric_with_halves(dd_daily, label_col="dd")
    dd_group_summary, dd_group_compare, dd_group_daily = _dd_group_summary(work, min_entity_dates=1)

    _write_csv(dd_summary, branch_dir / "dd_summary.csv")
    _write_csv(dd_daily, branch_dir / "dd_daily.csv")
    _write_csv(dd_compare, branch_dir / "dd_compare.csv")
    _write_csv(dd_group_summary, branch_dir / "dd_group_summary.csv")
    _write_csv(dd_group_daily, branch_dir / "dd_group_daily.csv")
    _write_csv(dd_group_compare, branch_dir / "dd_group_compare.csv")

    stable_dd = dd_compare[dd_compare["stable"].eq(True)].copy()
    stable_group = dd_group_compare[dd_group_compare["stable"].eq(True)].copy()

    report = [
        "# Branch A",
        "",
        "Target: kamata7 2F section 2179-2186.",
        "",
        "Old group mapping:",
        "- `multiple_of_5`, `salary_window_23_27`, `month_start_1` -> removed",
        "- `event_7`, `event_1`, `zorome_11_22`, `strong_zorome_mmdd` -> new event-day buckets",
        "- `month_end_actual` -> retained",
        "- `all_event` -> union of the five event groups above",
        "- `all_event` compare uses non-event days as the rest baseline",
        "",
        "## DD summary",
        _md_table(dd_summary),
        "",
        "## DD split-half compare",
        _md_table(dd_compare),
        "",
        "## DD group summary",
        _md_table(dd_group_summary),
        "",
        "## DD group split-half compare",
        _md_table(dd_group_compare),
        "",
        f"Stable DD rows: {len(stable_dd)}.",
        f"Stable group rows: {len(stable_group)}.",
        "",
        "Conclusion: DD-only law is present if the top DD rows and at least one DD group remain stable under split-half FDR checks.",
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
    parser = argparse.ArgumentParser(description="Kamata DD axis deep dive")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_7)
    parser.add_argument("--coords-path", type=Path, default=DEFAULT_COORDS_7_2F)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    frame = _load_target_frame(db_path=args.db_path, coords_path=args.coords_path)
    run_branch_a(frame, output_root=args.output_root)


if __name__ == "__main__":
    main()
