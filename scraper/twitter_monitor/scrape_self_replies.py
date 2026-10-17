"""各アカウントの「自分自身への返信」を別テーブル self_replies に集める。

なぜ要るか:
    予告に「狙い目はリプにぶら下げときます」(Kamacho_data、2026-10-17)のように、
    肝心の機種・台番号を返信に書くものがある。scrape_tweets.py はプロフィールの
    タイムラインを読み、返信を捨てる設計なので、この内容が一度も集まらない。

なぜ seen_tweets に入れないか:
    seen_tweets は prefilter.py → extract_answers.py の入力で、1行を1つの
    予告・結果報告として扱う。返信は「狙い目は A と B」のように日付やホールを
    持たない断片なので、混ぜると偽の予告が登録されうる。別テーブルに分け、
    朝の予測（scripts/run_morning_docs.py）が根拠として読むだけにする。

読み方:
    https://x.com/<handle>/with_replies を読む。次の条件をすべて満たす投稿だけ保存する。
      - そのアカウント自身の投稿（/<handle>/status/<id> へのリンクを持つ）
      - リポストではない（固定は可）
      - 「返信先」に自分以外のアカウントが無い（自分自身への返信、またはスレッド続き）
      - seen_tweets に既にある通常の投稿ではない
    スレッドの続きは、X が親の直下に連ねて表示するときは「返信先」の印が付かない
    ことがあるので、印が無い投稿も、seen_tweets に無ければ候補にする。
    親ツイートの ID は画面から確実には取れないため、保存しない。
    親との対応は、同じアカウントの直前の予告と投稿時刻の近さで読む側が決める。

使い方:
    python scrape_self_replies.py [--handles A,B] [--days 2] [--max-scrolls 15]
"""

from __future__ import annotations

import argparse
import logging
import random
import re
import sqlite3
from datetime import date, datetime, timedelta

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from scrape_tweets import (
    ACCOUNT_WAIT_SECONDS,
    ACCOUNTS,
    AUTH_STATE_PATH,
    CHROME_USER_AGENT,
    DB_PATH,
    JST,
    PINNED_MARKER_RE,
    REPLY_MARKER_RE,
    SCROLL_STEP_PX,
    SCROLL_WAIT_SECONDS,
    STATUS_ID_RE,
    LoggedOutError,
    article_for_tweet,
    as_jst,
    download_images,
    now_jst,
    raise_if_logged_out,
    wait_for_tweets,
)

LOGGER = logging.getLogger(__name__)
MENTION_RE = re.compile(r"@([A-Za-z0-9_]+)")
DEFAULT_DAYS = 2
DEFAULT_MAX_SCROLLS = 15


