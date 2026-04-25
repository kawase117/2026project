"""
Tests for BaseModel abstract base class.
"""
import numpy as np
import pytest
from ml.models.base_model import BaseModel


class TestBaseModelIsAbstract:
    """Test that BaseModel cannot be instantiated directly."""
    
    def test_base_model_is_abstract(self):
        """Verify TypeError on direct instantiation of BaseModel."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            BaseModel()


class TestBaseModelInterface:
    """Test that BaseModel interface is correctly defined."""
    
    def test_base_model_interface(self):
        """Create DummyModel implementing interface, verify methods exist."""
        
        class DummyModel(BaseModel):
            """Dummy model implementation for testing."""
            
            def fit(self, X: np.ndarray, y: np.ndarray) -> "DummyModel":
                """Fit the model."""
                self.X_ = X
                self.y_ = y
                return self
            
            def predict_proba(self, X: np.ndarray) -> np.ndarray:
                """Predict class probabilities."""
                n_samples = X.shape[0]
                # Return dummy probabilities: [class 0, class 1]
                proba = np.zeros((n_samples, 2))
                proba[:, 0] = 0.5  # 50% class 0
                proba[:, 1] = 0.5  # 50% class 1
                return proba
        
        # Should be able to instantiate DummyModel
        model = DummyModel()
        assert isinstance(model, BaseModel)
        
        # Should have all required methods
        assert hasattr(model, 'fit')
        assert hasattr(model, 'predict_proba')
        assert hasattr(model, 'predict')
        
        # fit should return self
        X = np.array([[0, 0], [1, 1]])
        y = np.array([0, 1])
        result = model.fit(X, y)
        assert result is model
        
        # predict_proba should return correct shape
        X_test = np.array([[0.5, 0.5]])
        proba = model.predict_proba(X_test)
        assert proba.shape == (1, 2)
        assert np.allclose(proba.sum(axis=1), 1.0)
        
        # predict should return binary labels
        preds = model.predict(X_test)
        assert preds.shape == (1,)
        assert np.all((preds == 0) | (preds == 1))
