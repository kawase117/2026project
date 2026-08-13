"""Backfill configured X accounts through overlapping live-search date windows."""

import argparse
import logging
import random
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from config import ACCOUNTS, AUTH_STATE_PATH, DB_PATH
from scrape_tweets import (
    CHROME_USER_AGENT,
    LoggedOutError,
    download_images,
    initialize_database,
    own_tweet_data,
    page_has_rate_limit,
    raise_if_logged_out,
    store_tweet,
)


LOGGER = logging.getLogger(__name__)
JST = ZoneInfo("Asia/Tokyo")
DEFAULT_SINCE = date(2026, 6, 1)
DEFAULT_WINDOW_DAYS = 7
DEFAULT_MIN_DELAY = 15.0
DEFAULT_MAX_DELAY = 30.0
SCROLL_DELAY_SECONDS = (2.0, 4.0)
BACKOFF_SECONDS = (60, 180, 600)
RESULT_WAIT_SECONDS = 15
MAX_STAGNANT_SCROLLS = 3
EMPTY_RESULT_RE = re.compile(
    r"(?:検索結果はありません|結果はありません|No results(?: for)?|Try searching for something else)",
    re.IGNORECASE,
)
LOGIN_TEXT_RE = re.compile(r"(?:ログインして|ログインしてください|Sign in to X|Log in to X)", re.IGNORECASE)


@dataclass(frozen=True)
class DateWindow:
    start: date
    end: date


@dataclass
class WindowResult:
    status: str
    inserted: int = 0
    eligible: int = 0
    reason: str = ""


def parse_date(value: str) -> date:
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


def nonnegative_float(value: str) -> float:
    try:
        number = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("数値で指定してください") from error
    if number < 0:
        raise argparse.ArgumentTypeError("0以上で指定してください")
    return number


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="X検索を重複する日付窓に分割し、本人投稿をstate.dbへバックフィルします。"
    )
    parser.add_argument(
        "--since",
        type=parse_date,
        default=DEFAULT_SINCE,
        metavar="YYYY-MM-DD",
        help=f"検索開始日（既定: {DEFAULT_SINCE.isoformat()}）。",
    )
    parser.add_argument(
        "--until",
        type=parse_date,
        default=None,
        metavar="YYYY-MM-DD",
        help="検索終了日（排他的、省略時はJSTの今日）。",
    )
    parser.add_argument(
        "--handles",
        help="対象アカウントをカンマ区切りで指定します（省略時はconfig.pyの全件）。",
    )
    parser.add_argument(
        "--window-days",
        type=positive_int,
        default=DEFAULT_WINDOW_DAYS,
        metavar="N",
        help=f"窓を進める日数（各検索窓は境界保護の1日を加える、既定: {DEFAULT_WINDOW_DAYS}）。",
    )
    parser.add_argument(
        "--min-delay",
        type=nonnegative_float,
        default=DEFAULT_MIN_DELAY,
        metavar="SECONDS",
        help=f"窓間ランダム待機の最小秒数（既定: {DEFAULT_MIN_DELAY:g}）。",
    )
    parser.add_argument(
        "--max-delay",
        type=nonnegative_float,
        default=DEFAULT_MAX_DELAY,
        metavar="SECONDS",
        help=f"窓間ランダム待機の最大秒数（既定: {DEFAULT_MAX_DELAY:g}）。",
    )
    parser.add_argument(
        "--redo-failed",
        action="store_true",
        help="既にstatus=failedで記録されている窓だけを再試行します。",
    )
    args = parser.parse_args()
    args.until = args.until or datetime.now(JST).date()
    if args.until <= args.since:
        parser.error("--until は --since より後の日付を指定してください（untilは排他的です）")
    if args.min_delay > args.max_delay:
        parser.error("--min-delay は --max-delay 以下にしてください")
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


def build_windows(since: date, until: date, window_days: int) -> list[DateWindow]:
    """Build windows with a one-day overlap, matching [06-01,06-09), [06-08,06-16)."""
    windows: list[DateWindow] = []
    start = since
    while start < until:
        end = min(start + timedelta(days=window_days + 1), until)
        windows.append(DateWindow(start, end))
        if end == until:
            break
        start = end - timedelta(days=1)
    return windows


def search_url(handle: str, window: DateWindow) -> str:
    query = f"from:{handle} since:{window.start.isoformat()} until:{window.end.isoformat()}"
    return f"https://x.com/search?q={quote(query, safe='')}&f=live"


