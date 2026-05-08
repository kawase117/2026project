"""
Phase 7: Rank Prediction - Step 3: Feature Importance & Threshold Optimization

Analyzes learned models to identify key features and find optimal prediction thresholds.
"""

import sys
sys.path.insert(0, str(__file__).rsplit('/', 1)[0])

import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.metrics import precision_recall_curve, f1_score
import xgboost as xgb
import json
from datetime import datetime
from scipy.special import comb

# Import from phase7_02
from phase7_02_rank_prediction_model import load_data, prepare_features

PROJECT_ROOT = Path("C:\\Users\\apto117\\Documents\\pachinko-analyzer\\src\\2026project")
COPY_DB = PROJECT_ROOT / "db" / "experiments" / "マルハンメガシティ2000-蒲田7_rank_exp.db"
RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase7_rank_prediction"

def extract_feature_importance(X, y_dict, dates):
    """Extract feature importances from trained models."""
    # Time-series split
    unique_dates = pd.Series(dates).unique()
    split_date_idx = len(unique_dates) - 57
    split_date = unique_dates[split_date_idx]
    train_mask = dates < split_date
    train_idx = np.where(train_mask)[0]
    X_train = X.iloc[train_idx]

    feature_importance = {}

    for target_name, y in y_dict.items():
        y_train = y.iloc[train_idx]
        pos_ratio = y_train.sum() / len(y_train)
        scale_pos_weight = (1 - pos_ratio) / pos_ratio

        # Train model
        model = xgb.XGBClassifier(
            max_depth=5, learning_rate=0.1, n_estimators=100,
            scale_pos_weight=scale_pos_weight, random_state=42, eval_metric='auc'
        )
        model.fit(X_train, y_train, verbose=False)

        # Extract importance
        importances = model.feature_importances_
        top_idx = np.argsort(importances)[::-1][:10]

        feature_importance[target_name] = {
            'model': model,
            'importances': {
                X.columns[i]: float(importances[i]) for i in top_idx
            }
        }

    return feature_importance

def optimize_thresholds(X, y_dict, dates, models_dict):
    """Find optimal prediction thresholds. (Legacy - see optimize_thresholds_extended)"""
    # Time-series split
    unique_dates = pd.Series(dates).unique()
    split_date_idx = len(unique_dates) - 57
    split_date = unique_dates[split_date_idx]
    test_mask = dates >= split_date
    test_idx = np.where(test_mask)[0]

    X_test = X.iloc[test_idx]

    threshold_results = {}

    for target_name, y in y_dict.items():
        y_test = y.iloc[test_idx]
        model = models_dict[target_name]['model']

        # Get probability predictions
        y_proba = model.predict_proba(X_test)[:, 1]

        # Precision-Recall curve
        p, r, thresholds = precision_recall_curve(y_test, y_proba)

        # Baseline (random)
        baseline_precision = y_test.sum() / len(y_test)

        # Find thresholds of interest
        thresholds_to_test = [0.01, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50]
        results = []

        for threshold in thresholds_to_test:
            y_pred = (y_proba >= threshold).astype(int)
            tp = ((y_pred == 1) & (y_test == 1)).sum()
            fp = ((y_pred == 1) & (y_test == 0)).sum()
            fn = ((y_pred == 0) & (y_test == 1)).sum()

            prec = tp / max(tp + fp, 1)
            recall = tp / max(tp + fn, 1)
            f1 = 2 * (prec * recall) / max(prec + recall, 0.0001)
            prec_lift = prec / max(baseline_precision, 0.0001)

            results.append({
                'threshold': threshold,
                'precision': prec,
                'recall': recall,
                'f1': f1,
                'precision_lift': prec_lift
            })

        # Sort by F1 to find optimal
        best_f1_result = max(results, key=lambda x: x['f1'])

        threshold_results[target_name] = {
            'baseline_precision': baseline_precision,
            'thresholds': results,
            'optimal_threshold_f1': best_f1_result['threshold'],
            'optimal_f1': best_f1_result['f1']
        }

    return threshold_results

