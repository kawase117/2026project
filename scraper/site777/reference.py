"""Read-only access to 2026Project machine layout and machine master."""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from collections import defaultdict
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REFERENCE_DB = PROJECT_ROOT / "db" / "楽園蒲田店.db"
DEFAULT_ALIAS_FILE = Path(__file__).resolve().parent / "config" / "machine_aliases.json"
ALIAS_SPLIT_PATTERN = re.compile(r"[,\n\r|/；;、]+")


def normalize_machine_key(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    if text.startswith("l") and not text.startswith("lb"):
        text = text[1:]
    return re.sub(r"[^\w]+", "", text, flags=re.UNICODE)


def _read_only_connection(path: Path) -> sqlite3.Connection:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"参照DBが見つかりません: {resolved}")
    return sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def _load_layout(connection: sqlite3.Connection, business_date: str | None) -> list[dict[str, Any]]:
    columns = (
        "machine_number, hall_name, x, y, display_y, section, section_min, "
        "section_max, rank_from_min, rank_from_max, rank_from_aisle"
    )
    if business_date and _table_exists(connection, "machine_layout_history"):
        rows = connection.execute(
            f"""
            SELECT {columns}
              FROM machine_layout_history
             WHERE valid_from <= ?
               AND (valid_to IS NULL OR valid_to >= ?)
            """,
            (business_date, business_date),
        ).fetchall()
    else:
        rows = connection.execute(f"SELECT {columns} FROM machine_layout").fetchall()
    names = [item.strip() for item in columns.split(",")]
    return [dict(zip(names, row)) for row in rows]


def _split_aliases(value: Any) -> Iterable[str]:
    if not value:
        return []
    normalized = unicodedata.normalize("NFKC", str(value))
    return [part.strip() for part in ALIAS_SPLIT_PATTERN.split(normalized) if part.strip()]


def _load_alias_overrides(path: Path | None) -> dict[str, str]:
    if path is None or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("machine_aliases.json は mdc: machine_name のオブジェクト形式が必要です")
    return {str(key): str(value) for key, value in payload.items()}


def load_reference_context(
    db_path: Path = DEFAULT_REFERENCE_DB,
    *,
    business_date: str | None = None,
    alias_path: Path | None = DEFAULT_ALIAS_FILE,
) -> dict[str, Any]:
    """Load only layout and machine-master rows; never open the DB for writing."""
    # `with sqlite3.connect(...)` はトランザクション境界でしかなく接続を閉じないため closing で包む。
    with closing(_read_only_connection(db_path)) as connection:
        layout = _load_layout(connection, business_date)
        master_rows = connection.execute(
            """
            SELECT machine_name_normalized, jug_flag, hana_flag, oki_flag, bt_flag,
                   display_names, official_name
              FROM machine_master
            """
        ).fetchall()

    master: dict[str, dict[str, Any]] = {}
    key_candidates: dict[str, set[str]] = defaultdict(set)
    for row in master_rows:
        item = {
            "machine_name_normalized": row[0],
            "jug_flag": int(row[1] or 0),
            "hana_flag": int(row[2] or 0),
            "oki_flag": int(row[3] or 0),
            "bt_flag": int(row[4] or 0),
            "display_names": row[5],
            "official_name": row[6],
        }
        canonical = str(row[0])
        master[canonical] = item
        aliases = [canonical, row[6], *_split_aliases(row[5])]
        for alias in aliases:
            key = normalize_machine_key(alias)
            if key:
                key_candidates[key].add(canonical)

    alias_index = {key: next(iter(values)) for key, values in key_candidates.items() if len(values) == 1}
    # 同じ正規化キーに複数の機種が当たる場合は自動対応を諦めるが、握り潰さず内容を返す。
    ambiguous_aliases = {key: sorted(values) for key, values in key_candidates.items() if len(values) > 1}
    return {
        "db_path": str(db_path.expanduser().resolve()),
        "business_date": business_date,
        "layout_by_number": {int(row["machine_number"]): row for row in layout},
        "master": master,
        "alias_index": alias_index,
        "ambiguous_aliases": ambiguous_aliases,
        "mdc_overrides": _load_alias_overrides(alias_path),
    }


def _machine_category(master: dict[str, Any] | None) -> str | None:
    if master is None:
        return None
    for column, category in (
        ("jug_flag", "jug"),
        ("hana_flag", "hana"),
        ("oki_flag", "oki"),
        ("bt_flag", "bt"),
    ):
        if master[column]:
            return category
    return "other"


