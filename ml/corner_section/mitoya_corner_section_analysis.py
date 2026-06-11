from __future__ import annotations

import argparse
import contextlib
import os
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from tqdm import tqdm as _tqdm_cls

    def _progress(iterable, **kwargs):
        return _tqdm_cls(iterable, **kwargs)

    @contextlib.contextmanager
    def _step_bar(total: int, **kwargs):
        bar = _tqdm_cls(total=total, **kwargs)
        try:
            yield bar
        finally:
            bar.close()

except ImportError:
    def _progress(iterable, **kwargs):  # type: ignore[misc]
        return iterable

    @contextlib.contextmanager
    def _step_bar(total: int, **kwargs):  # type: ignore[misc]
        class _Stub:
            def update(self, n=1): pass
            def set_description(self, s): pass
        yield _Stub()

WEEKDAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
REQUIRED_TABLES = {
    "machine_detailed_results",
    "machine_layout",
    "machine_master",
    "daily_hall_summary",
}
OUTPUT_FILES = {
    "corner_all": "corner_all.csv",
    "corner_by_type": "corner_by_type.csv",
    "section_all": "section_all.csv",
    "section_by_type": "section_by_type.csv",
    "corner_by_dd": "corner_by_dd.csv",
    "corner_by_weekday": "corner_by_weekday.csv",
    "corner_by_mmdd": "corner_by_mmdd.csv",
    "section_by_dd": "section_by_dd.csv",
    "section_by_weekday": "section_by_weekday.csv",
    "section_by_mmdd": "section_by_mmdd.csv",
}


def _has_required_tables(db_path: Path) -> bool:
    try:
        con = sqlite3.connect(db_path)
    except sqlite3.Error:
        return False
    try:
        tables = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    finally:
        con.close()
    return REQUIRED_TABLES.issubset(tables)


def resolve_mitoya_db_path(
    raw_path: str = "",
    *,
    db_dir: Path = Path("db"),
    index_hint: int = 6,
) -> Path:
    if raw_path:
        db_path = Path(raw_path)
        if not db_path.exists():
            raise FileNotFoundError(f"DB not found: {db_path}")
        return db_path

    names = sorted(os.listdir(db_dir))
    if index_hint < len(names):
        hinted = db_dir / names[index_hint]
        if hinted.suffix == ".db" and _has_required_tables(hinted):
            return hinted

    for name in names:
        candidate = db_dir / name
        if "みとや" not in name or candidate.suffix != ".db":
            continue
        if _has_required_tables(candidate):
            return candidate

    raise FileNotFoundError(
        f"No usable Mitoya DB found under {db_dir}. Checked index {index_hint} and Mitoya-named DB files."
    )


def load_analysis_frame(db_path: Path) -> pd.DataFrame:
    query = """
    SELECT
        m.date,
        m.machine_number,
        m.machine_name,
        m.diff_coins_normalized,
        m.machine_rank_in_type,
        m.games_normalized,
        ml.rank_from_min,
        ml.section,
        COALESCE(mm.jug_flag, 0) AS jug_flag,
        COALESCE(mm.hana_flag, 0) AS hana_flag,
        COALESCE(mm.oki_flag, 0) AS oki_flag,
        COALESCE(mm.bt_flag, 0) AS bt_flag,
        COALESCE(dh.avg_diff_per_machine, 0) AS avg_diff_per_machine
    FROM machine_detailed_results m
    LEFT JOIN machine_layout ml
      ON m.machine_number = ml.machine_number
    LEFT JOIN machine_master mm
      ON m.machine_name = mm.machine_name_normalized
    LEFT JOIN daily_hall_summary dh
      ON m.date = dh.date
    """
    con = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(query, con)
    finally:
        con.close()
    if df.empty:
        raise ValueError(f"No rows loaded from {db_path}")
    return df


