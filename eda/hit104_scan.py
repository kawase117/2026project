"""
機械割104%以上 出現率スキャン
差枚スキャンと同じ21次元を min_games=1000 で走査し、
Tier A/B パターンは min_games=3000 でも再検証する。

Tier 判定（ベースラインとの差 pp で）:
  A: pp >= 10  かつ n >= 30
  B: pp >=  5  かつ n >= 20
  C: それ以外
"""

import sqlite3
import pandas as pd
import numpy as np
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
WEEKDAY_JP = {0:'月',1:'火',2:'水',3:'木',4:'金',5:'土',6:'日'}
KAIWARI_THR = 104.0
TIER_A_PP, TIER_B_PP = 10.0, 5.0
MIN_N_A,   MIN_N_B   = 30,   20


def load_all(min_games: int) -> pd.DataFrame:
    frames = []
    for hall, (path, _) in HALLS.items():
        conn = sqlite3.connect(path)
        df = pd.read_sql_query(
            'SELECT machine_name, machine_number, date, '
            'games_normalized, diff_coins_normalized '
            'FROM machine_detailed_results '
            f'WHERE games_normalized >= {min_games}',
            conn
        )
        conn.close()
        df['hall'] = hall
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    dt = pd.to_datetime(df['date'], format='%Y%m%d')
    df['day_of_week'] = dt.dt.weekday.map(WEEKDAY_JP)
    df['dd']          = dt.dt.day
    df['dd_mod10']    = df['dd'] % 10
    df['last_digit']  = (df['machine_number'] % 10).astype(str)
    df['weekday_nth'] = dt.apply(
        lambda d: f"{WEEKDAY_JP[d.weekday()]}{(d.day-1)//7+1}"
    )
    df['kaiwari'] = (
        100 + (df['diff_coins_normalized']
               / df['games_normalized'].clip(lower=1)) / 3 * 100
    )
    df['hit104'] = (df['kaiwari'] >= KAIWARI_THR).astype(int)
    return df


def tier(pp: float, n: int) -> str:
    if pp >= TIER_A_PP and n >= MIN_N_A:
        return 'A'
    if pp >= TIER_B_PP and n >= MIN_N_B:
        return 'B'
    return 'C'


def scan_dim(df: pd.DataFrame, groupby_cols, label: str,
             baseline: float, hall: str) -> pd.DataFrame:
    grp = df.groupby(groupby_cols).agg(
        n=('hit104', 'count'),
        hit_rate=('hit104', 'mean'),
    ).reset_index()
    grp['hit_pct'] = (grp['hit_rate'] * 100).round(1)
    grp['pp']      = (grp['hit_pct'] - baseline).round(1)
    grp['tier']    = grp.apply(lambda r: tier(r['pp'], r['n']), axis=1)
    grp = grp[grp['tier'].isin(['A', 'B'])].copy()
    if grp.empty:
        return grp
    key_cols = groupby_cols if isinstance(groupby_cols, list) else [groupby_cols]
    grp['key'] = grp[key_cols].astype(str).agg('/'.join, axis=1)
    grp['dimension'] = label
    grp['hall'] = hall
    return grp[['tier', 'hall', 'dimension', 'key', 'n', 'hit_pct', 'pp']]


