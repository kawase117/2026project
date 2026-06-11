#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DD別・曜日別での104%超え比率を分析
"""

import sqlite3
import pandas as pd
from pathlib import Path

DB_PATH = Path(__file__).parent / "db" / "みとや大森町店.db"

conn = sqlite3.connect(DB_PATH)

print("=" * 80)
print("【DD別（1-31）での104%超え比率（全台）】")
print("=" * 80)

df_dd = pd.read_sql("""
    SELECT
        CAST(substr(date, 7, 2) AS INTEGER) as dd,
        COUNT(*) as total_count,
        COUNT(CASE WHEN (100 + CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0) * 100) >= 104 THEN 1 END) as over_104_count,
        ROUND(COUNT(CASE WHEN (100 + CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0) * 100) >= 104 THEN 1 END) * 100.0 / COUNT(*), 1) as over_104_ratio,
        ROUND(AVG(CAST(games_normalized AS REAL)), 0) as avg_games,
        ROUND(AVG(CAST(diff_coins_normalized AS REAL)), 1) as avg_diff,
        ROUND(100 + AVG(CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0)) * 100, 2) as kikaiwari_pct
    FROM machine_detailed_results
    GROUP BY dd
    ORDER BY over_104_ratio DESC
""", conn)

print(df_dd.to_string(index=False))

print("\n" + "=" * 80)
print("【曜日別での104%超え比率（全台）】")
print("=" * 80)

df_dow = pd.read_sql("""
    SELECT
        CASE
            WHEN strftime('%w', substr(date, 1, 4) || '-' || substr(date, 5, 2) || '-' || substr(date, 7, 2)) = '0' THEN 'Sunday'
            WHEN strftime('%w', substr(date, 1, 4) || '-' || substr(date, 5, 2) || '-' || substr(date, 7, 2)) = '1' THEN 'Monday'
            WHEN strftime('%w', substr(date, 1, 4) || '-' || substr(date, 5, 2) || '-' || substr(date, 7, 2)) = '2' THEN 'Tuesday'
            WHEN strftime('%w', substr(date, 1, 4) || '-' || substr(date, 5, 2) || '-' || substr(date, 7, 2)) = '3' THEN 'Wednesday'
            WHEN strftime('%w', substr(date, 1, 4) || '-' || substr(date, 5, 2) || '-' || substr(date, 7, 2)) = '4' THEN 'Thursday'
            WHEN strftime('%w', substr(date, 1, 4) || '-' || substr(date, 5, 2) || '-' || substr(date, 7, 2)) = '5' THEN 'Friday'
            WHEN strftime('%w', substr(date, 1, 4) || '-' || substr(date, 5, 2) || '-' || substr(date, 7, 2)) = '6' THEN 'Saturday'
        END as day_of_week,
        COUNT(*) as total_count,
        COUNT(CASE WHEN (100 + CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0) * 100) >= 104 THEN 1 END) as over_104_count,
        ROUND(COUNT(CASE WHEN (100 + CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0) * 100) >= 104 THEN 1 END) * 100.0 / COUNT(*), 1) as over_104_ratio,
        ROUND(AVG(CAST(games_normalized AS REAL)), 0) as avg_games,
        ROUND(AVG(CAST(diff_coins_normalized AS REAL)), 1) as avg_diff,
        ROUND(100 + AVG(CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0)) * 100, 2) as kikaiwari_pct
    FROM machine_detailed_results
    GROUP BY day_of_week
    ORDER BY over_104_ratio DESC
""", conn)

print(df_dow.to_string(index=False))

print("\n" + "=" * 80)
print("【DD別：3000G以上フィルタ後での104%超え比率】")
print("=" * 80)

df_dd_3000 = pd.read_sql("""
    SELECT
        CAST(substr(date, 7, 2) AS INTEGER) as dd,
        COUNT(*) as total_count,
        COUNT(CASE WHEN (100 + CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0) * 100) >= 104 THEN 1 END) as over_104_count,
        ROUND(COUNT(CASE WHEN (100 + CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0) * 100) >= 104 THEN 1 END) * 100.0 / COUNT(*), 1) as over_104_ratio,
        ROUND(AVG(CAST(games_normalized AS REAL)), 0) as avg_games,
        ROUND(AVG(CAST(diff_coins_normalized AS REAL)), 1) as avg_diff,
        ROUND(100 + AVG(CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0)) * 100, 2) as kikaiwari_pct
    FROM machine_detailed_results
    WHERE games_normalized >= 3000
    GROUP BY dd
    ORDER BY over_104_ratio DESC
""", conn)

print(df_dd_3000.to_string(index=False))

print("\n" + "=" * 80)
print("【曜日別：3000G以上フィルタ後での104%超え比率】")
print("=" * 80)

df_dow_3000 = pd.read_sql("""
    SELECT
        CASE
            WHEN strftime('%w', substr(date, 1, 4) || '-' || substr(date, 5, 2) || '-' || substr(date, 7, 2)) = '0' THEN 'Sunday'
            WHEN strftime('%w', substr(date, 1, 4) || '-' || substr(date, 5, 2) || '-' || substr(date, 7, 2)) = '1' THEN 'Monday'
            WHEN strftime('%w', substr(date, 1, 4) || '-' || substr(date, 5, 2) || '-' || substr(date, 7, 2)) = '2' THEN 'Tuesday'
            WHEN strftime('%w', substr(date, 1, 4) || '-' || substr(date, 5, 2) || '-' || substr(date, 7, 2)) = '3' THEN 'Wednesday'
            WHEN strftime('%w', substr(date, 1, 4) || '-' || substr(date, 5, 2) || '-' || substr(date, 7, 2)) = '4' THEN 'Thursday'
            WHEN strftime('%w', substr(date, 1, 4) || '-' || substr(date, 5, 2) || '-' || substr(date, 7, 2)) = '5' THEN 'Friday'
            WHEN strftime('%w', substr(date, 1, 4) || '-' || substr(date, 5, 2) || '-' || substr(date, 7, 2)) = '6' THEN 'Saturday'
        END as day_of_week,
        COUNT(*) as total_count,
        COUNT(CASE WHEN (100 + CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0) * 100) >= 104 THEN 1 END) as over_104_count,
        ROUND(COUNT(CASE WHEN (100 + CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0) * 100) >= 104 THEN 1 END) * 100.0 / COUNT(*), 1) as over_104_ratio,
        ROUND(AVG(CAST(games_normalized AS REAL)), 0) as avg_games,
        ROUND(AVG(CAST(diff_coins_normalized AS REAL)), 1) as avg_diff,
        ROUND(100 + AVG(CAST(diff_coins_normalized AS REAL) / (games_normalized * 3.0)) * 100, 2) as kikaiwari_pct
    FROM machine_detailed_results
    WHERE games_normalized >= 3000
    GROUP BY day_of_week
    ORDER BY over_104_ratio DESC
""", conn)

print(df_dow_3000.to_string(index=False))

conn.close()
