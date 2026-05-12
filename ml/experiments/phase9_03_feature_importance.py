# -*- coding: utf-8 -*-
"""
Phase 9-3: Feature Importance Analysis - Understanding Machine-Type Integration

Purpose: Diagnose why machine-type features didn't improve AUC as expected.
Analyze feature importance in the enhanced (20D) model to determine:
- Do machine-type features rank in top feature importance?
- Which baseline features are most critical?
- Are there feature interactions or redundancy?

Output:
- feature_importance.json: XGBoost gain/frequency for each feature
- feature_importance_comparison.html: Visualization of feature importance
- permutation_importance.json: Impact of shuffling each feature on AUC
- diagnostic_report.md: Analysis of unexpected results
"""

import sqlite3
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import roc_auc_score, average_precision_score
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json

PROJECT_ROOT = Path("C:\\Users\\apto117\\Documents\\pachinko-analyzer\\src\\2026project")
sys.path.insert(0, str(PROJECT_ROOT))

RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase9_machine_type_enhanced"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

FEATURES_CSV = RESULTS_DIR / "enhanced_features_20d.csv"


def load_enhanced_features(csv_path):
    """Load enhanced features from Phase 9-1 output."""
    df = pd.read_csv(csv_path)

    X_20d = df.iloc[:, :20].values.astype(np.float32)
    dates = pd.to_datetime(df['date']).values
    y_rank1 = df['is_rank_1'].values.astype(int)
    y_top3 = df['is_top_3'].values.astype(int)
    y_top5 = df['is_top_5'].values.astype(int)

    return X_20d, dates, y_rank1, y_top3, y_top5


def get_feature_names():
    """Return feature names for interpretation."""
    baseline_features = [
        'month_progress',
        'days_since_rank_1',
        'avg_diff_7d', 'avg_diff_14d', 'avg_diff_21d', 'avg_diff_28d', 'avg_diff_35d',
        'avg_games_7d', 'avg_games_14d', 'avg_games_21d', 'avg_games_28d', 'avg_games_35d',
        'avg_efficiency_7d', 'avg_efficiency_14d', 'avg_efficiency_28d',
        'machine_count'
    ]

    machine_type_features = [
        'machine_type_hana',
        'machine_type_oki',
        'machine_type_bt',
        'machine_type_other'
    ]

    return baseline_features + machine_type_features


def train_and_extract_importance(X, y, dates, feature_names, target_name):
    """Train XGBoost and extract feature importance metrics."""
    # Time-series split: train on first N-57 dates, test on last 57 dates
    unique_dates = pd.Series(dates).unique()
    split_date_idx = len(unique_dates) - 57
    split_date = unique_dates[split_date_idx]

    train_mask = dates < split_date
    test_mask = dates >= split_date

    X_train = X[train_mask]
    X_test = X[test_mask]
    y_train = y[train_mask]
    y_test = y[test_mask]

    # Train model
    model = xgb.XGBClassifier(
        objective='binary:logistic',
        max_depth=3,
        learning_rate=0.01,
        n_estimators=200,
        random_state=42,
        eval_metric='logloss',
        verbosity=0
    )
    model.fit(X_train, y_train, verbose=False)

    # Get XGBoost built-in importance
    importance_gain = model.get_booster().get_score(importance_type='gain')
    importance_cover = model.get_booster().get_score(importance_type='cover')
    importance_weight = model.get_booster().get_score(importance_type='weight')

    # Normalize importance scores
    def normalize_importance(imp_dict, feature_names):
        """Convert feature importance dict to array normalized."""
        imp_array = np.array([imp_dict.get(f'f{i}', 0.0) for i in range(len(feature_names))])
        if imp_array.sum() > 0:
            imp_array = imp_array / imp_array.sum()
        return imp_array

    gain_normalized = normalize_importance(importance_gain, feature_names)
    cover_normalized = normalize_importance(importance_cover, feature_names)
    weight_normalized = normalize_importance(importance_weight, feature_names)

    # Compute baseline metrics
    y_pred_proba = model.predict_proba(X_test)[:, 1]
    test_auc = float(roc_auc_score(y_test, y_pred_proba))
    test_ap = float(average_precision_score(y_test, y_pred_proba))

    # Permutation importance
    baseline_auc = test_auc
    permutation_impacts = {}

    for i, fname in enumerate(feature_names):
        X_test_shuffled = X_test.copy()
        np.random.seed(42)
        np.random.shuffle(X_test_shuffled[:, i])

        y_pred_shuffled = model.predict_proba(X_test_shuffled)[:, 1]
        shuffled_auc = float(roc_auc_score(y_test, y_pred_shuffled))
        auc_drop = baseline_auc - shuffled_auc

        permutation_impacts[fname] = {
            'auc_drop': auc_drop,
            'auc_drop_pct': float(auc_drop / baseline_auc * 100) if baseline_auc > 0 else 0.0
        }

    # Sort permutation importance by impact
    sorted_perm = sorted(permutation_impacts.items(), key=lambda x: abs(x[1]['auc_drop']), reverse=True)

    return {
        'model': model,
        'test_auc': test_auc,
        'test_ap': test_ap,
        'importance_gain': gain_normalized,
        'importance_cover': cover_normalized,
        'importance_weight': weight_normalized,
        'permutation_impacts': permutation_impacts,
        'sorted_permutation': sorted_perm,
        'y_test': y_test,
        'y_pred_proba': y_pred_proba
    }


