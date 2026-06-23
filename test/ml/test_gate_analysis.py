from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from ml.experiments.gate_analysis.config import SEGMENT_ORDER
from ml.experiments.gate_analysis.run_gate_analysis import (
    DEFAULT_DB_PATH,
    build_segment_daily_counts,
    classify_seg,
    resolve_default_db_path,
    run_gate_analysis,
)


def _actual_machine_names() -> tuple[str, str]:
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        names = pd.read_sql_query("SELECT DISTINCT machine_name FROM machine_detailed_results", conn)
    classified = names["machine_name"].map(classify_seg)
    a_name = names.loc[classified.eq("A"), "machine_name"].iloc[0]
    n_name = names.loc[classified.eq("N"), "machine_name"].iloc[0]
    return str(a_name), str(n_name)


def _write_coords(path: Path, rows: list[dict[str, object]]) -> None:
    frame = pd.DataFrame(rows)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def _write_db(path: Path, rows: list[dict[str, object]]) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE machine_detailed_results (
                date TEXT,
                machine_number INTEGER,
                machine_name TEXT,
                games_normalized INTEGER,
                diff_coins_normalized INTEGER
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO machine_detailed_results (
                date, machine_number, machine_name, games_normalized, diff_coins_normalized
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    row["date"],
                    row["machine_number"],
                    row["machine_name"],
                    row["games_normalized"],
                    row["diff_coins_normalized"],
                )
                for row in rows
            ],
        )
        conn.commit()


def _build_synthetic_bundle(tmp_path: Path) -> tuple[Path, Path, Path]:
    a_name, n_name = _actual_machine_names()
    db_path = tmp_path / "gate.db"
    coords_2f = tmp_path / "2f.csv"
    coords_3f = tmp_path / "3f.csv"

    _write_coords(
        coords_2f,
        [
            {
                "machine_number": 2001,
                "floor": "2F",
                "section": "2001-2002",
                "section_min": 2001,
                "section_max": 2002,
                "rank_from_min": 1,
                "rank_from_max": 2,
            },
            {
                "machine_number": 2002,
                "floor": "2F",
                "section": "2001-2002",
                "section_min": 2001,
                "section_max": 2002,
                "rank_from_min": 2,
                "rank_from_max": 1,
            },
        ],
    )
    _write_coords(
        coords_3f,
        [
            {
                "machine_number": 3001,
                "floor": "3F",
                "section": "3001-3002",
                "section_min": 3001,
                "section_max": 3002,
                "rank_from_min": 1,
                "rank_from_max": 2,
            },
            {
                "machine_number": 3002,
                "floor": "3F",
                "section": "3001-3002",
                "section_min": 3001,
                "section_max": 3002,
                "rank_from_min": 2,
                "rank_from_max": 1,
            },
            {
                "machine_number": 3003,
                "floor": "3F",
                "section": "3003-3004",
                "section_min": 3003,
                "section_max": 3004,
                "rank_from_min": 1,
                "rank_from_max": 2,
            },
            {
                "machine_number": 3004,
                "floor": "3F",
                "section": "3003-3004",
                "section_min": 3003,
                "section_max": 3004,
                "rank_from_min": 2,
                "rank_from_max": 1,
            },
        ],
    )

    warmup_rates = [95, 100, 100, 105, 100, 95, 100, 105, 100, 100]
    post_rates = [95, 115, 95, 110, 95, 115, 95, 110, 95, 115]
    segment_names = {
        2001: n_name,
        2002: n_name,
        3001: a_name,
        3002: n_name,
        3003: n_name,
        3004: a_name,
    }
    segment_offsets = {
        2001: 0,
        2002: 1,
        3001: 2,
        3002: 3,
        3003: 4,
        3004: 5,
    }

    rows: list[dict[str, object]] = []
    for day_index in range(100):
        date = (pd.Timestamp("2026-01-01") + pd.Timedelta(days=day_index)).strftime("%Y%m%d")
        for machine_number, machine_name in segment_names.items():
            offset = segment_offsets[machine_number]
            if day_index < 90:
                rate = warmup_rates[(day_index + offset) % len(warmup_rates)]
            else:
                rate = post_rates[(day_index - 90 + offset) % len(post_rates)]
            diff_coins = int(round(1500 * (rate / 100.0 - 1.0)))
            rows.append(
                {
                    "date": date,
                    "machine_number": machine_number,
                    "machine_name": machine_name,
                    "games_normalized": 500,
                    "diff_coins_normalized": diff_coins,
                }
            )

    _write_db(db_path, rows)
    return db_path, coords_2f, coords_3f


