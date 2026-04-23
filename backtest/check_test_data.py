import sqlite3
import pandas as pd
import sys
sys.stdout.reconfigure(encoding='utf-8')

db_path = '../db/マルハンメガシティ2000-蒲田1.db'
conn = sqlite3.connect(db_path)

print('=== テスト期間（2026年4月）のデータ日付 ===')
df_test_dates = pd.read_sql_query('''
    SELECT DISTINCT date, COUNT(*) as record_count
    FROM machine_detailed_results
    WHERE date >= '2026-04-01' AND date <= '2026-04-30'
    GROUP BY date
    ORDER BY date
''', conn)

print(f'データ存在日数: {len(df_test_dates)}')
if len(df_test_dates) > 0:
    print(f'最初の日付: {df_test_dates.iloc[0]["date"]}')
    print(f'最後の日付: {df_test_dates.iloc[-1]["date"]}')
print()
print(df_test_dates.to_string(index=False))

# dd（月内日付）の分布を確認
print('\n\n=== dd（月内日付）の分布 ===')
df_dd = pd.read_sql_query('''
    SELECT dd FROM machine_detailed_results
    WHERE date >= '2026-04-01' AND date <= '2026-04-30'
    GROUP BY dd
    ORDER BY dd
''', conn)
existing_dd = sorted(df_dd["dd"].tolist())
missing_dd = sorted(set(range(1, 31)) - set(existing_dd))

print(f'存在する dd: {existing_dd}')
print(f'存在しない dd: {missing_dd}')
print(f'データ日数: {len(existing_dd)}/30日')

# 訓練期間との比較
print('\n\n=== 訓練期間（2025年1月-3月）の dd 分布 ===')
df_train_dd = pd.read_sql_query('''
    SELECT dd FROM machine_detailed_results
    WHERE date >= '2025-01-01' AND date <= '2025-03-31'
    GROUP BY dd
    ORDER BY dd
''', conn)
train_dd = sorted(df_train_dd["dd"].tolist())
print(f'存在する dd: {train_dd}')

conn.close()
