"""
Phase 7-6 Diagnostic: Investigate DD Feature Paradox

Why does DD (high importance #4-5) worsen AUC when added?
Investigating:
1. Train vs test AUC (overfitting?)
2. DD distribution in train vs test
3. Target encoding behavior
"""

import sqlite3
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.preprocessing import TargetEncoder
from sklearn.metrics import roc_auc_score
import xgboost as xgb
import json

PROJECT_ROOT = Path("C:\\Users\\apto117\\Documents\\pachinko-analyzer\\src\\2026project")
sys.path.insert(0, str(PROJECT_ROOT))

COPY_DB = PROJECT_ROOT / "db" / "experiments" / "マルハンメガシティ2000-蒲田7_rank_exp.db"


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
            last_rank1_dates = rank1_dates[rank1_dates < current_date]

            if len(last_rank1_dates) > 0:
                days = (current_date - last_rank1_dates[-1]).days
                days = min(days, 365)
            else:
                days = 365

            days_since.append(days)

    return np.array(days_since)


def prepare_16d_features(df):
    """Prepare 16D base features."""
    X_16d = []
    days_since_last_rank1 = compute_days_since_last_rank1(df)

    for idx, row in df.iterrows():
        features = []

        day_of_month = row['date'].day
        days_in_month = (pd.to_datetime(row['date']) + pd.DateOffset(months=1)).replace(day=1) - pd.Timedelta(days=1)
        month_progress = day_of_month / days_in_month.day
        features.append(month_progress)

        features.append(float(days_since_last_rank1[idx]))

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


