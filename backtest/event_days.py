# -*- coding: utf-8 -*-
"""日付単位のイベント日レジストリ（予告ツイート由来）。

なぜ要るか
----------
2026-09-19 の蒲田1・蒲田7で「カマタに集合！（両店同日）」「蒲田1は同時に回胴エムワンバトル収録」が
開催されたが、この情報は予告JSONの自由記述にしか残らず、過去の開催日を引くこともできなかった。
その結果、過去の開催日を両店に同じ日で当てはめる誤りを起こした（M1収録日を蒲田7に混ぜた）。

`eda/event_calendar.py` は「DDルール x カテゴリ x status」の統計的カレンダーで、別物。
こちらは **特定の日付に何があったか** の事実の台帳。イベント日の多くは予告ツイートで分かる。

使い方
------
    venv\\Scripts\\python.exe -m backtest.event_days list [--hall 蒲田1] [--since 20260601]
    venv\\Scripts\\python.exe -m backtest.event_days add --hall H --date YYYYMMDD --name N --kind K \\
        --source-tweets ID,ID [--related-halls H2,H3] [--machines A,B] [--note ...] [--basis tweet|user|instinct]
    venv\\Scripts\\python.exe -m backtest.event_days scan --since 20260901 [--hall 蒲田]   # 未登録の候補を出す
    venv\\Scripts\\python.exe -m backtest.event_days check YYYYMMDD                        # その日に登録があるか

台帳: document/registry/EVENT_DAYS.jsonl（1行1イベント。追記のみ。訂正は supersedes で名指し）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(ROOT, "document", "registry", "EVENT_DAYS.jsonl")
STATE_DB = os.path.join(ROOT, "scraper", "twitter_monitor", "state.db")
JST = timezone(timedelta(hours=9))

KINDS = {
    "collab": "複数店合同・企画（カマタに集合、活性化プロジェクト等）",
    "recording": "収録来店・演者来店（回胴エムワンバトル等）",
    "coverage": "取材来店・取材日",
    "anniversary": "周年・記念日・特定日の企画",
    "renovation": "改装・入替・配置替え・リニューアル",
    "ip": "版権・映画公開・キャラ誕などの機種連動",
    "manager": "店長交代・体制変更",
    "other": "その他",
}
# 予告ツイートでイベントを示す語。scan の候補抽出だけに使う（自動登録はしない）
KEYWORDS = (
    "カマタに集合",
    "エムワンバトル",
    "収録",
    "取材",
    "来店",
    "周年",
    "記念",
    "新装",
    "改装",
    "入替",
    "入れ替え",
    "リニューアル",
    "活性化",
    "強化日",
    "特定日",
    "合同",
    "コラボ",
    "初開催",
    "初取材",
    "店長",
)
# 複数ホールの予告を出すアカウントは、対象ホールの語を含む投稿だけを候補にする
SHARED_HANDLE_HALL_WORDS = {
    "999999Q9Q": {
        "蒲田1": ("蒲田1", "蒲田一", "メガいち", "よこやん", "カマタ"),
        "蒲田7": ("蒲田7", "蒲田七", "メガなな", "ウスイ", "カマタ"),
    },
}
HALL_HANDLES = {
    "蒲田1": ("999999Q9Q", "j75gJ3j1539G", "yokoyan_777"),
    "蒲田7": ("999999Q9Q", "ngc2070r136a1"),
    "楽園": ("kawasakislot", "slokotae7", "fanta_tenchou", "minnade777judge"),
    "みとや": ("sloneko222",),
}


def load():
    if not os.path.exists(LEDGER):
        return []
    out = []
    with open(LEDGER, encoding="utf-8") as h:
        for line in h:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def active(records):
    """supersedes で閉じられたものを除く。"""
    closed = {s for r in records for s in r.get("supersedes", [])}
    return [r for r in records if r["event_id"] not in closed]


def make_id(hall, date, name):
    short = "".join(ch for ch in hall if ch.isalnum())[-6:]
    return "%s_%s_%s" % (date, short, "".join(ch for ch in name if ch.isalnum())[:12])


def add(rec):
    records = load()
    if rec["event_id"] in {r["event_id"] for r in records}:
        return False
    rec["registered_at"] = datetime.now(JST).isoformat(timespec="seconds")
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "a", encoding="utf-8") as h:
        h.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return True


def build(
    hall, date, name, kind, related_halls="", machines="", source_tweets="", basis="tweet", note="", supersedes=""
):
    rec = {
        "event_id": make_id(hall, date, name),
        "hall": hall,
        "date": date,
        "event_name": name,
        "kind": kind,
        "related_halls": [x for x in related_halls.split(",") if x],
        "machines": [x for x in machines.split(",") if x],
        "source_tweets": [x for x in source_tweets.split(",") if x],
        "basis": basis,
        "note": note,
    }
    if supersedes:
        rec["supersedes"] = [x for x in supersedes.split(",") if x]
    return rec


def cmd_add(a):
    rec = build(
        a.hall,
        a.date,
        a.name,
        a.kind,
        a.related_halls or "",
        a.machines or "",
        a.source_tweets or "",
        a.basis,
        a.note or "",
        a.supersedes or "",
    )
    print(("registered " if add(rec) else "already exists ") + rec["event_id"])
    return 0


def cmd_list(a):
    for r in sorted(active(load()), key=lambda r: (r["date"], r["hall"])):
        if a.hall and a.hall not in r["hall"]:
            continue
        if a.since and r["date"] < a.since:
            continue
        rel = ("  (関連: %s)" % ",".join(r["related_halls"])) if r.get("related_halls") else ""
        print("%s %-26s [%s] %s%s" % (r["date"], r["hall"], r["kind"], r["event_name"], rel))
    return 0


def cmd_check(a):
    rows = [r for r in active(load()) if r["date"] == a.date]
    if not rows:
        print("%s: 登録なし。予告ツイートを確認し、イベントがあれば add すること。" % a.date)
        return 1
    for r in rows:
        print("%s [%s] %s" % (r["hall"], r["kind"], r["event_name"]))
    return 0


def target_date(posted_at, text):
    """投稿日時と本文から対象営業日を推定する。曖昧なら投稿の翌日（12時以降の投稿）。要確認。"""
    posted = datetime.fromisoformat(posted_at)
    m = re.search(r"(\d{1,2})月(\d{1,2})日|(\d{1,2})/(\d{1,2})", text)
    if m:
        mo = int(m.group(1) or m.group(3))
        d = int(m.group(2) or m.group(4))
        try:
            return "%04d%02d%02d" % (posted.year, mo, d)
        except ValueError:
            pass
    nxt = posted + timedelta(days=1 if posted.hour >= 12 else 0)
    return nxt.strftime("%Y%m%d")


def cmd_scan(a):
    con = sqlite3.connect(STATE_DB)
    since = "%s-%s-%s" % (a.since[:4], a.since[4:6], a.since[6:8])
    known_dates = {r["date"] for r in active(load())}
    handles = set()
    for key, hs in HALL_HANDLES.items():
        if not a.hall or a.hall in key:
            handles.update(hs)
    q = (
        "select tweet_id,handle,posted_at_jst,coalesce(full_text,tweet_text),full_text is null "
        "from seen_tweets where posted_at_jst>=? order by posted_at_jst"
    )
    n = 0
    for tid, handle, posted, text, truncated in con.execute(q, (since,)):
        if handle not in handles:
            continue
        hit = [k for k in KEYWORDS if k in text]
        if not hit:
            continue
        words = SHARED_HANDLE_HALL_WORDS.get(handle)
        if words:
            targets = [w for hall, ws in words.items() if not a.hall or a.hall in hall for w in ws]
            if not any(w in text for w in targets):
                continue
        date = target_date(posted, text)
        n += 1
        print(
            "[%s] %s %s @%s tweet=%s%s\n    語: %s\n    %s"
            % (
                "登録済" if date in known_dates else "未登録",
                date,
                posted[:16],
                handle,
                tid,
                "（本文切れの可能性）" if truncated else "",
                ",".join(hit),
                text.replace("\n", " | ")[:200],
            )
        )
    print("候補 %d 件（自動登録はしない。内容を読んで add すること）" % n)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("add")
    s.add_argument("--hall", required=True)
    s.add_argument("--date", required=True)
    s.add_argument("--name", required=True)
    s.add_argument("--kind", required=True, choices=sorted(KINDS))
    s.add_argument("--related-halls")
    s.add_argument("--machines")
    s.add_argument("--source-tweets")
    s.add_argument("--basis", default="tweet", choices=["tweet", "user", "instinct"])
    s.add_argument("--note")
    s.add_argument("--supersedes")
    s.set_defaults(fn=cmd_add)
    s = sub.add_parser("list")
    s.add_argument("--hall")
    s.add_argument("--since")
    s.set_defaults(fn=cmd_list)
    s = sub.add_parser("scan")
    s.add_argument("--since", required=True)
    s.add_argument("--hall")
    s.set_defaults(fn=cmd_scan)
    s = sub.add_parser("check")
    s.add_argument("date")
    s.set_defaults(fn=cmd_check)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
