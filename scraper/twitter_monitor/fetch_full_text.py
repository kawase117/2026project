"""タイムラインで折り畳まれた本文を、個別ページから取り直す。

なぜ要るか:
    予告の検証では本文そのものがデータになる。ところがタイムラインと検索結果の
    article は長文を途中で畳むため、collector が保存した tweet_text は
    130〜180 文字で切れている。「アンケート内容は下記3つで、全てが発動」の
    直後で切れる、というように、よりによって仕掛けの列挙が始まる位置で
    落ちるので、そのままでは何が予告されたのか読めない。

    個別ステータスページは畳まないので、そこから取り直す。

破壊的更新を避ける:
    元の tweet_text は上書きせず、full_text 列に入れる。折り畳みが起きて
    いない短い投稿でも両者は一致するはずで、一致しない場合に「どちらが
    正しいか」を後から確かめられるようにしておく。

対象は絞る:
    全ツイートを開くとアクセス数が跳ね上がる。--contains で本文に含まれる
    語（既に取れている先頭部分に対して効く）と期間で絞ってから使うこと。
"""

from __future__ import annotations

import argparse
import logging
import random
import sqlite3
import sys
import time

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from config import AUTH_STATE_PATH, DB_PATH

LOGGER = logging.getLogger("fetch_full_text")

CHROME_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
MIN_DELAY = 6.0
MAX_DELAY = 12.0


def ensure_column(connection: sqlite3.Connection) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(seen_tweets)")}
    if "full_text" not in columns:
        connection.execute("ALTER TABLE seen_tweets ADD COLUMN full_text TEXT")
        connection.commit()


def select_targets(connection: sqlite3.Connection, args) -> list[tuple[str, str, str]]:
    conditions = ["full_text IS NULL", "tweet_url IS NOT NULL"]
    parameters: list[str] = []
    if args.tweet_ids:
        # 分析中に本文が切れている投稿を見つけたら、その場で個別に取り直す。
        # 日次の --any-of は監視ホール名でしか絞れず、朝の収集が遅れると
        # 登録の判断に間に合わない（2026-09-14 は 08:10 時点で未実行だった）。
        placeholders = ",".join("?" for _ in args.tweet_ids)
        conditions.append(f"tweet_id IN ({placeholders})")
        parameters.extend(args.tweet_ids)
    if args.handles:
        placeholders = ",".join("?" for _ in args.handles)
        conditions.append(f"handle IN ({placeholders})")
        parameters.extend(args.handles)
    if args.since:
        conditions.append("posted_at_jst >= ?")
        parameters.append(args.since)
    for needle in args.contains:
        conditions.append("tweet_text LIKE ?")
        parameters.append(f"%{needle}%")
    if args.any_of:
        # OR 条件。監視ホールのどれかに触れている投稿だけを開くのに使う。
        # 収集した本文の 7〜9% しか対象ホールに触れておらず、全件を開くと
        # 1日80件・14分かかるうえ新着に追いつかない。
        conditions.append("(" + " OR ".join("tweet_text LIKE ?" for _ in args.any_of) + ")")
        parameters.extend(f"%{needle}%" for needle in args.any_of)
    query = (
        "SELECT tweet_id, tweet_url, tweet_text FROM seen_tweets WHERE "
        + " AND ".join(conditions)
        + " ORDER BY posted_at_jst DESC"
    )
    if args.limit:
        query += f" LIMIT {int(args.limit)}"
    return connection.execute(query, parameters).fetchall()


def read_full_text(page, url: str) -> str | None:
    page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    page.wait_for_timeout(1_200)
    article = page.locator('article[data-testid="tweet"]').first
    try:
        article.wait_for(state="visible", timeout=20_000)
    except PlaywrightTimeoutError:
        return None
    # 「さらに表示」が残っている場合は開く。個別ページでは通常出ないが、
    # 引用の入れ子などで現れることがある。
    for label in ("さらに表示", "Show more"):
        more = article.get_by_role("button", name=label)
        if more.count():
            try:
                more.first.click(timeout=3_000)
                page.wait_for_timeout(600)
            except PlaywrightTimeoutError:
                pass
    node = article.locator('[data-testid="tweetText"]')
    if not node.count():
        return ""
    return node.first.inner_text()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handles", type=lambda v: [s for s in v.split(",") if s], default=[])
    parser.add_argument("--since", help="この日以降の投稿だけ (YYYY-MM-DD)")
    parser.add_argument("--contains", action="append", default=[], help="本文に含まれる語で絞る（複数可、AND）")
    parser.add_argument(
        "--any-of",
        type=lambda v: [s for s in v.split(",") if s],
        default=[],
        help="いずれかを含む投稿だけ（カンマ区切り、OR）。ホール名の表記ゆれを並べるのに使う",
    )
    parser.add_argument(
        "--tweet-ids",
        type=lambda v: [s for s in v.split(",") if s],
        default=[],
        help="この tweet_id だけを取り直す（カンマ区切り）。分析中に切れた本文を見つけたときに使う",
    )
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    connection = sqlite3.connect(DB_PATH, timeout=60)
    ensure_column(connection)
    targets = select_targets(connection, args)
    LOGGER.info("対象 %d 件", len(targets))
    if not targets:
        return 0

    filled = extended = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            storage_state=str(AUTH_STATE_PATH),
            user_agent=CHROME_USER_AGENT,
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
            viewport={"width": 1280, "height": 900},
        )
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = context.new_page()
        try:
            for index, (tweet_id, url, old_text) in enumerate(targets, 1):
                try:
                    text = read_full_text(page, url)
                except PlaywrightTimeoutError as error:
                    LOGGER.warning("%s: 取得できません: %s", tweet_id, error)
                    continue
                if text is None:
                    LOGGER.warning("%s: 記事が表示されません（削除・非公開の可能性）", tweet_id)
                    continue
                connection.execute("UPDATE seen_tweets SET full_text = ? WHERE tweet_id = ?", (text, tweet_id))
                connection.commit()
                filled += 1
                if len(text) > len(old_text or ""):
                    extended += 1
                if index % 10 == 0:
                    LOGGER.info("%d/%d 完了", index, len(targets))
                time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
        finally:
            context.close()
            browser.close()

    LOGGER.info("full_text を埋めた: %d 件 / うち本文が伸びた: %d 件", filled, extended)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
