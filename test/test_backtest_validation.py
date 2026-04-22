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
