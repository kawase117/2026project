"""
みとや大森町店：角番（rank_from_aisle）でのアンチパターン分析

通路側角番（rank_from_aisle=1）と奥側角番（壁側）での成績パターンを分析
「通路側が高い→奥側は低い」のような交互パターンがあるか検証
"""

import sqlite3
from pathlib import Path
import pandas as pd
import numpy as np

DB_PATH = Path("db/みとや大森町店.db")

def load_corner_data():
    """角番別データを読み込み"""
    conn = sqlite3.connect(DB_PATH)

    # 機械詳細データ
    df = pd.read_sql(
        """
        SELECT
            date,
            machine_number,
            diff_coins_normalized
        FROM machine_detailed_results
        ORDER BY date, machine_number
        """,
        conn,
    )

    # 台配置情報（角番）
    layout = pd.read_sql(
        """
        SELECT
            machine_number,
            section,
            rank_from_aisle,
            rank_from_min,
            rank_from_max,
            is_reversed_section
        FROM machine_layout
        """,
        conn,
    )

    conn.close()

    # マージ
    df = df.merge(layout, on="machine_number", how="left")

    # 角番カテゴリを定義
    # rank_from_aisle=1: 通路側角番
    # rank_from_aisle=max: 奥側角番（壁側）
    df["is_aisle_corner"] = (df["rank_from_aisle"] == 1).astype(int)

    # セクション内での最大rank_from_aisle
    section_max_aisle = df.groupby("section")["rank_from_aisle"].transform("max")
    df["is_far_corner"] = (df["rank_from_aisle"] == section_max_aisle).astype(int)

    return df


def analyze_daily_corner_pattern(df):
    """日別で角番ごとの成績を集計"""
    print("=" * 80)
    print("1. 日別×角番別の成績パターン")
    print("=" * 80)

    # 通路側角番
    aisle_daily = df[df["is_aisle_corner"] == 1].groupby("date").agg({
        "diff_coins_normalized": "mean",
        "machine_number": "count"
    }).reset_index()
    aisle_daily.columns = ["date", "aisle_avg_diff", "aisle_count"]

    # 奥側角番
    far_daily = df[df["is_far_corner"] == 1].groupby("date").agg({
        "diff_coins_normalized": "mean",
        "machine_number": "count"
    }).reset_index()
    far_daily.columns = ["date", "far_avg_diff", "far_count"]

    # マージ
    daily_corner = aisle_daily.merge(far_daily, on="date", how="outer")
    daily_corner["date_dt"] = pd.to_datetime(daily_corner["date"], format="%Y%m%d")
    daily_corner = daily_corner.sort_values("date_dt")

    # X_day判定
    daily_corner["dd"] = daily_corner["date_dt"].dt.day
    daily_corner["dd_mod"] = daily_corner["dd"] % 10
    daily_corner["is_xday"] = daily_corner["dd_mod"].isin([4, 7]).astype(int)

    # イベント日のみ
    xday_corner = daily_corner[daily_corner["is_xday"] == 1].copy()

    print(f"\nイベント日数: {len(xday_corner)} 日")
    print(f"\n通路側角番:")
    print(f"  平均差枚: {xday_corner['aisle_avg_diff'].mean():.0f} 円")
    print(f"  中央値: {xday_corner['aisle_avg_diff'].median():.0f} 円")
    print(f"  最高: {xday_corner['aisle_avg_diff'].max():.0f} 円")
    print(f"  最低: {xday_corner['aisle_avg_diff'].min():.0f} 円")

    print(f"\n奥側角番:")
    print(f"  平均差枚: {xday_corner['far_avg_diff'].mean():.0f} 円")
    print(f"  中央値: {xday_corner['far_avg_diff'].median():.0f} 円")
    print(f"  最高: {xday_corner['far_avg_diff'].max():.0f} 円")
    print(f"  最低: {xday_corner['far_avg_diff'].min():.0f} 円")

    return daily_corner, xday_corner


