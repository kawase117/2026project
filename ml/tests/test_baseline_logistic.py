"""
Tests for LogisticRegressionModel.
"""
import numpy as np
import pytest
from ml.models.baseline_logistic import LogisticRegressionModel
from ml.models.base_model import BaseModel


class TestLogisticRegressionInheritance:
    """Test that LogisticRegressionModel properly inherits from BaseModel."""
    
    def test_logistic_regression_is_base_model(self):
        """Verify LogisticRegressionModel is instance of BaseModel."""
        model = LogisticRegressionModel()
        assert isinstance(model, BaseModel)


class TestLogisticRegressionFitPredict:
    """Test fit and predict_proba methods of LogisticRegressionModel."""
    
    def test_logistic_regression_fit_predict(self):
        """Test logistic regression fit and predict_proba."""
        # Create simple linearly separable data
        X_train = np.array([[0, 0], [1, 1], [2, 2], [3, 3]], dtype=float)
        y_train = np.array([0, 0, 1, 1])
        
        # Initialize and fit model
        model = LogisticRegressionModel(random_state=42, max_iter=1000)
        result = model.fit(X_train, y_train)
        
        # fit should return self
        assert result is model
        
        # Predict probabilities on test data
        X_test = np.array([[0.5, 0.5], [2.5, 2.5]], dtype=float)
        proba = model.predict_proba(X_test)
        
        # Check shape: (n_samples, 2)
        assert proba.shape == (2, 2)
        
        # Check all probabilities are between 0 and 1
        assert np.all(proba >= 0.0)
        assert np.all(proba <= 1.0)
        
        # Check probabilities sum to 1 across classes
        assert np.allclose(proba.sum(axis=1), 1.0)


class TestLogisticRegressionPredict:
    """Test predict method (inherited from BaseModel)."""
    
    def test_logistic_regression_predict(self):
        """Test logistic regression predict labels."""
        # Create simple linearly separable data
        X_train = np.array([[0, 0], [1, 1], [2, 2], [3, 3]], dtype=float)
        y_train = np.array([0, 0, 1, 1])
        
        # Initialize and fit model
        model = LogisticRegressionModel(random_state=42, max_iter=1000)
        model.fit(X_train, y_train)
        
        # Predict labels on test data
        X_test = np.array([[0.5, 0.5], [2.5, 2.5]], dtype=float)
        preds = model.predict(X_test)
        
        # Check shape: (n_samples,)
        assert preds.shape == (2,)
        
        # Check all predictions are 0 or 1
        assert np.all((preds == 0) | (preds == 1))
        
        # Check prediction consistency: should classify low values as 0, high as 1
        assert preds[0] == 0  # [0.5, 0.5] should be close to [0, 0]
        assert preds[1] == 1  # [2.5, 2.5] should be close to [3, 3]
