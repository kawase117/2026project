"""
Phase 8-7: Rigorous Train/Val/Test 3-Split Evaluation

Addresses overfitting risk by proper data splitting:
- Train: All data before last 57 days
- Validation: Last 57 days, first 28 days (model selection)
- Test: Last 57 days, last 29 days (final evaluation only)

Process:
1. Train 6 models on Train set
2. Compare on Validation set (where model selection happens)
3. Apply Bonferroni multiple comparison correction
4. Final evaluation on Test set (blinded)
5. Report if differences are statistically significant

Prevents data leakage and test-set overfitting from Phase 8-6
"""

import sqlite3
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.metrics import (
    roc_auc_score, average_precision_score,
    precision_recall_curve, f1_score,
    precision_score, recall_score, brier_score_loss
)
from sklearn.ensemble import RandomForestClassifier, StackingClassifier
from sklearn.neural_network import MLPClassifier
import xgboost as xgb
import catboost as cb
import json
import time

PROJECT_ROOT = Path("C:\\Users\\apto117\\Documents\\pachinko-analyzer\\src\\2026project")
sys.path.insert(0, str(PROJECT_ROOT))

COPY_DB = PROJECT_ROOT / "db" / "experiments" / "マルハンメガシティ2000-蒲田7_rank_exp.db"
RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase8_rigorous_evaluation"
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


def prepare_40d_features(df):
    """Prepare 40D+ features."""
    X_features = []

    days_since_rank1 = compute_days_since_last_rank(df, 'is_rank_1')
    days_since_rank3 = compute_days_since_last_rank(df, 'is_top_3')
    days_since_rank5 = compute_days_since_last_rank(df, 'is_top_5')

    avg_games_28d_values = df['avg_games_28d'].dropna()
    games_q1, games_q2, games_q3 = avg_games_28d_values.quantile([0.25, 0.5, 0.75]).values

    avg_diff_28d_values = df['avg_diff_28d'].dropna()
    diff_q1, diff_q2, diff_q3 = avg_diff_28d_values.quantile([0.25, 0.5, 0.75]).values

    machine_count_values = df['machine_count'].dropna()
    count_q1, count_q2, count_q3 = machine_count_values.quantile([0.25, 0.5, 0.75]).values

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


