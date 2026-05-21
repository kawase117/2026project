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
    average_precision_score,
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


def calculate_pr_auc(
    y_true: Union[list, np.ndarray],
    y_pred_proba: Union[list, np.ndarray],
) -> float:
    """
    Calculate Area Under the Precision-Recall Curve (PR-AUC).

    Useful for imbalanced classification problems where ranking positives
    correctly matters more than true negatives.

    Args:
        y_true: True binary labels (0 or 1).
        y_pred_proba: Predicted probabilities for the positive class.

    Returns:
        PR-AUC score (float between 0 and 1).
    """
    y_true = np.asarray(y_true)
    y_pred_proba = np.asarray(y_pred_proba)
    return average_precision_score(y_true, y_pred_proba)


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


def optimize_binary_threshold(
    y_true: Union[list, np.ndarray],
    y_pred_proba: Union[list, np.ndarray],
) -> Dict[str, float]:
    """
    Find the validation threshold that maximizes F1.

    Ties are broken by recall, then precision, then closeness to 0.5.
    """
    y_true = np.asarray(y_true)
    y_pred_proba = np.asarray(y_pred_proba)
    candidate_thresholds = np.unique(
        np.concatenate(
            [
                np.linspace(0.05, 0.95, 19),
                np.clip(y_pred_proba, 0.0, 1.0),
                np.array([0.5]),
            ]
        )
    )

    best = None
    for threshold in candidate_thresholds:
        y_pred = (y_pred_proba >= threshold).astype(int)
        precision = calculate_precision(y_true, y_pred)
        recall = calculate_recall(y_true, y_pred)
        f1 = calculate_f1(y_true, y_pred)
        sort_key = (f1, recall, precision, -abs(float(threshold) - 0.5))
        if best is None or sort_key > best["sort_key"]:
            best = {
                "sort_key": sort_key,
                "best_threshold": float(threshold),
                "optimized_precision": float(precision),
                "optimized_recall": float(recall),
                "optimized_f1": float(f1),
            }

    baseline_pred = (y_pred_proba >= 0.5).astype(int)
    assert best is not None
    best["precision_at_0_5"] = float(calculate_precision(y_true, baseline_pred))
    best["recall_at_0_5"] = float(calculate_recall(y_true, baseline_pred))
    best["f1_at_0_5"] = float(calculate_f1(y_true, baseline_pred))
    best.pop("sort_key")
    return best


def calculate_hit_at_k(
    y_true: Union[list, np.ndarray],
    y_pred_proba: Union[list, np.ndarray],
    group_ids: Union[list, np.ndarray],
    k: int,
) -> float:
    """
    Calculate groupwise Hit@K.

    For each group, sort by predicted probability descending and mark a hit
    when any positive label is included in the top-k items.
    """
    y_true = np.asarray(y_true)
    y_pred_proba = np.asarray(y_pred_proba)
    group_ids = np.asarray(group_ids)
    unique_groups = np.unique(group_ids)
    hits = []
    for group_id in unique_groups:
        mask = group_ids == group_id
        group_true = y_true[mask]
        group_proba = y_pred_proba[mask]
        if group_true.size == 0:
            continue
        top_indices = np.argsort(-group_proba)[: min(k, group_true.size)]
        hits.append(float(group_true[top_indices].max() > 0))
    if not hits:
        return 0.0
    return float(np.mean(hits))


def evaluate_model(
    y_true: Union[list, np.ndarray],
    y_pred_proba: Union[list, np.ndarray],
    y_pred: Optional[Union[list, np.ndarray]] = None,
    *,
    lift_floor: float = 1.0,
    lift_penalty_weight: float = 0.0,
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
        "pr_auc": calculate_pr_auc(y_true, y_pred_proba),
        "brier_score": calculate_brier_score(y_true, y_pred_proba),
    }

    if y_pred is not None:
        y_true_arr = np.asarray(y_true)
        result["accuracy"] = calculate_accuracy(y_true, y_pred)
        result["precision"] = calculate_precision(y_true, y_pred)
        result["recall"] = calculate_recall(y_true, y_pred)
        result["f1"] = calculate_f1(y_true, y_pred)
        result["base_rate"] = float(np.mean(y_true_arr))
        if result["base_rate"] > 0.0:
            result["precision_lift_at_0_5"] = float(result["precision"] / result["base_rate"])
        else:
            result["precision_lift_at_0_5"] = 0.0
        result["zero_recall_penalty"] = 1.0 if result["recall"] <= 0.0 else 0.0
        threshold_metrics = optimize_binary_threshold(y_true, y_pred_proba)
        result.update(threshold_metrics)
        if result["base_rate"] > 0.0:
            result["optimized_precision_lift"] = float(result["optimized_precision"] / result["base_rate"])
        else:
            result["optimized_precision_lift"] = 0.0
        result["lift_floor"] = float(lift_floor)
        result["lift_shortfall"] = max(0.0, result["lift_floor"] - result["optimized_precision_lift"])
        result["lift_penalty_weight"] = float(lift_penalty_weight)
        result["lift_penalty"] = float(result["lift_shortfall"] * result["lift_penalty_weight"])
        result["objective_score"] = (
            result["auc"] + result["pr_auc"] - result["zero_recall_penalty"] - result["lift_penalty"]
        )

    return result
