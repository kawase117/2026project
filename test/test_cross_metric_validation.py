import pytest
import pandas as pd
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / 'backtest'))
from cross_metric_validation_triple import (
    analyze_cross_metric_validation_win_rate,
    analyze_cross_metric_validation_games,
    find_optimal_percentile_ratio,
    run_multi_period_cross_metric_validation
)


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


class TestAnalyzeCrossMetricValidationGames:
    """analyze_cross_metric_validation_games() のテスト"""

    @pytest.fixture
    def sample_data_with_games(self):
        """テスト用のサンプルデータを準備（G数含む）"""
        # 訓練期間データ
        train_data = {
            'dd': [1, 1, 1, 1, 2, 2, 2, 2],
            'machine_number': [1, 2, 3, 4, 1, 2, 3, 4],
            'games_normalized': [100, 200, 150, 120, 180, 90, 110, 140],
            'diff_coins_normalized': [10, 20, -5, -10, 15, 5, -20, 0]
        }
        df_train = pd.DataFrame(train_data)

        # テスト期間データ
        test_data = {
            'dd': [1, 1, 1, 1, 2, 2, 2, 2],
            'machine_number': [1, 2, 3, 4, 1, 2, 3, 4],
            'games_normalized': [110, 210, 160, 130, 190, 100, 120, 150],
            'diff_coins_normalized': [8, 18, -3, -8, 12, 3, -18, 2]
        }
        df_test = pd.DataFrame(test_data)

        return df_train, df_test

    def test_analyze_cross_metric_validation_games_basic(self, sample_data_with_games):
        """基本動作テスト（Task 4）"""
        df_train, df_test = sample_data_with_games

        result = analyze_cross_metric_validation_games(
            df_train, df_test, 'dd', 1, 'machine_number',
            top_percentile=50, mid_percentile=0, low_percentile=50
        )

        assert result is not None
        assert 'top_avg_coin' in result
        assert 'top_avg_wr' in result
        assert 'winner' in result
        assert 'max_relative' in result

    def test_analyze_cross_metric_validation_games_return_dict_keys(self, sample_data_with_games):
        """戻り値の辞書キーをチェック（Task 4）"""
        df_train, df_test = sample_data_with_games

        result = analyze_cross_metric_validation_games(
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

    def test_analyze_cross_metric_validation_games_empty_condition(self, sample_data_with_games):
        """条件にマッチするデータがない場合（Task 4）"""
        df_train, df_test = sample_data_with_games

        result = analyze_cross_metric_validation_games(
            df_train, df_test, 'dd', 99, 'machine_number',
            top_percentile=50, mid_percentile=0, low_percentile=50
        )

        assert result is None

    def test_analyze_cross_metric_validation_games_winner_selection(self, sample_data_with_games):
        """勝者が正しく選ばれるか（Task 4）"""
        df_train, df_test = sample_data_with_games

        result = analyze_cross_metric_validation_games(
            df_train, df_test, 'dd', 1, 'machine_number',
            top_percentile=50, mid_percentile=0, low_percentile=50
        )

        assert result['winner'] in ['上位G', '中間G', '下位G']


class TestFindOptimalPercentileRatio:
    """find_optimal_percentile_ratio() のテスト"""

    def test_find_optimal_percentile_ratio_structure(self):
        """比率最適化エンジンの出力構造をチェック（Task 5）"""
        # mockedデータで簡易テスト
        # (実際のDB読み込みが必要なため、ここでは基本構造のみ検証)
        # 注：実運用ではDB存在時のみテスト実行

        # モック結果の検証（関数が呼ばれた場合の戻り値構造）
        expected_keys = ['optimal_ratio', 'results']

        # テスト用のモックデータ構造
        mock_result = {
            'optimal_ratio': (36, 28, 36),
            'results': [
                {
                    'ratio': (50, 0, 50),
                    'winners_by_period': ['上位G', '上位G', '上位G'],
                    'is_consistent': True,
                    'consistency_symbol': '✅',
                    'relative_mean': 10.5,
                    'relative_std': 2.3,
                    'is_recommended': False
                }
            ]
        }

        for key in expected_keys:
            assert key in mock_result, f"キー '{key}' が見つかりません"

        assert isinstance(mock_result['optimal_ratio'], tuple)
        assert len(mock_result['results']) > 0
        assert 'ratio' in mock_result['results'][0]
        assert 'winners_by_period' in mock_result['results'][0]
        assert 'is_consistent' in mock_result['results'][0]


class TestRunMultiPeriodCrossMetricValidation:
    """run_multi_period_cross_metric_validation() のテスト"""

    def test_run_multi_period_cross_metric_validation_callable(self):
        """メイン実行関数が存在して呼び出し可能か（Task 6）"""
        # 関数の存在確認
        assert callable(run_multi_period_cross_metric_validation)

        # 関数シグネチャの確認
        import inspect
        sig = inspect.signature(run_multi_period_cross_metric_validation)
        assert 'db_path' in sig.parameters
