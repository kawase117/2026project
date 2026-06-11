"""
DD系列遷移パターンの詳細分析

4系→7系 と 7系→4系 での成績パターンを調査
「4系が高い→7系は低くなる」のような交互パターンがあるか検証
"""

import sqlite3
from pathlib import Path
import pandas as pd
import numpy as np
from scipy import stats

DB_PATH = Path("db/みとや大森町店.db")

def load_xday_data():
    """X_day（イベント日）データを読み込み"""
    conn = sqlite3.connect(DB_PATH)

    df = pd.read_sql(
        """
        SELECT
            date,
            diff_coins_normalized
        FROM machine_detailed_results
        ORDER BY date
        """,
        conn,
    )

    daily = pd.read_sql(
        """
        SELECT
            date,
            day_of_week
        FROM daily_hall_summary
        """,
        conn,
    )

    conn.close()

    daily_agg = df.groupby("date").agg({
        "diff_coins_normalized": "mean"
    }).reset_index()
    daily_agg.columns = ["date", "avg_diff"]

    daily = daily.merge(daily_agg, on="date", how="left")

    # X_day判定
    daily["date_dt"] = pd.to_datetime(daily["date"], format="%Y%m%d")
    daily["dd"] = daily["date_dt"].dt.day
    daily["dd_mod"] = daily["dd"] % 10
    daily["is_xday"] = daily["dd_mod"].isin([4, 7]).astype(int)
    daily["dd_group"] = daily["dd_mod"].apply(lambda x: "4系" if x == 4 else ("7系" if x == 7 else None))

    daily = daily[daily["dd_group"].notna()].sort_values("date_dt").reset_index(drop=True)

    return daily


def analyze_dd_transition(daily):
    """
    DD系列の遷移パターンを分析
    4系→7系 と 7系→4系 での成績変動
    """
    daily["next_dd_group"] = daily["dd_group"].shift(-1)
    daily["next_avg_diff"] = daily["avg_diff"].shift(-1)

    print("=" * 80)
    print("DD系列遷移パターン分析")
    print("=" * 80)

    # 1. 4系→7系の遷移
    transition_4to7 = daily[daily["dd_group"] == "4系"].copy()
    transition_4to7 = transition_4to7[transition_4to7["next_dd_group"] == "7系"]

    print(f"\n4系→7系遷移: {len(transition_4to7)} ケース")
    if len(transition_4to7) > 0:
        print(f"  4系の平均差枚: {transition_4to7['avg_diff'].mean():.0f} 円")
        print(f"  次の7系の平均差枚: {transition_4to7['next_avg_diff'].mean():.0f} 円")
        print(f"  差分（7系 - 4系）: {transition_4to7['next_avg_diff'].mean() - transition_4to7['avg_diff'].mean():.0f} 円")

        # 4系が高い場合と低い場合で分離
        median_4sys = daily[daily["dd_group"] == "4系"]["avg_diff"].median()

        high_4sys = transition_4to7[transition_4to7["avg_diff"] >= median_4sys]
        low_4sys = transition_4to7[transition_4to7["avg_diff"] < median_4sys]

        print(f"\n  4系が高成績（>={median_4sys:.0f}円）の場合:")
        print(f"    ケース数: {len(high_4sys)}")
        if len(high_4sys) > 0:
            print(f"    次の7系の平均差枚: {high_4sys['next_avg_diff'].mean():.0f} 円")
            print(f"    落ち込み率（7系が4系より低い）: {(high_4sys['next_avg_diff'] < high_4sys['avg_diff']).sum() / len(high_4sys) * 100:.1f}%")

        print(f"\n  4系が低成績（<{median_4sys:.0f}円）の場合:")
        print(f"    ケース数: {len(low_4sys)}")
        if len(low_4sys) > 0:
            print(f"    次の7系の平均差枚: {low_4sys['next_avg_diff'].mean():.0f} 円")
            print(f"    改善率（7系が4系より高い）: {(low_4sys['next_avg_diff'] > low_4sys['avg_diff']).sum() / len(low_4sys) * 100:.1f}%")

    # 2. 7系→4系の遷移
    transition_7to4 = daily[daily["dd_group"] == "7系"].copy()
    transition_7to4 = transition_7to4[transition_7to4["next_dd_group"] == "4系"]

    print(f"\n7系→4系遷移: {len(transition_7to4)} ケース")
    if len(transition_7to4) > 0:
        print(f"  7系の平均差枚: {transition_7to4['avg_diff'].mean():.0f} 円")
        print(f"  次の4系の平均差枚: {transition_7to4['next_avg_diff'].mean():.0f} 円")
        print(f"  差分（4系 - 7系）: {transition_7to4['next_avg_diff'].mean() - transition_7to4['avg_diff'].mean():.0f} 円")

        # 7系が高い場合と低い場合で分離
        median_7sys = daily[daily["dd_group"] == "7系"]["avg_diff"].median()

        high_7sys = transition_7to4[transition_7to4["avg_diff"] >= median_7sys]
        low_7sys = transition_7to4[transition_7to4["avg_diff"] < median_7sys]

        print(f"\n  7系が高成績（>={median_7sys:.0f}円）の場合:")
        print(f"    ケース数: {len(high_7sys)}")
        if len(high_7sys) > 0:
            print(f"    次の4系の平均差枚: {high_7sys['next_avg_diff'].mean():.0f} 円")
            print(f"    落ち込み率（4系が7系より低い）: {(high_7sys['next_avg_diff'] < high_7sys['avg_diff']).sum() / len(high_7sys) * 100:.1f}%")

        print(f"\n  7系が低成績（<{median_7sys:.0f}円）の場合:")
        print(f"    ケース数: {len(low_7sys)}")
        if len(low_7sys) > 0:
            print(f"    次の4系の平均差枚: {low_7sys['next_avg_diff'].mean():.0f} 円")
            print(f"    改善率（4系が7系より高い）: {(low_7sys['next_avg_diff'] > low_7sys['avg_diff']).sum() / len(low_7sys) * 100:.1f}%")

    return {
        "transition_4to7": transition_4to7,
        "transition_7to4": transition_7to4
    }


