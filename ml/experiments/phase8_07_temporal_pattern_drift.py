# -*- coding: utf-8 -*-
"""
Phase 8-7: 譎らｳｻ蛻縺ｮ謚募・繝代ち繝ｼ繝ｳ螟牙喧 - Temporal Pattern Drift Analysis

Detects temporal drift in setting patterns (seasonal/monthly changes).
Splits data by week, computes rank concentration per period, detects
drift periods, and analyzes pattern consistency over time.

Q: Do setting patterns drift over time? Are there seasonal or event-driven changes?
This reveals if the hall's setting strategy is static or dynamic/responsive.
"""

import sqlite3
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.spatial.distance import cosine
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json

PROJECT_ROOT = Path("C:\\Users\\apto117\\Documents\\pachinko-analyzer\\src\\2026project")
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "db" / "experiments" / "マルハンメガシティ2000-蒲田7_rank_exp.db"
RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase8_temporal_patterns"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def load_data(db_path):
    """Load machine daily data with time information."""
    conn = sqlite3.connect(db_path)

    df = pd.read_sql_query("""
        SELECT
            date,
            machine_name,
            is_rank_1,
            is_top_3,
            is_top_5
        FROM daily_machine_type_summary
        ORDER BY date, machine_name
    """, conn)

    conn.close()

    df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
    df['week'] = df['date'].dt.isocalendar().week
    df['month'] = df['date'].dt.to_period('M')
    df['year_week'] = df['date'].dt.to_period('W')

    return df


def compute_period_concentration(df, target_col, period_col):
    """
    Compute concentration for each time period.

    Returns:
        dict: {period: {concentration, sample_count, rank_count}}
    """
    results = {}

    for period in sorted(df[period_col].unique()):
        period_data = df[df[period_col] == period]

        rank_count = period_data[target_col].sum()
        total_count = len(period_data)
        concentration = (rank_count / total_count * 100) if total_count > 0 else 0

        results[str(period)] = {
            'concentration': concentration,
            'rank_count': int(rank_count),
            'total_count': int(total_count)
        }

    return results


def detect_drift_periods(concentrations, std_threshold=2.0):
    """
    Detect periods with significant drift (> std_threshold * std deviations from mean).
    """
    values = [c['concentration'] for c in concentrations.values()]
    mean = np.mean(values)
    std = np.std(values)

    drift_periods = []
    for period, data in concentrations.items():
        z_score = abs((data['concentration'] - mean) / std) if std > 0 else 0

        if z_score > std_threshold:
            drift_periods.append({
                'period': period,
                'concentration': data['concentration'],
                'z_score': z_score,
                'deviation': data['concentration'] - mean
            })

    drift_periods.sort(key=lambda x: x['z_score'], reverse=True)
    return drift_periods


def compute_pattern_correlation(concentrations_dict):
    """
    Compute correlation of setting patterns between consecutive periods.
    Returns list of correlations: how similar are adjacent periods?
    """
    periods = sorted(list(concentrations_dict.keys()))
    correlations = []

    for i in range(len(periods) - 1):
        period1 = periods[i]
        period2 = periods[i + 1]

        # Use concentration as a pattern vector (currently 1D, but extensible)
        c1 = concentrations_dict[period1]['concentration']
        c2 = concentrations_dict[period2]['concentration']

        # Cosine similarity between consecutive values
        # Normalize to 0-1 range
        if c1 > 0 and c2 > 0:
            similarity = 1 - abs(c1 - c2) / max(c1, c2)
        else:
            similarity = 0

        correlations.append({
            'period1': period1,
            'period2': period2,
            'similarity': similarity,
            'change_pct': ((c2 - c1) / c1 * 100) if c1 > 0 else 0
        })

    return correlations


