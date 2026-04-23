"""クロスメトリック検証 - 勝率・G数グループ分割からテスト差枚を検証"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd
from pathlib import Path
from io import StringIO
from loader import load_machine_data
from analysis_base import *


# ========== クロスメトリック検証関数（勝率→差枚） ==========

def analyze_cross_metric_validation_win_rate(df_train: pd.DataFrame, df_test: pd.DataFrame,
                                             condition_type: str, condition_value: str, attr: str,
                                             top_percentile: float, mid_percentile: float, low_percentile: float) -> dict:
    """訓練勝率グループ分割 → テスト差枚+勝率を検証（カスタム比率対応）"""

    train_filtered = df_train[df_train[condition_type] == condition_value]
    test_filtered = df_test[df_test[condition_type] == condition_value]

    if len(train_filtered) == 0 or len(test_filtered) == 0:
        return None

    # テスト期間での条件全体の平均差枚と勝率
    condition_avg_coin = test_filtered['diff_coins_normalized'].mean() if len(test_filtered) > 0 else 0
    condition_avg_wr = (test_filtered['diff_coins_normalized'] > 0).sum() / len(test_filtered) if len(test_filtered) > 0 else 0

    # 訓練期間で属性別の勝率を計算
    train_grouped = train_filtered.groupby(attr).agg({
        'diff_coins_normalized': ['count', lambda x: (x > 0).sum()]
    }).reset_index()
    train_grouped.columns = [attr, 'train_count', 'train_wins']
    train_grouped['train_win_rate'] = train_grouped['train_wins'] / train_grouped['train_count']

    if len(train_grouped) < 3:  # 3グループに分割できない場合
        return None

    # カスタム比率でグループ分割
    top_wr, mid_wr, low_wr = split_groups_triple_custom(train_grouped, 'train_win_rate',
                                                         top_percentile, mid_percentile, low_percentile)

    if top_wr is None or mid_wr is None or low_wr is None:
        return None

    # テスト期間での集計
    test_grouped = test_filtered.groupby(attr).agg({
        'diff_coins_normalized': ['mean', 'count', lambda x: (x > 0).sum()]
    }).reset_index()
    test_grouped.columns = [attr, 'test_avg_coin', 'test_count', 'test_wins']
    test_grouped['test_win_rate'] = test_grouped['test_wins'] / test_grouped['test_count']

    # グループ別のテスト期間での平均差枚と勝率を計算
    def get_group_test_metrics(group_df):
        coins = []
        rates = []
        for _, row in group_df.iterrows():
            test_match = test_grouped[test_grouped[attr] == row[attr]]
            if len(test_match) > 0:
                coins.append(test_match.iloc[0]['test_avg_coin'])
                rates.append(test_match.iloc[0]['test_win_rate'])
        return coins, rates

    top_test_coins, top_test_rates = get_group_test_metrics(top_wr)
    mid_test_coins, mid_test_rates = get_group_test_metrics(mid_wr)
    low_test_coins, low_test_rates = get_group_test_metrics(low_wr)

    top_avg_coin = sum(top_test_coins) / len(top_test_coins) if top_test_coins else 0
    mid_avg_coin = sum(mid_test_coins) / len(mid_test_coins) if mid_test_coins else 0
    low_avg_coin = sum(low_test_coins) / len(low_test_coins) if low_test_coins else 0

    top_avg_wr = sum(top_test_rates) / len(top_test_rates) if top_test_rates else 0
    mid_avg_wr = sum(mid_test_rates) / len(mid_test_rates) if mid_test_rates else 0
    low_avg_wr = sum(low_test_rates) / len(low_test_rates) if low_test_rates else 0

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
        'condition_avg_coin': condition_avg_coin,
        'condition_avg_wr': condition_avg_wr,
        'top_avg_coin': top_avg_coin,
        'top_avg_wr': top_avg_wr,
        'top_relative': top_relative,
        'top_count': len(top_wr),
        'mid_avg_coin': mid_avg_coin,
        'mid_avg_wr': mid_avg_wr,
        'mid_relative': mid_relative,
        'mid_count': len(mid_wr),
        'low_avg_coin': low_avg_coin,
        'low_avg_wr': low_avg_wr,
        'low_relative': low_relative,
        'low_count': len(low_wr),
        'winner': winner,
        'max_relative': max_relative,
    }


# ========== クロスメトリック検証関数（G数→差枚） ==========

def analyze_cross_metric_validation_games(df_train: pd.DataFrame, df_test: pd.DataFrame,
                                          condition_type: str, condition_value: str, attr: str,
                                          top_percentile: float, mid_percentile: float, low_percentile: float) -> dict:
    """訓練G数グループ分割 → テスト差枚+勝率を検証（カスタム比率対応）"""

    train_filtered = df_train[df_train[condition_type] == condition_value]
    test_filtered = df_test[df_test[condition_type] == condition_value]

    if len(train_filtered) == 0 or len(test_filtered) == 0:
        return None

    # テスト期間での条件全体の平均差枚と勝率
    condition_avg_coin = test_filtered['diff_coins_normalized'].mean() if len(test_filtered) > 0 else 0
    condition_avg_wr = (test_filtered['diff_coins_normalized'] > 0).sum() / len(test_filtered) if len(test_filtered) > 0 else 0

    # 訓練期間で属性別のG数を計算
    train_grouped = train_filtered.groupby(attr).agg({
        'games_normalized': ['mean']
    }).reset_index()
    train_grouped.columns = [attr, 'train_avg_games']

    if len(train_grouped) < 3:  # 3グループに分割できない場合
        return None

    # カスタム比率でグループ分割
    top_games, mid_games, low_games = split_groups_triple_custom(train_grouped, 'train_avg_games',
                                                                  top_percentile, mid_percentile, low_percentile)

    if top_games is None or mid_games is None or low_games is None:
        return None

    # テスト期間での集計
    test_grouped = test_filtered.groupby(attr).agg({
        'diff_coins_normalized': ['mean', lambda x: (x > 0).sum()],
        'games_normalized': ['count']
    }).reset_index()
    test_grouped.columns = [attr, 'test_avg_coin', 'test_wins', 'test_count']
    test_grouped['test_win_rate'] = test_grouped['test_wins'] / test_grouped['test_count']

    # グループ別のテスト期間での平均差枚と勝率を計算
    def get_group_test_metrics(group_df):
        coins = []
        rates = []
        for _, row in group_df.iterrows():
            test_match = test_grouped[test_grouped[attr] == row[attr]]
            if len(test_match) > 0:
                coins.append(test_match.iloc[0]['test_avg_coin'])
                rates.append(test_match.iloc[0]['test_win_rate'])
        return coins, rates

    top_test_coins, top_test_rates = get_group_test_metrics(top_games)
    mid_test_coins, mid_test_rates = get_group_test_metrics(mid_games)
    low_test_coins, low_test_rates = get_group_test_metrics(low_games)

    top_avg_coin = sum(top_test_coins) / len(top_test_coins) if top_test_coins else 0
    mid_avg_coin = sum(mid_test_coins) / len(mid_test_coins) if mid_test_coins else 0
    low_avg_coin = sum(low_test_coins) / len(low_test_coins) if low_test_coins else 0

    top_avg_wr = sum(top_test_rates) / len(top_test_rates) if top_test_rates else 0
    mid_avg_wr = sum(mid_test_rates) / len(mid_test_rates) if mid_test_rates else 0
    low_avg_wr = sum(low_test_rates) / len(low_test_rates) if low_test_rates else 0

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
        'condition_avg_coin': condition_avg_coin,
        'condition_avg_wr': condition_avg_wr,
        'top_avg_coin': top_avg_coin,
        'top_avg_wr': top_avg_wr,
        'top_relative': top_relative,
        'top_count': len(top_games),
        'mid_avg_coin': mid_avg_coin,
        'mid_avg_wr': mid_avg_wr,
        'mid_relative': mid_relative,
        'mid_count': len(mid_games),
        'low_avg_coin': low_avg_coin,
        'low_avg_wr': low_avg_wr,
        'low_relative': low_relative,
        'low_count': len(low_games),
        'winner': winner,
        'max_relative': max_relative,
    }


# ========== パーセンタイル比率自動最適化エンジン ==========

def find_optimal_percentile_ratio(db_path: str, metric_type: str, condition_type: str) -> dict:
    """複数パーセンタイル比率を試行（全DD対応） → 最適比率を推奨"""
    df = load_machine_data(db_path)
    df_test = df[(df['date'] >= TEST_START) & (df['date'] <= TEST_END)].copy()

    results = []

    # 各パーセンタイル比率を試行
    for top_pct, mid_pct, low_pct in PERCENTILE_CANDIDATES:
        # 複数訓練期間での結果を集計
        period_results = []
        winners_by_period = []

        for period_name, start_date, end_date in TRAINING_PERIODS:
            df_train = df[(df['date'] >= start_date) & (df['date'] <= end_date)].copy()

            # 全DD（1-20）での分析結果を集計
            dd_relative_values = []
            dd_winners = []

            for dd in range(1, 21):
                result = None
                if metric_type == 'win_rate':
                    result = analyze_cross_metric_validation_win_rate(
                        df_train, df_test, 'dd', dd, 'machine_number',
                        top_pct, mid_pct, low_pct
                    )
                else:  # games
                    result = analyze_cross_metric_validation_games(
                        df_train, df_test, 'dd', dd, 'machine_number',
                        top_pct, mid_pct, low_pct
                    )

                if result:
                    dd_relative_values.append(result['max_relative'])
                    dd_winners.append(result['winner'])

            # DD結果が存在する場合、その訓練期間の代表値を計算
            if dd_relative_values:
                period_relative = sum(dd_relative_values) / len(dd_relative_values)
                period_results.append(period_relative)

                # 勝者判定：複数DDの勝者の多数決で決定
                if dd_winners:
                    winner_counts = {}
                    for w in dd_winners:
                        winner_counts[w] = winner_counts.get(w, 0) + 1
                    period_winner = max(winner_counts, key=winner_counts.get)
                    winners_by_period.append(period_winner)

        # 3訓練期間での統計
        if len(period_results) == 3:
            is_consistent, symbol = calculate_consistency_score(winners_by_period)
            relative_mean = sum(period_results) / 3
            relative_std = (sum((x - relative_mean) ** 2 for x in period_results) / 3) ** 0.5

            results.append({
                'ratio': (top_pct, mid_pct, low_pct),
                'winners_by_period': winners_by_period,
                'is_consistent': is_consistent,
                'consistency_symbol': symbol,
                'relative_mean': relative_mean,
                'relative_std': relative_std,
                'is_recommended': False  # 後で判定
            })

    # 推奨比率を決定
    consistent_results = [r for r in results if r['is_consistent']]
    if consistent_results:
        recommended = max(consistent_results, key=lambda x: x['relative_mean'])
        recommended['is_recommended'] = True

    return {
        'optimal_ratio': recommended['ratio'] if consistent_results else PERCENTILE_CANDIDATES[3],  # デフォルト
        'results': results
    }


# ========== 出力関数 ==========

def print_percentile_optimization_header(metric_type: str, condition_type: str):
    """パーセンタイル比率最適化結果のヘッダー出力"""
    metric_name = '勝率→差枚' if metric_type == 'win_rate' else 'G数→差枚'
    condition_name = 'DD別' if condition_type == 'dd' else '曜日別'

    print(f"\n{'=' * 100}")
    print(f"パーセンタイル比率の自動最適化結果")
    print(f"（クロスメトリック検証：{metric_name}、{condition_name}分析、機械番号属性）")
    print(f"{'=' * 100}")
    print(f"{'比率':<15} {'勝者(6月)':<12} {'勝者(3月)':<12} {'勝者(1月)':<12} {'一貫性':<8} {'相対値μ':<10} {'相対値σ':<10} {'推奨':<10}")
    print(f"{'-' * 100}")


def print_percentile_result_row(result: dict):
    """パーセンタイル比率結果行の出力"""
    ratio_str = f"{result['ratio'][0]}-{result['ratio'][1]}-{result['ratio'][2]}"
    recommended = "← オススメ" if result['is_recommended'] else ""

    print(f"{ratio_str:<15} {result['winners_by_period'][0]:<12} {result['winners_by_period'][1]:<12} "
          f"{result['winners_by_period'][2]:<12} {result['consistency_symbol']:<8} "
          f"{result['relative_mean']:>8.1f}% {result['relative_std']:>8.1f}% {recommended:<10}")


def run_multi_period_cross_metric_validation(db_path: str):
    """複数訓練期間でのクロスメトリック検証メイン実行"""

    print(f"\n相対パフォーマンス分析（クロスメトリック検証、複数訓練期間） (DB: {Path(db_path).stem})")

    # 勝率グループ分割の比率最適化
    print("\n【 訓練勝率グループ分割 → テスト差枚+勝率 】")
    win_rate_optimization = find_optimal_percentile_ratio(db_path, 'win_rate', 'dd')

    print_percentile_optimization_header('win_rate', 'dd')
    for result in win_rate_optimization['results']:
        print_percentile_result_row(result)

    # G数グループ分割の比率最適化
    print("\n【 訓練G数グループ分割 → テスト差枚+勝率 】")
    games_optimization = find_optimal_percentile_ratio(db_path, 'games', 'dd')

    print_percentile_optimization_header('games', 'dd')
    for result in games_optimization['results']:
        print_percentile_result_row(result)

    print(f"\n{'=' * 100}")
    print("クロスメトリック検証完了")
    print(f"{'=' * 100}")


if __name__ == "__main__":
    # results/フォルダ作成
    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)

    # 出力ファイルパス設定
    output_file = results_dir / "cross_metric_validation_triple.txt"

    # 出力をファイルに保存
    old_stdout = sys.stdout
    captured_output = StringIO()
    sys.stdout = captured_output

    try:
        for hall in HALLS:
            db_path = f"../db/{hall}"
            if Path(db_path).exists():
                run_multi_period_cross_metric_validation(db_path)
    finally:
        sys.stdout = old_stdout
        output_content = captured_output.getvalue()
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(output_content)

        print(output_content)
        print(f"\n出力を保存しました: {output_file.absolute()}")
