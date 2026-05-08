# -*- coding: utf-8 -*-
"""
Phase 8-5: 機種別の投入パターン差 - Machine-Type Setting Pattern Analysis

Analyzes how setting patterns differ across machine types (model_type/machine categories).
For each machine type: computes rank concentration, identifies which machines have
higher/lower setting concentrations, and measures effect size of knowing machine type.

Q: Do certain machine types receive disproportionately more high-rank settings?
This reveals if the hall's setting strategy depends on machine type.
"""

import sqlite3
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
import plotly.graph_objects as go
import json

PROJECT_ROOT = Path("C:\\Users\\apto117\\Documents\\pachinko-analyzer\\src\\2026project")
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "db" / "experiments" / "マルハンメガシティ2000-蒲田7_rank_exp.db"
RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase8_machine_type_patterns"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def load_data(db_path):
    """Load machine daily data with machine type information."""
    conn = sqlite3.connect(db_path)

    df = pd.read_sql_query("""
        SELECT
            d.date,
            d.machine_name,
            d.machine_count,
            d.is_rank_1,
            d.is_top_3,
            d.is_top_5,
            m.jug_flag,
            m.hana_flag,
            m.oki_flag,
            m.bt_flag
        FROM daily_machine_type_summary d
        LEFT JOIN machine_master m ON d.machine_name = m.machine_name_normalized
        ORDER BY d.date, d.machine_name
    """, conn)

    conn.close()

    df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')

    # Categorize machine type based on flags
    def get_machine_type(row):
        if row['jug_flag']: return 'jug'
        if row['hana_flag']: return 'hana'
        if row['oki_flag']: return 'oki'
        if row['bt_flag']: return 'bt'
        return 'other'

    df['machine_type'] = df.apply(get_machine_type, axis=1)
    df = df.drop(['jug_flag', 'hana_flag', 'oki_flag', 'bt_flag'], axis=1)

    return df


def compute_machine_type_concentration(df, target_col):
    """
    Compute concentration for each machine type.

    Returns:
        dict: {machine_type: {concentration, sample_count, rank_count}}
    """
    results = {}

    for machine_type in df['machine_type'].dropna().unique():
        type_data = df[df['machine_type'] == machine_type]

        rank_count = type_data[target_col].sum()
        total_count = len(type_data)
        concentration = (rank_count / total_count * 100) if total_count > 0 else 0

        results[machine_type] = {
            'concentration': concentration,
            'rank_count': int(rank_count),
            'total_count': int(total_count)
        }

    return results


def compute_effect_size(df, target_col):
    """
    Compute effect size: how much does knowing machine_type help prediction?
    Uses AUC difference as effect size metric.
    """
    # Baseline: random model
    baseline_auc = 0.5

    # Model with machine_type: one-hot encode and use average concentration per type
    type_concentrations = compute_machine_type_concentration(df, target_col)

    # Map each row to its machine type's concentration as a predictor
    type_mapping = {}
    for mtype, data in type_concentrations.items():
        type_mapping[mtype] = data['concentration'] / 100.0  # normalize to 0-1

    df['type_prediction'] = df['machine_type'].map(type_mapping)

    # Filter out NaN values
    valid_mask = df['type_prediction'].notna()

    if valid_mask.sum() > 0:
        try:
            effect_auc = roc_auc_score(df[valid_mask][target_col], df[valid_mask]['type_prediction'])
            effect_size = effect_auc - baseline_auc
        except:
            effect_auc = None
            effect_size = None
    else:
        effect_auc = None
        effect_size = None

    return {
        'baseline_auc': baseline_auc,
        'effect_auc': effect_auc,
        'effect_size': effect_size
    }


def analyze_machine_type_patterns(df):
    """Main analysis: machine type patterns for all three targets."""
    results = {}

    for target_col, target_name in [
        ('is_rank_1', 'rank_1'),
        ('is_top_3', 'top_3'),
        ('is_top_5', 'top_5')
    ]:
        print(f"\n{'='*60}")
        print(f"Analyzing {target_name.upper()} concentration by machine type")
        print(f"{'='*60}")

        # Compute concentrations
        concentrations = compute_machine_type_concentration(df, target_col)

        # Compute effect size
        effect = compute_effect_size(df, target_col)

        # Sort by concentration
        sorted_types = sorted(concentrations.items(), key=lambda x: x[1]['concentration'], reverse=True)

        # Summary statistics
        concs = [c['concentration'] for c in concentrations.values()]

        results[target_name] = {
            'concentrations': concentrations,
            'effect_size': effect,
            'sorted_by_concentration': sorted_types,
            'statistics': {
                'mean_concentration': float(np.mean(concs)),
                'std_concentration': float(np.std(concs)),
                'min_concentration': float(np.min(concs)),
                'max_concentration': float(np.max(concs)),
                'concentration_range': float(np.max(concs) - np.min(concs))
            }
        }

        # Print summary
        print(f"\nConcentration Statistics:")
        print(f"  Mean: {results[target_name]['statistics']['mean_concentration']:.2f}%")
        print(f"  Std Dev: {results[target_name]['statistics']['std_concentration']:.2f}%")
        print(f"  Min: {results[target_name]['statistics']['min_concentration']:.2f}%")
        print(f"  Max: {results[target_name]['statistics']['max_concentration']:.2f}%")
        print(f"  Range: {results[target_name]['statistics']['concentration_range']:.2f}%")

        print(f"\nEffect Size (knowing machine type):")
        if effect['effect_auc'] is not None:
            print(f"  Baseline AUC: {effect['baseline_auc']:.4f}")
            print(f"  Type-based AUC: {effect['effect_auc']:.4f}")
            print(f"  Effect Size: {effect['effect_size']:.4f}")
        else:
            print(f"  Could not compute effect size")

        print(f"\nTop 5 Machine Types by Concentration:")
        for i, (mtype, data) in enumerate(sorted_types[:5], 1):
            pct_above_mean = ((data['concentration'] - results[target_name]['statistics']['mean_concentration']) /
                             results[target_name]['statistics']['mean_concentration'] * 100)
            print(f"  {i}. {mtype}: {data['concentration']:.2f}% "
                  f"({data['rank_count']}/{data['total_count']} samples, "
                  f"+{pct_above_mean:.1f}% above mean)")

    return results


