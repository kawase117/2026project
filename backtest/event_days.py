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

import pandas as pd

from backtest import model_alias as _model_alias
from scraper.twitter_monitor.hall_aliases import HALL_ALIAS_EXCLUSIONS, HALL_ALIASES
from backtest.announce import extract_narabi_mentions, load_announce_bundles
from backtest.announce import assign_segment, match_machine_names
from backtest.run_backtest import load_frame

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(ROOT, "document", "registry", "EVENT_DAYS.jsonl")
STATE_DB = os.path.join(ROOT, "scraper", "twitter_monitor", "state.db")
RESULT_DB = os.path.join(ROOT, "db", "analysis_results.db")
RESULT_LINKS_LEDGER = os.path.join(ROOT, "document", "registry", "EVENT_RESULT_LINKS.jsonl")
FIELD_OBS = os.path.join(ROOT, "backtest", "field_obs", "field_obs.jsonl")
SERIES_LEDGER = os.path.join(ROOT, "document", "registry", "EVENT_SERIES.jsonl")
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


# ---------------------------------------------------------------------------
# history (部品3)


def _asof_date(value):
    return datetime.strptime(str(value), "%Y%m%d").date()


def _posted_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except TypeError, ValueError:
        return None


def _before_asof(value, asof):
    d = _posted_date(value)
    return d is not None and d < _asof_date(asof)


def _latest_series(path):
    latest = {}
    for row in _load_jsonl(path):
        if row.get("series_id"):
            latest[row["series_id"]] = row
    return latest


def _history_announces(hall, target_date, asof, announce_dir):
    out = []
    for bundle in load_announce_bundles(announce_dir).get("bundles", []):
        if bundle.get("status") not in {"active", "retroactive"}:
            continue
        payload = bundle["payload"]
        if _normalize_hall(payload.get("hall")) != hall:
            continue
        source = payload.get("source", {})
        # 朝の再現では、予告自体もその朝までに見えていたものだけにする。
        if not _before_asof(source.get("posted_at"), asof):
            continue
        out.append({"bundle": bundle, "payload": payload})
    return out


def _history_groups(hall, target_date, asof, series_ids, pledge_args, event_ledger, series_ledger, announce_dir):
    events = [r for r in active(_load_jsonl(event_ledger)) if _normalize_hall(r.get("hall")) == hall]
    target_events = [r for r in events if str(r.get("date")) == target_date]
    announces = _history_announces(hall, target_date, asof, announce_dir)
    target_keys = set(pledge_args or [])
    for item in announces:
        if str(item["payload"].get("target_date")) == target_date:
            target_keys.update(pledge_keys(item["payload"]))

    latest = _latest_series(series_ledger)
    selected_name = []
    target_event_ids = {r.get("event_id") for r in target_events}
    for sid, row in latest.items():
        if row.get("decision") != "same" or row.get("axis") != "name":
            continue
        if series_ids and sid not in series_ids:
            continue
        if not series_ids and not target_event_ids.intersection(row.get("event_ids", [])):
            continue
        selected_name.append((sid, row))

    # name axis is ledger-defined; pledge axis intentionally comes from every
    # same-hall announcement, including dates absent from EVENT_DAYS.
    dates = {}
    for sid, row in selected_name:
        for event_id in row.get("event_ids", []):
            event = next((e for e in events if e.get("event_id") == event_id), None)
            if not event:
                continue
            d = str(event.get("date"))
            if d < target_date and d < asof:
                dates.setdefault(d, {"groups": set(), "event_ids": set()})["groups"].add(sid)
                dates[d]["event_ids"].add(event_id)

    if target_keys:
        for item in announces:
            payload = item["payload"]
            d = str(payload.get("target_date", ""))
            if d < target_date and d < asof and target_keys.intersection(pledge_keys(payload)):
                entry = dates.setdefault(d, {"groups": set(), "event_ids": set()})
                entry["groups"].update("pledge:" + k for k in target_keys.intersection(pledge_keys(payload)))
                entry["event_ids"].update(e.get("event_id") for e in events if str(e.get("date")) == d)

    return dates, events, announces, target_keys


def _history_matches(hall, text, names):
    """機種欄（略称・台番号範囲・複数機種の連結を含む）をその日の正式名に当てる。

    2026-09-28 に backtest.model_alias へ置き換えた。旧実装は略称の半数に当たらず
    （Lハナビ→新ハナビ の誤当たりを含む）、当たらないたびに実績DBを読み直す
    match_machine_names に落ちて遅かった。
    """
    if not text:
        return []
    return _model_alias.resolve(str(text), names)["names"]


def _history_matches_legacy(hall, text, names):
    if not text:
        return []
    exact = [n for n in names if n and n in text]
    if exact:
        return exact
    normalized = unicodedata.normalize("NFKC", text).lower()
    partial = [
        n
        for n in names
        if unicodedata.normalize("NFKC", n).lower() in normalized
        or normalized in unicodedata.normalize("NFKC", n).lower()
    ]
    if partial:
        return partial
    # Most result reports use a short model alias (e.g. カバネリ). Resolve
    # those locally before falling back to match_machine_names, which loads
    # the hall DB and is deliberately reserved for genuinely fuzzy cases.
    tokens = re.findall(r"[A-Za-z0-9ぁ-んァ-ヶ一-龯]{3,}", normalized)
    token_hits = [n for n in names if any(t in unicodedata.normalize("NFKC", n).lower() for t in tokens)]
    if token_hits:
        return token_hits
    try:
        return [x["machine_name"] for x in match_machine_names(hall, text) if x.get("score", 0) >= 0.6]
    except FileNotFoundError, sqlite3.Error, ValueError:
        return []


def _history_table_columns(con, table):
    return {r[1] for r in con.execute("pragma table_info(%s)" % table).fetchall()}