def analyze_temporal_patterns(df):
    """Main analysis: temporal patterns by week and month."""
    results = {}

    for target_col, target_name in [
        ('is_rank_1', 'rank_1'),
        ('is_top_3', 'top_3'),
        ('is_top_5', 'top_5')
    ]:
        print(f"\n{'='*60}")
        print(f"Analyzing {target_name.upper()} temporal patterns")
        print(f"{'='*60}")

        # Weekly analysis
        weekly_conc = compute_period_concentration(df, target_col, 'year_week')
        weekly_drift = detect_drift_periods(weekly_conc)
        weekly_corr = compute_pattern_correlation(weekly_conc)

        # Monthly analysis
        monthly_conc = compute_period_concentration(df, target_col, 'month')
        monthly_drift = detect_drift_periods(monthly_conc)
        monthly_corr = compute_pattern_correlation(monthly_conc)

        # Statistics
        weekly_values = [c['concentration'] for c in weekly_conc.values()]
        monthly_values = [c['concentration'] for c in monthly_conc.values()]

        results[target_name] = {
            'weekly': {
                'concentrations': weekly_conc,
                'drift_periods': weekly_drift,
                'consecutive_correlation': weekly_corr,
                'statistics': {
                    'mean': float(np.mean(weekly_values)),
                    'std': float(np.std(weekly_values)),
                    'min': float(np.min(weekly_values)),
                    'max': float(np.max(weekly_values)),
                    'coefficient_of_variation': float(np.std(weekly_values) / np.mean(weekly_values)) if np.mean(weekly_values) > 0 else 0
                }
            },
            'monthly': {
                'concentrations': monthly_conc,
                'drift_periods': monthly_drift,
                'consecutive_correlation': monthly_corr,
                'statistics': {
                    'mean': float(np.mean(monthly_values)),
                    'std': float(np.std(monthly_values)),
                    'min': float(np.min(monthly_values)),
                    'max': float(np.max(monthly_values)),
                    'coefficient_of_variation': float(np.std(monthly_values) / np.mean(monthly_values)) if np.mean(monthly_values) > 0 else 0
                }
            }
        }

        # Print summary
        print(f"\nWeekly Patterns:")
        print(f"  Mean: {results[target_name]['weekly']['statistics']['mean']:.2f}%")
        print(f"  Std Dev: {results[target_name]['weekly']['statistics']['std']:.2f}%")
        print(f"  CV: {results[target_name]['weekly']['statistics']['coefficient_of_variation']:.3f}")

        if weekly_drift:
            print(f"\nWeekly Drift Periods (top 3):")
            for i, drift in enumerate(weekly_drift[:3], 1):
                print(f"  {i}. {drift['period']}: {drift['concentration']:.2f}% "
                      f"(z={drift['z_score']:.2f}, ﾎ・{drift['deviation']:+.2f}%)")

        print(f"\nMonthly Patterns:")
        print(f"  Mean: {results[target_name]['monthly']['statistics']['mean']:.2f}%")
        print(f"  Std Dev: {results[target_name]['monthly']['statistics']['std']:.2f}%")
        print(f"  CV: {results[target_name]['monthly']['statistics']['coefficient_of_variation']:.3f}")

        if monthly_drift:
            print(f"\nMonthly Drift Periods (top 3):")
            for i, drift in enumerate(monthly_drift[:3], 1):
                print(f"  {i}. {drift['period']}: {drift['concentration']:.2f}% "
                      f"(z={drift['z_score']:.2f}, ﾎ・{drift['deviation']:+.2f}%)")

    return results


