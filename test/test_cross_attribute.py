import pytest
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'backtest'))
from backtest.analysis_base import map_groups_by_attr


def make_train_df():
    return pd.DataFrame({
        'dd': list(range(1, 10)),
        'games_normalized': [100, 200, 300, 400, 500, 600, 700, 800, 900],
        'diff_coins_normalized': [10, 20, 30, 40, 50, 60, 70, 80, 90],
    })


def make_test_df():
    return pd.DataFrame({
        'dd': [1, 5, 9],
        'diff_coins_normalized': [10, 50, 90],
    })


def test_map_groups_assigns_group_labels():
    result = map_groups_by_attr(make_train_df(), make_test_df(), 'games_normalized', 'dd')
    assert result is not None
    assert 'group' in result.columns
    assert set(result['group'].unique()).issubset({'Top', 'Mid', 'Low'})


def test_map_groups_returns_none_when_fewer_than_3_split_units():
    train_df = pd.DataFrame({
        'dd': [1, 2],
        'games_normalized': [100, 200],
    })
    test_df = pd.DataFrame({
        'dd': [1, 2],
        'diff_coins_normalized': [10, 20],
    })
    result = map_groups_by_attr(train_df, test_df, 'games_normalized', 'dd')
    assert result is None


def test_map_groups_low_group_has_lowest_train_attr():
    result = map_groups_by_attr(make_train_df(), make_test_df(), 'games_normalized', 'dd')
    assert result is not None
    # dd=1 は games_normalized=100（最小）→ Low グループ
    low_rows = result[result['group'] == 'Low']
    assert 1 in low_rows['dd'].values