def _history_result_data(hall, business_date, asof, links_path, analysis_db):
    latest = _latest_link_rows(links_path).get((hall, business_date))
    if not latest:
        # EVENT_DAYS に無い日（公約のまとまりで入る楽園の7のつく日など）は結びつき台帳にも行が無い。
        # その場合もホール名×営業日で結果発表を直接引く（下でホール名を絞る）。
        latest = {"status": "台帳外"}
    report_ids = set(latest.get("report_ids", []))
    reports, machines, models = [], [], []
    if not os.path.exists(analysis_db):
        return {
            "status": latest.get("status", "未発表"),
            "delay_days": None,
            "reports": [],
            "machines": [],
            "models": [],
        }
    with _ro_connect(analysis_db) as con:
        tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        if "external_result_reports" not in tables:
            return {
                "status": latest.get("status", "未発表"),
                "delay_days": latest.get("delay_days"),
                "reports": [],
                "machines": [],
                "models": [],
            }
        has_hall = "hall_name" in _history_table_columns(con, "external_result_reports")
        report_rows = con.execute(
            "select report_id,posted_at,tweet_url,%s from external_result_reports where business_date=?"
            % ("hall_name" if has_hall else "NULL"),
            (business_date,),
        ).fetchall()
        valid_reports = {
            str(r[0]): r
            for r in report_rows
            if (str(r[0]) in report_ids if report_ids else (not has_hall or _normalize_hall(r[3]) == hall))
            and _before_asof(r[1], asof)
        }
        reports = [{"report_id": k, "posted_at": v[1], "tweet_url": v[2]} for k, v in valid_reports.items()]
        if not valid_reports:
            return {"status": "未発表", "delay_days": None, "reports": [], "machines": [], "models": []}
        mcols = (
            _history_table_columns(con, "external_result_machines") if "external_result_machines" in tables else set()
        )
        if "external_result_machines" in tables:
            fields = [
                x
                for x in ("report_id", "machine_number", "actual_name", "granularity", "granularity_source")
                if x in mcols
            ]
            for row in con.execute(
                "select %s from external_result_machines where business_date=?" % ",".join(fields), (business_date,)
            ).fetchall():
                d = dict(zip(fields, row))
                if str(d.get("report_id")) in valid_reports and _normalize_hall(d.get("hall_name", hall)) == hall:
                    machines.append(d)
        if "external_result_models" in tables:
            for row in con.execute(
                "select report_id,granularity,model_name,n_target,n_total,number_from,number_to from external_result_models where report_id in (%s)"
                % (",".join("?" * len(valid_reports)) or "NULL"),
                tuple(valid_reports),
            ).fetchall():
                models.append(
                    dict(
                        zip(
                            (
                                "report_id",
                                "granularity",
                                "model_name",
                                "n_target",
                                "n_total",
                                "number_from",
                                "number_to",
                            ),
                            row,
                        )
                    )
                )
    business = _asof_date(business_date)
    delays = [(_posted_date(r["posted_at"]) - business).days for r in reports if _posted_date(r["posted_at"])]
    return {
        "status": latest.get("status", "linked"),
        "delay_days": min(delays) if delays else latest.get("delay_days"),
        "reports": reports,
        "machines": machines,
        "models": models,
    }


def _history_field_obs(hall, business_date, asof, path):
    out = []
    if not os.path.exists(path):
        return out
    for row in _load_jsonl(path):
        if _normalize_hall(row.get("hall")) != hall or str(row.get("business_date")) != business_date:
            continue
        if not _before_asof(row.get("registered_at"), asof):
            continue
        out.append(row)
    return out


def _history_score(day, frame, row, event_date):
    seg = row.get("segment")
    if seg in {"JUG", "HANA", "OKI", "BT"}:
        hist = frame[
            (frame["machine_number"] == row["machine_number"])
            & (frame["machine_name"] == row["machine_name"])
            & (frame["date"] < event_date)
            & (frame["dt"] >= pd.Timestamp(event_date) - pd.Timedelta(days=30))
        ]
        baseline = hist["rb_rate"].mean() if not hist.empty else None
        value = row.get("rb_rate")
        return {
            "value": None if pd.isna(value) else float(value),
            "baseline": None if pd.isna(baseline) else float(baseline),
            "ratio": None if baseline in (None, 0) or pd.isna(baseline) or pd.isna(value) else float(value / baseline),
        }
    model = day[day["machine_name"] == row["machine_name"]]
    pool = day["games_normalized"].mean()
    if model.empty or not pool:
        return {"value": None}
    gratio = model["games_normalized"].mean() / pool
    return {
        "value": float(gratio * model["diff_coins_normalized"].mean()),
        "gratio": float(gratio),
        "model_mean_diff": float(model["diff_coins_normalized"].mean()),
    }


def _is_precise_label(label):
    """その台に設定が入ったと台単位で言えるラベルか。"""
    if label.get("source") == "台":
        return True
    return str(label.get("granularity", "")).startswith("全")


def _label_category(granularity):
    g = str(granularity or "")
    if g.startswith("全"):
        return "全台"
    if "並び" in g:
        return "並び"
    if "/" in g:
        return "1/N"
    return "種類なし"


def _label_breakdown(rows):
    """ラベルの種類ごとの台数。「対象台103台」を全台と読み違えないよう分けて出す（2026-09-28）。

    台を特定できるラベル（precise）と、機種単位でどの台か分からないもの（粒度不一致）を別に数える。
    """
    out = {"全台": 0, "1/N": 0, "並び": 0, "種類なし": 0, "粒度不一致": 0}
    for r in rows:
        labels = r.get("labels") or []
        if not labels:
            continue
        precise = [x for x in labels if _is_precise_label(x)]
        if precise:
            cats = [_label_category(x.get("granularity")) for x in precise]
            # 同じ台に複数付いたら、種類の分かるものを優先する
            cat = next((c for c in ("全台", "並び", "1/N") if c in cats), "種類なし")
            out[cat] += 1
        else:
            out["粒度不一致"] += 1
    return out


