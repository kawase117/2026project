"""
DD9深掘り追加分析:
- 各日付(9日)ごとの詳細: 曜日、平均回転数、2k+比率、RB率
- 2k+区分(高RB率の主因)が特定曜日/日付に偏っているか
"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd
import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DB_PATH = Path(__file__).resolve().parents[1] / "db" / "みとや大森町店.db"


def load_data() -> pd.DataFrame:
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql_query(
        "SELECT date, machine_number, machine_name, games_normalized, rb_count, bb_count FROM machine_detailed_results",
        conn,
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["dd"] = df["date"].dt.day
    df["dow_num"] = df["date"].dt.dayofweek
    return df


def main():
    df = load_data()
    gals = df[df["machine_name"].str.contains("ジャグラーガールズ", na=False, case=False)].copy()
    dd9 = gals[gals["dd"] == 9].copy()
    dd9["rb_rate"] = dd9["rb_count"] / dd9["games_normalized"]

    dow_map = {0: "月", 1: "火", 2: "水", 3: "木", 4: "金", 5: "土", 6: "日"}
    dd9["dow_ja"] = dd9["dow_num"].map(dow_map)

    print("=== 日付ごとの詳細（6台分を集計） ===")
    date_detail = (
        dd9.groupby("date")
        .agg(
            dow_ja=("dow_ja", "first"),
            games_mean=("games_normalized", "mean"),
            games_sum=("games_normalized", "sum"),
            n_2k_plus=("games_normalized", lambda x: (x >= 2000).sum()),
            n_machines=("machine_number", "count"),
            rb_sum=("rb_count", "sum"),
        )
        .reset_index()
    )
    date_detail["rb_rate"] = date_detail["rb_sum"] / date_detail["games_sum"]
    date_detail["pct_2k_plus"] = date_detail["n_2k_plus"] / date_detail["n_machines"]
    date_detail = date_detail.sort_values("date")

    for idx, row in date_detail.iterrows():
        print(
            f"  {row['date'].strftime('%Y-%m-%d')} ({row['dow_ja']}): "
            f"平均games={row['games_mean']:.0f}, 2k+比率={row['pct_2k_plus']:.0%} "
            f"({row['n_2k_plus']}/{row['n_machines']}), RB率={row['rb_rate']:.4f}"
        )

    print("\n=== 曜日別: 平均回転数 と 2k+比率 ===")
    dow_summary = (
        date_detail.groupby("dow_ja")
        .agg(
            n_dates=("date", "count"),
            games_mean=("games_mean", "mean"),
            pct_2k_plus_mean=("pct_2k_plus", "mean"),
            rb_rate_mean=("rb_rate", "mean"),
        )
        .reset_index()
    )
    dow_order = ["月", "火", "水", "木", "金", "土", "日"]
    dow_summary["dow_ja"] = pd.Categorical(dow_summary["dow_ja"], categories=dow_order, ordered=True)
    dow_summary = dow_summary.sort_values("dow_ja")

    for idx, row in dow_summary.iterrows():
        print(
            f"  {row['dow_ja']}: n={row['n_dates']}日, "
            f"平均games={row['games_mean']:.0f}, "
            f"平均2k+比率={row['pct_2k_plus_mean']:.0%}, "
            f"平均RB率={row['rb_rate_mean']:.4f}"
        )

    print("\n=== 相関: games_mean vs rb_rate (日付レベル) ===")
    corr = date_detail[["games_mean", "rb_rate"]].corr().iloc[0, 1]
    print(f"  相関係数: {corr:.3f}")

    print("\n=== 土日 vs 平日 比較 ===")
    date_detail["is_weekend"] = date_detail["dow_ja"].isin(["土", "日"])
    weekend_agg = date_detail.groupby("is_weekend").agg(
        n_dates=("date", "count"),
        games_mean=("games_mean", "mean"),
        rb_sum=("rb_sum", "sum"),
        games_sum=("games_sum", "sum"),
    )
    weekend_agg["rb_rate_pooled"] = weekend_agg["rb_sum"] / weekend_agg["games_sum"]
    for is_we, row in weekend_agg.iterrows():
        label = "土日" if is_we else "平日"
        print(
            f"  {label}: n={row['n_dates']}日, 平均games={row['games_mean']:.0f}, "
            f"プールRB率={row['rb_rate_pooled']:.4f}"
        )

    print("\n=== 高RB率日(上位5) vs 低RB率日(下位5) の games_mean 比較 ===")
    top5 = date_detail.nlargest(5, "rb_rate")
    bot5 = date_detail.nsmallest(5, "rb_rate")
    print(f"  上位5日 平均games: {top5['games_mean'].mean():.0f}")
    print(f"  下位5日 平均games: {bot5['games_mean'].mean():.0f}")
    print("\n  上位5日詳細:")
    for idx, row in top5.iterrows():
        print(
            f"    {row['date'].strftime('%Y-%m-%d')}({row['dow_ja']}): RB率={row['rb_rate']:.4f}, games={row['games_mean']:.0f}"
        )
    print("\n  下位5日詳細:")
    for idx, row in bot5.iterrows():
        print(
            f"    {row['date'].strftime('%Y-%m-%d')}({row['dow_ja']}): RB率={row['rb_rate']:.4f}, games={row['games_mean']:.0f}"
        )


if __name__ == "__main__":
    main()
