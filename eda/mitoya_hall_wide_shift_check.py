"""
522番が直近2期間(1ヶ月window, Xgroup periods 15,16)で好調になったことが、
ホール全体の設定投入傾向パターンの変化(時期的な構造変化)によるものか、
あるいは522固有の要因(機種変更など)によるものかを切り分ける。

1. 期間(period)とカレンダー月の対応を確認
2. 522番のperiod別 machine_name を確認(機種変更の有無)
3. ホール全体の平均差枚・上位クインタイル閾値をperiod別に確認
   (period15,16前後で構造変化があるか)
4. 全266台のプラス率(差枚>0の割合)をperiod別に確認
"""
import sqlite3
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).resolve().parents[1] / "db" / "みとや大森町店.db"

X_DDS = [4, 7, 14, 17, 24, 27]
TARGET = 522


def load_data() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT date, machine_number, machine_name, diff_coins_normalized "
        "FROM machine_detailed_results",
        conn,
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["dd"] = df["date"].dt.day
    return df


def assign_period(dates: pd.Series, window_months: int) -> pd.Series:
    start = dates.min().to_period("M")
    return (dates.dt.to_period("M") - start).apply(lambda x: x.n) // window_months


def main() -> None:
    df = load_data()
    sub = df[df["dd"].isin(X_DDS)].copy()
    sub["period"] = assign_period(sub["date"], 1)
    sub["ym"] = sub["date"].dt.to_period("M")

    print("##### 1. period <-> カレンダー月 対応 #####")
    mapping = sub.groupby("period")["ym"].first()
    for p, ym in mapping.items():
        print(f"  period {p}: {ym}")

    print(f"\n##### 2. {TARGET}番のperiod別 machine_name #####")
    target_names = (
        sub[sub["machine_number"] == TARGET]
        .groupby("period")["machine_name"]
        .agg(lambda x: x.mode().iloc[0])
    )
    for p, name in target_names.items():
        marker = " <== 好調期" if p in (15, 16) else (" <== 不調期(直後)" if p == 17 else "")
        print(f"  period {p}: {name}{marker}")

    print("\n##### 3. ホール全体(266台)の差枚分布 (period別) #####")
    agg = (
        sub.groupby(["period", "machine_number"])["diff_coins_normalized"]
        .sum()
        .reset_index()
    )
    stats = agg.groupby("period")["diff_coins_normalized"].agg(
        mean="mean",
        std="std",
        median="median",
        q80=lambda x: x.quantile(0.8),
        q20=lambda x: x.quantile(0.2),
    )
    print(stats.round(1).to_string())

    print("\n##### 4. ホール全体プラス比率(差枚>0の台の割合) period別 #####")
    plus_ratio = agg.groupby("period")["diff_coins_normalized"].apply(lambda x: (x > 0).mean())
    print(plus_ratio.round(3).to_string())


if __name__ == "__main__":
    main()