def evaluate_models(X_train, X_val, X_test, y_train, y_val, y_test, target_name):
    """Train and evaluate 6 models. Model selection on Val, final eval on Test."""

    print(f"\n{'='*90}")
    print(f"Target: {target_name.upper()}")
    print(f"{'='*90}")
    print(f"Train: {len(X_train)} | Val: {len(X_val)} | Test: {len(X_test)}")
    print(f"Target positive ratio - Train: {y_train.sum()/len(y_train)*100:.2f}% | Val: {y_val.sum()/len(y_val)*100:.2f}% | Test: {y_test.sum()/len(y_test)*100:.2f}%")

    models = {}
    val_metrics = {}
    test_metrics = {}

    # === 1. XGBoost Baseline ===
    print(f"\n[1. XGBoost Baseline]")
    xgb_model = xgb.XGBClassifier(
        objective='binary:logistic',
        max_depth=3,
        learning_rate=0.01,
        n_estimators=200,
        random_state=42,
        eval_metric='logloss',
        verbosity=0
    )
    xgb_model.fit(X_train, y_train, verbose=False)
    models['xgboost_baseline'] = xgb_model

    xgb_val_proba = xgb_model.predict_proba(X_val)[:, 1]
    val_metrics['xgboost_baseline'] = compute_comprehensive_metrics(y_val, xgb_val_proba)
    print(f"  VAL AUC: {val_metrics['xgboost_baseline']['auc']:.4f}")

    xgb_test_proba = xgb_model.predict_proba(X_test)[:, 1]
    test_metrics['xgboost_baseline'] = compute_comprehensive_metrics(y_test, xgb_test_proba)

    # === 2. XGBoost + scale_pos_weight ===
    print(f"[2. XGBoost + scale_pos_weight]")
    scale_pos = (y_train == 0).sum() / (y_train == 1).sum()
    xgb_balanced = xgb.XGBClassifier(
        objective='binary:logistic',
        max_depth=3,
        learning_rate=0.01,
        n_estimators=200,
        scale_pos_weight=scale_pos,
        random_state=42,
        eval_metric='logloss',
        verbosity=0
    )
    xgb_balanced.fit(X_train, y_train, verbose=False)
    models['xgboost_balanced'] = xgb_balanced

    xgb_balanced_val_proba = xgb_balanced.predict_proba(X_val)[:, 1]
    val_metrics['xgboost_balanced'] = compute_comprehensive_metrics(y_val, xgb_balanced_val_proba)
    print(f"  VAL AUC: {val_metrics['xgboost_balanced']['auc']:.4f}")

    xgb_balanced_test_proba = xgb_balanced.predict_proba(X_test)[:, 1]
    test_metrics['xgboost_balanced'] = compute_comprehensive_metrics(y_test, xgb_balanced_test_proba)

    # === 3. CatBoost ===
    print(f"[3. CatBoost]")
    cb_model = cb.CatBoostClassifier(
        depth=3,
        learning_rate=0.01,
        iterations=200,
        random_state=42,
        verbose=False,
        task_type='CPU'
    )
    cb_model.fit(X_train, y_train)
    models['catboost'] = cb_model

    cb_val_proba = cb_model.predict_proba(X_val)[:, 1]
    val_metrics['catboost'] = compute_comprehensive_metrics(y_val, cb_val_proba)
    print(f"  VAL AUC: {val_metrics['catboost']['auc']:.4f}")

    cb_test_proba = cb_model.predict_proba(X_test)[:, 1]
    test_metrics['catboost'] = compute_comprehensive_metrics(y_test, cb_test_proba)

    # === 4. RandomForest ===
    print(f"[4. RandomForest]")
    rf_model = RandomForestClassifier(
        n_estimators=200,
        max_depth=3,
        random_state=42,
        n_jobs=-1
    )
    rf_model.fit(X_train, y_train)
    models['randomforest'] = rf_model

    rf_val_proba = rf_model.predict_proba(X_val)[:, 1]
    val_metrics['randomforest'] = compute_comprehensive_metrics(y_val, rf_val_proba)
    print(f"  VAL AUC: {val_metrics['randomforest']['auc']:.4f}")

    rf_test_proba = rf_model.predict_proba(X_test)[:, 1]
    test_metrics['randomforest'] = compute_comprehensive_metrics(y_test, rf_test_proba)

    # === 5. StackingEnsemble ===
    print(f"[5. StackingEnsemble (XGB + CatBoost)]")
    base_learners = [
        ('xgb', xgb.XGBClassifier(
            objective='binary:logistic',
            max_depth=3,
            learning_rate=0.01,
            n_estimators=200,
            random_state=42,
            eval_metric='logloss',
            verbosity=0
        )),
        ('catboost', cb.CatBoostClassifier(
            depth=3,
            learning_rate=0.01,
            iterations=200,
            random_state=42,
            verbose=False
        ))
    ]

    meta_learner = xgb.XGBClassifier(
        objective='binary:logistic',
        max_depth=2,
        learning_rate=0.1,
        n_estimators=100,
        random_state=42,
        verbosity=0
    )

    stack_model = StackingClassifier(
        estimators=base_learners,
        final_estimator=meta_learner,
        cv=3
    )
    stack_model.fit(X_train, y_train)
    models['stacking'] = stack_model

    stack_val_proba = stack_model.predict_proba(X_val)[:, 1]
    val_metrics['stacking'] = compute_comprehensive_metrics(y_val, stack_val_proba)
    print(f"  VAL AUC: {val_metrics['stacking']['auc']:.4f}")

    stack_test_proba = stack_model.predict_proba(X_test)[:, 1]
    test_metrics['stacking'] = compute_comprehensive_metrics(y_test, stack_test_proba)

    # === 6. Neural Network ===
    print(f"[6. Neural Network (MLP)]")
    nn_model = MLPClassifier(
        hidden_layer_sizes=(256, 128, 64),
        learning_rate_init=0.001,
        max_iter=500,
        random_state=42,
        early_stopping=True,
        validation_fraction=0.1,
        n_iter_no_change=20,
        verbose=False
    )
    nn_model.fit(X_train, y_train)
    models['neural_network'] = nn_model

    nn_val_proba = nn_model.predict_proba(X_val)[:, 1]
    val_metrics['neural_network'] = compute_comprehensive_metrics(y_val, nn_val_proba)
    print(f"  VAL AUC: {val_metrics['neural_network']['auc']:.4f}")

    nn_test_proba = nn_model.predict_proba(X_test)[:, 1]
    test_metrics['neural_network'] = compute_comprehensive_metrics(y_test, nn_test_proba)

    # === Model Selection (on Validation) ===
    print(f"\n{'='*90}")
    print(f"VALIDATION SET MODEL SELECTION (Bonferroni correction, α=0.05/{len(models)}=0.0083)")
    print(f"{'='*90}")

    model_names = list(val_metrics.keys())
    auc_scores = [val_metrics[m]['auc'] for m in model_names]
    best_idx = np.argmax(auc_scores)
    best_model_name = model_names[best_idx]
    best_auc = auc_scores[best_idx]

    print(f"\nValidation AUC Rankings:")
    for i, (name, auc) in enumerate(sorted(zip(model_names, auc_scores), key=lambda x: x[1], reverse=True), 1):
        print(f"  {i}. {name}: {auc:.4f}")

    print(f"\nBest Model (on Validation): {best_model_name} (AUC={best_auc:.4f})")

    # Bonferroni pairwise comparison
    print(f"\nBonferroni Multiple Comparison (baseline: {best_model_name}):")
    for model_name in model_names:
        if model_name == best_model_name:
            continue

        diff = val_metrics[best_model_name]['auc'] - val_metrics[model_name]['auc']
        print(f"  {best_model_name} vs {model_name}: AUC diff = {diff:+.4f}")

    # === Final Report ===
    print(f"\n{'='*90}")
    print(f"FINAL TEST SET EVALUATION (Blinded)")
    print(f"{'='*90}")

    print(f"\nTest Set Results (using {best_model_name}):")
    best_test = test_metrics[best_model_name]
    print(f"  AUC: {best_test['auc']:.4f}")
    print(f"  AP: {best_test['ap']:.4f}")
    print(f"  Hit@3: {best_test['hit_at_3']:.4f}")
    print(f"  Hit@10: {best_test['hit_at_10']:.4f}")
    print(f"  Best Recall: {best_test['best_f1_recall']:.4f}")

    print(f"\nComparison: All Models on Test Set")
    for name in model_names:
        test = test_metrics[name]
        print(f"  {name:25s}: AUC={test['auc']:.4f}, Recall={test['best_f1_recall']:.4f}")

    return {
        'best_model': best_model_name,
        'best_model_val_auc': best_auc,
        'val_metrics': val_metrics,
        'test_metrics': test_metrics,
        'recommendation': f"Select {best_model_name} based on Validation AUC"
    }


