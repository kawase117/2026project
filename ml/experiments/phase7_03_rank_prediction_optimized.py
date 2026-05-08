"""
Phase 7: Rank Prediction - Step 3: Optimized Feature Set

Based on feature importance analysis, removed unnecessary features:
- Removed: day-of-week one-hot (3.9% importance)
- Removed: payday_window ramp (0.4% importance)
- Removed: composite features (0.4% importance)
- Kept: rolling averages (88.5% importance) + month_progress (6.3% importance)

Tests unified feature set across all three targets (rank_1, top_3, top_5).
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
RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase7_rank_prediction_v3_optimized"


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
        ORDER BY date
    """, conn)

    df_hall = pd.read_sql_query("""
        SELECT date
        FROM daily_hall_summary
    """, conn)

    conn.close()

    df_machine['date'] = pd.to_datetime(df_machine['date'], format='%Y%m%d')
    df_hall['date'] = pd.to_datetime(df_hall['date'], format='%Y%m%d')

    df = df_machine.merge(df_hall, on='date', how='left')
    df = df.sort_values('date').reset_index(drop=True)

    return df


def prepare_optimized_features(df):
    """
    Prepare optimized features (rolling averages + month_progress only).

    Removed:
    - day_of_week (3.9% importance) - temporal encoding redundant with rolling windows
    - payday_window (0.4% importance) - negligible signal
    - composite features (0.4% importance) - negligible signal

    Kept:
    - rolling averages (88.5% importance)
    - month_progress (6.3% importance)
    """
    X_optimized = []

    for idx, row in df.iterrows():
        features = []

        # 1. Month progress rate (1D)
        day_of_month = row['date'].day
        days_in_month = (pd.to_datetime(row['date']) + pd.DateOffset(months=1)).replace(day=1) - pd.Timedelta(days=1)
        month_progress = day_of_month / days_in_month.day
        features.append(month_progress)

        # 2. Rolling average features (15D)
        rolling_cols = [
            'avg_diff_7d', 'avg_diff_14d', 'avg_diff_21d', 'avg_diff_28d', 'avg_diff_35d',
            'avg_games_7d', 'avg_games_14d', 'avg_games_21d', 'avg_games_28d', 'avg_games_35d',
            'avg_efficiency_7d', 'avg_efficiency_14d', 'avg_efficiency_21d', 'avg_efficiency_28d',
            'machine_count'
        ]
        rolling_vals = [float(row[col]) if col in row and pd.notna(row[col]) else 0.0 for col in rolling_cols]
        features.extend(rolling_vals)

        X_optimized.append(features)

    X_optimized = np.array(X_optimized)
    return X_optimized


def train_and_evaluate(X, y_dict, dates):
    """Train XGBoost models with time-series split."""
    results = {}

    # Time-series split (same as previous: 240 train days, 57 test days)
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
    print(f"Feature dimension: {X.shape[1]}D (1D month_progress + 15D rolling avg)")

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
    print("[Phase 7-3] Rank Prediction - Optimized Feature Set (Unified Model)")
    print("="*80)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Load data
    print(f"\n[1] Loading copy DB: {COPY_DB.name}")
    df = load_data(COPY_DB)
    print(f"    Loaded {len(df)} rows, {df['date'].nunique()} days")
    print(f"    Date range: {df['date'].min()} to {df['date'].max()}")

    # Prepare features
    print(f"\n[2] Preparing optimized features (month_progress + rolling avg only)...")
    X = prepare_optimized_features(df)
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
        'method': 'Optimized Features (Unified Model)',
        'feature_dimension': X.shape[1],
        'features_kept': 'month_progress (1D) + rolling averages (15D)',
        'features_removed': [
            'day_of_week one-hot (3.9% importance)',
            'payday_window ramp (0.4% importance)',
            'composite features (0.4% importance)'
        ],
        'design_rationale': 'Unified feature set across all targets to avoid overfitting. Rolling averages already encode temporal patterns.',
        'copy_db': str(COPY_DB.name),
        'results': {
            k: {kk: float(vv) if isinstance(vv, (int, float, np.number)) else str(vv)
                 for kk, vv in v.items() if kk != 'model'}
            for k, v in results.items()
        }
    }

    summary_path = RESULTS_DIR / "summary_optimized.json"
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*80}")
    print(f"[OK] Results saved to {summary_path}")
    print(f"{'='*80}")

    return results


if __name__ == "__main__":
    results = main()
