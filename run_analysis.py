#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sqlite3
import pandas as pd
from pathlib import Path
import sys

DB_PATH = Path(r"db\experiments\マルハンメガシティ2000-蒲田7_rank_exp_v2.db")
conn = sqlite3.connect(DB_PATH)

df_latest = pd.read_sql_query("""
    SELECT last_digit, total_diff_coins
    FROM last_digit_summary_all
    WHERE date = '20260510'
    ORDER BY total_diff_coins DESC
""", conn)

df_history = pd.read_sql_query("""
    SELECT date, last_digit, total_diff_coins
    FROM last_digit_summary_all
    WHERE date >= '20260504' AND date <= '20260510'
""", conn)

rank1_to_6 = df_latest['last_digit'].head(6).tolist()

feature_scores = {}
for digit in range(10):
    digit_str = str(digit)
    df_digit = df_history[df_history['last_digit'] == digit_str]
    win_count = (df_digit['total_diff_coins'] > 0).sum()
    win_rate = win_count / len(df_digit) if len(df_digit) > 0 else 0
    avg_diff = df_digit['total_diff_coins'].mean()
    df_recent = df_history[(df_history['date'] >= '20260508') & (df_history['last_digit'] == digit_str)]
    recent_avg = df_recent['total_diff_coins'].mean()
    score = (win_rate * 30) + (avg_diff / 1000) + (recent_avg / 500)
    feature_scores[digit_str] = score

sorted_scores = sorted(feature_scores.items(), key=lambda x: x[1], reverse=True)
predicted = [d for d, s in sorted_scores[:4]]
actual = ['4', '5', '1', '6']
matches = sum(1 for p, a in zip(predicted, actual) if p == a)

output = f"""Phase 10 Forward Prediction Analysis (v2 DB)
====================================

2026-05-10 Actual Rank1-6:  {rank1_to_6}
7-day Momentum Prediction:   {predicted}
2026-05-11 Actual Result:    {actual}

Direct Position Matches: {matches}/4

Position-by-Position:
  Rank1: Pred={predicted[0]}, Actual={actual[0]} {'MATCH' if predicted[0] == actual[0] else 'MISS'}
  Rank2: Pred={predicted[1]}, Actual={actual[1]} {'MATCH' if predicted[1] == actual[1] else 'MISS'}
  Rank3: Pred={predicted[2]}, Actual={actual[2]} {'MATCH' if predicted[2] == actual[2] else 'MISS'}
  Rank4: Pred={predicted[3]}, Actual={actual[3]} {'MATCH' if predicted[3] == actual[3] else 'MISS'}

Partial Match: {sum(1 for p in predicted if p in actual)}/4
"""

with open('analysis_result.txt', 'w', encoding='utf-8') as f:
    f.write(output)

print("Analysis complete. Results saved to analysis_result.txt")

conn.close()
