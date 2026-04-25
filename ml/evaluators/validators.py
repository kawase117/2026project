"""
Time series validation module for proper train/test splitting.

Provides TimeSeriesSplitter class that ensures temporal order is preserved
and no data leakage occurs when splitting time series data.
"""

from typing import Tuple
import numpy as np
import pandas as pd


class TimeSeriesSplitter:
    """
    Time series cross-validator that respects temporal order.

    Splits time series data into training and test sets based on date ranges,
    ensuring that all training data comes before all test data chronologically.
    This prevents data leakage that can occur with standard cross-validation
    when dealing with time-dependent data.

    Attributes:
        train_end_date (str): End date of training period (format: YYYY-MM-DD).
        test_start_date (str): Start date of test period (format: YYYY-MM-DD).
        test_end_date (str): End date of test period (format: YYYY-MM-DD).
    """

    def __init__(
        self,
        train_end_date: str,
        test_start_date: str,
        test_end_date: str,
    ) -> None:
        """
        Initialize TimeSeriesSplitter with date boundaries.

        Args:
            train_end_date: End date of training period (format: YYYY-MM-DD).
            test_start_date: Start date of test period (format: YYYY-MM-DD).
            test_end_date: End date of test period (format: YYYY-MM-DD).
        """
        self.train_end_date = train_end_date
        self.test_start_date = test_start_date
        self.test_end_date = test_end_date

    def split(
        self,
        df: pd.DataFrame,
        date_column: str = "date",
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Split DataFrame into training and test indices based on date ranges.

        Converts the date column to datetime format, creates boolean masks for
        train and test periods, and returns indices where train indices < test
        indices to preserve temporal order.

        Args:
            df: DataFrame containing time series data with a date column.
            date_column: Name of the date column (default: "date").

        Returns:
            Tuple of (train_indices, test_indices) as numpy arrays.
                - train_indices: Indices of rows in training period.
                - test_indices: Indices of rows in test period.
                - max(train_indices) < min(test_indices) is guaranteed.

        Raises:
            KeyError: If date_column does not exist in DataFrame.
            ValueError: If date conversion fails.
        """
        # Check that date column exists
        if date_column not in df.columns:
            raise KeyError(f"Column '{date_column}' not found in DataFrame")

        # Convert date column to datetime
        try:
            dates = pd.to_datetime(df[date_column])
        except Exception as e:
            raise ValueError(f"Failed to convert '{date_column}' to datetime: {e}")

        # Convert boundary dates to datetime
        train_end = pd.to_datetime(self.train_end_date)
        test_start = pd.to_datetime(self.test_start_date)
        test_end = pd.to_datetime(self.test_end_date)

        # Create boolean masks for train and test periods
        # Training period: dates <= train_end_date
        train_mask = dates <= train_end

        # Test period: dates > test_start_date AND dates <= test_end_date
        # Note: using > instead of >= to avoid overlap when train_end_date == test_start_date
        test_mask = (dates > test_start) & (dates <= test_end)

        # Get indices as numpy arrays
        train_indices = np.where(train_mask)[0]
        test_indices = np.where(test_mask)[0]

        return train_indices, test_indices
