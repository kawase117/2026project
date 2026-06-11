#!/usr/bin/env python3
"""
日曜日：機種の平均から突出している台の割合を分析
差枚 or 回転数が突出している台の比率を、カテゴリ別に集計
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
        description="Analyze outlier machines (high diff or high games) on Sundays by category."
    )
    parser.add_argument("--db-path", required=True, help="SQLite DB path.")
    parser.add_argument(
        "--output-dir",
        default="ml/experiments/results/sunday_outlier_analysis",
        help="Directory for CSV/JSON outputs.",
    )
    parser.add_argument("--diff-threshold", type=float, default=500, help="Diff outlier threshold (coins above mean).")
    parser.add_argument("--games-threshold", type=float, default=1000, help="Games outlier threshold (games above mean).")
    parser.add_argument("--log-level", default="INFO", help="Logging level.")
    return parser


def fetch_sunday_individual_machines(db_path: str | Path) -> pd.DataFrame:
    """日曜日の個別台データを取得"""
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
            """,
            conn,
        )
    finally:
        conn.close()
    return df


def fetch_machine_type_counts(db_path: str | Path) -> dict[str, float]:
    """各機種の台数を取得（日曜日）"""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    try:
        df = pd.read_sql(
            """
            SELECT m.machine_name, m.machine_count
            FROM daily_machine_type_summary m
            WHERE m.machine_count > 1
            """,
            conn,
        )
        # 機種名ごとに最初の machine_count を取得
        machine_counts = df.groupby("machine_name")["machine_count"].first().to_dict()
    finally:
        conn.close()
    return machine_counts


def categorize_machine_count(count: float | int) -> str:
    if pd.isna(count):
        return "unknown"
    value = int(count)
    if 2 <= value <= 5:
        return "2-5台"
    if 6 <= value <= 15:
        return "6-15台"
    if 16 <= value <= 50:
        return "16-50台"
    return "50台超"


def identify_outliers(
    df_individual: pd.DataFrame,
    machine_counts: dict[str, float],
    diff_threshold: float = 500,
    games_threshold: float = 1000,
) -> pd.DataFrame:
    """
    各機種の平均から突出している台を特定

    相対スコア化（percentile）と判定分離を追加
    - diff_percentile, games_percentile: 機種内での相対ランク（0-100）
    - is_hit_candidate: 当たり候補（games_pctile>=70 and diff_pctile>=60）
    - is_unfired_high_setting: 不発高設定（games_pctile>=80 and diff_pctile>=35 but not hit_candidate）

    Returns:
        DataFrame with columns: machine_name, machine_count, category,
                               avg_diff, avg_games, diff_above_mean, games_above_mean,
                               diff_percentile, games_percentile,
                               is_outlier_diff, is_outlier_games, is_outlier_either,
                               is_hit_candidate, is_unfired_high_setting
    """

    # 機種別の平均を計算
    machine_means = df_individual.groupby("machine_name").agg({
        "diff_coins_normalized": ["mean", "std"],
        "games_normalized": ["mean", "std"],
    }).reset_index()
    machine_means.columns = ["machine_name", "avg_diff", "std_diff", "avg_games", "std_games"]

    # 各台について、機種平均からの乖離度を計算
    outlier_records = []

    for machine_name in df_individual["machine_name"].unique():
        df_machine = df_individual[df_individual["machine_name"] == machine_name]
        mean_data = machine_means[machine_means["machine_name"] == machine_name].iloc[0]

        avg_diff = mean_data["avg_diff"]
        avg_games = mean_data["avg_games"]

        # 機種内での percentile ランクを計算（0～100）
        # rank() で重複を平均順位として扱い、正規化
        diff_ranks = df_machine["diff_coins_normalized"].rank(method="average")
        games_ranks = df_machine["games_normalized"].rank(method="average")

        diff_percentiles = (diff_ranks / len(df_machine) * 100).values
        games_percentiles = (games_ranks / len(df_machine) * 100).values

        for idx, (_, row) in enumerate(df_machine.iterrows()):
            diff_above_mean = row["diff_coins_normalized"] - avg_diff
            games_above_mean = row["games_normalized"] - avg_games

            # Percentile スコア（0～100）
            diff_pctile = diff_percentiles[idx]
            games_pctile = games_percentiles[idx]

            # 従来の固定しきい値判定
            is_outlier_diff = diff_above_mean >= diff_threshold
            is_outlier_games = games_above_mean >= games_threshold
            is_outlier_either = is_outlier_diff or is_outlier_games

            # 判定分離：当たり候補 vs 不発高設定
            # 当たり候補：games_percentile >= 70 かつ diff_percentile >= 60
            is_hit_candidate = (games_pctile >= 70) and (diff_pctile >= 60)

            # 不発候補：games_percentile >= 80 かつ diff_percentile >= 35 かつ当たり候補でない
            is_unfired_high_setting = (games_pctile >= 80) and (diff_pctile >= 35) and not is_hit_candidate

            outlier_records.append({
                "machine_name": machine_name,
                "machine_count": machine_counts.get(machine_name, np.nan),
                "avg_diff": avg_diff,
                "avg_games": avg_games,
                "diff_above_mean": diff_above_mean,
                "games_above_mean": games_above_mean,
                "diff_percentile": round(diff_pctile, 2),
                "games_percentile": round(games_pctile, 2),
                "is_outlier_diff": is_outlier_diff,
                "is_outlier_games": is_outlier_games,
                "is_outlier_either": is_outlier_either,
                "is_hit_candidate": is_hit_candidate,
                "is_unfired_high_setting": is_unfired_high_setting,
            })

    df_outliers = pd.DataFrame(outlier_records)
    df_outliers["category"] = df_outliers["machine_count"].apply(categorize_machine_count)

    return df_outliers


