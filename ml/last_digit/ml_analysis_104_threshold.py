#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
みとや大森町：104%機械割閾値の深掘り分析

Analyses:
  Step 4: 島別セグメント分析（main_jug / main_mix / bari）
  Step 2: 通常日 vs イベント日の比較
  Step 3: 回転数フィルタの段階的検証（1500-3500G）
  Step 1: 複数閾値感度分析（99%-106%）

実行順序：島別 → 日付 → 回転数 → 閾値
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
import json

# パス設定
PROJECT_ROOT = Path(__file__).parent
DB_PATH = PROJECT_ROOT / "db" / "みとや大森町店.db"

# イベント日定義（みとや大森町店固有）
EVENT_DAYS = {1, 4, 7, 14, 17, 24, 27, 30}  # ユーザー確認済みのみとや固有イベント日

def load_data():
    """DB から個別台データを読み込む"""
    print("=" * 80)
    print("データ読み込み中...")

    # DB から個別台データを取得
    conn = sqlite3.connect(DB_PATH)

    df_machines = pd.read_sql("""
        SELECT
            date, machine_number, machine_name, games_normalized, diff_coins_normalized
        FROM machine_detailed_results
        ORDER BY date DESC
    """, conn)

    conn.close()

    # 島別セグメント定義（みとや大森町店）
    def assign_island(machine_num):
        if machine_num < 641:
            return 'other'
        elif machine_num < 692:
            return 'main_jug'  # 641-691
        elif machine_num < 832:
            return 'main_mix'   # 692-831
        else:
            return 'bari'       # 832+

    df_machines['island'] = df_machines['machine_number'].apply(assign_island)

    # 日付情報を抽出
    df_machines['date_obj'] = pd.to_datetime(df_machines['date'], format='%Y%m%d')
    df_machines['day'] = df_machines['date_obj'].dt.day
    df_machines['weekday'] = df_machines['date_obj'].dt.weekday
    df_machines['is_event'] = df_machines['day'].isin(EVENT_DAYS)

    # 機械割計算（3枚がけ前提）
    df_machines['kikaiwari'] = 100 + (df_machines['diff_coins_normalized'] / (df_machines['games_normalized'] * 3)) * 100
    df_machines['is_over_104'] = (df_machines['kikaiwari'] >= 104).astype(int)

    print(f"読み込んだデータ行数: {len(df_machines)}")
    print(f"日付範囲: {df_machines['date'].min()} ~ {df_machines['date'].max()}")
    print(f"島別カウント:\n{df_machines['island'].value_counts()}\n")

    return df_machines

def analyze_by_island(df):
    """Step 4: 島別セグメント分析"""
    print("=" * 80)
    print("【Step 4】島別セグメント分析（104%超え比率）")
    print("=" * 80)

    results = []
    for island in ['main_jug', 'main_mix', 'bari', 'other']:
        df_island = df[df['island'] == island]
        if len(df_island) == 0:
            continue

        total_machines = len(df_island)
        over_104 = df_island['is_over_104'].sum()
        ratio = over_104 / total_machines * 100
        avg_kikaiwari = df_island['kikaiwari'].mean()
        median_games = df_island['games_normalized'].median()

        results.append({
            'island': island,
            'total_machines': total_machines,
            'over_104_count': int(over_104),
            'over_104_ratio': f"{ratio:.1f}%",
            'avg_kikaiwari': f"{avg_kikaiwari:.2f}%",
            'median_games': int(median_games)
        })

        print(f"\n【{island}】")
        print(f"  総台数: {total_machines}")
        print(f"  104%超え: {int(over_104)}/{total_machines} = {ratio:.1f}%")
        print(f"  平均機械割: {avg_kikaiwari:.2f}%")
        print(f"  中央ゲーム数: {int(median_games)}")

    return pd.DataFrame(results)

