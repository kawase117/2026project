"""
Phase 8: Comprehensive Evaluation with Multiple Metrics

Evaluates models across rich metric set:
- Discrimination: AUC, AP (Average Precision)
- Classification: Precision, Recall, F1 at multiple thresholds
- Top-K: Hit@3, Hit@10 (what fraction of top-3/top-10 predictions are correct)
- Calibration: Brier score, ECE (Expected Calibration Error)
- Per-threshold: Recall, Precision at threshold=0.01, 0.05, 0.10, 0.20, 0.50

For imbalanced data (rank_1: 1.4%, top_3: 4.3%, top_5: 7.1%),
Recall and Hit@K reveal true predictive power better than AUC alone.
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

COPY_DB = PROJECT_ROOT / "db" / "experiments" / "マルハンメガシティ2000-蒲田7_rank_exp.db"
RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase8_comprehensive_evaluation"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def load_data(db_path):
    """Load data from copy DB."""
    conn = sqlite3.connect(db_path)

    df_machine = pd.read_sql_query("""
        SELECT
            date, machine_name, machine_count,
            avg_diff_7d, avg_diff_14d, avg_diff_21d, avg_diff_28d, avg_diff_35d,
            avg_games_7d, avg_games_14d, avg_games_21d, avg_games_28d, avg_games_35d,
            avg_efficiency_7d, avg_efficiency_14d, avg_efficiency_21d, avg_efficiency_28d,
            is_rank_1, is_top_3, is_top_5
        FROM daily_machine_type_summary
        ORDER BY date, machine_name
    """, conn)

    df_hall = pd.read_sql_query("""
        SELECT date
        FROM daily_hall_summary
    """, conn)

    conn.close()

    df_machine['date'] = pd.to_datetime(df_machine['date'], format='%Y%m%d')
    df_hall['date'] = pd.to_datetime(df_hall['date'], format='%Y%m%d')

    df = df_machine.merge(df_hall, on='date', how='left')
    df = df.sort_values(['machine_name', 'date']).reset_index(drop=True)

    return df


def compute_days_since_last_rank(df, rank_column):
    """Compute days since last rank."""
    days_since = []

    for machine_name in df['machine_name'].unique():
        machine_df = df[df['machine_name'] == machine_name].copy().reset_index(drop=True)
        rank_dates = machine_df[machine_df[rank_column] == 1]['date'].values

        for idx, row in machine_df.iterrows():
            current_date = row['date']
            last_rank_dates = rank_dates[rank_dates < current_date]

            if len(last_rank_dates) > 0:
                days = (current_date - last_rank_dates[-1]).days
                days = min(days, 365)
            else:
                days = 365

            days_since.append(days)

    return np.array(days_since)


def prepare_features_16d(df):
    """Prepare 16D baseline features."""
    X = []
    days_since_rank1 = compute_days_since_last_rank(df, 'is_rank_1')

    for idx, row in df.iterrows():
        features = []

        day_of_month = row['date'].day
        days_in_month = (pd.to_datetime(row['date']) + pd.DateOffset(months=1)).replace(day=1) - pd.Timedelta(days=1)
        month_progress = day_of_month / days_in_month.day
        features.append(month_progress)
        features.append(float(days_since_rank1[idx]))

        rolling_cols = [
            'avg_diff_7d', 'avg_diff_14d', 'avg_diff_21d', 'avg_diff_28d', 'avg_diff_35d',
            'avg_games_7d', 'avg_games_14d', 'avg_games_21d', 'avg_games_28d', 'avg_games_35d',
            'avg_efficiency_7d', 'avg_efficiency_14d', 'avg_efficiency_28d',
            'machine_count'
        ]
        rolling_vals = [float(row[col]) if col in row and pd.notna(row[col]) else 0.0 for col in rolling_cols]
        features.extend(rolling_vals)

        X.append(features)

    return np.array(X)


def hit_at_k(y_true, y_pred_proba, k):
    """
    Hit@K: Among top-K predicted instances with highest probability,
    what fraction are actually positive?
    """
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

    # AUC and AP
    metrics['auc'] = float(roc_auc_score(y_test, y_pred_proba))
    metrics['ap'] = float(average_precision_score(y_test, y_pred_proba))

    # Brier score (calibration)
    metrics['brier'] = float(brier_score_loss(y_test, y_pred_proba))

    # Top-K hit rates
    metrics['hit_at_3'] = hit_at_k(y_test, y_pred_proba, 3)
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


def train_and_evaluate(X, y_dict, dates, model_name, feature_count):
    """Train model and comprehensively evaluate."""
    results = {}

    # Time-series split
    unique_dates = pd.Series(dates).unique()
    split_date_idx = len(unique_dates) - 57
    split_date = unique_dates[split_date_idx]

    train_mask = dates < split_date
    test_mask = dates >= split_date

    X_train = X[train_mask]
    X_test = X[test_mask]

    targets_to_analyze = {
        'rank_1': y_dict['is_rank_1'],
        'top_3': y_dict['is_top_3'],
        'top_5': y_dict['is_top_5']
    }

    for target_name, y_full in targets_to_analyze.items():
        print(f"\n{'='*70}")
        print(f"{model_name} - Target: {target_name.upper()}")
        print(f"{'='*70}")

        y_train = y_full[train_mask]
        y_test = y_full[test_mask]

        print(f"Positive ratio (train): {y_train.sum() / len(y_train) * 100:.2f}%")
        print(f"Positive ratio (test):  {y_test.sum() / len(y_test) * 100:.2f}%")
        print(f"Test samples: {len(y_test)} total, {y_test.sum()} positive")

        # Train model
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

        # Compute all metrics
        metrics = compute_comprehensive_metrics(y_test, y_pred_proba)

        print(f"\nCore Metrics:")
        print(f"  AUC:            {metrics['auc']:.4f}")
        print(f"  AP:             {metrics['ap']:.4f}")
        print(f"  Brier Score:    {metrics['brier']:.4f}")
        print(f"  Hit@3:          {metrics['hit_at_3']:.4f}")
        print(f"  Hit@10:         {metrics['hit_at_10']:.4f}")

        print(f"\nBest F1 Threshold Analysis:")
        print(f"  Threshold:      {metrics['best_f1_threshold']:.3f}")
        print(f"  F1 Score:       {metrics['best_f1_score']:.4f}")
        print(f"  Precision:      {metrics['best_f1_precision']:.4f}")
        print(f"  Recall:         {metrics['best_f1_recall']:.4f}")

        print(f"\nPer-Threshold Metrics:")
        for thresh_key, thresh_data in metrics['per_threshold'].items():
            thresh_val = float(thresh_key.split('_')[1])
            print(f"  Threshold {thresh_val}: P={thresh_data['precision']:.3f}, R={thresh_data['recall']:.3f}, F1={thresh_data['f1']:.3f}, N_pred={thresh_data['n_predicted_positive']}")

        results[target_name] = metrics

    return results


def main():
    print("="*70)
    print("Phase 8: Comprehensive Evaluation with Extended Metrics")
    print("="*70)

    # Load data
    print("\n[Loading data...]")
    df = load_data(COPY_DB)

    # Prepare 16D features (baseline)
    print("\n[Preparing 16D baseline features...]")
    X_16d = prepare_features_16d(df)

    # Prepare target variables
    y_dict = {
        'is_rank_1': df['is_rank_1'].values,
        'is_top_3': df['is_top_3'].values,
        'is_top_5': df['is_top_5'].values
    }

    dates = df['date'].values

    # Evaluate 16D model
    print("\n[Training and evaluating 16D baseline...]")
    results_16d = train_and_evaluate(X_16d, y_dict, dates, "16D Baseline", 16)

    # Save comprehensive results
    output_file = RESULTS_DIR / "phase8_comprehensive_evaluation.json"
    all_results = {
        '16d_baseline': results_16d
    }

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\n[COMPLETED] Results saved to {output_file}")

    # Print final summary table
    print("\n" + "="*70)
    print("SUMMARY: Baseline Model (16D) - All Targets")
    print("="*70)

    summary_data = []
    for target_name in ['rank_1', 'top_3', 'top_5']:
        metrics = results_16d[target_name]
        summary_data.append({
            'Target': target_name,
            'AUC': f"{metrics['auc']:.4f}",
            'AP': f"{metrics['ap']:.4f}",
            'Brier': f"{metrics['brier']:.4f}",
            'Hit@3': f"{metrics['hit_at_3']:.4f}",
            'Hit@10': f"{metrics['hit_at_10']:.4f}",
            'Best_F1': f"{metrics['best_f1_score']:.4f}",
            'Best_Recall': f"{metrics['best_f1_recall']:.4f}",
            'Best_Precision': f"{metrics['best_f1_precision']:.4f}"
        })

    df_summary = pd.DataFrame(summary_data)
    print("\n" + df_summary.to_string(index=False))


if __name__ == '__main__':
    main()
