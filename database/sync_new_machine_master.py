"""Discover new Anaslo machine names and add verified 1geki specifications.

Run after the hall DB import, not inside per-machine inserts. Ambiguous or
unpublished machines remain in a review report and are retried on the next run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.bonus_specs import categorize, load_specs, normalize  # noqa: E402
from scraper import fetch_rtp_via_llm as research  # noqa: E402
from scraper import machine_master_research_url_mapper as url_mapper  # noqa: E402

MASTER_CSV = ROOT / "document" / "machine_master_research" / "machine_master.csv"
DB_DIR = ROOT / "db"
REVIEW_PATH = ROOT / "scratch" / "machine_master_new_machine_review.json"
RELEASE_WINDOW_DAYS = 60
MAX_SEARCH_NAMES = 10
MAX_RUNTIME_SECONDS = 60


def fetch_html_quick(url: str) -> str:
    return url_mapper.fetch_html(url, timeout=6)


def identity_key(value: str) -> str:
    """Compare full titles, retaining sequel words and model numbers."""
    value = unicodedata.normalize("NFKC", value or "").casefold().strip()
    value = re.sub(r"^(?:(?:スマスロ|スマートスロット|パチスロ|スロット|l)\s*)+", "", value)
    return re.sub(r"[^\w]+", "", value)


def match_key(value: str) -> str:
    """Keep platform prefixes so old and smart-slot editions stay distinct."""
    value = unicodedata.normalize("NFKC", value or "").casefold()
    return re.sub(r"[^\w]+", "", value)


def known_rows(header: list[str], rows: list[list[str]]) -> dict[str, dict[str, str]]:
    known: dict[str, dict[str, str]] = {}
    ambiguous: set[str] = set()
    for row in rows:
        data = dict(zip(header, row))
        for field in ("machine_name", "canonical_machine_name"):
            if data.get(field):
                key = match_key(data[field])
                if key in known and known[key]["canonical_machine_name"] != data["canonical_machine_name"]:
                    ambiguous.add(key)
                else:
                    known.setdefault(key, data)
    for key in ambiguous:
        known.pop(key, None)
    return known


def discover(db_dir: Path, halls: list[str], known: dict[str, dict[str, str]]):
    missing: dict[str, dict] = {}
    category_gaps: list[tuple[Path, str, dict[str, str]]] = []
    for hall in halls:
        path = db_dir / f"{hall}.db"
        if not path.is_file() or path.stat().st_size == 0:
            continue
        with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"machine_detailed_results", "machine_master"} <= tables:
                continue
            columns = {r[1] for r in conn.execute("PRAGMA table_info(machine_master)")}
            has_category = "spec_category" in columns
            category_sql = "mm.spec_category" if has_category else "NULL"
            query = (
                "SELECT d.machine_name, MIN(d.date), " + category_sql + " FROM machine_detailed_results d "
                "LEFT JOIN machine_master mm ON mm.machine_name_normalized=d.machine_name "
                "GROUP BY d.machine_name"
            )
            for name, first_seen, category in conn.execute(query):
                if not name or name.endswith("その他機種"):
                    continue
                existing = known.get(match_key(name))
                if existing:
                    if category is None:
                        category_gaps.append((path, name, existing))
                    continue
                entry = missing.setdefault(name, {"name": name, "first_seen": first_seen, "halls": []})
                entry["halls"].append(hall)
                if first_seen and (not entry["first_seen"] or first_seen < entry["first_seen"]):
                    entry["first_seen"] = first_seen
    return missing, category_gaps


def candidate_urls(name: str, fetch_search=fetch_html_quick, deadline: float | None = None) -> tuple[list[str], bool]:
    urls: list[str] = []
    for query in url_mapper.build_query_variants(name)[:2]:
        if deadline is not None and time.monotonic() >= deadline:
            return urls, False
        try:
            html = fetch_search(url_mapper.build_search_url(query))
        except Exception:
            continue
        for candidate in url_mapper.extract_candidate_urls(html):
            url = candidate["url"]
            if url not in urls:
                urls.append(url)
        if len(urls) >= 4:
            break
    return urls[:4], True


def assess_page(name: str, first_seen: str, url: str, html: str) -> tuple[dict | None, str]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "1geki.jp" or not re.fullmatch(r"/slot/[^/]+/", parsed.path):
        return None, "invalid_source_url"
    result = research.extract_specs_from_html(name, html, url)
    official = str(result.get("official_name") or "")
    if not official:
        heading = BeautifulSoup(html, "html.parser").select_one(".h1_mini")
        official = heading.get_text(" ", strip=True) if heading else ""
        if official:
            result["official_name"] = official
    if not official or identity_key(name) != identity_key(official):
        return None, "official_name_mismatch"
    if not result.get("manufacturer") or not result.get("machine_type"):
        return None, "missing_identity_metadata"
    try:
        release = date.fromisoformat(result["release_date"])
        observed = datetime.strptime(first_seen, "%Y%m%d").date()
    except KeyError, TypeError, ValueError:
        return None, "missing_or_invalid_date"
    if not release <= observed <= release + timedelta(days=RELEASE_WINDOW_DAYS):
        return None, "release_outside_new_machine_window"
    if not result.get("rtp1") or not result.get("rtp6"):
        return None, "setting_rtp_incomplete"
    return result, "verified"


def make_row(header: list[str], name: str, result: dict) -> list[str]:
    row = [""] * len(header)
    columns = {column: idx for idx, column in enumerate(header)}
    row[columns["machine_name"]] = name
    row[columns["canonical_machine_name"]] = result["official_name"]
    row[columns["source_status"]] = "selected"
    row[columns["source_confidence"]] = "1.0"
    row[columns["source_query"]] = name
    row[columns["source_candidate_count"]] = "1"
    row[columns["source_reason"]] = "exact_official_name_recent_release"
    research.update_csv_with_results([row], header, [result])
    row[columns["source_checked_at"]] = datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()
    return row


def sync_categories(gaps: list[tuple[Path, str, dict[str, str]]], master_csv: Path, *, apply: bool) -> int:
    specs = load_specs(str(master_csv))
    count = 0
    for path, name, row in gaps:
        spec = specs.get(normalize(row["canonical_machine_name"] or row["machine_name"]))
        if spec is None:
            continue
        category = categorize(row["game_type"], row["bt_flag"])
        if apply:
            with sqlite3.connect(path) as conn:
                existing = {column[1] for column in conn.execute("PRAGMA table_info(machine_master)")}
                for column, kind in (
                    ("game_type", "TEXT"),
                    ("spec_category", "TEXT"),
                    ("bonus_judgeable", "INTEGER"),
                    ("spec_source", "TEXT"),
                ):
                    if column not in existing:
                        conn.execute(f"ALTER TABLE machine_master ADD COLUMN {column} {kind}")
                cursor = conn.execute(
                    "UPDATE machine_master SET game_type=?, spec_category=?, bonus_judgeable=?, spec_source=? "
                    "WHERE machine_name_normalized=? AND spec_category IS NULL",
                    (row["game_type"], category, int(spec["judgeable"]), spec["source"], name),
                )
                count += cursor.rowcount
        else:
            count += 1
    return count


def run(
    *,
    halls: list[str],
    apply: bool = False,
    master_csv: Path = MASTER_CSV,
    db_dir: Path = DB_DIR,
    review_path: Path = REVIEW_PATH,
    fetch_search=fetch_html_quick,
    fetch_page=fetch_html_quick,
) -> dict:
    original_digest = hashlib.sha256(master_csv.read_bytes()).digest()
    header, rows = research.read_csv(master_csv)
    if errors := research.validate_master(header, rows):
        raise ValueError(f"機種マスターCSVが不正です: {errors[:3]}")
    missing, gaps = discover(db_dir, halls, known_rows(header, rows))
    outcomes: list[dict] = []
    added = []
    deadline = time.monotonic() + MAX_RUNTIME_SECONDS
    for idx, item in enumerate(
        sorted(missing.values(), key=lambda x: (x["first_seen"] or "", x["name"]), reverse=True)
    ):
        if idx >= MAX_SEARCH_NAMES or time.monotonic() >= deadline:
            outcomes.append({**item, "status": "deferred", "reason": "daily_limit_or_time_budget"})
            continue
        accepted: list[dict] = []
        rejected: list[dict] = []
        urls, complete = candidate_urls(item["name"], fetch_search, deadline)
        for url in urls:
            if time.monotonic() >= deadline:
                complete = False
                break
            try:
                html = fetch_page(url)
                result, reason = assess_page(item["name"], item["first_seen"], url, html)
            except Exception as exc:
                result, reason = None, f"fetch_or_parse_error:{type(exc).__name__}"
            if result:
                accepted.append(result)
            else:
                rejected.append({"url": url, "reason": reason})
        if not complete:
            outcomes.append({**item, "status": "deferred", "reason": "time_budget"})
        elif len(accepted) == 1:
            rows.append(make_row(header, item["name"], accepted[0]))
            added.append(item["name"])
            outcomes.append({**item, "status": "added" if apply else "ready", "url": accepted[0]["source_url"]})
        else:
            outcomes.append(
                {
                    **item,
                    "status": "needs_review",
                    "reason": (
                        "multiple_verified_pages"
                        if accepted
                        else "search_unavailable_or_no_results"
                        if not rejected
                        else "no_verified_page"
                    ),
                    "verified_urls": [r["source_url"] for r in accepted],
                    "rejected": rejected[:8],
                }
            )
    if errors := research.validate_master(header, rows):
        raise ValueError(f"追加後の機種マスターCSVが不正です: {errors[:3]}")
    if apply and added:
        if hashlib.sha256(master_csv.read_bytes()).digest() != original_digest:
            raise RuntimeError("機種マスターCSVが処理中に変更されました。再実行してください")
        research._write_csv_atomic(master_csv, header, rows)
    if added:
        updated = known_rows(header, rows)
        _, new_gaps = discover(db_dir, halls, updated)
        gaps = new_gaps
    synced = sync_categories(gaps, master_csv, apply=apply)
    summary = {
        "new_names": len(missing),
        "added": added if apply else [],
        "ready": [] if apply else added,
        "category_rows_synced": synced if apply else 0,
        "category_rows_ready": 0 if apply else synced,
        "outcomes": outcomes,
    }
    if apply:
        review_path.parent.mkdir(parents=True, exist_ok=True)
        temp = review_path.with_suffix(".tmp")
        temp.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(review_path)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hall", action="append", help="DBのホール名。省略時は設定の全アクティブホール")
    parser.add_argument("--apply", action="store_true", help="検証済みの行とDB分類を書き込む")
    args = parser.parse_args()
    if args.hall:
        halls = args.hall
    else:
        config_path = ROOT / "config" / "hall_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        halls = [item["hall_name"] for item in config["halls"] if item.get("active", True)]
    result = run(halls=halls, apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
