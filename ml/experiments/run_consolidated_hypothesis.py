"""
Consolidated hypothesis testing across all 9 halls.
Reads each hall DB individually, unions data in Python, then validates.
"""

import sys
import numpy as np
from pathlib import Path
from ml.data_preparation import prepare_data_by_groupby
from ml.models.baseline_logistic import LogisticRegressionModel
from ml.models.tree_xgboost import XGBoostModel
from ml.experiments.experiment_runner import ExperimentRunner


HALL_DBS = [
    "db/ARROW池上店.db",
    "db/みとや大森町店.db",
    "db/ザ-シティ-ベルシティ雑色店.db",
    "db/ヒロキ東口店.db",
    "db/マルハンメガシティ2000-蒲田1.db",
    "db/マルハンメガシティ2000-蒲田7.db",
    "db/マルハン蒲田1.db",
    "db/レイトギャップ平和島.db",
    "db/楽園蒲田店.db",
]


def load_and_consolidate_data(groupby_strategy: str, task: str,
                               enable_extended_features: bool = False):
    """
    Load data from all 9 halls and union them.

    Returns:
        Consolidated (X_train, y_train, X_test, y_test)
    """
    X_train_list = []
    y_train_list = []
    X_test_list = []
    y_test_list = []

    print(f"\nLoading data from {len(HALL_DBS)} halls...")
    for db_path in HALL_DBS:
        try:
            X_train, y_train, X_test, y_test = prepare_data_by_groupby(
                db_path=db_path,
                groupby_strategy=groupby_strategy,
                task=task,
                enable_extended_features=enable_extended_features
            )
            X_train_list.append(X_train)
            y_train_list.append(y_train)
            X_test_list.append(X_test)
            y_test_list.append(y_test)

            hall_name = Path(db_path).stem
            print(f"  ✓ {hall_name}: {len(X_train)} train, {len(X_test)} test")
        except Exception as e:
            print(f"  ✗ {db_path}: {e}", file=sys.stderr)
            continue

    # Union all data
    X_train_consolidated = np.vstack(X_train_list)
    y_train_consolidated = np.concatenate(y_train_list)
    X_test_consolidated = np.vstack(X_test_list)
    y_test_consolidated = np.concatenate(y_test_list)

    print(f"\nConsolidated: {len(X_train_consolidated)} train, {len(X_test_consolidated)} test")
    return X_train_consolidated, y_train_consolidated, X_test_consolidated, y_test_consolidated


def run_consolidated_hypothesis_1(results_dir: str = None, enable_extended: bool = False):
    """Run Hypothesis 1 (groupby strategy) on consolidated all-hall data"""
    if results_dir is None:
        results_dir = Path(__file__).parent / "results"

    runner = ExperimentRunner(results_dir=results_dir)

    strategies = ["tail", "model_type", "machine_number"]
    tasks = ["a", "b"]

    for strategy in strategies:
        for task in tasks:
            print(f"\n{'='*60}")
            print(f"Consolidated Hypothesis 1: Strategy={strategy}, Task={task}")
            print(f"Extended Features: {enable_extended}")
            print(f"{'='*60}")

            try:
                X_train, y_train, X_test, y_test = load_and_consolidate_data(
                    groupby_strategy=strategy,
                    task=task,
                    enable_extended_features=enable_extended
                )

                model = LogisticRegressionModel(random_state=42)
                exp_id = f"consolidated_exp_001_groupby_{strategy}_task_{task}"
                if enable_extended:
                    exp_id = f"consolidated_extended_{exp_id}"

                runner.run_experiment(
                    experiment_id=exp_id,
                    phase=1,
                    hypothesis="グループ化戦略の最適性（全ホール統合）",
                    groupby_strategy=strategy,
                    task=task,
                    ml_model="logistic",
                    X_train=X_train,
                    y_train=y_train,
                    X_test=X_test,
                    y_test=y_test,
                    model=model,
                    interpretation=f"Consolidated all halls - Strategy {strategy} Task {task}",
                    next_step="ホール別検証へ"
                )

                print(f"[OK] {exp_id} completed")
            except Exception as e:
                print(f"[NG] Error: {e}", file=sys.stderr)
                raise


def run_consolidated_hypothesis_2(results_dir: str = None, enable_extended: bool = False):
    """Run Hypothesis 2 (ML model) on consolidated all-hall data with winner strategy"""
    if results_dir is None:
        results_dir = Path(__file__).parent / "results"

    runner = ExperimentRunner(results_dir=results_dir)

    # Use machine_number as the winner strategy (from Phase 1)
    winner_strategy = "machine_number"

    models_config = [
        ("logistic", LogisticRegressionModel(random_state=42)),
        ("xgboost", XGBoostModel(random_state=42)),
    ]

    tasks = ["a", "b"]

    for model_name, model_instance in models_config:
        for task in tasks:
            print(f"\n{'='*60}")
            print(f"Consolidated Hypothesis 2: Model={model_name}, Task={task}")
            print(f"Extended Features: {enable_extended}")
            print(f"{'='*60}")

            try:
                X_train, y_train, X_test, y_test = load_and_consolidate_data(
                    groupby_strategy=winner_strategy,
                    task=task,
                    enable_extended_features=enable_extended
                )

                exp_id = f"consolidated_exp_002_model_{model_name}_task_{task}"
                if enable_extended:
                    exp_id = f"consolidated_extended_{exp_id}"

                runner.run_experiment(
                    experiment_id=exp_id,
                    phase=2,
                    hypothesis="MLモデルの最適性（全ホール統合）",
                    groupby_strategy=winner_strategy,
                    task=task,
                    ml_model=model_name,
                    X_train=X_train,
                    y_train=y_train,
                    X_test=X_test,
                    y_test=y_test,
                    model=model_instance,
                    interpretation=f"Consolidated all halls - Model {model_name} Task {task}",
                    next_step="ホール別検証へ"
                )

                print(f"[OK] {exp_id} completed")
            except Exception as e:
                print(f"[NG] Error: {e}", file=sys.stderr)
                raise


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run consolidated hypothesis testing across all halls")
    parser.add_argument("--results-dir", default=None, help="Results directory")
    parser.add_argument("--hypothesis", choices=["1", "2", "both"], default="both",
                       help="Which hypothesis to run")
    parser.add_argument("--extended", action="store_true", help="Use extended 69D features")

    args = parser.parse_args()

    if args.hypothesis in ["1", "both"]:
        run_consolidated_hypothesis_1(results_dir=args.results_dir, enable_extended=args.extended)

    if args.hypothesis in ["2", "both"]:
        run_consolidated_hypothesis_2(results_dir=args.results_dir, enable_extended=args.extended)

    print("\n" + "="*60)
    print("Consolidated hypothesis testing completed")
    print("="*60)
