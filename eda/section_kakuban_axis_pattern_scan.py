from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

import eda.core as core
from eda.core import load_hall_df
from eda.machine_axis_pattern_scan import (
    DD_BIN_ORDER,
    EFFECT_SIZE_THRESHOLD,
    MIN_CELL_N,
    _axis_breakdown,
    _compute_dd_bin,
    _scan_binary_outcome,
    _scan_diff_outcome,
)
from ml.analysis.kamata_corner_mirror_analysis import infer_hall_name
from ml.analysis.kamata_kakuban_section_residual_eda import (
    DEFAULT_COORDS_1,
    DEFAULT_COORDS_7_2F,
    DEFAULT_COORDS_7_3F,
    _read_coordinates_with_section_fallback,
)
from ml.corner_section.mitoya_corner_deep_common import load_corner_frame
from ml.corner_section.mitoya_corner_section_analysis import resolve_mitoya_db_path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_HALLS = ["蒲田7", "蒲田1", "みとや"]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "eda" / "results" / "section_kakuban_axis_pattern_scan"
DEFAULT_MIN_GROUP_DAYS_TOTAL = 200
DEFAULT_MIN_OBS_FOR_RANKING = 100
DEFAULT_TOP_N = 30
DEFAULT_MITOYA_DB_DIR = Path("db")
WEEKDAY_ORDER = ["月", "火", "水", "木", "金", "土", "日"]

PATTERN_SUMMARY_COLUMNS = [
    "hall",
    "granularity",
    "group_value",
    "n_machine_days",
    "axis",
    "outcome",
    "test",
    "statistic",
    "p_value",
    "effect_size",
    "n_obs",
    "n_levels",
    "n_sparse_levels",
    "note",
]

TOP_SIGNALS_COLUMNS = [
    "hall",
    "granularity",
    "group_value",
    "n_machine_days",
    "axis",
    "outcome",
    "test",
    "statistic",
    "p_value",
    "effect_size",
    "n_obs",
    "n_levels",
    "n_sparse_levels",
    "note",
]

BREAKDOWN_COLUMNS = [
    "hall",
    "granularity",
    "group_value",
    "axis",
    "outcome",
    "axis_level",
    "axis_level_order",
    "n",
    "avg_diff",
    "plus_rate",
    "hit104_rate",
]

SUMMARY_COLUMNS = [
    "hall",
    "granularity",
    "axis",
    "outcome",
    "n_patterns",
    "n_valid_patterns",
    "n_effect_ge_0_1",
    "pct_effect_ge_0_1",
]


def _parse_halls(value: str) -> list[str]:
    halls = [item.strip() for item in value.split(",") if item.strip()]
    if not halls:
        raise argparse.ArgumentTypeError("halls must not be empty")
    return halls


