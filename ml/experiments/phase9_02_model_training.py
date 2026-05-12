# -*- coding: utf-8 -*-
"""
Phase 9-2: Model Training - Baseline vs Enhanced Comparison

Purpose: Train XGBoost models with 16D baseline and 20D enhanced (with machine-type) features.
Compare performance across all evaluation metrics.

Methodology:
- Load enhanced_features_20d.csv from Phase 9-1
- Extract 16D baseline features (first 16 columns) and 20D enhanced (all 20 columns)
- Train XGBoost models with identical hyperparameters (max_depth=3, learning_rate=0.01)
- Use time-series validation (train on first N-57 dates, test on last 57 dates)
- Evaluate on rank_1, top_3, top_5 targets with comprehensive metrics

Evaluation metrics:
- AUC (primary metric for ranking)
- Average Precision (handles class imbalance)
- Hit@K (K=1,3,5,10): % of true positives in top K predictions
- Best F1 score with threshold optimization
- Recall, Precision at multiple thresholds
- Brier score (calibration)

Output:
- metrics_comparison.json: Side-by-side comparison of baseline vs enhanced
- model_comparison_report.html: HTML summary with AUC improvements
- Visualizations: confusion matrices, ROC curves (in Phase 9-4)
"""

import sqlite3
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

PROJECT_ROOT = Path("C:\\Users\\apto117\\Documents\\pachinko-analyzer\\src\\2026project")
sys.path.insert(0, str(PROJECT_ROOT))
from ml.experiments.result_format import render_html_page, write_text

RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase9_machine_type_enhanced"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

FEATURES_CSV = RESULTS_DIR / "enhanced_features_20d.csv"


def load_enhanced_features(csv_path):
    """Load enhanced features from Phase 9-1 output."""
    df = pd.read_csv(csv_path)

    # Extract feature columns (0-19), metadata, and targets
    X_20d = df.iloc[:, :20].values.astype(np.float32)
    X_16d = df.iloc[:, :16].values.astype(np.float32)

    dates = pd.to_datetime(df['date']).values
    y_rank1 = df['is_rank_1'].values.astype(int)
    y_top3 = df['is_top_3'].values.astype(int)
    y_top5 = df['is_top_5'].values.astype(int)

    return X_16d, X_20d, dates, y_rank1, y_top3, y_top5


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


def train_and_evaluate_models(X_16d, X_20d, dates, y_dict):
    """Train baseline (16D) and enhanced (20D) models; comprehensively evaluate."""
    results = {}

    # Time-series split: train on first N-57 dates, test on last 57 dates
    unique_dates = pd.Series(dates).unique()
    split_date_idx = len(unique_dates) - 57
    split_date = unique_dates[split_date_idx]

    train_mask = dates < split_date
    test_mask = dates >= split_date

    X_train_16d = X_16d[train_mask]
    X_test_16d = X_16d[test_mask]
    X_train_20d = X_20d[train_mask]
    X_test_20d = X_20d[test_mask]

    print(f"\nTime-series split:")
    print(f"  Train: {train_mask.sum()} samples (dates < {split_date})")
    print(f"  Test:  {test_mask.sum()} samples (dates >= {split_date})")

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
        print(f"Test samples: {len(y_test)} total, {y_test.sum()} positive")

        target_results = {}

        # Train and evaluate baseline (16D) and enhanced (20D) models
        for model_name, X_train, X_test in [
            ('16D Baseline', X_train_16d, X_test_16d),
            ('20D Enhanced', X_train_20d, X_test_20d)
        ]:
            print(f"\n[{model_name}]")
            model = xgb.XGBClassifier(
                objective='binary:logistic',
                max_depth=3,
                learning_rate=0.01,
                n_estimators=200,
                random_state=42,
                eval_metric='logloss',
                verbosity=0
            )
            model.fit(X_train, y_train, verbose=False)

            y_pred_proba = model.predict_proba(X_test)[:, 1]
            metrics = compute_comprehensive_metrics(y_test, y_pred_proba)

            print(f"  AUC:       {metrics['auc']:.4f}")
            print(f"  AP:        {metrics['ap']:.4f}")
            print(f"  Hit@1:     {metrics['hit_at_1']:.4f}")
            print(f"  Hit@3:     {metrics['hit_at_3']:.4f}")
            print(f"  Hit@5:     {metrics['hit_at_5']:.4f}")
            print(f"  Best F1:   {metrics['best_f1_score']:.4f} (thresh={metrics['best_f1_threshold']:.3f}, recall={metrics['best_f1_recall']:.4f})")

            target_results[model_name] = metrics

        # Compute improvement
        baseline_auc = target_results['16D Baseline']['auc']
        enhanced_auc = target_results['20D Enhanced']['auc']
        auc_improvement = enhanced_auc - baseline_auc
        auc_improvement_pct = (auc_improvement / baseline_auc * 100) if baseline_auc > 0 else 0

        baseline_ap = target_results['16D Baseline']['ap']
        enhanced_ap = target_results['20D Enhanced']['ap']
        ap_improvement = enhanced_ap - baseline_ap

        print(f"\nImprovement (20D vs 16D):")
        print(f"  AUC delta: {auc_improvement:+.4f} ({auc_improvement_pct:+.2f}%)")
        print(f"  AP delta:  {ap_improvement:+.4f}")

        target_results['improvement'] = {
            'auc_delta': float(auc_improvement),
            'auc_improvement_pct': float(auc_improvement_pct),
            'ap_delta': float(ap_improvement)
        }

        results[target_name] = target_results

    return results


