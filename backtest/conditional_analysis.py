"""条件付き分析モジュール - 特定の日（DD or 曜日）での台選択有効性検証"""

import pandas as pd
from extractor import extract_winning_patterns


def analyze_by_condition(df_train: pd.DataFrame, df_test: pd.DataFrame, condition_type: str, condition_value) -> dict:
    """
    特定の条件（DD or 曜日）で絞った上での台番号/機種/台末尾の勝率再現性を検証

    Args:
        df_train: 学習期間のDataFrame
        df_test: テスト期間のDataFrame
        condition_type: 'dd' または 'weekday'
        condition_value: 条件値（例：23 for DD=23、'Friday' for 金曜日）

    Returns:
        dict: 各属性（台番号、機種、台末尾）での再現率
    """
    # 条件で日を限定
    train_filtered = df_train[df_train[condition_type] == condition_value]
    test_filtered = df_test[df_test[condition_type] == condition_value]

    if len(train_filtered) == 0:
        return {'error': f'学習期間に{condition_type}={condition_value}のデータがありません'}

    if len(test_filtered) == 0:
        return {'error': f'テスト期間に{condition_type}={condition_value}のデータがありません'}

    results = {}

    # 3つの属性で分析
    for attr in ['machine_number', 'machine_name', 'last_digit']:
        # 学習期間でこの属性別の勝率を計算
        train_grouped = train_filtered.groupby(attr).agg({
            'diff_coins_normalized': ['count', lambda x: (x > 0).sum()]
        }).reset_index()
        train_grouped.columns = [attr, 'train_count', 'train_wins']
        train_grouped['train_win_rate'] = train_grouped['train_wins'] / train_grouped['train_count']

        # 勝率50%以上のものを抽出（複数パターンを見たいので66%以上ではなく50%以上）
        train_top = train_grouped[train_grouped['train_win_rate'] >= 0.50].sort_values('train_win_rate', ascending=False)

        if len(train_top) == 0:
            results[attr] = {'error': 'データなし'}
            continue

        # テスト期間でこれらのパターンの勝率を確認
        test_grouped = test_filtered.groupby(attr).agg({
            'diff_coins_normalized': ['count', lambda x: (x > 0).sum()]
        }).reset_index()
        test_grouped.columns = [attr, 'test_count', 'test_wins']
        test_grouped['test_win_rate'] = test_grouped['test_wins'] / test_grouped['test_count']

        # 学習期間で上位だったパターンがテスト期間でも再現したか
        reproduced_count = 0
        total_count = len(train_top)

        for _, train_row in train_top.iterrows():
            attr_value = train_row[attr]
            test_match = test_grouped[test_grouped[attr] == attr_value]

            if len(test_match) > 0:
                test_wr = test_match.iloc[0]['test_win_rate']
                if test_wr >= 0.50:  # テスト期間でも50%以上なら再現と判定
                    reproduced_count += 1

        reproduction_rate = reproduced_count / total_count if total_count > 0 else 0

        results[attr] = {
            'train_patterns': len(train_top),
            'reproduced_count': reproduced_count,
            'reproduction_rate': reproduction_rate,
            'avg_train_wr': train_top['train_win_rate'].mean(),
            'test_count': len(test_grouped)
        }

    return results
