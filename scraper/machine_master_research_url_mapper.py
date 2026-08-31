#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resolve 1geki source URLs into the canonical machine master."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import tempfile
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from bs4 import BeautifulSoup


REPO_ROOT = Path(__file__).resolve().parents[1]
MACHINE_MASTER_RESEARCH_DIR = REPO_ROOT / "document" / "machine_master_research"
DB_DIR = REPO_ROOT / "db"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
SEARCH_BASE_URL = "https://www.1geki.jp/search/?keyword="
SITEMAP_INDEX_URL = "https://1geki.jp/sitemap.xml"
MACHINE_ALIAS_MAP = {
    "009recyborg": ["パチスロ009リサイボーグ", "009リサイボーグ", "リサイボーグ009"],
    "galfy": ["ガルフィー", "lbスロットガルフィーa4", "lbgalfy"],
    "sisterquest": ["シスタークエスト", "sisterquest", "シスクエ"],
}
ALIAS_SPLIT_PATTERN = re.compile(r"[,\n\r|/；;、]+")
SOURCE_COLUMNS = (
    "source_url",
    "source_status",
    "source_confidence",
    "source_query",
    "source_candidate_count",
    "source_reason",
)


@dataclass(frozen=True)
class Candidate:
    title: str
    url: str
    score: float
    reason: str


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[^\w]+", "", normalized, flags=re.UNICODE)
    return normalized


def _normalize_machine_key(machine_name: str) -> str:
    return normalize_text(machine_name)


def _add_unique_alias(bucket: list[str], alias: str) -> None:
    cleaned = alias.strip()
    if not cleaned:
        return
    key = normalize_text(cleaned)
    if any(normalize_text(existing) == key for existing in bucket):
        return
    bucket.append(cleaned)


def _split_alias_field(value: str | None) -> list[str]:
    if not value:
        return []
    normalized = unicodedata.normalize("NFKC", value)
    parts = [part.strip() for part in ALIAS_SPLIT_PATTERN.split(normalized)]
    return [part for part in parts if part]


def load_machine_master_alias_map(db_dir: Path = DB_DIR) -> dict[str, list[str]]:
    alias_map: dict[str, list[str]] = {}
    if not db_dir.exists():
        return alias_map

    for db_path in sorted(db_dir.glob("*.db")):
        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='machine_master'")
                if cursor.fetchone() is None:
                    continue
                cursor.execute("SELECT machine_name_normalized, display_names, official_name FROM machine_master")
                rows = cursor.fetchall()
        except sqlite3.Error:
            continue

        for machine_name_normalized, display_names, official_name in rows:
            machine_key = _normalize_machine_key(str(machine_name_normalized or ""))
            if not machine_key:
                continue

            bucket = alias_map.setdefault(machine_key, [])
            _add_unique_alias(bucket, str(machine_name_normalized or ""))
            for alias in _split_alias_field(display_names):
                _add_unique_alias(bucket, alias)
            for alias in _split_alias_field(official_name):
                _add_unique_alias(bucket, alias)

    return alias_map


def get_machine_aliases(
    machine_name: str,
    *,
    machine_master_alias_map: dict[str, list[str]] | None = None,
) -> list[str]:
    aliases = [machine_name]
    machine_key = _normalize_machine_key(machine_name)
    aliases.extend(MACHINE_ALIAS_MAP.get(machine_key, []))
    if machine_master_alias_map:
        aliases.extend(machine_master_alias_map.get(machine_key, []))
    aliases.extend(_generate_heuristic_aliases(machine_name))

    deduped: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        cleaned = alias.strip()
        if not cleaned:
            continue
        key = normalize_text(cleaned)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped


