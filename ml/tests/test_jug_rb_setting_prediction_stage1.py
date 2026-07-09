from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd


def _create_sample_db(path: Path) -> None:
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            """
            CREATE TABLE machine_detailed_results (
                date TEXT,
                machine_number INTEGER,
                machine_name TEXT,
                games_normalized INTEGER,
                rb_count INTEGER,
                bb_count INTEGER
            )
            """
        )
        rows = [
            ("20260601", 101, "アイムジャグラーEX", 1200, 4, 20),
            ("20260602", 102, "アイムジャグラーEX", 1300, 5, 18),
            ("20260601", 201, "マイジャグラーV", 1500, 6, 22),
            ("20260602", 202, "未確認ジャグラーX", 900, 2, 10),
            ("20260601", 301, "AT機", 2000, 0, 0),
        ]
        conn.executemany(
            "INSERT INTO machine_detailed_results VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()


def test_hall_db_config_excludes_forbidden_halls() -> None:
    from ml.experiments.jug_rb_setting_prediction import config

    assert set(config.HALL_DBS) == {
        "蒲田7",
        "蒲田1",
        "ARROW",
        "レイトギャップ",
        "みとや",
        "楽園蒲田",
        "ヒロキ",
        "ザシティ",
        "金時",
    }


def test_stage1_builds_catalog_and_setting_master(tmp_path: Path) -> None:
    from ml.experiments.jug_rb_setting_prediction import stage1_machine_catalog as stage1

    db_path = tmp_path / "sample.db"
    _create_sample_db(db_path)

    outputs = stage1.build_stage1_outputs(db_path=db_path, hall="蒲田7")
    catalog = outputs["machine_catalog"]
    master = outputs["setting_prob_master"]
    report = outputs["report"]

    assert isinstance(catalog, pd.DataFrame)
    assert isinstance(master, pd.DataFrame)
    assert {"hall", "machine_name", "family_key", "resolved_family_key", "is_unknown_family", "warning"} <= set(
        catalog.columns
    )
    assert catalog["machine_name"].tolist() == ["アイムジャグラーEX", "マイジャグラーV", "未確認ジャグラーX"]
    assert catalog.loc[catalog["machine_name"].eq("未確認ジャグラーX"), "family_key"].item() == "UNKNOWN"
    assert catalog.loc[catalog["machine_name"].eq("未確認ジャグラーX"), "resolved_family_key"].item() == ""
    assert catalog.loc[catalog["machine_name"].eq("未確認ジャグラーX"), "warning"].item() == "excluded_unknown_juggler"
    assert len(master) == 12
    row = master.loc[(master["machine_name"].eq("マイジャグラーV")) & (master["setting"].eq(6))].iloc[0]
    assert row["payout_rate"] == 109.4
    assert "未確認ジャグラーX" not in master["machine_name"].tolist()
    assert "Stage 1 Machine Catalog" in report


def test_main_writes_review_artifacts(tmp_path: Path) -> None:
    from ml.experiments.jug_rb_setting_prediction import stage1_machine_catalog as stage1

    db_path = tmp_path / "sample.db"
    _create_sample_db(db_path)
    output_dir = tmp_path / "out"

    exit_code = stage1.main(["--hall", "蒲田7", "--db-path", str(db_path), "--output-dir", str(output_dir)])

    assert exit_code == 0
    assert (output_dir / "stage1_machine_catalog.csv").exists()
    assert (output_dir / "stage1_setting_prob_master.csv").exists()
    assert (output_dir / "stage1_summary.md").exists()
