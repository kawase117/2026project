# -*- coding: utf-8 -*-
"""別のツイートに紐付いてしまった画像を、個別ステータスページから取り直す。

なぜ必要か
----------
`scrape_tweets.crawl_account` は記事を `articles.nth(index)` という遅延ロケータで
二度解決していた。ツイートIDを読むときと画像を取るときで、仮想スクロールにより
DOMがずれると別の記事を掴む。その結果、B の投稿の画像が A の `tweet_id` の名前で
保存される。2026-09-09 の実測で、slokotae7 の画像付き220投稿のうち42件（19%）は
本文の機種名と画像の機種名が **一件も重ならなかった**。

たとえば `2086853029756903714_1.jpg`（本文は 8/10 楽園蒲田店）の中身は、
別投稿 2085927740696609208（8/1 新！ガーデン川口安行、ToLOVEる 3/3 平均+3475枚）
のものだった。OCRは正確で、投稿も1件1ホールである。壊れていたのは紐付けだけ。

`scrape_tweets` 側は修正済み（`article_for_tweet` / `article_owns_tweet`）だが、
既に落ちている画像は `download_images` の `if target_path.exists()` により
二度と取り直されない。このスクリプトで消してから取り直す。

なぜ個別ステータスページなのか
------------------------------
`https://x.com/<handle>/status/<id>` は対象の投稿が主記事として1件だけ載るので、
タイムラインのようにスクロールで記事が入れ替わることがない。取り違えの余地がない。

安全のために
------------
- 既定は `--dry-run`。何も消さず、対象と理由だけ出す。
- 取り直しの前に、開いたページの記事が本当にそのツイートかを `article_owns_tweet`
  で確かめる。確かめられなければ、その投稿は触らない。
- 画像を消したら `extraction_entries` / `extractions` / `image_features` の
  該当行も消す。残すと古い抽出結果が生き続け、取り直した意味がなくなる。
"""

import argparse
import logging
import os
import re
import sqlite3
import sys

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from config import AUTH_STATE_PATH, DB_PATH, IMAGES_DIR
from scrape_tweets import (
    CHROME_USER_AGENT,
    image_download_url,
    now_jst,
    raise_if_logged_out,
)

LOGGER = logging.getLogger(__name__)

# 機種名の突き合わせ用。scrape 側と違い、ここは「重なりが皆無か」を見るだけなので
# 記号を広めに落として取りこぼしを減らす。
NOISE = re.compile(r"(スマスロ|パチスロ|^[LSＬＳ]\s*)")
PUNCT = re.compile(r"[\s　・:：\-−ー！!？?／/（）\(\)【】、。～〜]")


def normalize(value):
    return PUNCT.sub("", NOISE.sub("", str(value or ""))).lower()


ENUMERATES_MODELS = re.compile(r"【[^】]+】")


def find_suspects(connection, handle):
    """本文の機種名と画像側の機種名が一件も重ならない投稿を返す。

    画像が本文の一部しか写していないことは普通にあるので、「一部だけ一致」は
    疑わない。**皆無** のときだけ疑う。

    ⚠️ **本文が機種を列挙していない投稿は対象外にする。** パチンコの報告は
    ホール名・取材名・差玉の合計だけを書き、機種名は画像にしかない。これを
    疑うと一致率0%が当たり前に出てしまい、2026-09-09 の修復後の検証で
    19件が偽陽性として残った（いずれもパチンコの投稿で、紐付けは正しかった）。
    粒度ブロック【全台】等の有無を、機種を列挙しているかの判定に使う。
    """
    texts = dict(
        connection.execute(
            "SELECT tweet_id, COALESCE(full_text, tweet_text, '') FROM seen_tweets WHERE handle = ?", (handle,)
        )
    )
    extracted = {}
    for tweet_id, name in connection.execute("SELECT tweet_id, machine_name FROM extraction_entries"):
        if tweet_id in texts:
            extracted.setdefault(tweet_id, set()).add(normalize(name))

    suspects = []
    for tweet_id, names in extracted.items():
        raw = texts[tweet_id]
        if not ENUMERATES_MODELS.search(raw):
            continue
        body = normalize(raw)
        usable = [n for n in names if len(n) >= 3]
        if not usable:
            continue
        if any(n[:4] in body for n in usable):
            continue
        suspects.append(tweet_id)
    return sorted(suspects)


def images_of(connection, tweet_id):
    rows = connection.execute(
        "SELECT DISTINCT image_path FROM extraction_entries WHERE tweet_id = ?", (tweet_id,)
    ).fetchall()
    rows += connection.execute(
        "SELECT DISTINCT image_path FROM tweet_images WHERE tweet_id = ?", (tweet_id,)
    ).fetchall()
    return sorted({row[0] for row in rows if row[0]})


def purge(connection, tweet_id, paths):
    """壊れた画像とその抽出結果を消す。抽出結果を残すと取り直しが無意味になる。"""
    for path in paths:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError as error:
            LOGGER.warning("画像を削除できない %s: %s", path, error)
        connection.execute("DELETE FROM image_features WHERE image_path = ?", (path,))
        connection.execute("DELETE FROM extractions WHERE image_path = ?", (path,))
    connection.execute("DELETE FROM extraction_entries WHERE tweet_id = ?", (tweet_id,))
    connection.execute("DELETE FROM tweet_images WHERE tweet_id = ?", (tweet_id,))


def strip_emoji(value):
    """絵文字（U+FFFF超のサロゲートペア文字）を落とす。

    X は本文中の絵文字を画像（twemoji）として描画するため、Playwright の
    `inner_text()` はそれを拾わない。一方 DB の `full_text` は生のテキストを
    保持しているので絵文字が残る。両者をそのまま突き合わせると、絵文字で
    始まる投稿（🫛🌈🌹等）が軒並み「本文が一致しない」と誤判定される
    （2026-09-24、999999Q9Qの100件バッチで48%が誤スキップして発覚）。
    """
    return "".join(ch for ch in str(value or "") if ord(ch) <= 0xFFFF)


