"""
みとや×ジャグラーガールズ: 2026-07-09時点での座席選択判断のため、
直近の短期投資傾向(games_normalized)と直近RB率を台番号別に確認する
"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DB_PATH = Path(__file__).resolve().parents[1] / "db" / "みとや大森町店.db"


def load_data() -> pd.DataFrame:
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql_query(
        "SELECT date, machine_number, machine_name, games_normalized, rb_count FROM machine_detailed_results",
        conn,
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    return df


def main():
    df = load_data()
    gals = df[df["machine_name"].str.contains("ジャグラーガールズ", na=False, case=False)].copy()

    last_date = gals["date"].max()
    print(f"データ最終日: {last_date.strftime('%Y-%m-%d')}")

    for window_days, label in [(14, "直近14日"), (30, "直近30日"), (60, "直近60日")]:
        cutoff = last_date - pd.Timedelta(days=window_days)
        recent = gals[gals["date"] > cutoff]
        agg = (
            recent.groupby("machine_number")
            .agg(games_sum=("games_normalized", "sum"), rb_sum=("rb_count", "sum"), n_days=("date", "nunique"))
            .reset_index()
        )
        agg["rb_rate"] = agg["rb_sum"] / agg["games_sum"]
        agg = agg.sort_values("rb_rate", ascending=False)
        print(f"\n=== {label}（{cutoff.strftime('%Y-%m-%d')}以降）===")
        for idx, row in agg.iterrows():
            print(
                f"  台{row['machine_number']:.0f}: RB率={row['rb_rate']:.4f} (1/{1 / row['rb_rate']:.1f}) "
                f"games={row['games_sum']:.0f}, n_days={row['n_days']}"
            )

    # 直近7日の日別詳細（座席選択の最終判断材料）
    print("\n=== 直近7日の日別詳細 ===")
    cutoff7 = last_date - pd.Timedelta(days=7)
    recent7 = gals[gals["date"] > cutoff7].copy()
    recent7["rb_rate"] = recent7["rb_count"] / recent7["games_normalized"]
    pivot = recent7.pivot_table(index="date", columns="machine_number", values="games_normalized", aggfunc="sum")
    print("\n各台の日別games:")
    print(pivot.to_string())

    pivot_rb = recent7.pivot_table(index="date", columns="machine_number", values="rb_count", aggfunc="sum")
    print("\n各台の日別rb_count:")
    print(pivot_rb.to_string())


if __name__ == "__main__":
    main()
