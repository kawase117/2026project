"""Crawl configured X profile timelines using a manually saved Playwright session."""

import argparse
import logging
import random
import re
import sqlite3
from datetime import date, datetime
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from config import ACCOUNTS, AUTH_STATE_PATH, DB_PATH, IMAGES_DIR


LOGGER = logging.getLogger(__name__)
JST = ZoneInfo("Asia/Tokyo")
MAX_SCROLLS_PER_ACCOUNT = 20
CHROME_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)
SCROLL_WAIT_SECONDS = (1.5, 3.5)
ACCOUNT_WAIT_SECONDS = (5.0, 15.0)
BACKOFF_SECONDS = (60, 120, 240)
MAX_STAGNANT_SCROLLS = 3
STATUS_ID_RE = re.compile(r"/status/(\d+)")
REPLY_MARKER_RE = re.compile(r"(?:Replying to|返信先|返信しています)", re.IGNORECASE)
RATE_LIMIT_RE = re.compile(r"(?:Rate limit exceeded|レート制限|利用制限)", re.IGNORECASE)


class LoggedOutError(RuntimeError):
    """Raised when the saved X session is no longer authenticated."""


def now_jst() -> str:
    return datetime.now(JST).isoformat()


def as_jst(iso_datetime: str | None) -> str | None:
    if not iso_datetime:
        return None
    return datetime.fromisoformat(iso_datetime.replace("Z", "+00:00")).astimezone(JST).isoformat()


