"""
みとや大森町店：セクション間相関 & アンチパターン分析

蒲田七で見られた「A型とBTが逆側の末尾クラスタに投入される」という
セクション間アンチパターンがみとやにも存在するか検証する。

分析対象：
1. セクション別（機種タイプ別）の日別成績の相関行列
2. 時系列 momentum/reversal（連続高成績→落ち込み）
3. 連続最強セクション→別セクションへの移行パターン
"""

import sqlite3
from pathlib import Path
import pandas as pd
import numpy as np
from scipy import stats
import json
from datetime import datetime

DB_PATH = Path("db/みとや大森町店.db")

def load_raw_data():
    """機械詳細データ + 台配置情報を読み込み"""
    conn = sqlite3.connect(DB_PATH)

    # 機械詳細データ
    df = pd.read_sql(
        """
        SELECT
            date,
            machine_number,
            machine_name,
            games_normalized,
            diff_coins_normalized
        FROM machine_detailed_results
        ORDER BY date, machine_number
        """,
        conn,
    )

    # 台配置情報（セクション・機種タイプ）
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
    return df


def get_machine_type_category(machine_name):
    """機種名から機種タイプカテゴリを判定"""
    if not machine_name:
        return "Unknown"

    name_lower = str(machine_name).lower()

    # AT機判定
    at_keywords = ["北斗", "碧", "甲鉄城", "東京喰種", "バジリスク", "ビッグドリーム",
                   "ミリオンゴッド", "スマスロ", "AT"]
    if any(kw in machine_name for kw in at_keywords):
        return "AT"

    # ジャグラー判定
    if "ジャグラー" in machine_name or "ジャグ" in machine_name:
        return "Jaggler"

    # A型判定（その他）
    return "Other"


def analyze_section_daily_correlation(df):
    """
    セクション別（機種タイプ別）の日別平均成績を計算し、相関行列を出力
    """
    df["machine_type_cat"] = df.apply(
        lambda r: get_machine_type_category(r.get("machine_name", "")), axis=1
    )

    # セクション × 機種タイプ グループの日別成績
    daily_section = df.groupby(["date", "section", "machine_type_cat"]).agg({
        "diff_coins_normalized": ["mean", "sum", "count"],
        "games_normalized": "sum"
    }).reset_index()

    daily_section.columns = ["date", "section", "machine_type_cat",
                              "avg_diff", "total_diff", "n_machines", "total_games"]

    # セクション別（機種タイプ混合）の日別平均成績
    daily_by_section = df.groupby(["date", "section"]).agg({
        "diff_coins_normalized": ["mean", "sum", "count"],
        "games_normalized": "sum"
    }).reset_index()

    daily_by_section.columns = ["date", "section",
                                 "avg_diff", "total_diff", "n_machines", "total_games"]

    # ピボット：date x section（相関行列用）
    section_pivot = daily_by_section.pivot(index="date", columns="section", values="avg_diff")

    # 相関行列
    corr_matrix = section_pivot.corr()

    return {
        "daily_section": daily_section,
        "daily_by_section": daily_by_section,
        "section_pivot": section_pivot,
        "corr_matrix": corr_matrix
    }


def find_antipatterns(df):
    """
    アンチパターンを検出：
    1. 高成績が続く日の翌日が低成績（Reversal）
    2. セクションペア：A が高い日は B が低い傾向
    """
    df_sorted = df.sort_values("date").copy()

    daily_allhall = df_sorted.groupby("date").agg({
        "diff_coins_normalized": "mean",
    }).reset_index()

    daily_allhall.columns = ["date", "avg_diff"]
    daily_allhall["date_dt"] = pd.to_datetime(daily_allhall["date"], format="%Y%m%d")
    daily_allhall = daily_allhall.sort_values("date_dt")

    # 高成績フラグ（中央値以上）
    median_diff = daily_allhall["avg_diff"].median()
    daily_allhall["is_high"] = (daily_allhall["avg_diff"] >= median_diff).astype(int)

    # 連続高成績後の落ち込み検出
    daily_allhall["prev_is_high"] = daily_allhall["is_high"].shift(1)
    daily_allhall["next_avg_diff"] = daily_allhall["avg_diff"].shift(-1)

    # 「前日高成績→当日も高成績」の日数
    consecutive_high = (daily_allhall["is_high"] == 1) & (daily_allhall["prev_is_high"] == 1)

    # 「当日高→翌日低」の検出
    high_then_low = (daily_allhall["is_high"] == 1) & (daily_allhall["next_avg_diff"] < median_diff)

    reversals = daily_allhall[high_then_low].copy()

    return {
        "daily_allhall": daily_allhall,
        "median_diff": median_diff,
        "n_consecutive_high": consecutive_high.sum(),
        "n_reversals": len(reversals),
        "reversals": reversals
    }


