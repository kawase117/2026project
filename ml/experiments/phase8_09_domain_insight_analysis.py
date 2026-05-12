"""
Phase 8-9: Domain Insight Analysis

For high-precision predictions at fixed recall levels,
analyzes the characteristics of predicted machines:
- days_since_last_rank1/3/5
- day of month (DD)
- efficiency levels
- game counts

Connects model behavior to domain knowledge about shop's rank investment patterns.
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

TARGET_RECALL = 0.10


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

    return np.array(X), days_since_rank1, days_since_top3, days_since_top5


def analyze_predictions(y_test, y_pred_proba, df_test, days_since_rank1, days_since_top3, days_since_top5):
    """Analyze characteristics of high-precision predictions."""
    precision, recall, thresholds = precision_recall_curve(y_test, y_pred_proba)

    # Find threshold at target recall
    valid_idx = np.where(recall >= TARGET_RECALL)[0]
    if len(valid_idx) == 0:
        return None

    idx = max(valid_idx, key=lambda i: precision[i])
    thresh = thresholds[idx] if idx < len(thresholds) else 0.5

    # Get predicted positives at this threshold
    pred_mask = y_pred_proba >= thresh
    n_pred = pred_mask.sum()

    if n_pred == 0:
        return None

    # Analyze characteristics
    pred_data = {
        'threshold': float(thresh),
        'precision': float(precision[idx]),
        'recall': float(recall[idx]),
        'n_predicted': int(n_pred),
        'n_tp': int((y_test[pred_mask] == 1).sum()),
        'n_fp': int((y_test[pred_mask] == 0).sum()),
        'features': {}
    }

    # Extract feature statistics
    dd_values = df_test.loc[pred_mask, 'date'].dt.day.values
    efficiency_values = df_test.loc[pred_mask, 'avg_efficiency_7d'].values
    games_values = df_test.loc[pred_mask, 'avg_games_7d'].values

    pred_data['features']['dd'] = {
        'values': sorted(dd_values.tolist()),
        'mean': float(np.mean(dd_values)),
        'std': float(np.std(dd_values)),
        'min': int(np.min(dd_values)),
        'max': int(np.max(dd_values))
    }

    pred_data['features']['days_since_rank1'] = {
        'mean': float(np.mean(days_since_rank1[pred_mask])),
        'std': float(np.std(days_since_rank1[pred_mask])),
        'min': int(np.min(days_since_rank1[pred_mask])),
        'max': int(np.max(days_since_rank1[pred_mask]))
    }

    pred_data['features']['efficiency_7d'] = {
        'mean': float(np.mean(efficiency_values)),
        'std': float(np.std(efficiency_values)),
        'min': float(np.min(efficiency_values)),
        'max': float(np.max(efficiency_values))
    }

    pred_data['features']['games_7d'] = {
        'mean': float(np.mean(games_values)),
        'std': float(np.std(games_values)),
        'min': float(np.min(games_values)),
        'max': float(np.max(games_values))
    }

    return pred_data


def main():
    print("="*90)
    print(f"Phase 8-9: Domain Insight Analysis (Recall={TARGET_RECALL*100:.0f}%)")
    print("="*90)

    print("\n[Loading data...]")
    df = load_data(COPY_DB)

    print("[Preparing 40D+ features...]")
    X_40d, days_since_rank1, days_since_top3, days_since_top5 = prepare_40d_features(df)

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
    df_test = df[test_mask].reset_index(drop=True)
    days_since_rank1_test = days_since_rank1[test_mask]
    days_since_top3_test = days_since_top3[test_mask]
    days_since_top5_test = days_since_top5[test_mask]

    insights = {}

    for target_name in ['rank_1', 'top_3', 'top_5']:
        print(f"\n{'='*90}")
        print(f"Target: {target_name.upper()}")
        print(f"{'='*90}")

        y_full = y_dict[target_name]
        y_train = y_full[train_mask]
        y_test = y_full[test_mask]

        insights[target_name] = {}

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

            analysis = analyze_predictions(y_test, y_pred_proba, df_test, days_since_rank1_test, days_since_top3_test, days_since_top5_test)

            if analysis:
                insights[target_name][model_name] = analysis
                print(f"    Precision={analysis['precision']:.4f}, Recall={analysis['recall']:.4f}, N={analysis['n_predicted']}")
                print(f"    DD (day of month): mean={analysis['features']['dd']['mean']:.1f}, range={analysis['features']['dd']['min']}-{analysis['features']['dd']['max']}")
                print(f"    Days since rank1: mean={analysis['features']['days_since_rank1']['mean']:.1f}")
                print(f"    Efficiency: mean={analysis['features']['efficiency_7d']['mean']:.2f}")
            else:
                print(f"    [No predictions at this recall level]")

    # Save results
    output_file = RESULTS_DIR / "domain_insights.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(insights, f, ensure_ascii=False, indent=2)

    print(f"\n[COMPLETED] Results saved to {output_file}")


if __name__ == '__main__':
    main()