def analyze_dd_oscillation(daily):
    """
    DD系列が交互に振動するパターンを検出
    4系が高い→7系が低い→4系が高い... のような周期的なパターン
    """
    print("\n" + "=" * 80)
    print("DD系列振動パターン（交互高低）")
    print("=" * 80)

    daily_sorted = daily.sort_values("date_dt").reset_index(drop=True)

    # 連続3日分でのパターンマッチ
    oscillation_cases = []

    for i in range(len(daily_sorted) - 2):
        day1 = daily_sorted.iloc[i]
        day2 = daily_sorted.iloc[i + 1]
        day3 = daily_sorted.iloc[i + 2]

        # パターン1: 4系高 → 7系低 → 4系高
        if (day1["dd_group"] == "4系" and day2["dd_group"] == "7系" and day3["dd_group"] == "4系" and
            day1["avg_diff"] > day2["avg_diff"] and day3["avg_diff"] > day2["avg_diff"]):
            oscillation_cases.append({
                "pattern": "4高→7低→4高",
                "date1": day1["date"],
                "diff1": day1["avg_diff"],
                "date2": day2["date"],
                "diff2": day2["avg_diff"],
                "date3": day3["date"],
                "diff3": day3["avg_diff"]
            })

        # パターン2: 7系高 → 4系低 → 7系高
        if (day1["dd_group"] == "7系" and day2["dd_group"] == "4系" and day3["dd_group"] == "7系" and
            day1["avg_diff"] > day2["avg_diff"] and day3["avg_diff"] > day2["avg_diff"]):
            oscillation_cases.append({
                "pattern": "7高→4低→7高",
                "date1": day1["date"],
                "diff1": day1["avg_diff"],
                "date2": day2["date"],
                "diff2": day2["avg_diff"],
                "date3": day3["date"],
                "diff3": day3["avg_diff"]
            })

    oscillation_df = pd.DataFrame(oscillation_cases)

    if len(oscillation_df) > 0:
        print(f"\n振動パターン検出: {len(oscillation_df)} ケース")
        pattern_counts = oscillation_df["pattern"].value_counts()
        for pattern, count in pattern_counts.items():
            print(f"  {pattern}: {count} ケース")

        print("\n具体例（直近10件）:")
        for _, row in oscillation_df.tail(10).iterrows():
            print(f"  {row['date1']} {row['diff1']:+.0f}円 → {row['date2']} {row['diff2']:+.0f}円 → {row['date3']} {row['diff3']:+.0f}円  [{row['pattern']}]")
    else:
        print("\n振動パターン: 検出なし")

    return oscillation_df


