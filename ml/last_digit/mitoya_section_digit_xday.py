from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from ml.last_digit.utils import resolve_db_path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


AT_ISLAND = "AT島"
JUGGLER_ISLAND = "ジャグラー島"
VARIETY_ISLAND = "バラエティ島"
UNKNOWN_ISLAND = "unknown"

ISLAND_ORDER = {
    AT_ISLAND: 0,
    JUGGLER_ISLAND: 1,
    VARIETY_ISLAND: 2,
    UNKNOWN_ISLAND: 99,
}

PERIOD_ORDER = {
    "旧店長2025": 0,
    "旧店長2026前半": 1,
    "新店長2026/5-": 2,
    "unknown": 99,
}

MIN_XDAY_RECORDS = 5


def assign_island(machine_number: int) -> str:
    number = int(machine_number)
    if 501 <= number <= 640:
        return AT_ISLAND
    if 641 <= number <= 691:
        return JUGGLER_ISLAND
    if 692 <= number <= 755:
        return VARIETY_ISLAND
    return UNKNOWN_ISLAND


def is_x_day(value: object) -> bool:
    if isinstance(value, (int, float)) and not pd.isna(value):
        day = int(value)
    else:
        ts = pd.to_datetime(value, errors="coerce")
        if pd.isna(ts):
            return False
        day = int(ts.day)
    return day % 10 in {4, 7}


def assign_period(value: object) -> str:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return "unknown"
    if int(ts.year) == 2025:
        return "旧店長2025"
    if int(ts.year) == 2026 and 1 <= int(ts.month) <= 4:
        return "旧店長2026前半"
    if int(ts.year) == 2026 and int(ts.month) >= 5:
        return "新店長2026/5-"
    return "unknown"


def _fallback_section(machine_number: int) -> str:
    return f"{int(machine_number)}-{int(machine_number)}"


def _table_exists(con: sqlite3.Connection, table_name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def load_section_digit_rows(db_path: Path) -> pd.DataFrame:
    with sqlite3.connect(str(db_path)) as con:
        has_layout = _table_exists(con, "machine_layout")
        base_query = """
            SELECT
              m.date,
              m.machine_number,
              m.last_digit,
              m.diff_coins_normalized,
              m.games_normalized
            FROM machine_detailed_results m
        """
        if has_layout:
            base_query = """
                SELECT
                  m.date,
                  m.machine_number,
                  m.last_digit,
                  m.diff_coins_normalized,
                  m.games_normalized,
                  COALESCE(ml.section, '') AS section
                FROM machine_detailed_results m
                LEFT JOIN machine_layout ml
                  ON m.machine_number = ml.machine_number
            """
        df = pd.read_sql_query(base_query, con)

    if df.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "machine_number",
                "last_digit",
                "diff_coins_normalized",
                "games_normalized",
                "section",
                "island",
                "x_day",
                "period",
            ]
        )

    work = df.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.normalize()
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["last_digit"] = work["last_digit"].astype(str).str.strip()
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    work = work.dropna(subset=["date", "machine_number", "last_digit", "diff_coins_normalized", "games_normalized"]).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work = work[work["games_normalized"] >= 100].copy()
    work = work[work["last_digit"].str.fullmatch(r"[0-9]")].copy()
    if "section" not in work.columns:
        work["section"] = ""
    work["section"] = work["section"].fillna("").astype(str).str.strip()
    work.loc[work["section"].eq("") | work["section"].eq("unknown"), "section"] = (
        work.loc[work["section"].eq("") | work["section"].eq("unknown"), "machine_number"].map(_fallback_section)
    )
    work["island"] = work["machine_number"].map(assign_island)
    work = work[work["island"].ne(UNKNOWN_ISLAND)].copy()
    work["x_day"] = work["date"].map(is_x_day)
    work["period"] = work["date"].map(assign_period)
    return work.reset_index(drop=True)


