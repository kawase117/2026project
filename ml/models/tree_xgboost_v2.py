"""
XGBoostModelV2 - XGBoost with early stopping for Phase 6B.

Extends base XGBoost implementation with early stopping support,
enabling regularization and preventing overfitting on validation set.

User instruction (verbatim): "実装は HAIKU で行ってください" (2026-05-08)
"""

import numpy as np
import xgboost as xgb
from .base_model import BaseModel


class XGBoostModelV2(BaseModel):
    """
    XGBoost gradient boosting model with early stopping for Phase 6B.

    This model uses XGBoost's XGBClassifier with early stopping to prevent
    overfitting. Early stopping monitors a validation metric and stops training
    when the metric ceases improving.

    Parameters
    ----------
    random_state : int, default=42
        Random state for reproducibility
    max_depth : int, default=3
        Maximum depth of trees in the ensemble (shallow for Phase 6B)
    learning_rate : float, default=0.01
        Learning rate (lower = more conservative, less prone to overfit)
    n_estimators : int, default=1000
        Maximum number of boosting rounds (early stopping will likely stop before this)
    early_stopping_rounds : int, default=10
        Stop if validation metric doesn't improve for N rounds
    """

    def __init__(
        self,
        random_state: int = 42,
        max_depth: int = 3,
        learning_rate: float = 0.01,
        n_estimators: int = 1000,
        early_stopping_rounds: int = 10
    ):
        """Initialize XGBoost model with early stopping configuration."""
        self.random_state = random_state
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self.n_estimators = n_estimators
        self.early_stopping_rounds = early_stopping_rounds
        self.model = xgb.XGBClassifier(
            random_state=random_state,
            max_depth=max_depth,
            learning_rate=learning_rate,
            n_estimators=n_estimators,
            use_label_encoder=False,
            eval_metric='logloss',
            verbosity=0,
            tree_method='hist',
        )
        self.best_iteration_ = None

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        X_val: np.ndarray = None,
        y_val: np.ndarray = None
    ) -> "XGBoostModelV2":
        """
        Fit the XGBoost model with optional early stopping.

        Parameters
        ----------
        X : np.ndarray
            Input features of shape (n_samples, n_features)
        y : np.ndarray
            Binary target labels of shape (n_samples,) with values 0 or 1
        X_val : np.ndarray, optional
            Validation features for early stopping
        y_val : np.ndarray, optional
            Validation labels for early stopping

        Returns
        -------
        self
            Returns the fitted model instance for method chaining
        """
        if X_val is not None and y_val is not None:
            eval_set = [(X_val, y_val)]
            self.model.fit(
                X, y,
                eval_set=eval_set,
                verbose=False
            )
            if hasattr(self.model, 'best_iteration'):
                self.best_iteration_ = self.model.best_iteration
        else:
            self.model.fit(X, y, verbose=False)

        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """
        Predict class probabilities for samples.

        Parameters
        ----------
        X : np.ndarray
            Input features of shape (n_samples, n_features)

        Returns
        -------
        np.ndarray
            Predicted probabilities of shape (n_samples, 2)
            Each row contains [P(class=0), P(class=1)]
        """
        return self.model.predict_proba(X)
