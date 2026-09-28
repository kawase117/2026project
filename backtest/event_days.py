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
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from scraper.twitter_monitor.hall_aliases import HALL_ALIAS_EXCLUSIONS, HALL_ALIASES
from backtest.announce import extract_narabi_mentions, load_announce_bundles

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(ROOT, "document", "registry", "EVENT_DAYS.jsonl")
STATE_DB = os.path.join(ROOT, "scraper", "twitter_monitor", "state.db")
RESULT_DB = os.path.join(ROOT, "db", "analysis_results.db")
RESULT_LINKS_LEDGER = os.path.join(ROOT, "document", "registry", "EVENT_RESULT_LINKS.jsonl")
JST = timezone(timedelta(hours=9))

KINDS = {
    "collab": "複数店合同・企画（カマタに集合、活性化プロジェクト等）",
    "recording": "収録来店（回胴エムワンバトル等、撮影を伴う来店）",
    "visit": "演者来店（撮影を伴わない来店・イベント出演）",
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


def merged(records):
    """同じ event_id の行を、後の行で上書きして1件にまとめる（amend の追記行を反映）。"""
    out = {}
    for r in records:
        if r["event_id"] in out:
            out[r["event_id"]].update({k: v for k, v in r.items() if k not in ("amend",)})
        else:
            out[r["event_id"]] = {k: v for k, v in r.items() if k != "amend"}
    return list(out.values())


def active(records):
    """同じ event_id をまとめ、supersedes で閉じられたものを除く。"""
    records = merged(records)
    closed = {s for r in records for s in r.get("supersedes", [])}
    return [r for r in records if r["event_id"] not in closed]


def make_id(hall, date, name):
    short = "".join(ch for ch in hall if ch.isalnum())[-6:]
    return "%s_%s_%s" % (date, short, "".join(ch for ch in name if ch.isalnum())[:12])


def add(rec, amend=False):
    records = load()
    exists = rec["event_id"] in {r["event_id"] for r in records}
    if exists and not amend:
        return False
    if amend:
        rec["amend"] = True
        rec["amended_at"] = datetime.now(JST).isoformat(timespec="seconds")
    if not amend:
        rec["registered_at"] = datetime.now(JST).isoformat(timespec="seconds")
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "a", encoding="utf-8") as h:
        h.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return True


def parse_performers(text):
    """'名前|@handle|メモ;名前2|@handle2|メモ2' を [{name,handle,note}] にする。"""
    out = []
    for chunk in [c for c in (text or "").split(";") if c.strip()]:
        parts = [x.strip() for x in chunk.split("|")]
        parts += [""] * (3 - len(parts))
        out.append({"name": parts[0], "handle": parts[1].lstrip("@"), "note": parts[2]})
    return out


def build(
    hall,
    date,
    name,
    kind,
    related_halls="",
    machines="",
    source_tweets="",
    basis="tweet",
    note="",
    supersedes="",
    performers="",
    preferred_machines="",
    participants="",
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
    if performers:
        rec["performers"] = parse_performers(performers)
    if preferred_machines:
        rec["preferred_machines"] = [x for x in preferred_machines.split(",") if x]
    if participants:
        rec["participants"] = [x for x in participants.split(",") if x]
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
        a.performers or "",
        a.preferred_machines or "",
        a.participants or "",
    )
    print(("registered " if add(rec) else "already exists ") + rec["event_id"])
    return 0


def cmd_amend(a):
    """既存イベントに演者・好み・参加ホール・メモを追記する（元の行は消さず、後の行で上書きする）。"""
    eid = make_id(a.hall, a.date, a.name)
    base = next((r for r in merged(load()) if r["event_id"] == eid), None)
    if base is None:
        print("見つからない: " + eid)
        return 1
    rec = {"event_id": eid}
    if a.performers:
        rec["performers"] = parse_performers(a.performers)
    if a.preferred_machines:
        rec["preferred_machines"] = [x for x in a.preferred_machines.split(",") if x]
    if a.participants:
        rec["participants"] = [x for x in a.participants.split(",") if x]
    if a.source_tweets:
        rec["source_tweets"] = sorted(set(base.get("source_tweets", []) + [x for x in a.source_tweets.split(",") if x]))
    if a.note:
        rec["note"] = (base.get("note", "") + " / " + a.note).strip(" /")
    print(("amended " if add(rec, amend=True) else "failed ") + eid)
    return 0


