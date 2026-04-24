"""クロス属性パフォーマンス分析 - 複数訓練期間・複数条件値対応版"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd
from pathlib import Path
from io import StringIO
from loader import load_machine_data
from analysis_base import (
    TRAINING_PERIODS, TEST_START, TEST_END,
    ATTRIBUTES, ATTRIBUTES_JA, WEEKDAYS, WEEKDAY_JP, HALLS,
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


def print_dd_section_header():
    """DD別セクションのヘッダー出力"""
    print(f"\n========== DD別分析 ==========")
    print(f"{'条件':<6} {'訓練属性':<15} {'基準値':<10} "
          f"{'上位G':<10} {'vs':<8} {'中位G':<10} {'vs':<8} {'下位G':<10} {'vs':<8} "
          f"{'勝者':<10} | {'相関':<8} {'p値':<8}")
    print("-" * 150)


def print_weekday_section_header():
    """曜日別セクションのヘッダー出力"""
    print(f"\n========== 曜日別分析 ==========")
    print(f"{'曜日':<6} {'訓練属性':<15} {'基準値':<10} "
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


def run_cross_attribute_analysis_comprehensive(db_path: str) -> None:
    """
    複数訓練期間・複数条件値（DD/曜日）での包括的クロス属性分析を実施。

    処理フロー：
    1. DB読み込み、テスト期間データ抽出
    2. 訓練期間ループ：
       - セクション1：DD別（1-20） × 訓練属性 × split_unit（dd/last_digit/weekday）
       - セクション2：曜日別（Monday-Sunday） × 訓練属性 × split_unit（dd/last_digit/weekday）
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

    # 統計情報用の辞書（訓練属性ごと）
    dd_winner_count = {}
    for attr in TRAIN_ATTRS.values():
        dd_winner_count[attr] = {'上位G': 0, '中間G': 0, '下位G': 0}

    weekday_winner_count = {}
    for attr in TRAIN_ATTRS.values():
        weekday_winner_count[attr] = {'上位G': 0, '中間G': 0, '下位G': 0}

    # 訓練期間ループ
    for period_name, start_date, end_date in TRAINING_PERIODS:
        df_train = df[(df['date'] >= start_date) & (df['date'] <= end_date)].copy()

        if len(df_train) == 0:
            print(f"[SKIP] 訓練期間データなし: {period_name}")
            continue

        print(f"\n{'=' * 160}")
        print(f"訓練期間：{period_name} ({start_date} ～ {end_date})")
        print(f"テスト期間：{TEST_START} ～ {TEST_END}")
        print(f"DB：{Path(db_path).stem}")
        print(f"{'=' * 160}")

        # ========== DD別分析 ==========
        print_dd_section_header()

        for dd in range(1, 21):
            df_train_dd = df_train[df_train['dd'] == dd].copy()
            df_test_dd = df_test[df_test['dd'] == dd].copy()

            if len(df_train_dd) == 0 or len(df_test_dd) == 0:
                continue

            for attr_col, attr_label in TRAIN_ATTRS.items():
                # DD別分析では last_digit または weekday で分割（dd では3値未満になるため）
                for split_unit in ['last_digit', 'weekday']:
                    result = analyze_cross_attribute(df_train_dd, df_test_dd, attr_col, split_unit)
                    if result is None:
                        continue

                    line = format_result_line(f"D{dd:<3}", attr_label, result)
                    print(line)

                    # 統計カウント（最後の訓練期間のみ、last_digit split_unit のみ集計）
                    if period_name == TRAINING_PERIODS[-1][0] and split_unit == 'last_digit':
                        dd_winner_count[attr_label][result['winner']] += 1

        # ========== 曜日別分析 ==========
        print_weekday_section_header()

        for weekday, jp in zip(WEEKDAYS, WEEKDAY_JP):
            df_train_wd = df_train[df_train['weekday'] == weekday].copy()
            df_test_wd = df_test[df_test['weekday'] == weekday].copy()

            if len(df_train_wd) == 0 or len(df_test_wd) == 0:
                continue

            for attr_col, attr_label in TRAIN_ATTRS.items():
                # 曜日別分析では dd または last_digit で分割（weekday では1値になるため）
                for split_unit in ['dd', 'last_digit']:
                    result = analyze_cross_attribute(df_train_wd, df_test_wd, attr_col, split_unit)
                    if result is None:
                        continue

                    line = format_result_line(f"{jp}曜  ", attr_label, result)
                    print(line)

                    # 統計カウント（最後の訓練期間のみ、dd split_unit のみ集計）
                    if period_name == TRAINING_PERIODS[-1][0] and split_unit == 'dd':
                        weekday_winner_count[attr_label][result['winner']] += 1

    # ========== 最終統計出力 ==========
    print("\n" + "=" * 160)
    print("DD別 勝者統計（最終訓練期間、split_unit='dd'）:")
    for attr_label in TRAIN_ATTRS.values():
        top = dd_winner_count[attr_label]['上位G']
        mid = dd_winner_count[attr_label]['中間G']
        low = dd_winner_count[attr_label]['下位G']
        total = top + mid + low
        if total > 0:
            print(f"  {attr_label:<10}: 上位G勝利 {top:>2}/20回 ({top/20*100:>5.1f}%) | "
                  f"中間G勝利 {mid:>2}/20回 ({mid/20*100:>5.1f}%) | "
                  f"下位G勝利 {low:>2}/20回 ({low/20*100:>5.1f}%)")

    print("\n曜日別 勝者統計（最終訓練期間、split_unit='weekday'）:")
    for attr_label in TRAIN_ATTRS.values():
        top = weekday_winner_count[attr_label]['上位G']
        mid = weekday_winner_count[attr_label]['中間G']
        low = weekday_winner_count[attr_label]['下位G']
        total = top + mid + low
        if total > 0:
            print(f"  {attr_label:<10}: 上位G勝利 {top:>2}/7回 ({top/7*100:>5.1f}%) | "
                  f"中間G勝利 {mid:>2}/7回 ({mid/7*100:>5.1f}%) | "
                  f"下位G勝利 {low:>2}/7回 ({low/7*100:>5.1f}%)")

    print("\n" + "=" * 160)
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