def _dedupe_labels(labels):
    seen, out = set(), []
    for x in labels:
        key = (x.get("source"), x.get("granularity"))
        if key not in seen:
            seen.add(key)
            out.append(x)
    return out


def _setting_verdict(item, diff):
    """その台に設定が入っていたかの判断と、その根拠・食い違いを返す。

    情報の重み（2026-09-28 ユーザー決定）: 演出での設定確認 > 主催者ラベル > 現地組の報告 > 実績の数値。
    上位の情報があればそれを採り、下位の情報と食い違ったことは conflicts に残す（消さない）。
    例: 9/27 楽園エウレカ3227 は差枚-714 だが演出で設定5以上を確認 → 入っていた（差枚マイナスと食い違い）。
    """
    obs = item.get("field_obs", [])
    confirmed = [o for o in obs if o.get("source_kind") == "effect_confirmed"]
    group = [o for o in obs if o.get("source_kind") in ("field_group", "sns")]
    conflicts = []
    if confirmed:
        o = confirmed[-1]
        basis = "演出確認" + (" 設定%s" % o["setting_text"] if o.get("setting_text") else "")
    elif item.get("precise_label"):
        basis = "主催者ラベル"
    elif group:
        basis = "現地組の報告"
    else:
        return None
    if diff is not None and diff <= 0:
        conflicts.append("差枚マイナス")
    if basis != "主催者ラベル" and item.get("labels") is not None and not item.get("precise_label"):
        conflicts.append("主催者ラベルなし" if not item.get("labels") else "主催者ラベルは粒度不一致")
    return {"value": "入っていた", "basis": basis, "conflicts": conflicts}


def _claim_summary(result):
    """予告 JSON の result を、公約ごとの的中／外れの短い一覧にする。"""
    out = []
    for c in (result or {}).get("claims", []):
        claim = c.get("claim", {})
        what = (
            claim.get("machine_name")
            or ",".join(str(v) for v in claim.get("values", []) or [])
            or claim.get("n_models")
            or ""
        )
        hit = c.get("hit")
        out.append("%s(%s)=%s" % (c.get("type"), what, {True: "的中", False: "外れ", None: "判定なし"}.get(hit, hit)))
    return out


