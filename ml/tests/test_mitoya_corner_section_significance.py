from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from ml.corner_section.mitoya_corner_section_significance import (
    build_rank_from_min_significance_report,
    build_section_significance_report,
    main,
)


def _seed_significance_db(db_path: Path) -> None:
    con = sqlite3.connect(db_path)
    try:
        con.executescript(
            """
            CREATE TABLE machine_detailed_results (
                date TEXT,
                machine_number INTEGER,
                machine_name TEXT,
                diff_coins_normalized INTEGER,
                machine_rank_in_type INTEGER,
                games_normalized INTEGER
            );
            CREATE TABLE machine_layout (
                machine_number INTEGER,
                rank_from_min INTEGER,
                section TEXT
            );
            CREATE TABLE machine_master (
                machine_name_normalized TEXT,
                jug_flag INTEGER,
                hana_flag INTEGER,
                oki_flag INTEGER,
                bt_flag INTEGER
            );
            CREATE TABLE daily_hall_summary (
                date TEXT,
                avg_diff_per_machine INTEGER
            );
            """
        )
        pd.DataFrame(
            [
                {"machine_number": 101, "rank_from_min": 1, "section": "501-522"},
                {"machine_number": 102, "rank_from_min": 2, "section": "501-522"},
                {"machine_number": 103, "rank_from_min": 3, "section": "523-546"},
            ]
        ).to_sql("machine_layout", con, if_exists="append", index=False)
        pd.DataFrame(
            [
                {"machine_name_normalized": "A", "jug_flag": 0, "hana_flag": 0, "oki_flag": 0, "bt_flag": 0},
                {"machine_name_normalized": "B", "jug_flag": 0, "hana_flag": 0, "oki_flag": 0, "bt_flag": 0},
                {"machine_name_normalized": "C", "jug_flag": 0, "hana_flag": 0, "oki_flag": 0, "bt_flag": 0},
            ]
        ).to_sql("machine_master", con, if_exists="append", index=False)
        pd.DataFrame(
            [
                {"date": "20250106", "avg_diff_per_machine": 10},
                {"date": "20250107", "avg_diff_per_machine": 20},
                {"date": "20250108", "avg_diff_per_machine": 30},
            ]
        ).to_sql("daily_hall_summary", con, if_exists="append", index=False)
        pd.DataFrame(
            [
                {"date": "20250106", "machine_number": 101, "machine_name": "A", "diff_coins_normalized": 120, "machine_rank_in_type": 1, "games_normalized": 1000},
                {"date": "20250106", "machine_number": 102, "machine_name": "B", "diff_coins_normalized": 20, "machine_rank_in_type": 2, "games_normalized": 1000},
                {"date": "20250106", "machine_number": 103, "machine_name": "C", "diff_coins_normalized": -10, "machine_rank_in_type": 3, "games_normalized": 1000},
                {"date": "20250107", "machine_number": 101, "machine_name": "A", "diff_coins_normalized": 100, "machine_rank_in_type": 1, "games_normalized": 1000},
                {"date": "20250107", "machine_number": 102, "machine_name": "B", "diff_coins_normalized": 30, "machine_rank_in_type": 2, "games_normalized": 1000},
                {"date": "20250107", "machine_number": 103, "machine_name": "C", "diff_coins_normalized": -5, "machine_rank_in_type": 3, "games_normalized": 1000},
                {"date": "20250108", "machine_number": 101, "machine_name": "A", "diff_coins_normalized": 110, "machine_rank_in_type": 1, "games_normalized": 1000},
                {"date": "20250108", "machine_number": 102, "machine_name": "B", "diff_coins_normalized": 10, "machine_rank_in_type": 2, "games_normalized": 1000},
                {"date": "20250108", "machine_number": 103, "machine_name": "C", "diff_coins_normalized": 0, "machine_rank_in_type": 3, "games_normalized": 1000},
            ]
        ).to_sql("machine_detailed_results", con, if_exists="append", index=False)
        con.commit()
    finally:
        con.close()


def test_build_rank_from_min_significance_report_detects_clear_separation(tmp_path: Path) -> None:
    db_path = tmp_path / "mitoya.db"
    _seed_significance_db(db_path)

    from ml.corner_section.mitoya_corner_section_analysis import load_analysis_frame, prepare_analysis_frame

    df = prepare_analysis_frame(load_analysis_frame(db_path))
    report = build_rank_from_min_significance_report(df)

    overall = report.loc[report["test_type"].eq("kruskal_overall")].iloc[0]
    assert overall["n_groups"] == 3
    assert overall["n_rows"] == 9
    assert overall["p_value"] < 0.05
    assert overall["is_significant_5pct"] == 1


def test_main_writes_rank_from_min_report(tmp_path: Path, capsys) -> None:
    db_path = tmp_path / "mitoya.db"
    _seed_significance_db(db_path)
    out_csv = tmp_path / "out" / "kruskal_rank_from_min.csv"

    exit_code = main(["--db-path", str(db_path), "--output-csv", str(out_csv)])

    assert exit_code == 0
    assert out_csv.exists()
    report = pd.read_csv(out_csv)
    assert "kruskal_overall" in report["test_type"].tolist()
    captured = capsys.readouterr()
    assert "=== みとや 角番（rank_from_min）有意性検定 ===" in captured.out


def test_build_section_significance_report_uses_section_strings(tmp_path: Path) -> None:
    db_path = tmp_path / "mitoya.db"
    _seed_significance_db(db_path)

    from ml.corner_section.mitoya_corner_section_analysis import load_analysis_frame, prepare_analysis_frame

    df = prepare_analysis_frame(load_analysis_frame(db_path))
    report = build_section_significance_report(df)

    overall = report.loc[report["test_type"].eq("kruskal_overall")].iloc[0]
    assert overall["group_col"] == "section"
    assert overall["n_groups"] == 2
    assert overall["p_value"] < 0.05
    assert report.loc[report["test_type"].eq("group_summary"), "group_value"].map(type).eq(str).all()


def test_main_writes_two_csvs_to_output_dir(tmp_path: Path, capsys) -> None:
    db_path = tmp_path / "mitoya.db"
    _seed_significance_db(db_path)
    out_dir = tmp_path / "out"

    exit_code = main(["--db-path", str(db_path), "--output-dir", str(out_dir)])

    assert exit_code == 0
    rank_csv = out_dir / "kruskal_rank_from_min.csv"
    section_csv = out_dir / "kruskal_section.csv"
    assert rank_csv.exists()
    assert section_csv.exists()
    rank_report = pd.read_csv(rank_csv)
    section_report = pd.read_csv(section_csv)
    assert "kruskal_overall" in rank_report["test_type"].tolist()
    assert "kruskal_overall" in section_report["test_type"].tolist()
    captured = capsys.readouterr()
    assert "=== みとや 列（section）有意性検定 ===" in captured.out
