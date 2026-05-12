# -*- coding: utf-8 -*-
"""
Phase 9-8: Advanced Ensemble Methods
台番号末尾別 - Stacking with K-fold CV and Cascaded Top3→Rank1 prediction
Compare advanced ensemble strategies across all 3 targets (Rank1, Top3, Top5)
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
from xgboost import XGBClassifier
from sklearn.ensemble import RandomForestClassifier
import lightgbm as lgb
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import KFold
from sklearn.metrics import roc_auc_score, precision_score, recall_score, f1_score
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


def ensemble_stacking_cv(X_train, y_train, X_test, y_test, n_splits=3):
    """
    Stacking with K-fold cross-validation.
    Train 4 base models on K folds, generate meta-features via CV,
    train meta-learner on meta-features, apply to test set.
    """

    kf = KFold(n_splits=n_splits, shuffle=False)

    # Calculate scale_pos_weight
    pos_count = (y_train == 1).sum()
    neg_count = (y_train == 0).sum()
    scale_pos_weight = neg_count / pos_count if pos_count > 0 else 1.0

    # Initialize meta-feature arrays
    meta_train = np.zeros((X_train.shape[0], 4))  # 4 base models
    meta_test = np.zeros((X_test.shape[0], 4))

    # Fold-wise base model training
    for fold, (train_idx, val_idx) in enumerate(kf.split(X_train)):
        X_fold_train = X_train.iloc[train_idx].values.astype(np.float32)
        y_fold_train = y_train.iloc[train_idx].values
        X_fold_val = X_train.iloc[val_idx].values.astype(np.float32)

        # Base Model 1: XGBoost_3D
        m1 = XGBClassifier(
            objective='binary:logistic',
            max_depth=3,
            learning_rate=0.01,
            n_estimators=200,
            scale_pos_weight=scale_pos_weight,
            random_state=42,
            verbosity=0
        )
        m1.fit(X_fold_train, y_fold_train)
        meta_train[val_idx, 0] = m1.predict_proba(X_fold_val)[:, 1]

        # Base Model 2: XGBoost_5D
        m2 = XGBClassifier(
            objective='binary:logistic',
            max_depth=5,
            learning_rate=0.1,
            n_estimators=100,
            scale_pos_weight=scale_pos_weight,
            random_state=42,
            verbosity=0
        )
        m2.fit(X_fold_train, y_fold_train)
        meta_train[val_idx, 1] = m2.predict_proba(X_fold_val)[:, 1]

        # Base Model 3: RandomForest
        m3 = RandomForestClassifier(
            n_estimators=100,
            max_depth=7,
            random_state=42,
            n_jobs=-1
        )
        m3.fit(X_fold_train, y_fold_train)
        meta_train[val_idx, 2] = m3.predict_proba(X_fold_val)[:, 1]

        # Base Model 4: LightGBM
        m4 = lgb.LGBMClassifier(
            max_depth=3,
            learning_rate=0.01,
            n_estimators=200,
            random_state=42,
            verbosity=-1
        )
        m4.fit(X_fold_train, y_fold_train)
        meta_train[val_idx, 3] = m4.predict_proba(X_fold_val)[:, 1]

    # Train base models on full train set for test predictions
    for model_idx, (ModelClass, params) in enumerate([
        (XGBClassifier, {
            'objective': 'binary:logistic',
            'max_depth': 3,
            'learning_rate': 0.01,
            'n_estimators': 200,
            'scale_pos_weight': scale_pos_weight,
            'random_state': 42,
            'verbosity': 0
        }),
        (XGBClassifier, {
            'objective': 'binary:logistic',
            'max_depth': 5,
            'learning_rate': 0.1,
            'n_estimators': 100,
            'scale_pos_weight': scale_pos_weight,
            'random_state': 42,
            'verbosity': 0
        }),
        (RandomForestClassifier, {
            'n_estimators': 100,
            'max_depth': 7,
            'random_state': 42,
            'n_jobs': -1
        }),
        (lgb.LGBMClassifier, {
            'max_depth': 3,
            'learning_rate': 0.01,
            'n_estimators': 200,
            'random_state': 42,
            'verbosity': -1
        })
    ]):
        model = ModelClass(**params)
        model.fit(X_train.values.astype(np.float32), y_train.values)
        meta_test[:, model_idx] = model.predict_proba(X_test.values.astype(np.float32))[:, 1]

    # Train meta-learner on meta-features
    meta_learner = LogisticRegression(random_state=42, max_iter=1000)
    meta_learner.fit(meta_train, y_train)

    # Final predictions
    y_pred_proba = meta_learner.predict_proba(meta_test)[:, 1]

    return y_pred_proba


def cascade_top3_to_rank1(X_train, X_test, y_train_top3, y_train_rank1, y_test_rank1):
    """
    Cascaded prediction: Train Top3 model, use Top3 probability as feature for Rank1.
    Logic: Rank1 ⊂ Top3, so Top3 score is a strong signal for Rank1.
    """

    # Calculate scale_pos_weight for both targets
    pos_count_top3 = (y_train_top3 == 1).sum()
    neg_count_top3 = (y_train_top3 == 0).sum()
    scale_pos_weight_top3 = neg_count_top3 / pos_count_top3 if pos_count_top3 > 0 else 1.0

    pos_count_rank1 = (y_train_rank1 == 1).sum()
    neg_count_rank1 = (y_train_rank1 == 0).sum()
    scale_pos_weight_rank1 = neg_count_rank1 / pos_count_rank1 if pos_count_rank1 > 0 else 1.0

    # Train Top3 model
    top3_model = XGBClassifier(
        objective='binary:logistic',
        max_depth=5,
        learning_rate=0.1,
        n_estimators=100,
        scale_pos_weight=scale_pos_weight_top3,
        random_state=42,
        verbosity=0
    )
    top3_model.fit(X_train.values.astype(np.float32), y_train_top3.values)

    # Get Top3 probability on train and test
    top3_proba_train = top3_model.predict_proba(X_train.values.astype(np.float32))[:, 1]
    top3_proba_test = top3_model.predict_proba(X_test.values.astype(np.float32))[:, 1]

    # Augment features with Top3 probability
    X_train_augmented = np.column_stack([X_train.values.astype(np.float32), top3_proba_train])
    X_test_augmented = np.column_stack([X_test.values.astype(np.float32), top3_proba_test])

    # Train Rank1 model with augmented features
    rank1_model = XGBClassifier(
        objective='binary:logistic',
        max_depth=5,
        learning_rate=0.1,
        n_estimators=100,
        scale_pos_weight=scale_pos_weight_rank1,
        random_state=42,
        verbosity=0
    )
    rank1_model.fit(X_train_augmented, y_train_rank1.values)

    # Final predictions
    y_pred_proba = rank1_model.predict_proba(X_test_augmented)[:, 1]

    return y_pred_proba


def evaluate_advanced_ensembles(df_train, df_test):
    """Evaluate both advanced ensemble methods across all targets."""

    print(f"\n{'='*70}")
    print(f"Advanced Ensemble Methods: Stacking + Cascaded Prediction")
    print(f"{'='*70}")

    # Prepare features
    exclude_cols = {'date', 'last_digit', 'is_rank_1', 'is_top_3', 'is_top_5'}
    feature_list = [col for col in df_train.columns if col not in exclude_cols]

    X_train = df_train[feature_list].fillna(0).astype(np.float32)
    X_test = df_test[feature_list].fillna(0).astype(np.float32)

    results = {}

    # 1. Stacking for all 3 targets
    print(f"\n[Stacking with 3-Fold CV]")
    for target_col, target_name in [
        ('is_rank_1', 'Rank1'),
        ('is_top_3', 'Top3'),
        ('is_top_5', 'Top5')
    ]:
        y_train = df_train[target_col].astype(int)
        y_test = df_test[target_col].astype(int)

        print(f"  Training stacking for {target_name}...")
        y_pred_proba = ensemble_stacking_cv(X_train, y_train, X_test, y_test, n_splits=3)
        metrics = compute_metrics(y_test, y_pred_proba)
        results[f'stacking_{target_name}'] = metrics
        print(f"    {target_name}: AUC={metrics['auc']:.4f}, Recall={metrics['recall']:.4f}, Precision={metrics['precision']:.4f}")

    # 2. Cascaded Top3→Rank1
    print(f"\n[Cascaded Top3 → Rank1]")
    y_train_top3 = df_train['is_top_3'].astype(int)
    y_train_rank1 = df_train['is_rank_1'].astype(int)
    y_test_rank1 = df_test['is_rank_1'].astype(int)

    print(f"  Training cascaded prediction (Top3→Rank1)...")
    y_pred_proba = cascade_top3_to_rank1(X_train, X_test, y_train_top3, y_train_rank1, y_test_rank1)
    metrics = compute_metrics(y_test_rank1, y_pred_proba)
    results['cascaded_top3_to_rank1'] = metrics
    print(f"    Rank1 (cascaded): AUC={metrics['auc']:.4f}, Recall={metrics['recall']:.4f}, Precision={metrics['precision']:.4f}")

    return results


def main():
    """Main execution flow."""

    print("=" * 80)
    print("Phase 9-8: Advanced Ensemble Methods")
    print("Stacking with K-fold CV + Cascaded Top3→Rank1 Prediction")
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

    # Evaluate advanced ensembles
    print("\n[3] Evaluating advanced ensemble methods...")
    results = evaluate_advanced_ensembles(df_train, df_test)

    # Save results
    print("\n[4] Saving advanced ensemble results...")
    output = {
        'phase': '9-8',
        'description': 'Advanced Ensemble Methods (Stacking + Cascaded Prediction)',
        'train_test_split': {
            'train_size': len(df_train),
            'test_size': len(df_test)
        },
        'ensemble_strategies': {
            'stacking_3fold': 'XGBoost_3D + XGBoost_5D + RandomForest + LightGBM with 3-fold CV meta-learner',
            'cascaded_top3_rank1': 'Train Top3 model, use Top3 proba as feature for Rank1 (logical subset relationship)'
        },
        'results': {}
    }

    for method_name, metrics in results.items():
        output['results'][method_name] = metrics

    output_path = RESULTS_DIR / 'phase9_08_advanced_ensemble_results.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n[OK] Results saved to {output_path}")

    # Summary comparison with Phase 9-3 baselines
    print("\n" + "=" * 80)
    print("Summary: Advanced Ensemble vs Individual Models (Phase 9-3)")
    print("=" * 80)

    # Phase 9-3 baseline AUCs (from expected results)
    phase93_baselines = {
        'Rank1': 0.7920,
        'Top3': 0.8104,
        'Top5': 0.8110
    }

    print(f"\nPhase 9-3 Best Individual Model AUCs:")
    for target, auc in phase93_baselines.items():
        print(f"  {target}: {auc:.4f}")

    print(f"\nPhase 9-8 Advanced Ensemble AUCs:")
    for key, metrics in results.items():
        if 'stacking' in key:
            target = key.split('_')[1]
            baseline = phase93_baselines.get(target, 0.0)
            improvement = ((metrics['auc'] - baseline) / baseline * 100) if baseline > 0 else 0
            print(f"  Stacking {target}: {metrics['auc']:.4f} ({improvement:+.2f}% vs baseline)")

    cascaded_auc = results['cascaded_top3_to_rank1']['auc']
    baseline_rank1 = phase93_baselines['Rank1']
    improvement = ((cascaded_auc - baseline_rank1) / baseline_rank1 * 100)
    print(f"  Cascaded Top3→Rank1: {cascaded_auc:.4f} ({improvement:+.2f}% vs Rank1 baseline)")

    print("\n" + "=" * 80)
    print("[OK] Phase 9-8 Complete!")
    print("=" * 80)


if __name__ == '__main__':
    main()
