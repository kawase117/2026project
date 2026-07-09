from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys
from pathlib import Path

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda.cross_hall_pattern_verification import (
    COINS_PER_GAME,
    WINDOW_MONTHS,
    assign_period,
    load_data as base_load_data,
    quintile,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


DB_PATH = Path(__file__).resolve().parents[1] / "db" / "みとや大森町店.db"
FLOOR_CSV = Path(__file__).resolve().parents[1] / "Heatmap" / "mitoya_omorimachi_floor_coordinates.csv"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "mitoya_xdds_screening"
MIN_GAMES = 400
MIN_GAMES_Q5 = 1000
X_DDS = {4, 7, 14, 17, 24, 27}


def load_floor_layout(floor_csv: Path) -> pd.DataFrame:
    df = pd.read_csv(floor_csv, encoding="utf-8-sig")
    return df[["machine_number", "section"]].drop_duplicates()


def compute_current_q5_machines(
    db_path: Path,
    min_games: int,
    window_months: int,
) -> set[str]:
    df = base_load_data(db_path)
    df = df[df["games_normalized"] >= min_games].copy()
    if df.empty:
        return set()

    max_date = df["date"].max()
    window_start = max_date - pd.DateOffset(months=window_months)
    df_window = df[df["date"] >= window_start].copy()
    if df_window.empty:
        return set()

    agg = df_window.groupby("machine_name", as_index=False).agg(
        diff_sum=("diff_coins_normalized", "sum"),
        games_sum=("games_normalized", "sum"),
    )
    if agg.empty:
        return set()
    period_anchor = pd.Series(pd.to_datetime([max_date] * len(agg)))
    agg["period"] = assign_period(period_anchor, window_months)
    agg["quintile"] = quintile(agg, "diff_sum")
    qmax = agg["quintile"].max()
    return set(agg.loc[agg["quintile"] == qmax, "machine_name"])


def compute_machine_xdds_perf(db_path: Path, min_games: int) -> pd.DataFrame:
    df = base_load_data(db_path)
    df = df[df["games_normalized"] >= min_games].copy()
    if df.empty:
        return pd.DataFrame(
            columns=[
                "machine_name",
                "xdds_payout",
                "norm_payout",
                "lift_machine",
                "n_xdds",
            ]
        )

    df["dd"] = df["date"].dt.day
    df["is_xdds"] = df["dd"].isin(X_DDS)
    df["payout"] = (
        (df["games_normalized"] * COINS_PER_GAME + df["diff_coins_normalized"])
        / (df["games_normalized"] * COINS_PER_GAME)
        * 100
    )

    xdds = (
        df[df["is_xdds"]]
        .groupby("machine_name", as_index=False)
        .agg(
            xdds_payout=("payout", "mean"),
            n_xdds=("date", "nunique"),
        )
    )
    norm = df[~df["is_xdds"]].groupby("machine_name", as_index=False).agg(norm_payout=("payout", "mean"))
    out = xdds.merge(norm, on="machine_name", how="outer")
    out["lift_machine"] = out["xdds_payout"] - out["norm_payout"]
    return out


def _load_latest_machine_names(db_path: Path) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        # Get the most recent machine_name per machine_number,
        # restricted to machines with at least 5 recorded dates.
        return pd.read_sql_query(
            """
            WITH counts AS (
                SELECT machine_number, MAX(date) AS max_date, COUNT(DISTINCT date) AS total_dates
                FROM machine_detailed_results
                GROUP BY machine_number
                HAVING total_dates >= 5
            )
            SELECT c.machine_number, mdr.machine_name
            FROM counts c
            JOIN machine_detailed_results mdr
                ON mdr.machine_number = c.machine_number AND mdr.date = c.max_date
            GROUP BY c.machine_number
            """,
            conn,
        )


def _build_machine_section_table(db_path: Path, floor_csv: Path) -> pd.DataFrame:
    layout = load_floor_layout(floor_csv)
    latest_machines = _load_latest_machine_names(db_path)
    if latest_machines.empty or layout.empty:
        return pd.DataFrame(columns=["machine_name", "section", "machine_range", "n_machines"])

    machine_section = latest_machines.merge(layout, on="machine_number", how="left")
    machine_section = machine_section.dropna(subset=["section"]).copy()
    if machine_section.empty:
        return pd.DataFrame(columns=["machine_name", "section", "machine_range", "n_machines"])

    main_section = machine_section.groupby(["machine_name", "section"], as_index=False).agg(
        n_machines=("machine_number", "count"),
        machine_range=("machine_number", lambda x: f"{int(x.min())}-{int(x.max())}"),
    )
    main_section = main_section.loc[main_section.groupby("machine_name")["n_machines"].idxmax()].copy()
    return main_section


def build_screening_table(db_path: Path, floor_csv: Path, target_dd: int) -> pd.DataFrame:
    q5_names = compute_current_q5_machines(db_path, MIN_GAMES_Q5, WINDOW_MONTHS)
    machine_perf = compute_machine_xdds_perf(db_path, MIN_GAMES)
    section_table = _build_machine_section_table(db_path, floor_csv)

    result = machine_perf.copy()
    if result.empty:
        result["is_q5"] = pd.Series(dtype=bool)
        result["is_xdds_day"] = pd.Series(dtype=bool)
        return result

    result["is_q5"] = result["machine_name"].isin(q5_names)
    result = result.merge(section_table, on="machine_name", how="left")
    section_stats = (
        result.dropna(subset=["section"])
        .groupby("section", as_index=False)
        .agg(section_xdds_mean=("xdds_payout", "mean"))
        .sort_values(["section_xdds_mean", "section"], ascending=[False, True], kind="mergesort")
        .reset_index(drop=True)
    )
    section_stats["section_rank"] = range(1, len(section_stats) + 1)
    result = result.merge(section_stats, on="section", how="left")
    result["is_xdds_day"] = target_dd in X_DDS
    lift = result["lift_machine"].fillna(0)
    # Q5 bonus is suppressed when X_DDS lift is negative (machine underperforms on event days)
    q5_bonus = result["is_q5"].astype(int) * (lift > 0).astype(int) * 100
    result["score"] = q5_bonus + (11 - result["section_rank"].fillna(10)) * 5 + lift
    return result.sort_values("score", ascending=False).reset_index(drop=True)


def build_report(table: pd.DataFrame, target_date: dt.date) -> str:
    target_dd = target_date.day
    is_xdds_day = target_dd in X_DDS

    lines = [
        "# みとや X_DDS スクリーニング",
        "",
        f"実行日: {target_date}  DD={target_dd}  X_DDS日: {str(is_xdds_day)}",
        "",
        "## 推奨台 TOP10 (Q5 × Section × X_DDS lift)",
    ]

    def _fmt_num(value: object, digits: int = 2) -> str:
        if value is None:
            return ""
        if isinstance(value, str) and value.lower() == "nan":
            return ""
        if pd.isna(value):
            return ""
        return f"{float(value):.{digits}f}"

    def _fmt_text(value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, str) and value.lower() == "nan":
            return ""
        if pd.isna(value):
            return ""
        return str(value)

    top10 = table.head(10).copy()
    if top10.empty:
        lines.append("該当なし")
    else:
        lines.extend(
            [
                "| rank | 機種名 | 台番 | section | sec_rank | xdds% | lift | Q5 | score |",
                "|------|--------|------|---------|----------|-------|------|----|-------|",
            ]
        )
        for idx, row in enumerate(top10.itertuples(index=False), start=1):
            lines.append(
                f"| {idx} | {row.machine_name} | {_fmt_text(getattr(row, 'machine_range', ''))} | "
                f"{_fmt_text(getattr(row, 'section', ''))} | {'' if pd.isna(getattr(row, 'section_rank', None)) else int(row.section_rank)} | "
                f"{_fmt_num(getattr(row, 'xdds_payout', None))} | "
                f"{_fmt_num(getattr(row, 'lift_machine', None))} | "
                f"{'✓' if bool(row.is_q5) else '×'} | {row.score:.2f} |"
            )

    lines.extend(["", "## Q5機種一覧（直近3ヶ月）"])
    q5_table = table[table["is_q5"]].copy()
    if q5_table.empty:
        lines.append("該当なし")
    else:
        lines.extend(["| 機種名 | section | 台番 | score |", "|---|---|---|---:|"])
        for _, row in q5_table.iterrows():
            lines.append(
                f"| {row['machine_name']} | {_fmt_text(row.get('section', ''))} | "
                f"{_fmt_text(row.get('machine_range', ''))} | {row['score']:.2f} |"
            )

    # Auxiliary list: high X_DDS lift but section unknown
    no_section_lift = table[table["section"].isna() & (table["lift_machine"].fillna(0) > 5)].copy()
    if not no_section_lift.empty:
        lines.extend(
            [
                "",
                "## 補助リスト: section不明・X_DDS lift >5（台番要現地確認）",
                "| 機種名 | xdds% | lift | Q5 |",
                "|---|---:|---:|---|",
            ]
        )
        for _, row in no_section_lift.iterrows():
            lines.append(
                f"| {row['machine_name']} | {_fmt_num(row.get('xdds_payout'))} | "
                f"{_fmt_num(row.get('lift_machine'))} | {'✓' if bool(row['is_q5']) else '×'} |"
            )

    return "\n".join(lines) + "\n"


def save_outputs(table: pd.DataFrame, report: str, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    table.to_csv(output_dir / "screening.csv", index=False, encoding="utf-8-sig")
    table.head(10).to_csv(output_dir / "top10.csv", index=False, encoding="utf-8-sig")
    (output_dir / "report.md").write_text(report, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", type=Path, default=DB_PATH)
    parser.add_argument("--floor-csv", type=Path, default=FLOOR_CSV)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--target-dd", type=int, default=dt.date.today().day)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    table = build_screening_table(args.db_path, args.floor_csv, args.target_dd)
    report = build_report(table, dt.date.today())
    save_outputs(table, report, args.output_dir)
    print(f"saved outputs to {args.output_dir}")


if __name__ == "__main__":
    main()