def parse_until_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("YYYY-MM-DD形式で指定してください") from error


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("整数で指定してください") from error
    if number < 1:
        raise argparse.ArgumentTypeError("1以上で指定してください")
    return number


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Xアカウントの投稿と画像を収集します。")
    parser.add_argument(
        "--until-date",
        type=parse_until_date,
        metavar="YYYY-MM-DD",
        help="JST基準で指定日当日まで遡るバックフィルモードを有効にします。",
    )
    parser.add_argument(
        "--handles",
        help="対象アカウントをカンマ区切りで指定します（省略時はconfig.pyの全件）。",
    )
    parser.add_argument(
        "--max-scrolls",
        type=positive_int,
        default=MAX_SCROLLS_PER_ACCOUNT,
        metavar="N",
        help=f"アカウントごとのスクロール上限（既定: {MAX_SCROLLS_PER_ACCOUNT}）。",
    )
    args = parser.parse_args()
    if args.handles:
        handles = list(dict.fromkeys(item.strip() for item in args.handles.split(",") if item.strip()))
        if not handles:
            parser.error("--handles に1件以上のアカウントを指定してください")
        unknown = [handle for handle in handles if handle not in ACCOUNTS]
        if unknown:
            parser.error(f"config.pyにないアカウントです: {', '.join(unknown)}")
        args.handles = handles
    else:
        args.handles = list(ACCOUNTS)
    return args


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS accounts (
            handle TEXT PRIMARY KEY,
            hall TEXT,
            role TEXT,
            last_seen_tweet_id TEXT
        );
        CREATE TABLE IF NOT EXISTS seen_tweets (
            tweet_id TEXT PRIMARY KEY,
            handle TEXT,
            tweet_url TEXT,
            tweet_text TEXT,
            posted_at_jst TEXT,
            scraped_at_jst TEXT,
            has_image INTEGER
        );
        CREATE TABLE IF NOT EXISTS tweet_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tweet_id TEXT,
            image_path TEXT,
            downloaded_at_jst TEXT
        );
        """
    )
    for handle, details in ACCOUNTS.items():
        connection.execute(
            """
            INSERT INTO accounts(handle, hall, role)
            VALUES (?, ?, ?)
            ON CONFLICT(handle) DO UPDATE SET hall=excluded.hall, role=excluded.role
            """,
            (handle, details["hall"], details["role"]),
        )
    connection.commit()


def image_download_url(source_url: str) -> str:
    parsed = urlparse(source_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({"format": "jpg", "name": "large"})
    return urlunparse(parsed._replace(query=urlencode(query)))


def is_logged_out(page) -> bool:
    return "/login" in page.url or "/i/flow/login" in page.url


def raise_if_logged_out(page) -> None:
    if is_logged_out(page):
        raise LoggedOutError("Xのログインが切れています。import_cookies.pyを再実行して認証stateを更新してください。")


def own_tweet_data(article, handle: str):
    """Return own-post metadata or None for reposts, replies, and unusable cards."""
    if article.locator('[data-testid="socialContext"]').count() > 0:
        return None
    article_text = article.inner_text(timeout=3_000)
    if REPLY_MARKER_RE.search(article_text):
        return None

    status_links = article.locator('a[href*="/status/"]')
    for index in range(status_links.count()):
        href = status_links.nth(index).get_attribute("href") or ""
        match = STATUS_ID_RE.search(href)
        if not match:
            continue
        if not href.lower().startswith(f"/{handle.lower()}/status/"):
            continue
        tweet_id = match.group(1)
        text_node = article.locator('[data-testid="tweetText"]')
        tweet_text = text_node.first.inner_text() if text_node.count() else ""
        time_node = article.locator("time")
        posted_at = time_node.first.get_attribute("datetime") if time_node.count() else None
        return tweet_id, f"https://x.com{href}", tweet_text, as_jst(posted_at)
    return None


def download_images(page, article, handle: str, tweet_id: str) -> list[str]:
    image_nodes = article.locator('img[src*="pbs.twimg.com/media"]')
    saved_paths: list[str] = []
    target_dir = IMAGES_DIR / handle
    target_dir.mkdir(parents=True, exist_ok=True)
    for index in range(image_nodes.count()):
        source_url = image_nodes.nth(index).get_attribute("src")
        if not source_url:
            continue
        target_path = target_dir / f"{tweet_id}_{index + 1}.jpg"
        if target_path.exists():
            saved_paths.append(str(target_path))
            continue
        try:
            response = page.context.request.get(image_download_url(source_url), timeout=30_000)
            if not response.ok:
                raise RuntimeError(f"HTTP {response.status}")
            target_path.write_bytes(response.body())
            saved_paths.append(str(target_path))
        except (PlaywrightError, RuntimeError) as error:
            LOGGER.warning("Image download failed for %s: %s", target_path, error)
        except OSError as error:
            LOGGER.warning("Could not save image %s: %s", target_path, error)
    return saved_paths


def update_last_seen_max(connection: sqlite3.Connection, handle: str, tweet_id: str) -> None:
    row = connection.execute("SELECT last_seen_tweet_id FROM accounts WHERE handle = ?", (handle,)).fetchone()
    current_id = row[0] if row else None
    if current_id is None or int(tweet_id) > int(current_id):
        connection.execute("UPDATE accounts SET last_seen_tweet_id = ? WHERE handle = ?", (tweet_id, handle))


def store_tweet(connection, page, article, handle: str, data: tuple) -> bool:
    tweet_id, tweet_url, tweet_text, posted_at = data
    if connection.execute("SELECT 1 FROM seen_tweets WHERE tweet_id = ?", (tweet_id,)).fetchone():
        update_last_seen_max(connection, handle, tweet_id)
        connection.commit()
        return False
    image_paths = download_images(page, article, handle, tweet_id)
    connection.execute(
        """
        INSERT INTO seen_tweets
        (tweet_id, handle, tweet_url, tweet_text, posted_at_jst, scraped_at_jst, has_image)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (tweet_id, handle, tweet_url, tweet_text, posted_at, now_jst(), int(bool(image_paths))),
    )
    for image_path in image_paths:
        exists = connection.execute(
            "SELECT 1 FROM tweet_images WHERE tweet_id = ? AND image_path = ?",
            (tweet_id, image_path),
        ).fetchone()
        if not exists:
            connection.execute(
                "INSERT INTO tweet_images(tweet_id, image_path, downloaded_at_jst) VALUES (?, ?, ?)",
                (tweet_id, image_path, now_jst()),
            )
    update_last_seen_max(connection, handle, tweet_id)
    connection.commit()
    return True


