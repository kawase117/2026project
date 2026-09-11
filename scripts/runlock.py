#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""共有資源ごとの多重起動ロック。

なぜ要るか:
  2026-09-12 の朝、手で `run_daily_ingest.py` を回している最中に
  タスクスケジューラの `run_morning.bat` が発火し、
  `scraper/twitter_monitor/run_daily.py` が 07:51 と 08:01 の
  2本同時に走った。両者は

    - scraper/twitter_monitor/state.db（SQLite）
    - scraper/.browser_profile（Chrome の永続プロファイル）

  を共有している。プロファイルは「Cloudflare の通過クッキーを毎回捨てて
  403 を踏む」のを避けるために永続化したものなので、二重起動で壊れると
  翌朝の取得が丸ごと落ちる。SQLite 側も database is locked で無言の
  取りこぼしになる。

設計:
  PID ファイルではなく **OS のファイルロック** を使う。PID 方式だと
  クラッシュ時にロックが残り（stale lock）、PID の再利用で誤判定もする。
  OS ロックはプロセスが死ねばカーネルが必ず解放するので、両方起きない。

  ロックはバイト 0 の 1 バイトだけに掛け、保持者の情報（PID・開始時刻・
  コマンド）は オフセット 1 以降に平文で書く。ロックが取れなかった側は
  そこを読んで「誰が掴んでいるか」をログに出せる。

使い方:
    from runlock import single_instance, LockHeld

    with single_instance("daily_pipeline"):
        ...

  あるいは entry point で素直に抜けたいとき:

    lock = acquire_or_exit("daily_pipeline")   # 掴めなければ exit 0
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK_DIR = PROJECT_ROOT / "locks"

_IS_WINDOWS = os.name == "nt"
if _IS_WINDOWS:
    import msvcrt
else:
    import fcntl


class LockHeld(RuntimeError):
    """他のプロセスが同じ資源を掴んでいる。"""

    def __init__(self, name: str, holder: str) -> None:
        super().__init__("%s は他のプロセスが実行中: %s" % (name, holder))
        self.name = name
        self.holder = holder


def _try_lock(fd: int) -> bool:
    """バイト 0 に非ブロッキングで排他ロックを掛ける。取れたら True。"""
    os.lseek(fd, 0, os.SEEK_SET)
    try:
        if _IS_WINDOWS:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB, 1, 0, os.SEEK_SET)
    except OSError:
        return False
    return True


def _unlock(fd: int) -> None:
    os.lseek(fd, 0, os.SEEK_SET)
    try:
        if _IS_WINDOWS:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.lockf(fd, fcntl.LOCK_UN, 1, 0, os.SEEK_SET)
    except OSError:
        pass


def _read_holder(path: Path) -> str:
    """保持者の情報。ロック中のバイト 0 は読まずに 1 以降だけ読む。"""
    try:
        with open(path, "rb") as handle:
            handle.seek(1)
            text = handle.read(4096).decode("utf-8", "replace").strip()
    except OSError:
        return "(不明)"
    return text or "(不明)"


def _describe_self() -> str:
    argv = " ".join(sys.argv)
    if len(argv) > 300:
        argv = argv[:300] + "…"
    return "pid=%d start=%s cmd=%s" % (
        os.getpid(),
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        argv,
    )


class _Lock:
    def __init__(self, name: str) -> None:
        self.name = name
        self.path = LOCK_DIR / ("%s.lock" % name)
        self._fd: int | None = None

    def acquire(self) -> "_Lock":
        LOCK_DIR.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        if not _try_lock(fd):
            holder = _read_holder(self.path)
            os.close(fd)
            raise LockHeld(self.name, holder)
        self._fd = fd
        # ロックしているのはバイト 0 だけ。保持者の情報は 1 以降に置く。
        os.lseek(fd, 1, os.SEEK_SET)
        os.write(fd, _describe_self().encode("utf-8"))
        os.ftruncate(fd, 1 + len(_describe_self().encode("utf-8")))
        return self

    def release(self) -> None:
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        _unlock(fd)
        os.close(fd)

    def __enter__(self) -> "_Lock":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.release()


def single_instance(name: str) -> _Lock:
    """ロックを取って返す。取れなければ LockHeld を投げる。"""
    return _Lock(name).acquire()


def acquire_or_exit(name: str, *, exit_code: int = 0) -> _Lock:
    """ロックを取る。取れなければ理由を出して抜ける。

    既定の終了コードは 0。先行実行があるのは異常ではなく、二重に走らせない
    という設計どおりの動作なので、スケジューラ側を失敗扱いにしない。
    ただしログには必ず残す（無言でスキップすると、今度は「走ったのに
    何もしていない」が見えなくなる）。
    """
    try:
        return single_instance(name)
    except LockHeld as held:
        print("=" * 70, flush=True)
        print("[LOCK] %s は既に実行中のため、この実行は行いません。" % name, flush=True)
        print("[LOCK] 先行プロセス: %s" % held.holder, flush=True)
        print("[LOCK] ロックファイル: %s" % (LOCK_DIR / ("%s.lock" % name)), flush=True)
        print("=" * 70, flush=True)
        raise SystemExit(exit_code)
