"""
Phase 4 ML パイプライン最終検証
"""

from pathlib import Path
from ml.utils.logging_utils import get_experiments_dir
from ml.models.baseline_logistic import LogisticRegressionModel
from ml.models.tree_xgboost import XGBoostModel
from ml.evaluators.metrics import evaluate_model
from ml.evaluators.validators import TimeSeriesSplitter
from ml.experiments.experiment_runner import ExperimentRunner
from ml.data_preparation import prepare_data_by_groupby
import numpy as np


def validate_ml_pipeline():
    """Phase 4 パイプラインの総合検証"""
    print("="*60)
    print("Phase 4 ML Pipeline Final Validation")
    print("="*60)

    # 1. モジュールインポート確認
    print("\n[OK] All modules imported successfully")

    # 2. モデルインスタンス化確認
    lr_model = LogisticRegressionModel(random_state=42)
    xgb_model = XGBoostModel(random_state=42)
    print("[OK] Models instantiated (LogisticRegression, XGBoost)")

    # 3. メトリクス関数確認
    y_true = np.array([0, 1, 1, 0])
    y_pred_proba = np.array([0.1, 0.8, 0.7, 0.2])
    y_pred = (y_pred_proba > 0.5).astype(int)

    metrics = evaluate_model(y_true, y_pred_proba, y_pred)
    assert "auc" in metrics
    assert "accuracy" in metrics
    assert "f1" in metrics
    print(f"[OK] Metrics calculated: {list(metrics.keys())}")

    # 4. TimeSeriesSplitter 確認
    import pandas as pd
    df = pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=100),
        "value": np.random.randn(100)
    })
    splitter = TimeSeriesSplitter(
        train_end_date="2025-02-15",
        test_start_date="2025-02-15",
        test_end_date="2025-04-10"
    )
    train_idx, test_idx = splitter.split(df, date_column="date")
    print(f"[OK] TimeSeriesSplitter: train {len(train_idx)}, test {len(test_idx)}")

    # 5. ExperimentRunner 確認
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        runner = ExperimentRunner(results_dir=tmpdir)
        exp_id = runner.run_experiment(
            experiment_id="final_validation",
            phase=1,
            hypothesis="Final validation",
            groupby_strategy="tail",
            task="a",
            ml_model="logistic",
            X_train=np.array([[1, 0], [0, 1]]),
            y_train=np.array([0, 1]),
            X_test=np.array([[1, 0]]),
            y_test=np.array([0]),
            model=lr_model,
            interpretation="Validation",
            next_step="Done"
        )
        print(f"[OK] ExperimentRunner: experiment '{exp_id}' logged")

    # 6. ログディレクトリ確認
    exp_dir = get_experiments_dir()
    print(f"[OK] Experiments directory: {exp_dir}")

    print("\n" + "="*60)
    print("Phase 4 ML Pipeline: ALL VALIDATIONS PASSED")
    print("="*60)


if __name__ == "__main__":
    validate_ml_pipeline()
