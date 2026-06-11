"""
みとや大森町店：X_days（イベント日）内でのアンチパターン分析

高成績のイベント日（DD末尾4,7）→次のイベント日での成績変動を分析。
平日を除外して、「イベント日同士の相関」を検証する。

分析対象：
1. 当日高成績のイベント日→次のイベント日での成績（reversal検証）
2. セクション間：当日最高セクション→次のイベント日で別セクションが最高になるか
3. DD系列内（4系vs7系）での交互パターン
"""

import sqlite3
from pathlib import Path
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

DB_PATH = Path("db/みとや大森町店.db")

def load_raw_data():
    """機械詳細データ + 日付フラグを読み込み"""
    conn = sqlite3.connect(DB_PATH)

    # 機械詳細データ
    df = pd.read_sql(
        """
        SELECT
            date,
            machine_number,
            games_normalized,
            diff_coins_normalized
        FROM machine_detailed_results
        ORDER BY date, machine_number
        """,
        conn,
    )

    # 日別情報
    daily = pd.read_sql(
        """
        SELECT
            date,
            day_of_week,
            last_digit as day_last_digit
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

    # X_day判定（DD末尾4,7）
    daily["date_dt"] = pd.to_datetime(daily["date"], format="%Y%m%d")
    daily["dd"] = daily["date_dt"].dt.day
    daily["dd_mod"] = daily["dd"] % 10
    daily["is_xday"] = daily["dd_mod"].isin([4, 7]).astype(int)
    daily["dd_group"] = daily["dd_mod"].apply(lambda x: "4系" if x == 4 else ("7系" if x == 7 else "other"))

    daily = daily.sort_values("date_dt")

    return df, daily


def analyze_reversal_within_xday(daily):
    """
    イベント日（X_day）同士での成績変動を分析

    高成績のイベント日→次のイベント日での成績変動
    """
    xdays = daily[daily["is_xday"] == 1].copy()
    xdays = xdays.sort_values("date_dt").reset_index(drop=True)

    print("=" * 80)
    print("1. イベント日（X_day）同士での Reversal パターン")
    print("=" * 80)

    print(f"\n分析対象イベント日数: {len(xdays)} 日")

    # 当日→次のイベント日の成績変動
    xdays["next_date"] = xdays["date"].shift(-1)
    xdays["next_avg_diff"] = xdays["avg_diff"].shift(-1)
    xdays["next_dd_group"] = xdays["dd_group"].shift(-1)

    # 高成績フラグ（X_day全体の中央値以上）
    median_xday = xdays["avg_diff"].median()
    print(f"イベント日成績の中央値: {median_xday:.0f} 円")

    xdays["is_high_current"] = (xdays["avg_diff"] >= median_xday).astype(int)
    xdays["is_high_next"] = (xdays["next_avg_diff"] >= median_xday).astype(int)

    # 高成績→翌イベント日も高成績 (persistence)
    persistence = (xdays["is_high_current"] == 1) & (xdays["is_high_next"] == 1)
    reversal = (xdays["is_high_current"] == 1) & (xdays["is_high_next"] == 0)

    print(f"\n当日高成績→次のイベント日も高成績: {persistence.sum()} 日 (Persistence)")
    print(f"当日高成績→次のイベント日は低成績: {reversal.sum()} 日 (Reversal)")

    high_current = xdays[xdays["is_high_current"] == 1]
    if len(high_current) > 0:
        reversal_rate = reversal.sum() / len(high_current)
        print(f"  → Reversal率（高成績の翌イベント日が低くなる確率）: {reversal_rate*100:.1f}%")

    # 直近の高成績→翌イベント日例
    print("\n直近の高成績イベント日→次のイベント日（直近10件）:")
    high_recent = xdays[xdays["is_high_current"] == 1].tail(10)
    for _, row in high_recent.iterrows():
        next_str = f"次: {row['next_date']} ({row['next_dd_group']}) {row['next_avg_diff']:+.0f}円" if pd.notna(row['next_date']) else "（最後）"
        reversal_marker = "↓" if row['is_high_next'] == 0 else "↑"
        print(f"  {row['date']} ({row['dd_group']}) {row['avg_diff']:+.0f}円 {reversal_marker} {next_str}")

    return {
        "xdays": xdays,
        "median_xday": median_xday,
        "n_persistence": persistence.sum(),
        "n_reversal": reversal.sum()
    }


def analyze_dd_group_pattern(daily):
    """
    DD系列ごと（4系と7系）でのパターンを分析

    4系で高い日→7系で低いか
    """
    xdays = daily[daily["is_xday"] == 1].copy()
    xdays = xdays.sort_values("date_dt").reset_index(drop=True)

    print("\n" + "=" * 80)
    print("2. DD系列別パターン（4系 vs 7系）")
    print("=" * 80)

    for dd_group in ["4系", "7系"]:
        subset = xdays[xdays["dd_group"] == dd_group]
        print(f"\n{dd_group}イベント日:")
        print(f"  日数: {len(subset)} 日")
        print(f"  平均差枚: {subset['avg_diff'].mean():.0f} 円")
        print(f"  中央値: {subset['avg_diff'].median():.0f} 円")
        print(f"  最高: {subset['avg_diff'].max():.0f} 円")
        print(f"  最低: {subset['avg_diff'].min():.0f} 円")
        print(f"  プラス日数: {(subset['avg_diff'] > 0).sum()} 日 ({(subset['avg_diff'] > 0).sum()/len(subset)*100:.1f}%)")


def analyze_section_within_xday(df, daily):
    """
    イベント日（X_day）内でのセクション間パターンを分析
    """
    # X_dayのみフィルタ
    xday_dates = daily[daily["is_xday"] == 1]["date"].unique()
    df_xday = df[df["date"].isin(xday_dates)].copy()

    # セクション別集計
    layout_df = pd.read_sql(
        "SELECT machine_number, section FROM machine_layout",
        sqlite3.connect(DB_PATH)
    )
    df_xday = df_xday.merge(layout_df, on="machine_number", how="left")

    daily_section_xday = df_xday.groupby(["date", "section"]).agg({
        "diff_coins_normalized": "mean"
    }).reset_index()
    daily_section_xday.columns = ["date", "section", "avg_diff"]

    # 日ごとの最高セクション
    idx = daily_section_xday.groupby("date")["avg_diff"].idxmax()
    top_sections = daily_section_xday.loc[idx, ["date", "section", "avg_diff"]].reset_index(drop=True)

    # イベント日日付を追加
    top_sections = top_sections.merge(
        daily[["date", "dd_group"]],
        on="date",
        how="left"
    )

    top_sections = top_sections.sort_values("date")
    top_sections["prev_section"] = top_sections["section"].shift(1)
    top_sections["prev_date"] = top_sections["date"].shift(1)
    top_sections["prev_dd_group"] = top_sections["dd_group"].shift(1)

    print("\n" + "=" * 80)
    print("3. イベント日内のセクション遷移（当日最高セクション）")
    print("=" * 80)

    # 異なるセクションに遷移した割合
    transitions = top_sections[top_sections["prev_section"].notna()].copy()
    n_same_section = (transitions["section"] == transitions["prev_section"]).sum()
    n_different_section = (transitions["section"] != transitions["prev_section"]).sum()

    print(f"\n連続イベント日で同じセクション最高: {n_same_section} 回")
    print(f"異なるセクションに遷移: {n_different_section} 回")
    if len(transitions) > 0:
        print(f"  → セクション遷移率: {n_different_section / len(transitions) * 100:.1f}%")

    # セクション遷移の頻度Top10
    transition_counts = transitions.groupby(["prev_section", "section"]).size().reset_index(name="count")
    transition_counts = transition_counts.sort_values("count", ascending=False)

    print("\nセクション遷移の頻度 (Top10):")
    for _, row in transition_counts.head(10).iterrows():
        print(f"  {row['prev_section']} → {row['section']}: {row['count']} 回")

    return {
        "top_sections": top_sections,
        "transitions": transitions,
        "n_same": n_same_section,
        "n_different": n_different_section
    }


def analyze_consecutive_xday_same_dd(daily):
    """
    同じDD系列が連続した場合の成績パターンを分析
    （4系→4系、または7系→7系）
    """
    xdays = daily[daily["is_xday"] == 1].copy()
    xdays = xdays.sort_values("date_dt").reset_index(drop=True)

    xdays["next_dd_group"] = xdays["dd_group"].shift(-1)
    xdays["next_avg_diff"] = xdays["avg_diff"].shift(-1)

    # 同じDD系列が連続
    same_dd = xdays[xdays["dd_group"] == xdays["next_dd_group"]].copy()

    print("\n" + "=" * 80)
    print("4. 同じDD系列が連続した場合のパターン")
    print("=" * 80)

    print(f"\n分析ケース数: {len(same_dd)} ケース")

    median_xday = xdays["avg_diff"].median()

    if len(same_dd) > 0:
        same_dd["is_high_current"] = (same_dd["avg_diff"] >= median_xday).astype(int)
        same_dd["is_high_next"] = (same_dd["next_avg_diff"] >= median_xday).astype(int)

        # 高成績→同DD系列で再び高成績 (persistence within same DD)
        persistence = (same_dd["is_high_current"] == 1) & (same_dd["is_high_next"] == 1)
        reversal = (same_dd["is_high_current"] == 1) & (same_dd["is_high_next"] == 0)

        print(f"\n当日高成績→同DD系列で次も高成績: {persistence.sum()} ケース (Persistence)")
        print(f"当日高成績→同DD系列で次は低成績: {reversal.sum()} ケース (Reversal)")

        high_current = same_dd[same_dd["is_high_current"] == 1]
        if len(high_current) > 0:
            reversal_rate = reversal.sum() / len(high_current)
            print(f"  → Reversal率: {reversal_rate*100:.1f}%")

        print("\n具体例（直近10件）:")
        for _, row in same_dd.tail(10).iterrows():
            current_marker = "高" if row['is_high_current'] == 1 else "低"
            next_marker = "高" if row['is_high_next'] == 1 else "低"
            arrow = "→" if row['is_high_next'] == 1 else "↓"
            print(f"  {row['date']} ({row['dd_group']}) {row['avg_diff']:+.0f}円[{current_marker}] {arrow} " +
                  f"{row['next_dd_group']} {row['next_avg_diff']:+.0f}円[{next_marker}]")


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("みとや大森町店：イベント日（X_days）内でのアンチパターン分析")
    print("=" * 80)

    df, daily = load_raw_data()
    print(f"\n✓ データ読み込み完了: {len(daily)} 日")
    print(f"  うちイベント日（X_days）: {daily['is_xday'].sum()} 日")

    # 分析実行
    reversal_result = analyze_reversal_within_xday(daily)
    analyze_dd_group_pattern(daily)
    section_result = analyze_section_within_xday(df, daily)
    analyze_consecutive_xday_same_dd(daily)

    # 結果保存
    print("\n" + "=" * 80)
    print("5. 結果保存")
    print("=" * 80)

    output_dir = Path("ml/analysis/results")
    output_dir.mkdir(parents=True, exist_ok=True)

    # X_day詳細
    reversal_result["xdays"].to_csv(output_dir / "mitoya_xday_reversal_analysis.csv", index=False)
    print(f"✓ X_day Reversal分析: {output_dir / 'mitoya_xday_reversal_analysis.csv'}")

    # セクション遷移
    section_result["transitions"].to_csv(output_dir / "mitoya_xday_section_transitions.csv", index=False)
    print(f"✓ X_day セクション遷移: {output_dir / 'mitoya_xday_section_transitions.csv'}")

    print("\n" + "=" * 80)
    print("分析完了")
    print("=" * 80)
