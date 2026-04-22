"""バリデーション（テスト期間での検証）モジュール"""

import pandas as pd


def validate_patterns(df: pd.DataFrame, patterns: pd.DataFrame, attr1: str, attr2: str) -> pd.DataFrame:
    """
    テスト期間で複合属性パターンが勝利するか検証

    Args:
        df: ローダーで読み込んだDataFrame（attr1, attr2カラムが必須）
        patterns: extractorで抽出したパターンDataFrame
        attr1: 第1属性
        attr2: 第2属性

    Returns:
        DataFrame: パターン + 学習勝率 + テスト勝率 + 再現判定
    """
    results = []

    for _, pattern_row in patterns.iterrows():
        val1 = pattern_row[attr1]
        val2 = pattern_row[attr2]
        train_win_rate = pattern_row['win_rate']

        # テスト期間でこのパターンのデータを抽出
        test_data = df[(df[attr1] == val1) & (df[attr2] == val2)]

        if len(test_data) == 0:
            continue

        # テスト期間での勝率
        test_win_count = (test_data['diff_coins_normalized'] > 0).sum()
        test_total_count = len(test_data)
        test_win_rate = test_win_count / test_total_count if test_total_count > 0 else 0

        results.append({
            'attr1': val1,
            'attr2': val2,
            'train_win_rate': train_win_rate,
            'train_count': int(pattern_row['total_count']),
            'test_win_rate': test_win_rate,
            'test_count': test_total_count,
            'test_win_count': test_win_count,
            'reproduced': test_win_rate > 0.5  # 50%以上なら再現したと判定
        })

    return pd.DataFrame(results)


def analyze_win_rate_correlation(df: pd.DataFrame, patterns: pd.DataFrame, attr1: str, attr2: str) -> dict:
    """
    勝率と次月勝利の相関を分析

    勝率が高い → 次月も勝つ？
    勝率が低い → 次月も勝つ？

    Args:
        df: ローダーで読み込んだDataFrame（attr1, attr2カラムが必須）
        patterns: 学習期間で抽出したパターン
        attr1: 第1属性
        attr2: 第2属性

    Returns:
        dict: 高勝率・低勝率ごとの再現率
    """
    validated = validate_patterns(df, patterns, attr1, attr2)

    if len(validated) == 0:
        return {}

    # 中央値で分割
    median_win_rate = validated['train_win_rate'].median()

    high_wr = validated[validated['train_win_rate'] >= median_win_rate]
    low_wr = validated[validated['train_win_rate'] < median_win_rate]

    return {
        'high_win_rate': {
            'count': len(high_wr),
            'reproduced_count': (high_wr['test_win_rate'] > 0.5).sum(),
            'reproduction_rate': (high_wr['test_win_rate'] > 0.5).sum() / len(high_wr) if len(high_wr) > 0 else 0,
            'avg_train_wr': high_wr['train_win_rate'].mean(),
            'avg_test_wr': high_wr['test_win_rate'].mean()
        },
        'low_win_rate': {
            'count': len(low_wr),
            'reproduced_count': (low_wr['test_win_rate'] > 0.5).sum(),
            'reproduction_rate': (low_wr['test_win_rate'] > 0.5).sum() / len(low_wr) if len(low_wr) > 0 else 0,
            'avg_train_wr': low_wr['train_win_rate'].mean(),
            'avg_test_wr': low_wr['test_win_rate'].mean()
        }
    }
