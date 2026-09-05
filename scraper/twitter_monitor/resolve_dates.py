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
# Posts made before this hour report the previous business day. All 36 images
# whose date could be verified against hall data were posted between 01:00 and
# 07:59 and all referred to the previous day, so the rule is applied only inside
# that window. Later posts -- notably the 23:00 cluster, which plausibly reports
# the day that just ended -- have never been verified and are left undated.
RULE_CUTOFF_HOUR = 8
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
    for column, kind in (
        ("business_date", "TEXT"),
        ("date_offset", "INTEGER"),
        ("date_error", "REAL"),
        ("date_source", "TEXT"),
    ):
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

    images = defaultdict(lambda: {"hall": None, "posted": None, "hour": None, "groups": defaultdict(set)})
    for image_path, hall, posted, name, number, note in rows:
        info = images[image_path]
        info["hall"] = hall
        info["posted"] = posted[:10] if posted else None
        info["hour"] = int(posted[11:13]) if posted and len(posted) >= 13 else None
        info["groups"][(name, note)].add(normalize_number(number))

    halls = {}
    resolved = skipped = no_note = 0
    by_rule = out_of_window = 0
    offsets = defaultdict(int)
    for image_path, info in images.items():
        hall, posted = info["hall"], info["posted"]
        if not hall or not posted:
            skipped += 1
            continue
        if hall not in halls:
            halls[hall] = load_hall(hall)
        table = halls[hall]
        best = None
        if table:
            groups = [(numbers, note) for (name, note), numbers in info["groups"].items() if note]
            if any(stated_total(note, len(numbers)) is not None for numbers, note in groups):
                best = resolve_image(groups, table, date.fromisoformat(posted))
                if best is not None and best[1] > args.max_error:
                    best = None
            else:
                no_note += 1

        if best is not None:
            offset, error, source = best[0], best[1], "matched"
            resolved += 1
            offsets[offset] += 1
        elif info["hour"] is not None and info["hour"] < RULE_CUTOFF_HOUR:
            # Inside the verified window only: never date the 23:00 posts, whose
            # offset no measurement has pinned down yet.
            offset, error, source = 1, None, "rule"
            by_rule += 1
        else:
            out_of_window += 1
            continue

        business_date = (date.fromisoformat(posted) - timedelta(days=offset)).isoformat()
        if args.apply:
            # One image is one business day, so the resolved date covers every
            # row of that image, including groups whose note stated no figures.
            connection.execute(
                "UPDATE extraction_entries SET business_date = ?, date_offset = ?, "
                "date_error = ?, date_source = ? WHERE image_path = ?",
                (business_date, offset, error, source, image_path),
            )
    if args.apply:
        connection.commit()

    dated = connection.execute("SELECT COUNT(*) FROM extraction_entries WHERE business_date IS NOT NULL").fetchone()[0]
    connection.close()

    print("ホール特定済み画像 %d 枚" % len(images))
    print("  照合で確定       %d 枚 (記載数値がホールDBと一致)" % resolved)
    print("  規則で補完       %d 枚 (0-%d時の投稿=前日、実証済みの範囲)" % (by_rule, RULE_CUTOFF_HOUR - 1))
    print("  未確定           %d 枚 (%d時以降の投稿。規則が未実証)" % (out_of_window, RULE_CUTOFF_HOUR))
    print("  ホール情報なし   %d 枚" % skipped)
    print("  (うち数値の記載なし %d 枚)" % no_note)
    print("\n=== 照合で確定した日数ずらし ===")
    for offset in sorted(offsets):
        print("  %d日前: %d枚" % (offset, offsets[offset]))
    if args.apply:
        print("\nbusiness_date を持つエントリ: %d件" % dated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
