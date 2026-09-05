"""Daily pipeline entry point: collect, fill any gap, extract, then label.

Profile-timeline crawling silently stops paginating after roughly two and a half
weeks, so a run that follows a break leaves a hole and still exits reporting
success. That happened for real: a run on 2026-09-05 after collecting through
08-12 reported "226 new posts" while 08-14..09-01 came back empty for every
major account, nineteen days lost without a single error.

So the gap is measured before crawling, and anything older than a couple of days
goes through the date-window search instead, which is not subject to that limit.
"""

import argparse
import subprocess
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from config import DB_PATH

BASE_DIR = Path(__file__).resolve().parent
PYTHON = sys.executable
JST = ZoneInfo("Asia/Tokyo")
# One day of slack: yesterday's posts are still reachable by the normal crawl.
GAP_TRIGGER_DAYS = 2
# Re-collect from a day before the last known post so a partly-collected day is
# completed rather than half kept.
GAP_OVERLAP_DAYS = 1


def last_collected_date(connection):
    """Return the earliest 'newest post' across accounts, i.e. the weakest link."""
    rows = connection.execute("SELECT handle, MAX(posted_at_jst) FROM seen_tweets GROUP BY handle").fetchall()
    dates = [row[1][:10] for row in rows if row[1]]
    if not dates:
        return None
    return min(date.fromisoformat(value) for value in dates)


def run(script, *arguments):
    command = [PYTHON, str(BASE_DIR / script), *arguments]
    print("\n$ %s %s" % (script, " ".join(arguments)), flush=True)
    result = subprocess.run(command, cwd=str(BASE_DIR))
    if result.returncode != 0:
        print("  -> 終了コード %d" % result.returncode, flush=True)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="収集・欠損補完・抽出・ラベル付けを順に実行します。")
    parser.add_argument("--extract-limit", type=int, default=400, help="1回の抽出で処理する画像数の上限 (既定 400)")
    parser.add_argument("--extract-handles", default=None, help="抽出対象のアカウントを限定 (カンマ区切り)")
    parser.add_argument("--skip-extract", action="store_true", help="抽出を行わず、収集とラベル付けだけ実行します。")
    args = parser.parse_args()

    today = datetime.now(JST).date()
    with sqlite3.connect(DB_PATH, timeout=60) as connection:
        last = last_collected_date(connection)

    if last is None:
        print("収集履歴がありません。先に scrape_tweets.py を実行してください。")
        return 1

    gap_days = (today - last).days
    print("最終取得日 %s / 本日 %s (%d日の空き)" % (last, today, gap_days))

    if gap_days >= GAP_TRIGGER_DAYS:
        since = last - timedelta(days=GAP_OVERLAP_DAYS)
        until = today + timedelta(days=1)
        print("プロフィール巡回では遡り切れないため、検索で %s〜%s を補完します。" % (since, until))
        run(
            "backfill_search.py",
            "--since",
            since.isoformat(),
            "--until",
            until.isoformat(),
            "--window-days",
            "7",
            "--min-delay",
            "25",
            "--max-delay",
            "45",
        )
    else:
        print("空きは %d 日なので通常の巡回で足ります。" % gap_days)

    run("scrape_tweets.py")
    run("prefilter.py")

    if not args.skip_extract:
        extract = ["--limit", str(args.extract_limit), "--redo-failed", "--newest-first"]
        if args.extract_handles:
            extract = ["--handles", args.extract_handles] + extract
        run("extract_answers.py", *extract)

    run("infer_hall.py", "--apply")
    run("resolve_dates.py", "--apply")

    with sqlite3.connect(DB_PATH, timeout=60) as connection:
        gaps = connection.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT DISTINCT substr(posted_at_jst, 1, 10) AS day
                FROM seen_tweets WHERE posted_at_jst >= ?
            )
            """,
            ((today - timedelta(days=30)).isoformat(),),
        ).fetchone()[0]
    print("\n直近30日のうち投稿を取得できた日: %d 日" % gaps)
    if gaps < 25:
        print("  ※ 欠損が疑われます。backfill_search.py で期間を指定して補完してください。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