def page_has_rate_limit(page) -> bool:
    try:
        body_text = page.locator("body").inner_text(timeout=3_000)
    except PlaywrightTimeoutError:
        return False
    return bool(RATE_LIMIT_RE.search(body_text))


def wait_for_tweets(page, handle: str) -> bool:
    """Wait with exponential backoff when X is limited or tweet cards disappear."""
    for attempt in range(len(BACKOFF_SECONDS) + 1):
        raise_if_logged_out(page)
        article_count = page.locator('article[data-testid="tweet"]').count()
        limited = page_has_rate_limit(page)
        if article_count > 0 and not limited:
            return True
        if attempt == len(BACKOFF_SECONDS):
            reason = "rate limit" if limited else "tweet articles unavailable"
            LOGGER.error("%s: %s after %d retries; giving up account", handle, reason, attempt)
            return False
        delay = BACKOFF_SECONDS[attempt]
        reason = "rate limit detected" if limited else "tweet articles unavailable"
        LOGGER.warning("%s: %s; retrying in %d seconds", handle, reason, delay)
        page.wait_for_timeout(delay * 1_000)
    return False


def visible_status_ids(page) -> set[str]:
    ids: set[str] = set()
    links = page.locator('article[data-testid="tweet"] a[href*="/status/"]')
    for index in range(links.count()):
        match = STATUS_ID_RE.search(links.nth(index).get_attribute("href") or "")
        if match:
            ids.add(match.group(1))
    return ids


def crawl_account(
    page,
    connection: sqlite3.Connection,
    handle: str,
    until_date: date | None,
    max_scrolls: int,
) -> tuple[int, date | None, bool, str]:
    row = connection.execute("SELECT last_seen_tweet_id FROM accounts WHERE handle = ?", (handle,)).fetchone()
    last_seen_id = row[0] if row else None
    page.goto(f"https://x.com/{handle}", wait_until="domcontentloaded", timeout=45_000)
    page.wait_for_timeout(1_500)
    raise_if_logged_out(page)
    if not wait_for_tweets(page, handle):
        return 0, None, False, "記事取得失敗"

    backfill = until_date is not None
    inserted = 0
    oldest_date: date | None = None
    target_reached = False
    reached_last_seen = False
    seen_page_ids: set[str] = set()
    processed_ids: set[str] = set()
    stagnant_scrolls = 0
    stop_reason = "スクロール上限到達"

    for scroll_index in range(max_scrolls):
        if not wait_for_tweets(page, handle):
            stop_reason = "記事取得失敗"
            break
        visible_ids = visible_status_ids(page)
        new_visible_ids = visible_ids - seen_page_ids
        seen_page_ids.update(visible_ids)
        if new_visible_ids:
            stagnant_scrolls = 0
        else:
            stagnant_scrolls += 1

        articles = page.locator('article[data-testid="tweet"]')
        stop_for_date = False
        for index in range(articles.count()):
            try:
                data = own_tweet_data(articles.nth(index), handle)
            except PlaywrightTimeoutError as error:
                LOGGER.warning("%s: skipping slow-loading article %d: %s", handle, index, error)
                continue
            if not data:
                continue
            tweet_id, _, _, posted_at = data
            if tweet_id in processed_ids:
                continue
            processed_ids.add(tweet_id)

            posted_date = date.fromisoformat(posted_at[:10]) if posted_at else None
            if posted_date is not None and (oldest_date is None or posted_date < oldest_date):
                oldest_date = posted_date
            if backfill and posted_date is not None:
                if posted_date <= until_date:
                    target_reached = True
                if posted_date < until_date:
                    stop_for_date = True
                    stop_reason = "目標日より古い投稿に到達"
                    break

            if not backfill:
                if last_seen_id and tweet_id == last_seen_id:
                    reached_last_seen = True
                    continue
                if last_seen_id and int(tweet_id) <= int(last_seen_id):
                    continue

            if store_tweet(connection, page, articles.nth(index), handle, data):
                inserted += 1

        connection.commit()
        oldest_label = oldest_date.isoformat() if oldest_date else "不明"
        LOGGER.info(
            "%s: progress scroll=%d/%d, oldest posted_at_jst=%s",
            handle,
            scroll_index + 1,
            max_scrolls,
            oldest_label,
        )
        if stop_for_date:
            break
        if not backfill and reached_last_seen:
            stop_reason = "last_seen_tweet_id到達"
            break
        if stagnant_scrolls >= MAX_STAGNANT_SCROLLS:
            stop_reason = f"記事増加なし{MAX_STAGNANT_SCROLLS}回"
            break
        if scroll_index + 1 < max_scrolls:
            page.mouse.wheel(0, 2_000)
            page.wait_for_timeout(int(random.uniform(*SCROLL_WAIT_SECONDS) * 1_000))

    return inserted, oldest_date, target_reached, stop_reason


