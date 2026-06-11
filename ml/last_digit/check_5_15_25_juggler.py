#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
5.15.25のDD でジャグラー機械割を集計
"""

import sqlite3
import pandas as pd
from pathlib import Path

DB_PATH = Path(__file__).parent / "db" / "みとや大森町店.db"

conn = sqlite3.connect(DB_PATH)

# ジャグラー機種リスト
juggler_machines = [
    'マイジャグラーV',
    'アイムジャグラーEX-TP',
    'ゴーゴージャグラー3',
    'アイムジャグラーEX',
    'マイジャグラーM',
    'ファンキージャグラー2'
]

juggler_filter = "(" + ", ".join([f"'{m}'" for m in juggler_machines]) + ")"

print("=" * 80)
print("【ジャグラー全体：5.15.25 vs その他の通常日】")
print("=" * 80)

df_juggler = pd.read_sql(f"""
    SELECT
        CASE
            WHEN CAST(substr(date, 7, 2) AS INTEGER) IN (5, 15, 25)
            THEN '5.15.25 dd'
            ELSE 'other normal days'
        END as category,
        COUNT(*) as total_count,
        COUNT(CASE WHEN diff_coins_normalized > 0 THEN 1 END) as positive_count,
        ROUND(COUNT(CASE WHEN diff_coins_normalized > 0 THEN 1 END) * 100.0 / COUNT(*), 1) as positive_ratio,
        ROUND(AVG(CAST(games_normalized AS REAL)), 0) as avg_games,
        ROUND(AVG(CAST(diff_coins_normalized AS REAL)), 1) as avg_diff,
        ROUND(100 + AVG(CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0)) * 100, 2) as kikaiwari_pct
    FROM machine_detailed_results
    WHERE machine_name IN {juggler_filter}
        AND CAST(substr(date, 7, 2) AS INTEGER) NOT IN (1, 4, 7, 14, 17, 24, 27, 30)
    GROUP BY category
    ORDER BY category
""", conn)

print(df_juggler.to_string(index=False))

print("\n" + "=" * 80)
print("【ジャグラー + 3000G以上：5.15.25 vs その他の通常日】")
print("=" * 80)

df_juggler_3000 = pd.read_sql(f"""
    SELECT
        CASE
            WHEN CAST(substr(date, 7, 2) AS INTEGER) IN (5, 15, 25)
            THEN '5.15.25 dd'
            ELSE 'other normal days'
        END as category,
        COUNT(*) as total_count,
        COUNT(CASE WHEN diff_coins_normalized > 0 THEN 1 END) as positive_count,
        ROUND(COUNT(CASE WHEN diff_coins_normalized > 0 THEN 1 END) * 100.0 / COUNT(*), 1) as positive_ratio,
        ROUND(AVG(CAST(games_normalized AS REAL)), 0) as avg_games,
        ROUND(AVG(CAST(diff_coins_normalized AS REAL)), 1) as avg_diff,
        ROUND(100 + AVG(CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0)) * 100, 2) as kikaiwari_pct,
        COUNT(CASE WHEN (100 + CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0) * 100) >= 104 THEN 1 END) as over_104_count,
        ROUND(COUNT(CASE WHEN (100 + CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0) * 100) >= 104 THEN 1 END) * 100.0 / COUNT(*), 1) as over_104_ratio
    FROM machine_detailed_results
    WHERE machine_name IN {juggler_filter}
        AND games_normalized >= 3000
        AND CAST(substr(date, 7, 2) AS INTEGER) NOT IN (1, 4, 7, 14, 17, 24, 27, 30)
    GROUP BY category
    ORDER BY category
""", conn)

print(df_juggler_3000.to_string(index=False))

print("\n" + "=" * 80)
print("【ジャグラー機種別：5.15.25での機械割】")
print("=" * 80)

df_juggler_by_machine = pd.read_sql(f"""
    SELECT
        machine_name,
        COUNT(*) as count,
        ROUND(AVG(CAST(games_normalized AS REAL)), 0) as avg_games,
        ROUND(AVG(CAST(diff_coins_normalized AS REAL)), 1) as avg_diff,
        ROUND(100 + AVG(CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0)) * 100, 2) as kikaiwari_pct,
        COUNT(CASE WHEN (100 + CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0) * 100) >= 104 THEN 1 END) as over_104_count,
        ROUND(COUNT(CASE WHEN (100 + CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0) * 100) >= 104 THEN 1 END) * 100.0 / COUNT(*), 1) as over_104_ratio
    FROM machine_detailed_results
    WHERE machine_name IN {juggler_filter}
        AND CAST(substr(date, 7, 2) AS INTEGER) IN (5, 15, 25)
        AND CAST(substr(date, 7, 2) AS INTEGER) NOT IN (1, 4, 7, 14, 17, 24, 27, 30)
    GROUP BY machine_name
    ORDER BY over_104_ratio DESC
""", conn)

print(df_juggler_by_machine.to_string(index=False))

print("\n" + "=" * 80)
print("【ジャグラー機種別：その他の通常日での機械割】")
print("=" * 80)

df_juggler_other = pd.read_sql(f"""
    SELECT
        machine_name,
        COUNT(*) as count,
        ROUND(AVG(CAST(games_normalized AS REAL)), 0) as avg_games,
        ROUND(AVG(CAST(diff_coins_normalized AS REAL)), 1) as avg_diff,
        ROUND(100 + AVG(CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0)) * 100, 2) as kikaiwari_pct,
        COUNT(CASE WHEN (100 + CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0) * 100) >= 104 THEN 1 END) as over_104_count,
        ROUND(COUNT(CASE WHEN (100 + CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0) * 100) >= 104 THEN 1 END) * 100.0 / COUNT(*), 1) as over_104_ratio
    FROM machine_detailed_results
    WHERE machine_name IN {juggler_filter}
        AND CAST(substr(date, 7, 2) AS INTEGER) NOT IN (1, 4, 7, 14, 17, 24, 27, 30, 5, 15, 25)
    GROUP BY machine_name
    ORDER BY over_104_ratio DESC
""", conn)

print(df_juggler_other.to_string(index=False))

conn.close()
