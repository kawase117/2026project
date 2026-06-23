"""
蒲田1・蒲田7: 曜日別(日曜)スクリーニング法則のバックテスト

eda/kamata_saturday_screening.py で見つかった
「payout_rate>=100% & diff_std<median (AT機, 全期間の日曜)」のスクリーニングを、
みとやのバックテスト手法(eda/mitoya_backtest_and_eventday_range.py)と同様に
walk-forward(各日曜より前の日曜データのみで判定)で検証する。

対象: machine_name単位(機種別)。台番号単位は機種数に対しサンプルが薄いため対象外。
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
TARGET_WEEKDAY = 6  # 6 = Sunday


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


def compute_history_agg(hist: pd.DataFrame) -> pd.DataFrame:
    agg = (
        hist.groupby("machine_name")
        .agg(
            diff_sum=("diff_coins_normalized", "sum"),
            games_sum=("games_normalized", "sum"),
            n_days=("diff_coins_normalized", "size"),
        )
    )
    agg = agg[agg["n_days"] >= MIN_DAYS].copy()
    if agg.empty:
        return agg
    agg["payout_rate"] = (
        (agg["games_sum"] * COINS_PER_GAME + agg["diff_sum"])
        / (agg["games_sum"] * COINS_PER_GAME)
        * 100
    )
    daily_std = (
        hist.groupby(["machine_name", "date"])["diff_coins_normalized"]
        .sum()
        .groupby("machine_name")
        .std()
    )
    agg["diff_std"] = daily_std
    return agg


def evaluate_strategy(res_df: pd.DataFrame, label: str) -> None:
    if res_df.empty:
        print(f"  [{label}] 検証可能なサンプルなし")
        return
    n = len(res_df)
    n_q = res_df["quintile"].nunique()
    baseline = 1.0 / n_q
    print(f"\n  [{label}] n={n} (対象日数={res_df['date'].nunique()})")
    for q in sorted(res_df["quintile"].unique()):
        rate = (res_df["quintile"] == q).mean()
        print(f"    Q{q}到達率: {rate:.3f} (期待値={baseline:.3f})")
    q1_rate = (res_df["quintile"] == res_df["quintile"].min()).mean()
    q5_rate = (res_df["quintile"] == res_df["quintile"].max()).mean()
    top2_rate = (res_df["quintile"] >= res_df["quintile"].max() - 1).mean()
    bottom2_rate = (res_df["quintile"] <= res_df["quintile"].min() + 1).mean()
    print(f"    Q1(最下位)到達率: {q1_rate:.3f} (期待値={baseline:.3f})")
    print(f"    Q5(最上位)到達率: {q5_rate:.3f} (期待値={baseline:.3f})")
    print(f"    Q4+Q5到達率: {top2_rate:.3f} (期待値={2*baseline:.3f})")
    print(f"    Q1+Q2到達率: {bottom2_rate:.3f} (期待値={2*baseline:.3f})")


def backtest_hall(name: str, db_name: str) -> None:
    db_path = DB_DIR / f"{db_name}.db"
    df = load(db_path)

    is_at = (
        (df["jug_flag"].fillna(0) == 0)
        & (df["hana_flag"].fillna(0) == 0)
        & (df["oki_flag"].fillna(0) == 0)
        & (df["bt_flag"].fillna(0) == 0)
    )
    sun = df[(df["date"].dt.dayofweek == TARGET_WEEKDAY) & is_at].copy()
    dates = sorted(sun["date"].unique())

    print(f"\n===== {name} ({db_name}) =====")
    print(f"対象: 日曜AT機, 日数={len(dates)}")

    if len(dates) <= MIN_DAYS:
        print("  サンプル不足")
        return

    results = []
    results_rev = []  # 戦略1: diff_std>=median & payout>=100% (高分散側)
    for target_date in dates:
        hist = sun[sun["date"] < target_date]
        if hist["date"].nunique() < MIN_DAYS:
            continue

        agg = compute_history_agg(hist)
        if len(agg) < 5:
            continue

        today = sun[sun["date"] == target_date]
        today_agg = today.groupby("machine_name")["diff_coins_normalized"].sum()
        if len(today_agg) < 5:
            continue
        quintile = pd.qcut(today_agg, 5, labels=False, duplicates="drop") + 1

        median_std = agg["diff_std"].median()
        candidates = agg[(agg["payout_rate"] >= 100) & (agg["diff_std"] < median_std)]
        for mname in candidates.index:
            if mname in quintile.index:
                results.append({
                    "date": target_date,
                    "machine_name": mname,
                    "quintile": quintile.loc[mname],
                })

        candidates_rev = agg[(agg["payout_rate"] >= 100) & (agg["diff_std"] >= median_std)]
        for mname in candidates_rev.index:
            if mname in quintile.index:
                results_rev.append({
                    "date": target_date,
                    "machine_name": mname,
                    "quintile": quintile.loc[mname],
                })

    res_df = pd.DataFrame(results)
    evaluate_strategy(res_df, "法則: diff_std<median & payout>=100% (日曜, machine_name単位)")
    if not res_df.empty:
        print("\n  [機種別集計 (上位10件)]")
        by_name = res_df.groupby("machine_name").agg(
            n=("quintile", "size"),
            mean_quintile=("quintile", "mean"),
        ).sort_values("mean_quintile", ascending=False)
        print(by_name.head(10).to_string())

        hokuto = by_name[by_name.index.str.contains("北斗", na=False)]
        if not hokuto.empty:
            print("\n  [北斗の拳のみ]")
            print(hokuto.to_string())

    res_rev_df = pd.DataFrame(results_rev)
    evaluate_strategy(res_rev_df, "戦略1: diff_std>=median(高分散) & payout>=100% (日曜, machine_name単位)")
    if not res_rev_df.empty:
        print("\n  [機種別集計 (上位10件)]")
        by_name_rev = res_rev_df.groupby("machine_name").agg(
            n=("quintile", "size"),
            mean_quintile=("quintile", "mean"),
        ).sort_values("mean_quintile", ascending=False)
        print(by_name_rev.head(10).to_string())

        hokuto_rev = by_name_rev[by_name_rev.index.str.contains("北斗", na=False)]
        if not hokuto_rev.empty:
            print("\n  [北斗の拳のみ]")
            print(hokuto_rev.to_string())


def main() -> None:
    for name, db_name in HALLS.items():
        backtest_hall(name, db_name)


if __name__ == "__main__":
    main()
