"""
Phase 6B: Target Encoding for Composite Features

This module implements target encoding to create composite features from:
- model_type (machine_name one-hot): [machine1, machine2, ...]
- machine_number (individual machine ID): normalized [0-1]
- day_of_week (曜日): Mon, Tue, ..., Sun
- is_zorome (ゾロ目フラグ): 0 or 1
- day_of_month (月内日付): 1-31

Target encoding converts categorical variables into numeric features based on target mean,
reducing dimensionality from 3100+ (one-hot) to 10 dimensions while capturing
encoding-based predictive signal.

User instruction (verbatim): "実装は HAIKU で行ってください" (2026-05-08)
"""

import numpy as np
import pandas as pd
from typing import Tuple, Optional, Dict
from sklearn.preprocessing import LabelEncoder


class TargetEncoderPhase6B:
    """
    Target encoder for Phase 6B composite features.

    Uses target mean encoding to convert high-cardinality categorical features
    into numeric features, then creates composite features (interactions) to
    capture nonlinear relationships.

    Features encoded:
    1. model_type (machine name) → numeric (target mean)
    2. machine_number → normalized [0-1]
    3. day_of_week → numeric (target mean)
    4. is_zorome → binary [0, 1]
    5. day_of_month → numeric (target mean)

    Composite features (5D):
    6. model_type × is_zorome (interaction)
    7. model_type × day_of_month (interaction)
    8. day_of_week × is_zorome (interaction)
    9. machine_number × day_of_week (interaction)
    10. machine_number^2 (nonlinear)
    """

    def __init__(self, smoothing: float = 1.0):
        """
        Initialize target encoder.

        Parameters
        ----------
        smoothing : float
            Smoothing strength for target mean encoding.
            Higher values regularize category means toward global mean.
            Typical range: 0.5 - 10.0
        """
        self.smoothing = smoothing
        self.target_means_: Dict = {}
        self.global_mean_: float = None
        self.feature_names_: list = None

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> "TargetEncoderPhase6B":
        """
        Fit target encoder on training data.

        Parameters
        ----------
        X : pd.DataFrame
            Input features with columns:
            - 'machine_name' or equivalent for model_type
            - 'machine_number'
            - 'day_of_week'
            - 'is_zorome'
            - 'day_of_month'
        y : np.ndarray
            Binary target (0 or 1)

        Returns
        -------
        self
        """
        self.global_mean_ = y.mean()

        # Convert y to pandas Series if it's a numpy array
        if isinstance(y, np.ndarray):
            y_series = pd.Series(y)
        else:
            y_series = y

        # Fit target means for categorical features
        categorical_features = ['machine_name', 'day_of_week']
        for col in categorical_features:
            if col in X.columns:
                # Compute target mean per category with smoothing
                category_means = X.groupby(col).apply(
                    lambda g: (y_series.iloc[g.index].sum() + self.smoothing * self.global_mean_) /
                              (len(g) + self.smoothing)
                )
                self.target_means_[col] = category_means.to_dict()

        # Fit day_of_month target means (treat as categorical 1-31)
        if 'day_of_month' in X.columns:
            day_of_month_means = X.groupby('day_of_month').apply(
                lambda g: (y_series.iloc[g.index].sum() + self.smoothing * self.global_mean_) /
                          (len(g) + self.smoothing)
            )
            self.target_means_['day_of_month'] = day_of_month_means.to_dict()

        return self

    def transform(self, X: pd.DataFrame) -> np.ndarray:
        """
        Transform data using target encoding + composite features.

        Returns
        -------
        np.ndarray
            Shape (n_samples, 10) with:
            - Cols 0-4: Base features (model_type, machine_number, day_of_week, is_zorome, day_of_month)
            - Cols 5-9: Composite features (interactions)
        """
        X_encoded = X.copy()
        features_list = []
        feature_names = []

        # 1. model_type (machine_name) → target-encoded
        if 'machine_name' in X.columns:
            model_type_encoded = X['machine_name'].map(
                self.target_means_.get('machine_name', {})
            ).fillna(self.global_mean_).values
            features_list.append(model_type_encoded)
            feature_names.append('model_type_encoded')

        # 2. machine_number → normalized [0-1]
        if 'machine_number' in X.columns:
            machine_num = X['machine_number'].values.astype(float)
            machine_num_min = machine_num.min() if len(machine_num) > 0 else 0
            machine_num_max = machine_num.max() if len(machine_num) > 0 else 1
            if machine_num_max > machine_num_min:
                machine_num_norm = (machine_num - machine_num_min) / (machine_num_max - machine_num_min)
            else:
                machine_num_norm = np.zeros_like(machine_num)
            features_list.append(machine_num_norm)
            feature_names.append('machine_number_normalized')

        # 3. day_of_week → target-encoded
        if 'day_of_week' in X.columns:
            dow_encoded = X['day_of_week'].map(
                self.target_means_.get('day_of_week', {})
            ).fillna(self.global_mean_).values
            features_list.append(dow_encoded)
            feature_names.append('day_of_week_encoded')

        # 4. is_zorome → binary [0, 1]
        if 'is_zorome' in X.columns:
            zorome = X['is_zorome'].values.astype(float)
            features_list.append(zorome)
            feature_names.append('is_zorome')

        # 5. day_of_month → target-encoded
        if 'day_of_month' in X.columns:
            dom_encoded = X['day_of_month'].map(
                self.target_means_.get('day_of_month', {})
            ).fillna(self.global_mean_).values
            features_list.append(dom_encoded)
            feature_names.append('day_of_month_encoded')

        # Composite features (5D)
        # 6. model_type × is_zorome
        if 'machine_name' in X.columns and 'is_zorome' in X.columns:
            interaction = model_type_encoded * zorome
            features_list.append(interaction)
            feature_names.append('model_type_x_zorome')

        # 7. model_type × day_of_month
        if 'machine_name' in X.columns and 'day_of_month' in X.columns:
            interaction = model_type_encoded * dom_encoded
            features_list.append(interaction)
            feature_names.append('model_type_x_dom')

        # 8. day_of_week × is_zorome
        if 'day_of_week' in X.columns and 'is_zorome' in X.columns:
            interaction = dow_encoded * zorome
            features_list.append(interaction)
            feature_names.append('dow_x_zorome')

        # 9. machine_number × day_of_week
        if 'machine_number' in X.columns and 'day_of_week' in X.columns:
            interaction = machine_num_norm * dow_encoded
            features_list.append(interaction)
            feature_names.append('machine_number_x_dow')

        # 10. machine_number^2 (nonlinear)
        if 'machine_number' in X.columns:
            nonlinear = machine_num_norm ** 2
            features_list.append(nonlinear)
            feature_names.append('machine_number_squared')

        self.feature_names_ = feature_names

        # Stack into (n_samples, n_features)
        X_composite = np.column_stack(features_list)
        return X_composite

    def fit_transform(self, X: pd.DataFrame, y: np.ndarray) -> np.ndarray:
        """Fit and transform in one step."""
        return self.fit(X, y).transform(X)


def create_composite_features(
    X_raw: pd.DataFrame,
    y_train: Optional[np.ndarray] = None,
    encoder: Optional[TargetEncoderPhase6B] = None
) -> np.ndarray:
    """
    Convenience function to create composite features.

    Parameters
    ----------
    X_raw : pd.DataFrame
        Raw features from prepare_data_by_groupby with model_type groupby strategy.
        Expected columns: machine_name, machine_number, day_of_week, is_zorome, day_of_month
    y_train : np.ndarray, optional
        Target labels (required if encoder is None for fitting)
    encoder : TargetEncoderPhase6B, optional
        Pre-fitted encoder (if None, will fit on current data)

    Returns
    -------
    np.ndarray
        Composite features of shape (n_samples, 10)
    """
    if encoder is None:
        if y_train is None:
            raise ValueError("Either encoder or y_train must be provided")
        encoder = TargetEncoderPhase6B(smoothing=1.0)
        encoder.fit(X_raw, y_train)

    return encoder.transform(X_raw)
