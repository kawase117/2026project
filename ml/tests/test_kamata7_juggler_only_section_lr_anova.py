from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd


def _make_coords_csv(tmp_path: Path) -> Path:
    rows = []
    for section, machine_numbers, x_start in [
        ("S1", [1001, 1002, 1003, 1004], 10),
        ("S2", [1011, 1012, 1013, 1014, 1015, 1016, 1017, 1018, 1019, 1020], 100),
    ]:
        for rank, machine_number in enumerate(machine_numbers, start=1):
            rows.append(
                {
                    "hall_name": "蒲田7",
                    "floor": "3F",
                    "machine_number": machine_number,
                    "X": float(x_start + rank * 10),
                    "Y": float(rank),
                    "section": section,
                    "rank_from_min": rank,
                    "rank_from_max": len(machine_numbers) - rank + 1,
                }
            )
    coords_path = tmp_path / "coords_3f.csv"
    pd.DataFrame(rows).to_csv(coords_path, index=False, encoding="utf-8-sig")
    return coords_path


def _make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "kamata7.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE machine_detailed_results (
                date TEXT NOT NULL,
                machine_number INTEGER NOT NULL,
                machine_name TEXT NOT NULL,
                diff_coins_normalized REAL NOT NULL,
                games_normalized REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE machine_master (
                machine_name_normalized TEXT NOT NULL,
                jug_flag INTEGER NOT NULL,
                hana_flag INTEGER NOT NULL,
                bt_flag INTEGER NOT NULL
            )
            """
        )

        machine_rows = []
        master_rows = []

        for machine_number, pay_rate in zip(range(1001, 1005), [96.0, 97.0, 98.0, 99.0], strict=True):
            machine_name = "マイジャグラーV"
            diff = 1000 * 3 * (pay_rate / 100.0 - 1.0)
            machine_rows.append(("20260701", machine_number, machine_name, diff, 1000.0))
            master_rows.append((machine_name, 1, 0, 0))

        for machine_number, pay_rate in zip(
            range(1011, 1021),
            [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0],
            strict=True,
        ):
            machine_name = "アイムジャグラーEX"
            diff = 1000 * 3 * (pay_rate / 100.0 - 1.0)
            machine_rows.append(("20260701", machine_number, machine_name, diff, 1000.0))
            master_rows.append((machine_name, 1, 0, 0))

        machine_rows.append(("20260701", 2026, "マイジャグラーV", 0.0, 1000.0))
        master_rows.append(("マイジャグラーV", 1, 0, 0))

        machine_rows.append(("20260707", 1501, "ハナハナホウオウ", 0.0, 1000.0))
        master_rows.append(("ハナハナホウオウ", 0, 1, 0))

        machine_rows.append(("20260701", 1601, "その他機種", 0.0, 1000.0))
        master_rows.append(("その他機種", 0, 0, 0))

        conn.executemany(
            "INSERT INTO machine_detailed_results (date, machine_number, machine_name, diff_coins_normalized, games_normalized) VALUES (?, ?, ?, ?, ?)",
            machine_rows,
        )
        conn.executemany(
            "INSERT INTO machine_master (machine_name_normalized, jug_flag, hana_flag, bt_flag) VALUES (?, ?, ?, ?)",
            master_rows,
        )
        conn.commit()
    return db_path


def test_build_juggler_only_frame_and_summary(tmp_path: Path) -> None:
    from ml.analysis import kamata7_juggler_only_section_lr_anova as anova

    db_path = _make_db(tmp_path)
    coords_path = _make_coords_csv(tmp_path)

    frame = anova.build_juggler_only_frame(db_path=db_path, coords_path=coords_path)

    assert len(frame) == 14
    assert set(frame["machine_number"]) == set(range(1001, 1005)) | set(range(1011, 1021))
    assert 2026 not in set(frame["machine_number"])
    assert 1501 not in set(frame["machine_number"])
    assert 1601 not in set(frame["machine_number"])
    assert frame["section_size"].nunique() == 2
    assert set(frame["section_size_group"]) == {"small", "medium"}
    assert set(frame["side_lr"]) == {"L", "R"}

    summary = anova.build_juggler_only_f_values(frame)
    row = summary.iloc[0]
    assert row["n_rows"] == 14
    assert row["n_sections"] == 2
    assert np.isfinite(float(row["section_size_f"]))
    assert np.isfinite(float(row["lr_f"]))


def test_main_writes_requested_output(tmp_path: Path) -> None:
    from ml.analysis import kamata7_juggler_only_section_lr_anova as anova

    db_path = _make_db(tmp_path)
    coords_path = _make_coords_csv(tmp_path)
    output_path = tmp_path / "out" / "kamata7_juggler_only_f_values.csv"

    exit_code = anova.main(["--db", str(db_path), "--coords-3f", str(coords_path), "--output", str(output_path)])

    assert exit_code == 0
    assert output_path.exists()
    exported = pd.read_csv(output_path)
    assert {"section_size_f", "lr_f"} <= set(exported.columns)
