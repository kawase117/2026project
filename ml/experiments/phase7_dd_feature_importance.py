"""
Phase 7: DD (Day of Month) Feature Importance Analysis

Analyzes the importance of DD (月内の日付 01-31) feature for rank prediction.
Compares models with and without DD feature to quantify its contribution.

DD Features:
- dd: Day of month (1-31) as integer
- dd_categorical: Target-encoded DD feature
"""

import sqlite3
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.preprocessing import TargetEncoder
from sklearn.metrics import roc_auc_score, roc_curve
import xgboost as xgb
import json
from datetime import datetime

PROJECT_ROOT = Path("C:/Users/apto117/Documents/pachinko-analyzer/src/2026project")
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "db" / "experiments" / "マルハンメガシティ2000-蒲田7_rank_exp.db"
RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase7_dd_feature_importance"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def load_data(db_path):
    """Load data from experiment DB."""
    conn = sqlite3.connect(db_path)

    df_machine = pd.read_sql_query("""
        SELECT
            date, machine_name, machine_count,
            avg_diff_7d, avg_diff_14d, avg_diff_21d, avg_diff_28d, avg_diff_35d,
            avg_games_7d, avg_games_14d, avg_games_21d, avg_games_28d, avg_games_35d,
            avg_efficiency_7d, avg_efficiency_14d, avg_efficiency_21d, avg_efficiency_28d,
            avg_rank_diff_7d, avg_rank_diff_14d, avg_rank_diff_21d, avg_rank_diff_28d, avg_rank_diff_35d,
            is_rank_1, is_top_3, is_top_5
        FROM daily_machine_type_summary
        ORDER BY date, machine_name
    """, conn)

    conn.close()

    df_machine['date'] = pd.to_datetime(df_machine['date'], format='%Y%m%d')
    df_machine = df_machine.sort_values(['machine_name', 'date']).reset_index(drop=True)

    return df_machine


def prepare_base_features(df):
    """
    Prepare 16D base feature set (without DD).

    Base 16D:
    - month_progress (1D)
    - is_weekend (1D)
    - days_since_last_rank1 (1D)
    - rolling averages for diff (5D)
    - rolling averages for games (5D)
    - rolling averages for efficiency (3D)  # 7d, 14d, 28d
    """
    X_features = []
    feature_names = []

    # Calculate days_since_last_rank1 per machine
    df_with_days = df.copy()
    df_with_days['days_since_last_rank1'] = 0

    for machine_name in df['machine_name'].unique():
        mask = df_with_days['machine_name'] == machine_name
        machine_df = df_with_days[mask].copy()

        last_rank1_date = None
        days_since = []

        for idx, row in machine_df.iterrows():
            if row['is_rank_1'] == 1:
                last_rank1_date = row['date']

            if last_rank1_date is not None:
                days_diff = (row['date'] - last_rank1_date).days
            else:
                days_diff = 365

            days_since.append(days_diff)

        df_with_days.loc[mask, 'days_since_last_rank1'] = days_since

    # Build feature matrix
    for idx, row in df_with_days.iterrows():
        features = []

        # month_progress (1-31 → 0.0-1.0)
        month_progress = row['date'].day / 31.0
        features.append(month_progress)

        # is_weekend (Fri=1, Sat=1, Sun=1, else=0)
        is_weekend = 1.0 if row['date'].weekday() >= 4 else 0.0
        features.append(is_weekend)

        # days_since_last_rank1
        features.append(row['days_since_last_rank1'])

        # Diff rolling averages (5D)
        for col in ['avg_diff_7d', 'avg_diff_14d', 'avg_diff_21d', 'avg_diff_28d', 'avg_diff_35d']:
            features.append(row[col] if pd.notna(row[col]) else 0)

        # Games rolling averages (5D)
        for col in ['avg_games_7d', 'avg_games_14d', 'avg_games_21d', 'avg_games_28d', 'avg_games_35d']:
            features.append(row[col] if pd.notna(row[col]) else 0)

        # Efficiency rolling averages (3D: 7d, 14d, 28d)
        for col in ['avg_efficiency_7d', 'avg_efficiency_14d', 'avg_efficiency_28d']:
            features.append(row[col] if pd.notna(row[col]) else 0)

        # machine_count
        features.append(row['machine_count'] if pd.notna(row['machine_count']) else 0)

        X_features.append(features)

    feature_names = [
        'month_progress',
        'is_weekend',
        'days_since_last_rank1',
        'avg_diff_7d', 'avg_diff_14d', 'avg_diff_21d', 'avg_diff_28d', 'avg_diff_35d',
        'avg_games_7d', 'avg_games_14d', 'avg_games_21d', 'avg_games_28d', 'avg_games_35d',
        'avg_efficiency_7d', 'avg_efficiency_14d', 'avg_efficiency_28d',
        'machine_count'
    ]

    X = np.array(X_features, dtype=np.float32)

    return X, feature_names, df_with_days