def build_section_digit_xday_tables(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if raw.empty:
        allperiod_cols = [
            "island",
            "section",
            "last_digit",
            "xday_mean",
            "global_mean",
            "deviation",
            "n_xday_records",
            "n_global_records",
        ]
        byperiod_cols = [
            "island",
            "section",
            "last_digit",
            "period",
            "xday_mean",
            "period_mean",
            "deviation",
            "global_mean",
            "deviation_vs_global",
            "n_xday_records",
            "n_period_records",
        ]
        return pd.DataFrame(columns=allperiod_cols), pd.DataFrame(columns=byperiod_cols)

    work = raw.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.normalize()
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["last_digit"] = work["last_digit"].astype(str).str.strip()
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    if "section" not in work.columns:
        work["section"] = ""
    work["section"] = work["section"].fillna("").astype(str).str.strip()
    work = work.dropna(subset=["date", "machine_number", "last_digit", "diff_coins_normalized", "games_normalized"]).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work = work[work["games_normalized"] >= 100].copy()
    work = work[work["last_digit"].str.fullmatch(r"[0-9]")].copy()
    work.loc[work["section"].eq("") | work["section"].eq("unknown"), "section"] = (
    work.loc[work["section"].eq("") | work["section"].eq("unknown"), "machine_number"].map(_fallback_section)
    )
    work["island"] = work["machine_number"].map(assign_island)
    work = work[work["island"].ne(UNKNOWN_ISLAND)].copy()
    work["x_day"] = work["date"].map(is_x_day)
    work["period"] = work["date"].map(assign_period)

    group_cols = ["island", "section", "last_digit"]
    global_stats = (
        work.groupby(group_cols, sort=True)
        .agg(
            global_mean=("diff_coins_normalized", "mean"),
            n_global_records=("diff_coins_normalized", "size"),
        )
        .reset_index()
    )

    xday_stats = (
        work.loc[work["x_day"]]
        .groupby(group_cols, sort=True)
        .agg(
            xday_mean=("diff_coins_normalized", "mean"),
            n_xday_records=("diff_coins_normalized", "size"),
        )
        .reset_index()
    )

    allperiod = global_stats.merge(xday_stats, on=group_cols, how="inner")
    allperiod = allperiod[allperiod["n_xday_records"] >= MIN_XDAY_RECORDS].copy()
    allperiod["deviation"] = allperiod["xday_mean"] - allperiod["global_mean"]
    allperiod["island_order"] = allperiod["island"].map(ISLAND_ORDER).fillna(999).astype(int)
    allperiod["digit_order"] = pd.to_numeric(allperiod["last_digit"], errors="coerce").fillna(999).astype(int)
    allperiod = allperiod.sort_values(["island_order", "section", "digit_order"]).drop(
        columns=["island_order", "digit_order"]
    )
    allperiod = allperiod.reindex(
        columns=[
            "island",
            "section",
            "last_digit",
            "xday_mean",
            "global_mean",
            "deviation",
            "n_xday_records",
            "n_global_records",
        ]
    ).reset_index(drop=True)

    period_stats = (
        work.groupby(group_cols + ["period"], sort=True)
        .agg(
            period_mean=("diff_coins_normalized", "mean"),
            n_period_records=("diff_coins_normalized", "size"),
        )
        .reset_index()
    )
    period_xday_stats = (
        work.loc[work["x_day"]]
        .groupby(group_cols + ["period"], sort=True)
        .agg(
            xday_mean=("diff_coins_normalized", "mean"),
            n_xday_records=("diff_coins_normalized", "size"),
        )
        .reset_index()
    )

    byperiod = period_stats.merge(period_xday_stats, on=group_cols + ["period"], how="inner")
    byperiod = byperiod[byperiod["n_xday_records"] >= MIN_XDAY_RECORDS].copy()
    byperiod = byperiod.merge(global_stats[group_cols + ["global_mean"]], on=group_cols, how="left")
    byperiod["deviation"] = byperiod["xday_mean"] - byperiod["period_mean"]
    byperiod["deviation_vs_global"] = byperiod["xday_mean"] - byperiod["global_mean"]
    byperiod["island_order"] = byperiod["island"].map(ISLAND_ORDER).fillna(999).astype(int)
    byperiod["period_order"] = byperiod["period"].map(PERIOD_ORDER).fillna(999).astype(int)
    byperiod["digit_order"] = pd.to_numeric(byperiod["last_digit"], errors="coerce").fillna(999).astype(int)
    byperiod = byperiod.sort_values(["island_order", "period_order", "section", "digit_order"]).drop(
        columns=["island_order", "period_order", "digit_order"]
    )
    byperiod = byperiod.reindex(
        columns=[
            "island",
            "section",
            "last_digit",
            "period",
            "xday_mean",
            "period_mean",
            "deviation",
            "global_mean",
            "deviation_vs_global",
            "n_xday_records",
            "n_period_records",
        ]
    ).reset_index(drop=True)
    return allperiod, byperiod


def _print_section_report(allperiod: pd.DataFrame, byperiod: pd.DataFrame) -> None:
    if allperiod.empty:
        print("No qualifying rows.")
        return

    for island in [AT_ISLAND, JUGGLER_ISLAND, VARIETY_ISLAND, UNKNOWN_ISLAND]:
        island_df = allperiod.loc[allperiod["island"].eq(island)].copy()
        if island_df.empty:
            continue
        print(f"\n## {island}")
        top5 = island_df.sort_values(["deviation", "section", "last_digit"], ascending=[False, True, True]).head(5)
        bottom5 = island_df.sort_values(["deviation", "section", "last_digit"], ascending=[True, True, True]).head(5)
        print("Top 5 deviation")
        print(top5.to_string(index=False))
        print("Bottom 5 deviation")
        print(bottom5.to_string(index=False))

        print("Period comparison")
        island_period = byperiod.loc[byperiod["island"].eq(island)].copy()
        if island_period.empty:
            print("  (no period rows)")
            continue
        for period in ["旧店長2025", "旧店長2026前半", "新店長2026/5-"]:
            period_df = island_period.loc[island_period["period"].eq(period)].copy()
            if period_df.empty:
                continue
            best = period_df.sort_values(["deviation", "section", "last_digit"], ascending=[False, True, True]).head(5)
            print(f"  [{period}]")
            print(best.to_string(index=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cross-tab Mitoya section, last digit, and x_day raw payout structure.")
    parser.add_argument("--db-path", default="", help="DB path override. Empty uses resolve_db_path.")
    parser.add_argument("--db-glob", default="みとや大森町店.db", help="DB auto-detect glob pattern used when --db-path is empty")
    parser.add_argument("--output-dir", default="results", help="Directory for CSV outputs")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db_path = resolve_db_path(str(args.db_path), pattern=str(args.db_glob))
    raw = load_section_digit_rows(db_path)
    allperiod, byperiod = build_section_digit_xday_tables(raw)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    allperiod_path = out_dir / "mitoya_section_digit_xday_allperiod.csv"
    byperiod_path = out_dir / "mitoya_section_digit_xday_byperiod.csv"
    allperiod.to_csv(allperiod_path, index=False, encoding="utf-8-sig")
    byperiod.to_csv(byperiod_path, index=False, encoding="utf-8-sig")
    print(allperiod_path)
    print(byperiod_path)
    _print_section_report(allperiod, byperiod)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
