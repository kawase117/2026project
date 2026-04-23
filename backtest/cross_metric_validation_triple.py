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
