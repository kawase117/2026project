#!/usr/bin/env python3
"""Repair known machine-name aliases and verified 1geki URL mismatches."""

from __future__ import annotations

import argparse
import csv
import re
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MASTER = REPO_ROOT / "document" / "machine_master_research" / "machine_master.csv"
CANONICAL_NOTE_PREFIX = "正規名:"

CANONICAL_NAMES = {
    "/いざ番長/SB8": "いざ！番長",
    "いざ!番長": "いざ！番長",
    "いざ!番長(スマスロ)": "いざ！番長",
    "/ギルティクラウン2/XF": "スマスロ ギルティクラウン2",
    "ギルティクラウン2": "スマスロ ギルティクラウン2",
    "LB SHAKE BONUS TRIGGER": "SHAKE BONUS TRIGGER",
    "SHAKE BONUS TRIGGER(スマスロ)": "SHAKE BONUS TRIGGER",
    "LBニューパルサー": "ニューパルサーBT",
    "LBニューパルサーBTC9": "ニューパルサーBT",
    "スマスロニューパルサーBT": "ニューパルサーBT",
    "LB翔べ!ハーレムエースCF": "翔べ！ハーレムエース",
    "翔べ!ハーレムエース": "翔べ！ハーレムエース",
    "翔べ!ハーレムエース(スマスロ)": "翔べ！ハーレムエース",
    "Sister Quest(シスタークエスト)": "Sister Quest",
    "Sister Quest(スマスロ)": "Sister Quest",
    "少女☆歌劇 レヴュースタァライト ‐The SLOT‐(スマスロ)": "少女☆歌劇 レヴュースタァライト ‐The SLOT‐",
    "少女☆歌劇レヴュースタァライト": "少女☆歌劇 レヴュースタァライト ‐The SLOT‐",
    "回胴黙示録カイジ 狂宴(スマスロ)": "回胴黙示録カイジ 狂宴",
    "荒野のコトブキ飛行隊(スマスロ)": "荒野のコトブキ飛行隊",
    "バイオハザード5": "スマスロ バイオハザード5",
    "パチスロULTRAMAN-KE": "ULTRAMAN(スマスロ)",
    "吉宗(スマスロ)": "吉宗",
}

SETTING_METRICS = (
    "at_initial",
    "bonus_initial",
    "bonus_combined",
    "combined_initial",
    "rtp_complete",
)

BASE_COLUMNS = [
    "machine_name",
    "manufacturer",
    "release_date",
    "machine_type",
    *(f"rtp_setting{setting}" for setting in range(1, 7)),
    *(f"bb_setting{setting}" for setting in range(1, 7)),
    *(f"rb_setting{setting}" for setting in range(1, 7)),
    "notes",
    "source_url",
    "source_status",
    "source_confidence",
    "source_query",
    "source_candidate_count",
    "source_reason",
]

EXTRA_COLUMNS = [
    "canonical_machine_name",
    "manufacturer_canonical",
    "cabinet_type",
    "game_type",
    "bt_flag",
    *(f"{metric}_setting{setting}" for metric in SETTING_METRICS for setting in range(1, 7)),
    "source_title",
    "source_checked_at",
]

VERIFIED_SOURCE_URLS = {
    "頭文字D": "https://1geki.jp/slot/s_intiald/",
    "バジリスク絆2": "https://1geki.jp/slot/s_b_kizna2/",
    "犬夜叉": "https://1geki.jp/slot/s_inuyasha/",
    "甲鉄城のカバネリ": "https://1geki.jp/slot/s_kabaneri/",
    "この素晴らしい世界に祝福を！": "https://1geki.jp/slot/s_konosuba/",
    "ニューパルサーDX3": "https://1geki.jp/slot/s_newpal_dx3/",
    "ニューパルサーSP4 with 太鼓の達人": "https://1geki.jp/slot/s_newpulsar_with_tt/",
    "ニューパルサーSPⅢ": "https://1geki.jp/slot/s_newpulsar_sp3/",
    "アイムジャグラーEX-TP": "https://1geki.jp/slot/s_ij_ex_6/",
    "化物語": "https://1geki.jp/slot/l_bakemonogatari/",
    "サラリーマン金太郎": "https://1geki.jp/slot/l_kintaro/",
    "スーパービンゴネオ": "https://1geki.jp/slot/l_superbingo_neo/",
    "吉宗": "https://1geki.jp/slot/l_yoshimune/",
}

UNRESOLVED_LEGACY_SOURCES: set[str] = set()

SOURCE_NOTE_RE = re.compile(r"(?:^|[、。])出典:\s*https://1geki\.jp/slot/[^\s、,]+/?")
CANONICAL_NOTE_RE = re.compile(r"(?:^|、)正規名:[^、]+")
NOTE_SOURCE_URL_RE = re.compile(r"https://1geki\.jp/slot/[^\s、,]+/?")


