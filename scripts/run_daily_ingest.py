#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日次取り込みを手で回すときの入口。実体は run_morning.py に委ねる。

なぜ薄いラッパなのか:
  2026-09-12 以前、このスクリプトは run_morning.py とほぼ同じ段
  （アナスロ取得 → DB投入 → X収集）を**別の実装で**持っていた。
  結果、同じ朝に手動でこちらを、08:00 にスケジューラが向こうを回し、
  `scraper/twitter_monitor/run_daily.py` が 07:51 と 08:01 の2本同時に
  走って state.db と .browser_profile を奪い合った。
  「どちらを回したか分からない」状態を残さないため、パイプラインの実体は
  run_morning.py 一本に統一し、ここは

    - 引数の翻訳（--start-date → run_morning の --days）
    - 実行後の**実測**による検証（DB最終収録日・当日の投稿数）

  だけを持つ。多重起動そのものは run_morning.py 側の
  `runlock.acquire_or_exit("daily_pipeline")` が止めるので、
  ここではロックを取らない（取ると自分自身を弾いてしまう）。

使い方:
  venv/Scripts/python.exe scripts/run_daily_ingest.py
  venv/Scripts/python.exe scripts/run_daily_ingest.py --skip-twitter
  venv/Scripts/python.exe scripts/run_daily_ingest.py --start-date 20260909

成功報告ではなく実測で判断すること:
  各段は EXIT=0 のまま失敗する経路がある（ana-slo 側の未掲載、403 での遮断、
  絵文字 print による ABORT）。最後に出る「DB最終収録日」と
  「当日の投稿数」だけを信じること。
"""

from __future__ import annotations

import argparse
import glob
import os
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = str(ROOT / "venv" / "Scripts" / "python.exe")
if not Path(PYTHON).exists():  # 非Windows・別配置でも動くように
    PYTHON = sys.executable


def env_utf8() -> dict[str, str]:
    """絵文字の print で ABORT しないよう UTF-8 を強制した環境を返す。"""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def db_max_dates() -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(glob.glob(str(ROOT / "db" / "*.db"))):
        conn = None
        try:
            conn = sqlite3.connect(path)
            has = conn.execute(
                "select name from sqlite_master where type='table' and name='machine_detailed_results'"
            ).fetchone()
            if not has:
                continue
            value = conn.execute("select max(date) from machine_detailed_results").fetchone()[0]
            out[Path(path).stem] = value or "(空)"
        except sqlite3.Error as error:
            out[Path(path).stem] = f"(読めない: {error})"
        finally:
            if conn is not None:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass
    return out


def tweets_on(day: str) -> list[tuple[str, int]]:
    path = ROOT / "scraper" / "twitter_monitor" / "state.db"
    if not path.exists():
        return []
    conn = sqlite3.connect(str(path))
    try:
        rows = conn.execute(
            "select handle, count(*) from tweets where substr(created_at,1,10)=? group by 1 order by 1",
            (day,),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="日次取り込み（run_morning.py を呼ぶ）")
    parser.add_argument(
        "--days",
        type=int,
        default=10,
        help="何日前まで遡って欠落を探すか (既定 10)。取得済みの日は開かれない",
    )
    parser.add_argument(
        "--start-date",
        default=None,
        help="YYYYMMDD。指定すると --days をこの日までの日数に置き換える",
    )
    parser.add_argument("--skip-anaslo", action="store_true")
    parser.add_argument("--skip-twitter", action="store_true")
    parser.add_argument("--skip-history", action="store_true")
    parser.add_argument("--skip-forward", action="store_true")
    parser.add_argument("--skip-verify", action="store_true", help="実行後の検証を出さない")
    args = parser.parse_args()

    today = date.today()
    days = args.days
    if args.start_date:
        try:
            start = datetime.strptime(args.start_date, "%Y%m%d").date()
        except ValueError:
            print("--start-date は YYYYMMDD で指定すること: %s" % args.start_date)
            return 2
        days = max(1, (today - start).days)

    argv = [PYTHON, "-u", str(ROOT / "scripts" / "run_morning.py"), "--days", str(days)]
    for flag in ("skip_anaslo", "skip_twitter", "skip_history", "skip_forward"):
        if getattr(args, flag):
            argv.append("--" + flag.replace("_", "-"))

    print("=" * 72)
    print("[STEP] run_morning.py --days %d" % days)
    print("=" * 72, flush=True)
    proc = subprocess.run(argv, cwd=str(ROOT), env=env_utf8())
    print("[STEP] run_morning.py: exit=%d" % proc.returncode, flush=True)

    if args.skip_verify:
        return proc.returncode

    end_date = (today - timedelta(days=1)).strftime("%Y%m%d")
    after = db_max_dates()
    print()
    print("=" * 72)
    print("[検証] DB最終収録日（成功報告ではなくこちらで判断する）")
    print("=" * 72)
    stale = []
    for hall in sorted(after):
        print(f"  {hall:30s} {after[hall]}")
        if after[hall] < end_date:
            stale.append(hall)
    if stale:
        print()
        print(f"  ⚠️ {end_date} に届いていないホール {len(stale)}件: {', '.join(stale)}")
        print("     ana-slo 側が未掲載（404）なのか、遮断されたのかを切り分けること。")

    day = today.strftime("%Y-%m-%d")
    rows = tweets_on(day)
    print()
    print(f"[検証] {day} に収集できた投稿")
    if rows:
        for handle, count in rows:
            print(f"  {handle:20s} {count}件")
    else:
        print("  0件。プロフィールTLは2週半で無言で止まるので、欠落を疑うこと。")

    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
