"""絶対パフォーマンス分析 - テスト期間で最高勝率を達成するグループの特定"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd
from pathlib import Path
from io import StringIO
from loader import load_machine_data


def analyze_absolute_performance(df_train: pd.DataFrame, df_test: pd.DataFrame, condition_type: str, condition_value) -> dict:
    """
    訓練期間の高勝率 vs 低勝率グループが、
    テスト期間でどちらがより高い勝率を達成するかを比較
    """
    # 条件で日を限定
    train_filtered = df_train[df_train[condition_type] == condition_value]
    test_filtered = df_test[df_test[condition_type] == condition_value]

    if len(train_filtered) == 0 or len(test_filtered) == 0:
        return None

    results = {}

    for attr in ['machine_number', 'machine_name', 'last_digit']:
        # 訓練期間でこの属性別の勝率を計算
        train_grouped = train_filtered.groupby(attr).agg({
            'diff_coins_normalized': ['count', lambda x: (x > 0).sum()]
        }).reset_index()
        train_grouped.columns = [attr, 'train_count', 'train_wins']
        train_grouped['train_win_rate'] = train_grouped['train_wins'] / train_grouped['train_count']

        if len(train_grouped) == 0:
            continue

        # 中央値で分割
        median_wr = train_grouped['train_win_rate'].median()
        high_wr = train_grouped[train_grouped['train_win_rate'] >= median_wr]
        low_wr = train_grouped[train_grouped['train_win_rate'] < median_wr]

        # テスト期間での集計
        test_grouped = test_filtered.groupby(attr).agg({
            'diff_coins_normalized': ['count', lambda x: (x > 0).sum()]
        }).reset_index()
        test_grouped.columns = [attr, 'test_count', 'test_wins']
        test_grouped['test_win_rate'] = test_grouped['test_wins'] / test_grouped['test_count']

        # 高勝率グループのテスト期間での平均勝率
        high_test_rates = []
        for _, row in high_wr.iterrows():
            test_match = test_grouped[test_grouped[attr] == row[attr]]
            if len(test_match) > 0:
                high_test_rates.append(test_match.iloc[0]['test_win_rate'])

        # 低勝率グループのテスト期間での平均勝率
        low_test_rates = []
        for _, row in low_wr.iterrows():
            test_match = test_grouped[test_grouped[attr] == row[attr]]
            if len(test_match) > 0:
                low_test_rates.append(test_match.iloc[0]['test_win_rate'])

        high_avg_test_wr = sum(high_test_rates) / len(high_test_rates) if high_test_rates else 0
        low_avg_test_wr = sum(low_test_rates) / len(low_test_rates) if low_test_rates else 0

        # 誰が勝ったか
        winner = "高勝率グループ" if high_avg_test_wr >= low_avg_test_wr else "低勝率グループ"
        winner_rate = max(high_avg_test_wr, low_avg_test_wr)
        loser_rate = min(high_avg_test_wr, low_avg_test_wr)

        results[attr] = {
            'median_wr': median_wr,
            'high_count': len(high_wr),
            'high_test_rate': high_avg_test_wr,
            'low_count': len(low_wr),
            'low_test_rate': low_avg_test_wr,
            'winner': winner,
            'winner_rate': winner_rate,
            'loser_rate': loser_rate,
            'margin': winner_rate - loser_rate,
        }

    return results


def run_absolute_analysis(db_path: str, output_file=None):
    """DD別・曜日別でテスト期間の最高勝率グループを特定"""

    if output_file:
        output_file = open(output_file, 'a', encoding='utf-8')
        import sys
        old_stdout = sys.stdout
        sys.stdout = output_file

    print(f"\n絶対パフォーマンス分析 (DB: {Path(db_path).stem})")
    print("=" * 100)
    print("【テスト期間での最高勝率グループ特定分析】")
    print("訓練期間の高勝率グループと低勝率グループのうち、テスト期間で実際に高い勝率を達成するのはどちらか")
    print("=" * 100)

    df = load_machine_data(db_path)
    df_train = df[(df['date'] >= '2026-02-01') & (df['date'] <= '2026-03-31')].copy()
    df_test = df[(df['date'] >= '2026-04-01') & (df['date'] <= '2026-04-20')].copy()

    # ========== DD別分析 ==========
    print("\nDD別 テスト期間パフォーマンス（最高勝率グループ判定）")
    print("-" * 100)
    print(f"{'DD':<5} {'属性':<12} {'高グループ':<12} {'低グループ':<12} {'勝者':<10} {'勝率':<8} {'マージン':<8}")
    print("-" * 100)

    dd_winner_count = {'machine_number': {'high': 0, 'low': 0},
                       'machine_name': {'high': 0, 'low': 0},
                       'last_digit': {'high': 0, 'low': 0}}

    for dd in range(1, 21):
        result = analyze_absolute_performance(df_train, df_test, 'dd', dd)
        if result is None:
            continue

        for attr in ['machine_number', 'machine_name', 'last_digit']:
            if attr in result:
                r = result[attr]
                print(f"D{dd:<3} {attr:<12} {r['high_test_rate']*100:>6.1f}% ({r['high_count']:>2}) {r['low_test_rate']*100:>6.1f}% ({r['low_count']:>2}) {r['winner']:<10} {r['winner_rate']*100:>6.1f}% {r['margin']*100:>6.1f}%")

                # カウント
                if '高勝率' in r['winner']:
                    dd_winner_count[attr]['high'] += 1
                else:
                    dd_winner_count[attr]['low'] += 1

    # DD別統計
    print("\nDD別 勝者統計:")
    for attr in ['machine_number', 'machine_name', 'last_digit']:
        high_wins = dd_winner_count[attr]['high']
        low_wins = dd_winner_count[attr]['low']
        total = high_wins + low_wins
        if total > 0:
            print(f"  {attr}: 高勝率グループ勝利 {high_wins}/{total}回 ({high_wins/total*100:.1f}%) | 低勝率グループ勝利 {low_wins}/{total}回 ({low_wins/total*100:.1f}%)")

    # ========== 曜日別分析 ==========
    print("\n" + "=" * 100)
    print("曜日別 テスト期間パフォーマンス（最高勝率グループ判定）")
    print("-" * 100)
    print(f"{'曜日':<6} {'属性':<12} {'高グループ':<12} {'低グループ':<12} {'勝者':<10} {'勝率':<8} {'マージン':<8}")
    print("-" * 100)

    weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    weekday_jp = ['月', '火', '水', '木', '金', '土', '日']
    weekday_winner_count = {'machine_number': {'high': 0, 'low': 0},
                            'machine_name': {'high': 0, 'low': 0},
                            'last_digit': {'high': 0, 'low': 0}}

    for weekday, jp in zip(weekdays, weekday_jp):
        result = analyze_absolute_performance(df_train, df_test, 'weekday', weekday)
        if result is None:
            continue

        for attr in ['machine_number', 'machine_name', 'last_digit']:
            if attr in result:
                r = result[attr]
                print(f"{jp}曜   {attr:<12} {r['high_test_rate']*100:>6.1f}% ({r['high_count']:>2}) {r['low_test_rate']*100:>6.1f}% ({r['low_count']:>2}) {r['winner']:<10} {r['winner_rate']*100:>6.1f}% {r['margin']*100:>6.1f}%")

                # カウント
                if '高勝率' in r['winner']:
                    weekday_winner_count[attr]['high'] += 1
                else:
                    weekday_winner_count[attr]['low'] += 1

    # 曜日別統計
    print("\n曜日別 勝者統計:")
    for attr in ['machine_number', 'machine_name', 'last_digit']:
        high_wins = weekday_winner_count[attr]['high']
        low_wins = weekday_winner_count[attr]['low']
        total = high_wins + low_wins
        if total > 0:
            print(f"  {attr}: 高勝率グループ勝利 {high_wins}/{total}回 ({high_wins/total*100:.1f}%) | 低勝率グループ勝利 {low_wins}/{total}回 ({low_wins/total*100:.1f}%)")

    print("\n" + "=" * 100)


if __name__ == "__main__":
    # results/フォルダ作成
    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)

    # 出力ファイルパス設定
    output_file = results_dir / "absolute_performance_analysis.txt"

    # 出力をファイルに保存
    old_stdout = sys.stdout
    captured_output = StringIO()
    sys.stdout = captured_output

    try:
        halls = [
            "マルハンメガシティ2000-蒲田1.db",
            "マルハンメガシティ2000-蒲田7.db"
        ]

        for hall in halls:
            db_path = f"../db/{hall}"
            if Path(db_path).exists():
                run_absolute_analysis(db_path)

        print("\n" + "=" * 100)
        print("絶対パフォーマンス分析完了")
        print("=" * 100)
    finally:
        sys.stdout = old_stdout
        output_content = captured_output.getvalue()
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(output_content)

        print(output_content)
        print(f"\n出力を保存しました: {output_file.absolute()}")