def cmd_list(a):
    for r in sorted(active(load()), key=lambda r: (r["date"], r["hall"])):
        if a.hall and a.hall not in r["hall"]:
            continue
        if a.since and r["date"] < a.since:
            continue
        rel = ("  (関連: %s)" % ",".join(r["related_halls"])) if r.get("related_halls") else ""
        perf = (
            ("  演者: %s" % ",".join(p["name"] or "@" + p["handle"] for p in r["performers"]))
            if r.get("performers")
            else ""
        )
        print("%s %-26s [%s] %s%s%s" % (r["date"], r["hall"], r["kind"], r["event_name"], rel, perf))
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
    """投稿日時と本文から対象営業日を推定する。要確認。

    - 12時以降の投稿に『明日』があれば、見出しの日付にかかわらず投稿の翌日
      （楽園の予告は『6/2 楽園蒲田 明日から3日間』のように、見出しが投稿日になる）
    - 『明日』が無く見出しに日付があれば、その日付
    - どちらも無ければ、12時以降の投稿は翌日、それ以前は投稿日
    """
    posted = datetime.fromisoformat(posted_at)
    evening = posted.hour >= 12
    if evening and "明日" in text:
        return (posted + timedelta(days=1)).strftime("%Y%m%d")
    m = re.search(r"(\d{1,2})月(\d{1,2})日|(\d{1,2})/(\d{1,2})", text[:80])
    if m:
        mo = int(m.group(1) or m.group(3))
        d = int(m.group(2) or m.group(4))
        try:
            return "%04d%02d%02d" % (posted.year, mo, d)
        except ValueError:
            pass
    nxt = posted + timedelta(days=1 if evening else 0)
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


def pledge_keys(announce_payload):
    """予告の claims と本文から、イベント系列比較用の公約キーを作る。"""
    keys = set()
    for claim in announce_payload.get("claims", []) or []:
        typ = claim.get("type")
        if typ == "position_rule":
            values = claim.get("values", [])
            value = ",".join(map(str, values))
            if claim.get("field") == "last_digit":
                ratio = claim.get("ratio")
                ratio_text = f"1/{ratio}" if ratio is not None else "?"
                keys.add(f"末尾:{value}:{ratio_text}")
            else:
                keys.add(f"{claim.get('field')}:{value}")
        elif typ == "model_named_ratio":
            keys.add(f"機種指名:1/{claim.get('ratio')}")
        elif typ == "model_named":
            keys.add("機種指名:全")
        elif typ == "zentaikei_count":
            keys.add(f"全台系:{claim.get('n_models')}機種")
        elif typ == "narabi":
            keys.add(f"並び:{claim.get('n_adjacent')}台")
    for mention in extract_narabi_mentions(announce_payload.get("raw_text", "")):
        keys.add(f"並び:{mention['n_adjacent'] or '?'}台")
    return keys


def _series_name(name):
    value = unicodedata.normalize("NFKC", name or "").lower()
    value = re.sub(r"\d{1,4}年?\d{1,2}月?\d{1,2}日?|\d{1,2}/\d{1,2}", "", value)
    value = re.sub(r"第\s*\d+\s*弾|\d+\s*日目", "", value)
    value = re.sub(r"[初開催第\d０-９]+", "", value)
    value = re.sub(r"[^\wぁ-んァ-ヶ一-龯]", "", value)
    return value


def _grams(value):
    return {value[i : i + 2] for i in range(max(0, len(value) - 1))}


def _name_similarity(left, right):
    a, b = _grams(_series_name(left)), _grams(_series_name(right))
    return 1.0 if not a and not b else (len(a & b) / len(a | b) if a | b else 0.0)