def run_scan(df: pd.DataFrame, tag: str) -> pd.DataFrame:
    baseline_all = df['hit104'].mean() * 100
    hall_base = (df.groupby('hall')['hit104'].mean() * 100).to_dict()
    print(f"\n[{tag}] 全体baseline={baseline_all:.1f}% (n={len(df):,})")

    results = []

    # ── 全ホール合算 1次元 ──
    for col, label in [
        ('day_of_week', '曜日'),
        ('dd',          'DD個別'),
        ('dd_mod10',    'DD_mod10(X系)'),
        ('last_digit',  '台番号末尾'),
        ('weekday_nth', '第N曜日'),
    ]:
        results.append(scan_dim(df, col, label, baseline_all, '全ホール'))

    # ── 全ホール合算 2次元 ──
    for cols, label in [
        (['day_of_week', 'dd_mod10'],    '曜日×DD_mod10'),
        (['day_of_week', 'last_digit'],  '曜日×台番号末尾'),
        (['dd_mod10',    'last_digit'],  'DD_mod10×台番号末尾'),
        (['hall',        'dd_mod10'],    'ホール×DD_mod10'),
        (['hall',        'day_of_week'], 'ホール×曜日'),
        (['machine_name','day_of_week'], '機種×曜日'),
        (['machine_name','dd_mod10'],    '機種×DD_mod10'),
    ]:
        results.append(scan_dim(df, cols, label, baseline_all, '全ホール'))

    # ── ホール別個別スキャン ──
    for hall in HALLS:
        dh = df[df['hall'] == hall]
        if len(dh) < 100:
            continue
        base_h = hall_base.get(hall, baseline_all)

        for col, label in [
            ('day_of_week', '曜日'),
            ('dd',          'DD個別'),
            ('dd_mod10',    'DD_mod10(X系)'),
            ('last_digit',  '台番号末尾'),
            ('weekday_nth', '第N曜日'),
        ]:
            results.append(scan_dim(dh, col, label, base_h, hall))

        for cols, label in [
            (['day_of_week', 'dd_mod10'],    '曜日×DD_mod10'),
            (['day_of_week', 'last_digit'],  '曜日×台番号末尾'),
            (['machine_name','day_of_week'], '機種×曜日'),
            (['machine_name','dd_mod10'],    '機種×DD_mod10'),
        ]:
            results.append(scan_dim(dh, cols, label, base_h, hall))

    non_empty = [r for r in results if not r.empty]
    if not non_empty:
        return pd.DataFrame()
    out = pd.concat(non_empty, ignore_index=True)
    return out.sort_values(['tier', 'pp'], ascending=[True, False])


def lag_scan(df: pd.DataFrame, tag: str):
    print(f"\n[{tag}] ラグ分析（前日hit104→翌日hit104率）")
    df2 = df.sort_values(['hall', 'machine_number', 'date']).copy()
    df2['prev_hit'] = df2.groupby(['hall', 'machine_number'])['hit104'].shift(1)
    df2 = df2.dropna(subset=['prev_hit'])
    df2['prev_hit'] = df2['prev_hit'].astype(int)

    rows = []
    for hall in ['全ホール'] + list(HALLS.keys()):
        dh = df2 if hall == '全ホール' else df2[df2['hall'] == hall]
        if len(dh) < 200:
            continue
        base   = dh['hit104'].mean() * 100
        streak = dh[dh['prev_hit']==1]['hit104'].mean() * 100
        rebound= dh[dh['prev_hit']==0]['hit104'].mean() * 100
        n1 = (dh['prev_hit']==1).sum()
        n0 = (dh['prev_hit']==0).sum()
        rows.append({
            'hall': hall, 'baseline': round(base,1),
            '前日hit→翌日hit%': round(streak,1), 'n_streak': n1,
            '前日miss→翌日hit%': round(rebound,1), 'n_rebound': n0,
            'streak_pp': round(streak-base, 1),
        })
    print(pd.DataFrame(rows).to_string(index=False))


# ── 実行 ──────────────────────────────────────────
if __name__ == '__main__':
    print("=" * 70)
    print("PASS 1: min_games=1000")
    print("=" * 70)
    df1000 = load_all(1000)
    r1000  = run_scan(df1000, 'min_games=1000')

    if r1000.empty:
        print("Tier A/B なし")
    else:
        print(f"\nTier A/B 件数: {len(r1000)}")
        print(r1000.to_string(index=False))

    lag_scan(df1000, 'min_games=1000')

    # Tier A の (hall, dimension, key) を保存
    tier_a_set = set()
    if not r1000.empty:
        for _, row in r1000[r1000['tier']=='A'].iterrows():
            tier_a_set.add((row['hall'], row['dimension'], row['key']))

    print("\n" + "=" * 70)
    print("PASS 2: min_games=3000")
    print("=" * 70)
    df3000 = load_all(3000)
    r3000  = run_scan(df3000, 'min_games=3000')

    if r3000.empty:
        print("Tier A/B なし")
    else:
        print(f"\nTier A/B 件数: {len(r3000)}")
        print(r3000.to_string(index=False))

    lag_scan(df3000, 'min_games=3000')

    # 1000G Tier A → 3000Gで生存
    if not r3000.empty and tier_a_set:
        surviving = r3000[
            r3000.apply(
                lambda r: (r['hall'], r['dimension'], r['key']) in tier_a_set,
                axis=1
            )
        ]
        print(f"\n★ 1000G Tier A → 3000G生存: {len(surviving)}件")
        if not surviving.empty:
            print(surviving.to_string(index=False))
