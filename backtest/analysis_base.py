"""相対パフォーマンス分析の共通フレームワーク"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path
from loader import load_machine_data
import pandas as pd


# ========== データ定義 ==========

TRAINING_PERIODS = [
    ('6月', '2025-10-01', '2026-03-31'),
    ('3月', '2026-01-01', '2026-03-31'),
    ('1月', '2026-03-01', '2026-03-31'),
]

TEST_START = '2026-04-01'
TEST_END = '2026-04-20'

ATTRIBUTES = ['machine_number', 'machine_name', 'last_digit']
ATTRIBUTES_JA = {'machine_number': '機械番号', 'machine_name': '機種名', 'last_digit': '台末尾'}

WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
WEEKDAY_JP = ['月', '火', '水', '木', '金', '土', '日']

HALLS = [
    "マルハンメガシティ2000-蒲田1.db",
    "マルハンメガシティ2000-蒲田7.db"
]


# ========== ユーティリティ関数 ==========

def load_and_split_data(db_path: str, period_name: str, start_date: str, end_date: str):
    """DB読み込みと訓練・テストデータの分割"""
    df = load_machine_data(db_path)
    df_train = df[(df['date'] >= start_date) & (df['date'] <= end_date)].copy()
    df_test = df[(df['date'] >= TEST_START) & (df['date'] <= TEST_END)].copy()
    return df_train, df_test


def print_header(db_name: str, period_name: str, start_date: str, end_date: str):
    """ヘッダー出力"""
    print(f"\n{'=' * 140}")
    print(f"訓練期間：{period_name} ({start_date} ～ {end_date})")
    print(f"テスト期間：{TEST_START} ～ {TEST_END}")
    print(f"DB：{Path(db_name).stem}")
    print(f"{'=' * 140}")


def print_dd_section(period_name: str):
    """DD別セクションのヘッダー"""
    print(f"\nDD別 相対パフォーマンス（{period_name}訓練）")
    print("-" * 140)
    print(f"{'DD':<5} {'属性':<15} {'基準':<8} {'高G':<12} {'vs基準':<10} {'低G':<12} {'vs基準':<10} {'勝者':<12}")
    print("-" * 140)


def print_weekday_section(period_name: str):
    """曜日別セクションのヘッダー"""
    print(f"\n{'=' * 140}")
    print(f"曜日別 相対パフォーマンス（{period_name}訓練）")
    print("-" * 140)
    print(f"{'曜日':<6} {'属性':<15} {'基準':<8} {'高G':<12} {'vs基準':<10} {'低G':<12} {'vs基準':<10} {'勝者':<12}")
    print("-" * 140)


def print_result_row(condition_label: str, attr: str, result: dict):
    """結果行を出力"""
    if not result:
        return

    r = result
    high_sign = "+" if r['high_relative'] >= 0 else ""
    low_sign = "+" if r['low_relative'] >= 0 else ""

    print(f"{condition_label:<5} {attr:<15} {r['condition_avg']:>6.1f}% {r['high_avg']:>6.1f}% {high_sign}{r['high_relative']:>7.1f}% {r['low_avg']:>6.1f}% {low_sign}{r['low_relative']:>7.1f}% {r['winner']:<12}")


def get_condition_average(df_test: pd.DataFrame, metric_column: str) -> float:
    """条件（DD/曜日）全体の平均値を計算"""
    if metric_column == 'diff_coins_normalized':
        # 勝率の場合
        return (df_test[metric_column] > 0).sum() / len(df_test) if len(df_test) > 0 else 0
    else:
        # 数値平均の場合
        return df_test[metric_column].mean() if len(df_test) > 0 else 0


def get_group_average(group_list: list, test_grouped: pd.DataFrame, attr: str, metric_column: str) -> list:
    """グループの平均値を計算"""
    values = []
    for item in group_list:
        item_val = item[attr]
        test_match = test_grouped[test_grouped[attr] == item_val]
        if len(test_match) > 0:
            if metric_column == 'diff_coins_normalized':
                # 勝率
                avg = (test_match[metric_column] > 0).sum() / len(test_match)
            else:
                # 平均値
                avg = test_match[metric_column].mean()
            values.append(avg)
    return values


def get_group_stats(group_list: list, test_grouped: pd.DataFrame, attr: str, metric_column: str, condition_avg: float) -> dict:
    """グループの統計情報を計算"""
    values = get_group_average(group_list, test_grouped, attr, metric_column)

    if not values:
        return None

    avg = sum(values) / len(values)
    relative = avg - condition_avg

    return {
        'avg': avg,
        'relative': relative,
        'count': len(group_list),
    }