def analyze_machine_type_importance(results, feature_names):
    """Analyze if machine-type features are important."""
    machine_type_indices = [16, 17, 18, 19]
    machine_type_names = ['machine_type_hana', 'machine_type_oki', 'machine_type_bt', 'machine_type_other']

    analysis = {}

    for target, data in results.items():
        gain = data['importance_gain']
        cover = data['importance_cover']
        weight = data['importance_weight']

        # Sum machine-type importance
        mt_gain = gain[machine_type_indices].sum()
        mt_cover = cover[machine_type_indices].sum()
        mt_weight = weight[machine_type_indices].sum()

        # Rank of each machine-type feature
        gain_ranks = np.argsort(-gain)
        mt_gain_ranks = {fname: int(np.where(gain_ranks == idx)[0][0]) + 1
                        for fname, idx in zip(machine_type_names, machine_type_indices)}

        analysis[target] = {
            'total_importance_gain': float(mt_gain),
            'total_importance_cover': float(mt_cover),
            'total_importance_weight': float(mt_weight),
            'feature_ranks': mt_gain_ranks,
            'top_5_features': [(feature_names[idx], float(gain[idx]))
                              for idx in gain_ranks[:5]],
            'top_5_permutation': [(name, data['permutation_impacts'][name]['auc_drop_pct'])
                                 for name, _ in data['sorted_permutation'][:5]]
        }

    return analysis


