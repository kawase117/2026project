# -*- coding: utf-8 -*-
"""
Phase 9-5: 連続Rankパターン検出と店側ランダム化戦略の検証

検証対象:
1. Rank1連続 → Top3への反転傾向
2. Rank11連続 → Worst3への反転傾向
3. 過去3日パターン × 過去3回同一曜日パターンの相互情報量
4. ギャンブルのブレを考慮した多階層検証
"""

import sqlite3
import sys
import io
from pathlib import Path
from datetime import datetime
import numpy as np
import pandas as pd
import json
from scipy.stats import chi2_contingency
from sklearn.metrics import mutual_info_score

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

PROJECT_ROOT = Path(r"C:\Users\apto117\Documents\pachinko-analyzer\src\2026project")
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "db" / "experiments" / "マルハンメガシティ2000-蒲田7_rank_exp.db"
RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase9_last_digit_analysis"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def load_last_digit_summary(db_path):
    """Load pre-aggregated last-digit daily summary."""
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("""
        SELECT date, last_digit, machine_count, total_games, avg_games,
               total_diff_coins, avg_diff_coins, win_rate, high_profit_rate
        FROM last_digit_summary_all
        ORDER BY date, last_digit
    """, conn)
    conn.close()

    df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
    df['last_digit'] = df['last_digit'].astype(str)
    df['efficiency'] = (df['total_diff_coins'] / df['total_games'].replace(0, np.nan)).fillna(0)
    return df


def compute_digit_ranks(df):
    """Rank digits by total_diff_coins on each date."""
    df_copy = df.copy()
    df_copy['digit_rank'] = df_copy.groupby('date', group_keys=False).apply(
        lambda group: group['total_diff_coins'].rank(method='first', ascending=False)
    ).astype(int)

    df_copy['is_rank_1'] = (df_copy['digit_rank'] == 1).astype(int)
    df_copy['is_top_3'] = (df_copy['digit_rank'] <= 3).astype(int)
    df_copy['is_worst_3'] = (df_copy['digit_rank'] >= 9).astype(int)
    df_copy['is_rank_11'] = (df_copy['digit_rank'] == 11).astype(int)

    return df_copy


def add_temporal_features(df):
    """Add day_of_week for pattern matching."""
    df_copy = df.copy()
    df_copy['day_of_week'] = df_copy['date'].dt.dayofweek
    df_copy['day_name'] = df_copy['date'].dt.day_name()
    return df_copy


# ============================================================================
# 検証1: 連続Rankパターン検出
# ============================================================================

def detect_rank_patterns(df):
    """
    Detect 3-consecutive Rank patterns and their following outcomes.
    検証: Rank1が3連続の後はTop3になりやすいか
    """
    print("\n" + "="*80)
    print("検証1: 連続Rankパターン検出")
    print("="*80)

    results_by_digit = {}

    for digit in sorted(df['last_digit'].unique()):
        digit_df = df[df['last_digit'] == digit].sort_values('date').reset_index(drop=True)

        if len(digit_df) < 5:
            continue

        # 過去3日のRank合計
        digit_df['rank_sum_3d'] = digit_df['digit_rank'].rolling(3).sum()
        digit_df['is_rank1_consecutive'] = (digit_df['rank_sum_3d'] == 3).astype(int)
        digit_df['is_rank11_consecutive'] = (digit_df['rank_sum_3d'] == 33).astype(int)

        # 次のRank
        digit_df['next_rank'] = digit_df['digit_rank'].shift(-1)
        digit_df['next_is_top_3'] = (digit_df['next_rank'] <= 3).astype(int)
        digit_df['next_is_worst_3'] = (digit_df['next_rank'] >= 9).astype(int)

        # Rank1連続パターン分析
        rank1_patterns = digit_df[digit_df['is_rank1_consecutive'] == 1]
        rank1_next_top3_rate = rank1_patterns['next_is_top_3'].mean() if len(rank1_patterns) > 0 else 0

        # Rank11連続パターン分析
        rank11_patterns = digit_df[digit_df['is_rank11_consecutive'] == 1]
        rank11_next_worst3_rate = rank11_patterns['next_is_worst_3'].mean() if len(rank11_patterns) > 0 else 0

        results_by_digit[digit] = {
            'rank1_consecutive_count': len(rank1_patterns),
            'rank1_next_top3_rate': float(rank1_next_top3_rate),
            'rank1_next_top3_count': int(rank1_patterns['next_is_top_3'].sum()),
            'rank11_consecutive_count': len(rank11_patterns),
            'rank11_next_worst3_rate': float(rank11_next_worst3_rate),
            'rank11_next_worst3_count': int(rank11_patterns['next_is_worst_3'].sum())
        }

        print(f"\n末尾 {digit}:")
        print(f"  Rank1連続: {len(rank1_patterns):2d}回 → 次がTop3: {rank1_next_top3_rate:.1%}")
        print(f"  Rank11連続: {len(rank11_patterns):2d}回 → 次がWorst3: {rank11_next_worst3_rate:.1%}")

    return results_by_digit, digit_df


