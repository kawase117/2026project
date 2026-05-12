# -*- coding: utf-8 -*-
"""
Phase 9-1: Feature Engineering - Machine-Type Integration

Purpose: Incorporate machine-type features (jug/hana/oki/bt/"other") into the 16D baseline.

Methodology:
- Load daily_machine_type_summary and machine_master
- Map machine names to machine_type categories
- One-hot encode machine_type (4 binary features, drop first to avoid collinearity)
- Create 20D feature matrix: 16D baseline + 4D machine-type

Output:
- enhanced_features_20d.csv: Full feature matrix with machine-type
- feature_list.json: Feature descriptions and types
- feature_statistics.json: Sample counts by machine_type, NaN handling stats
"""

import sqlite3
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import json

PROJECT_ROOT = Path("C:\\Users\\apto117\\Documents\\pachinko-analyzer\\src\\2026project")
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "db" / "experiments" / "マルハンメガシティ2000-蒲田7_rank_exp.db"
RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase9_machine_type_enhanced"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def load_data_with_machine_type(db_path):
    """Load machine data with machine-type from machine_master table."""
    conn = sqlite3.connect(db_path)

    # Load daily_machine_type_summary
    df_machine = pd.read_sql_query("""
        SELECT
            date, machine_name, machine_count,
            avg_diff_7d, avg_diff_14d, avg_diff_21d, avg_diff_28d, avg_diff_35d,
            avg_games_7d, avg_games_14d, avg_games_21d, avg_games_28d, avg_games_35d,
            avg_efficiency_7d, avg_efficiency_14d, avg_efficiency_21d, avg_efficiency_28d, avg_efficiency_35d,
            is_rank_1, is_top_3, is_top_5
        FROM daily_machine_type_summary
        ORDER BY date, machine_name
    """, conn)

    # Load machine_master with flags
    df_master = pd.read_sql_query("""
        SELECT
            machine_name_normalized,
            jug_flag, hana_flag, oki_flag, bt_flag
        FROM machine_master
    """, conn)

    conn.close()

    # Convert dates
    df_machine['date'] = pd.to_datetime(df_machine['date'], format='%Y%m%d')

    # Join with machine_master on machine_name
    df = df_machine.merge(
        df_master,
        left_on='machine_name',
        right_on='machine_name_normalized',
        how='left'
    )

    # Map flags to machine_type
    def get_machine_type(row):
        if pd.isna(row['jug_flag']):
            return 'other'
        if row['jug_flag']:
            return 'jug'
        if row['hana_flag']:
            return 'hana'
        if row['oki_flag']:
            return 'oki'
        if row['bt_flag']:
            return 'bt'
        return 'other'

    df['machine_type'] = df.apply(get_machine_type, axis=1)

    # Sort for consistency
    df = df.sort_values(['machine_name', 'date']).reset_index(drop=True)

    return df


def compute_days_since_last_rank(df, rank_column):
    """Compute days since last rank for each machine."""
    days_since = []

    for machine_name in df['machine_name'].unique():
        machine_df = df[df['machine_name'] == machine_name].copy().reset_index(drop=True)
        rank_dates = machine_df[machine_df[rank_column] == 1]['date'].values

        for idx, row in machine_df.iterrows():
            current_date = row['date']
            last_rank_dates = rank_dates[rank_dates < current_date]

            if len(last_rank_dates) > 0:
                days = (current_date - last_rank_dates[-1]).days
                days = min(days, 365)
            else:
                days = 365

            days_since.append(days)

    return np.array(days_since)


def prepare_16d_baseline(df):
    """Prepare 16D baseline features (same as Phase 8-3)."""
    X_16d = []
    days_since_rank1 = compute_days_since_last_rank(df, 'is_rank_1')

    for idx, row in df.iterrows():
        features = []

        # Month progress (1D)
        day_of_month = row['date'].day
        days_in_month = (pd.to_datetime(row['date']) + pd.DateOffset(months=1)).replace(day=1) - pd.Timedelta(days=1)
        month_progress = day_of_month / days_in_month.day
        features.append(month_progress)

        # Days since rank_1 (1D)
        features.append(float(days_since_rank1[idx]))

        # Rolling averages (14D)
        rolling_cols = [
            'avg_diff_7d', 'avg_diff_14d', 'avg_diff_21d', 'avg_diff_28d', 'avg_diff_35d',
            'avg_games_7d', 'avg_games_14d', 'avg_games_21d', 'avg_games_28d', 'avg_games_35d',
            'avg_efficiency_7d', 'avg_efficiency_14d', 'avg_efficiency_28d',
            'machine_count'
        ]
        rolling_vals = [float(row[col]) if col in row and pd.notna(row[col]) else 0.0 for col in rolling_cols]
        features.extend(rolling_vals)

        X_16d.append(features)

    return np.array(X_16d)


