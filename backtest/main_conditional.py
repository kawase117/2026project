"""条件付き分析実行スクリプト"""

import pandas as pd
from pathlib import Path
from loader import load_machine_data
from conditional_analysis import analyze_by_condition


def run_conditional_analysis(db_path: str) -> None:
    """全DD及び全曜日での条件付き分析を実行"""

    print(f"\n条件付き分析開始 (DB: {Path(db_path).stem})")
    print(f"学習期間: 2026-01-01 ～ 2026-03-31")
    print(f"テスト期間: 2026-04-01 ～ 2026-04-20")

    # データ読み込み
    df = load_machine_data(db_path)
    df_train = df[(df['date'] >= '2026-01-01') & (df['date'] <= '2026-03-31')].copy()
    df_test = df[(df['date'] >= '2026-04-01') & (df['date'] <= '2026-04-20')].copy()

    print(f"データ読み込み完了")
    print(f"  学習期間: {len(df_train):,} 件")
    print(f"  テスト期間: {len(df_test):,} 件\n")

    # ========================================
    # DD別分析（1～31日）
    # ========================================
    print("=" * 80)
    print("DD別分析（月内日付）")
    print("=" * 80)

    dd_results = {}
    for dd in range(1, 32):
        result = analyze_by_condition(df_train, df_test, 'dd', dd)
        dd_results[dd] = result

    # 結果をテーブル形式で表示
    print("\n{:<5} {:<15} {:<15} {:<15} {:<15}".format("DD", "台番号", "機種", "台末尾", ""))
    print("-" * 65)

    for dd in sorted(dd_results.keys()):
        result = dd_results[dd]
        if 'error' in result:
            continue

        machine_repr = f"{result['machine_number']['reproduced_count']}/{result['machine_number']['train_patterns']}" if 'reproduced_count' in result.get('machine_number', {}) else "N/A"
        machine_rate = f"{result['machine_number']['reproduction_rate']*100:.0f}%" if 'reproduction_rate' in result.get('machine_number', {}) else ""

        name_repr = f"{result['machine_name']['reproduced_count']}/{result['machine_name']['train_patterns']}" if 'reproduced_count' in result.get('machine_name', {}) else "N/A"
        name_rate = f"{result['machine_name']['reproduction_rate']*100:.0f}%" if 'reproduction_rate' in result.get('machine_name', {}) else ""

        digit_repr = f"{result['last_digit']['reproduced_count']}/{result['last_digit']['train_patterns']}" if 'reproduced_count' in result.get('last_digit', {}) else "N/A"
        digit_rate = f"{result['last_digit']['reproduction_rate']*100:.0f}%" if 'reproduction_rate' in result.get('last_digit', {}) else ""

        print("{:<5} {:<7} {:<6} {:<7} {:<6} {:<7} {:<6}".format(
            f"D{dd}",
            machine_repr,
            machine_rate,
            name_repr,
            name_rate,
            digit_repr,
            digit_rate
        ))

    # 統計
    print("\n" + "=" * 80)
    print("DD別 再現率統計")
    print("=" * 80)
    for attr in ['machine_number', 'machine_name', 'last_digit']:
        valid_results = [r[attr] for r in dd_results.values() if attr in r and 'reproduction_rate' in r[attr]]
        if valid_results:
            avg_rate = sum(r['reproduction_rate'] for r in valid_results) / len(valid_results)
            print(f"{attr}: 平均再現率 {avg_rate*100:.1f}% ({len(valid_results)}/31日)")

    # ========================================
    # 曜日別分析（月～日）
    # ========================================
    print("\n" + "=" * 80)
    print("曜日別分析")
    print("=" * 80)

    weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    weekday_jp = ['月', '火', '水', '木', '金', '土', '日']
    weekday_results = {}

    for weekday in weekdays:
        result = analyze_by_condition(df_train, df_test, 'weekday', weekday)
        weekday_results[weekday] = result

    # 結果をテーブル形式で表示
    print("\n{:<6} {:<15} {:<15} {:<15}".format("曜日", "台番号", "機種", "台末尾"))
    print("-" * 55)

    for weekday, jp in zip(weekdays, weekday_jp):
        result = weekday_results[weekday]
        if 'error' in result:
            print(f"{jp}曜日: {result['error']}")
            continue

        machine_repr = f"{result['machine_number']['reproduced_count']}/{result['machine_number']['train_patterns']}" if 'reproduced_count' in result.get('machine_number', {}) else "N/A"
        machine_rate = f"{result['machine_number']['reproduction_rate']*100:.0f}%" if 'reproduction_rate' in result.get('machine_number', {}) else ""

        name_repr = f"{result['machine_name']['reproduced_count']}/{result['machine_name']['train_patterns']}" if 'reproduced_count' in result.get('machine_name', {}) else "N/A"
        name_rate = f"{result['machine_name']['reproduction_rate']*100:.0f}%" if 'reproduction_rate' in result.get('machine_name', {}) else ""

        digit_repr = f"{result['last_digit']['reproduced_count']}/{result['last_digit']['train_patterns']}" if 'reproduced_count' in result.get('last_digit', {}) else "N/A"
        digit_rate = f"{result['last_digit']['reproduction_rate']*100:.0f}%" if 'reproduction_rate' in result.get('last_digit', {}) else ""

        print("{:<6} {:<7} {:<6} {:<7} {:<6} {:<7} {:<6}".format(
            f"{jp}曜",
            machine_repr,
            machine_rate,
            name_repr,
            name_rate,
            digit_repr,
            digit_rate
        ))

    # 統計
    print("\n" + "=" * 80)
    print("曜日別 再現率統計")
    print("=" * 80)
    for attr in ['machine_number', 'machine_name', 'last_digit']:
        valid_results = [r[attr] for r in weekday_results.values() if attr in r and 'reproduction_rate' in r[attr]]
        if valid_results:
            avg_rate = sum(r['reproduction_rate'] for r in valid_results) / len(valid_results)
            print(f"{attr}: 平均再現率 {avg_rate*100:.1f}% ({len(valid_results)}/7曜日)")


if __name__ == "__main__":
    halls = [
        "マルハンメガシティ2000-蒲田1.db",
        "マルハンメガシティ2000-蒲田7.db"
    ]

    for hall in halls:
        db_path = f"../db/{hall}"
        if Path(db_path).exists():
            run_conditional_analysis(db_path)
        else:
            print(f"\nエラー: {hall} が見つかりません")

    print("\n" + "=" * 80)
    print("条件付き分析完了")
    print("=" * 80)
