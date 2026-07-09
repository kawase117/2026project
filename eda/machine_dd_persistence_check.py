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

DEFAULT_HALLS = ["蒲田1", "蒲田7", "みとや"]
DEFAULT_MIN_MACHINE_DAYS_FOR_SPLIT = 400
DEFAULT_MIN_CELL_N_FOR_SPLIT = 3
DEFAULT_MIN_COMMON_LEVELS = 10
DEFAULT_SIGNAL_DIR = PROJECT_ROOT / "eda" / "results" / "machine_axis_pattern_scan"
DEFAULT_OUTPUT_PATH = DEFAULT_SIGNAL_DIR / "persistence_check.csv"
DEFAULT_SHINDAI_EXCLUDE_DAYS = DEFAULT_SHINDAI_EXCLUDE_DAYS_FROM_NAME_SCAN
DEFAULT_CURRENTLY_INSTALLED_GRACE_DAYS = DEFAULT_CURRENTLY_INSTALLED_GRACE_DAYS_FROM_VOL_SCAN
TARGET_OUTCOMES = ("plus", "hit104")
DD_LEVELS = list(range(1, 32))
PERSISTENCE_COLUMNS = [
    "hall",
    "machine_name",
    "outcome",
    "split_date",
    "period_a_range",
    "period_b_range",
    "period_a_n",
    "period_b_n",
    "n_common_dd_levels",
    "spearman_rho",
    "spearman_p",
    "note",
]


def _parse_halls(value: str) -> list[str]:
    halls = [item.strip() for item in value.split(",") if item.strip()]
    if not halls:
        raise argparse.ArgumentTypeError("halls must not be empty")
    return halls


