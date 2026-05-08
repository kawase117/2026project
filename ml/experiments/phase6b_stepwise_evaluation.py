"""
Phase 6B: Stepwise AUC Improvement Evaluation

Called by: (to be created) ml/experiments/run_phase6b.py
Purpose: Evaluate 4-step AUC improvement path:
  Step 1: Baseline (Logistic Regression, no features)
  Step 2: +Composite Features (Logistic + target encoding)
  Step 3: +XGBoost (XGBoost without composite features)
  Step 4: +Both (XGBoost + composite features)

Output: Comparison table showing AUC at each step and cumulative delta

User instruction (verbatim): "実装は HAIKU で行ってください" (2026-05-08)
"""

import sys
import json
from pathlib import Path
from typing import Dict, Tuple
import numpy as np
import pandas as pd
import sqlite3
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import TimeSeriesSplit

from ..data_preparation import prepare_data_by_groupby
from ..models.baseline_logistic import LogisticRegressionModel
from ..models.tree_xgboost_v2 import XGBoostModelV2
from ..feature_engineering_phase6b import TargetEncoderPhase6B


class Phase6BEvaluator:
    """Orchestrates Phase 6B 4-step AUC evaluation across 3 halls."""

    HALLS = {
        "マルハン蒲田1": "db/マルハンメガシティ2000-蒲田1.db",
        "マルハン蒲田7": "db/マルハンメガシティ2000-蒲田7.db",
        "みとや大森町": "db/みとや大森町店.db",
    }

    def __init__(self):
        """Initialize evaluator."""
        self.results = {}
        self.comparison_table = None

    def evaluate_all_halls(self) -> pd.DataFrame:
        """
        Run all 4 evaluation steps across all 3 halls.

        Returns
        -------
        pd.DataFrame
            Comparison table with columns:
            - Hall: Hall name
            - Step1_Baseline: Logistic baseline AUC
            - Step2_PlusFeatures: Logistic + composite features AUC
            - Step3_PlusXGBoost: XGBoost baseline AUC
            - Step4_Both: XGBoost + composite features AUC
            - Delta_2to1: Step 2 improvement over Step 1
            - Delta_3to1: Step 3 improvement over Step 1
            - Delta_4to1: Step 4 improvement over Step 1 (total improvement)
        """
        rows = []

        for hall_name, db_path in self.HALLS.items():
            print(f"\n{'='*80}")
            print(f"Phase 6B Evaluation: {hall_name}")
            print(f"{'='*80}")

            try:
                # Load data for this hall
                print(f"\n[Data] Loading {hall_name} with model_type groupby strategy...")
                X_train, y_train, X_test, y_test = prepare_data_by_groupby(
                    db_path=db_path,
                    groupby_strategy="model_type",
                    task="a",
                    enable_extended_features=False
                )

                print(f"[Data] Train: {len(X_train)} samples, Features: {X_train.shape[1]}")
                print(f"[Data] Test: {len(X_test)} samples")
                print(f"[Label] Train positive: {y_train.sum()}/{len(y_train)} ({100*y_train.mean():.1f}%)")
                print(f"[Label] Test positive: {y_test.sum()}/{len(y_test)} ({100*y_test.mean():.1f}%)")

                # Step 1: Baseline (Logistic on raw one-hot features)
                print(f"\n[Step 1] Training baseline (Logistic, no features)...")
                model_baseline = LogisticRegressionModel(random_state=42)
                model_baseline.fit(X_train, y_train)
                y_pred_baseline = model_baseline.predict_proba(X_test)[:, 1]
                auc_step1 = roc_auc_score(y_test, y_pred_baseline)
                print(f"[Step 1] Baseline AUC = {auc_step1:.4f}")

                # Step 2: +Composite Features (Logistic + target encoding)
                print(f"\n[Step 2] Training with composite features (Logistic + target encoding)...")

                # Load raw feature dataframe for target encoding
                conn = sqlite3.connect(db_path)
                query = """
                    SELECT date, machine_number, machine_name, is_zorome
                    FROM machine_detailed_results
                    WHERE date <= '20260201'
                    ORDER BY date
                """
                df_train_raw = pd.read_sql_query(query, conn)

                query_test = """
                    SELECT date, machine_number, machine_name, is_zorome
                    FROM machine_detailed_results
                    WHERE date >= '20260201'
                    ORDER BY date
                """
                df_test_raw = pd.read_sql_query(query_test, conn)
                conn.close()

                # Add derived features
                df_train_raw['date'] = pd.to_datetime(df_train_raw['date'], format='%Y%m%d', errors='coerce')
                df_test_raw['date'] = pd.to_datetime(df_test_raw['date'], format='%Y%m%d', errors='coerce')
                df_train_raw['day_of_week'] = df_train_raw['date'].dt.day_name()
                df_test_raw['day_of_week'] = df_test_raw['date'].dt.day_name()
                df_train_raw['day_of_month'] = df_train_raw['date'].dt.day
                df_test_raw['day_of_month'] = df_test_raw['date'].dt.day

                # Fit target encoder on train, apply to test
                encoder = TargetEncoderPhase6B(smoothing=1.0)
                X_train_composite = encoder.fit_transform(df_train_raw, y_train)
                X_test_composite = encoder.transform(df_test_raw)

                print(f"[Step 2] Composite features shape: {X_train_composite.shape}")

                model_features = LogisticRegressionModel(random_state=42)
                model_features.fit(X_train_composite, y_train)
                y_pred_features = model_features.predict_proba(X_test_composite)[:, 1]
                auc_step2 = roc_auc_score(y_test, y_pred_features)
                print(f"[Step 2] With composite features AUC = {auc_step2:.4f}")

                # Step 3: +XGBoost (no composite features)
                print(f"\n[Step 3] Training XGBoost on raw features (no composite)...")
                model_xgb = XGBoostModelV2(
                    random_state=42,
                    max_depth=3,
                    learning_rate=0.01,
                    n_estimators=1000,
                    early_stopping_rounds=10
                )

                # Use validation set for early stopping (20% of train)
                split_idx = int(0.8 * len(X_train))
                X_train_main = X_train[:split_idx]
                y_train_main = y_train[:split_idx]
                X_val = X_train[split_idx:]
                y_val = y_train[split_idx:]

                model_xgb.fit(X_train_main, y_train_main, X_val, y_val)
                y_pred_xgb = model_xgb.predict_proba(X_test)[:, 1]
                auc_step3 = roc_auc_score(y_test, y_pred_xgb)
                print(f"[Step 3] XGBoost baseline AUC = {auc_step3:.4f}")
                if model_xgb.best_iteration_ is not None:
                    print(f"[Step 3] Early stopping at iteration {model_xgb.best_iteration_}")

                # Step 4: +Both (XGBoost + composite features)
                print(f"\n[Step 4] Training XGBoost with composite features...")
                model_both = XGBoostModelV2(
                    random_state=42,
                    max_depth=3,
                    learning_rate=0.01,
                    n_estimators=1000,
                    early_stopping_rounds=10
                )

                X_train_comp_main = X_train_composite[:split_idx]
                y_train_comp_main = y_train[:split_idx]
                X_val_comp = X_train_composite[split_idx:]
                y_val_comp = y_train[split_idx:]

                model_both.fit(X_train_comp_main, y_train_comp_main, X_val_comp, y_val_comp)
                y_pred_both = model_both.predict_proba(X_test_composite)[:, 1]
                auc_step4 = roc_auc_score(y_test, y_pred_both)
                print(f"[Step 4] XGBoost + composite features AUC = {auc_step4:.4f}")
                if model_both.best_iteration_ is not None:
                    print(f"[Step 4] Early stopping at iteration {model_both.best_iteration_}")

                # Calculate deltas
                delta_2to1 = auc_step2 - auc_step1
                delta_3to1 = auc_step3 - auc_step1
                delta_4to1 = auc_step4 - auc_step1

                print(f"\n[Summary] {hall_name}")
                print(f"  Step 1 (Baseline):      {auc_step1:.4f}")
                print(f"  Step 2 (+Features):     {auc_step2:.4f} (Δ {delta_2to1:+.4f})")
                print(f"  Step 3 (+XGBoost):      {auc_step3:.4f} (Δ {delta_3to1:+.4f})")
                print(f"  Step 4 (+Both):         {auc_step4:.4f} (Δ {delta_4to1:+.4f})")

                row = {
                    'Hall': hall_name,
                    'Step1_Baseline': auc_step1,
                    'Step2_PlusFeatures': auc_step2,
                    'Step3_PlusXGBoost': auc_step3,
                    'Step4_Both': auc_step4,
                    'Delta_2to1': delta_2to1,
                    'Delta_3to1': delta_3to1,
                    'Delta_4to1': delta_4to1,
                }
                rows.append(row)
                self.results[hall_name] = row

            except Exception as e:
                print(f"[ERROR] {hall_name}: {e}", file=sys.stderr)
                import traceback
                traceback.print_exc()
                continue

        # Create comparison table
        self.comparison_table = pd.DataFrame(rows)
        return self.comparison_table

    def print_summary(self):
        """Print summary comparison table."""
        if self.comparison_table is None:
            print("[WARN] No results to display")
            return

        print(f"\n{'='*120}")
        print("PHASE 6B EVALUATION SUMMARY")
        print(f"{'='*120}\n")

        # Format for display
        display_df = self.comparison_table.copy()
        for col in display_df.columns:
            if col != 'Hall':
                display_df[col] = display_df[col].apply(lambda x: f"{x:.4f}")

        print(display_df.to_string(index=False))

        # Overall statistics
        print(f"\n{'='*120}")
        print("OVERALL STATISTICS")
        print(f"{'='*120}")

        auc_step4_mean = self.comparison_table['Step4_Both'].mean()
        auc_step4_max = self.comparison_table['Step4_Both'].max()
        auc_step4_min = self.comparison_table['Step4_Both'].min()
        delta_4to1_mean = self.comparison_table['Delta_4to1'].mean()

        print(f"Average AUC (Step 4):      {auc_step4_mean:.4f}")
        print(f"Max AUC (Step 4):          {auc_step4_max:.4f}")
        print(f"Min AUC (Step 4):          {auc_step4_min:.4f}")
        print(f"Average improvement:       {delta_4to1_mean:+.4f}")

        print(f"\n[OK] Phase 6B evaluation completed\n")


def main():
    """Execute Phase 6B evaluation."""
    evaluator = Phase6BEvaluator()
    evaluator.evaluate_all_halls()
    evaluator.print_summary()


if __name__ == "__main__":
    main()