# ============================================================================
# 検証2: 有意性統計検定
# ============================================================================

def test_rank_reversal_hypothesis(df):
    """
    Chi-square test for rank reversal patterns.
    帰無仮説: 連続Rankパターンと次のRankは独立
    """
    print("\n" + "="*80)
    print("検証2: 有意性統計検定（カイ二乗検定）")
    print("="*80)

    test_results = {}

    for digit in sorted(df['last_digit'].unique()):
        digit_df = df[df['last_digit'] == digit].sort_values('date').reset_index(drop=True)

        if len(digit_df) < 5:
            continue

        # Rank1連続パターン検定
        digit_df['rank_sum_3d'] = digit_df['digit_rank'].rolling(3).sum()
        digit_df['is_rank1_consecutive'] = (digit_df['rank_sum_3d'] == 3).astype(int)
        digit_df['next_is_top_3'] = (digit_df['digit_rank'].shift(-1) <= 3).astype(int)

        valid_data = digit_df.dropna(subset=['is_rank1_consecutive', 'next_is_top_3'])

        if len(valid_data) < 3:
            continue

        # クロス集計
        contingency = pd.crosstab(
            valid_data['is_rank1_consecutive'],
            valid_data['next_is_top_3']
        )

        if contingency.shape == (2, 2):
            chi2, p_value, dof, expected = chi2_contingency(contingency)

            # Rank11→Worst3検定も追加
            digit_df['is_rank11_consecutive'] = (digit_df['rank_sum_3d'] == 33).astype(int)
            digit_df['next_is_worst_3'] = (digit_df['digit_rank'].shift(-1) >= 9).astype(int)

            valid_data_11 = digit_df.dropna(subset=['is_rank11_consecutive', 'next_is_worst_3'])
            contingency_11 = pd.crosstab(
                valid_data_11['is_rank11_consecutive'],
                valid_data_11['next_is_worst_3']
            )

            chi2_11, p_value_11, dof_11, expected_11 = chi2_contingency(contingency_11) if contingency_11.shape == (2, 2) else (0, 1.0, 0, None)

            test_results[digit] = {
                'rank1_to_top3': {
                    'chi2': float(chi2),
                    'p_value': float(p_value),
                    'significant_p005': bool(p_value < 0.05),
                    'significant_p001': bool(p_value < 0.01)
                },
                'rank11_to_worst3': {
                    'chi2': float(chi2_11),
                    'p_value': float(p_value_11),
                    'significant_p005': bool(p_value_11 < 0.05),
                    'significant_p001': bool(p_value_11 < 0.01)
                }
            }

            sig1 = "***" if p_value < 0.01 else "**" if p_value < 0.05 else "ns"
            sig11 = "***" if p_value_11 < 0.01 else "**" if p_value_11 < 0.05 else "ns"
            print(f"\n末尾 {digit}:")
            print(f"  Rank1→Top3: χ² = {chi2:.3f}, p = {p_value:.4f} {sig1}")
            print(f"  Rank11→Worst3: χ² = {chi2_11:.3f}, p = {p_value_11:.4f} {sig11}")

    return test_results


# ============================================================================
# 検証3: 相互情報量（過去3日パターン）
# ============================================================================

def compute_mutual_information_3day(df):
    """
    相互情報量: 過去3日のRankパターン × 次のRank
    """
    print("\n" + "="*80)
    print("検証3: 相互情報量 - 過去3日パターン")
    print("="*80)

    mi_results = {}

    for digit in sorted(df['last_digit'].unique()):
        digit_df = df[df['last_digit'] == digit].sort_values('date').reset_index(drop=True)

        if len(digit_df) < 5:
            continue

        digit_df['rank_sum_3d'] = digit_df['digit_rank'].rolling(3).sum()
        digit_df['next_rank'] = digit_df['digit_rank'].shift(-1)

        valid = digit_df.dropna(subset=['rank_sum_3d', 'next_rank'])

        if len(valid) > 5:
            rank_sum_binned = pd.cut(valid['rank_sum_3d'], bins=4, labels=False, duplicates='drop').astype(int)
            next_rank_binned = pd.cut(valid['next_rank'], bins=4, labels=False, duplicates='drop').astype(int)

            mi = mutual_info_score(rank_sum_binned, next_rank_binned)

            mi_results[digit] = {
                'mutual_information_3day': float(mi),
                'sample_count': len(valid)
            }

            print(f"末尾 {digit}: MI(3日パターン) = {mi:.4f} (n={len(valid)})")

    return mi_results


# ============================================================================
# 検証4: 相互情報量（過去3回同一曜日パターン）
# ============================================================================

