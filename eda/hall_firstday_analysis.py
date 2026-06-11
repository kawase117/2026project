import sqlite3
import pandas as pd
import sys
sys.stdout.reconfigure(encoding='utf-8')

halls = {
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

results = []
for hall, (path, db_start) in halls.items():
    conn = sqlite3.connect(path)
    df = pd.read_sql_query(
        'SELECT machine_name, date, games_normalized, diff_coins_normalized '
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
    fd = df2[df2['date'] == df2['debut_date']].copy()
    if fd.empty:
        continue

    fd['hall'] = hall
    results.append(fd)

df_all = pd.concat(results, ignore_index=True)
df_all['kaiwari'] = (
    100 + (df_all['diff_coins_normalized'] / df_all['games_normalized'].clip(lower=1)) / 3 * 100
)

# ==============================
# ホール別集計
# ==============================
hs = df_all.groupby('hall').agg(
    n_machine=('machine_name', 'nunique'),
    n_row=('kaiwari', 'count'),
    avg_games=('games_normalized', 'mean'),
    avg_diff=('diff_coins_normalized', 'mean'),
    avg_kaiwari=('kaiwari', 'mean'),
    med_diff=('diff_coins_normalized', 'median'),
    std_diff=('diff_coins_normalized', 'std'),
    plus_rate=('diff_coins_normalized', lambda x: (x > 0).mean() * 100),
).reset_index()

for c in ['avg_games', 'avg_diff', 'med_diff', 'std_diff']:
    hs[c] = hs[c].round(0).astype(int)
hs['avg_kaiwari'] = hs['avg_kaiwari'].round(1)
hs['plus_rate']   = hs['plus_rate'].round(1)
hs = hs.sort_values('avg_kaiwari', ascending=False)

print('=== ホール別 新台初日 機械割ランキング（生平均） ===')
print(hs[['hall', 'n_machine', 'n_row', 'avg_games', 'avg_diff',
           'avg_kaiwari', 'med_diff', 'plus_rate']].to_string(index=False))

# ==============================
# 固定効果: 同一機種を同時に導入したホール間での比較
# ==============================
machine_hall_count = df_all.groupby('machine_name')['hall'].nunique()
common_m = machine_hall_count[machine_hall_count >= 3].index
dfc = df_all[df_all['machine_name'].isin(common_m)].copy()

machine_avg = dfc.groupby('machine_name')['kaiwari'].mean().rename('m_avg')
dfc = dfc.join(machine_avg, on='machine_name')
dfc['resid'] = dfc['kaiwari'] - dfc['m_avg']

fe = dfc.groupby('hall').agg(
    n=('resid', 'count'),
    resid_kaiwari=('resid', 'mean'),
    avg_diff=('diff_coins_normalized', 'mean'),
).reset_index()
fe['resid_kaiwari'] = fe['resid_kaiwari'].round(2)
fe['avg_diff']      = fe['avg_diff'].round(0).astype(int)
fe = fe.sort_values('resid_kaiwari', ascending=False)

print()
print('=== 固定効果補正後 ランキング（同一機種比較）===')
print('（resid > 0 = 同機種の他ホール平均より高い設定を入れる傾向）')
print(fe.to_string(index=False))

# ==============================
# 月別ホール別 機械割推移
# ==============================
df_all['yearmonth'] = df_all['debut_date'].str[:6]

period_hall = df_all.groupby(['yearmonth', 'hall']).agg(
    n=('kaiwari', 'count'),
    avg_kaiwari=('kaiwari', 'mean'),
    avg_diff=('diff_coins_normalized', 'mean'),
).reset_index()
period_hall['avg_kaiwari'] = period_hall['avg_kaiwari'].round(1)
period_hall['avg_diff'] = period_hall['avg_diff'].round(0).astype(int)

pivot = period_hall.pivot_table(
    index='yearmonth', columns='hall', values='avg_kaiwari', aggfunc='mean'
).round(1)

print()
print('=== 月別ホール別 新台初日機械割（値=機械割%）===')
print(pivot.to_string())

# ==============================
# 機械割104%以上の出現率
# ==============================
THRESHOLD = 104.0

# 台単位で判定
df_all['hit104'] = df_all['kaiwari'] >= THRESHOLD

# ホール別
hs104 = df_all.groupby('hall').agg(
    n_row=('hit104', 'count'),
    hit104_count=('hit104', 'sum'),
    hit104_rate=('hit104', 'mean'),
    avg_kaiwari_when_hit=('kaiwari', lambda x: x[df_all.loc[x.index, 'hit104']].mean()),
).reset_index()
hs104['hit104_rate_pct'] = (hs104['hit104_rate'] * 100).round(1)
hs104['hit104_count']    = hs104['hit104_count'].astype(int)
hs104['avg_kaiwari_when_hit'] = hs104['avg_kaiwari_when_hit'].round(1)
hs104 = hs104.sort_values('hit104_rate_pct', ascending=False)

print()
print(f'=== ホール別 新台初日 機械割{THRESHOLD:.0f}%以上 出現率 ===')
print(hs104[['hall', 'n_row', 'hit104_count', 'hit104_rate_pct', 'avg_kaiwari_when_hit']].to_string(index=False))

# 固定効果補正後の104%出現率
dfc2 = df_all[df_all['machine_name'].isin(common_m)].copy()
machine_hit104_rate = dfc2.groupby('machine_name')['hit104'].mean().rename('m_hit104_rate')
dfc2 = dfc2.join(machine_hit104_rate, on='machine_name')
dfc2['hit104_resid'] = dfc2['hit104'].astype(float) - dfc2['m_hit104_rate']

fe104 = dfc2.groupby('hall').agg(
    n=('hit104_resid', 'count'),
    hit104_rate_pct=('hit104', lambda x: x.mean() * 100),
    resid_hit104=('hit104_resid', 'mean'),
).reset_index()
fe104['hit104_rate_pct'] = fe104['hit104_rate_pct'].round(1)
fe104['resid_hit104']    = fe104['resid_hit104'].round(4)
fe104 = fe104.sort_values('hit104_rate_pct', ascending=False)

print()
print(f'=== 固定効果補正後 機械割{THRESHOLD:.0f}%以上 出現率 ===')
print('（resid > 0 = 同機種の他ホール平均より高い設定を入れる頻度が高い）')
print(fe104.to_string(index=False))

# 閾値別感度チェック
print()
print('=== 閾値別 hit率サマリ（ホール順位の安定性確認）===')
for thr in [100, 102, 104, 106, 108, 110]:
    col = f'hit{thr}'
    df_all[col] = df_all['kaiwari'] >= thr
    rates = df_all.groupby('hall')[col].mean().mul(100).round(1)
    rates.name = f'>={thr}%'
    if thr == 100:
        summary = rates.to_frame()
    else:
        summary = summary.join(rates)

summary = summary.sort_values('>=104%', ascending=False)
print(summary.to_string())
