"""
比較ビュー用ユーティリティ
前期間比・全体平均比などの差分計算を集約
"""

from __future__ import annotations

import pandas as pd


def compute_previous_period_range(date_range: tuple) -> tuple:
    """date_range と同じ日数分、直前の期間を返す（前期間比較用）"""
    start, end = date_range
    period_length = end - start
    prev_end = start - pd.Timedelta(days=1)
    prev_start = prev_end - period_length
    return (prev_start, prev_end)


def add_baseline_diff_column(
    df: pd.DataFrame,
    value_col: str,
    baseline_value: float,
    new_col: str = 'vs_avg',
) -> pd.DataFrame:
    """指定カラムと baseline_value との差分カラムを追加した DataFrame を返す"""
    df = df.copy()
    df[new_col] = df[value_col] - baseline_value
    return df
