"""
Test suite for metrics.py evaluation metrics module.

Tests all evaluation metric functions including:
- AUC (Area Under Curve)
- Accuracy
- Brier Score
- Precision, Recall, F1-score
- Comprehensive evaluate_model function
"""

import pytest
import numpy as np
import pandas as pd
from ml.evaluators.metrics import (
    calculate_auc,
    calculate_accuracy,
    calculate_brier_score,
    calculate_precision,
    calculate_recall,
    calculate_f1,
    evaluate_model,
)


class TestCalculateAUC:
    """Test AUC (Area Under Curve) calculation."""

    def test_auc_perfect_prediction(self):
        """Test AUC with perfect predictions."""
        y_true = np.array([0, 1, 1, 0])
        y_pred_proba = np.array([0.0, 1.0, 1.0, 0.0])
        auc = calculate_auc(y_true, y_pred_proba)
        assert auc == 1.0, "Perfect predictions should yield AUC=1.0"

    def test_auc_worst_prediction(self):
        """Test AUC with worst predictions."""
        y_true = np.array([0, 1, 1, 0])
        y_pred_proba = np.array([1.0, 0.0, 0.0, 1.0])
        auc = calculate_auc(y_true, y_pred_proba)
        assert auc == 0.0, "Worst predictions should yield AUC=0.0"

    def test_auc_random_prediction(self):
        """Test AUC with reasonable prediction probabilities."""
        y_true = np.array([0, 1, 1, 0])
        y_pred_proba = np.array([0.1, 0.8, 0.9, 0.2])
        auc = calculate_auc(y_true, y_pred_proba)
        assert 0.0 <= auc <= 1.0, "AUC should be between 0 and 1"
        assert auc > 0.5, "Good predictions should have AUC > 0.5"

    def test_auc_with_list_inputs(self):
        """Test AUC with list inputs (should handle conversion)."""
        y_true = [0, 1, 1, 0]
        y_pred_proba = [0.1, 0.8, 0.9, 0.2]
        auc = calculate_auc(y_true, y_pred_proba)
        assert 0.0 <= auc <= 1.0, "AUC should handle list inputs"

    def test_auc_larger_dataset(self):
        """Test AUC with larger dataset."""
        np.random.seed(42)
        y_true = np.random.randint(0, 2, 100)
        y_pred_proba = np.random.rand(100)
        auc = calculate_auc(y_true, y_pred_proba)
        assert 0.0 <= auc <= 1.0, "AUC should be valid for larger datasets"


class TestCalculateAccuracy:
    """Test accuracy calculation."""

    def test_accuracy_perfect(self):
        """Test accuracy with perfect predictions."""
        y_true = np.array([0, 1, 1, 0])
        y_pred = np.array([0, 1, 1, 0])
        acc = calculate_accuracy(y_true, y_pred)
        assert acc == 1.0, "Perfect predictions should yield accuracy=1.0"

    def test_accuracy_half_correct(self):
        """Test accuracy with half correct predictions."""
        y_true = np.array([0, 1, 1, 0])
        y_pred = np.array([0, 1, 0, 0])
        acc = calculate_accuracy(y_true, y_pred)
        assert acc == 0.75, "3/4 correct predictions should yield accuracy=0.75"

    def test_accuracy_all_wrong(self):
        """Test accuracy with all wrong predictions."""
        y_true = np.array([0, 1, 1, 0])
        y_pred = np.array([1, 0, 0, 1])
        acc = calculate_accuracy(y_true, y_pred)
        assert acc == 0.0, "All wrong predictions should yield accuracy=0.0"


