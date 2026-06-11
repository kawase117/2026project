from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

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

DD_GROUP_ORDER = {
    "4-group": 0,
    "7-group": 1,
    "unknown": 99,
}

MIN_CELL_RECORDS = 3
MIN_RANKING_RECORDS = 5


def assign_island(machine_number: int) -> str:
    number = int(machine_number)
    if 501 <= number <= 640:
        return AT_ISLAND
    if 641 <= number <= 691:
        return JUGGLER_ISLAND
    if 692 <= number <= 755:
        return VARIETY_ISLAND
    return UNKNOWN_ISLAND


def extract_dd(value: object) -> int | None:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    return int(ts.day)


def is_x_day(value: object) -> bool:
    dd = extract_dd(value)
    return dd is not None and dd % 10 in {4, 7}


def dd_group_for_date(value: object) -> str:
    dd = extract_dd(value)
    if dd is None:
        return "unknown"
    if dd in {4, 14, 24}:
        return "4-group"
    if dd in {7, 17, 27}:
        return "7-group"
    return "unknown"


def _table_exists(con: sqlite3.Connection, table_name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _fallback_section(machine_number: int) -> str:
    number = int(machine_number)
    if 501 <= number <= 640:
        return "501-640"
    if 641 <= number <= 691:
        return "641-691"
    if 692 <= number <= 755:
        return "692-755"
    return f"{number}-{number}"


def _prepare_base_rows(raw: pd.DataFrame) -> pd.DataFrame:
    work = raw.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.normalize()
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["last_digit"] = work["last_digit"].astype(str).str.strip()
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    work = work.dropna(subset=["date", "machine_number", "last_digit", "diff_coins_normalized", "games_normalized"]).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work = work[work["games_normalized"] >= 100].copy()
    work = work[work["last_digit"].str.fullmatch(r"[0-9]")].copy()
    work["last_digit"] = work["last_digit"].astype(str)
    work["island"] = work["machine_number"].map(assign_island)
    work = work[work["island"].ne(UNKNOWN_ISLAND)].copy()
    work["dd"] = work["date"].dt.day.astype(int)
    work["dd_group"] = work["date"].map(dd_group_for_date)
    work["x_day"] = work["date"].map(is_x_day)
    if "section" not in work.columns:
        work["section"] = ""
    work["section"] = work["section"].fillna("").astype(str).str.strip()
    work.loc[work["section"].eq("") | work["section"].eq("unknown"), "section"] = (
        work.loc[work["section"].eq("") | work["section"].eq("unknown"), "machine_number"].map(_fallback_section)
    )
    return work.reset_index(drop=True)


def load_dd_section_digit_rows(db_path: Path) -> pd.DataFrame:
    with sqlite3.connect(str(db_path)) as con:
        has_layout = _table_exists(con, "machine_layout")
        if has_layout:
            df = pd.read_sql_query(
                """
                SELECT
                  m.date,
                  m.machine_number,
                  m.last_digit,
                  m.diff_coins_normalized,
                  m.games_normalized,
                  COALESCE(NULLIF(TRIM(ml.section), ''), '') AS section,
                  ml.section_min AS section_min,
                  ml.section_max AS section_max
                FROM machine_detailed_results m
                LEFT JOIN machine_layout ml
                  ON m.machine_number = ml.machine_number
                """,
                con,
            )
        else:
            df = pd.read_sql_query(
                """
                SELECT
                  m.date,
                  m.machine_number,
                  m.last_digit,
                  m.diff_coins_normalized,
                  m.games_normalized,
                  '' AS section,
                  NULL AS section_min,
                  NULL AS section_max
                FROM machine_detailed_results m
                """,
                con,
            )
    return _prepare_base_rows(df)


def _apply_section_fallback(work: pd.DataFrame) -> pd.DataFrame:
    out = work.copy()
    has_layout_bounds = {"section_min", "section_max"}.issubset(out.columns)
    if has_layout_bounds:
        bounds = out["section_min"].notna() & out["section_max"].notna()
        section_from_layout = (
            out.loc[bounds, "section_min"].astype(int).astype(str)
            + "-"
            + out.loc[bounds, "section_max"].astype(int).astype(str)
        )
        out.loc[bounds & (out["section"].eq("") | out["section"].eq("unknown")), "section"] = section_from_layout
    out.loc[out["section"].eq("") | out["section"].eq("unknown"), "section"] = (
        out.loc[out["section"].eq("") | out["section"].eq("unknown"), "machine_number"].map(_fallback_section)
    )
    return out


def build_dd_section_digit_detail(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(
            columns=[
                "island",
                "section",
                "last_digit",
                "dd",
                "dd_mean",
                "global_mean",
                "deviation_dd",
                "n_records",
            ]
        )

    work = _prepare_base_rows(raw)
    work = _apply_section_fallback(work)
    if work.empty:
        return pd.DataFrame(
            columns=[
                "island",
                "section",
                "last_digit",
                "dd",
                "dd_mean",
                "global_mean",
                "deviation_dd",
                "n_records",
            ]
        )

    group_cols = ["island", "section", "last_digit"]
    global_stats = (
        work.groupby(group_cols, sort=True)
        .agg(
            global_mean=("diff_coins_normalized", "mean"),
            n_global_records=("diff_coins_normalized", "size"),
        )
        .reset_index()
    )
    dd_stats = (
        work.groupby(group_cols + ["dd"], sort=True)
        .agg(
            dd_mean=("diff_coins_normalized", "mean"),
            n_records=("diff_coins_normalized", "size"),
        )
        .reset_index()
    )

    detail = dd_stats.merge(global_stats, on=group_cols, how="inner")
    detail = detail[detail["n_records"] >= MIN_CELL_RECORDS].copy()
    detail["deviation_dd"] = detail["dd_mean"] - detail["global_mean"]
    detail["island_order"] = detail["island"].map(ISLAND_ORDER).fillna(999).astype(int)
    detail["section_order"] = detail["section"].astype(str)
    detail["digit_order"] = pd.to_numeric(detail["last_digit"], errors="coerce").fillna(999).astype(int)
    detail = detail.sort_values(
        ["island_order", "section_order", "digit_order", "dd"],
        ascending=[True, True, True, True],
    ).drop(columns=["island_order", "section_order", "digit_order"])
    detail = detail.reindex(
        columns=[
            "island",
            "section",
            "last_digit",
            "dd",
            "dd_mean",
            "global_mean",
            "deviation_dd",
            "n_records",
        ]
    ).reset_index(drop=True)
    return detail


def build_dd_section_digit_group(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(
            columns=[
                "island",
                "section",
                "last_digit",
                "dd_group",
                "group_mean",
                "global_mean",
                "deviation_group",
                "n_records",
            ]
        )

    work = _prepare_base_rows(raw)
    work = _apply_section_fallback(work)
    if work.empty:
        return pd.DataFrame(
            columns=[
                "island",
                "section",
                "last_digit",
                "dd_group",
                "group_mean",
                "global_mean",
                "deviation_group",
                "n_records",
            ]
        )

    group_cols = ["island", "section", "last_digit"]
    global_stats = (
        work.groupby(group_cols, sort=True)
        .agg(global_mean=("diff_coins_normalized", "mean"))
        .reset_index()
    )
    group_stats = (
        work.loc[work["dd_group"].isin(["4-group", "7-group"])]
        .groupby(group_cols + ["dd_group"], sort=True)
        .agg(
            group_mean=("diff_coins_normalized", "mean"),
            n_records=("diff_coins_normalized", "size"),
        )
        .reset_index()
    )

    group_df = group_stats.merge(global_stats, on=group_cols, how="inner")
    group_df = group_df[group_df["n_records"] >= MIN_CELL_RECORDS].copy()
    group_df["deviation_group"] = group_df["group_mean"] - group_df["global_mean"]
    group_df["island_order"] = group_df["island"].map(ISLAND_ORDER).fillna(999).astype(int)
    group_df["section_order"] = group_df["section"].astype(str)
    group_df["digit_order"] = pd.to_numeric(group_df["last_digit"], errors="coerce").fillna(999).astype(int)
    group_df["dd_group_order"] = group_df["dd_group"].map(DD_GROUP_ORDER).fillna(999).astype(int)
    group_df = group_df.sort_values(
        ["island_order", "section_order", "digit_order", "dd_group_order"],
        ascending=[True, True, True, True],
    ).drop(columns=["island_order", "section_order", "digit_order", "dd_group_order"])
    group_df = group_df.reindex(
        columns=[
            "island",
            "section",
            "last_digit",
            "dd_group",
            "group_mean",
            "global_mean",
            "deviation_group",
            "n_records",
        ]
    ).reset_index(drop=True)
    return group_df


def build_dd_section_digit_ranking(detail: pd.DataFrame) -> pd.DataFrame:
    if detail.empty:
        return pd.DataFrame(
            columns=[
                "island",
                "section",
                "last_digit",
                "best_dd",
                "best_deviation",
                "worst_dd",
                "worst_deviation",
                "dd_spread",
            ]
        )

    work = detail.copy()
    work["n_records"] = pd.to_numeric(work["n_records"], errors="coerce")
    work["deviation_dd"] = pd.to_numeric(work["deviation_dd"], errors="coerce")
    work["dd"] = pd.to_numeric(work["dd"], errors="coerce")
    work = work[work["n_records"] >= MIN_RANKING_RECORDS].copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "island",
                "section",
                "last_digit",
                "best_dd",
                "best_deviation",
                "worst_dd",
                "worst_deviation",
                "dd_spread",
            ]
        )

    summary_rows: list[dict[str, object]] = []
    for (island, section, last_digit), grp in work.groupby(["island", "section", "last_digit"], sort=True):
        ordered = grp.sort_values(["deviation_dd", "dd"], ascending=[False, True]).reset_index(drop=True)
        best_row = ordered.iloc[0]
        worst_row = ordered.iloc[-1]
        best_deviation = float(best_row["deviation_dd"])
        worst_deviation = float(worst_row["deviation_dd"])
        summary_rows.append(
            {
                "island": island,
                "section": section,
                "last_digit": last_digit,
                "best_dd": int(best_row["dd"]),
                "best_deviation": best_deviation,
                "worst_dd": int(worst_row["dd"]),
                "worst_deviation": worst_deviation,
                "dd_spread": best_deviation - worst_deviation,
            }
        )

    ranking = pd.DataFrame(summary_rows)
    ranking["island_order"] = ranking["island"].map(ISLAND_ORDER).fillna(999).astype(int)
    ranking["digit_order"] = pd.to_numeric(ranking["last_digit"], errors="coerce").fillna(999).astype(int)
    ranking = ranking.sort_values(
        ["dd_spread", "island_order", "section", "digit_order", "best_dd"],
        ascending=[False, True, True, True, True],
    ).drop(columns=["island_order", "digit_order"])
    ranking = ranking.reindex(
        columns=[
            "island",
            "section",
            "last_digit",
            "best_dd",
            "best_deviation",
            "worst_dd",
            "worst_deviation",
            "dd_spread",
        ]
    ).reset_index(drop=True)
    return ranking


def build_dd_section_digit_tables(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    detail = build_dd_section_digit_detail(raw)
    group = build_dd_section_digit_group(raw)
    ranking = build_dd_section_digit_ranking(detail)
    return detail, group, ranking


def _print_focus_tables(detail: pd.DataFrame) -> None:
    focus_targets = [
        (AT_ISLAND, "574-590", "2"),
        (AT_ISLAND, "501-522", "2"),
        (JUGGLER_ISLAND, "675-691", "7"),
        (JUGGLER_ISLAND, "658-674", "7"),
        (VARIETY_ISLAND, "723-733", "7"),
    ]
    for island, section, digit in focus_targets:
        print(f"\n## {island} / {section} / 末尾{digit}")
        subset = detail.loc[
            detail["island"].eq(island)
            & detail["section"].eq(section)
            & detail["last_digit"].eq(digit)
        ].copy()
        if subset.empty:
            print("No qualifying rows.")
            continue
        print(
            subset.sort_values("dd")
            .to_string(
                index=False,
                columns=["dd", "dd_mean", "global_mean", "deviation_dd", "n_records"],
            )
        )


def _print_ranking_summary(ranking: pd.DataFrame) -> None:
    if ranking.empty:
        print("\nNo ranking rows.")
        return
    print("\n## dd_spread Top10")
    print(
        ranking.head(10).to_string(
            index=False,
            columns=[
                "island",
                "section",
                "last_digit",
                "best_dd",
                "best_deviation",
                "worst_dd",
                "worst_deviation",
                "dd_spread",
            ],
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mitoya DD x section x last digit cross analysis.")
    parser.add_argument("--db-path", default="", help="DB path override. Empty uses resolve_db_path.")
    parser.add_argument("--db-glob", default="みとや大森町店.db", help="DB auto-detect glob pattern used when --db-path is empty")
    parser.add_argument("--output-dir", default="results", help="Directory for CSV outputs")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db_path = resolve_db_path(str(args.db_path), pattern=str(args.db_glob))
    raw = load_dd_section_digit_rows(db_path)
    detail, group, ranking = build_dd_section_digit_tables(raw)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    detail_path = out_dir / "mitoya_dd_section_digit_detail.csv"
    group_path = out_dir / "mitoya_dd_section_digit_group.csv"
    ranking_path = out_dir / "mitoya_dd_section_digit_ranking.csv"
    detail.to_csv(detail_path, index=False, encoding="utf-8-sig")
    group.to_csv(group_path, index=False, encoding="utf-8-sig")
    ranking.to_csv(ranking_path, index=False, encoding="utf-8-sig")

    print(detail_path)
    print(group_path)
    print(ranking_path)
    _print_focus_tables(detail)
    _print_ranking_summary(ranking)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