def initialize_progress_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS backfill_progress (
            handle TEXT,
            window_start TEXT,
            window_end TEXT,
            found_count INTEGER,
            status TEXT,
            completed_at_jst TEXT,
            PRIMARY KEY (handle, window_start)
        )
        """
    )
    connection.commit()


def progress_status(connection: sqlite3.Connection, handle: str, window: DateWindow) -> str | None:
    row = connection.execute(
        """
        SELECT status FROM backfill_progress
        WHERE handle = ? AND window_start = ? AND window_end = ?
        """,
        (handle, window.start.isoformat(), window.end.isoformat()),
    ).fetchone()
    return row[0] if row else None


def should_process(status: str | None, redo_failed: bool) -> bool:
    if redo_failed:
        return status == "failed"
    return status not in {"done", "empty"}


def save_progress(
    connection: sqlite3.Connection,
    handle: str,
    window: DateWindow,
    found_count: int,
    status: str,
) -> None:
    connection.execute(
        """
        INSERT INTO backfill_progress
            (handle, window_start, window_end, found_count, status, completed_at_jst)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(handle, window_start) DO UPDATE SET
            window_end=excluded.window_end,
            found_count=excluded.found_count,
            status=excluded.status,
            completed_at_jst=excluded.completed_at_jst
        """,
        (
            handle,
            window.start.isoformat(),
            window.end.isoformat(),
            found_count,
            status,
            datetime.now(JST).isoformat(),
        ),
    )
    connection.commit()


def body_text(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=3_000)
    except PlaywrightTimeoutError:
        return ""


def raise_if_auth_lost(page) -> None:
    raise_if_logged_out(page)
    login_form_visible = page.locator('input[autocomplete="username"]').count() > 0
    text = body_text(page)
    if login_form_visible or (LOGIN_TEXT_RE.search(text) and "x.com/search" not in page.url):
        raise LoggedOutError("Xのログインが切れています。import_cookies.pyを再実行して認証stateを更新してください。")


def classify_initial_result(page) -> str:
    """Return tweets, empty, rate_limit, or unavailable without conflating zero results."""
    deadline = datetime.now().timestamp() + RESULT_WAIT_SECONDS
    while datetime.now().timestamp() < deadline:
        raise_if_auth_lost(page)
        if page_has_rate_limit(page):
            return "rate_limit"
        if page.locator('article[data-testid="tweet"]').count() > 0:
            return "tweets"
        if EMPTY_RESULT_RE.search(body_text(page)):
            return "empty"
        page.wait_for_timeout(1_000)
    return "unavailable"


def visible_status_ids(page) -> set[str]:
    ids: set[str] = set()
    links = page.locator('article[data-testid="tweet"] a[href*="/status/"]')
    for index in range(links.count()):
        href = links.nth(index).get_attribute("href") or ""
        match = re.search(r"/status/(\d+)", href)
        if match:
            ids.add(match.group(1))
    return ids


def collect_loaded_results(page, connection: sqlite3.Connection, handle: str) -> WindowResult:
    inserted = 0
    eligible_ids: set[str] = set()
    seen_page_ids: set[str] = set()
    stagnant_scrolls = 0

    while stagnant_scrolls < MAX_STAGNANT_SCROLLS:
        raise_if_auth_lost(page)
        if page_has_rate_limit(page):
            return WindowResult("retry", inserted, len(eligible_ids), "レート制限を検知")

        visible_ids = visible_status_ids(page)
        new_ids = visible_ids - seen_page_ids
        seen_page_ids.update(visible_ids)
        stagnant_scrolls = 0 if new_ids else stagnant_scrolls + 1

        articles = page.locator('article[data-testid="tweet"]')
        for index in range(articles.count()):
            article = articles.nth(index)
            try:
                data = own_tweet_data(article, handle)
            except PlaywrightTimeoutError as error:
                LOGGER.warning("%s: 読み込みの遅い記事%dをスキップ: %s", handle, index, error)
                continue
            if not data:
                continue
            tweet_id = data[0]
            if tweet_id in eligible_ids:
                continue
            eligible_ids.add(tweet_id)
            if store_tweet(connection, page, article, handle, data):
                inserted += 1

        if stagnant_scrolls >= MAX_STAGNANT_SCROLLS:
            break
        page.mouse.wheel(0, 2_500)
        page.wait_for_timeout(int(random.uniform(*SCROLL_DELAY_SECONDS) * 1_000))

    status = "done" if eligible_ids else "empty"
    return WindowResult(status, inserted, len(eligible_ids), "記事増加が停止")


def collect_window(
    page,
    connection: sqlite3.Connection,
    handle: str,
    window: DateWindow,
) -> WindowResult:
    inserted_total = 0
    had_eligible = False
    url = search_url(handle, window)

    for attempt in range(len(BACKOFF_SECONDS) + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            outcome = classify_initial_result(page)
            if outcome == "empty":
                status = "done" if had_eligible else "empty"
                return WindowResult(status, inserted_total, int(had_eligible), "検索結果なし")
            if outcome == "tweets":
                result = collect_loaded_results(page, connection, handle)
                inserted_total += result.inserted
                had_eligible = had_eligible or result.eligible > 0
                if result.status in {"done", "empty"}:
                    if had_eligible:
                        result.status = "done"
                    result.inserted = inserted_total
                    return result
                outcome = "rate_limit"
        except LoggedOutError:
            raise
        except (PlaywrightError, PlaywrightTimeoutError) as error:
            outcome = "unavailable"
            LOGGER.warning(
                "%s | %s..%s | 検索ページ取得エラー: %s",
                handle,
                window.start,
                window.end,
                error,
            )

        if attempt == len(BACKOFF_SECONDS):
            reason = "レート制限" if outcome == "rate_limit" else "記事取得不能"
            return WindowResult("failed", inserted_total, int(had_eligible), reason)
        delay = BACKOFF_SECONDS[attempt]
        LOGGER.warning(
            "%s | %s..%s | %s。%d秒後に再試行 (%d/%d)",
            handle,
            window.start,
            window.end,
            "レート制限" if outcome == "rate_limit" else "記事を取得できません",
            delay,
            attempt + 1,
            len(BACKOFF_SECONDS),
        )
        page.wait_for_timeout(delay * 1_000)

    return WindowResult("failed", inserted_total, int(had_eligible), "予期しない終了")


def account_status_counts(connection: sqlite3.Connection, handle: str, windows: list[DateWindow]) -> dict[str, int]:
    counts = {"done": 0, "empty": 0, "failed": 0}
    for window in windows:
        status = progress_status(connection, handle, window)
        if status in counts:
            counts[status] += 1
    return counts


def main() -> int:
    args = parse_args()
    if not AUTH_STATE_PATH.exists():
        print(f"ログインstateがありません: {AUTH_STATE_PATH}")
        print("import_cookies.pyを再実行してから再開してください。")
        return 1

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    windows = build_windows(args.since, args.until, args.window_days)
    total_inserted = 0
    total_processed = 0
    auth_lost = False
    interrupted = False

    with sqlite3.connect(DB_PATH) as connection:
        initialize_database(connection)
        initialize_progress_table(connection)
        runnable = sum(
            should_process(progress_status(connection, handle, window), args.redo_failed)
            for handle in args.handles
            for window in windows
        )
        remaining = runnable

        try:
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

                    for handle in args.handles:
                        account_inserted = 0
                        for window in windows:
                            old_status = progress_status(connection, handle, window)
                            if not should_process(old_status, args.redo_failed):
                                LOGGER.info(
                                    "%s | %s..%s | skip status=%s",
                                    handle,
                                    window.start,
                                    window.end,
                                    old_status or "未記録",
                                )
                                continue
                            try:
                                result = collect_window(page, connection, handle, window)
                            except LoggedOutError as error:
                                connection.commit()
                                LOGGER.critical("%s", error)
                                auth_lost = True
                                break
                            except (PlaywrightError, PlaywrightTimeoutError, RuntimeError, ValueError) as error:
                                connection.commit()
                                LOGGER.error(
                                    "%s | %s..%s | 失敗: %s",
                                    handle,
                                    window.start,
                                    window.end,
                                    error,
                                )
                                result = WindowResult("failed", reason=str(error))

                            save_progress(connection, handle, window, result.inserted, result.status)
                            account_inserted += result.inserted
                            total_inserted += result.inserted
                            total_processed += 1
                            remaining -= 1
                            LOGGER.info(
                                "%s | [%s,%s) | 取得%d件 | 累計%d件 | status=%s (%s)",
                                handle,
                                window.start,
                                window.end,
                                result.inserted,
                                total_inserted,
                                result.status,
                                result.reason,
                            )
                            if remaining > 0:
                                delay = random.uniform(args.min_delay, args.max_delay)
                                LOGGER.info("次の検索窓まで%.1f秒待機します", delay)
                                page.wait_for_timeout(int(delay * 1_000))

                        counts = account_status_counts(connection, handle, windows)
                        LOGGER.info(
                            "%s: 新規%d件 (窓%d個中、done=%d, empty=%d, failed=%d)",
                            handle,
                            account_inserted,
                            len(windows),
                            counts["done"],
                            counts["empty"],
                            counts["failed"],
                        )
                        if auth_lost:
                            break
                finally:
                    browser.close()
        except KeyboardInterrupt:
            connection.commit()
            interrupted = True
            LOGGER.warning("Ctrl+Cを検知しました。取得済みデータをcommitして終了します。")

        overall = {"done": 0, "empty": 0, "failed": 0}
        for handle in args.handles:
            counts = account_status_counts(connection, handle, windows)
            for status in overall:
                overall[status] += counts[status]

    print(
        "全体サマリ: "
        f"新規{total_inserted}件、処理窓{total_processed}/{len(windows) * len(args.handles)}、"
        f"done={overall['done']}, empty={overall['empty']}, failed={overall['failed']}"
    )
    if auth_lost:
        print("Xのログインが切れました。import_cookies.pyを再実行してから再開してください。")
        return 1
    if interrupted:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
