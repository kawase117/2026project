"""
新台投入0-7日目の機械割しきい値別 出現率分析
- kaiwari >= 104 / 108 / 112 の出現率(%)をホール別・day_index別に算出
- 既存レポート(document/reports/new_machine_0_7_*)と同一条件:
  games_normalized >= 200, debut_date > db_start, day_index 0-7
"""

import sqlite3
import pandas as pd
import sys
sys.stdout.reconfigure(encoding='utf-8')

HALLS = {
    '蒲田一':        ('db/マルハンメガシティ2000-蒲田1.db', '20250101'),
    '蒲田七':        ('db/マルハンメガシティ2000-蒲田7.db', '20250707'),
    '金時':         ('db/金時京急蒲田店.db',              '20250101'),
    '楽園':         ('db/楽園蒲田店.db',                  '20250101'),
    'レイトギャップ': ('db/レイトギャップ平和島.db',       '20250320'),
    'ARROW':        ('db/ARROW池上店.db',                 '20250101'),
    'ヒロキ':       ('db/ヒロキ東口店.db',               '20250101'),
    'ザシティ':     ('db/ザ-シティ-ベルシティ雑色店.db',  '20250101'),
    'みとや':       ('db/みとや大森町店.db',              '20250101'),
}

MAX_DAY_INDEX = 7
THRESHOLDS = [104, 108, 112]

frames = []
for hall, (path, db_start) in HALLS.items():
    conn = sqlite3.connect(path)
    df = pd.read_sql_query(
        'SELECT machine_name, machine_number, date, '
        'games_normalized, diff_coins_normalized '
        'FROM machine_detailed_results WHERE games_normalized >= 200',
        conn
    )
    conn.close()
    if df.empty:
        continue

    debut = df.groupby('machine_name')['date'].min().reset_index()
    debut.columns = ['machine_name', 'debut_date']
    new_m = debut[debut['debut_date'] > db_start]

    df2 = df.merge(new_m, on='machine_name')
    if df2.empty:
        continue

    df2 = df2.sort_values(['machine_name', 'date'])
    df2['day_index'] = df2.groupby('machine_name').cumcount()
    df2 = df2[df2['day_index'] <= MAX_DAY_INDEX]

    df2['hall'] = hall
    frames.append(df2)

df_all = pd.concat(frames, ignore_index=True)
df_all['kaiwari'] = (
    100 + (df_all['diff_coins_normalized']
           / df_all['games_normalized'].clip(lower=1)) / 3 * 100
)
for t in THRESHOLDS:
    df_all[f'hit{t}'] = (df_all['kaiwari'] >= t).astype(int)

# --- ホール別 全体(0-7日) 出現率 ---
agg_dict = {'n': ('kaiwari', 'count'), 'avg_kaiwari': ('kaiwari', 'mean')}
for t in THRESHOLDS:
    agg_dict[f'hit{t}_pct'] = (f'hit{t}', lambda x: x.mean() * 100)

hall_summary = df_all.groupby('hall').agg(**agg_dict).reset_index()
hall_summary['avg_kaiwari'] = hall_summary['avg_kaiwari'].round(1)
for t in THRESHOLDS:
    hall_summary[f'hit{t}_pct'] = hall_summary[f'hit{t}_pct'].round(1)
hall_summary = hall_summary.sort_values('avg_kaiwari', ascending=False)

print('=== ホール別 新台0-7日 出現率サマリー ===')
print(hall_summary.to_string(index=False))

# --- 全体(全ホール込み) day_index別 出現率 ---
print()
print('=== 全ホール込み day_index別 出現率 ===')
agg_dict2 = {'n': ('kaiwari', 'count'), 'avg_kaiwari': ('kaiwari', 'mean')}
for t in THRESHOLDS:
    agg_dict2[f'hit{t}_pct'] = (f'hit{t}', lambda x: x.mean() * 100)
day_summary = df_all.groupby('day_index').agg(**agg_dict2).reset_index()
day_summary['avg_kaiwari'] = day_summary['avg_kaiwari'].round(1)
for t in THRESHOLDS:
    day_summary[f'hit{t}_pct'] = day_summary[f'hit{t}_pct'].round(1)
print(day_summary.to_string(index=False))

# --- ホール×day_index 別 hit104/108/112 ---
for t in THRESHOLDS:
    print()
    print(f'=== ホール×day_index別 hit{t}%（kaiwari>={t}の割合） ===')
    pivot = df_all.groupby(['hall', 'day_index'])[f'hit{t}'].mean().mul(100).round(1)
    pivot_table = pivot.reset_index().pivot(index='day_index', columns='hall', values=f'hit{t}')
    print(pivot_table.to_string())

# --- 全体での母数(n) ---
print()
print(f'=== 全体サンプル数: n = {len(df_all)} ===')