def _history_day(hall, business_date, event_rows, announces, frame, result, asof, field_obs_path):
    day = frame[frame["date"].astype(str) == business_date].copy()
    current = (
        frame[(frame["date"].astype(str) < asof)].sort_values("date").drop_duplicates("machine_number", keep="last")
    )
    current_map = current.set_index("machine_number").to_dict("index") if not current.empty else {}
    names = sorted(day["machine_name"].dropna().unique().tolist())
    payloads = [x["payload"] for x in announces if str(x["payload"].get("target_date")) == business_date]
    claims = [c for p in payloads for c in p.get("claims", []) if c.get("type") in {"model_named", "model_named_ratio"}]
    announced_names = set()
    for claim in claims:
        announced_names.update(_history_matches(hall, str(claim.get("machine_name", "")), names))
    # Direct machine labels and model labels are kept separately so that a
    # model-level 1/2 label cannot masquerade as a precise machine label.
    labels = defaultdict(list)
    missing = []
    for m in result["machines"]:
        n = m.get("machine_number")
        labels[n].append({"granularity": m.get("granularity") or "台", "source": "台"})
        if n not in set(day["machine_number"]):
            missing.append(n)
    unresolved_labels = []
    day_numbers = set(int(x) for x in day["machine_number"])
    numbers_by_name = {k: set(int(x) for x in g["machine_number"]) for k, g in day.groupby("machine_name")}
    # 同じ結果発表の画像から取れた台番号。「とある2」のような略称をどちらの機種か決める手がかりにする。
    report_numbers = defaultdict(set)
    for m in result["machines"]:
        if m.get("machine_number") is not None:
            report_numbers[str(m.get("report_id"))].add(int(m["machine_number"]))
    for model in result["models"]:
        text = str(model.get("model_name", ""))
        res = _model_alias.resolve(
            text, names, numbers_by_name=numbers_by_name, hint_numbers=report_numbers.get(str(model.get("report_id")))
        )
        granularity = model.get("granularity") or "機種"
        for part in res["unresolved"]:
            unresolved_labels.append({"text": part["part"], "status": part["status"], "granularity": granularity})
        # 台番号の範囲が書かれていれば（列 number_from/number_to か機種欄の "2116-2118"）、
        # その範囲の台だけに付ける。どの台かが分かるので台単位のラベルとして扱う。
        ranges = list(res["ranges"])
        if model.get("number_from") and model.get("number_to"):
            ranges.append((int(model["number_from"]), int(model["number_to"])))
        if ranges:
            for lo, hi in ranges:
                for n in range(min(lo, hi), max(lo, hi) + 1):
                    if n not in day_numbers:
                        continue
                    if res["names"] and day.loc[day["machine_number"] == n, "machine_name"].iloc[0] not in res["names"]:
                        continue
                    labels[n].append({"granularity": granularity, "source": "台", "model_name": text})
            continue
        for name in res["names"]:
            for n in day.loc[day["machine_name"] == name, "machine_number"]:
                labels[n].append({"granularity": granularity, "source": "機種", "model_name": text})
    # 現場の報告（演出での設定確認・現地組の報告）。台番号で書かれたものと、機種で書かれた
    # もの（「モンハンライズ全」）がある。機種の報告はその日の設置台すべてに付ける。
    field_obs = _history_field_obs(hall, business_date, asof, field_obs_path)
    obs_by_number = defaultdict(list)
    for obs in field_obs:
        if obs.get("machine_number") not in (None, ""):
            obs_by_number[int(obs["machine_number"])].append(obs)
        elif obs.get("machine_name"):
            for name in _history_matches(hall, str(obs["machine_name"]), names):
                for n in day.loc[day["machine_name"] == name, "machine_number"]:
                    obs_by_number[int(n)].append(obs)
    numbers = (
        set(labels) | set(day.loc[day["machine_name"].isin(announced_names), "machine_number"]) | set(obs_by_number)
    )
    rows = []
    for n in sorted(numbers, key=lambda x: str(x)):
        actual = day[day["machine_number"] == n]
        item = {
            "machine_number": n,
            "labels": labels.get(n, []),
            "announced": bool(not actual.empty and actual.iloc[0]["machine_name"] in announced_names),
            "current_machine_name": current_map.get(n, {}).get("machine_name"),
        }
        if actual.empty:
            item["classification"] = "ラベルあり・実績DBに台が無い"
            rows.append(item)
            continue
        r = actual.iloc[0].to_dict()
        r["segment"] = str(assign_segment(pd.DataFrame([r])).iloc[0])
        item.update(
            {
                "machine_name": r["machine_name"],
                "segment": r["segment"],
                "diff": r.get("diff_coins_normalized"),
                "games": r.get("games_normalized"),
                "score": _history_score(day, frame, r, business_date),
                "machine_change": item["current_machine_name"] not in (None, r["machine_name"]),
            }
        )
        # 台を特定できるラベルは「台単位の公表」と「機種単位の全台」だけ。機種単位の
        # 1/2・1/3・3台並び等は、その機種のどの台かが分からない（2026-09-28、東京喰種の
        # 「3台並び」を17台全部に付けて9台を不発台と誤判定したため修正）。
        item["labels"] = _dedupe_labels(labels.get(n, []))
        item["precise_label"] = any(_is_precise_label(x) for x in item["labels"])
        if item["labels"] and not item["precise_label"]:
            item["classification"] = "粒度不一致"
        elif item["labels"]:
            item["classification"] = (
                "ラベルあり・差枚プラス"
                if (r.get("diff_coins_normalized") or 0) > 0
                else "ラベルあり・差枚マイナス（不発台）"
            )
        elif item["announced"] and (r.get("diff_coins_normalized") or 0) > 0:
            item["classification"] = "ラベルなし・差枚プラス"
        else:
            item["classification"] = None
        item["field_obs"] = obs_by_number.get(int(n), [])
        item["verdict"] = _setting_verdict(item, r.get("diff_coins_normalized"))
        rows.append(item)
    return {
        "business_date": business_date,
        "weekday": "月火水木金土日"[_asof_date(business_date).weekday()],
        "event_names": sorted(
            {r.get("event_name") for r in event_rows if str(r.get("date")) == business_date and r.get("event_name")}
        ),
        "announces": [
            {"account": p.get("source", {}).get("account"), "announce_id": p.get("announce_id")} for p in payloads
        ],
        "pledge_keys": sorted(set().union(*(pledge_keys(p) for p in payloads))) if payloads else [],
        "result": {k: result[k] for k in ("status", "delay_days", "reports")},
        "machines": rows,
        "field_obs": field_obs,
        "unresolved_labels": unresolved_labels,
        "summary": {
            "label_breakdown": _label_breakdown(rows),
            "labeled_count": sum(bool(x.get("precise_label")) for x in rows),
            "partial_label_count": sum(x.get("classification") == "粒度不一致" for x in rows),
            "negative_count": sum(x.get("classification") == "ラベルあり・差枚マイナス（不発台）" for x in rows),
            "claims": [s for p in payloads for s in _claim_summary(p.get("result"))],
        },
    }


