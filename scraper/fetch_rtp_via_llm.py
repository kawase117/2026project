#!/usr/bin/env python3
"""Refresh the research machine master from mapped 1geki pages.

The canonical pipeline is intentionally one command:

1. resolve (and optionally refresh) the target 1geki page address,
2. scrape the page's specification tables,
3. deterministically extract exact setting-numbered fields,
4. export unresolved fields and table HTML for LLM extraction (or call Claude),
5. validate the complete CSV before an atomic update.

Generic bonus probabilities are never re-labelled as BB/RB.
"""

import argparse
import csv
import json
import re
import subprocess
import sys
import tempfile
import unicodedata
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup

try:
    from scraper.machine_master_normalizer import canonical_manufacturer, split_machine_type
except ImportError:
    from machine_master_normalizer import canonical_manufacturer, split_machine_type

REPO_ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = REPO_ROOT / "document" / "machine_master_research" / "machine_master.csv"
DEFAULT_REPORT_PATH = REPO_ROOT / "scratch" / "machine_master_research_scrape_report.json"
DEFAULT_LLM_BATCH_PATH = REPO_ROOT / "scratch" / "machine_master_research_llm_requests.json"
BATCH_SIZE = 10

STRUCTURED_PROBABILITY_METRICS = (
    "at_initial",
    "bonus_initial",
    "bonus_combined",
    "combined_initial",
)

# Known 1geki.jp slugs from prior research (from previous curl + regex extraction)
SLUG_CACHE = {
    "1000ちゃんA": "lb_1000chan_a",
    "A-SLOT+ 異世界かるてっと": "l_isekai_quartet",
    "SHAKE BONUS TRIGGER": "lb_shake",
    "SHAKE BONUS TRIGGER(スマスロ)": "lb_shake",
    "SLOTドルアーガの塔": "s_druaga",
    "なめ猫～液晶ないけどなめんじゃねぇ～": "s_nameneko",
    "ようこそ実力至上主義の教室へ": "l_youjitsu",
    "アレックス ブライト": "lb_arexbright",
    "ストライクウィッチーズ2": "l_strikewitches2",
    "スマスロ炎炎ノ消防隊2": "l_ennenn2",
    "聖戦士ダンバイン": "l_dunbine",
    "スマート沖スロ スターハナハナ": "l_starhnhn30",
    "スマート沖スロ ニューキングハナハナV": "l_new_king_hanahana_v",
    "ニューキングハナハナV-30": "s_new_king_hanahana_v30",
    "スーパーリオエース2": "l_sp_rioace2",
    "ドッチ": "l_asd",
    "ハイビリターン-30": "s_haibi_return30",
    "ビッグドリーム THE GOLDEN PUSHER": "l_bigdream",
    "プレミアムうまい棒": "lb_umaibou",
    "マタドールIII": "l_mtd3",
    "モモキュンソード": "s_momokyun",
    "回胴黙示録カイジ 狂宴": "l_kaiji_ky",
    "少女☆歌劇 レヴュースタァライト ‐The SLOT‐": "l_revuestarlight",
    "甲鉄城のカバネリ 海門(うなと)決戦": "l_kabaneri2",
    "翔べ!ハーレムエース": "lb_harema",
    "荒野のコトブキ飛行隊": "l_kotobuki",
    "銀河英雄伝説 Die Neue These": "l_gineidendnt",
    "革命機ヴァルヴレイヴ2": "l_valvrave2",
    "鬼武者3": "l_onimusya3",
}

IDENTITY_ALIASES = {
    "009 RE:CYBORG": ["パチスロ009 リ・サイボーグ", "009 リ・サイボーグ"],
    "なめ猫～液晶ないけどなめんじゃねぇ～": ["なめ猫"],
    "モモキュンソード": ["モモキュンソードDX スロット 6号機"],
    "吉宗RISING": ["吉宗ライジング"],
    "新・必殺仕置人 回胴 CRASH SPEC": ["必殺仕置人"],
    "賞金首Angel": ["賞金首エンジェル"],
    "パチスロ新鬼武者": ["新鬼武者～DAWN OF DREAMS～"],
}


def read_csv(path: Path = CSV_PATH):
    """Read the research CSV."""
    with open(path, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.reader(f))
    return rows[0], rows[1:]  # header, data rows


def identify_missing_rtp(header, rows):
    """Find rows where at least one supported setting has no RTP value.

    A machine may expose only settings 1/2/5/6.  Such a row still needs to be
    fetched so the published setting numbers can be mapped explicitly; the
    absent settings remain blank after extraction.
    """
    rtp_cols = slice(4, 10)  # columns 4-9: rtp_setting1-6
    missing = []
    for idx, row in enumerate(rows, 1):
        if not all(row[rtp_cols]):
            missing.append((idx, row))
    return missing


def normalize_machine_type(value: str) -> str:
    """Normalize 1geki's free-form type into a useful composite label."""

    normalized = unicodedata.normalize("NFKC", value or "")
    compact = re.sub(r"\s+", "", normalized).upper()
    if not compact:
        return ""

    parts: list[str] = []
    if "スマスロ" in normalized or "スマートスロット" in normalized:
        parts.append("スマスロ")

    game_type = ""
    if re.search(r"A[+＋]ART", compact):
        game_type = "A+ART"
    elif re.search(r"A[+＋]RT", compact):
        game_type = "A+RT"
    elif re.search(r"A[+＋]AT", compact):
        game_type = "A+AT"
    elif "ART" in compact:
        game_type = "ART"
    elif re.search(r"(?:ノーマル|Aタイプ|A-TYPE|ATYPE)", compact):
        game_type = "ノーマル"
    elif re.search(r"(?<![A-Z])AT(?![A-Z])", compact):
        game_type = "AT"
    elif "BONUS" in compact:
        game_type = "ノーマル"

    has_bt = "ボーナストリガー" in normalized or bool(re.search(r"(?:^|[/、,])BT(?:$|[/、,])", compact))
    if has_bt and not game_type:
        game_type = "ノーマル"
    if game_type:
        parts.append(game_type)
    if has_bt:
        parts.append("BT")

    if not parts:
        return normalized.strip()
    return " / ".join(dict.fromkeys(parts))


