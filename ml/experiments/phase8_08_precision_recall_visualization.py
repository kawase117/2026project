"""
Phase 8-8: Precision-Recall Visualization

Creates Precision-Recall curves for all 6 models across 3 targets.
Highlights Precision=70%, 80%, 90% thresholds for domain insights.
"""

import json
from pathlib import Path
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np

PROJECT_ROOT = Path("C:\\Users\\apto117\\Documents\\pachinko-analyzer\\src\\2026project")
RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase8_precision_recall"
INPUT_FILE = RESULTS_DIR / "precision_recall_analysis.json"
OUTPUT_HTML = RESULTS_DIR / "precision_recall_curves.html"


def create_pr_visualization():
    """Create Precision-Recall curves with target precision thresholds."""

    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Colors for models
    colors = {
        'xgboost_baseline': '#1f77b4',
        'xgboost_balanced': '#ff7f0e',
        'catboost': '#2ca02c',
        'randomforest': '#d62728',
        'stacking': '#9467bd',
        'neural_network': '#8c564b'
    }

    model_labels = {
        'xgboost_baseline': 'XGBoost Baseline',
        'xgboost_balanced': 'XGBoost + scale_pos_weight',
        'catboost': 'CatBoost',
        'randomforest': 'RandomForest',
        'stacking': 'Stacking (XGB+CatBoost)',
        'neural_network': 'Neural Network (MLP)'
    }

    # Create subplots (1 row, 3 columns for 3 targets)
    fig = make_subplots(
        rows=1, cols=3,
        subplot_titles=('RANK_1', 'TOP_3', 'TOP_5'),
        specs=[[{'type': 'scatter'}, {'type': 'scatter'}, {'type': 'scatter'}]]
    )

    targets = ['rank_1', 'top_3', 'top_5']
    col_idx = 1

    for target in targets:
        target_data = data[target]

        # Add PR curves for each model
        for model_name, model_data in target_data.items():
            recall = model_data['recall']
            precision = model_data['precision']
            ap = model_data['ap']

            fig.add_trace(
                go.Scatter(
                    x=recall, y=precision,
                    mode='lines',
                    name=model_labels[model_name],
                    line=dict(color=colors[model_name], width=2),
                    hovertemplate=f"{model_labels[model_name]}<br>Recall: %{{x:.3f}}<br>Precision: %{{y:.3f}}<extra></extra>",
                    showlegend=(col_idx == 1)  # Only show legend for first subplot
                ),
                row=1, col=col_idx
            )

            # Add points for 70%, 80%, 90% precision levels
            pr_points = model_data['pr_points']
            for precision_level, point_data in pr_points.items():
                fig.add_trace(
                    go.Scatter(
                        x=[point_data['recall']],
                        y=[point_data['precision']],
                        mode='markers',
                        marker=dict(
                            size=8,
                            color=colors[model_name],
                            symbol='diamond',
                            line=dict(color='white', width=1)
                        ),
                        name=f"{model_labels[model_name]} {precision_level}",
                        hovertemplate=f"{model_labels[model_name]}<br>{precision_level} Precision<br>Recall: %{{x:.3f}}<br>Threshold: {point_data['threshold']:.4f}<br>N_pred: {point_data['n_predicted']}<extra></extra>",
                        showlegend=False,
                        visible='legendonly'  # Hidden by default, can be toggled
                    ),
                    row=1, col=col_idx
                )

        # Add horizontal lines for target precision levels
        for precision_level in [0.70, 0.80, 0.90]:
            fig.add_hline(
                y=precision_level,
                line_dash='dash',
                line_color='gray',
                opacity=0.3,
                row=1, col=col_idx,
                annotation_text=f"{int(precision_level*100)}%" if precision_level == 0.70 else None,
                annotation_position='right'
            )

        # Update x/y axes
        fig.update_xaxes(title_text='Recall', row=1, col=col_idx, range=[0, 1])
        fig.update_yaxes(title_text='Precision', row=1, col=col_idx, range=[0, 1])

        col_idx += 1

    # Update layout
    fig.update_layout(
        title_text='Precision-Recall Curves: Model Comparison Across Targets',
        height=600,
        width=1600,
        hovermode='closest',
        legend=dict(
            x=1.05, y=1,
            xanchor='left', yanchor='top',
            bgcolor='rgba(255,255,255,0.8)',
            bordercolor='gray',
            borderwidth=1
        )
    )

    fig.write_html(str(OUTPUT_HTML))
    print(f"[SAVED] Interactive visualization: {OUTPUT_HTML}")


def print_pr_summary():
    """Print summary statistics."""

    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    print("\n" + "="*100)
    print("PRECISION-RECALL SUMMARY: Threshold Analysis")
    print("="*100)

    for target in ['rank_1', 'top_3', 'top_5']:
        print(f"\n[TARGET: {target.upper()}]")
        print(f"{'Model':<30} {'70% P':<15} {'80% P':<15} {'90% P':<15}")
        print(f"{'':30} {'Recall/Thr/N':<15} {'Recall/Thr/N':<15} {'Recall/Thr/N':<15}")
        print("-" * 100)

        for model_name in ['xgboost_baseline', 'xgboost_balanced', 'catboost', 'randomforest', 'stacking', 'neural_network']:
            if model_name not in data[target]:
                continue

            model_data = data[target][model_name]
            pr_points = model_data['pr_points']

            row = f"{model_name:<30}"

            for precision_level in ['70%', '80%', '90%']:
                if precision_level in pr_points:
                    point = pr_points[precision_level]
                    recall = point['recall']
                    threshold = point['threshold']
                    n_pred = point['n_predicted']
                    row += f"R={recall:.3f}/T={threshold:.3f}/N={n_pred:<5} "
                else:
                    row += f"{'N/A':<15}"

            print(row)

    print("\n" + "="*100)
    print("INTERPRETATION:")
    print("="*100)
    print("""
Precision=70% : 70% of predicted positives are actually positive (30% false positives)
Precision=80% : 80% of predicted positives are actually positive (20% false positives)
Precision=90% : 90% of predicted positives are actually positive (10% false positives)

Recall = What % of actual positives were caught (higher = less lost profit)
Threshold = Confidence threshold for prediction (higher = more conservative, fewer predictions)
N_predicted = Number of machines predicted as positive at that threshold

DOMAIN INSIGHT:
- High Precision & Non-zero Recall = "特定の条件が揃えば、高確率で高設定"
- Model with best Precision@70-90% = "最も信頼できる予測が可能" (external validation needs to confirm)
    """)


if __name__ == '__main__':
    print("="*100)
    print("Phase 8-8: Precision-Recall Visualization")
    print("="*100)

    try:
        create_pr_visualization()
        print_pr_summary()
        print("\n[SUCCESS] Visualization complete!")
    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