def main():
    print("="*70)
    print("Phase 9-2: Model Training - Baseline vs Enhanced Comparison")
    print("="*70)

    # Load features from Phase 9-1
    print("\n[Loading enhanced features from Phase 9-1...]")
    if not FEATURES_CSV.exists():
        print(f"ERROR: Features file not found: {FEATURES_CSV}")
        print("Please run Phase 9-1 first.")
        return

    X_16d, X_20d, dates, y_rank1, y_top3, y_top5 = load_enhanced_features(FEATURES_CSV)
    print(f"  Loaded {len(X_16d)} samples")
    print(f"  Baseline features (16D): {X_16d.shape}")
    print(f"  Enhanced features (20D): {X_20d.shape}")

    y_dict = {
        'is_rank_1': y_rank1,
        'is_top_3': y_top3,
        'is_top_5': y_top5
    }

    print("\n[Training and evaluating models...]")
    all_results = train_and_evaluate_models(X_16d, X_20d, dates, y_dict)

    # Save results
    output_file = RESULTS_DIR / "metrics_comparison.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] Results saved to {output_file}")

    # Generate HTML report
    print("\n[Generating HTML report...]")
    sections = []
    for target_name in ['rank_1', 'top_3', 'top_5']:
        target_results = all_results[target_name]
        improvement = target_results['improvement']
        baseline_auc = target_results['16D Baseline']['auc']
        enhanced_auc = target_results['20D Enhanced']['auc']
        baseline_ap = target_results['16D Baseline']['ap']
        enhanced_ap = target_results['20D Enhanced']['ap']
        baseline_hit3 = target_results['16D Baseline']['hit_at_3']
        enhanced_hit3 = target_results['20D Enhanced']['hit_at_3']
        baseline_f1 = target_results['16D Baseline']['best_f1_score']
        enhanced_f1 = target_results['20D Enhanced']['best_f1_score']

        sections.append(f"""
        <section>
          <h2>{target_name.upper()}</h2>
          <table>
            <tr><th>Metric</th><th>16D Baseline</th><th>20D Enhanced</th><th>Delta</th><th>Delta %</th></tr>
            <tr><td>AUC</td><td>{baseline_auc:.4f}</td><td>{enhanced_auc:.4f}</td><td>{improvement['auc_delta']:+.4f}</td><td>{improvement['auc_improvement_pct']:+.2f}%</td></tr>
            <tr><td>AP</td><td>{baseline_ap:.4f}</td><td>{enhanced_ap:.4f}</td><td>{improvement['ap_delta']:+.4f}</td><td>-</td></tr>
            <tr><td>Hit@3</td><td>{baseline_hit3:.4f}</td><td>{enhanced_hit3:.4f}</td><td>{enhanced_hit3 - baseline_hit3:+.4f}</td><td>-</td></tr>
            <tr><td>Best F1</td><td>{baseline_f1:.4f}</td><td>{enhanced_f1:.4f}</td><td>{enhanced_f1 - baseline_f1:+.4f}</td><td>-</td></tr>
          </table>
        </section>
        """)

    html = render_html_page(
        title="Phase 9-2 Model Comparison",
        body="""
        <section class="hero">
          <p class="eyebrow">Phase 9-2</p>
          <h1>Baseline vs Enhanced Comparison</h1>
          <p class="lede">16D baseline features and 20D machine-type-enhanced features evaluated on the same time-series split.</p>
        </section>
        """ + "".join(sections)
    )
    report_file = RESULTS_DIR / "model_comparison_report.html"
    write_text(report_file, html)
    print(f"[OK] Report saved to {report_file}")

    # Summary
    print("\n" + "="*70)
    print("Phase 9-2 Complete!")
    print("="*70)
    print(f"\nSummary:")
    for target_name in ['rank_1', 'top_3', 'top_5']:
        improvement = all_results[target_name]['improvement']
        print(f"  {target_name}: AUC improvement {improvement['auc_improvement_pct']:+.2f}% ({improvement['auc_delta']:+.4f})")
    print(f"\nNext step: Run Phase 9-3 to analyze feature importance and interactions")


if __name__ == '__main__':
    main()