def _probability(value: str | float | int) -> str:
    return f"1/{value}"


def _setting_values(metric: str, values: dict[int, str | float | int]) -> dict[str, str]:
    formatter = str if metric.startswith("rtp") else _probability
    return {f"{metric}_setting{setting}": formatter(value) for setting, value in values.items()}


MANUAL_CORRECTIONS: dict[str, dict[str, str]] = {
    "うる星やつら": {
        "manufacturer": "EXCITE（エキサイト）",
        "release_date": "2024-04-08",
        "machine_type": "スマスロ / AT",
        **_setting_values("rtp", {1: 97.6, 2: 98.9, 4: 103.2, 5: 106.2, 6: 110.1}),
        **_setting_values("bonus_initial", {1: 266.5, 2: 256.3, 4: 232.9, 5: 216.4, 6: 196.7}),
        **_setting_values("at_initial", {1: 535.4, 2: 509.0, 4: 429.3, 5: 383.2, 6: 329.9}),
        "notes": "スマスロ/ATタイプ、設定1/2/4/5/6の5段階、天井は最大555G+α、AT純増約2.6枚/G",
    },
    "サラリーマン金太郎": {
        "manufacturer": "EXCITE（エキサイト）",
        "release_date": "2025-01-06",
        "machine_type": "スマスロ / AT",
        **_setting_values("rtp", {1: 97.8, 2: 99.1, 3: 100.5, 4: 104.1, 5: 108.2, 6: 114.9}),
        **_setting_values("bonus_initial", {1: 417, 2: 408, 3: 400, 4: 387, 5: 373, 6: 356}),
        **_setting_values("at_initial", {1: 844, 2: 813, 3: 781, 4: 712, 5: 641, 6: 574}),
        **_setting_values("combined_initial", {1: 279, 2: 272, 3: 265, 4: 251, 5: 236, 6: 220}),
        "notes": "スマスロ/ATタイプ、BONUS純増約6.0枚/G、AT純増約4.0枚/G、天井は最大999G+α",
    },
    "スーパービンゴネオ": {
        "manufacturer": "BELLCO（ベルコ）",
        "release_date": "2024-12-16",
        "machine_type": "スマスロ / AT",
        **_setting_values("rtp", {1: 97.3, 2: 98.5, 4: 104.3, 5: 108.3, 6: 114.9}),
        **_setting_values("at_initial", {1: 449.2, 2: 440.4, 4: 405.5, 5: 387.2, 6: 365.3}),
        "notes": "スマスロ/ATタイプ、AT純増約2.8枚/Gまたは約5.0枚/G、天井は最大999G+α",
    },
    "パチスロ新鬼武者": {
        "manufacturer": "Enterrise（エンターライズ）",
        "release_date": "2020-03-23",
        "machine_type": "AT",
        **_setting_values("rtp", {1: 97.9, 2: 99.4, 3: 100.8, 4: 103.6, 5: 105.7, 6: 110.0}),
        **_setting_values("bonus_initial", {1: 299.8, 2: 297.8, 3: 272.7, 4: 258.3, 5: 226.3, 6: 161.0}),
        "notes": "6号機 新鬼武者～DAWN OF DREAMS～、純増約3枚/GのAT機",
    },
    "劇場版魔法少女まどか☆マギカ[新編]叛逆の物語": {
        "manufacturer": "MACY（メーシー）",
        "release_date": "2019-09-02",
        "machine_type": "AT",
        **_setting_values("rtp", {1: 97.3, 2: 98.3, 3: 100.2, 4: 103.5, 5: 106.3, 6: 111.5}),
        **_setting_values("combined_initial", {1: 187.2, 2: 166.6, 3: 158.5, 4: 153.6, 5: 146.3, 6: 123.2}),
        "notes": "6号機、ボーナス・AT合算を設定推測指標として収録、AT純増約3.0枚/G",
    },
    "化物語": {
        "manufacturer": "GINZA（銀座）",
        "release_date": "2025-12-08",
        "machine_type": "スマスロ / AT",
        **_setting_values("rtp", {1: 97.9, 2: 98.9, 3: 100.9, 4: 105.0, 5: 107.8, 6: 112.1}),
        **_setting_values("at_initial", {1: 265.1, 2: 260.7, 3: 252.1, 4: 238.8, 5: 230.8, 6: 219.6}),
        "notes": "スマスロ/ATタイプ、直AT、ゲーム数天井は最大1000G",
    },
    "吉宗": {
        "manufacturer": "sabohani（サボハニ）",
        "release_date": "2025-04-21",
        "machine_type": "スマスロ / AT",
        **_setting_values("rtp", {1: 97.8, 2: 99.1, 3: 100.6, 4: 104.1, 5: 107.1, 6: 112.0}),
        **_setting_values("combined_initial", {1: 378.9, 2: 369.6, 3: 358.8, 4: 335.1, 5: 318.5, 6: 292.4}),
        "notes": "スマスロ/ATタイプ、AT純増約7.11枚/G、天井は最大999G+α",
    },
}


