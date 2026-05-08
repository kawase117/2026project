# -*- coding: utf-8 -*-
"""
Phase 8-6: 偽陽性根因分析 - False Positive Root Cause Analysis

Diagnoses what causes false positives (model predicts high rank but it's low).
Compares feature distributions between FP and TP cases to identify
common patterns and feature combinations that lead to misclassifications.

Q: What feature patterns cause the model to incorrectly predict high rank?
This reveals weaknesses in the model and potential setting patterns it misses.
"""

import sqlite3
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
import xgboost as xgb

PROJECT_ROOT = Path("C:\\Users\\apto117\\Documents\\pachinko-analyzer\\src\\2026project")
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "db" / "experiments" / "マルハンメガシティ2000-蒲田7_rank_exp.db"
RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase8_false_positives"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def load_data(db_path):
    """Load machine daily data with features."""
    conn = sqlite3.connect(db_path)

    df = pd.read_sql_query("""
        SELECT
            date,
            machine_name,
            machine_count,
            avg_diff_7d, avg_diff_14d, avg_diff_28d,
            avg_games_7d, avg_games_14d, avg_games_28d,
            avg_efficiency_7d, avg_efficiency_14d, avg_efficiency_28d,
            is_rank_1,
            is_top_3,
            is_top_5
        FROM daily_machine_type_summary
        ORDER BY date, machine_name
    """, conn)

    conn.close()

    df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')

    return df


def compute_days_since_last_rank(df, rank_column):
    """Compute days since last rank for each machine."""
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


def prepare_features(df):
    """Prepare feature matrix for analysis."""
    # Add days_since features
    df['days_since_rank_1'] = compute_days_since_last_rank(df, 'is_rank_1')
    df['days_since_top_3'] = compute_days_since_last_rank(df, 'is_top_3')
    df['days_since_top_5'] = compute_days_since_last_rank(df, 'is_top_5')

    # Add efficiency ratios
    df['efficiency_7d'] = df['avg_diff_7d'] / df['avg_games_7d'].replace(0, 1)
    df['efficiency_14d'] = df['avg_diff_14d'] / df['avg_games_14d'].replace(0, 1)
    df['efficiency_28d'] = df['avg_diff_28d'] / df['avg_games_28d'].replace(0, 1)

    feature_cols = [
        'machine_count',
        'avg_diff_7d', 'avg_diff_14d', 'avg_diff_28d',
        'avg_games_7d', 'avg_games_14d', 'avg_games_28d',
        'avg_efficiency_7d', 'avg_efficiency_14d', 'avg_efficiency_28d',
        'days_since_rank_1', 'days_since_top_3', 'days_since_top_5',
        'efficiency_7d', 'efficiency_14d', 'efficiency_28d'
    ]

    return df, feature_cols


def train_baseline_model(df, feature_cols, target_col):
    """Train baseline model for predictions."""
    valid_mask = df[feature_cols].notna().all(axis=1) & df[target_col].notna()
    X = df[valid_mask][feature_cols].fillna(0)
    y = df[valid_mask][target_col].astype(int)

    if len(y) == 0 or y.sum() < 10:
        return None, None, None

    model = xgb.XGBClassifier(
        max_depth=3,
        learning_rate=0.01,
        n_estimators=100,
        random_state=42,
        scale_pos_weight=1.0
    )

    model.fit(X, y, verbose=False)
    y_pred_proba = model.predict_proba(X)[:, 1]

    return model, y_pred_proba, valid_mask


def identify_error_cases(df, y_pred_proba, target_col, valid_mask, threshold=0.50):
    """
    Identify FP and TP cases.
    FP: predicted >= threshold, actual = 0
    TP: predicted >= threshold, actual = 1
    """
    df_valid = df[valid_mask].copy()
    df_valid['y_pred_proba'] = y_pred_proba

    high_conf_mask = df_valid['y_pred_proba'] >= threshold
    df_highconf = df_valid[high_conf_mask]

    fp_mask = (df_highconf['y_pred_proba'] >= threshold) & (df_highconf[target_col] == 0)
    tp_mask = (df_highconf['y_pred_proba'] >= threshold) & (df_highconf[target_col] == 1)

    fp_cases = df_highconf[fp_mask]
    tp_cases = df_highconf[tp_mask]

    return fp_cases, tp_cases


