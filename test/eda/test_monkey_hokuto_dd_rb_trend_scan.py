from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from eda import monkey_hokuto_dd_rb_trend_scan as mod


def _seed_machine_table(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE machine_detailed_results (
            date TEXT,
            machine_name TEXT,
            machine_number INTEGER,
            games_normalized INTEGER,
            rb_count INTEGER,
            rb_probability_decimal REAL,
            diff_coins_normalized REAL
        )
        """
    )
    rows = [
        ("20260101", "モンキーターンV", 101, 2500, 10, 0.0040, 100.0),
        ("20260102", "スマスロ北斗の拳", 102, 2600, 11, 0.0042, 120.0),
        ("20260103", "モンキーターンⅣ", 103, 2700, 12, 0.0044, 140.0),
        ("20260104", "北斗の拳 宿命", 104, 2800, 13, 0.0046, 160.0),
        ("20260105", "スマスロ真・北斗無双", 105, 2900, 14, 0.0048, 180.0),
        ("20260106", "モンキーターンV", 106, 1999, 15, 0.0050, 200.0),
    ]
    conn.executemany(
        """
        INSERT INTO machine_detailed_results
        (date, machine_name, machine_number, games_normalized, rb_count, rb_probability_decimal, diff_coins_normalized)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    conn.close()


def _make_scan_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = pd.date_range("2026-01-01", periods=180, freq="D")
    for machine_name, machine_number, bias in (
        ("モンキーターンV", 101, 0.0),
        ("スマスロ北斗の拳", 102, 0.0003),
    ):
        for idx, date_ts in enumerate(dates):
            dd = int(date_ts.day)
            rows.append(
                {
                    "date": date_ts.strftime("%Y%m%d"),
                    "machine_name": machine_name,
                    "machine_number": machine_number,
                    "games": 2400 + (idx % 7) * 10,
                    "rb_count": 10 + (dd % 4),
                    "rb_prob": 0.0035 + dd * 0.0001 + bias,
                    "diff": float(100 + dd),
                    "date_ts": date_ts,
                    "dd": dd,
                    "hall": "testhall",
                }
            )
    return pd.DataFrame(rows)


def test_load_target_machine_frame_uses_exact_machine_name_match(tmp_path: Path, monkeypatch) -> None:
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    db_path = db_dir / "test.db"
    _seed_machine_table(db_path)

    monkeypatch.setattr(mod, "DB_DIR", db_dir)
    monkeypatch.setattr(mod, "HALL_DBS", {"testhall": "test.db"})

    frame = mod.load_target_machine_frame("testhall")

    assert set(frame["machine_name"]) == {"モンキーターンV", "スマスロ北斗の拳"}
    assert frame["machine_number"].tolist() == [101, 102]
    assert set(frame["hall"]) == {"testhall"}


def test_main_writes_machine_level_outputs_without_pooled_csvs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "HALL_DBS", {"testhall": "unused.db"})
    monkeypatch.setattr(mod, "DEFAULT_HALLS", ["testhall"])
    monkeypatch.setattr(mod, "load_target_machine_frame", lambda hall: _make_scan_frame())

    output_dir = tmp_path / "results"
    exit_code = mod.main(["--halls", "testhall", "--output-dir", str(output_dir)])

    assert exit_code == 0
    assert (output_dir / "testhall_summary.csv").exists()
    assert (output_dir / "testhall_dd_profile.csv").exists()
    assert (output_dir / "all_halls_summary.csv").exists()
    assert (output_dir / "all_halls_dd_profile.csv").exists()
    assert not list(output_dir.glob("*pooled*"))

    summary = pd.read_csv(output_dir / "all_halls_summary.csv")
    assert len(summary) == 2
    assert set(summary["machine_name"]) == {"モンキーターンV", "スマスロ北斗の拳"}
