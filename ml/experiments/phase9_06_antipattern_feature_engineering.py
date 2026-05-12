# -*- coding: utf-8 -*-
"""
Phase 9-6: Anti-Pattern Feature Engineering (新特徴量: 店側対抗戦略の迂回)

Extends Phase 9-1 27D feature set with 5 new anti-pattern features based on Phase 9-5 findings.

Key Insight: Shop deliberately suppresses consecutive patterns and obvious signals.
Strategy: Target shop's counter-strategy blindspots with features detecting:
1. Same-weekday rolling rank sum (3x stronger signal than 3-day patterns)
2. Weekday-digit bias (digit-specific weekday effects)
3. Anti-pattern rank1 rate (signal in non-consecutive states)
4. Weekday × non-consecutive interaction (combining 2 strongest signals)
5. Consecutive suppression score (diagnostic: how aggressively shop suppresses patterns)

Output: features_32d_with_antipattern.csv (27D original + 5 new)

Expected AUC improvement: Rank1 +0.5-1.4% (0.6231 → 0.635-0.645)
"""

import sqlite3
import sys
from pathlib import Path
from datetime import datetime
import numpy as np
import pandas as pd
import json
import io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

PROJECT_ROOT = Path(r"C:\Users\apto117\Documents\pachinko-analyzer\src\2026project")
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "db" / "experiments" / "マルハンメガシティ2000-蒲田7_rank_exp.db"
RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase9_last_digit_analysis"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def load_last_digit_summary(db_path):
    """Load pre-aggregated last-digit daily summary from database."""
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("""
        SELECT
            date,
            last_digit,
            machine_count,
            total_games,
            avg_games,
            total_diff_coins,
            avg_diff_coins,
            win_rate,
            high_profit_rate
        FROM last_digit_summary_all
        ORDER BY date, last_digit
    """, conn)
    conn.close()

    df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
    df['last_digit'] = df['last_digit'].astype(str)
    df['efficiency'] = (df['total_diff_coins'] / df['total_games'].replace(0, np.nan)).fillna(0)

    return df


def compute_digit_ranks(df):
    """Compute digit ranks on each date (for new feature calculations)."""
    df['digit_rank'] = df.groupby('date', group_keys=False).apply(
        lambda group: group['total_diff_coins'].rank(method='first', ascending=False)
    ).astype(int)

    df['is_rank_1'] = (df['digit_rank'] == 1).astype(int)
    df['is_top_3'] = (df['digit_rank'] <= 3).astype(int)

    return df


# ============================================================================
# 新特徴量1: 同一曜日ローリングランク合計
# ============================================================================

def compute_same_weekday_rolling_rank_sum(df):
    """
    過去3回の同じ曜日でのRank合計

    動機: 同一曜日パターンが3日パターンの3倍強い（MI 0.053 vs 0.016）
    実装: 各digitについて、同じ曜日の過去3回のdigit_rankを合計
    """
    df = df.copy()
    df['day_of_week'] = df['date'].dt.dayofweek
    df['same_weekday_rolling_rank_sum_3'] = 0.0

    for digit in df['last_digit'].unique():
        for dow in range(7):
            # Filter: this digit on this day of week
            mask = (df['last_digit'] == digit) & (df['day_of_week'] == dow)
            subset = df[mask].sort_values('date').reset_index(drop=True)

            if len(subset) > 0:
                # Rolling sum of past 3 occurrences
                rank_sums = subset['digit_rank'].rolling(window=3, min_periods=1).sum()
                df.loc[mask, 'same_weekday_rolling_rank_sum_3'] = rank_sums.values

    return df


# ============================================================================
# 新特徴量2: 曜日別デバイアス（Digit-Weekday Bias Detection）
# ============================================================================

def compute_weekday_digit_bias(df):
    """
    このDigitは、この曜日で「高くなりやすい」か「低くなりやすい」か

    計算式: その曜日の平均Rank - 全曜日での平均Rank
    正 = その曜日では高い傾向, 負 = その曜日では低い傾向
    """
    df = df.copy()
    df['day_of_week'] = df['date'].dt.dayofweek
    df['weekday_digit_bias'] = 0.0

    for digit in df['last_digit'].unique():
        digit_mask = df['last_digit'] == digit
        digit_df = df[digit_mask]

        # 全体の平均Rank
        overall_mean_rank = digit_df['digit_rank'].mean()

        # 曜日別の平均Rank
        dow_mean_ranks = digit_df.groupby('day_of_week')['digit_rank'].transform('mean')

        # Bias = その曜日の平均 - 全体平均（負の値＝その曜日では低い）
        bias = dow_mean_ranks - overall_mean_rank
        df.loc[digit_mask, 'weekday_digit_bias'] = bias.values

    return df