def create_visualizations(results, feature_names):
    """Create visualizations of feature importance."""
    targets = list(results.keys())
    machine_type_indices = [16, 17, 18, 19]

    # Figure 1: Gain importance comparison across targets
    fig1 = go.Figure()

    for target in targets:
        gain = results[target]['importance_gain']
        fig1.add_trace(go.Bar(
            x=feature_names,
            y=gain,
            name=target,
            hovertemplate='<b>%{x}</b><br>' + target + ' gain: %{y:.4f}<extra></extra>'
        ))

    fig1.update_layout(
        title='Feature Importance (XGBoost Gain) - 20D Enhanced Model',
        xaxis_title='Feature',
        yaxis_title='Normalized Gain',
        barmode='group',
        height=500,
        xaxis={'tickangle': -45}
    )

    fig1.write_html(RESULTS_DIR / 'feature_importance_gain.html')

    # Figure 2: Machine-type feature ranking
    fig2 = make_subplots(
        rows=1, cols=3,
        subplot_titles=['rank_1', 'top_3', 'top_5'],
        specs=[[{'type': 'bar'}, {'type': 'bar'}, {'type': 'bar'}]]
    )

    colors_map = {
        'machine_type_hana': '#EF553B',
        'machine_type_oki': '#636EFA',
        'machine_type_bt': '#00CC96',
        'machine_type_other': '#AB63FA'
    }

    for col, target in enumerate(targets, 1):
        gain = results[target]['importance_gain']
        mt_names = ['hana', 'oki', 'bt', 'other']
        mt_gains = [gain[idx] for idx in machine_type_indices]
        mt_colors = [colors_map[f'machine_type_{name}'] for name in mt_names]

        fig2.add_trace(go.Bar(
            x=mt_names,
            y=mt_gains,
            marker_color=mt_colors,
            hovertemplate='<b>%{x}</b><br>Gain: %{y:.4f}<extra></extra>',
            showlegend=False
        ), row=1, col=col)

    fig2.update_layout(
        title='Machine-Type Feature Importance (Gain) by Target',
        height=400
    )

    fig2.write_html(RESULTS_DIR / 'machine_type_importance.html')

    # Figure 3: Permutation importance top 10
    fig3 = make_subplots(
        rows=1, cols=3,
        subplot_titles=['rank_1', 'top_3', 'top_5'],
        specs=[[{'type': 'bar'}, {'type': 'bar'}, {'type': 'bar'}]]
    )

    for col, target in enumerate(targets, 1):
        top_perm = results[target]['sorted_permutation'][:10]
        names = [name for name, _ in top_perm]
        drops = [data['auc_drop_pct'] for _, data in top_perm]

        fig3.add_trace(go.Bar(
            y=names,
            x=drops,
            orientation='h',
            hovertemplate='<b>%{y}</b><br>AUC drop: %{x:.3f}%<extra></extra>',
            showlegend=False
        ), row=1, col=col)

    fig3.update_xaxes(title_text='AUC Drop (%)')
    fig3.update_layout(
        title='Top 10 Features by Permutation Importance (AUC Drop %)',
        height=500
    )

    fig3.write_html(RESULTS_DIR / 'permutation_importance.html')

    print(f"\n Visualizations saved to {RESULTS_DIR}/")


