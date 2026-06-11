#!/usr/bin/env python3
"""
日曜日：機種別の突出台率・突出台の平均差枚を分析
各機種について、平均から突出している台の割合と質を調べる
"""

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.last_digit.utils import configure_logging
import logging

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze outlier rates and quality by machine type on Sundays."
    )
    parser.add_argument("--db-path", required=True, help="SQLite DB path.")
    parser.add_argument(
        "--output-dir",
        default="ml/experiments/results/sunday_machine_outlier_rank",
        help="Directory for CSV/JSON outputs.",
    )
    parser.add_argument("--diff-threshold", type=float, default=500, help="Diff outlier threshold (coins above mean).")
    parser.add_argument("--games-threshold", type=float, default=1000, help="Games outlier threshold (games above mean).")
    parser.add_argument("--min-observations", type=int, default=5, help="Minimum observations per machine type.")
    parser.add_argument("--latest-only", action="store_true", help="Analyze only latest Sunday data.")
    parser.add_argument("--log-level", default="INFO", help="Logging level.")
    return parser


def fetch_latest_sunday_date(db_path: str | Path) -> str | None:
    """最新の日曜日の日付を取得"""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    try:
        result = pd.read_sql(
            """
            SELECT MAX(date) as latest_date
            FROM daily_hall_summary
            WHERE day_of_week = '日'
            """,
            conn,
        )
        latest_date = result["latest_date"].iloc[0] if not result.empty else None
    finally:
        conn.close()
    return latest_date


def fetch_sunday_individual_machines(db_path: str | Path, latest_only: bool = False) -> pd.DataFrame:
    """日曜日の個別台データを取得

    Args:
        db_path: データベースパス
        latest_only: True の場合、最新の日曜日のみ
    """
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    try:
        if latest_only:
            latest_date = fetch_latest_sunday_date(db_path)
            if not latest_date:
                logger.warning("No Sunday data found")
                return pd.DataFrame()

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
                WHERE d.day_of_week = '日' AND m.date = ?
                """,
                conn,
                params=(latest_date,),
            )
            logger.info(f"Fetching latest Sunday data: {latest_date}")
        else:
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
                """,
                conn,
            )
    finally:
        conn.close()
    return df


