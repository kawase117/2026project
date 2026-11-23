"""任意のXアカウントを「手法研究用コーパス」として収集・書き出しする。

監視対象（config.ACCOUNTS）ではないアカウントを、分析手法を学ぶ目的で
まとめて読みたいときに使う。本番の state.db とは別の research.db に貯める。

設計上の判断:

1. **プロフィールTLは使わない。日付窓検索だけを使う。**
   プロフィールTLのページングは約2週半で「エラーを出さずに」沈黙する
   （2026-09-05 の実行が226件の成功を報告しながら19日分を落とした実績あり）。
   数ヶ月分をまとめて掘る用途ではこの罠に必ず当たるので、最初から
   backfill_search の日付窓検索（from:handle since: until:）だけを回す。

2. **収集先DBを分ける。**
   seen_tweets に研究用アカウントを混ぜると、prefilter → extract_answers →
   infer_hall の抽出パイプラインが「ホールの答え合わせ投稿」として
   扱ってしまう。研究用の投稿は台番号ラベルの根拠にしてはいけない。

3. **窓ごとの進捗を残す。**
   backfill_progress をそのまま使うので、レート制限で落ちても
   同じコマンドを再実行すれば未処理の窓から再開する。

画像は download_images をそのまま使うので images/<handle>/ に落ちる
（.gitignore 済み）。research.db も .gitignore 済みで、
コミットするのは research/<handle>.md / .jsonl のコーパスだけ。

収集されるのは本人の非リプライ投稿のみ（own_tweet_data の仕様）。
リプライでの補足解説は取れないので、本文中で議論が完結していない
アカウントではその点を割り引いて読むこと。

使い方:

    venv\\Scripts\\python.exe scraper\\twitter_monitor\\research_scrape.py \\
        --handle dgurcf --since 2026-03-01

    # 収集済みのものを書き出すだけ
    venv\\Scripts\\python.exe scraper\\twitter_monitor\\research_scrape.py \\
        --handle dgurcf --skip-collect
"""

import argparse
import json
import logging
import random
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

from config import AUTH_STATE_PATH, RESEARCH_DB_PATH, RESEARCH_DIR
from backfill_search import (
    DEFAULT_MAX_DELAY,
    DEFAULT_MIN_DELAY,
    DEFAULT_WINDOW_DAYS,
    build_windows,
    collect_window,
    initialize_progress_table,
    nonnegative_float,
    parse_date,
    positive_int,
    progress_status,
    save_progress,
    should_process,
)
from scrape_tweets import (
    CHROME_USER_AGENT,
    LoggedOutError,
    initialize_database,
)


LOGGER = logging.getLogger(__name__)
JST = ZoneInfo("Asia/Tokyo")
DEFAULT_LOOKBACK_DAYS = 180


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="任意のXアカウントを手法研究用コーパスとして収集・書き出しします。"
    )
    parser.add_argument("--handle", required=True, help="対象アカウント（@なし）。")
    parser.add_argument(
        "--since",
        type=parse_date,
        default=None,
        metavar="YYYY-MM-DD",
        help=f"収集開始日（既定: {DEFAULT_LOOKBACK_DAYS}日前）。",
    )
    parser.add_argument(
        "--until",
        type=parse_date,
        default=None,
        metavar="YYYY-MM-DD",
        help="収集終了日（排他的、既定: JSTの明日）。",
    )
    parser.add_argument(
        "--window-days",
        type=positive_int,
        default=DEFAULT_WINDOW_DAYS,
        metavar="N",
        help=f"窓を進める日数（既定: {DEFAULT_WINDOW_DAYS}）。",
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
        help="status=failed の窓だけを再試行します。",
    )
    parser.add_argument(
        "--skip-collect",
        action="store_true",
        help="収集を行わず、research.db にある分だけを書き出します。",
    )
    parser.add_argument(
        "--export-dir",
        type=Path,
        default=None,
        help=f"書き出し先（既定: {RESEARCH_DIR}\\<handle>）。",
    )
    parser.add_argument(
        "--no-export",
        action="store_true",
        help="収集のみ行い、書き出しをしません。",
    )
    args = parser.parse_args()
    today = datetime.now(JST).date()
    # until は排他的。「今日の投稿まで含める」を既定にしたいので明日を指す。
    args.until = args.until or today + timedelta(days=1)
    args.since = args.since or today - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    if args.until <= args.since:
        parser.error("--until は --since より後の日付を指定してください（untilは排他的です）")
    if args.min_delay > args.max_delay:
        parser.error("--min-delay は --max-delay 以下にしてください")
    args.handle = args.handle.lstrip("@").strip()
    if not args.handle:
        parser.error("--handle にアカウント名を指定してください")
    return args


def register_handle(connection: sqlite3.Connection, handle: str) -> None:
    """accounts に研究用アカウントの行を作る。

    store_tweet 内の update_last_seen_max が accounts を UPDATE するため、
    行が無いと last_seen_tweet_id が黙って記録されない。
    """
    connection.execute(
        """
        INSERT INTO accounts(handle, hall, role)
        VALUES (?, NULL, '手法研究')
        ON CONFLICT(handle) DO UPDATE SET role=excluded.role
        """,
        (handle,),
    )
    connection.commit()