class TestCalculateBrierScore:
    """Test Brier Score calculation."""

    def test_brier_score_perfect(self):
        """Test Brier Score with perfect predictions."""
        y_true = np.array([0, 1, 1, 0])
        y_pred_proba = np.array([0.0, 1.0, 1.0, 0.0])
        bs = calculate_brier_score(y_true, y_pred_proba)
        assert bs == 0.0, "Perfect predictions should yield Brier Score=0.0"

    def test_brier_score_worst(self):
        """Test Brier Score with worst predictions."""
        y_true = np.array([0, 1, 1, 0])
        y_pred_proba = np.array([1.0, 0.0, 0.0, 1.0])
        bs = calculate_brier_score(y_true, y_pred_proba)
        assert bs == 1.0, "Worst predictions should yield Brier Score=1.0"

    def test_brier_score_reasonable(self):
        """Test Brier Score with reasonable predictions."""
        y_true = np.array([0, 1, 1, 0])
        y_pred_proba = np.array([0.1, 0.8, 0.9, 0.2])
        bs = calculate_brier_score(y_true, y_pred_proba)
        assert 0.0 <= bs <= 1.0, "Brier Score should be between 0 and 1"
        assert bs < 0.2, "Good predictions should have low Brier Score"


class TestCalculatePrecision:
    """Test precision calculation."""

    def test_precision_perfect(self):
        """Test precision with perfect predictions."""
        y_true = np.array([0, 1, 1, 0])
        y_pred = np.array([0, 1, 1, 0])
        precision = calculate_precision(y_true, y_pred)
        assert precision == 1.0, "Perfect predictions should yield precision=1.0"

    def test_precision_partial(self):
        """Test precision with partial correct predictions."""
        y_true = np.array([0, 1, 1, 0])
        y_pred = np.array([0, 1, 0, 1])  # TP=1, FP=1
        precision = calculate_precision(y_true, y_pred)
        assert precision == 0.5, "1 TP, 1 FP should yield precision=0.5"

    def test_precision_no_positive_predictions(self):
        """Test precision with no positive predictions."""
        y_true = np.array([1, 1, 1, 1])
        y_pred = np.array([0, 0, 0, 0])
        precision = calculate_precision(y_true, y_pred)
        assert precision == 0.0, "No positive predictions should yield precision=0.0"


class TestCalculateRecall:
    """Test recall calculation."""

    def test_recall_perfect(self):
        """Test recall with perfect predictions."""
        y_true = np.array([0, 1, 1, 0])
        y_pred = np.array([0, 1, 1, 0])
        recall = calculate_recall(y_true, y_pred)
        assert recall == 1.0, "Perfect predictions should yield recall=1.0"

    def test_recall_partial(self):
        """Test recall with partial correct predictions."""
        y_true = np.array([0, 1, 1, 0])
        y_pred = np.array([0, 1, 0, 0])  # TP=1, FN=1
        recall = calculate_recall(y_true, y_pred)
        assert recall == 0.5, "1 TP, 1 FN should yield recall=0.5"

    def test_recall_all_negative(self):
        """Test recall when all predictions are negative."""
        y_true = np.array([0, 0, 0, 0])
        y_pred = np.array([0, 0, 0, 0])
        recall = calculate_recall(y_true, y_pred)
        assert recall == 0.0, "No positive labels should yield recall=0.0"


class TestCalculateF1:
    """Test F1-score calculation."""

    def test_f1_perfect(self):
        """Test F1-score with perfect predictions."""
        y_true = np.array([0, 1, 1, 0])
        y_pred = np.array([0, 1, 1, 0])
        f1 = calculate_f1(y_true, y_pred)
        assert f1 == 1.0, "Perfect predictions should yield F1=1.0"

    def test_f1_partial(self):
        """Test F1-score with partial correct predictions."""
        y_true = np.array([0, 1, 1, 0])
        y_pred = np.array([0, 1, 0, 0])  # precision=1.0, recall=0.5
        f1 = calculate_f1(y_true, y_pred)
        # F1 = 2 * (precision * recall) / (precision + recall) = 2 * (1.0 * 0.5) / 1.5 ≈ 0.667
        assert abs(f1 - 0.666666) < 0.01, "F1 should be harmonic mean of precision and recall"

    def test_f1_all_correct_negative(self):
        """Test F1-score when all predictions are negative."""
        y_true = np.array([0, 0, 0, 0])
        y_pred = np.array([0, 0, 0, 0])
        f1 = calculate_f1(y_true, y_pred)
        assert f1 == 0.0, "No positive predictions should yield F1=0.0"


