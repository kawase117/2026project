"""バックテスト実行スクリプト"""

import pandas as pd
from pathlib import Path
from loader import load_machine_data
from extractor import extract_winning_patterns
from validator import validate_patterns, analyze_win_rate_correlation


def run_backtest(db_path: str, win_rate_threshold: float = 0.66) -> None:
    """
    バックテスト実行・結果出力

    Args:
        db_path: SQLiteデータベースパス
        win_rate_threshold: 勝率しきい値（デフォルト0.66=66%）
    """
    print(f"\nバックテスト開始 (DB: {Path(db_path).stem})")
    print(f"学習期間: 2026-01-01 ～ 2026-03-31")
    print(f"テスト期間: 2026-04-01 ～ 2026-04-20")
    print(f"勝率しきい値: {win_rate_threshold*100:.0f}%")

    # ステップ1: データ読み込み
    try:
        df = load_machine_data(db_path)
    except Exception as e:
        print(f"  エラー: データ読み込み失敗 - {e}")
        return

    df_train = df[(df['date'] >= '2026-01-01') & (df['date'] <= '2026-03-31')].copy()
    df_test = df[(df['date'] >= '2026-04-01') & (df['date'] <= '2026-04-20')].copy()

    if len(df_train) == 0:
        print(f"  エラー: 学習期間データがありません")
        return

    if len(df_test) == 0:
        print(f"  エラー: テスト期間データがありません")
        return

    print(f"データ読み込み完了")
    print(f"  学習期間データ: {len(df_train):,} 件")
    print(f"  テスト期間データ: {len(df_test):,} 件")

    # 複合属性パターン（ダッシュボード page_11 と同様）
    patterns = [
        ('dd', 'last_digit', 'DD × 台末尾'),
        ('dd', 'machine_number', 'DD × 台番号'),
        ('dd', 'machine_name', 'DD × 機種'),
        ('weekday', 'last_digit', '曜日 × 台末尾'),
        ('weekday', 'machine_number', '曜日 × 台番号'),
        ('weekday', 'machine_name', '曜日 × 機種'),
    ]

    for attr1, attr2, display_name in patterns:
        print("\n" + "=" * 60)
        print(f"{display_name}")
        print("=" * 60)

        try:
            patterns_result = extract_winning_patterns(df_train, attr1, attr2, win_rate_threshold)
            print(f"\n学習期間で勝率{win_rate_threshold*100:.0f}%以上のパターン: {len(patterns_result)} 個")

            if len(patterns_result) > 0:
                print(patterns_result.to_string(index=False))

                validated = validate_patterns(df_test, patterns_result, attr1, attr2)
                print(f"\n---テスト期間での再現性---")
                print(validated.to_string(index=False))

                # 相関分析
                correlation = analyze_win_rate_correlation(df_test, patterns_result, attr1, attr2)
                if correlation:
                    print(f"\n---勝率と再現性の相関---")
                    print(f"高勝率グループ（中央値以上）:")
                    print(f"  パターン数: {correlation['high_win_rate']['count']}")
                    print(f"  再現パターン: {correlation['high_win_rate']['reproduced_count']}/{correlation['high_win_rate']['count']}")
                    print(f"  再現率: {correlation['high_win_rate']['reproduction_rate']*100:.1f}%")
                    print(f"  平均学習勝率: {correlation['high_win_rate']['avg_train_wr']*100:.1f}%")
                    print(f"  平均テスト勝率: {correlation['high_win_rate']['avg_test_wr']*100:.1f}%")

                    print(f"\n低勝率グループ（中央値未満）:")
                    print(f"  パターン数: {correlation['low_win_rate']['count']}")
                    print(f"  再現パターン: {correlation['low_win_rate']['reproduced_count']}/{correlation['low_win_rate']['count']}")
                    print(f"  再現率: {correlation['low_win_rate']['reproduction_rate']*100:.1f}%")
                    print(f"  平均学習勝率: {correlation['low_win_rate']['avg_train_wr']*100:.1f}%")
                    print(f"  平均テスト勝率: {correlation['low_win_rate']['avg_test_wr']*100:.1f}%")
            else:
                print("  → 該当パターンなし")

        except Exception as e:
            print(f"  エラー: {e}")


if __name__ == "__main__":
    import glob

    db_dir = Path("db")
    if not db_dir.exists():
        print(f"エラー: db/ ディレクトリが見つかりません")
        exit(1)

    # 指定されたホールでバックテスト実行
    halls = [
        "マルハンメガシティ2000-蒲田1.db",
        "マルハンメガシティ2000-蒲田7.db"
    ]

    for hall in halls:
        db_path = db_dir / hall
        if db_path.exists():
            run_backtest(str(db_path), win_rate_threshold=0.66)
        else:
            print(f"\nエラー: {hall} が見つかりません")

    print("\n" + "=" * 60)
    print("全バックテスト完了")
    print("=" * 60)
