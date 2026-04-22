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
