"""Infer which hall an extracted image belongs to, from machine numbers and names.

The accounts we monitor post chain-wide content, so an image's store cannot be
trusted to the account mapping, and `hall_hint` is absent on most data tables.
Matching the extracted (machine_number, machine_name) pairs against each hall's
own database identifies the store without another model call.

Number overlap alone is NOT sufficient: a hall with many machines matches a
foreign store's numbering by chance. Measured on the first 247 extracted images,
number-only matching claimed 29 images for レイトギャップ平和島 whose machine
names agreed just 8.2% of the time, while genuine matches
(マルハンメガシティ2000-蒲田1, 楽園蒲田店) agreed 68-83%. Both thresholds are
therefore required.
"""

import argparse
import glob
import os
import re
import sqlite3
from collections import defaultdict
from datetime import date

from config import DB_PATH
from hall_aliases import plausible_halls

HALL_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "db")
MIN_PAIRS = 3
MIN_NUMBER_RATE = 0.8
MIN_NAME_RATE = 0.5

# 999999Q9Qは店舗名ではなく店長ニックネームでマルハン全域を横断的に語るアカウントで、
# 対象外ホール（例: マルハン川口店）の投稿が、台番号+機種名の偶然の一致で追跡対象
# ホールに誤って割り当てられることがある（2026-09-24発覚）。この種のアカウントだけ、
# 本文にどの追跡対象ホールのエイリアスも現れない画像を「対象外」として除外する。
CHAIN_WIDE_HANDLES = frozenset({"999999Q9Q"})


def normalize_name(value: str) -> str:
    """Strip platform prefixes and separators so abbreviations still compare."""
    value = re.sub(r"(スマスロ|パチスロ|^[LSＬＳ]\s*)", "", str(value))
    return re.sub(r"[\s　・:：\-−ー]", "", value).lower()


def normalize_number(value: str) -> str:
    text = str(value).strip().lstrip("0")
    return text or "0"


def is_usable(number: str, name: str) -> bool:
    """Reject rows where the model mistook the table layout for machine data.

    A local 3B run on 2026-09-03 misread column boundaries and stored bonus
    rates ("1/207") and coin deltas ("+1,915") as machine numbers while putting
    the machine number into machine_name: 14.8% of its numbers were non-numeric
    and 78.5% of its names were bare digits, against 0-1.1% and 0% for Codex
    runs. Filtering at read time keeps such rows out of every downstream count
    without depending on them having been deleted first.
    """
    if not re.fullmatch(r"\d{1,4}", str(number).strip()):
        return False
    return not re.fullmatch(r"\d{1,4}", str(name).strip())


def load_hall_machines() -> dict[str, dict[str, set[str]]]:
    """Return {hall_name: {machine_number: {normalized machine names}}}."""
    halls: dict[str, dict[str, set[str]]] = {}
    for path in glob.glob(os.path.join(HALL_DB_DIR, "*.db")):
        hall_name = os.path.splitext(os.path.basename(path))[0]
        try:
            connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            machines: dict[str, set[str]] = defaultdict(set)
            for number, name in connection.execute(
                "SELECT machine_number, machine_name FROM machine_detailed_results WHERE machine_name IS NOT NULL"
            ):
                machines[normalize_number(number)].add(normalize_name(name))
            connection.close()
        except sqlite3.Error:
            continue
        if machines:
            halls[hall_name] = machines
    return halls


def names_agree(extracted: str, actual: str) -> bool:
    """Tweet images abbreviate ('マギレコ' vs 'マギアレコード…'), so compare loosely."""
    if not extracted or not actual:
        return False
    if extracted in actual or actual in extracted:
        return True
    return (len(extracted) >= 3 and extracted[:3] in actual) or (len(actual) >= 3 and actual[:3] in extracted)


def score_image(pairs: list[tuple[str, str]], halls) -> tuple[str | None, float, float]:
    """Return (hall, number_rate, name_rate) for the best-scoring hall."""
    best: tuple[str | None, float, float] = (None, 0.0, 0.0)
    for hall_name, machines in halls.items():
        number_hits = sum(1 for number, _ in pairs if number in machines)
        name_hits = sum(
            1
            for number, name in pairs
            if number in machines and any(names_agree(name, actual) for actual in machines[number])
        )
        number_rate = number_hits / len(pairs)
        name_rate = name_hits / len(pairs)
        if (number_rate, name_rate) > (best[1], best[2]):
            best = (hall_name, number_rate, name_rate)
    return best


