#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ana-slo の過去データを、指定ホールについて数日ずつ遡って取り込む（長時間・遮断回避型）。

ヒロキ蒲田西口店・ヒロキMAX蒲田店のように履歴が長いホールを一気に叩くと
ana-slo(Cloudflare) が 403 で遮断する（2026-09-07 は80ページで遮断）。
そのため次の方針で動く。

- JST 09:00 より前は待機し、何も取りに行かない（--start-hour で変更可）。
- 新しい日から古い日へ、chunk-days 日ずつ scraper/anaslo_scraper_auto_multi.py を呼ぶ。
  取得済みの日はスクレイパー側でスキップされるので、途中で止めても再実行で続きから進む。
- チャンク間・ホール間に待機を入れる（ジッター付き）。
- 遮断（[ABORT]/[STOP]/state=blocked）を検知したら指数バックオフで長く寝る。
  連続で max-blocks 回遮断されたら諦める（時間を空けて再実行すること）。
- 日付リンクが一覧に無い日だけのチャンクが続けば、そのホールの履歴の端と判断して終了する。
- 他の anaslo_browser 利用者（朝の日次パイプライン）が掴んでいるときは待つ。

使い方:
  venv\\Scripts\\python.exe scripts/backfill_anaslo_halls.py            # 既定の2ホール
  venv\\Scripts\\python.exe scripts/backfill_anaslo_halls.py --halls ヒロキMAX蒲田店 --chunk-days 5
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
JST = timezone(timedelta(hours=9))
DEFAULT_HALLS = ["ヒロキ蒲田西口店", "ヒロキMAX蒲田店"]

NO_LINK_RE = re.compile(r"\[WARN\] (\d{8}): 一覧ページに日付リンクがありません")
OK_RE = re.compile(r"\[OK\] (\d{8}): 取得・保存成功")
BLOCK_MARKERS = ("state=blocked", "state=challenge", "[STOP]", "[ABORT]", "403")


def log(msg: str) -> None:
    print("[%s] %s" % (datetime.now(JST).strftime("%m-%d %H:%M:%S"), msg), flush=True)


