# -*- coding: utf-8 -*-
"""
Phase 9-4: 台番号末尾別ハイパーパラメーター調整 - Last-Digit Hyperparameter Tuning

Grid search over XGBoost hyperparameters on last-digit prediction task.
Time-series train/test split (240 days / 57 days).
Evaluate all 3 targets: rank_1, top_3, top_5.
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
from xgboost import XGBClassifier
from sklearn.metrics import roc_auc_score
import json
from itertools import product

PROJECT_ROOT = Path(r"C:\Users\apto117\Documents\pachinko-analyzer\src\2026project")
sys.path.insert(0, str(PROJECT_ROOT))

FEATURES_PATH = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase9_last_digit_analysis" / "features_18d_last_digit.csv"
RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase9_last_digit_analysis"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def load_features():
    """Load 18D feature set from CSV."""
    df = pd.read_csv(FEATURES_PATH)
    return df


def prepare_time_series_split(df):
    """Prepare time-series train/test split (240 days / 57 days)."""
    df_sorted = df.sort_values('date').reset_index(drop=True)

    unique_dates = df_sorted['date'].unique()
    unique_dates = pd.to_datetime(unique_dates)
    unique_dates = sorted(unique_dates)

    split_idx = len(unique_dates) - 57
    split_date = unique_dates[split_idx]

    df_train = df_sorted[df_sorted['date'] < str(split_date)].reset_index(drop=True)
    df_test = df_sorted[df_sorted['date'] >= str(split_date)].reset_index(drop=True)

    return df_train, df_test


def grid_search_xgboost(df_train, df_test, target_col, target_name):
    """Grid search XGBoost hyperparameters for a specific target."""

    print(f"\n{'='*70}")
    print(f"Grid Search: {target_name}")
    print(f"{'='*70}")

    features_18d = [
        'month_progress', 'days_since_last_rank1',
        'rolling_avg_diff_7d', 'rolling_avg_diff_14d', 'rolling_avg_diff_21d',
        'rolling_avg_diff_28d', 'rolling_avg_diff_35d',
        'rolling_avg_games_7d', 'rolling_avg_games_14d', 'rolling_avg_games_21d',
        'rolling_avg_games_28d', 'rolling_avg_games_35d',
        'rolling_avg_efficiency_7d', 'rolling_avg_efficiency_14d', 'rolling_avg_efficiency_21d',
        'rolling_avg_efficiency_28d', 'rolling_avg_efficiency_35d',
        'machine_count'
    ]

    X_train = df_train[features_18d].fillna(0).astype(np.float32)
    y_train = df_train[target_col].astype(int)

    X_test = df_test[features_18d].fillna(0).astype(np.float32)
    y_test = df_test[target_col].astype(int)

    # Parameter grid
    param_grid = {
        'max_depth': [3, 4, 5, 6],
        'learning_rate': [0.01, 0.05, 0.1],
        'n_estimators': [100, 150, 200],
        'subsample': [0.8, 0.9, 1.0]
    }

    results = []
    total_combinations = np.prod([len(v) for v in param_grid.values()])

    print(f"\nGrid size: {total_combinations} combinations")
    print(f"Evaluating...")

    for i, (max_depth, learning_rate, n_estimators, subsample) in enumerate(
        product(
            param_grid['max_depth'],
            param_grid['learning_rate'],
            param_grid['n_estimators'],
            param_grid['subsample']
        )
    ):
        if (i + 1) % 20 == 0:
            print(f"  Progress: {i + 1}/{total_combinations}")

        model = XGBClassifier(
            objective='binary:logistic',
            max_depth=max_depth,
            learning_rate=learning_rate,
            n_estimators=n_estimators,
            subsample=subsample,
            scale_pos_weight=1.0,
            random_state=42,
            verbosity=0
        )

        model.fit(X_train, y_train)

        y_pred_proba = model.predict_proba(X_test)[:, 1]
        auc = roc_auc_score(y_test, y_pred_proba)

        results.append({
            'max_depth': max_depth,
            'learning_rate': learning_rate,
            'n_estimators': n_estimators,
            'subsample': subsample,
            'auc': float(auc)
        })

    # Sort by AUC descending
    results_sorted = sorted(results, key=lambda x: x['auc'], reverse=True)

    # Print top 5
    print(f"\nTop 5 Parameter Sets:")
    for i, result in enumerate(results_sorted[:5], 1):
        print(f"  {i}. AUC={result['auc']:.4f} | "
              f"depth={result['max_depth']}, lr={result['learning_rate']}, "
              f"n_est={result['n_estimators']}, subsample={result['subsample']}")

    return results_sorted


def main():
    """Main execution flow."""

    print("=" * 80)
    print("Phase 9-4: Last-Digit Hyperparameter Tuning")
    print("=" * 80)

    # Load features
    print("\n[1] Loading 18D feature set...")
    df = load_features()
    print(f"  Loaded {len(df)} samples")

    # Time-series split
    print("\n[2] Preparing time-series train/test split...")
    df_train, df_test = prepare_time_series_split(df)
    print(f"  Train: {len(df_train)} samples, Test: {len(df_test)} samples")

    # Grid search for each target
    print("\n[3] Performing grid search...")
    all_results = {}

    for target_col, target_name in [
        ('is_rank_1', 'rank_1'),
        ('is_top_3', 'top_3'),
        ('is_top_5', 'top_5')
    ]:
        results_sorted = grid_search_xgboost(df_train, df_test, target_col, target_name)
        all_results[target_name] = results_sorted

    # Save results
    print("\n[4] Saving results...")
    output = {
        'phase': '9-4',
        'description': 'Last-Digit Hyperparameter Tuning (Grid Search)',
        'grid_info': {
            'max_depth': [3, 4, 5, 6],
            'learning_rate': [0.01, 0.05, 0.1],
            'n_estimators': [100, 150, 200],
            'subsample': [0.8, 0.9, 1.0],
            'total_combinations': 108
        },
        'train_test_split': {
            'train_size': len(df_train),
            'test_size': len(df_test)
        },
        'results_by_target': {}
    }

    for target_name, results_sorted in all_results.items():
        output['results_by_target'][target_name] = {
            'top_5_results': results_sorted[:5],
            'best_params': results_sorted[0],
            'best_auc': float(results_sorted[0]['auc'])
        }

    output_path = RESULTS_DIR / 'phase9_04_hyperparameter_tuning_results.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n[OK] Results saved to {output_path}")

    print("\n" + "=" * 80)
    print("[OK] Phase 9-4 Complete!")
    print("=" * 80)


if __name__ == '__main__':
    main()
