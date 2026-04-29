"""
Unit tests for FeatureBuilder - Feature Engineering Module
Tests Temporal (11) + Group Identification (11) = 22 features
"""

import pytest
import pandas as pd
import numpy as np
import tempfile
import sqlite3
from pathlib import Path
from ml.feature_engineering import FeatureBuilder


@pytest.fixture
def temp_test_db():
    """Create a temporary test database with sample data"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = sqlite3.connect(db_path)

        # Sample data spanning multiple dates and machines
        test_data = pd.DataFrame({
            "date": [
                "20250101", "20250102", "20250103", "20250104",
                "20250123", "20250124", "20250125",  # Around payday
                "20250215", "20250216",
                "20250301"
            ],
            "machine_number": [1, 2, 11, 12, 21, 22, 23, 31, 32, 33],
            "machine_name": ["機種A"] * 10,
            "last_digit": ["1", "2", "1", "2", "3", "4", "5", "6", "7", "8"],
            "is_zorome": [0, 0, 1, 0, 1, 0, 0, 0, 1, 1],
            "games_normalized": [100] * 10,
            "diff_coins_normalized": [1200, 800, 1500, -500, 900, 2000, 300, 1100, -200, 1800]
        })
        test_data.to_sql("machine_detailed_results", conn, if_exists="replace", index=False)
        conn.close()

        yield db_path


@pytest.fixture
def sample_df():
    """Create sample DataFrame for direct testing"""
    return pd.DataFrame({
        "date": ["20250101", "20250102", "20250103", "20250104"],
        "machine_number": [1, 2, 11, 12],
        "machine_name": ["機種A"] * 4,
        "last_digit": ["1", "2", "1", "2"],
        "is_zorome": [0, 0, 1, 0],
        "games_normalized": [100] * 4,
        "diff_coins_normalized": [1200, 800, 1500, -500]
    })


class TestFeatureBuilderInitialization:
    """Test FeatureBuilder initialization and validation"""

    def test_feature_builder_initialization(self, sample_df):
        """Test that FeatureBuilder initializes correctly with valid data"""
        fb = FeatureBuilder(sample_df)
        assert fb.df is not None
        assert len(fb.df) == 4
        assert "date_parsed" in fb.df.columns
        assert "day_of_week" in fb.df.columns

    def test_missing_required_columns(self):
        """Test that ValueError is raised when required columns are missing"""
        df_incomplete = pd.DataFrame({
            "date": ["20250101"],
            "machine_number": [1],
            # Missing: last_digit, is_zorome, games_normalized, diff_coins_normalized
        })
        with pytest.raises(ValueError, match="Missing required columns"):
            FeatureBuilder(df_incomplete)


class TestTemporalFeatures:
    """Test Temporal feature generation"""

    def test_temporal_features_shape(self, sample_df):
        """Test that temporal features have correct shape (n, 11)"""
        fb = FeatureBuilder(sample_df)
        temporal = fb._build_temporal_features()
        assert temporal.shape == (4, 11)

    def test_day_of_week_encoding(self, sample_df):
        """Test that day_of_week is correctly one-hot encoded (7 dimensions)"""
        fb = FeatureBuilder(sample_df)
        temporal = fb._build_temporal_features()
        # First 7 columns should be day_of_week one-hot
        dow_features = temporal[:, :7]
        # Each row should have exactly one 1 and six 0s
        assert np.all(dow_features.sum(axis=1) == 1)
        assert np.all((dow_features == 0) | (dow_features == 1))

    def test_month_progress_rate(self, sample_df):
        """Test that month_progress_rate is in valid range [0, 1]"""
        fb = FeatureBuilder(sample_df)
        temporal = fb._build_temporal_features()
        # Column 7 is month_progress_rate
        month_progress = temporal[:, 7]
        assert np.all(month_progress >= 0)
        assert np.all(month_progress <= 1)

    def test_payday_detection(self):
        """Test that is_payday correctly identifies days 23-27"""
        df_payday = pd.DataFrame({
            "date": ["20250122", "20250123", "20250124", "20250127", "20250128"],
            "machine_number": [1, 2, 3, 4, 5],
            "machine_name": ["機種A"] * 5,
            "last_digit": ["1"] * 5,
            "is_zorome": [0] * 5,
            "games_normalized": [100] * 5,
            "diff_coins_normalized": [1000] * 5
        })
        fb = FeatureBuilder(df_payday)
        temporal = fb._build_temporal_features()
        # Column 8 is is_payday
        is_payday = temporal[:, 8]
        expected = np.array([0, 1, 1, 1, 0])  # 23-27 are payday
        assert np.array_equal(is_payday, expected)

    def test_day_normalized_feature(self):
        """Test that day_normalized is correctly computed (1 dimension)"""
        df_days = pd.DataFrame({
            "date": ["20250101", "20250115", "20250131"],
            "machine_number": [1, 2, 3],
            "machine_name": ["機種A"] * 3,
            "last_digit": ["1"] * 3,
            "is_zorome": [0] * 3,
            "games_normalized": [100] * 3,
            "diff_coins_normalized": [1000] * 3
        })
        fb = FeatureBuilder(df_days)
        temporal = fb._build_temporal_features()
        # Column 10 (last) is day_normalized
        day_normalized = temporal[:, 10]
        expected = np.array([1/31.0, 15/31.0, 31/31.0])
        np.testing.assert_array_almost_equal(day_normalized, expected)

    def test_zorome_feature_presence(self, sample_df):
        """Test that is_zorome feature is correctly included"""
        fb = FeatureBuilder(sample_df)
        temporal = fb._build_temporal_features()
        # Structure: [dow (7), month_progress (1), is_payday (1), is_zorome (1), day_normalized (1)]
        # is_zorome is at index 9 (7 + 1 + 1 = 9)
        is_zorome = temporal[:, 9]
        # Should match the is_zorome column in original data
        expected = sample_df["is_zorome"].values.astype(float)
        assert np.array_equal(is_zorome, expected)


class TestGroupIdentificationFeatures:
    """Test Group Identification feature generation"""

    def test_group_identification_features_shape(self, sample_df):
        """Test that group identification features have correct shape (n, 11)"""
        fb = FeatureBuilder(sample_df)
        group_id = fb._build_group_identification_features()
        assert group_id.shape == (4, 11)

    def test_last_digit_encoding(self, sample_df):
        """Test that last_digit is correctly one-hot encoded (10 dimensions)"""
        fb = FeatureBuilder(sample_df)
        group_id = fb._build_group_identification_features()
        # First 10 columns are last_digit one-hot
        last_digit_features = group_id[:, :10]
        # Each row should have exactly one 1 and nine 0s
        assert np.all(last_digit_features.sum(axis=1) == 1)
        assert np.all((last_digit_features == 0) | (last_digit_features == 1))

    def test_machine_number_normalized(self, sample_df):
        """Test that machine_number is correctly normalized to [0, 1]"""
        fb = FeatureBuilder(sample_df)
        group_id = fb._build_group_identification_features()
        # Column 10 (last) is machine_number_normalized
        machine_normalized = group_id[:, 10]
        assert np.all(machine_normalized >= 0)
        assert np.all(machine_normalized <= 1)


class TestBuildFeaturesCombined:
    """Test combined feature building"""

    def test_build_features_combined_shape(self, sample_df):
        """Test that combined features have correct shape (n, 22)"""
        fb = FeatureBuilder(sample_df)
        features = fb.build_features(is_train=True)
        assert features.shape == (4, 22)

    def test_build_features_is_train_true(self, sample_df):
        """Test build_features with is_train=True"""
        fb = FeatureBuilder(sample_df)
        features = fb.build_features(is_train=True)
        assert features.shape == (4, 22)
        assert fb._scaler_state.get("fitted", False)

    def test_build_features_is_train_false(self, sample_df):
        """Test build_features with is_train=False (should use pre-fitted scaler)"""
        fb = FeatureBuilder(sample_df)
        # First fit on train data
        fb.build_features(is_train=True)
        # Then apply to test data
        features = fb.build_features(is_train=False)
        assert features.shape == (4, 22)


class TestEdgeCases:
    """Test edge cases and error handling"""

    def test_empty_dataframe(self):
        """Test that empty DataFrame returns (0, 22) shaped array"""
        df_empty = pd.DataFrame({
            "date": [],
            "machine_number": [],
            "machine_name": [],
            "last_digit": [],
            "is_zorome": [],
            "games_normalized": [],
            "diff_coins_normalized": []
        })
        fb = FeatureBuilder(df_empty)
        features = fb.build_features(is_train=True)
        assert features.shape == (0, 22)

    def test_single_row_dataframe(self):
        """Test with single row DataFrame"""
        df_single = pd.DataFrame({
            "date": ["20250101"],
            "machine_number": [1],
            "machine_name": ["機種A"],
            "last_digit": ["1"],
            "is_zorome": [0],
            "games_normalized": [100],
            "diff_coins_normalized": [1200]
        })
        fb = FeatureBuilder(df_single)
        features = fb.build_features(is_train=True)
        assert features.shape == (1, 22)

    def test_large_machine_numbers(self):
        """Test normalization with large machine numbers"""
        df_large = pd.DataFrame({
            "date": ["20250101", "20250102"],
            "machine_number": [1000, 9999],
            "machine_name": ["機種A"] * 2,
            "last_digit": ["0", "9"],
            "is_zorome": [0, 0],
            "games_normalized": [100] * 2,
            "diff_coins_normalized": [1000, 2000]
        })
        fb = FeatureBuilder(df_large)
        group_id = fb._build_group_identification_features()
        machine_normalized = group_id[:, 10]
        # Should be normalized to [0, 1]
        assert np.array_equal(machine_normalized, np.array([0.0, 1.0]))

    def test_identical_machine_numbers(self):
        """Test when all machine numbers are identical"""
        df_identical = pd.DataFrame({
            "date": ["20250101", "20250102"],
            "machine_number": [5, 5],
            "machine_name": ["機種A"] * 2,
            "last_digit": ["5", "5"],
            "is_zorome": [0, 0],
            "games_normalized": [100] * 2,
            "diff_coins_normalized": [1000, 2000]
        })
        fb = FeatureBuilder(df_identical)
        group_id = fb._build_group_identification_features()
        machine_normalized = group_id[:, 10]
        # All should be 0 when min == max
        assert np.array_equal(machine_normalized, np.array([0.0, 0.0]))


class TestDataTypes:
    """Test data type handling"""

    def test_feature_dtype_is_float(self, sample_df):
        """Test that all features are float64 dtype"""
        fb = FeatureBuilder(sample_df)
        features = fb.build_features(is_train=True)
        assert features.dtype == np.float64

    def test_one_hot_values_are_binary(self, sample_df):
        """Test that one-hot encoded features only contain 0 and 1"""
        fb = FeatureBuilder(sample_df)
        features = fb.build_features(is_train=True)
        # Features structure:
        # Temporal (11):
        #   - dow one-hot: 0-6 (7 cols)
        #   - month_progress: 7 (1 col)
        #   - is_payday: 8 (1 col)
        #   - is_zorome: 9 (1 col)
        #   - day_normalized: 10 (1 col)
        # Group ID (11):
        #   - last_digit one-hot: 11-20 (10 cols)
        #   - machine_normalized: 21 (1 col)
        # Total: 22
        #
        # One-hot columns (should be 0 or 1):
        # - dow: 0-6
        # - is_payday: 8
        # - is_zorome: 9
        # - last_digit: 11-20
        one_hot_cols = list(range(7)) + [8, 9] + list(range(11, 21))
        for col_idx in one_hot_cols:
            col_values = features[:, col_idx]
            assert np.all((col_values == 0) | (col_values == 1)), f"Column {col_idx} not binary"

        # Normalized columns (should be in [0, 1]):
        normalized_cols = [7, 10, 21]  # month_progress, day_normalized, machine_normalized
        for col_idx in normalized_cols:
            col_values = features[:, col_idx]
            assert np.all(col_values >= 0) and np.all(col_values <= 1), f"Column {col_idx} not in [0, 1]"
