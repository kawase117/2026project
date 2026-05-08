"""
Phase 7: Rank Prediction - Step 2: Feature Engineering & XGBoost Model

Loads copy DB, prepares features, and trains XGBoost models to predict:
- is_rank_1: Top ranked machine
- is_top_3: Top 3 ranked
- is_top_5: Top 5 ranked
"""

import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import auc, roc_curve, precision_recall_curve, roc_auc_score, average_precision_score
import xgboost as xgb
import json
from datetime import datetime

# Paths
PROJECT_ROOT = Path("C:\\Users\\apto117\\Documents\\pachinko-analyzer\\src\\2026project")
COPY_DB = PROJECT_ROOT / "db" / "experiments" / "マルハンメガシティ2000-蒲田7_rank_exp.db"
RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase7_rank_prediction"

def load_data(db_path):
    """Load data from copy DB."""
    conn = sqlite3.connect(db_path)

    # Load machine type daily data
    df_machine = pd.read_sql_query("""
        SELECT
            date, machine_name, machine_count,
            avg_diff_coins, avg_games, efficiency,
            avg_diff_7d, avg_diff_14d, avg_diff_21d, avg_diff_28d, avg_diff_35d,
            avg_games_7d, avg_games_14d, avg_games_21d, avg_games_28d, avg_games_35d,
            avg_efficiency_7d, avg_efficiency_14d, avg_efficiency_21d, avg_efficiency_28d, avg_efficiency_35d,
            avg_rank_diff_7d, avg_rank_diff_14d, avg_rank_diff_21d, avg_rank_diff_28d, avg_rank_diff_35d,
            machine_type_rank_diff,
            is_rank_1, is_top_3, is_top_5
        FROM daily_machine_type_summary
        ORDER BY date, machine_type_rank_diff
    """, conn)

    # Load daily hall features
    df_hall = pd.read_sql_query("""
        SELECT
            date, day_of_week, last_digit, weekday_nth,
            is_weekend, is_holiday, is_any_event, week_of_month
        FROM daily_hall_summary
    """, conn)

    conn.close()

    # Convert date to datetime
    df_machine['date'] = pd.to_datetime(df_machine['date'], format='%Y%m%d')
    df_hall['date'] = pd.to_datetime(df_hall['date'], format='%Y%m%d')

    # Merge
    df = df_machine.merge(df_hall, on='date', how='left')
    df = df.sort_values('date').reset_index(drop=True)

    return df

def prepare_features(df):
    """Prepare feature matrix and targets."""
    # Rolling average features (not current-day to avoid leakage)
    rolling_cols = [
        'avg_diff_7d', 'avg_diff_14d', 'avg_diff_21d', 'avg_diff_28d', 'avg_diff_35d',
        'avg_games_7d', 'avg_games_14d', 'avg_games_21d', 'avg_games_28d', 'avg_games_35d',
        'avg_efficiency_7d', 'avg_efficiency_14d', 'avg_efficiency_21d', 'avg_efficiency_28d', 'avg_efficiency_35d',
        'avg_rank_diff_7d', 'avg_rank_diff_14d', 'avg_rank_diff_21d', 'avg_rank_diff_28d', 'avg_rank_diff_35d',
        'machine_count'
    ]

    # Date/hall features
    categorical_cols = ['day_of_week', 'weekday_nth']
    numeric_cols = ['last_digit', 'is_weekend', 'is_holiday', 'is_any_event', 'week_of_month']

    # One-hot encode categorical
    df_enc = pd.get_dummies(df[categorical_cols], drop_first=True)

    # Combine all features
    X = pd.concat([
        df[rolling_cols + numeric_cols].fillna(0),
        df_enc
    ], axis=1)

    # Targets
    y_rank1 = df['is_rank_1'].astype(int)
    y_top3 = df['is_top_3'].astype(int)
    y_top5 = df['is_top_5'].astype(int)

    # Dates for time-series split
    dates = df['date'].values

    return X, {'rank_1': y_rank1, 'top_3': y_top3, 'top_5': y_top5}, dates