def main():
    print("="*70)
    print("Diagnostic: DD Feature Paradox Investigation")
    print("="*70)

    # Load data
    print("\n[Loading data...]")
    df = load_data(COPY_DB)

    # Prepare features
    print("[Preparing features...]")
    X_16d = prepare_16d_features(df)
    dd_values = df['date'].dt.day.values
    dates = df['date'].values

    # Time-series split
    unique_dates = pd.Series(dates).unique()
    split_date_idx = len(unique_dates) - 57
    split_date = unique_dates[split_date_idx]

    train_mask = dates < split_date
    test_mask = dates >= split_date

    X_train = X_16d[train_mask]
    X_test = X_16d[test_mask]
    dd_train = dd_values[train_mask]
    dd_test = dd_values[test_mask]

    # Use rank_1 as example
    y_full = df['is_rank_1'].values
    y_train = y_full[train_mask]
    y_test = y_full[test_mask]

    print(f"\nTrain: {train_mask.sum()} samples")
    print(f"Test:  {test_mask.sum()} samples")

    # ========== DIAGNOSTIC 1: DD Distribution ==========
    print(f"\n{'='*70}")
    print("DIAGNOSTIC 1: DD (Day of Month) Distribution")
    print("="*70)

    print(f"\nTrain DD distribution:")
    print(f"  Mean: {dd_train.mean():.2f}, Std: {dd_train.std():.2f}")
    print(f"  Range: {dd_train.min()}-{dd_train.max()}")
    unique_dd_train, counts_train = np.unique(dd_train, return_counts=True)
    print(f"  Unique values: {len(unique_dd_train)}")

    print(f"\nTest DD distribution:")
    print(f"  Mean: {dd_test.mean():.2f}, Std: {dd_test.std():.2f}")
    print(f"  Range: {dd_test.min()}-{dd_test.max()}")
    unique_dd_test, counts_test = np.unique(dd_test, return_counts=True)
    print(f"  Unique values: {len(unique_dd_test)}")

    # Check overlap
    overlap = len(set(unique_dd_train) & set(unique_dd_test))
    print(f"\nDD overlap between train/test: {overlap}/31 values")

    # ========== DIAGNOSTIC 2: Target Encoding ==========
    print(f"\n{'='*70}")
    print("DIAGNOSTIC 2: Target Encoding Behavior")
    print("="*70)

    te = TargetEncoder(smooth=1.0)
    dd_train_encoded = te.fit_transform(dd_train.reshape(-1, 1), y_train).reshape(-1)
    dd_test_encoded = te.transform(dd_test.reshape(-1, 1)).reshape(-1)

    print(f"\nTarget encoding (train fit):")
    print(f"  Train encoded mean: {dd_train_encoded.mean():.6f}, std: {dd_train_encoded.std():.6f}")
    print(f"  Test encoded mean:  {dd_test_encoded.mean():.6f}, std: {dd_test_encoded.std():.6f}")

    # Check actual category statistics
    print(f"\nCategory-wise target encoding (first 10 days):")
    for dd in sorted(set(dd_train))[:10]:
        mask = dd_train == dd
        if mask.sum() > 0:
            pos_rate = y_train[mask].mean()
            encoded_val = dd_train_encoded[mask][0]
            print(f"  DD={dd:2d}: pos_rate={pos_rate:.4f}, encoded={encoded_val:.6f}")

    # ========== DIAGNOSTIC 3: Overfitting Check ==========
    print(f"\n{'='*70}")
    print("DIAGNOSTIC 3: Overfitting Analysis")
    print("="*70)

    # Train 16D model
    model_16d = xgb.XGBClassifier(
        objective='binary:logistic',
        max_depth=3,
        learning_rate=0.01,
        n_estimators=200,
        random_state=42,
        eval_metric='logloss',
        verbosity=0
    )
    model_16d.fit(X_train, y_train, verbose=False)

    y_pred_16d_train = model_16d.predict_proba(X_train)[:, 1]
    y_pred_16d_test = model_16d.predict_proba(X_test)[:, 1]
    auc_16d_train = roc_auc_score(y_train, y_pred_16d_train)
    auc_16d_test = roc_auc_score(y_test, y_pred_16d_test)

    print(f"\n16D Model (without DD):")
    print(f"  Train AUC: {auc_16d_train:.4f}")
    print(f"  Test AUC:  {auc_16d_test:.4f}")
    print(f"  Overfitting gap: {auc_16d_train - auc_16d_test:.4f}")

    # Train 17D model with DD
    X_train_17d = np.column_stack([X_train, dd_train_encoded])
    X_test_17d = np.column_stack([X_test, dd_test_encoded])

    model_17d = xgb.XGBClassifier(
        objective='binary:logistic',
        max_depth=3,
        learning_rate=0.01,
        n_estimators=200,
        random_state=42,
        eval_metric='logloss',
        verbosity=0
    )
    model_17d.fit(X_train_17d, y_train, verbose=False)

    y_pred_17d_train = model_17d.predict_proba(X_train_17d)[:, 1]
    y_pred_17d_test = model_17d.predict_proba(X_test_17d)[:, 1]
    auc_17d_train = roc_auc_score(y_train, y_pred_17d_train)
    auc_17d_test = roc_auc_score(y_test, y_pred_17d_test)

    print(f"\n17D Model (with DD target-encoded):")
    print(f"  Train AUC: {auc_17d_train:.4f}")
    print(f"  Test AUC:  {auc_17d_test:.4f}")
    print(f"  Overfitting gap: {auc_17d_train - auc_17d_test:.4f}")

    print(f"\nComparison:")
    print(f"  16D train AUC: {auc_16d_train:.4f} -> 17D train AUC: {auc_17d_train:.4f} ({auc_17d_train - auc_16d_train:+.4f})")
    print(f"  16D test AUC:  {auc_16d_test:.4f} -> 17D test AUC:  {auc_17d_test:.4f} ({auc_17d_test - auc_16d_test:+.4f})")

    if auc_17d_train > auc_16d_train and auc_17d_test < auc_16d_test:
        print(f"\n[VERDICT] OVERFITTING DETECTED:")
        print(f"  DD helps training ({auc_17d_train - auc_16d_train:+.4f}) but hurts test ({auc_17d_test - auc_16d_test:+.4f})")
    else:
        print(f"\n[VERDICT] Not typical overfitting pattern")

    # Feature importance
    importance_17d = model_17d.feature_importances_
    print(f"\nDD feature importance: {importance_17d[-1]:.4f}")


if __name__ == '__main__':
    main()
