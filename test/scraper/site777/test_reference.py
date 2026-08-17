from __future__ import annotations

import sqlite3
from pathlib import Path

from scraper.site777.reference import (
    build_physical_lanes,
    enrich_machines,
    load_reference_context,
)
from scraper.site777.site777_analyze import (
    build_lane_edge_summaries,
    build_positive_blocks,
    build_three_machine_runs,
)


def _create_reference_db(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE machine_layout (
                machine_number INTEGER PRIMARY KEY,
                hall_name TEXT, x INTEGER, y INTEGER, display_y INTEGER,
                section TEXT, section_min INTEGER, section_max INTEGER,
                rank_from_min INTEGER, rank_from_max INTEGER,
                rank_from_aisle INTEGER
            );
            CREATE TABLE machine_master (
                machine_name_normalized TEXT PRIMARY KEY,
                jug_flag INTEGER, hana_flag INTEGER, oki_flag INTEGER,
                bt_flag INTEGER, display_names TEXT, official_name TEXT
            );
            """
        )
        connection.executemany(
            "INSERT INTO machine_layout VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                (101, "楽園蒲田店", 1, 10, 10, "island-a", 101, 305, 1, 3, None),
                (203, "楽園蒲田店", 1, 20, 20, "island-a", 101, 305, 2, 2, None),
                (305, "楽園蒲田店", 1, 30, 30, "island-a", 101, 305, 3, 1, None),
            ],
        )
        connection.execute(
            "INSERT INTO machine_master VALUES (?,?,?,?,?,?,?)",
            ("マイジャグラーV", 1, 0, 0, 0, "マイジャグラーV", "マイジャグラーV"),
        )


def _machine(number: int) -> dict:
    return {
        "mdc": "120010",
        "model_name": "LマイジャグラーV",
        "machine_number": str(number),
        "games": 3000,
        "bb_count": 10,
        "rb_count": 8,
        "highest_payout": 1000,
        "graph_eligible": True,
        "latest_diff": 500,
        "win": True,
        "graph_reused": False,
        "diff_confidence": "high",
        "graph_age_minutes": 0,
        "graph_update_time": "2026/08/14 12:25",
    }


def test_reference_enrichment_uses_layout_and_existing_master(tmp_path: Path) -> None:
    db_path = tmp_path / "reference.db"
    _create_reference_db(db_path)
    machines = [_machine(number) for number in (101, 203, 305)]

    context = load_reference_context(db_path, alias_path=None)
    summary = enrich_machines(machines, context)

    assert summary["layout_matches"] == 3
    assert summary["master_matches"] == 3
    assert all(machine["section"] == "island-a" for machine in machines)
    assert all(machine["machine_category"] == "jug" for machine in machines)
    assert all(machine["machine_name_normalized"] == "マイジャグラーV" for machine in machines)


def test_three_machine_run_uses_physical_order_not_number_sequence(tmp_path: Path) -> None:
    db_path = tmp_path / "reference.db"
    _create_reference_db(db_path)
    machines = [_machine(number) for number in (101, 203, 305)]
    context = load_reference_context(db_path, alias_path=None)
    enrich_machines(machines, context)

    lanes = build_physical_lanes(machines)
    assert [machine["lane_edge_rank"] for machine in lanes[0]["machines"]] == [
        1,
        2,
        1,
    ]
    runs = build_three_machine_runs(machines, lanes)

    assert len(runs) == 1
    assert runs[0]["machine_numbers"] == ["101", "203", "305"]
    assert runs[0]["adjacency_mode"] == "physical_layout"
    assert runs[0]["section"] == "island-a"
    blocks = build_positive_blocks(runs, machines)
    assert len(blocks) == 1
    assert blocks[0]["machine_numbers"] == ["101", "203", "305"]

    corners = build_lane_edge_summaries(machines)
    assert [row["lane_edge_label"] for row in corners] == ["列端1", "列端2"]
    assert corners[0]["machine_count"] == 2
    assert corners[1]["machine_count"] == 1


def test_three_machine_run_keeps_games_and_highest_without_diff(tmp_path: Path) -> None:
    db_path = tmp_path / "reference.db"
    _create_reference_db(db_path)
    machines = [_machine(number) for number in (101, 203, 305)]
    for index, machine in enumerate(machines, start=1):
        machine.update(
            graph_eligible=False,
            latest_diff=None,
            win=None,
            diff_confidence=None,
            graph_update_time="",
            games=index * 100,
            highest_payout=index * 200,
        )
    context = load_reference_context(db_path, alias_path=None)
    enrich_machines(machines, context)

    runs = build_three_machine_runs(machines, build_physical_lanes(machines))

    assert len(runs) == 1
    assert runs[0]["average_games"] == 200
    assert runs[0]["average_highest_payout"] == 400
    assert runs[0]["average_diff"] is None
    assert runs[0]["high_rotation_high_diff_score"] is None
