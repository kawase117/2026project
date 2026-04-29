"""
仮説2：MLモデルの最適性検証

Step 1 の勝者グループ化戦略に対して、
複数のML候補（ロジスティック回帰、XGBoost、他）を試行し、
最適なモデルを選定する。
"""

import sys
import json
from pathlib import Path
from ml.data_preparation import prepare_data_by_groupby
from ml.models.baseline_logistic import LogisticRegressionModel
from ml.models.tree_xgboost import XGBoostModel
from ml.experiments.experiment_runner import ExperimentRunner


def load_winner_strategy(results_dir: str) -> str:
    """
    Step 1 の実験ログから勝者グループ化戦略を決定
    
    簡略化：最初にログされた戦略を使用
    実運用では、AUC等を比較して勝者を決定
    """
    results_dir = Path(results_dir)
    exp_files = sorted(results_dir.glob("exp_001_*.json"))
    
    if not exp_files:
        raise FileNotFoundError(f"No experiment logs found in {results_dir}")
    
    # 最初の実験ログから戦略を抽出
    with open(exp_files[0], "r", encoding="utf-8") as f:
        first_exp = json.load(f)
    
    winner = first_exp.get("groupby_strategy")
    print(f"Winner strategy from Step 1: {winner}")
    return winner


def run_hypothesis_2_experiments(db_path: str, results_dir: str = None):
    """
    仮説2を実行：勝者戦略 × ML候補2個 × タスク2 = 4実験
    """
    if results_dir is None:
        results_dir = Path(__file__).parent / "experiments" / "results"
    
    runner = ExperimentRunner(results_dir=results_dir)
    
    # Step 1 の勝者戦略を読み込み
    winner_strategy = load_winner_strategy(results_dir)
    
    # MLモデル候補
    models_config = [
        ("logistic", LogisticRegressionModel(random_state=42)),
        ("xgboost", XGBoostModel(random_state=42)),
    ]
    
    tasks = ["a", "b"]
    
    for model_name, model_instance in models_config:
        for task in tasks:
            print(f"\n{'='*60}")
            print(f"Experiment: Phase 2, Model={model_name}, Task={task}")
            print(f"{'='*60}")
            
            try:
                # データ準備（Step 1 の勝者戦略を使用）
                print(f"Loading data with strategy={winner_strategy}, task={task}...")
                X_train, y_train, X_test, y_test = prepare_data_by_groupby(
                    db_path=db_path,
                    groupby_strategy=winner_strategy,
                    task=task
                )
                
                print(f"Training samples: {len(X_train)}, Test samples: {len(X_test)}")
                
                # モデル訓練・評価
                exp_id = f"exp_002_model_{model_name}_task_{task}"
                
                runner.run_experiment(
                    experiment_id=exp_id,
                    phase=2,
                    hypothesis="MLモデルの最適性",
                    groupby_strategy=winner_strategy,
                    task=task,
                    ml_model=model_name,
                    X_train=X_train,
                    y_train=y_train,
                    X_test=X_test,
                    y_test=y_test,
                    model=model_instance,
                    interpretation=f"Model {model_name} with task {task} evaluated",
                    next_step="実装完了"
                )
                
                print(f"[OK] Experiment {exp_id} completed and logged")

            except Exception as e:
                print(f"[NG] Error in experiment {exp_id}: {e}", file=sys.stderr)
                raise
    
    print(f"\n{'='*60}")
    print("仮説2実行完了：4実験すべてがログに記録されました")
    print(f"ログディレクトリ: {results_dir}")
    print(f"{'='*60}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Run Hypothesis 2 experiments")
    parser.add_argument("--db-path", required=True, help="Path to SQLite database")
    parser.add_argument("--results-dir", default=None, help="Output directory for experiment logs")
    
    args = parser.parse_args()
    run_hypothesis_2_experiments(args.db_path, args.results_dir)
