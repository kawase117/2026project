import sqlite3
import tempfile
import sys
from pathlib import Path

import pytest
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "database"))


def _make_temp_db_path() -> Path:
    temp_dir = Path(__file__).resolve().parent.parent / "tmp_test_monthly_trend"
    temp_dir.mkdir(exist_ok=True)
    handle = tempfile.NamedTemporaryFile(dir=temp_dir, suffix=".db", delete=False)
    handle.close()
    return Path(handle.name)


def _create_last_digit_summary_table(conn: sqlite3.Connection, table_name: str) -> None:
    conn.execute(
        f"""
        CREATE TABLE {table_name} (
            date TEXT,
            last_digit TEXT,
            machine_count INTEGER,
            total_games INTEGER,
            avg_games REAL,
            max_games INTEGER,
            min_games INTEGER,
            total_diff_coins INTEGER,
            avg_diff_coins REAL,
            max_diff_coins INTEGER,
            min_diff_coins INTEGER,
            win_rate INTEGER,
            high_profit_rate REAL
        )
        """
    )


class TestMonthlyTrendTables:
    def test_last_digit_summary_variants_include_bt(self):
        from table_config import SUMMARY_TABLE_CONFIGS

        variants = next(
            config["variants"]
            for config in SUMMARY_TABLE_CONFIGS
            if config["base_name"] == "last_digit_summary"
        )

        assert variants == ["all", "jug", "hana", "oki", "bt", "other"]

    def test_daily_position_summary_variants_include_bt(self):
        from table_config import SUMMARY_TABLE_CONFIGS

        variants = next(
            config["variants"]
            for config in SUMMARY_TABLE_CONFIGS
            if config["base_name"] == "daily_position_summary"
        )

        assert variants == ["all", "jug", "hana", "oki", "bt", "other"]

    def test_monthly_trend_tables_include_bt_variant(self):
        from db_setup import _create_monthly_trend_tables

        db_path = _make_temp_db_path()
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        _create_monthly_trend_tables(cursor)
        conn.commit()

        rows = cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'monthly_trend_%' ORDER BY name"
        ).fetchall()
        table_names = [row[0] for row in rows]

        assert len(table_names) == 18
        assert "monthly_trend_date_digit_bt" in table_names
        assert "monthly_trend_weekday_bt" in table_names
        assert "monthly_trend_machine_digit_bt" in table_names

        conn.close()
        db_path.unlink(missing_ok=True)


class TestMonthlyTrendAggregation:
    def test_aggregate_by_key_uses_raw_diff_stats(self):
        from monthly_trend_calculator import MonthlyTrendCalculator

        calc = MonthlyTrendCalculator(":memory:")
        df = pd.DataFrame(
            {
                "date": ["20260601", "20260601", "20260602"],
                "machine_name": ["A", "B", "C"],
                "date_digit": [1, 1, 1],
                "games_normalized": [1000, 2000, 1000],
                "diff_coins_normalized": [100, 300, -50],
            }
        )

        result = calc._aggregate_by_key(df, "date_digit", "202606", 30)
        row = result.iloc[0]

        assert row["sample_count"] == 2
        assert row["avg_diff_per_machine"] == 75.0
        assert row["median_diff_per_machine"] == 100.0
        assert row["max_diff_coins"] == 300
        assert row["min_diff_coins"] == -50
        assert row["total_diff_coins"] == 350


class TestSummaryCalculatorBt:
    def test_last_digit_summary_bt_is_populated(self):
        from summary_calculator import SummaryCalculator

        db_path = _make_temp_db_path()
        conn = sqlite3.connect(db_path)

        conn.execute(
            """
            CREATE TABLE machine_detailed_results (
                date TEXT,
                machine_name TEXT,
                machine_number INTEGER,
                last_digit TEXT,
                is_zorome INTEGER,
                machine_rank_in_type INTEGER,
                games_normalized INTEGER,
                diff_coins_normalized INTEGER,
                games_deviation INTEGER,
                bb_count INTEGER,
                rb_count INTEGER,
                total_probability_fraction TEXT,
                total_probability_decimal REAL,
                bb_probability_fraction TEXT,
                bb_probability_decimal REAL,
                rb_probability_fraction TEXT,
                rb_probability_decimal REAL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE machine_master (
                machine_name_normalized TEXT PRIMARY KEY,
                jug_flag INTEGER,
                hana_flag INTEGER,
                oki_flag INTEGER,
                bt_flag INTEGER
            )
            """
        )

        for suffix in ["all", "jug", "hana", "oki", "bt", "other"]:
            _create_last_digit_summary_table(conn, f"last_digit_summary_{suffix}")

        conn.execute(
            """
            INSERT INTO machine_master (
                machine_name_normalized, jug_flag, hana_flag, oki_flag, bt_flag
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("BT1", 0, 0, 0, 1),
        )
        conn.execute(
            """
            INSERT INTO machine_detailed_results (
                date, machine_name, machine_number, last_digit, is_zorome,
                machine_rank_in_type, games_normalized, diff_coins_normalized,
                games_deviation, bb_count, rb_count,
                total_probability_fraction, total_probability_decimal,
                bb_probability_fraction, bb_probability_decimal,
                rb_probability_fraction, rb_probability_decimal
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("20260601", "BT1", 101, "1", 0, 1, 3000, 1200, 0, 5, 3, "1/1", 1.0, "1/1", 1.0, "1/1", 1.0),
        )
        conn.commit()
        conn.close()

        SummaryCalculator(str(db_path)).update_last_digit_summary_by_type("20260601")

        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT date, last_digit, machine_count, total_diff_coins FROM last_digit_summary_bt"
        ).fetchall()
        conn.close()
        db_path.unlink(missing_ok=True)

        assert rows == [("20260601", "1", 1, 1200)]


class TestMonthlyTrendSqlSafety:
    def test_upsert_rows_rejects_unsafe_table_name(self):
        from monthly_trend_calculator import MonthlyTrendCalculator

        calc = MonthlyTrendCalculator(":memory:")
        conn = sqlite3.connect(":memory:")
        df = pd.DataFrame([{"machine_digit": "1", "year_month": "202606"}])

        try:
            with pytest.raises(ValueError):
                calc._upsert_rows(conn, "monthly_trend_date_digit_all;drop", "machine_digit", df)
        finally:
            conn.close()

    def test_maybe_complete_prev_month_rejects_unsafe_identifier(self):
        import monthly_trend_calculator as mtc
        from monthly_trend_calculator import MonthlyTrendCalculator

        calc = MonthlyTrendCalculator(":memory:")
        db_path = _make_temp_db_path()
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE monthly_trend_date_digit_all (year_month TEXT, is_complete INTEGER)")
        conn.commit()
        conn.close()

        original_suffixes = mtc.MACHINE_SUFFIXES
        try:
            mtc.MACHINE_SUFFIXES = ["all;drop"]
            with pytest.raises(ValueError):
                calc._maybe_complete_prev_month("202606")
        finally:
            mtc.MACHINE_SUFFIXES = original_suffixes
            db_path.unlink(missing_ok=True)
