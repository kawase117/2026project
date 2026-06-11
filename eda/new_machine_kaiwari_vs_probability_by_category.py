"""
新台投入0-7日目: 機種カテゴリ別(ジャグラー系/オキドキ系/ハナハナ系/AT機/その他)に分けたうえで
kaiwariバケット別 total_probability_decimal の比較
- 前回(new_machine_kaiwari_vs_probability.py)の結果はホール間の機種構成の違いが
  確率の絶対値・ジャンプ比率に影響している可能性があったため、machine_master の
  jug_flag/hana_flag/oki_flag/bt_flag でカテゴリ分けして再検証する
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
    master = pd.read_sql_query(
        'SELECT machine_name_normalized, jug_flag, hana_flag, oki_flag, bt_flag '
        'FROM machine_master',
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

    df2 = df2.merge(
        master, left_on='machine_name', right_on='machine_name_normalized', how='left'
    )

    frames.append(df2)

df_all = pd.concat(frames, ignore_index=True)
df_all['kaiwari'] = (
    100 + (df_all['diff_coins_normalized']
           / df_all['games_normalized'].clip(lower=1)) / 3 * 100
)

# --- カテゴリ判定 ---
def categorize(row):
    if row.get('jug_flag') == 1:
        return 'ジャグラー系'
    if row.get('hana_flag') == 1:
        return 'ハナハナ系'
    if row.get('oki_flag') == 1:
        return '沖ドキ系'
    if row.get('bt_flag') == 1:
        return 'BT機'
    if pd.isna(row.get('jug_flag')):
        return '(マスタ未登録)'
    return 'AT機・その他'

df_all['category'] = df_all.apply(categorize, axis=1)

print('=== 0. machine_masterマッチ状況 ===')
print(df_all['category'].value_counts().to_string())
print()

df_all['kaiwari_bucket'] = pd.cut(
    df_all['kaiwari'],
    bins=[-float('inf'), 104, 112, float('inf')],
    labels=['<104', '104-112', '>=112'],
)

# --- 1. カテゴリ別 全体 kaiwariバケット x 確率 ---
print('=== 1. カテゴリ別 kaiwariバケット x avg_total_probability_decimal ===')
cat_bucket = df_all.groupby(['category', 'kaiwari_bucket'], observed=True).agg(
    n=('kaiwari', 'count'),
    avg_kaiwari=('kaiwari', 'mean'),
    avg_total_prob=('total_probability_decimal', 'mean'),
).reset_index()
cat_bucket['avg_kaiwari'] = cat_bucket['avg_kaiwari'].round(1)
cat_bucket['avg_total_prob'] = cat_bucket['avg_total_prob'].round(5)
print(cat_bucket.to_string(index=False))

# --- 2. ホール x カテゴリ別 サンプル数（機種構成の違いを確認） ---
print()
print('=== 2. ホール x カテゴリ別 n（機種構成の確認） ===')
hall_cat_n = df_all.groupby(['hall', 'category']).size().reset_index(name='n')
pivot_n = hall_cat_n.pivot(index='hall', columns='category', values='n').fillna(0).astype(int)
print(pivot_n.to_string())

# --- 3. 主要カテゴリ(ジャグラー系/AT機・その他)に絞ってホール別ジャンプ比率を再計算 ---
for target_cat in ['ジャグラー系', 'AT機・その他']:
    print()
    print(f'=== 3. カテゴリ={target_cat} 限定: ホール別 kaiwariバケット x avg_total_prob ===')
    sub = df_all[df_all['category'] == target_cat]
    if sub.empty:
        print('(データなし)')
        continue
    hall_bucket = sub.groupby(['hall', 'kaiwari_bucket'], observed=True).agg(
        n=('kaiwari', 'count'),
        avg_total_prob=('total_probability_decimal', 'mean'),
    ).reset_index()
    pivot_prob = hall_bucket.pivot(index='hall', columns='kaiwari_bucket', values='avg_total_prob')
    pivot_n2 = hall_bucket.pivot(index='hall', columns='kaiwari_bucket', values='n')
    for col in ['<104', '104-112', '>=112']:
        if col not in pivot_prob.columns:
            pivot_prob[col] = pd.NA
        if col not in pivot_n2.columns:
            pivot_n2[col] = 0
    pivot_prob = pivot_prob[['<104', '104-112', '>=112']].round(5)
    pivot_n2 = pivot_n2[['<104', '104-112', '>=112']].fillna(0).astype(int)

    step_table = pd.DataFrame({
        'low_to_mid': (pivot_prob['104-112'] - pivot_prob['<104']),
        'mid_to_high': (pivot_prob['>=112'] - pivot_prob['104-112']),
    })
    step_table['mid_to_high_ratio'] = (
        step_table['mid_to_high'] / (pivot_prob['>=112'] - pivot_prob['<104'])
    ).round(2)

    print(pivot_prob.to_string())
    print('--- n ---')
    print(pivot_n2.to_string())
    print('--- ratio ---')
    print(step_table.round(6).to_string())

print()
print(f'=== 全体サンプル数: n = {len(df_all)} ===')
