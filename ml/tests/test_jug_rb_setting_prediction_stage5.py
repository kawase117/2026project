from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.stats import binom


def _make_stage2_frame() -> pd.DataFrame:
    rows = []
    date = "20260701"
    for idx, machine_number in enumerate(range(1001, 1009), start=1):
        section = "A" if machine_number <= 1004 else "B"
        x = float(idx * 10)
        rows.append(
            {
                "date": date,
                "machine_number": machine_number,
                "machine_name": "マイジャグラーV",
                "G": 1000,
                "rb": 9 - idx,
                "bb": 0,
                "p_high": 0.2 + idx * 0.01,
                "e_setting": 1.0 + idx * 0.1,
                "e_payout": 96.0 + idx * 0.1,
                "section": section,
                "x": x,
                "section_min": 1 if section == "A" else 5,
                "section_max": 4 if section == "A" else 8,
                "rank_from_min": idx if section == "A" else idx - 4,
                "rank_from_max": 5 - idx if section == "A" else 9 - idx,
            }
        )
    for idx, machine_number in enumerate(range(2001, 2005), start=1):
        rows.append(
            {
                "date": date,
                "machine_number": machine_number,
                "machine_name": "ゴーゴージャグラー3",
                "G": 1000,
                "rb": 1 + idx,
                "bb": 0,
                "p_high": 0.1 + idx * 0.01,
                "e_setting": 1.0,
                "e_payout": 96.0,
                "section": "C" if machine_number <= 2002 else "D",
                "x": float(200 + idx * 10),
                "section_min": 1,
                "section_max": 2,
                "rank_from_min": idx if machine_number <= 2002 else idx - 2,
                "rank_from_max": 3 - idx if machine_number <= 2002 else 5 - idx,
            }
        )
    return pd.DataFrame(rows)


def _make_layout_frame() -> pd.DataFrame:
    rows = []
    for section, numbers, x_base in [
        ("A", range(1001, 1005), 10),
        ("B", range(1005, 1009), 100),
        ("C", range(2001, 2003), 200),
        ("D", range(2003, 2005), 300),
    ]:
        for offset, machine_number in enumerate(numbers, start=1):
            rows.append(
                {
                    "machine_number": machine_number,
                    "section": section,
                    "kakuban_rank_min": offset,
                    "kakuban_rank_max": len(list(numbers)) - offset + 1,
                    "section_size": len(list(numbers)),
                    "is_corner1": int(offset in {1, len(list(numbers))}),
                    "side_lr": "L" if offset <= len(list(numbers)) / 2 else "R",
                }
            )
    return pd.DataFrame(rows)


def _make_stage2_csv(path: Path) -> None:
    _make_stage2_frame().loc[
        :, ["date", "machine_number", "machine_name", "G", "rb", "bb", "p_high", "e_setting", "e_payout"]
    ].to_csv(
        path,
        index=False,
        encoding="utf-8-sig",
    )


def _make_db(path: Path) -> None:
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            """
            CREATE TABLE machine_layout (
                machine_number INTEGER,
                x REAL,
                section TEXT,
                section_min INTEGER,
                section_max INTEGER,
                rank_from_min INTEGER,
                rank_from_max INTEGER
            )
            """
        )
        layout = _make_stage2_frame().loc[
            :, ["machine_number", "x", "section", "section_min", "section_max", "rank_from_min", "rank_from_max"]
        ]
        conn.executemany(
            "INSERT INTO machine_layout (machine_number, x, section, section_min, section_max, rank_from_min, rank_from_max) VALUES (?, ?, ?, ?, ?, ?, ?)",
            layout.itertuples(index=False, name=None),
        )
        conn.commit()


def test_stage5_rank_daily_computes_midp_and_pct_columns() -> None:
    from ml.experiments.jug_rb_setting_prediction import stage5_rank_daily as stage5

    frame = _make_stage2_frame()
    layout = _make_layout_frame()
    out = stage5.build_stage5_rank_daily(frame, hall="蒲田7", layout_frame=layout)

    assert isinstance(out, pd.DataFrame)
    assert set(stage5.STAGE5_COLUMNS) <= set(out.columns)
    assert len(out) == len(frame)
    assert out["n_family"].eq(8).sum() == 8
    assert out["n_family"].eq(4).sum() == 4
    assert out["n_section"].eq(4).sum() == 8
    assert out["n_section"].eq(2).sum() == 4

    family_rows = out[out["family_key"].eq("MYV")].copy()
    assert family_rows["midp_family"].notna().all()
    assert family_rows["midp_section"].notna().all()
    assert family_rows["pct_family"].between(0.0, 1.0).all()
    assert family_rows["pct_family"].mean() == pytest.approx(0.5, abs=1e-12)

    low_family_rows = out[out["family_key"].eq("GOGO3")].copy()
    assert low_family_rows["midp_family"].isna().all()
    assert low_family_rows["pct_family"].isna().all()
    assert low_family_rows["midp_section"].isna().all()

    target = family_rows.iloc[0]
    pooled_rate = family_rows["rb"].sum() / family_rows["G"].sum()
    expected_midp = binom.cdf(int(target["rb"]) - 1, int(target["G"]), pooled_rate) + 0.5 * binom.pmf(
        int(target["rb"]), int(target["G"]), pooled_rate
    )
    assert target["midp_family"] == pytest.approx(expected_midp, rel=1e-12, abs=1e-12)
    assert target["pct_family"] == pytest.approx(0.9375, abs=1e-12)


def test_stage5_main_writes_requested_artifacts(tmp_path: Path) -> None:
    from ml.experiments.jug_rb_setting_prediction import stage5_rank_daily as stage5

    db_path = tmp_path / "kamata7.db"
    stage2_csv = tmp_path / "stage2_daily_posterior.csv"
    output_dir = tmp_path / "out"
    _make_db(db_path)
    _make_stage2_csv(stage2_csv)

    exit_code = stage5.main(
        [
            "--hall",
            "蒲田7",
            "--db-path",
            str(db_path),
            "--stage2-csv",
            str(stage2_csv),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    assert (output_dir / "stage5_rank_daily.csv").exists()
    assert (output_dir / "stage5_rank_daily_summary.md").exists()
    exported = pd.read_csv(output_dir / "stage5_rank_daily.csv")
    assert {"midp_family", "pct_family", "midp_section", "pct_section"} <= set(exported.columns)


def test_stage5_rank_daily_leaves_section_metrics_missing_when_layout_is_empty() -> None:
    from ml.experiments.jug_rb_setting_prediction import stage5_rank_daily as stage5

    frame = _make_stage2_frame()
    empty_layout = pd.DataFrame(
        columns=[
            "machine_number",
            "section",
            "kakuban_rank_min",
            "kakuban_rank_max",
            "section_size",
            "is_corner1",
            "side_lr",
        ]
    )

    out = stage5.build_stage5_rank_daily(frame, hall="arrow", layout_frame=empty_layout)

    assert len(out) == len(frame)
    assert out["section"].isna().all()
    assert out["n_section"].isna().all()
    assert out["n_family"].notna().all()
    assert out["midp_section"].isna().all()
    assert out["pct_section"].isna().all()