def initialize_table(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS self_replies (
            tweet_id TEXT PRIMARY KEY,
            handle TEXT,
            tweet_url TEXT,
            tweet_text TEXT,
            posted_at_jst TEXT,
            scraped_at_jst TEXT,
            image_paths TEXT,
            reply_to_handles TEXT
        );
        """
    )
    connection.commit()


def replied_handles(article_text: str) -> list[str]:
    """「返信先: @a さん @b さん」の宛先を取り出す。印が無ければ空。"""
    marker = REPLY_MARKER_RE.search(article_text)
    if not marker:
        return []
    # 宛先は印の直後に並ぶ。本文中の @メンション を拾わないよう、印から2行までだけ見る。
    head = "\n".join(article_text[marker.end() :].split("\n")[:2])
    return [m.group(1) for m in MENTION_RE.finditer(head)]


def own_reply_data(article, handle: str):
    """自分への返信（またはスレッドの続き）なら (id, url, text, posted_at, reply_to) を返す。"""
    social_context = article.locator('[data-testid="socialContext"]')
    if social_context.count() > 0 and not PINNED_MARKER_RE.search(social_context.first.inner_text(timeout=3_000)):
        return None  # リポスト
    article_text = article.inner_text(timeout=3_000)
    targets = replied_handles(article_text)
    if any(t.lower() != handle.lower() for t in targets):
        return None  # 他人への返信（会話への割り込み）は対象外
    links = article.locator('a[href*="/status/"]')
    for index in range(links.count()):
        href = links.nth(index).get_attribute("href") or ""
        match = STATUS_ID_RE.search(href)
        if not match or not href.lower().startswith(f"/{handle.lower()}/status/"):
            continue
        text_node = article.locator('[data-testid="tweetText"]')
        text = text_node.first.inner_text() if text_node.count() else ""
        time_node = article.locator("time")
        posted = time_node.first.get_attribute("datetime") if time_node.count() else None
        return match.group(1), f"https://x.com{href}", text, as_jst(posted), targets
    return None


def crawl_replies(page, connection: sqlite3.Connection, handle: str, since: date, max_scrolls: int) -> int:
    page.goto(f"https://x.com/{handle}/with_replies", wait_until="domcontentloaded", timeout=45_000)
    page.wait_for_timeout(1_500)
    raise_if_logged_out(page)
    if not wait_for_tweets(page, handle):
        LOGGER.warning("%s: with_replies の記事を取得できなかった", handle)
        return 0

    inserted = 0
    processed: set[str] = set()
    stagnant = 0
    for scroll_index in range(max_scrolls):
        articles = page.locator('article[data-testid="tweet"]')
        new_ids = 0
        too_old = False
        for index in range(articles.count()):
            try:
                data = own_reply_data(articles.nth(index), handle)
            except PlaywrightTimeoutError as error:
                LOGGER.warning("%s: 読み込みの遅い記事を飛ばす (%d): %s", handle, index, error)
                continue
            if not data:
                continue
            tweet_id, url, text, posted, targets = data
            if tweet_id in processed:
                continue
            processed.add(tweet_id)
            new_ids += 1
            if posted and date.fromisoformat(posted[:10]) < since:
                too_old = True  # 固定ツイートが先頭に来るので、1件で止めず全体で判定する
                continue
            if connection.execute("SELECT 1 FROM seen_tweets WHERE tweet_id = ?", (tweet_id,)).fetchone():
                continue  # 通常の投稿としてすでに集まっている
            if connection.execute("SELECT 1 FROM self_replies WHERE tweet_id = ?", (tweet_id,)).fetchone():
                continue
            article = article_for_tweet(page, handle, tweet_id)
            image_paths = download_images(page, article, handle, tweet_id)
            connection.execute(
                "INSERT INTO self_replies VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (tweet_id, handle, url, text, posted, now_jst(), ",".join(image_paths), ",".join(targets)),
            )
            inserted += 1
        connection.commit()
        stagnant = 0 if new_ids else stagnant + 1
        if too_old and scroll_index >= 2:
            break
        if stagnant >= 3:
            break
        page.mouse.wheel(0, SCROLL_STEP_PX)
        page.wait_for_timeout(int(random.uniform(*SCROLL_WAIT_SECONDS) * 1_000))
    return inserted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--handles", help="カンマ区切り（省略時は config.py の全件）")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="何日前の投稿まで見るか")
    parser.add_argument("--max-scrolls", type=int, default=DEFAULT_MAX_SCROLLS)
    args = parser.parse_args()
    handles = [h.strip() for h in args.handles.split(",")] if args.handles else list(ACCOUNTS)
    unknown = [h for h in handles if h not in ACCOUNTS]
    if unknown:
        parser.error("config.py にないアカウント: %s" % ", ".join(unknown))
    if not AUTH_STATE_PATH.exists():
        raise SystemExit(f"Login state not found: {AUTH_STATE_PATH}")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    since = datetime.now(JST).date() - timedelta(days=args.days)

    total = 0
    with sqlite3.connect(DB_PATH) as connection:
        initialize_table(connection)
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
                for number, handle in enumerate(handles):
                    try:
                        count = crawl_replies(page, connection, handle, since, args.max_scrolls)
                        total += count
                        LOGGER.info("%s: 新規の自己返信 %d 件", handle, count)
                    except LoggedOutError as error:
                        LOGGER.error("%s", error)
                        break
                    except (PlaywrightError, PlaywrightTimeoutError, RuntimeError, ValueError) as error:
                        connection.commit()
                        LOGGER.error("%s failed: %s", handle, error)
                    if number + 1 < len(handles):
                        page.wait_for_timeout(int(random.uniform(*ACCOUNT_WAIT_SECONDS) * 1_000))
            finally:
                browser.close()
    print(f"Newly inserted self_replies rows: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