def analyze_machine_outliers(
    df_individual: pd.DataFrame,
    diff_threshold: float = 500,
    games_threshold: float = 1000,
    min_observations: int = 5,
) -> pd.DataFrame:
    """
    機種別に突出台の統計を計算

    相対スコア化（percentile）と判定分離、excess_count を追加：
    - diff_percentile, games_percentile: 機種内での相対ランク（0-100）
    - is_hit_candidate: 当たり候補（games>=70 and diff>=60）
    - is_unfired_high_setting: 不発高設定（games>=80 and diff>=35 but not hit_candidate）
    - excess_count: 複数台投入数（hit_candidate_count - 1）
    """
    results = []

    for machine_name in df_individual["machine_name"].unique():
        df_machine = df_individual[df_individual["machine_name"] == machine_name]

        # 観察数がしきい値未満の場合はスキップ
        if len(df_machine) < min_observations:
            continue

        avg_diff = df_machine["diff_coins_normalized"].mean()
        avg_games = df_machine["games_normalized"].mean()
        std_diff = df_machine["diff_coins_normalized"].std()
        std_games = df_machine["games_normalized"].std()

        # 各台の乖離度を計算
        diff_above_mean = df_machine["diff_coins_normalized"] - avg_diff
        games_above_mean = df_machine["games_normalized"] - avg_games

        # 機種内での percentile ランクを計算
        diff_ranks = df_machine["diff_coins_normalized"].rank(method="average")
        games_ranks = df_machine["games_normalized"].rank(method="average")

        diff_percentiles = (diff_ranks / len(df_machine) * 100).values
        games_percentiles = (games_ranks / len(df_machine) * 100).values

        is_outlier_diff = diff_above_mean >= diff_threshold
        is_outlier_games = games_above_mean >= games_threshold
        is_outlier_either = is_outlier_diff | is_outlier_games

        # 判定分離：当たり候補 vs 不発高設定
        is_hit_candidate = (games_percentiles >= 70) & (diff_percentiles >= 60)
        is_unfired_high_setting = (games_percentiles >= 80) & (diff_percentiles >= 35) & ~is_hit_candidate

        outlier_count_diff = is_outlier_diff.sum()
        outlier_count_games = is_outlier_games.sum()
        outlier_count_either = is_outlier_either.sum()
        hit_candidate_count = is_hit_candidate.sum()
        unfired_high_setting_count = is_unfired_high_setting.sum()

        total_count = len(df_machine)

        # excess_count：複数台投入数（候補台数 - 1）
        excess_count = max(hit_candidate_count - 1, 0)
        excess_rate = (excess_count / total_count * 100) if total_count > 0 else 0

        # 突出台の平均差枚を計算
        if outlier_count_either > 0:
            outlier_avg_diff = df_machine[is_outlier_either]["diff_coins_normalized"].mean()
            outlier_avg_games = df_machine[is_outlier_either]["games_normalized"].mean()
        else:
            outlier_avg_diff = np.nan
            outlier_avg_games = np.nan

        # 当たり候補の平均差枚を計算
        if hit_candidate_count > 0:
            hit_candidate_avg_diff = df_machine[is_hit_candidate]["diff_coins_normalized"].mean()
            hit_candidate_avg_games = df_machine[is_hit_candidate]["games_normalized"].mean()
        else:
            hit_candidate_avg_diff = np.nan
            hit_candidate_avg_games = np.nan

        results.append({
            "machine_name": machine_name,
            "total_machines": total_count,
            "avg_diff": avg_diff,
            "avg_games": avg_games,
            "std_diff": std_diff,
            "std_games": std_games,
            "outlier_diff_count": outlier_count_diff,
            "outlier_games_count": outlier_count_games,
            "outlier_either_count": outlier_count_either,
            "outlier_diff_rate": (outlier_count_diff / total_count * 100) if total_count > 0 else 0,
            "outlier_games_rate": (outlier_count_games / total_count * 100) if total_count > 0 else 0,
            "outlier_either_rate": (outlier_count_either / total_count * 100) if total_count > 0 else 0,
            "outlier_avg_diff": outlier_avg_diff,
            "outlier_avg_games": outlier_avg_games,
            "hit_candidate_count": hit_candidate_count,
            "hit_candidate_rate": (hit_candidate_count / total_count * 100) if total_count > 0 else 0,
            "hit_candidate_avg_diff": hit_candidate_avg_diff,
            "hit_candidate_avg_games": hit_candidate_avg_games,
            "unfired_high_setting_count": unfired_high_setting_count,
            "unfired_high_setting_rate": (unfired_high_setting_count / total_count * 100) if total_count > 0 else 0,
            "excess_count": excess_count,
            "excess_rate": excess_rate,
        })

    df_results = pd.DataFrame(results)

    # ソート：当たり候補率 → 突出率の順でランク付け（降順）
    df_results = df_results.sort_values(
        ["hit_candidate_rate", "outlier_either_rate"],
        ascending=[False, False]
    ).reset_index(drop=True)

    return df_results


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(args.log_level)

    logger.info("Fetching individual machine data...")
    df_individual = fetch_sunday_individual_machines(args.db_path, latest_only=args.latest_only)

    if df_individual.empty:
        logger.error("No data found. Aborting.")
        return 1

    logger.info(f"Analyzing {df_individual['machine_name'].nunique()} machine types...")
    df_results = analyze_machine_outliers(
        df_individual,
        diff_threshold=args.diff_threshold,
        games_threshold=args.games_threshold,
        min_observations=args.min_observations,
    )

    # 出力
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # CSV 出力：突出率順ランキング
    df_results.to_csv(out_dir / "sunday_machine_outlier_rank.csv", index=False, encoding="utf-8")

    # JSON 出力
    payload = {
        "total_machine_types": len(df_results),
        "total_individual_machines": len(df_individual),
        "diff_threshold": args.diff_threshold,
        "games_threshold": args.games_threshold,
        "min_observations": args.min_observations,
        "machines": df_results.to_dict(orient="records"),
    }

    (out_dir / "sunday_machine_outlier_rank.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    logger.info(f"Wrote {len(df_results)} machine types: {out_dir / 'sunday_machine_outlier_rank.csv'}")
    logger.info(f"Wrote JSON report: {out_dir / 'sunday_machine_outlier_rank.json'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
