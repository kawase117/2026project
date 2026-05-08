"""
Phase 8-3: Comprehensive Comparison of All Models (16D vs 25D vs 40D+)

Evaluates all three feature engineering approaches using comprehensive metrics:
- Discrimination: AUC, AP (Average Precision)
- Top-K: Hit@3, Hit@10 (key user request for imbalanced data)
- Classification: Precision, Recall, F1 at multiple thresholds
- Calibration: Brier score
- Per-threshold: Recall, Precision at threshold=0.01, 0.05, 0.10, 0.20, 0.50

Compares:
1. 16D Baseline (Phase 7 model)
2. 25D Extended (Phase 8-1: days_since hierarchies)
3. 40D+ Trend & Binning (Phase 8-2: trend features + binning)

For imbalanced targets (rank_1: 1.4%, top_3: 4.3%, top_5: 7.1%),
Hit@K and Recall are more informative than AUC alone.
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
RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase8_comprehensive_all_models"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def load_data(db_path):
    """Load data from copy DB."""
    conn = sqlite3.connect(db_path)

    df_machine = pd.read_sql_query("""
        SELECT
            date, machine_name, machine_count,
            avg_diff_7d, avg_diff_14d, avg_diff_21d, avg_diff_28d, avg_diff_35d,
            avg_games_7d, avg_games_14d, avg_games_21d, avg_games_28d, avg_games_35d,
            avg_efficiency_7d, avg_efficiency_14d, avg_efficiency_21d, avg_efficiency_28d, avg_efficiency_35d,
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


def prepare_16d_baseline(df):
    """Prepare 16D base features (Phase 7 baseline)."""
    X_16d = []
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

        X_16d.append(features)

    return np.array(X_16d)


def prepare_25d_extended(df):
    """Prepare 25D extended features (Phase 8-1: days_since hierarchies)."""
    X_extended = []

    days_since_rank1 = compute_days_since_last_rank(df, 'is_rank_1')
    days_since_rank3 = compute_days_since_last_rank(df, 'is_top_3')
    days_since_rank5 = compute_days_since_last_rank(df, 'is_top_5')

    for idx, row in df.iterrows():
        features = []

        day_of_month = row['date'].day
        days_in_month = (pd.to_datetime(row['date']) + pd.DateOffset(months=1)).replace(day=1) - pd.Timedelta(days=1)
        month_progress = day_of_month / days_in_month.day
        features.append(month_progress)

        r1 = float(days_since_rank1[idx])
        r3 = float(days_since_rank3[idx])
        r5 = float(days_since_rank5[idx])
        features.extend([r1, r3, r5])

        ratio_3_1 = r3 / r1 if r1 > 0 else 1.0
        ratio_5_1 = r5 / r1 if r1 > 0 else 1.0
        ratio_5_3 = r5 / r3 if r3 > 0 else 1.0
        features.extend([ratio_3_1, ratio_5_1, ratio_5_3])

        diff_1_3 = r1 - r3
        diff_1_5 = r1 - r5
        diff_3_5 = r3 - r5
        features.extend([diff_1_3, diff_1_5, diff_3_5])

        days_since_any = max(r1, r3, r5)
        features.append(days_since_any)

        rolling_cols = [
            'avg_diff_7d', 'avg_diff_14d', 'avg_diff_21d', 'avg_diff_28d', 'avg_diff_35d',
            'avg_games_7d', 'avg_games_14d', 'avg_games_21d', 'avg_games_28d', 'avg_games_35d',
            'avg_efficiency_7d', 'avg_efficiency_14d', 'avg_efficiency_28d',
            'machine_count'
        ]
        rolling_vals = [float(row[col]) if col in row and pd.notna(row[col]) else 0.0 for col in rolling_cols]
        features.extend(rolling_vals)

        X_extended.append(features)

    return np.array(X_extended)


