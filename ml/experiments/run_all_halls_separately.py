"""
Per-hall hypothesis testing.
Run hypothesis 1 and 2 separately for each of 9 halls.
"""

import sys
from pathlib import Path
from ml.data_preparation import prepare_data_by_groupby
from ml.models.baseline_logistic import LogisticRegressionModel
from ml.models.tree_xgboost import XGBoostModel
from ml.experiments.experiment_runner import ExperimentRunner


HALLS = [
    ("ARROW池上店", "db/ARROW池上店.db"),
    ("みとや大森町店", "db/みとや大森町店.db"),
    ("ザ-シティ-ベルシティ雑色店", "db/ザ-シティ-ベルシティ雑色店.db"),
    ("ヒロキ東口店", "db/ヒロキ東口店.db"),
    ("マルハンメガシティ2000-蒲田1", "db/マルハンメガシティ2000-蒲田1.db"),
    ("マルハンメガシティ2000-蒲田7", "db/マルハンメガシティ2000-蒲田7.db"),
    ("マルハン蒲田1", "db/マルハン蒲田1.db"),
    ("レイトギャップ平和島", "db/レイトギャップ平和島.db"),
    ("楽園蒲田店", "db/楽園蒲田店.db"),
]


def run_per_hall_hypothesis_1(results_dir: str = None, enable_extended: bool = False):
    """Run Hypothesis 1 for each hall individually"""
    if results_dir is None:
        results_dir = Path(__file__).parent / "results"

    runner = ExperimentRunner(results_dir=results_dir)

    strategies = ["tail", "model_type", "machine_number"]
    tasks = ["a", "b"]

    results = []

    for hall_name, db_path in HALLS:
        print(f"\n{'='*60}")
        print(f"Hall: {hall_name}")
        print(f"{'='*60}")

        for strategy in strategies:
            for task in tasks:
                try:
                    X_train, y_train, X_test, y_test = prepare_data_by_groupby(
                        db_path=db_path,
                        groupby_strategy=strategy,
                        task=task,
                        enable_extended_features=enable_extended
                    )

                    model = LogisticRegressionModel(random_state=42)
                    exp_id = f"hall_{hall_name}_exp_001_{strategy}_task_{task}"
                    if enable_extended:
                        exp_id = f"{exp_id}_extended"

                    runner.run_experiment(
                        experiment_id=exp_id,
                        phase=1,
                        hypothesis=f"グループ化戦略の最適性（{hall_name}）",
                        groupby_strategy=strategy,
                        task=task,
                        ml_model="logistic",
                        X_train=X_train,
                        y_train=y_train,
                        X_test=X_test,
                        y_test=y_test,
                        model=model,
                        interpretation=f"{hall_name} - Strategy {strategy} Task {task}",
                        next_step="次ホール"
                    )

                    results.append({
                        'hall': hall_name,
                        'strategy': strategy,
                        'task': task,
                        'status': 'OK'
                    })

                except Exception as e:
                    print(f"[NG] {hall_name} {strategy} {task}: {e}", file=sys.stderr)
                    results.append({
                        'hall': hall_name,
                        'strategy': strategy,
                        'task': task,
                        'status': 'NG'
                    })

    return results


def run_per_hall_hypothesis_2(results_dir: str = None, enable_extended: bool = False):
    """Run Hypothesis 2 for each hall individually using machine_number strategy"""
    if results_dir is None:
        results_dir = Path(__file__).parent / "results"

    runner = ExperimentRunner(results_dir=results_dir)

    winner_strategy = "machine_number"

    models_config = [
        ("logistic", LogisticRegressionModel(random_state=42)),
        ("xgboost", XGBoostModel(random_state=42)),
    ]

    tasks = ["a", "b"]
    results = []

    for hall_name, db_path in HALLS:
        print(f"\n{'='*60}")
        print(f"Hall: {hall_name}")
        print(f"{'='*60}")

        for model_name, model_instance in models_config:
            for task in tasks:
                try:
                    X_train, y_train, X_test, y_test = prepare_data_by_groupby(
                        db_path=db_path,
                        groupby_strategy=winner_strategy,
                        task=task,
                        enable_extended_features=enable_extended
                    )

                    exp_id = f"hall_{hall_name}_exp_002_{model_name}_task_{task}"
                    if enable_extended:
                        exp_id = f"{exp_id}_extended"

                    runner.run_experiment(
                        experiment_id=exp_id,
                        phase=2,
                        hypothesis=f"MLモデルの最適性（{hall_name}）",
                        groupby_strategy=winner_strategy,
                        task=task,
                        ml_model=model_name,
                        X_train=X_train,
                        y_train=y_train,
                        X_test=X_test,
                        y_test=y_test,
                        model=model_instance,
                        interpretation=f"{hall_name} - Model {model_name} Task {task}",
                        next_step="次ホール"
                    )

                    results.append({
                        'hall': hall_name,
                        'model': model_name,
                        'task': task,
                        'status': 'OK'
                    })

                except Exception as e:
                    print(f"[NG] {hall_name} {model_name} {task}: {e}", file=sys.stderr)
                    results.append({
                        'hall': hall_name,
                        'model': model_name,
                        'task': task,
                        'status': 'NG'
                    })

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run per-hall hypothesis testing")
    parser.add_argument("--results-dir", default=None, help="Results directory")
    parser.add_argument("--hypothesis", choices=["1", "2", "both"], default="both",
                       help="Which hypothesis to run")
    parser.add_argument("--extended", action="store_true", help="Use extended 69D features")

    args = parser.parse_args()

    if args.hypothesis in ["1", "both"]:
        results_h1 = run_per_hall_hypothesis_1(results_dir=args.results_dir, enable_extended=args.extended)
        print(f"\nHypothesis 1 Summary: {sum(1 for r in results_h1 if r['status']=='OK')}/{len(results_h1)} OK")

    if args.hypothesis in ["2", "both"]:
        results_h2 = run_per_hall_hypothesis_2(results_dir=args.results_dir, enable_extended=args.extended)
        print(f"\nHypothesis 2 Summary: {sum(1 for r in results_h2 if r['status']=='OK')}/{len(results_h2)} OK")

    print("\n" + "="*60)
    print("Per-hall hypothesis testing completed")
    print("="*60)
