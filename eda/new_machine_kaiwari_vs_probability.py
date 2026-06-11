"""
新台投入0-7日目: kaiwariバケット別 total_probability_decimal / bb_probability_decimal の比較
- kaiwari < 104 / 104-112 / >= 112 の3バケットでホール別の平均確率を比較
- 「1or6型(メリハリ)」なら112+バケットで確率がジャンプして高くなるはず
- 「3,4,5,6を満遍なく使う段階型」なら104->104-112->112+ で滑らかに上昇するはず
- total_probability_decimal は 1/total_probability_fraction で、値が大きいほど
  ボーナス確率が高い=高設定の傾向を示す
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
        'games_normalized, diff_coins_normalized, '
        'total_probability_decimal, bb_probability_decimal '
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

df_all['kaiwari_bucket'] = pd.cut(
    df_all['kaiwari'],
    bins=[-float('inf'), 104, 112, float('inf')],
    labels=['<104', '104-112', '>=112'],
)

# --- 1. 全体（全ホール込み）バケット別 確率平均 ---
print('=== 1. 全体 kaiwariバケット別 確率平均 ===')
overall = df_all.groupby('kaiwari_bucket', observed=True).agg(
    n=('kaiwari', 'count'),
    avg_kaiwari=('kaiwari', 'mean'),
    avg_total_prob=('total_probability_decimal', 'mean'),
    avg_bb_prob=('bb_probability_decimal', 'mean'),
).reset_index()
overall['avg_kaiwari'] = overall['avg_kaiwari'].round(1)
overall['avg_total_prob'] = overall['avg_total_prob'].round(5)
overall['avg_bb_prob'] = overall['avg_bb_prob'].round(5)
print(overall.to_string(index=False))

# --- 2. ホール別 x kaiwariバケット別 確率平均 ---
print()
print('=== 2. ホール別 x kaiwariバケット別 avg_total_probability_decimal ===')
hall_bucket = df_all.groupby(['hall', 'kaiwari_bucket'], observed=True).agg(
    n=('kaiwari', 'count'),
    avg_total_prob=('total_probability_decimal', 'mean'),
).reset_index()
hall_bucket['avg_total_prob'] = hall_bucket['avg_total_prob'].round(5)
pivot_prob = hall_bucket.pivot(index='hall', columns='kaiwari_bucket', values='avg_total_prob')
pivot_prob = pivot_prob[['<104', '104-112', '>=112']]
pivot_n = hall_bucket.pivot(index='hall', columns='kaiwari_bucket', values='n')
pivot_n = pivot_n[['<104', '104-112', '>=112']]
print(pivot_prob.to_string())
print()
print('--- n ---')
print(pivot_n.to_string())

# --- 3. ジャンプ幅: (>=112) - (104-112) vs (104-112) - (<104) ---
print()
print('=== 3. ステップ幅の比較 (確率の差分) ===')
step_table = pd.DataFrame({
    'low_to_mid': (pivot_prob['104-112'] - pivot_prob['<104']),
    'mid_to_high': (pivot_prob['>=112'] - pivot_prob['104-112']),
})
step_table['high_minus_low_total'] = pivot_prob['>=112'] - pivot_prob['<104']
step_table['mid_to_high_ratio'] = (step_table['mid_to_high'] / step_table['high_minus_low_total']).round(2)
step_table = step_table.round(6)
print(step_table.to_string())
print()
print('mid_to_high_ratio が高いほど「>=112で確率がジャンプ」=メリハリ(1or6)型')
print('mid_to_high_ratio が0.5前後 かつ low_to_midも大きければ段階的(3-6満遍なく)型')

# --- 4. bb_probability_decimal でも同様に ---
print()
print('=== 4. ホール別 x kaiwariバケット別 avg_bb_probability_decimal ===')
hall_bucket_bb = df_all.groupby(['hall', 'kaiwari_bucket'], observed=True).agg(
    avg_bb_prob=('bb_probability_decimal', 'mean'),
).reset_index()
hall_bucket_bb['avg_bb_prob'] = hall_bucket_bb['avg_bb_prob'].round(5)
pivot_bb = hall_bucket_bb.pivot(index='hall', columns='kaiwari_bucket', values='avg_bb_prob')
pivot_bb = pivot_bb[['<104', '104-112', '>=112']]
print(pivot_bb.to_string())

print()
print(f'=== 全体サンプル数: n = {len(df_all)} ===')
