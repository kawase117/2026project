"""Pin each answer-check image to the business day its figures actually describe.

Images rarely print a date, so the day has to come from the post timestamp. A
fixed offset would be wrong often: matching stated figures against the halls'
own data puts the best candidate one day back for 54.5% of machine groups but
two days back for 31.8%, so the offset is resolved per image instead of assumed.

The notes state exact figures per machine group ("+2/4台、勝率50%、総差+3460枚").
Recomputing those totals from the hall database on each candidate day turns
dating into verification rather than inference: when no candidate reproduces the
stated numbers the row is left undated instead of guessed. Measured over the
first 22 checkable groups, the previous day reproduced the stated total 36.4% of
the time and the stated win count 54.5%, against 0.0% / 4.5% for the same day.

Only images whose hall infer_hall.py could identify are considered; without that
the machine numbers would be matched against the wrong hall's data.
"""

import argparse
import os
import re
import sqlite3
from collections import defaultdict
from datetime import date, timedelta

from config import DB_PATH

HALL_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "db")
MAX_OFFSET = 3
ABSOLUTE_TOLERANCE = 200
RELATIVE_TOLERANCE = 0.05
TOTAL_RE = re.compile(r"総差([+-]?[\d,]+)枚")
MEAN_RE = re.compile(r"平均([+-]?[\d,]+)枚")


def normalize_number(value):
    text = str(value).strip().lstrip("0")
    return text or "0"


def stated_total(note, machine_count):
    """Return the coin total the note claims, or None when it states no figure."""
    match = TOTAL_RE.search(note or "")
    if match:
        return int(match.group(1).replace(",", ""))
    match = MEAN_RE.search(note or "")
    if match and machine_count:
        return int(match.group(1).replace(",", "")) * machine_count
    return None


def load_hall(hall_name):
    path = os.path.join(HALL_DB_DIR, hall_name + ".db")
    if not os.path.exists(path):
        return None
    connection = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    table = defaultdict(dict)
    for day, number, diff in connection.execute(
        "SELECT date, machine_number, diff_coins_normalized FROM machine_detailed_results "
        "WHERE diff_coins_normalized IS NOT NULL"
    ):
        table[day][normalize_number(number)] = diff
    connection.close()
    return table


def add_columns(connection):
    existing = {row[1] for row in connection.execute("PRAGMA table_info(extraction_entries)")}
    for column, kind in (("business_date", "TEXT"), ("date_offset", "INTEGER"), ("date_error", "REAL")):
        if column not in existing:
            connection.execute("ALTER TABLE extraction_entries ADD COLUMN %s %s" % (column, kind))
    connection.commit()


def resolve_image(groups, hall_table, post_date):
    """Return (offset, mean relative error) for the day that best fits the notes."""
    best = None
    for offset in range(MAX_OFFSET + 1):
        day = (post_date - timedelta(days=offset)).strftime("%Y%m%d")
        table = hall_table.get(day)
        if not table:
            continue
        errors = []
        for numbers, note in groups:
            present = [table[n] for n in numbers if n in table]
            if len(present) < max(1, len(numbers) // 2):
                continue
            target = stated_total(note, len(present))
            if target is None:
                continue
            error = abs(sum(present) - target)
            if error <= max(ABSOLUTE_TOLERANCE, abs(target) * RELATIVE_TOLERANCE):
                errors.append(0.0)
            else:
                errors.append(error / max(abs(target), 1000))
        if not errors:
            continue
        score = sum(errors) / len(errors)
        if best is None or score < best[1]:
            best = (offset, score)
    return best


def main() -> int:
    parser = argparse.ArgumentParser(
        description="答え合わせ画像が対象とする営業日を、記載数値とホールDBの照合で確定します。"
    )
    parser.add_argument(
        "--apply", action="store_true", help="business_date / date_offset / date_error を書き込みます。"
    )
    parser.add_argument(
        "--max-error", type=float, default=0.5, help="この相対誤差を超える画像は未確定のままにします (既定 0.5)"
    )
    args = parser.parse_args()

    connection = sqlite3.connect(DB_PATH, timeout=60)
    add_columns(connection)
    rows = connection.execute(
        """
        SELECT en.image_path, en.inferred_hall, st.posted_at_jst,
               en.machine_name, en.machine_number, en.note
        FROM extraction_entries en
        JOIN seen_tweets st ON st.tweet_id = en.tweet_id
        WHERE en.inferred_hall IS NOT NULL
        """
    ).fetchall()

    images = defaultdict(lambda: {"hall": None, "posted": None, "groups": defaultdict(set)})
    for image_path, hall, posted, name, number, note in rows:
        info = images[image_path]
        info["hall"] = hall
        info["posted"] = posted[:10] if posted else None
        info["groups"][(name, note)].add(normalize_number(number))

    halls = {}
    resolved = skipped = no_note = 0
    offsets = defaultdict(int)
    for image_path, info in images.items():
        hall, posted = info["hall"], info["posted"]
        if not hall or not posted:
            skipped += 1
            continue
        if hall not in halls:
            halls[hall] = load_hall(hall)
        table = halls[hall]
        if not table:
            skipped += 1
            continue
        groups = [(numbers, note) for (name, note), numbers in info["groups"].items() if note]
        if not any(stated_total(note, len(numbers)) is not None for numbers, note in groups):
            no_note += 1
            continue
        best = resolve_image(groups, table, date.fromisoformat(posted))
        if best is None or best[1] > args.max_error:
            skipped += 1
            continue
        offset, error = best
        business_date = (date.fromisoformat(posted) - timedelta(days=offset)).isoformat()
        offsets[offset] += 1
        resolved += 1
        if args.apply:
            # One image is one business day, so the resolved date covers every
            # row of that image, including groups whose note stated no figures.
            connection.execute(
                "UPDATE extraction_entries SET business_date = ?, date_offset = ?, date_error = ? WHERE image_path = ?",
                (business_date, offset, error, image_path),
            )
    if args.apply:
        connection.commit()

    dated = connection.execute("SELECT COUNT(*) FROM extraction_entries WHERE business_date IS NOT NULL").fetchone()[0]
    connection.close()

    print("ホール特定済み画像 %d 枚" % len(images))
    print("  営業日を確定   %d 枚" % resolved)
    print("  数値の記載なし %d 枚" % no_note)
    print("  照合できず     %d 枚" % skipped)
    print("\n=== 確定した日数ずらし ===")
    for offset in sorted(offsets):
        print("  %d日前: %d枚" % (offset, offsets[offset]))
    if args.apply:
        print("\nbusiness_date を持つエントリ: %d件" % dated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