def main() -> int:
    parser = argparse.ArgumentParser(description="抽出済みエントリの所属ホールを台番号・機種名の一致から推定します。")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="推定結果を extraction_entries.inferred_hall に書き込みます。",
    )
    args = parser.parse_args()

    halls = load_hall_machines()
    if not halls:
        print(f"ホールDBが見つかりません: {HALL_DB_DIR}")
        return 1

    connection = sqlite3.connect(DB_PATH, timeout=60)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(extraction_entries)")}
    if "inferred_hall" not in columns:
        connection.execute("ALTER TABLE extraction_entries ADD COLUMN inferred_hall TEXT")
        connection.commit()
    elif args.apply:
        # 過去の実行で書き込んだ値は、ロジック変更で対象外になっても自動では消えない
        # （UPDATEは今回一致した行にしか効かない）。毎回全リセットしてから書き直し、
        # 古い判定が残留しないようにする（2026-09-24、ARROW池上店の誤判定19枚が
        # フィルタ追加後も残っていたことで発覚）。
        connection.execute("UPDATE extraction_entries SET inferred_hall = NULL")
        connection.commit()

    images: dict[str, dict] = defaultdict(lambda: {"handle": None, "pairs": [], "text": None, "posted": None})
    rejected = 0
    for image_path, handle, number, name, full_text, tweet_text, posted_at in connection.execute(
        """
        SELECT en.image_path, en.handle, en.machine_number, en.machine_name,
               st.full_text, st.tweet_text, st.posted_at_jst
        FROM extraction_entries en
        JOIN seen_tweets st ON st.tweet_id = en.tweet_id
        """
    ):
        if not is_usable(number, name):
            rejected += 1
            continue
        images[image_path]["handle"] = handle
        images[image_path]["text"] = full_text or tweet_text
        images[image_path]["posted"] = posted_at
        images[image_path]["pairs"].append((normalize_number(number), normalize_name(name)))
    if rejected:
        print(f"構造誤認として除外した行: {rejected}件")

    resolved: dict[str, int] = defaultdict(int)
    per_handle: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    unresolved = 0
    excluded_no_alias = 0
    for image_path, info in images.items():
        pairs = info["pairs"]
        if len(pairs) < MIN_PAIRS:
            unresolved += 1
            continue
        candidate_halls = halls
        if info["handle"] in CHAIN_WIDE_HANDLES:
            on_date = date.fromisoformat(info["posted"][:10]) if info["posted"] else None
            plausible = plausible_halls(info["text"], on_date)
            if not plausible:
                excluded_no_alias += 1
                unresolved += 1
                continue
            candidate_halls = {name: machines for name, machines in halls.items() if name in plausible}
            if not candidate_halls:
                unresolved += 1
                continue
        hall_name, number_rate, name_rate = score_image(pairs, candidate_halls)
        if hall_name and number_rate >= MIN_NUMBER_RATE and name_rate >= MIN_NAME_RATE:
            resolved[hall_name] += 1
            per_handle[info["handle"]][hall_name] += 1
            if args.apply:
                connection.execute(
                    "UPDATE extraction_entries SET inferred_hall = ? WHERE image_path = ?",
                    (hall_name, image_path),
                )
        else:
            unresolved += 1
    if args.apply:
        connection.commit()
    connection.close()

    total = len(images)
    hit = sum(resolved.values())
    print(f"画像 {total} 枚  対象ホール特定 {hit} 枚 ({hit / total * 100:.1f}%)  対象外/不明 {unresolved} 枚")
    if excluded_no_alias:
        print(f"  うちチェーン横断アカウントで本文にどの対象ホールも言及なし: {excluded_no_alias}枚")
    print("\n=== 特定されたホール ===")
    for hall_name, count in sorted(resolved.items(), key=lambda item: -item[1]):
        print(f"  {hall_name}: {count}枚")
    print("\n=== アカウント別 対象ホール含有率 ===")
    handle_totals: dict[str, int] = defaultdict(int)
    for info in images.values():
        handle_totals[info["handle"]] += 1
    for handle, total_images in sorted(handle_totals.items(), key=lambda item: -item[1]):
        counts = per_handle.get(handle, {})
        hits = sum(counts.values())
        detail = ", ".join(f"{name}:{value}" for name, value in sorted(counts.items(), key=lambda x: -x[1])[:3])
        print(f"  {handle:16} {hits:4}/{total_images:4} ({hits / total_images * 100:5.1f}%)  {detail}")
    if args.apply:
        print("\ninferred_hall を更新しました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
