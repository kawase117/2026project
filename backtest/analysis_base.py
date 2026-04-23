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


def print_dd_section_triple(period_name: str):
    """DD別セクションのヘッダー（3グループ用）"""
    print(f"\nDD別 相対パフォーマンス（{period_name}訓練）")
    print("-" * 160)
    print(f"{'DD':<5} {'属性':<15} {'基準':<8} {'上位G':<12} {'vs基準':<10} {'中間G':<12} {'vs基準':<10} {'下位G':<12} {'vs基準':<10} {'勝者':<12}")
    print("-" * 160)


def print_weekday_section(period_name: str):
    """曜日別セクションのヘッダー"""
    print(f"\n{'=' * 140}")
    print(f"曜日別 相対パフォーマンス（{period_name}訓練）")
    print("-" * 140)
    print(f"{'曜日':<6} {'属性':<15} {'基準':<8} {'高G':<12} {'vs基準':<10} {'低G':<12} {'vs基準':<10} {'勝者':<12}")
    print("-" * 140)


def print_weekday_section_triple(period_name: str):
    """曜日別セクションのヘッダー（3グループ用）"""
    print(f"\n{'=' * 160}")
    print(f"曜日別 相対パフォーマンス（{period_name}訓練）")
    print("-" * 160)
    print(f"{'曜日':<6} {'属性':<15} {'基準':<8} {'上位G':<12} {'vs基準':<10} {'中間G':<12} {'vs基準':<10} {'下位G':<12} {'vs基準':<10} {'勝者':<12}")
    print("-" * 160)


def print_result_row(condition_label: str, attr: str, result: dict):
    """結果行を出力"""
    if not result:
        return

    r = result
    high_sign = "+" if r['high_relative'] >= 0 else ""
    low_sign = "+" if r['low_relative'] >= 0 else ""

    print(f"{condition_label:<5} {attr:<15} {r['condition_avg']:>6.1f}% {r['high_avg']:>6.1f}% {high_sign}{r['high_relative']:>7.1f}% {r['low_avg']:>6.1f}% {low_sign}{r['low_relative']:>7.1f}% {r['winner']:<12}")


def print_result_row_triple(condition_label: str, attr: str, result: dict):
    """結果行を出力（3グループ用）"""
    if not result:
        return

    r = result
    top_sign = "+" if r['top_relative'] >= 0 else ""
    mid_sign = "+" if r['mid_relative'] >= 0 else ""
    low_sign = "+" if r['low_relative'] >= 0 else ""

    print(f"{condition_label:<5} {attr:<15} {r['condition_avg']:>6.1f}% "
          f"{r['top_avg']:>6.1f}% {top_sign}{r['top_relative']:>7.1f}% "
          f"{r['mid_avg']:>6.1f}% {mid_sign}{r['mid_relative']:>7.1f}% "
          f"{r['low_avg']:>6.1f}% {low_sign}{r['low_relative']:>7.1f}% "
          f"{r['winner']:<12}")


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


def split_groups_triple(train_grouped: pd.DataFrame, metric_column: str):
    """
    訓練期間データを3グループに分割（パーセンタイル固定）
    上位36% / 中間28% / 下位36%

    戻り値: (top_group, mid_group, low_group)
    """
    if len(train_grouped) == 0:
        return None, None, None

    sorted_df = train_grouped.sort_values(metric_column).reset_index(drop=True)
    n = len(sorted_df)

    # パーセンタイル計算（切り位置）
    low_cutoff_idx = max(0, int(n * 0.36) - 1)  # 下位36%の上限
    top_cutoff_idx = min(n - 1, int(n * 0.64))    # 上位36%の下限

    low_cutoff_val = sorted_df.iloc[low_cutoff_idx][metric_column]
    top_cutoff_val = sorted_df.iloc[top_cutoff_idx][metric_column]

    # 3グループに分割
    top_g = train_grouped[train_grouped[metric_column] > top_cutoff_val]
    mid_g = train_grouped[(train_grouped[metric_column] > low_cutoff_val) &
                          (train_grouped[metric_column] <= top_cutoff_val)]
    low_g = train_grouped[train_grouped[metric_column] <= low_cutoff_val]

    return top_g, mid_g, low_g