def _generate_heuristic_aliases(machine_name: str) -> list[str]:
    cleaned = machine_name.strip()
    cleaned = cleaned.replace("（", "(").replace("）", ")")
    cleaned = cleaned.replace("　", " ").replace("／", "/").replace("‐", "-").replace("－", "-")

    variants = {cleaned}
    if "/" in cleaned:
        variants.add(cleaned.split("/")[0].strip())
    if "(" in cleaned:
        variants.add(cleaned.split("(")[0].strip())

    prefix_patterns = [
        r"^スマスロ[\s\-]*",
        r"^パチスロ[\s\-]*",
        r"^LB[\s\-]*",
        r"^A[\-‐]SLOT\+?[\s\-]*",
        r"^SLOT[\s\-]*",
        r"^スマート沖スロ[\s\-]*",
    ]
    suffix_patterns = [
        r"\s*\(スマスロ\)$",
        r"\s*\(シスタークエスト\)$",
        r"\s*TRANCE\s*ver\.8\.7$",
        r"\s*BT$",
        r"\s*BTC9$",
        r"\s*CF$",
        r"\s*XF$",
        r"\s*A$",
        r"\s*TP$",
        r"\s*25Φ$",
        r"\s*30Φ$",
    ]

    for variant in list(variants):
        stripped = variant
        for pattern in prefix_patterns:
            stripped = re.sub(pattern, "", stripped, flags=re.IGNORECASE)
        for pattern in suffix_patterns:
            stripped = re.sub(pattern, "", stripped, flags=re.IGNORECASE)
        stripped = " ".join(stripped.split())
        if stripped:
            variants.add(stripped)

    series_aliases: list[str] = []
    series_rules = [
        ("番長", ["番長4", "番長ZERO"]),
        ("銭形", ["銭形4", "銭形5"]),
        ("秘宝伝", ["秘宝伝"]),
        ("ニューパルサー", ["ニューパルサー", "ニューパルサーSP4"]),
        ("ハーレムエース", ["ハーレムエース"]),
        ("シスタークエスト", ["シスタークエスト", "Sister Quest", "シスクエ"]),
        ("Sister Quest", ["シスタークエスト", "Sister Quest", "シスクエ"]),
        ("カイジ", ["カイジ狂宴"]),
        ("レヴュースタァライト", ["レヴュースタァライト", "少女☆歌劇レヴュースタァライト"]),
        ("ToLOVEる", ["ToLOVEるダークネス", "トラブルダークネス"]),
        ("ガルフィ", ["ガルフィー"]),
        ("1000ちゃん", ["1000ちゃん"]),
        (
            "コードギアス",
            [
                "パチスロコードギアス 反逆のルルーシュ3 C.C.＆Kallen ver.",
                "コードギアス反逆のルルーシュ3 C.C.＆Kallen ver.",
                "コードギアス反逆のルルーシュ3 CCカレンver.",
            ],
        ),
        ("ひぐらし", ["ひぐらしのなく頃に 業", "パチスロひぐらしのなく頃に 業", "ひぐらし業"]),
        ("ULTRAMAN", ["ULTRAMAN", "L ULTRAMAN", "パチスロULTRAMAN-KE"]),
        ("コトブキ飛行隊", ["荒野のコトブキ飛行隊", "コトブキ飛行隊"]),
        ("なめ猫", ["なめ猫", "なめ猫～液晶ないけどなめんじゃねぇ～"]),
        ("沖ドキ!ゴージャス", ["沖ドキ!ゴージャス", "沖ドキ!ゴージャス 25Φ", "沖ドキ!ゴージャス 30Φ"]),
    ]
    for needle, aliases in series_rules:
        if needle in cleaned:
            series_aliases.extend(aliases)

    return [variant for variant in list(variants) + series_aliases if variant and variant != machine_name]


def build_query_variants(machine_name: str) -> list[str]:
    raw = machine_name.strip()
    stripped = raw.strip("/ ")
    variants = [raw]
    for candidate in (stripped, stripped.replace("/", " "), stripped.replace("/", ""), raw.replace("/", " ")):
        candidate = " ".join(candidate.split())
        if candidate and candidate not in variants:
            variants.append(candidate)
    for candidate in _generate_heuristic_aliases(raw):
        candidate = " ".join(candidate.split())
        if candidate and candidate not in variants:
            variants.append(candidate)
    return variants


def build_search_url(query: str) -> str:
    return SEARCH_BASE_URL + urllib.parse.quote_plus(query)


