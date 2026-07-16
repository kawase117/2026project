"""Scan DD=14 rows across four halls and print the requested rankings."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCUMENT_DIR = PROJECT_ROOT / "document"

TARGET_DD = 14
MIN_N_DATES = 3
MIN_N_MACHINES = 3
TOP_N = 8

HALLS = ["みとや", "蒲田7", "蒲田1", "楽園"]
OUTPUT_COLUMNS = [
    "category",
    "value",
    "avg_diff",
    "hit104_rate",
    "win_rate",
    "n_records",
    "n_machines",
    "n_dates",
]


def find_latest_csv(hall_name: str) -> Path | None:
    pattern = f"{hall_name}_dd_crosstab_*.csv"
    matches = sorted(DOCUMENT_DIR.glob(pattern))
    return matches[-1] if matches else None


def load_dd14(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    if "dd" not in df.columns:
        raise KeyError(f"missing required column: dd in {csv_path}")
    return df[df["dd"] == TARGET_DD].copy()


def filter_reliable(df: pd.DataFrame, min_n_dates: int, min_n_machines: int) -> pd.DataFrame:
    required = {"n_dates", "n_machines"}
    missing = required.difference(df.columns)
    if missing:
        missing_cols = ", ".join(sorted(missing))
        raise KeyError(f"missing required columns: {missing_cols}")
    return df[(df["n_dates"] >= min_n_dates) & (df["n_machines"] >= min_n_machines)].copy()


def rank_by(df: pd.DataFrame, column: str, top_n: int) -> pd.DataFrame:
    if column not in df.columns:
        raise KeyError(f"missing required column: {column}")
    return df.sort_values(column, ascending=False).head(top_n)


def print_table(df: pd.DataFrame, cols: Iterable[str]) -> None:
    if df.empty:
        print("  (no rows)")
        return
    print(df.loc[:, list(cols)].to_string(index=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan DD=14 cross-hall crosstabs")
    parser.add_argument("--halls", nargs="+", default=HALLS)
    parser.add_argument("--min-n-dates", type=int, default=MIN_N_DATES)
    parser.add_argument("--min-n-machines", type=int, default=MIN_N_MACHINES)
    parser.add_argument("--top-n", type=int, default=TOP_N)
    args = parser.parse_args(argv)

    total_dd14_rows = 0
    total_reliable_rows = 0

    for hall_name in args.halls:
        print(f"\n{'=' * 70}")
        print(f"{hall_name} - DD={TARGET_DD}")
        print("=" * 70)

        csv_path = find_latest_csv(hall_name)
        if csv_path is None:
            print(f"  CSV not found for {hall_name}")
            continue

        df = load_dd14(csv_path)
        dd14_rows = len(df)
        total_dd14_rows += dd14_rows

        if df.empty:
            print(f"  dd={TARGET_DD} data not found")
            continue

        reliable = filter_reliable(df, args.min_n_dates, args.min_n_machines)
        reliable_rows = len(reliable)
        total_reliable_rows += reliable_rows
        excluded = dd14_rows - reliable_rows

        print(
            f"  total={dd14_rows} / reliable={reliable_rows} "
            f"(n_dates>={args.min_n_dates}, n_machines>={args.min_n_machines}, excluded={excluded})"
        )

        print(f"\n  [avg_diff top {args.top_n}]")
        top_diff = rank_by(reliable, "avg_diff", args.top_n)
        print_table(top_diff, OUTPUT_COLUMNS)

        print(f"\n  [hit104_rate top {args.top_n}]")
        top_hit104 = rank_by(reliable, "hit104_rate", args.top_n)
        print_table(top_hit104, OUTPUT_COLUMNS)

    excluded_total = total_dd14_rows - total_reliable_rows
    print(
        f"\n{('=' * 70)}\n"
        f"DD={TARGET_DD} summary: total={total_dd14_rows}, reliable={total_reliable_rows}, "
        f"excluded={excluded_total}\n"
        f"{('=' * 70)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
