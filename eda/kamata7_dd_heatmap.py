"""
蒲田7 DD条件付きセグメントヒートマップ

目的:
  - 10台ブロックごとの 104%超え率を DD(1-31) で可視化する
  - Even / Odd の差分を DD 別に確認する
  - 座標ベースの位置クォータイル(Q1-Q4)を DD 別に確認する

出力:
  - eda/results/kamata7_dd_heatmap_by_section.csv
  - eda/results/kamata7_dd_even_odd.csv
  - eda/results/kamata7_dd_quartile.csv
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田7.db"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "eda" / "results"
DEFAULT_COORD_2F = PROJECT_ROOT / "Heatmap" / "2F_floor_coordinates_kamata7.csv"
DEFAULT_COORD_3F = PROJECT_ROOT / "Heatmap" / "3F_floor_coordinates_kamata7.csv"

MIN_GAMES = 1500
MIN_CELL_N = 5
DD_VALUES = list(range(1, 32))
DD_COLUMNS = [f"DD{dd:02d}" for dd in DD_VALUES]
SECTION_FLOOR_ORDER = {"2F": 0, "3F": 1}
QUARTILE_ORDER = ["Q1", "Q2", "Q3", "Q4"]


def _calc_payout_rate(frame: pd.DataFrame) -> pd.Series:
    games = pd.to_numeric(frame["games_normalized"], errors="coerce")
    diff = pd.to_numeric(frame["diff_coins_normalized"], errors="coerce")
    denom = games * 3
    denom = denom.replace(0, np.nan)
    return ((denom + diff) / denom) * 100


def _load_coordinates() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in (DEFAULT_COORD_2F, DEFAULT_COORD_3F):
        coords = pd.read_csv(path)
        required = {"floor", "machine_number", "rank_from_aisle"}
        missing = required - set(coords.columns)
        if missing:
            raise ValueError(f"Missing coordinate columns in {path}: {sorted(missing)}")

        for column in ("machine_number", "X", "Y", "display_x", "display_y", "rank_from_aisle"):
            if column in coords.columns:
                coords[column] = pd.to_numeric(coords[column], errors="coerce")

        coords = coords.dropna(subset=["machine_number", "rank_from_aisle"]).copy()
        coords["machine_number"] = coords["machine_number"].astype(int)
        coords["rank_from_aisle"] = coords["rank_from_aisle"].astype(int)
        coords["floor"] = coords["floor"].astype(str)
        frames.append(coords[["floor", "machine_number", "rank_from_aisle"]].copy())

    coords = pd.concat(frames, ignore_index=True)
    coords = coords.drop_duplicates(subset=["machine_number"], keep="first").copy()
    return coords


def _load_frame(db_path: Path) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    try:
        frame = pd.read_sql_query(
            """
            SELECT
                date,
                machine_name,
                machine_number,
                games_normalized,
                diff_coins_normalized,
                CAST(SUBSTR(date, 7, 2) AS INTEGER) AS dd
            FROM machine_detailed_results
            WHERE games_normalized >= ?
              AND machine_number BETWEEN 2000 AND 3999
              AND machine_number != 2026
            """,
            conn,
            params=(MIN_GAMES,),
        )
    finally:
        conn.close()

    frame["machine_number"] = pd.to_numeric(frame["machine_number"], errors="coerce")
    frame["dd"] = pd.to_numeric(frame["dd"], errors="coerce")
    frame = frame.dropna(subset=["machine_number", "dd"]).copy()
    frame["machine_number"] = frame["machine_number"].astype(int)
    frame["dd"] = frame["dd"].astype(int)
    frame["floor"] = np.where(frame["machine_number"] < 3000, "2F", "3F")
    frame = frame[frame["floor"].isin(SECTION_FLOOR_ORDER)].copy()
    frame["payout_rate"] = _calc_payout_rate(frame)
    frame["hit104"] = (frame["payout_rate"] >= 104.0).astype(int)
    return frame


def _attach_coordinates(frame: pd.DataFrame) -> pd.DataFrame:
    coords = _load_coordinates()
    merged = frame.merge(coords, on="machine_number", how="left", validate="many_to_one")
    merged["floor"] = merged["floor_x"].fillna(merged["floor_y"]).fillna(merged["floor_x"])
    merged["rank_from_aisle"] = pd.to_numeric(merged["rank_from_aisle"], errors="coerce")
    merged = merged.drop(columns=[col for col in ("floor_x", "floor_y") if col in merged.columns])
    merged = merged[merged["floor"].isin(SECTION_FLOOR_ORDER)].copy()
    return merged


def _assign_quartiles(coords: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for floor, floor_coords in coords.groupby("floor", sort=False):
        unique = (
            floor_coords[["machine_number", "rank_from_aisle"]]
            .drop_duplicates(subset=["machine_number"], keep="first")
            .sort_values(["rank_from_aisle", "machine_number"], ascending=[True, True])
            .copy()
        )
        if unique.empty:
            continue

        unique["quartile"] = pd.NA
        parts = np.array_split(unique.index.to_numpy(), 4)
        for label, index_values in zip(QUARTILE_ORDER, parts, strict=True):
            if len(index_values) == 0:
                continue
            unique.loc[index_values, "quartile"] = label

        unique["quartile"] = unique["quartile"].fillna(QUARTILE_ORDER[-1])
        unique["floor"] = floor
        rows.append(unique[["floor", "machine_number", "quartile"]].copy())

    if not rows:
        return pd.DataFrame(columns=["floor", "machine_number", "quartile"])
    return pd.concat(rows, ignore_index=True)


def _build_section_frame(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    block_start = ((work["machine_number"] - 2001) // 10) * 10 + 2001
    block_end = block_start + 9
    work["block_start"] = block_start.astype(int)
    work["block_end"] = block_end.astype(int)
    work["block_label"] = work.apply(
        lambda row: f"{row['floor']}_{int(row['block_start'])}-{int(row['block_end'])}",
        axis=1,
    )

    agg = (
        work.groupby(["block_label", "dd"], as_index=False)
        .agg(
            n=("hit104", "size"),
            hit104_rate=("hit104", "mean"),
            floor=("floor", "first"),
            block_start=("block_start", "first"),
        )
        .sort_values(["floor", "block_start"], ascending=[True, True])
        .reset_index(drop=True)
    )
    agg["hit104_rate"] = (agg["hit104_rate"] * 100).round(1)
    agg.loc[agg["n"] < MIN_CELL_N, "hit104_rate"] = np.nan

    pivot = (
        agg.pivot_table(index=["floor", "block_label"], columns="dd", values="hit104_rate", aggfunc="first")
        .reindex(columns=DD_VALUES)
        .rename(columns={dd: col for dd, col in zip(DD_VALUES, DD_COLUMNS, strict=True)})
        .reset_index()
    )
    return pivot


def _build_even_odd_frame(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["parity"] = np.where(work["machine_number"] % 2 == 0, "Even", "Odd")
    agg = (
        work.groupby(["dd", "parity"], as_index=False)
        .agg(
            n=("hit104", "size"),
            hit104_rate=("hit104", "mean"),
        )
        .sort_values(["dd", "parity"], ascending=[True, True])
        .reset_index(drop=True)
    )
    agg["hit104_rate"] = (agg["hit104_rate"] * 100).round(1)
    agg.loc[agg["n"] < MIN_CELL_N, "hit104_rate"] = np.nan

    pivot = (
        agg.pivot(index="dd", columns="parity", values="hit104_rate")
        .reindex(index=DD_VALUES, columns=["Even", "Odd"])
        .rename(columns={"Even": "even_rate", "Odd": "odd_rate"})
    )
    counts = (
        agg.pivot(index="dd", columns="parity", values="n")
        .reindex(index=DD_VALUES, columns=["Even", "Odd"])
        .rename(columns={"Even": "n_even", "Odd": "n_odd"})
    )
    out = pivot.join(counts)
    out["diff_pp"] = out["even_rate"] - out["odd_rate"]
    out["n_total"] = out[["n_even", "n_odd"]].sum(axis=1, min_count=1)
    out.index.name = "dd"
    return out.reset_index()


def _build_quartile_frame(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    quartiles = _assign_quartiles(work[["floor", "machine_number", "rank_from_aisle"]].copy())
    work = work.merge(quartiles, on=["floor", "machine_number"], how="left", validate="many_to_one")
    work = work[work["quartile"].isin(QUARTILE_ORDER)].copy()

    agg = (
        work.groupby(["floor", "quartile", "dd"], as_index=False)
        .agg(
            n=("hit104", "size"),
            hit104_rate=("hit104", "mean"),
        )
        .sort_values(["floor", "quartile", "dd"], ascending=[True, True, True])
        .reset_index(drop=True)
    )
    agg["hit104_rate"] = (agg["hit104_rate"] * 100).round(1)
    agg.loc[agg["n"] < MIN_CELL_N, "hit104_rate"] = np.nan

    pivot = (
        agg.pivot_table(index=["floor", "quartile"], columns="dd", values="hit104_rate", aggfunc="first")
        .reindex(columns=DD_VALUES)
        .rename(columns={dd: col for dd, col in zip(DD_VALUES, DD_COLUMNS, strict=True)})
        .reset_index()
    )
    return pivot


def _format_rate(value: object) -> str:
    if value is None or pd.isna(value):
        return "NaN"
    return f"{float(value):.1f}"


def _print_section(title: str) -> None:
    print()
    print("=" * 88)
    print(title)
    print("=" * 88)


def _print_even_odd_summary(even_odd: pd.DataFrame) -> None:
    diff_df = even_odd.dropna(subset=["diff_pp"]).copy()
    if diff_df.empty:
        print("Even/Odd の差分を算出できる DD がありません。")
        return

    large = diff_df[diff_df["diff_pp"].abs() >= 5.0].copy()
    print("Even/Odd 差が 5pp 以上の DD:")
    if large.empty:
        print("  なし")
        print("  参考: abs(diff) 上位 10 件")
        top = diff_df.assign(abs_diff=diff_df["diff_pp"].abs()).sort_values("abs_diff", ascending=False).head(10)
        cols = ["dd", "even_rate", "odd_rate", "diff_pp", "n_even", "n_odd", "n_total"]
        display = top[cols].copy()
        display["even_rate"] = display["even_rate"].map(_format_rate)
        display["odd_rate"] = display["odd_rate"].map(_format_rate)
        display["diff_pp"] = display["diff_pp"].map(_format_rate)
        print(display.to_string(index=False))
        return

    large = large.sort_values("diff_pp", key=lambda s: s.abs(), ascending=False)
    cols = ["dd", "even_rate", "odd_rate", "diff_pp", "n_even", "n_odd", "n_total"]
    display = large[cols].copy()
    display["even_rate"] = display["even_rate"].map(_format_rate)
    display["odd_rate"] = display["odd_rate"].map(_format_rate)
    display["diff_pp"] = display["diff_pp"].map(_format_rate)
    print(display.to_string(index=False))


def _print_quartile_summary(quartile: pd.DataFrame) -> None:
    rows: list[dict[str, object]] = []
    rate_cols = DD_COLUMNS
    for _, row in quartile.iterrows():
        rates = pd.to_numeric(row[rate_cols], errors="coerce")
        finite = rates.dropna()
        if finite.empty:
            continue
        rows.append(
            {
                "floor": row["floor"],
                "quartile": row["quartile"],
                "mean_rate": float(finite.mean()),
                "spread_pp": float(finite.max() - finite.min()),
            }
        )

    if not rows:
        print("位置クォータイルの差分を算出できるセルがありません。")
        return

    print("位置クォータイルで spread が大きい DD 上位:")

    dd_rows: list[dict[str, object]] = []
    for dd_col in DD_COLUMNS:
        dd_num = int(dd_col[2:])
        cols = quartile[["floor", "quartile", dd_col]].copy()
        subset = cols.dropna(subset=[dd_col])
        if subset.empty:
            continue
        per_floor: list[dict[str, object]] = []
        for floor, floor_group in subset.groupby("floor"):
            rates = pd.to_numeric(floor_group[dd_col], errors="coerce").dropna()
            if rates.empty:
                continue
            spread = float(rates.max() - rates.min())
            per_floor.append({"floor": floor, "spread_pp": spread, "mean_rate": float(rates.mean())})

        if not per_floor:
            continue
        floor_summary = pd.DataFrame(per_floor)
        best = floor_summary.sort_values("spread_pp", ascending=False).iloc[0]
        dd_rows.append(
            {
                "dd": dd_num,
                "max_spread_pp": float(floor_summary["spread_pp"].max()),
                "mean_spread_pp": float(floor_summary["spread_pp"].mean()),
                "floor_with_max": str(best["floor"]),
                "best_floor_spread_pp": float(best["spread_pp"]),
            }
        )

    if not dd_rows:
        print("  なし")
        return

    dd_summary = pd.DataFrame(dd_rows).sort_values("max_spread_pp", ascending=False)
    large = dd_summary[dd_summary["max_spread_pp"] >= 5.0].head(20).copy()
    if large.empty:
        print("  5pp 以上の DD はありません。")
        print(dd_summary.head(10).to_string(index=False))
        return

    print(large.to_string(index=False))


def run_analysis(db_path: Path, output_dir: Path) -> dict[str, pd.DataFrame]:
    output_dir.mkdir(parents=True, exist_ok=True)

    frame = _load_frame(db_path)
    frame = _attach_coordinates(frame)

    section = _build_section_frame(frame)
    even_odd = _build_even_odd_frame(frame)
    quartile = _build_quartile_frame(frame)

    section_path = output_dir / "kamata7_dd_heatmap_by_section.csv"
    even_odd_path = output_dir / "kamata7_dd_even_odd.csv"
    quartile_path = output_dir / "kamata7_dd_quartile.csv"

    section.to_csv(section_path, index=False, encoding="utf-8-sig")
    even_odd.to_csv(even_odd_path, index=False, encoding="utf-8-sig")
    quartile.to_csv(quartile_path, index=False, encoding="utf-8-sig")

    print(f"DB: {db_path}")
    print(f"rows: {len(frame):,}")
    print(f"days: {frame['date'].nunique():,}")
    print(f"date range: {frame['date'].min()} - {frame['date'].max()}")
    print(f"floors: {sorted(frame['floor'].dropna().unique().tolist())}")
    print(f"output_dir: {output_dir}")

    _print_section("Even/Odd summary")
    _print_even_odd_summary(even_odd)

    _print_section("Quartile summary")
    _print_quartile_summary(quartile)

    return {"section": section, "even_odd": even_odd, "quartile": quartile}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kamata7 DD conditional heatmap EDA")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    run_analysis(args.db, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