def same_tweet_text(shown, expected):
    """開いた記事が目的の投稿かを本文で確かめる。

    個別ステータスページでは、主ツイートのタイムスタンプが **自分自身へのリンクに
    ならない** ため、`a[href^="/handle/status/<id>"]` では記事を特定できない
    （2026-09-09 にこれで取り違え検知が空振りした）。本文の先頭を突き合わせる。
    """
    left = PUNCT.sub("", strip_emoji(shown))[:20]
    right = PUNCT.sub("", strip_emoji(expected))[:20]
    return bool(left) and bool(right) and (left == right or left in right or right in left)


def fetch_images(page, handle, tweet_id, expected_text):
    """画像を取得して (連番, バイト列) で返す。**消す前に必ずこれを成功させる。**

    先に消してから取りに行くと、取得に失敗したときに元も失う（2026-09-09 に
    実際にやってしまった）。取得できたものだけを差し替える。
    """
    page.goto(f"https://x.com/{handle}/status/{tweet_id}", wait_until="domcontentloaded", timeout=45_000)
    page.wait_for_timeout(2_500)
    raise_if_logged_out(page)
    article = page.locator('article[data-testid="tweet"]').first
    if article.count() == 0:
        LOGGER.warning("%s: 記事が無い", tweet_id)
        return None
    node = article.locator('[data-testid="tweetText"]')
    shown = node.first.inner_text(timeout=5_000) if node.count() else ""
    if not same_tweet_text(shown, expected_text):
        LOGGER.warning("%s: 本文が一致しないので触らない (取得=%r)", tweet_id, shown[:30])
        return None

    # 引用ツイートの画像は主記事の中に描画されるので、media 画像を全部拾うと引用元の
    # 画像も取り直してしまう。自分の画像だけが /status/<自分のid>/photo/N に包まれる
    # （2026-09-13 に個別ステータスページで確認。scrape_tweets.download_images と同じ条件）。
    nodes = article.locator(f'a[href*="/status/{tweet_id}/photo/"] img[src*="pbs.twimg.com/media"]')
    blobs = []
    for index in range(nodes.count()):
        source = nodes.nth(index).get_attribute("src")
        if not source:
            continue
        response = page.context.request.get(image_download_url(source), timeout=30_000)
        if not response.ok:
            LOGGER.warning("%s: 画像%d の取得に失敗 HTTP %s", tweet_id, index + 1, response.status)
            return None
        blobs.append((index + 1, response.body()))
    return blobs


def save_images(connection, handle, tweet_id, blobs):
    target_dir = IMAGES_DIR / handle
    target_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for index, body in blobs:
        path = target_dir / f"{tweet_id}_{index}.jpg"
        path.write_bytes(body)
        paths.append(str(path))
        connection.execute(
            "INSERT INTO tweet_images(tweet_id, image_path, downloaded_at_jst) VALUES (?, ?, ?)",
            (tweet_id, str(path), now_jst()),
        )
    connection.execute("UPDATE seen_tweets SET has_image = ? WHERE tweet_id = ?", (int(bool(paths)), tweet_id))
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--handle", default="slokotae7")
    parser.add_argument("--apply", action="store_true", help="実際に削除・取り直しを行う")
    parser.add_argument("--limit", type=int, default=0, help="処理する投稿数の上限")
    parser.add_argument("--tweet-id", action="append", help="対象を明示指定する")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    connection = sqlite3.connect(DB_PATH, timeout=60)
    suspects = args.tweet_id or find_suspects(connection, args.handle)
    if args.limit:
        suspects = suspects[: args.limit]
    print("取り直し対象: %d 投稿" % len(suspects))
    for tweet_id in suspects:
        paths = images_of(connection, tweet_id)
        print("  %s  画像%d枚" % (tweet_id, len(paths)))
    if not args.apply:
        print("\n--dry-run（既定）。実行するには --apply を付けること。")
        return 0
    if not AUTH_STATE_PATH.exists():
        raise SystemExit("ログイン state が無い: %s" % AUTH_STATE_PATH)

    repaired = skipped = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        try:
            context = browser.new_context(
                storage_state=str(AUTH_STATE_PATH),
                user_agent=CHROME_USER_AGENT,
                locale="ja-JP",
                timezone_id="Asia/Tokyo",
                viewport={"width": 1280, "height": 800},
            )
            context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page = context.new_page()
            texts = dict(connection.execute("SELECT tweet_id, COALESCE(full_text, tweet_text, '') FROM seen_tweets"))
            for tweet_id in suspects:
                # 取得できてから消す。逆にすると失敗時に元も失う。
                try:
                    blobs = fetch_images(page, args.handle, tweet_id, texts.get(tweet_id))
                except PlaywrightError as error:
                    LOGGER.warning("%s: 取り直しに失敗: %s", tweet_id, error)
                    blobs = None
                if blobs is None:
                    skipped += 1
                    page.wait_for_timeout(3_000)
                    continue
                purge(connection, tweet_id, images_of(connection, tweet_id))
                fresh = save_images(connection, args.handle, tweet_id, blobs)
                connection.commit()
                repaired += 1
                LOGGER.info("%s: %d枚を取り直した", tweet_id, len(fresh))
                page.wait_for_timeout(3_000)
        finally:
            browser.close()

    print("\n取り直した投稿: %d / 触らなかった投稿: %d" % (repaired, skipped))
    print("画像の抽出は再実行が必要（extract_answers.py）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
