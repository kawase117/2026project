"""
1. 新台導入後の日数(day_index)別 機械割推移カーブ ホール別比較
   - 初日だけ強い/初日は弱く後で強くなる、のホール差を見る
2. 蒲田7 アイムジャグラーEX-TP の streak を機械割104%基準で再検証
   （diffベースのstreak=86%との比較）
"""

import sqlite3
import pandas as pd
import sys
sys.stdout.reconfigure(encoding='utf-8')

HALLS = {
    '蒲田1':        ('db/マルハンメガシティ2000-蒲田1.db', '20250101'),
    '蒲田7':        ('db/マルハンメガシティ2000-蒲田7.db', '20250707'),
    '金時':         ('db/金時京急蒲田店.db',              '20250101'),
    '楽園':         ('db/楽園蒲田店.db',                  '20250101'),
    'レイトギャップ': ('db/レイトギャップ平和島.db',       '20250320'),
    'ARROW':        ('db/ARROW池上店.db',                 '20250101'),
    'ヒロキ':       ('db/ヒロキ東口店.db',               '20250101'),
    'ザシティ':     ('db/ザ-シティ-ベルシティ雑色店.db',  '20250101'),
    'みとや':       ('db/みとや大森町店.db',              '20250101'),
}

MAX_DAY_INDEX = 9  # day_index 0 (初日) 〜 9 (10日目)

# ============================================================
# Part 1: 新台導入後 day_index 別 機械割推移カーブ
# ============================================================
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

    # day_index: 同一機種の中で date を昇順に並べたときの通し番号(0始まり)
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

curve = df_all.groupby(['hall', 'day_index']).agg(
    n=('kaiwari', 'count'),
    avg_kaiwari=('kaiwari', 'mean'),
    hit104_pct=('hit104', lambda x: x.mean() * 100),
).reset_index()
curve['avg_kaiwari'] = curve['avg_kaiwari'].round(1)
curve['hit104_pct'] = curve['hit104_pct'].round(1)

print('=== 新台導入後 day_index 別 機械割カーブ（avg_kaiwari） ===')
pivot_kaiwari = curve.pivot_table(index='day_index', columns='hall', values='avg_kaiwari')
print(pivot_kaiwari.to_string())

print()
print('=== 新台導入後 day_index 別 hit104%（kaiwari>=104の割合） ===')
pivot_hit = curve.pivot_table(index='day_index', columns='hall', values='hit104_pct')
print(pivot_hit.to_string())

print()
print('=== サンプルサイズ n（day_index別ホール別） ===')
pivot_n = curve.pivot_table(index='day_index', columns='hall', values='n')
print(pivot_n.to_string())

# day_index 0 (初日) と 1-3日目平均 の差をホール別に
d0 = curve[curve['day_index'] == 0].set_index('hall')['avg_kaiwari']
d1_3 = (
    curve[curve['day_index'].between(1, 3)]
    .groupby('hall')['avg_kaiwari'].mean()
)
diff_table = pd.DataFrame({
    'day0_kaiwari': d0,
    'day1_3_avg_kaiwari': d1_3.round(1),
})
diff_table['day1_3_minus_day0'] = (diff_table['day1_3_avg_kaiwari'] - diff_table['day0_kaiwari']).round(1)
diff_table = diff_table.sort_values('day1_3_minus_day0', ascending=False)

print()
print('=== 初日(day0) vs 2-4日目平均(day1-3) の差 ===')
print('（プラス = 初日より2-4日目の方が機械割が高い = 「持続/後乗せ」型）')
print(diff_table.to_string())


# ============================================================
# Part 2: 蒲田7 アイムジャグラーEX-TP の streak（機械割104%基準）
# ============================================================
print()
print('=' * 70)
print('Part 2: 蒲田7 アイムジャグラーEX-TP streak (hit104基準)')
print('=' * 70)

conn = sqlite3.connect(HALLS['蒲田7'][0])
df_aim = pd.read_sql_query(
    "SELECT machine_name, machine_number, date, "
    "games_normalized, diff_coins_normalized "
    "FROM machine_detailed_results "
    "WHERE machine_name LIKE '%アイムジャグラーEX%' AND games_normalized >= 1000",
    conn
)
conn.close()

if df_aim.empty:
    print("該当データなし")
else:
    df_aim['kaiwari'] = (
        100 + (df_aim['diff_coins_normalized']
               / df_aim['games_normalized'].clip(lower=1)) / 3 * 100
    )
    df_aim['hit104'] = (df_aim['kaiwari'] >= 104.0).astype(int)
    df_aim = df_aim.sort_values(['machine_number', 'date'])
    df_aim['prev_hit'] = df_aim.groupby('machine_number')['hit104'].shift(1)
    df_aim2 = df_aim.dropna(subset=['prev_hit']).copy()
    df_aim2['prev_hit'] = df_aim2['prev_hit'].astype(int)

    base = df_aim['hit104'].mean() * 100
    streak = df_aim2[df_aim2['prev_hit'] == 1]['hit104'].mean() * 100
    rebound = df_aim2[df_aim2['prev_hit'] == 0]['hit104'].mean() * 100
    n1 = (df_aim2['prev_hit'] == 1).sum()
    n0 = (df_aim2['prev_hit'] == 0).sum()

    print(f"全体 hit104率(baseline): {base:.1f}% (n={len(df_aim)})")
    print(f"前日hit104→翌日hit104率: {streak:.1f}% (n={n1}) [streak_pp={streak-base:+.1f}]")
    print(f"前日miss→翌日hit104率:  {rebound:.1f}% (n={n0}) [rebound_pp={rebound-base:+.1f}]")

    # 台番号別の内訳
    print()
    print("=== 台番号別 hit104率 ===")
    by_machine = df_aim.groupby('machine_number').agg(
        n=('hit104', 'count'),
        hit104_pct=('hit104', lambda x: round(x.mean()*100, 1)),
        avg_kaiwari=('kaiwari', lambda x: round(x.mean(), 1)),
    ).reset_index().sort_values('hit104_pct', ascending=False)
    print(by_machine.to_string(index=False))