def train_and_evaluate(X, y_dict, dates):
    """Train models with time-series CV."""
    results = {}

    # Time-series split: 240 train days, 57 test days (manual split)
    total_days = len(dates)
    unique_dates = pd.Series(dates).unique()
    split_date_idx = len(unique_dates) - 57
    split_date = unique_dates[split_date_idx]

    train_mask = dates < split_date
    test_mask = dates >= split_date
    train_idx = np.where(train_mask)[0]
    test_idx = np.where(test_mask)[0]

    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    dates_train, dates_test = dates[train_idx], dates[test_idx]

    print(f"\nTrain dates: {dates_train[0]} to {dates_train[-1]}")
    print(f"Test dates: {dates_test[0]} to {dates_test[-1]}")
    print(f"Train size: {len(train_idx)}, Test size: {len(test_idx)}")

    # Train models
    for target_name, y in y_dict.items():
        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

        # Class balance ratio
        pos_ratio = y_train.sum() / len(y_train)
        scale_pos_weight = (1 - pos_ratio) / pos_ratio

        print(f"\n=== {target_name} ===")
        print(f"Positive ratio: {pos_ratio:.2%}")
        print(f"scale_pos_weight: {scale_pos_weight:.2f}")

        # Train XGBoost
        model = xgb.XGBClassifier(
            max_depth=5,
            learning_rate=0.1,
            n_estimators=100,
            scale_pos_weight=scale_pos_weight,
            random_state=42,
            eval_metric='auc'
        )
        model.fit(X_train, y_train, verbose=False)

        # Predict
        y_pred_proba = model.predict_proba(X_test)[:, 1]
        y_pred = model.predict(X_test)

        # Evaluate
        auc_score = roc_auc_score(y_test, y_pred_proba)
        ap_score = average_precision_score(y_test, y_pred_proba)

        # Precision/Recall at 10%, 20% thresholds
        p, r, thresh = precision_recall_curve(y_test, y_pred_proba)
        prec_at_10 = p[np.argmin(np.abs(r - 0.1))]*100 if (r >= 0.1).any() else 0
        prec_at_20 = p[np.argmin(np.abs(r - 0.2))]*100 if (r >= 0.2).any() else 0

        # Baseline: random prediction
        baseline_auc = 0.5

        result = {
            'model': model,
            'auc': auc_score,
            'ap': ap_score,
            'baseline_auc': baseline_auc,
            'auc_gain': (auc_score - baseline_auc) * 100,
            'prec_at_r10': prec_at_10,
            'prec_at_r20': prec_at_20,
            'pos_count': y_test.sum(),
            'neg_count': (1 - y_test).sum(),
        }
        results[target_name] = result

        print(f"AUC: {auc_score:.4f} (baseline: 0.5000, gain: {result['auc_gain']:.2f}%)")
        print(f"AP: {ap_score:.4f}")
        print(f"Precision @R=10%: {prec_at_10:.1f}%")
        print(f"Precision @R=20%: {prec_at_20:.1f}%")

    return results

def main():
    print("[Phase 7-2] Rank Prediction Model")

    # Create results dir
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Load data
    print(f"\nLoading data from {COPY_DB.name}...")
    df = load_data(COPY_DB)
    print(f"Loaded {len(df)} rows, {df['date'].nunique()} days")
    print(f"Date range: {df['date'].min()} to {df['date'].max()}")

    # Prepare features
    print("\nPreparing features...")
    X, y_dict, dates = prepare_features(df)
    print(f"Features: {X.shape[1]} columns")

    # Train and evaluate
    print("\nTraining models...")
    results = train_and_evaluate(X, y_dict, dates)

    # Save results summary
    summary = {
        'timestamp': datetime.now().isoformat(),
        'results': {
            k: {kk: float(vv) if isinstance(vv, (int, float, np.number)) else str(vv)
                 for kk, vv in v.items() if kk != 'model'}
            for k, v in results.items()
        }
    }

    summary_path = RESULTS_DIR / "summary.json"
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)
    print(f"\n[OK] Saved results to {summary_path}")

    return results

if __name__ == "__main__":
    results = main()
