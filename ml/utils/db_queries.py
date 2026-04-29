"""
Database Query Utilities for Feature Engineering

Provides helper functions for loading data from SQLite database
used in Task 2 (Hall-wide and Periodicity Pattern features)
"""

import sqlite3
import pandas as pd
from typing import Tuple


def load_daily_hall_summary(
    db_path: str,
    train_start: str,
    train_end: str,
    test_start: str,
    test_end: str
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Load daily_hall_summary from SQLite database for train and test periods

    Args:
        db_path: Path to SQLite database file
        train_start: Training period start date (YYYY-MM-DD or YYYYMMDD)
        train_end: Training period end date (YYYY-MM-DD or YYYYMMDD)
        test_start: Test period start date (YYYY-MM-DD or YYYYMMDD)
        test_end: Test period end date (YYYY-MM-DD or YYYYMMDD)

    Returns:
        (df_train_hall, df_test_hall) - DataFrames with daily hall statistics
        - date column is stored as string (YYYYMMDD format)
        - Contains columns: date, win_rate, avg_diff_per_machine, avg_games_per_machine, total_machines
    """
    # Normalize date format to YYYYMMDD (remove hyphens if present)
    train_start_norm = train_start.replace('-', '')
    train_end_norm = train_end.replace('-', '')
    test_start_norm = test_start.replace('-', '')
    test_end_norm = test_end.replace('-', '')

    conn = sqlite3.connect(db_path)

    # Load training data
    query_train = """
        SELECT date, win_rate, avg_diff_per_machine, avg_games_per_machine, total_machines
        FROM daily_hall_summary
        WHERE date BETWEEN ? AND ?
        ORDER BY date
    """
    df_train_hall = pd.read_sql_query(
        query_train,
        conn,
        params=(train_start_norm, train_end_norm)
    )

    # Load test data
    query_test = """
        SELECT date, win_rate, avg_diff_per_machine, avg_games_per_machine, total_machines
        FROM daily_hall_summary
        WHERE date BETWEEN ? AND ?
        ORDER BY date
    """
    df_test_hall = pd.read_sql_query(
        query_test,
        conn,
        params=(test_start_norm, test_end_norm)
    )

    conn.close()

    # Ensure date column is string type
    df_train_hall["date"] = df_train_hall["date"].astype(str)
    df_test_hall["date"] = df_test_hall["date"].astype(str)

    return df_train_hall, df_test_hall


def load_daily_hall_with_date_info(
    db_path: str,
    train_start: str,
    train_end: str,
    test_start: str,
    test_end: str
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Load daily_hall_summary with date-related columns for periodicity analysis

    Includes: day_of_week, last_digit (day of month % 10), weekday_nth

    Args:
        db_path: Path to SQLite database file
        train_start: Training period start date (YYYY-MM-DD or YYYYMMDD)
        train_end: Training period end date (YYYY-MM-DD or YYYYMMDD)
        test_start: Test period start date (YYYY-MM-DD or YYYYMMDD)
        test_end: Test period end date (YYYY-MM-DD or YYYYMMDD)

    Returns:
        (df_train_hall, df_test_hall) - DataFrames with hall statistics and date info
    """
    # Normalize date format to YYYYMMDD
    train_start_norm = train_start.replace('-', '')
    train_end_norm = train_end.replace('-', '')
    test_start_norm = test_start.replace('-', '')
    test_end_norm = test_end.replace('-', '')

    conn = sqlite3.connect(db_path)

    query = """
        SELECT date, win_rate, avg_diff_per_machine, avg_games_per_machine, total_machines,
               day_of_week, last_digit
        FROM daily_hall_summary
        WHERE date BETWEEN ? AND ?
        ORDER BY date
    """

    df_train_hall = pd.read_sql_query(
        query,
        conn,
        params=(train_start_norm, train_end_norm)
    )

    df_test_hall = pd.read_sql_query(
        query,
        conn,
        params=(test_start_norm, test_end_norm)
    )

    conn.close()

    # Ensure date column is string type
    df_train_hall["date"] = df_train_hall["date"].astype(str)
    df_test_hall["date"] = df_test_hall["date"].astype(str)

    return df_train_hall, df_test_hall
