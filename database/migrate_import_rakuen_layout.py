"""One-shot import of 楽園蒲田店's machine_layout from Heatmap/*_rakuen.csv.

This script is intentionally not invoked by the dashboard. Run it manually.

楽園's machine_layout table exists but was never populated (0 rows) even though
Heatmap/*_rakuen.csv coordinate files exist and are already used to render the
EDA heatmaps in eda/section_lateral_expansion.py. This backfills machine_layout
from those CSVs so the dashboard's interaction explorer (which reads from the
DB, not the CSVs) can offer the 端番(hanaban_min/max) axes for 楽園, matching
how 蒲田1 is populated (rank_from_min/rank_from_max only).

rank_from_aisle is intentionally left NULL: unlike 蒲田7's CSVs, 楽園's CSVs do
not carry a curated rank_from_aisle column, so no aisle structure has been
verified for this hall. Fabricating rank_from_aisle from rank_from_min would
manufacture a fake 角番(kakuban) signal.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "db" / "楽園蒲田店.db"
HEATMAP_DIR = PROJECT_ROOT / "Heatmap"
HALL_NAME = "楽園蒲田店"
CSV_GLOB = "*_rakuen.csv"


def _to_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def load_records() -> list[tuple]:
    records: list[tuple] = []
    for path in sorted(HEATMAP_DIR.glob(CSV_GLOB)):
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if row.get("hall_name") != HALL_NAME:
                    continue
                machine_number = _to_int(row.get("machine_number"))
                if machine_number is None:
                    continue
                records.append(
                    (
                        machine_number,
                        HALL_NAME,
                        _to_int(row.get("X")),
                        _to_int(row.get("Y")),
                        _to_int(row.get("display_y")),
                        row.get("section"),
                        _to_int(row.get("section_min")),
                        _to_int(row.get("section_max")),
                        _to_int(row.get("rank_from_min")),
                        _to_int(row.get("rank_from_max")),
                    )
                )
    return records


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"DB not found: {DB_PATH}")

    records = load_records()
    if not records:
        raise SystemExit("No matching rows found in Heatmap/*_rakuen.csv")

    with sqlite3.connect(str(DB_PATH)) as con:
        columns = {row[1] for row in con.execute("PRAGMA table_info(machine_layout)").fetchall()}
        required = {
            "machine_number",
            "hall_name",
            "x",
            "y",
            "display_y",
            "section",
            "section_min",
            "section_max",
            "rank_from_min",
            "rank_from_max",
        }
        missing = required - columns
        if missing:
            raise SystemExit(f"machine_layout missing expected columns: {sorted(missing)}")

        con.executemany(
            """
            INSERT OR REPLACE INTO machine_layout
            (machine_number, hall_name, x, y, display_y,
             section, section_min, section_max,
             rank_from_min, rank_from_max)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            records,
        )
        con.commit()

    print(f"imported {len(records)} rows into {DB_PATH.name}:machine_layout")


if __name__ == "__main__":
    main()