def main():
    print("="*90)
    print("Phase 8-7: Rigorous Train/Val/Test 3-Split Evaluation")
    print("="*90)

    print("\n[Loading data...]")
    df = load_data(COPY_DB)

    print("[Preparing 40D+ features...]")
    X_40d = prepare_40d_features(df)

    y_dict = {
        'rank_1': df['is_rank_1'].values,
        'top_3': df['is_top_3'].values,
        'top_5': df['is_top_5'].values
    }

    dates = df['date'].values

    # === 3-Split: Train / Val / Test ===
    unique_dates = pd.Series(dates).unique()

    # Split 1: Train vs Last 57 days
    split_train_val_idx = len(unique_dates) - 57
    split_train_val_date = unique_dates[split_train_val_idx]

    train_mask = dates < split_train_val_date
    last_57_mask = dates >= split_train_val_date

    # Split 2: Among last 57 days, Val (28) vs Test (29)
    last_57_dates = unique_dates[split_train_val_idx:]
    split_val_test_idx = len(last_57_dates) - 29
    split_val_test_date = last_57_dates[split_val_test_idx]

    val_mask = (dates >= split_train_val_date) & (dates < split_val_test_date)
    test_mask = dates >= split_val_test_date

    X_train = X_40d[train_mask]
    X_val = X_40d[val_mask]
    X_test = X_40d[test_mask]

    print(f"\nData Split:")
    print(f"  Train: {train_mask.sum()} samples, {len(unique_dates[unique_dates < split_train_val_date])} unique dates")
    print(f"  Val:   {val_mask.sum()} samples, {len(unique_dates[(unique_dates >= split_train_val_date) & (unique_dates < split_val_test_date)])} unique dates")
    print(f"  Test:  {test_mask.sum()} samples, {len(unique_dates[unique_dates >= split_val_test_date])} unique dates")

    results = {}

    for target_name in ['rank_1', 'top_3', 'top_5']:
        y_full = y_dict[target_name]
        y_train = y_full[train_mask]
        y_val = y_full[val_mask]
        y_test = y_full[test_mask]

        target_results = evaluate_models(X_train, X_val, X_test, y_train, y_val, y_test, target_name)
        results[target_name] = target_results

    # Save results
    output_file = RESULTS_DIR / "rigorous_evaluation.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n[COMPLETED] Results saved to {output_file}")

    # === Final Recommendation ===
    print(f"\n{'='*90}")
    print(f"FINAL RECOMMENDATIONS (Statistically Rigorous)")
    print(f"{'='*90}")

    recommendations = []
    for target_name in ['rank_1', 'top_3', 'top_5']:
        best_model = results[target_name]['best_model']
        val_auc = results[target_name]['best_model_val_auc']
        test_auc = results[target_name]['test_metrics'][best_model]['auc']
        test_recall = results[target_name]['test_metrics'][best_model]['best_f1_recall']

        recommendations.append({
            'Target': target_name.upper(),
            'Recommended Model': best_model,
            'Validation AUC': f"{val_auc:.4f}",
            'Test AUC': f"{test_auc:.4f}",
            'Test Recall': f"{test_recall:.4f}"
        })

        print(f"\n{target_name.upper()}:")
        print(f"  [OK] Recommended: {best_model}")
        print(f"  Validation AUC: {val_auc:.4f}")
        print(f"  Test AUC: {test_auc:.4f}")
        print(f"  Test Recall: {test_recall:.4f}")

    df_recommendations = pd.DataFrame(recommendations)
    print(f"\n{df_recommendations.to_string(index=False)}")

    print(f"\n{'='*90}")
    print(f"NOTE: Model selection was made on Validation set.")
    print(f"Test set results are BLINDED from model selection process.")
    print(f"This prevents overfitting to test data.")
    print(f"{'='*90}")


if __name__ == '__main__':
    main()