def build_category_outlier_summary(df_outliers: pd.DataFrame, exclude_jaggler: bool = False) -> pd.DataFrame:
    """カテゴリ別のアウトライア割合を集計

    Args:
        df_outliers: アウトライア分析結果
        exclude_jaggler: ジャグラーを除外するか（ジャグラーは設定判断が難しい）
    """
    category_order = ["2-5台", "6-15台", "16-50台", "50台超"]

    if exclude_jaggler:
        # ジャグラーを含む全機種を除外
        df_filtered = df_outliers[~df_outliers["machine_name"].str.contains("ジャグラー", na=False)].copy()
    else:
        df_filtered = df_outliers.copy()

    summary = df_filtered.groupby("category", as_index=False).agg({
        "is_outlier_diff": ["sum", "count"],
        "is_outlier_games": "sum",
        "is_outlier_either": "sum",
        "is_hit_candidate": "sum",
        "is_unfired_high_setting": "sum",
    })
    summary.columns = [
        "category",
        "outlier_diff_count",
        "total_machines",
        "outlier_games_count",
        "outlier_either_count",
        "hit_candidate_count",
        "unfired_high_setting_count",
    ]

    # 割合を計算
    summary["outlier_diff_rate"] = (summary["outlier_diff_count"] / summary["total_machines"] * 100).round(2)
    summary["outlier_games_rate"] = (summary["outlier_games_count"] / summary["total_machines"] * 100).round(2)
    summary["outlier_either_rate"] = (summary["outlier_either_count"] / summary["total_machines"] * 100).round(2)
    summary["hit_candidate_rate"] = (summary["hit_candidate_count"] / summary["total_machines"] * 100).round(2)
    summary["unfired_high_setting_rate"] = (summary["unfired_high_setting_count"] / summary["total_machines"] * 100).round(2)

    # 突出台の平均差枚を計算
    outlier_avg_diff = df_filtered[df_filtered["is_outlier_either"]].groupby("category")["diff_above_mean"].mean().round(2)
    summary = summary.merge(
        outlier_avg_diff.rename("outlier_avg_diff_above_mean").reset_index(),
        on="category",
        how="left"
    )

    # 当たり候補の平均差枚を計算
    hit_candidate_avg_diff = df_filtered[df_filtered["is_hit_candidate"]].groupby("category")["diff_above_mean"].mean().round(2)
    summary = summary.merge(
        hit_candidate_avg_diff.rename("hit_candidate_avg_diff_above_mean").reset_index(),
        on="category",
        how="left"
    )

    # ソート
    summary["sort_key"] = summary["category"].map({label: i for i, label in enumerate(category_order)})
    summary = summary.sort_values("sort_key").drop(columns=["sort_key"]).reset_index(drop=True)

    return summary


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(args.log_level)

    logger.info("Fetching individual machine data...")
    df_individual = fetch_sunday_individual_machines(args.db_path)
    machine_counts = fetch_machine_type_counts(args.db_path)

    logger.info(f"Processing {len(df_individual)} individual machine records...")
    df_outliers = identify_outliers(
        df_individual,
        machine_counts,
        diff_threshold=args.diff_threshold,
        games_threshold=args.games_threshold,
    )

    # 2つのバージョンを生成：全機種版と非ジャグラー版
    summary_all = build_category_outlier_summary(df_outliers, exclude_jaggler=False)
    summary_no_jaggler = build_category_outlier_summary(df_outliers, exclude_jaggler=True)

    # 出力
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df_outliers.to_csv(out_dir / "sunday_outlier_machines.csv", index=False, encoding="utf-8")
    summary_all.to_csv(out_dir / "sunday_outlier_summary_all.csv", index=False, encoding="utf-8")
    summary_no_jaggler.to_csv(out_dir / "sunday_outlier_summary_no_jaggler.csv", index=False, encoding="utf-8")

    payload = {
        "total_machines": len(df_outliers),
        "diff_threshold": args.diff_threshold,
        "games_threshold": args.games_threshold,
        "all_machines": summary_all.to_dict(orient="records"),
        "excluding_jaggler": summary_no_jaggler.to_dict(orient="records"),
    }

    (out_dir / "sunday_outlier_analysis.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    logger.info(f"Wrote {len(df_outliers)} machine records: {out_dir / 'sunday_outlier_machines.csv'}")
    logger.info(f"Wrote category summary (all): {out_dir / 'sunday_outlier_summary_all.csv'}")
    logger.info(f"Wrote category summary (no jaggler): {out_dir / 'sunday_outlier_summary_no_jaggler.csv'}")
    logger.info(f"Wrote JSON report: {out_dir / 'sunday_outlier_analysis.json'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
