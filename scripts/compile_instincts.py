#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import yaml


COMPILER_VERSION = "1.3.0"
VERIFICATION_STATUSES = {"unverified", "confirmed", "refuted", "superseded"}
VERIFICATION_STATUS_ORDER = ("unverified", "confirmed", "refuted", "superseded")
EXCLUDED_STATUSES = {"refuted", "superseded"}
# INSTINCT_CONFIDENCE_THRESHOLD in the plugin's session-start.js.
INJECTION_MIN_CONFIDENCE = 0.7


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
    action: str = ""
    supersedes: list[str] = field(default_factory=list)
    invalidates: list[str] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    script_path = Path(__file__).resolve()
    repo_root = script_path.parent.parent
    default_dir = repo_root / "document" / "instincts"
    default_output = default_dir / "ACTIVE_INSTINCTS.md"
    default_jsonl_output = default_dir / "ACTIVE_INSTINCTS.jsonl"
    default_state = default_dir / ".active_instincts_state.json"

    parser = argparse.ArgumentParser(description="Compile instincts YAML files into a fast-to-read active summary.")
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
        "--recent-slots",
        type=int,
        default=60,
        help=(
            "Slots inside --max-records reserved for records within --recent-days. "
            "Without a reserve, high-confidence older records crowd recent work out entirely."
        ),
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
    parser.add_argument(
        "--sync-homunculus",
        action="store_true",
        help="Rewrite the session-start injection channel from the top-ranked records.",
    )
    parser.add_argument(
        "--homunculus-dir",
        type=Path,
        default=Path.home() / ".claude" / "homunculus" / "projects" / "257beeaeb232" / "instincts" / "inherited",
        help="Directory session-start.js reads project-scoped instincts from.",
    )
    parser.add_argument(
        "--homunculus-slots",
        type=int,
        default=6,
        help="Number of records to expose. Matches MAX_INJECTED_INSTINCTS in session-start.js.",
    )
    parser.add_argument(
        "--homunculus-project-id",
        default="257beeaeb232",
        help="project_id written into exported files (the homunculus id, not the repo name).",
    )
    parser.add_argument(
        "--injection-pins",
        type=Path,
        default=default_dir / "INJECTION_PINS.txt",
        help="Optional file listing record ids to force into injection slots, one per line.",
    )
    parser.add_argument(
        "--no-archive",
        action="store_true",
        help="Delete displaced injection files instead of moving them to a sibling archive.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report only; write nothing.")
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


def extract_action(body: str, trigger: str = "", limit: int = 160) -> str:
    """Pull the one-line directive that session-start.js will surface.

    The plugin's extractInstinctAction() takes the first non-empty line of the
    `## Action` section, falling back to the first line of the whole body. We
    resolve the same thing here so the exported file leads with a real
    directive instead of whatever text happens to come first.
    """
    # The corpus is overwhelmingly Japanese-headed (アクション ~1436, 背景 ~1446);
    # the English template headings appear in only a handful of records. Try the
    # directive sections first, then the finding, then the background.
    for heading in ("アクション", "Action", "発見", "Core claim", "背景", "Background"):
        m = re.search(
            rf"(?mi)^#+[ \t]*{heading}[ \t]*$\n+([\s\S]+?)(?=\n#+[ \t]|\Z)",
            body or "",
        )
        if not m:
            continue

        # Bodies are hard-wrapped Japanese prose, so the first *physical* line is
        # usually a fragment. Gather the first bullet/paragraph instead and fold
        # it into one line: session-start.js only ever surfaces a single line.
        chunk: list[str] = []
        for line in m.group(1).splitlines():
            text = line.strip()
            if text.startswith("```"):
                continue
            if not text:
                if chunk:
                    break
                continue
            if text.startswith(("- ", "* ")):
                if chunk:
                    break
                text = text[2:].strip()
            chunk.append(text)

        if chunk:
            return compact_text(" ".join(chunk), limit)

    return compact_text(trigger, limit)


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
    except TypeError, ValueError:
        return None