def _ensure_output_dir(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _date_series(frame: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(frame["date"].astype(str), format="%Y%m%d", errors="coerce")


def _format_range(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "empty"
    dates = _date_series(frame).dropna()
    if dates.empty:
        return "empty"
    return f"{dates.min().date().isoformat()}..{dates.max().date().isoformat()}"


def _split_timestamp(frame: pd.DataFrame) -> pd.Timestamp:
    dates = _date_series(frame).dropna()
    if dates.empty:
        return pd.NaT
    start = dates.min()
    end = dates.max()
    return start + (end - start) / 2


def _prepare_analysis_frame(
    raw: pd.DataFrame, *, shindai_exclude_days: int, currently_installed_grace_days: int
) -> pd.DataFrame:
    frame = _prepare_frame(raw, shindai_exclude_days=shindai_exclude_days).copy()
    if "hall" not in frame.columns:
        frame["hall"] = ""
    frame = _apply_currently_installed_filter(frame, grace_days=currently_installed_grace_days).copy()
    if "dd" not in frame.columns:
        frame["dd"] = _date_series(frame).dt.day
    else:
        frame["dd"] = pd.to_numeric(frame["dd"], errors="coerce")
    frame["date_ts"] = _date_series(frame)
    return frame


def _load_candidate_signals(hall: str) -> pd.DataFrame:
    path = DEFAULT_SIGNAL_DIR / f"{hall}_top_signals.csv"
    if not path.exists():
        raise FileNotFoundError(f"missing candidate file: {path}")

    signals = pd.read_csv(path, encoding="utf-8-sig")
    required = {"hall", "machine_name", "axis", "outcome"}
    missing = required.difference(signals.columns)
    if missing:
        raise ValueError(f"{path} missing columns: {sorted(missing)}")

    filtered = signals.loc[
        signals["axis"].astype(str).eq("dd") & signals["outcome"].astype(str).isin(TARGET_OUTCOMES)
    ].copy()
    if filtered.empty:
        return pd.DataFrame(columns=signals.columns)

    sort_cols = [col for col in ["effect_size", "n_obs", "machine_name", "outcome"] if col in filtered.columns]
    if sort_cols:
        ascending = [False, False, True, True][: len(sort_cols)]
        filtered = filtered.sort_values(sort_cols, ascending=ascending, kind="mergesort")
    filtered = filtered.drop_duplicates(subset=["hall", "machine_name", "outcome"], keep="first")
    return filtered.reset_index(drop=True)


def _dd_vector(machine_frame: pd.DataFrame, *, outcome: str, min_cell_n: int) -> tuple[pd.Series, int, int]:
    metric_col = "plus" if outcome == "plus" else "hit104"
    grouped = machine_frame.groupby("dd", dropna=False)[metric_col].agg(["mean", "size"])
    grouped = grouped.reindex(DD_LEVELS)
    sizes = grouped["size"].fillna(0)
    values = grouped["mean"].where(sizes >= min_cell_n)
    n_valid = int(values.notna().sum())
    n_dropped = int((sizes > 0).sum() - n_valid)
    return values.astype(float), n_valid, n_dropped


def _spearman_row(
    hall: str,
    machine_name: str,
    outcome: str,
    frame: pd.DataFrame,
    *,
    split_ts: pd.Timestamp,
    min_machine_days_for_split: int,
    min_cell_n_for_split: int,
    min_common_levels: int,
) -> dict[str, object]:
    machine_frame = frame.loc[frame["machine_name"].astype(str).eq(str(machine_name))].copy()
    machine_days = int(len(machine_frame))
    period_a = machine_frame.loc[machine_frame["date_ts"] < split_ts].copy()
    period_b = machine_frame.loc[machine_frame["date_ts"] >= split_ts].copy()

    period_a_range = _format_range(period_a)
    period_b_range = _format_range(period_b)
    period_a_n = int(len(period_a))
    period_b_n = int(len(period_b))

    if machine_days < min_machine_days_for_split:
        return {
            "hall": hall,
            "machine_name": machine_name,
            "outcome": outcome,
            "split_date": split_ts.date().isoformat() if pd.notna(split_ts) else "",
            "period_a_range": period_a_range,
            "period_b_range": period_b_range,
            "period_a_n": period_a_n,
            "period_b_n": period_b_n,
            "n_common_dd_levels": 0,
            "spearman_rho": np.nan,
            "spearman_p": np.nan,
            "note": f"skip: n_machine_days={machine_days} < min_machine_days_for_split={min_machine_days_for_split}",
        }

    if period_a.empty or period_b.empty:
        return {
            "hall": hall,
            "machine_name": machine_name,
            "outcome": outcome,
            "split_date": split_ts.date().isoformat() if pd.notna(split_ts) else "",
            "period_a_range": period_a_range,
            "period_b_range": period_b_range,
            "period_a_n": period_a_n,
            "period_b_n": period_b_n,
            "n_common_dd_levels": 0,
            "spearman_rho": np.nan,
            "spearman_p": np.nan,
            "note": "skip: empty period after split",
        }

    a_values, _, a_dropped = _dd_vector(period_a, outcome=outcome, min_cell_n=min_cell_n_for_split)
    b_values, _, b_dropped = _dd_vector(period_b, outcome=outcome, min_cell_n=min_cell_n_for_split)
    valid_mask = a_values.notna() & b_values.notna()
    n_common = int(valid_mask.sum())

    if n_common < min_common_levels:
        return {
            "hall": hall,
            "machine_name": machine_name,
            "outcome": outcome,
            "split_date": split_ts.date().isoformat() if pd.notna(split_ts) else "",
            "period_a_range": period_a_range,
            "period_b_range": period_b_range,
            "period_a_n": period_a_n,
            "period_b_n": period_b_n,
            "n_common_dd_levels": n_common,
            "spearman_rho": np.nan,
            "spearman_p": np.nan,
            "note": f"skip: n_common_dd_levels={n_common} < min_common_levels={min_common_levels}; dropped_sparse_a={a_dropped}; dropped_sparse_b={b_dropped}",
        }

    a_valid_values = a_values.loc[valid_mask]
    b_valid_values = b_values.loc[valid_mask]
    if a_valid_values.nunique(dropna=True) < 2 or b_valid_values.nunique(dropna=True) < 2:
        return {
            "hall": hall,
            "machine_name": machine_name,
            "outcome": outcome,
            "split_date": split_ts.date().isoformat() if pd.notna(split_ts) else "",
            "period_a_range": period_a_range,
            "period_b_range": period_b_range,
            "period_a_n": period_a_n,
            "period_b_n": period_b_n,
            "n_common_dd_levels": n_common,
            "spearman_rho": np.nan,
            "spearman_p": np.nan,
            "note": f"skip: insufficient variation; dropped_sparse_a={a_dropped}; dropped_sparse_b={b_dropped}",
        }

    rho, p_value = spearmanr(a_valid_values.to_numpy(), b_valid_values.to_numpy())
    if pd.isna(rho) or pd.isna(p_value):
        note = f"skip: spearman undefined; dropped_sparse_a={a_dropped}; dropped_sparse_b={b_dropped}"
    else:
        note = ""
    return {
        "hall": hall,
        "machine_name": machine_name,
        "outcome": outcome,
        "split_date": split_ts.date().isoformat() if pd.notna(split_ts) else "",
        "period_a_range": period_a_range,
        "period_b_range": period_b_range,
        "period_a_n": period_a_n,
        "period_b_n": period_b_n,
        "n_common_dd_levels": n_common,
        "spearman_rho": float(rho) if pd.notna(rho) else np.nan,
        "spearman_p": float(p_value) if pd.notna(p_value) else np.nan,
        "note": note,
    }


def build_hall_outputs(
    hall: str,
    raw: pd.DataFrame,
    *,
    candidate_signals: pd.DataFrame | None = None,
    shindai_exclude_days: int = DEFAULT_SHINDAI_EXCLUDE_DAYS,
    currently_installed_grace_days: int = DEFAULT_CURRENTLY_INSTALLED_GRACE_DAYS,
    min_machine_days_for_split: int = DEFAULT_MIN_MACHINE_DAYS_FOR_SPLIT,
    min_cell_n_for_split: int = DEFAULT_MIN_CELL_N_FOR_SPLIT,
    min_common_levels: int = DEFAULT_MIN_COMMON_LEVELS,
) -> pd.DataFrame:
    frame = _prepare_analysis_frame(
        raw,
        shindai_exclude_days=shindai_exclude_days,
        currently_installed_grace_days=currently_installed_grace_days,
    )
    if frame.empty:
        return pd.DataFrame(columns=PERSISTENCE_COLUMNS)

    if candidate_signals is None:
        candidate_signals = _load_candidate_signals(hall)
    else:
        candidate_signals = candidate_signals.copy()

    if candidate_signals.empty:
        return pd.DataFrame(columns=PERSISTENCE_COLUMNS)

    split_ts = _split_timestamp(frame)
    rows: list[dict[str, object]] = []
    for _, row in candidate_signals.sort_values(
        ["effect_size", "n_obs", "machine_name", "outcome"],
        ascending=[False, False, True, True],
        kind="mergesort",
    ).iterrows():
        rows.append(
            _spearman_row(
                hall,
                str(row["machine_name"]),
                str(row["outcome"]),
                frame,
                split_ts=split_ts,
                min_machine_days_for_split=min_machine_days_for_split,
                min_cell_n_for_split=min_cell_n_for_split,
                min_common_levels=min_common_levels,
            )
        )

    result = pd.DataFrame(rows, columns=PERSISTENCE_COLUMNS)
    if not result.empty:
        result = result.sort_values(
            ["hall", "spearman_rho", "machine_name", "outcome"],
            ascending=[True, False, True, True],
            na_position="last",
            kind="mergesort",
        ).reset_index(drop=True)
    return result


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def _print_hall_report(hall: str, frame: pd.DataFrame) -> None:
    print(f"\n=== {hall} ===")
    if frame.empty:
        print("no candidate rows")
        return
    print(
        frame.loc[
            :,
            [
                "machine_name",
                "outcome",
                "spearman_rho",
                "spearman_p",
                "n_common_dd_levels",
                "period_a_n",
                "period_b_n",
                "note",
            ],
        ].to_string(index=False)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check DD-pattern persistence by splitting each hall into two periods."
    )
    parser.add_argument("--halls", type=_parse_halls, default=DEFAULT_HALLS)
    parser.add_argument("--min-machine-days-for-split", type=int, default=DEFAULT_MIN_MACHINE_DAYS_FOR_SPLIT)
    parser.add_argument("--min-cell-n-for-split", type=int, default=DEFAULT_MIN_CELL_N_FOR_SPLIT)
    parser.add_argument("--min-common-levels", type=int, default=DEFAULT_MIN_COMMON_LEVELS)
    args = parser.parse_args(argv)

    _ensure_output_dir(DEFAULT_OUTPUT_PATH)
    all_rows: list[pd.DataFrame] = []

    for hall in args.halls:
        if hall not in HALL_DBS:
            raise ValueError(f"unknown hall: {hall}")
        raw = load_hall_df(hall)
        candidate_signals = _load_candidate_signals(hall)
        hall_rows = build_hall_outputs(
            hall,
            raw,
            candidate_signals=candidate_signals,
            min_machine_days_for_split=args.min_machine_days_for_split,
            min_cell_n_for_split=args.min_cell_n_for_split,
            min_common_levels=args.min_common_levels,
        )
        _print_hall_report(hall, hall_rows)
        all_rows.append(hall_rows)

    result = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame(columns=PERSISTENCE_COLUMNS)
    if not result.empty:
        result = result.sort_values(
            ["hall", "spearman_rho", "machine_name", "outcome"],
            ascending=[True, False, True, True],
            na_position="last",
            kind="mergesort",
        ).reset_index(drop=True)
    _write_csv(result, DEFAULT_OUTPUT_PATH)
    print(f"\nwritten: {DEFAULT_OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