def analyze_proba_distribution(X, y_dict, dates, models_dict):
    """Analyze y_proba distribution for diagnostic purposes."""
    unique_dates = pd.Series(dates).unique()
    split_date_idx = len(unique_dates) - 57
    split_date = unique_dates[split_date_idx]
    test_mask = dates >= split_date
    test_idx = np.where(test_mask)[0]

    X_test = X.iloc[test_idx]
    distribution_results = {}

    for target_name, y in y_dict.items():
        y_test = y.iloc[test_idx]
        model = models_dict[target_name]['model']

        # Get probability predictions
        y_proba = model.predict_proba(X_test)[:, 1]

        # Calculate percentiles for overall distribution
        percentiles = [0, 1, 5, 25, 50, 75, 90, 95, 99, 100]
        overall_dist = np.percentile(y_proba, percentiles)

        # Positive examples distribution
        pos_mask = y_test == 1
        y_proba_pos = y_proba[pos_mask]
        pos_dist = np.percentile(y_proba_pos, percentiles) if len(y_proba_pos) > 0 else [np.nan] * len(percentiles)

        # Negative examples distribution
        neg_mask = y_test == 0
        y_proba_neg = y_proba[neg_mask]
        neg_dist = np.percentile(y_proba_neg, percentiles) if len(y_proba_neg) > 0 else [np.nan] * len(percentiles)

        distribution_results[target_name] = {
            'percentiles': percentiles,
            'overall': overall_dist.tolist(),
            'positive': pos_dist.tolist(),
            'negative': neg_dist.tolist(),
            'y_proba_array': y_proba
        }

    return distribution_results

def optimize_thresholds_extended(X, y_dict, dates, models_dict, proba_dist):
    """Extended threshold optimization with data-driven candidates."""
    unique_dates = pd.Series(dates).unique()
    split_date_idx = len(unique_dates) - 57
    split_date = unique_dates[split_date_idx]
    test_mask = dates >= split_date
    test_idx = np.where(test_mask)[0]

    X_test = X.iloc[test_idx]
    threshold_results = {}

    for target_name, y in y_dict.items():
        y_test = y.iloc[test_idx]
        model = models_dict[target_name]['model']

        # Get probability predictions
        y_proba = model.predict_proba(X_test)[:, 1]

        # Baseline
        baseline_precision = y_test.sum() / len(y_test)

        # Fixed thresholds (low range for imbalanced data)
        fixed_thresholds = [0.01, 0.02, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]

        # Data-driven thresholds from positive examples distribution
        dist = proba_dist[target_name]
        pos_p25 = dist['positive'][3]  # percentile 25
        pos_p50 = dist['positive'][4]  # percentile 50
        pos_p75 = dist['positive'][5]  # percentile 75

        data_driven = [t for t in [pos_p25, pos_p50, pos_p75] if not np.isnan(t)]
        all_thresholds = sorted(set(fixed_thresholds + data_driven))

        results = []

        for threshold in all_thresholds:
            y_pred = (y_proba >= threshold).astype(int)
            tp = ((y_pred == 1) & (y_test == 1)).sum()
            fp = ((y_pred == 1) & (y_test == 0)).sum()
            fn = ((y_pred == 0) & (y_test == 1)).sum()
            tn = ((y_pred == 0) & (y_test == 0)).sum()

            prec = tp / max(tp + fp, 1)
            recall = tp / max(tp + fn, 1)
            f1 = 2 * (prec * recall) / max(prec + recall, 0.0001)
            prec_lift = prec / max(baseline_precision, 0.0001)
            pred_pos_rate = (tp + fp) / len(y_test)

            results.append({
                'threshold': float(threshold),
                'precision': prec,
                'recall': recall,
                'f1': f1,
                'precision_lift': prec_lift,
                'pred_positive_count': int(tp + fp),
                'true_positive_count': int(tp),
                'pred_positive_rate': pred_pos_rate
            })

        # Sort by F1 to find optimal
        best_f1_result = max(results, key=lambda x: x['f1'])

        threshold_results[target_name] = {
            'baseline_precision': baseline_precision,
            'baseline_positive_rate': baseline_precision,
            'thresholds': results,
            'optimal_threshold_f1': best_f1_result['threshold'],
            'optimal_f1': best_f1_result['f1'],
            'test_size': len(y_test)
        }

    return threshold_results

