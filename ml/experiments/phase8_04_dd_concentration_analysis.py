# -*- coding: utf-8 -*-
"""
Phase 8-4: DD・域･莉假ｼ蛾寔荳ｭ蠎ｦ蛻・梵 - Day-of-Month Concentration Analysis

Analyzes if high-rank settings cluster on specific days-of-month (1-31).
For each day: computes rank_1/top_3/top_5 concentration (% of high ranks),
performs chi-squared significance test, and visualizes patterns.

Q: Do certain days of the month have higher concentration of high-rank settings?
This reveals if the hall uses consistent temporal setting strategies.
"""

import sqlite3
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json

PROJECT_ROOT = Path("C:\\Users\\apto117\\Documents\\pachinko-analyzer\\src\\2026project")
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "db" / "experiments" / "マルハンメガシティ2000-蒲田7_rank_exp.db"
RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase8_dd_concentration"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def load_data(db_path):
    """Load machine daily data with targets."""
    conn = sqlite3.connect(db_path)

    df = pd.read_sql_query("""
        SELECT
            date,
            machine_name,
            machine_count,
            is_rank_1,
            is_top_3,
            is_top_5
        FROM daily_machine_type_summary
        ORDER BY date, machine_name
    """, conn)

    conn.close()

    df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
    df['day_of_month'] = df['date'].dt.day

    return df


def compute_daily_concentration(df, target_col):
    """
    Compute concentration (% of high ranks) for each day of month.

    Args:
        df: DataFrame with 'day_of_month' and target_col
        target_col: Column name (is_rank_1, is_top_3, is_top_5)

    Returns:
        dict: {day_of_month: concentration_pct}
    """
    concentrations = {}

    for day in range(1, 32):
        day_data = df[df['day_of_month'] == day]

        if len(day_data) == 0:
            concentrations[day] = None
            continue

        concentration = (day_data[target_col].sum() / len(day_data)) * 100
        concentrations[day] = concentration

    return concentrations


def perform_chi_squared_test(df, target_col):
    """
    Perform chi-squared test: are ranks uniformly distributed across days?

    H0: rank distribution is uniform across days of month
    H1: rank distribution differs across days
    """
    contingency_table = []
    days_list = []

    for day in range(1, 32):
        day_data = df[df['day_of_month'] == day]
        if len(day_data) == 0:
            continue

        rank_count = day_data[target_col].sum()
        non_rank_count = len(day_data) - rank_count

        contingency_table.append([rank_count, non_rank_count])
        days_list.append(day)

    contingency_array = np.array(contingency_table)
    chi2, p_value, dof, expected = chi2_contingency(contingency_array)

    return {
        'chi2_statistic': chi2,
        'p_value': p_value,
        'degrees_of_freedom': dof,
        'is_significant': p_value < 0.05
    }


def identify_peak_days(concentrations, target_col_name, percentile=75):
    """Identify days with above-percentile concentration."""
    values = [v for v in concentrations.values() if v is not None]
    threshold = np.percentile(values, percentile)

    peak_days = []
    for day, conc in concentrations.items():
        if conc is not None and conc >= threshold:
            peak_days.append((day, conc))

    peak_days.sort(key=lambda x: x[1], reverse=True)
    return peak_days


def analyze_dd_concentration(df):
    """Main analysis: DD concentration for all three targets."""
    results = {}

    for target_col, target_name in [
        ('is_rank_1', 'rank_1'),
        ('is_top_3', 'top_3'),
        ('is_top_5', 'top_5')
    ]:
        print(f"\n{'='*60}")
        print(f"Analyzing {target_name.upper()} concentration by day-of-month")
        print(f"{'='*60}")

        # Compute concentrations
        concentrations = compute_daily_concentration(df, target_col)

        # Chi-squared test
        chi2_result = perform_chi_squared_test(df, target_col)

        # Peak days
        peak_days = identify_peak_days(concentrations, target_name)

        # Summary statistics
        valid_concs = [c for c in concentrations.values() if c is not None]

        results[target_name] = {
            'concentrations': concentrations,
            'chi2_test': chi2_result,
            'peak_days': peak_days,
            'statistics': {
                'mean_concentration': float(np.mean(valid_concs)),
                'std_concentration': float(np.std(valid_concs)),
                'min_concentration': float(np.min(valid_concs)),
                'max_concentration': float(np.max(valid_concs)),
                'concentration_range': float(np.max(valid_concs) - np.min(valid_concs))
            }
        }

        # Print summary
        print(f"\nConcentration Statistics:")
        print(f"  Mean: {results[target_name]['statistics']['mean_concentration']:.2f}%")
        print(f"  Std Dev: {results[target_name]['statistics']['std_concentration']:.2f}%")
        print(f"  Min: {results[target_name]['statistics']['min_concentration']:.2f}%")
        print(f"  Max: {results[target_name]['statistics']['max_concentration']:.2f}%")
        print(f"  Range: {results[target_name]['statistics']['concentration_range']:.2f}%")

        print(f"\nChi-Squared Test:")
        print(f"  Chi2 = {chi2_result['chi2_statistic']:.4f}")
        print(f"  p-value = {chi2_result['p_value']:.6f}")
        print(f"  Significant (p<0.05): {chi2_result['is_significant']}")

        if peak_days:
            print(f"\nTop 5 Peak Days (>75th percentile):")
            for day, conc in peak_days[:5]:
                pct_above_mean = ((conc - results[target_name]['statistics']['mean_concentration']) /
                                 results[target_name]['statistics']['mean_concentration'] * 100)
                print(f"  Day {day:2d}: {conc:.2f}% (+{pct_above_mean:.1f}% above mean)")

    return results


