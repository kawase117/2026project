"""相対パフォーマンス分析 - 平均差枚ベース（勝率の代わりに平均差枚を指標）"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd
from pathlib import Path
from loader import load_machine_data
from analysis_base import *


def analyze_relative_performance_coin_diff(df_train: pd.DataFrame, df_test: pd.DataFrame, condition_type: str, condition_value: str, attr: str) -> dict:
    """平均差枚ベースの相対パフォーマンス分析"""

    train_filtered = df_train[df_train[condition_type] == condition_value]
    test_filtered = df_test[df_test[condition_type] == condition_value]

    if len(train_filtered) == 0 or len(test_filtered) == 0:
        return None

    # テスト期間での条件全体の平均差枚
    condition_avg_coin = test_filtered['diff_coins_normalized'].mean() if len(test_filtered) > 0 else 0

    # 訓練期間でこの属性別の平均差枚を計算
    train_grouped = train_filtered.groupby(attr).agg({
        'diff_coins_normalized': ['mean']
    }).reset_index()
    train_grouped.columns = [attr, 'train_avg_coin']

    if len(train_grouped) == 0:
        return None

    # 中央値で分割
    median_coin = train_grouped['train_avg_coin'].median()
    high_coin = train_grouped[train_grouped['train_avg_coin'] >= median_coin]
    low_coin = train_grouped[train_grouped['train_avg_coin'] < median_coin]

    # テスト期間での集計
    test_grouped = test_filtered.groupby(attr).agg({
        'diff_coins_normalized': ['mean']
    }).reset_index()
    test_grouped.columns = [attr, 'test_avg_coin']

    # 高差枚グループのテスト期間での平均
    high_test_coins = []
    for _, row in high_coin.iterrows():
        test_match = test_grouped[test_grouped[attr] == row[attr]]
        if len(test_match) > 0:
            high_test_coins.append(test_match.iloc[0]['test_avg_coin'])

    # 低差枚グループのテスト期間での平均
    low_test_coins = []
    for _, row in low_coin.iterrows():
        test_match = test_grouped[test_grouped[attr] == row[attr]]
        if len(test_match) > 0:
            low_test_coins.append(test_match.iloc[0]['test_avg_coin'])

    high_avg_coin = sum(high_test_coins) / len(high_test_coins) if high_test_coins else 0
    low_avg_coin = sum(low_test_coins) / len(low_test_coins) if low_test_coins else 0

    high_relative = high_avg_coin - condition_avg_coin
    low_relative = low_avg_coin - condition_avg_coin

    return {
        'condition_avg': condition_avg_coin,
        'high_avg': high_avg_coin,
        'high_relative': high_relative,
        'high_count': len(high_coin),
        'low_avg': low_avg_coin,
        'low_relative': low_relative,
        'low_count': len(low_coin),
        'winner': "高差枚G" if high_relative >= low_relative else "低差枚G",
    }


def run_multi_period_coin_diff_analysis(db_path: str):
    """複数訓練期間での平均差枚ベース分析"""

    print(f"\n相対パフォーマンス分析（平均差枚ベース、複数訓練期間） (DB: {Path(db_path).stem})")
    print("=" * 140)

    df = load_machine_data(db_path)
    df_test = df[(df['date'] >= TEST_START) & (df['date'] <= TEST_END)].copy()

    for period_name, start_date, end_date in TRAINING_PERIODS:
        df_train = df[(df['date'] >= start_date) & (df['date'] <= end_date)].copy()

        print_header(db_path, period_name, start_date, end_date)

        # ========== DD別分析 ==========
        print_dd_section(period_name)

        for dd in range(1, 21):
            for attr in ATTRIBUTES:
                result = analyze_relative_performance_coin_diff(df_train, df_test, 'dd', dd, attr)
                if result:
                    print_result_row(f"D{dd:<3}", f"{ATTRIBUTES_JA[attr]:<15}", result)

        # ========== 曜日別分析 ==========
        print_weekday_section(period_name)

        for weekday, jp in zip(WEEKDAYS, WEEKDAY_JP):
            for attr in ATTRIBUTES:
                result = analyze_relative_performance_coin_diff(df_train, df_test, 'weekday', weekday, attr)
                if result:
                    print_result_row(f"{jp}曜   ", f"{ATTRIBUTES_JA[attr]:<15}", result)

    print("\n" + "=" * 140)
    print("平均差枚ベース分析完了")
    print("=" * 140)


if __name__ == "__main__":
    # results/フォルダ作成
    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)

    # 出力ファイルパス設定
    output_file = results_dir / "relative_performance_analysis_coin_diff.txt"

    # 出力をファイルに保存
    import sys
    from io import StringIO

    # 既存stdout保存
    old_stdout = sys.stdout

    # StringIOで出力をキャプチャ
    captured_output = StringIO()
    sys.stdout = captured_output

    try:
        for hall in HALLS:
            db_path = f"../db/{hall}"
            if Path(db_path).exists():
                run_multi_period_coin_diff_analysis(db_path)
    finally:
        # stdout復元
        sys.stdout = old_stdout

        # ファイル保存
        output_content = captured_output.getvalue()
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(output_content)

        # コンソールにも出力
        print(output_content)
        print(f"\n出力を保存しました: {output_file.absolute()}")
