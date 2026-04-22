"""データ診断スクリプト"""

from loader import load_machine_data
from extractor import extract_winning_patterns
from pathlib import Path

db_path = "db/マルハンメガシティ2000-蒲田1.db"

df = load_machine_data(db_path)
df_train = df[(df['date'] >= '2026-01-01') & (df['date'] <= '2026-03-31')]

print("=" * 60)
print("DD別勝率分布")
print("=" * 60)

dd_stats = df_train.groupby('dd').agg({
    'diff_coins_normalized': ['count', lambda x: (x > 0).sum(), lambda x: (x > 0).sum() / len(x) * 100]
}).round(2)
dd_stats.columns = ['total_count', 'win_count', 'win_rate']
dd_stats = dd_stats.sort_values('win_rate', ascending=False)
print(dd_stats)

print("\n" + "=" * 60)
print("曜日別勝率分布")
print("=" * 60)

weekday_stats = df_train.groupby('weekday').agg({
    'diff_coins_normalized': ['count', lambda x: (x > 0).sum(), lambda x: (x > 0).sum() / len(x) * 100]
}).round(2)
weekday_stats.columns = ['total_count', 'win_count', 'win_rate']
weekday_stats = weekday_stats.sort_values('win_rate', ascending=False)
print(weekday_stats)

# 複数のしきい値で試す
print("\n" + "=" * 60)
print("異なるしきい値での検出パターン数")
print("=" * 60)

for threshold in [0.50, 0.55, 0.60, 0.65, 0.70]:
    patterns_dd = extract_winning_patterns(df_train, 'dd', threshold)
    patterns_weekday = extract_winning_patterns(df_train, 'weekday', threshold)
    print(f"Threshold {threshold*100:.0f}%: DD={len(patterns_dd)}, Weekday={len(patterns_weekday)}")
    if len(patterns_dd) > 0:
        print(f"  Top DD: {patterns_dd['pattern'].values[:3]} (win_rate: {patterns_dd['win_rate'].values[:3]})")
    if len(patterns_weekday) > 0:
        print(f"  Top Weekday: {patterns_weekday['pattern'].values[:3]} (win_rate: {patterns_weekday['win_rate'].values[:3]})")