def analyze_corner_reversal(xday_corner):
    """角番同士のreversal（逆相関）を分析"""
    print("\n" + "=" * 80)
    print("2. 角番同士の Reversal パターン")
    print("=" * 80)

    # 次のイベント日の成績
    xday_corner["next_aisle_avg_diff"] = xday_corner["aisle_avg_diff"].shift(-1)
    xday_corner["next_far_avg_diff"] = xday_corner["far_avg_diff"].shift(-1)

    median_aisle = xday_corner["aisle_avg_diff"].median()
    median_far = xday_corner["far_avg_diff"].median()

    # 当日高成績→翌イベント日の変動
    xday_corner["aisle_is_high"] = (xday_corner["aisle_avg_diff"] >= median_aisle).astype(int)
    xday_corner["far_is_high"] = (xday_corner["far_avg_diff"] >= median_far).astype(int)
    xday_corner["next_aisle_is_high"] = (xday_corner["next_aisle_avg_diff"] >= median_aisle).astype(int)
    xday_corner["next_far_is_high"] = (xday_corner["next_far_avg_diff"] >= median_far).astype(int)

    print(f"\n通路側角番が高成績の場合:")
    aisle_high = xday_corner[xday_corner["aisle_is_high"] == 1]
    if len(aisle_high) > 0:
        print(f"  当日高成績ケース: {len(aisle_high)} 日")
        print(f"  次のイベント日での奥側角番の平均差枚: {aisle_high['next_far_avg_diff'].mean():.0f} 円")
        print(f"  奥側が高成績→低成績に落ち込み: {(aisle_high['far_avg_diff'] > aisle_high['next_far_avg_diff']).sum() / len(aisle_high) * 100:.1f}%")

    print(f"\n奥側角番が高成績の場合:")
    far_high = xday_corner[xday_corner["far_is_high"] == 1]
    if len(far_high) > 0:
        print(f"  当日高成績ケース: {len(far_high)} 日")
        print(f"  次のイベント日での通路側角番の平均差枚: {far_high['next_aisle_avg_diff'].mean():.0f} 円")
        print(f"  通路側が高成績→低成績に落ち込み: {(far_high['aisle_avg_diff'] > far_high['next_aisle_avg_diff']).sum() / len(far_high) * 100:.1f}%")

    return xday_corner


def analyze_corner_oscillation(xday_corner):
    """角番が交互に高い/低いパターンを検出"""
    print("\n" + "=" * 80)
    print("3. 角番振動パターン（交互高低）")
    print("=" * 80)

    oscillation_cases = []

    for i in range(len(xday_corner) - 2):
        day1 = xday_corner.iloc[i]
        day2 = xday_corner.iloc[i + 1]
        day3 = xday_corner.iloc[i + 2]

        # パターン1: 通路側高 → 奥側低 → 通路側高
        if (day1["aisle_avg_diff"] > day1["far_avg_diff"] and
            day2["far_avg_diff"] > day2["aisle_avg_diff"] and
            day3["aisle_avg_diff"] > day3["far_avg_diff"]):
            oscillation_cases.append({
                "pattern": "通路高→奥低→通路高",
                "date1": day1["date"],
                "aisle1": day1["aisle_avg_diff"],
                "far1": day1["far_avg_diff"],
                "date2": day2["date"],
                "aisle2": day2["aisle_avg_diff"],
                "far2": day2["far_avg_diff"],
                "date3": day3["date"],
                "aisle3": day3["aisle_avg_diff"],
                "far3": day3["far_avg_diff"]
            })

        # パターン2: 奥側高 → 通路側低 → 奥側高
        if (day1["far_avg_diff"] > day1["aisle_avg_diff"] and
            day2["aisle_avg_diff"] > day2["far_avg_diff"] and
            day3["far_avg_diff"] > day3["aisle_avg_diff"]):
            oscillation_cases.append({
                "pattern": "奥高→通路低→奥高",
                "date1": day1["date"],
                "aisle1": day1["aisle_avg_diff"],
                "far1": day1["far_avg_diff"],
                "date2": day2["date"],
                "aisle2": day2["aisle_avg_diff"],
                "far2": day2["far_avg_diff"],
                "date3": day3["date"],
                "aisle3": day3["aisle_avg_diff"],
                "far3": day3["far_avg_diff"]
            })

    oscillation_df = pd.DataFrame(oscillation_cases)

    if len(oscillation_df) > 0:
        print(f"\n振動パターン検出: {len(oscillation_df)} ケース")
        pattern_counts = oscillation_df["pattern"].value_counts()
        for pattern, count in pattern_counts.items():
            print(f"  {pattern}: {count} ケース")

        print("\n具体例（直近10件）:")
        for _, row in oscillation_df.tail(10).iterrows():
            print(f"  {row['date1']} 通路{row['aisle1']:+.0f}/奥{row['far1']:+.0f} → " +
                  f"{row['date2']} 通路{row['aisle2']:+.0f}/奥{row['far2']:+.0f} → " +
                  f"{row['date3']} 通路{row['aisle3']:+.0f}/奥{row['far3']:+.0f}  [{row['pattern']}]")
    else:
        print("\n振動パターン: 検出なし")

    return oscillation_df


