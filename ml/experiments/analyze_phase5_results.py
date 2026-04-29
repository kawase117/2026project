"""
Phase 5-3: Consolidated vs Per-Hall Results Analysis

Aggregates results from Phase 5-1 (consolidated) and Phase 5-2 (per-hall)
to identify:
1. Baseline performance on unified data
2. Per-hall optimal strategies and models
3. Performance variance across halls
4. Statistical significance of hall-specific differences
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple, Any
import warnings

warnings.filterwarnings('ignore')


class Phase5Analyzer:
    """Analyze Phase 5 experimental results"""

    HALLS = [
        "ARROW池上店",
        "みとや大森町店",
        "ザ-シティ-ベルシティ雑色店",
        "ヒロキ東口店",
        "マルハンメガシティ2000-蒲田1",
        "マルハンメガシティ2000-蒲田7",
        "マルハン蒲田1",
        "レイトギャップ平和島",
        "楽園蒲田店",
    ]

    def __init__(self, results_dir: str = "ml/experiments/results"):
        self.results_dir = Path(results_dir)
        self.consolidated_results = {}
        self.per_hall_results = {}
        self.comparison_df = None

    def load_consolidated_results(self) -> Dict[str, Any]:
        """Load Phase 5-1 consolidated experiment results"""
        pattern = "consolidated_exp_*.json"
        files = sorted(self.results_dir.glob(pattern))

        if not files:
            print(f"[WARN]  No consolidated results found in {self.results_dir}")
            return {}

        results = {}
        for file in files:
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                exp_id = data['experiment_id']
                results[exp_id] = data

        self.consolidated_results = results
        print(f"[OK] Loaded {len(results)} consolidated experiment results")
        return results

    def load_per_hall_results(self) -> Dict[str, Dict[str, Any]]:
        """Load Phase 5-2 per-hall experiment results"""
        pattern = "hall_*_exp_*.json"
        files = sorted(self.results_dir.glob(pattern))

        if not files:
            print(f"[WARN]  No per-hall results found in {self.results_dir}")
            return {}

        results = {}
        for file in files:
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                exp_id = data['experiment_id']
                # Extract hall name from experiment ID: hall_{hall_name}_exp_...
                parts = exp_id.split('_')
                # Find where 'exp' starts (it's in the prefix "hall_{hall_name}_exp_...")
                hall_parts = []
                for i, part in enumerate(parts):
                    if part == 'exp':
                        break
                    if i > 0:  # Skip the initial "hall" marker
                        hall_parts.append(part)

                # Reconstruct hall name from parts
                # This is tricky because hall names have dashes and numbers
                # Actually, let's extract from the experiment_id more carefully
                # The pattern should be: hall_{hall_name_with_dashes}_exp_001_...

                # Better approach: extract everything between "hall_" and "_exp_"
                if exp_id.startswith("hall_"):
                    match_start = 5  # len("hall_")
                    match_end = exp_id.find("_exp_")
                    if match_end != -1:
                        hall_name = exp_id[match_start:match_end]
                        if hall_name not in results:
                            results[hall_name] = {}
                        results[hall_name][exp_id] = data

        self.per_hall_results = results
        print(f"[OK] Loaded {sum(len(v) for v in results.values())} per-hall experiment results across {len(results)} halls")
        return results

    def create_consolidated_summary(self) -> pd.DataFrame:
        """Create summary table of consolidated results"""
        if not self.consolidated_results:
            print("[WARN]  No consolidated results to summarize")
            return pd.DataFrame()

        rows = []
        for exp_id, data in sorted(self.consolidated_results.items()):
            row = {
                'experiment_id': exp_id,
                'phase': data.get('phase', ''),
                'hypothesis': data.get('hypothesis', ''),
                'groupby_strategy': data.get('groupby_strategy', 'N/A'),
                'task': data.get('task', ''),
                'ml_model': data.get('ml_model', 'N/A'),
                'auc': data.get('metrics', {}).get('auc', np.nan),
                'accuracy': data.get('metrics', {}).get('accuracy', np.nan),
                'precision': data.get('metrics', {}).get('precision', np.nan),
                'recall': data.get('metrics', {}).get('recall', np.nan),
                'f1': data.get('metrics', {}).get('f1', np.nan),
                'brier_score': data.get('metrics', {}).get('brier_score', np.nan),
            }
            rows.append(row)

        df = pd.DataFrame(rows)
        print(f"\n[SUMMARY] Consolidated Results Summary:")
        print(f"{'='*100}")
        print(df.to_string(index=False))
        print(f"{'='*100}")
        return df

    def create_per_hall_summary(self) -> pd.DataFrame:
        """Create summary table of per-hall results"""
        if not self.per_hall_results:
            print("[WARN]  No per-hall results to summarize")
            return pd.DataFrame()

        rows = []
        for hall_name, experiments in sorted(self.per_hall_results.items()):
            for exp_id, data in sorted(experiments.items()):
                row = {
                    'hall': hall_name,
                    'experiment_id': exp_id,
                    'phase': data.get('phase', ''),
                    'hypothesis': data.get('hypothesis', ''),
                    'groupby_strategy': data.get('groupby_strategy', 'N/A'),
                    'task': data.get('task', ''),
                    'ml_model': data.get('ml_model', 'N/A'),
                    'auc': data.get('metrics', {}).get('auc', np.nan),
                    'accuracy': data.get('metrics', {}).get('accuracy', np.nan),
                    'precision': data.get('metrics', {}).get('precision', np.nan),
                    'recall': data.get('metrics', {}).get('recall', np.nan),
                    'f1': data.get('metrics', {}).get('f1', np.nan),
                    'brier_score': data.get('metrics', {}).get('brier_score', np.nan),
                }
                rows.append(row)

        df = pd.DataFrame(rows)
        print(f"\n[SUMMARY] Per-Hall Results Summary (Partial):")
        print(f"{'='*120}")
        # Group by hall and show summary
        for hall in sorted(df['hall'].unique())[:3]:  # Show first 3 halls
            hall_df = df[df['hall'] == hall]
            print(f"\n{hall}:")
            print(hall_df[['experiment_id', 'hypothesis', 'groupby_strategy', 'task', 'auc', 'f1']].to_string(index=False))
        print(f"\n... and {len(df['hall'].unique()) - 3} more halls")
        print(f"{'='*120}")
        return df

    def identify_optimal_strategies(self) -> Dict[str, Dict[str, str]]:
        """
        Identify optimal groupby_strategy per task for each hall

        Returns:
            Dict[hall_name, Dict[task, optimal_strategy]]
        """
        if not self.per_hall_results:
            print("[WARN]  Cannot identify optimal strategies without per-hall results")
            return {}

        optimal = {}
        for hall_name, experiments in self.per_hall_results.items():
            optimal[hall_name] = {}

            # For each task (a, b)
            for task in ['a', 'b']:
                task_exps = {
                    exp_id: data
                    for exp_id, data in experiments.items()
                    if data.get('task') == task and 'groupby_strategy' in data
                }

                if not task_exps:
                    continue

                # Find experiment with highest AUC
                best_exp_id = max(
                    task_exps.keys(),
                    key=lambda eid: task_exps[eid].get('metrics', {}).get('auc', 0)
                )
                best_data = task_exps[best_exp_id]
                best_auc = best_data.get('metrics', {}).get('auc', 0)
                best_strategy = best_data.get('groupby_strategy', 'unknown')

                optimal[hall_name][task] = {
                    'strategy': best_strategy,
                    'auc': best_auc,
                    'experiment_id': best_exp_id
                }

        # Compare with consolidated baseline
        print(f"\n[BEST] Optimal Strategies by Hall (Phase 5-2):")
        print(f"{'='*80}")
        print(f"{'Hall':<30} {'Task A Strategy':<20} {'Task B Strategy':<20}")
        print(f"{'-'*80}")
        for hall in sorted(optimal.keys()):
            task_a_strat = optimal[hall].get('a', {}).get('strategy', 'N/A')
            task_b_strat = optimal[hall].get('b', {}).get('strategy', 'N/A')
            print(f"{hall:<30} {task_a_strat:<20} {task_b_strat:<20}")
        print(f"{'='*80}")

        return optimal

    def identify_optimal_models(self) -> Dict[str, Dict[str, str]]:
        """
        Identify optimal ML model per task for each hall

        Returns:
            Dict[hall_name, Dict[task, optimal_model]]
        """
        if not self.per_hall_results:
            print("[WARN]  Cannot identify optimal models without per-hall results")
            return {}

        optimal = {}
        for hall_name, experiments in self.per_hall_results.items():
            optimal[hall_name] = {}

            # For each task (a, b)
            for task in ['a', 'b']:
                task_exps = {
                    exp_id: data
                    for exp_id, data in experiments.items()
                    if data.get('task') == task and 'ml_model' in data and data.get('phase') == 2
                }

                if not task_exps:
                    continue

                # Find experiment with highest AUC
                best_exp_id = max(
                    task_exps.keys(),
                    key=lambda eid: task_exps[eid].get('metrics', {}).get('auc', 0)
                )
                best_data = task_exps[best_exp_id]
                best_auc = best_data.get('metrics', {}).get('auc', 0)
                best_model = best_data.get('ml_model', 'unknown')

                optimal[hall_name][task] = {
                    'model': best_model,
                    'auc': best_auc,
                    'experiment_id': best_exp_id
                }

        print(f"\n[BEST] Optimal ML Models by Hall (Phase 5-2):")
        print(f"{'='*80}")
        print(f"{'Hall':<30} {'Task A Model':<20} {'Task B Model':<20}")
        print(f"{'-'*80}")
        for hall in sorted(optimal.keys()):
            task_a_model = optimal[hall].get('a', {}).get('model', 'N/A')
            task_b_model = optimal[hall].get('b', {}).get('model', 'N/A')
            print(f"{hall:<30} {task_a_model:<20} {task_b_model:<20}")
        print(f"{'='*80}")

        return optimal

    def analyze_performance_variance(self, consolidated_df: pd.DataFrame, per_hall_df: pd.DataFrame) -> Dict[str, float]:
        """
        Analyze whether per-hall performance differs significantly from consolidated baseline

        Returns:
            Dict with variance statistics and conclusion
        """
        if consolidated_df.empty or per_hall_df.empty:
            return {}

        # Get baseline AUC from consolidated experiments
        baseline_auc = consolidated_df['auc'].mean()
        baseline_std = consolidated_df['auc'].std()

        # Get per-hall variance
        per_hall_auc = per_hall_df['auc'].mean()
        per_hall_std = per_hall_df['auc'].std()

        # Calculate coefficient of variation for each hall
        hall_cv = {}
        for hall in per_hall_df['hall'].unique():
            hall_aucs = per_hall_df[per_hall_df['hall'] == hall]['auc'].values
            if len(hall_aucs) > 0:
                cv = np.std(hall_aucs) / (np.mean(hall_aucs) + 1e-6)
                hall_cv[hall] = cv

        # Find halls with notably different performance
        diff_halls = {}
        for hall, cv in hall_cv.items():
            avg_auc = per_hall_df[per_hall_df['hall'] == hall]['auc'].mean()
            if abs(avg_auc - baseline_auc) > baseline_std:
                diff_halls[hall] = {
                    'avg_auc': avg_auc,
                    'diff_from_baseline': avg_auc - baseline_auc,
                    'cv': cv
                }

        print(f"\n[STATS] Performance Variance Analysis:")
        print(f"{'='*80}")
        print(f"Consolidated Baseline AUC: {baseline_auc:.4f} (±{baseline_std:.4f})")
        print(f"Per-Hall Average AUC: {per_hall_auc:.4f} (±{per_hall_std:.4f})")
        print(f"\nHalls with Significant Variance (|diff| > 1σ):")
        for hall, stats in sorted(diff_halls.items(), key=lambda x: x[1]['diff_from_baseline'], reverse=True):
            sign = '+' if stats['diff_from_baseline'] > 0 else ''
            print(f"  {hall:<30} AUC={stats['avg_auc']:.4f} ({sign}{stats['diff_from_baseline']:+.4f}), CV={stats['cv']:.4f}")

        if not diff_halls:
            print("  (All halls perform within 1σ of consolidated baseline)")
        print(f"{'='*80}")

        return {
            'baseline_auc': baseline_auc,
            'baseline_std': baseline_std,
            'per_hall_auc': per_hall_auc,
            'per_hall_std': per_hall_std,
            'differential_halls': diff_halls,
            'recommendation': 'hall_specific_models_needed' if len(diff_halls) > 2 else 'consolidated_model_sufficient'
        }

    def generate_report(self):
        """Generate Phase 5-3 analysis report"""
        print("\n" + "="*100)
        print("PHASE 5-3: CONSOLIDATED vs PER-HALL ANALYSIS REPORT")
        print("="*100)

        # Load results
        print("\n[1] Loading Results...")
        self.load_consolidated_results()
        self.load_per_hall_results()

        # Create summaries
        print("\n[2] Creating Summaries...")
        consolidated_df = self.create_consolidated_summary()
        per_hall_df = self.create_per_hall_summary()

        # Identify optimal strategies and models
        print("\n[3] Analyzing Optimal Strategies...")
        strategies = self.identify_optimal_strategies()

        print("\n[4] Analyzing Optimal Models...")
        models = self.identify_optimal_models()

        # Analyze variance
        print("\n[5] Analyzing Performance Variance...")
        variance_analysis = self.analyze_performance_variance(consolidated_df, per_hall_df)

        # Generate conclusion
        print("\n[CONCLUSION]")
        print("="*100)
        if variance_analysis.get('recommendation') == 'hall_specific_models_needed':
            print("[OK] RECOMMENDATION: Hall-specific models ARE NECESSARY")
            print(f"  Reason: {len(variance_analysis.get('differential_halls', {}))} halls show significant variance from baseline")
            print("  Next step: Implement hall-specific model selection in production pipeline")
        else:
            print("[NG] RECOMMENDATION: Consolidated model is SUFFICIENT")
            print("  Reason: All halls perform within acceptable variance of baseline")
            print("  Next step: Use unified consolidated model for all halls")
        print("="*100)

        return {
            'consolidated_df': consolidated_df,
            'per_hall_df': per_hall_df,
            'optimal_strategies': strategies,
            'optimal_models': models,
            'variance_analysis': variance_analysis,
        }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Analyze Phase 5 results")
    parser.add_argument("--results-dir", default="ml/experiments/results", help="Results directory path")

    args = parser.parse_args()

    analyzer = Phase5Analyzer(results_dir=args.results_dir)
    report = analyzer.generate_report()

    print("\n[OK] Phase 5-3 analysis complete")