def split_groups_triple_custom(train_grouped: pd.DataFrame, metric_column: str,
                               top_percentile: float, mid_percentile: float, low_percentile: float):
    """
    訓練期間データを3グループに分割（カスタム比率対応）

    パラメータ：
      top_percentile: 上位グループの割合（0-100）
      mid_percentile: 中間グループの割合（0-100）
      low_percentile: 下位グループの割合（0-100）

    戻り値: (top_group, mid_group, low_group)
    注：比率の合計が100になることを前提。呼び出し側で検証
    """
    if len(train_grouped) == 0:
        return None, None, None

    sorted_df = train_grouped.sort_values(metric_column).reset_index(drop=True)
    n = len(sorted_df)

    # パーセンタイル計算（インデックス位置）
    # 下位グループの要素数
    low_count = round(n * low_percentile / 100)
    # 中間グループの要素数
    mid_count = round(n * mid_percentile / 100)

    # 3グループに分割（インデックスベースで直接分割）
    low_g = sorted_df.iloc[:low_count]
    mid_g = sorted_df.iloc[low_count:low_count + mid_count]
    top_g = sorted_df.iloc[low_count + mid_count:]

    # 元のDataFrameのインデックスを復元
    low_g = train_grouped.loc[low_g.index]
    mid_g = train_grouped.loc[mid_g.index]
    top_g = train_grouped.loc[top_g.index]

    return top_g, mid_g, low_g


# ========== パーセンタイル比率の候補 ==========

PERCENTILE_CANDIDATES = [
    (50, 0, 50),    # 2分割相当：上位50%・下位50%
    (45, 10, 45),   # バランス型
    (40, 20, 40),   # 中間重視
    (36, 28, 36),   # 現在の設定
    (33, 34, 33),   # ほぼ均等
]


# ========== 一貫性計算関数 ==========

def calculate_consistency_score(winners_by_period: list) -> tuple:
    """
    複数訓練期間での勝者の一貫性をチェック

    パラメータ：
      winners_by_period: ['上位G', '上位G', '上位G'] など、各訓練期間での勝者リスト

    戻り値: (is_consistent, consistency_symbol)
      - is_consistent: bool — 3期間すべてで同じ勝者か
      - consistency_symbol: str — "✅" または "⚠️"
    """
    if not winners_by_period or len(winners_by_period) != 3:
        return False, "⚠️"

    first_winner = winners_by_period[0]
    is_consistent = all(w == first_winner for w in winners_by_period)

    return is_consistent, "✅" if is_consistent else "⚠️"


# ========== クロス属性分析 共通関数 ==========

def map_groups_by_attr(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    train_attr: str,
    split_unit: str,
) -> pd.DataFrame | None:
    """
    訓練期間で split_unit 別に train_attr を平均集計し Top/Mid/Low に分割。
    テスト期間データの各行に 'group' ラベル（Top/Mid/Low）を付与して返す。
    split_unit に 3 つ未満の一意値しかない場合は None を返す。
    """
    train_grouped = train_df.groupby(split_unit)[train_attr].mean().reset_index()
    train_grouped.columns = [split_unit, 'train_val']

    if len(train_grouped) < 3:
        return None

    top_g, mid_g, low_g = split_groups_triple(train_grouped, 'train_val')
    if top_g is None or mid_g is None or low_g is None:
        return None

    top_units = set(top_g[split_unit].values)
    mid_units = set(mid_g[split_unit].values)
    low_units = set(low_g[split_unit].values)

    def assign_group(val):
        if val in top_units:
            return 'Top'
        elif val in mid_units:
            return 'Mid'
        elif val in low_units:
            return 'Low'
        return None

    result = test_df.copy()
    result['group'] = result[split_unit].apply(assign_group)
    return result[result['group'].notna()].reset_index(drop=True)


def aggregate_group_metrics(
    df: pd.DataFrame,
    group_col: str = 'group',
    result_col: str = 'diff_coins_normalized',
) -> pd.DataFrame:
    """
    グループ別に台数・平均差枚・勝率を集計する。
    返却カラム: group, count, avg_coin, win_rate
    グループ順は Top → Mid → Low の固定順。
    """
    rows = []
    for group_label in ['Top', 'Mid', 'Low']:
        grp = df[df[group_col] == group_label]
        if len(grp) == 0:
            rows.append({'group': group_label, 'count': 0, 'avg_coin': 0.0, 'win_rate': 0.0})
            continue
        rows.append({
            'group': group_label,
            'count': len(grp),
            'avg_coin': grp[result_col].mean(),
            'win_rate': (grp[result_col] > 0).sum() / len(grp),
        })
    return pd.DataFrame(rows)
