from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from eda.core import HALL_DBS, load_hall_df
from eda.machine_axis_pattern_scan import (
    EFFECT_SIZE_THRESHOLD,
    _axis_breakdown,
    _scan_binary_outcome,
)
from eda.machine_dd_persistence_check import (
    DD_LEVELS,
    DEFAULT_MIN_CELL_N_FOR_SPLIT as DEFAULT_MIN_CELL_N_FOR_DD_FROM_PERSISTENCE,
    DEFAULT_MIN_COMMON_LEVELS as DEFAULT_MIN_COMMON_DD_LEVELS_FROM_PERSISTENCE,
    _format_range,
)
from eda.machine_name_significance_scan import (
    DEFAULT_SHINDAI_EXCLUDE_DAYS as DEFAULT_SHINDAI_EXCLUDE_DAYS_FROM_NAME_SCAN,
    _prepare_frame,
)
from eda.machine_volatility_event_gap_scan import (
    DEFAULT_CURRENTLY_INSTALLED_GRACE_DAYS as DEFAULT_CURRENTLY_INSTALLED_GRACE_DAYS_FROM_VOL_SCAN,
    _apply_currently_installed_filter,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_HALLS = ["蒲田1", "蒲田7", "みとや", "レイトギャップ", "ARROW", "ヒロキ", "ザシティ", "楽園", "金時"]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "eda" / "results" / "machine_dd_recent_window"
DEFAULT_SHINDAI_EXCLUDE_DAYS = DEFAULT_SHINDAI_EXCLUDE_DAYS_FROM_NAME_SCAN
DEFAULT_CURRENTLY_INSTALLED_GRACE_DAYS = DEFAULT_CURRENTLY_INSTALLED_GRACE_DAYS_FROM_VOL_SCAN
DEFAULT_WINDOW_DAYS = 90
# DD は 31 水準あるため、90日窓でも 1 水準あたりの件数が薄くなりやすい。
DEFAULT_MIN_MACHINE_DAYS_PER_WINDOW = 200
DEFAULT_MIN_CELL_N_FOR_DD = DEFAULT_MIN_CELL_N_FOR_DD_FROM_PERSISTENCE
DEFAULT_MIN_COMMON_DD_LEVELS = DEFAULT_MIN_COMMON_DD_LEVELS_FROM_PERSISTENCE
DEFAULT_MIN_WINDOW_EFFECT_FOR_CONSISTENCY = 0.05
TARGET_OUTCOMES = ("plus", "hit104")
RESULT_COLUMNS = [
    "hall",
    "machine_name",
    "outcome",
    "window0_range",
    "window0_n",
    "window0_p",
    "window0_effect",
    "window0_top_dd",
    "window1_range",
    "window1_n",
    "window1_p",
    "window1_effect",
    "window1_top_dd",
    "n_common_dd_levels",
    "spearman_rho",
    "spearman_p",
    "recent_significant",
    "consistent_with_prior_window",
    "note",
]


def _parse_halls(value: str) -> list[str]:
    halls = [item.strip() for item in value.split(",") if item.strip()]
    if not halls:
        raise argparse.ArgumentTypeError("halls must not be empty")
    return halls


def _ensure_output_dir(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _date_series(frame: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(frame["date"].astype(str), format="%Y%m%d", errors="coerce")


def _window_bounds(max_date: pd.Timestamp, *, window_days: int, window_index: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    if window_index == 0:
        start = max_date - pd.Timedelta(days=window_days - 1)
        end = max_date
    elif window_index == 1:
        start = max_date - pd.Timedelta(days=(2 * window_days) - 1)
        end = max_date - pd.Timedelta(days=window_days)
    else:
        raise ValueError(f"unsupported window index: {window_index}")
    return start, end


def _slice_window(frame: pd.DataFrame, *, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    return frame.loc[frame["date_ts"].between(start, end, inclusive="both")].copy()


def _dd_vector(breakdown: pd.DataFrame, *, rate_col: str, min_cell_n: int) -> pd.Series:
    if breakdown.empty:
        return pd.Series(index=DD_LEVELS, dtype=float)

    valid = breakdown.loc[breakdown["n"] >= min_cell_n, ["axis_level", rate_col]].copy()
    if valid.empty:
        return pd.Series(index=DD_LEVELS, dtype=float)

    series = valid.set_index("axis_level")[rate_col].astype(float)
    series.index = pd.to_numeric(series.index, errors="coerce").astype("Int64")
    series = series.reindex(DD_LEVELS)
    series.index.name = "dd"
    return series


def _top_dd(rate_vector: pd.Series) -> object:
    valid = rate_vector.dropna()
    if valid.empty:
        return np.nan
    return int(valid.idxmax())


def _window_result(
    hall: str,
    machine_name: str,
    outcome: str,
    machine_frame: pd.DataFrame,
    *,
    window_days: int,
    min_machine_days_per_window: int,
    min_cell_n_for_dd: int,
    min_common_dd_levels: int,
) -> dict[str, object]:
    if outcome not in TARGET_OUTCOMES:
        raise ValueError(f"unsupported outcome: {outcome}")

    rate_col = "plus_rate" if outcome == "plus" else "hit104_rate"
    max_date = machine_frame["date_ts"].max()
    if pd.isna(max_date):
        return {
            "hall": hall,
            "machine_name": machine_name,
            "outcome": outcome,
            "window0_range": "empty",
            "window0_n": np.nan,
            "window0_p": np.nan,
            "window0_effect": np.nan,
            "window0_top_dd": np.nan,
            "window1_range": "empty",
            "window1_n": np.nan,
            "window1_p": np.nan,
            "window1_effect": np.nan,
            "window1_top_dd": np.nan,
            "n_common_dd_levels": np.nan,
            "spearman_rho": np.nan,
            "spearman_p": np.nan,
            "recent_significant": False,
            "consistent_with_prior_window": False,
            "note": "skip: empty machine frame after filtering",
        }

    window_bounds = [_window_bounds(max_date, window_days=window_days, window_index=idx) for idx in (0, 1)]
    window_frames = [_slice_window(machine_frame, start=start, end=end) for start, end in window_bounds]
    window_ranges = [_format_range(window_frame) for window_frame in window_frames]
    window_ns = [int(len(window_frame)) for window_frame in window_frames]

    skip_reasons = [
        f"window{idx}_n={window_n} < {min_machine_days_per_window}"
        for idx, window_n in enumerate(window_ns)
        if window_n < min_machine_days_per_window
    ]
    if skip_reasons:
        return {
            "hall": hall,
            "machine_name": machine_name,
            "outcome": outcome,
            "window0_range": window_ranges[0],
            "window0_n": np.nan,
            "window0_p": np.nan,
            "window0_effect": np.nan,
            "window0_top_dd": np.nan,
            "window1_range": window_ranges[1],
            "window1_n": np.nan,
            "window1_p": np.nan,
            "window1_effect": np.nan,
            "window1_top_dd": np.nan,
            "n_common_dd_levels": np.nan,
            "spearman_rho": np.nan,
            "spearman_p": np.nan,
            "recent_significant": False,
            "consistent_with_prior_window": False,
            "note": "skip: " + "; ".join(skip_reasons),
        }

    window0_stats = _scan_binary_outcome(window_frames[0], axis="dd", outcome_col=outcome)
    window1_stats = _scan_binary_outcome(window_frames[1], axis="dd", outcome_col=outcome)

    window0_breakdown = _axis_breakdown(hall, machine_name, window_frames[0], axis="dd", outcome=outcome)
    window1_breakdown = _axis_breakdown(hall, machine_name, window_frames[1], axis="dd", outcome=outcome)
    window0_vector = _dd_vector(window0_breakdown, rate_col=rate_col, min_cell_n=min_cell_n_for_dd)
    window1_vector = _dd_vector(window1_breakdown, rate_col=rate_col, min_cell_n=min_cell_n_for_dd)

    window0_top_dd = _top_dd(window0_vector)
    window1_top_dd = _top_dd(window1_vector)

    common_mask = window0_vector.notna() & window1_vector.notna()
    n_common_dd_levels = int(common_mask.sum())

    spearman_rho = np.nan
    spearman_p = np.nan
    note_parts: list[str] = []
    if n_common_dd_levels < min_common_dd_levels:
        note_parts.append(f"skip: n_common_dd_levels={n_common_dd_levels} < {min_common_dd_levels}")
    else:
        spearman_rho, spearman_p = spearmanr(
            window0_vector.loc[common_mask].to_numpy(),
            window1_vector.loc[common_mask].to_numpy(),
        )
        if not np.isfinite(spearman_rho) or not np.isfinite(spearman_p):
            note_parts.append("skip: spearman undefined")

    recent_significant = bool(
        pd.notna(window0_stats["p_value"])
        and pd.notna(window0_stats["effect_size"])
        and (float(window0_stats["p_value"]) < 0.05)
        and (float(window0_stats["effect_size"]) >= EFFECT_SIZE_THRESHOLD)
    )

    consistent_with_prior_window = bool(
        n_common_dd_levels >= min_common_dd_levels
        and np.isfinite(spearman_rho)
        and np.isfinite(spearman_p)
        and float(spearman_rho) >= 0.5
        and pd.notna(window1_stats["effect_size"])
        and float(window1_stats["effect_size"]) >= DEFAULT_MIN_WINDOW_EFFECT_FOR_CONSISTENCY
    )
    if (
        recent_significant
        and n_common_dd_levels >= min_common_dd_levels
        and np.isfinite(spearman_rho)
        and np.isfinite(spearman_p)
        and float(spearman_rho) >= 0.5
        and pd.notna(window1_stats["effect_size"])
        and float(window1_stats["effect_size"]) < DEFAULT_MIN_WINDOW_EFFECT_FOR_CONSISTENCY
    ):
        note_parts.append(f"consistent候補だがwindow1_effect<{DEFAULT_MIN_WINDOW_EFFECT_FOR_CONSISTENCY}のため不採用")

    return {
        "hall": hall,
        "machine_name": machine_name,
        "outcome": outcome,
        "window0_range": window_ranges[0],
        "window0_n": window_ns[0],
        "window0_p": float(window0_stats["p_value"]) if pd.notna(window0_stats["p_value"]) else np.nan,
        "window0_effect": float(window0_stats["effect_size"]) if pd.notna(window0_stats["effect_size"]) else np.nan,
        "window0_top_dd": window0_top_dd,
        "window1_range": window_ranges[1],
        "window1_n": window_ns[1],
        "window1_p": float(window1_stats["p_value"]) if pd.notna(window1_stats["p_value"]) else np.nan,
        "window1_effect": float(window1_stats["effect_size"]) if pd.notna(window1_stats["effect_size"]) else np.nan,
        "window1_top_dd": window1_top_dd,
        "n_common_dd_levels": n_common_dd_levels,
        "spearman_rho": float(spearman_rho) if np.isfinite(spearman_rho) else np.nan,
        "spearman_p": float(spearman_p) if np.isfinite(spearman_p) else np.nan,
        "recent_significant": recent_significant,
        "consistent_with_prior_window": consistent_with_prior_window,
        "note": "; ".join(note_parts),
    }


def build_hall_outputs(
    hall: str,
    raw: pd.DataFrame,
    *,
    shindai_exclude_days: int = DEFAULT_SHINDAI_EXCLUDE_DAYS,
    currently_installed_grace_days: int = DEFAULT_CURRENTLY_INSTALLED_GRACE_DAYS,
    window_days: int = DEFAULT_WINDOW_DAYS,
    min_machine_days_per_window: int = DEFAULT_MIN_MACHINE_DAYS_PER_WINDOW,
    min_cell_n_for_dd: int = DEFAULT_MIN_CELL_N_FOR_DD,
    min_common_dd_levels: int = DEFAULT_MIN_COMMON_DD_LEVELS,
) -> pd.DataFrame:
    frame = _prepare_frame(raw, shindai_exclude_days=shindai_exclude_days).copy()
    if "hall" not in frame.columns:
        frame["hall"] = hall
    frame = _apply_currently_installed_filter(frame, grace_days=currently_installed_grace_days).copy()
    if frame.empty:
        return pd.DataFrame(columns=RESULT_COLUMNS)

    frame["date_ts"] = _date_series(frame)
    frame = frame.loc[frame["date_ts"].notna()].copy()
    if frame.empty:
        return pd.DataFrame(columns=RESULT_COLUMNS)

    rows: list[dict[str, object]] = []
    for machine_name, machine_frame in frame.groupby("machine_name", sort=True):
        machine_frame = machine_frame.copy()
        for outcome in TARGET_OUTCOMES:
            rows.append(
                _window_result(
                    hall,
                    str(machine_name),
                    outcome,
                    machine_frame,
                    window_days=window_days,
                    min_machine_days_per_window=min_machine_days_per_window,
                    min_cell_n_for_dd=min_cell_n_for_dd,
                    min_common_dd_levels=min_common_dd_levels,
                )
            )

    result = pd.DataFrame(rows, columns=RESULT_COLUMNS)
    if not result.empty:
        for col in ["window0_n", "window1_n", "n_common_dd_levels"]:
            if col in result.columns:
                result[col] = result[col].astype("Int64")
        result = result.sort_values(
            ["hall", "machine_name", "outcome"],
            ascending=[True, True, True],
            kind="mergesort",
        ).reset_index(drop=True)
    return result


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def _print_hall_report(hall: str, frame: pd.DataFrame) -> None:
    print(f"\n=== {hall} ===")
    if frame.empty:
        print("recent_significant rows: none")
        return

    significant = frame.loc[frame["recent_significant"].astype(bool)].copy()
    if significant.empty:
        print("recent_significant rows: none")
        return

    print(
        significant.loc[
            :,
            [
                "machine_name",
                "outcome",
                "window0_range",
                "window0_n",
                "window0_p",
                "window0_effect",
                "window0_top_dd",
                "window1_range",
                "window1_n",
                "window1_p",
                "window1_effect",
                "window1_top_dd",
                "n_common_dd_levels",
                "spearman_rho",
                "spearman_p",
                "consistent_with_prior_window",
                "note",
            ],
        ].to_string(index=False)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan DD signal persistence across two recent 90-day windows.")
    parser.add_argument("--halls", type=_parse_halls, default=DEFAULT_HALLS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument("--min-machine-days-per-window", type=int, default=DEFAULT_MIN_MACHINE_DAYS_PER_WINDOW)
    parser.add_argument("--min-cell-n-for-dd", type=int, default=DEFAULT_MIN_CELL_N_FOR_DD)
    parser.add_argument("--min-common-dd-levels", type=int, default=DEFAULT_MIN_COMMON_DD_LEVELS)
    parser.add_argument("--currently-installed-grace-days", type=int, default=DEFAULT_CURRENTLY_INSTALLED_GRACE_DAYS)
    args = parser.parse_args(argv)

    if args.window_days <= 0:
        raise ValueError("--window-days must be positive")
    if args.min_machine_days_per_window <= 0:
        raise ValueError("--min-machine-days-per-window must be positive")
    if args.min_cell_n_for_dd <= 0:
        raise ValueError("--min-cell-n-for-dd must be positive")
    if args.min_common_dd_levels <= 0:
        raise ValueError("--min-common-dd-levels must be positive")

    output_dir = _ensure_output_dir(args.output_dir)
    all_rows: list[pd.DataFrame] = []

    for hall in args.halls:
        if hall not in HALL_DBS:
            raise ValueError(f"unknown hall: {hall}")
        raw = load_hall_df(hall)
        hall_rows = build_hall_outputs(
            hall,
            raw,
            currently_installed_grace_days=args.currently_installed_grace_days,
            window_days=args.window_days,
            min_machine_days_per_window=args.min_machine_days_per_window,
            min_cell_n_for_dd=args.min_cell_n_for_dd,
            min_common_dd_levels=args.min_common_dd_levels,
        )

        _write_csv(hall_rows, output_dir / f"{hall}_recent_window.csv")
        _print_hall_report(hall, hall_rows)
        all_rows.append(hall_rows)

    all_frame = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame(columns=RESULT_COLUMNS)
    _write_csv(all_frame, output_dir / "all_halls_recent_window.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
