from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest


def _make_machine_rows(hall_name: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dates = pd.date_range("2026-01-01", periods=100, freq="D")
    machines = [
        (101, "alpha", "A", 1, "2F"),
        (102, "beta", "A", 2, "2F"),
        (201, "gamma", "B", 1, "3F"),
        (202, "delta", "B", 2, "3F"),
    ]

    detail_rows: list[dict[str, object]] = []
    layout_rows: list[dict[str, object]] = []
    master_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []

    for machine_number, machine_name, section, rank_from_min, floor in machines:
        layout_rows.append(
            {
                "machine_number": machine_number,
                "rank_from_min": rank_from_min,
                "rank_from_max": 3 - rank_from_min,
                "rank_from_aisle": rank_from_min,
                "is_reversed_section": 0,
                "section": section,
                "floor": floor,
            }
        )
        master_rows.append(
            {
                "machine_name_normalized": machine_name,
                "jug_flag": 0,
                "hana_flag": 0,
                "oki_flag": 0,
                "bt_flag": 0,
            }
        )

    for date in dates:
        date_str = date.strftime("%Y%m%d")
        dd = int(date_str[-2:])
        boost = dd in {1, 11, 21, 31}
        summary_rows.append(
            {
                "date": date_str,
                "avg_diff_per_machine": 120 if boost else 80,
            }
        )
        for machine_number, machine_name, section, rank_from_min, _floor in machines:
            if section == "A":
                diff = 600 if boost else 60
            else:
                diff = -200 if boost else -40
            detail_rows.append(
                {
                    "date": date_str,
                    "machine_number": machine_number,
                    "machine_name": machine_name,
                    "machine_rank_in_type": rank_from_min,
                    "last_digit": str(machine_number % 10),
                    "diff_coins_normalized": diff,
                    "games_normalized": 1000,
                    "is_zorome": 0,
                }
            )

    detail_frame = pd.DataFrame(detail_rows)
    layout_frame = pd.DataFrame(layout_rows)
    master_frame = pd.DataFrame(master_rows)
    summary_frame = pd.DataFrame(summary_rows)
    return detail_frame, layout_frame, master_frame, summary_frame


def _write_db(
    db_path: Path, detail: pd.DataFrame, layout: pd.DataFrame, master: pd.DataFrame, summary: pd.DataFrame
) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        detail.to_sql("machine_detailed_results", conn, index=False, if_exists="replace")
        layout.to_sql("machine_layout", conn, index=False, if_exists="replace")
        master.to_sql("machine_master", conn, index=False, if_exists="replace")
        summary.to_sql("daily_hall_summary", conn, index=False, if_exists="replace")


def _write_coords_csv_explicit(path: Path, hall_name: str, floor: str, rows: list[tuple[int, int, int, str]]) -> None:
    frame = pd.DataFrame(rows, columns=["machine_number", "rank_from_min", "rank_from_max", "section"])
    frame.insert(0, "hall_name", hall_name)
    frame.insert(1, "floor", floor)
    frame["X"] = frame["machine_number"]
    frame["Y"] = frame["machine_number"]
    frame["display_x"] = frame["X"]
    frame["display_y"] = frame["Y"]
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def test_main_writes_nonempty_section_and_kakuban_csvs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from eda import section_kakuban_axis_pattern_scan as analysis
    from eda.core import HALL_EVENT_DIGITS

    db_dir = tmp_path / "db"
    out_dir = tmp_path / "out"

    hall_db_names = {
        "蒲田7": "kamata7.db",
        "蒲田1": "kamata1.db",
        "みとや": "mitoya.db",
    }
    kama_detail, kama_layout, kama_master, kama_summary = _make_machine_rows("蒲田7")
    kama1_detail, kama1_layout, kama1_master, kama1_summary = _make_machine_rows("蒲田1")
    mito_detail, mito_layout, mito_master, mito_summary = _make_machine_rows("みとや")

    _write_db(db_dir / "kamata7.db", kama_detail, kama_layout, kama_master, kama_summary)
    _write_db(db_dir / "kamata1.db", kama1_detail, kama1_layout, kama1_master, kama1_summary)
    _write_db(db_dir / "mitoya.db", mito_detail, mito_layout, mito_master, mito_summary)

    coords1 = tmp_path / "coords1.csv"
    coords7_2f = tmp_path / "coords7_2f.csv"
    coords7_3f = tmp_path / "coords7_3f.csv"
    _write_coords_csv_explicit(
        coords1,
        "蒲田1",
        "2F",
        [(101, 1, 2, "A"), (102, 2, 1, "A"), (201, 1, 2, "B"), (202, 2, 1, "B")],
    )
    _write_coords_csv_explicit(
        coords7_2f,
        "蒲田7",
        "2F",
        [(101, 1, 2, "A"), (102, 2, 1, "A")],
    )
    _write_coords_csv_explicit(
        coords7_3f,
        "蒲田7",
        "3F",
        [(201, 1, 2, "B"), (202, 2, 1, "B")],
    )

    def _load_hall_df_from_db(hall: str) -> pd.DataFrame:
        db_path = db_dir / hall_db_names[hall]
        with sqlite3.connect(db_path) as conn:
            frame = pd.read_sql_query(
                """
                SELECT
                    date,
                    machine_number,
                    machine_name,
                    diff_coins_normalized AS diff,
                    games_normalized AS games
                FROM machine_detailed_results
                """,
                conn,
            )
        dates = pd.to_datetime(frame["date"], format="%Y%m%d")
        weekday_jp = ["月", "火", "水", "木", "金", "土", "日"]
        dd = dates.dt.day.astype(int)
        frame["plus"] = (pd.to_numeric(frame["diff"], errors="coerce").fillna(0) > 0).astype(int)
        frame["dd"] = dd
        frame["day_of_week"] = dates.dt.weekday.map(lambda idx: weekday_jp[idx])
        frame["is_x_day"] = dd.isin(set(HALL_EVENT_DIGITS[hall])).astype(int)
        frame["hall"] = hall
        return frame

    monkeypatch.setattr(analysis, "load_hall_df", _load_hall_df_from_db)

    exit_code = analysis.main(
        [
            "--halls",
            "蒲田7,蒲田1,みとや",
            "--output-dir",
            str(out_dir),
            "--min-group-days-total",
            "200",
            "--min-obs-for-ranking",
            "5",
            "--top-n",
            "10",
            "--coords1",
            str(coords1),
            "--coords7-2f",
            str(coords7_2f),
            "--coords7-3f",
            str(coords7_3f),
            "--mitoya-db-path",
            str(db_dir / "mitoya.db"),
        ]
    )

    assert exit_code == 0

    for hall in ["蒲田7", "蒲田1", "みとや"]:
        for granularity in ["section", "kakuban"]:
            pattern_path = out_dir / f"{hall}_{granularity}_pattern_summary.csv"
            top_path = out_dir / f"{hall}_{granularity}_top_signals.csv"
            breakdown_path = out_dir / f"{hall}_{granularity}_top_signal_breakdown.csv"
            summary_path = out_dir / f"{hall}_{granularity}_summary_report.csv"
            assert pattern_path.exists()
            assert top_path.exists()
            assert breakdown_path.exists()
            assert summary_path.exists()
            pattern = pd.read_csv(pattern_path, encoding="utf-8-sig")
            assert not pattern.empty
            assert set(pattern["granularity"].astype(str)) == {granularity}
