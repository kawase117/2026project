"""詳細条件付き分析 - 高勝率vs低勝率の再現性比較"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd
from pathlib import Path
from loader import load_machine_data


def analyze_hypothesis_by_condition(df_train: pd.DataFrame, df_test: pd.DataFrame, condition_type: str, condition_value) -> dict:
    """
    高勝率パターン vs 低勝率パターンの再現性を比較

    仮説A: 高勝率パターン（>中央値）が次月でも勝つ
    仮説B: 低勝率パターン（<中央値）が次月で逆転する
    """
    # 条件で日を限定
    train_filtered = df_train[df_train[condition_type] == condition_value]
    test_filtered = df_test[df_test[condition_type] == condition_value]

    if len(train_filtered) == 0 or len(test_filtered) == 0:
        return None

    results = {}

    for attr in ['machine_number', 'machine_name', 'last_digit']:
        # 学習期間でこの属性別の勝率を計算
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

        # 高勝率グループの再現
        high_reproduced = 0
        for _, row in high_wr.iterrows():
            test_match = test_grouped[test_grouped[attr] == row[attr]]
            if len(test_match) > 0 and test_match.iloc[0]['test_win_rate'] >= 0.50:
                high_reproduced += 1

        # 低勝率グループの再現
        low_reproduced = 0
        for _, row in low_wr.iterrows():
            test_match = test_grouped[test_grouped[attr] == row[attr]]
            if len(test_match) > 0 and test_match.iloc[0]['test_win_rate'] >= 0.50:
                low_reproduced += 1

        results[attr] = {
            'median_wr': median_wr,
            'high_count': len(high_wr),
            'high_reproduced': high_reproduced,
            'high_rate': high_reproduced / len(high_wr) if len(high_wr) > 0 else 0,
            'low_count': len(low_wr),
            'low_reproduced': low_reproduced,
            'low_rate': low_reproduced / len(low_wr) if len(low_wr) > 0 else 0,
        }

    return results


def run_detailed_analysis(db_path: str, output_file=None):
    """全DD/曜日での高低勝率比較分析"""

    if output_file:
        output_file = open(output_file, 'a', encoding='utf-8')
        import sys
        old_stdout = sys.stdout
        sys.stdout = output_file

    print(f"\n詳細分析開始 (DB: {Path(db_path).stem})")
    print("=" * 90)

    df = load_machine_data(db_path)
    df_train = df[(df['date'] >= '2026-02-01') & (df['date'] <= '2026-03-31')].copy()
    df_test = df[(df['date'] >= '2026-04-01') & (df['date'] <= '2026-04-20')].copy()

    # ========== DD別分析 ==========
    print("\nDD別 仮説検証（高勝率 vs 低勝率）")
    print("-" * 90)
    print(f"{'DD':<5} {'属性':<10} {'中央値':<8} {'高勝率':<10} {'低勝率':<10} {'差':<8}")
    print("-" * 90)

    dd_summary = {'machine_number': [], 'machine_name': [], 'last_digit': []}

    for dd in range(1, 21):  # テスト期間に存在するDD
        result = analyze_hypothesis_by_condition(df_train, df_test, 'dd', dd)
        if result is None:
            continue

        for attr in ['machine_number', 'machine_name', 'last_digit']:
            if attr in result:
                r = result[attr]
                high_rate = r['high_rate'] * 100
                low_rate = r['low_rate'] * 100
                diff = high_rate - low_rate
                print(f"D{dd:<3} {attr:<10} {r['median_wr']*100:>6.1f}% {high_rate:>6.1f}% ({r['high_reproduced']}/{r['high_count']}) {low_rate:>6.1f}% ({r['low_reproduced']}/{r['low_count']}) {diff:>6.1f}%")
                dd_summary[attr].append({'dd': dd, 'high': high_rate, 'low': low_rate, 'diff': diff})

    # DD別統計
    print("\nDD別 仮説判定:")
    for attr in ['machine_number', 'machine_name', 'last_digit']:
        if dd_summary[attr]:
            avg_high = sum(r['high'] for r in dd_summary[attr]) / len(dd_summary[attr])
            avg_low = sum(r['low'] for r in dd_summary[attr]) / len(dd_summary[attr])
            avg_diff = avg_high - avg_low
            hypothesis = "仮説A有利（高勝率が再現）" if avg_diff > 0 else "仮説B有利（低勝率が再現）"
            print(f"  {attr}: 高勝率平均 {avg_high:.1f}%, 低勝率平均 {avg_low:.1f}% → {hypothesis} (差: {avg_diff:.1f}%)")

    # ========== 曜日別分析 ==========
    print("\n" + "=" * 90)
    print("曜日別 仮説検証（高勝率 vs 低勝率）")
    print("-" * 90)
    print(f"{'曜日':<6} {'属性':<10} {'中央値':<8} {'高勝率':<10} {'低勝率':<10} {'差':<8}")
    print("-" * 90)

    weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    weekday_jp = ['月', '火', '水', '木', '金', '土', '日']
    weekday_summary = {'machine_number': [], 'machine_name': [], 'last_digit': []}

    for weekday, jp in zip(weekdays, weekday_jp):
        result = analyze_hypothesis_by_condition(df_train, df_test, 'weekday', weekday)
        if result is None:
            continue

        for attr in ['machine_number', 'machine_name', 'last_digit']:
            if attr in result:
                r = result[attr]
                high_rate = r['high_rate'] * 100
                low_rate = r['low_rate'] * 100
                diff = high_rate - low_rate
                print(f"{jp}曜<  {attr:<10} {r['median_wr']*100:>6.1f}% {high_rate:>6.1f}% ({r['high_reproduced']}/{r['high_count']}) {low_rate:>6.1f}% ({r['low_reproduced']}/{r['low_count']}) {diff:>6.1f}%")
                weekday_summary[attr].append({'weekday': weekday, 'high': high_rate, 'low': low_rate, 'diff': diff})

    # 曜日別統計
    print("\n曜日別 仮説判定:")
    for attr in ['machine_number', 'machine_name', 'last_digit']:
        if weekday_summary[attr]:
            avg_high = sum(r['high'] for r in weekday_summary[attr]) / len(weekday_summary[attr])
            avg_low = sum(r['low'] for r in weekday_summary[attr]) / len(weekday_summary[attr])
            avg_diff = avg_high - avg_low
            hypothesis = "仮説A有利（高勝率が再現）" if avg_diff > 0 else "仮説B有利（低勝率が再現）"
            print(f"  {attr}: 高勝率平均 {avg_high:.1f}%, 低勝率平均 {avg_low:.1f}% → {hypothesis} (差: {avg_diff:.1f}%)")


if __name__ == "__main__":
    halls = [
        "マルハンメガシティ2000-蒲田1.db",
        "マルハンメガシティ2000-蒲田7.db"
    ]

    for hall in halls:
        db_path = f"../db/{hall}"
        if Path(db_path).exists():
            run_detailed_analysis(db_path)

    print("\n" + "=" * 90)
    print("詳細分析完了")
    print("=" * 90)

    if output_file:
        sys.stdout = old_stdout
        output_file.close()