def fetch_html(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        encoding = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(encoding, errors="replace")


def _fetch_xml(url: str, timeout: int = 30) -> str:
    return fetch_html(url, timeout=timeout)


def _is_detail_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc and parsed.netloc not in {"1geki.jp", "www.1geki.jp"}:
        return False
    if not parsed.path.startswith("/slot/"):
        return False
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return False
    if any(token in parsed.path for token in ["/category/", "/tag/", "/author/", "/page/", "/feed"]):
        return False
    return True


def extract_candidate_urls(search_html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(search_html, "html.parser")
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        url = urllib.parse.urljoin("https://1geki.jp", anchor["href"].strip())
        if url in seen or not _is_detail_url(url):
            continue
        seen.add(url)
        title = anchor.get_text(" ", strip=True)
        candidates.append({"title": title, "url": url})

    return candidates


def _extract_sitemap_urls(xml_text: str) -> list[str]:
    root = ET.fromstring(xml_text)
    urls: list[str] = []
    for node in root.findall(".//{*}loc"):
        if node.text:
            urls.append(node.text.strip())
    return urls


def collect_slot_page_urls(*, fetch_xml: Callable[[str], str] = _fetch_xml) -> list[str]:
    sitemap_xml = fetch_xml(SITEMAP_INDEX_URL)
    child_sitemaps = [url for url in _extract_sitemap_urls(sitemap_xml) if "slot-sitemap" in url]

    page_urls: list[str] = []
    seen: set[str] = set()
    for sitemap_url in child_sitemaps:
        child_xml = fetch_xml(sitemap_url)
        for page_url in _extract_sitemap_urls(child_xml):
            if "/slot/" not in page_url:
                continue
            parsed = urllib.parse.urlparse(page_url)
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) != 2:
                continue
            if page_url in seen:
                continue
            seen.add(page_url)
            page_urls.append(page_url)
    return page_urls


def extract_page_title(html_text: str) -> str:
    soup = BeautifulSoup(html_text, "html.parser")
    for selector in ("h1", "title"):
        node = soup.find(selector)
        if node:
            title = node.get_text(" ", strip=True)
            if title:
                return title
    return ""


def build_page_index(
    *,
    index_path: Path,
    refresh: bool = False,
    limit: int | None = None,
    fetch_html: Callable[[str], str] = fetch_html,
    fetch_xml: Callable[[str], str] = _fetch_xml,
) -> list[dict[str, str]]:
    if index_path.exists() and not refresh:
        with index_path.open("r", encoding="utf-8") as handle:
            cached = json.load(handle)
        if isinstance(cached, list) and cached:
            return [item for item in cached if isinstance(item, dict) and item.get("url") and item.get("title")]

    page_urls = collect_slot_page_urls(fetch_xml=fetch_xml)
    if limit is not None:
        page_urls = page_urls[:limit]

    index: list[dict[str, str]] = []
    for url in page_urls:
        try:
            html_text = fetch_html(url)
        except Exception:
            continue
        title = extract_page_title(html_text)
        if title:
            index.append({"url": url, "title": title})

    _write_json(index_path, index)
    return index


def _score_candidate(
    machine_name: str,
    candidate: dict[str, str],
    *,
    machine_master_alias_map: dict[str, list[str]] | None = None,
) -> Candidate:
    machine_aliases = [
        normalize_text(alias)
        for alias in get_machine_aliases(machine_name, machine_master_alias_map=machine_master_alias_map)
    ]
    title_norm = normalize_text(candidate.get("title", ""))
    slug_norm = normalize_text(urllib.parse.unquote(urllib.parse.urlparse(candidate["url"]).path))

    score = 0.0
    reasons: list[str] = []

    if any(alias and alias == title_norm for alias in machine_aliases):
        score += 1.0
        reasons.append("title_exact")
    elif any(alias and alias in title_norm for alias in machine_aliases):
        score += 0.85
        reasons.append("title_contains")

    if any(alias and alias in slug_norm for alias in machine_aliases):
        score += 0.35
        reasons.append("slug_contains")

    if candidate["url"].endswith("/0/"):
        score -= 0.1
        reasons.append("detail_subpage")

    return Candidate(
        title=candidate.get("title", ""),
        url=candidate["url"],
        score=score,
        reason=",".join(reasons) if reasons else "unmatched",
    )


def _score_page_index_candidate(
    machine_name: str,
    candidate: dict[str, str],
    *,
    machine_master_alias_map: dict[str, list[str]] | None = None,
) -> Candidate:
    machine_aliases = [
        normalize_text(alias)
        for alias in get_machine_aliases(machine_name, machine_master_alias_map=machine_master_alias_map)
    ]
    title_norm = normalize_text(candidate.get("title", ""))
    slug_norm = normalize_text(urllib.parse.unquote(urllib.parse.urlparse(candidate["url"]).path))

    score = 0.0
    reasons: list[str] = []

    if any(alias and alias == title_norm for alias in machine_aliases):
        score += 1.0
        reasons.append("title_exact")
    elif any(alias and alias in title_norm for alias in machine_aliases):
        score += 0.9
        reasons.append("title_contains")

    if any(alias and alias in slug_norm for alias in machine_aliases):
        score += 0.2
        reasons.append("slug_contains")

    return Candidate(
        title=candidate.get("title", ""),
        url=candidate["url"],
        score=score,
        reason=",".join(reasons) if reasons else "unmatched",
    )


def _resolve_machine_url_via_search(
    machine_name: str,
    *,
    machine_master_alias_map: dict[str, list[str]] | None = None,
    fetch_html: Callable[[str], str] = fetch_html,
) -> dict[str, object] | None:
    best: Candidate | None = None
    best_query = ""
    best_candidates: list[Candidate] = []

    for query in build_query_variants(machine_name):
        search_url = build_search_url(query)
        try:
            html = fetch_html(search_url)
        except Exception:
            continue
        raw_candidates = extract_candidate_urls(html)
        scored = [
            _score_candidate(
                machine_name,
                candidate,
                machine_master_alias_map=machine_master_alias_map,
            )
            for candidate in raw_candidates
        ]
        scored.sort(key=lambda item: (item.score, len(item.title)), reverse=True)

        if scored:
            best_query = query
            best_candidates = scored
            best = scored[0]
            if best.score >= 0.8:
                break

    if not best:
        return None

    status = "selected" if best.score >= 0.8 else "needs_review"
    return {
        "machine_name": machine_name,
        "status": status,
        "selected_url": best.url,
        "confidence": round(min(best.score, 1.0), 3),
        "query": best_query,
        "candidates": [
            {"title": candidate.title, "url": candidate.url, "score": candidate.score, "reason": candidate.reason}
            for candidate in best_candidates
        ],
        "reason": best.reason,
    }


def resolve_machine_url(
    machine_name: str,
    *,
    page_index: list[dict[str, str]] | None = None,
    machine_master_alias_map: dict[str, list[str]] | None = None,
    fetch_html: Callable[[str], str] = fetch_html,
) -> dict[str, object]:
    if page_index is not None:
        scored = [
            _score_page_index_candidate(
                machine_name,
                candidate,
                machine_master_alias_map=machine_master_alias_map,
            )
            for candidate in page_index
        ]
        scored = [candidate for candidate in scored if candidate.score > 0.0]
        scored.sort(key=lambda item: (item.score, len(item.title)), reverse=True)
        if scored:
            best = scored[0]
            page_result = {
                "machine_name": machine_name,
                "status": "selected" if best.score >= 0.8 else "needs_review",
                "selected_url": best.url,
                "confidence": round(min(best.score, 1.0), 3),
                "query": machine_name,
                "candidates": [
                    {
                        "title": candidate.title,
                        "url": candidate.url,
                        "score": candidate.score,
                        "reason": candidate.reason,
                    }
                    for candidate in scored[:10]
                ],
                "reason": best.reason,
            }
            if best.score >= 0.8:
                return page_result
        else:
            page_result = {
                "machine_name": machine_name,
                "status": "not_found",
                "selected_url": "",
                "confidence": 0.0,
                "query": machine_name,
                "candidates": [],
                "reason": "no_candidates",
            }

        search_result = _resolve_machine_url_via_search(
            machine_name,
            machine_master_alias_map=machine_master_alias_map,
            fetch_html=fetch_html,
        )
        if search_result is not None:
            if page_result["status"] == "not_found":
                return search_result
            if search_result["confidence"] > page_result["confidence"]:
                return search_result
            return page_result
        return page_result

    search_result = _resolve_machine_url_via_search(
        machine_name,
        machine_master_alias_map=machine_master_alias_map,
        fetch_html=fetch_html,
    )
    if search_result is not None:
        return search_result
    return {
        "machine_name": machine_name,
        "status": "not_found",
        "selected_url": "",
        "confidence": 0.0,
        "query": "",
        "candidates": [],
        "reason": "no_candidates",
    }


def _read_machine_names(input_path: Path) -> list[str]:
    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [row.get("machine_name", "").strip() for row in rows if row.get("machine_name", "").strip()]


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _write_master_atomic(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8-sig",
        newline="",
        delete=False,
        dir=path.parent,
        prefix=f"{path.stem}_",
        suffix=".tmp",
    ) as handle:
        temp_path = Path(handle.name)
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temp_path.replace(path)


def _source_fields(entry: dict[str, object]) -> dict[str, str]:
    confidence = entry.get("confidence")
    candidate_count = entry.get("candidate_count")
    if candidate_count is None:
        candidate_count = len(entry.get("candidates", []))
    return {
        "source_url": str(entry.get("selected_url") or "").strip(),
        "source_status": str(entry.get("status") or "").strip(),
        "source_confidence": "" if confidence is None else str(confidence).strip(),
        "source_query": str(entry.get("query") or "").strip(),
        "source_candidate_count": "" if candidate_count is None else str(candidate_count).strip(),
        "source_reason": str(entry.get("reason") or "").strip(),
    }


def apply_url_entries_to_master(
    input_path: Path,
    entries: Iterable[dict[str, object]],
) -> dict[str, int]:
    """Store selected URLs and their resolution evidence in the canonical master."""
    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    if "machine_name" not in fieldnames:
        raise ValueError("machine_master_missing_machine_name")
    for column in SOURCE_COLUMNS:
        if column not in fieldnames:
            fieldnames.append(column)

    entry_by_name = {
        str(entry.get("machine_name") or "").strip(): entry
        for entry in entries
        if str(entry.get("machine_name") or "").strip()
    }
    updated = 0
    for row in rows:
        entry = entry_by_name.get(row.get("machine_name", "").strip())
        if entry is None:
            continue
        fields = _source_fields(entry)
        if any(row.get(column, "") != value for column, value in fields.items()):
            updated += 1
        row.update(fields)

    _write_master_atomic(input_path, fieldnames, rows)
    return {"rows_total": len(rows), "rows_updated": updated, "entries_applied": len(entry_by_name)}


def load_legacy_url_map(path: Path) -> list[dict[str, object]]:
    """Read the old flat URL map only for the one-time canonical-master migration."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    entries: list[dict[str, object]] = []
    for row in rows:
        entries.append(
            {
                "machine_name": row.get("machine_name", ""),
                "status": row.get("status", ""),
                "selected_url": row.get("selected_url", ""),
                "confidence": row.get("confidence", ""),
                "query": row.get("query", ""),
                "candidate_count": row.get("candidate_count", ""),
                "candidates": [],
                "reason": row.get("reason", ""),
            }
        )
    return entries


def build_url_map(
    *,
    input_path: Path,
    audit_path: Path | None = None,
    page_index: list[dict[str, str]] | None = None,
    page_index_path: Path | None = None,
    refresh_index: bool = False,
    machine_master_alias_map: dict[str, list[str]] | None = None,
    fetch_html: Callable[[str], str] = fetch_html,
) -> dict[str, object]:
    if page_index is None:
        if page_index_path is None:
            page_index_path = input_path.parent / "1geki_slot_page_index.json"
        page_index = build_page_index(
            index_path=page_index_path,
            refresh=refresh_index,
            fetch_html=fetch_html,
        )

    if machine_master_alias_map is None:
        machine_master_alias_map = load_machine_master_alias_map()

    machine_names = _read_machine_names(input_path)
    entries = [
        resolve_machine_url(
            machine_name,
            page_index=page_index,
            machine_master_alias_map=machine_master_alias_map,
            fetch_html=fetch_html,
        )
        for machine_name in machine_names
    ]
    master_summary = apply_url_entries_to_master(input_path, entries)
    if audit_path is not None:
        _write_json(audit_path, entries)

    selected = sum(1 for entry in entries if entry["status"] == "selected")
    review = sum(1 for entry in entries if entry["status"] == "needs_review")
    not_found = sum(1 for entry in entries if entry["status"] == "not_found")

    return {
        "rows_total": len(entries),
        "rows_selected": selected,
        "rows_needing_review": review,
        "rows_not_found": not_found,
        "master_path": str(input_path),
        "master_rows_updated": master_summary["rows_updated"],
        "audit_path": str(audit_path) if audit_path is not None else None,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve 1geki source URLs into machine_master.csv")
    parser.add_argument(
        "--input",
        type=Path,
        default=MACHINE_MASTER_RESEARCH_DIR / "machine_master.csv",
    )
    parser.add_argument(
        "--audit-json",
        type=Path,
        help="Optional detailed URL-resolution audit; not a runtime input",
    )
    parser.add_argument(
        "--page-index",
        type=Path,
        default=MACHINE_MASTER_RESEARCH_DIR / "1geki_slot_page_index.json",
    )
    parser.add_argument("--refresh-index", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = build_url_map(
        input_path=args.input,
        audit_path=args.audit_json,
        page_index_path=args.page_index,
        refresh_index=args.refresh_index,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
