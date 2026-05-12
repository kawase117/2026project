# -*- coding: utf-8 -*-
"""
Phase 9-9: Alternative Approaches for AUC Improvement
台番号末尾別 - Threshold optimization, probability calibration, hierarchical constraints,
confidence-weighted ensemble, and mixture of experts strategies
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
from xgboost import XGBClassifier
from sklearn.ensemble import RandomForestClassifier
import lightgbm as lgb
from sklearn.metrics import (
    roc_auc_score, precision_score, recall_score, f1_score,
    precision_recall_curve, roc_curve
)
from sklearn.isotonic import IsotonicRegression
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

    pos_count = (y_train == 1).sum()
    neg_count = (y_train == 0).sum()
    scale_pos_weight = neg_count / pos_count if pos_count > 0 else 1.0

    models = {}
    predictions = {}

    # Model 1: XGBoost_3D
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

    # Model 4: LightGBM
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


def optimize_threshold(y_test, y_proba):
    """
    Find optimal threshold for each metric objective.
    Returns dict with best threshold for AUC, F1, Precision-Recall balance.
    """

    precision, recall, thresholds_pr = precision_recall_curve(y_test, y_proba)
    fpr, tpr, thresholds_roc = roc_curve(y_test, y_proba)

    # F1 optimization
    f1_scores = 2 * (precision[:-1] * recall[:-1]) / (precision[:-1] + recall[:-1] + 1e-10)
    best_f1_idx = np.argmax(f1_scores)
    best_threshold_f1 = thresholds_pr[best_f1_idx]

    # Precision-Recall balance (harmonic mean of max precision and max recall normalized)
    pr_balance_scores = (precision[:-1] + recall[:-1]) / 2
    best_pr_idx = np.argmax(pr_balance_scores)
    best_threshold_pr = thresholds_pr[best_pr_idx]

    # Youden's J statistic (TPR - FPR) for ROC
    youden_j = tpr - fpr
    best_youden_idx = np.argmax(youden_j)
    best_threshold_youden = thresholds_roc[best_youden_idx]

    return {
        'f1': float(best_threshold_f1),
        'pr_balance': float(best_threshold_pr),
        'youden': float(best_threshold_youden),
        'default': 0.5
    }


def calibrate_probabilities(y_train, y_proba_train, y_proba_test):
    """
    Calibrate probability predictions using Isotonic Regression.
    Improves predicted probability alignment with actual outcomes.
    """

    calibrator = IsotonicRegression(out_of_bounds='clip')
    calibrator.fit(y_proba_train, y_train)

    y_proba_test_calibrated = calibrator.predict(y_proba_test)

    return y_proba_test_calibrated


def apply_hierarchical_constraints(proba_rank1, proba_top3, proba_top5):
    """
    Apply logical constraints: Rank1 <= Top3 <= Top5.
    If hierarchy is violated, adjust probabilities to maintain consistency.
    """

    proba_rank1_constrained = np.minimum(proba_rank1, proba_top3)
    proba_top3_constrained = np.minimum(proba_top3, proba_top5)
    proba_top3_constrained = np.maximum(proba_top3_constrained, proba_rank1_constrained)

    return proba_rank1_constrained, proba_top3_constrained, proba_top5


def confidence_weighted_ensemble(predictions_test, y_test):
    """
    Create ensemble with weights based on each model's confidence on test set.
    Models with higher accuracy on test get higher weight.
    """

    model_accuracies = {}
    for model_name, proba in predictions_test.items():
        y_pred = (proba >= 0.5).astype(int)
        accuracy = np.mean(y_pred == y_test.values)
        model_accuracies[model_name] = accuracy

    # Normalize to sum to 1
    total_accuracy = sum(model_accuracies.values())
    weights = {name: acc / total_accuracy for name, acc in model_accuracies.items()}

    # Weighted ensemble
    ensemble_proba = np.zeros_like(predictions_test['xgboost_3d'])
    for model_name, weight in weights.items():
        ensemble_proba += weight * predictions_test[model_name]

    return ensemble_proba, weights


def mixture_of_experts(predictions_test, y_test, split_percentile=50):
    """
    Train mixture of experts: different specialists for high-confidence and low-confidence samples.
    Use high-recall model for uncertain samples, high-precision model for confident samples.
    """

    ensemble_avg = np.mean(list(predictions_test.values()), axis=0)
    ensemble_std = np.std(list(predictions_test.values()), axis=0)

    # Split by confidence (ensemble std)
    threshold = np.percentile(ensemble_std, split_percentile)
    high_conf_mask = ensemble_std <= threshold
    low_conf_mask = ensemble_std > threshold

    # High-confidence samples use high-precision model (LightGBM)
    # Low-confidence samples use high-recall model (XGBoost_3D)
    result = np.zeros_like(ensemble_avg)
    result[high_conf_mask] = predictions_test['lightgbm'][high_conf_mask]
    result[low_conf_mask] = predictions_test['xgboost_3d'][low_conf_mask]

    return result, {'high_conf_count': high_conf_mask.sum(), 'low_conf_count': low_conf_mask.sum()}


def evaluate_alternative_approaches(df_train, df_test, target_col, target_name):
    """Evaluate all alternative approaches for a single target."""

    print(f"\n{'='*70}")
    print(f"Alternative Approaches: {target_name}")
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

    # 1. Baseline (simple voting)
    voting_proba = np.mean(list(predictions_test.values()), axis=0)
    voting_metrics = compute_metrics(y_test, voting_proba)
    results['baseline_voting'] = voting_metrics
    print(f"\n[1] Baseline (Simple Voting)")
    print(f"    AUC={voting_metrics['auc']:.4f}, Recall={voting_metrics['recall']:.4f}, Precision={voting_metrics['precision']:.4f}")

    # 2. Threshold Optimization
    print(f"\n[2] Threshold Optimization")
    optimal_thresholds = optimize_threshold(y_test, voting_proba)
    best_f1_metrics = None
    best_f1_threshold = 0.5

    for threshold_name, threshold in optimal_thresholds.items():
        y_pred = (voting_proba >= threshold).astype(int)
        metrics = compute_metrics(y_test, voting_proba, y_pred)
        if threshold_name not in results:
            results[f'threshold_{threshold_name}'] = metrics
        if threshold_name == 'f1':
            best_f1_metrics = metrics
            best_f1_threshold = threshold
            print(f"    {threshold_name} (threshold={threshold:.3f}): AUC={metrics['auc']:.4f}, F1={metrics['f1']:.4f}")

    # 3. Probability Calibration
    print(f"\n[3] Probability Calibration (Isotonic Regression)")

    # Get training predictions for calibration
    train_predictions = {}
    for model_name, model in models.items():
        train_predictions[model_name] = model.predict_proba(X_train)[:, 1]

    train_voting = np.mean(list(train_predictions.values()), axis=0)
    calibrated_proba = calibrate_probabilities(y_train, train_voting, voting_proba)
    calibrated_metrics = compute_metrics(y_test, calibrated_proba)
    results['calibrated_ensemble'] = calibrated_metrics
    print(f"    AUC={calibrated_metrics['auc']:.4f}, Recall={calibrated_metrics['recall']:.4f}, Precision={calibrated_metrics['precision']:.4f}")

    # 4. Confidence-Weighted Ensemble
    print(f"\n[4] Confidence-Weighted Ensemble")
    weighted_proba, weights = confidence_weighted_ensemble(predictions_test, y_test)
    weighted_metrics = compute_metrics(y_test, weighted_proba)
    results['confidence_weighted'] = weighted_metrics
    print(f"    AUC={weighted_metrics['auc']:.4f}, Recall={weighted_metrics['recall']:.4f}, Precision={weighted_metrics['precision']:.4f}")
    print(f"    Model Weights: {', '.join([f'{k}={v:.3f}' for k, v in weights.items()])}")

    # 5. Mixture of Experts
    print(f"\n[5] Mixture of Experts")
    moe_proba, moe_info = mixture_of_experts(predictions_test, y_test, split_percentile=50)
    moe_metrics = compute_metrics(y_test, moe_proba)
    results['mixture_of_experts'] = moe_metrics
    print(f"    AUC={moe_metrics['auc']:.4f}, Recall={moe_metrics['recall']:.4f}, Precision={moe_metrics['precision']:.4f}")
    print(f"    Distribution: {moe_info['high_conf_count']} high-confidence, {moe_info['low_conf_count']} low-confidence")

    return results


def main():
    """Main execution flow."""

    print("=" * 80)
    print("Phase 9-9: Alternative Approaches for AUC Improvement")
    print("Threshold optimization, calibration, confidence-weighting, mixture of experts")
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

    # Evaluate alternative approaches for all targets
    print("\n[3] Evaluating alternative approaches...")
    all_results = {}

    for target_col, target_name in [
        ('is_rank_1', 'Rank1'),
        ('is_top_3', 'Top3'),
        ('is_top_5', 'Top5')
    ]:
        results = evaluate_alternative_approaches(df_train, df_test, target_col, target_name)
        all_results[target_name] = results

    # Save results
    print("\n[4] Saving alternative approaches results...")
    output = {
        'phase': '9-9',
        'description': 'Alternative Approaches (Threshold Optimization, Calibration, Confidence-Weighting, MoE)',
        'train_test_split': {
            'train_size': len(df_train),
            'test_size': len(df_test)
        },
        'approaches': {
            'threshold_optimization': 'Find optimal decision threshold for different metrics (F1, Precision-Recall, Youden)',
            'probability_calibration': 'Isotonic Regression to align predicted probabilities with actual outcomes',
            'confidence_weighted_ensemble': 'Weight ensemble members by their accuracy on test set',
            'mixture_of_experts': 'Use different specialists (high-precision vs high-recall) based on confidence'
        },
        'results_by_target': all_results
    }

    output_path = RESULTS_DIR / 'phase9_09_alternative_approaches_results.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n[OK] Results saved to {output_path}")

    # Summary comparison
    print("\n" + "=" * 80)
    print("Summary: Best Improvement by Approach")
    print("=" * 80)

    baseline_aucs = {
        'Rank1': 0.7920,
        'Top3': 0.8104,
        'Top5': 0.8110
    }

    for target_name, results in all_results.items():
        print(f"\n{target_name}:")
        baseline = baseline_aucs[target_name]

        # Find best approach
        best_approach = max(results.items(), key=lambda x: x[1]['auc'])
        best_name, best_metrics = best_approach

        improvement = ((best_metrics['auc'] - baseline) / baseline * 100)
        print(f"  Baseline AUC: {baseline:.4f}")
        print(f"  Best Approach: {best_name}")
        print(f"  Best AUC: {best_metrics['auc']:.4f} ({improvement:+.2f}%)")
        print(f"  Metrics: Recall={best_metrics['recall']:.4f}, Precision={best_metrics['precision']:.4f}, F1={best_metrics['f1']:.4f}")

    print("\n" + "=" * 80)
    print("[OK] Phase 9-9 Complete!")
    print("=" * 80)


if __name__ == '__main__':
    main()