def compute_feature_differences(fp_cases, tp_cases, feature_cols):
    """
    Compute feature distribution differences between FP and TP cases.
    """
    differences = {}

    for col in feature_cols:
        if col not in fp_cases.columns or col not in tp_cases.columns:
            continue

        fp_vals = fp_cases[col].dropna()
        tp_vals = tp_cases[col].dropna()

        if len(fp_vals) == 0 or len(tp_vals) == 0:
            continue

        fp_mean = fp_vals.mean()
        tp_mean = tp_vals.mean()

        # Effect size: Cohen's d
        pooled_std = np.sqrt(((len(fp_vals) - 1) * fp_vals.std()**2 +
                              (len(tp_vals) - 1) * tp_vals.std()**2) /
                             (len(fp_vals) + len(tp_vals) - 2))

        cohen_d = (fp_mean - tp_mean) / pooled_std if pooled_std > 0 else 0

        differences[col] = {
            'fp_mean': float(fp_mean),
            'tp_mean': float(tp_mean),
            'fp_std': float(fp_vals.std()),
            'tp_std': float(tp_vals.std()),
            'cohen_d': float(cohen_d),
            'difference_pct': float((fp_mean - tp_mean) / tp_mean * 100) if tp_mean != 0 else 0,
            'fp_count': len(fp_vals),
            'tp_count': len(tp_vals)
        }

    # Sort by absolute Cohen's d
    sorted_diffs = sorted(differences.items(), key=lambda x: abs(x[1]['cohen_d']), reverse=True)

    return differences, sorted_diffs


def analyze_false_positives(df):
    """Main analysis: false positive root causes for all targets."""
    results = {}

    df_processed, feature_cols = prepare_features(df)

    for target_col, target_name in [
        ('is_rank_1', 'rank_1'),
        ('is_top_3', 'top_3'),
        ('is_top_5', 'top_5')
    ]:
        print(f"\n{'='*60}")
        print(f"Analyzing FALSE POSITIVES for {target_name.upper()}")
        print(f"{'='*60}")

        # Train model
        model, y_pred_proba, valid_mask = train_baseline_model(
            df_processed, feature_cols, target_col
        )

        if model is None:
            print(f"  Insufficient data for {target_name}")
            continue

        # Identify error cases
        fp_cases, tp_cases = identify_error_cases(
            df_processed, y_pred_proba, target_col, valid_mask, threshold=0.50
        )

        print(f"\nPrediction Summary (threshold=0.50):")
        print(f"  True Positives (TP): {len(tp_cases)}")
        print(f"  False Positives (FP): {len(fp_cases)}")
        if len(fp_cases) + len(tp_cases) > 0:
            print(f"  FP Rate: {len(fp_cases) / (len(fp_cases) + len(tp_cases)) * 100:.2f}%")
        else:
            print(f"  FP Rate: N/A (no predictions above threshold)")

        # Analyze feature differences
        differences, sorted_diffs = compute_feature_differences(
            fp_cases, tp_cases, feature_cols
        )

        fp_rate = 0.0
        if len(fp_cases) + len(tp_cases) > 0:
            fp_rate = float(len(fp_cases) / (len(fp_cases) + len(tp_cases)))

        results[target_name] = {
            'fp_count': int(len(fp_cases)),
            'tp_count': int(len(tp_cases)),
            'fp_rate': fp_rate,
            'feature_differences': differences,
            'top_difference_features': sorted_diffs[:10]
        }

        # Print top differences
        if sorted_diffs:
            print(f"\nTop 5 Differentiating Features (by Cohen's d):")
            for i, (col, diff) in enumerate(sorted_diffs[:5], 1):
                print(f"  {i}. {col}:")
                print(f"     FP mean: {diff['fp_mean']:.2f} ± {diff['fp_std']:.2f}")
                print(f"     TP mean: {diff['tp_mean']:.2f} ± {diff['tp_std']:.2f}")
                print(f"     Cohen's d: {diff['cohen_d']:.3f}")
                print(f"     Difference: {diff['difference_pct']:+.1f}%")
        else:
            print(f"\nNo FP/TP cases found for analysis")

    return results