def normalize_verification_status(value: object) -> str:
    status = str(value or "unverified").strip().lower()
    return status if status in VERIFICATION_STATUSES else "unverified"


def normalize_relation_ids(value: object) -> list[str]:
    """Accept `supersedes: [id, ...]` or `supersedes: [{id: x, reason: y}, ...]`."""
    if not value:
        return []
    items = value if isinstance(value, list) else [value]
    ids: list[str] = []
    for item in items:
        if isinstance(item, dict):
            target = str(item.get("id", "")).strip()
        else:
            target = str(item).strip()
        if target and target not in ids:
            ids.append(target)
    return ids


def apply_relations(records: list[InstinctRecord]) -> dict[str, int]:
    """Close out older records that a newer one declares it replaces.

    Without this, a correction can only be written as yet another record, and
    the claim it corrects stays live forever — which is how the corpus reached
    1476 records with zero refuted and zero superseded. Declaring the target on
    the *new* record means the author does the bookkeeping once, at the moment
    they already know what they are replacing.
    """
    by_id = {record.record_id: record for record in records}
    applied = Counter()

    for record in records:
        for target_id, status in (
            *((t, "superseded") for t in record.supersedes),
            *((t, "refuted") for t in record.invalidates),
        ):
            target = by_id.get(target_id)
            if target is None or target is record:
                continue
            # Never downgrade a record that was explicitly verified by hand.
            if target.verification_status != "unverified":
                continue
            target.verification_status = status
            target.verified_by = [
                {
                    "session": record.file_date or "unknown",
                    "method": f"declared by {record.record_id}",
                    "result": status,
                }
            ]
            applied[status] += 1

    return dict(applied)


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
                    supersedes=normalize_relation_ids(header.get("supersedes")),
                    invalidates=normalize_relation_ids(header.get("invalidates")),
                    domain=str(header.get("domain", "")).strip(),
                    source=str(header.get("source", "")).strip(),
                    project_id=str(header.get("project_id", "")).strip(),
                    project_name=str(header.get("project_name", "")).strip(),
                    body_summary=summarize_body(body),
                    action=extract_action(body, str(header.get("trigger", "")).strip()),
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


def sort_key(record: InstinctRecord) -> tuple[float, int, str]:
    conf = record.confidence if record.confidence is not None else -1.0
    return (conf, record.file_mtime_ns, record.record_id)


def sort_records(records: list[InstinctRecord]) -> list[InstinctRecord]:
    return sorted(records, key=sort_key, reverse=True)


def load_injection_pins(path: Path) -> list[str]:
    """Read record ids that must occupy injection slots, in priority order."""
    if not path.exists():
        return []
    pins: list[str] = []
    for line in read_text_with_fallback(path).splitlines():
        text = line.split("#", 1)[0].strip()
        if text and text not in pins:
            pins.append(text)
    return pins


def select_injection_records(
    records: list[InstinctRecord],
    slots: int,
    pins: list[str],
) -> list[InstinctRecord]:
    """Pick the records that get written to the session-start injection channel.

    Ranking is deliberately NOT confidence-first. Self-assigned confidence
    clusters near 1.0 on positive findings and sits lower on the refutations
    that correct them, so a confidence sort systematically keeps the optimistic
    claim and drops its correction. Recency decides instead; confidence only
    breaks ties. Explicit pins always win.
    """
    usable = [
        record
        for record in records
        if record.verification_status not in EXCLUDED_STATUSES
        and record.action
        # Below this the plugin drops the file on read, so writing it is a no-op.
        and (record.confidence if record.confidence is not None else 0.0) >= INJECTION_MIN_CONFIDENCE
    ]
    by_id = {record.record_id: record for record in usable}

    selected: list[InstinctRecord] = []
    for pin in pins:
        record = by_id.get(pin)
        if record is not None and record not in selected:
            selected.append(record)

    def rank(record: InstinctRecord) -> tuple[str, float, int]:
        return (
            record.file_date or "0000-00-00",
            record.confidence if record.confidence is not None else -1.0,
            record.file_mtime_ns,
        )

    for record in sorted(usable, key=rank, reverse=True):
        if len(selected) >= slots:
            break
        if record not in selected:
            selected.append(record)

    return selected[:slots]