def _row_mapping(header: list[str], row: list[str]) -> dict[str, str]:
    return {column: row[index].strip() if index < len(row) else "" for index, column in enumerate(header)}


def _looks_like_bonus_machine(row_data: dict[str, str]) -> bool:
    evidence = f"{row_data.get('machine_type', '')} {row_data.get('notes', '')}".upper()
    return bool(re.search(r"ノーマル|Aタイプ|A-TYPE|ボーナストリガー|(?:^|\W)BT(?:$|\W)", evidence))


def find_unresolved_fields(header: list[str], row: list[str]) -> list[str]:
    """Return source fields that still merit a 1geki/LLM lookup.

    A blank in a non-published setting is not automatically an error.  RTP is
    flagged only when wholly absent or when the populated pattern is unusually
    sparse.  Normal/BT machines additionally require explicit BB and RB data.
    """

    data = _row_mapping(header, row)
    unresolved: list[str] = []
    for field in ("manufacturer", "release_date"):
        if not data.get(field):
            unresolved.append(field)

    machine_type = data.get("machine_type", "")
    if not machine_type or machine_type in {"スマスロ", "スマートスロット"}:
        unresolved.append("machine_type")

    rtp_settings = [setting for setting in range(1, 7) if data.get(f"rtp_setting{setting}")]
    sparse_patterns = {(6,), (1, 6), (5, 6)}
    numeric_four_with_special_v = tuple(rtp_settings) == (1, 2, 3, 4) and "設定V:" in data.get("notes", "")
    if (
        not rtp_settings
        or tuple(rtp_settings) in sparse_patterns
        or (tuple(rtp_settings) == (1, 2, 3, 4) and not numeric_four_with_special_v)
    ):
        unresolved.append("rtp")

    if _looks_like_bonus_machine(data):
        notes = data.get("notes", "")
        bb_absence_recorded = any(
            marker in notes for marker in ("一撃掲載表にBB/RB個別確率なし", "一撃掲載表にBB個別確率なし")
        )
        rb_absence_recorded = any(
            marker in notes for marker in ("一撃掲載表にBB/RB個別確率なし", "一撃掲載表にRB個別確率なし")
        )
        if not bb_absence_recorded and not any(data.get(f"bb_setting{setting}") for setting in range(1, 7)):
            unresolved.append("bb")
        if not rb_absence_recorded and not any(data.get(f"rb_setting{setting}") for setting in range(1, 7)):
            unresolved.append("rb")
    return unresolved


def identify_incomplete_rows(header: list[str], rows: list[list[str]]):
    """Find rows with metadata, type, RTP, or normal-machine bonus gaps."""

    return [(index, row) for index, row in enumerate(rows, 1) if find_unresolved_fields(header, row)]


def get_1geki_slug(machine_name: str) -> Optional[str]:
    """Get 1geki.jp slug: check cache first, then try heuristic."""
    # Check known slugs
    if machine_name in SLUG_CACHE:
        return SLUG_CACHE[machine_name]

    # Fallback to heuristic (lowercase, replace spaces/parens)
    slug = machine_name.lower().replace(' ', '_').replace('(', '').replace(')', '')
    return slug


def load_master_source_urls(path: Path = CSV_PATH) -> dict[str, str]:
    """Read selected source URLs directly from the canonical machine master."""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = csv.DictReader(handle)
        return {
            row["machine_name"].strip(): row["source_url"].strip()
            for row in rows
            if row.get("source_status") == "selected" and row.get("source_url", "").strip()
        }


def resolve_1geki_url(machine_name: str, source_urls: dict[str, str] | None = None) -> str:
    if source_urls and machine_name in source_urls:
        return source_urls[machine_name]
    slug = get_1geki_slug(machine_name)
    return f"https://1geki.jp/slot/{slug}/" if slug else ""


def curl_1geki_page(machine_name: str, url: str = "") -> Optional[tuple[str, str]]:
    """Fetch one 1geki page and return its resolved URL and HTML."""
    target_url = url or resolve_1geki_url(machine_name)
    if not target_url:
        return None, None

    try:
        result = subprocess.run(
            ['curl', '-sS', '-L', '-A', 'Mozilla/5.0', '--max-time', '30', target_url],
            capture_output=True,
            timeout=35,
        )
        if result.returncode == 0 and result.stdout:
            charset_match = re.search(
                rb"charset\s*=\s*['\"]?([A-Za-z0-9._-]+)",
                result.stdout[:20000],
                flags=re.IGNORECASE,
            )
            encoding = charset_match.group(1).decode("ascii", errors="ignore") if charset_match else "utf-8"
            try:
                html = result.stdout.decode(encoding)
            except LookupError, UnicodeDecodeError:
                html = result.stdout.decode("utf-8", errors="replace")
            return target_url, html
    except Exception as e:
        print(f"    curl failed: {e}")
    return None, None


def extract_tables_from_html(html: str) -> list[str]:
    """Extract all <table>...</table> blocks from HTML."""
    pattern = r'<table[^>]*>.*?</table>'
    matches = re.findall(pattern, html, re.DOTALL)
    return matches


def _normalize_label(value: str) -> str:
    return re.sub(r"\s+", "", value).replace("（", "(").replace("）", ")")


