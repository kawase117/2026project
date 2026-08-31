"""
みとや大森町店: 直近1ヶ月・ジャグラー全機種プール・イベント日(X_DDS)除外での
日別RB確率スキャン。通常日の中で「いつもより良い日」を探す。
"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DB_PATH = Path(__file__).resolve().parents[1] / "db" / "みとや大森町店.db"
X_DDS = {4, 7, 14, 17, 24, 27}  # 確立済みみとやイベント日定義


def main():
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql_query(
        "SELECT date, machine_number, machine_name, games_normalized, rb_count, bb_count "
        "FROM machine_detailed_results WHERE machine_name LIKE '%ジャグラー%'",
        conn,
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["day"] = df["date"].dt.day
    df["is_event_day"] = df["day"].isin(X_DDS)

    print("ジャグラー機種一覧:", sorted(df["machine_name"].unique()))

    last_date = df["date"].max()
    cutoff = last_date - pd.Timedelta(days=30)
    recent = df[df["date"] > cutoff].copy()
    print(f"\n直近1ヶ月範囲: {cutoff.strftime('%Y-%m-%d')} 〜 {last_date.strftime('%Y-%m-%d')}")

    # ベースライン: 過去全期間の非イベント日 全ジャグラープールRB率
    baseline = df[~df["is_event_day"]]
    baseline_rate = baseline["rb_count"].sum() / baseline["games_normalized"].sum()
    print(f"全期間・非イベント日ベースラインRB率: {baseline_rate:.5f} (1/{1 / baseline_rate:.1f})")

    # 直近1ヶ月・非イベント日のみ、日別に全ジャグラー機種をプール
    non_event = recent[~recent["is_event_day"]].copy()
    daily = (
        non_event.groupby("date")
        .agg(
            games_sum=("games_normalized", "sum"), rb_sum=("rb_count", "sum"), n_machines=("machine_number", "nunique")
        )
        .reset_index()
    )
    daily["rb_rate"] = daily["rb_sum"] / daily["games_sum"]
    daily["day"] = daily["date"].dt.day
    daily["weekday"] = daily["date"].dt.day_name()
    daily["lift_vs_baseline"] = daily["rb_rate"] / baseline_rate - 1
    daily = daily.sort_values("rb_rate", ascending=False)

    print(f"\n=== 直近1ヶ月・非イベント日(DD{sorted(X_DDS)}を除外)の日別ジャグラー全体RB率ランキング ===")
    print(f"対象日数: {len(daily)}日")
    for _, row in daily.iterrows():
        flag = " <<<" if row["lift_vs_baseline"] > 0.10 else ""
        print(
            f"  {row['date'].strftime('%Y-%m-%d')}({row['weekday'][:3]}) DD={row['day']:02d}: "
            f"games={row['games_sum']:.0f}(n_machines={row['n_machines']}) RB={row['rb_sum']:.0f} "
            f"RB率={row['rb_rate']:.5f}(1/{1 / row['rb_rate']:.1f}) lift={row['lift_vs_baseline']:+.1%}{flag}"
        )

    # 上位日の機種内訳
    print("\n=== 上位3日の機種別内訳 ===")
    for d in daily["date"].head(3):
        sub = non_event[non_event["date"] == d]
        by_machine = (
            sub.groupby("machine_name")
            .agg(games_sum=("games_normalized", "sum"), rb_sum=("rb_count", "sum"))
            .reset_index()
        )
        by_machine["rb_rate"] = by_machine["rb_sum"] / by_machine["games_sum"]
        by_machine = by_machine.sort_values("rb_rate", ascending=False)
        print(f"\n  --- {d.strftime('%Y-%m-%d')} ---")
        for _, row in by_machine.iterrows():
            rate = row["rb_rate"]
            rate_str = f"{rate:.5f}(1/{1 / rate:.1f})" if rate else "0"
            print(f"    {row['machine_name']}: games={row['games_sum']:.0f} RB={row['rb_sum']:.0f} RB率={rate_str}")


if __name__ == "__main__":
    main()