def render_injection_file(record: InstinctRecord, project_id: str, project_name: str) -> str:
    """Emit ONE record per file.

    session-start.js parses with a flat `---` toggle, so several records
    concatenated in one file collapse into a single entry whose body is the
    raw text of the ones after it. Writing one record per file is what keeps
    the id, the confidence and the action line describing the same instinct.
    """
    confidence = record.confidence if record.confidence is not None else 0.7
    header = "\n".join(
        [
            f"id: {record.record_id}",
            f"trigger: {json.dumps(record.trigger, ensure_ascii=False)}",
            f"confidence: {confidence}",
            f"domain: {record.domain or 'general'}",
            "source: inherited",
            "scope: project",
            f"imported_from: {json.dumps('document/instincts/' + record.file_name, ensure_ascii=False)}",
            f"project_id: {project_id}",
            f"project_name: {project_name}",
            f"verification_status: {record.verification_status}",
            f"source_date: {record.file_date or 'unknown'}",
        ]
    )
    return (
        "# Generated by scripts/compile_instincts.py --sync-homunculus\n"
        "# Do not edit by hand: this directory is rewritten on every sync.\n"
        f"# Source: document/instincts/{record.file_name}\n"
        "---\n"
        f"{header}\n"
        "---\n\n"
        f"## Action\n{record.action}\n\n"
        f"## Trigger\n{record.trigger}\n\n"
        f"## Summary\n{record.body_summary}\n"
    )


def sync_homunculus(
    records: list[InstinctRecord],
    target_dir: Path,
    project_id: str,
    project_name: str,
    archive_dir: Path | None,
) -> tuple[int, int]:
    """Rewrite the injection channel so it holds exactly `records`.

    Returns (written, archived).
    """
    archived = 0
    if target_dir.exists():
        stale = [p for p in sorted(target_dir.iterdir()) if p.is_file()]
        if stale and archive_dir is not None:
            archive_dir.mkdir(parents=True, exist_ok=True)
            for path in stale:
                path.replace(archive_dir / path.name)
                archived += 1
        else:
            for path in stale:
                path.unlink()
                archived += 1

    target_dir.mkdir(parents=True, exist_ok=True)
    for rank, record in enumerate(records, start=1):
        name = f"{rank:02d}-{record.record_id}.yaml"
        (target_dir / name).write_text(render_injection_file(record, project_id, project_name), encoding="utf-8")
    return len(records), archived


