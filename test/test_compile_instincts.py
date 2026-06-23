from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import compile_instincts as ci  # noqa: E402


def write_instinct(path: Path, *, header: str, body: str = "body text") -> None:
    path.write_text(f"---\n{header}\n---\n{body}\n", encoding="utf-8")


def build_test_records(tmp_path: Path) -> list[ci.InstinctRecord]:
    write_instinct(
        tmp_path / "2026-06-23-confirmed.yaml",
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
        tmp_path / "2026-06-23-unverified.yaml",
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
        tmp_path / "2026-06-23-refuted.yaml",
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
        tmp_path / "2026-06-23-superseded.yaml",
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
