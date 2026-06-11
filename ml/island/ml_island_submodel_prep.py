#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
島別サブモデル実装：各島のデータ特性分析と学習用データセット準備
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "db" / "みとや大森町店.db"

# イベント日定義
EVENT_DAYS = {1, 4, 7, 14, 17, 24, 27, 30}

def assign_island(machine_num):
    """台番号から島を判定"""
    if machine_num < 641:
        return 'other'
    elif machine_num < 692:
        return 'main_jug'
    elif machine_num < 832:
        return 'main_mix'
    else:
        return 'bari'

def prepare_ml_dataset():
    """ML学習用データセット準備"""
    conn = sqlite3.connect(DB_PATH)

    # 全データ取得
    df = pd.read_sql("""
        SELECT
            date, machine_number, machine_name,
            games_normalized, diff_coins_normalized
        FROM machine_detailed_results
        ORDER BY date
    """, conn)

    conn.close()

    # 特徴量エンジニアリング
    df['date_obj'] = pd.to_datetime(df['date'], format='%Y%m%d')
    df['dd'] = df['date_obj'].dt.day
    df['dow'] = df['date_obj'].dt.dayofweek  # 0=月, 6=日
    df['is_event'] = df['dd'].isin(EVENT_DAYS).astype(int)
    df['island'] = df['machine_number'].apply(assign_island)

    # 機械割計算
    df['kikaiwari'] = 100 + (df['diff_coins_normalized'] / (df['games_normalized'] * 3)) * 100
    df['target_104'] = (df['kikaiwari'] >= 104).astype(int)

    # 機種タイプ抽出（簡易版：機種名の最初の数文字）
    df['machine_type'] = df['machine_name'].str[:4]

    return df

print("=" * 80)
print("【島別サブモデル：データセット準備】")
print("=" * 80)

df = prepare_ml_dataset()

# フィルタ適用
df_event = df[df['is_event'] == 1].copy()
df_normal = df[(df['is_event'] == 0) & (df['games_normalized'] >= 1500)].copy()

print(f"\nデータ行数: {len(df):,}")
print(f"イベント日: {len(df_event):,}")
print(f"通常日(1500G+): {len(df_normal):,}")

# 島別統計
print("\n" + "=" * 80)
print("【各島の統計情報】")
print("=" * 80)

for island in ['main_jug', 'main_mix', 'other']:
    print(f"\n【{island}】")

    df_island = df[df['island'] == island]
    df_island_event = df_event[df_event['island'] == island]
    df_island_normal = df_normal[df_normal['island'] == island]

    print(f"全体台数: {len(df_island):,}")
    print(f"  イベント日: {len(df_island_event):,}")
    print(f"  通常日(1500G+): {len(df_island_normal):,}")

    print(f"104%超え率: {df_island['target_104'].mean()*100:.1f}%")
    print(f"  イベント日: {df_island_event['target_104'].mean()*100:.1f}%")
    print(f"  通常日: {df_island_normal['target_104'].mean()*100:.1f}%")

    print(f"平均差枚: {df_island['diff_coins_normalized'].mean():.1f}")
    print(f"  イベント日: {df_island_event['diff_coins_normalized'].mean():.1f}")
    print(f"  通常日: {df_island_normal['diff_coins_normalized'].mean():.1f}")

    print(f"平均回転数: {df_island['games_normalized'].mean():.0f}")
    print(f"機種数: {df_island['machine_type'].nunique()}")
    print(f"台数: {df_island['machine_number'].nunique()}")

# 学習用データセット保存
print("\n" + "=" * 80)
print("【学習用データセット保存】")
print("=" * 80)

output_file = Path(__file__).parent / "ml_data_island_submodel.csv"
df.to_csv(output_file, index=False)
print(f"保存: {output_file}")
print(f"行数: {len(df):,}, 列数: {len(df.columns)}")

# 特徴量確認
print(f"\n特徴量一覧:")
print(f"  時間: date, dd(日付), dow(曜日), is_event(イベント日)")
print(f"  空間: island, machine_number, machine_type")
print(f"  ゲーム: games_normalized, diff_coins_normalized, kikaiwari")
print(f"  目的変数: target_104")

print("\n" + "=" * 80)
print("準備完了。次のステップ：島別モデル構築")
print("=" * 80)
