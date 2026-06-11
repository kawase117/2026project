#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diff_coins_normalized の値分布を確認
"""

import sqlite3
import pandas as pd
from pathlib import Path

DB_PATH = Path(__file__).parent / "db" / "みとや大森町店.db"

conn = sqlite3.connect(DB_PATH)

# サンプル20件
print("=" * 80)
print("【サンプルデータ】")
print("=" * 80)
df_sample = pd.read_sql("""
    SELECT date, machine_number, games_normalized, diff_coins_normalized
    FROM machine_detailed_results
    LIMIT 20
""", conn)
print(df_sample.to_string())

# 統計情報
print("\n" + "=" * 80)
print("【diff_coins_normalized の統計】")
print("=" * 80)
df_stats = pd.read_sql("""
    SELECT
        COUNT(*) as total_count,
        COUNT(CASE WHEN diff_coins_normalized > 0 THEN 1 END) as positive_count,
        COUNT(CASE WHEN diff_coins_normalized = 0 THEN 1 END) as zero_count,
        COUNT(CASE WHEN diff_coins_normalized < 0 THEN 1 END) as negative_count,
        MIN(diff_coins_normalized) as min_value,
        MAX(diff_coins_normalized) as max_value,
        AVG(CAST(diff_coins_normalized AS REAL)) as avg_value
    FROM machine_detailed_results
""", conn)
print(df_stats.to_string())

# 負の値のサンプル
print("\n" + "=" * 80)
print("【負の差枚を含むサンプル】")
print("=" * 80)
df_negative = pd.read_sql("""
    SELECT date, machine_number, games_normalized, diff_coins_normalized
    FROM machine_detailed_results
    WHERE diff_coins_normalized < 0
    LIMIT 10
""", conn)
if len(df_negative) > 0:
    print(df_negative.to_string())
else:
    print("負の差枚データなし")

conn.close()