def prepare_40d_with_trends_binning(df):
    """Prepare 40D+ features (Phase 8-2: trend + binning)."""
    X_features = []

    days_since_rank1 = compute_days_since_last_rank(df, 'is_rank_1')
    days_since_rank3 = compute_days_since_last_rank(df, 'is_top_3')
    days_since_rank5 = compute_days_since_last_rank(df, 'is_top_5')

    # Calculate statistics for binning
    avg_games_28d_values = df['avg_games_28d'].dropna()
    games_q1, games_q2, games_q3 = avg_games_28d_values.quantile([0.25, 0.5, 0.75]).values

    avg_diff_28d_values = df['avg_diff_28d'].dropna()
    diff_q1, diff_q2, diff_q3 = avg_diff_28d_values.quantile([0.25, 0.5, 0.75]).values

    machine_count_values = df['machine_count'].dropna()
    count_q1, count_q2, count_q3 = machine_count_values.quantile([0.25, 0.5, 0.75]).values

    for idx, row in df.iterrows():
        features = []

        # === 25D base features ===
        day_of_month = row['date'].day
        days_in_month = (pd.to_datetime(row['date']) + pd.DateOffset(months=1)).replace(day=1) - pd.Timedelta(days=1)
        month_progress = day_of_month / days_in_month.day
        features.append(month_progress)

        r1 = float(days_since_rank1[idx])
        r3 = float(days_since_rank3[idx])
        r5 = float(days_since_rank5[idx])
        features.extend([r1, r3, r5])

        ratio_3_1 = r3 / r1 if r1 > 0 else 1.0
        ratio_5_1 = r5 / r1 if r1 > 0 else 1.0
        ratio_5_3 = r5 / r3 if r3 > 0 else 1.0
        features.extend([ratio_3_1, ratio_5_1, ratio_5_3])

        diff_1_3 = r1 - r3
        diff_1_5 = r1 - r5
        diff_3_5 = r3 - r5
        features.extend([diff_1_3, diff_1_5, diff_3_5])

        days_since_any = max(r1, r3, r5)
        features.append(days_since_any)

        rolling_cols = [
            'avg_diff_7d', 'avg_diff_14d', 'avg_diff_21d', 'avg_diff_28d', 'avg_diff_35d',
            'avg_games_7d', 'avg_games_14d', 'avg_games_21d', 'avg_games_28d', 'avg_games_35d',
            'avg_efficiency_7d', 'avg_efficiency_14d', 'avg_efficiency_28d',
            'machine_count'
        ]
        rolling_vals = [float(row[col]) if col in row and pd.notna(row[col]) else 0.0 for col in rolling_cols]
        features.extend(rolling_vals)

        # === Trend features (3D) ===
        diff_7 = float(row['avg_diff_7d']) if pd.notna(row['avg_diff_7d']) else 0.0
        diff_35 = float(row['avg_diff_35d']) if pd.notna(row['avg_diff_35d']) else 0.0
        diff_trend = diff_7 - diff_35
        features.append(diff_trend)

        games_7 = float(row['avg_games_7d']) if pd.notna(row['avg_games_7d']) else 0.0
        games_35 = float(row['avg_games_35d']) if pd.notna(row['avg_games_35d']) else 0.0
        games_trend = games_7 - games_35
        features.append(games_trend)

        eff_7 = float(row['avg_efficiency_7d']) if pd.notna(row['avg_efficiency_7d']) else 0.0
        eff_35 = float(row['avg_efficiency_35d']) if pd.notna(row['avg_efficiency_35d']) else 0.0
        efficiency_trend = eff_7 - eff_35
        features.append(efficiency_trend)

        # === Binning features ===
        games_val = float(row['avg_games_28d']) if pd.notna(row['avg_games_28d']) else 0.0
        if games_val <= games_q1:
            games_bin = 0
        elif games_val <= games_q2:
            games_bin = 1
        elif games_val <= games_q3:
            games_bin = 2
        else:
            games_bin = 3
        for i in range(4):
            features.append(1.0 if i == games_bin else 0.0)

        diff_val = float(row['avg_diff_28d']) if pd.notna(row['avg_diff_28d']) else 0.0
        if diff_val <= diff_q1:
            diff_bin = 0
        elif diff_val <= diff_q2:
            diff_bin = 1
        elif diff_val <= diff_q3:
            diff_bin = 2
        else:
            diff_bin = 3
        for i in range(4):
            features.append(1.0 if i == diff_bin else 0.0)

        count_val = float(row['machine_count']) if pd.notna(row['machine_count']) else 0.0
        if count_val <= count_q1:
            count_bin = 0
        elif count_val <= count_q2:
            count_bin = 1
        elif count_val <= count_q3:
            count_bin = 2
        else:
            count_bin = 3
        for i in range(4):
            features.append(1.0 if i == count_bin else 0.0)

        X_features.append(features)

    return np.array(X_features)


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