def evaluate_top_k(X, y_dict, dates, models_dict):
    """Evaluate Top-K recommendation performance."""
    unique_dates = pd.Series(dates).unique()
    split_date_idx = len(unique_dates) - 57
    split_date = unique_dates[split_date_idx]
    test_mask = dates >= split_date
    test_idx = np.where(test_mask)[0]

    X_test = X.iloc[test_idx]
    top_k_results = {}

    for target_name, y in y_dict.items():
        y_test = y.iloc[test_idx]
        model = models_dict[target_name]['model']

        # Get probability predictions
        y_proba = model.predict_proba(X_test)[:, 1]

        # Baseline
        baseline_precision = y_test.sum() / len(y_test)

        # Evaluate various K values
        k_values = [1, 3, 5, 10, 20, 50, 100]
        k_results = []

        for k in k_values:
            k = min(k, len(y_test))  # Clamp K to test size
            top_k_indices = np.argsort(y_proba)[-k:]
            y_pred_k = np.zeros(len(y_test), dtype=int)
            y_pred_k[top_k_indices] = 1

            tp = ((y_pred_k == 1) & (y_test == 1)).sum()
            prec_at_k = tp / k if k > 0 else 0
            recall_at_k = tp / max(y_test.sum(), 1)
            lift_at_k = prec_at_k / max(baseline_precision, 0.0001)

            k_results.append({
                'k': k,
                'precision_at_k': prec_at_k,
                'recall_at_k': recall_at_k,
                'lift_at_k': lift_at_k,
                'true_positives': int(tp)
            })

        top_k_results[target_name] = {
            'baseline_precision': baseline_precision,
            'total_positives': int(y_test.sum()),
            'test_size': len(y_test),
            'k_evaluations': k_results
        }

    return top_k_results

