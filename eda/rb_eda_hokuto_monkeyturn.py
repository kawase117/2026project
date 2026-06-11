"""
RBデータが信頼できるホール/機種に絞ってのEDA。

- モンキーターンV: bb_count>0が確認できたホールのみ（蒲田1, 蒲田7, 金時, ザシティ）
  楽園・ARROW・ヒロキ・レイトギャップ・みとやはbb_count=0でRB定義が異なるため除外
- スマスロ北斗の拳: 全ホールでbb_count>0を確認済みなので全ホール対象
- games_normalized < 1000 は除外
- 蒲田7のモンキーターンV 台番号2026（鉄板）は別枠で扱う
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
WEEKDAY_JP = {0:'月',1:'火',2:'水',3:'木',4:'金',5:'土',6:'日'}
MIN_GAMES = 1000

# モンキーターンV: bb_count>0(=RB定義が一致)を確認したホールのみ
MONKEYTURN_OK_HALLS = ['蒲田1', '蒲田7', '金時', 'ザシティ']

# RBスペック（1/X → decimal）。設定3は2と4の中間で線形補間。
SPEC = {
    'モンキーターンV': {
        1: 1/299.8, 2: 1/295.5, 3: (1/295.5 + 1/258.8)/2, 4: 1/258.8, 5: 1/235.7, 6: 1/222.9,
    },
    'スマスロ北斗の拳': {
        1: 1/383.4, 2: 1/370.5, 3: (1/370.5 + 1/297.8)/2, 4: 1/297.8, 5: 1/258.7, 6: 1/235.1,
    },
}


def load(machine_name, hall):
    conn = sqlite3.connect(HALLS[hall])
    df = pd.read_sql_query(
        'SELECT machine_number, date, games_normalized, diff_coins_normalized, rb_probability_decimal '
        'FROM machine_detailed_results '
        f"WHERE machine_name = ? AND games_normalized >= {MIN_GAMES} AND rb_probability_decimal > 0",
        conn, params=(machine_name,)
    )
    conn.close()
    if df.empty:
        return df
    dt = pd.to_datetime(df['date'], format='%Y%m%d')
    df['day_of_week'] = dt.dt.weekday.map(WEEKDAY_JP)
    df['last_digit'] = (df['machine_number'] % 10).astype(str)
    df['kaiwari'] = (
        100 + (df['diff_coins_normalized']
               / df['games_normalized'].clip(lower=1)) / 3 * 100
    )
    return df


def classify_setting(decimal, spec):
    # spec[N] = decimal閾値。decimal >= spec[N] なら設定N以上相当
    if decimal >= spec[5]:
        return '5+'
    elif decimal >= spec[4]:
        return '4'
    elif decimal >= spec[3]:
        return '3'
    elif decimal >= spec[1]:
        return '1-2'
    else:
        return '<1'


def run(machine_name, halls, exclude_machine_numbers=None):
    spec = SPEC[machine_name]
    frames = []
    for hall in halls:
        df = load(machine_name, hall)
        if df.empty:
            continue
        if exclude_machine_numbers and hall in exclude_machine_numbers:
            df = df[~df['machine_number'].isin(exclude_machine_numbers[hall])]
        df['hall'] = hall
        frames.append(df)
    if not frames:
        print(f"\n--- {machine_name}: データなし ---")
        return
    df_all = pd.concat(frames, ignore_index=True)
    df_all['setting_est'] = df_all['rb_probability_decimal'].apply(lambda x: classify_setting(x, spec))
    df_all['high_setting'] = df_all['setting_est'].isin(['4', '5+']).astype(int)

    print(f"\n{'='*70}")
    print(f"{machine_name}  (n={len(df_all)}, 対象ホール={halls})")
    print('=' * 70)

    print("\n[推定設定分布 全体]")
    print(df_all['setting_est'].value_counts(normalize=True).mul(100).round(1).to_string())

    print("\n[ホール別: 設定4以上推定率 / avg_kaiwari]")
    g = df_all.groupby('hall').agg(
        n=('high_setting', 'count'),
        high_setting_pct=('high_setting', lambda x: round(x.mean()*100, 1)),
        avg_kaiwari=('kaiwari', lambda x: round(x.mean(), 2)),
    ).sort_values('high_setting_pct', ascending=False)
    print(g.to_string())

    print("\n[曜日別: 設定4以上推定率]")
    base = df_all['high_setting'].mean() * 100
    wd = df_all.groupby('day_of_week').agg(
        n=('high_setting', 'count'),
        high_setting_pct=('high_setting', lambda x: round(x.mean()*100, 1)),
    ).reindex(['月','火','水','木','金','土','日'])
    wd['pp'] = (wd['high_setting_pct'] - base).round(1)
    print(f"(全体平均={base:.1f}%)")
    print(wd.to_string())

    print("\n[台番号末尾別: 設定4以上推定率]")
    ld = df_all.groupby('last_digit').agg(
        n=('high_setting', 'count'),
        high_setting_pct=('high_setting', lambda x: round(x.mean()*100, 1)),
    ).reindex([str(i) for i in range(10)])
    ld['pp'] = (ld['high_setting_pct'] - base).round(1)
    print(ld.to_string())


# 蒲田7の台番号2026は鉄板(常時設定6)と判明しているため除外して再計算
run('モンキーターンV', MONKEYTURN_OK_HALLS, exclude_machine_numbers={'蒲田7': [2026]})

print("\n\n" + "#"*70)
print("# 参考: 台番号2026を含めた場合の蒲田7単独")
print("#"*70)
df_2026 = load('モンキーターンV', '蒲田7')
df_2026_only = df_2026[df_2026['machine_number'] == 2026]
spec = SPEC['モンキーターンV']
df_2026_only = df_2026_only.copy()
df_2026_only['setting_est'] = df_2026_only['rb_probability_decimal'].apply(lambda x: classify_setting(x, spec))
print(f"台2026 (n={len(df_2026_only)}) 推定設定分布:")
print(df_2026_only['setting_est'].value_counts(normalize=True).mul(100).round(1).to_string())

run('スマスロ北斗の拳', list(HALLS.keys()))