def find_dd_group_antipattern(daily):
    """
    「4系で高い場合、次の7系は必ず低い」というような法則を探索
    """
    print("\n" + "=" * 80)
    print("DD系列アンチパターンの統計検証")
    print("=" * 80)

    # 4系の高/低と次の7系の高/低をクロス集計
    data_4to7 = daily[daily["dd_group"] == "4系"].copy()
    data_4to7 = data_4to7[data_4to7["next_dd_group"] == "7系"]

    if len(data_4to7) > 0:
        median_4sys = daily[daily["dd_group"] == "4系"]["avg_diff"].median()
        median_7sys = daily[daily["dd_group"] == "7系"]["avg_diff"].median()

        data_4to7["is_high_4"] = (data_4to7["avg_diff"] >= median_4sys).astype(int)
        data_4to7["is_high_7"] = (data_4to7["next_avg_diff"] >= median_7sys).astype(int)

        crosstab = pd.crosstab(
            data_4to7["is_high_4"],
            data_4to7["is_high_7"],
            margins=True,
            margins_name="計"
        )
        crosstab.index = ["4系低", "4系高", "計"]
        crosstab.columns = ["7系低", "7系高", "計"]

        print("\n4系→7系 のクロス集計:")
        print(crosstab)

        # 4系高の時に7系低くなる確率
        high_4_then_low_7 = (
            (data_4to7["is_high_4"] == 1) &
            (data_4to7["is_high_7"] == 0)
        ).sum()

        if (data_4to7["is_high_4"] == 1).sum() > 0:
            prob = high_4_then_low_7 / (data_4to7["is_high_4"] == 1).sum()
            print(f"\n4系が高い場合、次の7系が低くなる確率: {prob*100:.1f}%")

    # 7系→4系も同様
    data_7to4 = daily[daily["dd_group"] == "7系"].copy()
    data_7to4 = data_7to4[data_7to4["next_dd_group"] == "4系"]

    if len(data_7to4) > 0:
        median_4sys = daily[daily["dd_group"] == "4系"]["avg_diff"].median()
        median_7sys = daily[daily["dd_group"] == "7系"]["avg_diff"].median()

        data_7to4["is_high_7"] = (data_7to4["avg_diff"] >= median_7sys).astype(int)
        data_7to4["is_high_4"] = (data_7to4["next_avg_diff"] >= median_4sys).astype(int)

        crosstab = pd.crosstab(
            data_7to4["is_high_7"],
            data_7to4["is_high_4"],
            margins=True,
            margins_name="計"
        )
        crosstab.index = ["7系低", "7系高", "計"]
        crosstab.columns = ["4系低", "4系高", "計"]

        print("\n7系→4系 のクロス集計:")
        print(crosstab)

        # 7系高の時に4系低くなる確率
        high_7_then_low_4 = (
            (data_7to4["is_high_7"] == 1) &
            (data_7to4["is_high_4"] == 0)
        ).sum()

        if (data_7to4["is_high_7"] == 1).sum() > 0:
            prob = high_7_then_low_4 / (data_7to4["is_high_7"] == 1).sum()
            print(f"\n7系が高い場合、次の4系が低くなる確率: {prob*100:.1f}%")


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("みとや大森町店：DD系列遷移パターン詳細分析")
    print("=" * 80)

    daily = load_xday_data()
    print(f"\nイベント日データ読み込み完了: {len(daily)} 日")
    print(f"  4系: {(daily['dd_group'] == '4系').sum()} 日")
    print(f"  7系: {(daily['dd_group'] == '7系').sum()} 日")

    # 分析実行
    transition_result = analyze_dd_transition(daily)
    oscillation_df = analyze_dd_oscillation(daily)
    find_dd_group_antipattern(daily)

    # 結果保存
    print("\n" + "=" * 80)
    print("結果保存")
    print("=" * 80)

    output_dir = Path("ml/analysis/results")
    output_dir.mkdir(parents=True, exist_ok=True)

    if len(oscillation_df) > 0:
        oscillation_df.to_csv(output_dir / "mitoya_dd_oscillation_pattern.csv", index=False)
        print(f"DD振動パターン: {output_dir / 'mitoya_dd_oscillation_pattern.csv'}")

    print("\n分析完了")
    print("=" * 80)
