"""
機種×ホール 固定効果分析（全期間版）
- 3ホール以上で導入されている機種について、同一機種内でのホール間機械割差(固定効果)を比較
- 機種×ホールのhit104率トップ組み合わせを抽出
"""

import sqlite3
import pandas as pd
import sys
sys.stdout.reconfigure(encoding='utf-8')

HALLS = {
    '蒲田1':        'db/マルハンメガシティ2000-蒲田1.db',
    '蒲田7':        'db/マルハンメガシティ2000-蒲田7.db',
    '金時':         'db/金時京急蒲田店.db',
    '楽園':         'db/楽園蒲田店.db',
    'レイトギャップ': 'db/レイトギャップ平和島.db',
    'ARROW':        'db/ARROW池上店.db',
    'ヒロキ':       'db/ヒロキ東口店.db',
    'ザシティ':     'db/ザ-シティ-ベルシティ雑色店.db',
    'みとや':       'db/みとや大森町店.db',
}

MIN_GAMES = 1000
MIN_N_PER_HALL = 30   # 機種×ホールで最低この行数
MIN_HALLS = 3         # この台数以上のホールに導入されている機種のみ

frames = []
for hall, path in HALLS.items():
    conn = sqlite3.connect(path)
    df = pd.read_sql_query(
        'SELECT machine_name, games_normalized, diff_coins_normalized '
        'FROM machine_detailed_results '
        f'WHERE games_normalized >= {MIN_GAMES}',
        conn
    )
    conn.close()
    df['hall'] = hall
    frames.append(df)

df_all = pd.concat(frames, ignore_index=True)
df_all['kaiwari'] = (
    100 + (df_all['diff_coins_normalized']
           / df_all['games_normalized'].clip(lower=1)) / 3 * 100
)
df_all['hit104'] = (df_all['kaiwari'] >= 104.0).astype(int)

# ============================================================
# 機種×ホール 集計
# ============================================================
mh = df_all.groupby(['machine_name', 'hall']).agg(
    n=('kaiwari', 'count'),
    avg_kaiwari=('kaiwari', 'mean'),
    hit104_pct=('hit104', lambda x: x.mean() * 100),
).reset_index()
mh = mh[mh['n'] >= MIN_N_PER_HALL]

# 3ホール以上で条件を満たす機種のみ
hall_count = mh.groupby('machine_name')['hall'].nunique()
common_m = hall_count[hall_count >= MIN_HALLS].index
mhc = mh[mh['machine_name'].isin(common_m)].copy()

print(f"対象機種数（{MIN_HALLS}ホール以上・各ホールn>={MIN_N_PER_HALL}）: {len(common_m)}")
print()

# ============================================================
# 固定効果: 機種内平均との残差
# ============================================================
m_avg = mhc.groupby('machine_name')['avg_kaiwari'].mean().rename('m_avg_kaiwari')
m_hit_avg = mhc.groupby('machine_name')['hit104_pct'].mean().rename('m_avg_hit104')
mhc = mhc.join(m_avg, on='machine_name').join(m_hit_avg, on='machine_name')
mhc['resid_kaiwari'] = (mhc['avg_kaiwari'] - mhc['m_avg_kaiwari']).round(2)
mhc['resid_hit104']  = (mhc['hit104_pct'] - mhc['m_avg_hit104']).round(2)

# ホール別 固定効果サマリ
fe = mhc.groupby('hall').agg(
    n_machines=('machine_name', 'nunique'),
    n_rows=('n', 'sum'),
    avg_resid_kaiwari=('resid_kaiwari', 'mean'),
    avg_resid_hit104=('resid_hit104', 'mean'),
).reset_index()
fe['avg_resid_kaiwari'] = fe['avg_resid_kaiwari'].round(2)
fe['avg_resid_hit104']  = fe['avg_resid_hit104'].round(2)
fe = fe.sort_values('avg_resid_kaiwari', ascending=False)

print("=== ホール別 固定効果サマリ（全期間・3ホール以上共通機種） ===")
print("（resid > 0 = 同機種の他ホール平均より高い設定を入れる傾向）")
print(fe.to_string(index=False))

# ============================================================
# 機種別: ホール間のばらつき(resid_kaiwariのレンジ)が大きい機種トップ
# ============================================================
machine_range = mhc.groupby('machine_name').agg(
    n_halls=('hall', 'nunique'),
    total_n=('n', 'sum'),
    range_kaiwari=('resid_kaiwari', lambda x: x.max() - x.min()),
).reset_index()
machine_range['range_kaiwari'] = machine_range['range_kaiwari'].round(2)
machine_range = machine_range.sort_values('range_kaiwari', ascending=False)

print()
print("=== ホール間ばらつき(resid_kaiwariのmax-min)が大きい機種 TOP15 ===")
print(machine_range.head(15).to_string(index=False))

# 上位機種について、ホール別の内訳を表示
print()
print("=== 上位5機種のホール別内訳 ===")
for m in machine_range.head(5)['machine_name']:
    sub = mhc[mhc['machine_name'] == m].sort_values('resid_kaiwari', ascending=False)
    print(f"\n--- {m} ---")
    print(sub[['hall', 'n', 'avg_kaiwari', 'resid_kaiwari', 'hit104_pct', 'resid_hit104']].to_string(index=False))

# ============================================================
# 機種×ホールのhit104率トップ組み合わせ
# ============================================================
top_combo = mh[mh['n'] >= 50].sort_values('hit104_pct', ascending=False).head(20)
print()
print("=== 機種×ホール hit104率トップ20（n>=50） ===")
print(top_combo.to_string(index=False))