def analyze_by_event_day(df, min_games=3000):
    """Step 2: イベント日 vs 通常日の詳細比較（全期間、最小ゲーム数フィルタ後）"""
    print("\n" + "=" * 80)
    print(f"【Step 2】イベント日 vs 通常日の詳細比較（最小ゲーム数: {min_games}G以上）")
    print("=" * 80)

    df_filtered = df[df['games_normalized'] >= min_games]

    results = []
    for is_event, label in [(True, 'イベント日'), (False, '通常日')]:
        df_subset = df_filtered[df_filtered['is_event'] == is_event]
        total = len(df_subset)
        over_104 = df_subset['is_over_104'].sum()
        ratio = over_104 / total * 100 if total > 0 else 0
        avg_kikaiwari = df_subset['kikaiwari'].mean()

        results.append({
            'category': label,
            'total_machines': total,
            'over_104_count': int(over_104),
            'over_104_ratio': f"{ratio:.1f}%",
            'avg_kikaiwari': f"{avg_kikaiwari:.2f}%"
        })

        print(f"\n【{label}】")
        print(f"  総台数: {total}")
        print(f"  104%超え: {int(over_104)}/{total} = {ratio:.1f}%")
        print(f"  平均機械割: {avg_kikaiwari:.2f}%")

        # 島別詳細
        print(f"  島別内訳:")
        for island in ['main_jug', 'main_mix', 'other']:
            df_detail = df_subset[df_subset['island'] == island]
            if len(df_detail) > 0:
                detail_count = df_detail['is_over_104'].sum()
                detail_ratio = detail_count / len(df_detail) * 100
                detail_avg = df_detail['kikaiwari'].mean()
                print(f"    {island}: {detail_ratio:.1f}% ({int(detail_count)}/{len(df_detail)}) avg={detail_avg:.2f}%")

    return pd.DataFrame(results)

def analyze_by_games_threshold(df):
    """Step 3: 回転数フィルタの段階的検証（1500-3500G）"""
    print("\n" + "=" * 80)
    print("【Step 3】回転数フィルタの段階的検証")
    print("=" * 80)

    thresholds = [1500, 2000, 2500, 3000, 3500]
    results = []

    for threshold in thresholds:
        df_filtered = df[df['games_normalized'] >= threshold]
        total = len(df_filtered)
        over_104 = df_filtered['is_over_104'].sum()
        ratio = over_104 / total * 100 if total > 0 else 0
        avg_kikaiwari = df_filtered['kikaiwari'].mean()

        results.append({
            'min_games': threshold,
            'remaining_machines': total,
            'remaining_ratio': f"{total/len(df)*100:.1f}%",
            'over_104_count': int(over_104),
            'over_104_ratio': f"{ratio:.1f}%",
            'avg_kikaiwari': f"{avg_kikaiwari:.2f}%"
        })

        print(f"\n【最小ゲーム数: {threshold}G以上】")
        print(f"  残存台数: {total}/{len(df)} = {total/len(df)*100:.1f}%")
        print(f"  104%超え: {int(over_104)}/{total} = {ratio:.1f}%")
        print(f"  平均機械割: {avg_kikaiwari:.2f}%")

    return pd.DataFrame(results)

def analyze_by_threshold(df, min_games=3000):
    """Step 1: 複数閾値感度分析（99%-106%）"""
    print("\n" + "=" * 80)
    print(f"【Step 1】複数閾値感度分析（最小ゲーム数: {min_games}G以上）")
    print("=" * 80)

    df_filtered = df[df['games_normalized'] >= min_games]
    thresholds = [99, 101, 103, 104, 105, 106]
    results = []

    for threshold in thresholds:
        over_threshold = (df_filtered['kikaiwari'] >= threshold).sum()
        ratio = over_threshold / len(df_filtered) * 100
        avg_kikaiwari = df_filtered['kikaiwari'].mean()

        results.append({
            'threshold': f"{threshold}%",
            'over_threshold_count': int(over_threshold),
            'over_threshold_ratio': f"{ratio:.1f}%",
            'sample_size': len(df_filtered)
        })

        print(f"\n【閾値: {threshold}%以上】")
        print(f"  該当台数: {int(over_threshold)}/{len(df_filtered)} = {ratio:.1f}%")

    return pd.DataFrame(results)

def main():
    df = load_data()

    # 各分析を実行
    island_results = analyze_by_island(df)
    event_results = analyze_by_event_day(df, min_games=3000)
    games_results = analyze_by_games_threshold(df)
    threshold_results = analyze_by_threshold(df, min_games=3000)

    # 結果をJSONで保存
    output_file = PROJECT_ROOT / "_analysis_104_threshold_results.json"
    summary = {
        'timestamp': datetime.now().isoformat(),
        'data_date_range': f"{df['date'].min()} ~ {df['date'].max()}",
        'island_analysis': island_results.to_dict('records'),
        'event_day_analysis': event_results.to_dict('records'),
        'games_threshold_analysis': games_results.to_dict('records'),
        'threshold_sensitivity_analysis': threshold_results.to_dict('records')
    }

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n" + "=" * 80)
    print(f"分析結果を保存しました: {output_file}")
    print("=" * 80)

if __name__ == '__main__':
    main()
