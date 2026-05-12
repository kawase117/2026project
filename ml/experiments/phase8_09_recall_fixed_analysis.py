"""
Phase 8-9: Recall-Fixed Precision Comparison

Fixes Recall at specific levels (5%, 10%, 15%, 20%)
and compares Precision across all 6 models.
Identifies which model is most trustworthy at each recall level.
"""

import sqlite3
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.metrics import precision_recall_curve
import xgboost as xgb
import catboost as cb
from sklearn.ensemble import RandomForestClassifier, StackingClassifier
from sklearn.neural_network import MLPClassifier
import json

PROJECT_ROOT = Path("C:\\Users\\apto117\\Documents\\pachinko-analyzer\\src\\2026project")
sys.path.insert(0, str(PROJECT_ROOT))

COPY_DB = PROJECT_ROOT / "db" / "experiments" / "マルハンメガシティ2000-蒲田7_rank_exp.db"
RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase8_recall_fixed"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

TARGET_RECALLS = [0.05, 0.10, 0.15, 0.20]


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
    X = []
    days_since_rank1 = compute_days_since_last_rank(df, 'is_rank_1')
    days_since_top3 = compute_days_since_last_rank(df, 'is_top_3')
    days_since_top5 = compute_days_since_last_rank(df, 'is_top_5')

    for idx, row in df.iterrows():
        features = []

        day_of_month = row['date'].day
        days_in_month = (pd.to_datetime(row['date']) + pd.DateOffset(months=1)).replace(day=1) - pd.Timedelta(days=1)
        month_progress = day_of_month / days_in_month.day
        features.append(month_progress)
        features.append(float(days_since_rank1[idx]))
        features.append(float(days_since_top3[idx]))
        features.append(float(days_since_top5[idx]))

        rolling_cols = [
            'avg_diff_7d', 'avg_diff_14d', 'avg_diff_21d', 'avg_diff_28d', 'avg_diff_35d',
            'avg_games_7d', 'avg_games_14d', 'avg_games_21d', 'avg_games_28d', 'avg_games_35d',
            'avg_efficiency_7d', 'avg_efficiency_14d', 'avg_efficiency_21d', 'avg_efficiency_28d', 'avg_efficiency_35d',
            'machine_count'
        ]
        rolling_vals = [float(row[col]) if col in row and pd.notna(row[col]) else 0.0 for col in rolling_cols]
        features.extend(rolling_vals)

        X.append(features)

    return np.array(X)


def find_precision_at_recall(y_true, y_pred_proba, target_recalls):
    """Find precision at specific recall levels."""
    precision, recall, thresholds = precision_recall_curve(y_true, y_pred_proba)

    result = {}
    for target_r in target_recalls:
        # Find closest recall >= target_r with highest precision
        valid_idx = np.where(recall >= target_r)[0]
        if len(valid_idx) > 0:
            # Choose the one with highest precision
            idx = max(valid_idx, key=lambda i: precision[i])
            thresh = thresholds[idx] if idx < len(thresholds) else 0.5
            n_pred = int((y_pred_proba >= thresh).sum())

            result[f"{int(target_r*100)}%"] = {
                'precision': float(precision[idx]),
                'recall': float(recall[idx]),
                'threshold': float(thresh),
                'n_predicted': n_pred
            }

    return result


def main():
    print("="*90)
    print("Phase 8-9: Recall-Fixed Precision Analysis")
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

    # === 3-Split ===
    unique_dates = pd.Series(dates).unique()
    split_train_val_idx = len(unique_dates) - 57
    split_train_val_date = unique_dates[split_train_val_idx]

    train_mask = dates < split_train_val_date

    last_57_dates = unique_dates[split_train_val_idx:]
    split_val_test_idx = len(last_57_dates) - 29
    split_val_test_date = last_57_dates[split_val_test_idx]

    test_mask = dates >= split_val_test_date

    X_train = X_40d[train_mask]
    X_test = X_40d[test_mask]

    print(f"\nData Split: Train={train_mask.sum()}, Test={test_mask.sum()}")

    results = {}

    for target_name in ['rank_1', 'top_3', 'top_5']:
        print(f"\n{'='*90}")
        print(f"Target: {target_name.upper()}")
        print(f"{'='*90}")

        y_full = y_dict[target_name]
        y_train = y_full[train_mask]
        y_test = y_full[test_mask]

        results[target_name] = {}

        # === 6 Models ===
        models = {
            'xgboost_baseline': xgb.XGBClassifier(
                objective='binary:logistic', max_depth=3, learning_rate=0.01,
                n_estimators=200, random_state=42, eval_metric='logloss', verbosity=0
            ),
            'xgboost_balanced': xgb.XGBClassifier(
                objective='binary:logistic', max_depth=3, learning_rate=0.01,
                n_estimators=200, scale_pos_weight=99.0, random_state=42,
                eval_metric='logloss', verbosity=0
            ),
            'catboost': cb.CatBoostClassifier(
                depth=3, learning_rate=0.01, iterations=200, random_state=42, verbose=0
            ),
            'randomforest': RandomForestClassifier(
                n_estimators=100, max_depth=5, random_state=42, n_jobs=-1
            ),
            'stacking': StackingClassifier(
                estimators=[
                    ('xgb', xgb.XGBClassifier(
                        max_depth=3, learning_rate=0.01, n_estimators=200,
                        random_state=42, eval_metric='logloss', verbosity=0
                    )),
                    ('cat', cb.CatBoostClassifier(
                        depth=3, learning_rate=0.01, iterations=200, random_state=42, verbose=0
                    ))
                ],
                final_estimator=xgb.XGBClassifier(
                    max_depth=2, learning_rate=0.01, n_estimators=100,
                    random_state=42, eval_metric='logloss', verbosity=0
                ),
                cv=3
            ),
            'neural_network': MLPClassifier(
                hidden_layer_sizes=(64, 32), learning_rate_init=0.001,
                max_iter=1000, random_state=42
            )
        }

        for model_name, model in models.items():
            print(f"\n  {model_name}...")
            model.fit(X_train, y_train)
            y_pred_proba = model.predict_proba(X_test)[:, 1]

            pr_points = find_precision_at_recall(y_test, y_pred_proba, TARGET_RECALLS)
            results[target_name][model_name] = pr_points

            print(f"    Recall vs Precision:")
            for recall_level in [f"{int(r*100)}%" for r in TARGET_RECALLS]:
                if recall_level in pr_points:
                    p = pr_points[recall_level]
                    print(f"      {recall_level}: Precision={p['precision']:.4f}, Threshold={p['threshold']:.4f}, N={p['n_predicted']}")

    # Save results
    output_file = RESULTS_DIR / "recall_fixed_analysis.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n[COMPLETED] Results saved to {output_file}")


if __name__ == '__main__':
    main()
