"""
Phase 7-6: DD Feature Importance Analysis

Analyzes the importance of DD (月内の日付 01-31) for rank prediction.
Compares 16D (without DD) vs 17D (with DD) models on properly time-series split data.

Based on phase7_05_rank_prediction_18d_comparison.py but focuses on DD contribution.
"""

import sqlite3
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.preprocessing import TargetEncoder
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss
import xgboost as xgb
import json
from datetime import datetime

PROJECT_ROOT = Path("C:\\Users\\apto117\\Documents\\pachinko-analyzer\\src\\2026project")
sys.path.insert(0, str(PROJECT_ROOT))

COPY_DB = PROJECT_ROOT / "db" / "experiments" / "マルハンメガシティ2000-蒲田7_rank_exp.db"
RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase7_dd_feature_importance"
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


def compute_days_since_last_rank1(df):
    """Compute days since last rank_1 for each machine per date."""
    days_since = []

    for machine_name in df['machine_name'].unique():
        machine_df = df[df['machine_name'] == machine_name].copy().reset_index(drop=True)

        rank1_dates = machine_df[machine_df['is_rank_1'] == 1]['date'].values

        for idx, row in machine_df.iterrows():
            current_date = row['date']

            # Find last rank_1 date
            last_rank1_dates = rank1_dates[rank1_dates < current_date]

            if len(last_rank1_dates) > 0:
                days = (current_date - last_rank1_dates[-1]).days
                days = min(days, 365)
            else:
                days = 365

            days_since.append(days)

    return np.array(days_since)


def prepare_16d_features(df):
    """Prepare 16D base features (without DD)."""
    X_16d = []
    days_since_last_rank1 = compute_days_since_last_rank1(df)

    for idx, row in df.iterrows():
        features = []

        # 1. Month progress (1D)
        day_of_month = row['date'].day
        days_in_month = (pd.to_datetime(row['date']) + pd.DateOffset(months=1)).replace(day=1) - pd.Timedelta(days=1)
        month_progress = day_of_month / days_in_month.day
        features.append(month_progress)

        # 2. Days since last rank_1 (1D)
        features.append(float(days_since_last_rank1[idx]))

        # 3. Rolling average features (14D)
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


def prepare_17d_with_dd(df, X_16d):
    """Add DD feature (target-encoded) to 16D base features."""
    # DD: day of month (1-31)
    dd_values = df['date'].dt.day.values

    return dd_values, X_16d