def canonical_name_for(machine_name: str, notes: str = "") -> str:
    """Return the canonical name while retaining the raw machine name as an alias."""
    direct = CANONICAL_NAMES.get(machine_name.strip())
    if direct:
        return direct
    match = CANONICAL_NOTE_RE.search(notes or "")
    if match:
        return match.group(0).lstrip("、").removeprefix(CANONICAL_NOTE_PREFIX).strip()
    return machine_name.strip()


def canonical_manufacturer(value: str) -> str:
    """Prefer the Japanese maker label while preserving distinct subsidiaries."""

    match = re.search(r"[（(]([^）)]+)[）)]\s*$", value or "")
    if match and re.search(r"[ぁ-んァ-ヶ一-龠]", match.group(1)):
        return match.group(1).strip()
    return (value or "").strip()


def split_machine_type(value: str) -> tuple[str, str, str]:
    normalized = (value or "").strip()
    cabinet = "スマスロ" if "スマスロ" in normalized or "スマートスロット" in normalized else "メダル"
    upper = normalized.upper().replace("＋", "+")
    if "A+ART" in upper:
        game_type = "A+ART"
    elif "A+RT" in upper:
        game_type = "A+RT"
    elif "A+AT" in upper:
        game_type = "A+AT"
    elif "ART" in upper:
        game_type = "ART"
    elif re.search(r"(?:ノーマル|Aタイプ)", normalized):
        game_type = "ノーマル"
    elif re.search(r"(?:^| / )AT(?:$| / )", upper):
        game_type = "AT"
    else:
        game_type = normalized
    bt_flag = "1" if "BT" in upper or "ボーナストリガー" in normalized else "0"
    return cabinet, game_type, bt_flag


def _append_note(notes: str, value: str) -> str:
    cleaned = notes.strip().strip("、")
    return f"{cleaned}、{value}" if cleaned else value


def _remove_source_note(notes: str) -> str:
    cleaned = SOURCE_NOTE_RE.sub("", notes or "").strip().strip("、")
    cleaned = re.sub(r"、{2,}", "、", cleaned)
    return cleaned


def _extract_setting_metrics_from_notes(row: dict[str, str]) -> None:
    notes = row.get("notes", "")
    labels = {
        "at_initial": ("AT初当り", "AT初当たり", "AT初当り確率", "AT初当たり確率"),
        "bonus_initial": ("ボーナス初当り", "ボーナス初当たり", "BONUS初当り", "BONUS初当たり"),
        "bonus_combined": ("ボーナス合算",),
        "combined_initial": ("初当り合算", "初当たり合算", "ボーナス・AT合算", "ボーナス･AT合算"),
        "rtp_complete": ("完全攻略時出玉率", "完全攻略時機械割"),
    }
    for metric, aliases in labels.items():
        for alias in aliases:
            start = notes.find(alias)
            if start < 0:
                continue
            segment = notes[start : start + 260]
            value_pattern = r"\d+(?:\.\d+)?%" if metric == "rtp_complete" else r"1\s*[/／]\s*\d+(?:\.\d+)?"
            for setting, value in re.findall(rf"設定([1-6])\s*[=＝]\s*({value_pattern})", segment):
                column = f"{metric}_setting{setting}"
                if row.get(column):
                    continue
                if metric == "rtp_complete":
                    row[column] = value.replace("%", "").strip()
                else:
                    row[column] = re.sub(r"\s+", "", value).replace("／", "/")
            break


def _clean_structured_metrics(row: dict[str, str]) -> None:
    for metric in SETTING_METRICS:
        for setting in range(1, 7):
            column = f"{metric}_setting{setting}"
            value = row.get(column, "").strip()
            if not value:
                continue
            if metric == "rtp_complete":
                if not re.fullmatch(r"\d{2,3}(?:\.\d+)?", value):
                    row[column] = ""
            elif not re.fullmatch(r"1/\d+(?:\.\d+)?", value):
                row[column] = ""


def _ensure_smart_platform(row: dict[str, str]) -> None:
    source_url = row.get("source_url", "")
    release_date = row.get("release_date", "")
    machine_type = row.get("machine_type", "").strip()
    is_modern_l_page = "/slot/l_" in source_url and (not release_date or release_date >= "2022-01-01")
    if is_modern_l_page and "スマスロ" not in machine_type and "スマートスロット" not in machine_type:
        row["machine_type"] = f"スマスロ / {machine_type}" if machine_type else "スマスロ"