def _ensure_output_dir(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def _sorted_axis_values(values: pd.Series, axis: str) -> list[object]:
    observed = pd.Series(values.dropna().tolist())
    if axis == "dd":
        numeric = pd.to_numeric(observed, errors="coerce").dropna().astype(int)
        return sorted(numeric.unique().tolist())
    if axis == "day_of_week":
        order = {name: idx for idx, name in enumerate(WEEKDAY_ORDER)}

        def _sort_key(value: object) -> tuple[int, str]:
            text = str(value)
            return (order.get(text, 99), text)

        return sorted(observed.unique().tolist(), key=_sort_key)
    if axis == "is_x_day":
        numeric = pd.to_numeric(observed, errors="coerce").dropna().astype(int)
        return sorted(numeric.unique().tolist())
    if axis == "dd_bin":
        order = {name: idx for idx, name in enumerate(DD_BIN_ORDER)}

        def _bin_sort_key(value: object) -> tuple[int, str]:
            text = str(value)
            return (order.get(text, 99), text)

        return sorted(observed.unique().tolist(), key=_bin_sort_key)
    return sorted(observed.unique().tolist(), key=lambda value: str(value))


def _add_hit104(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["diff"] = pd.to_numeric(work["diff"], errors="coerce")
    work["games"] = pd.to_numeric(work["games"], errors="coerce")
    denom = work["games"] * 3
    work["payout_rate"] = ((denom + work["diff"]) / denom) * 100
    work["hit104"] = work["payout_rate"].ge(104.0).astype(int)
    return work


def _normalize_layout_frame(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["rank_from_min"] = pd.to_numeric(work["rank_from_min"], errors="coerce")
    work["section"] = work["section"].fillna("").astype(str)
    work = work.dropna(subset=["machine_number", "rank_from_min"]).copy()
    work = work.loc[work["section"].str.strip().ne("")].copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work["rank_from_min"] = work["rank_from_min"].astype(int)
    work = work.drop_duplicates(subset=["machine_number"], keep="first").copy()
    return work.loc[:, ["machine_number", "rank_from_min", "section"]]


def _load_kamata_layout(
    *,
    coords_paths: list[tuple[Path, str]],
) -> pd.DataFrame:
    frames = [
        _read_coordinates_with_section_fallback(
            coords_path,
            hall_name=infer_hall_name(coords_path, floor=floor),
            floor=floor,
        )
        for coords_path, floor in coords_paths
    ]
    return _normalize_layout_frame(pd.concat(frames, ignore_index=True))


def _load_mitoya_layout(*, db_path: Path | None, db_dir: Path) -> pd.DataFrame:
    if db_path is not None:
        resolved_db = db_path
    else:
        resolved_db = core.DB_DIR / core.HALL_DBS["みとや"]
        if not resolved_db.exists():
            resolved_db = resolve_mitoya_db_path("", db_dir=db_dir, index_hint=-1)
    try:
        frame = load_corner_frame(resolved_db)
        layout = frame.loc[:, ["machine_number", "rank_from_min", "section"]].copy()
    except Exception:
        with sqlite3.connect(resolved_db) as conn:
            layout = pd.read_sql_query(
                """
                SELECT machine_number, rank_from_min, section
                FROM machine_layout
                """,
                conn,
            )
    return _normalize_layout_frame(layout)


def _load_hall_layout_frame(
    hall: str,
    *,
    coords1: Path,
    coords7_2f: Path,
    coords7_3f: Path,
    mitoya_db_path: Path | None,
    mitoya_db_dir: Path,
) -> pd.DataFrame:
    if hall == "蒲田7":
        return _load_kamata_layout(coords_paths=[(coords7_2f, "2F"), (coords7_3f, "3F")])
    if hall == "蒲田1":
        return _load_kamata_layout(coords_paths=[(coords1, "2F")])
    if hall == "みとや":
        return _load_mitoya_layout(db_path=mitoya_db_path, db_dir=mitoya_db_dir)
    raise ValueError(f"unknown hall: {hall}")


def _prepare_group_frame(raw: pd.DataFrame, layout_frame: pd.DataFrame) -> pd.DataFrame:
    frame = _add_hit104(raw)
    frame["section"] = pd.NA
    frame["kakuban"] = pd.NA
    merged = frame.merge(layout_frame, on="machine_number", how="inner", validate="many_to_one")
    if merged.empty:
        return merged

    merged["section"] = merged["section_y"].fillna("").astype(str)
    merged["kakuban"] = pd.to_numeric(merged["rank_from_min"], errors="coerce")
    merged["kakuban"] = merged["kakuban"].astype("Int64")
    merged["dd_bin"] = _compute_dd_bin(merged["dd"])
    merged = merged.drop(columns=["section_x", "section_y", "rank_from_min"])
    merged["group_section"] = merged["section"].fillna("").astype(str)
    merged["group_kakuban"] = merged["kakuban"]
    return merged


def _format_group_value(value: object) -> object:
    if pd.isna(value):
        return np.nan
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)) and float(value).is_integer():
        return int(value)
    return value


def _group_axis_outcome_rows(
    hall: str,
    granularity: str,
    group_col: str,
    group_value: object,
    group_frame: pd.DataFrame,
    *,
    min_cell_n: int,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    n_machine_days = int(len(group_frame))
    formatted_group_value = _format_group_value(group_value)

    for axis in ["dd", "day_of_week", "is_x_day", "dd_bin"]:
        diff_stats = _scan_diff_outcome(group_frame, axis=axis, min_cell_n=min_cell_n)
        rows.append(
            {
                "hall": hall,
                "granularity": granularity,
                "group_value": formatted_group_value,
                "n_machine_days": n_machine_days,
                "axis": axis,
                "outcome": "diff",
                **diff_stats,
            }
        )

        for outcome_col in ["plus", "hit104"]:
            binary_stats = _scan_binary_outcome(group_frame, axis=axis, outcome_col=outcome_col)
            rows.append(
                {
                    "hall": hall,
                    "granularity": granularity,
                    "group_value": formatted_group_value,
                    "n_machine_days": n_machine_days,
                    "axis": axis,
                    "outcome": outcome_col,
                    **binary_stats,
                }
            )

    return rows


def _axis_breakdown_group(
    hall: str,
    granularity: str,
    group_value: object,
    group_frame: pd.DataFrame,
    *,
    axis: str,
    outcome: str,
) -> pd.DataFrame:
    breakdown = _axis_breakdown(
        hall,
        str(group_value),
        group_frame,
        axis=axis,
        outcome=outcome,
    ).copy()
    if breakdown.empty:
        return pd.DataFrame(columns=BREAKDOWN_COLUMNS)
    breakdown = breakdown.rename(columns={"machine_name": "group_value"})
    breakdown.insert(1, "granularity", granularity)
    breakdown["group_value"] = _format_group_value(group_value)
    return breakdown.loc[:, BREAKDOWN_COLUMNS]


def _summarize_pattern_summary(pattern_summary: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if pattern_summary.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)

    for (hall, granularity, axis, outcome), group in pattern_summary.groupby(
        ["hall", "granularity", "axis", "outcome"],
        sort=True,
    ):
        tested = group.loc[group["effect_size"].notna()].copy()
        n_patterns = int(len(group))
        n_valid_patterns = int(len(tested))
        n_effect_ge_0_1 = int((tested["effect_size"] >= EFFECT_SIZE_THRESHOLD).sum())
        pct_effect_ge_0_1 = float((n_effect_ge_0_1 / n_valid_patterns) * 100.0) if n_valid_patterns else float("nan")
        rows.append(
            {
                "hall": hall,
                "granularity": granularity,
                "axis": axis,
                "outcome": outcome,
                "n_patterns": n_patterns,
                "n_valid_patterns": n_valid_patterns,
                "n_effect_ge_0_1": n_effect_ge_0_1,
                "pct_effect_ge_0_1": pct_effect_ge_0_1,
            }
        )
    return pd.DataFrame(rows, columns=SUMMARY_COLUMNS)


def build_group_outputs(
    hall: str,
    raw: pd.DataFrame,
    *,
    group_col: str,
    layout_frame: pd.DataFrame,
    granularity: str | None = None,
    min_group_days_total: int = DEFAULT_MIN_GROUP_DAYS_TOTAL,
    min_obs_for_ranking: int = DEFAULT_MIN_OBS_FOR_RANKING,
    top_n: int = DEFAULT_TOP_N,
    min_cell_n: int = MIN_CELL_N,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    granularity = granularity or group_col
    frame = _prepare_group_frame(raw, layout_frame)
    if frame.empty:
        empty_pattern = pd.DataFrame(columns=PATTERN_SUMMARY_COLUMNS)
        empty_top = pd.DataFrame(columns=TOP_SIGNALS_COLUMNS)
        empty_breakdown = pd.DataFrame(columns=BREAKDOWN_COLUMNS)
        empty_summary = pd.DataFrame(columns=SUMMARY_COLUMNS)
        return empty_pattern, empty_top, empty_breakdown, empty_summary

    work = frame.copy()
    if group_col == "section":
        work[group_col] = work[group_col].fillna("").astype(str).str.strip()
        work = work.loc[work[group_col].ne("")].copy()
    elif group_col == "kakuban":
        work[group_col] = pd.to_numeric(work[group_col], errors="coerce").astype("Int64")
        work = work.loc[work[group_col].notna()].copy()
    else:
        raise ValueError(f"unsupported group_col: {group_col}")

    group_counts = work.groupby(group_col, dropna=True).size()
    valid_groups = group_counts.loc[group_counts >= min_group_days_total].index.tolist()
    working = work.loc[work[group_col].isin(valid_groups)].copy()
    if working.empty:
        empty_pattern = pd.DataFrame(columns=PATTERN_SUMMARY_COLUMNS)
        empty_top = pd.DataFrame(columns=TOP_SIGNALS_COLUMNS)
        empty_breakdown = pd.DataFrame(columns=BREAKDOWN_COLUMNS)
        empty_summary = pd.DataFrame(columns=SUMMARY_COLUMNS)
        return empty_pattern, empty_top, empty_breakdown, empty_summary

    rows: list[dict[str, object]] = []
    for group_value, group_frame in working.groupby(group_col, sort=True, dropna=True):
        if group_frame.empty:
            continue
        rows.extend(
            _group_axis_outcome_rows(
                hall,
                granularity,
                group_col,
                group_value,
                group_frame,
                min_cell_n=min_cell_n,
            )
        )

    pattern_summary = pd.DataFrame(rows, columns=PATTERN_SUMMARY_COLUMNS)
    if pattern_summary.empty:
        empty_top = pd.DataFrame(columns=TOP_SIGNALS_COLUMNS)
        empty_breakdown = pd.DataFrame(columns=BREAKDOWN_COLUMNS)
        summary = _summarize_pattern_summary(pattern_summary)
        return pattern_summary, empty_top, empty_breakdown, summary

    pattern_summary = pattern_summary.sort_values(
        ["group_value", "axis", "outcome"],
        ascending=[True, True, True],
        kind="mergesort",
    ).reset_index(drop=True)

    top_signals = (
        pattern_summary.loc[pattern_summary["effect_size"].notna() & (pattern_summary["n_obs"] >= min_obs_for_ranking)]
        .sort_values(
            ["effect_size", "n_obs", "group_value", "axis", "outcome"],
            ascending=[False, False, True, True, True],
            kind="mergesort",
        )
        .head(top_n)
        .reset_index(drop=True)
    )

    breakdown_frames: list[pd.DataFrame] = []
    if not top_signals.empty:
        unique_pairs = (
            top_signals.sort_values(
                ["effect_size", "n_obs", "group_value", "axis", "outcome"],
                ascending=[False, False, True, True, True],
                kind="mergesort",
            )
            .drop_duplicates(subset=["group_value", "axis"], keep="first")
            .reset_index(drop=True)
        )
        for _, row in unique_pairs.iterrows():
            group_frame = working.loc[working[group_col].eq(row["group_value"])].copy()
            breakdown_frames.append(
                _axis_breakdown_group(
                    hall,
                    granularity,
                    row["group_value"],
                    group_frame,
                    axis=str(row["axis"]),
                    outcome=str(row["outcome"]),
                )
            )

    top_signal_breakdown = (
        pd.concat(breakdown_frames, ignore_index=True) if breakdown_frames else pd.DataFrame(columns=BREAKDOWN_COLUMNS)
    )

    summary = _summarize_pattern_summary(pattern_summary)
    return pattern_summary, top_signals, top_signal_breakdown, summary


def _write_group_outputs(
    hall: str,
    granularity: str,
    pattern_summary: pd.DataFrame,
    top_signals: pd.DataFrame,
    top_signal_breakdown: pd.DataFrame,
    summary: pd.DataFrame,
    *,
    output_dir: Path,
) -> None:
    _write_csv(pattern_summary, output_dir / f"{hall}_{granularity}_pattern_summary.csv")
    _write_csv(top_signals, output_dir / f"{hall}_{granularity}_top_signals.csv")
    _write_csv(top_signal_breakdown, output_dir / f"{hall}_{granularity}_top_signal_breakdown.csv")
    _write_csv(summary, output_dir / f"{hall}_{granularity}_summary_report.csv")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="section/kakuban axis pattern scan")
    parser.add_argument("--halls", type=_parse_halls, default=DEFAULT_HALLS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--min-group-days-total", type=int, default=DEFAULT_MIN_GROUP_DAYS_TOTAL)
    parser.add_argument("--min-obs-for-ranking", type=int, default=DEFAULT_MIN_OBS_FOR_RANKING)
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    parser.add_argument("--coords1", type=Path, default=DEFAULT_COORDS_1)
    parser.add_argument("--coords7-2f", dest="coords7_2f", type=Path, default=DEFAULT_COORDS_7_2F)
    parser.add_argument("--coords7-3f", dest="coords7_3f", type=Path, default=DEFAULT_COORDS_7_3F)
    parser.add_argument("--mitoya-db-path", type=Path, default=None)
    parser.add_argument("--mitoya-db-dir", type=Path, default=DEFAULT_MITOYA_DB_DIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = _ensure_output_dir(args.output_dir)

    for hall in args.halls:
        raw = load_hall_df(hall)
        layout_frame = _load_hall_layout_frame(
            hall,
            coords1=args.coords1,
            coords7_2f=args.coords7_2f,
            coords7_3f=args.coords7_3f,
            mitoya_db_path=args.mitoya_db_path,
            mitoya_db_dir=args.mitoya_db_dir,
        )
        for group_col, granularity in [("section", "section"), ("kakuban", "kakuban")]:
            pattern_summary, top_signals, top_signal_breakdown, summary = build_group_outputs(
                hall,
                raw,
                group_col=group_col,
                granularity=granularity,
                layout_frame=layout_frame,
                min_group_days_total=args.min_group_days_total,
                min_obs_for_ranking=args.min_obs_for_ranking,
                top_n=args.top_n,
                min_cell_n=MIN_CELL_N,
            )
            _write_group_outputs(
                hall,
                granularity,
                pattern_summary,
                top_signals,
                top_signal_breakdown,
                summary,
                output_dir=output_dir,
            )

    print(f"written: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