def build_history(
    hall,
    target_date,
    *,
    series_ids=None,
    pledge_args=None,
    asof=None,
    event_ledger=LEDGER,
    series_ledger=SERIES_LEDGER,
    announce_dir=None,
    links_path=RESULT_LINKS_LEDGER,
    analysis_db=RESULT_DB,
    field_obs_path=FIELD_OBS,
):
    hall = _normalize_hall(hall)
    asof = asof or target_date
    announce_dir = announce_dir or os.path.join(ROOT, "backtest", "announce")
    dates, events, announces, target_keys = _history_groups(
        hall, target_date, asof, series_ids or [], pledge_args or [], event_ledger, series_ledger, announce_dir
    )
    frame = load_frame(hall)
    frame["date"] = frame["date"].astype(str)
    histories = []
    for business_date in sorted(dates, reverse=True):
        day_events = [e for e in events if str(e.get("date")) == business_date]
        result = _history_result_data(hall, business_date, asof, links_path, analysis_db)
        histories.append(_history_day(hall, business_date, day_events, announces, frame, result, asof, field_obs_path))
    prior = frame[(frame["date"] < asof) & (frame["dt"] >= pd.Timestamp(_asof_date(asof)) - pd.Timedelta(days=30))]
    trend = []
    if not prior.empty and prior["games_normalized"].mean():
        for name, g in prior.groupby("machine_name"):
            trend.append(
                {
                    "machine_name": name,
                    "score": float(
                        g["games_normalized"].mean()
                        / prior["games_normalized"].mean()
                        * g["diff_coins_normalized"].mean()
                    ),
                    "gratio": float(g["games_normalized"].mean() / prior["games_normalized"].mean()),
                    "mean_diff": float(g["diff_coins_normalized"].mean()),
                }
            )
    trend.sort(key=lambda x: x["score"], reverse=True)
    repeats = {"machine_name": defaultdict(int), "machine_number": defaultdict(int), "last_digit": defaultdict(int)}
    n_results = sum(bool(h["result"].get("reports")) for h in histories)
    # 「何回の開催で出たか」を数える。1回の中で同じ機種・台番号・末尾は1回とする。
    for h in histories:
        labeled = [m for m in h["machines"] if m.get("precise_label")]
        for key, values in (
            ("machine_name", {m.get("machine_name") for m in labeled}),
            ("machine_number", {str(m.get("machine_number")) for m in labeled}),
            ("last_digit", {str(m.get("machine_number"))[-1] for m in labeled}),
        ):
            for v in values:
                repeats[key][v] += 1
    repeated = {
        k: [{"value": v, "count": c, "of": n_results} for v, c in d.items() if c >= 2] for k, d in repeats.items()
    }
    changes = [
        r for r in events if str(r.get("date")) < target_date and str(r.get("kind")) in {"renovation", "manager"}
    ]

    # 広い公約（そのホールの予告の半分以上に付く「全台系あり」等）だけで入った回は、
    # 詳細を出さず要約と集計にだけ使う（楽園 9/28 は29回・3,758行になった）。
    key_counts = defaultdict(int)
    for item in announces:
        for k in pledge_keys(item["payload"]):
            key_counts[k] += 1
    n_ann = len(announces)
    generic_keys = sorted(k for k, c in key_counts.items() if n_ann >= 4 and c / n_ann >= 0.5)
    hall_mean = frame.groupby("date")["diff_coins_normalized"].mean().to_dict()
    for h in histories:
        groups = sorted(dates[h["business_date"]]["groups"])
        h["groups"] = groups
        h["detail"] = any(not g.startswith("pledge:") or g[len("pledge:") :] not in generic_keys for g in groups)
        h["hall_mean_diff"] = hall_mean.get(h["business_date"])

    return {
        "hall": hall,
        "target_date": target_date,
        "asof": asof,
        "target_pledge_keys": sorted(target_keys),
        "generic_pledge_keys": generic_keys,
        "histories": histories,
        "trend_top10": trend[:10],
        "repeated": repeated,
        "result_days": n_results,
        # 全台に選ばれた機種と、予告あり/なしの比較は、表に載った回だけでなくホールの
        # 結果発表のある全ての日で数える（表の回は公約で集めているので全部「予告あり」になる）。
        "zentai_overview": _hall_zentai_overview(hall, asof, analysis_db, frame, announces),
        "tail_share": _tail_share(histories, frame),
        "changes": sorted(changes, key=lambda x: str(x.get("date"))),
    }


def _hall_zentai_overview(hall, asof, analysis_db, frame, announces):
    """ホールの結果発表のある全ての日について、全台に選ばれた機種と、全台系の予告の有無を集計する。

    - 全台 = 主催者ラベルの粒度が「全」で始まるもの（機種単位・台単位の両方）。
    - 予告あり = その日の予告（active/retroactive）に 全台系:N機種 か 機種指名:全 がある日。
      予告なし = 予告が無い日と、予告に全台系の公約が無い日。
    - asof より後に投稿された結果発表は使わない。平均だけを出し、検定はしない。
    """
    if not os.path.exists(analysis_db):
        return {}
    ann_by_date = defaultdict(list)
    for item in announces:
        ann_by_date[str(item["payload"].get("target_date"))].append(item["payload"])
    with _ro_connect(analysis_db) as con:
        tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        needed = {"external_result_reports", "external_result_models", "external_result_machines"}
        if not needed <= tables or "hall_name" not in _history_table_columns(con, "external_result_reports"):
            return {}
        reports = con.execute(
            "select report_id, business_date, posted_at, hall_name from external_result_reports where business_date < ?",
            (asof,),
        ).fetchall()
        reports = [r for r in reports if _normalize_hall(r[3]) == hall and _before_asof(r[2], asof)]
        by_date = defaultdict(list)
        for rid, d, _, _ in reports:
            by_date[str(d)].append(str(rid))
        models = defaultdict(list)
        machines = defaultdict(list)
        for d, rids in by_date.items():
            q = ",".join("?" * len(rids))
            models[d] = con.execute(
                "select granularity, model_name from external_result_models where report_id in (%s)" % q, rids
            ).fetchall()
            machines[d] = con.execute(
                "select granularity, machine_number from external_result_machines where report_id in (%s)" % q, rids
            ).fetchall()
    names_by_date = {d: sorted(g["machine_name"].dropna().unique()) for d, g in frame.groupby("date")}
    name_by_num = {d: dict(zip(g["machine_number"], g["machine_name"])) for d, g in frame.groupby("date")}
    hall_mean = frame.groupby("date")["diff_coins_normalized"].mean().to_dict()
    days = []
    for d in sorted(by_date):
        names = names_by_date.get(d, [])
        zentai = set()
        for g, text in models[d]:
            if str(g or "").startswith("全"):
                zentai.update(_model_alias.resolve(str(text), names)["names"])
        for g, n in machines[d]:
            if str(g or "").startswith("全") and n in name_by_num.get(d, {}):
                zentai.add(name_by_num[d][n])
        declared = any(
            k.startswith("全台系:") or k == "機種指名:全" for p in ann_by_date.get(d, []) for k in pledge_keys(p)
        )
        days.append(
            {
                "date": d,
                "declared": declared,
                "has_announce": bool(ann_by_date.get(d)),
                "zentai": sorted(zentai),
                "hall_mean_diff": hall_mean.get(d),
            }
        )
    counts = defaultdict(lambda: {"declared": 0, "not_declared": 0})
    for x in days:
        for name in x["zentai"]:
            counts[name]["declared" if x["declared"] else "not_declared"] += 1
    model_rows = sorted(
        ({"machine_name": k, **v, "total": v["declared"] + v["not_declared"]} for k, v in counts.items()),
        key=lambda r: (-r["total"], r["machine_name"]),
    )
    groups = {}
    for key, pick in (("declared", True), ("not_declared", False)):
        xs = [x for x in days if x["declared"] == pick]
        diffs = [x["hall_mean_diff"] for x in xs if x["hall_mean_diff"] is not None]
        groups[key] = {
            "n": len(xs),
            "with_announce": sum(x["has_announce"] for x in xs),
            "zentai_models_mean": (sum(len(x["zentai"]) for x in xs) / len(xs)) if xs else None,
            "days_with_zentai": sum(bool(x["zentai"]) for x in xs),
            "hall_mean_diff_mean": (sum(diffs) / len(diffs)) if diffs else None,
        }
    return {"n_days": len(days), "models": model_rows, "groups": groups}