def _normalize_row(row: dict[str, str]) -> bool:
    before = dict(row)
    machine_name = row.get("machine_name", "").strip()

    note_url = NOTE_SOURCE_URL_RE.search(row.get("notes", ""))
    if not row.get("source_url", "").strip() and note_url:
        row.update(
            {
                "source_url": note_url.group(0),
                "source_status": "selected",
                "source_confidence": "1.0",
                "source_query": machine_name,
                "source_candidate_count": "1",
                "source_reason": "migrated_from_notes",
            }
        )

    canonical_name = CANONICAL_NAMES.get(machine_name)
    if canonical_name:
        row["notes"] = CANONICAL_NOTE_RE.sub("", row.get("notes", "")).strip().strip("、")

    if machine_name in VERIFIED_SOURCE_URLS:
        source_url = VERIFIED_SOURCE_URLS[machine_name]
        row.update(
            {
                "source_url": source_url,
                "source_status": "selected",
                "source_confidence": "1.0",
                "source_query": machine_name,
                "source_candidate_count": "1",
                "source_reason": "manual_verified_distinct_machine",
                "notes": _remove_source_note(row.get("notes", "")),
            }
        )
    elif machine_name in UNRESOLVED_LEGACY_SOURCES:
        row.update(
            {
                "source_url": "",
                "source_status": "not_found",
                "source_confidence": "0.0",
                "source_query": machine_name,
                "source_candidate_count": "0",
                "source_reason": "legacy_machine_no_matching_1geki_page",
                "notes": _remove_source_note(row.get("notes", "")),
            }
        )

    correction = MANUAL_CORRECTIONS.get(machine_name) or MANUAL_CORRECTIONS.get(CANONICAL_NAMES.get(machine_name, ""))
    if correction:
        for metric in SETTING_METRICS:
            for setting in range(1, 7):
                row[f"{metric}_setting{setting}"] = ""
        row.update(correction)

    row["notes"] = _remove_source_note(row.get("notes", ""))
    row["canonical_machine_name"] = CANONICAL_NAMES.get(machine_name, machine_name)
    row["manufacturer_canonical"] = canonical_manufacturer(row.get("manufacturer", ""))
    _ensure_smart_platform(row)
    cabinet, game_type, bt_flag = split_machine_type(row.get("machine_type", ""))
    row["cabinet_type"] = cabinet
    row["game_type"] = game_type
    row["bt_flag"] = bt_flag
    _clean_structured_metrics(row)
    _extract_setting_metrics_from_notes(row)

    return row != before


def _synchronize_alias_groups(rows: list[dict[str, str]]) -> None:
    groups: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        groups.setdefault(row["canonical_machine_name"], []).append(row)

    shared_fields = [
        "manufacturer",
        "manufacturer_canonical",
        "release_date",
        "machine_type",
        "cabinet_type",
        "game_type",
        "bt_flag",
        *(f"{metric}_setting{setting}" for metric in ("rtp", "bb", "rb", *SETTING_METRICS) for setting in range(1, 7)),
        "source_url",
        "source_status",
        "source_confidence",
        "source_title",
        "source_checked_at",
    ]
    for canonical_name, group in groups.items():
        if len(group) < 2:
            continue
        reference = next((row for row in group if row["machine_name"] == canonical_name), group[0])
        for field in shared_fields:
            value = reference.get(field, "").strip()
            if not value:
                value = next((row.get(field, "").strip() for row in group if row.get(field, "").strip()), "")
            for row in group:
                row[field] = value


def normalize_master(path: Path, *, write: bool = False) -> dict[str, int]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    for column in [*BASE_COLUMNS, *EXTRA_COLUMNS]:
        if column not in fieldnames:
            fieldnames.append(column)
            for row in rows:
                row[column] = ""

    required = {"machine_name", "notes", "source_url", "source_status"}
    missing = sorted(required - set(fieldnames))
    if missing:
        raise ValueError(f"missing_columns:{','.join(missing)}")

    before_rows = [dict(row) for row in rows]
    for row in rows:
        _normalize_row(row)
    _synchronize_alias_groups(rows)
    changed = sum(row != before for row, before in zip(rows, before_rows))
    if write and changed:
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

    return {
        "rows_total": len(rows),
        "rows_changed": changed,
        "aliases_registered": sum(1 for row in rows if row.get("machine_name") in CANONICAL_NAMES),
        "source_urls_verified": sum(1 for row in rows if row.get("machine_name") in VERIFIED_SOURCE_URLS),
        "legacy_sources_unresolved": sum(1 for row in rows if row.get("machine_name") in UNRESOLVED_LEGACY_SOURCES),
        "columns_total": len(fieldnames),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize machine-master aliases and known source URLs")
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    parser.add_argument("--write", action="store_true", help="Atomically update the master")
    args = parser.parse_args()
    summary = normalize_master(args.master, write=args.write)
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
