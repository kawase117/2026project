"""
LogisticRegressionModel - Baseline linear classification model.

This model uses sklearn's LogisticRegression as the baseline approach
for binary classification in the pachinko analyzer.
"""
import numpy as np
from sklearn.linear_model import LogisticRegression
from ml.models.base_model import BaseModel


class LogisticRegressionModel(BaseModel):
    """
    Logistic regression model for binary classification.
    
    This is the baseline model using scikit-learn's LogisticRegression.
    It provides a simple, interpretable linear classifier that can serve
    as a performance baseline for more complex models.
    
    Parameters
    ----------
    random_state : int, default=42
        Random state for reproducibility
    max_iter : int, default=1000
        Maximum number of iterations for convergence
    """
    
    def __init__(self, random_state: int = 42, max_iter: int = 1000):
        """
        Initialize the logistic regression model.
        
        Parameters
        ----------
        random_state : int, default=42
            Random state for reproducibility
        max_iter : int, default=1000
            Maximum number of iterations for the solver
        """
        self.random_state = random_state
        self.max_iter = max_iter
        self.model = LogisticRegression(
            random_state=random_state,
            max_iter=max_iter
        )
    
    def fit(self, X: np.ndarray, y: np.ndarray) -> "LogisticRegressionModel":
        """
        Fit the logistic regression model.
        
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
