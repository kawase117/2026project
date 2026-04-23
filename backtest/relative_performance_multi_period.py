"""相対パフォーマンス分析 - 6月・3月・1月の3訓練期間での比較"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd
from pathlib import Path
from io import StringIO
from loader import load_machine_data


def analyze_relative_performance(df_train: pd.DataFrame, df_test: pd.DataFrame, condition_type: str, condition_value, attr: str) -> dict:
    """条件別平均との相対パフォーマンスを分析"""

    train_filtered = df_train[df_train[condition_type] == condition_value]
    test_filtered = df_test[df_test[condition_type] == condition_value]

    if len(train_filtered) == 0 or len(test_filtered) == 0:
        return None

    # テスト期間での条件全体の平均勝率
    condition_avg_wr = (test_filtered['diff_coins_normalized'] > 0).sum() / len(test_filtered) if len(test_filtered) > 0 else 0

    # 訓練期間でこの属性別の勝率を計算
    train_grouped = train_filtered.groupby(attr).agg({
        'diff_coins_normalized': ['count', lambda x: (x > 0).sum()]
    }).reset_index()
    train_grouped.columns = [attr, 'train_count', 'train_wins']
    train_grouped['train_win_rate'] = train_grouped['train_wins'] / train_grouped['train_count']

    if len(train_grouped) == 0:
        return None

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

    # グループ別のテスト期間での平均勝率と相対値
    high_test_rates = []
    for _, row in high_wr.iterrows():
        test_match = test_grouped[test_grouped[attr] == row[attr]]
        if len(test_match) > 0:
            high_test_rates.append(test_match.iloc[0]['test_win_rate'])

    low_test_rates = []
    for _, row in low_wr.iterrows():
        test_match = test_grouped[test_grouped[attr] == row[attr]]
        if len(test_match) > 0:
            low_test_rates.append(test_match.iloc[0]['test_win_rate'])

    high_avg_wr = sum(high_test_rates) / len(high_test_rates) if high_test_rates else 0
    low_avg_wr = sum(low_test_rates) / len(low_test_rates) if low_test_rates else 0

    high_relative = high_avg_wr - condition_avg_wr
    low_relative = low_avg_wr - condition_avg_wr

    return {
        'condition_avg_wr': condition_avg_wr,
        'high_test_rate': high_avg_wr,
        'high_relative': high_relative,
        'high_count': len(high_wr),
        'low_test_rate': low_avg_wr,
        'low_relative': low_relative,
        'low_count': len(low_wr),
        'winner': "高勝率G" if high_relative >= low_relative else "低勝率G",
        'winner_relative': max(high_relative, low_relative),
    }


def analyze_machine_number_win_loss(df_train: pd.DataFrame, df_test: pd.DataFrame, condition_type: str, condition_value) -> dict:
    """1ヶ月用：訓練期間で勝った台がテスト期間でも勝つか（勝敗再現性）"""

    train_filtered = df_train[df_train[condition_type] == condition_value]
    test_filtered = df_test[df_test[condition_type] == condition_value]

    if len(train_filtered) == 0 or len(test_filtered) == 0:
        return None

    # 訓練期間で各台の勝敗を判定
    train_machines = train_filtered.groupby('machine_number').agg({
        'diff_coins_normalized': lambda x: (x > 0).sum() > 0  # 1回でも勝ったか
    }).reset_index()
    train_machines.columns = ['machine_number', 'trained_won']

    winning_machines = train_machines[train_machines['trained_won'] == True]['machine_number'].tolist()
    losing_machines = train_machines[train_machines['trained_won'] == False]['machine_number'].tolist()

    # テスト期間で同じ台が勝つかどうかを確認
    test_machines = test_filtered.groupby('machine_number').agg({
        'diff_coins_normalized': lambda x: (x > 0).sum() > 0
    }).reset_index()
    test_machines.columns = ['machine_number', 'test_won']

    # 再現率を計算
    winning_reproduced = 0
    for m in winning_machines:
        if m in test_machines[test_machines['test_won'] == True]['machine_number'].values:
            winning_reproduced += 1

    losing_reproduced = 0
    for m in losing_machines:
        if m in test_machines[test_machines['test_won'] == True]['machine_number'].values:
            losing_reproduced += 1

    if len(winning_machines) == 0 or len(losing_machines) == 0:
        return None

    return {
        'winning_count': len(winning_machines),
        'winning_reproduced': winning_reproduced,
        'winning_rate': winning_reproduced / len(winning_machines),
        'losing_count': len(losing_machines),
        'losing_reproduced': losing_reproduced,
        'losing_rate': losing_reproduced / len(losing_machines),
        'winner': "訓練期間勝者" if winning_reproduced / len(winning_machines) >= losing_reproduced / len(losing_machines) else "訓練期間敗者",
    }


def run_multi_period_analysis(db_path: str):
    """6月・3月・1月の3訓練期間で相対パフォーマンス分析を実施"""

    print(f"\n相対パフォーマンス分析（複数訓練期間） (DB: {Path(db_path).stem})")
    print("=" * 140)

    df = load_machine_data(db_path)
    df_test = df[(df['date'] >= '2026-04-01') & (df['date'] <= '2026-04-20')].copy()

    # 3つの訓練期間
    training_periods = [
        ('6月', '2025-10-01', '2026-03-31'),
        ('3月', '2026-01-01', '2026-03-31'),
        ('1月', '2026-03-01', '2026-03-31'),
    ]

    for period_name, start_date, end_date in training_periods:
        df_train = df[(df['date'] >= start_date) & (df['date'] <= end_date)].copy()

        print(f"\n{'=' * 140}")
        print(f"訓練期間：{period_name} ({start_date} ～ {end_date})")
        print(f"テスト期間：2026-04-01 ～ 2026-04-20")
        print(f"{'=' * 140}")

        # ========== DD別分析 ==========
        print(f"\nDD別 相対パフォーマンス（{period_name}訓練）")
        print("-" * 140)
        print(f"{'DD':<5} {'属性':<15} {'基準':<8} {'高G':<12} {'vs基準':<10} {'低G':<12} {'vs基準':<10} {'勝者':<12}")
        print("-" * 140)

        for dd in range(1, 21):
            # 機械番号
            result = analyze_relative_performance(df_train, df_test, 'dd', dd, 'machine_number')
            if result:
                r = result
                print(f"D{dd:<3} {'machine_number':<15} {r['condition_avg_wr']*100:>6.1f}% {r['high_test_rate']*100:>6.1f}% {r['high_relative']*100:>8.1f}% {r['low_test_rate']*100:>6.1f}% {r['low_relative']*100:>8.1f}% {r['winner']:<12}")

            # 特殊：1月訓練の機械番号は勝敗再現性で表示
            if period_name == '1月':
                result_wl = analyze_machine_number_win_loss(df_train, df_test, 'dd', dd)
                if result_wl:
                    r = result_wl
                    print(f"     {'  → 勝敗再現性':<15} {'':<8} {r['winning_rate']*100:>6.1f}% ({r['winning_reproduced']}/{r['winning_count']}) vs {r['losing_rate']*100:>6.1f}% ({r['losing_reproduced']}/{r['losing_count']}) {r['winner']:<12}")

        # 機種名
        print(f"\nDD別 機種名")
        print("-" * 140)
        for dd in range(1, 21):
            result = analyze_relative_performance(df_train, df_test, 'dd', dd, 'machine_name')
            if result:
                r = result
                print(f"D{dd:<3} {'machine_name':<15} {r['condition_avg_wr']*100:>6.1f}% {r['high_test_rate']*100:>6.1f}% {r['high_relative']*100:>8.1f}% {r['low_test_rate']*100:>6.1f}% {r['low_relative']*100:>8.1f}% {r['winner']:<12}")

        # 台末尾
        print(f"\nDD別 台末尾")
        print("-" * 140)
        for dd in range(1, 21):
            result = analyze_relative_performance(df_train, df_test, 'dd', dd, 'last_digit')
            if result:
                r = result
                print(f"D{dd:<3} {'last_digit':<15} {r['condition_avg_wr']*100:>6.1f}% {r['high_test_rate']*100:>6.1f}% {r['high_relative']*100:>8.1f}% {r['low_test_rate']*100:>6.1f}% {r['low_relative']*100:>8.1f}% {r['winner']:<12}")

        # ========== 曜日別分析 ==========
        print(f"\n{'=' * 140}")
        print(f"曜日別 相対パフォーマンス（{period_name}訓練）")
        print("-" * 140)
        print(f"{'曜日':<6} {'属性':<15} {'基準':<8} {'高G':<12} {'vs基準':<10} {'低G':<12} {'vs基準':<10} {'勝者':<12}")
        print("-" * 140)

        weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        weekday_jp = ['月', '火', '水', '木', '金', '土', '日']

        for weekday, jp in zip(weekdays, weekday_jp):
            # 機械番号
            result = analyze_relative_performance(df_train, df_test, 'weekday', weekday, 'machine_number')
            if result:
                r = result
                print(f"{jp}曜   {'machine_number':<15} {r['condition_avg_wr']*100:>6.1f}% {r['high_test_rate']*100:>6.1f}% {r['high_relative']*100:>8.1f}% {r['low_test_rate']*100:>6.1f}% {r['low_relative']*100:>8.1f}% {r['winner']:<12}")

            # 1月訓練の機械番号は勝敗再現性
            if period_name == '1月':
                result_wl = analyze_machine_number_win_loss(df_train, df_test, 'weekday', weekday)
                if result_wl:
                    r = result_wl
                    print(f"     {'  → 勝敗再現性':<15} {'':<8} {r['winning_rate']*100:>6.1f}% ({r['winning_reproduced']}/{r['winning_count']}) vs {r['losing_rate']*100:>6.1f}% ({r['losing_reproduced']}/{r['losing_count']}) {r['winner']:<12}")

        # 機種名
        print(f"\n曜日別 機種名")
        print("-" * 140)
        for weekday, jp in zip(weekdays, weekday_jp):
            result = analyze_relative_performance(df_train, df_test, 'weekday', weekday, 'machine_name')
            if result:
                r = result
                print(f"{jp}曜   {'machine_name':<15} {r['condition_avg_wr']*100:>6.1f}% {r['high_test_rate']*100:>6.1f}% {r['high_relative']*100:>8.1f}% {r['low_test_rate']*100:>6.1f}% {r['low_relative']*100:>8.1f}% {r['winner']:<12}")

        # 台末尾
        print(f"\n曜日別 台末尾")
        print("-" * 140)
        for weekday, jp in zip(weekdays, weekday_jp):
            result = analyze_relative_performance(df_train, df_test, 'weekday', weekday, 'last_digit')
            if result:
                r = result
                print(f"{jp}曜   {'last_digit':<15} {r['condition_avg_wr']*100:>6.1f}% {r['high_test_rate']*100:>6.1f}% {r['high_relative']*100:>8.1f}% {r['low_test_rate']*100:>6.1f}% {r['low_relative']*100:>8.1f}% {r['winner']:<12}")

    print("\n" + "=" * 140)
    print("複数訓練期間の相対パフォーマンス分析完了")
    print("=" * 140)


if __name__ == "__main__":
    # results/フォルダ作成
    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)

    # 出力ファイルパス設定
    output_file = results_dir / "relative_performance_multi_period.txt"

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
                run_multi_period_analysis(db_path)
    finally:
        sys.stdout = old_stdout
        output_content = captured_output.getvalue()
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(output_content)

        print(output_content)
        print(f"\n出力を保存しました: {output_file.absolute()}")