def train_and_evaluate_all_models(X_16d, X_25d, X_40d, y_dict, dates):
    """Train all models and comprehensively evaluate."""
    results = {}

    unique_dates = pd.Series(dates).unique()
    split_date_idx = len(unique_dates) - 57
    split_date = unique_dates[split_date_idx]

    train_mask = dates < split_date
    test_mask = dates >= split_date

    X_train_16d = X_16d[train_mask]
    X_test_16d = X_16d[test_mask]
    X_train_25d = X_25d[train_mask]
    X_test_25d = X_25d[test_mask]
    X_train_40d = X_40d[train_mask]
    X_test_40d = X_40d[test_mask]

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

        # Train and evaluate each model
        for model_name, X_train, X_test in [
            ('16D Baseline', X_train_16d, X_test_16d),
            ('25D Extended', X_train_25d, X_test_25d),
            ('40D+ Trend&Binning', X_train_40d, X_test_40d)
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
            print(f"  Hit@3:     {metrics['hit_at_3']:.4f}")
            print(f"  Hit@10:    {metrics['hit_at_10']:.4f}")
            print(f"  Best F1:   {metrics['best_f1_score']:.4f} (thresh={metrics['best_f1_threshold']:.3f}, recall={metrics['best_f1_recall']:.4f})")

            target_results[model_name] = metrics

        results[target_name] = target_results

    return results


def main():
    print("="*70)
    print("Phase 8-3: Comprehensive All-Models Comparison")
    print("="*70)

    print("\n[Loading data...]")
    df = load_data(COPY_DB)

    print("[Preparing 16D baseline features...]")
    X_16d = prepare_16d_baseline(df)

    print("[Preparing 25D extended features (Phase 8-1)...]")
    X_25d = prepare_25d_extended(df)

    print("[Preparing 40D+ trend & binning features (Phase 8-2)...]")
    X_40d = prepare_40d_with_trends_binning(df)

    print(f"\nFeature dimensions: 16D={X_16d.shape[1]}, 25D={X_25d.shape[1]}, 40D+={X_40d.shape[1]}")

    y_dict = {
        'is_rank_1': df['is_rank_1'].values,
        'is_top_3': df['is_top_3'].values,
        'is_top_5': df['is_top_5'].values
    }

    dates = df['date'].values

    print("\n[Training and evaluating all models...]")
    all_results = train_and_evaluate_all_models(X_16d, X_25d, X_40d, y_dict, dates)

    # Save results
    output_file = RESULTS_DIR / "phase8_comprehensive_all_models.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\n[COMPLETED] Results saved to {output_file}")

    # Print summary comparison table
    print("\n" + "="*70)
    print("SUMMARY: Model Comparison Across All Targets")
    print("="*70)

    for target_name in ['rank_1', 'top_3', 'top_5']:
        print(f"\n{target_name.upper()}:")
        print(f"{'Model':<25} {'AUC':<10} {'AP':<10} {'Hit@3':<10} {'Hit@10':<10} {'Best Recall':<10}")
        print("-" * 75)

        for model_name in ['16D Baseline', '25D Extended', '40D+ Trend&Binning']:
            m = all_results[target_name][model_name]
            print(f"{model_name:<25} {m['auc']:<10.4f} {m['ap']:<10.4f} {m['hit_at_3']:<10.4f} {m['hit_at_10']:<10.4f} {m['best_f1_recall']:<10.4f}")


if __name__ == '__main__':
    main()
