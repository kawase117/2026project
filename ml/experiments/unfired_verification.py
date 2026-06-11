#!/usr/bin/env python3
"""
不発高設定の検証スクリプト
仮説：不発高設定台（高回転・低差枚）は翌週日曜に当たり候補になりやすい
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Dict, Tuple
import logging

import numpy as np
import pandas as pd

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ml.last_digit.utils import configure_logging

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify unfired high setting hypothesis by tracking recovery rate."
    )
    parser.add_argument("--db-path", required=True, help="SQLite DB path.")
    parser.add_argument(
        "--output-dir",
        default="ml/experiments/results/unfired_verification",
        help="Directory for CSV/JSON outputs.",
    )
    parser.add_argument(
        "--diff-threshold", type=float, default=500, help="Diff outlier threshold (coins above mean)."
    )
    parser.add_argument(
        "--games-threshold", type=float, default=1000, help="Games outlier threshold (games above mean)."
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level.")
    return parser


def fetch_all_sunday_data(db_path: str | Path) -> pd.DataFrame:
    """全日曜データを取得（日付昇順）"""
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
            JOIN daily_hall_summary d ON m.date = d.date
            WHERE d.day_of_week = '日'
            ORDER BY m.date, m.machine_number
            """,
            conn,
        )
        df["date"] = df["date"].astype(str)
    finally:
        conn.close()
    return df


def compute_percentiles_per_machine(df: pd.DataFrame) -> pd.DataFrame:
    """機種ごとにpercentileを計算、フラグを付与"""
    results = []

    for machine_name in df["machine_name"].unique():
        df_machine = df[df["machine_name"] == machine_name].copy()

        avg_diff = df_machine["diff_coins_normalized"].mean()
        avg_games = df_machine["games_normalized"].mean()

        # percentile 計算
        diff_ranks = df_machine["diff_coins_normalized"].rank(method="average")
        games_ranks = df_machine["games_normalized"].rank(method="average")

        diff_percentiles = (diff_ranks / len(df_machine) * 100).values
        games_percentiles = (games_ranks / len(df_machine) * 100).values

        diff_above_mean = df_machine["diff_coins_normalized"].values - avg_diff
        games_above_mean = df_machine["games_normalized"].values - avg_games

        # フラグ計算
        is_hit_candidate = (games_percentiles >= 70) & (diff_percentiles >= 60)
        is_unfired_high_setting = (games_percentiles >= 80) & (diff_percentiles >= 35) & ~is_hit_candidate

        df_machine["diff_percentile"] = diff_percentiles
        df_machine["games_percentile"] = games_percentiles
        df_machine["diff_above_mean"] = diff_above_mean
        df_machine["games_above_mean"] = games_above_mean
        df_machine["is_hit_candidate"] = is_hit_candidate
        df_machine["is_unfired_high_setting"] = is_unfired_high_setting

        results.append(df_machine)

    return pd.concat(results, ignore_index=True)


def build_machine_timeline(df: pd.DataFrame) -> pd.DataFrame:
    """(machine_number, machine_name, date) の時系列を構築"""
    df = df.sort_values(["machine_name", "machine_number", "date"]).reset_index(drop=True)
    return df


def compute_recovery_rate(timeline: pd.DataFrame) -> pd.DataFrame:
    """
    翌週追跡分析：不発高設定→当たり候補への回復率を計算
    """
    recovery_records = []

    # (machine_name, machine_number) ごとにグループ化
    for (machine_name, machine_number), group in timeline.groupby(["machine_name", "machine_number"]):
        group = group.sort_values("date").reset_index(drop=True)

        if len(group) < 2:
            continue  # 2週以上のデータがないとスキップ

        for i in range(len(group) - 1):
            row_n = group.iloc[i]
            row_n1 = group.iloc[i + 1]

            date_n = row_n["date"]
            date_n1 = row_n1["date"]

            # ステータス判定
            if row_n["is_unfired_high_setting"]:
                status_n = "unfired"
            elif row_n["is_hit_candidate"]:
                status_n = "hit_candidate"
            else:
                status_n = "other"

            if row_n1["is_unfired_high_setting"]:
                status_n1 = "unfired"
            elif row_n1["is_hit_candidate"]:
                status_n1 = "hit_candidate"
            else:
                status_n1 = "other"

            # 回復判定：翌週が hit_candidate になった
            is_recovered = status_n1 == "hit_candidate"

            # 差枚改善
            diff_improvement = row_n1["diff_coins_normalized"] - row_n["diff_coins_normalized"]

            recovery_records.append({
                "machine_name": machine_name,
                "machine_number": machine_number,
                "date_n": date_n,
                "date_n1": date_n1,
                "status_n": status_n,
                "status_n1": status_n1,
                "diff_n": row_n["diff_coins_normalized"],
                "diff_n1": row_n1["diff_coins_normalized"],
                "diff_improvement": diff_improvement,
                "games_n": row_n["games_normalized"],
                "games_n1": row_n1["games_normalized"],
                "is_recovered": is_recovered,
            })

    df_recovery = pd.DataFrame(recovery_records)
    return df_recovery


