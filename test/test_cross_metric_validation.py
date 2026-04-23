import pytest
import pandas as pd
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / 'backtest'))
from cross_metric_validation_triple import analyze_cross_metric_validation_win_rate


class TestAnalyzeCrossMetricValidationWinRate:
    """analyze_cross_metric_validation_win_rate() のテスト"""

    @pytest.fixture
    def sample_data(self):
        """テスト用のサンプルデータを準備"""
        # 訓練期間データ
        train_data = {
            'dd': [1, 1, 1, 1, 2, 2, 2, 2],
            'machine_number': [1, 2, 3, 4, 1, 2, 3, 4],
            'diff_coins_normalized': [10, 20, -5, -10, 15, 5, -20, 0]
        }
        df_train = pd.DataFrame(train_data)

        # テスト期間データ
        test_data = {
            'dd': [1, 1, 1, 1, 2, 2, 2, 2],
            'machine_number': [1, 2, 3, 4, 1, 2, 3, 4],
            'diff_coins_normalized': [8, 18, -3, -8, 12, 3, -18, 2]
        }
        df_test = pd.DataFrame(test_data)

        return df_train, df_test

    def test_analyze_cross_metric_validation_win_rate_basic(self, sample_data):
        """基本動作テスト"""
        df_train, df_test = sample_data

        result = analyze_cross_metric_validation_win_rate(
            df_train, df_test, 'dd', 1, 'machine_number',
            top_percentile=50, mid_percentile=0, low_percentile=50
        )

        assert result is not None
        assert 'top_avg_coin' in result
        assert 'top_avg_wr' in result
        assert 'winner' in result
        assert 'max_relative' in result

    def test_analyze_cross_metric_validation_win_rate_return_dict_keys(self, sample_data):
        """戻り値の辞書キーをチェック"""
        df_train, df_test = sample_data

        result = analyze_cross_metric_validation_win_rate(
            df_train, df_test, 'dd', 1, 'machine_number',
            top_percentile=36, mid_percentile=28, low_percentile=36
        )

        required_keys = [
            'condition_avg_coin', 'condition_avg_wr',
            'top_avg_coin', 'top_avg_wr', 'top_relative', 'top_count',
            'mid_avg_coin', 'mid_avg_wr', 'mid_relative', 'mid_count',
            'low_avg_coin', 'low_avg_wr', 'low_relative', 'low_count',
            'winner', 'max_relative'
        ]

        for key in required_keys:
            assert key in result, f"キー '{key}' が見つかりません"

    def test_analyze_cross_metric_validation_win_rate_empty_condition(self, sample_data):
        """条件にマッチするデータがない場合"""
        df_train, df_test = sample_data

        result = analyze_cross_metric_validation_win_rate(
            df_train, df_test, 'dd', 99, 'machine_number',
            top_percentile=50, mid_percentile=0, low_percentile=50
        )

        assert result is None

    def test_analyze_cross_metric_validation_win_rate_winner_selection(self, sample_data):
        """勝者が正しく選ばれるか"""
        df_train, df_test = sample_data

        result = analyze_cross_metric_validation_win_rate(
            df_train, df_test, 'dd', 1, 'machine_number',
            top_percentile=50, mid_percentile=0, low_percentile=50
        )

        assert result['winner'] in ['上位G', '中間G', '下位G']