def enrich_machines(machines: list[dict[str, Any]], context: dict[str, Any]) -> dict[str, Any]:
    layout_by_number = context["layout_by_number"]
    master = context["master"]
    alias_index = context["alias_index"]
    overrides = context["mdc_overrides"]
    layout_matches = 0
    master_matches = 0
    override_matches = 0
    unmatched_models: dict[str, dict[str, Any]] = {}
    unmatched_layout_numbers: list[int] = []

    for machine in machines:
        number = int(machine["machine_number"])
        layout = layout_by_number.get(number)
        machine["layout_matched"] = layout is not None
        for column in (
            "hall_name",
            "x",
            "y",
            "display_y",
            "section",
            "section_min",
            "section_max",
            "rank_from_min",
            "rank_from_max",
            "rank_from_aisle",
        ):
            machine[column] = layout.get(column) if layout else None
        layout_matches += layout is not None
        if layout is None:
            unmatched_layout_numbers.append(number)

        canonical = overrides.get(str(machine["mdc"]))
        mapping_method = "mdc_override" if canonical else "normalized_alias"
        if canonical:
            override_matches += 1
        else:
            canonical = alias_index.get(normalize_machine_key(machine["model_name"]))
        master_item = master.get(canonical) if canonical else None
        machine["master_matched"] = master_item is not None
        machine["master_mapping_method"] = mapping_method if master_item else None
        machine["machine_name_normalized"] = canonical if master_item else None
        machine["machine_category"] = _machine_category(master_item)
        for flag in ("jug_flag", "hana_flag", "oki_flag", "bt_flag"):
            machine[flag] = master_item[flag] if master_item else None
        master_matches += master_item is not None
        if master_item is None:
            # config/machine_aliases.json を埋められるように、落ちた機種を mdc 単位で控える。
            entry = unmatched_models.setdefault(
                str(machine["mdc"]),
                {
                    "mdc": str(machine["mdc"]),
                    "model_name": machine["model_name"],
                    "normalized_key": normalize_machine_key(machine["model_name"]),
                    "machine_count": 0,
                },
            )
            entry["machine_count"] += 1

    ambiguous_aliases = context.get("ambiguous_aliases", {})
    return {
        "enabled": True,
        "db_path": context["db_path"],
        "business_date": context["business_date"],
        "layout_rows": len(layout_by_number),
        "layout_matches": layout_matches,
        "layout_unmatched": len(machines) - layout_matches,
        "layout_unmatched_numbers": sorted(unmatched_layout_numbers),
        "master_rows": len(master),
        "master_matches": master_matches,
        "master_unmatched": len(machines) - master_matches,
        "master_unmatched_models": sorted(
            unmatched_models.values(), key=lambda item: (-item["machine_count"], item["mdc"])
        ),
        "master_unmatched_model_count": len(unmatched_models),
        "ambiguous_alias_count": len(ambiguous_aliases),
        "ambiguous_aliases": ambiguous_aliases,
        "mdc_override_matches": override_matches,
    }


def build_physical_lanes(
    machines: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build ordered rows inside each section using the less-variable axis as lane."""
    sections: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for machine in machines:
        if (
            machine.get("layout_matched")
            and machine.get("section") is not None
            and machine.get("x") is not None
            and machine.get("y") is not None
        ):
            sections[str(machine["section"])].append(machine)

    lanes: list[dict[str, Any]] = []
    for section, group in sections.items():
        x_count = len({machine["x"] for machine in group})
        y_count = len({machine["y"] for machine in group})
        lane_axis, position_axis = ("x", "y") if x_count <= y_count else ("y", "x")
        by_lane: dict[Any, list[dict[str, Any]]] = defaultdict(list)
        for machine in group:
            by_lane[machine[lane_axis]].append(machine)
        for lane_value, lane_machines in by_lane.items():
            ordered = sorted(
                lane_machines,
                key=lambda machine: (machine[position_axis], int(machine["machine_number"])),
            )
            lane_key = f"{section}|{lane_axis}={lane_value}"
            lane_size = len(ordered)
            for index, machine in enumerate(ordered):
                machine["physical_lane_key"] = lane_key
                machine["physical_lane_size"] = lane_size
                # 列の端からの距離。プロジェクトの「角番」(rank_from_aisle / rank_from_min-max)
                # とは別概念なので、角番とは呼ばない。
                machine["lane_edge_rank"] = min(index + 1, lane_size - index)
            lanes.append(
                {
                    "key": lane_key,
                    "section": section,
                    "lane_axis": lane_axis,
                    "lane_value": lane_value,
                    "position_axis": position_axis,
                    "machines": ordered,
                }
            )
    return lanes
