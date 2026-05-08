# -*- coding: utf-8 -*-
"""
Phase 9-1: 台番号末尾別の特徴量エンジニアリング - Last-Digit Feature Engineering

Creates 18D feature set for predicting high-rank settings by last digit (末尾: 0～9).
Extends Phase 7-8 machine-type learning to digit-level analysis.

Features:
- month_progress: (day - 1) / days_in_month
- days_since_last_rank1: Days since last achievement of Rank1 per digit
- rolling_averages (7/14/21/28/35 days): avg_diff, avg_games, avg_efficiency, machine_count
"""

import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json

PROJECT_ROOT = Path(r"C:\Users\apto117\Documents\pachinko-analyzer\src\2026project")
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "db" / "experiments" / "マルハンメガシティ2000-蒲田7_rank_exp.db"
RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase9_last_digit_analysis"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def load_last_digit_summary(db_path):
    """Load pre-aggregated last-digit daily summary."""
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

    # Parse date
    df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')

    # Ensure last_digit is TEXT
    df['last_digit'] = df['last_digit'].astype(str)

    # Compute efficiency
    df['efficiency'] = (df['total_diff_coins'] / df['total_games'].replace(0, np.nan)).fillna(0)

    return df


def compute_digit_ranks_by_date(df):
    """Rank digits on each date by total_diff_coins (main performance metric)."""

    df_copy = df.copy()

    # Rank digits by total_diff_coins on each date (descending)
    # If tie, use avg_diff_coins as tiebreaker
    df_copy['digit_rank'] = df_copy.groupby('date', group_keys=False).apply(
        lambda group: group['total_diff_coins'].rank(method='first', ascending=False)
    ).astype(int)

    # Derive rank flags
    df_copy['is_rank_1'] = (df_copy['digit_rank'] == 1).astype(int)
    df_copy['is_top_3'] = (df_copy['digit_rank'] <= 3).astype(int)
    df_copy['is_top_5'] = (df_copy['digit_rank'] <= 5).astype(int)

    return df_copy.drop(columns=['digit_rank'])


def compute_days_since_last_rank1(df):
    """Compute days since last Rank1 achievement for each last_digit."""

    df_copy = df.copy()

    # For each last_digit, find the most recent date where is_rank_1 = 1
    def get_days_since_rank1(group):
        rank1_dates = group[group['is_rank_1'] == 1]['date']

        if len(rank1_dates) == 0:
            # Never achieved rank1
            return pd.Series([365] * len(group), index=group.index)

        last_rank1_date = rank1_dates.max()
        days_since = (group['date'] - last_rank1_date).dt.days

        # Cap at 365 days
        return days_since.clip(lower=0, upper=365)

    df_copy['days_since_last_rank1'] = df_copy.groupby('last_digit', group_keys=False).apply(
        get_days_since_rank1
    )

    return df_copy


def compute_month_progress(df):
    """Compute month progress (0 to 1) for each date."""

    df_copy = df.copy()

    # Calculate days in month
    df_copy['days_in_month'] = df_copy['date'].dt.daysinmonth

    # Month progress: (day - 1) / days_in_month
    df_copy['month_progress'] = (df_copy['date'].dt.day - 1) / df_copy['days_in_month']

    df_copy = df_copy.drop(columns=['days_in_month'])

    return df_copy


def compute_rolling_averages(df, windows=[7, 14, 21, 28, 35]):
    """Compute rolling averages for each last_digit separately."""

    df_copy = df.copy()

    # For each last_digit, compute rolling averages independently
    for digit in df_copy['last_digit'].unique():
        digit_mask = df_copy['last_digit'] == digit
        digit_df = df_copy[digit_mask].sort_values('date')

        for window in windows:
            # Rolling mean with shift(1) to avoid future leakage
            rolling_diff = digit_df['total_diff_coins'].rolling(window=window, min_periods=1).mean().shift(1).fillna(0)
            rolling_games = digit_df['total_games'].rolling(window=window, min_periods=1).mean().shift(1).fillna(0)
            rolling_efficiency = digit_df['efficiency'].rolling(window=window, min_periods=1).mean().shift(1).fillna(0)
            rolling_machines = digit_df['machine_count'].rolling(window=window, min_periods=1).mean().shift(1).fillna(0)

            # Assign back to dataframe
            df_copy.loc[digit_mask, f'rolling_avg_diff_{window}d'] = rolling_diff.values
            df_copy.loc[digit_mask, f'rolling_avg_games_{window}d'] = rolling_games.values
            df_copy.loc[digit_mask, f'rolling_avg_efficiency_{window}d'] = rolling_efficiency.values
            df_copy.loc[digit_mask, f'rolling_avg_machines_{window}d'] = rolling_machines.values

    return df_copy


def create_feature_set(df):
    """Create 18D feature set."""

    # Select target variables
    targets = ['is_rank_1', 'is_top_3', 'is_top_5']

    # Select 18D features
    features_18d = [
        'month_progress',
        'days_since_last_rank1',
        'rolling_avg_diff_7d', 'rolling_avg_diff_14d', 'rolling_avg_diff_21d', 'rolling_avg_diff_28d', 'rolling_avg_diff_35d',
        'rolling_avg_games_7d', 'rolling_avg_games_14d', 'rolling_avg_games_21d', 'rolling_avg_games_28d', 'rolling_avg_games_35d',
        'rolling_avg_efficiency_7d', 'rolling_avg_efficiency_14d', 'rolling_avg_efficiency_21d', 'rolling_avg_efficiency_28d', 'rolling_avg_efficiency_35d',
        'machine_count'
    ]

    # Create feature matrix
    X = df[features_18d].copy()

    # Ensure all features are numeric
    X = X.astype(np.float32)

    # Create metadata
    metadata = df[['date', 'last_digit']].copy()

    return X, targets, features_18d, metadata, df


