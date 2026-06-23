"""
蒲田1・蒲田7: 曜日別(日曜)候補台スクリーニング (2026-06-14は日曜)

事前確認: daily_hall_summaryのwin_rate/avg_diff_per_machineを曜日別集計すると、
両ホールとも「土」が最高(蒲田1: win_rate=41.9%, avg_diff=97.3 / 蒲田7: win_rate=43.1%, avg_diff=210.5)。
蒲田系はDD(4/7など)よりも曜日(特に日曜)の影響が強いという仮説に基づき、
Xgroupではなく「全期間の日曜日」でAT機をスクリーニングする。

手法(みとやのXgroup手法を曜日版に置換):
  payout_rate >= 100% AND diff_std < median(diff_std)
  対象: 全期間の日曜日・AT機(jug/hana/oki/bt flagが全て0)
  さらに上位候補は前半/後半split-halfでpayout_rateの持続性を確認する
"""
import sqlite3
from pathlib import Path

import pandas as pd

DB_DIR = Path(__file__).resolve().parents[1] / "db"

HALLS = {
    "蒲田1": "マルハンメガシティ2000-蒲田1",
    "蒲田7": "マルハンメガシティ2000-蒲田7",
}

COINS_PER_GAME = 3
MIN_DAYS = 10
TARGET_WEEKDAY = 6  # pandas dayofweek: 6 = Sunday (2026-06-14 is a Sunday)


def load(db_path: Path) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        "SELECT date, machine_number, machine_name, diff_coins_normalized, "
        "games_normalized FROM machine_detailed_results",
        conn,
    )
    master = pd.read_sql_query(
        "SELECT machine_name_normalized AS machine_name, jug_flag, hana_flag, "
        "oki_flag, bt_flag FROM machine_master",
        conn,
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df = df.merge(master, on="machine_name", how="left")
    return df


def payout_rate(g: pd.DataFrame) -> float:
    diff_sum = g["diff_coins_normalized"].sum()
    games_sum = g["games_normalized"].sum()
    return (games_sum * COINS_PER_GAME + diff_sum) / (games_sum * COINS_PER_GAME) * 100


def screen(name: str, db_name: str) -> None:
    db_path = DB_DIR / f"{db_name}.db"
    df = load(db_path)

    sat = df[df["date"].dt.dayofweek == TARGET_WEEKDAY].copy()
    n_sat = sat["date"].nunique()

    print(f"\n===== {name} ({db_name}) =====")
    print(f"対象: {sat['date'].min().date()} ~ {sat['date'].max().date()}, 日曜日数={n_sat}")

    is_at = (
        (sat["jug_flag"].fillna(0) == 0)
        & (sat["hana_flag"].fillna(0) == 0)
        & (sat["oki_flag"].fillna(0) == 0)
        & (sat["bt_flag"].fillna(0) == 0)
    )
    at = sat[is_at]

    agg = (
        at.groupby(["machine_number", "machine_name"])
        .agg(
            diff_sum=("diff_coins_normalized", "sum"),
            diff_std=("diff_coins_normalized", "std"),
            games_sum=("games_normalized", "sum"),
            n_days=("diff_coins_normalized", "size"),
        )
        .reset_index()
    )
    agg = agg[agg["n_days"] >= MIN_DAYS]
    agg["payout_rate"] = (
        (agg["games_sum"] * COINS_PER_GAME + agg["diff_sum"])
        / (agg["games_sum"] * COINS_PER_GAME)
        * 100
    )
    median_std = agg["diff_std"].median()
    print(f"AT機(jug/hana/oki/bt=0) 台数={len(agg)} (n_days>={MIN_DAYS}), diff_std median={median_std:.0f}")

    candidates = agg[(agg["payout_rate"] >= 100) & (agg["diff_std"] < median_std)].copy()
    stable_min_days = int(n_sat * 0.7)
    stable = candidates[candidates["n_days"] >= stable_min_days].sort_values(
        "payout_rate", ascending=False
    )
    print(f"\n候補({len(candidates)}台) -> 安定候補(n_days>={stable_min_days}, 上位8件):")
    print(
        stable.head(8)[["machine_number", "machine_name", "payout_rate", "diff_std", "n_days"]]
        .round({"payout_rate": 2, "diff_std": 0})
        .to_string(index=False)
    )

    # split-half persistence (前半/後半の日曜)
    sat_dates = sorted(sat["date"].unique())
    mid = len(sat_dates) // 2
    first_dates, second_dates = set(sat_dates[:mid]), set(sat_dates[mid:])

    rows = []
    for _, row in stable.head(8).iterrows():
        m = at[
            (at["machine_number"] == row["machine_number"])
            & (at["machine_name"] == row["machine_name"])
        ]
        first = m[m["date"].isin(first_dates)]
        second = m[m["date"].isin(second_dates)]
        if len(first) < 3 or len(second) < 3:
            continue
        rows.append(
            {
                "machine_number": row["machine_number"],
                "machine_name": row["machine_name"],
                "payout_first": payout_rate(first),
                "payout_second": payout_rate(second),
                "n_first": len(first),
                "n_second": len(second),
            }
        )
    if rows:
        sh = pd.DataFrame(rows)
        print(f"\nsplit-half検証 (前半{len(first_dates)}回 / 後半{len(second_dates)}回):")
        print(sh.round({"payout_first": 2, "payout_second": 2}).to_string(index=False))

    # ジャグラー機: 機械割上位を参考表示
    jug = sat[sat["jug_flag"].fillna(0) == 1]
    jug_agg = (
        jug.groupby(["machine_number", "machine_name"])
        .agg(
            diff_sum=("diff_coins_normalized", "sum"),
            diff_std=("diff_coins_normalized", "std"),
            games_sum=("games_normalized", "sum"),
            n_days=("diff_coins_normalized", "size"),
        )
        .reset_index()
    )
    jug_agg = jug_agg[jug_agg["n_days"] >= MIN_DAYS]
    jug_agg["payout_rate"] = (
        (jug_agg["games_sum"] * COINS_PER_GAME + jug_agg["diff_sum"])
        / (jug_agg["games_sum"] * COINS_PER_GAME)
        * 100
    )
    jug_top = jug_agg.sort_values("payout_rate", ascending=False).head(5)
    print(f"\nジャグラー機 日曜 上位5台 (n_days>={MIN_DAYS}):")
    print(
        jug_top[["machine_number", "machine_name", "payout_rate", "diff_std", "n_days"]]
        .round({"payout_rate": 2, "diff_std": 0})
        .to_string(index=False)
    )


def main() -> None:
    for name, db_name in HALLS.items():
        screen(name, db_name)


if __name__ == "__main__":
    main()