def train_and_compare(X_16d, dd_values, y_dict, dates):
    """Train models with and without DD feature."""
    results = {}

    # Time-series split
    unique_dates = pd.Series(dates).unique()
    split_date_idx = len(unique_dates) - 57
    split_date = unique_dates[split_date_idx]

    train_mask = dates < split_date
    test_mask = dates >= split_date

    X_train_16d = X_16d[train_mask]
    X_test_16d = X_16d[test_mask]
    dd_train = dd_values[train_mask]
    dd_test = dd_values[test_mask]

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

        # Model 1: 16D base (without DD)
        print(f"\n[Model 1: Base 16D (without DD)]")
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

        # Model 2: 17D with DD (target-encoded)
        print(f"\n[Model 2: With DD 17D (target-encoded)]")

        te = TargetEncoder(smooth=1.0)
        dd_train_encoded = te.fit_transform(dd_train.reshape(-1, 1), y_train).reshape(-1)
        dd_test_encoded = te.transform(dd_test.reshape(-1, 1)).reshape(-1)

        X_train_17d = np.column_stack([X_train_16d, dd_train_encoded])
        X_test_17d = np.column_stack([X_test_16d, dd_test_encoded])

        model_17d = xgb.XGBClassifier(
            objective='binary:logistic',
            max_depth=3,
            learning_rate=0.01,
            n_estimators=200,
            random_state=42,
            eval_metric='logloss',
            verbosity=0
        )
        model_17d.fit(X_train_17d, y_train, verbose=False)

        y_pred_17d = model_17d.predict_proba(X_test_17d)[:, 1]
        auc_17d = roc_auc_score(y_test, y_pred_17d)
        ap_17d = average_precision_score(y_test, y_pred_17d)

        importance_17d = model_17d.feature_importances_

        print(f"  AUC: {auc_17d:.4f}")
        print(f"  AP:  {ap_17d:.4f}")

        # Comparison
        auc_delta = (auc_17d - auc_16d) / auc_16d * 100
        dd_importance = importance_17d[-1]
        dd_rank = int(np.argsort(importance_17d)[::-1].tolist().index(len(importance_17d) - 1)) + 1

        print(f"\n[Comparison]")
        print(f"  AUC delta:           {auc_delta:+.2f}%")
        print(f"  DD feature importance: {dd_importance:.4f}")
        print(f"  DD rank among 17 features: #{dd_rank}")

        # Store results
        feature_names = [
            'month_progress', 'days_since_last_rank1',
            'avg_diff_7d', 'avg_diff_14d', 'avg_diff_21d', 'avg_diff_28d', 'avg_diff_35d',
            'avg_games_7d', 'avg_games_14d', 'avg_games_21d', 'avg_games_28d', 'avg_games_35d',
            'avg_efficiency_7d', 'avg_efficiency_14d', 'avg_efficiency_28d',
            'machine_count'
        ]
        feature_names_17d = feature_names + ['dd_encoded']

        results[target_name] = {
            'base_16d': {
                'auc': float(auc_16d),
                'ap': float(ap_16d),
                'feature_importances': {name: float(imp) for name, imp in zip(feature_names, importance_16d)}
            },
            'with_dd_17d': {
                'auc': float(auc_17d),
                'ap': float(ap_17d),
                'feature_importances': {name: float(imp) for name, imp in zip(feature_names_17d, importance_17d)}
            },
            'comparison': {
                'auc_base': float(auc_16d),
                'auc_with_dd': float(auc_17d),
                'auc_delta_pct': float(auc_delta),
                'ap_base': float(ap_16d),
                'ap_with_dd': float(ap_17d),
                'dd_importance': float(dd_importance),
                'dd_rank': int(dd_rank)
            }
        }

    return results


def main():
    print("="*70)
    print("Phase 7-6: DD Feature Importance Analysis")
    print("="*70)

    # Load data
    print("\n[Loading data...]")
    df = load_data(COPY_DB)
    print(f"  Loaded {len(df)} rows, {len(df['machine_name'].unique())} machines")

    # Prepare base features
    print("\n[Preparing 16D base features...]")
    X_16d = prepare_16d_features(df)
    print(f"  Base feature matrix shape: {X_16d.shape}")

    # Extract DD values
    print("\n[Extracting DD (day of month) values...]")
    dd_values, X_16d = prepare_17d_with_dd(df, X_16d)
    print(f"  DD range: {dd_values.min()}-{dd_values.max()}")

    # Prepare target variables
    y_dict = {
        'is_rank_1': df['is_rank_1'].values,
        'is_top_3': df['is_top_3'].values,
        'is_top_5': df['is_top_5'].values
    }

    dates = df['date'].values

    # Train and compare
    print("\n[Training and comparing models...]")
    all_results = train_and_compare(X_16d, dd_values, y_dict, dates)

    # Save results
    output_file = RESULTS_DIR / "dd_feature_importance_analysis.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\n[COMPLETED] Results saved to {output_file}")

    # Print summary
    print("\n" + "="*70)
    print("SUMMARY: DD Feature Impact")
    print("="*70)
    for target_name in ['rank_1', 'top_3', 'top_5']:
        comp = all_results[target_name]['comparison']
        print(f"\n{target_name.upper()}:")
        print(f"  Base 16D AUC:      {comp['auc_base']:.4f}")
        print(f"  With DD 17D AUC:   {comp['auc_with_dd']:.4f}")
        print(f"  AUC improvement:   {comp['auc_delta_pct']:+.2f}%")
        print(f"  DD importance:     {comp['dd_importance']:.4f} (rank #{comp['dd_rank']})")


if __name__ == '__main__':
    main()
