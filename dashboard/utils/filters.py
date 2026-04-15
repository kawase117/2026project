"""
共通フィルタリング関数
全ページで重複していたフィルタロジックを集約
"""

import pandas as pd
from typing import Tuple
from datetime import datetime


def filter_by_date_range(
    df: pd.DataFrame,
    date_range: Tuple[datetime, datetime],
    date_column: str = 'date'
) -> pd.DataFrame:
    """日付範囲でDataFrameをフィルタリングする"""
    if df.empty or date_range is None:
        return df
    start, end = date_range
    return df[(df[date_column] >= start) & (df[date_column] <= end)]


def filter_by_min_games(
    df: pd.DataFrame,
    min_games: int,
    column: str = 'avg_games_per_machine'
) -> pd.DataFrame:
    """最小G数でDataFrameをフィルタリングする"""
    if df.empty:
        return df
    return df[df[column] >= min_games]


def apply_sidebar_filters(
    df: pd.DataFrame,
    date_range: Tuple[datetime, datetime],
    min_games: int,
    show_low_confidence: bool,
    date_column: str = 'date',
    games_column: str = 'avg_games_per_machine'
) -> pd.DataFrame:
    """
    サイドバーのフィルタ設定を一括適用する（ホール集計用）
    """
    df = filter_by_date_range(df, date_range, date_column)
    if not show_low_confidence and not df.empty:
        df = filter_by_min_games(df, min_games, games_column)
    return df


def apply_machine_filters(
    df: pd.DataFrame,
    date_range: Tuple[datetime, datetime],
    min_games: int,
    show_low_confidence: bool,
    date_column: str = 'date',
    games_column: str = 'games_normalized'
) -> pd.DataFrame:
    """
    サイドバーのフィルタ設定を一括適用する（個別台データ用）
    min_gamesは集計前に個別台レベルで適用する。
    """
    df = filter_by_date_range(df, date_range, date_column)
    if not show_low_confidence and not df.empty:
        df = filter_by_min_games(df, min_games, games_column)
    return df