def wait_until_hour(start_hour: int) -> None:
    while True:
        now = datetime.now(JST)
        if now.hour >= start_hour:
            return
        target = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        secs = (target - now).total_seconds()
        log("%02d:00 まで待機 (あと %d 分)" % (start_hour, secs // 60))
        time.sleep(min(secs, 600))


def jitter(base: float) -> float:
    return base * random.uniform(0.8, 1.3)


def load_hall(name: str) -> dict:
    cfg = json.loads((PROJECT_ROOT / "config" / "hall_config.json").read_text(encoding="utf-8"))
    for hall in cfg["halls"]:
        if hall.get("hall_name") == name:
            return hall
    raise SystemExit("hall_config.json に %s が無い" % name)


def missing_days(hall_name: str, start: datetime, end: datetime) -> list[str]:
    save_dir = PROJECT_ROOT / "data" / hall_name
    out = []
    d = start
    while d <= end:
        s = d.strftime("%Y%m%d")
        if not (save_dir / ("%s_%s_data.json" % (s, hall_name))).exists():
            out.append(s)
        d += timedelta(days=1)
    return out


def run_chunk(hall: dict, start: datetime, end: datetime, timeout: int) -> tuple[str, int]:
    """1ホール・1窓をスクレイパーに渡す。戻り値は (標準出力, 終了コード)。"""
    cfg_name = "_backfill_%d.json" % os.getpid()
    cfg_path = PROJECT_ROOT / "config" / cfg_name
    cfg_path.write_text(json.dumps({"halls": [hall]}, ensure_ascii=False), encoding="utf-8")
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.run(
            [
                PYTHON,
                "-u",
                str(PROJECT_ROOT / "scraper" / "anaslo_scraper_auto_multi.py"),
                "--start-date",
                start.strftime("%Y%m%d"),
                "--end-date",
                end.strftime("%Y%m%d"),
                "--config",
                cfg_name,
            ],
            cwd=PROJECT_ROOT / "scraper",
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return proc.stdout + "\n" + proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as e:
        return "[ABORT] timeout %s" % (e.stdout or ""), 1
    finally:
        cfg_path.unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--halls", nargs="+", default=DEFAULT_HALLS)
    ap.add_argument("--chunk-days", type=int, default=6, help="1回に開く日数(既定6)")
    ap.add_argument("--max-lookback", type=int, default=1100, help="最大何日前まで遡るか")
    ap.add_argument("--start-hour", type=int, default=9, help="この時刻(JST)より前は動かない")
    ap.add_argument("--chunk-interval", type=float, default=150.0, help="チャンク間の待機秒")
    ap.add_argument("--block-backoff", type=float, default=900.0, help="遮断時の初回待機秒(倍々)")
    ap.add_argument("--max-blocks", type=int, default=6, help="連続遮断の許容回数")
    ap.add_argument("--max-chunks", type=int, default=0, help="処理するチャンク総数の上限(0=無制限)")
    ap.add_argument("--chunk-timeout", type=int, default=1500)
    args = ap.parse_args()

    halls = {name: load_hall(name) for name in args.halls}
    today = datetime.now(JST).replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
    oldest = today - timedelta(days=args.max_lookback)
    cursor = {n: today - timedelta(days=1) for n in halls}  # 窓の終端(新→旧)
    dead = {n: 0 for n in halls}
    done: set[str] = set()
    blocks = 0
    chunks = 0
    gained = 0

    while len(done) < len(halls):
        for name, hall in halls.items():
            if name in done:
                continue
            wait_until_hour(args.start_hour)
            end = cursor[name]
            if end < oldest:
                log("%s: 遡り上限に到達" % name)
                done.add(name)
                continue
            start = max(end - timedelta(days=args.chunk_days - 1), oldest)
            todo = missing_days(name, start, end)
            if not todo:
                cursor[name] = start - timedelta(days=1)
                continue

            log("%s: %s〜%s (未取得 %d日)" % (name, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), len(todo)))
            out, _code = run_chunk(hall, start, end, args.chunk_timeout)
            chunks += 1
            oks = set(OK_RE.findall(out))
            nolink = set(NO_LINK_RE.findall(out))
            blocked = any(m in out for m in BLOCK_MARKERS) and not oks
            locked = "[LOCK]" in out
            gained += len(oks)
            log("%s: 成功%d / リンク無し%d / 遮断=%s / ロック=%s" % (name, len(oks), len(nolink), blocked, locked))

            if locked:
                time.sleep(jitter(300))  # 日次パイプライン等が使用中。同じ窓をやり直す
                continue
            if blocked:
                blocks += 1
                if blocks >= args.max_blocks:
                    log("連続%d回遮断されたため中断。時間を空けて再実行すること(取得済みの日はスキップされる)" % blocks)
                    return 2
                wait = jitter(args.block_backoff * (2 ** (blocks - 1)))
                log("遮断を検知。%d分待機してから再開 (連続%d回目)" % (wait // 60, blocks))
                time.sleep(wait)
                continue  # 同じ窓をやり直す(カーソルは進めない)
            blocks = 0

            rest = set(missing_days(name, start, end))
            if not oks and rest and rest <= nolink:
                dead[name] += 1  # 全て「一覧にリンク無し」=掲載範囲外か休業の可能性
                if dead[name] >= 2:
                    log("%s: 掲載範囲の端と判断して終了" % name)
                    done.add(name)
                    continue
            else:
                dead[name] = 0
            cursor[name] = start - timedelta(days=1)
            if args.max_chunks and chunks >= args.max_chunks:
                log("--max-chunks に到達。ここで終了")
                return finish(gained)
            time.sleep(jitter(args.chunk_interval))

    return finish(gained)


def finish(gained: int) -> int:
    log("取得・保存した日数: %d" % gained)
    if gained:
        log("database/batch_incremental_updater.py を実行")
        subprocess.run(
            [PYTHON, "-u", str(PROJECT_ROOT / "database" / "batch_incremental_updater.py")], cwd=PROJECT_ROOT
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
