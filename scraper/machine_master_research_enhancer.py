#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Enhance machine_list_for_research.csv from existing notes.

Phase 0 of the revised workflow:
- extract structured values from notes
- keep existing values untouched
- write a new CSV plus a diff JSON for review
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
MACHINE_MASTER_RESEARCH_DIR = REPO_ROOT / "document" / "machine_master_research"
CSV_COLUMNS = [
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

RTP_LABEL_PATTERN = r"(?:機械割|出玉率|RTP|完全攻略時出玉率)"
BB_LABEL_PATTERN = r"(?:BB|BIG|BB初当たり|BB確率|BB合算)"
RB_LABEL_PATTERN = r"(?:RB|REG|RB初当たり|RB確率|RB合算|LIVE BONUS)"
COMBINED_BB_RB_PATTERN = re.compile(
    rf"(?:BB[:/／]RB|RB[:/／]BB|BB/RB|BB:RB確率\(ボーナス合算\)|BB/RB合算確率)[^。！？\n]*?"
    rf"設定(?P<setting>[1-6])\s*(?:=|:|：|は)\s*(?P<bb>1/\d+(?:\.\d+)?)\s*[:：]\s*(?P<rb>1/\d+(?:\.\d+)?)"
)
SETTING_ASSIGNMENT_PATTERN = re.compile(
    r"設定(?P<setting>[1-6])\s*(?:=|:|：|は)\s*(?P<value>1/\d+(?:\.\d+)?|\d+(?:\.\d+)?%?)"
)
ANY_LABEL_PATTERN = re.compile(
    rf"(?:{RTP_LABEL_PATTERN}|{BB_LABEL_PATTERN}|{RB_LABEL_PATTERN})",
    re.IGNORECASE,
)


def _normalize_text(text: str) -> str:
    return (
        text.replace("％", "%")
        .replace("：", ":")
        .replace("／", "/")
        .replace("〜", "~")
        .replace("～", "~")
        .replace("・", " ")
    )


def _remove_spans(text: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return text
    chars = list(text)
    for start, end in spans:
        for index in range(start, end):
            chars[index] = " "
    return "".join(chars)


def _extract_labelled_setting_values(text: str, label_pattern: str) -> dict[str, str]:
    label_regex = re.compile(label_pattern, re.IGNORECASE)
    extracted: dict[str, str] = {}
    for match in label_regex.finditer(text):
        segment_start = match.start()
        next_label = ANY_LABEL_PATTERN.search(text, match.end())
        segment_end = next_label.start() if next_label else len(text)
        segment = text[segment_start:segment_end]
        for value_match in SETTING_ASSIGNMENT_PATTERN.finditer(segment):
            extracted[value_match.group("setting")] = value_match.group("value")
    return extracted


def _extract_machine_type(note: str) -> str | None:
    keywords = [
        "スマスロ",
        "6号機",
        "5号機",
        "AT",
        "ART",
        "BT",
        "ノーマル",
        "ボーナストリガー",
    ]
    found: list[str] = []
    for keyword in keywords:
        if keyword in note and keyword not in found:
            found.append(keyword)
    if not found:
        return None
    return " / ".join(found)


def extract_note_updates(note: str) -> dict[str, str]:
    """Extract candidate values from notes.

    The function returns only normalized values and leaves precedence decisions
    to the caller. Existing data should still win over newly extracted values.
    """

    if not note:
        return {}

    normalized = _normalize_text(note)
    updates: dict[str, str] = {}
    combined_spans: list[tuple[int, int]] = []

    for match in COMBINED_BB_RB_PATTERN.finditer(normalized):
        setting = match.group("setting")
        updates[f"bb_setting{setting}"] = match.group("bb")
        updates[f"rb_setting{setting}"] = match.group("rb")
        combined_spans.append(match.span())

    cleaned = _remove_spans(normalized, combined_spans)

    for setting, value in _extract_labelled_setting_values(cleaned, RTP_LABEL_PATTERN).items():
        updates[f"rtp_setting{setting}"] = value.replace("%", "")

    for setting, value in _extract_labelled_setting_values(cleaned, BB_LABEL_PATTERN).items():
        updates[f"bb_setting{setting}"] = value

    for setting, value in _extract_labelled_setting_values(cleaned, RB_LABEL_PATTERN).items():
        updates[f"rb_setting{setting}"] = value

    machine_type = _extract_machine_type(normalized)
    if machine_type:
        updates["machine_type"] = machine_type

    return updates


def apply_row_updates(row: dict[str, str]) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Apply note-derived updates to one CSV row.

    Returns the updated row plus a diff map keyed by changed column name.
    """

    updated = dict(row)
    note_updates = extract_note_updates(row.get("notes", ""))
    changes: dict[str, dict[str, str]] = {}

    for column, new_value in note_updates.items():
        current_value = updated.get(column, "")
        if current_value.strip():
            continue
        if not new_value.strip():
            continue
        updated[column] = new_value
        changes[column] = {
            "before": current_value,
            "after": new_value,
            "source": "notes",
        }

    return updated, changes


def _read_rows(input_path: Path) -> list[dict[str, str]]:
    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv_atomic(output_path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8-sig",
        newline="",
        delete=False,
        dir=str(output_path.parent),
        prefix=output_path.stem + "_",
        suffix=".tmp",
    ) as handle:
        temp_path = Path(handle.name)
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temp_path.replace(output_path)


def _write_json_atomic(output_path: Path, payload: Any) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        delete=False,
        dir=str(output_path.parent),
        prefix=output_path.stem + "_",
        suffix=".tmp",
    ) as handle:
        temp_path = Path(handle.name)
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temp_path.replace(output_path)


def enhance_csv(input_path: Path, output_path: Path, diff_path: Path) -> dict[str, Any]:
    rows = _read_rows(input_path)
    fieldnames = list(rows[0].keys()) if rows else CSV_COLUMNS

    updated_rows: list[dict[str, str]] = []
    diff_entries: list[dict[str, Any]] = []
    field_counter: Counter[str] = Counter()

    for row in rows:
        updated_row, changes = apply_row_updates(row)
        updated_rows.append(updated_row)
        if changes:
            diff_entries.append(
                {
                    "machine_name": row.get("machine_name", ""),
                    "changes": changes,
                }
            )
            field_counter.update(changes.keys())

    _write_csv_atomic(output_path, fieldnames, updated_rows)
    _write_json_atomic(diff_path, diff_entries)

    return {
        "rows_total": len(rows),
        "rows_changed": len(diff_entries),
        "fields_filled": dict(field_counter),
        "output_path": str(output_path),
        "diff_path": str(diff_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Enhance machine_list_for_research.csv from notes")
    parser.add_argument(
        "--input",
        type=Path,
        default=MACHINE_MASTER_RESEARCH_DIR / "machine_list_for_research.csv",
        help="Input CSV path",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=MACHINE_MASTER_RESEARCH_DIR / "machine_master_research_enhanced.csv",
        help="Output CSV path",
    )
    parser.add_argument(
        "--diff",
        type=Path,
        default=MACHINE_MASTER_RESEARCH_DIR / "machine_master_research_diff.json",
        help="Diff JSON path",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = enhance_csv(args.input, args.output, args.diff)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