def train_and_evaluate_models(X_base, dd_values, y, feature_names_base, dates, target_name):
    """
    Train two models with proper time-series split:
    1. Without DD feature (16D)
    2. With DD feature (17D after target encoding)

    Uses last 57 unique dates for test (to avoid data leakage).
    """
    results = {}

    # Time-series split: train on past, test on future
    unique_dates = pd.Series(dates).unique()
    split_date_idx = len(unique_dates) - 57
    split_date = unique_dates[split_date_idx]

    train_mask = dates < split_date
    test_mask = dates >= split_date

    X_train, X_test = X_base[train_mask], X_base[test_mask]
    dd_train, dd_test = dd_values[train_mask], dd_values[test_mask]
    y_train, y_test = y[train_mask], y[test_mask]

    # Model 1: Base 16D (without DD)
    model_base = xgb.XGBClassifier(
        objective='binary:logistic',
        max_depth=3,
        learning_rate=0.01,
        n_estimators=200,
        random_state=42,
        eval_metric='logloss',
        verbosity=0
    )
    model_base.fit(X_train, y_train, verbose=False)

    y_pred_base = model_base.predict_proba(X_test)[:, 1]
    auc_base = roc_auc_score(y_test, y_pred_base)

    # Get feature importance for base model
    importance_base = model_base.feature_importances_

    results['base_16d'] = {
        'auc': float(auc_base),
        'n_features': 16,
        'feature_importances': {name: float(imp) for name, imp in zip(feature_names_base, importance_base)}
    }

    # Model 2: With DD feature (target encoded)
    te = TargetEncoder(smooth=1.0)
    dd_train_encoded = te.fit_transform(dd_train.reshape(-1, 1), y_train).reshape(-1)
    dd_test_encoded = te.transform(dd_test.reshape(-1, 1)).reshape(-1)

    X_train_with_dd = np.column_stack([X_train, dd_train_encoded])
    X_test_with_dd = np.column_stack([X_test, dd_test_encoded])

    model_with_dd = xgb.XGBClassifier(
        objective='binary:logistic',
        max_depth=3,
        learning_rate=0.01,
        n_estimators=200,
        random_state=42,
        eval_metric='logloss',
        verbosity=0
    )
    model_with_dd.fit(X_train_with_dd, y_train, verbose=False)

    y_pred_with_dd = model_with_dd.predict_proba(X_test_with_dd)[:, 1]
    auc_with_dd = roc_auc_score(y_test, y_pred_with_dd)

    # Get feature importance for model with DD
    importance_with_dd = model_with_dd.feature_importances_

    feature_names_with_dd = feature_names_base + ['dd_encoded']

    results['with_dd_17d'] = {
        'auc': float(auc_with_dd),
        'n_features': 17,
        'feature_importances': {name: float(imp) for name, imp in zip(feature_names_with_dd, importance_with_dd)}
    }

    # Calculate improvement
    auc_improvement = (auc_with_dd - auc_base) / auc_base * 100  # percentage

    results['comparison'] = {
        'base_auc': float(auc_base),
        'with_dd_auc': float(auc_with_dd),
        'auc_improvement_pct': float(auc_improvement),
        'dd_feature_importance': float(importance_with_dd[-1]),  # DD importance
        'dd_importance_rank': int(np.argsort(importance_with_dd)[::-1].tolist().index(len(importance_with_dd) - 1)) + 1
    }

    return results


def main():
    print("=" * 60)
    print("Phase 7: DD Feature Importance Analysis")
    print("=" * 60)

    # Load data
    print("\n[Loading data...]")
    df = load_data(DB_PATH)
    print(f"   Loaded {len(df)} rows from {len(df['machine_name'].unique())} machines")

    # Prepare base features
    print("\n[Preparing base features (16D)...]")
    X_base, feature_names_base, df_prepared = prepare_base_features(df)
    print(f"   Base feature matrix shape: {X_base.shape}")

    # Extract DD values
    print("\n[Extracting DD (day of month) feature...]")
    dd_values = df_prepared['date'].dt.day.values
    print(f"   DD values range: {dd_values.min()}-{dd_values.max()}")

    # Analyze for each target
    targets = {
        'rank_1': 'is_rank_1',
        'top_3': 'is_top_3',
        'top_5': 'is_top_5'
    }

    all_results = {}

    # Get dates for time-series split
    dates = df_prepared['date'].values

    for target_key, target_col in targets.items():
        print(f"\n[Analyzing {target_key}...]")
        y = df_prepared[target_col].values
        print(f"   Positive samples: {y.sum()} / {len(y)} ({y.sum()/len(y)*100:.2f}%)")

        results = train_and_evaluate_models(X_base, dd_values, y, feature_names_base, dates, target_key)
        all_results[target_key] = results

        # Print results
        comp = results['comparison']
        print(f"   Base (16D) AUC:    {comp['base_auc']:.4f}")
        print(f"   With DD (17D) AUC: {comp['with_dd_auc']:.4f}")
        print(f"   Improvement:       {comp['auc_improvement_pct']:+.2f}%")
        print(f"   DD feature importance: {comp['dd_feature_importance']:.4f}")
        print(f"   DD rank among 17 features: #{comp['dd_importance_rank']}")

    # Save results
    output_file = RESULTS_DIR / "dd_feature_importance_analysis.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\n[COMPLETED] Results saved to {output_file}")

    # Print summary table
    print("\n" + "=" * 60)
    print("SUMMARY: DD Feature Impact Across Targets")
    print("=" * 60)
    for target_key, results in all_results.items():
        comp = results['comparison']
        print(f"\n{target_key.upper()}:")
        print(f"  Base 16D AUC:       {comp['base_auc']:.4f}")
        print(f"  With DD 17D AUC:    {comp['with_dd_auc']:.4f}")
        print(f"  ΔAUC:               {comp['auc_improvement_pct']:+.2f}%")
        print(f"  DD importance:      {comp['dd_feature_importance']:.4f} (rank #{comp['dd_importance_rank']})")


if __name__ == '__main__':
    main()
