"""
Phase 7: Feature Importance Analysis - Expanded Feature Set v2

Analyzes which features contribute most to predictions using expanded feature set:
- month_progress (1D)
- is_weekend (1D) - compressed day-of-week
- days_since_last_rank1 (1D) - time since last rank1 prediction
- rolling averages for diff (5D)
- rolling averages for games (5D)
- rolling averages for efficiency (4D)
- rolling averages for rank_diff (5D) - NEW
- machine_count (1D)

Total: 23D expanded features
"""

import sqlite3
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
import xgboost as xgb
import json
from datetime import datetime

PROJECT_ROOT = Path("C:\Users\apto117\Documents\pachinko-analyzer\src\2026project")
sys.path.insert(0, str(PROJECT_ROOT))

COPY_DB = PROJECT_ROOT / "db" / "experiments" / "マルハンメガシティ2000-蒲田7_rank_exp.db"
RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase7_rank_prediction_v4_expanded"


def load_data(db_path):
    """Load data from copy DB."""
    conn = sqlite3.connect(db_path)

    df_machine = pd.read_sql_query("""
        SELECT
            date, machine_name, machine_count,
            avg_diff_7d, avg_diff_14d, avg_diff_21d, avg_diff_28d, avg_diff_35d,
            avg_games_7d, avg_games_14d, avg_games_21d, avg_games_28d, avg_games_35d,
            avg_efficiency_7d, avg_efficiency_14d, avg_efficiency_21d, avg_efficiency_28d,
            avg_rank_diff_7d, avg_rank_diff_14d, avg_rank_diff_21d, avg_rank_diff_28d, avg_rank_diff_35d,
            is_rank_1, is_top_3, is_top_5
        FROM daily_machine_type_summary
        ORDER BY date, machine_name
    """, conn)

    conn.close()

    df_machine['date'] = pd.to_datetime(df_machine['date'], format='%Y%m%d')
    df_machine = df_machine.sort_values(['machine_name', 'date']).reset_index(drop=True)

    return df_machine


