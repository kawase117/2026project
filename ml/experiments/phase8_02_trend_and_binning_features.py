"""
Phase 8-2: Trend Features and Binning

Adds trend features (7d - 35d differences) and binned versions of continuous variables:
- Trend features: short-term vs long-term momentum
  * diff_trend: avg_diff_7d - avg_diff_35d
  * games_trend: avg_games_7d - avg_games_35d
  * efficiency_trend: avg_efficiency_7d - avg_efficiency_35d

- Binned features (to capture non-monotonic relationships):
  * games_bin: quartiles of avg_games (small/medium/large)
  * diff_bin: categories based on profit/loss
  * efficiency_bin: performance tiers
  * machine_count_bin: size categories (reflects store strategy, not linear)

Compares 25D extended vs ~40D+ model with trend/binning to measure incremental gains.
"""

import sqlite3
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, average_precision_score
import xgboost as xgb
import json

PROJECT_ROOT = Path("C:\\Users\\apto117\\Documents\\pachinko-analyzer\\src\\2026project")
sys.path.insert(0, str(PROJECT_ROOT))

COPY_DB = PROJECT_ROOT / "db" / "experiments" / "マルハンメガシティ2000-蒲田7_rank_exp.db"
RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase8_trend_binning"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


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
    """Compute days since last rank for rank_1, top_3, or top_5."""
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


