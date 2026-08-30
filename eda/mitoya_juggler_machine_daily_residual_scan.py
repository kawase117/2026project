"""
みとや大森町店: 直近1ヶ月・機種別の日次RB率スキャン。
イベント日(X_DDS)と、既に説明のついた3日(8/5=5のつく日, 8/8=強ゾロ目,
8/10=蒲田1周年対抗)を除外した残りの日で、機種固有ベースラインを
大きく上回る日がないかを機種ごとに確認する。
"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd
from scipy.stats import norm

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DB_PATH = Path(__file__).resolve().parents[1] / "db" / "みとや大森町店.db"
X_DDS = {4, 7, 14, 17, 24, 27}
EXPLAINED_DATES = {"20260805", "20260808", "20260810"}
MIN_GAMES = 1500


def main():
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql_query(
        "SELECT date, machine_number, machine_name, games_normalized, rb_count "
        "FROM machine_detailed_results WHERE machine_name LIKE '%ジャグラー%'",
        conn,
    )
    conn.close()
    df["date_dt"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["day"] = df["date_dt"].dt.day
    df["is_event_day"] = df["day"].isin(X_DDS)

    last_date = df["date_dt"].max()
    cutoff = last_date - pd.Timedelta(days=30)

    # 機種固有ベースライン(全期間・非イベント日)
    baseline_pool = df[~df["is_event_day"]]
    machine_baseline = (
        baseline_pool.groupby("machine_name")
        .agg(games_sum=("games_normalized", "sum"), rb_sum=("rb_count", "sum"))
        .reset_index()
    )
    machine_baseline["baseline_rate"] = machine_baseline["rb_sum"] / machine_baseline["games_sum"]

    # 直近1ヶ月、非イベント日、既説明3日を除外
    recent = df[(df["date_dt"] > cutoff) & (~df["is_event_day"]) & (~df["date"].isin(EXPLAINED_DATES))].copy()
    recent = recent[recent["games_normalized"] >= MIN_GAMES]

    daily_machine = (
        recent.groupby(["machine_name", "date_dt", "day"])
        .agg(games_sum=("games_normalized", "sum"), rb_sum=("rb_count", "sum"))
        .reset_index()
        .merge(machine_baseline[["machine_name", "baseline_rate"]], on="machine_name")
    )
    daily_machine["rb_rate"] = daily_machine["rb_sum"] / daily_machine["games_sum"]
    daily_machine["lift"] = daily_machine["rb_rate"] / daily_machine["baseline_rate"] - 1

    se = (daily_machine["baseline_rate"] * (1 - daily_machine["baseline_rate"]) / daily_machine["games_sum"]) ** 0.5
    daily_machine["z"] = (daily_machine["rb_rate"] - daily_machine["baseline_rate"]) / se
    daily_machine["p_one_sided"] = 1 - norm.cdf(daily_machine["z"])

    n_tests = len(daily_machine)
    bonferroni = 0.05 / n_tests
    print(f"総検定数(機種×日): {n_tests}, Bonferroni閾値p<{bonferroni:.5f}")

    print("\n=== 機種別ベースライン ===")
    for _, row in machine_baseline.sort_values("baseline_rate", ascending=False).iterrows():
        print(f"  {row['machine_name']}: {row['baseline_rate']:.5f}(1/{1 / row['baseline_rate']:.1f})")

    top = daily_machine.sort_values("lift", ascending=False).head(20)
    print(f"\n=== 残り期間・機種×日 lift上位20件 ===")
    for _, row in top.iterrows():
        d = row["date_dt"].strftime("%Y-%m-%d(%a)")
        print(
            f"  {d} DD={row['day']:02d} {row['machine_name']}: games={row['games_sum']:.0f} "
            f"RB={row['rb_sum']:.0f} rate={row['rb_rate']:.5f}(1/{1 / row['rb_rate']:.1f}) "
            f"lift={row['lift']:+.1%} z={row['z']:.2f} p={row['p_one_sided']:.4f}"
        )

    survivors = daily_machine[daily_machine["p_one_sided"] < bonferroni]
    print(f"\n=== Bonferroni補正後も生き残る機種×日({len(survivors)}件) ===")
    if survivors.empty:
        print("  なし")
    else:
        for _, row in survivors.sort_values("p_one_sided").iterrows():
            d = row["date_dt"].strftime("%Y-%m-%d(%a)")
            print(
                f"  {d} DD={row['day']:02d} {row['machine_name']}: lift={row['lift']:+.1%} p={row['p_one_sided']:.5f}"
            )

    # 機種×DD番号（曜日でなく日付の日）の集約：同じDDが複数回出ていないか
    print("\n=== 機種×DD 集約(同じDDが複数日にまたがって出ていないか) ===")
    dd_agg = (
        daily_machine.groupby(["machine_name", "day"])
        .agg(n_days=("date_dt", "nunique"), lift_mean=("lift", "mean"))
        .reset_index()
    )
    dd_multi = dd_agg[dd_agg["n_days"] >= 2].sort_values("lift_mean", ascending=False)
    if dd_multi.empty:
        print("  この期間内では同一DDが複数回出現するケースなし(1ヶ月では月1回しか各DDが来ないため当然)")
    else:
        print(dd_multi.to_string(index=False))


if __name__ == "__main__":
    main()
