"""クロス属性パフォーマンス分析 - 訓練G数/勝率/差枚 → テスト差枚 の予測力を検証"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd
from pathlib import Path
from io import StringIO
from loader import load_machine_data
from analysis_base import (
    map_groups_by_attr, aggregate_group_metrics, calculate_rank_correlation,
)

TRAIN_ATTRS = {
    'games_normalized': 'G数',
    'win_rate_train': '勝率',
    'diff_coins_normalized': '差枚',
}

SIGNIFICANCE_LABEL = {True: '(*)', False: ''}


def _calc_win_rate_col(df: pd.DataFrame, split_unit: str) -> pd.DataFrame:
    """split_unit 別に勝率カラム win_rate_train を計算して追加"""
    wr = df.groupby(split_unit)['diff_coins_normalized'].apply(
        lambda x: (x > 0).sum() / len(x)
    ).reset_index()
    wr.columns = [split_unit, 'win_rate_train']
    return df.merge(wr, on=split_unit, how='left')


def analyze_cross_attribute(
    df_train: pd.DataFrame,
    df_test: pd.DataFrame,
    train_attr: str,
    split_unit: str,
) -> dict | None:
    """
    単一の訓練属性×split_unit で分析を実行し結果 dict を返す。

    Returns:
        {'metrics': DataFrame, 'corr': float, 'p_value': float}
        グループ分割不可の場合は None
    """
    if train_attr == 'win_rate_train':
        df_train = _calc_win_rate_col(df_train, split_unit)

    labeled_test = map_groups_by_attr(df_train, df_test, train_attr, split_unit)
    if labeled_test is None:
        return None

    metrics = aggregate_group_metrics(labeled_test)

    grp_units = df_train.groupby(split_unit)[train_attr].mean()
    train_avgs = []
    for group_label in ['Top', 'Mid', 'Low']:
        units_in_group = labeled_test[labeled_test['group'] == group_label][split_unit].unique()
        if len(units_in_group) == 0:
            train_avgs.append(0.0)
        else:
            train_avgs.append(float(grp_units[grp_units.index.isin(units_in_group)].mean()))

    test_avgs = metrics['avg_coin'].tolist()
    corr, p_value = calculate_rank_correlation(train_avgs, test_avgs)

    return {'metrics': metrics, 'corr': corr, 'p_value': p_value}


def format_result_block(
    train_attr_label: str,
    condition_type: str,
    condition_value,
    train_start: str,
    train_end: str,
    test_start: str,
    test_end: str,
    result: dict,
) -> str:
    """結果を文字列フォーマットして返す"""
    buf = StringIO()
    buf.write("=" * 48 + "\n")
    buf.write(f"訓練属性: {train_attr_label}\n")
    buf.write(f"条件: {condition_type} = {condition_value}\n")
    buf.write(f"訓練期間: {train_start} 〜 {train_end} / テスト期間: {test_start[:7]}\n")
    buf.write("=" * 48 + "\n")
    buf.write(f"{'グループ':<14} | {'台数':>4} | {'平均差枚':>8} | {'勝率(%)':>7}\n")
    buf.write("-" * 48 + "\n")
    for _, row in result['metrics'].iterrows():
        sign = "+" if row['avg_coin'] >= 0 else ""
        label = f"{row['group']}（{'上位' if row['group']=='Top' else '中位' if row['group']=='Mid' else '下位'}33%）"
        buf.write(f"{label:<14} | {int(row['count']):>4} | {sign}{row['avg_coin']:>7.0f}枚 | {row['win_rate']*100:>6.1f}%\n")
    buf.write("-" * 48 + "\n")
    sig = SIGNIFICANCE_LABEL[result['p_value'] < 0.05]
    buf.write(f"スピアマン相関: {result['corr']:.2f}  有意性: p={result['p_value']:.3f} {sig}\n")
    buf.write("=" * 48 + "\n")
    return buf.getvalue()


def run_cross_attribute_analysis(
    db_path: str,
    train_start: str,
    train_end: str,
    test_start: str,
    test_end: str,
    condition_type: str,
    condition_value,
) -> None:
    """
    G数/勝率/差枚 × condition_type/condition_value で一括分析を実行し、
    コンソール出力とファイル保存を行う。
    """
    df = load_machine_data(db_path)
    df = df[df[condition_type] == condition_value].copy()

    df_train = df[(df['date'] >= pd.Timestamp(train_start)) &
                  (df['date'] <= pd.Timestamp(train_end))]
    df_test = df[(df['date'] >= pd.Timestamp(test_start)) &
                 (df['date'] <= pd.Timestamp(test_end))]

    if len(df_train) == 0 or len(df_test) == 0:
        print(f"[SKIP] データなし: {condition_type}={condition_value}")
        return

    output_lines = []

    for attr_col, attr_label in TRAIN_ATTRS.items():
        for split_unit in ['dd', 'last_digit', 'weekday']:
            result = analyze_cross_attribute(df_train, df_test, attr_col, split_unit)
            if result is None:
                continue
            block = format_result_block(
                attr_label, condition_type, condition_value,
                train_start, train_end, test_start, test_end, result,
            )
            print(block)
            output_lines.append(block)

    test_month = pd.Timestamp(test_start).strftime('%Y-%m')
    out_dir = Path(__file__).parent / 'results'
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"cross_attribute_analysis_{condition_type}_{condition_value}_{test_month}.txt"
    out_path.write_text("\n".join(output_lines), encoding='utf-8')
    print(f"\n結果を保存: {out_path}")
