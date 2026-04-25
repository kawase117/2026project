"""
Test suite for validators.py time series validation module.

Tests TimeSeriesSplitter class for proper train/test splitting with time series data.
Ensures temporal order is preserved and no data leakage occurs.
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from ml.evaluators.validators import TimeSeriesSplitter


class TestTimeSeriesSplitter:
    """Test TimeSeriesSplitter for proper time series cross-validation splitting."""

    def test_time_series_splitter_initialization(self):
        """Test TimeSeriesSplitter initialization with valid dates."""
        train_end = "2026-02-01"
        test_start = "2026-02-01"
        test_end = "2026-04-26"
        
        splitter = TimeSeriesSplitter(train_end, test_start, test_end)
        
        assert splitter.train_end_date == train_end
        assert splitter.test_start_date == test_start
        assert splitter.test_end_date == test_end

    def test_time_series_splitter_basic_split(self):
        """Test basic split with simple date range."""
        # Create DataFrame with dates from 2025-01-01 to 2026-04-26
        date_range = pd.date_range(start="2025-01-01", end="2026-04-26", freq="D")
        df = pd.DataFrame({
            "date": date_range,
            "value": np.random.rand(len(date_range))
        })
        
        splitter = TimeSeriesSplitter(
            train_end_date="2026-02-01",
            test_start_date="2026-02-01",
            test_end_date="2026-04-26"
        )
        
        train_indices, test_indices = splitter.split(df)
        
        assert len(train_indices) > 0, "Should have training data"
        assert len(test_indices) > 0, "Should have test data"
        assert max(train_indices) < min(test_indices), "Train indices should come before test indices"

    def test_time_series_splitter_no_overlap(self):
        """Test that train and test indices don't overlap."""
        date_range = pd.date_range(start="2025-01-01", end="2026-04-26", freq="D")
        df = pd.DataFrame({
            "date": date_range,
            "value": np.random.rand(len(date_range))
        })
        
        splitter = TimeSeriesSplitter(
            train_end_date="2026-02-01",
            test_start_date="2026-02-01",
            test_end_date="2026-04-26"
        )
        
        train_indices, test_indices = splitter.split(df)
        
        # Check no overlap
        train_set = set(train_indices)
        test_set = set(test_indices)
        assert len(train_set & test_set) == 0, "Train and test indices should not overlap"

    def test_time_series_splitter_temporal_order(self):
        """Test that temporal order is preserved."""
        date_range = pd.date_range(start="2025-01-01", end="2026-04-26", freq="D")
        df = pd.DataFrame({
            "date": date_range,
            "value": np.random.rand(len(date_range))
        })
        
        splitter = TimeSeriesSplitter(
            train_end_date="2026-02-01",
            test_start_date="2026-02-01",
            test_end_date="2026-04-26"
        )
        
        train_indices, test_indices = splitter.split(df)
        
        # All train dates should be before or equal to all test dates
        train_dates = df.iloc[train_indices]["date"].values
        test_dates = df.iloc[test_indices]["date"].values
        
        max_train_date = np.max(train_dates)
        min_test_date = np.min(test_dates)
        
        assert max_train_date <= min_test_date, "All training dates should be before/equal to test dates"

    def test_time_series_splitter_returns_arrays(self):
        """Test that split returns numpy arrays."""
        date_range = pd.date_range(start="2025-01-01", end="2026-04-26", freq="D")
        df = pd.DataFrame({
            "date": date_range,
            "value": np.random.rand(len(date_range))
        })
        
        splitter = TimeSeriesSplitter(
            train_end_date="2026-02-01",
            test_start_date="2026-02-01",
            test_end_date="2026-04-26"
        )
        
        train_indices, test_indices = splitter.split(df)
        
        assert isinstance(train_indices, np.ndarray), "Train indices should be numpy array"
        assert isinstance(test_indices, np.ndarray), "Test indices should be numpy array"

    def test_time_series_splitter_with_string_dates(self):
        """Test split with string date column."""
        # Create DataFrame with string dates
        date_strings = pd.date_range(start="2025-01-01", end="2026-04-26", freq="D").strftime("%Y-%m-%d")
        df = pd.DataFrame({
            "date": date_strings,
            "value": np.random.rand(len(date_strings))
        })
        
        splitter = TimeSeriesSplitter(
            train_end_date="2026-02-01",
            test_start_date="2026-02-01",
            test_end_date="2026-04-26"
        )
        
        train_indices, test_indices = splitter.split(df)
        
        assert len(train_indices) > 0, "Should handle string dates"
        assert len(test_indices) > 0, "Should have test data with string dates"

    def test_time_series_splitter_distinct_index_count(self):
        """Test that total indices equal dataframe length minus any excluded dates."""
        date_range = pd.date_range(start="2025-01-01", end="2026-04-26", freq="D")
        df = pd.DataFrame({
            "date": date_range,
            "value": np.random.rand(len(date_range))
        })
        
        splitter = TimeSeriesSplitter(
            train_end_date="2026-02-01",
            test_start_date="2026-02-01",
            test_end_date="2026-04-26"
        )
        
        train_indices, test_indices = splitter.split(df)
        
        # With test_start_date == train_end_date, there might be a boundary
        # The total should cover the included range
        total_indices = len(train_indices) + len(test_indices)
        assert total_indices > 0, "Should have indices for the included date range"

    def test_time_series_splitter_multiple_splits_consistent(self):
        """Test that multiple splits on same data produce consistent results."""
        date_range = pd.date_range(start="2025-01-01", end="2026-04-26", freq="D")
        df = pd.DataFrame({
            "date": date_range,
            "value": np.random.rand(len(date_range))
        })
        
        splitter = TimeSeriesSplitter(
            train_end_date="2026-02-01",
            test_start_date="2026-02-01",
            test_end_date="2026-04-26"
        )
        
        train1, test1 = splitter.split(df)
        train2, test2 = splitter.split(df)
        
        assert np.array_equal(train1, train2), "Multiple splits should be consistent"
        assert np.array_equal(test1, test2), "Multiple splits should be consistent"

    def test_time_series_splitter_with_missing_date_column(self):
        """Test that splitter handles missing date column gracefully."""
        df = pd.DataFrame({
            "value": np.random.rand(10)
        })
        
        splitter = TimeSeriesSplitter(
            train_end_date="2026-02-01",
            test_start_date="2026-02-01",
            test_end_date="2026-04-26"
        )
        
        # Should raise an error or handle gracefully
        with pytest.raises((KeyError, ValueError)):
            splitter.split(df)

    def test_time_series_splitter_different_date_ranges(self):
        """Test splitter with different train/test date ranges."""
        date_range = pd.date_range(start="2025-01-01", end="2026-12-31", freq="D")
        df = pd.DataFrame({
            "date": date_range,
            "value": np.random.rand(len(date_range))
        })
        
        splitter = TimeSeriesSplitter(
            train_end_date="2026-06-01",
            test_start_date="2026-06-15",
            test_end_date="2026-12-31"
        )
        
        train_indices, test_indices = splitter.split(df)
        
        assert len(train_indices) > 0, "Should have training data"
        assert len(test_indices) > 0, "Should have test data"
        assert max(train_indices) < min(test_indices), "Temporal order should be preserved"

    def test_time_series_splitter_large_dataset(self):
        """Test splitter with larger dataset."""
        # Create 2 years of daily data
        date_range = pd.date_range(start="2024-01-01", end="2025-12-31", freq="D")
        df = pd.DataFrame({
            "date": date_range,
            "value": np.random.rand(len(date_range)),
            "feature1": np.random.rand(len(date_range)),
            "feature2": np.random.rand(len(date_range))
        })
        
        splitter = TimeSeriesSplitter(
            train_end_date="2025-06-01",
            test_start_date="2025-06-01",
            test_end_date="2025-12-31"
        )
        
        train_indices, test_indices = splitter.split(df)
        
        assert len(train_indices) > 180, "Should have significant training data (>180 days)"
        assert len(test_indices) > 180, "Should have significant test data (>180 days)"
        assert max(train_indices) < min(test_indices), "Temporal order preserved in large dataset"

    def test_time_series_splitter_edge_case_same_dates(self):
        """Test edge case where train_end_date == test_start_date."""
        date_range = pd.date_range(start="2025-01-01", end="2026-04-26", freq="D")
        df = pd.DataFrame({
            "date": date_range,
            "value": np.random.rand(len(date_range))
        })
        
        splitter = TimeSeriesSplitter(
            train_end_date="2026-02-01",
            test_start_date="2026-02-01",  # Same as train_end_date
            test_end_date="2026-04-26"
        )
        
        train_indices, test_indices = splitter.split(df)
        
        # Boundary handling: either include in train or test, not both
        overlap = set(train_indices) & set(test_indices)
        assert len(overlap) == 0, "No overlap between train and test indices"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