def evaluate_daily_hit_rate(X, y_dict, dates, models_dict):
    """Evaluate hit rate when selecting top-K per day."""
    unique_dates = pd.Series(dates).unique()
    split_date_idx = len(unique_dates) - 57
    split_date = unique_dates[split_date_idx]
    test_mask = dates >= split_date
    test_idx = np.where(test_mask)[0]

    X_test = X.iloc[test_idx]
    dates_test = dates[test_idx]

    daily_hit_results = {}

    for target_name, y in y_dict.items():
        y_test = y.iloc[test_idx]
        model = models_dict[target_name]['model']

        # Get probability predictions
        y_proba = model.predict_proba(X_test)[:, 1]

        # Create DataFrame for easier grouping
        test_df = pd.DataFrame({
            'date': dates_test,
            'y_true': y_test.values,
            'y_proba': y_proba
        })

        k_values = [1, 3, 5, 10]
        daily_results = {}

        for k in k_values:
            hit_rates = []
            valid_days = 0

            for date in test_df['date'].unique():
                day_mask = test_df['date'] == date
                day_df = test_df[day_mask]

                # Number of machines on this day
                machines_on_day = len(day_df)
                if machines_on_day == 0:
                    continue

                k_clamped = min(k, machines_on_day)

                # Get top-K machines by probability
                top_k_mask = day_df['y_proba'].nlargest(k_clamped).index
                top_k_positives = day_df.loc[top_k_mask, 'y_true'].sum()

                # Check if any true positive is in top-K
                hit = 1 if top_k_positives > 0 else 0
                hit_rates.append(hit)
                valid_days += 1

            # Calculate metrics
            hit_rate = np.mean(hit_rates) if hit_rates else 0

            # Random baseline: analytical calculation using hypergeometric distribution
            # P(at least 1 positive in random K selections from average daily pool)
            avg_machines_per_day = len(test_df) / len(test_df['date'].unique())
            avg_positives_per_day = y_test.sum() / len(test_df['date'].unique())

            k_clamped_baseline = min(k, int(avg_machines_per_day))
            if avg_machines_per_day > k_clamped_baseline and avg_positives_per_day > 0:
                # P(all K are negative) = C(N-M, K) / C(N, K)
                try:
                    prob_no_positive = comb(int(avg_machines_per_day - avg_positives_per_day), k_clamped_baseline, exact=False) / \
                                      comb(int(avg_machines_per_day), k_clamped_baseline, exact=False)
                    baseline_prob = 1 - prob_no_positive
                except:
                    baseline_prob = min(k_clamped_baseline / avg_machines_per_day, 1.0)
            else:
                baseline_prob = min(k_clamped_baseline / max(avg_machines_per_day, 1), 1.0)

            baseline_prob = min(max(baseline_prob, 0), 1)  # Clamp to [0, 1]

            daily_results[k] = {
                'k': k,
                'hit_rate_model': float(hit_rate),
                'hit_rate_random_baseline': float(baseline_prob),
                'lift_vs_random': float(hit_rate / max(baseline_prob, 0.001)),
                'valid_days': valid_days
            }

        daily_hit_results[target_name] = {
            'total_test_days': len(test_df['date'].unique()),
            'daily_evaluations': daily_results
        }

    return daily_hit_results

