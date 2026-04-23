"""相対パフォーマンス分析 - 平均差枚ベース（3グループ版）"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd
from pathlib import Path
from io import StringIO
from loader import load_machine_data
from analysis_base import *
from analysis_base import analyze_relative_performance


def run_multi_period_coin_diff_triple_analysis(db_path: str):
    """複数訓練期間での平均差枚ベース分析実施（3グループ版）"""

    print(f"\n相対パフォーマンス分析（平均差枚ベース、3グループ版、複数訓練期間） (DB: {Path(db_path).stem})")
    print("=" * 160)

    df = load_machine_data(db_path)
    df_test = df[(df['date'] >= TEST_START) & (df['date'] <= TEST_END)].copy()

    # 統計情報用の辞書
    dd_winner_count = {}
    for attr in ATTRIBUTES:
        dd_winner_count[attr] = {'top': 0, 'mid': 0, 'low': 0}

    for period_name, start_date, end_date in TRAINING_PERIODS:
        df_train = df[(df['date'] >= start_date) & (df['date'] <= end_date)].copy()

        print_header(db_path, period_name, start_date, end_date)

        # ========== DD別分析 ==========
        print_dd_section_triple(period_name)

        for dd in range(1, 21):
            for attr in ATTRIBUTES:
                result = analyze_relative_performance(df_train, df_test, 'dd', dd, attr, metric='coin_diff')
                if result:
                    r = result
                    # 結果行を出力（3グループ対応 + スピアマン相関）
                    condition_label = f"D{dd:<3}"
                    attr_label = f"{ATTRIBUTES_JA[attr]:<15}"
                    top_sign = "+" if r['top_relative'] >= 0 else ""
                    mid_sign = "+" if r['mid_relative'] >= 0 else ""
                    low_sign = "+" if r['low_relative'] >= 0 else ""
                    sig_label = "(*)" if r['p_value'] < 0.05 else ""

                    print(f"{condition_label:<5} {attr_label} {r['condition_avg']:>6.1f}% "
                          f"{r['top_avg']:>6.1f}% {top_sign}{r['top_relative']:>7.1f}% "
                          f"{r['mid_avg']:>6.1f}% {mid_sign}{r['mid_relative']:>7.1f}% "
                          f"{r['low_avg']:>6.1f}% {low_sign}{r['low_relative']:>7.1f}% "
                          f"{r['winner']:<12} | Rho={r['corr']:.2f} p={r['p_value']:.3f} {sig_label}")

                    # 統計カウント（最後の訓練期間のみ）
                    if period_name == TRAINING_PERIODS[-1][0]:
                        if r['winner'] == "上位G":
                            dd_winner_count[attr]['top'] += 1
                        elif r['winner'] == "中間G":
                            dd_winner_count[attr]['mid'] += 1
                        else:
                            dd_winner_count[attr]['low'] += 1

        # ========== 曜日別分析 ==========
        print_weekday_section_triple(period_name)

        for weekday, jp in zip(WEEKDAYS, WEEKDAY_JP):
            for attr in ATTRIBUTES:
                result = analyze_relative_performance(df_train, df_test, 'weekday', weekday, attr, metric='coin_diff')
                if result:
                    r = result
                    attr_label = f"{ATTRIBUTES_JA[attr]:<15}"
                    top_sign = "+" if r['top_relative'] >= 0 else ""
                    mid_sign = "+" if r['mid_relative'] >= 0 else ""
                    low_sign = "+" if r['low_relative'] >= 0 else ""
                    sig_label = "(*)" if r['p_value'] < 0.05 else ""

                    print(f"{jp}曜   {attr_label} {r['condition_avg']:>6.1f}% "
                          f"{r['top_avg']:>6.1f}% {top_sign}{r['top_relative']:>7.1f}% "
                          f"{r['mid_avg']:>6.1f}% {mid_sign}{r['mid_relative']:>7.1f}% "
                          f"{r['low_avg']:>6.1f}% {low_sign}{r['low_relative']:>7.1f}% "
                          f"{r['winner']:<12} | Rho={r['corr']:.2f} p={r['p_value']:.3f} {sig_label}")

    # 最終統計
    print("\n" + "=" * 160)
    print("DD別 勝者統計:")
    for attr in ATTRIBUTES:
        top = dd_winner_count[attr]['top']
        mid = dd_winner_count[attr]['mid']
        low = dd_winner_count[attr]['low']
        total = top + mid + low
        if total > 0:
            print(f"  {attr}: 上位G勝利 {top}/20回 ({top/20*100:.1f}%) | "
                  f"中間G勝利 {mid}/20回 ({mid/20*100:.1f}%) | "
                  f"下位G勝利 {low}/20回 ({low/20*100:.1f}%)")

    print("\n" + "=" * 160)
    print("平均差枚ベース分析（3グループ版）完了")
    print("=" * 160)


if __name__ == "__main__":
    # results/フォルダ作成
    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)

    # 出力ファイルパス設定
    output_file = results_dir / "relative_performance_analysis_coin_diff_triple.txt"

    # 出力をファイルに保存
    old_stdout = sys.stdout
    captured_output = StringIO()
    sys.stdout = captured_output

    try:
        for hall in HALLS:
            db_path = f"../db/{hall}"
            if Path(db_path).exists():
                run_multi_period_coin_diff_triple_analysis(db_path)
    finally:
        sys.stdout = old_stdout
        output_content = captured_output.getvalue()
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(output_content)

        print(output_content)
        print(f"\n出力を保存しました: {output_file.absolute()}")
