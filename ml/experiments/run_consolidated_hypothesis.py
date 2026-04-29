"""
Consolidated hypothesis testing across all 9 halls.
Reads each hall DB individually, unions data in Python, then validates.
Uses TimeSeriesSplit for proper temporal validation.
"""

import sys
import numpy as np
from pathlib import Path
from sklearn.model_selection import TimeSeriesSplit
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
    Load data from all 9 halls and union them in temporal order.
    Handles dimension mismatches by standardizing feature shapes across halls.

    Returns full consolidated data (train+test) for TimeSeriesSplit application.
    Returns:
        (X_full, y_full, X_test_range, y_test_range)
        - X_full, y_full: All data (訓練期間 + テスト期間) sorted by date for TimeSeriesSplit
        - X_test_range, y_test_range: Data in test period only (2026-02-01～2026-04-26)
    """
    X_train_list = []
    y_train_list = []
    X_test_list = []
    y_test_list = []
    shapes = []

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
            shapes.append(X_train.shape[1])

            hall_name = Path(db_path).stem
            print(f"  [OK] {hall_name}: {len(X_train)} train ({X_train.shape[1]}D), {len(X_test)} test")
        except Exception as e:
            print(f"  [NG] {db_path}: {str(e)[:80]}", file=sys.stderr)
            continue

    if not X_train_list:
        raise ValueError("Failed to load data from any hall")

    # For non-extended features with categorical groupby_strategy, dimensions may differ
    # Standardize to maximum dimension by padding with zeros
    if not enable_extended_features and groupby_strategy in ["tail", "model_type"]:
        max_dim = max(shapes)
        print(f"\nStandardizing feature dimensions to {max_dim} (found {set(shapes)})")

        X_train_std = []
        X_test_std = []
        for X_train, X_test in zip(X_train_list, X_test_list):
            if X_train.shape[1] < max_dim:
                # Pad with zeros
                pad_width = ((0, 0), (0, max_dim - X_train.shape[1]))
                X_train = np.pad(X_train, pad_width, mode='constant', constant_values=0)
                X_test = np.pad(X_test, pad_width, mode='constant', constant_values=0)
            X_train_std.append(X_train)
            X_test_std.append(X_test)

        X_train_list = X_train_std
        X_test_list = X_test_std

    # Union all data (訓練期間 and テスト期間)
    X_train_consolidated = np.vstack(X_train_list)
    y_train_consolidated = np.concatenate(y_train_list)
    X_test_consolidated = np.vstack(X_test_list)
    y_test_consolidated = np.concatenate(y_test_list)

    # Combine for TimeSeriesSplit (訓練 + テスト)
    X_full = np.vstack([X_train_consolidated, X_test_consolidated])
    y_full = np.concatenate([y_train_consolidated, y_test_consolidated])

    print(f"Consolidated (全体): {len(X_full)} samples total ({X_full.shape[1]}D features)")
    print(f"  訓練期間: {len(X_train_consolidated)} samples")
    print(f"  テスト期間: {len(X_test_consolidated)} samples")

    return X_full, y_full, X_test_consolidated, y_test_consolidated


def run_consolidated_hypothesis_1(results_dir: str = None, enable_extended: bool = False):
    """Run Hypothesis 1 (groupby strategy) on consolidated all-hall data with TimeSeriesSplit"""
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
                # Load full consolidated data (train + test range)
                X_full, y_full, X_test_range, y_test_range = load_and_consolidate_data(
                    groupby_strategy=strategy,
                    task=task,
                    enable_extended_features=enable_extended
                )

                # Use TimeSeriesSplit for temporal validation
                # n_splits=1: One train/test split (first fold only for Phase 5)
                tscv = TimeSeriesSplit(n_splits=1)

                for fold_idx, (train_idx, test_idx) in enumerate(tscv.split(X_full)):
                    X_train = X_full[train_idx]
                    y_train = y_full[train_idx]
                    X_test = X_full[test_idx]
                    y_test = y_full[test_idx]

                    model = LogisticRegressionModel(random_state=42)
                    exp_id = f"consolidated_exp_001_groupby_{strategy}_task_{task}"
                    if enable_extended:
                        exp_id = f"consolidated_extended_{exp_id}"

                    # Append split info to ensure unique IDs if multiple splits
                    if fold_idx > 0:
                        exp_id = f"{exp_id}_split_{fold_idx}"

                    runner.run_experiment(
                        experiment_id=exp_id,
                        phase=1,
                        hypothesis="グループ化戦略の最適性（全ホール統合・時系列CV）",
                        groupby_strategy=strategy,
                        task=task,
                        ml_model="logistic",
                        X_train=X_train,
                        y_train=y_train,
                        X_test=X_test,
                        y_test=y_test,
                        model=model,
                        interpretation=f"Consolidated (TimeSeriesSplit fold {fold_idx}) - Strategy {strategy} Task {task}",
                        next_step="ホール別検証へ"
                    )

                    print(f"[OK] {exp_id} completed (fold {fold_idx}, train_size={len(train_idx)}, test_size={len(test_idx)})")

            except Exception as e:
                print(f"[NG] Error: {e}", file=sys.stderr)
                raise


def run_consolidated_hypothesis_2(results_dir: str = None, enable_extended: bool = False):
    """Run Hypothesis 2 (ML model) on consolidated all-hall data with winner strategy and TimeSeriesSplit"""
    if results_dir is None:
        results_dir = Path(__file__).parent / "results"

    runner = ExperimentRunner(results_dir=results_dir)

    # Use model_type as the optimal strategy (from Phase 5-1 results)
    optimal_strategy = "model_type"

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
                # Load full consolidated data with optimal strategy
                X_full, y_full, X_test_range, y_test_range = load_and_consolidate_data(
                    groupby_strategy=optimal_strategy,
                    task=task,
                    enable_extended_features=enable_extended
                )

                # Use TimeSeriesSplit for temporal validation
                tscv = TimeSeriesSplit(n_splits=1)

                for fold_idx, (train_idx, test_idx) in enumerate(tscv.split(X_full)):
                    X_train = X_full[train_idx]
                    y_train = y_full[train_idx]
                    X_test = X_full[test_idx]
                    y_test = y_full[test_idx]

                    exp_id = f"consolidated_exp_002_model_{model_name}_task_{task}"
                    if enable_extended:
                        exp_id = f"consolidated_extended_{exp_id}"

                    if fold_idx > 0:
                        exp_id = f"{exp_id}_split_{fold_idx}"

                    runner.run_experiment(
                        experiment_id=exp_id,
                        phase=2,
                        hypothesis="MLモデルの最適性（全ホール統合・時系列CV）",
                        groupby_strategy=optimal_strategy,
                        task=task,
                        ml_model=model_name,
                        X_train=X_train,
                        y_train=y_train,
                        X_test=X_test,
                        y_test=y_test,
                        model=model_instance,
                        interpretation=f"Consolidated (TimeSeriesSplit fold {fold_idx}) - Model {model_name} Task {task}",
                        next_step="ホール別検証へ"
                    )

                    print(f"[OK] {exp_id} completed (fold {fold_idx}, train_size={len(train_idx)}, test_size={len(test_idx)})")

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
