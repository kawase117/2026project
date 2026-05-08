"""
Phase 7-5: Rank Prediction - 18D scale_pos_weight Comparison

Tests 18D features (month_progress + days_since_last_rank1 + rolling_averages)
with Balanced vs Calibrated scale_pos_weight strategies.
Measures AUC, AP, Brier, and ECE (Expected Calibration Error).
"""

import sqlite3
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.metrics import (
    roc_auc_score, average_precision_score, brier_score_loss,
    accuracy_score, precision_recall_curve
)
import xgboost as xgb
import json
from datetime import datetime

PROJECT_ROOT = Path("C:\\Users\\apto117\\Documents\\pachinko-analyzer\\src\\2026project")
sys.path.insert(0, str(PROJECT_ROOT))

COPY_DB = PROJECT_ROOT / "db" / "experiments" / "マルハンメガシティ2000-蒲田7_rank_exp.db"
RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase7_rank_prediction_v5_18d_comparison"


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


def compute_days_since_last_rank1(df):
    """Compute days since last rank_1 for each machine per date."""
    days_since = []

    for machine_name in df['machine_name'].unique():
        machine_df = df[df['machine_name'] == machine_name].copy().reset_index(drop=True)

        rank1_dates = machine_df[machine_df['is_rank_1'] == 1]['date'].values

        for idx, row in machine_df.iterrows():
            current_date = row['date']

            # Find last rank_1 date
            last_rank1_dates = rank1_dates[rank1_dates < current_date]

            if len(last_rank1_dates) > 0:
                days = (current_date - last_rank1_dates[-1]).days
                days = min(days, 365)  # Cap at 365 days
            else:
                days = 365  # No prior rank_1

            days_since.append(days)

    return np.array(days_since)


def prepare_18d_features(df):
    """Prepare 18D features: month_progress + days_since_last_rank1 + rolling_averages."""
    X_18d = []

    days_since_last_rank1 = compute_days_since_last_rank1(df)

    for idx, row in df.iterrows():
        features = []

        # 1. Month progress (1D)
        day_of_month = row['date'].day
        days_in_month = (pd.to_datetime(row['date']) + pd.DateOffset(months=1)).replace(day=1) - pd.Timedelta(days=1)
        month_progress = day_of_month / days_in_month.day
        features.append(month_progress)

        # 2. Days since last rank_1 (1D)
        features.append(float(days_since_last_rank1[idx]))

        # 3. Rolling average features (15D)
        rolling_cols = [
            'avg_diff_7d', 'avg_diff_14d', 'avg_diff_21d', 'avg_diff_28d', 'avg_diff_35d',
            'avg_games_7d', 'avg_games_14d', 'avg_games_21d', 'avg_games_28d', 'avg_games_35d',
            'avg_efficiency_7d', 'avg_efficiency_14d', 'avg_efficiency_21d', 'avg_efficiency_28d',
            'machine_count'
        ]
        rolling_vals = [float(row[col]) if col in row and pd.notna(row[col]) else 0.0 for col in rolling_cols]
        features.extend(rolling_vals)

        X_18d.append(features)

    return np.array(X_18d)


def calculate_ece(y_true, y_pred_proba, n_bins=10):
    """Calculate Expected Calibration Error."""
    bin_sums = np.zeros(n_bins)
    bin_true = np.zeros(n_bins)
    bin_total = np.zeros(n_bins)

    for i in range(len(y_true)):
        bin_idx = int(y_pred_proba[i] * n_bins)
        if bin_idx == n_bins:
            bin_idx = n_bins - 1

        bin_sums[bin_idx] += y_pred_proba[i]
        bin_true[bin_idx] += y_true[i]
        bin_total[bin_idx] += 1

    ece = 0.0
    for i in range(n_bins):
        if bin_total[i] > 0:
            bin_accuracy = bin_true[i] / bin_total[i]
            bin_confidence = bin_sums[i] / bin_total[i]
            ece += (bin_total[i] / len(y_true)) * abs(bin_accuracy - bin_confidence)

    return ece


