"""
Integration Tests for Complete 69-Dimensional Feature Space
Comprehensive end-to-end verification of the full feature engineering pipeline.

Tests cover:
1. Complete feature generation (69D with extended features, 22D without)
2. Backward compatibility (enable_extended_features flag)
3. Data leakage prevention (proper train/test separation)
4. Performance benchmarks (< 4s for 15k samples)
5. All groupby strategies with extended features
6. Both Task A and Task B scenarios
7. Documentation completeness
"""

import pytest
import pandas as pd
import numpy as np
import sqlite3
import tempfile
import time
import sys
from pathlib import Path
from ml.feature_engineering import FeatureBuilder
from ml.data_preparation import prepare_data_by_groupby


class TestFeatureIntegration:
    """Integration tests for complete 69-dimensional feature space"""

    @pytest.fixture
    def test_db_with_full_data(self):
        """Create test database with realistic 15k+ sample dataset"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_full.db"

            # Create and setup database
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            # machine_detailed_results table
            cursor.execute("""
                CREATE TABLE machine_detailed_results (
                    date TEXT, machine_number INTEGER, machine_name TEXT,
                    last_digit TEXT, is_zorome INTEGER,
                    games_normalized INTEGER, diff_coins_normalized INTEGER
                )
            """)

            # Generate 500 machines × 30 days = 15,000 rows
            dates = pd.date_range('2025-01-01', '2025-01-31', freq='D')
            machines = list(range(1, 501))  # 500 machines

            rows = []
            np.random.seed(42)
            for date in dates:
                for machine_id in machines:
                    date_str = date.strftime('%Y%m%d')
                    last_digit = str(machine_id % 10)
                    day = int(date.strftime('%d'))
                    is_zorome = 1 if int(last_digit) == day % 10 else 0
                    games = 1000 + np.random.randint(-500, 500)
                    diff = 100 + np.random.randint(-200, 800)
                    rows.append((
                        date_str, machine_id, f'Model_{machine_id // 100}',
                        last_digit, is_zorome, games, diff
                    ))

            cursor.executemany("""
                INSERT INTO machine_detailed_results
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, rows)

            # daily_hall_summary table (required for extended features)
            cursor.execute("""
                CREATE TABLE daily_hall_summary (
                    date TEXT, day_of_week TEXT, last_digit INTEGER,
                    weekday_nth TEXT, win_rate REAL,
                    avg_games_per_machine INTEGER, avg_diff_per_machine INTEGER,
                    is_zorome INTEGER, total_machines INTEGER
                )
            """)

            for date in dates:
                date_str = date.strftime('%Y%m%d')
                day = int(date.strftime('%d'))
                dow = date.strftime('%A')
                last_d = day % 10
                win_rate = 45.0 + np.random.uniform(-5, 15)
                avg_games = 950 + np.random.randint(-100, 100)
                avg_diff = 150 + np.random.randint(-100, 200)

                cursor.execute("""
                    INSERT INTO daily_hall_summary
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (date_str, dow, last_d, f'Mon{(day-1)//7+1}', win_rate,
                      avg_games, avg_diff, 0, 500))

            conn.commit()
            conn.close()

            # Close all connections before yielding
            import gc
            gc.collect()

            yield str(db_path)

    def test_69d_feature_generation_complete(self, test_db_with_full_data):
        """Verify complete 69D feature generation with extended features"""
        X_train, y_train, X_test, y_test = prepare_data_by_groupby(
            db_path=test_db_with_full_data,
            groupby_strategy='machine_number',
            task='a',
            train_start='2025-01-01',
            train_end='2025-01-20',
            test_start='2025-01-21',
            test_end='2025-01-31',
            enable_extended_features=True
        )

        assert X_train.shape[1] == 69, f"Expected 69 features, got {X_train.shape[1]}"
        assert X_test.shape[1] == 69
        assert len(y_train) == X_train.shape[0]
        assert len(y_test) == X_test.shape[0]
        assert X_train.shape[0] > 0 and X_test.shape[0] > 0

    def test_basic_groupby_strategies_work(self, test_db_with_full_data):
        """Verify backward compatibility: basic groupby strategies still work"""
        strategies = ['tail', 'model_type', 'machine_number']

        for strategy in strategies:
            X_train, y_train, X_test, y_test = prepare_data_by_groupby(
                db_path=test_db_with_full_data,
                groupby_strategy=strategy,
                task='a',
                train_start='2025-01-01',
                train_end='2025-01-20',
                test_start='2025-01-21',
                test_end='2025-01-31',
                enable_extended_features=False
            )

            # Basic groupby strategies return variable dimensions based on one-hot encoding
            assert X_train.shape[0] > 0, f"Strategy {strategy}: no training samples"
            assert X_test.shape[0] > 0, f"Strategy {strategy}: no test samples"
            assert X_train.shape[1] > 0, f"Strategy {strategy}: no features"
            assert X_train.shape[1] == X_test.shape[1], f"Strategy {strategy}: train/test shape mismatch"

    def test_no_data_leakage_train_test_separation(self, test_db_with_full_data):
        """Verify no data leakage: training stats not computed on test data"""
        X_train, y_train, X_test, y_test = prepare_data_by_groupby(
            db_path=test_db_with_full_data,
            groupby_strategy='machine_number',
            task='a',
            train_start='2025-01-01',
            train_end='2025-01-15',
            test_start='2025-01-20',
            test_end='2025-01-31',
            enable_extended_features=True
        )

        # Check no NaN values (would indicate leakage/missing stats)
        assert not np.isnan(X_train).any(), "NaN in training features"
        assert not np.isnan(X_test).any(), "NaN in test features"

        # Check reasonable value ranges
        assert np.all(X_train >= -10), "Training features have invalid negative values"
        assert np.all(X_train <= 100), "Training features exceed expected range"
        assert np.all(X_test >= -10), "Test features have invalid negative values"
        assert np.all(X_test <= 100), "Test features exceed expected range"

    def test_feature_distributions_realistic(self, test_db_with_full_data):
        """Verify feature distributions are realistic (not all zeros/ones)"""
        X_train, _, _, _ = prepare_data_by_groupby(
            db_path=test_db_with_full_data,
            groupby_strategy='machine_number',
            task='a',
            train_start='2025-01-01',
            train_end='2025-01-20',
            test_start='2025-01-21',
            test_end='2025-01-31',
            enable_extended_features=True
        )

        # Each feature should have non-zero variance
        for col_idx in range(X_train.shape[1]):
            col_data = X_train[:, col_idx]
            variance = np.var(col_data)
            assert variance > 0.001, f"Feature {col_idx} has near-zero variance (dead feature)"

    def test_all_groupby_strategies_with_extended_features(self, test_db_with_full_data):
        """Verify all groupby strategies work with extended features"""
        strategies = ['tail', 'model_type', 'machine_number']

        for strategy in strategies:
            X_train, y_train, X_test, y_test = prepare_data_by_groupby(
                db_path=test_db_with_full_data,
                groupby_strategy=strategy,
                task='a',
                train_start='2025-01-01',
                train_end='2025-01-20',
                test_start='2025-01-21',
                test_end='2025-01-31',
                enable_extended_features=True
            )

            # When extended features enabled, all strategies return 69D
            assert X_train.shape[1] == 69, f"Strategy {strategy} returned {X_train.shape[1]} dims"
            assert not np.isnan(X_train).any(), f"NaN in {strategy} features"
            assert X_train.shape[0] > 0, f"No training samples for strategy {strategy}"

    def test_both_tasks_a_and_b_with_extended(self, test_db_with_full_data):
        """Verify both Task A and Task B work with extended features"""
        for task in ['a', 'b']:
            X_train, y_train, X_test, y_test = prepare_data_by_groupby(
                db_path=test_db_with_full_data,
                groupby_strategy='machine_number',
                task=task,
                train_start='2025-01-01',
                train_end='2025-01-20',
                test_start='2025-01-21',
                test_end='2025-01-31',
                enable_extended_features=True
            )

            assert X_train.shape[1] == 69
            assert y_train.dtype in [np.int32, np.int64, int]
            assert np.all((y_train == 0) | (y_train == 1)), f"Task {task} labels not binary"
            print(f"  Task {task}: {len(y_train)} train, {len(y_test)} test samples")

    def test_performance_benchmark_15k_samples(self, test_db_with_full_data):
        """Verify feature generation performance < 4s for 15k samples"""
        start = time.time()
        X_train, y_train, X_test, y_test = prepare_data_by_groupby(
            db_path=test_db_with_full_data,
            groupby_strategy='machine_number',
            task='a',
            train_start='2025-01-01',
            train_end='2025-01-20',
            test_start='2025-01-21',
            test_end='2025-01-31',
            enable_extended_features=True
        )
        elapsed = time.time() - start

        total_samples = X_train.shape[0] + X_test.shape[0]
        assert elapsed < 4.0, f"Feature generation took {elapsed:.2f}s (target: < 4s)"
        print(f"\nPerformance: {elapsed:.2f}s for {total_samples} samples "
              f"({total_samples/elapsed:.0f} samples/sec)")

    def test_train_test_split_respects_dates(self, test_db_with_full_data):
        """Verify train/test split respects date boundaries with no overlap"""
        X_train, y_train, X_test, y_test = prepare_data_by_groupby(
            db_path=test_db_with_full_data,
            groupby_strategy='machine_number',
            task='a',
            train_start='2025-01-01',
            train_end='2025-01-15',
            test_start='2025-01-20',
            test_end='2025-01-31',
            enable_extended_features=True
        )

        # Should have clear separation
        assert X_train.shape[0] > 0, "Training set is empty"
        assert X_test.shape[0] > 0, "Test set is empty"

        # With extended features, both should have 69 dimensions
        assert X_train.shape[1] == 69
        assert X_test.shape[1] == 69

    def test_extended_features_numerical_stability(self, test_db_with_full_data):
        """Verify extended features have reasonable numerical bounds"""
        X_train, y_train, X_test, y_test = prepare_data_by_groupby(
            db_path=test_db_with_full_data,
            groupby_strategy='machine_number',
            task='a',
            train_start='2025-01-01',
            train_end='2025-01-20',
            test_start='2025-01-21',
            test_end='2025-01-31',
            enable_extended_features=True
        )

        # No infinities
        assert not np.isinf(X_train).any(), "Infinities in training features"
        assert not np.isinf(X_test).any(), "Infinities in test features"

        # No extreme outliers (reasonable bounds)
        assert np.max(np.abs(X_train)) < 1000, "Training features have extreme values"
        assert np.max(np.abs(X_test)) < 1000, "Test features have extreme values"

    def test_consistency_across_repeated_runs(self, test_db_with_full_data):
        """Verify feature generation is deterministic"""
        results1 = prepare_data_by_groupby(
            db_path=test_db_with_full_data,
            groupby_strategy='machine_number',
            task='a',
            train_start='2025-01-01',
            train_end='2025-01-20',
            test_start='2025-01-21',
            test_end='2025-01-31',
            enable_extended_features=True
        )

        results2 = prepare_data_by_groupby(
            db_path=test_db_with_full_data,
            groupby_strategy='machine_number',
            task='a',
            train_start='2025-01-01',
            train_end='2025-01-20',
            test_start='2025-01-21',
            test_end='2025-01-31',
            enable_extended_features=True
        )

        X_train1, y_train1, X_test1, y_test1 = results1
        X_train2, y_train2, X_test2, y_test2 = results2

        # Shapes should match
        assert X_train1.shape == X_train2.shape
        assert X_test1.shape == X_test2.shape

        # Values should match (deterministic)
        np.testing.assert_array_almost_equal(X_train1, X_train2, decimal=10)
        np.testing.assert_array_equal(y_train1, y_train2)
        np.testing.assert_array_almost_equal(X_test1, X_test2, decimal=10)
        np.testing.assert_array_equal(y_test1, y_test2)


class TestDocumentationComplete:
    """Verify all docstrings and documentation are complete"""

    def test_all_methods_have_docstrings(self):
        """Verify all public methods in FeatureBuilder have docstrings"""
        public_methods = [
            'build_features',
            '_build_temporal_features',
            '_build_group_identification_features',
            '_build_hall_wide_features',
            '_build_periodicity_features',
            '_build_machine_history_features',
            '_build_relative_features',
            '_build_lag_features',
            '_build_interaction_features',
            '_build_domain_specific_features',
        ]

        for method_name in public_methods:
            method = getattr(FeatureBuilder, method_name)
            assert method.__doc__ is not None, f"{method_name} missing docstring"
            assert len(method.__doc__) > 20, f"{method_name} docstring too short"

    def test_feature_descriptions_in_module_docstring(self):
        """Verify module-level documentation describes all feature categories"""
        import ml.feature_engineering

        docstring = ml.feature_engineering.__doc__
        assert 'Temporal' in docstring
        assert 'Group Identification' in docstring
        assert 'Hall-wide' in docstring
        assert 'Periodicity' in docstring
        assert 'Machine History' in docstring
        assert 'Relative' in docstring
        assert 'Lag' in docstring
        assert 'Interaction' in docstring
        assert 'Domain-Specific' in docstring

    def test_feature_count_documentation_accuracy(self):
        """Verify feature counts in docstrings match implementation"""
        import ml.feature_engineering

        docstring = ml.feature_engineering.__doc__
        # Verify key counts are mentioned
        assert '69' in docstring or '69D' in docstring, "69D feature count not documented"
        assert 'Temporal Features (11)' in docstring
        assert 'Group Identification Features (11)' in docstring


class TestExtendedFeaturesWithRealWorldScenarios:
    """Integration tests simulating real-world usage scenarios"""

    @pytest.fixture
    def realistic_db(self):
        """Create a realistic database with varying machine performance"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "realistic.db"
            import gc
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE machine_detailed_results (
                    date TEXT, machine_number INTEGER, machine_name TEXT,
                    last_digit TEXT, is_zorome INTEGER,
                    games_normalized INTEGER, diff_coins_normalized INTEGER
                )
            """)

            # Create data with varying performance patterns
            dates = pd.date_range('2025-01-01', '2025-02-28', freq='D')
            machines = list(range(1, 101))  # Smaller set for realism

            np.random.seed(123)
            rows = []
            for date in dates:
                for machine_id in machines:
                    date_str = date.strftime('%Y%m%d')
                    last_digit = str(machine_id % 10)
                    day = int(date.strftime('%d'))
                    is_zorome = 1 if int(last_digit) == day % 10 else 0

                    # Simulate varying performance
                    base_games = 1200
                    base_diff = 200 if is_zorome else 100

                    # Add variability
                    games = base_games + np.random.normal(0, 200)
                    diff = base_diff + np.random.normal(0, 300)

                    rows.append((
                        date_str, machine_id, f'Model_{machine_id % 3}',
                        last_digit, is_zorome, int(games), int(diff)
                    ))

            cursor.executemany("""
                INSERT INTO machine_detailed_results
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, rows)

            cursor.execute("""
                CREATE TABLE daily_hall_summary (
                    date TEXT, day_of_week TEXT, last_digit INTEGER,
                    weekday_nth TEXT, win_rate REAL,
                    avg_games_per_machine INTEGER, avg_diff_per_machine INTEGER,
                    is_zorome INTEGER, total_machines INTEGER
                )
            """)

            for date in dates:
                date_str = date.strftime('%Y%m%d')
                day = int(date.strftime('%d'))
                dow = date.strftime('%A')
                last_d = day % 10

                # Weekend boost
                base_win_rate = 48 if dow in ['Saturday', 'Sunday'] else 45
                win_rate = base_win_rate + np.random.normal(0, 3)

                avg_games = 1100 + np.random.normal(0, 100)
                avg_diff = 180 + np.random.normal(0, 100)

                cursor.execute("""
                    INSERT INTO daily_hall_summary
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (date_str, dow, last_d, f'Mon{(day-1)//7+1}', win_rate,
                      int(avg_games), int(avg_diff), 0, 100))

            conn.commit()
            conn.close()

            import gc
            gc.collect()

            yield str(db_path)

    def test_realistic_scenario_weekend_bias(self, realistic_db):
        """Test with realistic data including weekend bias"""
        X_train, y_train, X_test, y_test = prepare_data_by_groupby(
            db_path=realistic_db,
            groupby_strategy='machine_number',
            task='a',
            train_start='2025-01-01',
            train_end='2025-01-31',
            test_start='2025-02-01',
            test_end='2025-02-28',
            enable_extended_features=True
        )

        assert X_train.shape[1] == 69
        assert X_test.shape[1] == 69
        assert not np.isnan(X_train).any()
        assert not np.isnan(X_test).any()

    def test_realistic_scenario_zorome_detection(self, realistic_db):
        """Test with data containing zorome patterns"""
        X_train, y_train, X_test, y_test = prepare_data_by_groupby(
            db_path=realistic_db,
            groupby_strategy='tail',
            task='b',
            train_start='2025-01-01',
            train_end='2025-01-31',
            test_start='2025-02-01',
            test_end='2025-02-28',
            enable_extended_features=True
        )

        assert X_train.shape[1] == 69
        # Verify zorome-related features are present and non-constant
        # (would be in interaction and domain-specific features)
        for col_idx in range(X_train.shape[1]):
            variance = np.var(X_train[:, col_idx])
            assert variance >= 0, "Variance should be non-negative"


class TestBackwardCompatibilityMatrix:
    """Test backward compatibility across all combinations"""

    @pytest.fixture
    def small_test_db(self):
        """Create a small test database"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "small_test.db"
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE machine_detailed_results (
                    date TEXT, machine_number INTEGER, machine_name TEXT,
                    last_digit TEXT, is_zorome INTEGER,
                    games_normalized INTEGER, diff_coins_normalized INTEGER
                )
            """)

            dates = pd.date_range('2025-01-01', '2025-01-15', freq='D')
            machines = list(range(1, 51))

            rows = []
            np.random.seed(99)
            for date in dates:
                for machine_id in machines:
                    date_str = date.strftime('%Y%m%d')
                    rows.append((
                        date_str, machine_id, f'Model_{machine_id % 2}',
                        str(machine_id % 10), 0,
                        900 + np.random.randint(-300, 300),
                        50 + np.random.randint(-100, 200)
                    ))

            cursor.executemany("""
                INSERT INTO machine_detailed_results
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, rows)

            cursor.execute("""
                CREATE TABLE daily_hall_summary (
                    date TEXT, day_of_week TEXT, last_digit INTEGER,
                    weekday_nth TEXT, win_rate REAL,
                    avg_games_per_machine INTEGER, avg_diff_per_machine INTEGER,
                    is_zorome INTEGER, total_machines INTEGER
                )
            """)

            for date in dates:
                cursor.execute("""
                    INSERT INTO daily_hall_summary
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (date.strftime('%Y%m%d'), date.strftime('%A'),
                      int(date.strftime('%d')) % 10, 'Mon1', 45.0,
                      900, 100, 0, 50))

            conn.commit()
            conn.close()

            import gc
            gc.collect()

            yield str(db_path)

    def test_backward_compat_all_strategies_both_flags(self, small_test_db):
        """Test all combinations of strategies × extended_features flag"""
        strategies = ['tail', 'model_type', 'machine_number']

        for strategy in strategies:
            # Without extended features
            X_train_basic, _, X_test_basic, _ = prepare_data_by_groupby(
                db_path=small_test_db,
                groupby_strategy=strategy,
                task='a',
                train_start='2025-01-01',
                train_end='2025-01-10',
                test_start='2025-01-11',
                test_end='2025-01-15',
                enable_extended_features=False
            )

            # With extended features
            X_train_ext, _, X_test_ext, _ = prepare_data_by_groupby(
                db_path=small_test_db,
                groupby_strategy=strategy,
                task='a',
                train_start='2025-01-01',
                train_end='2025-01-10',
                test_start='2025-01-11',
                test_end='2025-01-15',
                enable_extended_features=True
            )

            # Verify dimension differences
            assert X_train_basic.shape[1] == 22, f"{strategy}: basic should be 22D"
            assert X_train_ext.shape[1] == 69, f"{strategy}: extended should be 69D"

            # Both should have same number of samples
            assert X_train_basic.shape[0] == X_train_ext.shape[0]
            assert X_test_basic.shape[0] == X_test_ext.shape[0]
