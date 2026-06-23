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
    assign_period,
    load_data as base_load_data,
    quintile,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


DB_PATH = Path(__file__).resolve().parents[1] / "db" / "みとや大森町店.db"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "mitoya_current_q5_list"
MIN_GAMES = 1000
ACTIVE_DAYS = 30


def load_data(db_path: Path, min_games: int = MIN_GAMES) -> pd.DataFrame:
    df = base_load_data(db_path)
    df = df[df["games_normalized"] >= min_games].copy()
    return df


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
    period_anchor = pd.Series(pd.to_datetime([df["date"].min()] * len(agg)))
    agg["period"] = assign_period(period_anchor, WINDOW_MONTHS)
    agg["quintile"] = quintile(agg, "diff_sum")
    return agg


def build_current_q5_table(df_window: pd.DataFrame, max_date: pd.Timestamp) -> pd.DataFrame:
    overall = aggregate_machine_overall(df_window)
    if overall.empty:
        return pd.DataFrame(
            columns=[
                "machine_name",
                "quintile",
                "payout_rate",
                "diff_sum",
                "n_dates",
                "n_machines",
                "last_date",
                "active",
            ]
        )

    current = overall.copy()
    current["active"] = current["last_date"] >= (max_date - pd.Timedelta(days=ACTIVE_DAYS))

    qmax = current["quintile"].max()
    current = current[current["quintile"] == qmax].copy()
    current["last_date"] = current["last_date"].dt.strftime("%Y-%m-%d")
    return current[
        [
            "machine_name",
            "quintile",
            "payout_rate",
            "diff_sum",
            "n_dates",
            "n_machines",
            "last_date",
            "active",
        ]
    ].sort_values(["payout_rate", "diff_sum"], ascending=[False, False])


def build_checklist_markdown(
    q5_current: pd.DataFrame,
    *,
    window_start: pd.Timestamp,
    max_date: pd.Timestamp,
) -> str:
    lines = [
        "# みとや Q5機種名チェックリスト",
        f"算出窓: {window_start.date()} 〜 {max_date.date()}",
        "",
        "| 機種名 | 台数 | 機械割 | 最終登場 | active |",
        "|---|---:|---:|---|---|",
    ]
    for _, row in q5_current.iterrows():
        lines.append(
            f"| {row['machine_name']} | {int(row['n_machines'])} | "
            f"{row['payout_rate']:.2f}% | {row['last_date']} | "
            f"{'✓' if row['active'] else '×'} |"
        )

    inactive = q5_current[~q5_current["active"]]
    if not inactive.empty:
        lines.extend(["", "## 注意: 要確認（30日以上登場なし）"])
        for _, row in inactive.sort_values("last_date").iterrows():
            lines.append(f"- {row['machine_name']}（最終登場: {row['last_date']}）")

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