def compute_mutual_information_same_weekday(df):
    """
    相互情報量: 過去3回の同じ曜日のRankパターン × 次のRank
    """
    print("\n" + "="*80)
    print("検証4: 相互情報量 - 過去3回同一曜日パターン")
    print("="*80)

    mi_results = {}

    for digit in sorted(df['last_digit'].unique()):
        digit_df = df[df['last_digit'] == digit].sort_values('date').reset_index(drop=True)

        if len(digit_df) < 10:
            continue

        digit_df['day_of_week'] = digit_df['date'].dt.dayofweek

        mi_by_dow = {}

        for dow in range(7):
            dow_df = digit_df[digit_df['day_of_week'] == dow].reset_index(drop=True)

            if len(dow_df) < 4:
                continue

            dow_df['rank_sum_prev3_same_dow'] = dow_df['digit_rank'].rolling(3).sum()
            dow_df['next_rank'] = dow_df['digit_rank'].shift(-1)

            valid = dow_df.dropna(subset=['rank_sum_prev3_same_dow', 'next_rank'])

            if len(valid) > 3:
                rank_sum_binned = pd.cut(valid['rank_sum_prev3_same_dow'], bins=3, labels=False, duplicates='drop').astype(int)
                next_rank_binned = pd.cut(valid['next_rank'], bins=3, labels=False, duplicates='drop').astype(int)

                mi = mutual_info_score(rank_sum_binned, next_rank_binned)
                mi_by_dow[dow] = mi

        if mi_by_dow:
            avg_mi = np.mean(list(mi_by_dow.values()))
            mi_results[digit] = {
                'mutual_information_same_weekday': float(avg_mi),
                'by_day_of_week': {str(dow): float(mi) for dow, mi in mi_by_dow.items()}
            }

            print(f"末尾 {digit}: MI(同一曜日3回) = {avg_mi:.4f}")

    return mi_results


def save_validation_results(pattern_results, test_results, mi_3day, mi_dow):
    """Save all validation results to JSON."""

    output = {
        'phase': '9-5',
        'description': 'Rank Reversal Validation - 店側ランダム化戦略検証',
        'timestamp': datetime.now().isoformat(),
        'validations': {
            'rank_reversal_patterns': pattern_results,
            'chi_square_tests': test_results,
            'mutual_information_3day': mi_3day,
            'mutual_information_same_weekday': mi_dow
        }
    }

    output_path = RESULTS_DIR / 'phase9_05_rank_reversal_validation_results.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n[OK] Results saved to {output_path}")

    # Summary
    print("\n" + "="*80)
    print("総合評価: 店側ランダム化戦略の可能性")
    print("="*80)

    significant_count = sum(
        1 for r in test_results.values()
        if r.get('rank1_to_top3', {}).get('significant_p005', False)
    )
    total_tests = len(test_results)

    avg_mi_3day = np.mean([r.get('mutual_information_3day', 0) for r in mi_3day.values()]) if mi_3day else 0
    avg_mi_dow = np.mean([r.get('mutual_information_same_weekday', 0) for r in mi_dow.values()]) if mi_dow else 0

    print(f"\n有意な関係: {significant_count}/{total_tests} (p<0.05)")
    print(f"平均MI（3日パターン）: {avg_mi_3day:.4f}")
    print(f"平均MI（同一曜日）: {avg_mi_dow:.4f}")

    if significant_count >= total_tests * 0.5:
        print("\n✅ 連続Rankパターン後の反転傾向が有意")
        print("   → 店側が意図的にランダム化している可能性あり")
    else:
        print("\n⚠️  有意な反転傾向なし")

    if avg_mi_3day > 0.3 or avg_mi_dow > 0.3:
        print("\n✅ 相互情報量が高い → Rankパターンから次が予測可能")
    else:
        print("\n⚠️  相互情報量が低い → ランダムに近い")


def main():
    """Main execution flow."""

    print("="*80)
    print("Phase 9-5: Rank Reversal Validation")
    print("店側ランダム化戦略の検証")
    print("="*80)

    print("\n[1] Loading last_digit_summary...")
    df = load_last_digit_summary(DB_PATH)
    print(f"  Loaded {len(df)} records")

    print("\n[2] Computing digit ranks...")
    df = compute_digit_ranks(df)

    print("\n[3] Adding temporal features...")
    df = add_temporal_features(df)

    print("\n[4] Running Validation 1...")
    pattern_results, _ = detect_rank_patterns(df)

    print("\n[5] Running Validation 2...")
    test_results = test_rank_reversal_hypothesis(df)

    print("\n[6] Running Validation 3...")
    mi_3day = compute_mutual_information_3day(df)

    print("\n[7] Running Validation 4...")
    mi_dow = compute_mutual_information_same_weekday(df)

    print("\n[8] Saving results...")
    save_validation_results(pattern_results, test_results, mi_3day, mi_dow)

    print("\n" + "="*80)
    print("[OK] Phase 9-5 Complete!")
    print("="*80)


if __name__ == '__main__':
    main()
