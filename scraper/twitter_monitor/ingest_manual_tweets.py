"""Ingest a human-collected tweet manifest into the monitor's collection DB."""

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding="utf-8")

from config import DB_PATH
from prefilter import MAX_COLORS, MIN_WHITE_RATIO, image_features


JST = ZoneInfo("Asia/Tokyo")
BACKUP_PATH = DB_PATH.with_name("state.db.bak-pre-manual-20261006")
EXPECTED_COLUMNS = {
    "seen_tweets": {
        "tweet_id",
        "handle",
        "tweet_url",
        "tweet_text",
        "posted_at_jst",
        "scraped_at_jst",
        "has_image",
        "full_text",
    },
    "tweet_images": {"id", "tweet_id", "image_path", "downloaded_at_jst"},
    "image_features": {"image_path", "width", "height", "colors", "white_ratio", "is_candidate", "computed_at_jst"},
}


def check_schema(connection: sqlite3.Connection) -> None:
    for table, expected in EXPECTED_COLUMNS.items():
        columns = connection.execute(f"PRAGMA table_info({table})").fetchall()
        actual = {column[1] for column in columns}
        if not columns or actual != expected:
            raise ValueError(f"{table} のスキーマが想定と異なります: {sorted(actual)}")
        supplied = expected - {"id"} if table == "tweet_images" else expected
        required = {
            column[1]
            for column in columns
            if column[3] and column[4] is None and not (column[5] and column[2] == "INTEGER")
        }
        if not required <= supplied:
            raise ValueError(f"{table} に未指定の NOT NULL 列があります: {sorted(required - supplied)}")


def load_manifest(path: Path) -> tuple[list[dict], dict[str, tuple[int, int, int, float]]]:
    tweets = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(tweets, list) or not tweets:
        raise ValueError("manifest は空ではない配列である必要があります")
    features = {}
    ids = set()
    paths = set()
    for tweet in tweets:
        for key in ("tweet_id", "handle", "tweet_url", "posted_at_jst", "full_text", "images"):
            if key not in tweet:
                raise ValueError(f"manifest に {key} がありません")
        tweet_id = tweet["tweet_id"]
        if not isinstance(tweet_id, str) or not tweet_id or tweet_id in ids:
            raise ValueError(f"tweet_id が不正または重複: {tweet_id}")
        ids.add(tweet_id)
        if not all(isinstance(tweet[key], str) for key in ("handle", "tweet_url", "posted_at_jst", "full_text")):
            raise ValueError(f"{tweet_id}: 文字列フィールドが不正です")
        if not isinstance(tweet["images"], list):
            raise ValueError(f"{tweet_id}: images は配列である必要があります")
        for raw_path in tweet["images"]:
            if not isinstance(raw_path, str) or not Path(raw_path).is_absolute():
                raise ValueError(f"{tweet_id}: 画像パスが絶対パスではありません: {raw_path}")
            if raw_path in paths:
                raise ValueError(f"画像パスが manifest 内で重複: {raw_path}")
            paths.add(raw_path)
            image_path = Path(raw_path)
            if not image_path.is_file():
                raise FileNotFoundError(f"画像ファイルがありません: {raw_path}")
            features[raw_path] = image_features(raw_path)
    return tweets, features


def print_table(connection: sqlite3.Connection, tweets: list[dict]) -> None:
    print("tweet_id | seen_tweets | tweet_images | image_features.is_candidate")
    for tweet in tweets:
        tweet_id = tweet["tweet_id"]
        seen = connection.execute("SELECT COUNT(*) FROM seen_tweets WHERE tweet_id = ?", (tweet_id,)).fetchone()[0]
        images = connection.execute("SELECT COUNT(*) FROM tweet_images WHERE tweet_id = ?", (tweet_id,)).fetchone()[0]
        candidates = connection.execute(
            """SELECT f.is_candidate FROM tweet_images i
               LEFT JOIN image_features f ON f.image_path = i.image_path
               WHERE i.tweet_id = ? ORDER BY i.id""",
            (tweet_id,),
        ).fetchall()
        values = ",".join("NULL" if row[0] is None else str(row[0]) for row in candidates)
        print(f"{tweet_id} | {seen} | {images} | {values}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", type=Path, default=Path("manual_ingest_20261006.json"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    tweets, features = load_manifest(args.manifest)
    uri = DB_PATH.as_uri() + "?mode=ro" if args.dry_run else str(DB_PATH)
    connection = sqlite3.connect(uri, uri=args.dry_run, timeout=60)
    try:
        check_schema(connection)
        print(f"manifest: {len(tweets)}件、画像: {len(features)}枚")
        if args.dry_run:
            print("dry-run: DB・バックアップへの書き込みなし")
            print_table(connection, tweets)
            return 0

        if BACKUP_PATH.exists():
            raise FileExistsError(f"バックアップが既に存在します: {BACKUP_PATH}")
        with DB_PATH.open("rb") as source, BACKUP_PATH.open("xb") as backup:
            shutil.copyfileobj(source, backup)
        print(f"backup: {BACKUP_PATH} ({BACKUP_PATH.stat().st_size} bytes)")

        for tweet in tweets:
            tweet_id = tweet["tweet_id"]
            now = datetime.now(JST).isoformat()
            with connection:
                existing = connection.execute("SELECT 1 FROM seen_tweets WHERE tweet_id = ?", (tweet_id,)).fetchone()
                if existing:
                    print(f"{tweet_id}: seen_tweets 既存のため INSERT スキップ")
                else:
                    connection.execute(
                        """INSERT INTO seen_tweets
                           (tweet_id, handle, tweet_url, tweet_text, posted_at_jst,
                            scraped_at_jst, has_image, full_text)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            tweet_id,
                            tweet["handle"],
                            tweet["tweet_url"],
                            tweet["full_text"],
                            tweet["posted_at_jst"],
                            now,
                            int(bool(tweet["images"])),
                            tweet["full_text"],
                        ),
                    )
                for path in tweet["images"]:
                    existing_image = connection.execute(
                        "SELECT 1 FROM tweet_images WHERE image_path = ?", (path,)
                    ).fetchone()
                    if existing_image:
                        print(f"{tweet_id}: tweet_images 既存のためスキップ: {path}")
                    else:
                        connection.execute(
                            "INSERT INTO tweet_images (tweet_id, image_path, downloaded_at_jst) VALUES (?, ?, ?)",
                            (tweet_id, path, now),
                        )
                    existing_feature = connection.execute(
                        "SELECT 1 FROM image_features WHERE image_path = ?", (path,)
                    ).fetchone()
                    if not existing_feature:
                        width, height, colors, white_ratio = features[path]
                        candidate = int(colors <= MAX_COLORS and white_ratio >= MIN_WHITE_RATIO)
                        connection.execute(
                            """INSERT INTO image_features
                               (image_path, width, height, colors, white_ratio, is_candidate, computed_at_jst)
                               VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (path, width, height, colors, white_ratio, candidate, now),
                        )
        print_table(connection, tweets)
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
