# dashboard/utils/backtest_helpers.py

import pandas as pd
from typing import Dict, Tuple
import streamlit as st

@st.cache_data(ttl=3600)
def compute_training_stats(
    df: pd.DataFrame,
    train_start: str = "20260101",
    train_end: str = "20260331"
) -> Dict:
    """
    訓練期間（1月～3月）のランキング統計を計算

    Args:
        df: machine_detailed_results DataFrame
        train_start: 訓練開始日 (YYYYMMDD)
        train_end: 訓練終了日 (YYYYMMDD)

    Returns:
        {
            'dd_tail': {(dd, tail): {'win_rate': X, 'avg_diff': Y, 'avg_games': Z, 'count': N}},
            'dd_machine': {...},
            'dd_type': {...},
            'weekday_tail': {...},
            'weekday_machine': {...},
            'weekday_type': {...}
        }
    """
    result = {}

    # 空DataFrameの場合は空辞書を返す
    if df.empty or 'date' not in df.columns:
        return result

    df_train = df[(df['date'] >= train_start) & (df['date'] <= train_end)].copy()

    # 訓練期間にデータがない場合は空辞書を返す
    if df_train.empty:
        return result
    
    # 日付カラムから DD（月内日付）を抽出
    df_train['dd'] = df_train['date'].str[4:6].astype(int)
    
    # 曜日は daily_hall_summary から別途取得する必要あり（後のタスクで対応）
    
    patterns = {
        'dd_tail': ['dd', 'last_digit'],
        'dd_machine': ['dd', 'machine_number'],
        'dd_type': ['dd', 'machine_name'],
        'weekday_tail': ['weekday', 'last_digit'],
        'weekday_machine': ['weekday', 'machine_number'],
        'weekday_type': ['weekday', 'machine_name']
    }
    
    for pattern_name, group_cols in patterns.items():
        if pattern_name.startswith('weekday'):
            # weekday は後のタスク Task 2 で統合
            continue
        
        grouped = df_train.groupby(group_cols, as_index=False).agg({
            'diff_coins_normalized': ['mean', 'count'],
            'games_normalized': 'mean'
        }).round(2)
        
        grouped.columns = ['_'.join(col).strip('_') if col[1] else col[0] for col in grouped.columns.values]
        
        # 勝率計算（差枚 > 0 の割合）
        count_win = df_train[df_train['diff_coins_normalized'] > 0].groupby(group_cols).size()
        count_total = df_train.groupby(group_cols).size()
        grouped['win_rate'] = (count_win / count_total * 100).round(2).values
        
        result[pattern_name] = grouped

    return result


def compute_top_percentile_rankings(
    stats_dict: Dict[str, pd.DataFrame]
) -> Dict[str, Dict[str, pd.DataFrame]]:
    """
    訓練統計からTOP20%/10%のランキングを計算

    Args:
        stats_dict: compute_training_stats() の出力

    Returns:
        {
            'dd_tail': {
                'win_rate': {'top20': set(), 'top10': set()},
                'avg_diff': {...},
                'avg_games': {...}
            },
            ...
        }
    """
    result = {}

    for pattern_name, df in stats_dict.items():
        result[pattern_name] = {}

        # 勝率のランキング
        threshold_20_wr = df['win_rate'].quantile(0.8)
        threshold_10_wr = df['win_rate'].quantile(0.9)

        top20_wr = set(zip(df[df['win_rate'] >= threshold_20_wr].iloc[:, 0],
                           df[df['win_rate'] >= threshold_20_wr].iloc[:, 1]))
        top10_wr = set(zip(df[df['win_rate'] >= threshold_10_wr].iloc[:, 0],
                           df[df['win_rate'] >= threshold_10_wr].iloc[:, 1]))

        result[pattern_name]['win_rate'] = {
            'top20': top20_wr,
            'top10': top10_wr,
            'threshold20': threshold_20_wr,
            'threshold10': threshold_10_wr
        }

        # 平均差枚のランキング
        if 'diff_coins_normalized_mean' in df.columns:
            threshold_20_diff = df['diff_coins_normalized_mean'].quantile(0.8)
            threshold_10_diff = df['diff_coins_normalized_mean'].quantile(0.9)

            top20_diff = set(zip(df[df['diff_coins_normalized_mean'] >= threshold_20_diff].iloc[:, 0],
                                 df[df['diff_coins_normalized_mean'] >= threshold_20_diff].iloc[:, 1]))
            top10_diff = set(zip(df[df['diff_coins_normalized_mean'] >= threshold_10_diff].iloc[:, 0],
                                 df[df['diff_coins_normalized_mean'] >= threshold_10_diff].iloc[:, 1]))

            result[pattern_name]['avg_diff'] = {
                'top20': top20_diff,
                'top10': top10_diff,
                'threshold20': threshold_20_diff,
                'threshold10': threshold_10_diff
            }

        # 平均G数のランキング
        if 'games_normalized_mean' in df.columns:
            threshold_20_g = df['games_normalized_mean'].quantile(0.8)
            threshold_10_g = df['games_normalized_mean'].quantile(0.9)

            top20_g = set(zip(df[df['games_normalized_mean'] >= threshold_20_g].iloc[:, 0],
                              df[df['games_normalized_mean'] >= threshold_20_g].iloc[:, 1]))
            top10_g = set(zip(df[df['games_normalized_mean'] >= threshold_10_g].iloc[:, 0],
                              df[df['games_normalized_mean'] >= threshold_10_g].iloc[:, 1]))

            result[pattern_name]['avg_games'] = {
                'top20': top20_g,
                'top10': top10_g,
                'threshold20': threshold_20_g,
                'threshold10': threshold_10_g
            }

    return result