def _declared_zentai(h):
    """その回の予告が全台系を約束していたか（全台系:N機種 か 機種指名:全）。"""
    return any(k.startswith("全台系:") or k == "機種指名:全" for k in h.get("pledge_keys", []))


def _zentai_model_names(h):
    """その回に全台ラベルが付いた機種（台を特定できる全台ラベルの台がある機種）。"""
    out = set()
    for m in h["machines"]:
        if any(_label_category(x.get("granularity")) == "全台" and _is_precise_label(x) for x in m.get("labels", [])):
            if m.get("machine_name"):
                out.add(m["machine_name"])
    return out


def _zentai_models(histories):
    """全台に選ばれた機種の回数。予告が全台系を約束した回としなかった回に分けて数える。

    分母は結果発表がある回だけ（発表の無い回は全台が無かったとは言えない）。
    """
    with_result = [h for h in histories if h["result"].get("reports")]
    declared = [h for h in with_result if _declared_zentai(h)]
    counts = defaultdict(lambda: {"declared": 0, "not_declared": 0})
    for h in with_result:
        for name in _zentai_model_names(h):
            counts[name]["declared" if _declared_zentai(h) else "not_declared"] += 1
    rows = [
        {
            "machine_name": k,
            "declared": v["declared"],
            "not_declared": v["not_declared"],
            "total": v["declared"] + v["not_declared"],
        }
        for k, v in counts.items()
    ]
    rows.sort(key=lambda x: (-x["total"], x["machine_name"]))
    return {"n_result_days": len(with_result), "n_declared": len(declared), "models": rows}


def _declared_vs_not(histories):
    """全台系を約束した回としなかった回の違い（結果発表のある回だけ）。平均だけで検定はしない。"""
    out = {}
    for label, pick in (("declared", True), ("not_declared", False)):
        hs = [h for h in histories if h["result"].get("reports") and _declared_zentai(h) == pick]
        if not hs:
            out[label] = {"n": 0}
            continue
        out[label] = {
            "n": len(hs),
            "zentai_models_mean": sum(len(_zentai_model_names(h)) for h in hs) / len(hs),
            "labeled_machines_mean": sum(h["summary"]["labeled_count"] for h in hs) / len(hs),
            "hall_mean_diff_mean": sum((h.get("hall_mean_diff") or 0) for h in hs) / len(hs),
            "dates": [h["business_date"] for h in hs],
        }
    return out


def _tail_share(histories, frame):
    """末尾ごとに「ラベル台に占める割合」と「その日の全台に占める割合」を比べる。

    ラベル台が数十〜百台ある回では、どの末尾にも毎回ラベル台が入るので回数は情報にならない
    （楽園 9/28 で末尾8が19回中19回）。割合の比（>1 なら偏り）で見る。
    """
    labeled = defaultdict(int)
    total = defaultdict(int)
    for h in histories:
        if not h["result"].get("reports"):
            continue
        day = frame[frame["date"] == h["business_date"]]
        for n in day["machine_number"]:
            total[str(int(n))[-1]] += 1
        for m in h["machines"]:
            if m.get("precise_label"):
                labeled[str(m["machine_number"])[-1]] += 1
    n_lab, n_tot = sum(labeled.values()), sum(total.values())
    if not n_lab or not n_tot:
        return []
    rows = []
    for d in sorted(total):
        share_lab, share_tot = labeled[d] / n_lab, total[d] / n_tot
        rows.append(
            {
                "digit": d,
                "labeled": labeled[d],
                "labeled_share": share_lab,
                "hall_share": share_tot,
                "ratio": share_lab / share_tot if share_tot else None,
            }
        )
    rows.sort(key=lambda x: -(x["ratio"] or 0))
    return rows


def cmd_history(a):
    result = build_history(
        a.hall,
        a.target_date,
        series_ids=a.series,
        pledge_args=a.pledge,
        asof=a.asof,
        event_ledger=a.event_ledger,
        series_ledger=a.series_ledger,
        announce_dir=a.announce_dir,
        links_path=a.links_ledger,
        analysis_db=a.analysis_db,
        field_obs_path=a.field_obs,
    )
    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    print(render_history(result))
    return 0


def _render_machine_row(m):
    score = m.get("score", {}) or {}
    if m.get("segment") in {"JUG", "HANA", "OKI", "BT"}:
        value = None if score.get("ratio") is None else "RB比%.2f" % score["ratio"]
    else:
        value = None if score.get("value") is None else "機種%+.0f" % score["value"]
    v = m.get("verdict")
    obs = ";".join(str(x.get("observation", x.get("text", ""))) for x in m.get("field_obs", []))
    if v:
        obs = (obs + " → " if obs else "") + "%s（%s%s）" % (
            v["value"],
            v["basis"],
            "・食い違い: " + "/".join(v["conflicts"]) if v["conflicts"] else "",
        )
    label = ",".join(x.get("granularity", "") for x in m.get("labels", [])) or "なし"
    name = m.get("machine_name", "-")
    if m.get("machine_change"):
        name += "（今は%s）" % m.get("current_machine_name")
    diff = m.get("diff")
    games = m.get("games")
    return "%s | %s | %s | %s | %s | %s | %s | %s | %s | %s" % (
        m.get("machine_number"),
        name,
        m.get("segment", "-"),
        "○" if m.get("announced") else "",
        label,
        "-" if diff is None else "%+.0f" % diff,
        "-" if games is None else "%.0f" % games,
        value if value is not None else "-",
        m.get("classification") or "-",
        obs,
    )