def train_and_compare(X, y_dict, dates):
    """Train models with Balanced vs Calibrated scale_pos_weight."""
    results = {}

    unique_dates = pd.Series(dates).unique()
    split_date_idx = len(unique_dates) - 57
    split_date = unique_dates[split_date_idx]

    train_mask = dates < split_date
    test_mask = dates >= split_date
    train_idx = np.where(train_mask)[0]
    test_idx = np.where(test_mask)[0]

    X_train, X_test = X[train_idx], X[test_idx]
    dates_train, dates_test = dates[train_idx], dates[test_idx]

    print(f"\n{'='*80}")
    print(f"[18D Scale PosWeight Comparison]")
    print(f"{'='*80}")
    print(f"Train dates: {dates_train[0]} to {dates_train[-1]}")
    print(f"Test dates: {dates_test[0]} to {dates_test[-1]}")
    print(f"Train size: {len(train_idx)}, Test size: {len(test_idx)}")
    print(f"Feature dimension: {X.shape[1]}D (1D month_progress + 1D days_since_last_rank1 + 15D rolling avg)")

    for target_name, y in y_dict.items():
        y_train, y_test = y[train_idx], y[test_idx]

        pos_ratio = y_train.sum() / len(y_train)

        print(f"\n{'='*70}")
        print(f"Target: {target_name.upper()}")
        print(f"{'='*70}")
        print(f"Positive ratio (train): {pos_ratio:.2%}")

        results[target_name] = {}

        # Strategy 1: Balanced (class rebalancing)
        scale_pos_weight_balanced = (1 - pos_ratio) / pos_ratio if pos_ratio > 0 else 1.0

        print(f"\n[Strategy 1: Balanced (scale_pos_weight={scale_pos_weight_balanced:.2f})]")
        model_balanced = xgb.XGBClassifier(
            max_depth=5,
            learning_rate=0.1,
            n_estimators=100,
            scale_pos_weight=scale_pos_weight_balanced,
            random_state=42,
            eval_metric='auc'
        )
        model_balanced.fit(X_train, y_train, verbose=False)

        y_pred_proba_balanced = model_balanced.predict_proba(X_test)[:, 1]
        auc_balanced = roc_auc_score(y_test, y_pred_proba_balanced)
        ap_balanced = average_precision_score(y_test, y_pred_proba_balanced)
        brier_balanced = brier_score_loss(y_test, y_pred_proba_balanced)
        ece_balanced = calculate_ece(y_test, y_pred_proba_balanced)

        print(f"  AUC:   {auc_balanced:.4f}")
        print(f"  AP:    {ap_balanced:.4f}")
        print(f"  Brier: {brier_balanced:.4f}")
        print(f"  ECE:   {ece_balanced:.4f}")

        results[target_name]['balanced'] = {
            'scale_pos_weight': float(scale_pos_weight_balanced),
            'auc': float(auc_balanced),
            'ap': float(ap_balanced),
            'brier': float(brier_balanced),
            'ece': float(ece_balanced)
        }

        # Strategy 2: Calibrated (scale_pos_weight=1.0)
        print(f"\n[Strategy 2: Calibrated (scale_pos_weight=1.0)]")
        model_calibrated = xgb.XGBClassifier(
            max_depth=5,
            learning_rate=0.1,
            n_estimators=100,
            scale_pos_weight=1.0,
            random_state=42,
            eval_metric='auc'
        )
        model_calibrated.fit(X_train, y_train, verbose=False)

        y_pred_proba_calibrated = model_calibrated.predict_proba(X_test)[:, 1]
        auc_calibrated = roc_auc_score(y_test, y_pred_proba_calibrated)
        ap_calibrated = average_precision_score(y_test, y_pred_proba_calibrated)
        brier_calibrated = brier_score_loss(y_test, y_pred_proba_calibrated)
        ece_calibrated = calculate_ece(y_test, y_pred_proba_calibrated)

        print(f"  AUC:   {auc_calibrated:.4f}")
        print(f"  AP:    {ap_calibrated:.4f}")
        print(f"  Brier: {brier_calibrated:.4f}")
        print(f"  ECE:   {ece_calibrated:.4f}")

        results[target_name]['calibrated'] = {
            'scale_pos_weight': 1.0,
            'auc': float(auc_calibrated),
            'ap': float(ap_calibrated),
            'brier': float(brier_calibrated),
            'ece': float(ece_calibrated)
        }

        # Comparison
        auc_delta = (auc_calibrated - auc_balanced) * 100
        ece_ratio = ece_balanced / ece_calibrated if ece_calibrated > 0 else 0

        print(f"\n[Comparison]")
        print(f"  AUC delta:   {auc_delta:+.2f}% (Calibrated wins: {auc_delta > 0})")
        print(f"  ECE ratio:   {ece_ratio:.1f}x (Calibrated better: {ece_ratio > 1})")

    return results


def main():
    print("="*80)
    print("[Phase 7-5] Rank Prediction - 18D Scale PosWeight Comparison")
    print("="*80)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n[1] Loading data...")
    df = load_data(COPY_DB)
    print(f"    Loaded {len(df)} rows, {df['machine_name'].nunique()} machines")

    print(f"\n[2] Preparing 18D features...")
    X = prepare_18d_features(df)
    print(f"    Feature matrix shape: {X.shape}")

    y_dict = {
        'rank_1': df['is_rank_1'].values.astype(int),
        'top_3': df['is_top_3'].values.astype(int),
        'top_5': df['is_top_5'].values.astype(int)
    }
    dates = df['date'].values

    print(f"\n[3] Training and comparing models...")
    results = train_and_compare(X, y_dict, dates)

    summary = {
        'timestamp': datetime.now().isoformat(),
        'method': '18D Features with Balanced vs Calibrated Comparison',
        'feature_dimension': X.shape[1],
        'features': 'month_progress (1D) + days_since_last_rank1 (1D) + rolling_averages (15D)',
        'results': results
    }

    results_path = RESULTS_DIR / "comparison_18d.json"
    with open(results_path, 'w') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*80}")
    print(f"[OK] Results saved to {results_path}")
    print(f"{'='*80}")

    return results


if __name__ == "__main__":
    results = main()