def create_visualizations(df, results):
    """Create visualizations for temporal patterns."""
    targets = ['rank_1', 'top_3', 'top_5']
    colors = ['#EF553B', '#636EFA', '#00CC96']

    # 1. Weekly concentration over time
    fig1 = make_subplots(rows=3, cols=1, subplot_titles=('Rank 1', 'Top 3', 'Top 5'),
                         vertical_spacing=0.1)

    for idx, (target, color) in enumerate(zip(targets, colors), 1):
        weekly = results[target]['weekly']['concentrations']
        periods = sorted(list(weekly.keys()))
        concentrations = [weekly[p]['concentration'] for p in periods]

        fig1.add_trace(
            go.Scatter(
                x=periods,
                y=concentrations,
                name=target,
                mode='lines+markers',
                line=dict(color=color, width=2),
                marker=dict(size=6),
                hovertemplate='<b>%{x}</b><br>Concentration: %{y:.2f}%<extra></extra>'
            ),
            row=idx, col=1
        )

    fig1.update_xaxes(title_text='Week', row=3, col=1)
    fig1.update_yaxes(title_text='Concentration (%)', row=1, col=1)
    fig1.update_layout(height=900, showlegend=False,
                       title_text='譎らｳｻ蛻繝代ち繝ｼ繝ｳ - Weekly Concentration Over Time')

    fig1.write_html(RESULTS_DIR / 'temporal_weekly_pattern.html')

    # 2. Monthly concentration over time
    fig2 = make_subplots(rows=3, cols=1, subplot_titles=('Rank 1', 'Top 3', 'Top 5'),
                         vertical_spacing=0.1)

    for idx, (target, color) in enumerate(zip(targets, colors), 1):
        monthly = results[target]['monthly']['concentrations']
        periods = sorted(list(monthly.keys()))
        concentrations = [monthly[p]['concentration'] for p in periods]

        fig2.add_trace(
            go.Scatter(
                x=periods,
                y=concentrations,
                name=target,
                mode='lines+markers',
                line=dict(color=color, width=2),
                marker=dict(size=8),
                hovertemplate='<b>%{x}</b><br>Concentration: %{y:.2f}%<extra></extra>'
            ),
            row=idx, col=1
        )

    fig2.update_xaxes(title_text='Month', row=3, col=1)
    fig2.update_yaxes(title_text='Concentration (%)', row=1, col=1)
    fig2.update_layout(height=900, showlegend=False,
                       title_text='譎らｳｻ蛻繝代ち繝ｼ繝ｳ - Monthly Concentration Over Time')

    fig2.write_html(RESULTS_DIR / 'temporal_monthly_pattern.html')

    print(f"\n Visualizations saved to {RESULTS_DIR}/")


def save_results(results):
    """Save detailed results to JSON."""
    output = {
        'analysis': '譎らｳｻ蛻縺ｮ謚募・繝代ち繝ｼ繝ｳ螟牙喧',
        'description': 'Temporal pattern drift analysis',
        'results_by_target': {}
    }

    for target, data in results.items():
        output['results_by_target'][target] = {
            'weekly': {
                'concentrations': data['weekly']['concentrations'],
                'drift_periods': data['weekly']['drift_periods'],
                'statistics': data['weekly']['statistics']
            },
            'monthly': {
                'concentrations': data['monthly']['concentrations'],
                'drift_periods': data['monthly']['drift_periods'],
                'statistics': data['monthly']['statistics']
            }
        }

    with open(RESULTS_DIR / 'phase8_07_temporal_drift_results.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n Results saved to {RESULTS_DIR}/phase8_07_temporal_drift_results.json")


def main():
    print("\n" + "="*70)
    print("Phase 8-7: 譎らｳｻ蛻縺ｮ謚募・繝代ち繝ｼ繝ｳ螟牙喧 - Temporal Pattern Drift Analysis")
    print("="*70)

    # Load data
    print("\n[1/4] Loading data from database...")
    df = load_data(DB_PATH)
    print(f"  Loaded {len(df)} machine-day records")
    print(f"  Date range: {df['date'].min().date()} to {df['date'].max().date()}")
    print(f"  Weeks: {df['year_week'].nunique()}, Months: {df['month'].nunique()}")

    # Analyze
    print("\n[2/4] Analyzing temporal patterns...")
    results = analyze_temporal_patterns(df)

    # Visualize
    print("\n[3/4] Creating visualizations...")
    create_visualizations(df, results)

    # Save
    print("\n[4/4] Saving results...")
    save_results(results)

    print("\n" + "="*70)
    print("Phase 8-7 Complete!")
    print("="*70)


if __name__ == '__main__':
    main()