def _render_at_group(name, ms):
    """AT機を機種ごとに1行にまとめる。"""
    labels = sorted({x.get("granularity", "") for m in ms for x in m.get("labels", [])}) or ["なし"]
    diffs = [m.get("diff") for m in ms if m.get("diff") is not None]
    plus = sum(1 for d in diffs if d > 0)
    value = (ms[0].get("score") or {}).get("value")
    changed = [m for m in ms if m.get("machine_change")]
    nums = sorted(int(m["machine_number"]) for m in ms)
    rng = "%d〜%d" % (nums[0], nums[-1]) if len(nums) > 1 else str(nums[0])
    cls = defaultdict(int)
    for m in ms:
        cls[m.get("classification") or "-"] += 1
    return "%s | %s（%d台%s） | AT | %s | %s | %s | - | %s | %s | " % (
        rng,
        name,
        len(ms),
        "・うち%d台入替" % len(changed) if changed else "",
        "○" if any(m.get("announced") for m in ms) else "",
        ",".join(labels),
        "プラス%d/マイナス%d（%+.0f〜%+.0f）" % (plus, len(diffs) - plus, min(diffs), max(diffs)) if diffs else "-",
        "-" if value is None else "機種%+.0f" % value,
        "、".join("%s%d" % (k, v) for k, v in cls.items()),
    )


def render_history(result):
    """build_history の結果を、ターミナル・テキストファイル向けの表にする。"""
    out = []
    print = out.append  # noqa: A001 — 下の表組みを print のまま流用するため
    print(f"{result['hall']} history target={result['target_date']} asof={result['asof']}")
    if not result["histories"]:
        print("（同じイベント・同じ公約の過去の回が見つからない）")
    else:
        # 回が多いと詳細が数千行になるので、先に1回1行の要約を出す。
        print(
            "\n--- 要約（新しい順。[詳]=下に詳細あり [要]=広い公約だけで一致したので要約のみ。ラベル=台を特定できる主催者ラベルの台数） ---"
        )
        for h in result["histories"]:
            s = h["summary"]
            hits = sum("=的中" in c for c in s["claims"])
            print(
                "%s %s(%s) %s | 結果=%s | ラベル%d台(うちマイナス%d) | 現場報告%d件 | 予告の採点 %d/%d 的中"
                % (
                    "[詳]" if h.get("detail", True) else "[要]",
                    h["business_date"],
                    h["weekday"],
                    "/".join(h["event_names"]) or "-",
                    h["result"]["status"],
                    s["labeled_count"],
                    s["negative_count"],
                    len(h["field_obs"]),
                    hits,
                    len(s["claims"]),
                )
            )
    if result.get("generic_pledge_keys"):
        print(
            "\n※ 広い公約（このホールの予告の半分以上に付く）: %s。これだけで一致した回は要約と集計のみ。"
            % "、".join(result["generic_pledge_keys"])
        )
    for h in result["histories"]:
        if not h.get("detail", True):
            continue
        r = h["result"]
        print(
            f"\n=== {h['business_date']} ({h['weekday']}) {'/'.join(h['event_names']) or '-'} | 先バレ={','.join(x['account'] or '-' for x in h['announces']) or '-'} | 公約={','.join(h['pledge_keys']) or '-'} | 結果={r['status']} 遅れ={r['delay_days'] if r['delay_days'] is not None else '-'}日 ==="
        )
        print("台番号 | 機種（入替） | 区分 | 指名 | ラベル | 差枚 | G | 判定値 | 分類 | 現場報告")
        # AT機は台単位で設定を判定できないので機種ごとに1行。ノーマル・BTは台ごとのRB比に意味があるので1台1行。
        at_groups = defaultdict(list)
        for m in h["machines"]:
            if m.get("segment") == "AT" and not m.get("field_obs"):
                at_groups[m.get("machine_name")].append(m)
                continue
            print(_render_machine_row(m))
        for name, ms in at_groups.items():
            print(_render_at_group(name, ms))
        s = h["summary"]
        b = s.get("label_breakdown", {})
        print(
            "集計: 全台%d台 / 並び%d台 / 1/N%d台 / 種類なし%d台（台を特定できる計%d台、うち差枚マイナス%d）/ どの台か分からない%d台"
            % (
                b.get("全台", 0),
                b.get("並び", 0),
                b.get("1/N", 0),
                b.get("種類なし", 0),
                s["labeled_count"],
                s["negative_count"],
                b.get("粒度不一致", 0),
            )
        )
        if h.get("unresolved_labels"):
            print(
                "照合できなかった発表: "
                + "、".join(
                    "%s(%s・%s)"
                    % (u["text"], u["granularity"], "判断不能" if u["status"] == "ambiguous" else "該当なし")
                    for u in h["unresolved_labels"]
                )
            )
        if s["claims"]:
            print("予告の採点: " + " / ".join(s["claims"]))
    print("\n直近30日 G比×平均差枚 上位10")
    for x in result["trend_top10"]:
        print(f"{x['machine_name']}\t{x['score']:.1f}\tG比={x['gratio']:.3f}\t平均差枚={x['mean_diff']:.1f}")
    z = result.get("zentai_overview") or {}
    if z.get("n_days"):
        g = z["groups"]
        print(
            "\n全台に選ばれた機種（このホールで結果発表のある全%d日。全台系を予告した日%d・しなかった日%d）"
            % (z["n_days"], g["declared"]["n"], g["not_declared"]["n"])
        )
        for x in z["models"][:15]:
            print(
                "  %s: %d日（予告あり%d・なし%d）" % (x["machine_name"], x["total"], x["declared"], x["not_declared"])
            )
        print("\n全台系を予告した日としなかった日（平均。日数が少ないので参考値、検定はしていない）")
        for key, title in (("declared", "予告あり"), ("not_declared", "予告なし")):
            x = g.get(key, {})
            if not x.get("n"):
                print("  %s: 0日" % title)
                continue
            print(
                "  %s: %d日（うち予告が出ていた日%d）| 全台があった日 %d | 全台の機種数 %.1f | ホール平均差枚 %s"
                % (
                    title,
                    x["n"],
                    x["with_announce"],
                    x["days_with_zentai"],
                    x["zentai_models_mean"],
                    "-" if x["hall_mean_diff_mean"] is None else "%+.0f" % x["hall_mean_diff_mean"],
                )
            )
    print("\n過去の回で繰り返しラベルが付いたもの（結果発表のあった %d 回中）" % result["result_days"])
    for key, title in (("machine_name", "機種"), ("machine_number", "台番号")):
        items = sorted(result["repeated"].get(key, []), key=lambda x: -x["count"])[:15]
        print("  %s: %s" % (title, "、".join("%s %d回" % (x["value"], x["count"]) for x in items) or "なし"))
    tails = result.get("tail_share") or []
    if tails:
        print(
            "  末尾（ラベル台に占める割合 ÷ 全台に占める割合。1より大きいほど偏り）: "
            + "、".join("%s:%.2f(%d台)" % (x["digit"], x["ratio"], x["labeled"]) for x in tails)
        )
    if result["changes"]:
        print("体制変化: " + ", ".join(f"{x.get('date')} {x.get('event_name', '')}" for x in result["changes"]))
    else:
        print("体制変化の台帳なし")
    return "\n".join(str(x) for x in out)