def compute_baseline_recovery_rate(timeline: pd.DataFrame) -> float:
    """
    ベースライン：unfired でも hit_candidate でもない台が翌週 hit_candidate になった割合
    """
    baseline_records = []

    for (machine_name, machine_number), group in timeline.groupby(["machine_name", "machine_number"]):
        group = group.sort_values("date").reset_index(drop=True)

        if len(group) < 2:
            continue

        for i in range(len(group) - 1):
            row_n = group.iloc[i]
            row_n1 = group.iloc[i + 1]

            # ベースライン条件：n週目が unfired_high_setting でも hit_candidate でもない
            if not row_n["is_unfired_high_setting"] and not row_n["is_hit_candidate"]:
                is_recovered = row_n1["is_hit_candidate"]
                baseline_records.append({"is_recovered": is_recovered})

    if not baseline_records:
        return 0.0

    df_baseline = pd.DataFrame(baseline_records)
    return (df_baseline["is_recovered"].sum() / len(df_baseline) * 100) if len(df_baseline) > 0 else 0.0


def analyze_recovery_by_threshold(
    timeline: pd.DataFrame, thresholds: list = None
) -> pd.DataFrame:
    """
    diff_percentile 閾値を変えて回復率を分析
    """
    if thresholds is None:
        thresholds = [25, 30, 35, 40, 45, 50]

    results = []

    for threshold in thresholds:
        # unfired_high_setting を再定義（diff_percentile >= threshold を使用）
        timeline["is_unfired_high_setting_alt"] = (
            (timeline["games_percentile"] >= 80)
            & (timeline["diff_percentile"] >= threshold)
            & ~timeline["is_hit_candidate"]
        )

        recovery_records = []

        for (machine_name, machine_number), group in timeline.groupby(["machine_name", "machine_number"]):
            group = group.sort_values("date").reset_index(drop=True)

            if len(group) < 2:
                continue

            for i in range(len(group) - 1):
                row_n = group.iloc[i]
                row_n1 = group.iloc[i + 1]

                if row_n["is_unfired_high_setting_alt"]:
                    is_recovered = row_n1["is_hit_candidate"]
                    recovery_records.append({"is_recovered": is_recovered})

        if recovery_records:
            df_recovery = pd.DataFrame(recovery_records)
            recovery_rate = df_recovery["is_recovered"].sum() / len(df_recovery) * 100
        else:
            recovery_rate = 0.0

        results.append({
            "diff_percentile_threshold": threshold,
            "unfired_count": len(recovery_records),
            "recovery_rate": recovery_rate,
        })

    return pd.DataFrame(results)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(args.log_level)

    logger.info("Fetching all Sunday data...")
    df = fetch_all_sunday_data(args.db_path)

    if df.empty:
        logger.error("No Sunday data found. Aborting.")
        return 1

    logger.info(f"Loaded {len(df)} individual machines from {df['date'].nunique()} Sundays")

    logger.info("Computing percentiles per machine type...")
    df = compute_percentiles_per_machine(df)

    logger.info("Building machine timeline...")
    timeline = build_machine_timeline(df)

    logger.info("Computing recovery rate...")
    df_recovery = compute_recovery_rate(timeline)

    # 統計情報
    unfired_count = timeline["is_unfired_high_setting"].sum()
    unfired_recovery_count = (
        df_recovery[df_recovery["status_n"] == "unfired"]["is_recovered"].sum()
    )
    unfired_total = len(df_recovery[df_recovery["status_n"] == "unfired"])
    unfired_recovery_rate = (
        (unfired_recovery_count / unfired_total * 100) if unfired_total > 0 else 0.0
    )

    baseline_recovery_rate = compute_baseline_recovery_rate(timeline)

    logger.info(f"Unfired high setting count (all weeks): {unfired_count}")
    logger.info(f"Unfired recovery rate: {unfired_recovery_rate:.2f}%")
    logger.info(f"Baseline recovery rate: {baseline_recovery_rate:.2f}%")

    logger.info("Analyzing threshold sensitivity...")
    df_threshold = analyze_recovery_by_threshold(timeline)

    # 出力
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df_recovery.to_csv(out_dir / "unfired_recovery_timeline.csv", index=False, encoding="utf-8")
    df_threshold.to_csv(out_dir / "threshold_sensitivity.csv", index=False, encoding="utf-8")

    # JSON サマリー
    summary = {
        "unfired_high_setting_total": int(unfired_count),
        "unfired_recovery_rate": round(unfired_recovery_rate, 2),
        "baseline_recovery_rate": round(baseline_recovery_rate, 2),
        "recovery_improvement": round(unfired_recovery_rate - baseline_recovery_rate, 2),
        "interpretation": (
            "仮説支持：本当の高設定" if unfired_recovery_rate > baseline_recovery_rate + 10
            else "仮説不支持：低設定の長時間稼働" if abs(unfired_recovery_rate - baseline_recovery_rate) <= 10
            else "逆効果：除外対象を検討"
        ),
    }

    (out_dir / "recovery_rate_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    logger.info(f"Wrote recovery timeline: {out_dir / 'unfired_recovery_timeline.csv'}")
    logger.info(f"Wrote threshold sensitivity: {out_dir / 'threshold_sensitivity.csv'}")
    logger.info(f"Wrote summary: {out_dir / 'recovery_rate_summary.json'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
