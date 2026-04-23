import pandas as pd
import sys
sys.stdout.reconfigure(encoding='utf-8')
from analysis_base import analyze_relative_performance

df_train = pd.DataFrame({
    'dd': list(range(1, 10)) * 10,
    'diff_coins_normalized': list(range(100, 190)),
    'games_normalized': list(range(200, 290)),
})

df_test = pd.DataFrame({
    'dd': list(range(1, 10)) * 5,
    'diff_coins_normalized': list(range(50, 95)),
    'games_normalized': list(range(150, 195)),
})

print('=== analyze_relative_performance() 動作確認 ===')

# coin_diff テスト（全データを使用）
# 訓練データに condition_type カラムを追加
df_train['condition'] = 'test'
df_test['condition'] = 'test'

result = analyze_relative_performance(df_train, df_test, 'condition', 'test', 'dd', metric='coin_diff')
if result:
    print(f'\n差枚ベース:')
    print(f'  Top 平均: {result["top_avg"]:.1f}')
    print(f'  Mid 平均: {result["mid_avg"]:.1f}')
    print(f'  Low 平均: {result["low_avg"]:.1f}')
    print(f'  相関: Rho={result["corr"]:.2f}, p={result["p_value"]:.3f}')
    print(f'  勝者: {result["winner"]}')

# games テスト
result = analyze_relative_performance(df_train, df_test, 'condition', 'test', 'dd', metric='games')
if result:
    print(f'\nG数ベース:')
    print(f'  Top 平均: {result["top_avg"]:.1f}')
    print(f'  Mid 平均: {result["mid_avg"]:.1f}')
    print(f'  Low 平均: {result["low_avg"]:.1f}')
    print(f'  相関: Rho={result["corr"]:.2f}, p={result["p_value"]:.3f}')
    print(f'  勝者: {result["winner"]}')

# win_rate テスト
result = analyze_relative_performance(df_train, df_test, 'condition', 'test', 'dd', metric='win_rate')
if result:
    print(f'\n勝率ベース:')
    print(f'  Top 平均: {result["top_avg"]:.3f}')
    print(f'  Mid 平均: {result["mid_avg"]:.3f}')
    print(f'  Low 平均: {result["low_avg"]:.3f}')
    print(f'  相関: Rho={result["corr"]:.2f}, p={result["p_value"]:.3f}')
    print(f'  勝者: {result["winner"]}')

print('\n✅ 統合関数の動作確認完了')
