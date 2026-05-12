# -*- coding: utf-8 -*-
"""
Phase 9-4: Comprehensive Evaluation & Reporting

Purpose: Synthesize Phase 9 findings (features, training, importance) into a final
comprehensive report with recommendations.

Output:
- phase9_results.json: Complete results summary
- phase9_evaluation_report.html: Comprehensive written findings and recommendations
- roc_curves_comparison.html: ROC curve visualization
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
import json
import xgboost as xgb
from sklearn.metrics import roc_curve, auc
import plotly.graph_objects as go
from plotly.subplots import make_subplots

PROJECT_ROOT = Path("C:\\Users\\apto117\\Documents\\pachinko-analyzer\\src\\2026project")
sys.path.insert(0, str(PROJECT_ROOT))
from ml.experiments.result_format import render_html_page, write_text

RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "results" / "phase9_machine_type_enhanced"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

FEATURES_CSV = RESULTS_DIR / "enhanced_features_20d.csv"
METRICS_JSON = RESULTS_DIR / "metrics_comparison.json"
IMPORTANCE_JSON = RESULTS_DIR / "feature_importance.json"


def load_all_results():
    """Load Phase 9 results from all phases."""
    with open(METRICS_JSON, "r", encoding="utf-8") as f:
        metrics = json.load(f)

    with open(IMPORTANCE_JSON, "r", encoding="utf-8") as f:
        importance = json.load(f)

    df_features = pd.read_csv(FEATURES_CSV)
    return metrics, importance, df_features


def load_enhanced_features(csv_path):
    """Load enhanced features for model comparison."""
    df = pd.read_csv(csv_path)
    X_20d = df.iloc[:, :20].values.astype(np.float32)
    X_16d = df.iloc[:, :16].values.astype(np.float32)
    dates = pd.to_datetime(df["date"]).values
    y_rank1 = df["is_rank_1"].values.astype(int)
    y_top3 = df["is_top_3"].values.astype(int)
    y_top5 = df["is_top_5"].values.astype(int)
    return X_16d, X_20d, dates, y_rank1, y_top3, y_top5


def train_models_for_visualization(X_16d, X_20d, dates, y):
    """Train baseline and enhanced models for ROC curve visualization."""
    unique_dates = pd.Series(dates).unique()
    split_date_idx = len(unique_dates) - 57
    split_date = unique_dates[split_date_idx]

    train_mask = dates < split_date
    test_mask = dates >= split_date

    X_train_16d = X_16d[train_mask]
    X_test_16d = X_16d[test_mask]
    X_train_20d = X_20d[train_mask]
    X_test_20d = X_20d[test_mask]

    y_train = y[train_mask]
    y_test = y[test_mask]

    model_16d = xgb.XGBClassifier(
        objective="binary:logistic",
        max_depth=3,
        learning_rate=0.01,
        n_estimators=200,
        random_state=42,
        eval_metric="logloss",
        verbosity=0,
    )
    model_16d.fit(X_train_16d, y_train, verbose=False)

    model_20d = xgb.XGBClassifier(
        objective="binary:logistic",
        max_depth=3,
        learning_rate=0.01,
        n_estimators=200,
        random_state=42,
        eval_metric="logloss",
        verbosity=0,
    )
    model_20d.fit(X_train_20d, y_train, verbose=False)

    y_pred_16d = model_16d.predict_proba(X_test_16d)[:, 1]
    y_pred_20d = model_20d.predict_proba(X_test_20d)[:, 1]
    return y_test, y_pred_16d, y_pred_20d


def create_roc_curves(X_16d, X_20d, dates, y_rank1, y_top3, y_top5):
    """Create ROC curve comparison for all targets."""
    targets = [
        ("rank_1", y_rank1, "Rank 1"),
        ("top_3", y_top3, "Top 3"),
        ("top_5", y_top5, "Top 5"),
    ]

    fig = make_subplots(
        rows=1,
        cols=3,
        subplot_titles=[name for _, _, name in targets],
        specs=[[{"type": "scatter"}, {"type": "scatter"}, {"type": "scatter"}]],
    )

    for col, (_, y_data, _) in enumerate(targets, 1):
        y_test, y_pred_16d, y_pred_20d = train_models_for_visualization(X_16d, X_20d, dates, y_data)
        fpr_16d, tpr_16d, _ = roc_curve(y_test, y_pred_16d)
        fpr_20d, tpr_20d, _ = roc_curve(y_test, y_pred_20d)
        auc_16d = auc(fpr_16d, tpr_16d)
        auc_20d = auc(fpr_20d, tpr_20d)

        fig.add_trace(
            go.Scatter(
                x=fpr_16d,
                y=tpr_16d,
                name=f"16D (AUC={auc_16d:.4f})",
                mode="lines",
                line=dict(color="#EF553B", width=2),
                hovertemplate="FPR: %{x:.3f}<br>TPR: %{y:.3f}<extra></extra>",
                showlegend=(col == 1),
            ),
            row=1,
            col=col,
        )
        fig.add_trace(
            go.Scatter(
                x=fpr_20d,
                y=tpr_20d,
                name=f"20D (AUC={auc_20d:.4f})",
                mode="lines",
                line=dict(color="#636EFA", width=2),
                hovertemplate="FPR: %{x:.3f}<br>TPR: %{y:.3f}<extra></extra>",
                showlegend=(col == 1),
            ),
            row=1,
            col=col,
        )
        fig.add_trace(
            go.Scatter(
                x=[0, 1],
                y=[0, 1],
                mode="lines",
                line=dict(color="gray", width=1, dash="dash"),
                showlegend=(col == 1),
                name="Random",
                hoverinfo="skip",
            ),
            row=1,
            col=col,
        )
        fig.update_xaxes(title_text="False Positive Rate", row=1, col=col)
        fig.update_yaxes(title_text="True Positive Rate", row=1, col=col)

    fig.update_layout(
        title="ROC Curve Comparison: 16D Baseline vs 20D Enhanced",
        height=500,
        hovermode="closest",
    )
    fig.write_html(RESULTS_DIR / "roc_curves_comparison.html")
    print("[OK] ROC curves saved")


def create_comprehensive_report(metrics, importance):
    """Generate comprehensive HTML report."""
    training_sections = []
    for target in ["rank_1", "top_3", "top_5"]:
        data = metrics[target]
        baseline = data["16D Baseline"]
        enhanced = data["20D Enhanced"]
        improvement = data["improvement"]
        training_sections.append(f"""
        <section>
          <h2>{target.upper()}</h2>
          <table>
            <tr><th>Metric</th><th>16D Baseline</th><th>20D Enhanced</th><th>Delta</th><th>Delta %</th></tr>
            <tr><td>AUC</td><td>{baseline['auc']:.4f}</td><td>{enhanced['auc']:.4f}</td><td>{improvement['auc_delta']:+.4f}</td><td>{improvement['auc_improvement_pct']:+.2f}%</td></tr>
            <tr><td>AP</td><td>{baseline['ap']:.4f}</td><td>{enhanced['ap']:.4f}</td><td>{enhanced['ap'] - baseline['ap']:+.4f}</td><td>-</td></tr>
            <tr><td>Hit@3</td><td>{baseline['hit_at_3']:.4f}</td><td>{enhanced['hit_at_3']:.4f}</td><td>{enhanced['hit_at_3'] - baseline['hit_at_3']:+.4f}</td><td>-</td></tr>
            <tr><td>Best F1</td><td>{baseline['best_f1_score']:.4f}</td><td>{enhanced['best_f1_score']:.4f}</td><td>{enhanced['best_f1_score'] - baseline['best_f1_score']:+.4f}</td><td>-</td></tr>
          </table>
        </section>
        """)

    importance_sections = []
    for target in ["rank_1", "top_3", "top_5"]:
        gains = importance["results_by_target"][target]["feature_importance_gain"]
        mt_gain = (
            gains.get("machine_type_other", 0)
            + gains.get("machine_type_hana", 0)
            + gains.get("machine_type_oki", 0)
            + gains.get("machine_type_bt", 0)
        )
        importance_sections.append(f"""
        <section>
          <h2>{target.upper()} Feature Importance</h2>
          <table>
            <tr><th>Total machine-type importance</th><td>{mt_gain:.4f}</td></tr>
            <tr><th>machine_type_other</th><td>{gains.get('machine_type_other', 0):.4f}</td></tr>
            <tr><th>machine_type_hana</th><td>{gains.get('machine_type_hana', 0):.4f}</td></tr>
            <tr><th>machine_type_oki</th><td>{gains.get('machine_type_oki', 0):.4f}</td></tr>
            <tr><th>machine_type_bt</th><td>{gains.get('machine_type_bt', 0):.4f}</td></tr>
          </table>
        </section>
        """)

    html = render_html_page(
        title="Phase 9 Machine-Type Enhanced Evaluation",
        body=f"""
        <section class="hero">
          <p class="eyebrow">Phase 9 Final</p>
          <h1>Machine-Type Enhanced Rank Prediction</h1>
          <p class="lede">Machine-type features add only marginal value on top of the 16D baseline: AUC gain stays between +0.0003 and +0.0042.</p>
        </section>
        <section>
          <h2>Executive Summary</h2>
          <p><strong>Objective:</strong> integrate machine-type features into the 16D baseline and measure incremental accuracy.</p>
          <p><strong>Finding:</strong> only the <code>other</code> category carries usable signal; rare one-hot categories remain effectively unused.</p>
        </section>
        <section>
          <h2>Training Results</h2>
          <p>Time-series validation uses the first N-57 dates for training and the last 57 dates for testing.</p>
        </section>
        {''.join(training_sections)}
        <section>
          <h2>Feature Importance</h2>
          <p>XGBoost gain confirms that the explicit machine-type encoding mostly duplicates signal already captured by the rolling baseline features.</p>
        </section>
        {''.join(importance_sections)}
        <section>
          <h2>Why It Underperformed</h2>
          <ol>
            <li>Baseline rolling features already absorb much of the machine-type signal.</li>
            <li>Rare categories such as <code>hana</code>, <code>oki</code>, and <code>bt</code> do not have enough samples for stable one-hot learning.</li>
            <li>The <code>other</code> signal is diluted across multiple binary columns instead of a single dense feature.</li>
            <li>Standalone effect size from earlier phases does not translate into marginal gain once strong baseline features are already present.</li>
          </ol>
        </section>
        <section>
          <h2>Recommendations</h2>
          <ol>
            <li>Replace one-hot machine-type columns with a single <code>is_other</code> flag.</li>
            <li>Try target encoding per machine type on training folds only.</li>
            <li>If gains remain small, shift effort to baseline tuning and interaction features.</li>
            <li>Only consider specialist ensembles after cheaper feature simplifications fail.</li>
          </ol>
        </section>
        <section>
          <h2>Statistical Read</h2>
          <p>With roughly 5,800 test samples, the observed AUC gain is small enough that it is unlikely to change downstream business decisions even when positive.</p>
        </section>
        <section>
          <h2>Conclusion</h2>
          <p>Machine-type information exists, but the current one-hot integration is an inefficient way to expose it to the model.</p>
          <p><strong>Recommended next step:</strong> test the simpler <code>is_other</code> encoding before spending more time on complex ensembles.</p>
        </section>
        """,
    )

    report_file = RESULTS_DIR / "phase9_evaluation_report.html"
    write_text(report_file, html)
    print(f"[OK] Comprehensive report saved to {report_file}")


def save_final_results(metrics, importance):
    """Save consolidated results to JSON."""
    output = {
        "project": "Phase 9: Machine-Type Enhanced Rank Prediction",
        "status": "COMPLETE",
        "summary": {
            "finding": "Machine-type features provide minimal improvement (AUC +0.0003 to +0.0042)",
            "root_cause": "Multicollinearity + rare category encoding inefficiency",
            "recommendation": 'Skip one-hot encoding; try simple "is_other" flag or hyperparameter optimize baseline',
        },
        "phase9_2_metrics": metrics,
        "phase9_3_importance": {
            target: {
                "machine_type_other_gain": importance["results_by_target"][target]["feature_importance_gain"].get("machine_type_other", 0),
                "machine_type_total_gain": (
                    importance["results_by_target"][target]["feature_importance_gain"].get("machine_type_other", 0)
                    + importance["results_by_target"][target]["feature_importance_gain"].get("machine_type_hana", 0)
                    + importance["results_by_target"][target]["feature_importance_gain"].get("machine_type_oki", 0)
                    + importance["results_by_target"][target]["feature_importance_gain"].get("machine_type_bt", 0)
                ),
            }
            for target in ["rank_1", "top_3", "top_5"]
        },
    }

    with open(RESULTS_DIR / "phase9_results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"[OK] Final results saved to {RESULTS_DIR}/phase9_results.json")


def main():
    print("\n" + "=" * 70)
    print("Phase 9-4: Comprehensive Evaluation & Reporting")
    print("=" * 70)

    print("\n[1/3] Loading all Phase 9 results...")
    metrics, importance, _ = load_all_results()

    print("\n[2/3] Creating visualizations...")
    X_16d, X_20d, dates, y_rank1, y_top3, y_top5 = load_enhanced_features(FEATURES_CSV)
    create_roc_curves(X_16d, X_20d, dates, y_rank1, y_top3, y_top5)

    print("\n[3/3] Generating comprehensive report...")
    create_comprehensive_report(metrics, importance)
    save_final_results(metrics, importance)

    print("\n" + "=" * 70)
    print("Phase 9-4 Complete!")
    print("=" * 70)
    print("\nPhase 9 Output Summary:")
    print("  [1] enhanced_features_20d.csv")
    print("  [2] metrics_comparison.json")
    print("  [3] feature_importance.json")
    print("  [4] roc_curves_comparison.html")
    print("  [5] phase9_results.json")
    print("  [6] phase9_evaluation_report.html")


if __name__ == "__main__":
    main()
