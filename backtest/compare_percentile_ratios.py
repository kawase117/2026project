"""比率最適化分析 - 複数分割比率の系統的テスト"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd
from pathlib import Path
from io import StringIO
from loader import load_machine_data
from analysis_base import (
    TRAINING_PERIODS, TEST_START, TEST_END, ATTRIBUTES, ATTRIBUTES_JA,
    WEEKDAYS, WEEKDAY_JP, HALLS, PERCENTILE_CANDIDATES,
    split_groups_triple_custom, load_and_split_data, print_header,
    print_dd_section_triple, print_weekday_section_triple,
    map_groups_by_attr, aggregate_group_metrics, calculate_rank_correlation
)


# ========== カスタムパーセンタイル対応版 analyze_cross_attribute ==========

def analyze_cross_attribute(
    df_train: pd.DataFrame,
    df_test: pd.DataFrame,
    split_type: str,
    split_value,
    attribute: str,
    top_pct: float = 36,
    mid_pct: float = 28,
    low_pct: float = 36,
) -> dict | None:
    """
    カスタムパーセンタイル対応版クロス属性分析

    Args:
        df_train, df_test: 訓練・テスト期間のデータフレーム
        split_type: グループ分割タイプ（'dd', 'weekday'など）
        split_value: グループ分割値（DD値、曜日など）
        attribute: 分割属性（'machine_number', 'machine_name', 'last_digit'）
        top_pct, mid_pct, low_pct: パーセンタイル比率（デフォルト36/28/36）

    Returns:
        分析結果dict or None
    """
    # 条件値でフィルタ
    train_filtered = df_train[df_train[split_type] == split_value].copy()
    test_filtered = df_test[df_test[split_type] == split_value].copy()

    if len(train_filtered) == 0 or len(test_filtered) == 0:
        return None

    # テスト期間での条件全体の平均差枚
    condition_avg = test_filtered['diff_coins_normalized'].mean() if len(test_filtered) > 0 else 0

    # 訓練期間で属性別の差枚平均を計算
    train_grouped = train_filtered.groupby(attribute).agg({
        'diff_coins_normalized': ['mean']
    }).reset_index()
    train_grouped.columns = [attribute, 'train_avg_coin']

    if len(train_grouped) < 3:  # 3グループに分割できない場合
        return None

    # カスタム比率でグループ分割
    top_g, mid_g, low_g = split_groups_triple_custom(
        train_grouped, 'train_avg_coin',
        top_pct, mid_pct, low_pct
    )

    if top_g is None or mid_g is None or low_g is None:
        return None

    # テスト期間での集計
    test_grouped = test_filtered.groupby(attribute).agg({
        'diff_coins_normalized': ['mean', lambda x: (x > 0).sum()],
        'games_normalized': ['count']
    }).reset_index()
    test_grouped.columns = [attribute, 'test_avg_coin', 'test_wins', 'test_count']
    test_grouped['test_win_rate'] = test_grouped['test_wins'] / test_grouped['test_count']

    # グループ別のテスト期間での平均差枚と勝率を計算
    def get_group_test_metrics(group_df):
        coins = []
        rates = []
        for _, row in group_df.iterrows():
            test_match = test_grouped[test_grouped[attribute] == row[attribute]]
            if len(test_match) > 0:
                coins.append(test_match.iloc[0]['test_avg_coin'])
                rates.append(test_match.iloc[0]['test_win_rate'])
        return coins, rates

    top_test_coins, top_test_rates = get_group_test_metrics(top_g)
    mid_test_coins, mid_test_rates = get_group_test_metrics(mid_g)
    low_test_coins, low_test_rates = get_group_test_metrics(low_g)

    top_avg = sum(top_test_coins) / len(top_test_coins) if top_test_coins else 0
    mid_avg = sum(mid_test_coins) / len(mid_test_coins) if mid_test_coins else 0
    low_avg = sum(low_test_coins) / len(low_test_coins) if low_test_coins else 0

    top_relative = top_avg - condition_avg
    mid_relative = mid_avg - condition_avg
    low_relative = low_avg - condition_avg

    # 最高値のグループを勝者とする
    max_relative = max(top_relative, mid_relative, low_relative)
    if max_relative == top_relative:
        winner = "上位G"
    elif max_relative == mid_relative:
        winner = "中間G"
    else:
        winner = "下位G"

    # スピアマン相関計算（訓練vs テスト）
    from scipy.stats import spearmanr

    train_vals = [
        train_grouped[train_grouped[attribute].isin(top_g[attribute])]['train_avg_coin'].mean(),
        train_grouped[train_grouped[attribute].isin(mid_g[attribute])]['train_avg_coin'].mean(),
        train_grouped[train_grouped[attribute].isin(low_g[attribute])]['train_avg_coin'].mean(),
    ]
    test_vals = [top_avg, mid_avg, low_avg]

    corr, p_value = spearmanr(train_vals, test_vals)

    return {
        'condition_avg': condition_avg,
        'top_avg': top_avg,
        'top_relative': top_relative,
        'top_count': len(top_g),
        'mid_avg': mid_avg,
        'mid_relative': mid_relative,
        'mid_count': len(mid_g),
        'low_avg': low_avg,
        'low_relative': low_relative,
        'low_count': len(low_g),
        'winner': winner,
        'max_relative': max_relative,
        'corr': float(corr) if not pd.isna(corr) else 0.0,
        'p_value': float(p_value) if not pd.isna(p_value) else 1.0,
    }


def run_percentile_comparison_analysis(db_path: str):
    """複数分割比率での相対パフォーマンス分析（全比率テスト）"""

    print(f"\n分割比率最適化分析 (DB: {Path(db_path).stem})")
    print("=" * 180)

    df = load_machine_data(db_path)
    df_test = df[(df['date'] >= TEST_START) & (df['date'] <= TEST_END)].copy()

    # 結果保存用：比率 → [訓練期間1, 訓練期間2, 訓練期間3] の構造
    ratio_results = {}  # {(top%, mid%, low%): {'dd': {...}, 'wd': {...}}}

    for top_pct, mid_pct, low_pct in PERCENTILE_CANDIDATES:
        ratio_name = f"{top_pct}/{mid_pct}/{low_pct}"
        print(f"\n{'='*180}")
        print(f"分割比率: {ratio_name}")
        print(f"{'='*180}")

        ratio_results[ratio_name] = {}

        # 訓練期間ループ
        for period_name, start_date, end_date in TRAINING_PERIODS:
            df_train = df[(df['date'] >= start_date) & (df['date'] <= end_date)].copy()

            print_header(db_path, period_name, start_date, end_date)

            # ========== DD別分析 ==========
            print_dd_section_triple(period_name)

            dd_results = {}  # {dd: {attr: result_dict}}

            for dd in range(1, 21):
                dd_results[dd] = {}
                for attr in ATTRIBUTES:
                    result = analyze_cross_attribute(
                        df_train, df_test, 'dd', dd, attr,
                        top_pct=top_pct, mid_pct=mid_pct, low_pct=low_pct
                    )
                    if result:
                        dd_results[dd][attr] = result
                        r = result
                        condition_label = f"D{dd:<3}"
                        attr_label = f"{ATTRIBUTES_JA[attr]:<15}"
                        top_sign = "+" if r['top_relative'] >= 0 else ""
                        mid_sign = "+" if r['mid_relative'] >= 0 else ""
                        low_sign = "+" if r['low_relative'] >= 0 else ""
                        sig_label = "(*)" if r['p_value'] < 0.05 else ""

                        print(f"{condition_label:<5} {attr_label} {r['condition_avg']:>9.1f} "
                              f"{r['top_avg']:>9.1f} {top_sign}{r['top_relative']:>8.1f} "
                              f"{r['mid_avg']:>9.1f} {mid_sign}{r['mid_relative']:>8.1f} "
                              f"{r['low_avg']:>9.1f} {low_sign}{r['low_relative']:>8.1f} "
                              f"{r['winner']:<12} | Rho={r['corr']:.2f} p={r['p_value']:.3f} {sig_label}")

            ratio_results[ratio_name]['dd'] = dd_results

            # ========== 曜日別分析 ==========
            print_weekday_section_triple(period_name)

            wd_results = {}  # {weekday: {attr: result_dict}}

            for weekday, jp in zip(WEEKDAYS, WEEKDAY_JP):
                wd_results[weekday] = {}
                for attr in ATTRIBUTES:
                    result = analyze_cross_attribute(
                        df_train, df_test, 'weekday', weekday, attr,
                        top_pct=top_pct, mid_pct=mid_pct, low_pct=low_pct
                    )
                    if result:
                        wd_results[weekday][attr] = result
                        r = result
                        attr_label = f"{ATTRIBUTES_JA[attr]:<15}"
                        top_sign = "+" if r['top_relative'] >= 0 else ""
                        mid_sign = "+" if r['mid_relative'] >= 0 else ""
                        low_sign = "+" if r['low_relative'] >= 0 else ""
                        sig_label = "(*)" if r['p_value'] < 0.05 else ""

                        print(f"{jp}曜   {attr_label} {r['condition_avg']*100:>6.1f}% "
                              f"{r['top_avg']*100:>6.1f}% {top_sign}{r['top_relative']*100:>7.1f}% "
                              f"{r['mid_avg']*100:>6.1f}% {mid_sign}{r['mid_relative']*100:>7.1f}% "
                              f"{r['low_avg']*100:>6.1f}% {low_sign}{r['low_relative']*100:>7.1f}% "
                              f"{r['winner']:<12} | Rho={r['corr']:.2f} p={r['p_value']:.3f} {sig_label}")

            ratio_results[ratio_name]['wd'] = wd_results

    # TODO: 最終統計と比率比較マトリクスの出力

    print(f"\n{'='*180}")
    print(f"分割比率最適化分析 完了")
    print(f"{'='*180}")


if __name__ == "__main__":
    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)

    output_file = results_dir / "compare_percentile_ratios.txt"

    old_stdout = sys.stdout
    captured_output = StringIO()
    sys.stdout = captured_output

    try:
        for hall in HALLS:
            db_path = f"../db/{hall}"
            if Path(db_path).exists():
                run_percentile_comparison_analysis(db_path)
    finally:
        sys.stdout = old_stdout
        output_content = captured_output.getvalue()
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(output_content)

        print(output_content)
        print(f"\n出力を保存しました: {output_file.absolute()}")
