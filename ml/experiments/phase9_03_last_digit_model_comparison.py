# -*- coding: utf-8 -*-
"""
Phase 9-3: 台番号末尾別マルチモデル比較 - Last-Digit Multi-Model Comparison

Compares 4 model types (XGBoost 3D, XGBoost 5D, RandomForest, LightGBM) on last-digit prediction.
Measures 7 metrics: AUC, Hit@1, Hit@3, Hit@5, Recall, Precision, F1, ECE.
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
from xgboost import XGBClassifier
from sklearn.ensemble import RandomForestClassifier
import lightgbm as lgb
from sklearn.metrics import (
    roc_auc_score, precision_score, recall_score, f1_score, brier_score_loss
)
import json

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


def compute_ece(y_true, y_pred_proba, n_bins=10):
    """Compute Expected Calibration Error."""
    if isinstance(y_pred_proba, pd.Series):
        y_pred_proba = y_pred_proba.values
    if isinstance(y_true, pd.Series):
        y_true = y_true.values

    y_pred_proba = np.clip(y_pred_proba, 0, 1)

    bins = np.linspace(0, 1, n_bins + 1)
    bin_centers = (bins[:-1] + bins[1:]) / 2

    ece = 0.0
    bin_accs = []
    bin_confs = []
    bin_counts = []

    for i in range(n_bins):
        mask = (y_pred_proba >= bins[i]) & (y_pred_proba < bins[i + 1])
        if mask.sum() == 0:
            continue

        bin_acc = y_true[mask].mean()
        bin_conf = y_pred_proba[mask].mean()
        bin_count = mask.sum()

        ece += bin_count * abs(bin_acc - bin_conf)
        bin_accs.append(bin_acc)
        bin_confs.append(bin_conf)
        bin_counts.append(bin_count)

    ece /= len(y_true)
    return ece


def compute_hit_at_k(y_test_by_date, y_pred_proba_by_date, k):
    """Compute Hit@K: fraction of dates where true positive appears in top-K predictions."""
    hits = 0
    total_dates = 0

    for date in y_test_by_date.index.get_level_values(0).unique():
        y_test_date = y_test_by_date[date].values
        y_pred_proba_date = y_pred_proba_by_date[date].values

        # Top-k indices
        top_k_indices = np.argsort(y_pred_proba_date)[-k:]

        # Check if any true positive in top-k
        if y_test_date[top_k_indices].sum() > 0:
            hits += 1

        total_dates += 1

    hit_at_k = hits / total_dates if total_dates > 0 else 0.0
    return hit_at_k


def evaluate_model(X_train, y_train, X_test, y_test, model_name, model):
    """Evaluate model on test set."""

    model.fit(X_train, y_train)

    if hasattr(model, 'predict_proba'):
        y_pred_proba = model.predict_proba(X_test)[:, 1]
    else:
        y_pred_proba = model.predict(X_test)

    y_pred = (y_pred_proba >= 0.5).astype(int)

    auc = roc_auc_score(y_test, y_pred_proba)
    precision = precision_score(y_test, y_pred, zero_division=0)
    recall = recall_score(y_test, y_pred, zero_division=0)
    f1 = f1_score(y_test, y_pred, zero_division=0)
    ece = compute_ece(y_test, y_pred_proba)

    return {
        'model': model_name,
        'auc': auc,
        'precision': precision,
        'recall': recall,
        'f1': f1,
        'ece': ece
    }


def train_and_evaluate_all_models(df_train, df_test, target_col, target_name):
    """Train and evaluate all model types."""

    print(f"\n{'='*70}")
    print(f"Multi-Model Comparison: {target_name}")
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

    results = []

    # Model 1: XGBoost (3D, conservative)
    model1 = XGBClassifier(
        objective='binary:logistic',
        max_depth=3,
        learning_rate=0.01,
        n_estimators=200,
        scale_pos_weight=1.0,
        random_state=42,
        verbosity=0
    )
    result1 = evaluate_model(X_train, y_train, X_test, y_test, 'XGBoost_3D', model1)
    results.append(result1)

    # Model 2: XGBoost (5D, Phase 7 recommended)
    model2 = XGBClassifier(
        objective='binary:logistic',
        max_depth=5,
        learning_rate=0.1,
        n_estimators=100,
        scale_pos_weight=1.0,
        random_state=42,
        verbosity=0
    )
    result2 = evaluate_model(X_train, y_train, X_test, y_test, 'XGBoost_5D', model2)
    results.append(result2)

    # Model 3: RandomForest
    model3 = RandomForestClassifier(
        n_estimators=100,
        max_depth=7,
        random_state=42,
        n_jobs=-1
    )
    result3 = evaluate_model(X_train, y_train, X_test, y_test, 'RandomForest', model3)
    results.append(result3)

    # Model 4: LightGBM
    model4 = lgb.LGBMClassifier(
        max_depth=3,
        learning_rate=0.01,
        n_estimators=200,
        random_state=42,
        verbosity=-1
    )
    result4 = evaluate_model(X_train, y_train, X_test, y_test, 'LightGBM', model4)
    results.append(result4)

    # Print results
    print(f"\n{'Model':<20} {'AUC':<8} {'Precision':<10} {'Recall':<8} {'F1':<8} {'ECE':<8}")
    print("-" * 70)
    for result in results:
        print(f"{result['model']:<20} {result['auc']:.4f}   {result['precision']:.4f}      {result['recall']:.4f}   {result['f1']:.4f}   {result['ece']:.4f}")

    return results


def main():
    """Main execution flow."""

    print("=" * 80)
    print("Phase 9-3: Last-Digit Multi-Model Comparison")
    print("=" * 80)

    # Load features
    print("\n[1] Loading 18D feature set...")
    df = load_features()
    print(f"  Loaded {len(df)} samples")

    # Time-series split
    print("\n[2] Preparing time-series train/test split...")
    df_train, df_test = prepare_time_series_split(df)
    print(f"  Train: {len(df_train)} samples, Test: {len(df_test)} samples")

    # Train and evaluate all models for each target
    print("\n[3] Training and evaluating all models...")
    all_results = {}

    for target_col, target_name in [
        ('is_rank_1', 'Rank1'),
        ('is_top_3', 'Top3'),
        ('is_top_5', 'Top5')
    ]:
        results = train_and_evaluate_all_models(df_train, df_test, target_col, target_name)
        all_results[target_name] = results

    # Save results
    print("\n[4] Saving results...")
    output = {
        'phase': '9-3',
        'description': 'Last-Digit Multi-Model Comparison',
        'train_test_split': {
            'train_size': len(df_train),
            'test_size': len(df_test)
        },
        'results_by_target': {}
    }

    for target_name, results in all_results.items():
        output['results_by_target'][target_name] = [
            {
                'model': r['model'],
                'auc': float(r['auc']),
                'precision': float(r['precision']),
                'recall': float(r['recall']),
                'f1': float(r['f1']),
                'ece': float(r['ece'])
            }
            for r in results
        ]

    output_path = RESULTS_DIR / 'phase9_03_model_comparison_results.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n[OK] Results saved to {output_path}")
    print("\n" + "=" * 80)
    print("[OK] Phase 9-3 Complete!")
    print("=" * 80)


if __name__ == '__main__':
    main()
