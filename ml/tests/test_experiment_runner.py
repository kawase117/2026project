"""
Tests for ExperimentRunner - Experiment execution and logging engine.

Tests cover:
- Experiment execution with model training
- Metrics evaluation and recording
- JSON log file creation and structure
- Metadata persistence (hypothesis, interpretation, next steps)
- Multi-experiment log retrieval
"""
import tempfile
import pytest
import numpy as np
import json
from pathlib import Path
from ml.experiments.experiment_runner import ExperimentRunner
from ml.models.baseline_logistic import LogisticRegressionModel


class TestExperimentRunnerExecution:
    """Test basic experiment execution and logging."""

    def test_experiment_runner_execution(self):
        """ExperimentRunner が実験を実行し、ログを記録するか"""
        with tempfile.TemporaryDirectory() as tmpdir:
            X_train = np.array([[0, 0], [1, 1], [2, 2], [3, 3]])
            y_train = np.array([0, 0, 1, 1])
            X_test = np.array([[0.5, 0.5], [2.5, 2.5]])
            y_test = np.array([0, 1])

            runner = ExperimentRunner(results_dir=tmpdir)
            model = LogisticRegressionModel(random_state=42)

            exp_id = runner.run_experiment(
                experiment_id="test_exp_001",
                phase=1,
                hypothesis="Test hypothesis",
                groupby_strategy="tail",
                task="a",
                ml_model="logistic",
                X_train=X_train,
                y_train=y_train,
                X_test=X_test,
                y_test=y_test,
                model=model,
                interpretation="Test interpretation",
                next_step="Test next step"
            )

            # ログファイルが作成されたか
            log_file = Path(tmpdir) / f"{exp_id}.json"
            assert log_file.exists()

            # ログの内容を検証
            with open(log_file, "r", encoding="utf-8") as f:
                log_data = json.load(f)

            assert log_data["experiment_id"] == exp_id
            assert log_data["phase"] == 1
            assert "metrics" in log_data
            assert "auc" in log_data["metrics"]
            assert "accuracy" in log_data["metrics"]


class TestExperimentRunnerMetrics:
    """Test that metrics are correctly calculated and stored."""

    def test_metrics_in_log_file(self):
        """Verify all expected metrics are present in log file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            X_train = np.array([[0, 0], [1, 1], [2, 2], [3, 3]])
            y_train = np.array([0, 0, 1, 1])
            X_test = np.array([[0.5, 0.5], [2.5, 2.5]])
            y_test = np.array([0, 1])

            runner = ExperimentRunner(results_dir=tmpdir)
            model = LogisticRegressionModel(random_state=42)

            runner.run_experiment(
                experiment_id="test_metrics_001",
                phase=1,
                hypothesis="Metrics test",
                groupby_strategy="dd",
                task="b",
                ml_model="logistic",
                X_train=X_train,
                y_train=y_train,
                X_test=X_test,
                y_test=y_test,
                model=model,
                interpretation="Interpretation",
                next_step=""
            )

            log_file = Path(tmpdir) / "test_metrics_001.json"
            with open(log_file, "r", encoding="utf-8") as f:
                log_data = json.load(f)

            metrics = log_data["metrics"]

            # Check all expected metrics are present
            assert "auc" in metrics
            assert "brier_score" in metrics
            assert "accuracy" in metrics
            assert "precision" in metrics
            assert "recall" in metrics
            assert "f1" in metrics

            # Check metrics are numeric
            for metric_value in metrics.values():
                assert isinstance(metric_value, (int, float))
                assert 0 <= metric_value <= 1


class TestExperimentRunnerMetadata:
    """Test that experiment metadata is correctly stored."""

    def test_experiment_metadata_storage(self):
        """Verify experiment metadata (hypothesis, interpretation, etc.) is stored."""
        with tempfile.TemporaryDirectory() as tmpdir:
            X_train = np.array([[0, 0], [1, 1], [2, 2], [3, 3]])
            y_train = np.array([0, 0, 1, 1])
            X_test = np.array([[0.5, 0.5], [2.5, 2.5]])
            y_test = np.array([0, 1])

            runner = ExperimentRunner(results_dir=tmpdir)
            model = LogisticRegressionModel(random_state=42)

            hypothesis_text = "High-configuration machines are more likely to be placed on weekends"
            interpretation_text = "Found significant correlation in dd=25 data"
            next_step_text = "Investigate machine_type effect"

            runner.run_experiment(
                experiment_id="test_metadata_001",
                phase=2,
                hypothesis=hypothesis_text,
                groupby_strategy="weekday",
                task="a",
                ml_model="logistic",
                X_train=X_train,
                y_train=y_train,
                X_test=X_test,
                y_test=y_test,
                model=model,
                interpretation=interpretation_text,
                next_step=next_step_text
            )

            log_file = Path(tmpdir) / "test_metadata_001.json"
            with open(log_file, "r", encoding="utf-8") as f:
                log_data = json.load(f)

            # Verify metadata fields
            assert log_data["hypothesis"] == hypothesis_text
            assert log_data["interpretation"] == interpretation_text
            assert log_data["next_step"] == next_step_text
            assert log_data["phase"] == 2
            assert log_data["groupby_strategy"] == "weekday"
            assert log_data["task"] == "a"
            assert log_data["ml_model"] == "logistic"


class TestExperimentRunnerTimestamp:
    """Test that timestamp is recorded in log."""

    def test_timestamp_recorded(self):
        """Verify timestamp is recorded in ISO format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            X_train = np.array([[0, 0], [1, 1], [2, 2], [3, 3]])
            y_train = np.array([0, 0, 1, 1])
            X_test = np.array([[0.5, 0.5], [2.5, 2.5]])
            y_test = np.array([0, 1])

            runner = ExperimentRunner(results_dir=tmpdir)
            model = LogisticRegressionModel(random_state=42)

            runner.run_experiment(
                experiment_id="test_timestamp_001",
                phase=1,
                hypothesis="Test",
                groupby_strategy="tail",
                task="a",
                ml_model="logistic",
                X_train=X_train,
                y_train=y_train,
                X_test=X_test,
                y_test=y_test,
                model=model,
                interpretation="Test",
                next_step=""
            )

            log_file = Path(tmpdir) / "test_timestamp_001.json"
            with open(log_file, "r", encoding="utf-8") as f:
                log_data = json.load(f)

            # Verify timestamp exists and is ISO format
            assert "timestamp" in log_data
            timestamp = log_data["timestamp"]
            assert isinstance(timestamp, str)
            assert "T" in timestamp  # ISO format includes T


