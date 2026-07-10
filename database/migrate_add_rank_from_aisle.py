"""One-shot migration for machine_layout.rank_from_aisle.

This script is intentionally not invoked by the dashboard. Run it manually after
reviewing the target DB list.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_DIR = PROJECT_ROOT / "db"
HEATMAP_DIR = PROJECT_ROOT / "Heatmap"

HALL_ALIASES = {
    "kamata7": ("kamata7", "蒲田7"),
    "kamata1": ("kamata1", "蒲田1"),
}


def _machine_layout_columns(con: sqlite3.Connection) -> set[str]:
    return {row[1] for row in con.execute("PRAGMA table_info(machine_layout)").fetchall()}


def _has_machine_layout(con: sqlite3.Connection) -> bool:
    row = con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'machine_layout' LIMIT 1").fetchone()
    return row is not None


def _infer_hall_key(db_path: Path, con: sqlite3.Connection) -> str | None:
    candidates = [db_path.stem, db_path.name]
    try:
        rows = con.execute("SELECT DISTINCT hall_name FROM machine_layout WHERE hall_name IS NOT NULL").fetchall()
        candidates.extend(str(row[0]) for row in rows)
    except sqlite3.Error:
        pass

    haystack = " ".join(candidates).lower()
    for hall_key, aliases in HALL_ALIASES.items():
        if any(alias.lower() in haystack for alias in aliases):
            return hall_key
    return None


def _load_rank_from_aisle(hall_key: str) -> dict[int, int]:
    ranks: dict[int, int] = {}
    for path in sorted(HEATMAP_DIR.glob(f"*floor_coordinates_{hall_key}.csv")):
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if "machine_number" not in (reader.fieldnames or []) or "rank_from_aisle" not in (reader.fieldnames or []):
                continue
            for row in reader:
                try:
                    machine_number = int(str(row["machine_number"]).strip())
                    rank_from_aisle = int(str(row["rank_from_aisle"]).strip())
                except TypeError, ValueError:
                    continue
                ranks[machine_number] = rank_from_aisle
    return ranks


def migrate_db(db_path: Path) -> tuple[str, int]:
    with sqlite3.connect(str(db_path)) as con:
        if not _has_machine_layout(con):
            return "skip:no_machine_layout", 0

        columns = _machine_layout_columns(con)
        if "rank_from_aisle" not in columns:
            con.execute("ALTER TABLE machine_layout ADD COLUMN rank_from_aisle INTEGER")

        hall_key = _infer_hall_key(db_path, con)
        if hall_key is None:
            con.commit()
            return "skip:unknown_hall", 0

        ranks = _load_rank_from_aisle(hall_key)
        if not ranks:
            con.commit()
            return f"skip:no_csv_rank:{hall_key}", 0

        con.executemany(
            "UPDATE machine_layout SET rank_from_aisle = ? WHERE machine_number = ?",
            [(rank, machine_number) for machine_number, rank in ranks.items()],
        )
        updated = int(con.total_changes)
        con.commit()
        return f"updated:{hall_key}", updated


def main() -> None:
    for db_path in sorted(DB_DIR.glob("*.db")):
        status, updated = migrate_db(db_path)
        print(f"{db_path.name}\t{status}\trows={updated}")


if __name__ == "__main__":
    main()
