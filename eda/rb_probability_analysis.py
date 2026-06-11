"""
スマスロ北斗の拳・モンキーターンV・ジャグラー各種について、
機械割/差枚だけでなくRB確率(rb_probability_decimal)の観点からホール別の傾向を分析する。
games_normalized < 1000 は除外。
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

# 機種名 LIKE パターン と、設定4相当のRB確率(decimal)しきい値
# ジャグラー系はユーザー提供スペックの「設定4のRB確率」を1/X→decimalに変換
# 北斗の拳・モンキーターンVはスペック未提供のため empirical (全体の上位25%)で代用
TARGETS = {
    'スマスロ北斗の拳':     {'pattern': 'スマスロ北斗の拳', 'set4_rb_decimal': None},
    'モンキーターンV':       {'pattern': 'モンキーターンV',   'set4_rb_decimal': None},
    'アイムジャグラーEX-TP': {'pattern': 'アイムジャグラーEX-TP', 'set4_rb_decimal': 1/315.1},
    'マイジャグラーV':       {'pattern': 'マイジャグラーV',   'set4_rb_decimal': 1/290.0},
    'ファンキージャグラー2': {'pattern': 'ファンキージャグラー2', 'set4_rb_decimal': 1/322.8},
    'ゴーゴージャグラー3':   {'pattern': 'ゴーゴージャグラー3', 'set4_rb_decimal': 1/268.6},
    'ミスタージャグラー':    {'pattern': 'ミスタージャグラー', 'set4_rb_decimal': 1/291.3},
    'ジャグラーガールズ':    {'pattern': 'ジャグラーガールズ', 'set4_rb_decimal': 1/281.3},
    'ハッピージャグラーVIII': {'pattern': 'ハッピージャグラー', 'set4_rb_decimal': 1/300.6},
    'ウルトラミラクルジャグラー': {'pattern': 'ウルトラミラクルジャグラー', 'set4_rb_decimal': 1/322.8},
}

# 全ホール分のデータをロード
frames = []
for hall, path in HALLS.items():
    conn = sqlite3.connect(path)
    df = pd.read_sql_query(
        'SELECT machine_name, games_normalized, diff_coins_normalized, '
        'rb_count, rb_probability_decimal, bb_probability_decimal '
        'FROM machine_detailed_results '
        f'WHERE games_normalized >= {MIN_GAMES} AND rb_probability_decimal > 0',
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

for label, cfg in TARGETS.items():
    sub = df_all[df_all['machine_name'].str.contains(cfg['pattern'], na=False, regex=False)].copy()
    if sub.empty:
        print(f"\n--- {label}: データなし ---")
        continue

    set4_thr = cfg['set4_rb_decimal']
    if set4_thr is None:
        # empirical: 全体の75percentileをしきい値として代用
        set4_thr = sub['rb_probability_decimal'].quantile(0.75)
        thr_note = f"(empirical 75%ile=1/{1/set4_thr:.1f})"
    else:
        thr_note = f"(設定4相当: 1/{1/set4_thr:.1f})"

    sub['high_rb'] = (sub['rb_probability_decimal'] >= set4_thr).astype(int)

    g = sub.groupby('hall').agg(
        n=('rb_probability_decimal', 'count'),
        avg_games=('games_normalized', 'mean'),
        avg_rb_decimal=('rb_probability_decimal', 'mean'),
        high_rb_pct=('high_rb', lambda x: round(x.mean()*100, 1)),
        avg_kaiwari=('kaiwari', 'mean'),
        hit104_pct=('hit104', lambda x: round(x.mean()*100, 1)),
    ).reset_index()
    g = g[g['n'] >= 30]
    if g.empty:
        print(f"\n--- {label}: n>=30のホールなし ---")
        continue

    g['avg_rb_1overx'] = (1 / g['avg_rb_decimal']).round(1)
    g['avg_kaiwari'] = g['avg_kaiwari'].round(2)
    g = g.sort_values('high_rb_pct', ascending=False)

    print(f"\n{'='*70}")
    print(f"{label} {thr_note}  全体n={len(sub)}")
    print('=' * 70)
    print(g[['hall', 'n', 'avg_games', 'avg_rb_1overx', 'high_rb_pct', 'avg_kaiwari', 'hit104_pct']].to_string(index=False))
