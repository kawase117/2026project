"""
BaseModel abstract base class for all ML models in the pachinko analyzer.

This class defines the common interface for all prediction models:
- fit(X, y): Train the model
- predict_proba(X): Get class probabilities
- predict(X): Get binary predictions
"""
from abc import ABC, abstractmethod
import numpy as np


class BaseModel(ABC):
    """
    Abstract base class for all ML models.
    
    Defines the interface that all models must implement:
    - fit: Train the model
    - predict_proba: Get class probabilities
    - predict: Get binary predictions (0 or 1)
    """
    
    @abstractmethod
    def fit(self, X: np.ndarray, y: np.ndarray) -> "BaseModel":
        """
        Fit the model to training data.
        
        Parameters
        ----------
        X : np.ndarray
            Input features of shape (n_samples, n_features)
        y : np.ndarray
            Target labels of shape (n_samples,) with values 0 or 1
        
        Returns
        -------
        self
            Returns the fitted model instance for method chaining
        """
        pass
    
    @abstractmethod
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
        pass
    
    def predict(self, X: np.ndarray) -> np.ndarray:
        """
        Predict binary class labels based on probabilities.
        
        Parameters
        ----------
        X : np.ndarray
            Input features of shape (n_samples, n_features)
        
        Returns
        -------
        np.ndarray
            Predicted labels of shape (n_samples,) with values 0 or 1
            Predictions are: 1 if P(class=1) > 0.5, else 0
        """
        proba = self.predict_proba(X)
        return (proba[:, 1] > 0.5).astype(int)