class TestEvaluateModel:
    """Test comprehensive evaluate_model function."""

    def test_evaluate_model_with_proba_only(self):
        """Test evaluate_model with only probability predictions."""
        y_true = np.array([0, 1, 1, 0])
        y_pred_proba = np.array([0.1, 0.8, 0.9, 0.2])
        
        result = evaluate_model(y_true, y_pred_proba)
        
        assert isinstance(result, dict), "Should return a dictionary"
        assert "auc" in result, "Result should contain 'auc'"
        assert "brier_score" in result, "Result should contain 'brier_score'"
        assert 0.0 <= result["auc"] <= 1.0, "AUC should be valid"
        assert 0.0 <= result["brier_score"] <= 1.0, "Brier Score should be valid"

    def test_evaluate_model_with_both_predictions(self):
        """Test evaluate_model with both probability and class predictions."""
        y_true = np.array([0, 1, 1, 0])
        y_pred_proba = np.array([0.1, 0.8, 0.9, 0.2])
        y_pred = np.array([0, 1, 1, 0])
        
        result = evaluate_model(y_true, y_pred_proba, y_pred)
        
        assert isinstance(result, dict), "Should return a dictionary"
        assert "accuracy" in result, "Result should contain 'accuracy'"
        assert "precision" in result, "Result should contain 'precision'"
        assert "recall" in result, "Result should contain 'recall'"
        assert "f1" in result, "Result should contain 'f1'"
        assert result["accuracy"] == 1.0, "Perfect predictions should yield accuracy=1.0"

    def test_evaluate_model_perfect_predictions(self):
        """Test evaluate_model with perfect predictions."""
        y_true = np.array([0, 1, 1, 0, 1, 0])
        y_pred_proba = np.array([0.0, 1.0, 1.0, 0.0, 1.0, 0.0])
        y_pred = np.array([0, 1, 1, 0, 1, 0])
        
        result = evaluate_model(y_true, y_pred_proba, y_pred)
        
        assert result["auc"] == 1.0, "Perfect predictions should yield AUC=1.0"
        assert result["accuracy"] == 1.0, "Perfect predictions should yield accuracy=1.0"
        assert result["precision"] == 1.0, "Perfect predictions should yield precision=1.0"
        assert result["recall"] == 1.0, "Perfect predictions should yield recall=1.0"
        assert result["f1"] == 1.0, "Perfect predictions should yield F1=1.0"
        assert result["brier_score"] == 0.0, "Perfect predictions should yield Brier Score=0.0"

    def test_evaluate_model_returns_all_metrics(self):
        """Test that evaluate_model returns all expected metrics."""
        y_true = np.array([0, 1, 1, 0])
        y_pred_proba = np.array([0.1, 0.8, 0.9, 0.2])
        y_pred = np.array([0, 1, 1, 0])
        
        result = evaluate_model(y_true, y_pred_proba, y_pred)
        
        expected_keys = {"auc", "accuracy", "precision", "recall", "f1", "brier_score"}
        assert set(result.keys()) == expected_keys, "Should return all expected metrics"

    def test_evaluate_model_with_list_inputs(self):
        """Test evaluate_model with list inputs."""
        y_true = [0, 1, 1, 0]
        y_pred_proba = [0.1, 0.8, 0.9, 0.2]
        y_pred = [0, 1, 1, 0]
        
        result = evaluate_model(y_true, y_pred_proba, y_pred)
        
        assert isinstance(result, dict), "Should handle list inputs"
        assert len(result) > 0, "Should return metrics"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
