from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ml.last_digit.kamata7_notebooklm_verification import build_report, load_sources, main


def _seed_kamata7_db(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE machine_detailed_results (
                date TEXT NOT NULL,
                machine_name TEXT NOT NULL,
                machine_number INTEGER NOT NULL,
                games_normalized INTEGER NOT NULL,
                diff_coins_normalized INTEGER NOT NULL,
                is_zorome INTEGER NOT NULL
            );

            CREATE TABLE machine_master (
                machine_name_normalized TEXT NOT NULL,
                jug_flag INTEGER NOT NULL DEFAULT 0,
                hana_flag INTEGER NOT NULL DEFAULT 0,
                oki_flag INTEGER NOT NULL DEFAULT 0,
                bt_flag INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE daily_hall_summary (
                date TEXT NOT NULL,
                day_of_week TEXT,
                last_digit INTEGER,
                weekday_nth TEXT,
                is_any_event INTEGER NOT NULL DEFAULT 0,
                is_zorome INTEGER NOT NULL DEFAULT 0,
                avg_diff_per_machine REAL,
                avg_games_per_machine REAL,
                win_rate REAL
            );
            """
        )
        conn.executemany(
            "INSERT INTO machine_master VALUES (?, ?, ?, ?, ?)",
            [
                ("マイジャグラーV", 1, 0, 0, 0),
                ("東京喰種", 0, 0, 0, 0),
                ("ミリオンゴッド-神々の系譜-", 0, 0, 0, 0),
                ("新台A", 0, 0, 0, 0),
            ],
        )
        conn.executemany(
            "INSERT INTO daily_hall_summary VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("20260528", "木", 8, "Thu4", 0, 0, 0.0, 0.0, 0.0),
                ("20260529", "金", 9, "Fri5", 0, 0, 0.0, 0.0, 0.0),
                ("20260530", "土", 0, "Sat5", 1, 0, 0.0, 0.0, 0.0),
                ("20260531", "日", 1, "Sun5", 1, 1, 0.0, 0.0, 0.0),
                ("20260601", "月", 1, "Mon1", 0, 0, 0.0, 0.0, 0.0),
                ("20260602", "火", 2, "Tue1", 0, 0, 0.0, 0.0, 0.0),
            ],
        )
        conn.executemany(
            "INSERT INTO machine_detailed_results VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("20260528", "マイジャグラーV", 2101, 1200, 180, 0),
                ("20260528", "東京喰種", 3101, 1400, 420, 0),
                ("20260528", "ミリオンゴッド-神々の系譜-", 3201, 1600, -1200, 0),
                ("20260529", "マイジャグラーV", 2101, 1300, 250, 0),
                ("20260529", "東京喰種", 3101, 1500, 600, 0),
                ("20260529", "ミリオンゴッド-神々の系譜-", 3201, 1600, -1000, 0),
                ("20260530", "マイジャグラーV", 2101, 1400, 650, 0),
                ("20260530", "東京喰種", 3101, 1600, 900, 0),
                ("20260530", "ミリオンゴッド-神々の系譜-", 3201, 1700, -800, 0),
                ("20260531", "マイジャグラーV", 2101, 1500, 700, 0),
                ("20260531", "東京喰種", 3101, 1700, 850, 0),
                ("20260531", "ミリオンゴッド-神々の系譜-", 3201, 1700, -700, 0),
                ("20260601", "マイジャグラーV", 2101, 1000, 50, 0),
                ("20260601", "東京喰種", 3101, 1800, 500, 0),
                ("20260601", "ミリオンゴッド-神々の系譜-", 3201, 1800, -500, 0),
                ("20260601", "新台A", 3301, 1000, -300, 0),
                ("20260602", "マイジャグラーV", 2101, 900, -100, 0),
                ("20260602", "東京喰種", 3101, 1900, 700, 0),
                ("20260602", "ミリオンゴッド-神々の系譜-", 3201, 1800, -400, 0),
                ("20260602", "新台A", 3301, 1100, -200, 0),
            ],
        )


def test_build_report_emits_all_task_sections(tmp_path: Path) -> None:
    db_path = tmp_path / "kamata7.db"
    _seed_kamata7_db(db_path)

    sources = load_sources(db_path)
    report = build_report(sources=sources, min_games=0)

    assert "Task 1" in report.markdown
    assert "Task 2" in report.markdown
    assert "Task 3" in report.markdown
    assert "Task 4" in report.markdown
    assert "2026-05-30" in report.markdown
    assert "0-2" in set(report.tables["task2_debut_buckets"]["debut_bucket"])
    assert {"juggler", "candidate_at", "other"} <= set(report.tables["task3_variance_summary"]["category"])


def test_cli_writes_markdown_and_csv(tmp_path: Path) -> None:
    db_path = tmp_path / "kamata7.db"
    out_dir = tmp_path / "out"
    _seed_kamata7_db(db_path)

    exit_code = main(
        [
            "--db-path",
            str(db_path),
            "--output-dir",
            str(out_dir),
            "--min-games",
            "0",
        ]
    )

    assert exit_code == 0
    assert (out_dir / "report.md").exists()
    assert (out_dir / "report.json").exists()
    assert any(p.suffix == ".csv" for p in out_dir.iterdir())
    md = (out_dir / "report.md").read_text(encoding="utf-8")
    assert "Task 1" in md
    assert "Task 2" in md
    payload = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    assert payload["db_path"].endswith("kamata7.db")
