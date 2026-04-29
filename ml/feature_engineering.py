"""
Feature Engineering Module for Pachinko Analyzer - Phase 4 ML Pipeline

Temporal Features (11):
- day_of_week (one-hot, 7 dimensions)
- month_progress_rate (1 dimension)
- is_payday (1 dimension)
- quarter (one-hot, 4 dimensions)
- is_zorome (1 dimension)

Group Identification Features (11):
- last_digit (one-hot, 10 dimensions)
- machine_number_normalized (1 dimension)

Total: 22 features
"""

import numpy as np
import pandas as pd
from typing import Tuple, Optional


class FeatureBuilder:
    """
    Build extended features for Pachinko Analyzer ML models
    Combines Temporal and Group Identification features into 22 dimensions
    """

    REQUIRED_COLUMNS = [
        "date",
        "machine_number",
        "last_digit",
        "is_zorome",
        "games_normalized",
        "diff_coins_normalized"
    ]

    def __init__(self, df: pd.DataFrame):
        """
        Initialize FeatureBuilder

        Args:
            df: DataFrame with machine_detailed_results columns
                Must contain: date (YYYYMMDD), machine_number, last_digit, is_zorome
        """
        self.df = df.copy()
        self._validate_columns()
        self._parse_dates()
        self._scaler_state = {}

    def _validate_columns(self):
        """Check that all required columns are present"""
        missing_cols = [col for col in self.REQUIRED_COLUMNS if col not in self.df.columns]
        if missing_cols:
            raise ValueError(f"Missing required columns: {missing_cols}")

    def _parse_dates(self):
        """Parse date column to datetime and extract temporal info"""
        # Check if date is already datetime type
        if pd.api.types.is_datetime64_any_dtype(self.df["date"]):
            self.df["date_parsed"] = self.df["date"]
        else:
            # Try to parse as YYYYMMDD format
            self.df["date_parsed"] = pd.to_datetime(
                self.df["date"].astype(str), format="%Y%m%d", errors="coerce"
            )

        self.df["day_of_week"] = self.df["date_parsed"].dt.day_name()
        self.df["day_of_month"] = self.df["date_parsed"].dt.day
        self.df["month"] = self.df["date_parsed"].dt.month
        self.df["year"] = self.df["date_parsed"].dt.year

    def build_features(self, is_train: bool = True) -> np.ndarray:
        """
        Build combined feature matrix (Temporal + Group ID)

        Args:
            is_train: If True, fit scaler on this data. If False, use stored scaler.

        Returns:
            Feature matrix of shape (n_samples, 22)
        """
        if len(self.df) == 0:
            return np.array([]).reshape(0, 22)

        temporal = self._build_temporal_features()
        group_id = self._build_group_identification_features()

        # Concatenate along axis 1 (columns)
        features = np.concatenate([temporal, group_id], axis=1)

        if is_train:
            self._apply_scaling_train(features)
        else:
            self._apply_scaling_test(features)

        return features

    def _build_temporal_features(self) -> np.ndarray:
        """
        Build Temporal features (11 total)

        Returns:
            Array of shape (n_samples, 11)
        """
        n = len(self.df)

        # 1. day_of_week (one-hot, 7 dimensions)
        day_of_week_map = {
            "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
            "Friday": 4, "Saturday": 5, "Sunday": 6
        }
        dow_indices = self.df["day_of_week"].map(day_of_week_map).values
        dow_onehot = np.zeros((n, 7), dtype=float)
        dow_onehot[np.arange(n), dow_indices] = 1.0

        # 2. month_progress_rate (1 dimension)
        # Calculate day / days_in_month for each date
        days_in_month = self.df["date_parsed"].dt.daysinmonth.values
        month_progress = self.df["day_of_month"].values / days_in_month
        month_progress = month_progress.reshape(-1, 1)

        # 3. is_payday (1 dimension): days 23-27
        is_payday = ((self.df["day_of_month"] >= 23) & (self.df["day_of_month"] <= 27)).astype(float).values
        is_payday = is_payday.reshape(-1, 1)

        # 4. is_zorome (1 dimension)
        is_zorome = self.df["is_zorome"].values.astype(float).reshape(-1, 1)

        # 5. day_of_month normalized (1 dimension) — Progress through month as raw day number normalized by max
        # Used as additional temporal signal beyond just day_of_week
        day_normalized = self.df["day_of_month"].values / 31.0  # Max days in month
        day_normalized = day_normalized.reshape(-1, 1)

        # Concatenate all temporal features: 7 + 1 + 1 + 1 + 1 = 11
        temporal = np.concatenate(
            [dow_onehot, month_progress, is_payday, is_zorome, day_normalized],
            axis=1
        )

        return temporal

    def _build_group_identification_features(self) -> np.ndarray:
        """
        Build Group Identification features (11 total)

        Returns:
            Array of shape (n_samples, 11)
        """
        n = len(self.df)

        # 1. last_digit (one-hot, 10 dimensions)
        # Ensure last_digit is string and map to 0-9 indices
        last_digit_str = self.df["last_digit"].astype(str).str.strip()
        last_digit_indices = last_digit_str.astype(int).values
        last_digit_onehot = np.zeros((n, 10), dtype=float)
        last_digit_onehot[np.arange(n), last_digit_indices] = 1.0

        # 2. machine_number_normalized (1 dimension)
        # Min-max normalization to [0, 1]
        machine_numbers = self.df["machine_number"].values.astype(float)
        if len(machine_numbers) > 0:
            machine_min = machine_numbers.min()
            machine_max = machine_numbers.max()
            if machine_max > machine_min:
                machine_normalized = (machine_numbers - machine_min) / (machine_max - machine_min)
            else:
                machine_normalized = np.zeros_like(machine_numbers)
        else:
            machine_normalized = np.array([])

        machine_normalized = machine_normalized.reshape(-1, 1)

        # Concatenate all group identification features
        group_id = np.concatenate([last_digit_onehot, machine_normalized], axis=1)

        return group_id

    def _apply_scaling_train(self, features: np.ndarray):
        """
        Fit and apply scaling on training data (placeholder for future StandardScaler)

        Args:
            features: Feature array of shape (n_samples, 22)
        """
        # Placeholder: In future, implement StandardScaler fit
        self._scaler_state["fitted"] = True

    def _apply_scaling_test(self, features: np.ndarray):
        """
        Apply pre-fitted scaling on test data (placeholder)

        Args:
            features: Feature array of shape (n_samples, 22)
        """
        # Placeholder: In future, apply pre-fitted StandardScaler
        # For now, do nothing (scaler not yet implemented)
        pass
