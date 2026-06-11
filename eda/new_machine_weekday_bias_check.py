"""
新台投入0-7日目における曜日バイアスの検証
- 過去のやり取りで「月曜が最も強く、土日は全体では強くない」という結論が出た。
- 同条件(games_normalized>=200, debut_date>db_start, day_index 0-7)で再現し、
  さらにホール別の Monday/Weekend lift も確認して一般化可能か切り分ける。
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
df_all['hit104'] = (df_all['kaiwari'] >= 104.0).astype(int)

df_all['date_dt'] = pd.to_datetime(df_all['date'], format='%Y%m%d')
df_all['weekday'] = df_all['date_dt'].dt.dayofweek  # 0=Mon ... 6=Sun
weekday_names = {0: 'Mon', 1: 'Tue', 2: 'Wed', 3: 'Thu', 4: 'Fri', 5: 'Sat', 6: 'Sun'}
df_all['weekday_name'] = df_all['weekday'].map(weekday_names)

df_all['weekday_group'] = 'OtherWeekday'
df_all.loc[df_all['weekday'] == 0, 'weekday_group'] = 'Mon'
df_all.loc[df_all['weekday'].isin([5, 6]), 'weekday_group'] = 'Weekend'

# --- 1. 全体 (全ホール込み) day_index x weekday_group ---
print('=== 1. day_index x weekday_group サマリー (全ホール込み) ===')
summary = df_all.groupby(['day_index', 'weekday_group']).agg(
    n=('kaiwari', 'count'),
    avg_kaiwari=('kaiwari', 'mean'),
    win_rate_pct=('diff_coins_normalized', lambda s: (s > 0).mean() * 100),
    hit104_pct=('hit104', lambda x: x.mean() * 100),
).reset_index()
summary['avg_kaiwari'] = summary['avg_kaiwari'].round(1)
summary['win_rate_pct'] = summary['win_rate_pct'].round(1)
summary['hit104_pct'] = summary['hit104_pct'].round(1)
print(summary.sort_values(['day_index', 'weekday_group']).to_string(index=False))

# --- 2. 全体 weekday_group のみ ---
print()
print('=== 2. weekday_group 全体サマリー ===')
overall = df_all.groupby('weekday_group').agg(
    n=('kaiwari', 'count'),
    avg_kaiwari=('kaiwari', 'mean'),
    win_rate_pct=('diff_coins_normalized', lambda s: (s > 0).mean() * 100),
    hit104_pct=('hit104', lambda x: x.mean() * 100),
).reset_index()
overall['avg_kaiwari'] = overall['avg_kaiwari'].round(1)
overall['win_rate_pct'] = overall['win_rate_pct'].round(1)
overall['hit104_pct'] = overall['hit104_pct'].round(1)
print(overall.to_string(index=False))

# --- 3. day_index x 曜日(7曜日フル)で Mon の山を再確認 ---
print()
print('=== 3. day_index x 曜日(7曜日) avg_kaiwari ===')
pivot_full = df_all.groupby(['day_index', 'weekday_name'])['kaiwari'].mean().round(1)
pivot_full = pivot_full.reset_index().pivot(index='day_index', columns='weekday_name', values='kaiwari')
pivot_full = pivot_full[['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']]
print(pivot_full.to_string())

# --- 4. ホール別 Monday / Weekend lift ---
print()
print('=== 4. ホール別 weekday_group avg_kaiwari (Mon/Weekend/OtherWeekdayとの差) ===')
hall_pivot = df_all.groupby(['hall', 'weekday_group'])['kaiwari'].mean().round(1)
hall_pivot = hall_pivot.reset_index().pivot(index='hall', columns='weekday_group', values='kaiwari')
hall_pivot['Mon_minus_Other'] = (hall_pivot['Mon'] - hall_pivot['OtherWeekday']).round(1)
hall_pivot['Weekend_minus_Other'] = (hall_pivot['Weekend'] - hall_pivot['OtherWeekday']).round(1)
print(hall_pivot.to_string())

# --- 5. ホール別 n (サンプル数の偏り確認) ---
print()
print('=== 5. ホール別 weekday_group n ===')
hall_n = df_all.groupby(['hall', 'weekday_group']).size().reset_index(name='n')
hall_n_pivot = hall_n.pivot(index='hall', columns='weekday_group', values='n')
print(hall_n_pivot.to_string())

# --- 6. Monday lift の符号一致ホール数 ---
print()
n_pos = (hall_pivot['Mon_minus_Other'] > 0).sum()
n_total = len(hall_pivot)
print(f'Monday > OtherWeekday となったホール数: {n_pos} / {n_total}')
n_pos_we = (hall_pivot['Weekend_minus_Other'] > 0).sum()
print(f'Weekend > OtherWeekday となったホール数: {n_pos_we} / {n_total}')

print()
print(f'=== 全体サンプル数: n = {len(df_all)} ===')
