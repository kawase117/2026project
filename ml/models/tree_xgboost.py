"""
XGBoostModel - Gradient Boosting Tree-based classification model.

This model uses XGBoost for non-linear binary classification in the pachinko analyzer.
XGBoost provides powerful gradient boosting with tree-based ensemble learning,
enabling capture of complex non-linear relationships in the data.
"""
import numpy as np
import xgboost as xgb
from ml.models.base_model import BaseModel


class XGBoostModel(BaseModel):
    """
    XGBoost gradient boosting model for binary classification.
    
    This model uses XGBoost's XGBClassifier for non-linear classification.
    It is more powerful than logistic regression and can capture complex
    non-linear relationships in the feature space.
    
    Parameters
    ----------
    random_state : int, default=42
        Random state for reproducibility
    max_depth : int, default=6
        Maximum depth of trees in the ensemble
    n_estimators : int, default=100
        Number of boosting rounds (trees) in the ensemble
    """
    
    def __init__(
        self,
        random_state: int = 42,
        max_depth: int = 6,
        n_estimators: int = 100
    ):
        """
        Initialize the XGBoost model.
        
        Parameters
        ----------
        random_state : int, default=42
            Random state for reproducibility
        max_depth : int, default=6
            Maximum depth of trees in the ensemble
        n_estimators : int, default=100
            Number of boosting rounds (trees)
        """
        self.random_state = random_state
        self.max_depth = max_depth
        self.n_estimators = n_estimators
        self.model = xgb.XGBClassifier(
            random_state=random_state,
            max_depth=max_depth,
            n_estimators=n_estimators,
            use_label_encoder=False,
            eval_metric='logloss',
            verbosity=0
        )
    
    def fit(self, X: np.ndarray, y: np.ndarray) -> "XGBoostModel":
        """
        Fit the XGBoost model.
        
        Parameters
        ----------
        X : np.ndarray
            Input features of shape (n_samples, n_features)
        y : np.ndarray
            Binary target labels of shape (n_samples,) with values 0 or 1
        
        Returns
        -------
        self
            Returns the fitted model instance for method chaining
        """
        self.model.fit(X, y)
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
