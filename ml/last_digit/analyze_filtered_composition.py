#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3000G以上フィルタ後の機種と台番号の構成を分析
"""

import sqlite3
import pandas as pd
from pathlib import Path

DB_PATH = Path(__file__).parent / "db" / "みとや大森町店.db"

conn = sqlite3.connect(DB_PATH)

print("=" * 80)
print("【通常日：3000G以上の機種TOP30】")
print("=" * 80)

df_normal_machines = pd.read_sql("""
    SELECT
        machine_name,
        COUNT(*) as count,
        ROUND(AVG(CAST(games_normalized AS REAL)), 0) as avg_games,
        ROUND(AVG(CAST(diff_coins_normalized AS REAL)), 1) as avg_diff,
        ROUND(100 + AVG(CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0)) * 100, 2) as kikaiwari_pct
    FROM machine_detailed_results
    WHERE games_normalized >= 3000
        AND CAST(substr(date, 7, 2) AS INTEGER) NOT IN (1, 4, 7, 14, 17, 24, 27, 30)
    GROUP BY machine_name
    ORDER BY count DESC
    LIMIT 30
""", conn)

print(df_normal_machines.to_string(index=False))

print("\n" + "=" * 80)
print("【通常日：3000G以上の台番号TOP50】")
print("=" * 80)

df_normal_machines_num = pd.read_sql("""
    SELECT
        machine_number,
        machine_name,
        COUNT(*) as count,
        ROUND(AVG(CAST(games_normalized AS REAL)), 0) as avg_games,
        ROUND(AVG(CAST(diff_coins_normalized AS REAL)), 1) as avg_diff,
        ROUND(100 + AVG(CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0)) * 100, 2) as kikaiwari_pct
    FROM machine_detailed_results
    WHERE games_normalized >= 3000
        AND CAST(substr(date, 7, 2) AS INTEGER) NOT IN (1, 4, 7, 14, 17, 24, 27, 30)
    GROUP BY machine_number
    ORDER BY count DESC
    LIMIT 50
""", conn)

print(df_normal_machines_num.to_string(index=False))

print("\n" + "=" * 80)
print("【イベント日：3000G以上の機種TOP30】")
print("=" * 80)

df_event_machines = pd.read_sql("""
    SELECT
        machine_name,
        COUNT(*) as count,
        ROUND(AVG(CAST(games_normalized AS REAL)), 0) as avg_games,
        ROUND(AVG(CAST(diff_coins_normalized AS REAL)), 1) as avg_diff,
        ROUND(100 + AVG(CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0)) * 100, 2) as kikaiwari_pct
    FROM machine_detailed_results
    WHERE games_normalized >= 3000
        AND CAST(substr(date, 7, 2) AS INTEGER) IN (1, 4, 7, 14, 17, 24, 27, 30)
    GROUP BY machine_name
    ORDER BY count DESC
    LIMIT 30
""", conn)

print(df_event_machines.to_string(index=False))

print("\n" + "=" * 80)
print("【イベント日：3000G以上の台番号TOP50】")
print("=" * 80)

df_event_machines_num = pd.read_sql("""
    SELECT
        machine_number,
        machine_name,
        COUNT(*) as count,
        ROUND(AVG(CAST(games_normalized AS REAL)), 0) as avg_games,
        ROUND(AVG(CAST(diff_coins_normalized AS REAL)), 1) as avg_diff,
        ROUND(100 + AVG(CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0)) * 100, 2) as kikaiwari_pct
    FROM machine_detailed_results
    WHERE games_normalized >= 3000
        AND CAST(substr(date, 7, 2) AS INTEGER) IN (1, 4, 7, 14, 17, 24, 27, 30)
    GROUP BY machine_number
    ORDER BY count DESC
    LIMIT 50
""", conn)

print(df_event_machines_num.to_string(index=False))

conn.close()
