"""相対パフォーマンス分析 - 平均差枚ベース（3グループ版）"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd
from pathlib import Path
from io import StringIO
from loader import load_machine_data
from analysis_base import *


def analyze_relative_performance_coin_diff_triple(df_train: pd.DataFrame, df_test: pd.DataFrame,
                                                   condition_type: str, condition_value: str, attr: str) -> dict:
    """平均差枚ベースの相対パフォーマンス分析（3グループ版）"""

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

    if len(train_grouped) < 3:  # 3グループに分割できない場合
        return None

    # 3グループに分割（パーセンタイル固定）
    top_coin, mid_coin, low_coin = split_groups_triple(train_grouped, 'train_avg_coin')

    if top_coin is None or mid_coin is None or low_coin is None:
        return None

    # テスト期間での集計
    test_grouped = test_filtered.groupby(attr).agg({
        'diff_coins_normalized': ['mean']
    }).reset_index()
    test_grouped.columns = [attr, 'test_avg_coin']

    # グループ別のテスト期間での平均差枚を計算
    def get_group_test_coins(group_df):
        coins = []
        for _, row in group_df.iterrows():
            test_match = test_grouped[test_grouped[attr] == row[attr]]
            if len(test_match) > 0:
                coins.append(test_match.iloc[0]['test_avg_coin'])
        return coins

    top_test_coins = get_group_test_coins(top_coin)
    mid_test_coins = get_group_test_coins(mid_coin)
    low_test_coins = get_group_test_coins(low_coin)

    top_avg_coin = sum(top_test_coins) / len(top_test_coins) if top_test_coins else 0
    mid_avg_coin = sum(mid_test_coins) / len(mid_test_coins) if mid_test_coins else 0
    low_avg_coin = sum(low_test_coins) / len(low_test_coins) if low_test_coins else 0

    top_relative = top_avg_coin - condition_avg_coin
    mid_relative = mid_avg_coin - condition_avg_coin
    low_relative = low_avg_coin - condition_avg_coin

    # 最高値のグループを勝者とする
    max_relative = max(top_relative, mid_relative, low_relative)
    if max_relative == top_relative:
        winner = "上位G"
    elif max_relative == mid_relative:
        winner = "中間G"
    else:
        winner = "下位G"

    return {
        'condition_avg': condition_avg_coin,
        'top_avg': top_avg_coin,
        'top_relative': top_relative,
        'top_count': len(top_coin),
        'mid_avg': mid_avg_coin,
        'mid_relative': mid_relative,
        'mid_count': len(mid_coin),
        'low_avg': low_avg_coin,
        'low_relative': low_relative,
        'low_count': len(low_coin),
        'winner': winner,
        'max_relative': max_relative,
    }


def run_multi_period_coin_diff_triple_analysis(db_path: str):
    """複数訓練期間での平均差枚ベース分析実施（3グループ版）"""

    print(f"\n相対パフォーマンス分析（平均差枚ベース、3グループ版、複数訓練期間） (DB: {Path(db_path).stem})")
    print("=" * 160)

    df = load_machine_data(db_path)
    df_test = df[(df['date'] >= TEST_START) & (df['date'] <= TEST_END)].copy()

    # 統計情報用の辞書
    dd_winner_count = {}
    for attr in ATTRIBUTES:
        dd_winner_count[attr] = {'top': 0, 'mid': 0, 'low': 0}

    for period_name, start_date, end_date in TRAINING_PERIODS:
        df_train = df[(df['date'] >= start_date) & (df['date'] <= end_date)].copy()

        print_header(db_path, period_name, start_date, end_date)

        # ========== DD別分析 ==========
        print_dd_section_triple(period_name)

        for dd in range(1, 21):
            for attr in ATTRIBUTES:
                result = analyze_relative_performance_coin_diff_triple(df_train, df_test, 'dd', dd, attr)
                if result:
                    r = result
                    # 結果行を出力（3グループ対応）
                    condition_label = f"D{dd:<3}"
                    attr_label = f"{ATTRIBUTES_JA[attr]:<15}"
                    top_sign = "+" if r['top_relative'] >= 0 else ""
                    mid_sign = "+" if r['mid_relative'] >= 0 else ""
                    low_sign = "+" if r['low_relative'] >= 0 else ""

                    print(f"{condition_label:<5} {attr_label} {r['condition_avg']:>6.1f}% "
                          f"{r['top_avg']:>6.1f}% {top_sign}{r['top_relative']:>7.1f}% "
                          f"{r['mid_avg']:>6.1f}% {mid_sign}{r['mid_relative']:>7.1f}% "
                          f"{r['low_avg']:>6.1f}% {low_sign}{r['low_relative']:>7.1f}% "
                          f"{r['winner']:<12}")

                    # 統計カウント（最後の訓練期間のみ）
                    if period_name == TRAINING_PERIODS[-1][0]:
                        if r['winner'] == "上位G":
                            dd_winner_count[attr]['top'] += 1
                        elif r['winner'] == "中間G":
                            dd_winner_count[attr]['mid'] += 1
                        else:
                            dd_winner_count[attr]['low'] += 1

        # ========== 曜日別分析 ==========
        print_weekday_section_triple(period_name)

        for weekday, jp in zip(WEEKDAYS, WEEKDAY_JP):
            for attr in ATTRIBUTES:
                result = analyze_relative_performance_coin_diff_triple(df_train, df_test, 'weekday', weekday, attr)
                if result:
                    r = result
                    attr_label = f"{ATTRIBUTES_JA[attr]:<15}"
                    top_sign = "+" if r['top_relative'] >= 0 else ""
                    mid_sign = "+" if r['mid_relative'] >= 0 else ""
                    low_sign = "+" if r['low_relative'] >= 0 else ""

                    print(f"{jp}曜   {attr_label} {r['condition_avg']:>6.1f}% "
                          f"{r['top_avg']:>6.1f}% {top_sign}{r['top_relative']:>7.1f}% "
                          f"{r['mid_avg']:>6.1f}% {mid_sign}{r['mid_relative']:>7.1f}% "
                          f"{r['low_avg']:>6.1f}% {low_sign}{r['low_relative']:>7.1f}% "
                          f"{r['winner']:<12}")

    # 最終統計
    print("\n" + "=" * 160)
    print("DD別 勝者統計:")
    for attr in ATTRIBUTES:
        top = dd_winner_count[attr]['top']
        mid = dd_winner_count[attr]['mid']
        low = dd_winner_count[attr]['low']
        total = top + mid + low
        if total > 0:
            print(f"  {attr}: 上位G勝利 {top}/20回 ({top/20*100:.1f}%) | "
                  f"中間G勝利 {mid}/20回 ({mid/20*100:.1f}%) | "
                  f"下位G勝利 {low}/20回 ({low/20*100:.1f}%)")

    print("\n" + "=" * 160)
    print("平均差枚ベース分析（3グループ版）完了")
    print("=" * 160)


if __name__ == "__main__":
    # results/フォルダ作成
    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)

    # 出力ファイルパス設定
    output_file = results_dir / "relative_performance_analysis_coin_diff_triple.txt"

    # 出力をファイルに保存
    old_stdout = sys.stdout
    captured_output = StringIO()
    sys.stdout = captured_output

    try:
        for hall in HALLS:
            db_path = f"../db/{hall}"
            if Path(db_path).exists():
                run_multi_period_coin_diff_triple_analysis(db_path)
    finally:
        sys.stdout = old_stdout
        output_content = captured_output.getvalue()
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(output_content)

        print(output_content)
        print(f"\n出力を保存しました: {output_file.absolute()}")
