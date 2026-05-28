import sqlite3
from pathlib import Path

import pandas as pd
import pytest


def test_nextday_zorome_report_confidence_uses_higher_score_as_better() -> None:
    from ml.last_digit import nextday_zorome_report as report

    rows = [
        {"rank": 1, "last_digit": "7", "combined_score": 2.8},
        {"rank": 2, "last_digit": "1", "combined_score": 1.9},
        {"rank": 3, "last_digit": "5", "combined_score": 1.0},
    ]

    enriched = report.attach_confidence_pct(rows)

    assert [row["confidence_pct"] for row in enriched] == [100, 50, 0]


def test_nextday_zorome_report_reads_latest_is_zorome_rows(tmp_path: Path) -> None:
    from ml.last_digit import nextday_zorome_report as report

    db_path = tmp_path / "sample.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE machine_detailed_results (
            date TEXT,
            machine_name TEXT,
            machine_number INTEGER,
            last_digit TEXT,
            is_zorome INTEGER
        )
        """
    )
    conn.executemany(
        "INSERT INTO machine_detailed_results VALUES (?, ?, ?, ?, ?)",
        [
            ("20260527", "old", 1111, "1", 1),
            ("20260528", "keep-a", 2077, "7", 1),
            ("20260528", "skip", 2012, "2", 0),
            ("20260528", "keep-b", 2111, "1", 1),
        ],
    )
    conn.commit()
    conn.close()

    latest_date, grouped = report.fetch_latest_zorome_by_digit(db_path)

    assert latest_date == "20260528"
    assert grouped == {
        "1": [(2111, "keep-b")],
        "7": [(2077, "keep-a")],
    }


def test_sunday_machine_analysis_aggregates_daily_machine_type_rows() -> None:
    from ml.experiments import sunday_machine_analysis as analysis

    df = pd.DataFrame(
        [
            {"machine_name": "A", "machine_count": 3, "avg_diff_coins": 300.0, "win_rate": 0.60, "high_profit_rate": 0.20, "total_games": 8000},
            {"machine_name": "A", "machine_count": 3, "avg_diff_coins": 100.0, "win_rate": 0.50, "high_profit_rate": 0.10, "total_games": 7500},
            {"machine_name": "B", "machine_count": 20, "avg_diff_coins": 500.0, "win_rate": 0.70, "high_profit_rate": 0.30, "total_games": 12000},
            {"machine_name": "B", "machine_count": 20, "avg_diff_coins": 300.0, "win_rate": 0.65, "high_profit_rate": 0.25, "total_games": 11800},
        ]
    )

    stats = analysis.build_machine_stats(df, min_days=2)

    row_a = stats.loc[stats["machine_name"] == "A"].iloc[0]
    row_b = stats.loc[stats["machine_name"] == "B"].iloc[0]

    assert row_a["num_machines"] == 3
    assert row_a["n_days"] == 2
    assert row_a["avg_diff"] == pytest.approx(200.0)
    assert row_b["num_machines"] == 20
    assert row_b["avg_high_profit_rate"] == pytest.approx(0.275)


def test_sunday_machine_analysis_category_boundaries() -> None:
    from ml.experiments import sunday_machine_analysis as analysis

    assert analysis.categorize_machine_count(2) == "2-5台"
    assert analysis.categorize_machine_count(5) == "2-5台"
    assert analysis.categorize_machine_count(6) == "6-15台"
    assert analysis.categorize_machine_count(16) == "16-50台"
    assert analysis.categorize_machine_count(50) == "16-50台"
    assert analysis.categorize_machine_count(51) == "50台超"


def test_signal_machine_analysis_uses_rb_probability_greater_than_threshold() -> None:
    from ml.experiments import signal_machine_correlation_analysis as analysis

    signal_rows = pd.DataFrame(
        [
            {"date": "20260528", "machine_name": "スマスロ北斗の拳", "last_digit": "7", "avg_diff": 50.0, "avg_rb_prob": (1 / 250), "n_machines": 3},
            {"date": "20260528", "machine_name": "モンキーターンV", "last_digit": "1", "avg_diff": 250.0, "avg_rb_prob": (1 / 500), "n_machines": 2},
        ]
    )

    flagged = analysis.attach_signal_flags(signal_rows, diff_threshold=200.0, rb_threshold=(1 / 300))

    hokuto = flagged.loc[flagged["machine_name"] == "スマスロ北斗の拳"].iloc[0]
    monkey = flagged.loc[flagged["machine_name"] == "モンキーターンV"].iloc[0]
    assert bool(hokuto["signal_rb"]) is True
    assert bool(hokuto["signal"]) is True
    assert bool(monkey["signal_diff"]) is True
    assert bool(monkey["signal"]) is True


def test_signal_machine_analysis_marks_signal_pairs_by_date_and_digit() -> None:
    from ml.experiments import signal_machine_correlation_analysis as analysis

    signal_rows = pd.DataFrame(
        [
            {"date": "20260528", "machine_name": "スマスロ北斗の拳", "last_digit": "7", "avg_diff": 250.0, "avg_rb_prob": 0.001, "n_machines": 3},
            {"date": "20260528", "machine_name": "モンキーターンV", "last_digit": "7", "avg_diff": 300.0, "avg_rb_prob": 0.001, "n_machines": 2},
            {"date": "20260529", "machine_name": "モンキーターンV", "last_digit": "1", "avg_diff": 10.0, "avg_rb_prob": 0.001, "n_machines": 2},
        ]
    )
    flagged = analysis.attach_signal_flags(signal_rows, diff_threshold=200.0, rb_threshold=(1 / 300))
    signal_pairs = analysis.extract_signal_pairs(flagged, flag_column="signal")

    other_df = pd.DataFrame(
        [
            {"date": "20260528", "last_digit": "7", "machine_name": "other-a", "diff_coins_normalized": 500},
            {"date": "20260528", "last_digit": "1", "machine_name": "other-b", "diff_coins_normalized": 200},
            {"date": "20260529", "last_digit": "1", "machine_name": "other-c", "diff_coins_normalized": 300},
        ]
    )

    marked = analysis.mark_signal_membership(other_df, signal_pairs, output_column="in_signal")

    assert marked["in_signal"].tolist() == [True, False, False]
