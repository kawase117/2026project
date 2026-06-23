"""
2026-06-14 (DD=14, Xgroup={4,7,14,17,24,27}) の蒲田1・蒲田7 候補台スクリーニング

みとや大森町店で確立した手法(2026-06-14分析)を移植:
  payout_rate >= 100% AND diff_std < median(diff_std)
  対象: Xgroup日・直近6ヶ月・AT機(jug/hana/oki/bt flagが全て0の機種)
  ジャグラー機(jug_flag=1)は別枠で機械割上位を参考表示
"""
import sqlite3
from pathlib import Path

import pandas as pd

DB_DIR = Path(__file__).resolve().parents[1] / "db"

HALLS = {
    "蒲田1": "マルハンメガシティ2000-蒲田1",
    "蒲田7": "マルハンメガシティ2000-蒲田7",
}

X_DDS = [4, 7, 14, 17, 24, 27]
COINS_PER_GAME = 3
WINDOW_MONTHS = 6
MIN_DAYS = 10


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
    df["dd"] = df["date"].dt.day
    df = df.merge(master, on="machine_name", how="left")
    return df


def screen(name: str, db_name: str) -> None:
    db_path = DB_DIR / f"{db_name}.db"
    df = load(db_path)

    max_date = df["date"].max()
    cutoff = max_date - pd.DateOffset(months=WINDOW_MONTHS)
    sub = df[(df["dd"].isin(X_DDS)) & (df["date"] > cutoff)].copy()

    print(f"\n===== {name} ({db_name}) =====")
    print(f"対象期間: {cutoff.date()} ~ {max_date.date()}, Xgroup日数={sub['date'].nunique()}")

    is_at = (
        (sub["jug_flag"].fillna(0) == 0)
        & (sub["hana_flag"].fillna(0) == 0)
        & (sub["oki_flag"].fillna(0) == 0)
        & (sub["bt_flag"].fillna(0) == 0)
    )
    at = sub[is_at]

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
    candidates = candidates.sort_values("payout_rate", ascending=False)
    print(f"\n候補({len(candidates)}台): payout_rate>=100% AND diff_std<median (n_days>={MIN_DAYS})")

    # 安定候補: ほぼ全Xgroup日(直近6ヶ月=36日)に稼働している台に絞り込む
    stable_min_days = int(sub["date"].nunique() * 0.8)
    stable = candidates[candidates["n_days"] >= stable_min_days].sort_values(
        "payout_rate", ascending=False
    )
    print(f"\n安定候補(n_days>={stable_min_days}, 上位8件):")
    print(
        stable.head(8)[["machine_number", "machine_name", "payout_rate", "diff_std", "n_days"]]
        .round({"payout_rate": 2, "diff_std": 0})
        .to_string(index=False)
    )

    # ジャグラー機: 機械割上位を参考表示
    jug = sub[sub["jug_flag"].fillna(0) == 1]
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
    print(f"\nジャグラー機 上位5台 (n_days>={MIN_DAYS}):")
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
