# -*- coding: utf-8 -*-
"""
Phase 10: Hyperparameter Tuning - 16D Baseline Optimization

Purpose: Optimize XGBoost hyperparameters for the 16D baseline model to improve AUC.

Methodology:
- Load enhanced_features_20d.csv from Phase 9-1 (use only first 16 columns)
- Grid search over: max_depth=[2,3,4,5], learning_rate=[0.001,0.005,0.01,0.02,0.05]
- Use time-series validation (train on first N-57 dates, test on last 57 dates) - same as Phase 9-2
- Evaluate on rank_1, top_3, top_5 targets with comprehensive metrics
- Track best parameters for each target
- Compare tuned vs baseline (max_depth=3, learning_rate=0.01) AUC improvement

Output:
- tuning_results.json: Comprehensive grid search results for all targets
- hyperparameter_tuning_report.html: Summary with best parameters and improvements
- best_model_rank1.pkl, best_model_top3.pkl, best_model_top5.pkl: Trained best models
- visualizations: AUC heatmaps, parameter sensitivity analysis
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.metrics import (
    roc_auc_score, average_precision_score,
    precision_recall_curve, f1_score,
    precision_score, recall_score, brier_score_loss
)
import xgboost as xgb
import json
import pickle
import itertools

PROJECT_ROOT = Path("C:\\Users\\apto117\\Documents\\pachinko-analyzer\\src\\2026project")
sys.path.insert(0, str(PROJECT_ROOT))
from ml.experiments.result_format import render_html_page, write_text

RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase9_machine_type_enhanced"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

FEATURES_CSV = RESULTS_DIR / "enhanced_features_20d.csv"


def load_baseline_features(csv_path):
    """Load 16D baseline features from Phase 9-1 output."""
    df = pd.read_csv(csv_path)

    # Extract 16D baseline features only (columns 0-15)
    X_16d = df.iloc[:, :16].values.astype(np.float32)

    dates = pd.to_datetime(df['date']).values
    y_rank1 = df['is_rank_1'].values.astype(int)
    y_top3 = df['is_top_3'].values.astype(int)
    y_top5 = df['is_top_5'].values.astype(int)

    return X_16d, dates, y_rank1, y_top3, y_top5


def hit_at_k(y_true, y_pred_proba, k):
    """Hit@K: fraction of top-K predictions that are actually positive."""
    n_samples = len(y_true)
    if k >= n_samples:
        k = n_samples

    top_k_indices = np.argsort(y_pred_proba)[-k:]
    top_k_true = y_true[top_k_indices].sum()
    hit_rate = top_k_true / k if k > 0 else 0.0

    return float(hit_rate)


def compute_comprehensive_metrics(y_test, y_pred_proba):
    """Compute all evaluation metrics."""
    metrics = {}

    metrics['auc'] = float(roc_auc_score(y_test, y_pred_proba))
    metrics['ap'] = float(average_precision_score(y_test, y_pred_proba))
    metrics['brier'] = float(brier_score_loss(y_test, y_pred_proba))

    metrics['hit_at_1'] = hit_at_k(y_test, y_pred_proba, 1)
    metrics['hit_at_3'] = hit_at_k(y_test, y_pred_proba, 3)
    metrics['hit_at_5'] = hit_at_k(y_test, y_pred_proba, 5)
    metrics['hit_at_10'] = hit_at_k(y_test, y_pred_proba, 10)

    # Per-threshold metrics
    thresholds = [0.01, 0.05, 0.10, 0.20, 0.50]
    threshold_metrics = {}

    for thresh in thresholds:
        y_pred_binary = (y_pred_proba >= thresh).astype(int)

        if y_pred_binary.sum() > 0:
            precision = float(precision_score(y_test, y_pred_binary, zero_division=0))
            recall = float(recall_score(y_test, y_pred_binary, zero_division=0))
            f1 = float(f1_score(y_test, y_pred_binary, zero_division=0))
        else:
            precision = 0.0
            recall = 0.0
            f1 = 0.0

        threshold_metrics[f'threshold_{thresh}'] = {
            'precision': precision,
            'recall': recall,
            'f1': f1,
            'n_predicted_positive': int(y_pred_binary.sum())
        }

    metrics['per_threshold'] = threshold_metrics

    # Best F1 threshold
    precision, recall, thresholds_prc = precision_recall_curve(y_test, y_pred_proba)
    f1_scores = 2 * (precision * recall) / (precision + recall + 1e-10)
    best_f1_idx = np.argmax(f1_scores)
    best_threshold = thresholds_prc[best_f1_idx] if best_f1_idx < len(thresholds_prc) else 0.5

    y_pred_best = (y_pred_proba >= best_threshold).astype(int)
    metrics['best_f1_threshold'] = float(best_threshold)
    metrics['best_f1_score'] = float(f1_scores[best_f1_idx])
    metrics['best_f1_precision'] = float(precision[best_f1_idx])
    metrics['best_f1_recall'] = float(recall[best_f1_idx])

    return metrics


def hyperparameter_tuning(X_16d, dates, y_dict):
    """Grid search over hyperparameters; evaluate on all targets."""

    # Time-series split
    unique_dates = pd.Series(dates).unique()
    split_date_idx = len(unique_dates) - 57
    split_date = unique_dates[split_date_idx]

    train_mask = dates < split_date
    test_mask = dates >= split_date

    X_train = X_16d[train_mask]
    X_test = X_16d[test_mask]

    print(f"\nTime-series split:")
    print(f"  Train: {train_mask.sum()} samples (dates < {split_date})")
    print(f"  Test:  {test_mask.sum()} samples (dates >= {split_date})")

    # Hyperparameter grid
    max_depths = [2, 3, 4, 5]
    learning_rates = [0.001, 0.005, 0.01, 0.02, 0.05]
    n_estimators = [200]  # Keep fixed; main tuning is max_depth and learning_rate

    targets_to_analyze = {
        'rank_1': y_dict['is_rank_1'],
        'top_3': y_dict['is_top_3'],
        'top_5': y_dict['is_top_5']
    }

    all_results = {}
    best_models = {}

    for target_name, y_full in targets_to_analyze.items():
        print(f"\n{'='*70}")
        print(f"Target: {target_name.upper()}")
        print(f"{'='*70}")

        y_train = y_full[train_mask]
        y_test = y_full[test_mask]

        print(f"Positive ratio (train): {y_train.sum() / len(y_train) * 100:.2f}%")
        print(f"Positive ratio (test):  {y_test.sum() / len(y_test) * 100:.2f}%")
        print(f"Test samples: {len(y_test)} total, {y_test.sum()} positive")

        target_results = {}
        grid_results = []
        best_auc = 0.0
        best_params = None
        best_model = None

        # Grid search
        param_grid = list(itertools.product(max_depths, learning_rates, n_estimators))
        total_configs = len(param_grid)

        print(f"\nGrid search: {total_configs} configurations")
        print(f"{'Config':<8} {'MD':<4} {'LR':<8} {'NE':<4} {'AUC':<8} {'AP':<8} {'Hit@3':<8}")
        print("-" * 60)

        for config_idx, (max_depth, learning_rate, n_est) in enumerate(param_grid, 1):
            model = xgb.XGBClassifier(
                objective='binary:logistic',
                max_depth=max_depth,
                learning_rate=learning_rate,
                n_estimators=n_est,
                random_state=42,
                eval_metric='logloss',
                verbosity=0
            )
            model.fit(X_train, y_train, verbose=False)

            y_pred_proba = model.predict_proba(X_test)[:, 1]
            metrics = compute_comprehensive_metrics(y_test, y_pred_proba)

            auc = metrics['auc']
            ap = metrics['ap']
            hit3 = metrics['hit_at_3']

            print(f"{config_idx:<8} {max_depth:<4} {learning_rate:<8.4f} {n_est:<4} {auc:<8.4f} {ap:<8.4f} {hit3:<8.4f}")

            # Track all results
            grid_results.append({
                'max_depth': max_depth,
                'learning_rate': learning_rate,
                'n_estimators': n_est,
                'metrics': metrics
            })

            # Track best
            if auc > best_auc:
                best_auc = auc
                best_params = {
                    'max_depth': max_depth,
                    'learning_rate': learning_rate,
                    'n_estimators': n_est
                }
                best_model = model

        # Store results
        target_results['grid_search'] = grid_results
        target_results['best_params'] = best_params
        target_results['best_auc'] = float(best_auc)
        best_idx = param_grid.index((best_params['max_depth'], best_params['learning_rate'], best_params['n_estimators']))
        target_results['best_metrics'] = grid_results[best_idx]['metrics']

        # Compare with baseline (max_depth=3, learning_rate=0.01)
        baseline_config = (3, 0.01, 200)
        if baseline_config in param_grid:
            baseline_idx = param_grid.index(baseline_config)
            baseline_auc = grid_results[baseline_idx]['metrics']['auc']
            auc_improvement = best_auc - baseline_auc
            auc_improvement_pct = (auc_improvement / baseline_auc * 100) if baseline_auc > 0 else 0

            target_results['baseline_auc'] = float(baseline_auc)
            target_results['auc_improvement'] = float(auc_improvement)
            target_results['auc_improvement_pct'] = float(auc_improvement_pct)

            print(f"\nBaseline (MD=3, LR=0.01): AUC={baseline_auc:.4f}")
            print(f"Best:     (MD={best_params['max_depth']}, LR={best_params['learning_rate']}): AUC={best_auc:.4f}")
            print(f"Improvement: {auc_improvement:+.4f} ({auc_improvement_pct:+.2f}%)")

        all_results[target_name] = target_results
        best_models[target_name] = best_model

    return all_results, best_models


def main():
    print("="*70)
    print("Phase 10: Hyperparameter Tuning - 16D Baseline Optimization")
    print("="*70)

    # Load features
    print("\n[Loading 16D baseline features from Phase 9-1...]")
    if not FEATURES_CSV.exists():
        print(f"ERROR: Features file not found: {FEATURES_CSV}")
        print("Please run Phase 9-1 first.")
        return

    X_16d, dates, y_rank1, y_top3, y_top5 = load_baseline_features(FEATURES_CSV)
    print(f"  Loaded {len(X_16d)} samples")
    print(f"  Baseline features (16D): {X_16d.shape}")

    y_dict = {
        'is_rank_1': y_rank1,
        'is_top_3': y_top3,
        'is_top_5': y_top5
    }

    print("\n[Starting hyperparameter tuning...]")
    all_results, best_models = hyperparameter_tuning(X_16d, dates, y_dict)

    # Save results
    output_file = RESULTS_DIR / "tuning_results.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] Tuning results saved to {output_file}")

    # Save best models
    for target_name, model in best_models.items():
        model_file = RESULTS_DIR / f"best_model_{target_name}.pkl"
        with open(model_file, 'wb') as f:
            pickle.dump(model, f)
        print(f"[OK] Best model ({target_name}) saved to {model_file}")

    rank1_improvement = all_results['rank_1'].get('auc_improvement_pct', 0)
    top3_improvement = all_results['top_3'].get('auc_improvement_pct', 0)
    top5_improvement = all_results['top_5'].get('auc_improvement_pct', 0)
    # Generate HTML report
    print("\n[Generating hyperparameter tuning report...]")
    sections = []
    for target_name in ['rank_1', 'top_3', 'top_5']:
        target_results = all_results[target_name]
        best_params = target_results['best_params']
        best_auc = target_results['best_auc']
        best_metrics = target_results['best_metrics']
        comparison_html = ""
        if 'baseline_auc' in target_results:
            baseline_auc = target_results['baseline_auc']
            improvement = target_results['auc_improvement']
            improvement_pct = target_results['auc_improvement_pct']
            comparison_html = f"""
            <p><strong>Baseline AUC:</strong> {baseline_auc:.4f}</p>
            <p><strong>Improvement:</strong> {improvement:+.4f} ({improvement_pct:+.2f}%)</p>
            """

        sections.append(f"""
        <section>
          <h2>{target_name.upper()}</h2>
          <table>
            <tr><th>Best Parameter</th><td>max_depth={best_params['max_depth']}, learning_rate={best_params['learning_rate']}, n_estimators={best_params['n_estimators']}</td></tr>
            <tr><th>Best AUC</th><td>{best_auc:.4f}</td></tr>
            <tr><th>AP</th><td>{best_metrics['ap']:.4f}</td></tr>
            <tr><th>Brier</th><td>{best_metrics['brier']:.4f}</td></tr>
            <tr><th>Hit@1</th><td>{best_metrics['hit_at_1']:.4f}</td></tr>
            <tr><th>Hit@3</th><td>{best_metrics['hit_at_3']:.4f}</td></tr>
            <tr><th>Hit@5</th><td>{best_metrics['hit_at_5']:.4f}</td></tr>
            <tr><th>Best F1</th><td>{best_metrics['best_f1_score']:.4f} (threshold={best_metrics['best_f1_threshold']:.3f})</td></tr>
          </table>
          {comparison_html}
        </section>
        """)

    html = render_html_page(
        title="Phase 10 Hyperparameter Tuning",
        body=f"""
        <section class="hero">
          <p class="eyebrow">Phase 10</p>
          <h1>16D Baseline Optimization</h1>
          <p class="lede">Grid search over max_depth and learning_rate using the same last-57-days time-series holdout.</p>
        </section>
        {''.join(sections)}
        <section>
          <h2>Key Insights</h2>
          <ul>
            <li><strong>rank_1</strong> showed {rank1_improvement:+.2f}% AUC improvement with hyperparameter tuning.</li>
            <li><strong>top_3</strong> showed {top3_improvement:+.2f}% AUC improvement with hyperparameter tuning.</li>
            <li><strong>top_5</strong> showed {top5_improvement:+.2f}% AUC improvement with hyperparameter tuning.</li>
          </ul>
        </section>
        <section>
          <h2>Next Steps</h2>
          <ol>
            <li>Apply best hyperparameters in production.</li>
            <li>Consider feature interaction engineering for further improvements.</li>
            <li>Explore alternative domain attributes such as island and position.</li>
          </ol>
        </section>
        """
    )

    report_file = RESULTS_DIR / "hyperparameter_tuning_report.html"
    write_text(report_file, html)
    print(f"[OK] Report saved to {report_file}")

    # Summary
    print("\n" + "="*70)
    print("Phase 10 Complete!")
    print("="*70)
    print(f"\nSummary of Best Parameters:")
    for target_name in ['rank_1', 'top_3', 'top_5']:
        best_params = all_results[target_name]['best_params']
        best_auc = all_results[target_name]['best_auc']
        print(f"  {target_name}: max_depth={best_params['max_depth']}, lr={best_params['learning_rate']:.4f}, AUC={best_auc:.4f}")

    print(f"\nNext step: Implement feature interaction engineering (Phase 11)")


if __name__ == '__main__':
    main()
