from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda.cross_hall_pattern_verification import (
    WINDOW_MONTHS,
    load_data as base_load_data,
)
from eda.kamata7_machinename_q5_backtest import (
    assign_period,
    quintile,
)
from eda.kamata7_current_q5_list import (
    ACTIVE_DAYS,
    aggregate_machine_floor,
    aggregate_machine_overall,
    build_current_q5_table,
    determine_floor_main,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


DB_PATH = Path(__file__).resolve().parents[1] / "db" / "マルハンメガシティ2000-蒲田1.db"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "kamata1_current_q5_list"
HALL_NAME = "蒲田1"
FLOOR_BOUNDARY = 3000  # 蒲田1は台番号1631-2415、全台2F相当
MIN_GAMES = 1000


def load_data(db_path: Path, min_games: int = MIN_GAMES) -> pd.DataFrame:
    df = base_load_data(db_path)
    df = df[df["games_normalized"] >= min_games].copy()
    df["floor"] = df["machine_number"].apply(lambda x: "2F" if x < FLOOR_BOUNDARY else "3F")
    return df


def build_checklist_markdown(
    q5_current: pd.DataFrame,
    *,
    window_start: pd.Timestamp,
    max_date: pd.Timestamp,
) -> str:
    lines = [
        f"# {HALL_NAME} Q5機種名チェックリスト",
        f"算出窓: {window_start.date()} 〜 {max_date.date()}",
        "※ 蒲田1は台番号1631-2415（全台2F相当）。フロア分割なし。",
        "",
        "## Q5機種一覧（backtest excess +86、5ペア全正）",
    ]

    section = q5_current[q5_current["floor_main"].isin(["2F", "両方"])].copy()
    section = section.sort_values(["payout_rate", "diff_sum"], ascending=[False, False])
    if section.empty:
        lines.append("該当なし")
    else:
        lines.extend([
            "| 機種名 | 台数 | 機械割 | 最終登場 |",
            "|---|---:|---:|---|",
        ])
        for _, row in section.iterrows():
            lines.append(
                f"| {row['machine_name']} | {int(row['n_machines_2F'])} | "
                f"{row['payout_rate']:.2f}% | {row['last_date']} |"
            )

    inactive = q5_current[~q5_current["active"]].copy().sort_values("last_date")
    lines.extend(["", "## 注意: 要確認（30日以上登場なし）"])
    if inactive.empty:
        lines.append("該当なし")
    else:
        for _, row in inactive.iterrows():
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
