"""Measure exact image-hash overlap for tweets with more than four images.

This is intentionally a read-only measurement script.  It never writes to the
SQLite database or modifies image files; its only output file is the requested
CSV report.
"""

from __future__ import annotations

import csv
import hashlib
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from config import DB_PATH, IMAGES_DIR


CSV_PATH = Path(__file__).resolve().parent / "quote_image_hash_matches.csv"
CSV_FIELDS = [
    "suspect_tweet_id",
    "suspect_handle",
    "image_index",
    "image_path",
    "matched_tweet_id",
    "matched_handle",
    "matched_image_path",
]


def resolve_image_path(raw_path: str) -> Path:
    """Resolve both the current absolute-path format and relative paths."""
    path = Path(raw_path)
    return path if path.is_absolute() else IMAGES_DIR / path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as image_file:
        for chunk in iter(lambda: image_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def group_by_handle(rows: Iterable[dict], key: str) -> dict[str, int]:
    result: dict[str, int] = defaultdict(int)
    for row in rows:
        result[row["handle"] or "(unknown)"] += row[key]
    return dict(result)


def main() -> None:
    conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        image_rows = [
            dict(row) for row in conn.execute("SELECT id, tweet_id, image_path FROM tweet_images ORDER BY id")
        ]
        handles = {
            row["tweet_id"]: row["handle"] or "(unknown)"
            for row in conn.execute("SELECT tweet_id, handle FROM seen_tweets")
        }
    finally:
        conn.close()

    by_tweet: dict[str, list[dict]] = defaultdict(list)
    for row in image_rows:
        row["handle"] = handles.get(row["tweet_id"], "(unknown)")
        by_tweet[row["tweet_id"]].append(row)

    suspect_ids = {tweet_id for tweet_id, rows in by_tweet.items() if len(rows) >= 5}

    # Build the comparison index from every tweet, then filter out the
    # suspect tweet itself and exact path duplicates at comparison time.
    hash_index: dict[str, list[dict]] = defaultdict(list)
    unreadable: list[tuple[str, str, str]] = []
    hash_cache: dict[str, str] = {}
    for row in image_rows:
        raw_path = row["image_path"]
        path = resolve_image_path(raw_path)
        cache_key = str(path)
        try:
            digest = hash_cache.get(cache_key)
            if digest is None:
                digest = sha256_file(path)
                hash_cache[cache_key] = digest
        except (OSError, ValueError) as exc:
            unreadable.append((row["tweet_id"], raw_path, f"{type(exc).__name__}: {exc}"))
            continue
        row["sha256"] = digest
        row["resolved_path"] = cache_key
        hash_index[digest].append(row)

    rows_for_csv: list[dict] = []
    per_handle: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    matched_tweet_ids_by_handle: dict[str, set[str]] = defaultdict(set)
    matched_suspect_ids: set[str] = set()
    matched_image_count = 0
    matched_pair_count = 0
    unmatched_image_count = 0
    same_path_duplicate_count = 0
    same_path_duplicate_tweet_ids: set[str] = set()
    internal_duplicate_count = 0
    internal_duplicate_tweet_ids: set[str] = set()
    readable_suspect_image_count = 0
    unreadable_suspect_image_count = 0

    for tweet_id in sorted(suspect_ids):
        suspect_rows = by_tweet[tweet_id]
        handle = suspect_rows[0]["handle"]
        stats = per_handle[handle]
        stats["suspect_posts"] += 1
        seen_paths_in_tweet: set[str] = set()
        for image_index, row in enumerate(suspect_rows, start=1):
            stats["all_images"] += 1
            bucket = "after_four" if image_index >= 5 else "first_four"
            raw_path = row["image_path"]
            path = resolve_image_path(raw_path)
            path_key = str(path)
            try:
                digest = row.get("sha256") or sha256_file(path)
            except (OSError, ValueError) as exc:
                unreadable_suspect_image_count += 1
                stats["unreadable_images"] += 1
                unreadable.append((tweet_id, raw_path, f"{type(exc).__name__}: {exc}"))
                continue
            readable_suspect_image_count += 1
            if path_key in seen_paths_in_tweet:
                internal_duplicate_count += 1
                internal_duplicate_tweet_ids.add(tweet_id)
                stats["internal_duplicates"] += 1
                continue
            seen_paths_in_tweet.add(path_key)
            candidates = hash_index.get(digest, [])
            eligible = [
                candidate
                for candidate in candidates
                if candidate["tweet_id"] != tweet_id
                and candidate.get("resolved_path", str(resolve_image_path(candidate["image_path"]))) != path_key
            ]
            same_path = [
                candidate
                for candidate in candidates
                if candidate["tweet_id"] != tweet_id
                and candidate.get("resolved_path", str(resolve_image_path(candidate["image_path"]))) == path_key
            ]
            if same_path:
                same_path_duplicate_count += len(same_path)
                same_path_duplicate_tweet_ids.add(tweet_id)
                stats["same_path_duplicates"] += len(same_path)
            if not eligible:
                unmatched_image_count += 1
                stats["unmatched_images"] += 1
                continue
            matched_suspect_ids.add(tweet_id)
            matched_tweet_ids_by_handle[handle].add(tweet_id)
            matched_image_count += 1
            stats["matched_images"] += 1
            stats[f"matched_{bucket}"] += 1
            for candidate in eligible:
                matched_pair_count += 1
                rows_for_csv.append(
                    {
                        "suspect_tweet_id": tweet_id,
                        "suspect_handle": handle,
                        "image_index": image_index,
                        "image_path": raw_path,
                        "matched_tweet_id": candidate["tweet_id"],
                        "matched_handle": candidate["handle"],
                        "matched_image_path": candidate["image_path"],
                    }
                )

    with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows_for_csv)

    suspect_count = len(suspect_ids)
    matched_post_count = len(matched_suspect_ids)
    matched_post_pct = (matched_post_count / suspect_count * 100) if suspect_count else 0.0
    print(f"CSV: {CSV_PATH}")
    print(f"tweet_images総数: {len(image_rows)}")
    print(f"suspect投稿数 (画像5枚以上): {suspect_count}")
    print(f"画像ハッシュ一致が1件以上のsuspect投稿数: {matched_post_count} ({matched_post_pct:.2f}%)")
    print(f"一致した画像数 (suspect画像単位): {matched_image_count}")
    print(f"  5枚目以降: {sum(s['matched_after_four'] for s in per_handle.values())}")
    print(f"  1〜4枚目: {sum(s['matched_first_four'] for s in per_handle.values())}")
    print(f"一致ペア行数 (CSV行数): {matched_pair_count}")
    print(f"一致しなかった画像数 (読込成功かつ一致なし): {unmatched_image_count}")
    print(f"読込できたsuspect画像数: {readable_suspect_image_count}")
    print(f"読込できなかった画像数: {len(unreadable)} (うちsuspect: {unreadable_suspect_image_count})")
    print(f"同一ファイルパス重複として除外した一致候補数: {same_path_duplicate_count}")
    print(f"同一ファイルパス重複があったsuspect投稿数: {len(same_path_duplicate_tweet_ids)}")
    print(f"同一tweet_id内の重複画像行数 (一致対象外): {internal_duplicate_count}")
    print(f"同一tweet_id内の重複があったsuspect投稿数: {len(internal_duplicate_tweet_ids)}")
    print("handle別内訳:")
    display_handles = ["999999Q9Q", "kawasakislot", "sloneko222", "その他"]
    grouped_stats: dict[str, defaultdict[str, int]] = {handle: defaultdict(int) for handle in display_handles}
    grouped_matched_posts: dict[str, int] = defaultdict(int)
    for handle, stats in per_handle.items():
        display_handle = handle if handle in display_handles[:3] else "その他"
        for key, value in stats.items():
            grouped_stats[display_handle][key] += value
        grouped_matched_posts[display_handle] += len(matched_tweet_ids_by_handle[handle])
    for handle in display_handles:
        stats = grouped_stats[handle]
        matched_posts = grouped_matched_posts[handle]
        post_pct = (matched_posts / stats["suspect_posts"] * 100) if stats["suspect_posts"] else 0.0
        print(
            f"  {handle}: suspect投稿={stats['suspect_posts']}, "
            f"一致投稿={matched_posts} ({post_pct:.2f}%), "
            f"一致画像={stats['matched_images']} "
            f"(5枚目以降={stats['matched_after_four']}, 1〜4枚目={stats['matched_first_four']}), "
            f"不一致画像={stats['unmatched_images']}, "
            f"読込不可={stats['unreadable_images']}, "
            f"同一パス重複除外={stats['same_path_duplicates']}, "
            f"同一tweet_id内重複={stats['internal_duplicates']}"
        )
    if unreadable:
        print("読込不可ログ:")
        for tweet_id, raw_path, error in unreadable:
            print(f"  tweet_id={tweet_id} path={raw_path} error={error}")


if __name__ == "__main__":
    main()
