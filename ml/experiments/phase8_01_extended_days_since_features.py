"""
Phase 8-1: Extended Days-Since Features (Rank1/Rank3/Rank5 Hierarchy)

Adds days_since_last_rank3 and days_since_last_rank5, along with variations:
- Individual features: days_since_rank1, days_since_rank3, days_since_rank5
- Ratios: rank3/rank1, rank5/rank1, rank5/rank3
- Differences: rank1-rank3, rank1-rank5, rank3-rank5
- Composite: max(rank1,rank3,rank5) as "days_since_any_top"

Compares 16D baseline vs ~25D extended model to determine which features are worth keeping.
"""

import sqlite3
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.preprocessing import TargetEncoder
from sklearn.metrics import roc_auc_score, average_precision_score
import xgboost as xgb
import json
from datetime import datetime

PROJECT_ROOT = Path("C:\\Users\\apto117\\Documents\\pachinko-analyzer\\src\\2026project")
sys.path.insert(0, str(PROJECT_ROOT))

COPY_DB = PROJECT_ROOT / "db" / "experiments" / "マルハンメガシティ2000-蒲田7_rank_exp.db"
RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase8_extended_features"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def load_data(db_path):
    """Load data from copy DB."""
    conn = sqlite3.connect(db_path)

    df_machine = pd.read_sql_query("""
        SELECT
            date, machine_name, machine_count,
            avg_diff_7d, avg_diff_14d, avg_diff_21d, avg_diff_28d, avg_diff_35d,
            avg_games_7d, avg_games_14d, avg_games_21d, avg_games_28d, avg_games_35d,
            avg_efficiency_7d, avg_efficiency_14d, avg_efficiency_21d, avg_efficiency_28d,
            is_rank_1, is_top_3, is_top_5
        FROM daily_machine_type_summary
        ORDER BY date, machine_name
    """, conn)

    df_hall = pd.read_sql_query("""
        SELECT date
        FROM daily_hall_summary
    """, conn)

    conn.close()

    df_machine['date'] = pd.to_datetime(df_machine['date'], format='%Y%m%d')
    df_hall['date'] = pd.to_datetime(df_hall['date'], format='%Y%m%d')

    df = df_machine.merge(df_hall, on='date', how='left')
    df = df.sort_values(['machine_name', 'date']).reset_index(drop=True)

    return df


def compute_days_since_last_rank(df, rank_column):
    """
    Compute days since last rank for rank_1, top_3, or top_5.

    rank_column: 'is_rank_1', 'is_top_3', or 'is_top_5'
    Returns: numpy array of days (capped at 365)
    """
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
    """Prepare 16D base features (Phase 7 baseline)."""
    X_16d = []
    days_since_rank1 = compute_days_since_last_rank(df, 'is_rank_1')

    for idx, row in df.iterrows():
        features = []

        # Month progress
        day_of_month = row['date'].day
        days_in_month = (pd.to_datetime(row['date']) + pd.DateOffset(months=1)).replace(day=1) - pd.Timedelta(days=1)
        month_progress = day_of_month / days_in_month.day
        features.append(month_progress)

        # Days since last rank_1
        features.append(float(days_since_rank1[idx]))

        # Rolling average features (14D)
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


