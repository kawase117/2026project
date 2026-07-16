"""
DD別クロステーブル分析 — 複数ホール対応
複数カテゴリ（セクション・端番・台末尾・機種名）ごとに DD別の
Win_rate, 104%超え率, 差枚を計算

機種名は正確な文字列そのものを使用する（部分一致によるグルーピングはしない）。
例：「スマスロ北斗の拳」と「北斗の拳 転生の章2」はスペックが異なる別機種のため統合しない。
"""

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "document"
RUN_DATE = pd.Timestamp.today().strftime("%Y%m%d")

HALL_DBS = {
    "みとや": "みとや大森町店.db",
    "蒲田7": "マルハンメガシティ2000-蒲田7.db",
    "蒲田1": "マルハンメガシティ2000-蒲田1.db",
    "楽園": "楽園蒲田店.db",
}


BET_PER_GAME = 3.0  # 1ゲーム=3枚ベットの近似（dashboard/utils/daily_report.py:52-66 と同じ前提）
HIT104_THRESHOLD = 104.0


def load_data(db_path):
    """機械詳細結果を読み込み"""
    with sqlite3.connect(str(db_path)) as conn:
        machine = pd.read_sql_query(
            """
            SELECT date, machine_number, machine_name, games_normalized, diff_coins_normalized
            FROM machine_detailed_results
            """,
            conn,
        )
        layout = pd.read_sql_query(
            """
            SELECT machine_number, section, rank_from_min, rank_from_max
            FROM machine_layout
            """,
            conn,
        )
    return machine, layout


def normalize_data(machine, layout):
    """データ正規化と個別台の機械割（payout_rate）を計算"""
    machine["date"] = machine["date"].astype(str)
    machine["date_dt"] = pd.to_datetime(machine["date"], format="%Y%m%d")
    machine["dd"] = machine["date_dt"].dt.day.astype(int)
    machine["diff_coins_normalized"] = pd.to_numeric(machine["diff_coins_normalized"], errors="coerce")
    machine["games_normalized"] = pd.to_numeric(machine["games_normalized"], errors="coerce")
    machine["machine_number"] = pd.to_numeric(machine["machine_number"], errors="coerce")
    machine["machine_tail"] = machine["machine_number"].mod(10).astype("Int64")

    # 個別台×個別日の機械割（payout_rate）: 100 + diff/games/BET_PER_GAME*100
    bet = machine["games_normalized"] * BET_PER_GAME
    payout = bet + machine["diff_coins_normalized"]
    machine["payout_rate"] = (payout / bet) * 100.0
    machine["payout_rate"] = machine["payout_rate"].where((bet > 0) & bet.notna())
    machine["hit104"] = (machine["payout_rate"] >= HIT104_THRESHOLD).astype("float")

    layout["machine_number"] = pd.to_numeric(layout["machine_number"], errors="coerce")

    machine = machine.merge(layout, on="machine_number", how="left")

    return machine


def calculate_metrics(group_df):
    """グループの3指標を計算（個別台×個別日レコードをカテゴリ内で集計）"""
    diff = group_df["diff_coins_normalized"]
    win_rate = float(diff.gt(0).mean()) if diff.notna().any() else np.nan
    hit104_rate = float(group_df["hit104"].mean()) if group_df["hit104"].notna().any() else np.nan
    avg_diff = float(diff.mean()) if len(group_df) > 0 else np.nan
    n_records = len(group_df)
    n_unique_machines = int(group_df["machine_number"].nunique())
    n_unique_dates = int(group_df["date"].nunique())

    return {
        "win_rate": win_rate,
        "hit104_rate": hit104_rate,
        "avg_diff": avg_diff,
        "n_records": n_records,
        "n_machines": n_unique_machines,
        "n_dates": n_unique_dates,
    }


def crosstab_by_category(machine, category_name, category_col):
    """カテゴリ×DD のクロステーブル生成"""
    rows = []

    for dd in sorted(machine["dd"].unique()):
        dd_data = machine[machine["dd"] == dd].copy()
        if dd_data.empty:
            continue

        for category_val in sorted(dd_data[category_col].dropna().unique()):
            group = dd_data[dd_data[category_col] == category_val]
            if group.empty:
                continue

            metrics = calculate_metrics(group)
            rows.append(
                {
                    "dd": int(dd),
                    "category": category_name,
                    "value": str(category_val),
                    "win_rate": metrics["win_rate"],
                    "hit104_rate": metrics["hit104_rate"],
                    "avg_diff": metrics["avg_diff"],
                    "n_records": metrics["n_records"],
                    "n_machines": metrics["n_machines"],
                    "n_dates": metrics["n_dates"],
                }
            )

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def main(argv=None):
    parser = argparse.ArgumentParser(description="DD別クロステーブル分析（複数ホール）")
    parser.add_argument("--halls", nargs="+", choices=list(HALL_DBS.keys()), default=list(HALL_DBS.keys()))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    for hall_name in args.halls:
        print(f"\n{'=' * 60}")
        print(f"Processing: {hall_name}")
        print('=' * 60)

        db_path = PROJECT_ROOT / "db" / HALL_DBS[hall_name]
        if not db_path.exists():
            print(f"DB not found: {db_path}")
            continue

        try:
            machine, layout = load_data(db_path)
            machine = normalize_data(machine, layout)

            all_results = []

            categories = {
                "section": "section",
                "rank_from_min": "rank_from_min",
                "rank_from_max": "rank_from_max",
                "machine_tail": "machine_tail",
                "machine_name": "machine_name",
            }

            for category_label, category_col in categories.items():
                print(f"  {category_label}...", end=" ", flush=True)
                result = crosstab_by_category(machine, category_label, category_col)
                if not result.empty:
                    all_results.append(result)
                    print(f"OK ({len(result)} rows)")
                else:
                    print("empty")

            if not all_results:
                print("No results generated")
                continue

            combined = pd.concat(all_results, ignore_index=True)
            combined = combined.sort_values(["dd", "category", "value"]).reset_index(drop=True)

            output_path = args.output_dir / f"{hall_name}_dd_crosstab_{RUN_DATE}.csv"
            combined.to_csv(output_path, index=False, encoding="utf-8-sig")

            print(f"\nwritten: {output_path}")
            print(f"Total rows: {len(combined)}")
            print("\nSample (first 10 rows):")
            print(combined.head(10).to_string(index=False))

        except Exception as e:
            print(f"Error processing {hall_name}: {e}")
            import traceback

            traceback.print_exc()
            continue

    return 0


if __name__ == "__main__":
    sys.exit(main())
