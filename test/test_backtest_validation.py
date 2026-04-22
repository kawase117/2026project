# test/test_backtest_validation.py

import pytest
import pandas as pd
from dashboard.utils.backtest_helpers import compute_training_stats

def test_compute_training_stats_basic():
    """訓練統計が正しく計算されることを確認"""
    df = pd.DataFrame({
        'date': ['20260115', '20260115', '20260220', '20260220'] * 3,
        'machine_number': [1, 2, 1, 2] * 3,
        'machine_name': ['AA', 'BB', 'AA', 'BB'] * 3,
        'last_digit': ['0', '1', '0', '1'] * 3,
        'diff_coins_normalized': [100, -50, 200, 0] * 3,
        'games_normalized': [50, 60, 70, 80] * 3
    })
    
    result = compute_training_stats(df)
    
    assert 'dd_tail' in result
    assert 'dd_machine' in result
    assert len(result['dd_tail']) > 0
    assert 'win_rate' in result['dd_tail'].columns

def test_compute_training_stats_empty():
    """空DataFrameで例外を出さない"""
    df = pd.DataFrame({
        'date': [],
        'machine_number': [],
        'machine_name': [],
        'last_digit': [],
        'diff_coins_normalized': [],
        'games_normalized': []
    })

    result = compute_training_stats(df)
    assert isinstance(result, dict)


from dashboard.utils.backtest_helpers import compute_top_percentile_rankings

def test_compute_top_percentile_rankings():
    """TOP20%/10%計算が正しく行われることを確認"""
    df = pd.DataFrame({
        'dd': [1, 1, 1, 2, 2, 2],
        'last_digit': ['0', '1', '0', '1', '0', '1'],
        'win_rate': [80.0, 60.0, 40.0, 70.0, 50.0, 30.0],
        'diff_coins_normalized_mean': [100, 50, 0, 80, 30, -20],
        'games_normalized_mean': [500, 400, 300, 450, 350, 250]
    })

    stats = {'test_pattern': df}
    result = compute_top_percentile_rankings(stats)

    assert 'test_pattern' in result
    assert 'win_rate' in result['test_pattern']
    assert 'top20' in result['test_pattern']['win_rate']
    assert 'top10' in result['test_pattern']['win_rate']
    assert len(result['test_pattern']['win_rate']['top20']) >= len(result['test_pattern']['win_rate']['top10'])


from dashboard.utils.backtest_helpers import compute_validation_metrics

def test_compute_validation_metrics():
    """検証指標が正しく計算されることを確認"""
    df_test = pd.DataFrame({
        'date': ['20260401', '20260401', '20260402', '20260402'] * 2,
        'machine_number': [1, 2, 1, 2] * 2,
        'machine_name': ['AA', 'BB', 'AA', 'BB'] * 2,
        'last_digit': ['0', '1', '0', '1'] * 2,
        'diff_coins_normalized': [100, -50, 200, 50] * 2,
        'games_normalized': [50, 60, 70, 80] * 2
    })

    rankings = {
        'dd_tail': {
            'win_rate': {
                'top20': {(4, '0')},
                'top10': {(4, '0')},
                'threshold20': 50.0,
                'threshold10': 75.0
            }
        }
    }

    result = compute_validation_metrics(
        df_test, rankings, 'dd_tail', ['dd', 'last_digit']
    )

    assert isinstance(result, pd.DataFrame)
    assert 'd_20260401' in result.columns or 'd_20260402' in result.columns


def test_compute_training_stats_weekday():
    """曜日別パターンの集計が正しく行われることを確認"""
    df = pd.DataFrame({
        'date': ['20260103', '20260110', '20260117', '20260124'] * 3,  # 複数の金曜日
        'machine_number': [1, 2, 1, 2] * 3,
        'machine_name': ['AA', 'BB', 'AA', 'BB'] * 3,
        'last_digit': ['0', '1', '0', '1'] * 3,
        'diff_coins_normalized': [100, -50, 200, 0] * 3,
        'games_normalized': [50, 60, 70, 80] * 3
    })

    result = compute_training_stats(df)

    assert 'weekday_tail' in result
    assert 'weekday_machine' in result
    assert 'weekday_type' in result
    assert len(result['weekday_tail']) > 0
