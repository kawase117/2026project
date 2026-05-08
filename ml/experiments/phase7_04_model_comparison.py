"""
Phase 7: Rank Prediction - Step 4: Model Comparison (scale_pos_weight variants)

Compares two modeling strategies:
1. Balanced (scale_pos_weight adjusted) - optimizes F1 with class rebalancing
2. Calibrated (scale_pos_weight=1) - preserves probabilistic interpretation
"""

import sys
sys.path.insert(0, str(__file__).rsplit('/', 1)[0])

import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.metrics import roc_auc_score, average_precision_score, precision_recall_curve, f1_score
import xgboost as xgb
import json
from datetime import datetime
from scipy.special import comb

from phase7_02_rank_prediction_model import load_data, prepare_features

PROJECT_ROOT = Path("C:\\Users\\apto117\\Documents\\pachinko-analyzer\\src\\2026project")
COPY_DB = PROJECT_ROOT / "db" / "experiments" / "マルハンメガシティ2000-蒲田7_rank_exp.db"
RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase7_rank_prediction"

def train_models_with_variants(X, y_dict, dates):
    """Train models with both scale_pos_weight variants."""
    unique_dates = pd.Series(dates).unique()
    split_date_idx = len(unique_dates) - 57
    split_date = unique_dates[split_date_idx]
    train_mask = dates < split_date
    test_mask = dates >= split_date
    train_idx = np.where(train_mask)[0]
    test_idx = np.where(test_mask)[0]

    X_train = X.iloc[train_idx]
    X_test = X.iloc[test_idx]

    results = {}

    for target_name, y in y_dict.items():
        y_train = y.iloc[train_idx]
        y_test = y.iloc[test_idx]

        pos_ratio = y_train.sum() / len(y_train)
        scale_pos_weight_adjusted = (1 - pos_ratio) / pos_ratio

        print(f"\n=== Training {target_name} ===")
        print(f"Positive ratio: {pos_ratio:.2%}")
        print(f"Adjusted scale_pos_weight: {scale_pos_weight_adjusted:.2f}")

        # Model 1: Balanced (adjusted scale_pos_weight)
        print(f"  Training balanced model...")
        model_balanced = xgb.XGBClassifier(
            max_depth=5, learning_rate=0.1, n_estimators=100,
            scale_pos_weight=scale_pos_weight_adjusted, random_state=42, eval_metric='auc'
        )
        model_balanced.fit(X_train, y_train, verbose=False)
        y_proba_balanced = model_balanced.predict_proba(X_test)[:, 1]

        # Model 2: Calibrated (scale_pos_weight=1, preserves probabilistic meaning)
        print(f"  Training calibrated model...")
        model_calibrated = xgb.XGBClassifier(
            max_depth=5, learning_rate=0.1, n_estimators=100,
            scale_pos_weight=1.0, random_state=42, eval_metric='auc'
        )
        model_calibrated.fit(X_train, y_train, verbose=False)
        y_proba_calibrated = model_calibrated.predict_proba(X_test)[:, 1]

        # Evaluate both models
        auc_balanced = roc_auc_score(y_test, y_proba_balanced)
        ap_balanced = average_precision_score(y_test, y_proba_balanced)

        auc_calibrated = roc_auc_score(y_test, y_proba_calibrated)
        ap_calibrated = average_precision_score(y_test, y_proba_calibrated)

        # Calibration: Expected Calibration Error
        ece_balanced = compute_ece(y_test, y_proba_balanced)
        ece_calibrated = compute_ece(y_test, y_proba_calibrated)

        # Top-K hit rates
        daily_hit_balanced = compute_daily_hit_rate(y_test, y_proba_balanced, dates[test_idx])
        daily_hit_calibrated = compute_daily_hit_rate(y_test, y_proba_calibrated, dates[test_idx])

        results[target_name] = {
            'pos_ratio': pos_ratio,
            'balanced': {
                'model': model_balanced,
                'y_proba': y_proba_balanced,
                'auc': auc_balanced,
                'ap': ap_balanced,
                'ece': ece_balanced,
                'daily_hit_k5': daily_hit_balanced.get(5, 0),
                'daily_hit_k10': daily_hit_balanced.get(10, 0)
            },
            'calibrated': {
                'model': model_calibrated,
                'y_proba': y_proba_calibrated,
                'auc': auc_calibrated,
                'ap': ap_calibrated,
                'ece': ece_calibrated,
                'daily_hit_k5': daily_hit_calibrated.get(5, 0),
                'daily_hit_k10': daily_hit_calibrated.get(10, 0)
            },
            'y_test': y_test.values,
            'test_size': len(y_test)
        }

    return results

def compute_ece(y_true, y_proba, n_bins=10):
    """Compute Expected Calibration Error (lower is better - more calibrated)."""
    bin_edges = np.linspace(0, 1, n_bins + 1)
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    ece = 0

    for i in range(n_bins):
        bin_mask = (y_proba >= bin_edges[i]) & (y_proba < bin_edges[i + 1])
        if bin_mask.sum() == 0:
            continue

        bin_accuracy = y_true[bin_mask].mean()
        bin_confidence = y_proba[bin_mask].mean()
        bin_weight = bin_mask.sum() / len(y_true)

        ece += bin_weight * np.abs(bin_accuracy - bin_confidence)

    return ece