def create_eda_report(df):
    """Create exploratory data analysis visualizations."""

    # 1. Sample counts by digit
    digit_counts = df.groupby('last_digit').size()

    fig1 = go.Figure()
    fig1.add_trace(go.Bar(
        x=digit_counts.index,
        y=digit_counts.values,
        marker_color='#636EFA',
        name='Sample Count'
    ))
    fig1.update_layout(
        title='Sample Count by Last-Digit',
        xaxis_title='Last Digit',
        yaxis_title='Count',
        height=400
    )
    fig1.write_html(RESULTS_DIR / 'eda_01_sample_counts.html')

    # 2. Rank rates by digit
    fig2 = go.Figure()

    for target, color in [('is_rank_1', '#EF553B'), ('is_top_3', '#636EFA'), ('is_top_5', '#00CC96')]:
        rank_rates = df.groupby('last_digit')[target].mean() * 100
        fig2.add_trace(go.Bar(
            x=rank_rates.index,
            y=rank_rates.values,
            name=target.replace('is_', ''),
            marker_color=color
        ))

    fig2.update_layout(
        title='Rank Achievement Rate by Last-Digit',
        xaxis_title='Last Digit',
        yaxis_title='Rate (%)',
        barmode='group',
        height=400
    )
    fig2.write_html(RESULTS_DIR / 'eda_02_rank_rates.html')

    # 3. Feature distributions
    feature_cols = ['total_games', 'total_diff_coins', 'efficiency', 'machine_count']

    fig3 = make_subplots(
        rows=2, cols=2,
        subplot_titles=[f'Distribution: {col}' for col in feature_cols]
    )

    for idx, col in enumerate(feature_cols, 1):
        row, col_idx = (idx - 1) // 2 + 1, (idx - 1) % 2 + 1
        fig3.add_trace(
            go.Box(y=df[col], name=col, showlegend=False),
            row=row, col=col_idx
        )

    fig3.update_layout(height=600, title='Feature Distributions')
    fig3.write_html(RESULTS_DIR / 'eda_03_distributions.html')

    print(f"EDA reports saved to {RESULTS_DIR}")
    print(f"\n[OK] Sample counts by digit: {len(digit_counts)} groups")
    print(f"[OK] Rank rate summary generated")


def save_features_to_csv(df, X, targets, features_18d, metadata):
    """Save features to CSV for model training."""

    # Create output dataframe
    output_df = metadata.copy()

    # Add targets
    for target in targets:
        output_df[target] = df[target].values

    # Add features
    for i, feat in enumerate(features_18d):
        output_df[feat] = X.iloc[:, i].values

    # Save
    output_path = RESULTS_DIR / 'features_18d_last_digit.csv'
    output_df.to_csv(output_path, index=False)

    print(f"\n[OK] Features saved to {output_path}")
    print(f"  Shape: {output_df.shape}")
    print(f"  Columns: {list(output_df.columns)}")


def main():
    """Main execution flow."""

    print("=" * 80)
    print("Phase 9-1: Last-Digit Feature Engineering")
    print("=" * 80)

    # Step 1: Load data
    print("\n[1] Loading last_digit_summary_all...")
    df = load_last_digit_summary(DB_PATH)
    print(f"  Loaded {len(df)} records")
    print(f"  Date range: {df['date'].min()} to {df['date'].max()}")
    unique_digits = sorted(df['last_digit'].unique())
    print(f"  Unique last_digits: {len(unique_digits)} groups")

    # Step 2: Compute digit ranks on each date
    print("\n[2] Computing digit ranks by date...")
    df = compute_digit_ranks_by_date(df)
    print(f"  Rank flags computed (is_rank_1, is_top_3, is_top_5)")

    # Step 3: Compute days_since_last_rank1
    print("\n[3] Computing days_since_last_rank1...")
    df = compute_days_since_last_rank1(df)

    # Step 4: Compute month_progress
    print("\n[4] Computing month_progress...")
    df = compute_month_progress(df)

    # Step 5: Compute rolling averages
    print("\n[5] Computing rolling averages (7/14/21/28/35 days)...")
    df = compute_rolling_averages(df, windows=[7, 14, 21, 28, 35])

    # Step 6: Create 18D feature set
    print("\n[6] Creating 18D feature set...")
    X, targets, features_18d, metadata, df_final = create_feature_set(df)
    print(f"  Feature matrix shape: {X.shape}")
    print(f"  Features: {features_18d}")

    # Step 7: Create EDA report
    print("\n[7] Creating EDA report...")
    create_eda_report(df_final)

    # Step 8: Save to CSV
    print("\n[8] Saving features to CSV...")
    save_features_to_csv(df_final, X, targets, features_18d, metadata)

    # Step 9: Summary statistics
    print("\n" + "=" * 80)
    print("SUMMARY STATISTICS")
    print("=" * 80)

    for i, digit in enumerate(sorted(df_final['last_digit'].unique())):
        digit_data = df_final[df_final['last_digit'] == digit]
        print(f"\nDigit {i} (n={len(digit_data)})")
        print(f"  Rank1 rate: {digit_data['is_rank_1'].mean()*100:.2f}%")
        print(f"  Top3 rate:  {digit_data['is_top_3'].mean()*100:.2f}%")
        print(f"  Top5 rate:  {digit_data['is_top_5'].mean()*100:.2f}%")
        print(f"  Avg machines: {digit_data['machine_count'].mean():.1f}")

    print("\n[OK] Phase 9-1 Complete!")
    print(f"Results saved to: {RESULTS_DIR}")


if __name__ == '__main__':
    main()
