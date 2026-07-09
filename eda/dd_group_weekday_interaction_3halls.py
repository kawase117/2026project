"""
DD系統 × 曜日 3ホール横断スキャン.

Outputs:
  - eda/results/dd_group_weekday_3halls.csv

This script reuses eda.core.load_hall_df and eda.core.scan_dimension.
It reports:
  - dd_group × day_of_week
  - is_x_day × day_of_week
for 蒲田1 / 蒲田7 / みとや.
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda.core import load_hall_df, scan_dimension


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "eda" / "results"
OUTPUT_CSV = OUTPUT_DIR / "dd_group_weekday_3halls.csv"
HALLS = ["蒲田1", "蒲田7", "みとや"]
DOW_ORDER = ["月", "火", "水", "木", "金", "土", "日"]
MATRIX_KINDS = ("dd_group", "is_x_day")
MIN_N_DEFAULT = 5
EXPECTED_REPRO = {
    ("蒲田7", "dd_group", "7系", "月"): {"avg_diff": 807.0, "ci_low": 692.0, "ci_high": 930.0},
    ("蒲田7", "dd_group", "7系", "土"): {"avg_diff": 150.0},
    ("みとや", "dd_group", "4系", "土"): {"avg_diff": 356.0, "ci_low": 217.0, "ci_high": 493.0},
}


def _calc_hit104_rate(frame: pd.DataFrame, group_cols: list[str]) -> pd.Series:
    work = frame.copy()
    games = pd.to_numeric(work["games"], errors="coerce")
    diff = pd.to_numeric(work["diff"], errors="coerce")
    denom = (games * 3).replace(0, np.nan)
    payout_rate = ((denom + diff) / denom) * 100
    work["_hit104"] = (payout_rate >= 104.0).astype(int)
    grouped = work.groupby(group_cols)["_hit104"].mean() * 100
    return grouped


def _prepare_frame(
    hall_name: str,
    df: pd.DataFrame | None = None,
    *,
    exclude_anniversary: bool = True,
    log_exclusion: bool = False,
) -> pd.DataFrame:
    work = load_hall_df(hall_name) if df is None else df.copy()
    if hall_name == "蒲田7" and exclude_anniversary:
        before = len(work)
        work = work.loc[work["date"].astype(str) != "20250707"].copy()
        removed = before - len(work)
        if removed and log_exclusion:
            print(f"[{hall_name}] 7/7除外: {removed:,} rows")
    return work


def _matrix_spec(matrix_kind: str) -> tuple[list[str], dict[object, str], str]:
    if matrix_kind == "dd_group":
        return ["dd_group", "day_of_week"], {}, "dd_group"
    if matrix_kind == "is_x_day":
        return ["is_x_day", "day_of_week"], {0: "非イベント", 1: "X_DDS"}, "dd_group"
    raise ValueError(f"Unknown matrix_kind: {matrix_kind!r}")


def build_hall_matrix(
    hall_name: str,
    *,
    matrix_kind: str,
    df: pd.DataFrame | None = None,
    min_n: int = MIN_N_DEFAULT,
    exclude_anniversary: bool = True,
) -> pd.DataFrame:
    work = _prepare_frame(hall_name, df, exclude_anniversary=exclude_anniversary)
    group_cols, label_map, label_col = _matrix_spec(matrix_kind)

    scanned = scan_dimension(hall_name, group_cols, min_n=min_n, df=work)
    if scanned.empty:
        return pd.DataFrame(
            columns=[
                "hall",
                "dd_group",
                "day_of_week",
                "avg_diff",
                "plus_rate",
                "hit104_rate",
                "n",
                "ci_low",
                "ci_high",
                "tier",
            ]
        )

    hit104 = _calc_hit104_rate(work, group_cols).rename("hit104_rate").reset_index()
    merged = scanned.merge(hit104, on=group_cols, how="left", validate="one_to_one")

    if label_map:
        merged[label_col] = merged["is_x_day"].map(label_map)
    elif label_col != "dd_group":
        merged[label_col] = merged[label_col].astype(str)

    if matrix_kind == "is_x_day":
        merged["dd_group"] = merged["dd_group"].astype(str)

    out = merged.rename(columns={"ci_lo": "ci_low", "ci_hi": "ci_high"})
    out["hall"] = hall_name
    out["hit104_rate"] = out["hit104_rate"].round(1)
    out = out.loc[
        :,
        [
            "hall",
            "dd_group",
            "day_of_week",
            "avg_diff",
            "plus_rate",
            "hit104_rate",
            "n",
            "ci_low",
            "ci_high",
            "tier",
        ],
    ].copy()

    if matrix_kind == "dd_group":
        dd_order = ["4系", "7系", "その他"]
    else:
        dd_order = ["X_DDS", "非イベント"]
    out["dd_group"] = pd.Categorical(out["dd_group"], categories=dd_order, ordered=True)
    out["day_of_week"] = pd.Categorical(out["day_of_week"], categories=DOW_ORDER, ordered=True)
    out = out.sort_values(["dd_group", "day_of_week"], kind="mergesort").reset_index(drop=True)
    out["dd_group"] = out["dd_group"].astype(str)
    out["day_of_week"] = out["day_of_week"].astype(str)
    return out


def build_three_hall_results(
    halls: list[str] | None = None,
    *,
    min_n: int = MIN_N_DEFAULT,
) -> pd.DataFrame:
    hall_list = halls or HALLS
    frames: list[pd.DataFrame] = []
    for hall in hall_list:
        for matrix_kind in MATRIX_KINDS:
            frames.append(build_hall_matrix(hall, matrix_kind=matrix_kind, min_n=min_n))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _format_value(value: object) -> str:
    if value is None or pd.isna(value):
        return "NaN"
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.0f}" if float(value).is_integer() else f"{float(value):.1f}"
    return str(value)


def _print_matrix(title: str, frame: pd.DataFrame) -> None:
    print(title)
    if frame.empty:
        print("  <no rows>")
        return
    summary = frame.loc[
        :, ["dd_group", "day_of_week", "avg_diff", "plus_rate", "hit104_rate", "n", "ci_low", "ci_high", "tier"]
    ].copy()
    for _, row in summary.iterrows():
        print(
            f"  {row['dd_group']}×{row['day_of_week']}: "
            f"avg={_format_value(row['avg_diff'])} "
            f"(plus={_format_value(row['plus_rate'])}%, "
            f"hit104={_format_value(row['hit104_rate'])}%, "
            f"n={int(row['n'])}, "
            f"CI=[{_format_value(row['ci_low'])}, {_format_value(row['ci_high'])}], "
            f"Tier {row['tier']})"
        )


def _cell_lookup(frame: pd.DataFrame, dd_group: str, day_of_week: str) -> pd.Series | None:
    mask = frame["dd_group"].astype(str).eq(dd_group) & frame["day_of_week"].astype(str).eq(day_of_week)
    if not mask.any():
        return None
    return frame.loc[mask].iloc[0]


def _warn_if_repro_mismatch(frame: pd.DataFrame, hall_name: str) -> None:
    for (expected_hall, matrix_kind, group_value, day_of_week), expected in EXPECTED_REPRO.items():
        if expected_hall != hall_name:
            continue
        subset = frame if matrix_kind == "dd_group" else pd.DataFrame()
        cell = _cell_lookup(subset, group_value, day_of_week)
        if cell is None:
            warnings.warn(f"[{hall_name}] missing check cell: {group_value}×{day_of_week}")
            continue
        avg_diff = float(cell["avg_diff"])
        ci_low = float(cell["ci_low"])
        ci_high = float(cell["ci_high"])
        avg_ok = abs(avg_diff - expected["avg_diff"]) <= 5.0
        ci_low_ok = "ci_low" not in expected or abs(ci_low - expected["ci_low"]) <= 5.0
        ci_high_ok = "ci_high" not in expected or abs(ci_high - expected["ci_high"]) <= 5.0
        if avg_ok and ci_low_ok and ci_high_ok:
            print(f"  [repro OK] {group_value}×{day_of_week}: avg={avg_diff:.0f}, CI=[{ci_low:.0f}, {ci_high:.0f}]")
        else:
            print(
                f"  [WARN] {group_value}×{day_of_week}: "
                f"avg={avg_diff:.0f} vs expected {expected['avg_diff']:.0f}, "
                f"CI=[{ci_low:.0f}, {ci_high:.0f}]"
            )


def _print_hall_report(hall_name: str, df: pd.DataFrame) -> None:
    print()
    print(f"=== {hall_name} ===")
    dd_matrix = build_hall_matrix(hall_name, matrix_kind="dd_group", df=df, exclude_anniversary=False)
    xday_matrix = build_hall_matrix(hall_name, matrix_kind="is_x_day", df=df, exclude_anniversary=False)

    print("dd_group × 曜日マトリクス:")
    _print_matrix("  dd_group × 曜日", dd_matrix)
    print("is_x_day × 曜日マトリクス:")
    _print_matrix("  is_x_day × 曜日", xday_matrix)

    for day in ["月", "土", "木", "日"]:
        cell = _cell_lookup(dd_matrix, "7系", day)
        if cell is not None:
            print(
                f"  7系×{day}: avg={_format_value(cell['avg_diff'])} "
                f"(n={int(cell['n'])}, CI=[{_format_value(cell['ci_low'])}, {_format_value(cell['ci_high'])}], Tier {cell['tier']})"
            )

    if hall_name in {"蒲田7", "みとや"}:
        _warn_if_repro_mismatch(dd_matrix, hall_name)

    if hall_name == "みとや":
        cell = _cell_lookup(dd_matrix, "4系", "土")
        if cell is not None:
            print(
                f"  4系×土: avg={_format_value(cell['avg_diff'])} "
                f"(n={int(cell['n'])}, CI=[{_format_value(cell['ci_low'])}, {_format_value(cell['ci_high'])}], Tier {cell['tier']})"
            )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DD系統×曜日 3ホール横断スキャン")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--min-n", type=int, default=MIN_N_DEFAULT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    combined_rows: list[pd.DataFrame] = []
    for hall_name in HALLS:
        df = _prepare_frame(hall_name, load_hall_df(hall_name), log_exclusion=True)
        _print_hall_report(hall_name, df)
        combined_rows.append(
            build_hall_matrix(hall_name, matrix_kind="dd_group", df=df, min_n=args.min_n, exclude_anniversary=False)
        )
        combined_rows.append(
            build_hall_matrix(hall_name, matrix_kind="is_x_day", df=df, min_n=args.min_n, exclude_anniversary=False)
        )

    combined = pd.concat(combined_rows, ignore_index=True) if combined_rows else pd.DataFrame()
    combined.to_csv(output_dir / OUTPUT_CSV.name, index=False, encoding="utf-8-sig")
    print()
    print(f"Wrote: {output_dir / OUTPUT_CSV.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
