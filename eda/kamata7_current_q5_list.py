from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda.cross_hall_pattern_verification import (
    COINS_PER_GAME,
    WINDOW_MONTHS,
    load_data as base_load_data,
)
from eda.kamata7_machinename_q5_backtest import (
    assign_period,
    quintile,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


DB_PATH = Path(__file__).resolve().parents[1] / "db" / "マルハンメガシティ2000-蒲田7.db"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "kamata7_current_q5_list"
MIN_GAMES = 1000
ACTIVE_DAYS = 30


def load_data(db_path: Path, min_games: int = MIN_GAMES) -> pd.DataFrame:
    df = base_load_data(db_path)
    df = df[df["games_normalized"] >= min_games].copy()
    df["floor"] = df["machine_number"].apply(lambda x: "2F" if x < 3000 else "3F")
    return df


def aggregate_machine_floor(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=[
                "machine_name",
                "floor",
                "diff_sum",
                "games_sum",
                "payout_rate",
                "n_dates",
                "n_machines",
                "last_date",
            ]
        )

    agg = (
        df.groupby(["machine_name", "floor"], as_index=False)
        .agg(
            diff_sum=("diff_coins_normalized", "sum"),
            games_sum=("games_normalized", "sum"),
            n_dates=("date", "nunique"),
            n_machines=("machine_number", "nunique"),
            last_date=("date", "max"),
        )
    )
    agg["payout_rate"] = (
        (agg["games_sum"] * COINS_PER_GAME + agg["diff_sum"])
        / (agg["games_sum"] * COINS_PER_GAME)
        * 100
    )
    return agg


def aggregate_machine_overall(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=[
                "machine_name",
                "period",
                "diff_sum",
                "games_sum",
                "payout_rate",
                "n_dates",
                "n_machines",
                "last_date",
                "quintile",
            ]
        )

    agg = (
        df.groupby("machine_name", as_index=False)
        .agg(
            diff_sum=("diff_coins_normalized", "sum"),
            games_sum=("games_normalized", "sum"),
            n_dates=("date", "nunique"),
            n_machines=("machine_number", "nunique"),
            last_date=("date", "max"),
        )
    )
    agg["payout_rate"] = (
        (agg["games_sum"] * COINS_PER_GAME + agg["diff_sum"])
        / (agg["games_sum"] * COINS_PER_GAME)
        * 100
    )
    # Reuse shared backtest logic by treating the current snapshot as a single synthetic period.
    period_anchor = pd.Series(pd.to_datetime([df["date"].min()] * len(agg)))
    agg["period"] = assign_period(period_anchor, WINDOW_MONTHS)
    agg["quintile"] = quintile(agg, "diff_sum")
    return agg


def determine_floor_main(diff_2f: float, diff_3f: float) -> str:
    total = diff_2f + diff_3f
    if total == 0:
        if diff_2f == diff_3f:
            return "両方"
        return "2F" if diff_2f > diff_3f else "3F"
    share_2f = diff_2f / total
    if 0.4 <= share_2f <= 0.6:
        return "両方"
    return "2F" if diff_2f > diff_3f else "3F"


def build_current_q5_table(df_window: pd.DataFrame, max_date: pd.Timestamp) -> pd.DataFrame:
    overall = aggregate_machine_overall(df_window)
    by_floor = aggregate_machine_floor(df_window)

    floor_pivot = (
        by_floor.pivot(index="machine_name", columns="floor")
        .reindex(columns=["2F", "3F"], level=1, fill_value=0)
    )
    if floor_pivot.empty:
        floor_stats = pd.DataFrame(
            columns=[
                "machine_name",
                "diff_sum_2F",
                "diff_sum_3F",
                "n_machines_2F",
                "n_machines_3F",
            ]
        )
    else:
        floor_stats = floor_pivot.copy()
        floor_stats.columns = [f"{metric}_{floor}" for metric, floor in floor_stats.columns]
        floor_stats = floor_stats.reset_index()
        for col in ["diff_sum_2F", "diff_sum_3F", "n_machines_2F", "n_machines_3F"]:
            if col not in floor_stats.columns:
                floor_stats[col] = 0

    current = overall.merge(floor_stats, on="machine_name", how="left")
    for col in ["diff_sum_2F", "diff_sum_3F", "n_machines_2F", "n_machines_3F"]:
        current[col] = current[col].fillna(0)
    current["floor_main"] = current.apply(
        lambda row: determine_floor_main(row["diff_sum_2F"], row["diff_sum_3F"]),
        axis=1,
    )
    current["active"] = current["last_date"] >= (max_date - pd.Timedelta(days=ACTIVE_DAYS))

    qmax = current["quintile"].max()
    current = current[current["quintile"] == qmax].copy()
    current["n_machines_2F"] = current["n_machines_2F"].astype(int)
    current["n_machines_3F"] = current["n_machines_3F"].astype(int)
    current["last_date"] = current["last_date"].dt.strftime("%Y-%m-%d")
    return current[
        [
            "machine_name",
            "quintile",
            "floor_main",
            "payout_rate",
            "diff_sum",
            "n_dates",
            "n_machines_2F",
            "n_machines_3F",
            "last_date",
            "active",
        ]
    ].sort_values(["floor_main", "payout_rate", "diff_sum"], ascending=[True, False, False])


def build_checklist_markdown(
    q5_current: pd.DataFrame,
    *,
    window_start: pd.Timestamp,
    max_date: pd.Timestamp,
) -> str:
    lines = [
        "# 蒲田7 Q5機種名チェックリスト",
        f"算出窓: {window_start.date()} 〜 {max_date.date()}",
        "",
        "## 2F（優先度高: backtestでexcess +129）",
    ]

    def _section_rows(floor: str) -> list[str]:
        if floor == "2F":
            section = q5_current[q5_current["floor_main"].isin(["2F", "両方"])].copy()
            count_col = "n_machines_2F"
        else:
            section = q5_current[q5_current["floor_main"].isin(["3F", "両方"])].copy()
            count_col = "n_machines_3F"
        section = section.sort_values(["payout_rate", "diff_sum"], ascending=[False, False])
        if section.empty:
            return ["該当なし"]
        rows = [
            "| 機種名 | 台数 | 機械割 | 最終登場 |",
            "|---|---:|---:|---|",
        ]
        for _, row in section.iterrows():
            rows.append(
                f"| {row['machine_name']} | {int(row[count_col])} | "
                f"{row['payout_rate']:.2f}% | {row['last_date']} |"
            )
        return rows

    lines.extend(_section_rows("2F"))
    lines.extend(["", "## 3F"])
    lines.extend(_section_rows("3F"))

    inactive = q5_current[~q5_current["active"]].copy().sort_values("last_date")
    lines.extend(["", "## 注意: 要確認（30日以上登場なし）"])
    if inactive.empty:
        lines.append("該当なし")
    else:
        for _, row in inactive.iterrows():
            lines.append(f"- {row['machine_name']}（最終登場: {row['last_date']} / floor_main: {row['floor_main']}）")

    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", type=Path, default=DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--min-games", type=int, default=MIN_GAMES)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    df = load_data(args.db_path, min_games=args.min_games)
    max_date = df["date"].max()
    window_start = max_date - pd.DateOffset(months=WINDOW_MONTHS)
    df_window = df[df["date"] >= window_start].copy()

    q5_current = build_current_q5_table(df_window, max_date)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    q5_current.to_csv(args.output_dir / "q5_current.csv", index=False, encoding="utf-8-sig")
    checklist = build_checklist_markdown(q5_current, window_start=window_start, max_date=max_date)
    (args.output_dir / "checklist.md").write_text(checklist, encoding="utf-8")

    print(f"saved outputs to {args.output_dir}")
    print(f"source_latest_date={max_date.date()}")
    print(f"window_start={window_start.date()}")
    print(f"q5_count={len(q5_current)}")


if __name__ == "__main__":
    main()
