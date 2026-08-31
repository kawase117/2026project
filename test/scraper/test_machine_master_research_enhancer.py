import csv
import json
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scraper"))


def test_extract_note_updates_parses_rtp_bb_rb_and_machine_type() -> None:
    from machine_master_research_enhancer import extract_note_updates

    note = (
        "機械割は設定1=97.6%・設定2=98.9%・設定5=112.1%・設定6=114.9%、"
        "BBは設定1=1/386.9・設定2=1/368.5・設定5=1/351.6・設定6=1/312.1、"
        "RBは設定1=1/532.8・設定2=1/468.1・設定5=1/372.4・設定6=1/336.1、"
        "スマスロ/ATタイプ"
    )

    updates = extract_note_updates(note)

    assert updates["rtp_setting1"] == "97.6"
    assert updates["rtp_setting2"] == "98.9"
    assert updates["rtp_setting5"] == "112.1"
    assert updates["rtp_setting6"] == "114.9"
    assert updates["bb_setting1"] == "1/386.9"
    assert updates["bb_setting2"] == "1/368.5"
    assert updates["bb_setting5"] == "1/351.6"
    assert updates["bb_setting6"] == "1/312.1"
    assert updates["rb_setting1"] == "1/532.8"
    assert updates["rb_setting2"] == "1/468.1"
    assert updates["rb_setting5"] == "1/372.4"
    assert updates["rb_setting6"] == "1/336.1"
    assert updates["machine_type"] == "スマスロ / AT"


def test_apply_row_updates_preserves_existing_values() -> None:
    from machine_master_research_enhancer import apply_row_updates

    row = {
        "machine_name": "TEST",
        "manufacturer": "MFR",
        "release_date": "",
        "machine_type": "",
        "rtp_setting1": "99.1",
        "rtp_setting2": "",
        "rtp_setting3": "",
        "rtp_setting4": "",
        "rtp_setting5": "",
        "rtp_setting6": "",
        "bb_setting1": "",
        "bb_setting2": "",
        "bb_setting3": "",
        "bb_setting4": "",
        "bb_setting5": "",
        "bb_setting6": "",
        "rb_setting1": "",
        "rb_setting2": "",
        "rb_setting3": "",
        "rb_setting4": "",
        "rb_setting5": "",
        "rb_setting6": "",
        "notes": "機械割は設定1=97.6%・設定2=98.9%、BBは設定1=1/386.9",
    }

    updated_row, changes = apply_row_updates(row)

    assert updated_row["rtp_setting1"] == "99.1"
    assert updated_row["rtp_setting2"] == "98.9"
    assert updated_row["bb_setting1"] == "1/386.9"
    assert changes["rtp_setting2"]["after"] == "98.9"
    assert "rtp_setting1" not in changes


def test_extract_note_updates_never_treats_fraction_as_rtp() -> None:
    from machine_master_research_enhancer import extract_note_updates

    updates = extract_note_updates("AT初当り:1/181.7")

    assert "rtp_setting1" not in updates
    assert "bb_setting1" not in updates
    assert "rb_setting1" not in updates


def test_enhance_csv_writes_output_and_diff(tmp_path: Path) -> None:
    from machine_master_research_enhancer import enhance_csv

    input_path = tmp_path / "machine_master.csv"
    output_path = tmp_path / "machine_master_output.csv"
    diff_path = tmp_path / "machine_master_research_diff.json"

    with input_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "machine_name",
                "manufacturer",
                "release_date",
                "machine_type",
                "rtp_setting1",
                "rtp_setting2",
                "rtp_setting3",
                "rtp_setting4",
                "rtp_setting5",
                "rtp_setting6",
                "bb_setting1",
                "bb_setting2",
                "bb_setting3",
                "bb_setting4",
                "bb_setting5",
                "bb_setting6",
                "rb_setting1",
                "rb_setting2",
                "rb_setting3",
                "rb_setting4",
                "rb_setting5",
                "rb_setting6",
                "notes",
            ]
        )
        writer.writerow(
            [
                "TEST",
                "MFR",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "機械割は設定1=97.6%・設定2=98.9%、BBは設定1=1/386.9、RBは設定1=1/532.8、スマスロ/ATタイプ",
            ]
        )

    summary = enhance_csv(input_path, output_path, diff_path)

    assert output_path.exists()
    assert diff_path.exists()
    assert summary["rows_changed"] == 1
    assert summary["fields_filled"]["rtp_setting1"] == 1

    with output_path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["rtp_setting1"] == "97.6"
    assert rows[0]["bb_setting1"] == "1/386.9"
    assert rows[0]["rb_setting1"] == "1/532.8"

    with diff_path.open("r", encoding="utf-8") as f:
        diff = json.load(f)
    assert diff[0]["machine_name"] == "TEST"
    assert "rtp_setting1" in diff[0]["changes"]


def test_default_paths_use_single_canonical_master() -> None:
    from machine_master_research_enhancer import build_parser

    args = build_parser().parse_args([])

    assert args.input.name == "machine_master.csv"
    assert args.output == args.input
