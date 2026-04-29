"""
仮説1：グループ化戦略の最適性検証

グループ化戦略（末尾別、機種別、台番号別）の中で、
どの戦略が最も予測性能が高いかを検証する。
各戦略に対して、同じML（ロジスティック回帰）で訓練・評価。
"""

import sys
from pathlib import Path
from ml.data_preparation import prepare_data_by_groupby
from ml.models.baseline_logistic import LogisticRegressionModel
from ml.experiments.experiment_runner import ExperimentRunner


def run_hypothesis_1_experiments(db_path: str, results_dir: str = None):
    """
    仮説1を実行：グループ化戦略3方式 × タスク2 = 6実験
    
    Args:
        db_path: SQLite DBファイルパス
        results_dir: 実験結果出力ディレクトリ（Noneの場合はデフォルト）
    """
    if results_dir is None:
        results_dir = Path(__file__).parent / "experiments" / "results"
    
    runner = ExperimentRunner(results_dir=results_dir)
    
    strategies = ["tail", "model_type", "machine_number"]
    tasks = ["a", "b"]
    
    for strategy in strategies:
        for task in tasks:
            print(f"\n{'='*60}")
            print(f"Experiment: Phase 1, Strategy={strategy}, Task={task}")
            print(f"{'='*60}")
            
            try:
                # データ準備
                print(f"Loading data with strategy={strategy}, task={task}...")
                X_train, y_train, X_test, y_test = prepare_data_by_groupby(
                    db_path=db_path,
                    groupby_strategy=strategy,
                    task=task
                )
                
                print(f"Training samples: {len(X_train)}, Test samples: {len(X_test)}")
                
                # モデル訓練・評価
                model = LogisticRegressionModel(random_state=42)
                exp_id = f"exp_001_groupby_{strategy}_task_{task}"
                
                runner.run_experiment(
                    experiment_id=exp_id,
                    phase=1,
                    hypothesis="グループ化戦略の最適性",
                    groupby_strategy=strategy,
                    task=task,
                    ml_model="logistic",
                    X_train=X_train,
                    y_train=y_train,
                    X_test=X_test,
                    y_test=y_test,
                    model=model,
                    interpretation=f"Strategy {strategy} with task {task} evaluated",
                    next_step="Step 2へ進む"
                )
                
                print(f"[OK] Experiment {exp_id} completed and logged")

            except Exception as e:
                print(f"[NG] Error in experiment {exp_id}: {e}", file=sys.stderr)
                raise
    
    print(f"\n{'='*60}")
    print("仮説1実行完了：6実験すべてがログに記録されました")
    print(f"ログディレクトリ: {results_dir}")
    print(f"{'='*60}")


def run_hypothesis_1_with_extended_features(db_path: str, results_dir: str = None):
    """
    仮説1を実行（拡張特徴量版）：グループ化戦略3方式 × タスク2 = 6実験（69D特徴量）

    Args:
        db_path: SQLite DBファイルパス
        results_dir: 実験結果出力ディレクトリ（Noneの場合はデフォルト）
    """
    if results_dir is None:
        results_dir = Path(__file__).parent / "experiments" / "results"

    runner = ExperimentRunner(results_dir=results_dir)

    strategies = ["tail", "model_type", "machine_number"]
    tasks = ["a", "b"]

    for strategy in strategies:
        for task in tasks:
            print(f"\n{'='*60}")
            print(f"Experiment: Phase 1 Extended (69D), Strategy={strategy}, Task={task}")
            print(f"{'='*60}")

            try:
                # データ準備（拡張特徴量有効化）
                print(f"Loading data with strategy={strategy}, task={task}...")
                X_train, y_train, X_test, y_test = prepare_data_by_groupby(
                    db_path=db_path,
                    groupby_strategy=strategy,
                    task=task,
                    enable_extended_features=True
                )

                print(f"Training samples: {len(X_train)}, Features: {X_train.shape[1]}D")
                print(f"Test samples: {len(X_test)}")

                # モデル訓練・評価
                model = LogisticRegressionModel(random_state=42)
                exp_id = f"exp_001_extended_{strategy}_task_{task}"

                runner.run_experiment(
                    experiment_id=exp_id,
                    phase=1,
                    hypothesis="グループ化戦略の最適性（拡張特徴量69D）",
                    groupby_strategy=strategy,
                    task=task,
                    ml_model="logistic",
                    X_train=X_train,
                    y_train=y_train,
                    X_test=X_test,
                    y_test=y_test,
                    model=model,
                    interpretation=f"Strategy {strategy} with task {task} (69D extended features)",
                    next_step="Step 2へ進む"
                )

                print(f"[OK] Experiment {exp_id} completed and logged")

            except Exception as e:
                print(f"[NG] Error in experiment {exp_id}: {e}", file=sys.stderr)
                raise

    print(f"\n{'='*60}")
    print("仮説1実行完了（拡張特徴量）：6実験すべてがログに記録されました")
    print(f"ログディレクトリ: {results_dir}")
    print(f"{'='*60}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run Hypothesis 1 experiments")
    parser.add_argument("--db-path", required=True, help="Path to SQLite database")
    parser.add_argument("--results-dir", default=None, help="Output directory for experiment logs")
    parser.add_argument("--extended", action="store_true", help="Use extended 69D features")

    args = parser.parse_args()

    if args.extended:
        run_hypothesis_1_with_extended_features(args.db_path, args.results_dir)
    else:
        run_hypothesis_1_experiments(args.db_path, args.results_dir)