def main():
    print("[Phase 7-3] Feature Importance & Threshold Optimization (Extended)")

    # Load data
    print(f"\nLoading data from {COPY_DB.name}...")
    df = load_data(COPY_DB)
    X, y_dict, dates = prepare_features(df)
    print(f"Features: {X.shape[1]} columns, {len(df)} rows")

    # Feature importance
    print("\nExtracting feature importance...")
    feature_importance = extract_feature_importance(X, y_dict, dates)

    print("\n=== Feature Importance (Top 10) ===")
    for target_name, data in feature_importance.items():
        print(f"\n{target_name}:")
        for i, (feat, imp) in enumerate(list(data['importances'].items())[:10], 1):
            try:
                feat_safe = feat.encode('ascii', 'replace').decode('ascii')[:30]
            except:
                feat_safe = f"feature_{i}"
            print(f"  {i:2d}. {feat_safe:30s}: {imp:.4f}")

    # Phase 1: Probability distribution analysis
    print("\n[Phase 1] Analyzing y_proba distribution...")
    proba_dist = analyze_proba_distribution(X, y_dict, dates, feature_importance)

    print("\n=== y_proba Distribution (Diagnostic) ===")
    percentile_labels = ['min', 'p1', 'p5', 'p25', 'p50', 'p75', 'p90', 'p95', 'p99', 'max']
    for target_name, dist in proba_dist.items():
        print(f"\n{target_name}:")
        print(f"  {'':8s} {' '.join(f'{l:>8s}' for l in percentile_labels)}")
        overall_str = ' '.join(f"{v:8.4f}" for v in dist['overall'])
        print(f"  {'all':8s} {overall_str}")
        pos_str = ' '.join(f"{v:8.4f}" if not np.isnan(v) else '    nan ' for v in dist['positive'])
        print(f"  {'pos':8s} {pos_str}")
        neg_str = ' '.join(f"{v:8.4f}" if not np.isnan(v) else '    nan ' for v in dist['negative'])
        print(f"  {'neg':8s} {neg_str}")

    # Phase 2: Extended threshold optimization
    print("\n[Phase 2] Extended threshold optimization...")
    threshold_results_ext = optimize_thresholds_extended(X, y_dict, dates, feature_importance, proba_dist)

    print("\n=== Extended Threshold Analysis ===")
    for target_name, data in threshold_results_ext.items():
        print(f"\n{target_name} (baseline: {data['baseline_precision']:.2%}, test_size: {data['test_size']}):")
        print(f"{'thresh':>10s} {'precision':>12s} {'recall':>10s} {'f1':>10s} {'lift':>8s} {'pred+':>8s}")
        print("-" * 70)
        for row in data['thresholds']:
            print(f"{row['threshold']:10.4f} {row['precision']:12.2%} {row['recall']:10.2%} "
                  f"{row['f1']:10.4f} {row['precision_lift']:8.2f}x {row['pred_positive_count']:8d}")
        print(f"\nOptimal threshold (max F1): {data['optimal_threshold_f1']:.4f} (F1={data['optimal_f1']:.4f})")

    # Phase 3: Top-K evaluation
    print("\n[Phase 3] Top-K recommendation evaluation...")
    top_k_results = evaluate_top_k(X, y_dict, dates, feature_importance)

    print("\n=== Top-K Evaluation ===")
    for target_name, data in top_k_results.items():
        print(f"\n{target_name} (baseline: {data['baseline_precision']:.2%}, total_pos: {data['total_positives']}):")
        print(f"{'K':>5s} {'precision@K':>12s} {'recall@K':>12s} {'lift@K':>10s} {'TP':>6s}")
        print("-" * 50)
        for row in data['k_evaluations']:
            print(f"{row['k']:5d} {row['precision_at_k']:12.2%} {row['recall_at_k']:12.2%} "
                  f"{row['lift_at_k']:10.2f}x {row['true_positives']:6d}")

    # Phase 4: Daily hit rate evaluation
    print("\n[Phase 4] Daily hit rate evaluation...")
    daily_hit_results = evaluate_daily_hit_rate(X, y_dict, dates, feature_importance)

    print("\n=== Daily Hit Rate@K (Business Metric) ===")
    for target_name, data in daily_hit_results.items():
        print(f"\n{target_name} (total_test_days: {data['total_test_days']}):")
        print(f"{'K':>5s} {'hit_rate':>12s} {'random_baseline':>16s} {'lift_vs_random':>15s}")
        print("-" * 50)
        for evals in sorted(data['daily_evaluations'].values(), key=lambda x: x['k']):
            print(f"{evals['k']:5d} {evals['hit_rate_model']:12.2%} {evals['hit_rate_random_baseline']:16.2%} "
                  f"{evals['lift_vs_random']:15.2f}x")

    # Save all results
    print("\n[OK] Saving all analysis results...")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    analysis_output = {
        'timestamp': datetime.now().isoformat(),
        'feature_importance': {
            k: v['importances'] for k, v in feature_importance.items()
        },
        'proba_distribution': {
            k: {
                'percentiles': v['percentiles'],
                'overall': v['overall'],
                'positive': v['positive'],
                'negative': v['negative']
            }
            for k, v in proba_dist.items()
        },
        'threshold_optimization_extended': {
            k: {
                'baseline_precision': v['baseline_precision'],
                'optimal_threshold_f1': v['optimal_threshold_f1'],
                'optimal_f1': v['optimal_f1'],
                'thresholds': v['thresholds'],
                'test_size': v['test_size']
            }
            for k, v in threshold_results_ext.items()
        },
        'top_k_evaluation': {
            k: {
                'baseline_precision': v['baseline_precision'],
                'total_positives': v['total_positives'],
                'test_size': v['test_size'],
                'k_evaluations': v['k_evaluations']
            }
            for k, v in top_k_results.items()
        },
        'daily_hit_rate': daily_hit_results
    }

    analysis_path = RESULTS_DIR / "analysis.json"
    with open(analysis_path, 'w') as f:
        json.dump(analysis_output, f, indent=2)
    print(f"[OK] Saved analysis to {analysis_path}")

if __name__ == "__main__":
    main()