def prepare_20d_with_machine_type(df):
    """Prepare 20D features: 16D baseline + 4D machine-type one-hot encoding."""
    X_16d = []
    machine_types_list = []
    days_since_rank1 = compute_days_since_last_rank(df, 'is_rank_1')

    for idx, row in df.iterrows():
        features = []

        # Month progress (1D)
        day_of_month = row['date'].day
        days_in_month = (pd.to_datetime(row['date']) + pd.DateOffset(months=1)).replace(day=1) - pd.Timedelta(days=1)
        month_progress = day_of_month / days_in_month.day
        features.append(month_progress)

        # Days since rank_1 (1D)
        features.append(float(days_since_rank1[idx]))

        # Rolling averages (14D)
        rolling_cols = [
            'avg_diff_7d', 'avg_diff_14d', 'avg_diff_21d', 'avg_diff_28d', 'avg_diff_35d',
            'avg_games_7d', 'avg_games_14d', 'avg_games_21d', 'avg_games_28d', 'avg_games_35d',
            'avg_efficiency_7d', 'avg_efficiency_14d', 'avg_efficiency_28d',
            'machine_count'
        ]
        rolling_vals = [float(row[col]) if col in row and pd.notna(row[col]) else 0.0 for col in rolling_cols]
        features.extend(rolling_vals)

        # Machine-type one-hot encoding (4D: hana, oki, bt, other — drop jug as reference)
        machine_type = row['machine_type']
        machine_types_list.append(machine_type)

        # One-hot encode: hana, oki, bt, other (jug is reference/baseline)
        features.append(1.0 if machine_type == 'hana' else 0.0)   # hana feature
        features.append(1.0 if machine_type == 'oki' else 0.0)    # oki feature
        features.append(1.0 if machine_type == 'bt' else 0.0)     # bt feature
        features.append(1.0 if machine_type == 'other' else 0.0)  # other feature

        X_16d.append(features)

    return np.array(X_16d), machine_types_list


def generate_feature_list():
    """Generate feature names and descriptions."""
    feature_list = {
        'baseline_16d': [
            {'index': 0, 'name': 'month_progress', 'type': 'float', 'description': 'Progress through month (day / days_in_month)'},
            {'index': 1, 'name': 'days_since_rank_1', 'type': 'int', 'description': 'Days since machine last ranked rank_1'},
            {'index': 2, 'name': 'avg_diff_7d', 'type': 'float', 'description': 'Average difference (coins) over 7 days'},
            {'index': 3, 'name': 'avg_diff_14d', 'type': 'float', 'description': 'Average difference over 14 days'},
            {'index': 4, 'name': 'avg_diff_21d', 'type': 'float', 'description': 'Average difference over 21 days'},
            {'index': 5, 'name': 'avg_diff_28d', 'type': 'float', 'description': 'Average difference over 28 days'},
            {'index': 6, 'name': 'avg_diff_35d', 'type': 'float', 'description': 'Average difference over 35 days'},
            {'index': 7, 'name': 'avg_games_7d', 'type': 'float', 'description': 'Average games played over 7 days'},
            {'index': 8, 'name': 'avg_games_14d', 'type': 'float', 'description': 'Average games played over 14 days'},
            {'index': 9, 'name': 'avg_games_21d', 'type': 'float', 'description': 'Average games played over 21 days'},
            {'index': 10, 'name': 'avg_games_28d', 'type': 'float', 'description': 'Average games played over 28 days'},
            {'index': 11, 'name': 'avg_games_35d', 'type': 'float', 'description': 'Average games played over 35 days'},
            {'index': 12, 'name': 'avg_efficiency_7d', 'type': 'float', 'description': 'Average efficiency (diff/games) over 7 days'},
            {'index': 13, 'name': 'avg_efficiency_14d', 'type': 'float', 'description': 'Average efficiency over 14 days'},
            {'index': 14, 'name': 'avg_efficiency_28d', 'type': 'float', 'description': 'Average efficiency over 28 days'},
            {'index': 15, 'name': 'machine_count', 'type': 'int', 'description': 'Number of machines of this type'},
        ],
        'machine_type_4d': [
            {'index': 16, 'name': 'machine_type_hana', 'type': 'binary', 'description': 'One-hot: machine type is hana (0=jug)'},
            {'index': 17, 'name': 'machine_type_oki', 'type': 'binary', 'description': 'One-hot: machine type is oki (0=jug)'},
            {'index': 18, 'name': 'machine_type_bt', 'type': 'binary', 'description': 'One-hot: machine type is bt (0=jug)'},
            {'index': 19, 'name': 'machine_type_other', 'type': 'binary', 'description': 'One-hot: machine type is other (0=jug)'},
        ]
    }

    return feature_list