def _announce_for_events(event_rows, announce_dir):
    bundles = load_announce_bundles(announce_dir)["bundles"]
    by_day = defaultdict(list)
    for bundle in bundles:
        payload = bundle["payload"]
        by_day[(_normalize_hall(payload.get("hall")), str(payload.get("target_date")))].append((bundle, payload))
    out = {}
    for row in event_rows:
        key = (_normalize_hall(row.get("hall")), str(row.get("date")))
        matches = by_day.get(key, [])
        out[row["event_id"]] = matches
    return out


def _source_handle(row, payloads, state_db=STATE_DB):
    handles = {p.get("source", {}).get("account") for _, p in payloads if p.get("source", {}).get("account")}
    if handles:
        return sorted(handles)[0]
    ids = row.get("source_tweets", [])
    if not ids or not os.path.exists(state_db):
        return None
    with _ro_connect(state_db) as con:
        q = "select distinct handle from seen_tweets where tweet_id in (%s)" % ",".join("?" * len(ids))
        got = con.execute(q, tuple(ids)).fetchall()
    return got[0][0] if got else None


def _series_rows(event_ledger=LEDGER, announce_dir=None, state_db=STATE_DB):
    rows = active(_load_jsonl(event_ledger))
    announce_dir = announce_dir or os.path.join(ROOT, "backtest", "announce")
    matched = _announce_for_events(rows, announce_dir)
    out = []
    for row in rows:
        payloads = matched.get(row["event_id"], [])
        keys = set().union(*(pledge_keys(p) for _, p in payloads)) if payloads else set()
        out.append(
            {
                **row,
                "pledge_keys": keys,
                "announce_payloads": payloads,
                "source_handle": _source_handle(row, payloads, state_db),
            }
        )
    return out


def _series_candidates(event_ledger=LEDGER, announce_dir=None, series_ledger=None, state_db=STATE_DB):
    rows = _series_rows(event_ledger, announce_dir, state_db)
    decided = []
    if series_ledger and os.path.exists(series_ledger):
        decided = _load_jsonl(series_ledger)
    decided_events = {
        e for row in decided if row.get("decision") in {"same", "different"} for e in row.get("event_ids", [])
    }
    result = []
    for axis in ("name", "pledge"):
        groups = []
        if axis == "pledge":
            buckets = defaultdict(list)
            for row in rows:
                for key in row["pledge_keys"]:
                    buckets[(row["hall"], key)].append(row)
            group_iter = [(label, values, label) for (hall, label), values in buckets.items() if len(values) >= 2]
        else:
            parent = list(range(len(rows)))

            def root(index):
                while parent[index] != index:
                    parent[index] = parent[parent[index]]
                    index = parent[index]
                return index

            def union(left, right):
                left, right = root(left), root(right)
                if left != right:
                    parent[right] = left

            for i, left in enumerate(rows):
                for j, right in enumerate(rows[i + 1 :], i + 1):
                    if left["hall"] != right["hall"] or _name_similarity(left["event_name"], right["event_name"]) < 0.5:
                        continue
                    if (
                        left.get("source_handle")
                        and right.get("source_handle")
                        and left["source_handle"] != right["source_handle"]
                    ):
                        continue
                    union(i, j)
            buckets = defaultdict(list)
            for index, row in enumerate(rows):
                buckets[root(index)].append(row)
            group_iter = [
                (values[0]["event_name"], values, _series_name(values[0]["event_name"]))
                for values in buckets.values()
                if len(values) >= 2
            ]
        for label, values, reason in group_iter:
            event_ids = sorted({v["event_id"] for v in values})
            if decided_events.intersection(event_ids):
                continue
            score = 0.0
            if axis == "name":
                score = max(_name_similarity(values[0]["event_name"], v["event_name"]) for v in values[1:])
                evidence = f"名称2-gram Jaccard={score:.3f}; source={values[0].get('source_handle') or '?'}"
                series_label = _series_name(label) or "unnamed"
            else:
                score = 1.0
                evidence = f"公約キー={reason}"
                series_label = reason
            hall_short = re.sub(r"[^0-9A-Za-zぁ-んァ-ヶ一-龯]+", "", values[0]["hall"])[-12:]
            result.append(
                {
                    "series_id": f"{hall_short}__{axis}__{series_label}",
                    "axis": axis,
                    "hall": values[0]["hall"],
                    "label": label,
                    "event_ids": event_ids,
                    "auto_score": round(score, 3),
                    "evidence": evidence,
                }
            )
    return result


