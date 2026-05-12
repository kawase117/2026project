# -*- coding: utf-8 -*-
"""
Phase 9-2: 台番号末尾別の特徴量重要度分析 - Last-Digit Feature Importance Analysis

Trains shallow XGBoost on 18D features to identify top features and prune to optimal subset.
Replicates machine-type finding: rolling_averages expected to dominate (88-89%).
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBClassifier
from sklearn.metrics import roc_auc_score, precision_score, recall_score, f1_score
import json

PROJECT_ROOT = Path(r"C:\Users\apto117\Documents\pachinko-analyzer\src\2026project")
sys.path.insert(0, str(PROJECT_ROOT))

RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase9_last_digit_analysis"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def load_features():
    """Load feature set from CSV (prefer 32D anti-pattern, fall back to 27D)."""
    features_path_32d = RESULTS_DIR / 'features_32d_with_antipattern.csv'
    features_path_27d = RESULTS_DIR / 'features_27d_last_digit_final.csv'

    if features_path_32d.exists():
        df = pd.read_csv(features_path_32d)
        print("  Using 32D features with anti-pattern features (Phase 9-6)")
    elif features_path_27d.exists():
        df = pd.read_csv(features_path_27d)
        print("  Using 27D base features (Phase 9-1)")
    else:
        raise FileNotFoundError("Neither 32D nor 27D feature files found!")

    return df


def prepare_time_series_split(df):
    """Prepare time-series train/test split (240 days / 57 days)."""
    df_sorted = df.sort_values('date').reset_index(drop=True)

    # Get unique dates
    unique_dates = df_sorted['date'].unique()
    unique_dates = pd.to_datetime(unique_dates)
    unique_dates = sorted(unique_dates)

    # 240 days train, 57 days test
    split_idx = len(unique_dates) - 57
    split_date = unique_dates[split_idx]

    df_train = df_sorted[df_sorted['date'] < str(split_date)].reset_index(drop=True)
    df_test = df_sorted[df_sorted['date'] >= str(split_date)].reset_index(drop=True)

    print(f"[Train/Test Split]")
    print(f"  Train: {df_train['date'].min()} to {df_train['date'].max()} ({len(df_train)} samples)")
    print(f"  Test:  {df_test['date'].min()} to {df_test['date'].max()} ({len(df_test)} samples)")

    return df_train, df_test


def compute_feature_importance(df_train, df_test, target_col, target_name):
    """Train XGBoost and compute feature importance."""

    print(f"\n{'='*70}")
    print(f"Feature Importance: {target_name}")
    print(f"{'='*70}")

    # Auto-detect features (all columns except metadata and targets)
    exclude_cols = {'date', 'last_digit', 'is_rank_1', 'is_top_3', 'is_top_5'}
    feature_list = [col for col in df_train.columns if col not in exclude_cols]

    print(f"Using {len(feature_list)} features")

    X_train = df_train[feature_list].fillna(0).astype(np.float32)
    y_train = df_train[target_col].astype(int)

    X_test = df_test[feature_list].fillna(0).astype(np.float32)
    y_test = df_test[target_col].astype(int)

    # Train shallow XGBoost
    model = XGBClassifier(
        objective='binary:logistic',
        max_depth=3,
        learning_rate=0.01,
        n_estimators=200,
        scale_pos_weight=1.0,
        random_state=42,
        verbosity=0
    )

    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

    # Evaluate on test set
    y_pred_proba = model.predict_proba(X_test)[:, 1]
    y_pred = model.predict(X_test)

    auc = roc_auc_score(y_test, y_pred_proba)
    precision = precision_score(y_test, y_pred, zero_division=0)
    recall = recall_score(y_test, y_pred, zero_division=0)
    f1 = f1_score(y_test, y_pred, zero_division=0)

    print(f"Test Set Performance:")
    print(f"  AUC: {auc:.4f}")
    print(f"  Precision: {precision:.4f}")
    print(f"  Recall: {recall:.4f}")
    print(f"  F1: {f1:.4f}")

    # Feature importance
    importance_dict = model.get_booster().get_score(importance_type='weight')

    # Normalize importance
    total_importance = sum(importance_dict.values())
    importance_normalized = {feat: (imp / total_importance * 100) for feat, imp in importance_dict.items()}

    # Sort by importance
    importance_sorted = sorted(importance_normalized.items(), key=lambda x: x[1], reverse=True)

    print(f"\nTop 10 Features by Importance:")
    for i, (feat, imp) in enumerate(importance_sorted[:10], 1):
        print(f"  {i}. {feat}: {imp:.2f}%")

    # Categorize importance
    rolling_avg_importance = sum([imp for feat, imp in importance_normalized.items() if feat.startswith('rolling_avg')])
    temporal_importance = sum([imp for feat, imp in importance_normalized.items() if feat in ['month_progress', 'days_since_last_rank1']])
    other_importance = sum([imp for feat, imp in importance_normalized.items() if feat == 'machine_count'])

    print(f"\nImportance by Category:")
    print(f"  Rolling averages: {rolling_avg_importance:.2f}%")
    print(f"  Temporal (month_progress + days_since_last_rank1): {temporal_importance:.2f}%")
    print(f"  Other (machine_count): {other_importance:.2f}%")

    return {
        'target': target_name,
        'auc': auc,
        'precision': precision,
        'recall': recall,
        'f1': f1,
        'importance': importance_normalized,
        'importance_sorted': importance_sorted,
        'model': model,
        'rolling_avg_importance': rolling_avg_importance,
        'temporal_importance': temporal_importance,
        'other_importance': other_importance
    }


def select_optimal_features(results_dict):
    """Select features for each target based on importance threshold."""

    print(f"\n{'='*70}")
    print(f"Feature Selection (Importance Threshold: >0.5%)")
    print(f"{'='*70}")

    selected_features_by_target = {}

    for target_name, results in results_dict.items():
        threshold = 0.5
        selected = [feat for feat, imp in results['importance'].items() if imp > threshold]
        selected_features_by_target[target_name] = selected

        print(f"\n{target_name}:")
        print(f"  Original: 18 features")
        print(f"  Selected (>0.5%): {len(selected)} features")
        print(f"  Features: {sorted(selected)}")

    return selected_features_by_target


def save_results(results_dict, selected_features_by_target):
    """Save feature importance results to JSON."""

    output = {
        'phase': '9-2',
        'description': 'Last-Digit Feature Importance Analysis',
        'results_by_target': {}
    }

    for target_name, results in results_dict.items():
        output['results_by_target'][target_name] = {
            'test_auc': float(results['auc']),
            'precision': float(results['precision']),
            'recall': float(results['recall']),
            'f1': float(results['f1']),
            'importance_by_category': {
                'rolling_avg': float(results['rolling_avg_importance']),
                'temporal': float(results['temporal_importance']),
                'other': float(results['other_importance'])
            },
            'selected_features': selected_features_by_target[target_name],
            'top_10_features': [[feat, float(imp)] for feat, imp in results['importance_sorted'][:10]]
        }

    output_path = RESULTS_DIR / 'phase9_02_feature_importance_results.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n[OK] Results saved to {output_path}")


def main():
    """Main execution flow."""

    print("=" * 80)
    print("Phase 9-2: Last-Digit Feature Importance Analysis")
    print("=" * 80)

    # Load features
    print("\n[1] Loading feature set (27D or 32D)...")
    df = load_features()
    exclude_cols = {'date', 'last_digit', 'is_rank_1', 'is_top_3', 'is_top_5'}
    feature_count = len([col for col in df.columns if col not in exclude_cols])
    print(f"  Loaded {len(df)} samples with {feature_count}D features")

    # Time-series split
    print("\n[2] Preparing time-series train/test split...")
    df_train, df_test = prepare_time_series_split(df)

    # Compute feature importance for each target
    print("\n[3] Computing feature importance for each target...")
    results_dict = {}

    for target_col, target_name in [
        ('is_rank_1', 'Rank1'),
        ('is_top_3', 'Top3'),
        ('is_top_5', 'Top5')
    ]:
        results = compute_feature_importance(df_train, df_test, target_col, target_name)
        results_dict[target_name] = results

    # Feature selection
    print("\n[4] Selecting optimal feature subset...")
    selected_features_by_target = select_optimal_features(results_dict)

    # Save results
    print("\n[5] Saving results...")
    save_results(results_dict, selected_features_by_target)

    print("\n" + "=" * 80)
    print("[OK] Phase 9-2 Complete!")
    print("=" * 80)


if __name__ == '__main__':
    main()