def main():
    print("\n" + "="*70)
    print("Phase 9-1: Feature Engineering - Machine-Type Integration")
    print("="*70)

    # Load data
    print("\n[1/4] Loading data with machine-type...")
    df = load_data_with_machine_type(DB_PATH)
    print(f"  Loaded {len(df)} machine-day records")

    # Compute machine-type distribution
    machine_type_counts = df['machine_type'].value_counts()
    print(f"\nMachine-type distribution:")
    for mtype, count in machine_type_counts.items():
        pct = count / len(df) * 100
        print(f"  {mtype}: {count} ({pct:.2f}%)")

    # Prepare baseline features
    print("\n[2/4] Preparing 16D baseline features...")
    X_16d = prepare_16d_baseline(df)
    print(f"  Shape: {X_16d.shape}")

    # Prepare enhanced features with machine-type
    print("\n[3/4] Preparing 20D features with machine-type encoding...")
    X_20d, machine_types_list = prepare_20d_with_machine_type(df)
    print(f"  Shape: {X_20d.shape}")

    # Verify no NaN values
    nan_count_16d = np.isnan(X_16d).sum()
    nan_count_20d = np.isnan(X_20d).sum()
    print(f"\nNaN validation:")
    print(f"  16D baseline: {nan_count_16d} NaN values")
    print(f"  20D enhanced: {nan_count_20d} NaN values")

    if nan_count_20d > 0:
        print(f"  WARNING: Found {nan_count_20d} NaN values in enhanced features!")
        X_20d = np.nan_to_num(X_20d, nan=0.0)
        print(f"  Replaced NaN with 0.0")

    # Generate feature list
    print("\n[4/4] Generating feature documentation...")
    feature_list = generate_feature_list()

    # Save outputs
    print("\nSaving outputs...")

    # Save enhanced features
    features_output = RESULTS_DIR / "enhanced_features_20d.csv"
    feature_df = pd.DataFrame(X_20d)
    feature_df['date'] = df['date'].values
    feature_df['machine_name'] = df['machine_name'].values
    feature_df['machine_type'] = machine_types_list
    feature_df['is_rank_1'] = df['is_rank_1'].values
    feature_df['is_top_3'] = df['is_top_3'].values
    feature_df['is_top_5'] = df['is_top_5'].values

    feature_df.to_csv(features_output, index=False)
    print(f"  [OK] Features saved to {features_output}")

    # Save feature list
    feature_list_output = RESULTS_DIR / "feature_list.json"
    with open(feature_list_output, 'w', encoding='utf-8') as f:
        json.dump(feature_list, f, indent=2, ensure_ascii=False)
    print(f"  [OK] Feature list saved to {feature_list_output}")

    # Save feature statistics
    feature_stats = {
        'total_samples': len(df),
        'feature_dimensions': {
            'baseline_16d': 16,
            'machine_type_4d': 4,
            'total_20d': 20
        },
        'machine_type_distribution': {
            k: int(v) for k, v in machine_type_counts.items()
        },
        'nan_statistics': {
            'baseline_16d_nan_count': int(nan_count_16d),
            'enhanced_20d_nan_count': int(nan_count_20d)
        },
        'class_balance': {
            'rank_1_positive_rate': float(df['is_rank_1'].sum() / len(df) * 100),
            'top_3_positive_rate': float(df['is_top_3'].sum() / len(df) * 100),
            'top_5_positive_rate': float(df['is_top_5'].sum() / len(df) * 100),
        }
    }

    stats_output = RESULTS_DIR / "feature_statistics.json"
    with open(stats_output, 'w', encoding='utf-8') as f:
        json.dump(feature_stats, f, indent=2, ensure_ascii=False)
    print(f"  [OK] Feature statistics saved to {stats_output}")

    # Summary
    print("\n" + "="*70)
    print("Phase 9-1 Complete!")
    print("="*70)
    print(f"\nSummary:")
    print(f"  Total samples: {len(df)}")
    print(f"  Baseline features: 16D")
    print(f"  Machine-type features: 4D (one-hot encoded, jug=reference)")
    print(f"  Total features: 20D")
    print(f"  Class balance (rank_1): {feature_stats['class_balance']['rank_1_positive_rate']:.2f}% positive")
    print(f"\nNext step: Run Phase 9-2 to train baseline (16D) and enhanced (20D) models")


if __name__ == '__main__':
    main()
