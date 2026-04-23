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


from backtest.analysis_base import aggregate_group_metrics


def test_aggregate_group_metrics_columns():
    df = pd.DataFrame({
        'group': ['Top', 'Top', 'Mid', 'Mid', 'Low', 'Low'],
        'diff_coins_normalized': [100, 200, 10, 20, -100, -200],
    })
    result = aggregate_group_metrics(df)
    assert list(result.columns) == ['group', 'count', 'avg_coin', 'win_rate']
    assert len(result) == 3


def test_aggregate_group_metrics_win_rate():
    df = pd.DataFrame({
        'group': ['Top', 'Top', 'Top', 'Top'],
        'diff_coins_normalized': [100, 200, -50, 300],
    })
    result = aggregate_group_metrics(df)
    top_row = result[result['group'] == 'Top'].iloc[0]
    assert top_row['win_rate'] == pytest.approx(0.75)   # 3/4
    assert top_row['avg_coin'] == pytest.approx(137.5)  # (100+200-50+300)/4


def test_aggregate_group_metrics_order():
    df = pd.DataFrame({
        'group': ['Low', 'Mid', 'Top'],
        'diff_coins_normalized': [-100, 10, 200],
    })
    result = aggregate_group_metrics(df)
    assert list(result['group']) == ['Top', 'Mid', 'Low']


from backtest.analysis_base import calculate_rank_correlation


def test_calculate_rank_correlation_perfect_positive():
    corr, p = calculate_rank_correlation([1.0, 2.0, 3.0], [10.0, 20.0, 30.0])
    assert corr == pytest.approx(1.0)


def test_calculate_rank_correlation_perfect_negative():
    corr, p = calculate_rank_correlation([1.0, 2.0, 3.0], [30.0, 20.0, 10.0])
    assert corr == pytest.approx(-1.0)


def test_calculate_rank_correlation_returns_tuple():
    corr, p = calculate_rank_correlation([3.0, 2.0, 1.0], [30.0, 20.0, 10.0])
    assert isinstance(corr, float)
    assert isinstance(p, float)
    assert 0.0 <= p <= 1.0


from backtest.cross_attribute_performance_analysis import analyze_cross_attribute


def make_full_df():
    """9 台 × 2 期間のダミーデータ"""
    rows = []
    for date_str, period in [('2025-01-10', 'train'), ('2026-04-10', 'test')]:
        for dd in range(1, 10):
            rows.append({
                'date': pd.Timestamp(date_str),
                'dd': dd,
                'weekday': 'Monday',
                'last_digit': str(dd % 10),
                'games_normalized': dd * 100,
                'diff_coins_normalized': dd * 50 - 250,  # dd=5 がゼロ
            })
    return pd.DataFrame(rows)


def test_analyze_cross_attribute_returns_dict():
    df = make_full_df()
    df_train = df[df['date'] == pd.Timestamp('2025-01-10')]
    df_test = df[df['date'] == pd.Timestamp('2026-04-10')]
    result = analyze_cross_attribute(df_train, df_test, 'games_normalized', 'dd')
    assert result is not None
    assert 'metrics' in result
    assert 'corr' in result
    assert 'p_value' in result


def test_analyze_cross_attribute_metrics_structure():
    df = make_full_df()
    df_train = df[df['date'] == pd.Timestamp('2025-01-10')]
    df_test = df[df['date'] == pd.Timestamp('2026-04-10')]
    result = analyze_cross_attribute(df_train, df_test, 'games_normalized', 'dd')
    metrics = result['metrics']
    assert list(metrics.columns) == ['group', 'count', 'avg_coin', 'win_rate']
    assert len(metrics) == 3


from backtest.analysis_base import get_group_test_values_vectorized


def test_get_group_test_values_vectorized_basic():
    """基本的な merge() テスト"""
    group_df = pd.DataFrame({
        'dd': [1, 2, 3],
    })
    test_grouped = pd.DataFrame({
        'dd': [1, 2, 3, 4, 5],
        'value': [10.0, 20.0, 30.0, 40.0, 50.0],
    })
    result = get_group_test_values_vectorized(group_df, test_grouped, 'dd', 'value')
    assert result == [10.0, 20.0, 30.0]


def test_get_group_test_values_vectorized_partial_match():
    """部分マッチのテスト"""
    group_df = pd.DataFrame({
        'dd': [1, 5],  # 5 は test_grouped に存在しない
    })
    test_grouped = pd.DataFrame({
        'dd': [1, 2, 3],
        'value': [100.0, 200.0, 300.0],
    })
    result = get_group_test_values_vectorized(group_df, test_grouped, 'dd', 'value')
    assert result == [100.0]  # マッチしたもののみ


def test_get_group_test_values_vectorized_order():
    """順序の保持"""
    group_df = pd.DataFrame({
        'dd': [3, 1, 2],
    })
    test_grouped = pd.DataFrame({
        'dd': [1, 2, 3],
        'value': [10.0, 20.0, 30.0],
    })
    result = get_group_test_values_vectorized(group_df, test_grouped, 'dd', 'value')
    # merge() は左側の順序を保持する
    assert result == [30.0, 10.0, 20.0]
