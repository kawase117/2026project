#!/usr/bin/env python3
"""
不発高設定の翌日検証スクリプト（改訂版）

分析方針：
- 不発台・当たり台・その他台の「翌日相対差枚」を比較
- 相対差枚 = 翌日の差枚 - 翌日の全台平均差枚（同日効果を除去）
- G数減少によるマイナス削減バイアスを除外するため、絶対差枚ではなく相対値で評価
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path
import logging

import numpy as np
import pandas as pd

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ml.last_digit.utils import configure_logging

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify unfired high setting hypothesis by tracking next-day relative performance."
    )
    parser.add_argument("--db-path", required=True, help="SQLite DB path.")
    parser.add_argument(
        "--output-dir",
        default="ml/experiments/results/unfired_nextday_verification",
        help="Directory for CSV/JSON outputs.",
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level.")
    return parser


def fetch_all_machine_data(db_path: str | Path) -> pd.DataFrame:
    """全機械データを取得"""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    try:
        df = pd.read_sql(
            """
            SELECT
                m.date,
                m.machine_number,
                m.machine_name,
                m.games_normalized,
                m.diff_coins_normalized
            FROM machine_detailed_results m
            ORDER BY m.date, m.machine_number
            """,
            conn,
        )
        df["date"] = df["date"].astype(str)
    finally:
        conn.close()
    return df


def compute_percentiles_per_machine(df: pd.DataFrame) -> pd.DataFrame:
    """機種ごとにpercentileを計算してフラグを付与"""
    results = []

    for machine_name in df["machine_name"].unique():
        df_machine = df[df["machine_name"] == machine_name].copy()

        diff_ranks = df_machine["diff_coins_normalized"].rank(method="average")
        games_ranks = df_machine["games_normalized"].rank(method="average")

        diff_percentiles = (diff_ranks / len(df_machine) * 100).values
        games_percentiles = (games_ranks / len(df_machine) * 100).values

        is_hit_candidate = (games_percentiles >= 70) & (diff_percentiles >= 60)
        is_unfired = (games_percentiles >= 80) & (diff_percentiles >= 35) & ~is_hit_candidate

        df_machine["diff_percentile"] = diff_percentiles
        df_machine["games_percentile"] = games_percentiles
        df_machine["is_hit_candidate"] = is_hit_candidate
        df_machine["is_unfired"] = is_unfired

        results.append(df_machine)

    return pd.concat(results, ignore_index=True)


def compute_daily_avg(df: pd.DataFrame) -> pd.Series:
    """日付ごとの全台平均差枚を計算"""
    return df.groupby("date")["diff_coins_normalized"].mean()


def build_nextday_pairs(df: pd.DataFrame) -> pd.DataFrame:
    """
    連続する営業日ペアを構築。
    各台について (today, tomorrow) のペアを作り、
    翌日差枚を当日の全台平均で補正した「相対差枚」を計算する。
    """
    all_dates = sorted(df["date"].unique().tolist())
    date_to_next = {d: all_dates[i + 1] for i, d in enumerate(all_dates[:-1])}

    # 日付ごとの全台平均差枚（翌日効果の補正用）
    daily_avg = compute_daily_avg(df)

    records = []

    for (machine_name, machine_number), group in df.groupby(["machine_name", "machine_number"]):
        group = group.sort_values("date").reset_index(drop=True)

        if len(group) < 2:
            continue

        for i in range(len(group) - 1):
            row_today = group.iloc[i]
            row_tomorrow = group.iloc[i + 1]

            date_today = row_today["date"]
            date_tomorrow = row_tomorrow["date"]

            # 連続営業日チェック
            if date_to_next.get(date_today) != date_tomorrow:
                continue

            # ステータス分類
            if row_today["is_unfired"]:
                status_today = "unfired"
            elif row_today["is_hit_candidate"]:
                status_today = "hit_candidate"
            else:
                status_today = "other"

            diff_tomorrow = row_tomorrow["diff_coins_normalized"]
            day_avg_tomorrow = daily_avg.get(date_tomorrow, 0.0)

            # 翌日相対差枚 = 翌日差枚 - 翌日の全台平均差枚
            relative_diff_tomorrow = diff_tomorrow - day_avg_tomorrow

            records.append({
                "machine_name": machine_name,
                "machine_number": machine_number,
                "date_today": date_today,
                "date_tomorrow": date_tomorrow,
                "status_today": status_today,
                "diff_today": row_today["diff_coins_normalized"],
                "games_today": row_today["games_normalized"],
                "diff_tomorrow": diff_tomorrow,
                "games_tomorrow": row_tomorrow["games_normalized"],
                "day_avg_diff_tomorrow": round(day_avg_tomorrow, 2),
                "relative_diff_tomorrow": round(relative_diff_tomorrow, 2),
            })

    return pd.DataFrame(records)


def summarize_by_status(df_pairs: pd.DataFrame) -> dict:
    """ステータス別に翌日相対差枚を集計"""
    summary = {}

    for status in ["unfired", "hit_candidate", "other"]:
        sub = df_pairs[df_pairs["status_today"] == status]
        if sub.empty:
            continue

        summary[status] = {
            "count": int(len(sub)),
            "today_avg_diff": round(sub["diff_today"].mean(), 2),
            "tomorrow_avg_diff": round(sub["diff_tomorrow"].mean(), 2),
            "tomorrow_avg_relative_diff": round(sub["relative_diff_tomorrow"].mean(), 2),
            "tomorrow_positive_rate": round((sub["relative_diff_tomorrow"] > 0).sum() / len(sub) * 100, 2),
        }

    return summary


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(args.log_level)

    logger.info("Fetching all machine data...")
    df = fetch_all_machine_data(args.db_path)

    if df.empty:
        logger.error("No data found. Aborting.")
        return 1

    all_dates = sorted(df["date"].unique())
    logger.info(f"Loaded {len(df)} records from {len(all_dates)} business days")

    logger.info("Computing percentiles per machine type...")
    df = compute_percentiles_per_machine(df)

    logger.info("Building next-day pairs...")
    df_pairs = build_nextday_pairs(df)

    if df_pairs.empty:
        logger.error("No consecutive day pairs found. Aborting.")
        return 1

    logger.info(f"Built {len(df_pairs)} consecutive-day pairs")

    # 集計
    summary = summarize_by_status(df_pairs)

    # 相対差枚のギャップ（unfired vs other, hit_candidate vs other）
    other_rel = summary.get("other", {}).get("tomorrow_avg_relative_diff", 0.0)
    gaps = {}
    for status in ["unfired", "hit_candidate"]:
        if status in summary:
            gaps[f"{status}_vs_other_gap"] = round(
                summary[status]["tomorrow_avg_relative_diff"] - other_rel, 2
            )

    output = {
        "by_status": summary,
        "gaps_vs_other": gaps,
        "note": (
            "relative_diff_tomorrow = diff_tomorrow - day_avg_diff_tomorrow\n"
            "day_avg_diff_tomorrow は翌日の全台平均差枚（曜日・日別効果を除去）"
        ),
    }

    # ログ出力
    for status, s in summary.items():
        logger.info(
            f"[{status}] n={s['count']} | "
            f"today_avg={s['today_avg_diff']:+.0f} | "
            f"tomorrow_abs={s['tomorrow_avg_diff']:+.0f} | "
            f"tomorrow_relative={s['tomorrow_avg_relative_diff']:+.0f} | "
            f"positive_rate={s['tomorrow_positive_rate']:.1f}%"
        )

    for gap_name, val in gaps.items():
        logger.info(f"Gap: {gap_name} = {val:+.2f}")

    # 出力
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df_pairs.to_csv(out_dir / "unfired_nextday_recovery_timeline.csv", index=False, encoding="utf-8")

    (out_dir / "nextday_recovery_summary.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    logger.info(f"Wrote timeline: {out_dir / 'unfired_nextday_recovery_timeline.csv'}")
    logger.info(f"Wrote summary: {out_dir / 'nextday_recovery_summary.json'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
