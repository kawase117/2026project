"""
蒲田7 押忍！番長4で見られた「月火高/水金低」の曜日パターンが、
他の(特に現役の)機種でも再現されるかを検証する。
"""

import sqlite3
import pandas as pd
import sys
sys.stdout.reconfigure(encoding='utf-8')

WEEKDAY_JP = {0:'月',1:'火',2:'水',3:'木',4:'金',5:'土',6:'日'}
DB = 'db/マルハンメガシティ2000-蒲田7.db'

# 蒲田7で現役・大規模n の機種
MACHINES = [
    '東京喰種',
    '北斗の拳 転生の章2',
    '戦国乙女4 戦乱に閃く炯眼の軍師',
    '東京リベンジャーズ',
    '甲鉄城のカバネリ 海門(うなと)決戦',
    '甲鉄城のカバネリ',
    '新鬼武者3',
    '革命機ヴァルヴレイヴ2',
    '無職転生 ～異世界行ったら本気だす～',
]

conn = sqlite3.connect(DB)
results = []
for m in MACHINES:
    df = pd.read_sql_query(
        'SELECT date, games_normalized, diff_coins_normalized '
        'FROM machine_detailed_results '
        'WHERE machine_name = ? AND games_normalized >= 1000',
        conn, params=(m,)
    )
    if df.empty:
        continue
    dt = pd.to_datetime(df['date'], format='%Y%m%d')
    df['day_of_week'] = dt.dt.weekday.map(WEEKDAY_JP)
    df['kaiwari'] = (
        100 + (df['diff_coins_normalized']
               / df['games_normalized'].clip(lower=1)) / 3 * 100
    )
    df['hit104'] = (df['kaiwari'] >= 104.0).astype(int)
    base = df['hit104'].mean() * 100

    wd = df.groupby('day_of_week').agg(
        n=('hit104', 'count'),
        hit104_pct=('hit104', lambda x: round(x.mean()*100, 1)),
    ).reindex(['月','火','水','木','金','土','日'])
    wd['pp'] = (wd['hit104_pct'] - base).round(1)

    getsuka = wd.loc[['月','火'], 'pp'].mean()
    suikin  = wd.loc[['水','金'], 'pp'].mean()

    print(f"\n=== {m} (n={len(df)}, baseline={base:.1f}%) ===")
    print(wd.to_string())
    print(f"月火平均pp={getsuka:.1f}  水金平均pp={suikin:.1f}  差={getsuka-suikin:.1f}")

    results.append({
        'machine': m, 'n': len(df), 'baseline': round(base,1),
        '月火pp': round(getsuka,1), '水金pp': round(suikin,1),
        '差': round(getsuka-suikin, 1),
    })

conn.close()

print("\n" + "=" * 70)
print("=== サマリ：月火 vs 水金 のpp差 ===")
summary = pd.DataFrame(results).sort_values('差', ascending=False)
print(summary.to_string(index=False))
