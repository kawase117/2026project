from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import compile_instincts as ci  # noqa: E402


# filter_records() compares file dates against datetime.now(), so fixtures must
# be dated relative to the run. A hardcoded date silently rots the suite once
# wall-clock passes the recency window.
RECENT_DATE = datetime.now(timezone.utc).date().isoformat()


def write_instinct(path: Path, *, header: str, body: str = "body text") -> None:
    path.write_text(f"---\n{header}\n---\n{body}\n", encoding="utf-8")


def build_test_records(tmp_path: Path) -> list[ci.InstinctRecord]:
    write_instinct(
        tmp_path / f"{RECENT_DATE}-confirmed.yaml",
        header=(
            'id: confirmed-instinct\n'
            'trigger: "confirmed trigger"\n'
            "confidence: 0.97\n"
            "verification_status: confirmed\n"
            "verified_by:\n"
            '  - session: "2026-06-23"\n'
            '    method: "walk-forward backtest"\n'
            '    result: "confirmed"\n'
            '    evidence: "lift 1.43x on holdout, p<0.01"\n'
            "domain: test\n"
            "source: session-observation\n"
            "project_id: 2026project\n"
            "project_name: pachinko-analyzer"
        ),
    )
    write_instinct(
        tmp_path / f"{RECENT_DATE}-unverified.yaml",
        header=(
            'id: unverified-instinct\n'
            'trigger: "unverified trigger"\n'
            "confidence: 0.93\n"
            "domain: test\n"
            "source: session-observation\n"
            "project_id: 2026project\n"
            "project_name: pachinko-analyzer"
        ),
    )
    write_instinct(
        tmp_path / f"{RECENT_DATE}-refuted.yaml",
        header=(
            'id: refuted-instinct\n'
            'trigger: "refuted trigger"\n'
            "confidence: 0.96\n"
            "verification_status: refuted\n"
            "domain: test\n"
            "source: session-observation\n"
            "project_id: 2026project\n"
            "project_name: pachinko-analyzer"
        ),
    )
    write_instinct(
        tmp_path / f"{RECENT_DATE}-superseded.yaml",
        header=(
            'id: superseded-instinct\n'
            'trigger: "superseded trigger"\n'
            "confidence: 0.95\n"
            "verification_status: superseded\n"
            "domain: test\n"
            "source: session-observation\n"
            "project_id: 2026project\n"
            "project_name: pachinko-analyzer"
        ),
    )

    records = ci.collect_records(tmp_path, include_underscored_sources=False)
    return ci.dedupe_latest(records)


def test_verification_status_missing_defaults_to_unverified(tmp_path: Path) -> None:
    records = build_test_records(tmp_path)
    unverified = next(record for record in records if record.record_id == "unverified-instinct")
    assert unverified.verification_status == "unverified"


def test_refuted_and_superseded_are_excluded_by_default(tmp_path: Path) -> None:
    records = build_test_records(tmp_path)
    filtered = ci.filter_records(
        records,
        min_confidence=0.80,
        high_confidence_pin=0.95,
        recent_days=30,
        include_refuted=False,
    )
    ids = {record.record_id for record in filtered}
    assert ids == {"confirmed-instinct", "unverified-instinct"}


def test_confirmed_is_kept_and_include_refuted_adds_audit_records(tmp_path: Path) -> None:
    records = build_test_records(tmp_path)
    filtered = ci.filter_records(
        records,
        min_confidence=0.80,
        high_confidence_pin=0.95,
        recent_days=30,
        include_refuted=True,
    )
    ids = {record.record_id for record in filtered}
    assert ids == {
        "confirmed-instinct",
        "unverified-instinct",
        "refuted-instinct",
        "superseded-instinct",
    }


def test_jsonl_and_markdown_include_status_and_verified_by(tmp_path: Path) -> None:
    records = build_test_records(tmp_path)
    filtered = ci.filter_records(
        records,
        min_confidence=0.80,
        high_confidence_pin=0.95,
        recent_days=30,
        include_refuted=True,
    )
    sorted_records = ci.sort_records(filtered)
    jsonl_text = ci.render_jsonl(sorted_records)
    lines = [json.loads(line) for line in jsonl_text.splitlines() if line.strip()]

    assert lines[0]["verification_status"] == "confirmed"
    assert lines[0]["verified_by"] == [
        {
            "session": "2026-06-23",
            "method": "walk-forward backtest",
            "result": "confirmed",
            "evidence": "lift 1.43x on holdout, p<0.01",
        }
    ]
    assert lines[1]["verification_status"] == "refuted"
    assert lines[2]["verification_status"] == "superseded"
    assert lines[3]["verification_status"] == "unverified"

    markdown = ci.render_markdown(
        sorted_records,
        total_records_scanned=len(records),
        instincts_dir=tmp_path,
        min_confidence=0.80,
        recent_days=30,
        status_breakdown=ci.count_statuses(records),
    )

    assert "- status_breakdown: unverified=1, confirmed=1, refuted=1, superseded=1" in markdown
    assert "status: `confirmed`" in markdown
    assert "status: `refuted`" in markdown
    assert "status: `superseded`" in markdown
    assert "status: `unverified`" in markdown