def analyze_top_section_persistence(df):
    """
    日々で最高成績のセクションが変わるパターンを分析
    """
    daily_by_section = df.groupby(["date", "section"]).agg({
        "diff_coins_normalized": "mean"
    }).reset_index()

    daily_by_section.columns = ["date", "section", "avg_diff"]

    # 日ごとの最高成績セクション
    idx = daily_by_section.groupby("date")["avg_diff"].idxmax()
    top_sections = daily_by_section.loc[idx, ["date", "section", "avg_diff"]].reset_index(drop=True)

    # セクション遷移パターン
    top_sections["date_dt"] = pd.to_datetime(top_sections["date"], format="%Y%m%d")
    top_sections = top_sections.sort_values("date_dt")

    top_sections["prev_section"] = top_sections["section"].shift(1)
    top_sections["next_section"] = top_sections["section"].shift(-1)

    # 連続で同じセクションが最高のケース
    consecutive_top = (top_sections["section"] == top_sections["prev_section"]).sum()

    # セクション遷移カウント
    transitions = top_sections[top_sections["prev_section"].notna()].copy()
    transition_counts = transitions.groupby(["prev_section", "section"]).size().reset_index(name="count")

    return {
        "top_sections": top_sections,
        "n_consecutive_top": consecutive_top,
        "transition_counts": transition_counts
    }


if __name__ == "__main__":
    print("=" * 80)
    print("みとや大森町店：セクション間相関 & アンチパターン分析")
    print("=" * 80)

    df = load_raw_data()
    print(f"\n✓ データ読み込み完了: {len(df)} 行, {df['date'].nunique()} 日")

    # 1. セクション間相関
    print("\n" + "=" * 80)
    print("1. セクション間相関行列")
    print("=" * 80)

    corr_result = analyze_section_daily_correlation(df)
    corr_matrix = corr_result["corr_matrix"]

    print("\nセクション相関行列（相関係数）:")
    print(corr_matrix.round(3))

    # 逆相関（r < -0.1）を抽出
    anticorr_mask = corr_matrix < -0.1
    anticorr_data = []
    for i in range(len(corr_matrix)):
        for j in range(i+1, len(corr_matrix)):
            if anticorr_mask.iloc[i, j]:
                anticorr_data.append({
                    "section1": corr_matrix.index[i],
                    "section2": corr_matrix.columns[j],
                    "correlation": corr_matrix.iloc[i, j]
                })
    anticorr = pd.DataFrame(anticorr_data) if anticorr_data else pd.DataFrame()

    if len(anticorr) > 0:
        print("\n逆相関パターン（r < -0.1）:")
        for _, row in anticorr.iterrows():
            print(f"  セクション {row['section1']} <-> セクション {row['section2']}: r={row['correlation']:.3f}")
    else:
        print("\n有意な逆相関パターン：検出なし")

    # 2. Reversal パターン（時系列）
    print("\n" + "=" * 80)
    print("2. 時系列 Momentum/Reversal パターン")
    print("=" * 80)

    antipattern_result = find_antipatterns(df)
    daily_allhall = antipattern_result["daily_allhall"]

    print(f"\n分析対象期間: {daily_allhall['date'].min()} ～ {daily_allhall['date'].max()}")
    print(f"平均差枚の中央値: {antipattern_result['median_diff']:.0f} 円")
    print(f"連続高成績日数: {antipattern_result['n_consecutive_high']} 日")
    print(f"高成績→翌日低成績（Reversal）: {antipattern_result['n_reversals']} 日")

    if antipattern_result['n_reversals'] > 0:
        reversal_rate = antipattern_result['n_reversals'] / len(daily_allhall[daily_allhall['is_high'] == 1])
        print(f"  → Reversal率: {reversal_rate*100:.1f}%")

        print("\n最近のReversal例（直近5件）:")
        for _, row in antipattern_result['reversals'].tail(5).iterrows():
            print(f"  {row['date']}: 当日 {row['avg_diff']:+.0f}円 → 翌日 {row['next_avg_diff']:+.0f}円")

    # 3. セクション最高の遷移パターン
    print("\n" + "=" * 80)
    print("3. 日々の最高成績セクション遷移パターン")
    print("=" * 80)

    top_result = analyze_top_section_persistence(df)
    transitions = top_result["transition_counts"]

    print(f"\n連続で同じセクションが最高: {top_result['n_consecutive_top']} 日")

    print("\nセクション遷移の頻度（前日→当日）:")
    transitions_sorted = transitions.sort_values("count", ascending=False)
    for _, row in transitions_sorted.head(10).iterrows():
        print(f"  {row['prev_section']} → {row['section']}: {row['count']} 回")

    # 4. 保存
    print("\n" + "=" * 80)
    print("4. 結果保存")
    print("=" * 80)

    output_dir = Path("ml/analysis/results")
    output_dir.mkdir(parents=True, exist_ok=True)

    # 相関行列CSV
    corr_matrix.to_csv(output_dir / "mitoya_section_correlation.csv")
    print(f"✓ 相関行列: {output_dir / 'mitoya_section_correlation.csv'}")

    # 日別セクション成績
    corr_result["daily_by_section"].to_csv(output_dir / "mitoya_daily_by_section.csv", index=False)
    print(f"✓ 日別セクション成績: {output_dir / 'mitoya_daily_by_section.csv'}")

    # Reversal詳細
    antipattern_result['daily_allhall'].to_csv(output_dir / "mitoya_reversal_analysis.csv", index=False)
    print(f"✓ Reversal分析: {output_dir / 'mitoya_reversal_analysis.csv'}")

    # セクション遷移
    transitions.to_csv(output_dir / "mitoya_section_transitions.csv", index=False)
    print(f"✓ セクション遷移: {output_dir / 'mitoya_section_transitions.csv'}")

    print("\n" + "=" * 80)
    print("分析完了")
    print("=" * 80)