# ============================================================================
# 新特徴量3: 逆パターン検出（Anti-Pattern Signal）
# ============================================================================

def compute_anti_pattern_rank1_rate(df):
    """
    「前日がRank1ではない」状態でのRank1達成率

    背景: 店側は「Rank1が連続しやすい」パターンを打ち消す。
    逆を言えば、「連続していない状態で Rank1 になる」ことは、
    店側も対抗できていない、より深い法則かもしれない。
    """
    df = df.copy()
    df['is_prev_rank1'] = df.groupby('last_digit')['is_rank_1'].shift(1).fillna(0)
    df['anti_pattern_rank1_rate'] = 0.0

    for digit in df['last_digit'].unique():
        digit_mask = df['last_digit'] == digit
        subset = df[digit_mask].sort_values('date')

        # 「前日がRank1ではない」状態でのRank1率
        non_consecutive = subset[subset['is_prev_rank1'] == 0]
        if len(non_consecutive) > 0:
            rate = non_consecutive['is_rank_1'].mean()
            df.loc[digit_mask, 'anti_pattern_rank1_rate'] = rate

    return df


# ============================================================================
# 新特徴量4: 曜日×非連続相互作用
# ============================================================================

def compute_weekday_non_consecutive_rank1_rate(df):
    """
    「この曜日で、かつ前日がRank1ではない」という条件でのRank1率

    最も強い信号（同一曜日MI 0.053）と、
    最も隠れた信号（非連続状態）を組み合わせる
    """
    df = df.copy()
    df['day_of_week'] = df['date'].dt.dayofweek
    df['is_prev_rank1'] = df.groupby('last_digit')['is_rank_1'].shift(1).fillna(0)
    df['weekday_non_consecutive_rank1_rate'] = 0.0

    for digit in df['last_digit'].unique():
        for dow in range(7):
            # (曜日, 非連続) の2条件を満たす状態
            mask = (df['last_digit'] == digit) & (df['day_of_week'] == dow) & (df['is_prev_rank1'] == 0)
            subset = df[mask]

            if len(subset) > 0:
                rate = subset['is_rank_1'].mean()
                df.loc[mask, 'weekday_non_consecutive_rank1_rate'] = rate

    return df


# ============================================================================
# 新特徴量5: 連続抑制スコア（診断用）
# ============================================================================

def compute_consecutive_suppression_score(df):
    """
    このDigitが「連続Rank1を避けている」程度を定量化

    計算式:
    - 期待値（完全ランダム）: (1/11)^3 ≈ 0.08%
    - 実績: (実際の3日連続Rank1数) / (全date-digit対)
    - スコア = (期待値 - 実績) / 期待値 * 100

    スコアが高い = 店側が意図的に抑制している
    スコアが低い = ランダムに見える（抑制成功）
    """
    df = df.copy()
    df['consecutive_suppression_score'] = 0.0

    for digit in df['last_digit'].unique():
        digit_mask = df['last_digit'] == digit
        subset = df[digit_mask].sort_values('date').reset_index(drop=True)

        total_samples = len(subset)

        # 3日連続Rank1の数を数える
        rank1_flag = (subset['digit_rank'] == 1).astype(int).values
        consecutive_3 = 0
        for i in range(2, len(rank1_flag)):
            if rank1_flag[i-2] == 1 and rank1_flag[i-1] == 1 and rank1_flag[i] == 1:
                consecutive_3 += 1

        expected_consecutive = total_samples * (1/11)**3
        actual_rate = consecutive_3 / max(total_samples - 2, 1)
        expected_rate = (1/11)**3

        if expected_rate > 0:
            suppression_score = ((expected_rate - actual_rate) / expected_rate) * 100
        else:
            suppression_score = 0

        df.loc[digit_mask, 'consecutive_suppression_score'] = suppression_score

    return df


def load_phase9_01_features(csv_path):
    """Load 27D features from Phase 9-1 output."""
    df = pd.read_csv(csv_path)
    df['date'] = pd.to_datetime(df['date'])
    return df


