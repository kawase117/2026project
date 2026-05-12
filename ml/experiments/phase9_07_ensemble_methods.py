# -*- coding: utf-8 -*-
"""
Phase 9-7: Ensemble Methods Comparison
台番号末尾別 - Multiple ensemble strategies (voting, weighted average)
Compare across all 3 targets (Rank1, Top3, Top5)
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
from xgboost import XGBClassifier
from sklearn.ensemble import RandomForestClassifier
import lightgbm as lgb
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

    unique_dates = df_sorted['date'].unique()
    unique_dates = pd.to_datetime(unique_dates)
    unique_dates = sorted(unique_dates)

    split_idx = len(unique_dates) - 57
    split_date = unique_dates[split_idx]

    df_train = df_sorted[df_sorted['date'] < str(split_date)].reset_index(drop=True)
    df_test = df_sorted[df_sorted['date'] >= str(split_date)].reset_index(drop=True)

    return df_train, df_test


def train_base_models(X_train, y_train, X_test, y_test):
    """Train 4 base models and return their predictions on test set."""

    # Calculate scale_pos_weight for class balance
    pos_count = (y_train == 1).sum()
    neg_count = (y_train == 0).sum()
    scale_pos_weight = neg_count / pos_count if pos_count > 0 else 1.0

    models = {}
    predictions = {}

    # Model 1: XGBoost_3D (high recall)
    model1 = XGBClassifier(
        objective='binary:logistic',
        max_depth=3,
        learning_rate=0.01,
        n_estimators=200,
        scale_pos_weight=scale_pos_weight,
        random_state=42,
        verbosity=0
    )
    model1.fit(X_train, y_train)
    predictions['xgboost_3d'] = model1.predict_proba(X_test)[:, 1]
    models['xgboost_3d'] = model1

    # Model 2: XGBoost_5D
    model2 = XGBClassifier(
        objective='binary:logistic',
        max_depth=5,
        learning_rate=0.1,
        n_estimators=100,
        scale_pos_weight=scale_pos_weight,
        random_state=42,
        verbosity=0
    )
    model2.fit(X_train, y_train)
    predictions['xgboost_5d'] = model2.predict_proba(X_test)[:, 1]
    models['xgboost_5d'] = model2

    # Model 3: RandomForest
    model3 = RandomForestClassifier(
        n_estimators=100,
        max_depth=7,
        random_state=42,
        n_jobs=-1
    )
    model3.fit(X_train, y_train)
    predictions['randomforest'] = model3.predict_proba(X_test)[:, 1]
    models['randomforest'] = model3

    # Model 4: LightGBM (high precision)
    model4 = lgb.LGBMClassifier(
        max_depth=3,
        learning_rate=0.01,
        n_estimators=200,
        random_state=42,
        verbosity=-1
    )
    model4.fit(X_train, y_train)
    predictions['lightgbm'] = model4.predict_proba(X_test)[:, 1]
    models['lightgbm'] = model4

    return models, predictions


def compute_metrics(y_test, y_proba, y_pred=None):
    """Compute evaluation metrics."""
    if y_pred is None:
        y_pred = (y_proba >= 0.5).astype(int)

    auc = roc_auc_score(y_test, y_proba)
    precision = precision_score(y_test, y_pred, zero_division=0)
    recall = recall_score(y_test, y_pred, zero_division=0)
    f1 = f1_score(y_test, y_pred, zero_division=0)

    return {
        'auc': float(auc),
        'precision': float(precision),
        'recall': float(recall),
        'f1': float(f1)
    }


def ensemble_voting(predictions):
    """Simple voting ensemble: average of all 4 model predictions."""
    return np.mean(list(predictions.values()), axis=0)


def ensemble_weighted_xgb_lgb(predictions):
    """Weighted ensemble: XGBoost_3D (high recall) + LightGBM (high precision) dominant."""
    weights = {
        'xgboost_3d': 0.5,      # High recall
        'lightgbm': 0.3,        # High precision
        'xgboost_5d': 0.1,
        'randomforest': 0.1
    }
    weighted_sum = np.zeros_like(predictions['xgboost_3d'])
    for model_name, weight in weights.items():
        weighted_sum += weight * predictions[model_name]
    return weighted_sum


def ensemble_weighted_high_recall(predictions):
    """Weighted ensemble: maximize recall (for Rank1 detection)."""
    weights = {
        'xgboost_3d': 0.6,      # Highest recall
        'xgboost_5d': 0.2,
        'lightgbm': 0.1,
        'randomforest': 0.1
    }
    weighted_sum = np.zeros_like(predictions['xgboost_3d'])
    for model_name, weight in weights.items():
        weighted_sum += weight * predictions[model_name]
    return weighted_sum


def ensemble_weighted_high_precision(predictions):
    """Weighted ensemble: maximize precision (for high-confidence predictions)."""
    weights = {
        'lightgbm': 0.5,        # Highest precision
        'xgboost_3d': 0.2,
        'xgboost_5d': 0.2,
        'randomforest': 0.1
    }
    weighted_sum = np.zeros_like(predictions['xgboost_3d'])
    for model_name, weight in weights.items():
        weighted_sum += weight * predictions[model_name]
    return weighted_sum


def evaluate_ensemble_methods(df_train, df_test, target_col, target_name):
    """Train base models and evaluate multiple ensemble methods."""

    print(f"\n{'='*70}")
    print(f"Ensemble Methods: {target_name}")
    print(f"{'='*70}")

    # Prepare features
    exclude_cols = {'date', 'last_digit', 'is_rank_1', 'is_top_3', 'is_top_5'}
    feature_list = [col for col in df_train.columns if col not in exclude_cols]

    X_train = df_train[feature_list].fillna(0).astype(np.float32)
    y_train = df_train[target_col].astype(int)

    X_test = df_test[feature_list].fillna(0).astype(np.float32)
    y_test = df_test[target_col].astype(int)

    # Train base models
    models, predictions_test = train_base_models(X_train, y_train, X_test, y_test)

    results = {}

    # 1. Individual models
    print(f"\n[Individual Models]")
    print(f"{'Model':<25} {'AUC':<8} {'Precision':<10} {'Recall':<8} {'F1':<8}")
    print("-" * 65)

    for model_name in ['xgboost_3d', 'xgboost_5d', 'randomforest', 'lightgbm']:
        metrics = compute_metrics(y_test, predictions_test[model_name])
        results[f'individual_{model_name}'] = metrics
        print(f"{model_name:<25} {metrics['auc']:.4f}   {metrics['precision']:.4f}      "
              f"{metrics['recall']:.4f}   {metrics['f1']:.4f}")

    # 2. Simple voting (equal weights, all 4 models)
    print(f"\n[Ensemble Methods]")
    voting_proba = ensemble_voting(predictions_test)
    voting_metrics = compute_metrics(y_test, voting_proba)
    results['ensemble_voting_4'] = voting_metrics
    print(f"{'Voting (equal, 4)':<25} {voting_metrics['auc']:.4f}   {voting_metrics['precision']:.4f}      "
          f"{voting_metrics['recall']:.4f}   {voting_metrics['f1']:.4f}")

    # 3. Weighted ensemble: XGBoost + LightGBM focus
    weighted_xgb_lgb = ensemble_weighted_xgb_lgb(predictions_test)
    weighted_xgb_lgb_metrics = compute_metrics(y_test, weighted_xgb_lgb)
    results['ensemble_weighted_xgb_lgb'] = weighted_xgb_lgb_metrics
    print(f"{'Weighted (XGB-LGB)':<25} {weighted_xgb_lgb_metrics['auc']:.4f}   {weighted_xgb_lgb_metrics['precision']:.4f}      "
          f"{weighted_xgb_lgb_metrics['recall']:.4f}   {weighted_xgb_lgb_metrics['f1']:.4f}")

    # 4. Weighted ensemble: High Recall (for detection)
    weighted_recall = ensemble_weighted_high_recall(predictions_test)
    weighted_recall_metrics = compute_metrics(y_test, weighted_recall)
    results['ensemble_weighted_recall'] = weighted_recall_metrics
    print(f"{'Weighted (Recall)':<25} {weighted_recall_metrics['auc']:.4f}   {weighted_recall_metrics['precision']:.4f}      "
          f"{weighted_recall_metrics['recall']:.4f}   {weighted_recall_metrics['f1']:.4f}")

    # 5. Weighted ensemble: High Precision (for confidence)
    weighted_precision = ensemble_weighted_high_precision(predictions_test)
    weighted_precision_metrics = compute_metrics(y_test, weighted_precision)
    results['ensemble_weighted_precision'] = weighted_precision_metrics
    print(f"{'Weighted (Precision)':<25} {weighted_precision_metrics['auc']:.4f}   {weighted_precision_metrics['precision']:.4f}      "
          f"{weighted_precision_metrics['recall']:.4f}   {weighted_precision_metrics['f1']:.4f}")

    return results


def main():
    """Main execution flow."""

    print("=" * 80)
    print("Phase 9-7: Ensemble Methods Comparison")
    print("Rank1 / Top3 / Top5 across multiple ensemble strategies")
    print("=" * 80)

    # Load features
    print("\n[1] Loading feature set (32D or 27D)...")
    df = load_features()
    exclude_cols = {'date', 'last_digit', 'is_rank_1', 'is_top_3', 'is_top_5'}
    feature_count = len([col for col in df.columns if col not in exclude_cols])
    print(f"  Loaded {len(df)} samples with {feature_count}D features")

    # Time-series split
    print("\n[2] Preparing time-series train/test split...")
    df_train, df_test = prepare_time_series_split(df)
    print(f"  Train: {len(df_train)} samples, Test: {len(df_test)} samples")

    # Evaluate ensemble methods for each target
    print("\n[3] Evaluating ensemble methods for each target...")
    all_results = {}

    for target_col, target_name in [
        ('is_rank_1', 'Rank1'),
        ('is_top_3', 'Top3'),
        ('is_top_5', 'Top5')
    ]:
        results = evaluate_ensemble_methods(df_train, df_test, target_col, target_name)
        all_results[target_name] = results

    # Save results
    print("\n[4] Saving ensemble comparison results...")
    output = {
        'phase': '9-7',
        'description': 'Ensemble Methods Comparison (Voting, Weighted Average)',
        'train_test_split': {
            'train_size': len(df_train),
            'test_size': len(df_test)
        },
        'ensemble_strategies': {
            'voting_4': 'Equal weight average of all 4 models',
            'weighted_xgb_lgb': 'XGBoost_3D (0.5) + LightGBM (0.3) + others (0.2)',
            'weighted_recall': 'XGBoost_3D (0.6) - optimized for recall/detection',
            'weighted_precision': 'LightGBM (0.5) - optimized for precision/confidence'
        },
        'results_by_target': all_results
    }

    output_path = RESULTS_DIR / 'phase9_07_ensemble_methods_results.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n[OK] Results saved to {output_path}")

    # Summary comparison
    print("\n" + "=" * 80)
    print("Summary: Best Methods by Target")
    print("=" * 80)

    for target_name, results in all_results.items():
        print(f"\n{target_name}:")
        sorted_results = sorted(results.items(), key=lambda x: x[1]['auc'], reverse=True)
        for i, (method_name, metrics) in enumerate(sorted_results[:6], 1):
            marker = "[Best]" if i == 1 else "       "
            print(f"  {marker} {i}. {method_name:<30} AUC={metrics['auc']:.4f}, Recall={metrics['recall']:.4f}, Precision={metrics['precision']:.4f}")

    print("\n" + "=" * 80)
    print("[OK] Phase 9-7 Complete!")
    print("=" * 80)


if __name__ == '__main__':
    main()
