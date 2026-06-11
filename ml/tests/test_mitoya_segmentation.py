from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from ml.last_digit.mitoya_segmentation import (
    add_atype3_columns,
    aggregate_mode_mitoya,
    classify_positive_combined_bucket,
    build_base_rows_mitoya,
)


def test_add_atype3_columns_bt_overrides_a_flags() -> None:
    df = pd.DataFrame(
        {
            "machine_number": [101, 102, 103],
            "jug_flag": [1, 1, 0],
            "hana_flag": [0, 0, 0],
            "oki_flag": [0, 0, 0],
            "bt_flag": [1, 0, 0],
        }
    )

    out = add_atype3_columns(df)

    assert out["expert"].tolist() == ["BT", "A", "N"]
    assert out["atype_bucket"].tolist() == ["BT", "A", "N"]
    assert out["is_a_type"].tolist() == [1, 1, 0]


def test_aggregate_mode_mitoya_supports_atype3() -> None:
    raw = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-01", "2026-01-02"]),
            "machine_number": [101, 102, 201],
            "last_digit": ["1", "2", "1"],
            "games_normalized": [100, 200, 150],
            "diff_coins_normalized": [10, -20, 30],
            "diff_focus": [10.0, -20.0, 30.0],
            "win_flag": [1.0, 0.0, 1.0],
            "is_event_day": [0, 0, 1],
            "is_a_type": [0, 1, 1],
            "atype_bucket": ["N", "A", "BT"],
            "expert": ["N", "A", "BT"],
        }
    )

    out = aggregate_mode_mitoya(raw, mode="atype3")

    assert set(out["group_key"]) == {"N", "A", "BT"}
    assert "lag1_hall_digit_diff" in out.columns
    assert "mean_section_rank" in out.columns
    assert "mean_physical_corner" in out.columns
    assert "pct_strong_section" in out.columns


def test_aggregate_mode_mitoya_supports_n_only() -> None:
    raw = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-01", "2026-01-02", "2026-01-02"]),
            "machine_number": [101, 102, 201, 202],
            "last_digit": ["1", "2", "1", "2"],
            "games_normalized": [100, 200, 150, 120],
            "diff_coins_normalized": [10, -20, 30, -15],
            "diff_focus": [10.0, -20.0, 30.0, -15.0],
            "win_flag": [1.0, 0.0, 1.0, 0.0],
            "is_event_day": [0, 0, 1, 1],
            "is_a_type": [0, 1, 0, 1],
            "atype_bucket": ["N", "A", "N", "BT"],
            "expert": ["N", "A", "N", "BT"],
        }
    )

    out = aggregate_mode_mitoya(raw, mode="N_only")

    assert set(out["group_key"]) == {"N"}
    assert set(out["last_digit"]) == {"1"}
    assert "lag1_hall_digit_diff" in out.columns


def test_aggregate_mode_mitoya_supports_positive_combined() -> None:
    raw = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-11", "2026-01-30", "2026-01-02"]),
            "machine_number": [101, 102, 201],
            "last_digit": ["1", "2", "1"],
            "games_normalized": [100, 200, 150],
            "diff_coins_normalized": [10, -20, 30],
            "diff_focus": [10.0, -20.0, 30.0],
            "win_flag": [1.0, 0.0, 1.0],
            "is_event_day": [0, 0, 1],
            "is_a_type": [0, 1, 1],
            "atype_bucket": ["N", "A", "BT"],
            "expert": ["N", "A", "BT"],
        }
    )

    out = aggregate_mode_mitoya(raw, mode="positive_combined")

    assert set(out["group_key"]) == {"positive_day", "others"}
    assert "lag1_hall_digit_diff" in out.columns


def test_classify_positive_combined_bucket_maps_special_days_to_positive_day() -> None:
    assert classify_positive_combined_bucket(pd.Timestamp("2026-01-11")) == "positive_day"
    assert classify_positive_combined_bucket(pd.Timestamp("2026-01-30")) == "positive_day"
    assert classify_positive_combined_bucket(pd.Timestamp("2026-02-02")) == "positive_day"
    assert classify_positive_combined_bucket(pd.Timestamp("2026-02-03")) == "others"


def test_build_base_rows_mitoya_includes_section_and_physical_corner(tmp_path: Path) -> None:
    db_path = tmp_path / "mitoya.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE machine_detailed_results (
            date TEXT,
            machine_number INTEGER,
            machine_name TEXT,
            last_digit TEXT,
            games_normalized INTEGER,
            diff_coins_normalized INTEGER
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE machine_layout (
            machine_number INTEGER,
            section TEXT,
            rank_from_min INTEGER,
            rank_from_max INTEGER
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE machine_master (
            machine_name_normalized TEXT,
            jug_flag INTEGER,
            hana_flag INTEGER,
            oki_flag INTEGER,
            bt_flag INTEGER
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE daily_hall_summary (
            date TEXT,
            is_any_event INTEGER,
            is_strong_zorome INTEGER
        )
        """
    )
    cursor.executemany(
        "INSERT INTO machine_detailed_results VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("20250101", 101, "Model_A", "1", 100, 200),
            ("20250101", 102, "Model_B", "2", 100, -50),
        ],
    )
    cursor.execute("INSERT INTO machine_layout VALUES (?, ?, ?, ?)", (101, "574-590", 1, 18))
    cursor.execute(
        "INSERT INTO machine_master VALUES (?, ?, ?, ?, ?)",
        ("Model_A", 1, 0, 0, 0),
    )
    cursor.execute(
        "INSERT INTO machine_master VALUES (?, ?, ?, ?, ?)",
        ("Model_B", 0, 0, 0, 0),
    )
    cursor.execute("INSERT INTO daily_hall_summary VALUES (?, ?, ?)", ("20250101", 0, 0))
    conn.commit()
    conn.close()

    df = build_base_rows_mitoya(db_path=db_path, a_weight=1.0, non_a_weight=1.0)

    for column in ["section", "rank_from_min", "rank_from_max", "physical_corner", "physical_corner_valid"]:
        assert column in df.columns

    first = df.loc[df["machine_number"].eq(101)].iloc[0]
    second = df.loc[df["machine_number"].eq(102)].iloc[0]

    assert first["section"] == "574-590"
    assert int(first["section_rank"]) == 1
    assert int(first["is_strong_section"]) == 1
    assert int(first["physical_corner"]) == 1
    assert int(first["physical_corner_valid"]) == 1
    assert second["section"] == "unknown"
    assert int(second["section_rank"]) == 0
    assert int(second["is_strong_section"]) == 0
    assert int(second["physical_corner"]) == -1
    assert int(second["physical_corner_valid"]) == 0
