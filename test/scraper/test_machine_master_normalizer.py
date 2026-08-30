import csv
from pathlib import Path

from scraper.machine_master_normalizer import canonical_name_for, normalize_master


FIELDNAMES = [
    "machine_name",
    "notes",
    "source_url",
    "source_status",
    "source_confidence",
    "source_query",
    "source_candidate_count",
    "source_reason",
]


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def test_normalizer_repairs_urls_and_records_aliases_idempotently(tmp_path: Path) -> None:
    path = tmp_path / "machine_master.csv"
    _write_rows(
        path,
        [
            {
                "machine_name": "/いざ番長/SB8",
                "notes": "ATタイプ",
                "source_url": "https://1geki.jp/slot/l_bancho_iza/",
                "source_status": "selected",
            },
            {
                "machine_name": "頭文字D",
                "notes": "出典:https://1geki.jp/slot/ini_d2nd/",
                "source_url": "https://1geki.jp/slot/ini_d2nd/",
                "source_status": "selected",
            },
            {
                "machine_name": "化物語",
                "notes": "5号機、出典:https://1geki.jp/slot/s_monogatari2/",
                "source_url": "https://1geki.jp/slot/s_monogatari2/",
                "source_status": "selected",
            },
        ],
    )

    summary = normalize_master(path, write=True)
    assert summary["rows_changed"] == 3

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = {row["machine_name"]: row for row in csv.DictReader(handle)}

    assert canonical_name_for("/いざ番長/SB8", rows["/いざ番長/SB8"]["notes"]) == "いざ！番長"
    assert rows["/いざ番長/SB8"]["canonical_machine_name"] == "いざ！番長"
    assert rows["頭文字D"]["source_url"] == "https://1geki.jp/slot/s_intiald/"
    assert "ini_d2nd" not in rows["頭文字D"]["notes"]
    assert "出典:https://" not in rows["頭文字D"]["notes"]
    assert rows["化物語"]["source_url"] == "https://1geki.jp/slot/l_bakemonogatari/"
    assert rows["化物語"]["source_status"] == "selected"
    assert rows["化物語"]["release_date"] == "2025-12-08"
    assert rows["化物語"]["at_initial_setting1"] == "1/265.1"
    assert normalize_master(path, write=True)["rows_changed"] == 0


def test_normalizer_migrates_note_url_into_source_columns(tmp_path: Path) -> None:
    path = tmp_path / "machine_master.csv"
    _write_rows(
        path,
        [
            {
                "machine_name": "new machine",
                "notes": "ATタイプ、出典:https://1geki.jp/slot/new_machine/",
                "source_url": "",
                "source_status": "",
            }
        ],
    )

    normalize_master(path, write=True)

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["source_url"] == "https://1geki.jp/slot/new_machine/"
    assert row["source_status"] == "selected"
    assert row["source_reason"] == "migrated_from_notes"
    assert row["notes"] == "ATタイプ"


def test_normalizer_synchronizes_specs_across_alias_group(tmp_path: Path) -> None:
    path = tmp_path / "machine_master.csv"
    _write_rows(
        path,
        [
            {"machine_name": "吉宗", "notes": "", "source_url": "", "source_status": ""},
            {"machine_name": "吉宗(スマスロ)", "notes": "", "source_url": "", "source_status": ""},
        ],
    )

    normalize_master(path, write=True)

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["canonical_machine_name"] for row in rows} == {"吉宗"}
    assert {row["rtp_setting6"] for row in rows} == {"112.0"}
    assert {row["combined_initial_setting1"] for row in rows} == {"1/378.9"}