def morning_halls(business_date, event_ledger=LEDGER, announce_dir=None):
    """その日にイベント（EVENT_DAYS）か予告（announce、active）があるホール。"""
    announce_dir = announce_dir or os.path.join(ROOT, "backtest", "announce")
    halls = {
        _normalize_hall(r.get("hall")) for r in active(_load_jsonl(event_ledger)) if str(r.get("date")) == business_date
    }
    for bundle in load_announce_bundles(announce_dir).get("bundles", []):
        p = bundle["payload"]
        if bundle.get("status") == "active" and str(p.get("target_date")) == business_date:
            halls.add(_normalize_hall(p.get("hall")))
    return sorted(h for h in halls if h)


def cmd_morning(a):
    """朝の定例から呼ぶ。当日イベント・予告のあるホールごとに答え合わせ表を書き出す。

    1ホールの失敗で他を止めない（朝の処理全体を落とさない）。表は毎日作り直せるので
    output/event_history/ は git 管理外。
    """
    business_date = a.date or datetime.now(JST).strftime("%Y%m%d")
    out_dir = os.path.join(a.out_dir, business_date)
    halls = morning_halls(business_date, a.event_ledger, a.announce_dir)
    print("答え合わせ表 %s: 対象 %d ホール %s" % (business_date, len(halls), " / ".join(halls) or "-"))
    os.makedirs(out_dir, exist_ok=True)
    failed = 0
    for hall in halls:
        path = os.path.join(out_dir, re.sub(r"[\\/:*?\"<>|]", "_", hall))
        try:
            result = build_history(hall, business_date, announce_dir=a.announce_dir, event_ledger=a.event_ledger)
            text = render_history(result)
            with open(path + ".txt", "w", encoding="utf-8") as f:
                f.write(text + "\n")
            with open(path + ".json", "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        except Exception as exc:  # noqa: BLE001 — 1ホールの失敗で朝の処理を止めない
            failed += 1
            print("  %s: 失敗 %s: %s" % (hall, type(exc).__name__, exc))
            continue
        print("  %s: 過去の回 %d → %s.txt" % (hall, len(result["histories"]), path))
    return 1 if failed else 0


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
    s = sub.add_parser("history", help="同じイベントの過去回を答え合わせ表で表示する")
    s.add_argument("hall")
    s.add_argument("target_date")
    s.add_argument("--series", action="append", default=[])
    s.add_argument("--pledge", action="append", default=[])
    s.add_argument("--asof", default=None)
    s.add_argument("--json", action="store_true")
    s.add_argument("--event-ledger", default=LEDGER)
    s.add_argument("--series-ledger", default=SERIES_LEDGER)
    s.add_argument("--announce-dir", default=os.path.join(ROOT, "backtest", "announce"))
    s.add_argument("--links-ledger", default=RESULT_LINKS_LEDGER)
    s.add_argument("--analysis-db", default=RESULT_DB)
    s.add_argument("--field-obs", default=FIELD_OBS)
    s.set_defaults(fn=cmd_history)
    s = sub.add_parser("morning", help="当日イベント・予告のあるホールの答え合わせ表を書き出す（朝の定例用）")
    s.add_argument("--date", default=None, help="YYYYMMDD。省略時は当日（JST）")
    s.add_argument("--out-dir", default=os.path.join(ROOT, "output", "event_history"))
    s.add_argument("--event-ledger", default=LEDGER)
    s.add_argument("--announce-dir", default=os.path.join(ROOT, "backtest", "announce"))
    s.set_defaults(fn=cmd_morning)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