def prepare_trend_and_binning_features(df):
    """
    Prepare extended feature set WITH trend and binning features.

    Starts with 25D extended model, adds:
    - 3D trend features (diff_trend, games_trend, efficiency_trend)
    - Binned versions of continuous features (~10-15D depending on encoding)

    Returns:
    - X_features: feature matrix (~40D)
    - feature_names: list of feature names
    """
    X_features = []
    feature_names = []

    # Compute days_since for all three ranks
    days_since_rank1 = compute_days_since_last_rank(df, 'is_rank_1')
    days_since_rank3 = compute_days_since_last_rank(df, 'is_top_3')
    days_since_rank5 = compute_days_since_last_rank(df, 'is_top_5')

    for idx, row in df.iterrows():
        features = []

        # === Original 25D features from Phase 8-1 ===

        # Month progress
        day_of_month = row['date'].day
        days_in_month = (pd.to_datetime(row['date']) + pd.DateOffset(months=1)).replace(day=1) - pd.Timedelta(days=1)
        month_progress = day_of_month / days_in_month.day
        features.append(month_progress)

        # Individual days_since (3D)
        r1 = float(days_since_rank1[idx])
        r3 = float(days_since_rank3[idx])
        r5 = float(days_since_rank5[idx])
        features.extend([r1, r3, r5])

        # Ratios (3D)
        ratio_3_1 = r3 / r1 if r1 > 0 else 1.0
        ratio_5_1 = r5 / r1 if r1 > 0 else 1.0
        ratio_5_3 = r5 / r3 if r3 > 0 else 1.0
        features.extend([ratio_3_1, ratio_5_1, ratio_5_3])

        # Differences (3D)
        diff_1_3 = r1 - r3
        diff_1_5 = r1 - r5
        diff_3_5 = r3 - r5
        features.extend([diff_1_3, diff_1_5, diff_3_5])

        # Composite (1D)
        days_since_any = max(r1, r3, r5)
        features.append(days_since_any)

        # Rolling average features (14D)
        rolling_cols = [
            'avg_diff_7d', 'avg_diff_14d', 'avg_diff_21d', 'avg_diff_28d', 'avg_diff_35d',
            'avg_games_7d', 'avg_games_14d', 'avg_games_21d', 'avg_games_28d', 'avg_games_35d',
            'avg_efficiency_7d', 'avg_efficiency_14d', 'avg_efficiency_28d',
            'machine_count'
        ]
        rolling_vals = [float(row[col]) if col in row and pd.notna(row[col]) else 0.0 for col in rolling_cols]
        features.extend(rolling_vals)

        # === NEW: Trend Features (3D) ===
        avg_diff_7d = float(row['avg_diff_7d']) if pd.notna(row['avg_diff_7d']) else 0.0
        avg_diff_35d = float(row['avg_diff_35d']) if pd.notna(row['avg_diff_35d']) else 0.0
        diff_trend = avg_diff_7d - avg_diff_35d

        avg_games_7d = float(row['avg_games_7d']) if pd.notna(row['avg_games_7d']) else 0.0
        avg_games_35d = float(row['avg_games_35d']) if pd.notna(row['avg_games_35d']) else 0.0
        games_trend = avg_games_7d - avg_games_35d

        avg_efficiency_7d = float(row['avg_efficiency_7d']) if pd.notna(row['avg_efficiency_7d']) else 0.0
        avg_efficiency_35d = float(row['avg_efficiency_28d']) if pd.notna(row['avg_efficiency_28d']) else 0.0
        efficiency_trend = avg_efficiency_7d - avg_efficiency_35d

        features.extend([diff_trend, games_trend, efficiency_trend])

        # === NEW: Binned Features ===

        # games_bin: quartile binning of avg_games_28d (representative of activity level)
        avg_games_28d = float(row['avg_games_28d']) if pd.notna(row['avg_games_28d']) else 0.0
        if avg_games_28d < 2000:
            games_bin = 0  # low
        elif avg_games_28d < 3000:
            games_bin = 1  # medium
        elif avg_games_28d < 4000:
            games_bin = 2  # high
        else:
            games_bin = 3  # very high
        features.extend([games_bin, games_bin == 0, games_bin == 1, games_bin == 2, games_bin == 3])

        # diff_bin: profit/loss category
        avg_diff_28d = float(row['avg_diff_28d']) if pd.notna(row['avg_diff_28d']) else 0.0
        if avg_diff_28d < -200:
            diff_bin = 0  # heavy loss
        elif avg_diff_28d < 0:
            diff_bin = 1  # loss
        elif avg_diff_28d < 200:
            diff_bin = 2  # break-even
        else:
            diff_bin = 3  # profit
        features.extend([diff_bin, diff_bin == 0, diff_bin == 1, diff_bin == 2, diff_bin == 3])

        # machine_count_bin: size category (NOT monotonic—mid-range often preferred per user feedback)
        machine_count = float(row['machine_count']) if pd.notna(row['machine_count']) else 0.0
        if machine_count < 20:
            count_bin = 0  # small (niche/specialty)
        elif machine_count < 50:
            count_bin = 1  # medium (balanced)
        elif machine_count < 100:
            count_bin = 2  # large (popular)
        else:
            count_bin = 3  # very large (flagship)
        features.extend([count_bin, count_bin == 0, count_bin == 1, count_bin == 2, count_bin == 3])

        X_features.append(features)

    # Build feature names (25D original + 3D trend + 15D binning)
    feature_names = [
        'month_progress',
        'days_since_rank1', 'days_since_rank3', 'days_since_rank5',
        'ratio_rank3_to_rank1', 'ratio_rank5_to_rank1', 'ratio_rank5_to_rank3',
        'diff_rank1_minus_rank3', 'diff_rank1_minus_rank5', 'diff_rank3_minus_rank5',
        'days_since_any',
        'avg_diff_7d', 'avg_diff_14d', 'avg_diff_21d', 'avg_diff_28d', 'avg_diff_35d',
        'avg_games_7d', 'avg_games_14d', 'avg_games_21d', 'avg_games_28d', 'avg_games_35d',
        'avg_efficiency_7d', 'avg_efficiency_14d', 'avg_efficiency_28d',
        'machine_count',
        'diff_trend', 'games_trend', 'efficiency_trend',
        'games_bin', 'games_bin_0', 'games_bin_1', 'games_bin_2', 'games_bin_3',
        'diff_bin', 'diff_bin_0', 'diff_bin_1', 'diff_bin_2', 'diff_bin_3',
        'count_bin', 'count_bin_0', 'count_bin_1', 'count_bin_2', 'count_bin_3'
    ]

    return np.array(X_features), feature_names