def prepare_extended_features(df):
    """
    Prepare extended feature set with days_since variations.

    Returns:
    - X_extended: feature matrix
    - feature_names: list of feature names
    """
    X_extended = []
    feature_names = []

    # Compute days_since for all three ranks
    days_since_rank1 = compute_days_since_last_rank(df, 'is_rank_1')
    days_since_rank3 = compute_days_since_last_rank(df, 'is_top_3')
    days_since_rank5 = compute_days_since_last_rank(df, 'is_top_5')

    for idx, row in df.iterrows():
        features = []

        # Month progress
        day_of_month = row['date'].day
        days_in_month = (pd.to_datetime(row['date']) + pd.DateOffset(months=1)).replace(day=1) - pd.Timedelta(days=1)
        month_progress = day_of_month / days_in_month.day
        features.append(month_progress)

        # Individual days_since (3D)
        features.append(float(days_since_rank1[idx]))
        features.append(float(days_since_rank3[idx]))
        features.append(float(days_since_rank5[idx]))

        # Ratios (3D) - avoid division by zero
        r1 = float(days_since_rank1[idx])
        r3 = float(days_since_rank3[idx])
        r5 = float(days_since_rank5[idx])

        # ratio_rank3_to_rank1
        ratio_3_1 = r3 / r1 if r1 > 0 else 1.0
        features.append(ratio_3_1)

        # ratio_rank5_to_rank1
        ratio_5_1 = r5 / r1 if r1 > 0 else 1.0
        features.append(ratio_5_1)

        # ratio_rank5_to_rank3
        ratio_5_3 = r5 / r3 if r3 > 0 else 1.0
        features.append(ratio_5_3)

        # Differences (3D)
        diff_1_3 = r1 - r3
        diff_1_5 = r1 - r5
        diff_3_5 = r3 - r5
        features.extend([diff_1_3, diff_1_5, diff_3_5])

        # Composite (1D)
        days_since_any = max(r1, r3, r5)
        features.append(days_since_any)

        # Rolling average features (14D) - same as 16D baseline
        rolling_cols = [
            'avg_diff_7d', 'avg_diff_14d', 'avg_diff_21d', 'avg_diff_28d', 'avg_diff_35d',
            'avg_games_7d', 'avg_games_14d', 'avg_games_21d', 'avg_games_28d', 'avg_games_35d',
            'avg_efficiency_7d', 'avg_efficiency_14d', 'avg_efficiency_28d',
            'machine_count'
        ]
        rolling_vals = [float(row[col]) if col in row and pd.notna(row[col]) else 0.0 for col in rolling_cols]
        features.extend(rolling_vals)

        X_extended.append(features)

    # Build feature names
    feature_names = [
        'month_progress',
        'days_since_rank1', 'days_since_rank3', 'days_since_rank5',
        'ratio_rank3_to_rank1', 'ratio_rank5_to_rank1', 'ratio_rank5_to_rank3',
        'diff_rank1_minus_rank3', 'diff_rank1_minus_rank5', 'diff_rank3_minus_rank5',
        'days_since_any',
        'avg_diff_7d', 'avg_diff_14d', 'avg_diff_21d', 'avg_diff_28d', 'avg_diff_35d',
        'avg_games_7d', 'avg_games_14d', 'avg_games_21d', 'avg_games_28d', 'avg_games_35d',
        'avg_efficiency_7d', 'avg_efficiency_14d', 'avg_efficiency_28d',
        'machine_count'
    ]

    return np.array(X_extended), feature_names


def train_and_compare(X_16d, X_extended, feature_names_16d, feature_names_extended, y_dict, dates):
    """
    Train 16D and extended models, compare performance.

    Returns:
    - results: dict with baseline, extended, and comparison metrics for each target
    """
    results = {}

    # Time-series split
    unique_dates = pd.Series(dates).unique()
    split_date_idx = len(unique_dates) - 57
    split_date = unique_dates[split_date_idx]

    train_mask = dates < split_date
    test_mask = dates >= split_date

    X_train_16d = X_16d[train_mask]
    X_test_16d = X_16d[test_mask]
    X_train_extended = X_extended[train_mask]
    X_test_extended = X_extended[test_mask]

    print(f"\nTrain dates: {dates[train_mask].min()} to {dates[train_mask].max()}")
    print(f"Test dates:  {dates[test_mask].min()} to {dates[test_mask].max()}")
    print(f"Train size: {train_mask.sum()}, Test size: {test_mask.sum()}")

    targets_to_analyze = {
        'rank_1': y_dict['is_rank_1'],
        'top_3': y_dict['is_top_3'],
        'top_5': y_dict['is_top_5']
    }

    for target_name, y_full in targets_to_analyze.items():
        print(f"\n{'='*70}")
        print(f"Target: {target_name.upper()}")
        print(f"{'='*70}")

        y_train = y_full[train_mask]
        y_test = y_full[test_mask]

        print(f"Positive ratio (train): {y_train.sum() / len(y_train) * 100:.2f}%")
        print(f"Positive ratio (test):  {y_test.sum() / len(y_test) * 100:.2f}%")

        # Model 1: 16D baseline
        print(f"\n[Model 1: 16D Baseline]")
        model_16d = xgb.XGBClassifier(
            objective='binary:logistic',
            max_depth=3,
            learning_rate=0.01,
            n_estimators=200,
            random_state=42,
            eval_metric='logloss',
            verbosity=0
        )
        model_16d.fit(X_train_16d, y_train, verbose=False)

        y_pred_16d = model_16d.predict_proba(X_test_16d)[:, 1]
        auc_16d = roc_auc_score(y_test, y_pred_16d)
        ap_16d = average_precision_score(y_test, y_pred_16d)

        importance_16d = model_16d.feature_importances_

        print(f"  AUC: {auc_16d:.4f}")
        print(f"  AP:  {ap_16d:.4f}")

        # Model 2: Extended with days_since variations
        print(f"\n[Model 2: Extended ~25D with Days-Since Variations]")
        model_extended = xgb.XGBClassifier(
            objective='binary:logistic',
            max_depth=3,
            learning_rate=0.01,
            n_estimators=200,
            random_state=42,
            eval_metric='logloss',
            verbosity=0
        )
        model_extended.fit(X_train_extended, y_train, verbose=False)

        y_pred_extended = model_extended.predict_proba(X_test_extended)[:, 1]
        auc_extended = roc_auc_score(y_test, y_pred_extended)
        ap_extended = average_precision_score(y_test, y_pred_extended)

        importance_extended = model_extended.feature_importances_

        print(f"  AUC: {auc_extended:.4f}")
        print(f"  AP:  {ap_extended:.4f}")

        # Comparison
        auc_delta_pct = (auc_extended - auc_16d) / auc_16d * 100
        ap_delta_pct = (ap_extended - ap_16d) / ap_16d * 100

        print(f"\n[Comparison]")
        print(f"  AUC delta:  {auc_delta_pct:+.2f}%")
        print(f"  AP delta:   {ap_delta_pct:+.2f}%")

        # Top features from extended model
        top_indices = np.argsort(importance_extended)[::-1][:5]
        print(f"\n[Top 5 Features in Extended Model]")
        for rank, idx in enumerate(top_indices, 1):
            print(f"  {rank}. {feature_names_extended[idx]}: {importance_extended[idx]:.4f}")

        # Store results
        results[target_name] = {
            'baseline_16d': {
                'auc': float(auc_16d),
                'ap': float(ap_16d),
                'n_features': 16,
                'feature_importances': {name: float(imp) for name, imp in zip(feature_names_16d, importance_16d)}
            },
            'extended_25d': {
                'auc': float(auc_extended),
                'ap': float(ap_extended),
                'n_features': len(feature_names_extended),
                'feature_importances': {name: float(imp) for name, imp in zip(feature_names_extended, importance_extended)}
            },
            'comparison': {
                'auc_baseline': float(auc_16d),
                'auc_extended': float(auc_extended),
                'auc_delta_pct': float(auc_delta_pct),
                'ap_baseline': float(ap_16d),
                'ap_extended': float(ap_extended),
                'ap_delta_pct': float(ap_delta_pct)
            }
        }

    return results


