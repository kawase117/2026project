#!/usr/bin/env python3
"""Retrieve instincts by what you are about to do, not by when they were written.

`trigger` is the only field with 100% coverage across the corpus (1476/1476 as
of 2026-07-31) and it is written as "…するとき" — a statement of when the record
applies. Nothing consulted it until now: ACTIVE_INSTINCTS is ordered by date and
the session-start injection pushes 6 records chosen without reference to the
task at hand. This script closes that gap.

Usage:
    venv\\Scripts\\python.exe scripts/query_instincts.py "楽園のセクション分析"
    venv\\Scripts\\python.exe scripts/query_instincts.py --top 15 "DD 曜日 交絡"
    venv\\Scripts\\python.exe scripts/query_instincts.py --json "角番 残差"
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from compile_instincts import (  # noqa: E402
    EXCLUDED_STATUSES,
    apply_relations,
    collect_records,
    dedupe_latest,
)

CJK = r"぀-ヿ㐀-䶿一-鿿ｦ-ﾟ"
LATIN_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}|\d{2,}")
CJK_RUN = re.compile(rf"[{CJK}]{{2,}}")

# trigger states when a record applies, so a hit there is worth far more than a
# hit anywhere else. id is a hand-written slug and nearly as intentional.
FIELD_WEIGHTS = (
    ("trigger", 6.0),
    ("record_id", 3.0),
    ("domain", 2.0),
    ("action", 1.5),
    ("body_summary", 1.0),
)


def tokenize(text: str) -> set[str]:
    """Character bigrams for CJK plus whole words for latin/digits.

    Bigrams avoid a morphological-analyser dependency while still matching
    "セクション" inside "セクション分析" and "角番" inside "角番残差".
    """
    text = (text or "").lower()
    tokens = set(LATIN_TOKEN.findall(text))
    for run in CJK_RUN.findall(text):
        for i in range(len(run) - 1):
            tokens.add(run[i : i + 2])
    return tokens


# Findings in this project are hall-specific almost without exception, so a
# record about a different hall is usually noise rather than a weaker match.
HALL_ALIASES = {
    "kamata7": ("蒲田7", "蒲田七", "kamata7", "k7"),
    "kamata1": ("蒲田1", "蒲田一", "kamata1", "k1"),
    "rakuen": ("楽園", "rakuen"),
    "mitoya": ("みとや", "ミトヤ", "mitoya"),
    "hiroki": ("ヒロキ", "hiroki"),
    "thecity": ("ザシティ", "thecity"),
    "arrow": ("アロー", "arrow"),
    "kintoki": ("キントキ", "金時", "kintoki"),
    "lategap": ("レイトギャップ", "lategap"),
}
OFF_HALL_PENALTY = 0.25


def detect_halls(text: str) -> set[str]:
    lowered = (text or "").lower()
    return {hall for hall, aliases in HALL_ALIASES.items() if any(a.lower() in lowered for a in aliases)}


def build_idf(records) -> dict[str, float]:
    """Down-weight bigrams that occur nearly everywhere.

    Without this, filler like 結果 / 分析 / 場合 scores as highly as 検出力 or
    事前登録, and a two-word query returns whatever record happens to be
    verbose. Rare terms are what actually identify a record.
    """
    total_docs = len(records) or 1
    document_freq: dict[str, int] = {}
    for record in records:
        seen = tokenize(f"{record.trigger} {record.record_id} {record.domain} {record.body_summary}")
        for token in seen:
            document_freq[token] = document_freq.get(token, 0) + 1
    return {token: math.log(total_docs / (1 + freq)) + 1.0 for token, freq in document_freq.items()}


def score(record, query_tokens: set[str], query_halls: set[str], idf: dict[str, float]) -> tuple[float, list[str]]:
    total = 0.0
    matched: list[str] = []
    # Normalise by the query's own total weight so scores stay comparable
    # across queries of different length.
    query_weight = sum(idf.get(token, 1.0) for token in query_tokens) or 1.0
    for field_name, weight in FIELD_WEIGHTS:
        field_tokens = tokenize(str(getattr(record, field_name, "") or ""))
        hits = query_tokens & field_tokens
        if hits:
            total += weight * sum(idf.get(token, 1.0) for token in hits) / query_weight
            if field_name in ("trigger", "record_id"):
                matched.extend(sorted(hits))

    if query_halls:
        record_halls = detect_halls(f"{record.record_id} {record.trigger} {record.body_summary}")
        # Hall-agnostic records (methodology, statistics) keep full weight.
        if record_halls and not (record_halls & query_halls):
            total *= OFF_HALL_PENALTY

    return total, matched


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(
        description="Search instincts by the task you are about to start.",
    )
    parser.add_argument("query", nargs="+", help="What you are about to do, in your own words.")
    parser.add_argument("--instinct-dir", type=Path, default=repo_root / "document" / "instincts")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument(
        "--hall",
        action="append",
        choices=sorted(HALL_ALIASES),
        help="Restrict to a hall. Inferred from the query when omitted.",
    )
    parser.add_argument(
        "--no-hall-filter",
        action="store_true",
        help="Do not penalise records about other halls.",
    )
    parser.add_argument("--min-confidence", type=float, default=0.0)
    parser.add_argument(
        "--include-retired",
        action="store_true",
        help="Also search refuted/superseded records (for audit).",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    query = " ".join(args.query)
    query_tokens = tokenize(query)
    if not query_tokens:
        print("[ERROR] query produced no searchable tokens")
        return 1

    query_halls: set[str] = set()
    if not args.no_hall_filter:
        query_halls = set(args.hall or []) or detect_halls(query)

    records = dedupe_latest(collect_records(args.instinct_dir.resolve(), include_underscored_sources=False))
    apply_relations(records)
    idf = build_idf(records)

    scored = []
    for record in records:
        if not args.include_retired and record.verification_status in EXCLUDED_STATUSES:
            continue
        if (record.confidence or 0.0) < args.min_confidence:
            continue
        value, matched = score(record, query_tokens, query_halls, idf)
        if value > 0:
            scored.append((value, matched, record))

    scored.sort(key=lambda row: (row[0], row[2].file_date or "", row[2].confidence or 0.0), reverse=True)
    top = scored[: args.top]

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "id": r.record_id,
                        "score": round(v, 3),
                        "matched": m,
                        "date": r.file_date,
                        "confidence": r.confidence,
                        "status": r.verification_status,
                        "domain": r.domain,
                        "trigger": r.trigger,
                        "action": r.action,
                        "file": r.file_name,
                    }
                    for v, m, r in top
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    hall_note = f"  hall={','.join(sorted(query_halls))}" if query_halls else ""
    print(f'query: "{query}"{hall_note}  -> {len(scored)} hit / {len(records)} records (showing {len(top)})')
    if not top:
        print("  該当なし。語を減らすか、別の言い方を試す。")
        return 0
    for rank, (value, matched, record) in enumerate(top, start=1):
        status = "" if record.verification_status == "unverified" else f" [{record.verification_status}]"
        print(f"\n{rank}. {record.record_id}{status}")
        print(f"   {record.file_date} | conf={record.confidence} | {record.domain} | score={value:.2f}")
        print(f"   trigger: {record.trigger}")
        if record.action:
            print(f"   action : {record.action}")
        print(f"   source : {record.file_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
