"""
Phase 6B Demo with Synthetic Data

Demonstrates the Phase 6B implementation using synthetic data,
proving the architecture works correctly. Use with actual databases
once they are available via phase6b_stepwise_evaluation.py.

User instruction (verbatim): "実装は HAIKU で行ってください" (2026-05-08)
"""

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from ml.models.baseline_logistic import LogisticRegressionModel
from ml.models.tree_xgboost_v2 import XGBoostModelV2
from ml.feature_engineering_phase6b import TargetEncoderPhase6B


def generate_synthetic_data(n_samples=5000):
    """
    Generate synthetic pachinko machine data for testing.

    Returns
    -------
    X_train, y_train, X_test, y_test, X_train_raw, X_test_raw
    """
    np.random.seed(42)

    # Synthetic raw features
    machine_names = ['CR北斗9', 'ギラギラ', 'スカイラッキー', 'ABCDEF']
    days_of_week = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

    n_train = int(0.8 * n_samples)

    # Generate raw feature dataframes
    df_train_raw = pd.DataFrame({
        'machine_name': np.random.choice(machine_names, n_train),
        'machine_number': np.random.randint(1, 300, n_train),
        'day_of_week': np.random.choice(days_of_week, n_train),
        'is_zorome': np.random.randint(0, 2, n_train),
        'day_of_month': np.random.randint(1, 32, n_train),
    })

    df_test_raw = pd.DataFrame({
        'machine_name': np.random.choice(machine_names, n_samples - n_train),
        'machine_number': np.random.randint(1, 300, n_samples - n_train),
        'day_of_week': np.random.choice(days_of_week, n_samples - n_train),
        'is_zorome': np.random.randint(0, 2, n_samples - n_train),
        'day_of_month': np.random.randint(1, 32, n_samples - n_train),
    })

    # Generate synthetic one-hot features (baseline)
    model_train = pd.get_dummies(df_train_raw['machine_name'], prefix='model')
    model_test = pd.get_dummies(df_test_raw['machine_name'], prefix='model')
    model_test = model_test.reindex(columns=model_train.columns, fill_value=0.0)

    X_train = model_train.values.astype(float)
    X_test = model_test.values.astype(float)

    # Generate synthetic target with some signal
    y_train = (
        (df_train_raw['machine_number'] > 150) &
        (df_train_raw['is_zorome'] == 1) &
        (df_train_raw['day_of_month'] > 15)
    ).astype(int).values
    y_train = np.random.binomial(1, 0.4 + 0.2 * y_train.astype(float))

    y_test = (
        (df_test_raw['machine_number'] > 150) &
        (df_test_raw['is_zorome'] == 1) &
        (df_test_raw['day_of_month'] > 15)
    ).astype(int).values
    y_test = np.random.binomial(1, 0.4 + 0.2 * y_test.astype(float))

    return X_train, y_train, X_test, y_test, df_train_raw, df_test_raw


def run_phase6b_demo():
    """Run Phase 6B demo with synthetic data."""
    print("="*80)
    print("PHASE 6B DEMO - Synthetic Data Validation")
    print("="*80)

    # Generate synthetic data
    print("\n[Data] Generating synthetic data...")
    X_train, y_train, X_test, y_test, df_train_raw, df_test_raw = generate_synthetic_data(n_samples=5000)
    print(f"[Data] Train: {len(X_train)} samples, Features: {X_train.shape[1]}")
    print(f"[Data] Test: {len(X_test)} samples")
    print(f"[Label] Train positive: {y_train.sum()}/{len(y_train)} ({100*y_train.mean():.1f}%)")
    print(f"[Label] Test positive: {y_test.sum()}/{len(y_test)} ({100*y_test.mean():.1f}%)")

    # Step 1: Baseline
    print(f"\n[Step 1] Baseline (Logistic on raw features)...")
    model_baseline = LogisticRegressionModel(random_state=42)
    model_baseline.fit(X_train, y_train)
    y_pred_baseline = model_baseline.predict_proba(X_test)[:, 1]
    auc_step1 = roc_auc_score(y_test, y_pred_baseline)
    print(f"[Step 1] AUC = {auc_step1:.4f}")

    # Step 2: +Composite Features
    print(f"\n[Step 2] With composite features (target encoding)...")
    encoder = TargetEncoderPhase6B(smoothing=1.0)
    X_train_composite = encoder.fit_transform(df_train_raw, y_train)
    X_test_composite = encoder.transform(df_test_raw)
    print(f"[Step 2] Composite feature shape: {X_train_composite.shape}")

    model_features = LogisticRegressionModel(random_state=42)
    model_features.fit(X_train_composite, y_train)
    y_pred_features = model_features.predict_proba(X_test_composite)[:, 1]
    auc_step2 = roc_auc_score(y_test, y_pred_features)
    print(f"[Step 2] AUC = {auc_step2:.4f}")

    # Step 3: +XGBoost
    print(f"\n[Step 3] XGBoost baseline (no composite)...")
    model_xgb = XGBoostModelV2(
        random_state=42,
        max_depth=3,
        learning_rate=0.01,
        n_estimators=1000,
        early_stopping_rounds=10
    )

    split_idx = int(0.8 * len(X_train))
    X_train_main = X_train[:split_idx]
    y_train_main = y_train[:split_idx]
    X_val = X_train[split_idx:]
    y_val = y_train[split_idx:]

    model_xgb.fit(X_train_main, y_train_main, X_val, y_val)
    y_pred_xgb = model_xgb.predict_proba(X_test)[:, 1]
    auc_step3 = roc_auc_score(y_test, y_pred_xgb)
    print(f"[Step 3] AUC = {auc_step3:.4f}")
    if model_xgb.best_iteration_ is not None:
        print(f"[Step 3] Early stopping at iteration {model_xgb.best_iteration_}")

    # Step 4: +Both
    print(f"\n[Step 4] XGBoost with composite features...")
    model_both = XGBoostModelV2(
        random_state=42,
        max_depth=3,
        learning_rate=0.01,
        n_estimators=1000,
        early_stopping_rounds=10
    )

    X_train_comp_main = X_train_composite[:split_idx]
    y_train_comp_main = y_train[:split_idx]
    X_val_comp = X_train_composite[split_idx:]

    model_both.fit(X_train_comp_main, y_train_comp_main, X_val_comp, y_val)
    y_pred_both = model_both.predict_proba(X_test_composite)[:, 1]
    auc_step4 = roc_auc_score(y_test, y_pred_both)
    print(f"[Step 4] AUC = {auc_step4:.4f}")
    if model_both.best_iteration_ is not None:
        print(f"[Step 4] Early stopping at iteration {model_both.best_iteration_}")

    # Summary
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"Step 1 (Baseline):          {auc_step1:.4f}")
    print(f"Step 2 (+Features):         {auc_step2:.4f} (Δ {auc_step2-auc_step1:+.4f})")
    print(f"Step 3 (+XGBoost):          {auc_step3:.4f} (Δ {auc_step3-auc_step1:+.4f})")
    print(f"Step 4 (+Both):             {auc_step4:.4f} (Δ {auc_step4-auc_step1:+.4f})")
    print(f"{'='*80}")
    print("[OK] Phase 6B demo completed successfully\n")


if __name__ == "__main__":
    run_phase6b_demo()
