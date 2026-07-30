from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import compile_instincts as ci  # noqa: E402
from scripts import query_instincts as qi  # noqa: E402

RECENT_DATE = datetime.now(timezone.utc).date().isoformat()


def write(path: Path, record_id: str, trigger: str, *, confidence: float = 0.9, body: str = "本文") -> None:
    path.write_text(
        "---\n"
        f"id: {record_id}\n"
        f'trigger: "{trigger}"\n'
        f"confidence: {confidence}\n"
        "domain: test\n"
        "source: session-observation\n"
        "project_id: 2026project\n"
        "project_name: pachinko-analyzer\n"
        "---\n"
        f"{body}\n",
        encoding="utf-8",
    )


def rank(tmp_path: Path, query: str) -> list[str]:
    records = ci.dedupe_latest(ci.collect_records(tmp_path, include_underscored_sources=False))
    ci.apply_relations(records)
    idf = qi.build_idf(records)
    tokens = qi.tokenize(query)
    halls = qi.detect_halls(query)

    scored = []
    for record in records:
        if record.verification_status in ci.EXCLUDED_STATUSES:
            continue
        value, _ = qi.score(record, tokens, halls, idf)
        if value > 0:
            scored.append((value, record.record_id))
    scored.sort(reverse=True)
    return [record_id for _, record_id in scored]


def test_tokenize_bigrams_match_inside_compounds() -> None:
    tokens = qi.tokenize("セクション分析")
    assert "セク" in tokens
    assert "分析" in tokens
    # Latin identifiers stay whole rather than being split into bigrams.
    assert qi.tokenize("walk_forward AUC") >= {"walk_forward", "auc"}


def test_trigger_match_outranks_body_match(tmp_path: Path) -> None:
    write(tmp_path / f"{RECENT_DATE}-a.yaml", "on-trigger", "角番の残差を評価するとき")
    write(tmp_path / f"{RECENT_DATE}-b.yaml", "on-body", "全く別の話をするとき", body="角番の残差にも触れておく")

    assert rank(tmp_path, "角番の残差")[0] == "on-trigger"


def test_other_hall_records_are_penalised(tmp_path: Path) -> None:
    write(tmp_path / f"{RECENT_DATE}-r.yaml", "rakuen-section", "楽園のセクションを分析するとき")
    write(tmp_path / f"{RECENT_DATE}-m.yaml", "mitoya-section", "みとやのセクションを分析するとき")
    write(tmp_path / f"{RECENT_DATE}-g.yaml", "general-section", "セクションを分析するとき")

    ordering = rank(tmp_path, "楽園のセクション分析")
    assert ordering[0] == "rakuen-section"
    # Hall-agnostic methodology keeps full weight; the other hall drops below it.
    assert ordering.index("general-section") < ordering.index("mitoya-section")


def test_idf_demotes_ubiquitous_terms(tmp_path: Path) -> None:
    for i in range(10):
        write(tmp_path / f"{RECENT_DATE}-common{i}.yaml", f"common-{i}", "結果を分析するとき")
    write(tmp_path / f"{RECENT_DATE}-rare.yaml", "rare-term", "結果の検出力を測るとき")

    # 検出力 appears once; 結果/分析 appear everywhere and must not dominate.
    assert rank(tmp_path, "結果の検出力")[0] == "rare-term"


def test_superseded_records_are_hidden(tmp_path: Path) -> None:
    write(tmp_path / f"{RECENT_DATE}-old.yaml", "old-claim", "角番を評価するとき")
    (tmp_path / f"{RECENT_DATE}-new.yaml").write_text(
        "---\n"
        "id: new-claim\n"
        'trigger: "角番を評価するとき"\n'
        "confidence: 0.85\n"
        "supersedes:\n"
        "  - id: old-claim\n"
        "    reason: data_bug\n"
        "domain: test\n"
        "source: session-observation\n"
        "project_id: 2026project\n"
        "project_name: pachinko-analyzer\n"
        "---\n本文\n",
        encoding="utf-8",
    )

    assert rank(tmp_path, "角番を評価") == ["new-claim"]