def train_and_compare(X_25d_baseline, X_40d_extended, feature_names_25d, feature_names_40d, y_dict, dates):
    """Train and compare 25D vs ~40D models."""
    results = {}

    # Time-series split
    unique_dates = pd.Series(dates).unique()
    split_date_idx = len(unique_dates) - 57
    split_date = unique_dates[split_date_idx]

    train_mask = dates < split_date
    test_mask = dates >= split_date

    X_train_25d = X_25d_baseline[train_mask]
    X_test_25d = X_25d_baseline[test_mask]
    X_train_40d = X_40d_extended[train_mask]
    X_test_40d = X_40d_extended[test_mask]

    print(f"\nTrain dates: {dates[train_mask].min()} to {dates[train_mask].max()}")
    print(f"Test dates:  {dates[test_mask].min()} to {dates[test_mask].max()}")
    print(f"Train size: {train_mask.sum()}, Test size: {test_mask.sum()}")

    targets_to_analyze = {
        'rank_1': y_dict['is_rank_1'],
        'top_3': y_dict['is_top_3'],
        'top_5': y_dict['is_top_5']
    }

    for target_name, y_full in targets_to_analyze.items():
        print(f"\n{'='*70}")
        print(f"Target: {target_name.upper()}")
        print(f"{'='*70}")

        y_train = y_full[train_mask]
        y_test = y_full[test_mask]

        print(f"Positive ratio (train): {y_train.sum() / len(y_train) * 100:.2f}%")
        print(f"Positive ratio (test):  {y_test.sum() / len(y_test) * 100:.2f}%")

        # Model 1: 25D extended (Phase 8-1 result)
        print(f"\n[Model 1: 25D Extended (Phase 8-1)]")
        model_25d = xgb.XGBClassifier(
            objective='binary:logistic',
            max_depth=3,
            learning_rate=0.01,
            n_estimators=200,
            random_state=42,
            eval_metric='logloss',
            verbosity=0
        )
        model_25d.fit(X_train_25d, y_train, verbose=False)

        y_pred_25d = model_25d.predict_proba(X_test_25d)[:, 1]
        auc_25d = roc_auc_score(y_test, y_pred_25d)
        ap_25d = average_precision_score(y_test, y_pred_25d)

        importance_25d = model_25d.feature_importances_

        print(f"  AUC: {auc_25d:.4f}")
        print(f"  AP:  {ap_25d:.4f}")

        # Model 2: 40D with trend + binning
        print(f"\n[Model 2: 40D+ with Trend + Binning Features]")
        model_40d = xgb.XGBClassifier(
            objective='binary:logistic',
            max_depth=3,
            learning_rate=0.01,
            n_estimators=200,
            random_state=42,
            eval_metric='logloss',
            verbosity=0
        )
        model_40d.fit(X_train_40d, y_train, verbose=False)

        y_pred_40d = model_40d.predict_proba(X_test_40d)[:, 1]
        auc_40d = roc_auc_score(y_test, y_pred_40d)
        ap_40d = average_precision_score(y_test, y_pred_40d)

        importance_40d = model_40d.feature_importances_

        print(f"  AUC: {auc_40d:.4f}")
        print(f"  AP:  {ap_40d:.4f}")

        # Comparison
        auc_delta_pct = (auc_40d - auc_25d) / auc_25d * 100
        ap_delta_pct = (ap_40d - ap_25d) / ap_25d * 100

        print(f"\n[Comparison]")
        print(f"  AUC delta:  {auc_delta_pct:+.2f}%")
        print(f"  AP delta:   {ap_delta_pct:+.2f}%")

        # Top features from 40D model
        top_indices = np.argsort(importance_40d)[::-1][:10]
        print(f"\n[Top 10 Features in 40D+ Model]")
        for rank, idx in enumerate(top_indices, 1):
            print(f"  {rank}. {feature_names_40d[idx]}: {importance_40d[idx]:.4f}")

        # Store results
        results[target_name] = {
            'baseline_25d': {
                'auc': float(auc_25d),
                'ap': float(ap_25d),
                'n_features': 25
            },
            'extended_40d': {
                'auc': float(auc_40d),
                'ap': float(ap_40d),
                'n_features': len(feature_names_40d),
                'feature_importances': {name: float(imp) for name, imp in zip(feature_names_40d, importance_40d)}
            },
            'comparison': {
                'auc_baseline': float(auc_25d),
                'auc_extended': float(auc_40d),
                'auc_delta_pct': float(auc_delta_pct),
                'ap_baseline': float(ap_25d),
                'ap_extended': float(ap_40d),
                'ap_delta_pct': float(ap_delta_pct)
            }
        }

    return results


