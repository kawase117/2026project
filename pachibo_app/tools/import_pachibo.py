"""Export all recoverable data from a ぱち簿 .pcb backup.

Produces a ZIP of complete CSV tables and a JSON file for the Android app.
The proprietary format is undocumented; malformed fields are counted and
preserved as text instead of silently discarded.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


RECORD = re.compile(r"(?:(?<=,)|\A)(Integer|String|Boolean|Long),([A-Za-z0-9_]+),(\d+),")
ITEM_KEY = re.compile(r"item(\d{8}_\d+)_(.+)")
MASTER_KEY = re.compile(r"(tag|machine|hall)(\d+)_(.+)")
ITEM_ID = re.compile(r"(\d{8})_(\d+)")


def parse_pcb(path: Path) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, dict[str, str]]], dict]:
    decoded = bytes(byte ^ 0xFF for byte in path.read_bytes()).decode("utf-8", "replace")
    markers = list(RECORD.finditer(decoded))
    entities: dict[str, dict[str, dict[str, str]]] = {kind: defaultdict(dict) for kind in ("item", "tag", "machine", "hall")}
    other: dict[str, dict[str, str]] = {}
    bad_lengths: list[str] = []
    duplicate_keys = 0
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() - 1 if index + 1 < len(markers) else len(decoded)
        value = decoded[marker.end() : end]
        key = marker.group(2)
        # Java's String.length() counts UTF-16 code units, including two for emoji.
        if len(value.encode("utf-16-le")) // 2 != int(marker.group(3)):
            bad_lengths.append(key)
        if match := ITEM_KEY.fullmatch(key):
            kind, entity_id, field = "item", *match.groups()
            if field in entities[kind][entity_id]:
                duplicate_keys += 1
            entities[kind][entity_id][field] = value
        elif match := MASTER_KEY.fullmatch(key):
            kind, entity_id, field = match.groups()
            if field in entities[kind][entity_id]:
                duplicate_keys += 1
            entities[kind][entity_id][field] = value
        else:
            if key in other:
                duplicate_keys += 1
            other[key] = {"type": marker.group(1), "value": value}
    return other, {kind: dict(rows) for kind, rows in entities.items()}, {
        "raw_entries": len(markers),
        "bad_length_keys": bad_lengths,
        "duplicate_keys": duplicate_keys,
        "utf8_replacement_characters": decoded.count("\ufffd"),
    }


def integer(value: str | None) -> int:
    try:
        return int(value or "0")
    except ValueError:
        return 0


def normalized_date(item_id: str) -> str | None:
    match = ITEM_ID.fullmatch(item_id)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def create_export(path: Path) -> dict:
    other, entities, audit = parse_pcb(path)
    items, tags, machines, halls = (entities[kind] for kind in ("item", "tag", "machine", "hall"))
    records: list[dict] = []
    csv_items: list[dict] = []
    unresolved_halls = 0
    unresolved_machines = 0
    play_like_invalid_dates = 0
    for item_id, fields in sorted(items.items()):
        hall = halls.get(fields.get("hall_id", ""), {})
        machine = machines.get(fields.get("machine_id", ""), {})
        tag_count = max(0, min(integer(fields.get("tag_count")), 100))
        tag_ids = [fields[f"tag{n}"] for n in range(tag_count) if fields.get(f"tag{n}")]
        tag_names = [tags.get(tag_id, {}).get("name", "") for tag_id in tag_ids]
        if fields.get("hall_id") and not hall.get("name"):
            unresolved_halls += 1
        if fields.get("machine_id") and not machine.get("name"):
            unresolved_machines += 1
        enriched = {
            "item_id": item_id,
            "date_iso": normalized_date(item_id) or "",
            "hall_name": hall.get("name", ""),
            "machine_name": machine.get("name", ""),
            "tag_ids": "|".join(tag_ids),
            "tag_names": "|".join(tag_names),
            "investment_total_yen": integer(fields.get("invest")) + integer(fields.get("invest2")),
            "recovery_total_yen": integer(fields.get("recovery")) + integer(fields.get("recovery2")),
            **fields,
        }
        enriched["profit_yen"] = enriched["recovery_total_yen"] - enriched["investment_total_yen"]
        csv_items.append(enriched)
        # Type 1 matched the official play CSV in the observed backup. Entries
        # without type but with complete money fields are retained for review.
        playable = fields.get("type") == "1" or (
            "type" not in fields and "invest" in fields and "recovery" in fields
        )
        if playable and not enriched["date_iso"]:
            play_like_invalid_dates += 1
        if not playable or not enriched["date_iso"]:
            continue
        records.append({
            "id": "pcb-" + item_id,
            "date": enriched["date_iso"],
            "hall": enriched["hall_name"],
            "kind": "未分類",  # The PCB has no verified pachinko/slot category field.
            "machine": enriched["machine_name"],
            "machine_number": fields.get("number", ""),
            "investment_yen": enriched["investment_total_yen"],
            "recovery_yen": enriched["recovery_total_yen"],
            "profit_yen": enriched["profit_yen"],
            "duration": fields.get("time", ""),
            "memo": fields.get("memo", ""),
            "tag_ids": tag_ids,
            "match_status": "pcb_direct" if fields.get("type") == "1" else "pcb_type_missing",
            "source_item_id": item_id,
            "legacy_tag_bits": fields.get("tag", ""),
        })
    audit.update({
        "items": len(items), "play_records": len(records), "tag_definitions": len(tags),
        "review_required_records": sum(row["match_status"] == "pcb_type_missing" for row in records),
        "play_like_invalid_dates": play_like_invalid_dates,
        "machine_definitions": len(machines), "hall_definitions": len(halls),
        "unresolved_hall_names": unresolved_halls,
        "unresolved_machine_names": unresolved_machines,
        "item_types": dict(Counter(fields.get("type", "missing") for fields in items.values())),
    })
    portable = {
        "format": "pachibo-ledger-v1",
        "source": {"pcb": path.name},
        "tags": [{"source_id": key, **value} for key, value in sorted(tags.items()) if value.get("name")],
        "records": records,
        "audit": audit,
    }
    return {"portable": portable, "items": csv_items, "tags": tags, "machines": machines, "halls": halls, "other": other, "audit": audit}


def csv_text(rows: list[dict]) -> str:
    keys = sorted({key for row in rows for key in row})
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=keys, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return "\ufeff" + output.getvalue()


def write_zip(result: dict, output: Path) -> None:
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("items.csv", csv_text(result["items"]))
        for kind in ("tags", "machines", "halls"):
            rows = [{"source_id": key, **value} for key, value in sorted(result[kind].items())]
            archive.writestr(f"{kind}.csv", csv_text(rows))
        rows = [{"key": key, **value} for key, value in sorted(result["other"].items())]
        archive.writestr("other_settings.csv", csv_text(rows))
        archive.writestr("audit.json", json.dumps(result["audit"], ensure_ascii=False, indent=2))
        archive.writestr("android_import.json", json.dumps(result["portable"], ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pcb", type=Path)
    parser.add_argument("--output", type=Path, help="ZIP path containing full CSV tables and Android import JSON")
    args = parser.parse_args()
    result = create_export(args.pcb)
    print(json.dumps(result["audit"], ensure_ascii=False, indent=2))
    if args.output:
        write_zip(result, args.output)


if __name__ == "__main__":
    main()