def test_default_db_path_points_to_real_kamata7_db() -> None:
    assert DEFAULT_DB_PATH.exists()
    assert DEFAULT_DB_PATH.stat().st_size > 0
    assert resolve_default_db_path() == DEFAULT_DB_PATH


def test_classify_seg_marks_actual_a_and_n_types() -> None:
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        names = pd.read_sql_query("SELECT DISTINCT machine_name FROM machine_detailed_results", conn)
    counts = names["machine_name"].map(classify_seg).value_counts()

    assert counts.get("A", 0) > 0
    assert counts.get("N", 0) > 0


def test_build_segment_daily_counts_attaches_rolling_quantile_gate(tmp_path: Path) -> None:
    db_path, coords_2f, coords_3f = _build_synthetic_bundle(tmp_path)
    counts = build_segment_daily_counts(db_path, coords_2f, coords_3f)

    assert len(counts) == 600
    assert set(counts["segment"].unique()) == set(SEGMENT_ORDER)
    assert counts["segment_avg_payout"].isna().sum() == 0
    assert counts["eligible_for_gate"].dtype == bool
    assert counts["gate_positive_q70"].dtype == bool

    for date in sorted(counts["date"].unique()):
        date_segments = counts[counts["date"] == date]["segment"].tolist()
        assert date_segments == list(SEGMENT_ORDER)

    first_segment = counts[counts["segment"] == "2F_L_N"].sort_values("date")
    assert first_segment.iloc[:90]["eligible_for_gate"].eq(False).all()
    assert first_segment.iloc[89]["history_days"] == 89
    assert first_segment.iloc[90]["history_days"] == 90
    assert bool(first_segment.iloc[90]["eligible_for_gate"]) is True
    assert first_segment.iloc[90:]["gate_positive_q70"].isin([True, False]).all()
    assert first_segment.iloc[90:]["gate_positive_q70"].any()
    assert (~first_segment.iloc[90:]["gate_positive_q70"]).any()
    assert first_segment.iloc[90:]["rolling_q70"].notna().all()


def test_run_gate_analysis_writes_rolling_quantile_bundle(tmp_path: Path) -> None:
    db_path, coords_2f, coords_3f = _build_synthetic_bundle(tmp_path)
    output_dir = tmp_path / "results"

    result = run_gate_analysis(
        db_path=db_path,
        output_dir=output_dir,
        coords_2f_path=coords_2f,
        coords_3f_path=coords_3f,
    )

    report_path = output_dir / "report.md"
    daily_path = output_dir / "segment_daily_counts.csv"
    gate_path = output_dir / "gate_sensitivity.csv"

    assert report_path.exists()
    assert daily_path.exists()
    assert gate_path.exists()

    report = report_path.read_text(encoding="utf-8")
    assert "Gate Condition Analysis Report" in report
    assert "Rolling Quantile Gate Sensitivity" in report
    assert "Warmup rows" in report
    assert "Primary gate quantile" in report

    daily = pd.read_csv(daily_path, encoding="utf-8-sig")
    gate = pd.read_csv(gate_path, encoding="utf-8-sig")
    assert len(daily) == 600
    assert len(gate) == 18
    assert result["segment_daily_counts"].shape[0] == 600
    assert result["gate_sensitivity"].shape[0] == 18
