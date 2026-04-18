"""
属性値計算の共通ロジック
page_11 と page_14 で共用
"""

import pandas as pd


def get_attr_value(df: pd.DataFrame, attr: str) -> pd.Series:
    """
    属性値を計算して返す

    Args:
        df: データフレーム（'date', 'machine_number', 'is_zorome', 'machine_name' カラムを含む）
        attr: 属性名
            - '台番号末尾': 台番号の末尾（ゾロ目の場合は「ゾロ目」）
            - '日末尾': 日付の末尾（1-9の数値）
            - 'DD別': 月内の日付（1-31）
            - '曜日': 曜日（英語）
            - '第X曜日': 月内の第N曜日（"Mon1" など）
            - '機種別': 機種名
            - '台番号別': 台番号（文字列）

    Returns:
        属性値を含む Series

    Raises:
        ValueError: 不明な属性名の場合
    """
    if attr == '台番号末尾':
        # ゾロ目（is_zorome == 1）の場合は「ゾロ目」、それ以外は末尾を返す
        result = pd.Series((df['machine_number'] % 10).astype(str), index=df.index)
        zorome_mask = df['is_zorome'] == 1
        result[zorome_mask] = 'ゾロ目'
        return result

    elif attr == '日末尾':
        return df['date'].dt.strftime('%d').str[-1].astype(int)

    elif attr == 'DD別':
        return df['date'].dt.day

    elif attr == '曜日':
        return df['date'].dt.day_name()

    elif attr == '第X曜日':
        # 日付から計算
        dates = df['date'].unique()
        weekday_nth_map = {}
        for d in dates:
            dow = d.strftime('%a')
            day = d.day
            week_of_month = (day - 1) // 7 + 1
            dow_map = {
                'Mon': 'Mon', 'Tue': 'Tue', 'Wed': 'Wed',
                'Thu': 'Thu', 'Fri': 'Fri', 'Sat': 'Sat', 'Sun': 'Sun'
            }
            weekday_nth_map[d.date()] = f"{dow_map[dow]}{week_of_month}"
        return df['date'].dt.date.map(weekday_nth_map)

    elif attr == '機種別':
        return df['machine_name']

    elif attr == '台番号別':
        return df['machine_number'].astype(str)

    else:
        raise ValueError(f"不明な属性: {attr}")
