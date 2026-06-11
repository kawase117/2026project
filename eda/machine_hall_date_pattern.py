"""
機種×ホール固有パターンの日付/曜日依存性チェック
前回特定した強い機種×ホール組み合わせについて、
曜日別・DD_mod10別のhit104率/機械割を見て、
「特定の日に集中投入されているのか」「常時強いのか」を判別する。
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

# 検証対象: (機種名, ホール, min_games)
TARGETS = [
    ('押忍！番長4', '蒲田7', 1000),
    ('無職転生 ～異世界行ったら本気だす～', '金時', 1000),
    ('甲鉄城のカバネリ', '蒲田1', 1000),
    ('甲鉄城のカバネリ', '蒲田7', 1000),
    ('真・一騎当千', '蒲田7', 1000),
]


def load(machine_name, hall, min_games):
    conn = sqlite3.connect(HALLS[hall])
    df = pd.read_sql_query(
        'SELECT machine_number, date, games_normalized, diff_coins_normalized '
        'FROM machine_detailed_results '
        f'WHERE machine_name = ? AND games_normalized >= {min_games}',
        conn, params=(machine_name,)
    )
    conn.close()
    if df.empty:
        return df
    dt = pd.to_datetime(df['date'], format='%Y%m%d')
    df['day_of_week'] = dt.dt.weekday.map(WEEKDAY_JP)
    df['dd'] = dt.dt.day
    df['dd_mod10'] = df['dd'] % 10
    df['kaiwari'] = (
        100 + (df['diff_coins_normalized']
               / df['games_normalized'].clip(lower=1)) / 3 * 100
    )
    df['hit104'] = (df['kaiwari'] >= 104.0).astype(int)
    return df


for machine_name, hall, min_games in TARGETS:
    df = load(machine_name, hall, min_games)
    if df.empty:
        print(f"\n--- {machine_name} × {hall} : データなし ---")
        continue

    base = df['hit104'].mean() * 100
    print(f"\n{'='*70}")
    print(f"{machine_name} × {hall}  (n={len(df)}, baseline hit104={base:.1f}%, "
          f"avg_kaiwari={df['kaiwari'].mean():.1f})")
    print('=' * 70)

    # 曜日別
    wd = df.groupby('day_of_week').agg(
        n=('hit104', 'count'),
        hit104_pct=('hit104', lambda x: round(x.mean()*100, 1)),
        avg_kaiwari=('kaiwari', lambda x: round(x.mean(), 1)),
    ).reindex(['月','火','水','木','金','土','日'])
    wd['pp'] = (wd['hit104_pct'] - base).round(1)
    print("\n[曜日別]")
    print(wd.to_string())

    # DD_mod10別
    dd = df.groupby('dd_mod10').agg(
        n=('hit104', 'count'),
        hit104_pct=('hit104', lambda x: round(x.mean()*100, 1)),
        avg_kaiwari=('kaiwari', lambda x: round(x.mean(), 1)),
    )
    dd['pp'] = (dd['hit104_pct'] - base).round(1)
    print("\n[DD_mod10別]")
    print(dd.to_string())

    # DD個別（n>=10のみ）でTier的に高いものを抽出
    ddraw = df.groupby('dd').agg(
        n=('hit104', 'count'),
        hit104_pct=('hit104', lambda x: round(x.mean()*100, 1)),
        avg_kaiwari=('kaiwari', lambda x: round(x.mean(), 1)),
    )
    ddraw = ddraw[ddraw['n'] >= 10]
    ddraw['pp'] = (ddraw['hit104_pct'] - base).round(1)
    ddraw = ddraw.sort_values('pp', ascending=False)
    print("\n[DD個別 上位5（n>=10）]")
    print(ddraw.head(5).to_string())
    print("\n[DD個別 下位5（n>=10）]")
    print(ddraw.tail(5).to_string())
