"""
522番(マギレコ角台)と近隣台番号の代替/シーソー関係の検証

eda/mitoya_dd_persistence_metric_comparison.py の3ヶ月windowでは期間数=6で
検出力不足だったため、以下2パターンで再検証する:

1. 1ヶ月windowクインタイル相関 (Xgroup, n≈18期間)
2. 日次差枚の直接相関 (全日, n≈525日)
"""
import sqlite3
from pathlib import Path

import pandas as pd
from scipy.stats import spearmanr

DB_PATH = Path(__file__).resolve().parents[1] / "db" / "みとや大森町店.db"

X_DDS = [4, 7, 14, 17, 24, 27]
N_BINS = 5
TARGET = 522
RADIUS = 5


def load_data() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT date, machine_number, diff_coins_normalized FROM machine_detailed_results",
        conn,
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["dd"] = df["date"].dt.day
    return df


def assign_period(dates: pd.Series, window_months: int) -> pd.Series:
    start = dates.min().to_period("M")
    return (dates.dt.to_period("M") - start).apply(lambda x: x.n) // window_months


def section_monthly_quintile(df: pd.DataFrame) -> None:
    print("\n##### 1. 1ヶ月windowクインタイル相関 (Xgroup) #####")
    sub = df[df["dd"].isin(X_DDS)].copy()
    sub["period"] = assign_period(sub["date"], 1)

    agg = (
        sub.groupby(["period", "machine_number"])["diff_coins_normalized"]
        .sum()
        .reset_index()
    )
    agg["quintile"] = agg.groupby("period")["diff_coins_normalized"].transform(
        lambda x: pd.qcut(x, N_BINS, labels=False, duplicates="drop") + 1
    )

    target = agg[agg["machine_number"] == TARGET].set_index("period")["quintile"]
    print(f"  522番 期間別クインタイル(n={len(target)}): {target.to_dict()}")

    neighbors = [n for n in range(TARGET - RADIUS, TARGET + RADIUS + 1) if n != TARGET]
    rows = []
    for m in neighbors:
        other = agg[agg["machine_number"] == m].set_index("period")["quintile"]
        common = target.index.intersection(other.index)
        if len(common) < 5:
            continue
        rho, pval = spearmanr(target.loc[common], other.loc[common])
        rows.append((m, len(common), rho, pval))

    rows.sort(key=lambda x: x[2])
    for m, n, rho, pval in rows:
        flag = " *" if pval < 0.05 else ""
        print(f"  522 vs {m}: n={n} rho={rho:.3f} (p={pval:.3f}){flag}")


def section_daily_correlation(df: pd.DataFrame) -> None:
    print("\n##### 2. 日次差枚の直接相関 (全日) #####")
    pivot = df.pivot_table(
        index="date", columns="machine_number", values="diff_coins_normalized"
    )
    if TARGET not in pivot.columns:
        print(f"  {TARGET}番のデータなし")
        return

    target = pivot[TARGET].dropna()
    neighbors = [n for n in range(TARGET - RADIUS, TARGET + RADIUS + 1) if n != TARGET]
    rows = []
    for m in neighbors:
        if m not in pivot.columns:
            continue
        other = pivot[m].dropna()
        common = target.index.intersection(other.index)
        if len(common) < 30:
            continue
        rho, pval = spearmanr(target.loc[common], other.loc[common])
        rows.append((m, len(common), rho, pval))

    rows.sort(key=lambda x: x[2])
    for m, n, rho, pval in rows:
        flag = " *" if pval < 0.05 else ""
        print(f"  522 vs {m}: n={n} rho={rho:.3f} (p={pval:.3f}){flag}")


def main() -> None:
    df = load_data()
    section_monthly_quintile(df)
    section_daily_correlation(df)


if __name__ == "__main__":
    main()
