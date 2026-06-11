#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3000G フィルタの効果を確認
"""

import sqlite3
import pandas as pd
from pathlib import Path

DB_PATH = Path(__file__).parent / "db" / "みとや大森町店.db"

conn = sqlite3.connect(DB_PATH)

# 全データ
print("=" * 80)
print("【全データ（フィルタなし）】")
print("=" * 80)
df_all = pd.read_sql("""
    SELECT
        COUNT(*) as total,
        COUNT(CASE WHEN diff_coins_normalized > 0 THEN 1 END) as positive,
        COUNT(CASE WHEN diff_coins_normalized < 0 THEN 1 END) as negative,
        AVG(CAST(diff_coins_normalized AS REAL)) as avg_diff
    FROM machine_detailed_results
""", conn)
print(df_all.to_string(index=False))

# 3000G以上フィルタ
print("\n" + "=" * 80)
print("【3000G以上フィルタ後】")
print("=" * 80)
df_filtered = pd.read_sql("""
    SELECT
        COUNT(*) as total,
        COUNT(CASE WHEN diff_coins_normalized > 0 THEN 1 END) as positive,
        COUNT(CASE WHEN diff_coins_normalized < 0 THEN 1 END) as negative,
        AVG(CAST(diff_coins_normalized AS REAL)) as avg_diff
    FROM machine_detailed_results
    WHERE games_normalized >= 3000
""", conn)
print(df_filtered.to_string(index=False))

# 通常日 vs イベント日（3000G以上）
print("\n" + "=" * 80)
print("【通常日 vs イベント日（3000G以上）】")
print("=" * 80)

# 通常日
df_normal = pd.read_sql("""
    SELECT
        'normal_day' as category,
        COUNT(*) as total,
        COUNT(CASE WHEN diff_coins_normalized > 0 THEN 1 END) as positive,
        COUNT(CASE WHEN diff_coins_normalized < 0 THEN 1 END) as negative,
        AVG(CAST(diff_coins_normalized AS REAL)) as avg_diff,
        AVG(CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0)) * 100 as kikaiwari_pct
    FROM machine_detailed_results
    WHERE games_normalized >= 3000
        AND CAST(substr(date, 7, 2) AS INTEGER) NOT IN (1, 4, 7, 14, 17, 24, 27, 30)
""", conn)

# イベント日
df_event = pd.read_sql("""
    SELECT
        'event_day' as category,
        COUNT(*) as total,
        COUNT(CASE WHEN diff_coins_normalized > 0 THEN 1 END) as positive,
        COUNT(CASE WHEN diff_coins_normalized < 0 THEN 1 END) as negative,
        AVG(CAST(diff_coins_normalized AS REAL)) as avg_diff,
        AVG(CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0)) * 100 as kikaiwari_pct
    FROM machine_detailed_results
    WHERE games_normalized >= 3000
        AND CAST(substr(date, 7, 2) AS INTEGER) IN (1, 4, 7, 14, 17, 24, 27, 30)
""", conn)

result = pd.concat([df_normal, df_event], ignore_index=True)
print(result.to_string(index=False))

conn.close()
