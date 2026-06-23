#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import yaml


COMPILER_VERSION = "1.2.0"
VERIFICATION_STATUSES = {"unverified", "confirmed", "refuted", "superseded"}
VERIFICATION_STATUS_ORDER = ("unverified", "confirmed", "refuted", "superseded")
EXCLUDED_STATUSES = {"refuted", "superseded"}


@dataclass
class InstinctRecord:
    record_id: str
    trigger: str
    confidence: float | None
    verification_status: str
    verified_by: list[dict[str, object]] | None
    domain: str
    source: str
    project_id: str
    project_name: str
    body_summary: str
    file_name: str
    file_path: str
    file_date: str | None
    file_mtime_ns: int


def parse_args() -> argparse.Namespace:
    script_path = Path(__file__).resolve()
    repo_root = script_path.parent.parent
    default_dir = repo_root / "document" / "instincts"
    default_output = default_dir / "ACTIVE_INSTINCTS.md"
    default_jsonl_output = default_dir / "ACTIVE_INSTINCTS.jsonl"
    default_state = default_dir / ".active_instincts_state.json"

    parser = argparse.ArgumentParser(
        description="Compile instincts YAML files into a fast-to-read active summary."
    )
    parser.add_argument("--instinct-dir", type=Path, default=default_dir)
    parser.add_argument("--output", type=Path, default=default_output)
    parser.add_argument("--jsonl-output", type=Path, default=default_jsonl_output)
    parser.add_argument("--state", type=Path, default=default_state)
    parser.add_argument("--min-confidence", type=float, default=0.80)
    parser.add_argument(
        "--high-confidence-pin",
        type=float,
        default=0.95,
        help="Always keep records above this confidence, even if older than recency window.",
    )
    parser.add_argument(
        "--recent-days",
        type=int,
        default=21,
        help="Keep records whose source file date is within this many days.",
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=120,
        help="Maximum records to render in ACTIVE_INSTINCTS.md.",
    )
    parser.add_argument(
        "--include-underscored-sources",
        action="store_true",
        help="Include source files that start with '_' (for example '_cli_export.yaml').",
    )
    parser.add_argument(
        "--include-refuted",
        action="store_true",
        help="Include refuted and superseded records in output (for audit).",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def read_text_with_fallback(path: Path) -> str:
    encodings = ("utf-8-sig", "utf-8", "cp932")
    for enc in encodings:
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def split_frontmatter_documents(text: str) -> Iterable[tuple[str, str]]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    docs: list[tuple[str, str]] = []
    key_pattern = re.compile(r"^[A-Za-z0-9_-]+\s*:")
    chunks = re.split(r"(?m)^---\s*$", normalized)
    for chunk in chunks:
        part = chunk.strip("\n")
        if not part:
            continue

        lines = part.split("\n")
        header_lines: list[str] = []
        i = 0
        seen_header_key = False
        while i < len(lines):
            raw_line = lines[i]
            stripped = raw_line.strip()

            if not stripped:
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if not seen_header_key or j >= len(lines):
                    header_lines.append(raw_line)
                    i += 1
                    continue

                next_line = lines[j]
                next_stripped = next_line.lstrip()
                if not next_line.startswith((" ", "\t")) and not key_pattern.match(next_stripped):
                    i = j
                    break

                header_lines.append(raw_line)
                i += 1
                continue

            if key_pattern.match(stripped):
                seen_header_key = True
                header_lines.append(raw_line)
                i += 1
                continue

            if raw_line.startswith((" ", "\t")) and seen_header_key:
                header_lines.append(raw_line)
                i += 1
                continue
            break

        if not header_lines:
            continue

        while i < len(lines) and not lines[i].strip():
            i += 1
        body = "\n".join(lines[i:]).strip()
        docs.append(("\n".join(header_lines), body))
    return docs


def parse_date_from_filename(file_name: str) -> str | None:
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", file_name)
    return m.group(1) if m else None


def summarize_body(body: str, limit: int = 200) -> str:
    lines = [line.strip() for line in body.splitlines()]
    cleaned: list[str] = []
    for line in lines:
        if not line:
            continue
        if line.startswith("```"):
            continue
        if line.startswith("#"):
            continue
        if line.startswith("- "):
            line = line[2:].strip()
        cleaned.append(line)

    text = re.sub(r"\s+", " ", " ".join(cleaned)).strip()
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def compact_text(value: str, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_verification_status(value: object) -> str:
    status = str(value or "unverified").strip().lower()
    return status if status in VERIFICATION_STATUSES else "unverified"


def normalize_verified_by(value: object) -> list[dict[str, object]] | None:
    if not isinstance(value, list):
        return None

    normalized: list[dict[str, object]] = []
    for item in value:
        if isinstance(item, dict):
            normalized.append(dict(item))
    return normalized or None


def collect_records(instinct_dir: Path, include_underscored_sources: bool) -> list[InstinctRecord]:
    records: list[InstinctRecord] = []
    for path in sorted(instinct_dir.glob("*.yaml")):
        if path.name.startswith("ACTIVE_INSTINCTS"):
            continue
        if path.name.startswith("_") and not include_underscored_sources:
            continue

        text = read_text_with_fallback(path)
        docs = list(split_frontmatter_documents(text))
        if not docs:
            continue

        file_date = parse_date_from_filename(path.name)
        mtime_ns = path.stat().st_mtime_ns

        for header_text, body in docs:
            try:
                header = yaml.safe_load(header_text) or {}
            except yaml.YAMLError:
                continue
            if not isinstance(header, dict):
                continue

            record_id = str(header.get("id", "")).strip()
            if not record_id:
                continue

            verification_status = normalize_verification_status(header.get("verification_status"))
            verified_by = normalize_verified_by(header.get("verified_by"))
            records.append(
                InstinctRecord(
                    record_id=record_id,
                    trigger=str(header.get("trigger", "")).strip(),
                    confidence=as_float(header.get("confidence")),
                    verification_status=verification_status,
                    verified_by=verified_by,
                    domain=str(header.get("domain", "")).strip(),
                    source=str(header.get("source", "")).strip(),
                    project_id=str(header.get("project_id", "")).strip(),
                    project_name=str(header.get("project_name", "")).strip(),
                    body_summary=summarize_body(body),
                    file_name=path.name,
                    file_path=str(path.as_posix()),
                    file_date=file_date,
                    file_mtime_ns=mtime_ns,
                )
            )
    return records


def dedupe_latest(records: list[InstinctRecord]) -> list[InstinctRecord]:
    latest: dict[str, InstinctRecord] = {}
    for record in records:
        existing = latest.get(record.record_id)
        if existing is None:
            latest[record.record_id] = record
            continue
        if record.file_mtime_ns >= existing.file_mtime_ns:
            latest[record.record_id] = record
    return list(latest.values())


def filter_records(
    records: list[InstinctRecord],
    min_confidence: float,
    high_confidence_pin: float,
    recent_days: int,
    include_refuted: bool,
) -> list[InstinctRecord]:
    today = datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=recent_days)

    filtered: list[InstinctRecord] = []
    for record in records:
        if not include_refuted and record.verification_status in EXCLUDED_STATUSES:
            continue

        conf = record.confidence if record.confidence is not None else -1.0
        if conf < min_confidence:
            continue

        keep_by_conf = conf >= high_confidence_pin
        keep_by_date = False
        if record.file_date:
            try:
                keep_by_date = datetime.strptime(record.file_date, "%Y-%m-%d").date() >= cutoff
            except ValueError:
                keep_by_date = True
        else:
            keep_by_date = True

        if keep_by_conf or keep_by_date:
            filtered.append(record)
    return filtered


def sort_records(records: list[InstinctRecord]) -> list[InstinctRecord]:
    def score(record: InstinctRecord) -> tuple[float, int, str]:
        conf = record.confidence if record.confidence is not None else -1.0
        return (conf, record.file_mtime_ns, record.record_id)

    return sorted(records, key=score, reverse=True)


def count_statuses(records: list[InstinctRecord]) -> dict[str, int]:
    counts = Counter(record.verification_status for record in records)
    return {status: counts.get(status, 0) for status in VERIFICATION_STATUS_ORDER}


def build_snapshot_hash(instinct_dir: Path) -> str:
    items: list[str] = []
    for path in sorted(instinct_dir.glob("*.yaml")):
        stat = path.stat()
        items.append(f"{path.name}|{stat.st_size}|{stat.st_mtime_ns}")
    raw = "\n".join(items).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def render_markdown(
    records: list[InstinctRecord],
    total_records_scanned: int,
    instincts_dir: Path,
    min_confidence: float,
    recent_days: int,
    status_breakdown: dict[str, int],
) -> str:
    now = datetime.now().astimezone()
    lines: list[str] = []
    lines.append("# ACTIVE_INSTINCTS")
    lines.append("")
    lines.append(f"- generated_at: {now.isoformat(timespec='seconds')}")
    lines.append(f"- compiler_version: {COMPILER_VERSION}")
    lines.append(f"- source_dir: `{instincts_dir.as_posix()}`")
    lines.append(f"- total_records_scanned: {total_records_scanned}")
    lines.append(f"- active_records: {len(records)}")
    breakdown = ", ".join(f"{status}={status_breakdown.get(status, 0)}" for status in VERIFICATION_STATUS_ORDER)
    lines.append(f"- status_breakdown: {breakdown}")
    lines.append(
        f"- filters: `confidence >= {min_confidence:.2f}` and `file_date within {recent_days} days` (unless pinned by high confidence)"
    )
    lines.append("")
    lines.append("## Usage")
    lines.append(
        "- Start of work: run `venv\\Scripts\\python.exe scripts/compile_instincts.py` (or `python scripts/compile_instincts.py`)."
    )
    lines.append("- Long sessions: rerun before major decisions or every 15-20 minutes.")
    lines.append("- Preferred source for Codex: `ACTIVE_INSTINCTS.jsonl` (machine-readable canonical).")
    lines.append("- This Markdown is a quick view. Open raw YAML only when detail is missing.")
    lines.append("- Default behavior skips files like `_cli_export.yaml`; add `--include-underscored-sources` when needed.")
    lines.append("")
    lines.append("## Active List")
    lines.append("")

    if not records:
        lines.append("No active instincts matched current filters.")
        return "\n".join(lines) + "\n"

    for idx, record in enumerate(records, start=1):
        conf = "n/a" if record.confidence is None else f"{record.confidence:.2f}"
        lines.append(f"### {idx}. `{record.record_id}`")
        lines.append(
            f"- confidence: `{conf}` | status: `{record.verification_status}` | date: `{record.file_date or 'n/a'}` | file: `{record.file_name}`"
        )
        if record.domain or record.source:
            lines.append(f"- domain/source: `{record.domain or 'n/a'}` / `{record.source or 'n/a'}`")
        if record.trigger:
            lines.append(f"- trigger: {compact_text(record.trigger, 140)}")
        if record.body_summary:
            lines.append(f"- summary: {compact_text(record.body_summary, 160)}")
        lines.append("")

    return "\n".join(lines)


def record_to_json(record: InstinctRecord, rank: int) -> dict:
    confidence = None if record.confidence is None else round(record.confidence, 6)
    search_text = " | ".join(
        [
            record.record_id,
            record.trigger,
            record.domain,
            record.source,
            record.file_name,
            record.body_summary,
        ]
    )
    return {
        "rank": rank,
        "id": record.record_id,
        "confidence": confidence,
        "verification_status": record.verification_status,
        "verified_by": record.verified_by,
        "trigger": record.trigger,
        "domain": record.domain,
        "source": record.source,
        "project_id": record.project_id,
        "project_name": record.project_name,
        "file_name": record.file_name,
        "file_path": record.file_path,
        "file_date": record.file_date,
        "summary": record.body_summary,
        "search_text": compact_text(search_text, limit=500),
    }


def render_jsonl(records: list[InstinctRecord]) -> str:
    lines: list[str] = []
    for idx, record in enumerate(records, start=1):
        payload = record_to_json(record, rank=idx)
        lines.append(json.dumps(payload, ensure_ascii=False))
    return "\n".join(lines) + ("\n" if lines else "")


def main() -> int:
    args = parse_args()
    instincts_dir = args.instinct_dir.resolve()
    output_path = args.output.resolve()
    jsonl_output_path = args.jsonl_output.resolve()
    state_path = args.state.resolve()

    if not instincts_dir.exists():
        print(f"[ERROR] instinct directory not found: {instincts_dir}")
        return 1

    snapshot_hash = build_snapshot_hash(instincts_dir)
    run_signature = {
        "instinct_dir": str(instincts_dir.as_posix()),
        "min_confidence": args.min_confidence,
        "high_confidence_pin": args.high_confidence_pin,
        "recent_days": args.recent_days,
        "max_records": args.max_records,
        "include_underscored_sources": args.include_underscored_sources,
        "include_refuted": args.include_refuted,
        "output_path": str(output_path.as_posix()),
        "jsonl_output_path": str(jsonl_output_path.as_posix()),
    }
    state = load_state(state_path)
    if (
        not args.force
        and output_path.exists()
        and jsonl_output_path.exists()
        and state.get("snapshot_hash") == snapshot_hash
        and state.get("compiler_version") == COMPILER_VERSION
        and state.get("run_signature") == run_signature
    ):
        print(
            f"[SKIP] no changes detected. outputs are up-to-date: {output_path} and {jsonl_output_path}"
        )
        return 0

    raw_records = collect_records(
        instincts_dir, include_underscored_sources=args.include_underscored_sources
    )
    deduped = dedupe_latest(raw_records)
    filtered = filter_records(
        deduped,
        min_confidence=args.min_confidence,
        high_confidence_pin=args.high_confidence_pin,
        recent_days=args.recent_days,
        include_refuted=args.include_refuted,
    )
    sorted_records = sort_records(filtered)[: args.max_records]
    status_breakdown = count_statuses(deduped)

    markdown = render_markdown(
        sorted_records,
        total_records_scanned=len(raw_records),
        instincts_dir=instincts_dir,
        min_confidence=args.min_confidence,
        recent_days=args.recent_days,
        status_breakdown=status_breakdown,
    )
    jsonl_text = render_jsonl(sorted_records)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    jsonl_output_path.parent.mkdir(parents=True, exist_ok=True)
    jsonl_output_path.write_text(jsonl_text, encoding="utf-8")

    save_state(
        state_path,
        {
            "snapshot_hash": snapshot_hash,
            "compiler_version": COMPILER_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "output_path": str(output_path.as_posix()),
            "jsonl_output_path": str(jsonl_output_path.as_posix()),
            "source_dir": str(instincts_dir.as_posix()),
            "run_signature": run_signature,
            "raw_records": len(raw_records),
            "active_records": len(sorted_records),
        },
    )

    print(f"[OK] compiled instincts -> {output_path}")
    print(f"[OK] compiled instincts(jsonl) -> {jsonl_output_path}")
    print(
        f"[INFO] scanned={len(raw_records)} active={len(sorted_records)} refuted={status_breakdown.get('refuted', 0)} superseded={status_breakdown.get('superseded', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
