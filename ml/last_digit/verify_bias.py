#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
フィルタによるバイアスの確認
通常日 vs イベント日の差枚・機械割を、フィルタ有無で比較
"""

import sqlite3
import pandas as pd
from pathlib import Path

DB_PATH = Path(__file__).parent / "db" / "みとや大森町店.db"

conn = sqlite3.connect(DB_PATH)

print("=" * 80)
print("【フィルタなし（全台）での通常日 vs イベント日】")
print("=" * 80)

df_unfiltered = pd.read_sql("""
    SELECT
        CASE
            WHEN CAST(substr(date, 7, 2) AS INTEGER) IN (1, 4, 7, 14, 17, 24, 27, 30)
            THEN 'event_day'
            ELSE 'normal_day'
        END as category,
        COUNT(*) as total_count,
        COUNT(CASE WHEN diff_coins_normalized > 0 THEN 1 END) as positive_count,
        ROUND(COUNT(CASE WHEN diff_coins_normalized > 0 THEN 1 END) * 100.0 / COUNT(*), 1) as positive_ratio,
        ROUND(AVG(CAST(games_normalized AS REAL)), 0) as avg_games,
        ROUND(AVG(CAST(diff_coins_normalized AS REAL)), 1) as avg_diff,
        ROUND(100 + AVG(CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0)) * 100, 2) as kikaiwari_pct
    FROM machine_detailed_results
    GROUP BY category
    ORDER BY category
""", conn)

print(df_unfiltered.to_string(index=False))

print("\n" + "=" * 80)
print("【3000G以上フィルタ後の通常日 vs イベント日】")
print("=" * 80)

df_filtered = pd.read_sql("""
    SELECT
        CASE
            WHEN CAST(substr(date, 7, 2) AS INTEGER) IN (1, 4, 7, 14, 17, 24, 27, 30)
            THEN 'event_day'
            ELSE 'normal_day'
        END as category,
        COUNT(*) as total_count,
        COUNT(CASE WHEN diff_coins_normalized > 0 THEN 1 END) as positive_count,
        ROUND(COUNT(CASE WHEN diff_coins_normalized > 0 THEN 1 END) * 100.0 / COUNT(*), 1) as positive_ratio,
        ROUND(AVG(CAST(games_normalized AS REAL)), 0) as avg_games,
        ROUND(AVG(CAST(diff_coins_normalized AS REAL)), 1) as avg_diff,
        ROUND(100 + AVG(CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0)) * 100, 2) as kikaiwari_pct
    FROM machine_detailed_results
    WHERE games_normalized >= 3000
    GROUP BY category
    ORDER BY category
""", conn)

print(df_filtered.to_string(index=False))

print("\n" + "=" * 80)
print("【3000G以上の台の割合（通常日 vs イベント日）】")
print("=" * 80)

df_ratio = pd.read_sql("""
    SELECT
        CASE
            WHEN CAST(substr(date, 7, 2) AS INTEGER) IN (1, 4, 7, 14, 17, 24, 27, 30)
            THEN 'event_day'
            ELSE 'normal_day'
        END as category,
        COUNT(*) as total_machines,
        COUNT(CASE WHEN games_normalized >= 3000 THEN 1 END) as machines_3000plus,
        ROUND(COUNT(CASE WHEN games_normalized >= 3000 THEN 1 END) * 100.0 / COUNT(*), 1) as ratio_3000plus
    FROM machine_detailed_results
    GROUP BY category
    ORDER BY category
""", conn)

print(df_ratio.to_string(index=False))

conn.close()
