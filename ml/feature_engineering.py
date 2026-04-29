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

Hall-wide Features (4):
- win_rate_daily (1 dimension)
- avg_diff_daily (1 dimension)
- avg_games_daily (1 dimension)
- total_machines (1 dimension)

Periodicity Pattern Features (5):
- weekday_avg_diff (1 dimension)
- weekday_avg_games (1 dimension)
- dd_pattern_score (1 dimension)
- is_event_day (1 dimension)
- anomaly_score (1 dimension)

Machine History Features (10):
- ma_14_diff, ma_7_diff, ma_14_games, ma_7_games, ma_30_diff (5 dimensions)
- efficiency, stability, trend_14, consecutive_wins, win_rate_machine (5 dimensions)

Relative Features (4):
- diff_vs_hall, games_vs_hall, efficiency_vs_hall, rank_percentile (4 dimensions)

Lag Features (8):
- lag_1_diff, lag_2_diff, lag_7_diff, lag_30_diff (4 dimensions)
- lag_1_games, lag_7_games, lag_1_win_rate, lag_1_win_rate_mean (4 dimensions)

Total: 22 features (Task 1), 31 features (Task 1+2), or 53 features (Task 1+2+3)
"""

import numpy as np
import pandas as pd
from typing import Tuple, Optional, Dict
from sklearn.preprocessing import StandardScaler


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

    def __init__(self, df: pd.DataFrame, df_hall: Optional[pd.DataFrame] = None,
                 df_full: Optional[pd.DataFrame] = None, train_end_date: Optional[str] = None):
        """
        Initialize FeatureBuilder

        Args:
            df: DataFrame with machine_detailed_results columns (train or test subset)
            df_hall: Optional DataFrame with daily_hall_summary columns
                     Used for Hall-wide and Periodicity features (Task 2)
            df_full: Optional full DataFrame (train + test) for rolling calculations
            train_end_date: End date of training period (YYYYMMDD) for coherence detection
        """
        self.df = df.copy()
        self.df_hall = df_hall.copy() if df_hall is not None else None
        self.df_full = df_full.copy() if df_full is not None else df.copy()  # Default to current df
        self.train_end_date = train_end_date
        self._validate_columns()
        self._parse_dates()
        self._scaler_state = {}
        self.train_stats = {}  # Storage for train statistics (Data Leakage Prevention)

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

    def build_features(self, is_train: bool = True, enable_extended_features: bool = False) -> np.ndarray:
        """
        Build combined feature matrix (Temporal + Group ID + optional Hall-wide + Periodicity)

        Args:
            is_train: If True, fit scaler on this data. If False, use stored scaler.
            enable_extended_features: If True, add Hall-wide (4) + Periodicity (5) features for 31 total.
                                     If False, return only Task 1 features (22).

        Returns:
            Feature matrix of shape (n_samples, 22) or (n_samples, 31)
        """
        if len(self.df) == 0:
            n_features = 31 if enable_extended_features else 22
            return np.array([]).reshape(0, n_features)

        temporal = self._build_temporal_features()
        group_id = self._build_group_identification_features()

        # Concatenate Task 1 features (22)
        features = np.concatenate([temporal, group_id], axis=1)

        # Add Task 2 features if requested
        if enable_extended_features:
            hall_wide = self._build_hall_wide_features(is_train=is_train)
            periodicity = self._build_periodicity_features(is_train=is_train)
            features = np.concatenate([features, hall_wide, periodicity], axis=1)

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

    def _build_machine_history_features(self, is_train: bool = True) -> np.ndarray:
        """
        Build Machine History features (10 total)

        Features:
        1-2. ma_14_diff, ma_7_diff — Moving average of diff_coins (14/7 days)
        3-4. ma_14_games, ma_7_games — Moving average of games (14/7 days)
        5. ma_30_diff — Moving average of diff_coins (30 days)
        6. efficiency — ma_14_diff / (ma_14_games + 1e-8), normalized
        7. stability — Std of diff_coins over 7 days
        8. trend_14 — (recent_7_mean - older_7_mean) / older_7_mean
        9. consecutive_wins — Count of consecutive days with diff > 0
        10. win_rate_machine — (days_with_positive_diff / total_days), normalized

        Data Leakage Prevention:
        - All rolling calculations done on df_full (train + test combined)
        - Statistics (mean, std) computed only on training data
        - Test data uses training statistics for normalization

        Args:
            is_train: If True, fit scalers. If False, use stored scalers.

        Returns:
            Array of shape (n_samples, 10)
        """
        n = len(self.df)

        # Sort df_full by machine_number and date for rolling calculations
        df_full_sorted = self.df_full.sort_values(['machine_number', 'date_parsed']).copy()

        # Initialize feature arrays
        ma_14_diff_vals = np.zeros(n, dtype=float)
        ma_7_diff_vals = np.zeros(n, dtype=float)
        ma_14_games_vals = np.zeros(n, dtype=float)
        ma_7_games_vals = np.zeros(n, dtype=float)
        ma_30_diff_vals = np.zeros(n, dtype=float)
        efficiency_vals = np.zeros(n, dtype=float)
        stability_vals = np.zeros(n, dtype=float)
        trend_14_vals = np.zeros(n, dtype=float)
        consecutive_wins_vals = np.zeros(n, dtype=float)
        win_rate_machine_vals = np.zeros(n, dtype=float)

        # Create mapping: (machine_number, date) -> index in self.df
        df_indexed = self.df.copy()
        df_indexed['idx_in_self'] = range(n)

        # Calculate rolling statistics by machine
        for machine_id in df_full_sorted['machine_number'].unique():
            df_machine = df_full_sorted[df_full_sorted['machine_number'] == machine_id].reset_index(drop=True)

            if len(df_machine) < 2:
                continue

            # Rolling means (minimum 1 period to handle sparse data)
            ma_14_diff = df_machine['diff_coins_normalized'].rolling(14, min_periods=1).mean().values
            ma_7_diff = df_machine['diff_coins_normalized'].rolling(7, min_periods=1).mean().values
            ma_14_games = df_machine['games_normalized'].rolling(14, min_periods=1).mean().values
            ma_7_games = df_machine['games_normalized'].rolling(7, min_periods=1).mean().values
            ma_30_diff = df_machine['diff_coins_normalized'].rolling(30, min_periods=1).mean().values

            # Efficiency: ma_14_diff / ma_14_games
            efficiency = ma_14_diff / (ma_14_games + 1e-8)

            # Stability: std of diff over 7 days (low std = stable)
            stability = df_machine['diff_coins_normalized'].rolling(7, min_periods=1).std().values
            stability = np.nan_to_num(stability, nan=0.0)  # Handle NaN in first period

            # Trend: (recent_7_mean - older_7_mean) / older_7_mean
            trend_14 = np.zeros_like(df_machine['diff_coins_normalized'].values, dtype=float)
            for i in range(len(df_machine)):
                if i >= 14:
                    recent_7_mean = ma_7_diff[i-1]  # Use previous 7-day average
                    older_7_start = max(0, i-14)
                    older_7_mean = df_machine['diff_coins_normalized'].iloc[older_7_start:i-7].mean()
                    if older_7_mean != 0:
                        trend_14[i] = (recent_7_mean - older_7_mean) / abs(older_7_mean)
                    else:
                        trend_14[i] = 0.0
                else:
                    trend_14[i] = 0.0

            # Consecutive wins: count days with diff > 0 consecutively
            consecutive_wins = np.zeros_like(df_machine['diff_coins_normalized'].values, dtype=float)
            win_indicator = (df_machine['diff_coins_normalized'].values > 0).astype(int)

            count = 0
            for i, is_win in enumerate(win_indicator):
                if is_win:
                    count += 1
                else:
                    count = 0
                consecutive_wins[i] = count

            # Win rate: fraction of days with diff > 0
            total_days = len(df_machine)
            win_days = (df_machine['diff_coins_normalized'].values > 0).sum()
            win_rate = float(win_days) / float(total_days) if total_days > 0 else 0.0
            win_rate_machine_arr = np.full(len(df_machine), win_rate, dtype=float)

            # Map back to indices in self.df
            for idx_in_machine, row_machine in enumerate(df_machine.itertuples()):
                # Find matching row in self.df
                mask = (df_indexed['machine_number'] == machine_id) & (df_indexed['date_parsed'] == row_machine.date_parsed)
                idx_list = df_indexed[mask]['idx_in_self'].values

                if len(idx_list) > 0:
                    idx_in_self = idx_list[0]
                    ma_14_diff_vals[idx_in_self] = ma_14_diff[idx_in_machine]
                    ma_7_diff_vals[idx_in_self] = ma_7_diff[idx_in_machine]
                    ma_14_games_vals[idx_in_self] = ma_14_games[idx_in_machine]
                    ma_7_games_vals[idx_in_self] = ma_7_games[idx_in_machine]
                    ma_30_diff_vals[idx_in_self] = ma_30_diff[idx_in_machine]
                    efficiency_vals[idx_in_self] = efficiency[idx_in_machine]
                    stability_vals[idx_in_self] = stability[idx_in_machine]
                    trend_14_vals[idx_in_self] = trend_14[idx_in_machine]
                    consecutive_wins_vals[idx_in_self] = consecutive_wins[idx_in_machine]
                    win_rate_machine_vals[idx_in_self] = win_rate_machine_arr[idx_in_machine]

        # Normalize efficiency, stability, win_rate using training statistics
        if is_train:
            scaler_efficiency = StandardScaler()
            scaler_stability = StandardScaler()
            scaler_win_rate = StandardScaler()

            # Fit on non-zero values
            valid_eff = efficiency_vals[efficiency_vals != 0].reshape(-1, 1) if (efficiency_vals != 0).sum() > 0 else np.array([[0.0]])
            valid_stab = stability_vals[stability_vals != 0].reshape(-1, 1) if (stability_vals != 0).sum() > 0 else np.array([[0.0]])
            valid_wr = win_rate_machine_vals.reshape(-1, 1)

            scaler_efficiency.fit(valid_eff)
            scaler_stability.fit(valid_stab)
            scaler_win_rate.fit(valid_wr)

            self.train_stats['scaler_efficiency'] = scaler_efficiency
            self.train_stats['scaler_stability'] = scaler_stability
            self.train_stats['scaler_win_rate'] = scaler_win_rate
        else:
            scaler_efficiency = self.train_stats.get('scaler_efficiency', StandardScaler())
            scaler_stability = self.train_stats.get('scaler_stability', StandardScaler())
            scaler_win_rate = self.train_stats.get('scaler_win_rate', StandardScaler())

        # Apply scaling
        efficiency_normalized = np.full_like(efficiency_vals, 0.0)
        stability_normalized = np.full_like(stability_vals, 0.0)
        win_rate_normalized = np.full_like(win_rate_machine_vals, 0.0)

        valid_eff_mask = efficiency_vals != 0
        valid_stab_mask = stability_vals != 0

        if valid_eff_mask.sum() > 0:
            efficiency_normalized[valid_eff_mask] = scaler_efficiency.transform(
                efficiency_vals[valid_eff_mask].reshape(-1, 1)
            ).flatten()

        if valid_stab_mask.sum() > 0:
            stability_normalized[valid_stab_mask] = scaler_stability.transform(
                stability_vals[valid_stab_mask].reshape(-1, 1)
            ).flatten()

        win_rate_normalized = scaler_win_rate.transform(win_rate_machine_vals.reshape(-1, 1)).flatten()

        # Concatenate all machine history features: 10 dimensions
        machine_history = np.concatenate([
            ma_14_diff_vals.reshape(-1, 1),
            ma_7_diff_vals.reshape(-1, 1),
            ma_14_games_vals.reshape(-1, 1),
            ma_7_games_vals.reshape(-1, 1),
            ma_30_diff_vals.reshape(-1, 1),
            efficiency_normalized.reshape(-1, 1),
            stability_normalized.reshape(-1, 1),
            trend_14_vals.reshape(-1, 1),
            consecutive_wins_vals.reshape(-1, 1),
            win_rate_normalized.reshape(-1, 1)
        ], axis=1)

        return machine_history

    def _build_relative_features(self, is_train: bool = True) -> np.ndarray:
        """
        Build Relative Features (4 total)

        Features compare individual machine performance to hall-wide statistics:
        1. diff_vs_hall — machine_diff / (hall_avg_diff + 1e-8)
        2. games_vs_hall — machine_games / (hall_avg_games + 1e-8)
        3. efficiency_vs_hall — machine_efficiency / (hall_efficiency + 1e-8)
        4. rank_percentile — rank of machine by diff / total_machines (0-1)

        Args:
            is_train: If True, fit scalers. If False, use stored scalers.

        Returns:
            Array of shape (n_samples, 4)
        """
        if self.df_hall is None:
            # Return zeros if no hall data available
            return np.zeros((len(self.df), 4), dtype=float)

        n = len(self.df)

        # Merge hall statistics with machine data by date
        df_merged = self.df.copy()
        df_merged['date_str'] = df_merged['date'].astype(str)

        df_hall_copy = self.df_hall.copy()
        df_hall_copy['date'] = df_hall_copy['date'].astype(str)

        df_merged = df_merged.merge(
            df_hall_copy[['date', 'avg_diff_per_machine', 'avg_games_per_machine']],
            left_on='date_str',
            right_on='date',
            how='left'
        )

        # Feature 1: diff_vs_hall
        machine_diff = self.df['diff_coins_normalized'].values.astype(float)
        hall_avg_diff = df_merged['avg_diff_per_machine'].values.astype(float)
        diff_vs_hall = machine_diff / (np.abs(hall_avg_diff) + 1e-8)
        diff_vs_hall = np.nan_to_num(diff_vs_hall, nan=0.0)
        diff_vs_hall_feature = diff_vs_hall.reshape(-1, 1)

        # Feature 2: games_vs_hall
        machine_games = self.df['games_normalized'].values.astype(float)
        hall_avg_games = df_merged['avg_games_per_machine'].values.astype(float)
        games_vs_hall = machine_games / (hall_avg_games + 1e-8)
        games_vs_hall = np.nan_to_num(games_vs_hall, nan=0.0)
        games_vs_hall_feature = games_vs_hall.reshape(-1, 1)

        # Feature 3: efficiency_vs_hall
        machine_efficiency = machine_diff / (machine_games + 1e-8)
        hall_efficiency = hall_avg_diff / (hall_avg_games + 1e-8)
        efficiency_vs_hall = machine_efficiency / (np.abs(hall_efficiency) + 1e-8)
        efficiency_vs_hall = np.nan_to_num(efficiency_vs_hall, nan=0.0)
        efficiency_vs_hall_feature = efficiency_vs_hall.reshape(-1, 1)

        # Feature 4: rank_percentile
        # Rank machines by diff within each date
        rank_percentile = np.zeros(n, dtype=float)

        for date_val in self.df['date'].unique():
            mask = self.df['date'] == date_val
            date_machines = self.df[mask].copy()

            # Rank by diff_coins (0 = worst, 1 = best)
            if len(date_machines) > 1:
                diffs = date_machines['diff_coins_normalized'].values
                ranks = (diffs.argsort().argsort() + 1) / len(date_machines)  # 1-indexed to 0-indexed percentile
                rank_percentile[mask] = ranks
            elif len(date_machines) == 1:
                rank_percentile[mask] = 0.5  # Single machine gets middle percentile

        rank_percentile_feature = rank_percentile.reshape(-1, 1)

        # Concatenate all relative features: 4 dimensions
        relative = np.concatenate([
            diff_vs_hall_feature,
            games_vs_hall_feature,
            efficiency_vs_hall_feature,
            rank_percentile_feature
        ], axis=1)

        return relative

    def _build_lag_features(self, is_train: bool = True) -> np.ndarray:
        """
        Build Lag Features (8 total)

        Features use past values to capture temporal patterns:
        1-4. lag_1_diff, lag_2_diff, lag_7_diff, lag_30_diff — Previous differences
        5-6. lag_1_games, lag_7_games — Previous game counts
        7. lag_1_win_rate — Binary: was previous day a win? (diff > 0)
        8. lag_1_win_rate_mean — 7-day win rate from previous day

        Time Series Coherence:
        - All calculations use df_full (train + test combined by date order)
        - Test period lags connect to training period values (no gap)
        - Missing values in first 30 days filled with ffill then 0

        Data Leakage Prevention:
        - Lag values are by definition historical (t-1, t-7, etc.)
        - No future information used

        Args:
            is_train: Unused (lag features have no fitting required)

        Returns:
            Array of shape (n_samples, 8)
        """
        n = len(self.df)

        # Sort df_full by machine and date to compute lags properly
        df_full_sorted = self.df_full.sort_values(['machine_number', 'date_parsed']).copy()

        # Initialize lag arrays
        lag_1_diff = np.zeros(n, dtype=float)
        lag_2_diff = np.zeros(n, dtype=float)
        lag_7_diff = np.zeros(n, dtype=float)
        lag_30_diff = np.zeros(n, dtype=float)
        lag_1_games = np.zeros(n, dtype=float)
        lag_7_games = np.zeros(n, dtype=float)
        lag_1_win_rate = np.zeros(n, dtype=float)
        lag_1_win_rate_mean = np.zeros(n, dtype=float)

        # Create mapping: (machine_number, date) -> index in self.df
        df_indexed = self.df.copy()
        df_indexed['idx_in_self'] = range(n)

        # Calculate lags by machine
        for machine_id in df_full_sorted['machine_number'].unique():
            df_machine = df_full_sorted[df_full_sorted['machine_number'] == machine_id].reset_index(drop=True)

            if len(df_machine) < 2:
                continue

            # Create lag columns
            df_machine_copy = df_machine.copy()
            df_machine_copy['lag_1_diff'] = df_machine_copy['diff_coins_normalized'].shift(1)
            df_machine_copy['lag_2_diff'] = df_machine_copy['diff_coins_normalized'].shift(2)
            df_machine_copy['lag_7_diff'] = df_machine_copy['diff_coins_normalized'].shift(7)
            df_machine_copy['lag_30_diff'] = df_machine_copy['diff_coins_normalized'].shift(30)
            df_machine_copy['lag_1_games'] = df_machine_copy['games_normalized'].shift(1)
            df_machine_copy['lag_7_games'] = df_machine_copy['games_normalized'].shift(7)
            df_machine_copy['lag_1_win'] = (df_machine_copy['diff_coins_normalized'].shift(1) > 0).astype(int)

            # Forward-fill missing lags (first 30 days)
            df_machine_copy['lag_1_diff'] = df_machine_copy['lag_1_diff'].fillna(method='ffill')
            df_machine_copy['lag_2_diff'] = df_machine_copy['lag_2_diff'].fillna(method='ffill')
            df_machine_copy['lag_7_diff'] = df_machine_copy['lag_7_diff'].fillna(method='ffill')
            df_machine_copy['lag_30_diff'] = df_machine_copy['lag_30_diff'].fillna(method='ffill')
            df_machine_copy['lag_1_games'] = df_machine_copy['lag_1_games'].fillna(method='ffill')
            df_machine_copy['lag_7_games'] = df_machine_copy['lag_7_games'].fillna(method='ffill')

            # Fill remaining NaNs with 0
            df_machine_copy['lag_1_diff'] = df_machine_copy['lag_1_diff'].fillna(0)
            df_machine_copy['lag_2_diff'] = df_machine_copy['lag_2_diff'].fillna(0)
            df_machine_copy['lag_7_diff'] = df_machine_copy['lag_7_diff'].fillna(0)
            df_machine_copy['lag_30_diff'] = df_machine_copy['lag_30_diff'].fillna(0)
            df_machine_copy['lag_1_games'] = df_machine_copy['lag_1_games'].fillna(0)
            df_machine_copy['lag_7_games'] = df_machine_copy['lag_7_games'].fillna(0)
            df_machine_copy['lag_1_win'] = df_machine_copy['lag_1_win'].fillna(0)

            # 7-day rolling win rate shifted by 1
            df_machine_copy['win_indicator'] = (df_machine_copy['diff_coins_normalized'] > 0).astype(int)
            df_machine_copy['lag_1_win_rate_mean'] = df_machine_copy['win_indicator'].rolling(7, min_periods=1).mean().shift(1)
            df_machine_copy['lag_1_win_rate_mean'] = df_machine_copy['lag_1_win_rate_mean'].fillna(0)

            # Map back to indices in self.df
            for idx_in_machine, row_machine in enumerate(df_machine_copy.itertuples()):
                # Find matching row in self.df
                mask = (df_indexed['machine_number'] == machine_id) & (df_indexed['date_parsed'] == row_machine.date_parsed)
                idx_list = df_indexed[mask]['idx_in_self'].values

                if len(idx_list) > 0:
                    idx_in_self = idx_list[0]
                    lag_1_diff[idx_in_self] = row_machine.lag_1_diff
                    lag_2_diff[idx_in_self] = row_machine.lag_2_diff
                    lag_7_diff[idx_in_self] = row_machine.lag_7_diff
                    lag_30_diff[idx_in_self] = row_machine.lag_30_diff
                    lag_1_games[idx_in_self] = row_machine.lag_1_games
                    lag_7_games[idx_in_self] = row_machine.lag_7_games
                    lag_1_win_rate[idx_in_self] = row_machine.lag_1_win
                    lag_1_win_rate_mean[idx_in_self] = row_machine.lag_1_win_rate_mean

        # Concatenate all lag features: 8 dimensions
        lag_features = np.concatenate([
            lag_1_diff.reshape(-1, 1),
            lag_2_diff.reshape(-1, 1),
            lag_7_diff.reshape(-1, 1),
            lag_30_diff.reshape(-1, 1),
            lag_1_games.reshape(-1, 1),
            lag_7_games.reshape(-1, 1),
            lag_1_win_rate.reshape(-1, 1),
            lag_1_win_rate_mean.reshape(-1, 1)
        ], axis=1)

        return lag_features

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
            features: Feature array of shape (n_samples, 22) or (n_samples, 31)
        """
        # Placeholder: In future, apply pre-fitted StandardScaler
        # For now, do nothing (scaler not yet implemented)
        pass

    def _build_hall_wide_features(self, is_train: bool = True) -> np.ndarray:
        """
        Build Hall-wide features (4 total)

        Features:
        1. win_rate_daily (%) — Hall-wide win rate from daily_hall_summary
        2. avg_diff_daily — Hall-wide average diff coins per machine
        3. avg_games_daily — Hall-wide average games per machine
        4. total_machines — Number of machines in operation that day

        Normalization:
        - win_rate: uses training mean for normalization
        - avg_diff_daily: StandardScaler fit on training data
        - avg_games_daily: StandardScaler fit on training data
        - total_machines: StandardScaler fit on training data

        Args:
            is_train: If True, fit scalers on this data. If False, use stored scalers.

        Returns:
            Array of shape (n_samples, 4)
        """
        if self.df_hall is None:
            # Return zeros if no hall data available
            return np.zeros((len(self.df), 4), dtype=float)

        n = len(self.df)

        # Merge hall statistics with machine data by date
        df_merged = self.df.copy()
        df_merged["date_str"] = df_merged["date"].astype(str)

        df_hall_copy = self.df_hall.copy()
        df_hall_copy["date"] = df_hall_copy["date"].astype(str)

        df_merged = df_merged.merge(
            df_hall_copy[["date", "win_rate", "avg_diff_per_machine", "avg_games_per_machine", "total_machines"]],
            left_on="date_str",
            right_on="date",
            how="left"
        )

        # Feature 1: win_rate_daily (%)
        win_rate = df_merged["win_rate"].values.astype(float)
        if is_train:
            # Compute mean/std on non-NaN values
            valid_win_rate = win_rate[~np.isnan(win_rate)]
            if len(valid_win_rate) > 0:
                self.train_stats["win_rate_mean"] = float(np.mean(valid_win_rate))
                self.train_stats["win_rate_std"] = float(np.std(valid_win_rate))
            else:
                self.train_stats["win_rate_mean"] = 0.0
                self.train_stats["win_rate_std"] = 1.0
        # Normalize by training mean
        win_rate_train_mean = self.train_stats.get("win_rate_mean", 0.0)
        win_rate_normalized = (win_rate - win_rate_train_mean) / (win_rate_train_mean + 1e-8)
        win_rate_normalized = np.nan_to_num(win_rate_normalized, nan=0.0)
        win_rate_feature = win_rate_normalized.reshape(-1, 1)

        # Feature 2 & 3: avg_diff_daily and avg_games_daily (StandardScaler)
        avg_diff = df_merged["avg_diff_per_machine"].values.astype(float)
        avg_games = df_merged["avg_games_per_machine"].values.astype(float)

        if is_train:
            scaler_diff = StandardScaler()
            scaler_games = StandardScaler()

            # Fit on non-NaN values
            valid_diff = avg_diff[~np.isnan(avg_diff)].reshape(-1, 1)
            valid_games = avg_games[~np.isnan(avg_games)].reshape(-1, 1)

            if len(valid_diff) > 0:
                scaler_diff.fit(valid_diff)
                self.train_stats["scaler_avg_diff"] = scaler_diff
            if len(valid_games) > 0:
                scaler_games.fit(valid_games)
                self.train_stats["scaler_avg_games"] = scaler_games
        else:
            scaler_diff = self.train_stats.get("scaler_avg_diff", StandardScaler())
            scaler_games = self.train_stats.get("scaler_avg_games", StandardScaler())

        # Apply scaling
        avg_diff_normalized = np.full_like(avg_diff, 0.0)
        avg_games_normalized = np.full_like(avg_games, 0.0)

        valid_mask_diff = ~np.isnan(avg_diff)
        valid_mask_games = ~np.isnan(avg_games)

        if valid_mask_diff.sum() > 0:
            avg_diff_normalized[valid_mask_diff] = scaler_diff.transform(
                avg_diff[valid_mask_diff].reshape(-1, 1)
            ).flatten()

        if valid_mask_games.sum() > 0:
            avg_games_normalized[valid_mask_games] = scaler_games.transform(
                avg_games[valid_mask_games].reshape(-1, 1)
            ).flatten()

        avg_diff_feature = avg_diff_normalized.reshape(-1, 1)
        avg_games_feature = avg_games_normalized.reshape(-1, 1)

        # Feature 4: total_machines (StandardScaler)
        total_machines = df_merged["total_machines"].values.astype(float)

        if is_train:
            scaler_machines = StandardScaler()
            valid_machines = total_machines[~np.isnan(total_machines)].reshape(-1, 1)
            if len(valid_machines) > 0:
                scaler_machines.fit(valid_machines)
                self.train_stats["scaler_total_machines"] = scaler_machines
        else:
            scaler_machines = self.train_stats.get("scaler_total_machines", StandardScaler())

        # Apply scaling
        total_machines_normalized = np.full_like(total_machines, 0.0)
        valid_mask_machines = ~np.isnan(total_machines)

        if valid_mask_machines.sum() > 0:
            total_machines_normalized[valid_mask_machines] = scaler_machines.transform(
                total_machines[valid_mask_machines].reshape(-1, 1)
            ).flatten()

        total_machines_feature = total_machines_normalized.reshape(-1, 1)

        # Concatenate all hall-wide features
        hall_wide = np.concatenate(
            [win_rate_feature, avg_diff_feature, avg_games_feature, total_machines_feature],
            axis=1
        )

        return hall_wide

    def _build_periodicity_features(self, is_train: bool = True) -> np.ndarray:
        """
        Build Periodicity Pattern features (5 total)

        Features:
        1. weekday_avg_diff — Weekday average diff (lookup from training statistics)
        2. weekday_avg_games — Weekday average games (lookup from training statistics)
        3. dd_pattern_score — Day-of-month z-score pattern (lookup from training statistics)
        4. is_event_day — Flag for event days (month start/payday/month end)
        5. anomaly_score — Day-specific anomaly z-score (lookup from training statistics)

        Data Leakage Prevention:
        - All statistics are computed on training data only
        - Test data uses lookup tables from training statistics
        - Never computes statistics on test data

        Args:
            is_train: If True, compute and store statistics. If False, use stored statistics.

        Returns:
            Array of shape (n_samples, 5)
        """
        n = len(self.df)

        if is_train:
            # === Compute statistics on training data ===

            # Weekday statistics: group by day_of_week, compute mean diff and games
            weekday_stats = self.df.groupby("day_of_week").agg({
                "diff_coins_normalized": ["mean", "std"],
                "games_normalized": ["mean", "std"]
            }).fillna(0)

            # Extract values for storage
            weekday_avg_diff_dict = {}
            weekday_avg_games_dict = {}
            for dow in self.df["day_of_week"].unique():
                if dow in weekday_stats.index:
                    weekday_avg_diff_dict[dow] = float(weekday_stats.loc[dow, ("diff_coins_normalized", "mean")])
                    weekday_avg_games_dict[dow] = float(weekday_stats.loc[dow, ("games_normalized", "mean")])

            self.train_stats["weekday_avg_diff"] = weekday_avg_diff_dict
            self.train_stats["weekday_avg_games"] = weekday_avg_games_dict
            self.train_stats["weekday_diff_global_mean"] = float(self.df["diff_coins_normalized"].mean())
            self.train_stats["weekday_diff_global_std"] = float(self.df["diff_coins_normalized"].std() + 1e-8)
            self.train_stats["weekday_games_global_mean"] = float(self.df["games_normalized"].mean())
            self.train_stats["weekday_games_global_std"] = float(self.df["games_normalized"].std() + 1e-8)

            # DD (day-of-month) statistics
            dd_stats = self.df.groupby("day_of_month").agg({
                "diff_coins_normalized": ["mean", "std"]
            }).fillna(0)

            dd_avg_diff_dict = {}
            for dd in self.df["day_of_month"].unique():
                if dd in dd_stats.index:
                    dd_avg_diff_dict[int(dd)] = float(dd_stats.loc[dd, ("diff_coins_normalized", "mean")])

            self.train_stats["dd_avg_diff"] = dd_avg_diff_dict
            self.train_stats["dd_global_mean"] = float(self.df["diff_coins_normalized"].mean())
            self.train_stats["dd_global_std"] = float(self.df["diff_coins_normalized"].std() + 1e-8)

            # Day-specific anomaly statistics (date level)
            date_stats = self.df.groupby("date").agg({
                "diff_coins_normalized": ["mean", "count"]
            }).fillna(0)

            date_zscore_dict = {}
            global_mean = float(self.df["diff_coins_normalized"].mean())
            global_std = float(self.df["diff_coins_normalized"].std() + 1e-8)

            for date in self.df["date"].unique():
                if date in date_stats.index:
                    date_mean = float(date_stats.loc[date, ("diff_coins_normalized", "mean")])
                    zscore = (date_mean - global_mean) / global_std if global_std != 0 else 0.0
                    date_zscore_dict[str(date)] = float(zscore)

            self.train_stats["date_zscore"] = date_zscore_dict
            self.train_stats["date_global_mean"] = global_mean
            self.train_stats["date_global_std"] = global_std

        # === Apply statistics to current data ===

        # Feature 1: weekday_avg_diff
        weekday_avg_diff_dict = self.train_stats.get("weekday_avg_diff", {})
        weekday_diff_global_mean = self.train_stats.get("weekday_diff_global_mean", 0.0)

        weekday_avg_diff = np.full(n, weekday_diff_global_mean, dtype=float)
        for i, dow in enumerate(self.df["day_of_week"]):
            if dow in weekday_avg_diff_dict:
                weekday_avg_diff[i] = weekday_avg_diff_dict[dow]
            else:
                weekday_avg_diff[i] = weekday_diff_global_mean

        weekday_avg_diff_feature = (weekday_avg_diff.reshape(-1, 1) - weekday_diff_global_mean) / (
            self.train_stats.get("weekday_diff_global_std", 1.0) + 1e-8
        )

        # Feature 2: weekday_avg_games
        weekday_avg_games_dict = self.train_stats.get("weekday_avg_games", {})
        weekday_games_global_mean = self.train_stats.get("weekday_games_global_mean", self.df["games_normalized"].mean())
        weekday_games_global_std = self.train_stats.get("weekday_games_global_std", self.df["games_normalized"].std() + 1e-8)

        weekday_avg_games = np.full(n, weekday_games_global_mean, dtype=float)
        for i, dow in enumerate(self.df["day_of_week"]):
            if dow in weekday_avg_games_dict:
                weekday_avg_games[i] = weekday_avg_games_dict[dow]
            else:
                weekday_avg_games[i] = weekday_games_global_mean

        weekday_avg_games_feature = (weekday_avg_games.reshape(-1, 1) - weekday_games_global_mean) / (
            weekday_games_global_std + 1e-8
        )

        # Feature 3: dd_pattern_score
        dd_avg_diff_dict = self.train_stats.get("dd_avg_diff", {})
        dd_global_mean = self.train_stats.get("dd_global_mean", 0.0)
        dd_global_std = self.train_stats.get("dd_global_std", 1.0)

        dd_pattern_score = np.zeros(n, dtype=float)
        for i, dd in enumerate(self.df["day_of_month"]):
            if int(dd) in dd_avg_diff_dict:
                dd_value = dd_avg_diff_dict[int(dd)]
                dd_pattern_score[i] = (dd_value - dd_global_mean) / (dd_global_std + 1e-8)
            else:
                dd_pattern_score[i] = 0.0

        dd_pattern_score_feature = dd_pattern_score.reshape(-1, 1)

        # Feature 4: is_event_day
        is_event_day = np.zeros(n, dtype=float)
        for i, dd in enumerate(self.df["day_of_month"]):
            # Month start (1-3), payday (23-27), month end (28-31)
            if (1 <= dd <= 3) or (23 <= dd <= 27) or (28 <= dd <= 31):
                is_event_day[i] = 1.0

        is_event_day_feature = is_event_day.reshape(-1, 1)

        # Feature 5: anomaly_score (date-specific z-score)
        date_zscore_dict = self.train_stats.get("date_zscore", {})

        anomaly_score = np.zeros(n, dtype=float)
        for i, date in enumerate(self.df["date"]):
            date_str = str(date)
            if date_str in date_zscore_dict:
                anomaly_score[i] = date_zscore_dict[date_str]
            else:
                # If date not in training data, use 0 (neutral anomaly)
                anomaly_score[i] = 0.0

        # Fill any remaining NaN with 0
        anomaly_score = np.nan_to_num(anomaly_score, nan=0.0)
        anomaly_score_feature = anomaly_score.reshape(-1, 1)

        # Concatenate all periodicity features
        periodicity = np.concatenate(
            [weekday_avg_diff_feature, weekday_avg_games_feature, dd_pattern_score_feature,
             is_event_day_feature, anomaly_score_feature],
            axis=1
        )

        return periodicity