def _identity_cores(value: str) -> set[str]:
    if not value:
        return set()
    normalized = unicodedata.normalize("NFKC", value).casefold()
    parts = re.split(r"[|｜:：]", normalized)
    cores = set()
    for part in parts:
        part = re.sub(r"解析(?:攻略|情報サイト)?.*$", "", part)
        part = re.sub(r"[（(][^）)]*[）)]", "", part)
        part = re.sub(r"(?:スロット[/／])?スマスロ$", "", part)
        part = re.sub(r"^(?:(?:パチスロ|スマスロ|lb?|slot)\s*)+", "", part, flags=re.IGNORECASE)
        part = re.sub(r"(?:btc?9|cf|xf|tp)$", "", part, flags=re.IGNORECASE)
        core = re.sub(r"[^\w]+", "", part, flags=re.UNICODE)
        if len(core) >= 2:
            cores.add(core)
    return cores


def identity_matches(machine_name: str, row: list[str], result: dict) -> tuple[bool, str]:
    """Conservatively reject URL-map collisions before overwriting master data."""

    existing_release = (row[2] or "").strip()
    source_release = str(result.get("release_date") or "").strip()
    release_mismatch = bool(
        re.fullmatch(r"\d{4}-\d{2}(?:-\d{2})?", existing_release)
        and source_release
        and existing_release[:7] != source_release[:7]
    )
    release_month_matches = bool(existing_release and source_release and existing_release[:7] == source_release[:7])

    target_cores = _identity_cores(machine_name)
    for alias in IDENTITY_ALIASES.get(machine_name, []):
        target_cores.update(_identity_cores(alias))
    source_texts = [str(value).strip() for value in result.get("identity_names", []) if str(value).strip()]
    if not source_texts:
        source_texts = [
            str(result.get(key) or "").strip()
            for key in ("official_name", "page_title")
            if str(result.get(key) or "").strip()
        ]
    target_is_smart = bool(re.search(r"スマ(?:スロ|ートスロット|ート沖スロ)", machine_name))
    source_platform_text = " ".join(source_texts + [str(result.get("source_machine_type") or "")])
    source_is_smart = bool(re.search(r"スマ(?:スロ|ートスロット|ート沖スロ)", source_platform_text))
    legacy_notes = row[22] if len(row) > 22 else ""
    legacy_row = bool(
        not existing_release
        and "スマスロ" not in (row[3] if len(row) > 3 else "")
        and re.search(r"過去機種|[45]号機|データ割愛", legacy_notes)
    )
    if legacy_row:
        return False, "legacy_row_requires_manual_source"
    if target_is_smart and not source_is_smart and not release_month_matches:
        return False, "platform_mismatch:target_smart_source_unspecified"
    source_cores = set().union(*(_identity_cores(text) for text in source_texts))
    if not target_cores or not source_cores:
        return False, "identity_text_missing"
    if target_cores & source_cores:
        reason = "exact_identity_release_correction" if release_mismatch else "exact_identity"
        return True, reason

    if release_mismatch:
        return False, f"release_mismatch:{existing_release}!={source_release}"

    best_ratio = max(
        SequenceMatcher(None, target, source).ratio() for target in target_cores for source in source_cores
    )
    target_digits = {digit for target in target_cores for digit in re.findall(r"\d+", target)}
    source_digits = {digit for source in source_cores for digit in re.findall(r"\d+", source)}
    digits_compatible = not target_digits or not source_digits or bool(target_digits & source_digits)
    if (
        release_month_matches
        and digits_compatible
        and any(target in source or source in target for target in target_cores for source in source_cores)
    ):
        return True, "contained_identity"
    if best_ratio >= 0.88 and digits_compatible:
        return True, f"fuzzy_identity:{best_ratio:.3f}"
    # A matching published introduction month is strong independent evidence
    # for aliases such as LB-prefixed model names. Keep a modest name-similarity
    # floor and digit compatibility so similarly dated sequels are not accepted.
    if release_month_matches and best_ratio >= 0.30 and digits_compatible:
        return True, f"release_and_name:{best_ratio:.3f}"
    existing_maker = _identity_cores(row[1] if len(row) > 1 else "")
    source_maker = _identity_cores(str(result.get("manufacturer") or ""))
    exact_release_matches = bool(existing_release and source_release and existing_release == source_release)
    if exact_release_matches and existing_maker & source_maker and digits_compatible:
        return True, "release_and_manufacturer"
    return False, f"name_mismatch:{best_ratio:.3f}"


