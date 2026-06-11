#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修正フィルタでのイベント日 vs 通常日 再分析
- イベント日：フィルタなし（全台）
- 通常日：1500G以上フィルタ
"""

import sqlite3
import pandas as pd
from pathlib import Path

DB_PATH = Path(__file__).parent / "db" / "みとや大森町店.db"

conn = sqlite3.connect(DB_PATH)

print("=" * 80)
print("【修正フィルタでのイベント日 vs 通常日 比較】")
print("=" * 80)

print("\n" + "=" * 80)
print("【イベント日：フィルタなし（全台）】")
print("=" * 80)

df_event = pd.read_sql("""
    SELECT
        'event_day' as category,
        COUNT(*) as total_count,
        COUNT(CASE WHEN (100 + CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0) * 100) >= 104 THEN 1 END) as over_104_count,
        ROUND(COUNT(CASE WHEN (100 + CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0) * 100) >= 104 THEN 1 END) * 100.0 / COUNT(*), 1) as over_104_ratio,
        ROUND(AVG(CAST(games_normalized AS REAL)), 0) as avg_games,
        ROUND(AVG(CAST(diff_coins_normalized AS REAL)), 1) as avg_diff,
        ROUND(100 + AVG(CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0)) * 100, 2) as kikaiwari_pct
    FROM machine_detailed_results
    WHERE CAST(substr(date, 7, 2) AS INTEGER) IN (1, 4, 7, 14, 17, 24, 27, 30)
""", conn)

print(df_event.to_string(index=False))

print("\n" + "=" * 80)
print("【通常日：1500G以上フィルタ】")
print("=" * 80)

df_normal_1500 = pd.read_sql("""
    SELECT
        'normal_day (1500G+)' as category,
        COUNT(*) as total_count,
        COUNT(CASE WHEN (100 + CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0) * 100) >= 104 THEN 1 END) as over_104_count,
        ROUND(COUNT(CASE WHEN (100 + CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0) * 100) >= 104 THEN 1 END) * 100.0 / COUNT(*), 1) as over_104_ratio,
        ROUND(AVG(CAST(games_normalized AS REAL)), 0) as avg_games,
        ROUND(AVG(CAST(diff_coins_normalized AS REAL)), 1) as avg_diff,
        ROUND(100 + AVG(CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0)) * 100, 2) as kikaiwari_pct
    FROM machine_detailed_results
    WHERE games_normalized >= 1500
        AND CAST(substr(date, 7, 2) AS INTEGER) NOT IN (1, 4, 7, 14, 17, 24, 27, 30)
""", conn)

print(df_normal_1500.to_string(index=False))

print("\n" + "=" * 80)
print("【通常日：2000G以上フィルタ（参考）】")
print("=" * 80)

df_normal_2000 = pd.read_sql("""
    SELECT
        'normal_day (2000G+)' as category,
        COUNT(*) as total_count,
        COUNT(CASE WHEN (100 + CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0) * 100) >= 104 THEN 1 END) as over_104_count,
        ROUND(COUNT(CASE WHEN (100 + CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0) * 100) >= 104 THEN 1 END) * 100.0 / COUNT(*), 1) as over_104_ratio,
        ROUND(AVG(CAST(games_normalized AS REAL)), 0) as avg_games,
        ROUND(AVG(CAST(diff_coins_normalized AS REAL)), 1) as avg_diff,
        ROUND(100 + AVG(CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0)) * 100, 2) as kikaiwari_pct
    FROM machine_detailed_results
    WHERE games_normalized >= 2000
        AND CAST(substr(date, 7, 2) AS INTEGER) NOT IN (1, 4, 7, 14, 17, 24, 27, 30)
""", conn)

print(df_normal_2000.to_string(index=False))

print("\n" + "=" * 80)
print("【島別分析：イベント日 vs 通常日(1500G+)】")
print("=" * 80)

df_island_event = pd.read_sql("""
    SELECT
        'event_day' as category,
        CASE
            WHEN machine_number < 641 THEN 'other'
            WHEN machine_number < 692 THEN 'main_jug'
            WHEN machine_number < 832 THEN 'main_mix'
            ELSE 'bari'
        END as island,
        COUNT(*) as total_count,
        ROUND(COUNT(CASE WHEN (100 + CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0) * 100) >= 104 THEN 1 END) * 100.0 / COUNT(*), 1) as over_104_ratio,
        ROUND(AVG(CAST(diff_coins_normalized AS REAL)), 1) as avg_diff,
        ROUND(100 + AVG(CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0)) * 100, 2) as kikaiwari_pct
    FROM machine_detailed_results
    WHERE CAST(substr(date, 7, 2) AS INTEGER) IN (1, 4, 7, 14, 17, 24, 27, 30)
    GROUP BY island
    ORDER BY island
""", conn)

df_island_normal = pd.read_sql("""
    SELECT
        'normal_day(1500G+)' as category,
        CASE
            WHEN machine_number < 641 THEN 'other'
            WHEN machine_number < 692 THEN 'main_jug'
            WHEN machine_number < 832 THEN 'main_mix'
            ELSE 'bari'
        END as island,
        COUNT(*) as total_count,
        ROUND(COUNT(CASE WHEN (100 + CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0) * 100) >= 104 THEN 1 END) * 100.0 / COUNT(*), 1) as over_104_ratio,
        ROUND(AVG(CAST(diff_coins_normalized AS REAL)), 1) as avg_diff,
        ROUND(100 + AVG(CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0)) * 100, 2) as kikaiwari_pct
    FROM machine_detailed_results
    WHERE games_normalized >= 1500
        AND CAST(substr(date, 7, 2) AS INTEGER) NOT IN (1, 4, 7, 14, 17, 24, 27, 30)
    GROUP BY island
    ORDER BY island
""", conn)

print("\n【イベント日（全台）：島別】")
print(df_island_event.to_string(index=False))

print("\n【通常日（1500G+）：島別】")
print(df_island_normal.to_string(index=False))

conn.close()
