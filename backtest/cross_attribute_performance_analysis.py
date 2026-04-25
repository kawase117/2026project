"""クロス属性パフォーマンス分析 - 複数訓練期間・複数条件値対応版"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd
import warnings
from pathlib import Path
from io import StringIO
from loader import load_machine_data
from analysis_base import (
    TRAINING_PERIODS, TEST_START, TEST_END,
    ATTRIBUTES, ATTRIBUTES_JA, WEEKDAYS, WEEKDAY_JP, HALLS,
    map_groups_by_attr, aggregate_group_metrics, calculate_rank_correlation,
)

warnings.filterwarnings('ignore', message='An input array is constant')

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

    Args:
        df_train, df_test: 既に条件値でフィルタされたDataFrame
        train_attr: 訓練属性カラム名
        split_unit: グループ分割単位（'dd', 'weekday', 'last_digit'等）

    Returns:
        {'metrics': DataFrame, 'corr': float, 'p_value': float, 'winner': str}
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

    # 勝者判定：test_avgs から最も高い値を持つグループ
    winner_idx = test_avgs.index(max(test_avgs))
    winner_map = {0: '上位G', 1: '中間G', 2: '下位G'}
    winner = winner_map[winner_idx]

    return {'metrics': metrics, 'corr': corr, 'p_value': p_value, 'winner': winner}


class WinnerStatistics:
    """統計カウント管理クラス - DD別・曜日別の勝者カウント集約（訓練属性×分割単位）"""

    def __init__(self, train_attrs: dict) -> None:
        """
        Args:
            train_attrs: 訓練属性辞書 {'col_name': 'ラベル', ...}
        """
        self.is_recording = False  # 統計記録有効フラグ（最終訓練期間のみ）
        self.dd_stats = {
            f"{attr_label}_{split_unit}": {'上位G': 0, '中間G': 0, '下位G': 0}
            for attr_label in train_attrs.values()
            for split_unit in ATTRIBUTES
        }
        self.wd_stats = {
            f"{attr_label}_{split_unit}": {'上位G': 0, '中間G': 0, '下位G': 0}
            for attr_label in train_attrs.values()
            for split_unit in ATTRIBUTES
        }

    def enable_recording(self) -> None:
        """最終訓練期間で統計記録を有効化"""
        self.is_recording = True

    def record_dd_result(self, attr_label: str, result: dict, split_unit: str) -> None:
        """DD別の結果を記録（全split_unit対象）"""
        if self.is_recording and result:
            key = f"{attr_label}_{split_unit}"
            if key in self.dd_stats:
                self.dd_stats[key][result['winner']] += 1

    def record_wd_result(self, attr_label: str, result: dict, split_unit: str) -> None:
        """曜日別の結果を記録（全split_unit対象）"""
        if self.is_recording and result:
            key = f"{attr_label}_{split_unit}"
            if key in self.wd_stats:
                self.wd_stats[key][result['winner']] += 1

    def print_dd_statistics(self) -> None:
        """DD別統計を出力"""
        print("\nDD別 勝者統計（最終訓練期間、訓練属性×分割単位）:")
        for key in sorted(self.dd_stats.keys()):
            counts = self.dd_stats[key]
            top = counts['上位G']
            mid = counts['中間G']
            low = counts['下位G']
            total = top + mid + low
            if total > 0:
                print(f"  {key:<25}: 上位G勝利 {top:>2}/20回 ({top/20*100:>5.1f}%) | "
                      f"中間G勝利 {mid:>2}/20回 ({mid/20*100:>5.1f}%) | "
                      f"下位G勝利 {low:>2}/20回 ({low/20*100:>5.1f}%)")

    def print_wd_statistics(self) -> None:
        """曜日別統計を出力"""
        print("\n曜日別 勝者統計（最終訓練期間、訓練属性×分割単位）:")
        for key in sorted(self.wd_stats.keys()):
            counts = self.wd_stats[key]
            top = counts['上位G']
            mid = counts['中間G']
            low = counts['下位G']
            total = top + mid + low
            if total > 0:
                print(f"  {key:<25}: 上位G勝利 {top:>2}/7回 ({top/7*100:>5.1f}%) | "
                      f"中間G勝利 {mid:>2}/7回 ({mid/7*100:>5.1f}%) | "
                      f"下位G勝利 {low:>2}/7回 ({low/7*100:>5.1f}%)")


def _print_section_header(section_type: str) -> None:
    """セクションヘッダーを出力

    Args:
        section_type: 'dd' または 'weekday'
    """
    if section_type == 'dd':
        label = "DD別分析"
        col_label = "条件"
    else:
        label = "曜日別分析"
        col_label = "曜日"

    print(f"\n========== {label} ==========")
    print(f"{col_label:<6} {'訓練属性':<15} {'基準値':<10} "
          f"{'上位G':<10} {'vs':<8} {'中位G':<10} {'vs':<8} {'下位G':<10} {'vs':<8} "
          f"{'勝者':<10} | {'相関':<8} {'p値':<8}")
    print("-" * 150)


def format_result_line(
    condition_label: str,
    train_attr_label: str,
    result: dict,
) -> str:
    """結果を1行フォーマットして返す"""
    if result is None:
        return ""

    m = result['metrics']
    top_avg = m[m['group'] == 'Top']['avg_coin'].values[0] if len(m[m['group'] == 'Top']) > 0 else 0.0
    mid_avg = m[m['group'] == 'Mid']['avg_coin'].values[0] if len(m[m['group'] == 'Mid']) > 0 else 0.0
    low_avg = m[m['group'] == 'Low']['avg_coin'].values[0] if len(m[m['group'] == 'Low']) > 0 else 0.0

    # 基準値は全体平均（ここでは差枚平均で代用）
    baseline = (top_avg * len(m[m['group'] == 'Top']) +
                mid_avg * len(m[m['group'] == 'Mid']) +
                low_avg * len(m[m['group'] == 'Low'])) / len(m)

    top_vs = top_avg - baseline
    mid_vs = mid_avg - baseline
    low_vs = low_avg - baseline

    top_sign = "+" if top_vs >= 0 else ""
    mid_sign = "+" if mid_vs >= 0 else ""
    low_sign = "+" if low_vs >= 0 else ""
    sig_label = "(*)" if result['p_value'] < 0.05 else ""

    return (f"{condition_label:<6} {train_attr_label:<15} {baseline:>9.0f}枚 "
            f"{top_avg:>9.0f}枚 {top_sign}{top_vs:>7.0f}枚 "
            f"{mid_avg:>9.0f}枚 {mid_sign}{mid_vs:>7.0f}枚 "
            f"{low_avg:>9.0f}枚 {low_sign}{low_vs:>7.0f}枚 "
            f"{result['winner']:<10} | Rho={result['corr']:.2f} p={result['p_value']:.3f} {sig_label}")


def _analyze_condition_by_attributes(
    df_train_cond: pd.DataFrame,
    df_test_cond: pd.DataFrame,
    condition_type: str,
    condition_value: int | str,
    condition_label: str,
    train_attrs: dict,
    stats: WinnerStatistics,
    is_recording_dd: bool = False,
    is_recording_wd: bool = False,
) -> None:
    """条件値 × 訓練属性 での分析を実行（分割単位はATTRIBUTES固定）

    Args:
        df_train_cond, df_test_cond: 条件値でフィルタ済みのDataFrame
        condition_type: 'dd' または 'weekday'
        condition_value: 条件値（DDなら1-20、曜日ならMondayなど）
        condition_label: 出力用ラベル（'D1'など）
        train_attrs: 訓練属性辞書
        stats: WinnerStatistics インスタンス
        is_recording_dd: DD別統計記録フラグ
        is_recording_wd: 曜日別統計記録フラグ
    """
    for attr_col, attr_label in train_attrs.items():
        for split_unit in ATTRIBUTES:
            result = analyze_cross_attribute(df_train_cond, df_test_cond, attr_col, split_unit)
            if result is None:
                continue

            line = format_result_line(condition_label, attr_label, result)
            print(line)

            # 統計カウント（条件に応じて記録）
            if is_recording_dd:
                stats.record_dd_result(attr_label, result, split_unit)
            if is_recording_wd:
                stats.record_wd_result(attr_label, result, split_unit)


def _run_grouped_analysis(
    df_train: pd.DataFrame,
    df_test: pd.DataFrame,
    group_config: dict,
    train_attrs: dict,
    stats: WinnerStatistics,
    period_name: str,
    is_final_period: bool,
) -> None:
    """グループ別（DD or 曜日）に分析を実行

    Args:
        df_train, df_test: 訓練期間・テスト期間のDataFrame
        group_config: グループ設定
            {
                'type': 'dd' or 'weekday',
                'values': イテラブル,
                'jp_labels': {value: ラベル} 辞書（曜日用）,
                'filter_attr': フィルタ属性名
            }
        train_attrs: 訓練属性辞書
        stats: WinnerStatistics インスタンス
        period_name: 訓練期間名
        is_final_period: 最終訓練期間フラグ
    """
    group_type = group_config['type']
    group_values = group_config['values']
    jp_labels = group_config.get('jp_labels', {})
    filter_attr = group_config['filter_attr']

    # セクションヘッダー出力
    _print_section_header(group_type)

    # 統計記録フラグの決定
    is_recording_dd = is_final_period and group_type == 'dd'
    is_recording_wd = is_final_period and group_type == 'weekday'

    for group_val in group_values:
        df_train_grp = df_train[df_train[filter_attr] == group_val].copy()
        df_test_grp = df_test[df_test[filter_attr] == group_val].copy()

        if len(df_train_grp) == 0 or len(df_test_grp) == 0:
            continue

        # グループ値に対応するラベルを取得
        if jp_labels and group_val in jp_labels:
            label = jp_labels[group_val]
        elif group_type == 'dd':
            label = f"D{group_val:<3}"
        else:
            label = group_val

        _analyze_condition_by_attributes(
            df_train_grp,
            df_test_grp,
            condition_type=group_type,
            condition_value=group_val,
            condition_label=label,
            train_attrs=train_attrs,
            stats=stats,
            is_recording_dd=is_recording_dd,
            is_recording_wd=is_recording_wd,
        )


def run_cross_attribute_analysis_comprehensive(db_path: str) -> None:
    """
    複数訓練期間・複数条件値（DD/曜日）での包括的クロス属性分析を実施。

    処理フロー：
    1. DB読み込み、テスト期間データ抽出
    2. 訓練期間ループ：
       - セクション1：DD別（1-20） × 訓練属性 × split_unit（last_digit/weekday）
       - セクション2：曜日別（Monday-Sunday） × 訓練属性 × split_unit（dd/last_digit）
    3. 最終統計：DD別・曜日別の勝者カウント出力
    4. 単一統合ファイルに保存
    """
    print(f"\n相対パフォーマンス分析（クロス属性版、複数訓練期間） (DB: {Path(db_path).stem})")
    print("=" * 160)

    df = load_machine_data(db_path)
    df_test = df[(df['date'] >= TEST_START) & (df['date'] <= TEST_END)].copy()

    if len(df_test) == 0:
        print(f"[SKIP] テスト期間データなし: {db_path}")
        return

    # 統計情報管理（クラス化）
    stats = WinnerStatistics(TRAIN_ATTRS)

    # 訓練期間ループ
    for period_idx, (period_name, start_date, end_date) in enumerate(TRAINING_PERIODS):
        df_train = df[(df['date'] >= start_date) & (df['date'] <= end_date)].copy()

        if len(df_train) == 0:
            print(f"[SKIP] 訓練期間データなし: {period_name}")
            continue

        is_final_period = (period_idx == len(TRAINING_PERIODS) - 1)

        # 最終訓練期間で統計記録を有効化
        if is_final_period:
            stats.enable_recording()

        print(f"\n{'=' * 160}")
        print(f"訓練期間：{period_name} ({start_date} ～ {end_date})")
        print(f"テスト期間：{TEST_START} ～ {TEST_END}")
        print(f"DB：{Path(db_path).stem}")
        print(f"{'=' * 160}")

        # DD別分析
        _run_grouped_analysis(
            df_train,
            df_test,
            group_config={
                'type': 'dd',
                'values': range(1, 21),
                'filter_attr': 'dd',
            },
            train_attrs=TRAIN_ATTRS,
            stats=stats,
            period_name=period_name,
            is_final_period=is_final_period,
        )

        # 曜日別分析
        weekday_labels = {wd: jp for wd, jp in zip(WEEKDAYS, WEEKDAY_JP)}
        _run_grouped_analysis(
            df_train,
            df_test,
            group_config={
                'type': 'weekday',
                'values': WEEKDAYS,
                'jp_labels': weekday_labels,
                'filter_attr': 'weekday',
            },
            train_attrs=TRAIN_ATTRS,
            stats=stats,
            period_name=period_name,
            is_final_period=is_final_period,
        )

    # ========== 最終統計出力 ==========
    print("\n" + "=" * 160)
    stats.print_dd_statistics()
    stats.print_wd_statistics()
    print("=" * 160)
    print("クロス属性分析（複数訓練期間版）完了")
    print("=" * 160)


if __name__ == "__main__":
    # results/フォルダ作成
    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)

    # 出力ファイルパス設定
    output_file = results_dir / "cross_attribute_analysis_comprehensive.txt"

    # 出力をファイルに保存
    old_stdout = sys.stdout
    captured_output = StringIO()
    sys.stdout = captured_output

    try:
        for hall in HALLS:
            db_path = f"../db/{hall}"
            if Path(db_path).exists():
                run_cross_attribute_analysis_comprehensive(db_path)
    finally:
        sys.stdout = old_stdout
        output_content = captured_output.getvalue()
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(output_content)

        print(output_content)
        print(f"\n出力を保存しました: {output_file.absolute()}")
