import pytest
import pandas as pd
from datetime import datetime
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def make_hall_summary_df():
    return pd.DataFrame({
        'date': pd.to_datetime(['2026-01-10', '2026-01-15', '2026-01-20']),
        'avg_games_per_machine': [800, 1200, 1500],
        'avg_diff_per_machine': [100, 200, 300],
        'win_rate': [45.0, 55.0, 60.0],
    })

def make_machine_df():
    return pd.DataFrame({
        'date': pd.to_datetime(['2026-01-10', '2026-01-15', '2026-01-20']),
        'games_normalized': [800, 1200, 1500],
        'diff_coins_normalized': [100, 200, 300],
        'machine_number': [101, 102, 103],
    })

class TestFilterByDateRange:
    def test_日付範囲内のデータのみ返す(self):
        from dashboard.utils.filters import filter_by_date_range
        df = make_hall_summary_df()
        start = datetime(2026, 1, 12)
        end = datetime(2026, 1, 18)
        result = filter_by_date_range(df, (start, end))
        assert len(result) == 1
        assert result.iloc[0]['avg_games_per_machine'] == 1200

    def test_空のDataFrameを受け取った場合空を返す(self):
        from dashboard.utils.filters import filter_by_date_range
        result = filter_by_date_range(pd.DataFrame(), (datetime(2026, 1, 1), datetime(2026, 12, 31)))
        assert result.empty

class TestFilterByMinGames:
    def test_ホール集計テーブルでmin_games未満を除外する(self):
        from dashboard.utils.filters import filter_by_min_games
        df = make_hall_summary_df()
        result = filter_by_min_games(df, 1000, column='avg_games_per_machine')
        assert len(result) == 2
        assert result['avg_games_per_machine'].min() >= 1000

    def test_個別台テーブルでmin_games未満を除外する(self):
        from dashboard.utils.filters import filter_by_min_games
        df = make_machine_df()
        result = filter_by_min_games(df, 1000, column='games_normalized')
        assert len(result) == 2

class TestApplySidebarFilters:
    def test_show_low_confidenceがTrueなら全件残る(self):
        from dashboard.utils.filters import apply_sidebar_filters
        df = make_hall_summary_df()
        result = apply_sidebar_filters(
            df,
            date_range=(datetime(2026, 1, 1), datetime(2026, 12, 31)),
            min_games=9999,
            show_low_confidence=True
        )
        assert len(result) == 3

    def test_show_low_confidenceがFalseならmin_gamesでフィルタ(self):
        from dashboard.utils.filters import apply_sidebar_filters
        df = make_hall_summary_df()
        result = apply_sidebar_filters(
            df,
            date_range=(datetime(2026, 1, 1), datetime(2026, 12, 31)),
            min_games=1000,
            show_low_confidence=False
        )
        assert len(result) == 2

class TestApplyMachineFilters:
    def test_個別台データにgames_normalizedで適用する(self):
        from dashboard.utils.filters import apply_machine_filters
        df = make_machine_df()
        result = apply_machine_filters(
            df,
            date_range=(datetime(2026, 1, 1), datetime(2026, 12, 31)),
            min_games=1000,
            show_low_confidence=False
        )
        assert len(result) == 2
        assert result['games_normalized'].min() >= 1000