def main() -> int:
    args = parse_args()
    if not AUTH_STATE_PATH.exists():
        raise SystemExit(f"Login state not found: {AUTH_STATE_PATH}. import_cookies.pyを再実行してください。")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    total_inserted = 0
    interrupted = False
    auth_lost = False

    with sqlite3.connect(DB_PATH) as connection:
        try:
            initialize_database(connection)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"],
                )
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
                    for handle_index, handle in enumerate(args.handles):
                        try:
                            count, oldest_date, target_reached, stop_reason = crawl_account(
                                page, connection, handle, args.until_date, args.max_scrolls
                            )
                            total_inserted += count
                            oldest_label = oldest_date.isoformat() if oldest_date else "不明"
                            target_label = "Yes" if target_reached else "No"
                            if args.until_date:
                                LOGGER.info(
                                    "%s: 新規%d件、到達した最古日=%s、目標日到達=%s (%s)",
                                    handle,
                                    count,
                                    oldest_label,
                                    target_label,
                                    stop_reason,
                                )
                                if not target_reached:
                                    LOGGER.warning(
                                        "%s: 目標日%sに未到達。到達した最古日=%s、終了理由=%s",
                                        handle,
                                        args.until_date.isoformat(),
                                        oldest_label,
                                        stop_reason,
                                    )
                            else:
                                LOGGER.info("%s: %d new own posts", handle, count)
                        except LoggedOutError as error:
                            connection.commit()
                            if args.until_date:
                                LOGGER.critical("%s バックフィルを全体中断します", error)
                                auth_lost = True
                                break
                            LOGGER.error("%s failed: %s", handle, error)
                        except (PlaywrightError, PlaywrightTimeoutError, RuntimeError, ValueError) as error:
                            connection.commit()
                            LOGGER.error("%s failed: %s", handle, error)
                        if handle_index + 1 < len(args.handles):
                            delay = random.uniform(*ACCOUNT_WAIT_SECONDS)
                            LOGGER.info("次のアカウントまで%.1f秒待機します", delay)
                            page.wait_for_timeout(int(delay * 1_000))
                finally:
                    browser.close()
        except KeyboardInterrupt:
            connection.commit()
            interrupted = True
            LOGGER.warning("Ctrl+Cを検知しました。取得済みデータをcommitして終了します。")

    print(f"Newly inserted seen_tweets rows: {total_inserted}")
    if auth_lost:
        print("Xのログインが切れました。import_cookies.pyを再実行してから再開してください。")
        return 1
    if interrupted:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
