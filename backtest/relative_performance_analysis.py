"""相対パフォーマンス分析 - 条件別平均との比較"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd
from pathlib import Path
from loader import load_machine_data


def analyze_relative_performance(df_train: pd.DataFrame, df_test: pd.DataFrame, condition_type: str, condition_value) -> dict:
    """
    訓練期間の高勝率 vs 低勝率グループが、
    テスト期間で「その条件（DD/曜日）の平均勝率」と比べてどのくらい上回るか／下回るかを比較
    """
    # 条件で日を限定
    train_filtered = df_train[df_train[condition_type] == condition_value]
    test_filtered = df_test[df_test[condition_type] == condition_value]

    if len(train_filtered) == 0 or len(test_filtered) == 0:
        return None

    # テスト期間での条件全体の平均勝率を計算
    condition_avg_wins = (test_filtered['diff_coins_normalized'] > 0).sum()
    condition_total = len(test_filtered)
    condition_avg_wr = condition_avg_wins / condition_total if condition_total > 0 else 0

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

        # 高勝率グループのテスト期間での平均勝率と相対値
        high_test_rates = []
        for _, row in high_wr.iterrows():
            test_match = test_grouped[test_grouped[attr] == row[attr]]
            if len(test_match) > 0:
                high_test_rates.append(test_match.iloc[0]['test_win_rate'])

        # 低勝率グループのテスト期間での平均勝率と相対値
        low_test_rates = []
        for _, row in low_wr.iterrows():
            test_match = test_grouped[test_grouped[attr] == row[attr]]
            if len(test_match) > 0:
                low_test_rates.append(test_match.iloc[0]['test_win_rate'])

        high_avg_test_wr = sum(high_test_rates) / len(high_test_rates) if high_test_rates else 0
        low_avg_test_wr = sum(low_test_rates) / len(low_test_rates) if low_test_rates else 0

        # 条件平均との相対値
        high_relative = high_avg_test_wr - condition_avg_wr
        low_relative = low_avg_test_wr - condition_avg_wr

        # 誰が「条件平均を最も上回っているか」で判定
        winner = "高勝率グループ" if high_relative >= low_relative else "低勝率グループ"
        winner_relative = max(high_relative, low_relative)
        loser_relative = min(high_relative, low_relative)

        results[attr] = {
            'condition_avg_wr': condition_avg_wr,
            'high_test_rate': high_avg_test_wr,
            'high_relative': high_relative,  # 平均との差
            'high_count': len(high_wr),
            'low_test_rate': low_avg_test_wr,
            'low_relative': low_relative,  # 平均との差
            'low_count': len(low_wr),
            'winner': winner,
            'winner_relative': winner_relative,
            'loser_relative': loser_relative,
        }

    return results


def run_relative_analysis(db_path: str):
    """DD別・曜日別で条件平均との相対パフォーマンスを比較"""

    print(f"\n相対パフォーマンス分析 (DB: {Path(db_path).stem})")
    print("=" * 120)
    print("【条件別平均勝率との相対比較】")
    print("各DD/曜日の全体平均勝率から、高勝率グループと低勝率グループがどのくらい上回っているかを比較")
    print("=" * 120)

    df = load_machine_data(db_path)
    df_train = df[(df['date'] >= '2026-02-01') & (df['date'] <= '2026-03-31')].copy()
    df_test = df[(df['date'] >= '2026-04-01') & (df['date'] <= '2026-04-20')].copy()

    # ========== DD別分析 ==========
    print("\nDD別 相対パフォーマンス（条件平均との比較）")
    print("-" * 120)
    print(f"{'DD':<5} {'属性':<12} {'条件平均':<8} {'高グループ':<12} {'vs平均':<10} {'低グループ':<12} {'vs平均':<10} {'勝者':<10}")
    print("-" * 120)

    for dd in range(1, 21):
        result = analyze_relative_performance(df_train, df_test, 'dd', dd)
        if result is None:
            continue

        for attr in ['machine_number', 'machine_name', 'last_digit']:
            if attr in result:
                r = result[attr]
                high_sign = "+" if r['high_relative'] >= 0 else ""
                low_sign = "+" if r['low_relative'] >= 0 else ""
                print(f"D{dd:<3} {attr:<12} {r['condition_avg_wr']*100:>6.1f}% {r['high_test_rate']*100:>6.1f}% ({r['high_count']:>2}) {high_sign}{r['high_relative']*100:>7.1f}% {r['low_test_rate']*100:>6.1f}% ({r['low_count']:>2}) {low_sign}{r['low_relative']*100:>7.1f}% {r['winner']:<10}")

    # ========== 曜日別分析 ==========
    print("\n" + "=" * 120)
    print("曜日別 相対パフォーマンス（条件平均との比較）")
    print("-" * 120)
    print(f"{'曜日':<6} {'属性':<12} {'条件平均':<8} {'高グループ':<12} {'vs平均':<10} {'低グループ':<12} {'vs平均':<10} {'勝者':<10}")
    print("-" * 120)

    weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    weekday_jp = ['月', '火', '水', '木', '金', '土', '日']

    for weekday, jp in zip(weekdays, weekday_jp):
        result = analyze_relative_performance(df_train, df_test, 'weekday', weekday)
        if result is None:
            continue

        for attr in ['machine_number', 'machine_name', 'last_digit']:
            if attr in result:
                r = result[attr]
                high_sign = "+" if r['high_relative'] >= 0 else ""
                low_sign = "+" if r['low_relative'] >= 0 else ""
                print(f"{jp}曜   {attr:<12} {r['condition_avg_wr']*100:>6.1f}% {r['high_test_rate']*100:>6.1f}% ({r['high_count']:>2}) {high_sign}{r['high_relative']*100:>7.1f}% {r['low_test_rate']*100:>6.1f}% ({r['low_count']:>2}) {low_sign}{r['low_relative']*100:>7.1f}% {r['winner']:<10}")

    print("\n" + "=" * 120)


if __name__ == "__main__":
    halls = [
        "マルハンメガシティ2000-蒲田1.db",
        "マルハンメガシティ2000-蒲田7.db"
    ]

    for hall in halls:
        db_path = f"../db/{hall}"
        if Path(db_path).exists():
            run_relative_analysis(db_path)

    print("\n" + "=" * 120)
    print("相対パフォーマンス分析完了")
    print("=" * 120)