def merge_new_features(df_original, df_new, feature_columns):
    """Merge new features into original feature dataframe."""
    # Keep metadata and targets from original
    df_result = df_original[['date', 'last_digit', 'is_rank_1', 'is_top_3', 'is_top_5']].copy()

    # Add original 27D features
    feature_cols_27d = [col for col in df_original.columns if col not in ['date', 'last_digit', 'is_rank_1', 'is_top_3', 'is_top_5']]
    for col in feature_cols_27d:
        df_result[col] = df_original[col]

    # Add new 5 features
    for col in feature_columns:
        if col in df_new.columns:
            df_result[col] = df_new[col]

    return df_result


def save_extended_features(df, output_path):
    """Save 32D feature set to CSV."""
    df.to_csv(output_path, index=False)
    print(f"\n[OK] Extended features saved to {output_path}")
    print(f"  Shape: {df.shape}")
    print(f"  Total features: {len([c for c in df.columns if c not in ['date', 'last_digit', 'is_rank_1', 'is_top_3', 'is_top_5']])}D")


def main():
    """Main execution flow."""

    print("=" * 80)
    print("Phase 9-6: Anti-Pattern Feature Engineering")
    print("店側対抗戦略の迂回特徴量実装")
    print("=" * 80)

    # Step 1: Load database data
    print("\n[1] Loading last_digit_summary_all from database...")
    df_db = load_last_digit_summary(DB_PATH)
    print(f"  Loaded {len(df_db)} records")

    # Step 2: Compute digit ranks for feature calculation
    print("\n[2] Computing digit ranks...")
    df_db = compute_digit_ranks(df_db)

    # Step 3: Compute 5 new anti-pattern features
    print("\n[3] Computing 5 new anti-pattern features...")

    print("  [3-1] same_weekday_rolling_rank_sum_3...")
    df_db = compute_same_weekday_rolling_rank_sum(df_db)

    print("  [3-2] weekday_digit_bias...")
    df_db = compute_weekday_digit_bias(df_db)

    print("  [3-3] anti_pattern_rank1_rate...")
    df_db = compute_anti_pattern_rank1_rate(df_db)

    print("  [3-4] weekday_non_consecutive_rank1_rate...")
    df_db = compute_weekday_non_consecutive_rank1_rate(df_db)

    print("  [3-5] consecutive_suppression_score (diagnostic)...")
    df_db = compute_consecutive_suppression_score(df_db)

    # Step 4: Load Phase 9-1 features
    print("\n[4] Loading Phase 9-1 base features (27D)...")
    phase9_01_path = RESULTS_DIR / 'features_27d_last_digit_final.csv'
    if not phase9_01_path.exists():
        print(f"  ERROR: {phase9_01_path} not found!")
        print("  Please run Phase 9-1 first.")
        return

    df_phase9_01 = load_phase9_01_features(phase9_01_path)
    print(f"  Loaded {len(df_phase9_01)} rows")

    # Step 5: Merge new features
    print("\n[5] Merging new features with base features...")
    new_features = [
        'same_weekday_rolling_rank_sum_3',
        'weekday_digit_bias',
        'anti_pattern_rank1_rate',
        'weekday_non_consecutive_rank1_rate',
        'consecutive_suppression_score'
    ]

    df_combined = merge_new_features(df_phase9_01, df_db, new_features)
    print(f"  Combined shape: {df_combined.shape}")

    # Step 6: Save extended features
    print("\n[6] Saving 32D feature set...")
    output_path = RESULTS_DIR / 'features_32d_with_antipattern.csv'
    save_extended_features(df_combined, output_path)

    # Step 7: Summary statistics
    print("\n[7] Feature Summary:")
    print(f"  Original features (27D): month_progress, rolling_avg_*, rolling_rank_sum_*, dow_lastdigit_rank1_rate, periodicity_strength, prior_*")
    print(f"  New features (5D):")
    for feat in new_features:
        mean_val = df_combined[feat].mean()
        std_val = df_combined[feat].std()
        print(f"    - {feat}: mean={mean_val:.4f}, std={std_val:.4f}")

    print("\n" + "=" * 80)
    print("[OK] Phase 9-6 Complete!")
    print("=" * 80)
    print("\nNext Steps:")
    print("1. Run Phase 9-2 with features_32d_with_antipattern.csv")
    print("2. Analyze new feature importance (expect 4-6% contribution)")
    print("3. Re-run Phase 9-3 model comparison with 32D features")
    print("4. Re-run Phase 9-4 hyperparameter tuning")
    print("5. Compare AUC improvements (target: Rank1 +0.5-1.4%)")


if __name__ == '__main__':
    main()