def cmd_series(a):
    candidates = _series_candidates(a.event_ledger, a.announce_dir, a.series_ledger, a.state_db)
    if getattr(a, "hall", None):
        hall = _normalize_hall(a.hall)
        candidates = [x for x in candidates if x["hall"] == hall]
    print(
        "候補数: name=%d pledge=%d"
        % (sum(x["axis"] == "name" for x in candidates), sum(x["axis"] == "pledge" for x in candidates))
    )
    if getattr(a, "json", False):
        print(json.dumps(candidates, ensure_ascii=False, indent=2))
        return 0
    # ユーザーが「同じ／違う」を判断しやすいよう、1候補1行（日付の並び・根拠）で出す。
    for i, x in enumerate(candidates, 1):
        # 同じ日に複数の event_id がある回は1回として数える
        days = sorted({e[:8] for e in x["event_ids"]})
        dates = ",".join(d[4:6].lstrip("0") + "/" + d[6:8].lstrip("0") for d in days)
        print(
            "%2d [%s] %s | %d回: %s | score=%s | %s"
            % (i, x["axis"], x["label"], len(days), dates, x["auto_score"], x.get("evidence", ""))
        )
    return 0


def cmd_series_list(a):
    rows = _load_jsonl(a.series_ledger)
    latest = {}
    for row in rows:
        latest[row.get("series_id")] = row
    print(json.dumps(list(latest.values()), ensure_ascii=False, indent=2))
    return 0


def cmd_series_decide(a):
    path = a.series_ledger
    previous = _load_jsonl(path)
    old = next((r for r in reversed(previous) if r.get("series_id") == a.series_id), None)
    row = {
        "row_id": "s-%04d" % (len(previous) + 1),
        "series_id": a.series_id,
        "axis": a.axis,
        "hall": a.hall,
        "label": a.label,
        "pledge_key": a.pledge_key,
        "event_ids": [x for x in a.event_ids.split(",") if x],
        "decision": a.decision,
        "decided_by": "user",
        "auto_score": a.auto_score,
        "auto_decision": None if a.auto_score is None else ("same" if float(a.auto_score) >= 0.5 else "different"),
        "decided_at": datetime.now(JST).isoformat(timespec="seconds"),
        "supersedes": old.get("row_id") if old else None,
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps(row, ensure_ascii=False))
    return 0


def cmd_series_accuracy(a):
    rows = _load_jsonl(a.series_ledger)[-20:]
    judged = [r for r in rows if r.get("decided_by") == "user" and r.get("auto_decision")]
    matched = sum(r["decision"] == r["auto_decision"] for r in judged)
    print("直近ユーザー判定: %d件中%d件一致" % (len(judged), matched))
    if matched >= 19:
        print("自動判定に切り替え可")
    return 0


def _normalize_hall(name):
    """台帳・結果DB・monitorの内部名を実績DB名へ寄せる。"""
    value = (name or "").strip()
    if not value:
        return value
    canonical = set(HALL_ALIASES)
    if value in canonical:
        return value
    aliases = {
        "楽園": "楽園蒲田店",
        "rakuen_kamata": "楽園蒲田店",
        "蒲田1": "マルハンメガシティ2000-蒲田1",
        "kamata1": "マルハンメガシティ2000-蒲田1",
        "蒲田7": "マルハンメガシティ2000-蒲田7",
        "kamata7": "マルハンメガシティ2000-蒲田7",
        "kamata7_kamata1": "",
        "みとや": "みとや大森町店",
        "mitoya": "みとや大森町店",
        "hiroki": "ヒロキ東口店",
        "arrow_ikegami_mitoya_omori": "",
    }
    if value in aliases and aliases[value]:
        return aliases[value]
    for hall in canonical:
        if value in hall or hall in value:
            return hall
    return value