def prepare_analysis_frame(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work = work.dropna(subset=["rank_from_min", "section"]).copy()
    work["rank_from_min"] = pd.to_numeric(work["rank_from_min"], errors="coerce")
    work = work.dropna(subset=["rank_from_min"]).copy()
    work["rank_from_min"] = work["rank_from_min"].astype(int)
    work["date"] = pd.to_datetime(work["date"], format="%Y%m%d")

    machine_type_conditions = [
        pd.to_numeric(work["jug_flag"], errors="coerce").fillna(0).eq(1),
        pd.to_numeric(work["hana_flag"], errors="coerce").fillna(0).eq(1),
        pd.to_numeric(work["oki_flag"], errors="coerce").fillna(0).eq(1),
        pd.to_numeric(work["bt_flag"], errors="coerce").fillna(0).eq(1),
    ]
    work["machine_type"] = np.select(
        machine_type_conditions,
        ["jug", "hana", "oki", "bt"],
        default="other",
    )
    work["dd"] = work["date"].dt.day.astype(int)
    work["mm"] = work["date"].dt.month.astype(int)
    work["day_of_week"] = work["date"].dt.strftime("%a")
    work["is_mm_dd"] = work["mm"].eq(work["dd"]).astype(int)
    work["is_hall_plus"] = pd.to_numeric(work["avg_diff_per_machine"], errors="coerce").fillna(0).gt(0).astype(int)
    work["plus_flag"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce").fillna(0).gt(0).astype(int)
    work["date"] = work["date"].dt.strftime("%Y%m%d")
    return work


def aggregate_metrics(df: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    grouped = (
        df.groupby(group_columns, dropna=False, sort=True)
        .agg(
            avg_diff=("diff_coins_normalized", "mean"),
            avg_rank=("machine_rank_in_type", "mean"),
            plus_rate=("plus_flag", "mean"),
            sample_n=("diff_coins_normalized", "size"),
        )
        .reset_index()
    )
    grouped["sample_n"] = grouped["sample_n"].astype(int)
    return sort_aggregated_frame(grouped, group_columns)


def sort_aggregated_frame(df: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    work = df.copy()
    sort_columns: list[str] = []
    ascending: list[bool] = []

    if "day_of_week" in work.columns:
        work["day_of_week"] = pd.Categorical(
            work["day_of_week"],
            categories=WEEKDAY_ORDER,
            ordered=True,
        )

    for column in group_columns:
        sort_columns.append(column)
        ascending.append(True)

    work = work.sort_values(sort_columns, ascending=ascending, kind="mergesort").reset_index(drop=True)
    if "day_of_week" in work.columns:
        work["day_of_week"] = work["day_of_week"].astype(str)
    return work


_AGGREGATION_SPECS: list[tuple[str, list[str]]] = [
    ("corner_all",      ["rank_from_min"]),
    ("corner_by_type",  ["machine_type", "rank_from_min"]),
    ("section_all",     ["section"]),
    ("section_by_type", ["machine_type", "section"]),
    ("corner_by_dd",    ["dd", "rank_from_min"]),
    ("corner_by_weekday", ["day_of_week", "rank_from_min"]),
    ("corner_by_mmdd",  ["is_mm_dd", "rank_from_min"]),
    ("section_by_dd",   ["dd", "section"]),
    ("section_by_weekday", ["day_of_week", "section"]),
    ("section_by_mmdd", ["is_mm_dd", "section"]),
]


def build_output_frames(base_df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    plus_df = base_df.loc[base_df["is_hall_plus"].eq(1)].copy()
    frames: dict[str, pd.DataFrame] = {}
    for key, group_cols in _progress(
        _AGGREGATION_SPECS,
        desc="集計中",
        unit="table",
        leave=False,
    ):
        frames[key] = aggregate_metrics(plus_df, group_cols)
    return frames


def write_output_frames(frames: dict[str, pd.DataFrame], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for key, file_name in _progress(
        OUTPUT_FILES.items(),
        desc="CSV書き込み",
        unit="file",
        leave=False,
    ):
        frames[key].to_csv(output_dir / file_name, index=False, encoding="utf-8-sig")


def _print_table(df: pd.DataFrame, columns: list[str], top_n: int) -> None:
    if df.empty:
        print("(no rows)")
        return
    print(df.loc[:, columns].head(top_n).to_string(index=False))


def print_summary(frames: dict[str, pd.DataFrame]) -> None:
    print("=== みとや 角番・列 分析サマリー ===")
    print()

    print("[角番 TOP5（プラス日・全機種）]")
    _print_table(
        frames["corner_all"].sort_values("avg_diff", ascending=False),
        ["rank_from_min", "avg_diff", "plus_rate", "sample_n"],
        5,
    )
    print()

    print("[列 TOP5（プラス日・全機種）]")
    _print_table(
        frames["section_all"].sort_values("avg_diff", ascending=False),
        ["section", "avg_diff", "plus_rate", "sample_n"],
        5,
    )
    print()

    print("[曜日×角番 ハイライト]")
    _print_table(
        frames["corner_by_weekday"].sort_values("avg_diff", ascending=False),
        ["day_of_week", "rank_from_min", "avg_diff", "plus_rate", "sample_n"],
        3,
    )
    print()

    print("[DD×角番 ハイライト]")
    _print_table(
        frames["corner_by_dd"].sort_values("avg_diff", ascending=False),
        ["dd", "rank_from_min", "avg_diff", "plus_rate", "sample_n"],
        3,
    )
    print()

    print("[MM=DD日の角番傾向]")
    mmdd = frames["corner_by_mmdd"].loc[frames["corner_by_mmdd"]["is_mm_dd"].eq(1)]
    _print_table(
        mmdd.sort_values("avg_diff", ascending=False),
        ["is_mm_dd", "rank_from_min", "avg_diff", "plus_rate", "sample_n"],
        3,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze Mitoya corner-position and section setting patterns.")
    parser.add_argument("--db-path", default="", help="Explicit DB path override.")
    parser.add_argument("--db-dir", default="db", help="Directory used for DB auto-resolution.")
    parser.add_argument(
        "--output-dir",
        default="data/mitoya_corner_section_analysis",
        help="Directory for analysis CSV outputs.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)

    with _step_bar(total=4, desc="みとや 角番・列 分析", unit="step") as bar:
        bar.set_description("DB解決中")
        db_path = resolve_mitoya_db_path(args.db_path, db_dir=Path(args.db_dir))
        bar.update()

        bar.set_description("データ読み込み中")
        base_df = prepare_analysis_frame(load_analysis_frame(db_path))
        bar.update()

        bar.set_description("集計中")
        frames = build_output_frames(base_df)
        bar.update()

        bar.set_description("CSV書き込み中")
        write_output_frames(frames, Path(args.output_dir))
        bar.update()

    print_summary(frames)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
