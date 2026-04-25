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
    print_dd_section_triple, print_weekday_section_triple
)
from cross_attribute_performance_analysis import analyze_cross_attribute


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

        # TODO: 訓練期間ループ、DD別・曜日別分析の実装

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