def _ro_connect(path):
    return sqlite3.connect("file:" + os.path.abspath(path) + "?mode=ro", uri=True)


def _load_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _event_groups(path):
    groups = {}
    for rec in active(_load_jsonl(path)):
        hall = _normalize_hall(rec.get("hall"))
        business_date = str(rec.get("date", ""))
        if not hall or len(business_date) != 8:
            continue
        key = (hall, business_date)
        groups.setdefault(key, set()).add(rec["event_id"])
    return groups


def _date_from_posted(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


_DATE_TOKEN = re.compile(r"(?<!\d)(\d{1,2})(?:/|月)(\d{1,2})(?!\d)")


def _candidate_text_has_date(text, business_date):
    """本文で最初に現れる日付が営業日であるか。

    結果発表は冒頭に営業日を書く。後の日付の予告が「過去2回（9/14.15）」のように
    過去回へ言及するだけのものを拾わないよう、最初の日付だけを見る。
    """
    try:
        d = datetime.strptime(business_date, "%Y%m%d").date()
    except ValueError:
        return False
    m = _DATE_TOKEN.search(text or "")
    return bool(m) and (int(m.group(1)), int(m.group(2))) == (d.month, d.day)


# 候補探索ではチェーン名だけの別名を使わない。slokotae7 等は約89ホールを扱い、
# 「楽園」は楽園柏店・楽園松戸店などにも一致する（2026-09-28 に楽園蒲田 9/14 の候補12件中10件が他ホールだった）。
_CHAIN_ONLY_ALIASES = {"楽園"}


def _candidate_mentions_hall(text, hall, on_date):
    scan = text or ""
    for other in HALL_ALIAS_EXCLUSIONS.get(hall, ()):
        scan = scan.replace(other, "")
    for keyword, valid_from, valid_until in HALL_ALIASES.get(hall, []):
        if keyword in _CHAIN_ONLY_ALIASES or keyword not in scan:
            continue
        if valid_from is not None and on_date < valid_from:
            continue
        if valid_until is not None and on_date > valid_until:
            continue
        return True
    return False


def _result_data(analysis_db, state_db, hall, business_date):
    reports = []
    report_tweet_ids = set()
    with _ro_connect(analysis_db) as con:
        rows = con.execute(
            "select report_id,tweet_url,posted_at,hall_name,business_date "
            "from external_result_reports where business_date=?",
            (business_date,),
        ).fetchall()
        machine_counts = dict(
            con.execute("select report_id,count(*) from external_result_machines group by report_id").fetchall()
        )
    for report_id, tweet_url, posted_at, hall_name, report_date in rows:
        if _normalize_hall(hall_name) != hall:
            continue
        reports.append(
            {
                "report_id": report_id,
                "tweet_url": tweet_url,
                "posted_at": posted_at,
                "machine_count": machine_counts.get(report_id, 0),
            }
        )
        report_tweet_ids.add(str(report_id))
        if tweet_url:
            report_tweet_ids.add(str(tweet_url).rsplit("/", 1)[-1].split("?", 1)[0])
    reports.sort(key=lambda r: (r["posted_at"] or "", str(r["report_id"])))

    candidates = []
    start = datetime.strptime(business_date, "%Y%m%d").date()
    end = start + timedelta(days=45)
    with _ro_connect(state_db) as con:
        accounts = con.execute("select handle,hall,role from accounts").fetchall()
        allowed = {
            handle
            for handle, account_hall, role in accounts
            if (
                _normalize_hall(account_hall) == hall
                or (
                    account_hall == "kamata7_kamata1"
                    and hall in {"マルハンメガシティ2000-蒲田1", "マルハンメガシティ2000-蒲田7"}
                )
            )
            and ("答え合わせ" in (role or "") or "結果報告" in (role or ""))
        }
        if allowed:
            tweets = con.execute(
                "select tweet_id,handle,tweet_url,posted_at_jst,tweet_text,full_text "
                "from seen_tweets order by posted_at_jst,tweet_id"
            ).fetchall()
            for tweet_id, handle, tweet_url, posted_at, tweet_text, full_text in tweets:
                if handle not in allowed or str(tweet_id) in report_tweet_ids:
                    continue
                posted_date = _date_from_posted(posted_at)
                if posted_date is None or not (start <= posted_date <= end):
                    continue
                text = full_text or tweet_text or ""
                if not _candidate_text_has_date(text, business_date):
                    continue
                if not _candidate_mentions_hall(text, hall, posted_date):
                    continue
                candidates.append(
                    {"tweet_id": str(tweet_id), "handle": handle, "posted_at_jst": posted_at, "tweet_url": tweet_url}
                )
    return reports, candidates


def _link_row(hall, business_date, event_ids, reports, candidates, previous, checked_at, row_id):
    if reports:
        primary = max(reports, key=lambda r: (r["machine_count"], -(reports.index(r))))
        first_date = _date_from_posted(reports[0]["posted_at"])
        business = datetime.strptime(business_date, "%Y%m%d").date()
        delay = (first_date - business).days if first_date else None
        status = "linked"
        report_ids = [r["report_id"] for r in reports]
        primary_id = primary["report_id"]
    else:
        status = "multiple_candidates" if len(candidates) >= 2 else "waiting"
        # not_found は45日以内に結果発表が無かったという意味であり、設定が入らなかった意味ではない。
        # 候補ツイートがある回は45日を過ぎても not_found にしない（過去分の遡及探索で拾うため）。
        expired = datetime.now(JST).date() > datetime.strptime(business_date, "%Y%m%d").date() + timedelta(days=45)
        if expired and not candidates:
            status = "not_found"
        report_ids, primary_id, delay = [], None, None
    return {
        "row_id": row_id,
        "hall": hall,
        "business_date": business_date,
        "event_ids": sorted(event_ids),
        "status": status,
        "report_ids": report_ids,
        "primary_report_id": primary_id,
        "candidate_tweets": [{k: c[k] for k in ("tweet_id", "handle", "posted_at_jst")} for c in candidates],
        "delay_days": delay,
        "checked_at": checked_at,
        "method": "hall_date_report_or_state_tweet",
        "supersedes": previous.get("row_id") if previous else None,
    }


def _same_link_state(left, right):
    return all(left.get(k) == right.get(k) for k in ("status", "report_ids", "candidate_tweets"))


def _latest_link_rows(path):
    latest = {}
    for row in _load_jsonl(path):
        latest[(row.get("hall"), row.get("business_date"))] = row
    return latest


def cmd_link(a):
    groups = _event_groups(a.event_ledger)
    latest = _latest_link_rows(a.links_ledger)
    checked_at = datetime.now(JST).isoformat(timespec="seconds")
    pending, counts = [], {s: 0 for s in ("linked", "multiple_candidates", "waiting", "not_found")}
    for (hall, business_date), event_ids in sorted(groups.items()):
        reports, candidates = _result_data(a.analysis_db, a.state_db, hall, business_date)
        previous = latest.get((hall, business_date))
        probe = _link_row(hall, business_date, event_ids, reports, candidates, previous, checked_at, "")
        if previous and _same_link_state(previous, probe):
            row = previous
        else:
            row_id = "erl-%s-%s-%06d" % (
                re.sub(r"[^0-9A-Za-z]+", "-", hall).strip("-"),
                business_date,
                len(_load_jsonl(a.links_ledger)) + len(pending) + 1,
            )
            row = _link_row(hall, business_date, event_ids, reports, candidates, previous, checked_at, row_id)
            pending.append(row)
        counts[row["status"]] += 1
        if a.dry_run:
            print(json.dumps(row, ensure_ascii=False))
    if not a.dry_run and pending:
        os.makedirs(os.path.dirname(a.links_ledger), exist_ok=True)
        with open(a.links_ledger, "a", encoding="utf-8") as f:
            for row in pending:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print("追記: %d 行%s" % (len(pending), "（dry-run）" if a.dry_run else ""))
    print("status: " + " ".join("%s=%d" % (key, counts[key]) for key in counts))
    return 0


def cmd_link_report(a):
    latest = _latest_link_rows(a.links_ledger)
    rows = [r for r in latest.values() if r.get("status") != "linked"]
    rows.sort(key=lambda r: (r.get("business_date", ""), r.get("hall", "")))
    for row in rows:
        urls = []
        with _ro_connect(a.state_db) as con:
            for tweet_id in [c["tweet_id"] for c in row.get("candidate_tweets", [])]:
                got = con.execute("select tweet_url from seen_tweets where tweet_id=?", (tweet_id,)).fetchone()
                if got and got[0]:
                    urls.append(got[0])
        print("%s %s %s %s" % (row["hall"], row["business_date"], row["status"], " ".join(urls) or "-"))
    print("未linked: %d 件" % len(rows))
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
    s.add_argument("--performers")
    s.add_argument("--preferred-machines")
    s.add_argument("--participants")
    s.set_defaults(fn=cmd_add)
    s = sub.add_parser("amend")
    s.add_argument("--hall", required=True)
    s.add_argument("--date", required=True)
    s.add_argument("--name", required=True)
    s.add_argument("--performers")
    s.add_argument("--preferred-machines")
    s.add_argument("--participants")
    s.add_argument("--source-tweets")
    s.add_argument("--note")
    s.set_defaults(fn=cmd_amend)
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
    for name, fn in (("link", cmd_link), ("link-report", cmd_link_report)):
        s = sub.add_parser(name)
        s.add_argument("--event-ledger", default=LEDGER)
        s.add_argument("--analysis-db", default=RESULT_DB)
        s.add_argument("--state-db", default=STATE_DB)
        s.add_argument("--links-ledger", default=RESULT_LINKS_LEDGER)
        if name == "link":
            s.add_argument("--dry-run", action="store_true")
        s.set_defaults(fn=fn)
    s = sub.add_parser("series")
    s.add_argument("--event-ledger", default=LEDGER)
    s.add_argument("--announce-dir", default=os.path.join(ROOT, "backtest", "announce"))
    s.add_argument("--series-ledger", default=os.path.join(ROOT, "document", "registry", "EVENT_SERIES.jsonl"))
    s.add_argument("--state-db", default=STATE_DB)
    s.add_argument("--hall", help="このホールの候補だけ出す（表記ゆれは吸収）")
    s.add_argument("--json", action="store_true", help="全件を JSON で出す（既定は1候補1行の一覧）")
    s.set_defaults(fn=cmd_series)
    s = sub.add_parser("series-decide")
    s.add_argument("--series-ledger", default=os.path.join(ROOT, "document", "registry", "EVENT_SERIES.jsonl"))
    s.add_argument("--series-id", required=True)
    s.add_argument("--axis", required=True, choices=["name", "pledge"])
    s.add_argument("--hall", required=True)
    s.add_argument("--label", required=True)
    s.add_argument("--pledge-key", default=None)
    s.add_argument("--event-ids", required=True)
    s.add_argument("--decision", required=True, choices=["same", "different"])
    s.add_argument("--auto-score", type=float, default=None)
    s.set_defaults(fn=cmd_series_decide)
    s = sub.add_parser("series-accuracy")
    s.add_argument("--series-ledger", default=os.path.join(ROOT, "document", "registry", "EVENT_SERIES.jsonl"))
    s.set_defaults(fn=cmd_series_accuracy)
    s = sub.add_parser("series-list")
    s.add_argument("--series-ledger", default=os.path.join(ROOT, "document", "registry", "EVENT_SERIES.jsonl"))
    s.set_defaults(fn=cmd_series_list)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
