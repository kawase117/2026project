"""
Evaluation metrics module for model performance assessment.

Provides functions to calculate various evaluation metrics including:
- AUC (Area Under ROC Curve)
- Accuracy
- Brier Score
- Precision, Recall, F1-score
- Comprehensive model evaluation

All metrics use sklearn.metrics as the underlying implementation.
"""

from typing import Optional, Dict, Union
import numpy as np
from sklearn.metrics import (
    roc_auc_score,
    accuracy_score,
    brier_score_loss,
    precision_score,
    recall_score,
    f1_score,
)


def calculate_auc(
    y_true: Union[list, np.ndarray],
    y_pred_proba: Union[list, np.ndarray],
) -> float:
    """
    Calculate Area Under the ROC Curve (AUC).

    Measures the probability that the model ranks a random positive
    example higher than a random negative example.

    Args:
        y_true: True binary labels (0 or 1).
        y_pred_proba: Predicted probabilities for the positive class.

    Returns:
        AUC score (float between 0 and 1).
    """
    y_true = np.asarray(y_true)
    y_pred_proba = np.asarray(y_pred_proba)
    return roc_auc_score(y_true, y_pred_proba)


def calculate_accuracy(
    y_true: Union[list, np.ndarray],
    y_pred: Union[list, np.ndarray],
) -> float:
    """
    Calculate classification accuracy.

    Proportion of correct predictions among the total number of predictions.

    Args:
        y_true: True binary labels (0 or 1).
        y_pred: Predicted binary labels (0 or 1).

    Returns:
        Accuracy score (float between 0 and 1).
    """
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    return accuracy_score(y_true, y_pred)


def calculate_brier_score(
    y_true: Union[list, np.ndarray],
    y_pred_proba: Union[list, np.ndarray],
) -> float:
    """
    Calculate Brier Score (mean squared error for probabilities).

    Measures the difference between predicted probabilities and actual outcomes.
    Lower is better.

    Args:
        y_true: True binary labels (0 or 1).
        y_pred_proba: Predicted probabilities for the positive class.

    Returns:
        Brier Score (float between 0 and 1).
    """
    y_true = np.asarray(y_true)
    y_pred_proba = np.asarray(y_pred_proba)
    return brier_score_loss(y_true, y_pred_proba)


def calculate_precision(
    y_true: Union[list, np.ndarray],
    y_pred: Union[list, np.ndarray],
) -> float:
    """
    Calculate precision (positive predictive value).

    Proportion of positive predictions that were actually positive.
    TP / (TP + FP)

    Args:
        y_true: True binary labels (0 or 1).
        y_pred: Predicted binary labels (0 or 1).

    Returns:
        Precision score (float between 0 and 1).
    """
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    return precision_score(y_true, y_pred, zero_division=0.0)


def calculate_recall(
    y_true: Union[list, np.ndarray],
    y_pred: Union[list, np.ndarray],
) -> float:
    """
    Calculate recall (sensitivity, true positive rate).

    Proportion of actual positives that were correctly identified.
    TP / (TP + FN)

    Args:
        y_true: True binary labels (0 or 1).
        y_pred: Predicted binary labels (0 or 1).

    Returns:
        Recall score (float between 0 and 1).
    """
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    return recall_score(y_true, y_pred, zero_division=0.0)


def calculate_f1(
    y_true: Union[list, np.ndarray],
    y_pred: Union[list, np.ndarray],
) -> float:
    """
    Calculate F1-score (harmonic mean of precision and recall).

    Balances precision and recall, useful when classes are imbalanced.
    F1 = 2 * (precision * recall) / (precision + recall)

    Args:
        y_true: True binary labels (0 or 1).
        y_pred: Predicted binary labels (0 or 1).

    Returns:
        F1 score (float between 0 and 1).
    """
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    return f1_score(y_true, y_pred, zero_division=0.0)


def evaluate_model(
    y_true: Union[list, np.ndarray],
    y_pred_proba: Union[list, np.ndarray],
    y_pred: Optional[Union[list, np.ndarray]] = None,
) -> Dict[str, float]:
    """
    Comprehensive model evaluation with multiple metrics.

    Always calculates AUC and Brier Score.
    If y_pred is provided, also calculates accuracy, precision, recall, and F1.

    Args:
        y_true: True binary labels (0 or 1).
        y_pred_proba: Predicted probabilities for the positive class.
        y_pred: Optional predicted binary labels (0 or 1).

    Returns:
        Dictionary containing:
            - auc: Area Under ROC Curve
            - brier_score: Brier Score
            - accuracy: Classification accuracy (if y_pred provided)
            - precision: Precision score (if y_pred provided)
            - recall: Recall score (if y_pred provided)
            - f1: F1-score (if y_pred provided)
    """
    result = {
        "auc": calculate_auc(y_true, y_pred_proba),
        "brier_score": calculate_brier_score(y_true, y_pred_proba),
    }

    if y_pred is not None:
        result["accuracy"] = calculate_accuracy(y_true, y_pred)
        result["precision"] = calculate_precision(y_true, y_pred)
        result["recall"] = calculate_recall(y_true, y_pred)
        result["f1"] = calculate_f1(y_true, y_pred)

    return result