def analyze_corner_antipattern_stats(xday_corner):
    """角番間のアンチパターンを統計検証"""
    print("\n" + "=" * 80)
    print("4. 角番アンチパターンの統計検証")
    print("=" * 80)

    median_aisle = xday_corner["aisle_avg_diff"].median()
    median_far = xday_corner["far_avg_diff"].median()

    xday_corner["aisle_is_high"] = (xday_corner["aisle_avg_diff"] >= median_aisle).astype(int)
    xday_corner["far_is_high"] = (xday_corner["far_avg_diff"] >= median_far).astype(int)

    crosstab = pd.crosstab(
        xday_corner["aisle_is_high"],
        xday_corner["far_is_high"],
        margins=True,
        margins_name="計"
    )
    crosstab.index = ["通路低", "通路高", "計"]
    crosstab.columns = ["奥低", "奥高", "計"]

    print("\n通路側 vs 奥側 のクロス集計:")
    print(crosstab)

    # 相関係数
    corr = xday_corner["aisle_avg_diff"].corr(xday_corner["far_avg_diff"])
    print(f"\n相関係数: {corr:.3f}")
    if corr < -0.1:
        print(f"  → 逆相関あり（通路が高い日は奥が低い傾向）")
    elif corr > 0.1:
        print(f"  → 順相関あり（通路と奥が同調する傾向）")
    else:
        print(f"  → 相関なし（独立している）")


def analyze_section_corner_interaction(df):
    """セクション別での角番パターンを分析（蒲田七のA型/BT分析に相当）"""
    print("\n" + "=" * 80)
    print("5. セクション別×角番の相互作用パターン")
    print("=" * 80)

    # X_day のみフィルタ
    df_xday = df.copy()
    df_xday["date_dt"] = pd.to_datetime(df_xday["date"], format="%Y%m%d")
    df_xday["dd"] = df_xday["date_dt"].dt.day
    df_xday["dd_mod"] = df_xday["dd"] % 10
    df_xday = df_xday[df_xday["dd_mod"].isin([4, 7])]

    # セクション×角番 で集計
    section_corner = df_xday.groupby(["date", "section", "is_aisle_corner"]).agg({
        "diff_coins_normalized": "mean"
    }).reset_index()
    section_corner.columns = ["date", "section", "is_aisle_corner", "avg_diff"]

    # ピボット
    section_corner_pivot = section_corner.pivot_table(
        index=["date", "section"],
        columns="is_aisle_corner",
        values="avg_diff"
    ).reset_index()
    section_corner_pivot.columns = ["date", "section", "far_avg_diff", "aisle_avg_diff"]

    # 角番間の相関（セクション別）
    print("\nセクション別での通路側vs奥側の相関:")
    for section in sorted(section_corner_pivot["section"].unique()):
        subset = section_corner_pivot[section_corner_pivot["section"] == section]
        if len(subset) > 5:
            corr = subset["aisle_avg_diff"].corr(subset["far_avg_diff"])
            print(f"  セクション {section}: r={corr:.3f}")


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("みとや大森町店：角番（rank_from_aisle）アンチパターン分析")
    print("=" * 80)

    df = load_corner_data()
    print(f"\nデータ読み込み完了")

    # 分析実行
    daily_corner, xday_corner = analyze_daily_corner_pattern(df)
    xday_corner = analyze_corner_reversal(xday_corner)
    oscillation_df = analyze_corner_oscillation(xday_corner)
    analyze_corner_antipattern_stats(xday_corner)
    analyze_section_corner_interaction(df)

    # 結果保存
    print("\n" + "=" * 80)
    print("結果保存")
    print("=" * 80)

    output_dir = Path("ml/analysis/results")
    output_dir.mkdir(parents=True, exist_ok=True)

    # 日別×角番成績
    daily_corner.to_csv(output_dir / "mitoya_daily_corner_performance.csv", index=False)
    print(f"✓ 日別×角番成績: {output_dir / 'mitoya_daily_corner_performance.csv'}")

    # 振動パターン
    if len(oscillation_df) > 0:
        oscillation_df.to_csv(output_dir / "mitoya_corner_oscillation_pattern.csv", index=False)
        print(f"✓ 角番振動パターン: {output_dir / 'mitoya_corner_oscillation_pattern.csv'}")

    print("\n" + "=" * 80)
    print("分析完了")
    print("=" * 80)