def create_visualizations(results):
    """Create visualizations for false positive analysis."""
    targets = list(results.keys())

    if len(targets) == 0:
        print("  No results to visualize")
        return

    # 1. Feature difference comparison (top features across targets)
    fig1 = go.Figure()

    all_features = set()
    for target_data in results.values():
        for col in target_data['feature_differences'].keys():
            all_features.add(col)

    # Get top 10 features by max Cohen's d across targets
    feature_importance = {}
    for feature in all_features:
        max_d = 0
        for target_data in results.values():
            if feature in target_data['feature_differences']:
                max_d = max(max_d, abs(target_data['feature_differences'][feature]['cohen_d']))
        feature_importance[feature] = max_d

    top_features = sorted(feature_importance.items(), key=lambda x: x[1], reverse=True)[:10]
    top_feature_names = [f[0] for f in top_features]

    for target in targets:
        cohens_d = []
        for feature in top_feature_names:
            if feature in results[target]['feature_differences']:
                cohens_d.append(results[target]['feature_differences'][feature]['cohen_d'])
            else:
                cohens_d.append(0)

        fig1.add_trace(go.Bar(
            x=top_feature_names,
            y=cohens_d,
            name=target,
            hovertemplate='<b>%{x}</b><br>' + target + ' Cohen\'s d: %{y:.3f}<extra></extra>'
        ))

    fig1.update_layout(
        title='偽陽性根因分析 - Feature Differences (Cohen\'s d)',
        xaxis_title='Feature',
        yaxis_title='Cohen\'s d',
        barmode='group',
        height=500,
        hovermode='x unified'
    )

    fig1.write_html(RESULTS_DIR / 'fp_feature_differences.html')

    # 2. FP rate comparison
    fig2 = go.Figure()

    fp_rates = [results[t]['fp_rate'] * 100 for t in targets]
    fp_counts = [results[t]['fp_count'] for t in targets]

    fig2.add_trace(go.Bar(
        x=targets,
        y=fp_rates,
        text=fp_counts,
        textposition='outside',
        marker_color=['#EF553B', '#636EFA', '#00CC96'],
        hovertemplate='<b>%{x}</b><br>FP Rate: %{y:.2f}%<br>Count: %{text}<extra></extra>'
    ))

    fig2.update_layout(
        title='False Positive Rates by Target',
        xaxis_title='Target',
        yaxis_title='FP Rate (%)',
        height=400
    )

    fig2.write_html(RESULTS_DIR / 'fp_rates.html')

    print(f"\n Visualizations saved to {RESULTS_DIR}/")


def save_results(results):
    """Save detailed results to JSON."""
    output = {
        'analysis': '偽陽性根因分析',
        'description': 'False positive root cause analysis (threshold=0.50)',
        'results_by_target': {}
    }

    for target, data in results.items():
        top_diffs = [[f[0], {k: v for k, v in f[1].items() if k != 'cohen_d'}, f[1]['cohen_d']]
                     for f in data['top_difference_features']]

        output['results_by_target'][target] = {
            'fp_count': data['fp_count'],
            'tp_count': data['tp_count'],
            'fp_rate': data['fp_rate'],
            'top_difference_features': top_diffs
        }

    with open(RESULTS_DIR / 'phase8_06_false_positive_results.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n Results saved to {RESULTS_DIR}/phase8_06_false_positive_results.json")


def main():
    print("\n" + "="*70)
    print("Phase 8-6: 偽陽性根因分析 - False Positive Root Cause Analysis")
    print("="*70)

    # Load data
    print("\n[1/4] Loading data from database...")
    df = load_data(DB_PATH)
    print(f"  Loaded {len(df)} machine-day records")

    # Analyze
    print("\n[2/4] Analyzing false positive patterns...")
    results = analyze_false_positives(df)

    # Visualize
    print("\n[3/4] Creating visualizations...")
    create_visualizations(results)

    # Save
    print("\n[4/4] Saving results...")
    save_results(results)

    print("\n" + "="*70)
    print(" Phase 8-6 Complete!")
    print("="*70)


if __name__ == '__main__':
    main()