def create_visualizations(df, results):
    """Create visualizations for DD concentration."""
    targets = ['rank_1', 'top_3', 'top_5']
    colors = ['#EF553B', '#636EFA', '#00CC96']

    # 1. Bar chart: concentration by day
    fig1 = make_subplots(
        rows=3, cols=1,
        subplot_titles=('Rank 1 Concentration by Day',
                       'Top 3 Concentration by Day',
                       'Top 5 Concentration by Day'),
        vertical_spacing=0.12
    )

    for idx, (target, color) in enumerate(zip(targets, colors), 1):
        concentrations = results[target]['concentrations']
        days = list(range(1, 32))
        concs = [concentrations[d] if concentrations[d] is not None else 0 for d in days]

        mean_conc = results[target]['statistics']['mean_concentration']

        fig1.add_trace(
            go.Bar(
                x=days,
                y=concs,
                name=target,
                marker_color=color,
                hovertemplate='<b>Day %{x}</b><br>Concentration: %{y:.2f}%<extra></extra>'
            ),
            row=idx, col=1
        )

        # Add mean line
        fig1.add_hline(
            y=mean_conc,
            line_dash='dash',
            line_color=color,
            annotation_text=f'Mean: {mean_conc:.2f}%',
            annotation_position='right',
            row=idx, col=1
        )

    fig1.update_xaxes(title_text='Day of Month', row=3, col=1)
    fig1.update_yaxes(title_text='Concentration (%)', row=1, col=1)
    fig1.update_yaxes(title_text='Concentration (%)', row=2, col=1)
    fig1.update_yaxes(title_text='Concentration (%)', row=3, col=1)
    fig1.update_layout(height=1000, showlegend=False, title_text='DD・域･莉假ｼ蛾寔荳ｭ蠎ｦ蛻・梵 - Day-of-Month Concentration')

    fig1.write_html(RESULTS_DIR / 'dd_concentration_bars.html')

    # 2. Heatmap-style visualization: show which days have high concentration
    fig2 = go.Figure()

    concentration_matrix = []
    for target in targets:
        concentrations = results[target]['concentrations']
        concs = [concentrations[d] if concentrations[d] is not None else 0 for d in range(1, 32)]
        concentration_matrix.append(concs)

    fig2.add_trace(go.Heatmap(
        z=concentration_matrix,
        x=list(range(1, 32)),
        y=targets,
        colorscale='RdYlGn',
        text=[[f'{concentration_matrix[i][j]:.1f}%' for j in range(31)] for i in range(3)],
        texttemplate='%{text}',
        textfont={"size": 10},
        colorbar=dict(title='Concentration %')
    ))

    fig2.update_layout(
        title='DD・域･莉假ｼ蛾寔荳ｭ蠎ｦ繝偵・繝医・繝・・- Concentration Heatmap',
        xaxis_title='Day of Month',
        yaxis_title='Rank Target',
        height=400
    )

    fig2.write_html(RESULTS_DIR / 'dd_concentration_heatmap.html')

    print(f"\n Visualizations saved to {RESULTS_DIR}/")


def save_results(results):
    """Save detailed results to JSON."""
    output = {
        'analysis': 'DD・域･莉假ｼ蛾寔荳ｭ蠎ｦ蛻・梵',
        'description': 'Day-of-month concentration analysis of high-rank settings',
        'results_by_target': {}
    }

    for target, data in results.items():
        output['results_by_target'][target] = {
            'concentrations': {str(k): v for k, v in data['concentrations'].items()},
            'chi2_test': {
                'chi2_statistic': float(data['chi2_test']['chi2_statistic']),
                'p_value': float(data['chi2_test']['p_value']),
                'is_significant': bool(data['chi2_test']['is_significant'])
            },
            'peak_days': [[int(d), float(c)] for d, c in data['peak_days'][:5]],
            'statistics': data['statistics']
        }

    with open(RESULTS_DIR / 'phase8_04_dd_concentration_results.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n Results saved to {RESULTS_DIR}/phase8_04_dd_concentration_results.json")


def main():
    print("\n" + "="*70)
    print("Phase 8-4: DD・域･莉假ｼ蛾寔荳ｭ蠎ｦ蛻・梵 - Day-of-Month Concentration Analysis")
    print("="*70)

    # Load data
    print("\n[1/4] Loading data from database...")
    df = load_data(DB_PATH)
    print(f"  Loaded {len(df)} machine-day records")
    print(f"  Date range: {df['date'].min().date()} to {df['date'].max().date()}")

    # Analyze
    print("\n[2/4] Analyzing DD concentration...")
    results = analyze_dd_concentration(df)

    # Visualize
    print("\n[3/4] Creating visualizations...")
    create_visualizations(df, results)

    # Save
    print("\n[4/4] Saving results...")
    save_results(results)

    print("\n" + "="*70)
    print("Phase 8-4 Complete!")
    print("="*70)
    print("\nKey Insights:")
    for target in ['rank_1', 'top_3', 'top_5']:
        chi2 = results[target]['chi2_test']
        status = "SIGNIFICANT" if chi2['is_significant'] else "Not significant"
        print(f"\n{target}:")
        print(f"  {status} (p={chi2['p_value']:.6f})")
        if results[target]['peak_days']:
            day, conc = results[target]['peak_days'][0]
            mean = results[target]['statistics']['mean_concentration']
            print(f"  Peak: Day {day} ({conc:.2f}%, +{((conc-mean)/mean*100):.1f}% above mean)")


if __name__ == '__main__':
    main()
