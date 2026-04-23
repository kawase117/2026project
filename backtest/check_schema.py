import sqlite3
import pandas as pd
import sys
sys.stdout.reconfigure(encoding='utf-8')

db_path = '../db/マルハンメガシティ2000-蒲田1.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print('=== テーブル一覧 ===')
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
for table in tables:
    print(f'  - {table[0]}')

print('\n=== machine_detailed_results のカラム ===')
cursor.execute('PRAGMA table_info(machine_detailed_results)')
columns = cursor.fetchall()
for col in columns:
    print(f'  {col[1]}: {col[2]}')

print('\n=== データ日付範囲 ===')
df_dates = pd.read_sql_query('SELECT MIN(date) as min_date, MAX(date) as max_date, COUNT(*) as count FROM machine_detailed_results', conn)
print(df_dates.to_string(index=False))

print('\n=== 2026年のレコード数 ===')
df_2026 = pd.read_sql_query("SELECT COUNT(*) as count FROM machine_detailed_results WHERE date LIKE '2026%'", conn)
print(f'{df_2026.iloc[0][0]} レコード')

print('\n=== データが存在する最新月 ===')
df_latest = pd.read_sql_query('SELECT DISTINCT date FROM machine_detailed_results ORDER BY date DESC LIMIT 5', conn)
print(df_latest.to_string(index=False))

conn.close()
