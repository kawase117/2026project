"""Score every collected image so extraction only runs on plausible data tables.

Most collected images are photos, promo graphics, or memes that carry no machine
numbers at all, and a model call on those is pure waste. Two cheap PIL features
separate them: data tables are rendered documents (few distinct colors, sizable
white background) while the rest are photographic.

Thresholds come from the 1,003 images already extracted with Codex, labelled by
whether they yielded any machine number:

    colors<=150 AND white>=0.04  ->  62.3% of images dropped, 5.9% of real
                                     tables lost, 71.2% of what remains is real

Looser rules keep more tables but cut far less (colors<=200 alone drops only
41%), and stricter white-ratio rules lose over 30% of real tables, so this pair
is the measured optimum. Rejected rows stay in the table with is_candidate=0 so
a later pass can sweep them up.
"""

import argparse
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
from PIL import Image

from config import DB_PATH

JST = ZoneInfo("Asia/Tokyo")
THUMBNAIL = (200, 200)
MAX_COLORS = 150
MIN_WHITE_RATIO = 0.04


def image_features(path: str) -> tuple[int, int, int, float]:
    """Return (width, height, distinct colors, white ratio) from a downsampled copy."""
    image = Image.open(path)
    width, height = image.size
    image = image.convert("RGB")
    image.thumbnail(THUMBNAIL)
    pixels = np.asarray(image).astype(np.int16)
    colors = len(np.unique((pixels // 32).reshape(-1, 3), axis=0))
    white_ratio = float((pixels.min(axis=2) > 200).mean())
    return width, height, colors, white_ratio


def initialize_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS image_features (
            image_path TEXT PRIMARY KEY,
            width INTEGER,
            height INTEGER,
            colors INTEGER,
            white_ratio REAL,
            is_candidate INTEGER,
            computed_at_jst TEXT
        )
        """
    )
    connection.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description="収集済み画像を安価な特徴量で分別し、抽出対象候補を絞り込みます。")
    parser.add_argument("--recompute", action="store_true", help="計算済みの画像も再計算します。")
    parser.add_argument("--max-colors", type=int, default=MAX_COLORS)
    parser.add_argument("--min-white", type=float, default=MIN_WHITE_RATIO)
    args = parser.parse_args()

    connection = sqlite3.connect(DB_PATH, timeout=60)
    initialize_table(connection)

    query = "SELECT DISTINCT image_path FROM tweet_images"
    if not args.recompute:
        query += " WHERE image_path NOT IN (SELECT image_path FROM image_features)"
    paths = [row[0] for row in connection.execute(query)]
    print(f"対象画像: {len(paths)}枚")

    processed = 0
    unreadable = 0
    for index, path in enumerate(paths, 1):
        try:
            width, height, colors, white_ratio = image_features(path)
        except Exception:
            unreadable += 1
            continue
        candidate = int(colors <= args.max_colors and white_ratio >= args.min_white)
        connection.execute(
            """
            INSERT INTO image_features
                (image_path, width, height, colors, white_ratio, is_candidate, computed_at_jst)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(image_path) DO UPDATE SET
                width=excluded.width, height=excluded.height, colors=excluded.colors,
                white_ratio=excluded.white_ratio, is_candidate=excluded.is_candidate,
                computed_at_jst=excluded.computed_at_jst
            """,
            (path, width, height, colors, white_ratio, candidate, datetime.now(JST).isoformat()),
        )
        processed += 1
        if index % 500 == 0:
            connection.commit()
            print(f"  {index}/{len(paths)} 処理中...", flush=True)
    connection.commit()

    total = connection.execute("SELECT COUNT(*) FROM image_features").fetchone()[0]
    candidates = connection.execute("SELECT COUNT(*) FROM image_features WHERE is_candidate = 1").fetchone()[0]
    pending = connection.execute(
        """
        SELECT COUNT(*) FROM image_features f
        WHERE f.is_candidate = 1
          AND NOT EXISTS (SELECT 1 FROM extractions e
                          WHERE e.image_path = f.image_path AND e.status = 'success')
        """
    ).fetchone()[0]
    connection.close()

    print(f"\n今回処理 {processed}枚 (読み込み失敗 {unreadable}枚)")
    print(f"判定済み合計 {total}枚")
    print(f"  抽出対象候補   {candidates}枚 ({candidates / total * 100:.1f}%)")
    print(f"  除外           {total - candidates}枚 ({(total - candidates) / total * 100:.1f}%)")
    print(f"  うち未抽出の候補 {pending}枚  ← これが残作業")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