def _parse_release_date(value: str) -> Optional[str]:
    match = re.search(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", value)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    return f"{year:04d}-{month:02d}-{day:02d}"


def _metric_key(header: str) -> Optional[str]:
    normalized = _normalize_label(header).upper()
    if re.search(r"出玉率|機械割|RTP|^PAY$", normalized):
        return "rtp"
    if re.search(r"(?:^|[^A-Z])(?:BB|BIG)(?:[^A-Z]|$)", normalized):
        return "bb"
    if re.search(r"(?:^|[^A-Z])(?:RB|REG)(?:[^A-Z]|$)", normalized):
        return "rb"
    if re.search(r"(?:ボーナス|BONUS)初当", normalized):
        return "bonus_initial"
    if re.search(r"AT(?:初当|確率)", normalized):
        return "at_initial"
    if ("ボーナス" in normalized or "BONUS" in normalized) and "AT" in normalized and "合算" in normalized:
        return "combined_initial"
    if normalized == "初当り合算" or normalized == "初当たり合算":
        return "combined_initial"
    if "ボーナス合算" in normalized:
        return "bonus_combined"
    return None


def extract_specs_from_html(machine_name: str, html: str, source_url: str = "") -> dict:
    """Extract setting-keyed specs and metadata from 1geki HTML tables.

    Published setting numbers are used as keys.  This is essential for
    four-setting machines such as 1/2/5/6; positional assignment is invalid.
    Generic bonus columns are kept separate from explicit BB/RB columns.
    """

    soup = BeautifulSoup(html, "html.parser")
    result: dict = {"name": machine_name}
    title_node = soup.find("title") or soup.find("h1")
    if title_node:
        result["page_title"] = title_node.get_text(" ", strip=True)
    identity_names: list[str] = []
    for selector in ("title", "h1", "caption"):
        identity_names.extend(
            node.get_text(" ", strip=True) for node in soup.find_all(selector) if node.get_text(" ", strip=True)
        )
    for meta_selector in (
        {"property": "og:title"},
        {"name": "twitter:title"},
    ):
        node = soup.find("meta", attrs=meta_selector)
        if node and node.get("content"):
            identity_names.append(str(node["content"]).strip())
    for node in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            payload = json.loads(node.string or node.get_text())
        except TypeError, json.JSONDecodeError:
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("name"):
                identity_names.append(str(candidate["name"]).strip())
    if identity_names:
        result["identity_names"] = list(dict.fromkeys(identity_names))
    if source_url:
        result["source_url"] = source_url

    for table in soup.find_all("table"):
        for table_row in table.find_all("tr"):
            cells = table_row.find_all(["th", "td"], recursive=False)
            if len(cells) != 2:
                continue
            label = _normalize_label(cells[0].get_text(" ", strip=True))
            value = cells[1].get_text(" ", strip=True)
            if label == "メーカー" and value:
                result["manufacturer"] = value
            elif label in {"導入開始日", "導入日"}:
                release_date = _parse_release_date(value)
                if release_date:
                    result["release_date"] = release_date
            elif label in {"タイプ", "スペック"} and value:
                result["source_machine_type"] = value
                normalized_type = normalize_machine_type(value)
                if normalized_type:
                    result["machine_type"] = normalized_type
            elif label == "正式名称" and value:
                result["official_name"] = value
                if value not in result.setdefault("identity_names", []):
                    result["identity_names"].append(value)

        header_row = None
        if table.thead:
            candidate_rows = table.thead.find_all("tr")
            if candidate_rows:
                header_row = candidate_rows[-1]
        if header_row is None:
            for candidate_row in table.find_all("tr"):
                candidate_headers = [
                    cell.get_text(" ", strip=True) for cell in candidate_row.find_all(["th", "td"], recursive=False)
                ]
                if any(_metric_key(header) for header in candidate_headers):
                    header_row = candidate_row
                    break
        if header_row is None:
            continue

        headers = [cell.get_text(" ", strip=True) for cell in header_row.find_all(["th", "td"], recursive=False)]
        normalized_headers = [_normalize_label(header).upper() for header in headers]
        if any(re.search(r"AT(?:初当|確率)", header) or header == "初当り合算" for header in normalized_headers):
            page_identity = " ".join(result.get("identity_names", []))
            result["machine_type"] = "スマスロ / AT" if "スマスロ" in page_identity else "AT"
        metric_columns = {}
        rtp_column_seen = False
        for index, header in enumerate(headers):
            metric = _metric_key(header)
            if not metric:
                continue
            if metric == "rtp":
                if rtp_column_seen:
                    metric = "rtp_complete"
                rtp_column_seen = True
            metric_columns[index] = metric
        if not metric_columns:
            continue

        body_rows = table.tbody.find_all("tr") if table.tbody else table.find_all("tr")
        for table_row in body_rows:
            if table_row is header_row:
                continue
            cells = table_row.find_all(["th", "td"], recursive=False)
            if not cells:
                continue
            setting_text = _normalize_label(cells[0].get_text(" ", strip=True))
            is_special_setting = setting_text.upper() == "V"
            if not re.fullmatch(r"[1-6]", setting_text) and not is_special_setting:
                continue
            setting = int(setting_text) if not is_special_setting else None
            for column_index, metric in metric_columns.items():
                if column_index >= len(cells):
                    cell_text = ""
                else:
                    cell_text = cells[column_index].get_text(" ", strip=True)
                if metric in {"rtp", "rtp_complete"}:
                    percentage = re.search(r"(\d{2,3}(?:\.\d+)?)\s*%", cell_text)
                    if metric == "rtp" and not percentage:
                        for cell in reversed(cells[1:]):
                            percentage = re.search(
                                r"(\d{2,3}(?:\.\d+)?)\s*%",
                                cell.get_text(" ", strip=True),
                            )
                            if percentage:
                                break
                    if percentage:
                        if is_special_setting:
                            result.setdefault("special_settings", {}).setdefault("V", {})[metric] = percentage.group(1)
                        else:
                            result[f"{metric}{setting}"] = percentage.group(1)
                            published_key = (
                                "published_rtp_settings" if metric == "rtp" else "published_rtp_complete_settings"
                            )
                            published_settings = result.setdefault(published_key, [])
                            if setting not in published_settings:
                                published_settings.append(setting)
                        if metric == "rtp" and "完全攻略" in normalized_headers[column_index]:
                            percentages = re.findall(r"(\d{2,3}(?:\.\d+)?)\s*%", cell_text)
                            if len(percentages) >= 2 and not is_special_setting:
                                result[f"rtp_complete{setting}"] = percentages[1]
                                complete_settings = result.setdefault("published_rtp_complete_settings", [])
                                if setting not in complete_settings:
                                    complete_settings.append(setting)
                else:
                    probability = re.search(r"1\s*[/／]\s*(\d+(?:\.\d+)?)", cell_text)
                    if probability:
                        value = f"1/{probability.group(1)}"
                        if is_special_setting:
                            result.setdefault("special_settings", {}).setdefault("V", {})[metric] = value
                        else:
                            result[f"{metric}{setting}"] = value
                            published_settings = result.setdefault(f"published_{metric}_settings", [])
                            if setting not in published_settings:
                                published_settings.append(setting)

    return result


LLM_SYSTEM_PROMPT = """You are a Japanese pachislot data extraction expert.
Given specification tables from 1geki.jp, extract only source-supported data.
Return a JSON array with one object per machine, containing:
- name, manufacturer, release_date (YYYY-MM-DD), machine_type
- rtp1..rtp6, bb1..bb6, rb1..rb6
- at_initial1..at_initial6, bonus_initial1..bonus_initial6,
  bonus_combined1..bonus_combined6, and combined_initial1..combined_initial6
- rtp_complete1..rtp_complete6 for complete-strategy payout
- published_*_settings for every returned metric

machine_type must retain both the platform and game system when published, for
example "スマスロ / AT" or "スマスロ / ノーマル / BT". Map every numeric
value by the printed setting number, never by position. Do not put generic AT
initial-hit probabilities or generic ボーナス初当たり/合算 into BB/RB. A
four-setting 1/2/5/6 machine must leave settings 3 and 4 null. Do not infer a
value from prose if a table does not identify its metric. Use null when unclear.
Return only valid JSON, without markdown."""


def format_batch_for_llm(machines_with_html: list[dict]) -> str:
    """Format a batch of machines, requested fields, and tables for an LLM."""
    prompt_parts = []
    for item in machines_with_html:
        fields = ", ".join(item.get("unresolved_fields", [])) or "none"
        prompt_parts.append(
            f"\n【{item['name']}】\nsource_url: {item.get('source_url', '')}\nunresolved_fields: {fields}\n"
        )
        prompt_parts.append(item['html_snippet'])
    return "".join(prompt_parts)


def query_llm_for_specs(batch_prompt: str, model: str = "claude-opus-4-8") -> Optional[str]:
    """Send an HTML batch to Claude and return the JSON response."""
    try:
        import anthropic
    except ImportError as exc:
        print(f"  ✗ LLM query unavailable: {exc}")
        return None

    client = anthropic.Anthropic()

    try:
        message = client.messages.create(
            model=model, max_tokens=4000, system=LLM_SYSTEM_PROMPT, messages=[{"role": "user", "content": batch_prompt}]
        )
        return message.content[0].text
    except Exception as e:
        print(f"  ✗ LLM query failed: {e}")
        return None


def write_llm_batch(path: Path, requests: list[dict]) -> None:
    """Write a portable LLM extraction package without requiring an API key."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "system_prompt": LLM_SYSTEM_PROMPT,
        "requests": requests,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_rtp_value(s: str) -> Optional[float]:
    """Parse RTP string like '97.3%' or '97.3' to float."""
    if not s:
        return None
    s = str(s).replace('%', '').strip()
    try:
        value = float(s)
        if 80.0 <= value <= 130.0:
            return value
        return None
    except:
        return None


def parse_probability(s: str) -> Optional[str]:
    """Parse a probability and reject labels or malformed cell fragments."""
    if not s:
        return None
    value = str(s).strip().replace('／', '/')
    match = re.fullmatch(r'1\s*/\s*(\d+(?:\.\d+)?)', value)
    if not match:
        return None
    return f"1/{match.group(1)}"


def _format_generic_bonus_note(result: dict) -> str:
    """Format generic bonus metrics for notes without pretending they are BB/RB."""

    parts = []
    for key_prefix, label in (
        ('bonus_initial', 'ボーナス初当り'),
        ('bonus_combined', 'ボーナス合算'),
    ):
        values = []
        for setting in range(1, 7):
            value = parse_probability(result.get(f'{key_prefix}{setting}'))
            if value:
                values.append(f'設定{setting}={value}')
        if values:
            parts.append(f"{label}は{'/'.join(values)}")
    complete_values = []
    for setting in range(1, 7):
        value = parse_rtp_value(result.get(f'rtp_complete{setting}'))
        if value is not None:
            complete_values.append(f'設定{setting}={value}%')
    if complete_values:
        parts.append(f"完全攻略時出玉率は{'/'.join(complete_values)}")
    return '、'.join(parts)


def _format_special_settings_note(result: dict) -> str:
    labels = {
        "rtp": "出玉率",
        "rtp_complete": "完全攻略時出玉率",
        "bb": "BB",
        "rb": "RB",
        "bonus_initial": "ボーナス初当り",
        "bonus_combined": "ボーナス合算",
    }
    notes = []
    for setting_label, metrics in result.get("special_settings", {}).items():
        values = [f"{labels.get(metric, metric)}={value}" for metric, value in metrics.items() if value]
        if values:
            notes.append(f"設定{setting_label}:{'/'.join(values)}")
    return "、".join(notes)


def update_csv_with_results(rows, header, results: list[dict], *, overwrite_existing: bool = False):
    """Update CSV rows with extracted RTP/BB/RB data."""
    updated_count = 0
    for result in results:
        machine_name = result.get('name')
        if not machine_name:
            continue

        # Find matching row
        for row in rows:
            if row[0].strip().lower() == machine_name.lower():
                column_index = {column: index for index, column in enumerate(header)}

                for result_key, column in (
                    ('manufacturer', 'manufacturer'),
                    ('release_date', 'release_date'),
                    ('machine_type', 'machine_type'),
                ):
                    value = str(result.get(result_key) or '').strip()
                    if result_key == 'machine_type':
                        value = normalize_machine_type(value)
                        target_is_smart = bool(re.search(r"スマ(?:スロ|ートスロット|ート沖スロ)", machine_name))
                        if target_is_smart and value and "スマスロ" not in value:
                            value = f"スマスロ / {value}"
                    target_index = column_index[column]
                    replace_generic_type = column == 'machine_type' and row[target_index].strip() in {
                        'スマスロ',
                        'スマートスロット',
                    }
                    if value and (overwrite_existing or not row[target_index] or replace_generic_type):
                        row[target_index] = value

                published_rtp_settings = result.get('published_rtp_settings')
                if overwrite_existing and isinstance(published_rtp_settings, list):
                    published_set = {int(setting) for setting in published_rtp_settings}
                    for setting in range(1, 7):
                        if setting not in published_set:
                            row[column_index[f'rtp_setting{setting}']] = ''

                for metric in ('bb', 'rb'):
                    published_metric_settings = result.get(f'published_{metric}_settings')
                    if overwrite_existing and isinstance(published_metric_settings, list):
                        published_set = {int(setting) for setting in published_metric_settings}
                        for setting in range(1, 7):
                            if setting not in published_set:
                                row[column_index[f'{metric}_setting{setting}']] = ''

                for setting in range(1, 7):
                    rtp = parse_rtp_value(result.get(f'rtp{setting}'))
                    rtp_index = column_index[f'rtp_setting{setting}']
                    if rtp is not None and (overwrite_existing or not row[rtp_index]):
                        row[rtp_index] = str(rtp)

                    bb = parse_probability(result.get(f'bb{setting}'))
                    bb_index = column_index[f'bb_setting{setting}']
                    if bb is not None and (overwrite_existing or not row[bb_index]):
                        row[bb_index] = bb

                    rb = parse_probability(result.get(f'rb{setting}'))
                    rb_index = column_index[f'rb_setting{setting}']
                    if rb is not None and (overwrite_existing or not row[rb_index]):
                        row[rb_index] = rb

                    for metric in STRUCTURED_PROBABILITY_METRICS:
                        column = f"{metric}_setting{setting}"
                        if column not in column_index:
                            continue
                        value = parse_probability(result.get(f"{metric}{setting}"))
                        target_index = column_index[column]
                        if value is not None and (overwrite_existing or not row[target_index]):
                            row[target_index] = value

                    complete_column = f"rtp_complete_setting{setting}"
                    if complete_column in column_index:
                        value = parse_rtp_value(result.get(f"rtp_complete{setting}"))
                        target_index = column_index[complete_column]
                        if value is not None and (overwrite_existing or not row[target_index]):
                            row[target_index] = str(value)

                generic_bonus_note = _format_generic_bonus_note(result)
                notes_index = column_index['notes']
                has_structured_generic_columns = "bonus_initial_setting1" in column_index
                if (
                    generic_bonus_note
                    and not has_structured_generic_columns
                    and generic_bonus_note not in row[notes_index]
                ):
                    separator = '、' if row[notes_index].strip() else ''
                    row[notes_index] = f"{row[notes_index]}{separator}{generic_bonus_note}"

                special_settings_note = _format_special_settings_note(result)
                if special_settings_note and special_settings_note not in row[notes_index]:
                    separator = '、' if row[notes_index].strip() else ''
                    row[notes_index] = f"{row[notes_index]}{separator}{special_settings_note}"

                has_generic_bonus = any(
                    result.get(f"{prefix}{setting}")
                    for prefix in ("bonus_initial", "bonus_combined")
                    for setting in range(1, 7)
                )
                no_bb = not result.get("published_bb_settings")
                no_rb = not result.get("published_rb_settings")
                source_type = normalize_machine_type(str(result.get("source_machine_type") or ""))
                if overwrite_existing and has_generic_bonus and "ノーマル" in source_type:
                    if no_bb and no_rb:
                        absence_notes = ["一撃掲載表にBB/RB個別確率なし"]
                    elif no_bb:
                        absence_notes = ["一撃掲載表にBB個別確率なし"]
                    elif no_rb:
                        absence_notes = ["一撃掲載表にRB個別確率なし"]
                    else:
                        absence_notes = []
                    for absence_note in absence_notes:
                        if absence_note not in row[notes_index]:
                            separator = '、' if row[notes_index].strip() else ''
                            row[notes_index] = f"{row[notes_index]}{separator}{absence_note}"

                source_url = str(result.get('source_url') or '').strip()
                if source_url and 'source_url' in column_index:
                    row[column_index['source_url']] = source_url
                    if 'source_status' in column_index:
                        row[column_index['source_status']] = 'selected'

                if "canonical_machine_name" in column_index and not row[column_index["canonical_machine_name"]].strip():
                    row[column_index["canonical_machine_name"]] = machine_name
                if "manufacturer_canonical" in column_index:
                    maker = row[column_index["manufacturer"]]
                    row[column_index["manufacturer_canonical"]] = canonical_manufacturer(maker)
                if all(column in column_index for column in ("cabinet_type", "game_type", "bt_flag")):
                    machine_type = row[column_index["machine_type"]]
                    cabinet, game_type, bt_flag = split_machine_type(machine_type)
                    row[column_index["cabinet_type"]] = cabinet
                    row[column_index["game_type"]] = game_type
                    row[column_index["bt_flag"]] = bt_flag
                if "source_title" in column_index:
                    row[column_index["source_title"]] = str(result.get("page_title") or "").strip()
                if "source_checked_at" in column_index:
                    row[column_index["source_checked_at"]] = date.today().isoformat()

                updated_count += 1
                break

    return updated_count


def validate_master(header: list[str], rows: list[list[str]]) -> list[str]:
    """Validate the artifact contract before replacing the research CSV."""

    errors: list[str] = []
    expected_columns = len(header)
    names: set[str] = set()
    column_index = {column: index for index, column in enumerate(header)}
    required = {
        "machine_name",
        "manufacturer",
        "release_date",
        "machine_type",
        "notes",
        "source_url",
        "source_status",
        "source_confidence",
        "source_query",
        "source_candidate_count",
        "source_reason",
        *(f"rtp_setting{setting}" for setting in range(1, 7)),
        *(f"bb_setting{setting}" for setting in range(1, 7)),
        *(f"rb_setting{setting}" for setting in range(1, 7)),
        "canonical_machine_name",
        "manufacturer_canonical",
        "cabinet_type",
        "game_type",
        "bt_flag",
        *(f"{metric}_setting{setting}" for metric in STRUCTURED_PROBABILITY_METRICS for setting in range(1, 7)),
        *(f"rtp_complete_setting{setting}" for setting in range(1, 7)),
        "source_title",
        "source_checked_at",
    }
    missing_columns = sorted(required - set(header))
    if missing_columns:
        errors.append(f"missing_columns:{','.join(missing_columns)}")
        return errors

    for row_number, row in enumerate(rows, 2):
        if len(row) != expected_columns:
            errors.append(f"row_{row_number}:column_count:{len(row)}!={expected_columns}")
            continue
        name = row[column_index["machine_name"]].strip()
        if not name:
            errors.append(f"row_{row_number}:empty_machine_name")
        elif name in names:
            errors.append(f"row_{row_number}:duplicate_machine_name:{name}")
        names.add(name)

        release_date = row[column_index["release_date"]].strip()
        if release_date and not re.fullmatch(r"\d{4}-\d{2}(?:-\d{2})?", release_date):
            errors.append(f"row_{row_number}:invalid_release_date:{release_date}")
        for setting in range(1, 7):
            rtp = row[column_index[f"rtp_setting{setting}"]].strip()
            if rtp and parse_rtp_value(rtp) is None:
                errors.append(f"row_{row_number}:invalid_rtp{setting}:{rtp}")
            for metric in ("bb", "rb"):
                probability = row[column_index[f"{metric}_setting{setting}"]].strip()
                if probability and parse_probability(probability) is None:
                    errors.append(f"row_{row_number}:invalid_{metric}{setting}:{probability}")
            for metric in STRUCTURED_PROBABILITY_METRICS:
                probability = row[column_index[f"{metric}_setting{setting}"]].strip()
                if probability and parse_probability(probability) is None:
                    errors.append(f"row_{row_number}:invalid_{metric}{setting}:{probability}")
            complete_rtp = row[column_index[f"rtp_complete_setting{setting}"]].strip()
            if complete_rtp and parse_rtp_value(complete_rtp) is None:
                errors.append(f"row_{row_number}:invalid_rtp_complete{setting}:{complete_rtp}")
        canonical_name = row[column_index["canonical_machine_name"]].strip()
        if not canonical_name:
            errors.append(f"row_{row_number}:empty_canonical_machine_name")
        if row[column_index["bt_flag"]].strip() not in {"0", "1"}:
            errors.append(f"row_{row_number}:invalid_bt_flag")
    return errors


def _write_csv_atomic(path: Path, header: list[str], rows: list[list[str]]) -> None:
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
        csv.writer(handle).writerows([header] + rows)
    temp_path.replace(path)


def refresh_master_source_urls(*, refresh_index: bool = False) -> dict[str, object]:
    """Refresh source URLs in the canonical machine master."""

    try:
        from scraper.machine_master_research_url_mapper import build_url_map
    except ModuleNotFoundError:
        from machine_master_research_url_mapper import build_url_map

    return build_url_map(
        input_path=CSV_PATH,
        page_index_path=CSV_PATH.parent / "1geki_slot_page_index.json",
        refresh_index=refresh_index,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Refresh machine specs from mapped 1geki pages")
    parser.add_argument("--limit", type=int, default=0, help="0 processes every selected row")
    parser.add_argument(
        "--machine",
        action="append",
        default=[],
        help="Process an exact machine name; repeat for multiple names (overrides --scope)",
    )
    parser.add_argument(
        "--scope",
        choices=("unresolved", "rtp", "all"),
        default="unresolved",
        help="Fields used to select target rows (default: unresolved metadata/specs)",
    )
    parser.add_argument(
        "--llm-mode",
        choices=("batch", "anthropic", "off"),
        default="batch",
        help="Export unresolved tables by default; anthropic calls the API directly",
    )
    parser.add_argument(
        "--with-llm",
        action="store_true",
        help="Backward-compatible alias for --llm-mode anthropic",
    )
    parser.add_argument("--llm-batch", type=Path, default=DEFAULT_LLM_BATCH_PATH)
    parser.add_argument("--model", default="claude-opus-4-8")
    parser.add_argument(
        "--refresh-source-urls",
        "--refresh-url-map",
        dest="refresh_source_urls",
        action="store_true",
        help="Refresh source URLs and resolution provenance in the master",
    )
    parser.add_argument(
        "--refresh-page-index",
        action="store_true",
        help="Re-download the 1geki sitemap/page index (implies --refresh-source-urls)",
    )
    parser.add_argument(
        "--allow-url-fallback",
        action="store_true",
        help="Allow heuristic slugs for rows absent from the master source URL",
    )
    parser.add_argument("--dry-run", action="store_true", help="Fetch and report without writing the CSV")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.with_llm:
        args.llm_mode = "anthropic"
    print("[Machine Master] Resolving and scraping mapped 1geki pages...\n")

    source_url_refresh_summary: dict[str, object] | None = None
    if args.refresh_source_urls or args.refresh_page_index:
        print("[Machine Master] Refreshing master source URLs...")
        source_url_refresh_summary = refresh_master_source_urls(refresh_index=args.refresh_page_index)
        print(json.dumps(source_url_refresh_summary, ensure_ascii=False))

    header, rows = read_csv()
    before_rows = [row.copy() for row in rows]
    if args.machine:
        requested_names = set(args.machine)
        targets = [(index, row) for index, row in enumerate(rows, 1) if row[0].strip() in requested_names]
        missing_names = sorted(requested_names - {row[0].strip() for _, row in targets})
        if missing_names:
            print(f"[Machine Master] Unknown --machine names: {', '.join(missing_names)}")
            return 2
    elif args.scope == "rtp":
        targets = identify_missing_rtp(header, rows)
    elif args.scope == "all":
        targets = list(enumerate(rows, 1))
    else:
        targets = identify_incomplete_rows(header, rows)
    if args.limit > 0:
        targets = targets[: args.limit]
    source_urls = load_master_source_urls()

    print(f"[Machine Master] Processing {len(targets)} machines (scope={args.scope})")
    print(f"[Machine Master] Loaded {len(source_urls)} selected source URLs from the master")
    if not targets:
        print("[Machine Master] No unresolved rows")
        return 0

    total_updated = 0
    fetched = 0
    parsed_specs = 0
    failures: list[dict[str, str]] = []
    llm_requests: list[dict] = []
    llm_updated_rows = 0
    for batch_start in range(0, len(targets), BATCH_SIZE):
        batch = targets[batch_start : batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        print(f"\n[Batch {batch_num}] ({len(batch)} machines)")

        machines_with_html = []
        deterministic_results = []
        for row_idx, row in batch:
            machine_name = row[0].strip()
            mapped_url = source_urls.get(machine_name, "")
            if mapped_url:
                target_url = mapped_url
            elif args.allow_url_fallback:
                target_url = resolve_1geki_url(machine_name)
            else:
                target_url = ""

            print(f"  {machine_name}...", end=" ")
            if not target_url:
                print("SKIP (unmapped)")
                failures.append({"machine_name": machine_name, "url": "", "reason": "unmapped"})
                continue
            source_url, html = curl_1geki_page(machine_name, target_url)

            if html:
                fetched += 1
                tables = extract_tables_from_html(html)
                if tables:
                    print(f"OK ({len(tables)} tables)")
                    result = extract_specs_from_html(machine_name, html, source_url=source_url)
                    identity_ok, identity_reason = identity_matches(machine_name, row, result)
                    if not identity_ok:
                        failures.append(
                            {
                                "machine_name": machine_name,
                                "url": source_url,
                                "reason": f"identity_rejected:{identity_reason}",
                            }
                        )
                        print(f"    REJECT ({identity_reason})")
                        continue
                    if result.get("published_rtp_settings"):
                        parsed_specs += 1
                    else:
                        failures.append({"machine_name": machine_name, "url": source_url, "reason": "no_rtp_table"})
                    deterministic_results.append(result)
                    machines_with_html.append(
                        {
                            'name': machine_name,
                            'html_snippet': ''.join(tables),
                            'row_idx': row_idx,
                            'source_url': source_url,
                        }
                    )
                else:
                    print("SKIP (no tables)")
                    failures.append({"machine_name": machine_name, "url": source_url, "reason": "no_tables"})
            else:
                print("FAIL (curl error)")
                failures.append({"machine_name": machine_name, "url": target_url, "reason": "fetch_failed"})

        if not machines_with_html:
            print("  WARNING: No accepted pages in this batch")
            continue

        deterministic_updated = update_csv_with_results(
            rows,
            header,
            deterministic_results,
            overwrite_existing=True,
        )
        total_updated += deterministic_updated
        print(f"  Parsed deterministic tables for {deterministic_updated} machines")

        row_by_name = {row[0].strip(): row for row in rows}
        pending_requests = []
        for item in machines_with_html:
            updated_row = row_by_name[item["name"]]
            item["unresolved_fields"] = find_unresolved_fields(header, updated_row)
            if item["unresolved_fields"]:
                pending_requests.append(item)
                if args.llm_mode != "off":
                    llm_requests.append(item.copy())

        if args.llm_mode != "anthropic" or not pending_requests:
            continue

        print(f"\n  Querying LLM for {len(pending_requests)} unresolved machines...")
        batch_prompt = format_batch_for_llm(pending_requests)
        response = query_llm_for_specs(batch_prompt, model=args.model)
        if response:
            try:
                results = json.loads(response)
                if not isinstance(results, list):
                    raise ValueError("LLM response must be a JSON array")
                request_by_name = {item["name"]: item for item in pending_requests}
                accepted_results = []
                for result in results:
                    if not isinstance(result, dict) or result.get("name") not in request_by_name:
                        continue
                    item = request_by_name[result["name"]]
                    result["source_url"] = item["source_url"]
                    accepted_results.append(result)
                updated = update_csv_with_results(rows, header, accepted_results)
                total_updated += updated
                llm_updated_rows += updated
                print(f"  DONE: Updated {updated} machines")
            except (json.JSONDecodeError, ValueError) as e:
                print(f"  ERROR: Failed to parse LLM response: {e}")
                print(f"  Response: {response[:200]}")
        else:
            print("  ERROR: LLM query failed")

    if args.llm_mode == "batch":
        write_llm_batch(args.llm_batch, llm_requests)
        print(f"\n[Machine Master] Wrote {len(llm_requests)} unresolved LLM requests: {args.llm_batch}")

    changes = []
    for before, after in zip(before_rows, rows):
        field_changes = {
            column: {"before": before[index], "after": after[index]}
            for index, column in enumerate(header)
            if before[index] != after[index]
        }
        if field_changes:
            changes.append({"machine_name": after[0], "changes": field_changes})

    report = {
        "scope": args.scope,
        "llm_mode": args.llm_mode,
        "target_rows": len(targets),
        "fetched_rows": fetched,
        "parsed_rtp_rows": parsed_specs,
        "llm_request_rows": len(llm_requests),
        "llm_updated_rows": llm_updated_rows,
        "changed_rows": len(changes),
        "changed_fields": sum(len(item["changes"]) for item in changes),
        "source_url_refresh": source_url_refresh_summary,
        "failures": failures,
        "changes": changes,
    }
    validation_errors = validate_master(header, rows)
    report["validation_errors"] = validation_errors
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.dry_run:
        print(f"\n[Machine Master] Dry run; CSV not written. Report: {args.report}")
    elif validation_errors:
        print(f"\n[Machine Master] Validation failed; CSV not written. Report: {args.report}")
        for error in validation_errors[:20]:
            print(f"  - {error}")
        return 2
    else:
        _write_csv_atomic(CSV_PATH, header, rows)
        print(f"\n[Machine Master] Wrote {len(changes)} changed rows atomically")
    print(
        json.dumps(
            {key: value for key, value in report.items() if key not in {"changes", "failures"}}, ensure_ascii=False
        )
    )
    print(f"[Machine Master] Failures: {len(failures)}; report: {args.report}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