def main():
    print("="*70)
    print("Phase 8-1: Extended Days-Since Features (Rank1/Rank3/Rank5 Hierarchy)")
    print("="*70)

    # Load data
    print("\n[Loading data...]")
    df = load_data(COPY_DB)
    print(f"  Loaded {len(df)} rows, {len(df['machine_name'].unique())} machines")

    # Prepare 16D baseline
    print("\n[Preparing 16D baseline...]")
    X_16d = prepare_16d_baseline(df)
    feature_names_16d = [
        'month_progress', 'days_since_rank1',
        'avg_diff_7d', 'avg_diff_14d', 'avg_diff_21d', 'avg_diff_28d', 'avg_diff_35d',
        'avg_games_7d', 'avg_games_14d', 'avg_games_21d', 'avg_games_28d', 'avg_games_35d',
        'avg_efficiency_7d', 'avg_efficiency_14d', 'avg_efficiency_28d',
        'machine_count'
    ]
    print(f"  Baseline shape: {X_16d.shape}")

    # Prepare extended features
    print("\n[Preparing extended ~25D features...]")
    X_extended, feature_names_extended = prepare_extended_features(df)
    print(f"  Extended shape: {X_extended.shape}")
    print(f"  New features: {len(feature_names_extended) - len(feature_names_16d)} composite/ratio features")

    # Prepare target variables
    y_dict = {
        'is_rank_1': df['is_rank_1'].values,
        'is_top_3': df['is_top_3'].values,
        'is_top_5': df['is_top_5'].values
    }

    dates = df['date'].values

    # Train and compare
    print("\n[Training and comparing models...]")
    all_results = train_and_compare(X_16d, X_extended, feature_names_16d, feature_names_extended, y_dict, dates)

    # Save results
    output_file = RESULTS_DIR / "phase8_01_extended_features_analysis.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\n[COMPLETED] Results saved to {output_file}")

    # Print summary
    print("\n" + "="*70)
    print("SUMMARY: Extended Features Impact")
    print("="*70)
    for target_name in ['rank_1', 'top_3', 'top_5']:
        comp = all_results[target_name]['comparison']
        print(f"\n{target_name.upper()}:")
        print(f"  Baseline 16D AUC:     {comp['auc_baseline']:.4f}")
        print(f"  Extended 25D AUC:     {comp['auc_extended']:.4f}")
        print(f"  AUC improvement:      {comp['auc_delta_pct']:+.2f}%")
        print(f"  AP improvement:       {comp['ap_delta_pct']:+.2f}%")


if __name__ == '__main__':
    main()