def compute_daily_hit_rate(y_test, y_proba, dates_test):
    """Compute daily hit rates for K=5, 10."""
    test_df = pd.DataFrame({
        'date': dates_test,
        'y_true': y_test,
        'y_proba': y_proba
    })

    daily_hits = {}

    for k in [5, 10]:
        hit_rates = []

        for date in test_df['date'].unique():
            day_mask = test_df['date'] == date
            day_df = test_df[day_mask]

            machines_on_day = len(day_df)
            if machines_on_day == 0:
                continue

            k_clamped = min(k, machines_on_day)
            top_k_mask = day_df['y_proba'].nlargest(k_clamped).index
            top_k_positives = day_df.loc[top_k_mask, 'y_true'].sum()

            hit = 1 if top_k_positives > 0 else 0
            hit_rates.append(hit)

        daily_hits[k] = np.mean(hit_rates) if hit_rates else 0

    return daily_hits

def print_comparison(results):
    """Print comprehensive comparison."""
    print("\n" + "=" * 80)
    print("MODEL COMPARISON: Balanced (scale_pos_weight adjusted) vs Calibrated (scale_pos_weight=1)")
    print("=" * 80)

    for target_name, data in results.items():
        print(f"\n{target_name.upper()} (positive ratio: {data['pos_ratio']:.2%}, test_size: {data['test_size']})")
        print("-" * 80)

        balanced = data['balanced']
        calibrated = data['calibrated']

        print(f"{'Metric':<30s} {'Balanced':>15s} {'Calibrated':>15s} {'Diff (Cal-Bal)':>15s}")
        print("-" * 80)

        # AUC
        auc_diff = calibrated['auc'] - balanced['auc']
        print(f"{'AUC':<30s} {balanced['auc']:>15.4f} {calibrated['auc']:>15.4f} {auc_diff:>15.4f}")

        # AP
        ap_diff = calibrated['ap'] - balanced['ap']
        print(f"{'Average Precision':<30s} {balanced['ap']:>15.4f} {calibrated['ap']:>15.4f} {ap_diff:>15.4f}")

        # ECE (lower is better)
        ece_diff = calibrated['ece'] - balanced['ece']
        print(f"{'Expected Calibration Error':<30s} {balanced['ece']:>15.4f} {calibrated['ece']:>15.4f} {ece_diff:>15.4f}")
        print(f"{'  (lower = better calibrated)':<30s}")

        # Daily Hit Rates
        hit5_diff = calibrated['daily_hit_k5'] - balanced['daily_hit_k5']
        print(f"{'Daily Hit Rate @ K=5':<30s} {balanced['daily_hit_k5']:>15.2%} {calibrated['daily_hit_k5']:>15.2%} {hit5_diff:>15.2%}")

        hit10_diff = calibrated['daily_hit_k10'] - balanced['daily_hit_k10']
        print(f"{'Daily Hit Rate @ K=10':<30s} {balanced['daily_hit_k10']:>15.2%} {calibrated['daily_hit_k10']:>15.2%} {hit10_diff:>15.2%}")

        # Threshold-based F1 at default 0.5
        print("\nThreshold analysis (threshold=0.5):")
        for name, proba in [('Balanced', balanced['y_proba']), ('Calibrated', calibrated['y_proba'])]:
            y_pred = (proba >= 0.5).astype(int)
            y_test = data['y_test']
            precision = (y_pred * y_test).sum() / max((y_pred).sum(), 1)
            recall = (y_pred * y_test).sum() / max(y_test.sum(), 1)
            f1 = 2 * precision * recall / max(precision + recall, 0.0001)
            print(f"  {name:<20s}: Precision={precision:.2%}, Recall={recall:.2%}, F1={f1:.4f}")

def main():
    print("[Phase 7-4] Model Comparison: scale_pos_weight variants")

    # Load data
    print(f"\nLoading data from {COPY_DB.name}...")
    df = load_data(COPY_DB)
    X, y_dict, dates = prepare_features(df)
    print(f"Features: {X.shape[1]} columns, {len(df)} rows")

    # Train and compare models
    print("\nTraining models with both scale_pos_weight strategies...")
    results = train_models_with_variants(X, y_dict, dates)

    # Print comparison
    print_comparison(results)

    # Save comparison results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    comparison_output = {
        'timestamp': datetime.now().isoformat(),
        'description': 'Comparison of scale_pos_weight=adjusted (balanced) vs scale_pos_weight=1 (calibrated)',
        'comparisons': {
            target: {
                'pos_ratio': data['pos_ratio'],
                'test_size': data['test_size'],
                'balanced': {
                    'auc': data['balanced']['auc'],
                    'ap': data['balanced']['ap'],
                    'ece': data['balanced']['ece'],
                    'daily_hit_k5': data['balanced']['daily_hit_k5'],
                    'daily_hit_k10': data['balanced']['daily_hit_k10']
                },
                'calibrated': {
                    'auc': data['calibrated']['auc'],
                    'ap': data['calibrated']['ap'],
                    'ece': data['calibrated']['ece'],
                    'daily_hit_k5': data['calibrated']['daily_hit_k5'],
                    'daily_hit_k10': data['calibrated']['daily_hit_k10']
                }
            }
            for target, data in results.items()
        }
    }

    comparison_path = RESULTS_DIR / "model_comparison.json"
    with open(comparison_path, 'w') as f:
        json.dump(comparison_output, f, indent=2)
    print(f"\n[OK] Saved comparison to {comparison_path}")

if __name__ == "__main__":
    main()