def main():
    print("="*70)
    print("Phase 8-2: Trend Features and Binning")
    print("="*70)

    # Load data
    print("\n[Loading data...]")
    df = load_data(COPY_DB)
    print(f"  Loaded {len(df)} rows, {len(df['machine_name'].unique())} machines")

    # Prepare features
    print("\n[Preparing 25D baseline...]")
    # For 25D, we need to recompute (simplified version)
    days_since_rank1 = compute_days_since_last_rank(df, 'is_rank_1')
    X_25d = []
    for idx, row in df.iterrows():
        features = []
        day_of_month = row['date'].day
        days_in_month = (pd.to_datetime(row['date']) + pd.DateOffset(months=1)).replace(day=1) - pd.Timedelta(days=1)
        month_progress = day_of_month / days_in_month.day
        features.append(month_progress)
        features.append(float(days_since_rank1[idx]))
        rolling_cols = [
            'avg_diff_7d', 'avg_diff_14d', 'avg_diff_21d', 'avg_diff_28d', 'avg_diff_35d',
            'avg_games_7d', 'avg_games_14d', 'avg_games_21d', 'avg_games_28d', 'avg_games_35d',
            'avg_efficiency_7d', 'avg_efficiency_14d', 'avg_efficiency_28d',
            'machine_count'
        ]
        rolling_vals = [float(row[col]) if col in row and pd.notna(row[col]) else 0.0 for col in rolling_cols]
        features.extend(rolling_vals)
        X_25d.append(features)
    X_25d = np.array(X_25d)
    feature_names_25d = ['month_progress', 'days_since_rank1'] + rolling_cols
    print(f"  Baseline 25D shape: {X_25d.shape}")

    print("\n[Preparing 40D+ with trend and binning...]")
    X_40d, feature_names_40d = prepare_trend_and_binning_features(df)
    print(f"  Extended 40D+ shape: {X_40d.shape}")

    # Prepare target variables
    y_dict = {
        'is_rank_1': df['is_rank_1'].values,
        'is_top_3': df['is_top_3'].values,
        'is_top_5': df['is_top_5'].values
    }

    dates = df['date'].values

    # Train and compare
    print("\n[Training and comparing models...]")
    all_results = train_and_compare(X_25d, X_40d, feature_names_25d, feature_names_40d, y_dict, dates)

    # Save results
    output_file = RESULTS_DIR / "phase8_02_trend_binning_analysis.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\n[COMPLETED] Results saved to {output_file}")

    # Print summary
    print("\n" + "="*70)
    print("SUMMARY: Trend + Binning Features Impact")
    print("="*70)
    for target_name in ['rank_1', 'top_3', 'top_5']:
        comp = all_results[target_name]['comparison']
        print(f"\n{target_name.upper()}:")
        print(f"  25D Extended AUC:     {comp['auc_baseline']:.4f}")
        print(f"  40D+ Trend/Binning AUC: {comp['auc_extended']:.4f}")
        print(f"  AUC improvement:      {comp['auc_delta_pct']:+.2f}%")
        print(f"  AP improvement:       {comp['ap_delta_pct']:+.2f}%")


if __name__ == '__main__':
    main()