def collect(args: argparse.Namespace, connection: sqlite3.Connection) -> int:
    if not AUTH_STATE_PATH.exists():
        LOGGER.error("ログインstateがありません: %s。import_cookies.py を先に実行してください。", AUTH_STATE_PATH)
        return 1

    windows = build_windows(args.since, args.until, args.window_days)
    pending = [w for w in windows if should_process(progress_status(connection, args.handle, w), args.redo_failed)]
    LOGGER.info(
        "%s: %s..%s を %d窓に分割、うち未処理 %d窓",
        args.handle,
        args.since.isoformat(),
        args.until.isoformat(),
        len(windows),
        len(pending),
    )
    if not pending:
        return 0

    total_inserted = 0
    failed = 0
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
            for index, window in enumerate(pending):
                try:
                    result = collect_window(page, connection, args.handle, window)
                except LoggedOutError:
                    LOGGER.error("ログアウトを検出しました。import_cookies.py を再実行してください。")
                    return 1
                except KeyboardInterrupt:
                    LOGGER.warning("中断されました。同じコマンドで未処理の窓から再開できます。")
                    return 1
                save_progress(connection, args.handle, window, result.eligible, result.status)
                total_inserted += result.inserted
                if result.status == "failed":
                    failed += 1
                LOGGER.info(
                    "%s | %s..%s | %s | 新規%d件 %s",
                    args.handle,
                    window.start,
                    window.end,
                    result.status,
                    result.inserted,
                    result.reason,
                )
                if index + 1 < len(pending):
                    page.wait_for_timeout(int(random.uniform(args.min_delay, args.max_delay) * 1_000))
        finally:
            browser.close()

    LOGGER.info("%s: 収集完了 新規%d件、失敗窓%d", args.handle, total_inserted, failed)
    if failed:
        LOGGER.warning("失敗窓があります。--redo-failed で再試行してください。")
    return 0


def fetch_rows(connection: sqlite3.Connection, handle: str) -> list[dict]:
    rows = connection.execute(
        """
        SELECT tweet_id, tweet_url, tweet_text, posted_at_jst, has_image
        FROM seen_tweets
        WHERE handle = ?
        ORDER BY posted_at_jst
        """,
        (handle,),
    ).fetchall()
    records = []
    for tweet_id, tweet_url, tweet_text, posted_at, has_image in rows:
        images = [
            path
            for (path,) in connection.execute(
                "SELECT image_path FROM tweet_images WHERE tweet_id = ? ORDER BY image_path",
                (tweet_id,),
            )
        ]
        records.append(
            {
                "tweet_id": tweet_id,
                "url": tweet_url,
                "posted_at_jst": posted_at,
                "text": tweet_text or "",
                "has_image": bool(has_image),
                "images": images,
            }
        )
    return records


def coverage_report(connection: sqlite3.Connection, handle: str) -> list[tuple[str, int]]:
    return list(
        connection.execute(
            """
            SELECT substr(posted_at_jst, 1, 7) AS month, COUNT(*)
            FROM seen_tweets WHERE handle = ?
            GROUP BY month ORDER BY month
            """,
            (handle,),
        )
    )


def export(connection: sqlite3.Connection, handle: str, export_dir: Path) -> int:
    records = fetch_rows(connection, handle)
    if not records:
        LOGGER.warning("%s: research.db に投稿がありません。先に収集してください。", handle)
        return 1

    export_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = export_dir / f"{handle}.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as handle_out:
        for record in records:
            handle_out.write(json.dumps(record, ensure_ascii=False) + "\n")

    months = coverage_report(connection, handle)
    lines = [
        f"# @{handle} 投稿コーパス",
        "",
        f"- 書き出し日時: {datetime.now(JST).isoformat()}",
        f"- 件数: {len(records)}（本人の非リプライ投稿のみ）",
        f"- 期間: {records[0]['posted_at_jst']} 〜 {records[-1]['posted_at_jst']}",
        f"- 画像付き: {sum(1 for r in records if r['has_image'])}件",
        "",
        "## 月別件数",
        "",
        "| 月 | 件数 |",
        "|---|---|",
    ]
    lines += [f"| {month} | {count} |" for month, count in months]
    # 月別件数が途中で 0 や極端に少ない月があれば、その窓の収集が失敗している。
    # backfill_progress の status も併せて確認すること。
    lines += ["", "## 投稿", ""]

    current_month = None
    for record in records:
        month = (record["posted_at_jst"] or "")[:7]
        if month != current_month:
            current_month = month
            lines += [f"### {month}", ""]
        lines.append(f"#### {record['posted_at_jst']} — {record['url']}")
        lines.append("")
        lines.append(record["text"].strip() or "（本文なし）")
        if record["images"]:
            lines.append("")
            lines.append("画像: " + ", ".join(Path(p).name for p in record["images"]))
        lines += ["", "---", ""]

    corpus_path = export_dir / f"{handle}.md"
    corpus_path.write_text("\n".join(lines), encoding="utf-8")
    LOGGER.info("書き出しました: %s / %s", jsonl_path, corpus_path)
    for month, count in months:
        LOGGER.info("  %s: %d件", month, count)
    return 0


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    RESEARCH_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(RESEARCH_DB_PATH) as connection:
        initialize_database(connection)
        initialize_progress_table(connection)
        register_handle(connection, args.handle)

        if not args.skip_collect:
            code = collect(args, connection)
            if code != 0:
                return code
        if args.no_export:
            return 0
        export_dir = args.export_dir or (RESEARCH_DIR / args.handle)
        return export(connection, args.handle, export_dir)


if __name__ == "__main__":
    sys.exit(main())
