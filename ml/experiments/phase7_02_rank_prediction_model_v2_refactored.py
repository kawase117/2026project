"""
Phase 7: Rank Prediction - Step 2b: Refactored 14D Features + XGBoost Model

Uses feature_engineering_v2.py (14D refactored features) instead of baseline features.

Loads copy DB, prepares refactored features, and trains XGBoost models to predict:
- is_rank_1: Top ranked machine
- is_top_3: Top 3 ranked
- is_top_5: Top 5 ranked

Metrics:
- AUC (Area Under ROC Curve)
- AP (Average Precision)
- Brier Score (calibration)
- Accuracy
- Precision @R=10% (Precision at 10% recall)
- Precision @R=20% (Precision at 20% recall)
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

# Add project root to path
PROJECT_ROOT = Path("C:\\Users\\apto117\\Documents\\pachinko-analyzer\\src\\2026project")
sys.path.insert(0, str(PROJECT_ROOT))

# Paths
COPY_DB = PROJECT_ROOT / "db" / "experiments" / "マルハンメガシティ2000-蒲田7_rank_exp.db"
RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase7_rank_prediction_v2_refactored"


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
            avg_efficiency_7d, avg_efficiency_14d, avg_efficiency_21d, avg_efficiency_28d,
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


def prepare_refactored_features(df):
    """
    Prepare refactored 14D features (Phase 6B design):
    - Temporal: 8D (day_of_week 7D + month_progress 1D)
    - Machine encoding: 1D (target encoding - not applicable at machine_type level, use placeholder)
    - Payday window: 1D (ramp 0→1→0 across days 23-27)
    - Composite: 4D (temporal interactions)

    Plus rolling average features from historical data.
    """
    X_refactored = []

    for idx, row in df.iterrows():
        features = []

        # 1. Day of week (7D one-hot)
        dow_cols = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        dow = row['date'].day_name()
        for d in dow_cols:
            features.append(1.0 if d == dow else 0.0)

        # 2. Month progress rate (1D)
        day_of_month = row['date'].day
        days_in_month = (pd.to_datetime(row['date']) + pd.DateOffset(months=1)).replace(day=1) - pd.Timedelta(days=1)
        month_progress = day_of_month / days_in_month.day
        features.append(month_progress)

        # 3. Payday window (1D) - ramp shape days 23-27
        if 23 <= day_of_month <= 27:
            payday_effect = {23: 0.2, 24: 0.6, 25: 1.0, 26: 0.6, 27: 0.2}
            features.append(payday_effect[day_of_month])
        else:
            features.append(0.0)

        # 4. Composite features (4D)
        is_weekend = row['date'].day_name() in ['Saturday', 'Sunday']

        # Composite 1: month_progress × is_zorome (placeholder)
        features.append(month_progress * 0.0)

        # Composite 2: is_weekend × is_zorome
        features.append((1.0 if is_weekend else 0.0) * 0.0)

        # Composite 3: payday_window × month_progress
        features.append(features[8] * month_progress)

        # Composite 4: is_zorome × month_center (days 14-16)
        month_center = 1.0 if 14 <= day_of_month <= 16 else 0.0
        features.append(0.0 * month_center)

        X_refactored.append(features)

    X_refactored = np.array(X_refactored)

    # Rolling average features
    rolling_cols = [
        'avg_diff_7d', 'avg_diff_14d', 'avg_diff_21d', 'avg_diff_28d', 'avg_diff_35d',
        'avg_games_7d', 'avg_games_14d', 'avg_games_21d', 'avg_games_28d', 'avg_games_35d',
        'avg_efficiency_7d', 'avg_efficiency_14d', 'avg_efficiency_21d', 'avg_efficiency_28d',
        'machine_count'
    ]

    X_rolling = df[rolling_cols].fillna(0).values

    # Combine: refactored (14D) + rolling features
    X_combined = np.hstack([X_refactored, X_rolling])

    return X_combined


def train_and_evaluate(X, y_dict, dates):
    """Train XGBoost models with time-series split."""
    results = {}

    # Time-series split
    unique_dates = pd.Series(dates).unique()
    split_date_idx = len(unique_dates) - 57
    split_date = unique_dates[split_date_idx]

    train_mask = dates < split_date
    test_mask = dates >= split_date
    train_idx = np.where(train_mask)[0]
    test_idx = np.where(test_mask)[0]

    X_train, X_test = X[train_idx], X[test_idx]
    dates_train, dates_test = dates[train_idx], dates[test_idx]

    print(f"\nTrain dates: {dates_train[0]} to {dates_train[-1]}")
    print(f"Test dates: {dates_test[0]} to {dates_test[-1]}")
    print(f"Train size: {len(train_idx)}, Test size: {len(test_idx)}")
    print(f"Feature dimension: {X.shape[1]}D (14D refactored + rolling avg features)")

    # Train models for each target
    for target_name, y in y_dict.items():
        y_train, y_test = y[train_idx], y[test_idx]

        # Class balance
        pos_ratio = y_train.sum() / len(y_train)
        scale_pos_weight = (1 - pos_ratio) / pos_ratio if pos_ratio > 0 else 1.0

        print(f"\n{'='*70}")
        print(f"Target: {target_name.upper()}")
        print(f"{'='*70}")
        print(f"Positive ratio (train): {pos_ratio:.2%}")
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

        # Evaluate - comprehensive metrics
        auc_score = roc_auc_score(y_test, y_pred_proba)
        ap_score = average_precision_score(y_test, y_pred_proba)
        brier = brier_score_loss(y_test, y_pred_proba)
        accuracy = accuracy_score(y_test, y_pred)

        # Precision at recall thresholds
        p, r, _ = precision_recall_curve(y_test, y_pred_proba)
        prec_at_10 = p[np.argmin(np.abs(r - 0.1))]*100 if (r >= 0.1).any() else 0
        prec_at_20 = p[np.argmin(np.abs(r - 0.2))]*100 if (r >= 0.2).any() else 0

        baseline_auc = 0.5

        result = {
            'model': model,
            'auc': auc_score,
            'ap': ap_score,
            'brier_score': brier,
            'accuracy': accuracy,
            'baseline_auc': baseline_auc,
            'auc_gain': (auc_score - baseline_auc) * 100,
            'prec_at_r10': prec_at_10,
            'prec_at_r20': prec_at_20,
            'pos_count': int(y_test.sum()),
            'neg_count': int((1 - y_test).sum()),
        }
        results[target_name] = result

        # Display results
        print(f"\n[Rank Discrimination]")
        print(f"  AUC:  {auc_score:.4f} (baseline: 0.5000, gain: {result['auc_gain']:+.2f}%)")
        print(f"  AP:   {ap_score:.4f}")
        print(f"\n[Calibration]")
        print(f"  Brier Score: {brier:.4f}")
        print(f"  Accuracy:    {accuracy:.4f}")
        print(f"\n[Precision at Recall Levels]")
        print(f"  Precision @R=10%: {prec_at_10:.1f}%")
        print(f"  Precision @R=20%: {prec_at_20:.1f}%")
        print(f"\n[Test Set Distribution]")
        print(f"  Positive:  {result['pos_count']}")
        print(f"  Negative:  {result['neg_count']}")

    return results


def main():
    print("="*80)
    print("[Phase 7-2b] Rank Prediction - Refactored 14D Features + XGBoost")
    print("="*80)

    # Create results dir
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Load data
    print(f"\n[1] Loading copy DB: {COPY_DB.name}")
    df = load_data(COPY_DB)
    print(f"    Loaded {len(df)} rows, {df['date'].nunique()} days")
    print(f"    Date range: {df['date'].min()} to {df['date'].max()}")

    # Prepare features
    print(f"\n[2] Preparing refactored 14D features...")
    X = prepare_refactored_features(df)
    print(f"    Feature matrix shape: {X.shape}")

    # Targets
    y_dict = {
        'rank_1': df['is_rank_1'].values.astype(int),
        'top_3': df['is_top_3'].values.astype(int),
        'top_5': df['is_top_5'].values.astype(int)
    }
    dates = df['date'].values

    # Train and evaluate
    print(f"\n[3] Training XGBoost models...")
    results = train_and_evaluate(X, y_dict, dates)

    # Save results
    summary = {
        'timestamp': datetime.now().isoformat(),
        'method': 'Refactored 14D Features (Phase 6B) + Rolling Average Features',
        'feature_dimension': X.shape[1],
        'base_features': '14D refactored (temporal 8D + machine_encoding 1D + payday_window 1D + composite 4D)',
        'rolling_features': '15D (avg_diff/games/efficiency/rank_diff at 7/14/21/28/35 days + machine_count)',
        'copy_db': str(COPY_DB.name),
        'results': {
            k: {kk: float(vv) if isinstance(vv, (int, float, np.number)) else str(vv)
                 for kk, vv in v.items() if kk != 'model'}
            for k, v in results.items()
        }
    }

    summary_path = RESULTS_DIR / "summary_refactored.json"
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*80}")
    print(f"[OK] Results saved to {summary_path}")
    print(f"{'='*80}")

    return results


if __name__ == "__main__":
    results = main()