def allocate_records(
    records: list[InstinctRecord],
    max_records: int,
    recent_days: int,
    recent_slots: int,
) -> list[InstinctRecord]:
    """Split the ACTIVE list into a recency quota and a durable-claim remainder.

    Ranking purely by confidence saturates the list: there are far more records
    above the pin threshold than there are slots, so the effective cutline
    climbs (0.97 at 1473 records) and the recency window stops mattering. Worse,
    self-assigned confidence is not independent of what a record says — positive
    findings get high values, the refutations that correct them get lower ones,
    so a confidence sort keeps the claim and drops its correction.

    Reserving slots for recent records fixes both: recent work is guaranteed
    representation regardless of how confident older entries are.
    """
    today = datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=recent_days)

    def is_recent(record: InstinctRecord) -> bool:
        if not record.file_date:
            return False
        try:
            return datetime.strptime(record.file_date, "%Y-%m-%d").date() >= cutoff
        except ValueError:
            return False

    def by_date(record: InstinctRecord) -> tuple[str, float, int]:
        return (
            record.file_date or "0000-00-00",
            record.confidence if record.confidence is not None else -1.0,
            record.file_mtime_ns,
        )

    recent = sorted((r for r in records if is_recent(r)), key=by_date, reverse=True)
    older = sorted((r for r in records if not is_recent(r)), key=lambda r: sort_key(r), reverse=True)

    quota = max(0, min(recent_slots, max_records))
    selected = recent[:quota]
    # Unused recency slots fall through to older records, and vice versa, so a
    # quiet week never shrinks the list.
    selected += older[: max_records - len(selected)]
    if len(selected) < max_records:
        chosen = {id(r) for r in selected}
        selected += [r for r in recent[quota:] if id(r) not in chosen][: max_records - len(selected)]

    return sorted(selected, key=by_date, reverse=True)


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
    except json.JSONDecodeError, OSError:
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
    lines.append(
        "- Default behavior skips files like `_cli_export.yaml`; add `--include-underscored-sources` when needed."
    )
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
        "recent_slots": args.recent_slots,
        "include_underscored_sources": args.include_underscored_sources,
        "include_refuted": args.include_refuted,
        "output_path": str(output_path.as_posix()),
        "jsonl_output_path": str(jsonl_output_path.as_posix()),
        "sync_homunculus": args.sync_homunculus,
        "homunculus_slots": args.homunculus_slots,
    }
    state = load_state(state_path)
    if (
        not args.force
        and not args.dry_run
        and output_path.exists()
        and jsonl_output_path.exists()
        and state.get("snapshot_hash") == snapshot_hash
        and state.get("compiler_version") == COMPILER_VERSION
        and state.get("run_signature") == run_signature
    ):
        print(f"[SKIP] no changes detected. outputs are up-to-date: {output_path} and {jsonl_output_path}")
        return 0

    raw_records = collect_records(instincts_dir, include_underscored_sources=args.include_underscored_sources)
    deduped = dedupe_latest(raw_records)
    relations = apply_relations(deduped)
    if relations:
        detail = ", ".join(f"{k}={v}" for k, v in sorted(relations.items()))
        print(f"[INFO] applied declared relations: {detail}")
    filtered = filter_records(
        deduped,
        min_confidence=args.min_confidence,
        high_confidence_pin=args.high_confidence_pin,
        recent_days=args.recent_days,
        include_refuted=args.include_refuted,
    )
    sorted_records = allocate_records(
        filtered,
        max_records=args.max_records,
        recent_days=args.recent_days,
        recent_slots=args.recent_slots,
    )
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

    injection: list[InstinctRecord] = []
    if args.sync_homunculus:
        pins = load_injection_pins(args.injection_pins.resolve())
        injection = select_injection_records(deduped, args.homunculus_slots, pins)
        print(f"[INFO] injection channel ({len(injection)}/{args.homunculus_slots} slots):")
        for rank, record in enumerate(injection, start=1):
            pinned = " [pinned]" if record.record_id in pins else ""
            print(f"  {rank}. {record.record_id} ({record.file_date}, conf={record.confidence}){pinned}")
            print(f"     -> {record.action}")

    if args.dry_run:
        print("[DRY-RUN] no files written")
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    jsonl_output_path.parent.mkdir(parents=True, exist_ok=True)
    jsonl_output_path.write_text(jsonl_text, encoding="utf-8")

    if args.sync_homunculus:
        target_dir = args.homunculus_dir.resolve()
        archive_dir = None
        if not args.no_archive:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
            archive_dir = target_dir.parent / f"{target_dir.name}_archive_{stamp}"
        written, archived = sync_homunculus(
            injection,
            target_dir=target_dir,
            project_id=args.homunculus_project_id,
            project_name="2026project",
            archive_dir=archive_dir,
        )
        where = f" -> {archive_dir}" if archive_dir else " (deleted)"
        print(f"[OK] synced injection channel: wrote {written}, displaced {archived}{where}")

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
