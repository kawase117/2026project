"""
Phase 7: Feature Importance Analysis

Analyzes which features (refactored 14D + rolling avg) contribute most to predictions.
Identifies redundant/low-signal features for removal.
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

PROJECT_ROOT = Path("C:\\Users\\apto117\\Documents\\pachinko-analyzer\\src\\2026project")
sys.path.insert(0, str(PROJECT_ROOT))

COPY_DB = PROJECT_ROOT / "db" / "experiments" / "マルハンメガシティ2000-蒲田7_rank_exp.db"
RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase7_rank_prediction_v2_refactored"


def load_data(db_path):
    """Load data from copy DB."""
    conn = sqlite3.connect(db_path)

    df_machine = pd.read_sql_query("""
        SELECT date, machine_name, machine_count,
               avg_diff_7d, avg_diff_14d, avg_diff_21d, avg_diff_28d, avg_diff_35d,
               avg_games_7d, avg_games_14d, avg_games_21d, avg_games_28d, avg_games_35d,
               avg_efficiency_7d, avg_efficiency_14d, avg_efficiency_21d, avg_efficiency_28d,
               avg_rank_diff_7d, avg_rank_diff_14d, avg_rank_diff_21d, avg_rank_diff_28d, avg_rank_diff_35d,
               is_rank_1, is_top_3, is_top_5
        FROM daily_machine_type_summary
        ORDER BY date
    """, conn)

    df_hall = pd.read_sql_query("""
        SELECT date, day_of_week, last_digit, is_weekend, is_holiday
        FROM daily_hall_summary
    """, conn)

    conn.close()

    df_machine['date'] = pd.to_datetime(df_machine['date'], format='%Y%m%d')
    df_hall['date'] = pd.to_datetime(df_hall['date'], format='%Y%m%d')

    df = df_machine.merge(df_hall, on='date', how='left')
    df = df.sort_values('date').reset_index(drop=True)

    return df


def prepare_features_with_names(df):
    """Prepare features with descriptive names."""
    X_features = []
    feature_names = []

    for idx, row in df.iterrows():
        features = []

        # 1. Day of week (7D)
        dow_cols = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        dow = row['date'].day_name()
        dow_vec = [1.0 if d == dow else 0.0 for d in dow_cols]
        features.extend(dow_vec)
        if idx == 0:
            feature_names.extend([f'dow_{d[:3]}' for d in dow_cols])

        # 2. Month progress (1D)
        day_of_month = row['date'].day
        days_in_month = (pd.to_datetime(row['date']) + pd.DateOffset(months=1)).replace(day=1) - pd.Timedelta(days=1)
        month_progress = day_of_month / days_in_month.day
        features.append(month_progress)
        if idx == 0:
            feature_names.append('month_progress')

        # 3. Payday window (1D)
        if 23 <= day_of_month <= 27:
            payday_effect = {23: 0.2, 24: 0.6, 25: 1.0, 26: 0.6, 27: 0.2}
            features.append(payday_effect[day_of_month])
        else:
            features.append(0.0)
        if idx == 0:
            feature_names.append('payday_window')

        # 4. Composite features (4D)
        is_weekend = 1.0 if row['date'].day_name() in ['Saturday', 'Sunday'] else 0.0
        features.append(month_progress * 0.0)
        features.append(is_weekend * 0.0)
        features.append(features[8] * month_progress)
        month_center = 1.0 if 14 <= day_of_month <= 16 else 0.0
        features.append(0.0 * month_center)
        if idx == 0:
            feature_names.extend([f'composite_{i+1}' for i in range(4)])

        # 5. Rolling average features (15D)
        rolling_cols = [
            'avg_diff_7d', 'avg_diff_14d', 'avg_diff_21d', 'avg_diff_28d', 'avg_diff_35d',
            'avg_games_7d', 'avg_games_14d', 'avg_games_21d', 'avg_games_28d', 'avg_games_35d',
            'avg_efficiency_7d', 'avg_efficiency_14d', 'avg_efficiency_21d', 'avg_efficiency_28d',
            'machine_count'
        ]
        rolling_vals = [float(row[col]) if col in row and pd.notna(row[col]) else 0.0 for col in rolling_cols]
        features.extend(rolling_vals)
        if idx == 0:
            feature_names.extend(rolling_cols)

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
    print("[Phase 7] Feature Importance Analysis")
    print("="*80)

    print(f"\nLoading data...")
    df = load_data(COPY_DB)
    print(f"Loaded {len(df)} rows")

    print(f"\nPreparing features...")
    X, feature_names = prepare_features_with_names(df)
    print(f"Feature matrix: {X.shape}")

    results = {}

    for target_name in ['rank_1', 'top_3', 'top_5']:
        print(f"\n{'='*80}")
        print(f"Target: {target_name.upper()}")
        print(f"{'='*80}")

        y = df[f'is_{target_name}'].values.astype(int)
        importance_dict, auc = train_and_get_importance(X, y, feature_names, target_name)

        sorted_importance = sorted(importance_dict.items(), key=lambda x: x[1], reverse=True)

        print(f"\nAUC: {auc:.4f}")
        print(f"\nTop 15 Important Features:")
        print(f"{'Rank':<6} {'Feature':<30} {'Importance':<15}")
        print("-" * 52)

        total_importance = sum(importance_dict.values())
        for rank, (fname, imp) in enumerate(sorted_importance[:15], 1):
            pct = (imp / total_importance * 100) if total_importance > 0 else 0
            print(f"{rank:<6} {fname:<30} {imp:<10.2f} ({pct:>6.2f}%)")

        # Category summary
        print(f"\nImportance by Category:")
        categories = {
            'dow': {f: importance_dict.get(f, 0) for f in feature_names if f.startswith('dow_')},
            'month_progress': {f: importance_dict.get(f, 0) for f in feature_names if f == 'month_progress'},
            'payday_window': {f: importance_dict.get(f, 0) for f in feature_names if f == 'payday_window'},
            'composite': {f: importance_dict.get(f, 0) for f in feature_names if f.startswith('composite_')},
            'rolling_avg': {f: importance_dict.get(f, 0) for f in feature_names
                           if not any(f.startswith(p) for p in ['dow_', 'composite_'])
                           and f not in ['month_progress', 'payday_window']}
        }

        for cat_name, cat_dict in categories.items():
            cat_importance = sum(cat_dict.values())
            cat_pct = (cat_importance / total_importance * 100) if total_importance > 0 else 0
            print(f"  {cat_name:<25}: {cat_importance:>10.2f} ({cat_pct:>6.2f}%)")

        results[target_name] = {
            'auc': float(auc),
            'total_importance': float(total_importance),
            'top_10_features': [fname for fname, _ in sorted_importance[:10]],
            'feature_importance': {fname: float(imp) for fname, imp in sorted_importance}
        }

    # Save results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    results_path = RESULTS_DIR / "feature_importance_analysis.json"
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*80}")
    print(f"[OK] Results saved to {results_path}")
    print(f"{'='*80}")

    return results


if __name__ == "__main__":
    results = main()
