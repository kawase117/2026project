from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from ml.corner_section.mitoya_section_type_breakdown import (
    build_physical_corner_kruskal,
    build_section_type_cross,
    build_within_type_section_kruskal,
    load_analysis_frame_with_corner,
    main,
)


def _seed_breakdown_db(db_path: Path) -> None:
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
                rank_from_max INTEGER,
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

        machine_types = [
            ("jug", {"jug_flag": 1, "hana_flag": 0, "oki_flag": 0, "bt_flag": 0}, 130),
            ("bt", {"jug_flag": 0, "hana_flag": 0, "oki_flag": 0, "bt_flag": 1}, 100),
            ("hana", {"jug_flag": 0, "hana_flag": 1, "oki_flag": 0, "bt_flag": 0}, 70),
            ("oki", {"jug_flag": 0, "hana_flag": 0, "oki_flag": 1, "bt_flag": 0}, 40),
            ("other", {"jug_flag": 0, "hana_flag": 0, "oki_flag": 0, "bt_flag": 0}, 10),
        ]
        sections = [
            ("501-522", 1, 22, 60),
            ("557-573", 10, 15, 10),
            ("692-700", 3, 20, -50),
        ]

        master_rows = []
        layout_rows = []
        detail_rows = []
        machine_number = 1000
        for machine_type, flags, base in machine_types:
            master_rows.append({"machine_name_normalized": machine_type, **flags})
            for section, rank_min, rank_max, section_bonus in sections:
                for i in range(30):
                    noise = (i % 7) - 3
                    diff = base + section_bonus + noise
                    layout_rows.append(
                        {
                            "machine_number": machine_number,
                            "rank_from_min": rank_min,
                            "rank_from_max": rank_max,
                            "section": section,
                        }
                    )
                    detail_rows.append(
                        {
                            "date": "20250106",
                            "machine_number": machine_number,
                            "machine_name": machine_type,
                            "diff_coins_normalized": diff,
                            "machine_rank_in_type": (i % 5) + 1,
                            "games_normalized": 1000,
                        }
                    )
                    machine_number += 1

        pd.DataFrame(master_rows).to_sql("machine_master", con, if_exists="append", index=False)
        pd.DataFrame(layout_rows).to_sql("machine_layout", con, if_exists="append", index=False)
        pd.DataFrame(detail_rows).to_sql("machine_detailed_results", con, if_exists="append", index=False)
        pd.DataFrame([{"date": "20250106", "avg_diff_per_machine": 100}]).to_sql(
            "daily_hall_summary", con, if_exists="append", index=False
        )
        con.commit()
    finally:
        con.close()


def test_load_analysis_frame_with_corner_exposes_rank_bounds(tmp_path: Path) -> None:
    db_path = tmp_path / "mitoya.db"
    _seed_breakdown_db(db_path)

    df = load_analysis_frame_with_corner(db_path)

    assert "rank_from_max" in df.columns
    assert "rank_from_min" in df.columns


def test_section_and_physical_corner_reports(tmp_path: Path) -> None:
    db_path = tmp_path / "mitoya.db"
    _seed_breakdown_db(db_path)

    base_df = load_analysis_frame_with_corner(db_path)
    from ml.corner_section.mitoya_corner_section_analysis import prepare_analysis_frame

    prepared = prepare_analysis_frame(base_df)
    section_cross = build_section_type_cross(prepared)
    section_kruskal = build_within_type_section_kruskal(prepared)
    physical_kruskal = build_physical_corner_kruskal(prepared)

    assert set(section_cross["machine_type"].unique()) == {"jug", "bt", "hana", "oki", "other"}
    assert {"section", "machine_type", "avg_diff", "plus_rate", "sample_n"}.issubset(section_cross.columns)
    assert section_cross.groupby("section")["sample_n"].sum().to_dict() == {
        "501-522": 150,
        "557-573": 150,
        "692-700": 150,
    }

    assert set(section_kruskal["machine_type"]) == {"jug", "bt", "hana", "oki", "other"}
    assert section_kruskal["is_significant_5pct"].eq(1).all()
    assert (section_kruskal["epsilon_sq"] > 0).all()

    assert set(physical_kruskal["machine_type"]) == {"ALL", "jug", "bt", "hana", "oki", "other"}
    assert physical_kruskal.loc[physical_kruskal["machine_type"].eq("ALL"), "is_significant_5pct"].iloc[0] == 1


def test_main_writes_three_csvs_and_summaries(tmp_path: Path, capsys) -> None:
    db_path = tmp_path / "mitoya.db"
    _seed_breakdown_db(db_path)
    out_dir = tmp_path / "out"

    exit_code = main(["--db-path", str(db_path), "--output-dir", str(out_dir)])

    assert exit_code == 0
    assert (out_dir / "section_type_cross.csv").exists()
    assert (out_dir / "section_within_type_kruskal.csv").exists()
    assert (out_dir / "physical_corner_kruskal.csv").exists()
    captured = capsys.readouterr()
    assert "=== section の独立効果検証 ===" in captured.out
