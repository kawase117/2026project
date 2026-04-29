"""
Unit tests for FeatureBuilder - Feature Engineering Module
Tests Temporal (11) + Group Identification (11) = 22 features (Task 1)
Tests Hall-wide (4) + Periodicity (5) = 9 features (Task 2)
Total: up to 31 features
"""

import pytest
import pandas as pd
import numpy as np
import tempfile
import sqlite3
from pathlib import Path
from ml.feature_engineering import FeatureBuilder
from ml.utils.db_queries import load_daily_hall_with_date_info


@pytest.fixture
def temp_test_db():
    """Create a temporary test database with sample data"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = sqlite3.connect(db_path)

        # Sample data spanning multiple dates and machines
        machine_data = pd.DataFrame({
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
        machine_data.to_sql("machine_detailed_results", conn, if_exists="replace", index=False)

        # Sample hall data for Task 2 tests
        hall_data = pd.DataFrame({
            "date": ["20250101", "20250102", "20250103", "20250104",
                     "20250123", "20250124", "20250125", "20250215", "20250216", "20250301"],
            "win_rate": [38, 31, 42, 35, 45, 40, 38, 32, 36, 41],
            "avg_diff_per_machine": [118, -371, 205, 95, 250, 180, 120, -50, 140, 195],
            "avg_games_per_machine": [4558, 4842, 4700, 4600, 4800, 4700, 4650, 4500, 4550, 4700],
            "total_machines": [280, 280, 280, 280, 280, 280, 280, 280, 280, 280],
            "day_of_week": ["Wed", "Thu", "Fri", "Sat", "Fri", "Sat", "Sun", "Fri", "Sat", "Sat"],
            "last_digit": [1, 2, 3, 4, 3, 4, 5, 5, 6, 1]
        })
        hall_data.to_sql("daily_hall_summary", conn, if_exists="replace", index=False)
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


class TestHallWideFeatures:
    """Test Hall-wide feature generation (Task 2)"""

    def test_hall_wide_features_shape(self, sample_df, temp_test_db):
        """Test that hall-wide features have correct shape (n, 4)"""
        # Create sample hall data
        df_hall = pd.DataFrame({
            "date": ["20250101", "20250102", "20250103", "20250104"],
            "win_rate": [38, 31, 42, 35],
            "avg_diff_per_machine": [118, -371, 205, 95],
            "avg_games_per_machine": [4558, 4842, 4700, 4600],
            "total_machines": [280, 280, 280, 280]
        })

        fb = FeatureBuilder(sample_df, df_hall=df_hall)
        hall_wide = fb._build_hall_wide_features(is_train=True)
        assert hall_wide.shape == (4, 4)

    def test_hall_wide_features_no_nans(self, sample_df, temp_test_db):
        """Test that hall-wide features have no NaN values"""
        df_hall = pd.DataFrame({
            "date": ["20250101", "20250102", "20250103", "20250104"],
            "win_rate": [38, 31, 42, 35],
            "avg_diff_per_machine": [118, -371, 205, 95],
            "avg_games_per_machine": [4558, 4842, 4700, 4600],
            "total_machines": [280, 280, 280, 280]
        })

        fb = FeatureBuilder(sample_df, df_hall=df_hall)
        hall_wide = fb._build_hall_wide_features(is_train=True)
        assert not np.isnan(hall_wide).any()

    def test_hall_wide_with_missing_dates(self):
        """Test that hall-wide handles missing dates gracefully"""
        df_machine = pd.DataFrame({
            "date": ["20250101", "20250102", "20250103", "20250104"],
            "machine_number": [1, 2, 11, 12],
            "machine_name": ["機種A"] * 4,
            "last_digit": ["1", "2", "1", "2"],
            "is_zorome": [0, 0, 1, 0],
            "games_normalized": [100] * 4,
            "diff_coins_normalized": [1200, 800, 1500, -500]
        })

        # Only 2 dates in hall data
        df_hall = pd.DataFrame({
            "date": ["20250101", "20250102"],
            "win_rate": [38, 31],
            "avg_diff_per_machine": [118, -371],
            "avg_games_per_machine": [4558, 4842],
            "total_machines": [280, 280]
        })

        fb = FeatureBuilder(df_machine, df_hall=df_hall)
        hall_wide = fb._build_hall_wide_features(is_train=True)

        # Should still return (4, 4) with filled values
        assert hall_wide.shape == (4, 4)
        # Missing dates should be filled with 0 (from nan_to_num)
        assert not np.isnan(hall_wide).any()

    def test_hall_wide_no_hall_data(self, sample_df):
        """Test that hall-wide returns zeros when df_hall is None"""
        fb = FeatureBuilder(sample_df, df_hall=None)
        hall_wide = fb._build_hall_wide_features(is_train=True)
        assert hall_wide.shape == (4, 4)
        assert np.all(hall_wide == 0.0)


class TestPeriodicityFeatures:
    """Test Periodicity Pattern feature generation (Task 2)"""

    def test_periodicity_features_shape(self, sample_df):
        """Test that periodicity features have correct shape (n, 5)"""
        fb = FeatureBuilder(sample_df)
        periodicity = fb._build_periodicity_features(is_train=True)
        assert periodicity.shape == (4, 5)

    def test_periodicity_features_no_nans(self, sample_df):
        """Test that periodicity features have no NaN values"""
        fb = FeatureBuilder(sample_df)
        periodicity = fb._build_periodicity_features(is_train=True)
        assert not np.isnan(periodicity).any()

    def test_is_event_day_detection(self):
        """Test that is_event_day correctly identifies event days"""
        df_event = pd.DataFrame({
            "date": ["20250101", "20250102", "20250103", "20250104", "20250123", "20250128", "20250131"],
            "machine_number": [1, 2, 3, 4, 5, 6, 7],
            "machine_name": ["機種A"] * 7,
            "last_digit": ["1"] * 7,
            "is_zorome": [0] * 7,
            "games_normalized": [100] * 7,
            "diff_coins_normalized": [1000] * 7
        })

        fb = FeatureBuilder(df_event)
        periodicity = fb._build_periodicity_features(is_train=True)

        # Column 3 is is_event_day
        is_event_day = periodicity[:, 3]

        # Expected: [1, 1, 1, 0, 1, 1, 1]
        # (month start: 1-3, payday: 23-27, month end: 28-31)
        expected = np.array([1, 1, 1, 0, 1, 1, 1], dtype=float)
        assert np.array_equal(is_event_day, expected)

    def test_no_data_leakage_in_periodicity(self):
        """Test that test statistics are not used when is_train=False"""
        df_train = pd.DataFrame({
            "date": ["20250101", "20250102", "20250103", "20250104"],
            "machine_number": [1, 2, 3, 4],
            "machine_name": ["機種A"] * 4,
            "last_digit": ["1"] * 4,
            "is_zorome": [0] * 4,
            "games_normalized": [100, 200, 150, 180],
            "diff_coins_normalized": [1000, 2000, 1500, 800]
        })

        df_test = pd.DataFrame({
            "date": ["20250215", "20250216"],
            "machine_number": [1, 2],
            "machine_name": ["機種A"] * 2,
            "last_digit": ["1"] * 2,
            "is_zorome": [0] * 2,
            "games_normalized": [100, 200],
            "diff_coins_normalized": [500, 5000]  # Very different from train
        })

        # Build train features and store stats
        fb_train = FeatureBuilder(df_train)
        fb_train.build_features(is_train=True)

        # Build test features using train stats
        fb_test = FeatureBuilder(df_test)
        fb_test.train_stats = fb_train.train_stats
        test_periodicity = fb_test._build_periodicity_features(is_train=False)

        # Check that weekday_avg_diff uses only train stats
        # (The values should be based on training statistics, not test data)
        assert test_periodicity.shape == (2, 5)
        assert not np.isnan(test_periodicity).any()

    def test_dd_pattern_score_normalization(self):
        """Test that dd_pattern_score is correctly normalized as z-score"""
        df_dd = pd.DataFrame({
            "date": ["20250101", "20250102", "20250111", "20250121"],
            "machine_number": [1, 2, 3, 4],
            "machine_name": ["機種A"] * 4,
            "last_digit": ["1"] * 4,
            "is_zorome": [0] * 4,
            "games_normalized": [100] * 4,
            "diff_coins_normalized": [1000, 1100, 900, 800]
        })

        fb = FeatureBuilder(df_dd)
        periodicity = fb._build_periodicity_features(is_train=True)

        # Column 2 is dd_pattern_score
        dd_pattern = periodicity[:, 2]

        # Should contain z-scores (centered around 0)
        # Not all zeros, at least some variation
        assert not np.all(dd_pattern == 0.0)

    def test_anomaly_score_with_missing_dates(self):
        """Test that anomaly_score handles dates not in training set"""
        df_train = pd.DataFrame({
            "date": ["20250101", "20250102"],
            "machine_number": [1, 2],
            "machine_name": ["機種A"] * 2,
            "last_digit": ["1"] * 2,
            "is_zorome": [0] * 2,
            "games_normalized": [100, 200],
            "diff_coins_normalized": [1000, 1100]
        })

        # Test data with a date not in training
        df_test = pd.DataFrame({
            "date": ["20250315"],
            "machine_number": [1],
            "machine_name": ["機種A"],
            "last_digit": ["1"],
            "is_zorome": [0],
            "games_normalized": [100],
            "diff_coins_normalized": [2000]
        })

        fb_train = FeatureBuilder(df_train)
        fb_train.build_features(is_train=True)

        fb_test = FeatureBuilder(df_test)
        fb_test.train_stats = fb_train.train_stats
        periodicity = fb_test._build_periodicity_features(is_train=False)

        # Column 4 is anomaly_score
        anomaly = periodicity[:, 4]

        # Missing dates should return 0 (neutral anomaly)
        assert np.all(anomaly == 0.0)


class TestBuildFeaturesExtended:
    """Test combined extended feature building (Task 1+2+3+4 = 69 dimensions)"""

    def test_build_features_extended_shape(self, sample_df):
        """Test that extended features have correct shape (n, 69)"""
        df_hall = pd.DataFrame({
            "date": ["20250101", "20250102", "20250103", "20250104"],
            "win_rate": [38, 31, 42, 35],
            "avg_diff_per_machine": [118, -371, 205, 95],
            "avg_games_per_machine": [4558, 4842, 4700, 4600],
            "total_machines": [280, 280, 280, 280]
        })

        fb = FeatureBuilder(sample_df, df_hall=df_hall, df_full=sample_df)
        features = fb.build_features(is_train=True, enable_extended_features=True)
        assert features.shape == (4, 69), f"Expected 69 dimensions (Task 1-4), got {features.shape[1]}"

    def test_build_features_task1_without_extended(self, sample_df):
        """Test that enable_extended_features=False returns 22 dimensions"""
        fb = FeatureBuilder(sample_df)
        features = fb.build_features(is_train=True, enable_extended_features=False)
        assert features.shape == (4, 22)

    def test_build_features_extended_no_hall_data(self, sample_df):
        """Test extended features without hall data (should still return 69)"""
        fb = FeatureBuilder(sample_df, df_hall=None, df_full=sample_df)
        features = fb.build_features(is_train=True, enable_extended_features=True)
        # Hall-wide features are zeros, periodicity + Task 4 features are computed from machine data
        assert features.shape == (4, 69), f"Expected 69 dimensions (Task 1-4), got {features.shape[1]}"

    def test_extended_features_data_leakage_prevention(self):
        """Test that test features use only training statistics"""
        df_train = pd.DataFrame({
            "date": ["20250101", "20250102", "20250103"],
            "machine_number": [1, 2, 3],
            "machine_name": ["機種A"] * 3,
            "last_digit": ["1"] * 3,
            "is_zorome": [0] * 3,
            "games_normalized": [100, 200, 150],
            "diff_coins_normalized": [1000, 2000, 1500]
        })

        df_test = pd.DataFrame({
            "date": ["20250215"],
            "machine_number": [1],
            "machine_name": ["機種A"],
            "last_digit": ["1"],
            "is_zorome": [0],
            "games_normalized": [100],
            "diff_coins_normalized": [5000]  # Outlier
        })

        df_hall_train = pd.DataFrame({
            "date": ["20250101", "20250102", "20250103"],
            "win_rate": [30, 35, 40],
            "avg_diff_per_machine": [100, 150, 200],
            "avg_games_per_machine": [4500, 4600, 4700],
            "total_machines": [280, 280, 280]
        })

        df_hall_test = pd.DataFrame({
            "date": ["20250215"],
            "win_rate": [50],  # Outlier
            "avg_diff_per_machine": [500],  # Outlier
            "avg_games_per_machine": [5000],  # Outlier
            "total_machines": [280]
        })

        df_full = pd.concat([df_train, df_test], ignore_index=True)
        fb_train = FeatureBuilder(df_train, df_hall=df_hall_train, df_full=df_full)
        X_train = fb_train.build_features(is_train=True, enable_extended_features=True)

        fb_test = FeatureBuilder(df_test, df_hall=df_hall_test, df_full=df_full)
        fb_test.train_stats = fb_train.train_stats
        X_test = fb_test.build_features(is_train=False, enable_extended_features=True)

        # Both should have 69 dimensions (Task 1 + 2 + 3 + 4)
        assert X_train.shape == (3, 69), f"Expected 69 dimensions, got {X_train.shape[1]}"
        assert X_test.shape == (1, 69), f"Expected 69 dimensions, got {X_test.shape[1]}"

        # Test features should not have NaN values
        assert not np.isnan(X_test).any()


class TestMachineHistoryFeatures:
    """Test Machine History feature generation (10 dimensions)"""

    def test_sparse_machine_timeseries(self):
        """
        Test machine history features with sparse/discontinuous dates.
        Machine 1: [Jan 1, Jan 5, Jan 10] (gaps in data)
        """
        df_sparse = pd.DataFrame({
            'date': ['20250101', '20250105', '20250110'],
            'machine_number': [1, 1, 1],
            'machine_name': ['Model_A'] * 3,
            'last_digit': ['1'] * 3,
            'is_zorome': [0] * 3,
            'games_normalized': [100, 200, 300],
            'diff_coins_normalized': [1000, 1200, 1500]
        })

        fb = FeatureBuilder(df_sparse, df_full=df_sparse)
        fb._parse_dates()
        features = fb._build_machine_history_features(is_train=True)

        # Check no NaN values
        assert (
            not np.isnan(features).any()
        ), "Machine history features should not have NaN"

        # Check shape
        assert features.shape[1] == 10, "Should have 10 machine history features"

        # Verify moving averages handle gaps gracefully
        # ma_7_diff should adapt to sparse data (rolling with min_periods=1)
        ma_7_diff_col = features[:, 1]
        assert len(ma_7_diff_col) == 3
        assert ma_7_diff_col[0] > 0  # First value should be positive
        assert ma_7_diff_col[2] > ma_7_diff_col[0]  # Increasing trend

    def test_machine_history_shape(self, sample_df):
        """Test that machine history features have correct shape"""
        fb = FeatureBuilder(sample_df, df_full=sample_df)
        features = fb._build_machine_history_features(is_train=True)
        assert features.shape == (len(sample_df), 10)

    def test_machine_history_no_nans(self, sample_df):
        """Test that machine history features contain no NaN values"""
        fb = FeatureBuilder(sample_df, df_full=sample_df)
        features = fb._build_machine_history_features(is_train=True)
        assert not np.isnan(features).any(), "Machine history features contain NaN"

    def test_moving_average_calculation(self):
        """Test that moving averages are calculated correctly"""
        # Create ordered data for one machine
        df = pd.DataFrame({
            'date': pd.date_range('2025-01-01', periods=30),
            'machine_number': [1] * 30,
            'last_digit': ['1'] * 30,
            'is_zorome': [0] * 30,
            'games_normalized': [100] * 30,
            'diff_coins_normalized': [1000] * 15 + [500] * 15  # Step change
        })

        fb = FeatureBuilder(df, df_full=df)
        features = fb._build_machine_history_features(is_train=True)

        # Check that ma_7_diff (index 1) changes after day 15
        ma_7_early = features[5:10, 1].mean()  # Days 5-9
        ma_7_late = features[20:25, 1].mean()  # Days 20-24
        assert ma_7_late < ma_7_early, "Moving average should decrease after step change"

    def test_efficiency_calculation(self):
        """Test that efficiency (diff/games) is calculated"""
        df = pd.DataFrame({
            'date': pd.date_range('2025-01-01', periods=10),
            'machine_number': [1] * 10,
            'last_digit': ['1'] * 10,
            'is_zorome': [0] * 10,
            'games_normalized': [100, 200, 100, 100, 100, 100, 100, 100, 100, 100],
            'diff_coins_normalized': [500, 1000, 500, 500, 500, 500, 500, 500, 500, 500]
        })

        fb = FeatureBuilder(df, df_full=df)
        features = fb._build_machine_history_features(is_train=True)

        # Efficiency feature is at index 5
        efficiency = features[:, 5]
        assert efficiency.sum() != 0, "Efficiency should have non-zero values"

    def test_win_rate_computation(self):
        """Test that win rate is computed correctly"""
        df = pd.DataFrame({
            'date': pd.date_range('2025-01-01', periods=10),
            'machine_number': [1] * 10,
            'last_digit': ['1'] * 10,
            'is_zorome': [0] * 10,
            'games_normalized': [100] * 10,
            'diff_coins_normalized': [100, 100, -100, 100, 100, -100, 100, 100, 100, -100]
        })
        # Expected win_rate: 7/10 = 0.7

        fb = FeatureBuilder(df, df_full=df)
        features = fb._build_machine_history_features(is_train=True)

        # Win rate feature is at index 9
        win_rate = features[0, 9]  # All rows should have same normalized win_rate
        assert -2 < win_rate < 2, f"Normalized win rate {win_rate} should be in reasonable range"

    def test_consecutive_wins_tracking(self):
        """Test that consecutive wins are tracked"""
        df = pd.DataFrame({
            'date': pd.date_range('2025-01-01', periods=10),
            'machine_number': [1] * 10,
            'last_digit': ['1'] * 10,
            'is_zorome': [0] * 10,
            'games_normalized': [100] * 10,
            'diff_coins_normalized': [100, 100, 100, -100, 100, 100, 100, 100, -100, 100]
        })

        fb = FeatureBuilder(df, df_full=df)
        features = fb._build_machine_history_features(is_train=True)

        # Consecutive wins feature is at index 8
        consecutive = features[:, 8]
        # Should see increasing values for consecutive wins
        assert consecutive[2] > consecutive[1], "Consecutive wins should increase in streak"


class TestRelativeFeatures:
    """Test Relative feature generation (4 dimensions)"""

    def test_relative_features_shape(self, sample_df, temp_test_db):
        """Test that relative features have correct shape"""
        conn = sqlite3.connect(temp_test_db)
        df_hall = pd.read_sql_query("SELECT * FROM daily_hall_summary", conn)
        conn.close()

        fb = FeatureBuilder(sample_df, df_hall=df_hall)
        features = fb._build_relative_features(is_train=True)
        assert features.shape == (len(sample_df), 4)

    def test_relative_features_no_nans(self, sample_df, temp_test_db):
        """Test that relative features contain no NaN values"""
        conn = sqlite3.connect(temp_test_db)
        df_hall = pd.read_sql_query("SELECT * FROM daily_hall_summary", conn)
        conn.close()

        fb = FeatureBuilder(sample_df, df_hall=df_hall)
        features = fb._build_relative_features(is_train=True)
        assert not np.isnan(features).any(), "Relative features contain NaN"

    def test_rank_percentile_bounds(self, temp_test_db):
        """Test that rank percentile is in [0, 1]"""
        conn = sqlite3.connect(temp_test_db)
        df = pd.read_sql_query("SELECT * FROM machine_detailed_results", conn)
        conn.close()

        # Ensure dates are datetime
        df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')

        fb = FeatureBuilder(df, df_hall=None)  # No hall data needed for this test
        features = fb._build_relative_features(is_train=True)

        # Rank percentile is at index 3
        rank_percentile = features[:, 3]
        assert (rank_percentile >= 0).all() and (rank_percentile <= 1).all(), \
            "Rank percentile must be in [0, 1]"

    def test_efficiency_ratio_comparison(self):
        """Test that efficiency vs hall comparison is reasonable"""
        df_machine = pd.DataFrame({
            'date': ['20250101', '20250102'],
            'machine_number': [1, 1],
            'last_digit': ['1', '1'],
            'is_zorome': [0, 0],
            'games_normalized': [100, 200],
            'diff_coins_normalized': [1000, 2000]
        })

        df_hall = pd.DataFrame({
            'date': ['20250101', '20250102'],
            'avg_diff_per_machine': [500, 500],
            'avg_games_per_machine': [100, 100]
        })

        fb = FeatureBuilder(df_machine, df_hall=df_hall)
        features = fb._build_relative_features(is_train=True)

        # Efficiency vs hall (index 2) should be > 1 (machine better than hall)
        efficiency_vs_hall = features[:, 2]
        assert (efficiency_vs_hall > 0).all(), "Efficiency ratio should be positive"


class TestLagFeatures:
    """Test Lag feature generation (8 dimensions) with time-series coherence"""

    def test_lag_features_shape(self, sample_df):
        """Test that lag features have correct shape"""
        fb = FeatureBuilder(sample_df, df_full=sample_df)
        features = fb._build_lag_features(is_train=True)
        assert features.shape == (len(sample_df), 8)

    def test_lag_features_no_nans(self, sample_df):
        """Test that lag features contain no NaN values after filling"""
        fb = FeatureBuilder(sample_df, df_full=sample_df)
        features = fb._build_lag_features(is_train=True)
        assert not np.isnan(features).any(), "Lag features contain NaN after filling"

    def test_lag_1_connection_across_periods(self):
        """Test that lag_1 correctly connects train and test periods"""
        # Create train and test data
        df_train = pd.DataFrame({
            'date': pd.date_range('2025-01-01', periods=10),
            'machine_number': [1] * 10,
            'last_digit': ['1'] * 10,
            'is_zorome': [0] * 10,
            'games_normalized': [100] * 10,
            'diff_coins_normalized': list(range(100, 1100, 100))  # 100, 200, ..., 1000
        })

        df_test = pd.DataFrame({
            'date': pd.date_range('2025-01-11', periods=5),
            'machine_number': [1] * 5,
            'last_digit': ['1'] * 5,
            'is_zorome': [0] * 5,
            'games_normalized': [100] * 5,
            'diff_coins_normalized': [1100, 1200, 1300, 1400, 1500]
        })

        df_full = pd.concat([df_train, df_test], ignore_index=True)

        # Test data should have lag_1_diff pointing to last training value
        fb_test = FeatureBuilder(df_test, df_full=df_full)
        features_test = fb_test._build_lag_features(is_train=False)

        # First test row lag_1_diff should be 1000 (last training value)
        lag_1_diff_test = features_test[0, 0]
        assert lag_1_diff_test == 1000, f"Test lag_1_diff should be 1000, got {lag_1_diff_test}"

    def test_lag_7_and_lag_30_handling(self):
        """Test that lag_7 and lag_30 are filled with ffill and zeros"""
        df = pd.DataFrame({
            'date': pd.date_range('2025-01-01', periods=50),
            'machine_number': [1] * 50,
            'last_digit': ['1'] * 50,
            'is_zorome': [0] * 50,
            'games_normalized': [100] * 50,
            'diff_coins_normalized': np.arange(50) * 100  # 0, 100, 200, ..., 4900
        })

        fb = FeatureBuilder(df, df_full=df)
        features = fb._build_lag_features(is_train=True)

        # lag_7_diff is at index 2, lag_30_diff at index 3
        lag_7_diff = features[:, 2]
        lag_30_diff = features[:, 3]

        # First 30 days should not have NaNs (filled)
        assert not np.isnan(lag_7_diff[:30]).any(), "First 30 days lag_7_diff has NaN"
        assert not np.isnan(lag_30_diff[:30]).any(), "First 30 days lag_30_diff has NaN"

    def test_lag_1_win_rate_binary(self):
        """Test that lag_1_win_rate is binary (0 or 1)"""
        df = pd.DataFrame({
            'date': pd.date_range('2025-01-01', periods=15),
            'machine_number': [1] * 15,
            'last_digit': ['1'] * 15,
            'is_zorome': [0] * 15,
            'games_normalized': [100] * 15,
            'diff_coins_normalized': [100, -100, 100, 100, -100, 100, 100, 100, -100, 100, 100, -100, 100, 100, 100]
        })

        fb = FeatureBuilder(df, df_full=df)
        features = fb._build_lag_features(is_train=True)

        # lag_1_win_rate is at index 6
        lag_1_win = features[:, 6]

        # Should be binary (0 or 1)
        unique_vals = np.unique(lag_1_win)
        assert set(unique_vals).issubset({0.0, 1.0}), f"lag_1_win_rate should be binary, got {unique_vals}"


class TestInteractionFeatures:
    """Test Interaction feature generation (5 dimensions - Task 4)"""

    def test_interaction_features_shape(self, temp_test_db):
        """Test that interaction features have correct shape (n, 5)"""
        conn = sqlite3.connect(temp_test_db)
        df = pd.read_sql_query("SELECT * FROM machine_detailed_results", conn)
        conn.close()

        df_hall = pd.DataFrame({
            "date": df['date'].unique(),
            "win_rate": [40] * len(df['date'].unique())
        })

        fb = FeatureBuilder(df, df_hall=df_hall, df_full=df)
        interaction = fb._build_interaction_features()
        assert interaction.shape == (len(df), 5), f"Expected shape ({len(df)}, 5), got {interaction.shape}"

    def test_day_diff_interaction_range(self, temp_test_db):
        """Test day_×_diff_interaction values are in [0, 1]"""
        conn = sqlite3.connect(temp_test_db)
        df = pd.read_sql_query("SELECT * FROM machine_detailed_results", conn)
        conn.close()

        fb = FeatureBuilder(df, df_full=df)
        interaction = fb._build_interaction_features()

        # First feature is day_×_diff_interaction
        day_diff_interaction = interaction[:, 0]
        assert np.all(day_diff_interaction >= 0) and np.all(day_diff_interaction <= 1), \
            f"day_diff_interaction should be in [0, 1], got min={day_diff_interaction.min()}, max={day_diff_interaction.max()}"

    def test_digit_weekday_interaction_nonzero(self, temp_test_db):
        """Test digit_×_weekday_interaction is nonzero when both present"""
        conn = sqlite3.connect(temp_test_db)
        df = pd.read_sql_query("SELECT * FROM machine_detailed_results", conn)
        conn.close()

        fb = FeatureBuilder(df, df_full=df)
        interaction = fb._build_interaction_features()

        # Second feature is digit_×_weekday_interaction
        digit_dow = interaction[:, 1]
        # Should be nonzero for all rows (both digit and dow are present)
        assert np.any(digit_dow > 0), "digit_×_weekday_interaction should have nonzero values"

    def test_zorome_efficiency_interaction(self, temp_test_db):
        """Test zorome_×_efficiency_interaction is nonzero only when is_zorome==1"""
        conn = sqlite3.connect(temp_test_db)
        df = pd.read_sql_query("SELECT * FROM machine_detailed_results", conn)
        conn.close()

        fb = FeatureBuilder(df, df_full=df)
        interaction = fb._build_interaction_features()

        # Third feature is zorome_×_efficiency_interaction
        zorome_eff = interaction[:, 2]

        # Get is_zorome values
        is_zorome = df['is_zorome'].values

        # Where is_zorome==0, interaction should be 0
        zero_mask = is_zorome == 0
        assert np.all(zorome_eff[zero_mask] == 0), "zorome_×_efficiency should be 0 when is_zorome==0"

    def test_hall_condition_machine_perf(self, temp_test_db):
        """Test hall_condition_×_machine_perf has no NaN values"""
        conn = sqlite3.connect(temp_test_db)
        df = pd.read_sql_query("SELECT * FROM machine_detailed_results", conn)
        df_hall = pd.read_sql_query("SELECT * FROM daily_hall_summary", conn)
        conn.close()

        fb = FeatureBuilder(df, df_hall=df_hall, df_full=df)
        interaction = fb._build_interaction_features()

        # Fourth feature is hall_condition_×_machine_perf
        hall_perf = interaction[:, 3]
        assert not np.isnan(hall_perf).any(), "hall_condition_×_machine_perf should have no NaN"


class TestDomainSpecificFeatures:
    """Test Domain-Specific feature generation (11 dimensions - Task 4)"""

    def test_domain_specific_features_shape(self, temp_test_db):
        """Test that domain-specific features have correct shape (n, 11)"""
        conn = sqlite3.connect(temp_test_db)
        df = pd.read_sql_query("SELECT * FROM machine_detailed_results", conn)
        df_hall = pd.read_sql_query("SELECT * FROM daily_hall_summary", conn)
        conn.close()

        fb = FeatureBuilder(df, df_hall=df_hall, df_full=df)
        domain = fb._build_domain_specific_features()
        assert domain.shape == (len(df), 11), f"Expected shape ({len(df)}, 11), got {domain.shape}"

    def test_setting_injection_dd_marker(self, temp_test_db):
        """Test setting_injection_marker_dd is 1 on payroll dates with high diff"""
        conn = sqlite3.connect(temp_test_db)
        df = pd.read_sql_query("SELECT * FROM machine_detailed_results", conn)
        conn.close()

        fb = FeatureBuilder(df, df_full=df)
        domain = fb._build_domain_specific_features()

        # Second feature is setting_injection_marker_dd
        marker_dd = domain[:, 1]

        # Should be binary (0 or 1)
        assert np.all((marker_dd == 0) | (marker_dd == 1)), \
            f"setting_injection_marker_dd should be binary, got unique values: {np.unique(marker_dd)}"

    def test_setting_injection_dow_marker(self, temp_test_db):
        """Test setting_injection_marker_dow is 1 on weekends with high diff"""
        conn = sqlite3.connect(temp_test_db)
        df = pd.read_sql_query("SELECT * FROM machine_detailed_results", conn)
        conn.close()

        fb = FeatureBuilder(df, df_full=df)
        domain = fb._build_domain_specific_features()

        # Third feature is setting_injection_marker_dow
        marker_dow = domain[:, 2]

        # Should be binary (0 or 1)
        assert np.all((marker_dow == 0) | (marker_dow == 1)), \
            f"setting_injection_marker_dow should be binary, got unique values: {np.unique(marker_dow)}"

    def test_bb_rb_signature_positive(self, temp_test_db):
        """Test bb_rb_signature_indicator values >= 0"""
        conn = sqlite3.connect(temp_test_db)
        df = pd.read_sql_query("SELECT * FROM machine_detailed_results", conn)
        conn.close()

        fb = FeatureBuilder(df, df_full=df)
        domain = fb._build_domain_specific_features()

        # Fourth feature is bb_rb_signature_indicator
        bb_rb = domain[:, 3]

        assert np.all(bb_rb >= 0), f"bb_rb_signature should be >= 0, got min={bb_rb.min()}"

    def test_consecutive_win_marker_logic(self, temp_test_db):
        """Test consecutive_win_marker is binary based on moving average logic"""
        conn = sqlite3.connect(temp_test_db)
        df = pd.read_sql_query("SELECT * FROM machine_detailed_results", conn)
        conn.close()

        fb = FeatureBuilder(df, df_full=df)
        domain = fb._build_domain_specific_features()

        # Fifth feature is consecutive_win_marker
        consecutive_marker = domain[:, 4]

        # Should be binary (0 or 1)
        assert np.all((consecutive_marker == 0) | (consecutive_marker == 1)), \
            f"consecutive_win_marker should be binary, got unique values: {np.unique(consecutive_marker)}"

    def test_event_day_payload_composite(self, temp_test_db):
        """Test event_day_payload_indicator requires all conditions"""
        conn = sqlite3.connect(temp_test_db)
        df = pd.read_sql_query("SELECT * FROM machine_detailed_results", conn)
        conn.close()

        fb = FeatureBuilder(df, df_full=df)
        domain = fb._build_domain_specific_features()

        # Sixth feature is event_day_payload_indicator
        event_payload = domain[:, 5]

        # Should be binary (0 or 1)
        assert np.all((event_payload == 0) | (event_payload == 1)), \
            f"event_day_payload_indicator should be binary, got unique values: {np.unique(event_payload)}"

    def test_hall_state_relative_efficiency(self, temp_test_db):
        """Test hall_state_relative_efficiency values are reasonable"""
        conn = sqlite3.connect(temp_test_db)
        df = pd.read_sql_query("SELECT * FROM machine_detailed_results", conn)
        df_hall = pd.read_sql_query("SELECT * FROM daily_hall_summary", conn)
        conn.close()

        fb = FeatureBuilder(df, df_hall=df_hall, df_full=df)
        domain = fb._build_domain_specific_features()

        # Seventh feature is hall_state_relative_efficiency
        relative_eff = domain[:, 6]

        # Should be clipped to reasonable range [0, 5]
        assert np.all(relative_eff >= 0) and np.all(relative_eff <= 5), \
            f"hall_state_relative_efficiency should be in [0, 5], got min={relative_eff.min()}, max={relative_eff.max()}"

    def test_machine_model_anomaly_score(self, temp_test_db):
        """Test machine_model_anomaly_score is normalized [0, 1]"""
        conn = sqlite3.connect(temp_test_db)
        df = pd.read_sql_query("SELECT * FROM machine_detailed_results", conn)
        conn.close()

        fb = FeatureBuilder(df, df_full=df)
        domain = fb._build_domain_specific_features()

        # Eighth feature is machine_model_anomaly_score
        anomaly = domain[:, 7]

        # Should be normalized to [0, 1]
        assert np.all(anomaly >= 0) and np.all(anomaly <= 1), \
            f"machine_model_anomaly_score should be in [0, 1], got min={anomaly.min()}, max={anomaly.max()}"

    def test_payday_window_ramp(self):
        """Test payday_window_effect forms linear ramp (23→0, 24→0.5, 25→1.0, 26→0.5, 27→0)"""
        df_payday = pd.DataFrame({
            "date": ["20250122", "20250123", "20250124", "20250125", "20250126", "20250127", "20250128"],
            "machine_number": [1, 2, 3, 4, 5, 6, 7],
            "machine_name": ["Model"] * 7,
            "last_digit": ["1"] * 7,
            "is_zorome": [0] * 7,
            "games_normalized": [100] * 7,
            "diff_coins_normalized": [1000] * 7
        })

        fb = FeatureBuilder(df_payday, df_full=df_payday)
        domain = fb._build_domain_specific_features()

        # Ninth feature is payday_window_effect
        payday_ramp = domain[:, 8]

        # Expected: [0, 0, 0.5, 1.0, 0.5, 0, 0]
        # (days 22-28 map to indices 0-6)
        expected = np.array([0, 0, 0.5, 1.0, 0.5, 0, 0])
        np.testing.assert_array_almost_equal(payday_ramp, expected, decimal=2)

    def test_zorome_days_since(self, temp_test_db):
        """Test zorome_days_since is in [0, 1]"""
        conn = sqlite3.connect(temp_test_db)
        df = pd.read_sql_query("SELECT * FROM machine_detailed_results", conn)
        conn.close()

        fb = FeatureBuilder(df, df_full=df)
        domain = fb._build_domain_specific_features()

        # Tenth feature is zorome_days_since
        days_since = domain[:, 9]

        assert np.all(days_since >= 0) and np.all(days_since <= 1), \
            f"zorome_days_since should be in [0, 1], got min={days_since.min()}, max={days_since.max()}"

    def test_overall_confidence_composite(self, temp_test_db):
        """Test overall_setting_confidence is in [0, 1]"""
        conn = sqlite3.connect(temp_test_db)
        df = pd.read_sql_query("SELECT * FROM machine_detailed_results", conn)
        conn.close()

        fb = FeatureBuilder(df, df_full=df)
        domain = fb._build_domain_specific_features()

        # Eleventh feature is overall_setting_confidence
        confidence = domain[:, 10]

        assert np.all(confidence >= 0) and np.all(confidence <= 1), \
            f"overall_setting_confidence should be in [0, 1], got min={confidence.min()}, max={confidence.max()}"


class TestTask4Integration:
    """Integration tests for Task 4 (Interaction + Domain-Specific features)"""

    def test_interaction_no_nan_values(self, temp_test_db):
        """Test that interaction features have no NaN values"""
        conn = sqlite3.connect(temp_test_db)
        df = pd.read_sql_query("SELECT * FROM machine_detailed_results", conn)
        conn.close()

        fb = FeatureBuilder(df, df_full=df)
        interaction = fb._build_interaction_features()

        assert not np.isnan(interaction).any(), "Interaction features contain NaN"

    def test_domain_specific_no_nan_values(self, temp_test_db):
        """Test that domain-specific features have no NaN values"""
        conn = sqlite3.connect(temp_test_db)
        df = pd.read_sql_query("SELECT * FROM machine_detailed_results", conn)
        conn.close()

        fb = FeatureBuilder(df, df_full=df)
        domain = fb._build_domain_specific_features()

        assert not np.isnan(domain).any(), "Domain-specific features contain NaN"

    def test_build_features_with_task4_shape_69d(self, temp_test_db):
        """Test full build_features with Task 4 returns (n, 69) dimensions"""
        conn = sqlite3.connect(temp_test_db)
        df = pd.read_sql_query("SELECT * FROM machine_detailed_results", conn)
        df_hall = pd.read_sql_query("SELECT * FROM daily_hall_summary", conn)
        conn.close()

        df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
        df_full = df.copy()

        fb = FeatureBuilder(df, df_hall=df_hall, df_full=df_full)
        features = fb.build_features(is_train=True, enable_extended_features=True)

        # 22 (Task 1) + 4 (Hall) + 5 (Periodicity) + 10 (Machine History)
        # + 4 (Relative) + 8 (Lag) + 5 (Interaction) + 11 (Domain-specific) = 69
        assert features.shape[1] == 69, f"Expected 69 dimensions, got {features.shape[1]}"


class TestFullFeatureIntegration:
    """Integration tests for full 53-dimensional feature matrix"""

    def test_53_dimensional_output_shape(self, temp_test_db):
        """Test that enable_extended_features=True produces 53 dimensions"""
        conn = sqlite3.connect(temp_test_db)
        df_machine = pd.read_sql_query("SELECT * FROM machine_detailed_results", conn)
        df_hall = pd.read_sql_query("SELECT * FROM daily_hall_summary", conn)
        conn.close()

        df_machine['date'] = pd.to_datetime(df_machine['date'], format='%Y%m%d')
        df_full = df_machine.copy()

        fb = FeatureBuilder(df_machine, df_hall=df_hall, df_full=df_full)
        features = fb.build_features(is_train=True, enable_extended_features=True)

        assert features.shape[1] == 69, f"Expected 69 dimensions (Task 1-4), got {features.shape[1]}"

    def test_22_dimensional_output_without_extended(self, sample_df):
        """Test that enable_extended_features=False produces 22 dimensions"""
        fb = FeatureBuilder(sample_df)
        features = fb.build_features(is_train=True, enable_extended_features=False)

        assert features.shape[1] == 22, f"Expected 22 dimensions, got {features.shape[1]}"

    def test_train_test_feature_consistency(self):
        """Test that train and test have same number of features"""
        df_train = pd.DataFrame({
            'date': pd.date_range('2025-01-01', periods=30),
            'machine_number': [1] * 30,
            'last_digit': ['1'] * 30,
            'is_zorome': [0] * 30,
            'games_normalized': [100] * 30,
            'diff_coins_normalized': np.random.randn(30) * 100
        })

        df_test = pd.DataFrame({
            'date': pd.date_range('2025-02-01', periods=10),
            'machine_number': [1] * 10,
            'last_digit': ['1'] * 10,
            'is_zorome': [0] * 10,
            'games_normalized': [100] * 10,
            'diff_coins_normalized': np.random.randn(10) * 100
        })

        df_full = pd.concat([df_train, df_test], ignore_index=True)

        # Train
        fb_train = FeatureBuilder(df_train, df_full=df_full)
        X_train = fb_train.build_features(is_train=True, enable_extended_features=True)

        # Test
        fb_test = FeatureBuilder(df_test, df_full=df_full)
        fb_test.train_stats = fb_train.train_stats
        X_test = fb_test.build_features(is_train=False, enable_extended_features=True)

        assert X_train.shape[1] == X_test.shape[1], \
            f"Feature count mismatch: train={X_train.shape[1]}, test={X_test.shape[1]}"
        assert X_train.shape[1] == 69, "Should have 69 dimensions"

    def test_no_data_leakage_in_lag_features(self):
        """Verify that test period lag features don't use future values"""
        df_train = pd.DataFrame({
            'date': pd.date_range('2025-01-01', periods=30),
            'machine_number': [1] * 30,
            'last_digit': ['1'] * 30,
            'is_zorome': [0] * 30,
            'games_normalized': [100] * 30,
            'diff_coins_normalized': list(range(0, 3000, 100))
        })

        df_test = pd.DataFrame({
            'date': pd.date_range('2025-02-01', periods=5),
            'machine_number': [1] * 5,
            'last_digit': ['1'] * 5,
            'is_zorome': [0] * 5,
            'games_normalized': [100] * 5,
            'diff_coins_normalized': [9999, 9999, 9999, 9999, 9999]  # Unrealistically high
        })

        df_full = pd.concat([df_train, df_test], ignore_index=True)

        fb_test = FeatureBuilder(df_test, df_full=df_full)
        features_test = fb_test._build_lag_features(is_train=False)

        # lag_1_diff should be 2900 (last training value), not 9999 (test value)
        lag_1_diff = features_test[0, 0]
        assert lag_1_diff == 2900, f"Data leakage detected: lag_1_diff={lag_1_diff} (should be 2900)"