class TestExperimentRunnerReturnValue:
    """Test that run_experiment returns the experiment ID."""

    def test_run_experiment_return_value(self):
        """Verify run_experiment returns the experiment_id."""
        with tempfile.TemporaryDirectory() as tmpdir:
            X_train = np.array([[0, 0], [1, 1], [2, 2], [3, 3]])
            y_train = np.array([0, 0, 1, 1])
            X_test = np.array([[0.5, 0.5], [2.5, 2.5]])
            y_test = np.array([0, 1])

            runner = ExperimentRunner(results_dir=tmpdir)
            model = LogisticRegressionModel(random_state=42)

            exp_id = runner.run_experiment(
                experiment_id="test_return_001",
                phase=1,
                hypothesis="Test",
                groupby_strategy="tail",
                task="a",
                ml_model="logistic",
                X_train=X_train,
                y_train=y_train,
                X_test=X_test,
                y_test=y_test,
                model=model,
                interpretation="Test",
                next_step=""
            )

            assert exp_id == "test_return_001"


class TestExperimentRunnerLoadAllExperiments:
    """Test loading multiple experiments."""

    def test_load_all_experiments(self):
        """Verify load_all_experiments loads all experiments correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            X_train = np.array([[0, 0], [1, 1], [2, 2], [3, 3]])
            y_train = np.array([0, 0, 1, 1])
            X_test = np.array([[0.5, 0.5], [2.5, 2.5]])
            y_test = np.array([0, 1])

            runner = ExperimentRunner(results_dir=tmpdir)
            model = LogisticRegressionModel(random_state=42)

            # Run 3 experiments
            for i in range(3):
                runner.run_experiment(
                    experiment_id=f"test_load_{i:03d}",
                    phase=1,
                    hypothesis=f"Hypothesis {i}",
                    groupby_strategy="tail",
                    task="a",
                    ml_model="logistic",
                    X_train=X_train,
                    y_train=y_train,
                    X_test=X_test,
                    y_test=y_test,
                    model=model,
                    interpretation=f"Interpretation {i}",
                    next_step=""
                )

            # Load all experiments
            experiments = runner.load_all_experiments()

            # Verify count
            assert len(experiments) == 3

            # Verify each has expected fields
            for exp in experiments:
                assert "experiment_id" in exp
                assert "timestamp" in exp
                assert "phase" in exp
                assert "metrics" in exp


class TestExperimentRunnerDefaultResultsDir:
    """Test that default results directory is created correctly."""

    def test_default_results_directory(self):
        """Verify default results_dir is created if not specified."""
        runner = ExperimentRunner(results_dir=None)

        # Should have created a results directory path
        assert runner.results_dir.exists()
        assert runner.results_dir.is_dir()
