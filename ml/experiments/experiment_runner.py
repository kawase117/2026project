"""
ExperimentRunner - Experiment execution and logging engine for Phase 4 ML pipeline.

This module provides:
- Experiment execution with model training and prediction
- Comprehensive metrics evaluation
- JSON-based experiment logging
- Multi-experiment retrieval and analysis

The runner encapsulates the full workflow:
1. Model training on provided training data
2. Probability predictions on test data
3. Binary predictions (with 0.5 threshold)
4. Metrics calculation via evaluate_model()
5. JSON logging with metadata (hypothesis, interpretation, next_step)
6. Timestamp recording in ISO format
"""

import json
import numpy as np
from pathlib import Path
from datetime import datetime
from ml.models.base_model import BaseModel
from ml.evaluators.metrics import evaluate_model


class ExperimentRunner:
    """
    Experiment execution and result logging engine.

    Manages the execution of ML experiments, calculates comprehensive metrics,
    and persists results as JSON logs with full metadata.

    Attributes:
        results_dir (Path): Directory where experiment logs are stored
    """

    def __init__(self, results_dir: str = None):
        """
        Initialize the ExperimentRunner.

        Args:
            results_dir: Directory path where experiment logs will be saved.
                        If None, creates 'results' directory in ml/experiments/
        """
        if results_dir is None:
            results_dir = Path(__file__).parent / "results"

        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def run_experiment(
        self,
        experiment_id: str,
        phase: int,
        hypothesis: str,
        groupby_strategy: str,
        task: str,
        ml_model: str,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_test: np.ndarray,
        y_test: np.ndarray,
        model: BaseModel,
        interpretation: str,
        next_step: str = ""
    ) -> str:
        """
        Execute a single experiment and log results.

        Workflow:
        1. Train the model on X_train, y_train
        2. Get probability predictions on X_test (shape: n_samples)
        3. Convert probabilities to binary predictions (threshold: 0.5)
        4. Calculate metrics using evaluate_model()
        5. Create log entry with metadata and metrics
        6. Save as JSON file: {experiment_id}.json
        7. Return experiment_id

        Args:
            experiment_id (str): Unique identifier for the experiment
            phase (int): Phase number (1 or 2 in Phase 4 design)
            hypothesis (str): Hypothesis being tested
            groupby_strategy (str): Grouping strategy used (e.g., 'tail', 'dd', 'weekday')
            task (str): Task identifier (e.g., 'a' or 'b')
            ml_model (str): ML model name (e.g., 'logistic', 'xgboost')
            X_train (np.ndarray): Training feature matrix (n_samples, n_features)
            y_train (np.ndarray): Training target labels (n_samples,) with values 0 or 1
            X_test (np.ndarray): Test feature matrix (n_samples, n_features)
            y_test (np.ndarray): Test target labels (n_samples,) with values 0 or 1
            model (BaseModel): Fitted or unfitted model instance (must implement fit, predict_proba)
            interpretation (str): Interpretation of results
            next_step (str, optional): Description of next steps. Default: ""

        Returns:
            str: The experiment_id (for chaining/verification)

        Raises:
            ValueError: If model is not a BaseModel instance
        """
        if not isinstance(model, BaseModel):
            raise ValueError("model must be an instance of BaseModel")

        # Step 1: Train the model
        model.fit(X_train, y_train)

        # Step 2: Get probability predictions
        y_pred_proba = model.predict_proba(X_test)[:, 1]

        # Step 3: Convert to binary predictions
        y_pred = (y_pred_proba > 0.5).astype(int)

        # Step 4: Calculate metrics
        metrics = evaluate_model(y_test, y_pred_proba, y_pred)

        # Step 5: Create log entry
        log_data = {
            "experiment_id": experiment_id,
            "timestamp": datetime.now().isoformat(),
            "phase": phase,
            "hypothesis": hypothesis,
            "groupby_strategy": groupby_strategy,
            "task": task,
            "ml_model": ml_model,
            "metrics": metrics,
            "interpretation": interpretation,
            "next_step": next_step
        }

        # Step 6: Save as JSON
        json_file = self.results_dir / f"{experiment_id}.json"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2)

        # Step 7: Return experiment_id
        return experiment_id

    def load_all_experiments(self) -> list:
        """
        Load all experiment logs from results directory.

        Reads all .json files in the results directory and returns
        them as a list of dictionaries.

        Returns:
            list: List of experiment dictionaries, sorted by filename.
                 Each dict contains: experiment_id, timestamp, phase, hypothesis,
                 groupby_strategy, task, ml_model, metrics, interpretation, next_step

        Example:
            >>> runner = ExperimentRunner()
            >>> all_exps = runner.load_all_experiments()
            >>> for exp in all_exps:
            ...     print(exp['experiment_id'], exp['metrics']['auc'])
        """
        experiments = []
        for json_file in sorted(self.results_dir.glob("*.json")):
            with open(json_file, "r", encoding="utf-8") as f:
                exp = json.load(f)
                experiments.append(exp)
        return experiments
