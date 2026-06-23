#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resolve duplicate machine-name groups via the shared 1geki URL mapper."""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from machine_master_research_url_mapper import (
    build_page_index,
    load_machine_master_alias_map,
    resolve_machine_url,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
MACHINE_MASTER_RESEARCH_DIR = REPO_ROOT / "document" / "machine_master_research"
SOURCE_MD = MACHINE_MASTER_RESEARCH_DIR / "duplicate_selected_url_groups_split.md"
DEFAULT_JSON = MACHINE_MASTER_RESEARCH_DIR / "duplicate_url_resolution.json"
DEFAULT_CSV = MACHINE_MASTER_RESEARCH_DIR / "duplicate_url_resolution.csv"
DEFAULT_MD = MACHINE_MASTER_RESEARCH_DIR / "duplicate_url_resolution.md"
DEFAULT_PAGE_INDEX = MACHINE_MASTER_RESEARCH_DIR / "1geki_slot_page_index.json"

SECTION_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$")
ROW_RE = re.compile(r"^\|\s*`(?P<selected_url>[^`]+)`\s*\|\s*(?P<machines>.+?)\s*(?:\|\s*(?P<note>[^|]+?)\s*)?\|$")
MACHINE_RE = re.compile(r"`([^`]+)`")


@dataclass(frozen=True)
class ParsedRow:
    section: str
    selected_url: str
    machine_names: list[str]
    note: str = ""


def _parse_machine_names(cell: str) -> list[str]:
    return [match.group(1).strip() for match in MACHINE_RE.finditer(cell) if match.group(1).strip()]


def parse_duplicate_groups_markdown(path: Path) -> list[ParsedRow]:
    text = path.read_text(encoding="utf-8")
    section = ""
    rows: list[ParsedRow] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        section_match = SECTION_RE.match(line)
        if section_match:
            section = section_match.group("title").strip()
            continue
        if not line.startswith("|"):
            continue
        if line.startswith("|---") or "selected_url" in line and "machine_names" in line:
            continue

        match = ROW_RE.match(line)
        if not match:
            continue

        machine_names = _parse_machine_names(match.group("machines"))
        if not machine_names:
            continue
        rows.append(
            ParsedRow(
                section=section,
                selected_url=match.group("selected_url").strip(),
                machine_names=machine_names,
                note=(match.group("note") or "").strip(),
            )
        )

    return rows


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _write_csv(path: Path, rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "section",
        "group_selected_url",
        "machine_name",
        "resolved_status",
        "resolved_url",
        "confidence",
        "query",
        "reason",
        "candidate_count",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _render_markdown(summary: dict[str, object], sections: list[dict[str, object]]) -> str:
    lines = [
        "# Duplicate URL Resolution",
        "",
        f"- rows_total: {summary['rows_total']}",
        f"- rows_selected: {summary['rows_selected']}",
        f"- rows_needing_review: {summary['rows_needing_review']}",
        f"- rows_not_found: {summary['rows_not_found']}",
        "",
    ]

    for section in sections:
        lines.append(f"## {section['section']}")
        lines.append("")
        lines.append("| group_selected_url | machine_name | resolved_status | resolved_url | confidence | reason |")
        lines.append("|---|---|---|---|---:|---|")
        for row in section["rows"]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"`{row['group_selected_url']}`",
                        f"`{row['machine_name']}`",
                        row["resolved_status"],
                        f"`{row['resolved_url']}`" if row["resolved_url"] else "",
                        f"{row['confidence']}",
                        row["reason"],
                    ]
                )
                + " |"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def resolve_duplicate_groups(
    *,
    source_path: Path,
    json_path: Path,
    csv_path: Path,
    md_path: Path,
    page_index: list[dict[str, str]] | None = None,
    page_index_path: Path | None = None,
    refresh_index: bool = False,
) -> dict[str, object]:
    parsed_rows = parse_duplicate_groups_markdown(source_path)
    if page_index is None:
        if page_index_path is None:
            page_index_path = DEFAULT_PAGE_INDEX
        page_index = build_page_index(index_path=page_index_path, refresh=refresh_index)

    alias_map = load_machine_master_alias_map()

    all_rows: list[dict[str, object]] = []
    sections: dict[str, list[dict[str, object]]] = {}
    for parsed in parsed_rows:
        section_rows = sections.setdefault(parsed.section, [])
        for machine_name in parsed.machine_names:
            resolved = resolve_machine_url(
                machine_name,
                page_index=page_index,
                machine_master_alias_map=alias_map,
            )
            row = {
                "section": parsed.section,
                "group_selected_url": parsed.selected_url,
                "machine_name": machine_name,
                "resolved_status": resolved["status"],
                "resolved_url": resolved["selected_url"],
                "confidence": resolved["confidence"],
                "query": resolved["query"],
                "reason": resolved["reason"],
                "candidate_count": len(resolved.get("candidates", [])),
                "candidates": resolved.get("candidates", []),
            }
            section_rows.append(row)
            all_rows.append(row)

    payload = {
        "source_path": str(source_path),
        "rows_total": len(all_rows),
        "rows_selected": sum(1 for row in all_rows if row["resolved_status"] == "selected"),
        "rows_needing_review": sum(1 for row in all_rows if row["resolved_status"] == "needs_review"),
        "rows_not_found": sum(1 for row in all_rows if row["resolved_status"] == "not_found"),
        "sections": [
            {
                "section": section_name,
                "rows": section_rows,
            }
            for section_name, section_rows in sections.items()
        ],
    }

    _write_json(json_path, payload)
    _write_csv(
        csv_path,
        (
            {
                "section": row["section"],
                "group_selected_url": row["group_selected_url"],
                "machine_name": row["machine_name"],
                "resolved_status": row["resolved_status"],
                "resolved_url": row["resolved_url"],
                "confidence": row["confidence"],
                "query": row["query"],
                "reason": row["reason"],
                "candidate_count": row["candidate_count"],
            }
            for row in all_rows
        ),
    )
    md_path.write_text(_render_markdown(payload, payload["sections"]), encoding="utf-8")
    payload["json_path"] = str(json_path)
    payload["csv_path"] = str(csv_path)
    payload["md_path"] = str(md_path)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve duplicate URL groups via the shared 1geki mapper")
    parser.add_argument("--source", type=Path, default=SOURCE_MD)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--md", type=Path, default=DEFAULT_MD)
    parser.add_argument("--page-index", type=Path, default=DEFAULT_PAGE_INDEX)
    parser.add_argument("--refresh-index", action="store_true")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    summary = resolve_duplicate_groups(
        source_path=args.source,
        json_path=args.json,
        csv_path=args.csv,
        md_path=args.md,
        page_index_path=args.page_index,
        refresh_index=args.refresh_index,
    )

    print(
        "[duplicate-url-resolver] "
        f"rows_total={summary['rows_total']} "
        f"selected={summary['rows_selected']} "
        f"needs_review={summary['rows_needing_review']} "
        f"not_found={summary['rows_not_found']}"
    )
    print(f"[duplicate-url-resolver] json={summary['json_path']}")
    print(f"[duplicate-url-resolver] csv={summary['csv_path']}")
    print(f"[duplicate-url-resolver] md={summary['md_path']}")


if __name__ == "__main__":
    main()
