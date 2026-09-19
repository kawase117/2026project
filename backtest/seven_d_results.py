# -*- coding: utf-8 -*-
"""SEVEN-D（@datagasubete）の楽園蒲田の結果投稿を、外部結果テーブルへ取り込む。

投稿の形式（機種名の列挙。台番号は無い）:

    5月20日(水)
    楽園蒲田

    《ハーフテン》
    総差枚+55183枚

    全台✍️
    ・東リベ

    1/2✍️
    ・ネオアイム
    ...
    2台機種から1/2が2機種

日付の書式は『5月20日(水)』と『9/6』（曜日なし）の両方がある。
対象は `state.db` の seen_tweets（handle=datagasubete）。`db/analysis_results.db` の
external_result_reports / external_result_models に、source='datagasubete' で入れる。
既存の report_id（tweet_id）はスキップする。楽園蒲田以外のホールの投稿は対象外。

使い方:
    venv\\Scripts\\python.exe -m backtest.seven_d_results            # 取り込み
    venv\\Scripts\\python.exe -m backtest.seven_d_results --dry-run  # 解析結果の確認のみ

⚠️ 分類（全台/1/2）は第三者の基準で、機種内の台数・台番号は分からない。閾値+1800の取りこぼし32〜36%と
同種の欠陥がある。実対象の台番号の代わりにはならない。
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_DB = os.path.join(ROOT, "scraper", "twitter_monitor", "state.db")
RESULT_DB = os.path.join(ROOT, "db", "analysis_results.db")
WEEKDAYS = "月火水木金土日"
HEAD = re.compile(r"^(?:(\d{1,2})月(\d{1,2})日|(\d{1,2})/(\d{1,2}))\s*(?:[（(]([月火水木金土日])[）)])?", re.M)


def parse(text, posted_at):
    """投稿本文から日付・イベント名・総差枚・分類別の機種を取り出す。楽園蒲田以外は None。

    分類の見出し（全台・1/2・1/3・3台以上並び・10台並び・全＋全で列全 など）は
    『・』で始まらない行として拾い、末尾の『✍️』は除く。
    """
    lines = [ln.strip() for ln in text.replace("\r", "").split("\n")]
    body = "\n".join(lines)
    m = HEAD.search(body)
    if not m or "楽園蒲田" not in body[:80]:
        return None
    mo = int(m.group(1) or m.group(3))
    d = int(m.group(2) or m.group(4))
    wd = m.group(5)
    posted = datetime.datetime.fromisoformat(posted_at)
    year = posted.year
    if datetime.date(year, mo, d) > posted.date():  # 年をまたぐ投稿の保険
        year -= 1
    date = datetime.date(year, mo, d)
    ev = re.search(r"《(.+?)》", body)
    tot = re.search(r"総差枚\s*([+\-−]?[\d,]+)\s*枚", body)
    models, gran = [], None
    started = False
    for ln in lines:
        if ln.startswith("《") or ln.startswith("総差枚"):
            started = True
            continue
        if not started or not ln:
            continue
        if ln.startswith("・"):
            if gran:
                models.append((gran, ln.lstrip("・").strip()))
        elif re.match(r"\d+台機種から1/2が\d+機種", ln):
            models.append(("1/2", "(%s)" % ln))
        elif ln.startswith("その他"):
            models.append(("その他", "(その他)"))
        else:
            gran = ln.replace("✍️", "").replace("✍", "").strip()
    return {
        "business_date": date.strftime("%Y%m%d"),
        "weekday_stated": wd,
        "weekday_ok": (int(WEEKDAYS[date.weekday()] == wd) if wd else None),
        "event_name": ev.group(1) if ev else None,
        "hall_total_diff": int(tot.group(1).replace(",", "").replace("−", "-")) if tot else None,
        "models": models,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    st = sqlite3.connect(STATE_DB)
    rows = st.execute(
        "select tweet_id,posted_at_jst,coalesce(full_text,tweet_text),full_text is null from seen_tweets "
        "where handle='datagasubete' order by posted_at_jst"
    ).fetchall()
    db = sqlite3.connect(RESULT_DB)
    have = {r[0] for r in db.execute("select report_id from external_result_reports")}
    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    n_new = n_skip = n_other = 0
    for tid, posted, text, truncated in rows:
        p = parse(text, posted)
        if p is None:
            n_other += 1
            continue
        flag = "（本文切れの可能性）" if truncated else ""
        print(
            "%s %s(%s) %-10s 全台%d 1/2 %d 総差枚%s%s"
            % (
                tid,
                p["business_date"],
                p["weekday_stated"],
                p["event_name"] or "-",
                sum(1 for g, _ in p["models"] if g == "全台"),
                sum(1 for g, _ in p["models"] if g == "1/2"),
                p["hall_total_diff"],
                flag,
            )
        )
        if tid in have:
            n_skip += 1
            continue
        n_new += 1
        if a.dry_run:
            continue
        db.execute(
            "insert into external_result_reports(report_id,source,tweet_url,posted_at,hall_name,business_date,"
            "weekday_stated,weekday_ok,event_name,target_machines,total_machines,target_pct,target_mean_diff,"
            "hall_total_diff,is_tracked_hall,raw_text,ingested_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                tid,
                "datagasubete",
                "https://x.com/datagasubete/status/" + tid,
                posted,
                "楽園蒲田店",
                p["business_date"],
                p["weekday_stated"],
                p["weekday_ok"],
                p["event_name"],
                None,
                None,
                None,
                None,
                p["hall_total_diff"],
                1,
                text,
                now,
            ),
        )
        for seq, (g, nm) in enumerate(p["models"]):
            db.execute(
                "insert into external_result_models(report_id,seq,granularity,model_name,n_target,n_total,"
                "mean_diff,number_from,number_to) values(?,?,?,?,?,?,?,?,?)",
                (tid, seq, g, nm, None, None, None, None, None),
            )
    db.commit()
    print("新規 %d / 既存 %d / 楽園蒲田以外・形式外 %d" % (n_new, n_skip, n_other))
    return 0


if __name__ == "__main__":
    sys.exit(main())
