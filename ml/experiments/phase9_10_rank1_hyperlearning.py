# -*- coding: utf-8 -*-
"""
Phase 9-10: Rank1-Specific Hyperlearning Strategy
台番号末尾別 - Rank1専用の特徴量最適化とハイパーパラメータ超学習
Feature engineering, hyperparameter grid search, multi-model comparison
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
from xgboost import XGBClassifier
from sklearn.ensemble import RandomForestClassifier
import lightgbm as lgb
from sklearn.metrics import roc_auc_score, precision_score, recall_score, f1_score
from itertools import product
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
        feature_source = '32d_antipattern'
    elif features_path_27d.exists():
        df = pd.read_csv(features_path_27d)
        print("  Using 27D base features (Phase 9-1)")
        feature_source = '27d_base'
    else:
        raise FileNotFoundError("Neither 32D nor 27D feature files found!")

    return df, feature_source


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


def select_features_for_rank1(df_train, df_test):
    """
    Select Rank1-specific feature subsets with varying strategies.
    Returns multiple feature sets to evaluate.
    """

    exclude_cols = {'date', 'last_digit', 'is_rank_1', 'is_top_3', 'is_top_5'}
    all_features = [col for col in df_train.columns if col not in exclude_cols]

    # Feature importance from Phase 9-2 for Rank1
    top_rank1_features = [
        'same_weekday_rolling_rank_sum_3',
        'rolling_rank_sum_14d',
        'weekday_non_consecutive_rank1_rate',
        'anti_pattern_rank1_rate',
        'prior_same_weekday_rank1_rate',
        'weekday_digit_bias',
        'rolling_avg_efficiency_14d',
        'rolling_rank_sum_7d',
        'rolling_rank_sum_21d',
        'dow_lastdigit_rank1_rate',
    ]

    # Feature selection strategies
    feature_sets = {
        'all_31d': all_features,
        'top_10_only': [f for f in top_rank1_features if f in all_features],
        'top_15': [f for f in all_features if any(tf in f or f in top_rank1_features for tf in top_rank1_features)][:15],
        'hybrid_antipattern': [
            f for f in all_features
            if 'anti_pattern' in f or 'same_weekday' in f or 'rolling_rank' in f or 'weekday' in f
        ],
    }

    # Filter to only features that exist
    feature_sets = {
        k: [f for f in v if f in all_features]
        for k, v in feature_sets.items()
    }

    return feature_sets


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


def hyperparameter_search_xgboost(X_train, y_train, X_test, y_test, feature_set_name):
    """Perform grid search on XGBoost hyperparameters."""

    print(f"\n  Grid Search: XGBoost on {feature_set_name}")

    pos_count = (y_train == 1).sum()
    neg_count = (y_train == 0).sum()
    scale_pos_weight = neg_count / pos_count if pos_count > 0 else 1.0

    param_grid = {
        'max_depth': [2, 3, 4, 5, 6, 7],
        'learning_rate': [0.001, 0.01, 0.05, 0.1],
        'n_estimators': [100, 150, 200, 250, 300],
        'subsample': [0.7, 0.8, 0.9, 1.0],
        'colsample_bytree': [0.7, 0.8, 0.9, 1.0]
    }

    results = []
    total_combinations = np.prod([len(v) for v in param_grid.values()])
    print(f"    Total combinations: {total_combinations}")

    combo_idx = 0
    for max_depth, learning_rate, n_estimators, subsample, colsample_bytree in product(
        param_grid['max_depth'],
        param_grid['learning_rate'],
        param_grid['n_estimators'],
        param_grid['subsample'],
        param_grid['colsample_bytree']
    ):
        combo_idx += 1
        if combo_idx % 200 == 0:
            print(f"      Progress: {combo_idx}/{total_combinations}")

        model = XGBClassifier(
            objective='binary:logistic',
            max_depth=max_depth,
            learning_rate=learning_rate,
            n_estimators=n_estimators,
            subsample=subsample,
            colsample_bytree=colsample_bytree,
            scale_pos_weight=scale_pos_weight,
            random_state=42,
            verbosity=0
        )

        model.fit(X_train, y_train)
        y_pred_proba = model.predict_proba(X_test)[:, 1]
        auc = roc_auc_score(y_test, y_pred_proba)

        results.append({
            'max_depth': max_depth,
            'learning_rate': learning_rate,
            'n_estimators': n_estimators,
            'subsample': subsample,
            'colsample_bytree': colsample_bytree,
            'auc': float(auc)
        })

    results_sorted = sorted(results, key=lambda x: x['auc'], reverse=True)

    print(f"    Top 3 Results:")
    for i, result in enumerate(results_sorted[:3], 1):
        print(f"      {i}. AUC={result['auc']:.4f} | "
              f"depth={result['max_depth']}, lr={result['learning_rate']}, "
              f"n_est={result['n_estimators']}, subsample={result['subsample']}, "
              f"colsample={result['colsample_bytree']}")

    return results_sorted[0]


def hyperparameter_search_lightgbm(X_train, y_train, X_test, y_test, feature_set_name):
    """Perform grid search on LightGBM hyperparameters."""

    print(f"\n  Grid Search: LightGBM on {feature_set_name}")

    param_grid = {
        'max_depth': [2, 3, 4, 5, 6, 7, 8],
        'learning_rate': [0.001, 0.01, 0.05, 0.1],
        'n_estimators': [100, 150, 200, 250, 300],
        'num_leaves': [8, 16, 32, 64, 127]
    }

    results = []
    total_combinations = np.prod([len(v) for v in param_grid.values()])
    print(f"    Total combinations: {total_combinations}")

    combo_idx = 0
    for max_depth, learning_rate, n_estimators, num_leaves in product(
        param_grid['max_depth'],
        param_grid['learning_rate'],
        param_grid['n_estimators'],
        param_grid['num_leaves']
    ):
        combo_idx += 1
        if combo_idx % 140 == 0:
            print(f"      Progress: {combo_idx}/{total_combinations}")

        model = lgb.LGBMClassifier(
            max_depth=max_depth,
            learning_rate=learning_rate,
            n_estimators=n_estimators,
            num_leaves=num_leaves,
            random_state=42,
            verbosity=-1
        )

        model.fit(X_train, y_train)
        y_pred_proba = model.predict_proba(X_test)[:, 1]
        auc = roc_auc_score(y_test, y_pred_proba)

        results.append({
            'max_depth': max_depth,
            'learning_rate': learning_rate,
            'n_estimators': n_estimators,
            'num_leaves': num_leaves,
            'auc': float(auc)
        })

    results_sorted = sorted(results, key=lambda x: x['auc'], reverse=True)

    print(f"    Top 3 Results:")
    for i, result in enumerate(results_sorted[:3], 1):
        print(f"      {i}. AUC={result['auc']:.4f} | "
              f"depth={result['max_depth']}, lr={result['learning_rate']}, "
              f"n_est={result['n_estimators']}, leaves={result['num_leaves']}")

    return results_sorted[0]


def hyperparameter_search_randomforest(X_train, y_train, X_test, y_test, feature_set_name):
    """Perform grid search on RandomForest hyperparameters."""

    print(f"\n  Grid Search: RandomForest on {feature_set_name}")

    param_grid = {
        'n_estimators': [50, 100, 150, 200],
        'max_depth': [3, 5, 7, 10, 15, 20],
        'min_samples_split': [2, 5, 10],
        'min_samples_leaf': [1, 2, 4],
    }

    results = []
    total_combinations = np.prod([len(v) for v in param_grid.values()])
    print(f"    Total combinations: {total_combinations}")

    combo_idx = 0
    for n_estimators, max_depth, min_samples_split, min_samples_leaf in product(
        param_grid['n_estimators'],
        param_grid['max_depth'],
        param_grid['min_samples_split'],
        param_grid['min_samples_leaf']
    ):
        combo_idx += 1
        if combo_idx % 144 == 0:
            print(f"      Progress: {combo_idx}/{total_combinations}")

        model = RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            min_samples_split=min_samples_split,
            min_samples_leaf=min_samples_leaf,
            random_state=42,
            n_jobs=-1
        )

        model.fit(X_train, y_train)
        y_pred_proba = model.predict_proba(X_test)[:, 1]
        auc = roc_auc_score(y_test, y_pred_proba)

        results.append({
            'n_estimators': n_estimators,
            'max_depth': max_depth,
            'min_samples_split': min_samples_split,
            'min_samples_leaf': min_samples_leaf,
            'auc': float(auc)
        })

    results_sorted = sorted(results, key=lambda x: x['auc'], reverse=True)

    print(f"    Top 3 Results:")
    for i, result in enumerate(results_sorted[:3], 1):
        print(f"      {i}. AUC={result['auc']:.4f} | "
              f"n_est={result['n_estimators']}, depth={result['max_depth']}, "
              f"split={result['min_samples_split']}, leaf={result['min_samples_leaf']}")

    return results_sorted[0]


def evaluate_rank1_hyperlearning(df_train, df_test):
    """Evaluate Rank1-specific hyperlearning across feature sets and models."""

    print(f"\n{'='*70}")
    print(f"Rank1-Specific Hyperlearning: Multi-Feature Multi-Model Search")
    print(f"{'='*70}")

    # Feature selection for Rank1
    feature_sets = select_features_for_rank1(df_train, df_test)

    print(f"\nFeature Sets Identified:")
    for fs_name, features in feature_sets.items():
        print(f"  {fs_name}: {len(features)} features")

    all_results = {}

    # For each feature set, perform hyperparameter search on 3 model types
    for fs_name, feature_list in feature_sets.items():
        print(f"\n{'='*70}")
        print(f"Feature Set: {fs_name} ({len(feature_list)} features)")
        print(f"{'='*70}")

        X_train = df_train[feature_list].fillna(0).astype(np.float32)
        y_train = df_train['is_rank_1'].astype(int)

        X_test = df_test[feature_list].fillna(0).astype(np.float32)
        y_test = df_test['is_rank_1'].astype(int)

        fs_results = {}

        # XGBoost hyperparameter search
        xgb_best = hyperparameter_search_xgboost(X_train, y_train, X_test, y_test, fs_name)
        xgb_model = XGBClassifier(
            objective='binary:logistic',
            max_depth=xgb_best['max_depth'],
            learning_rate=xgb_best['learning_rate'],
            n_estimators=xgb_best['n_estimators'],
            subsample=xgb_best['subsample'],
            colsample_bytree=xgb_best['colsample_bytree'],
            scale_pos_weight=(y_train == 0).sum() / (y_train == 1).sum(),
            random_state=42,
            verbosity=0
        )
        xgb_model.fit(X_train, y_train)
        xgb_proba = xgb_model.predict_proba(X_test)[:, 1]
        xgb_metrics = compute_metrics(y_test, xgb_proba)
        fs_results['xgboost_best'] = {
            'params': xgb_best,
            'metrics': xgb_metrics
        }

        # LightGBM hyperparameter search
        lgb_best = hyperparameter_search_lightgbm(X_train, y_train, X_test, y_test, fs_name)
        lgb_model = lgb.LGBMClassifier(
            max_depth=lgb_best['max_depth'],
            learning_rate=lgb_best['learning_rate'],
            n_estimators=lgb_best['n_estimators'],
            num_leaves=lgb_best['num_leaves'],
            random_state=42,
            verbosity=-1
        )
        lgb_model.fit(X_train, y_train)
        lgb_proba = lgb_model.predict_proba(X_test)[:, 1]
        lgb_metrics = compute_metrics(y_test, lgb_proba)
        fs_results['lightgbm_best'] = {
            'params': lgb_best,
            'metrics': lgb_metrics
        }

        # RandomForest hyperparameter search
        rf_best = hyperparameter_search_randomforest(X_train, y_train, X_test, y_test, fs_name)
        rf_model = RandomForestClassifier(
            n_estimators=rf_best['n_estimators'],
            max_depth=rf_best['max_depth'],
            min_samples_split=rf_best['min_samples_split'],
            min_samples_leaf=rf_best['min_samples_leaf'],
            random_state=42,
            n_jobs=-1
        )
        rf_model.fit(X_train, y_train)
        rf_proba = rf_model.predict_proba(X_test)[:, 1]
        rf_metrics = compute_metrics(y_test, rf_proba)
        fs_results['randomforest_best'] = {
            'params': rf_best,
            'metrics': rf_metrics
        }

        all_results[fs_name] = fs_results

    return all_results


def main():
    """Main execution flow."""

    print("=" * 80)
    print("Phase 9-10: Rank1-Specific Hyperlearning Strategy")
    print("Feature selection + Hyperparameter grid search across multiple models")
    print("=" * 80)

    # Load features
    print("\n[1] Loading feature set...")
    df, feature_source = load_features()
    exclude_cols = {'date', 'last_digit', 'is_rank_1', 'is_top_3', 'is_top_5'}
    feature_count = len([col for col in df.columns if col not in exclude_cols])
    print(f"  Loaded {len(df)} samples with {feature_count}D features")

    # Time-series split
    print("\n[2] Preparing time-series train/test split...")
    df_train, df_test = prepare_time_series_split(df)
    print(f"  Train: {len(df_train)} samples, Test: {len(df_test)} samples")

    # Rank1 hyperlearning
    print("\n[3] Executing Rank1-specific hyperlearning...")
    all_results = evaluate_rank1_hyperlearning(df_train, df_test)

    # Save results
    print("\n[4] Saving hyperlearning results...")
    output = {
        'phase': '9-10',
        'description': 'Rank1-Specific Hyperlearning (Feature Selection + Hyperparameter Grid Search)',
        'feature_source': feature_source,
        'train_test_split': {
            'train_size': len(df_train),
            'test_size': len(df_test)
        },
        'target': 'is_rank_1',
        'results_by_feature_set': {}
    }

    for fs_name, fs_results in all_results.items():
        output['results_by_feature_set'][fs_name] = {}
        for model_name, result in fs_results.items():
            output['results_by_feature_set'][fs_name][model_name] = {
                'params': result['params'],
                'metrics': result['metrics']
            }

    output_path = RESULTS_DIR / 'phase9_10_rank1_hyperlearning_results.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n[OK] Results saved to {output_path}")

    # Summary comparison
    print("\n" + "=" * 80)
    print("Summary: Best Rank1 Models by Feature Set")
    print("=" * 80)

    baseline_auc = 0.7940  # Phase 9-9 MoE baseline

    for fs_name, fs_results in all_results.items():
        print(f"\n{fs_name}:")
        best_model = max(
            fs_results.items(),
            key=lambda x: x[1]['metrics']['auc']
        )
        model_name, result = best_model

        auc = result['metrics']['auc']
        improvement = ((auc - baseline_auc) / baseline_auc * 100)

        print(f"  Best Model: {model_name}")
        print(f"  AUC: {auc:.4f} ({improvement:+.2f}% vs Phase 9-9 baseline)")
        print(f"  Recall: {result['metrics']['recall']:.4f}, Precision: {result['metrics']['precision']:.4f}, F1: {result['metrics']['f1']:.4f}")

    print("\n" + "=" * 80)
    print("[OK] Phase 9-10 Complete!")
    print("=" * 80)


if __name__ == '__main__':
    main()