def create_visualizations(df, results):
    """Create visualizations for machine type patterns."""
    targets = ['rank_1', 'top_3', 'top_5']
    colors = ['#EF553B', '#636EFA', '#00CC96']

    # 1. Bar chart: concentration by machine type (all targets)
    fig1 = go.Figure()

    for target, color in zip(targets, colors):
        sorted_types = results[target]['sorted_by_concentration']
        machine_types = [t[0] for t in sorted_types]
        concentrations = [t[1]['concentration'] for t in sorted_types]

        fig1.add_trace(go.Bar(
            x=machine_types,
            y=concentrations,
            name=target,
            marker_color=color,
            hovertemplate='<b>%{x}</b><br>' + target + ': %{y:.2f}%<extra></extra>'
        ))

    fig1.update_layout(
        title='機種別の投入パターン差 - Concentration by Machine Type',
        xaxis_title='Machine Type',
        yaxis_title='Concentration (%)',
        barmode='group',
        height=500,
        hovermode='x unified'
    )

    fig1.write_html(RESULTS_DIR / 'machine_type_concentration_bars.html')

    # 2. Comparison chart: target-specific patterns
    fig2 = go.Figure()

    all_types = set()
    for target in targets:
        for mtype in results[target]['concentrations'].keys():
            all_types.add(mtype)

    all_types = sorted(list(all_types))

    for target, color in zip(targets, colors):
        concentrations = [results[target]['concentrations'].get(t, {}).get('concentration', 0)
                         for t in all_types]

        fig2.add_trace(go.Scatter(
            x=all_types,
            y=concentrations,
            name=target,
            mode='lines+markers',
            line=dict(color=color, width=2),
            marker=dict(size=8),
            hovertemplate='<b>%{x}</b><br>' + target + ': %{y:.2f}%<extra></extra>'
        ))

    fig2.update_layout(
        title='機種別パターン比較 - Machine Type Pattern Comparison',
        xaxis_title='Machine Type',
        yaxis_title='Concentration (%)',
        height=500,
        hovermode='x unified'
    )

    fig2.write_html(RESULTS_DIR / 'machine_type_pattern_comparison.html')

    print(f"\n Visualizations saved to {RESULTS_DIR}/")


def save_results(results):
    """Save detailed results to JSON."""
    output = {
        'analysis': '機種別の投入パターン差',
        'description': 'Machine type setting pattern analysis',
        'results_by_target': {}
    }

    for target, data in results.items():
        # Convert sorted_by_concentration to JSON-serializable format
        sorted_by_conc = [[t[0], t[1]['concentration'], t[1]['rank_count'], t[1]['total_count']]
                          for t in data['sorted_by_concentration']]

        output['results_by_target'][target] = {
            'concentrations': {k: v for k, v in data['concentrations'].items()},
            'sorted_by_concentration': sorted_by_conc,
            'effect_size': {
                'baseline_auc': float(data['effect_size']['baseline_auc']),
                'effect_auc': float(data['effect_size']['effect_auc']) if data['effect_size']['effect_auc'] else None,
                'effect_size': float(data['effect_size']['effect_size']) if data['effect_size']['effect_size'] else None
            },
            'statistics': data['statistics']
        }

    with open(RESULTS_DIR / 'phase8_05_machine_type_results.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n Results saved to {RESULTS_DIR}/phase8_05_machine_type_results.json")


def main():
    print("\n" + "="*70)
    print("Phase 8-5: 機種別の投入パターン差 - Machine-Type Setting Pattern Analysis")
    print("="*70)

    # Load data
    print("\n[1/4] Loading data from database...")
    df = load_data(DB_PATH)
    print(f"  Loaded {len(df)} machine-day records")
    print(f"  Machine types found: {df['machine_type'].nunique()}")

    # Analyze
    print("\n[2/4] Analyzing machine type patterns...")
    results = analyze_machine_type_patterns(df)

    # Visualize
    print("\n[3/4] Creating visualizations...")
    create_visualizations(df, results)

    # Save
    print("\n[4/4] Saving results...")
    save_results(results)

    print("\n" + "="*70)
    print(" Phase 8-5 Complete!")
    print("="*70)
    print("\nKey Insights:")
    for target in ['rank_1', 'top_3', 'top_5']:
        effect = results[target]['effect_size']
        if effect['effect_auc'] is not None:
            print(f"\n{target}:")
            print(f"  Effect Size: {effect['effect_size']:.4f}")
            print(f"  Range: {results[target]['statistics']['concentration_range']:.2f}%")
            top_type = results[target]['sorted_by_concentration'][0]
            print(f"  Top machine type: {top_type[0]} ({top_type[1]['concentration']:.2f}%)")


if __name__ == '__main__':
    main()