def prepare_expanded_features_with_names(df):
    """
    Prepare expanded features with descriptive names.

    Features (23D):
    - month_progress (1D)
    - is_weekend (1D) - compressed day-of-week
    - days_since_last_rank1 (1D) - time since this machine last ranked 1
    - rolling averages for diff (5D)
    - rolling averages for games (5D)
    - rolling averages for efficiency (4D)
    - rolling averages for rank_diff (5D) - NEW
    - machine_count (1D)
    """
    X_features = []
    feature_names = []

    # Calculate days_since_last_rank1 per machine
    df_with_days = df.copy()
    df_with_days['days_since_last_rank1'] = 0

    for machine_name in df['machine_name'].unique():
        mask = df_with_days['machine_name'] == machine_name
        machine_df = df_with_days[mask].copy()

        last_rank1_date = None
        days_since = []

        for idx, row in machine_df.iterrows():
            if row['is_rank_1'] == 1:
                last_rank1_date = row['date']

            if last_rank1_date is not None:
                days_diff = (row['date'] - last_rank1_date).days
            else:
                days_diff = 365  # Default to 365 days if never ranked 1

            days_since.append(days_diff)

        df_with_days.loc[mask, 'days_since_last_rank1'] = days_since

    # Build feature matrix
    for idx, row in df_with_days.iterrows():
        features = []

        # 1. Month progress (1D)
        day_of_month = row['date'].day
        days_in_month = (pd.to_datetime(row['date']) + pd.DateOffset(months=1)).replace(day=1) - pd.Timedelta(days=1)
        month_progress = day_of_month / days_in_month.day
        features.append(month_progress)
        if idx == 0:
            feature_names.append('month_progress')

        # 2. Is weekend (1D) - compressed day-of-week
        is_weekend = 1.0 if row['date'].day_name() in ['Saturday', 'Sunday'] else 0.0
        features.append(is_weekend)
        if idx == 0:
            feature_names.append('is_weekend')

        # 3. Days since last rank1 (1D)
        days_since_rank1 = float(row['days_since_last_rank1']) if pd.notna(row['days_since_last_rank1']) else 365.0
        features.append(days_since_rank1)
        if idx == 0:
            feature_names.append('days_since_last_rank1')

        # 4. Rolling average features for diff (5D)
        diff_cols = ['avg_diff_7d', 'avg_diff_14d', 'avg_diff_21d', 'avg_diff_28d', 'avg_diff_35d']
        diff_vals = [float(row[col]) if col in row and pd.notna(row[col]) else 0.0 for col in diff_cols]
        features.extend(diff_vals)
        if idx == 0:
            feature_names.extend(diff_cols)

        # 5. Rolling average features for games (5D)
        games_cols = ['avg_games_7d', 'avg_games_14d', 'avg_games_21d', 'avg_games_28d', 'avg_games_35d']
        games_vals = [float(row[col]) if col in row and pd.notna(row[col]) else 0.0 for col in games_cols]
        features.extend(games_vals)
        if idx == 0:
            feature_names.extend(games_cols)

        # 6. Rolling average features for efficiency (4D)
        eff_cols = ['avg_efficiency_7d', 'avg_efficiency_14d', 'avg_efficiency_21d', 'avg_efficiency_28d']
        eff_vals = [float(row[col]) if col in row and pd.notna(row[col]) else 0.0 for col in eff_cols]
        features.extend(eff_vals)
        if idx == 0:
            feature_names.extend(eff_cols)

        # 7. Rolling average features for rank_diff (5D) - NEW
        rank_cols = ['avg_rank_diff_7d', 'avg_rank_diff_14d', 'avg_rank_diff_21d', 'avg_rank_diff_28d', 'avg_rank_diff_35d']
        rank_vals = [float(row[col]) if col in row and pd.notna(row[col]) else 0.0 for col in rank_cols]
        features.extend(rank_vals)
        if idx == 0:
            feature_names.extend(rank_cols)

        # 8. Machine count (1D)
        machine_count = float(row['machine_count']) if pd.notna(row['machine_count']) else 0.0
        features.append(machine_count)
        if idx == 0:
            feature_names.append('machine_count')

        X_features.append(features)

    X = np.array(X_features)
    return X, feature_names


def train_and_get_importance(X, y, feature_names, target_name):
    """Train model and extract feature importance."""
    split_idx = int(len(X) * 0.76)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    pos_ratio = y_train.sum() / len(y_train)
    scale_pos_weight = (1 - pos_ratio) / pos_ratio if pos_ratio > 0 else 1.0

    model = xgb.XGBClassifier(
        max_depth=5,
        learning_rate=0.1,
        n_estimators=100,
        scale_pos_weight=scale_pos_weight,
        random_state=42,
        eval_metric='auc'
    )
    model.fit(X_train, y_train, verbose=False)

    importances = model.get_booster().get_score(importance_type='weight')

    importance_dict = {}
    for fname in feature_names:
        f_key = f'f{feature_names.index(fname)}'
        importance_dict[fname] = importances.get(f_key, 0)

    y_pred_proba = model.predict_proba(X_test)[:, 1]
    auc = roc_auc_score(y_test, y_pred_proba)

    return importance_dict, auc


def main():
    print("="*80)
    print("[Phase 7-4] Feature Importance Analysis - Expanded Features v2")
    print("="*80)

    print(f"\nLoading data...")
    df = load_data(COPY_DB)
    print(f"Loaded {len(df)} rows")

    print(f"\nPreparing expanded features (23D)...")
    X, feature_names = prepare_expanded_features_with_names(df)
    print(f"Feature matrix: {X.shape}")
    print(f"Features ({len(feature_names)}): {', '.join(feature_names)}")

    results = {}

    for target_name in ['
