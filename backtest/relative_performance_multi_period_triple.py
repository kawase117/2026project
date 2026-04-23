"""相対パフォーマンス分析 - 3グループ版（上位36%・中間28%・下位36%）"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd
from pathlib import Path
from io import StringIO
from loader import load_machine_data
from analysis_base import *


def analyze_relative_performance_triple(df_train: pd.DataFrame, df_test: pd.DataFrame,
                                        condition_type: str, condition_value, attr: str) -> dict:
    """条件別平均との相対パフォーマンスを分析（3グループ版）"""

    train_filtered = df_train[df_train[condition_type] == condition_value]
    test_filtered = df_test[df_test[condition_type] == condition_value]

    if len(train_filtered) == 0 or len(test_filtered) == 0:
        return None

    # テスト期間での条件全体の平均勝率
    condition_avg_wr = (test_filtered['diff_coins_normalized'] > 0).sum() / len(test_filtered) if len(test_filtered) > 0 else 0

    # 訓練期間でこの属性別の勝率を計算
    train_grouped = train_filtered.groupby(attr).agg({
        'diff_coins_normalized': ['count', lambda x: (x > 0).sum()]
    }).reset_index()
    train_grouped.columns = [attr, 'train_count', 'train_wins']
    train_grouped['train_win_rate'] = train_grouped['train_wins'] / train_grouped['train_count']

    if len(train_grouped) < 3:  # 3グループに分割できない場合
        return None

    # 3グループに分割（パーセンタイル固定）
    top_wr, mid_wr, low_wr = split_groups_triple(train_grouped, 'train_win_rate')

    if top_wr is None or mid_wr is None or low_wr is None:
        return None

    # テスト期間での集計
    test_grouped = test_filtered.groupby(attr).agg({
        'diff_coins_normalized': ['count', lambda x: (x > 0).sum()]
    }).reset_index()
    test_grouped.columns = [attr, 'test_count', 'test_wins']
    test_grouped['test_win_rate'] = test_grouped['test_wins'] / test_grouped['test_count']

    # グループ別のテスト期間での平均勝率を計算
    def get_group_test_rates(group_df):
        rates = []
        for _, row in group_df.iterrows():
            test_match = test_grouped[test_grouped[attr] == row[attr]]
            if len(test_match) > 0:
                rates.append(test_match.iloc[0]['test_win_rate'])
        return rates

    top_test_rates = get_group_test_rates(top_wr)
    mid_test_rates = get_group_test_rates(mid_wr)
    low_test_rates = get_group_test_rates(low_wr)

    top_avg_wr = sum(top_test_rates) / len(top_test_rates) if top_test_rates else 0
    mid_avg_wr = sum(mid_test_rates) / len(mid_test_rates) if mid_test_rates else 0
    low_avg_wr = sum(low_test_rates) / len(low_test_rates) if low_test_rates else 0

    top_relative = top_avg_wr - condition_avg_wr
    mid_relative = mid_avg_wr - condition_avg_wr
    low_relative = low_avg_wr - condition_avg_wr

    # 最高値のグループを勝者とする
    max_relative = max(top_relative, mid_relative, low_relative)
    if max_relative == top_relative:
        winner = "上位G"
    elif max_relative == mid_relative:
        winner = "中間G"
    else:
        winner = "下位G"

    return {
        'condition_avg_wr': condition_avg_wr,
        'top_test_rate': top_avg_wr,
        'top_relative': top_relative,
        'top_count': len(top_wr),
        'mid_test_rate': mid_avg_wr,
        'mid_relative': mid_relative,
        'mid_count': len(mid_wr),
        'low_test_rate': low_avg_wr,
        'low_relative': low_relative,
        'low_count': len(low_wr),
        'winner': winner,
        'max_relative': max_relative,
    }


def run_multi_period_triple_analysis(db_path: str):
    """複数訓練期間での相対パフォーマンス分析実施（3グループ版）"""

    print(f"\n相対パフォーマンス分析（3グループ版、複数訓練期間） (DB: {Path(db_path).stem})")
    print("=" * 160)

    df = load_machine_data(db_path)
    df_test = df[(df['date'] >= TEST_START) & (df['date'] <= TEST_END)].copy()

    # 統計情報用の辞書
    dd_winner_count = {}
    for attr in ATTRIBUTES:
        dd_winner_count[attr] = {'top': 0, 'mid': 0, 'low': 0}

    weekday_winner_count = {}
    for attr in ATTRIBUTES:
        weekday_winner_count[attr] = {'top': 0, 'mid': 0, 'low': 0}

    for period_name, start_date, end_date in TRAINING_PERIODS:
        df_train = df[(df['date'] >= start_date) & (df['date'] <= end_date)].copy()

        print_header(db_path, period_name, start_date, end_date)

        # ========== DD別分析 ==========
        print_dd_section_triple(period_name)

        for dd in range(1, 21):
            for attr in ATTRIBUTES:
                result = analyze_relative_performance_triple(df_train, df_test, 'dd', dd, attr)
                if result:
                    r = result
                    # 結果行を出力（3グループ対応）
                    condition_label = f"D{dd:<3}"
                    attr_label = f"{ATTRIBUTES_JA[attr]:<15}"
                    top_sign = "+" if r['top_relative'] >= 0 else ""
                    mid_sign = "+" if r['mid_relative'] >= 0 else ""
                    low_sign = "+" if r['low_relative'] >= 0 else ""

                    print(f"{condition_label:<5} {attr_label} {r['condition_avg_wr']*100:>6.1f}% "
                          f"{r['top_test_rate']*100:>6.1f}% {top_sign}{r['top_relative']*100:>7.1f}% "
                          f"{r['mid_test_rate']*100:>6.1f}% {mid_sign}{r['mid_relative']*100:>7.1f}% "
                          f"{r['low_test_rate']*100:>6.1f}% {low_sign}{r['low_relative']*100:>7.1f}% "
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
                result = analyze_relative_performance_triple(df_train, df_test, 'weekday', weekday, attr)
                if result:
                    r = result
                    attr_label = f"{ATTRIBUTES_JA[attr]:<15}"
                    top_sign = "+" if r['top_relative'] >= 0 else ""
                    mid_sign = "+" if r['mid_relative'] >= 0 else ""
                    low_sign = "+" if r['low_relative'] >= 0 else ""

                    print(f"{jp}曜   {attr_label} {r['condition_avg_wr']*100:>6.1f}% "
                          f"{r['top_test_rate']*100:>6.1f}% {top_sign}{r['top_relative']*100:>7.1f}% "
                          f"{r['mid_test_rate']*100:>6.1f}% {mid_sign}{r['mid_relative']*100:>7.1f}% "
                          f"{r['low_test_rate']*100:>6.1f}% {low_sign}{r['low_relative']*100:>7.1f}% "
                          f"{r['winner']:<12}")

                    # 統計カウント（最後の訓練期間のみ）
                    if period_name == TRAINING_PERIODS[-1][0]:
                        if r['winner'] == "上位G":
                            weekday_winner_count[attr]['top'] += 1
                        elif r['winner'] == "中間G":
                            weekday_winner_count[attr]['mid'] += 1
                        else:
                            weekday_winner_count[attr]['low'] += 1

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

    print("\n曜日別 勝者統計:")
    for attr in ATTRIBUTES:
        top = weekday_winner_count[attr]['top']
        mid = weekday_winner_count[attr]['mid']
        low = weekday_winner_count[attr]['low']
        total = top + mid + low
        if total > 0:
            print(f"  {attr}: 上位G勝利 {top}/7回 ({top/7*100:.1f}%) | "
                  f"中間G勝利 {mid}/7回 ({mid/7*100:.1f}%) | "
                  f"下位G勝利 {low}/7回 ({low/7*100:.1f}%)")

    print("\n" + "=" * 160)
    print("複数訓練期間の相対パフォーマンス分析（3グループ版）完了")
    print("=" * 160)


if __name__ == "__main__":
    # results/フォルダ作成
    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)

    # 出力ファイルパス設定
    output_file = results_dir / "relative_performance_multi_period_triple.txt"

    # 出力をファイルに保存
    old_stdout = sys.stdout
    captured_output = StringIO()
    sys.stdout = captured_output

    try:
        for hall in HALLS:
            db_path = f"../db/{hall}"
            if Path(db_path).exists():
                run_multi_period_triple_analysis(db_path)
    finally:
        sys.stdout = old_stdout
        output_content = captured_output.getvalue()
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(output_content)

        print(output_content)
        print(f"\n出力を保存しました: {output_file.absolute()}")
