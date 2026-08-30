"""
みとや大森町店: 8/8(強ゾロ目)・8/10(蒲田1周年対抗仮説)・8/5(5のつく日)の
3日について、ジャグラー機種別にRB率を機種固有ベースライン比で評価する。
"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DB_PATH = Path(__file__).resolve().parents[1] / "db" / "みとや大森町店.db"
X_DDS = {4, 7, 14, 17, 24, 27}
TARGET_DATES = {
    "20260808": "強ゾロ目(8/8)",
    "20260810": "蒲田1周年対抗仮説(8/10)",
    "20260805": "5のつく日(8/5)",
}


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

    # 機種固有ベースライン(全期間・非イベント日)
    baseline = df[~df["is_event_day"]]
    machine_baseline = (
        baseline.groupby("machine_name")
        .agg(games_sum=("games_normalized", "sum"), rb_sum=("rb_count", "sum"))
        .reset_index()
    )
    machine_baseline["baseline_rate"] = machine_baseline["rb_sum"] / machine_baseline["games_sum"]

    print("=== 機種別ベースラインRB率(全期間・非イベント日) ===")
    for _, row in machine_baseline.sort_values("baseline_rate", ascending=False).iterrows():
        print(f"  {row['machine_name']}: {row['baseline_rate']:.5f}(1/{1 / row['baseline_rate']:.1f})")

    for d, label in TARGET_DATES.items():
        sub = df[df["date"] == d].copy()
        sub = sub.merge(machine_baseline[["machine_name", "baseline_rate"]], on="machine_name")
        by_machine = (
            sub.groupby(["machine_name", "baseline_rate"])
            .agg(games_sum=("games_normalized", "sum"), rb_sum=("rb_count", "sum"))
            .reset_index()
        )
        by_machine["rb_rate"] = by_machine["rb_sum"] / by_machine["games_sum"]
        by_machine["lift_vs_own_baseline"] = by_machine["rb_rate"] / by_machine["baseline_rate"] - 1
        by_machine = by_machine.sort_values("lift_vs_own_baseline", ascending=False)

        print(f"\n=== {d[:4]}-{d[4:6]}-{d[6:]} : {label} ===")
        for _, row in by_machine.iterrows():
            print(
                f"  {row['machine_name']}: games={row['games_sum']:.0f} RB={row['rb_sum']:.0f} "
                f"当日RB率={row['rb_rate']:.5f}(1/{1 / row['rb_rate']:.1f}) "
                f"機種ベース={row['baseline_rate']:.5f}(1/{1 / row['baseline_rate']:.1f}) "
                f"機種内lift={row['lift_vs_own_baseline']:+.1%}"
            )


if __name__ == "__main__":
    main()