def save_results(results, feature_names, analysis):
    """Save detailed results to JSON."""
    output = {
        'analysis': 'Feature Importance Analysis',
        'description': '20D enhanced model feature importance diagnosis',
        'results_by_target': {}
    }

    for target, data in results.items():
        output['results_by_target'][target] = {
            'test_auc': data['test_auc'],
            'test_ap': data['test_ap'],
            'feature_importance_gain': {fname: float(val) for fname, val in zip(feature_names, data['importance_gain'])},
            'feature_importance_cover': {fname: float(val) for fname, val in zip(feature_names, data['importance_cover'])},
            'feature_importance_weight': {fname: float(val) for fname, val in zip(feature_names, data['importance_weight'])},
            'permutation_importance': {fname: data['permutation_impacts'][fname]
                                      for fname in feature_names},
            'top_10_permutation_features': [[name, data['permutation_impacts'][name]['auc_drop_pct']]
                                           for name, _ in data['sorted_permutation'][:10]]
        }

    with open(RESULTS_DIR / 'feature_importance.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"[OK] Feature importance saved to {RESULTS_DIR}/feature_importance.json")


def generate_diagnostic_report(analysis):
    """Generate markdown diagnostic report."""
    report_lines = [
        "# Phase 9-3: Feature Importance Diagnostic Report\n",
        "\n",
        "## Summary\n",
        "\n",
        "Phase 9-2 showed that machine-type features provided minimal AUC improvement:\n",
        "- rank_1: +0.0042 (+0.61%) — only 6.5% of Phase 8-5's +0.0664 effect\n",
        "- top_3: -0.0015 (-0.22%) — regression\n",
        "- top_5: +0.0003 (+0.04%) — negligible\n",
        "\n",
        "This diagnostic analyzes feature importance to understand why.\n",
        "\n",
    ]

    for target in ['rank_1', 'top_3', 'top_5']:
        target_analysis = analysis[target]

        report_lines.append(f"## {target.upper()}\n\n")

        report_lines.append(f"**Machine-Type Total Importance (Gain):** {target_analysis['total_importance_gain']:.6f}\n\n")

        report_lines.append("**Machine-Type Feature Ranks (by Gain):**\n")
        for fname, rank in target_analysis['feature_ranks'].items():
            report_lines.append(f"  - {fname}: rank {rank}/20\n")

        report_lines.append("\n**Top 5 Features (by Gain):**\n")
        for i, (fname, gain) in enumerate(target_analysis['top_5_features'], 1):
            report_lines.append(f"  {i}. {fname}: {gain:.6f}\n")

        report_lines.append("\n**Top 5 Features (by Permutation AUC Drop):**\n")
        for i, (fname, drop_pct) in enumerate(target_analysis['top_5_permutation'], 1):
            report_lines.append(f"  {i}. {fname}: {drop_pct:.3f}% AUC drop\n")

        report_lines.append("\n")

    report_lines.extend([
        "## Interpretation\n",
        "\n",
        "### Hypothesis 1: Multicollinearity\n",
        "If machine-type features rank outside top 5 overall, their signal is likely already captured by baseline features.\n",
        "This suggests rolling averages (avg_diff, avg_games, avg_efficiency) implicitly encode machine-type patterns.\n",
        "\n",
        "### Hypothesis 2: Suboptimal Encoding\n",
        "One-hot encoding with 83.7% 'other' dominance might dilute signal. Alternative encodings (target encoding, embedding) could be explored.\n",
        "\n",
        "### Hypothesis 3: Feature Interactions\n",
        "Machine-type might only improve predictions through interactions (e.g., machine_type X days_since_rank1).\n",
        "This would require explicit interaction features.\n",
        "\n",
        "### Next Steps\n",
        "1. **If machine-type ranks low**: Conclude multicollinearity; skip machine-type and optimize baseline features instead\n",
        "2. **If machine-type ranks high but AUC still low**: Explore interaction features and target encoding\n",
        "3. **If XGBoost importance vs permutation differ significantly**: Investigate feature interactions\n",
        "\n",
    ])

    report_file = RESULTS_DIR / "phase9_03_diagnostic_report.md"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.writelines(report_lines)

    print(f"[OK] Diagnostic report saved to {report_file}")


def main():
    print("\n" + "="*70)
    print("Phase 9-3: Feature Importance Analysis")
    print("="*70)

    # Load features
    print("\n[1/4] Loading enhanced features...")
    if not FEATURES_CSV.exists():
        print(f"ERROR: Features file not found: {FEATURES_CSV}")
        print("Please run Phase 9-1 first.")
        return

    X_20d, dates, y_rank1, y_top3, y_top5 = load_enhanced_features(FEATURES_CSV)
    print(f"  Loaded {len(X_20d)} samples")

    feature_names = get_feature_names()

    # Train models and extract importance
    print("\n[2/4] Training models and extracting feature importance...")
    results = {}

    for target_col, target_name, y_data in [
        ('rank_1', 'rank_1', y_rank1),
        ('top_3', 'top_3', y_top3),
        ('top_5', 'top_5', y_top5)
    ]:
        print(f"\n  [{target_name.upper()}]")
        result = train_and_extract_importance(X_20d, y_data, dates, feature_names, target_name)
        results[target_name] = result
        print(f"    Test AUC: {result['test_auc']:.4f}")
        print(f"    Test AP:  {result['test_ap']:.4f}")

    # Analyze machine-type importance
    print("\n[3/4] Analyzing machine-type feature importance...")
    analysis = analyze_machine_type_importance(results, feature_names)

    for target, analysis_data in analysis.items():
        print(f"\n  [{target.upper()}]")
        print(f"    Machine-type total gain: {analysis_data['total_importance_gain']:.6f}")
        print(f"    Feature ranks: {analysis_data['feature_ranks']}")

    # Visualize
    print("\n[4/4] Creating visualizations...")
    create_visualizations(results, feature_names)

    # Save results
    save_results(results, feature_names, analysis)
    generate_diagnostic_report(analysis)

    print("\n" + "="*70)
    print("Phase 9-3 Complete!")
    print("="*70)


if __name__ == '__main__':
    main()
