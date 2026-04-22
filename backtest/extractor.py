"""パターン抽出モジュール"""

import pandas as pd


def extract_winning_patterns(
    df: pd.DataFrame,
    attr1: str,
    attr2: str,
    win_rate_threshold: float = 0.66
) -> pd.DataFrame:
    """
    学習期間の複合属性パターンを抽出し、勝率がしきい値以上のものを返す

    Args:
        df: ローダーで読み込んだDataFrame（attr1, attr2カラムが必須）
        attr1: 第1属性（'dd', 'weekday' など）
        attr2: 第2属性（'last_digit', 'machine_number', 'machine_name' など）
        win_rate_threshold: 勝率しきい値（デフォルト0.66=66%）

    Returns:
        DataFrame: attr1 | attr2 | win_rate | total_count | avg_diff | avg_games
    """
    # グループ化して集計
    grouped = df.groupby([attr1, attr2], as_index=False).agg({
        'diff_coins_normalized': ['count', 'mean'],
        'games_normalized': 'mean'
    })

    # カラム名を整理
    grouped.columns = [attr1, attr2, 'total_count', 'avg_diff', 'avg_games']

    # 勝利数計算
    win_counts = df[df['diff_coins_normalized'] > 0].groupby([attr1, attr2]).size()
    grouped['win_count'] = grouped.apply(
        lambda row: win_counts.get((row[attr1], row[attr2]), 0),
        axis=1
    )

    # 勝率計算
    grouped['win_rate'] = grouped['win_count'] / grouped['total_count']

    # しきい値以上のみ抽出
    result = grouped[grouped['win_rate'] >= win_rate_threshold].copy()
    result = result.sort_values('win_rate', ascending=False).reset_index(drop=True)

    return result[[attr1, attr2, 'win_rate', 'total_count', 'avg_diff', 'avg_games']]
