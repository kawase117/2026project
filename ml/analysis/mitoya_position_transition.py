"""
みとや大森町店：ポジション遷移分析（末尾×角番）

「末尾Xが高成績 → 次回イベント日で末尾X/Yはどうなるか」
「角番が高成績 → 次回イベント日で角番はどうなるか」

前回イベント日での最高ポジション → 次回イベント日でのポジション遷移パターンを検証
"""

import sqlite3
from pathlib import Path
import pandas as pd
import numpy as np

DB_PATH = Path("db/みとや大森町店.db")

def load_xday_data():
    """X_day（イベント日）のセクション×末尾×角番成績を読み込み"""
    conn = sqlite3.connect(DB_PATH)

    df = pd.read_sql(
        """
        SELECT
            date,
            machine_number,
            last_digit,
            diff_coins_normalized
        FROM machine_detailed_results
        ORDER BY date, machine_number
        """,
        conn,
    )

    # 台配置情報
    layout = pd.read_sql(
        """
        SELECT
            machine_number,
            section,
            rank_from_aisle
        FROM machine_layout
        """,
        conn,
    )

    conn.close()

    df = df.merge(layout, on="machine_number", how="left")

    # X_day判定
    df["date_dt"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["dd"] = df["date_dt"].dt.day
    df["dd_mod"] = df["dd"] % 10
    df["is_xday"] = df["dd_mod"].isin([4, 7]).astype(int)
    df["dd_group"] = df["dd_mod"].apply(lambda x: "4系" if x == 4 else ("7系" if x == 7 else None))

    # 角番フラグ
    df["is_aisle_corner"] = (df["rank_from_aisle"] == 1).astype(int)
    section_max_aisle = df.groupby("section")["rank_from_aisle"].transform("max")
    df["is_far_corner"] = (df["rank_from_aisle"] == section_max_aisle).astype(int)

    return df[df["dd_group"].notna()].copy()


def analyze_dd_last_digit_transition(df):
    """
    末尾別の遷移パターン分析

    末尾4 or 末尾7 が高成績 → 次のイベント日での末尾別成績の遷移
    """
    print("=" * 80)
    print("1. 末尾（0-9）の遷移パターン分析")
    print("=" * 80)

    # イベント日のみ
    df_xday = df[df["is_xday"] == 1].copy()

    # 日別×末尾別の成績
    daily_digit = df_xday.groupby(["date", "last_digit"]).agg({
        "diff_coins_normalized": "mean",
        "machine_number": "count"
    }).reset_index()
    daily_digit.columns = ["date", "last_digit", "avg_diff", "n_machines"]

    # ソート
    daily_digit["date_dt"] = pd.to_datetime(daily_digit["date"], format="%Y%m%d")
    daily_digit = daily_digit.sort_values("date_dt")

    # 日ごとの最高末尾を抽出
    idx_max = daily_digit.groupby("date")["avg_diff"].idxmax()
    best_digit_daily = daily_digit.loc[idx_max, ["date", "last_digit", "avg_diff"]].copy()
    best_digit_daily.columns = ["date", "best_last_digit", "best_digit_diff"]
    best_digit_daily = best_digit_daily.sort_values("date")

    # イベント日のみ
    xday_dates = df_xday["date"].unique()
    best_digit_daily = best_digit_daily[best_digit_daily["date"].isin(xday_dates)].reset_index(drop=True)

    print(f"\nイベント日での最高末尾遷移: {len(best_digit_daily)} 日")

    # 遷移パターン
    best_digit_daily["date_dt"] = pd.to_datetime(best_digit_daily["date"], format="%Y%m%d")
    best_digit_daily["prev_best_digit"] = best_digit_daily["best_last_digit"].shift(1)
    best_digit_daily["prev_diff"] = best_digit_daily["best_digit_diff"].shift(1)
    best_digit_daily["next_best_digit"] = best_digit_daily["best_last_digit"].shift(-1)
    best_digit_daily["next_diff"] = best_digit_daily["best_digit_diff"].shift(-1)

    # 前回が高成績 → 次回の成績
    high_threshold = daily_digit["avg_diff"].median()

    transitions = best_digit_daily[best_digit_daily["prev_best_digit"].notna()].copy()

    print(f"\n前回イベント日の末尾別分析:")
    print(f"  遷移ケース数: {len(transitions)}")

    # 前回高 → 次回の成績分布
    prev_high = transitions[transitions["prev_diff"] >= high_threshold]
    print(f"\n  前回が高成績（>={high_threshold:.0f}円）の場合:")
    print(f"    ケース数: {len(prev_high)}")
    if len(prev_high) > 0:
        print(f"    次回の平均差枚: {prev_high['next_diff'].mean():.0f} 円")
        print(f"    前回より低くなる: {(prev_high['next_diff'] < prev_high['prev_diff']).sum() / len(prev_high) * 100:.1f}%")
        print(f"    前回より高くなる: {(prev_high['next_diff'] > prev_high['prev_diff']).sum() / len(prev_high) * 100:.1f}%")

    # 前回低 → 次回の成績分布
    prev_low = transitions[transitions["prev_diff"] < high_threshold]
    print(f"\n  前回が低成績（<{high_threshold:.0f}円）の場合:")
    print(f"    ケース数: {len(prev_low)}")
    if len(prev_low) > 0:
        print(f"    次回の平均差枚: {prev_low['next_diff'].mean():.0f} 円")
        print(f"    前回より低くなる: {(prev_low['next_diff'] < prev_low['prev_diff']).sum() / len(prev_low) * 100:.1f}%")
        print(f"    前回より高くなる: {(prev_low['next_diff'] > prev_low['prev_diff']).sum() / len(prev_low) * 100:.1f}%")

    # 末尾遷移の頻度（前回の最高末尾 → 次回の最高末尾）
    print(f"\n最高末尾の遷移パターン (Top 10):")
    digit_transitions = transitions.groupby(["prev_best_digit", "best_last_digit"]).size().reset_index(name="count")
    digit_transitions = digit_transitions.sort_values("count", ascending=False)
    for _, row in digit_transitions.head(10).iterrows():
        print(f"  末尾{int(row['prev_best_digit'])} → 末尾{int(row['best_last_digit'])}: {row['count']} 回")

    return best_digit_daily


def analyze_dd_group_transition(df):
    """
    DD系列（4系vs7系）での遷移パターンを詳細に分析
    """
    print("\n" + "=" * 80)
    print("2. DD系列（4系vs7系）の遷移パターン（詳細版）")
    print("=" * 80)

    df_xday = df[df["is_xday"] == 1].copy()

    # 日別×DD系別の成績
    daily_dd = df_xday.groupby(["date", "dd_group"]).agg({
        "diff_coins_normalized": "mean"
    }).reset_index()
    daily_dd.columns = ["date", "dd_group", "avg_diff"]

    daily_dd["date_dt"] = pd.to_datetime(daily_dd["date"], format="%Y%m%d")
    daily_dd = daily_dd.sort_values("date_dt")

    # イベント日のみでソート
    xday_dates = df_xday["date"].unique()
    daily_dd_xday = daily_dd[daily_dd["date"].isin(xday_dates)].sort_values("date_dt").reset_index(drop=True)

    print(f"\nイベント日数: {len(daily_dd_xday)} 日")

    median_4sys = daily_dd_xday[daily_dd_xday["dd_group"] == "4系"]["avg_diff"].median()
    median_7sys = daily_dd_xday[daily_dd_xday["dd_group"] == "7系"]["avg_diff"].median()

    # 前回4系が高い場合→次の7系はどうなるか
    transitions_4to7 = []
    for i in range(len(daily_dd_xday) - 1):
        if (daily_dd_xday.iloc[i]["dd_group"] == "4系" and
            daily_dd_xday.iloc[i+1]["dd_group"] == "7系"):
            transitions_4to7.append({
                "prev_dd": "4系",
                "prev_date": daily_dd_xday.iloc[i]["date"],
                "prev_diff": daily_dd_xday.iloc[i]["avg_diff"],
                "next_dd": "7系",
                "next_date": daily_dd_xday.iloc[i+1]["date"],
                "next_diff": daily_dd_xday.iloc[i+1]["avg_diff"]
            })

    df_trans_4to7 = pd.DataFrame(transitions_4to7)

    if len(df_trans_4to7) > 0:
        print(f"\n4系が高成績（>={median_4sys:.0f}円）→次の7系:")
        high_4 = df_trans_4to7[df_trans_4to7["prev_diff"] >= median_4sys]
        if len(high_4) > 0:
            print(f"  ケース数: {len(high_4)}")
            print(f"  次の7系の平均: {high_4['next_diff'].mean():.0f} 円")
            print(f"  7系で高成績：{(high_4['next_diff'] >= median_7sys).sum() / len(high_4) * 100:.1f}%")
            print(f"  7系で低成績：{(high_4['next_diff'] < median_7sys).sum() / len(high_4) * 100:.1f}%")

        print(f"\n4系が低成績（<{median_4sys:.0f}円）→次の7系:")
        low_4 = df_trans_4to7[df_trans_4to7["prev_diff"] < median_4sys]
        if len(low_4) > 0:
            print(f"  ケース数: {len(low_4)}")
            print(f"  次の7系の平均: {low_4['next_diff'].mean():.0f} 円")
            print(f"  7系で高成績：{(low_4['next_diff'] >= median_7sys).sum() / len(low_4) * 100:.1f}%")
            print(f"  7系で低成績：{(low_4['next_diff'] < median_7sys).sum() / len(low_4) * 100:.1f}%")

    # 7系→4系も同様
    transitions_7to4 = []
    for i in range(len(daily_dd_xday) - 1):
        if (daily_dd_xday.iloc[i]["dd_group"] == "7系" and
            daily_dd_xday.iloc[i+1]["dd_group"] == "4系"):
            transitions_7to4.append({
                "prev_dd": "7系",
                "prev_date": daily_dd_xday.iloc[i]["date"],
                "prev_diff": daily_dd_xday.iloc[i]["avg_diff"],
                "next_dd": "4系",
                "next_date": daily_dd_xday.iloc[i+1]["date"],
                "next_diff": daily_dd_xday.iloc[i+1]["avg_diff"]
            })

    df_trans_7to4 = pd.DataFrame(transitions_7to4)

    if len(df_trans_7to4) > 0:
        print(f"\n7系が高成績（>={median_7sys:.0f}円）→次の4系:")
        high_7 = df_trans_7to4[df_trans_7to4["prev_diff"] >= median_7sys]
        if len(high_7) > 0:
            print(f"  ケース数: {len(high_7)}")
            print(f"  次の4系の平均: {high_7['next_diff'].mean():.0f} 円")
            print(f"  4系で高成績：{(high_7['next_diff'] >= median_4sys).sum() / len(high_7) * 100:.1f}%")
            print(f"  4系で低成績：{(high_7['next_diff'] < median_4sys).sum() / len(high_7) * 100:.1f}%")

        print(f"\n7系が低成績（<{median_7sys:.0f}円）→次の4系:")
        low_7 = df_trans_7to4[df_trans_7to4["prev_diff"] < median_7sys]
        if len(low_7) > 0:
            print(f"  ケース数: {len(low_7)}")
            print(f"  次の4系の平均: {low_7['next_diff'].mean():.0f} 円")
            print(f"  4系で高成績：{(low_7['next_diff'] >= median_4sys).sum() / len(low_7) * 100:.1f}%")
            print(f"  4系で低成績：{(low_7['next_diff'] < median_4sys).sum() / len(low_7) * 100:.1f}%")


def analyze_corner_position_transition(df):
    """
    角番（通路側vs奥側）での遷移パターン分析
    """
    print("\n" + "=" * 80)
    print("3. 角番（通路側vs奥側）の遷移パターン（詳細版）")
    print("=" * 80)

    df_xday = df[df["is_xday"] == 1].copy()

    # 日別×角番別の成績
    daily_corner = df_xday.groupby(["date", "is_aisle_corner"]).agg({
        "diff_coins_normalized": "mean"
    }).reset_index()
    daily_corner.columns = ["date", "is_aisle_corner", "avg_diff"]

    daily_corner["corner_name"] = daily_corner["is_aisle_corner"].apply(lambda x: "通路側" if x == 1 else "奥側")
    daily_corner["date_dt"] = pd.to_datetime(daily_corner["date"], format="%Y%m%d")

    xday_dates = df_xday["date"].unique()
    daily_corner_xday = daily_corner[daily_corner["date"].isin(xday_dates)].sort_values("date_dt").reset_index(drop=True)

    print(f"\nイベント日での角番成績遷移: {len(daily_corner_xday)} 日")

    median_aisle = daily_corner_xday[daily_corner_xday["is_aisle_corner"] == 1]["avg_diff"].median()
    median_far = daily_corner_xday[daily_corner_xday["is_aisle_corner"] == 0]["avg_diff"].median()

    # 通路側→奥側の遷移を追跡
    transitions_aisle_to_far = []
    for i in range(len(daily_corner_xday) - 1):
        if (daily_corner_xday.iloc[i]["is_aisle_corner"] == 1 and
            daily_corner_xday.iloc[i+1]["is_aisle_corner"] == 0):
            transitions_aisle_to_far.append({
                "prev_corner": "通路側",
                "prev_diff": daily_corner_xday.iloc[i]["avg_diff"],
                "next_corner": "奥側",
                "next_diff": daily_corner_xday.iloc[i+1]["avg_diff"]
            })
        elif (daily_corner_xday.iloc[i]["is_aisle_corner"] == 0 and
              daily_corner_xday.iloc[i+1]["is_aisle_corner"] == 1):
            transitions_aisle_to_far.append({
                "prev_corner": "奥側",
                "prev_diff": daily_corner_xday.iloc[i]["avg_diff"],
                "next_corner": "通路側",
                "next_diff": daily_corner_xday.iloc[i+1]["avg_diff"]
            })

    df_trans_corner = pd.DataFrame(transitions_aisle_to_far)

    if len(df_trans_corner) > 0:
        print(f"\n通路側が高成績（>={median_aisle:.0f}円）→次の奥側:")
        high_aisle = df_trans_corner[
            (df_trans_corner["prev_corner"] == "通路側") &
            (df_trans_corner["prev_diff"] >= median_aisle) &
            (df_trans_corner["next_corner"] == "奥側")
        ]
        if len(high_aisle) > 0:
            print(f"  ケース数: {len(high_aisle)}")
            print(f"  次の奥側の平均: {high_aisle['next_diff'].mean():.0f} 円")
            print(f"  奥側で高成績：{(high_aisle['next_diff'] >= median_far).sum() / len(high_aisle) * 100:.1f}%")
            print(f"  奥側で低成績：{(high_aisle['next_diff'] < median_far).sum() / len(high_aisle) * 100:.1f}%")

        print(f"\n奥側が高成績（>={median_far:.0f}円）→次の通路側:")
        high_far = df_trans_corner[
            (df_trans_corner["prev_corner"] == "奥側") &
            (df_trans_corner["prev_diff"] >= median_far) &
            (df_trans_corner["next_corner"] == "通路側")
        ]
        if len(high_far) > 0:
            print(f"  ケース数: {len(high_far)}")
            print(f"  次の通路側の平均: {high_far['next_diff'].mean():.0f} 円")
            print(f"  通路側で高成績：{(high_far['next_diff'] >= median_aisle).sum() / len(high_far) * 100:.1f}%")
            print(f"  通路側で低成績：{(high_far['next_diff'] < median_aisle).sum() / len(high_far) * 100:.1f}%")


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("みとや大森町店：ポジション遷移分析（末尾×角番）")
    print("=" * 80)

    df = load_xday_data()
    print(f"\nイベント日データ読み込み完了")

    # 分析実行
    best_digit_daily = analyze_dd_last_digit_transition(df)
    analyze_dd_group_transition(df)
    analyze_corner_position_transition(df)

    # 結果保存
    print("\n" + "=" * 80)
    print("結果保存")
    print("=" * 80)

    output_dir = Path("ml/analysis/results")
    output_dir.mkdir(parents=True, exist_ok=True)

    best_digit_daily.to_csv(output_dir / "mitoya_best_digit_daily.csv", index=False)
    print(f"✓ 日別最高末尾: {output_dir / 'mitoya_best_digit_daily.csv'}")

    print("\n" + "=" * 80)
    print("分析完了")
    print("=" * 80)