def _relation_header(record_id: str, *, confidence: float, relation: str = "", target: str = "") -> str:
    lines = [
        f"id: {record_id}",
        f'trigger: "{record_id} trigger"',
        f"confidence: {confidence}",
    ]
    if relation:
        lines += [f"{relation}:", f"  - id: {target}", "    reason: data_bug"]
    lines += [
        "domain: test",
        "source: session-observation",
        "project_id: 2026project",
        "project_name: pachinko-analyzer",
    ]
    return "\n".join(lines)


def test_declared_supersedes_closes_the_target(tmp_path: Path) -> None:
    write_instinct(tmp_path / f"{RECENT_DATE}-old.yaml", header=_relation_header("old-claim", confidence=0.99))
    write_instinct(
        tmp_path / f"{RECENT_DATE}-new.yaml",
        header=_relation_header("new-claim", confidence=0.85, relation="supersedes", target="old-claim"),
    )

    records = ci.dedupe_latest(ci.collect_records(tmp_path, include_underscored_sources=False))
    applied = ci.apply_relations(records)
    by_id = {record.record_id: record for record in records}

    assert applied == {"superseded": 1}
    assert by_id["old-claim"].verification_status == "superseded"
    assert by_id["new-claim"].verification_status == "unverified"
    # The superseded record must drop out even though its confidence is higher.
    kept = ci.filter_records(
        records, min_confidence=0.80, high_confidence_pin=0.95, recent_days=30, include_refuted=False
    )
    assert [record.record_id for record in kept] == ["new-claim"]


def test_declared_invalidates_marks_refuted_and_respects_manual_status(tmp_path: Path) -> None:
    write_instinct(
        tmp_path / f"{RECENT_DATE}-confirmed.yaml",
        header=_relation_header("already-confirmed", confidence=0.9) + "\nverification_status: confirmed",
    )
    write_instinct(tmp_path / f"{RECENT_DATE}-target.yaml", header=_relation_header("bad-claim", confidence=0.9))
    write_instinct(
        tmp_path / f"{RECENT_DATE}-refuter.yaml",
        header=_relation_header("refuter", confidence=0.8, relation="invalidates", target="bad-claim"),
    )
    write_instinct(
        tmp_path / f"{RECENT_DATE}-overreach.yaml",
        header=_relation_header("overreach", confidence=0.8, relation="invalidates", target="already-confirmed"),
    )

    records = ci.dedupe_latest(ci.collect_records(tmp_path, include_underscored_sources=False))
    ci.apply_relations(records)
    by_id = {record.record_id: record for record in records}

    assert by_id["bad-claim"].verification_status == "refuted"
    # A hand-verified record is never downgraded by someone else's declaration.
    assert by_id["already-confirmed"].verification_status == "confirmed"


def test_allocate_records_reserves_slots_for_recent_work(tmp_path: Path) -> None:
    old_date = (datetime.now(timezone.utc).date() - timedelta(days=120)).isoformat()
    for i in range(10):
        write_instinct(tmp_path / f"{old_date}-old{i}.yaml", header=_relation_header(f"old-{i}", confidence=1.0))
    for i in range(10):
        write_instinct(tmp_path / f"{RECENT_DATE}-new{i}.yaml", header=_relation_header(f"new-{i}", confidence=0.81))

    records = ci.dedupe_latest(ci.collect_records(tmp_path, include_underscored_sources=False))
    selected = ci.allocate_records(records, max_records=10, recent_days=21, recent_slots=6)
    ids = [record.record_id for record in selected]

    # Without a reserve, all ten slots would go to the confidence-1.0 old records.
    assert sum(1 for i in ids if i.startswith("new-")) == 6
    assert sum(1 for i in ids if i.startswith("old-")) == 4


def test_extract_action_prefers_japanese_action_heading(tmp_path: Path) -> None:
    body = "# title\n\n## 背景\nbackground line\n\n## アクション\n- 折り返された\n  指針の続き\n\n## 例\nexample\n"
    assert ci.extract_action(body, "fallback trigger") == "折り返された 指針の続き"
    assert ci.extract_action("# title\n\nno sections here", "fallback trigger") == "fallback trigger"


def test_collect_records_and_filtering_can_be_used_end_to_end(tmp_path: Path) -> None:
    records = build_test_records(tmp_path)
    filtered = ci.filter_records(
        records,
        min_confidence=0.80,
        high_confidence_pin=0.95,
        recent_days=30,
        include_refuted=False,
    )
    markdown = ci.render_markdown(
        filtered,
        total_records_scanned=len(records),
        instincts_dir=tmp_path,
        min_confidence=0.80,
        recent_days=30,
        status_breakdown=ci.count_statuses(records),
    )
    payloads = [json.loads(line) for line in ci.render_jsonl(filtered).splitlines()]

    assert len(filtered) == 2
    assert payloads[0]["id"] == "confirmed-instinct"
    assert payloads[1]["id"] == "unverified-instinct"
    assert "active_records: 2" in markdown
