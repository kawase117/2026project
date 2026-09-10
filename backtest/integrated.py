# -*- coding: utf-8 -*-
"""予告・結果発表・実績を1つの表に束ねる。

なぜ要るか
----------
3系統がそれぞれ別の場所に、別の形で溜まっている。

| 系統 | 置き場所 | 形 |
|---|---|---|
| 実績 | `db/<hall>.db` の `machine_detailed_results` | SQLite・台×日 |
| 予告 | `backtest/announce/*.json` | JSONファイル群 |
| 結果発表 | `db/analysis_results.db` の `external_result_*` | SQLite・機種×日／台×日 |

「あるホールのある日について、予告は何を言い、ホールは何を該当台と発表し、
実際はどうだったか」を引くのに、DBを3つ開いてJSONのディレクトリを走査する必要があった。
分析のたびに scratchpad で結合スクリプトを書き直していたのを、ここに一本化する。

設計方針
--------
- **実績DBには書かない。** `machine_layout` に日付次元を足すと約60ファイルの単純結合が
  静かに二重計上になった事例がある（`database/CLAUDE.md`）。同じ轍は踏まない。
  ここは読み取り専用の結合層であり、materialize するのは予告のインデックスだけ。
- **予告のJSONファイルが正本。** `announce_reports` はそこから作り直せる派生インデックスで、
  凍結の意味はファイル側にある（`backtest/announce/LEDGER.jsonl`）。
- **ホール名と営業日が結合キー。** ホール名は実績DBのファイル名と同じ表記に揃える。
  台単位まで降りるときは `machine_number` を足す。

⚠️ 予告JSONは安定コア（hall / target_date / source / zentaikei / claims / result）と、
その回限りの検討メモ（`tiger_dash_history` や `n9_roster` など60種以上）が混在している。
コアだけを列にし、残りは `payload_json` から引く。列を増やして追随しようとしない。
"""

import argparse
import glob
import json
import os
import sqlite3
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ANALYSIS_DB = os.path.join(ROOT, "db", "analysis_results.db")
ANNOUNCE_DIR = os.path.join(HERE, "announce")
HALL_DIR = os.path.join(ROOT, "db")

# 取り下げ・無効化されたファイルは取り込まない。ファイル名で分かるようにしてある。
EXCLUDED_MARKERS = ("withdrawn", "invalidated")

SCHEMA = """
CREATE TABLE IF NOT EXISTS announce_reports (
    announce_id     TEXT PRIMARY KEY,
    hall_name       TEXT NOT NULL,
    target_date     TEXT NOT NULL,      -- YYYYMMDD
    account         TEXT,
    posted_at       TEXT,
    kind            TEXT,               -- 予告 / 結果報告 など
    metric          TEXT,               -- zentaikei.metric
    threshold       REAL,
    min_machines    INTEGER,
    file_path       TEXT NOT NULL,
    announce_digest TEXT,
    payload_json    TEXT NOT NULL,      -- 全文。安定コア以外はここから引く
    ingested_at     TEXT NOT NULL,
    -- 0=事前登録（的中率に使ってよい） / 1=遡及（名指しの有無を引くだけ）
    retroactive     INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_ar_hall_date
    ON announce_reports(hall_name, target_date);

CREATE TABLE IF NOT EXISTS announce_claims (
    announce_id  TEXT NOT NULL REFERENCES announce_reports(announce_id),
    seq          INTEGER NOT NULL,
    claim_type   TEXT NOT NULL,         -- model_named / zentaikei_count / position_rule ...
    machine_name TEXT,
    n_models     INTEGER,
    ratio        TEXT,
    field        TEXT,
    values_json  TEXT,
    segment      TEXT,
    category     TEXT,
    min_share    REAL,
    note         TEXT,
    PRIMARY KEY (announce_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_ac_type
    ON announce_claims(claim_type, machine_name);
"""


def announce_files():
    for path in sorted(glob.glob(os.path.join(ANNOUNCE_DIR, "*.json"))):
        name = os.path.basename(path)
        if any(marker in name for marker in EXCLUDED_MARKERS):
            continue
        yield path


def ingest_announce(analysis_db=ANALYSIS_DB):
    """`backtest/announce/*.json` を検索可能なテーブルに写す。ファイルが正本。"""
    connection = sqlite3.connect(analysis_db)
    connection.executescript(SCHEMA)
    now = datetime.now().astimezone().isoformat(timespec="seconds")

    reports = claims = skipped = 0
    for path in announce_files():
        try:
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except OSError, json.JSONDecodeError:
            skipped += 1
            continue
        hall = payload.get("hall")
        target = payload.get("target_date")
        if not hall or not target:
            skipped += 1
            continue
        announce_id = payload.get("announce_id") or os.path.splitext(os.path.basename(path))[0]
        source = payload.get("source") or {}
        zentaikei = payload.get("zentaikei") or {}

        connection.execute(
            "INSERT OR REPLACE INTO announce_reports "
            "(announce_id, hall_name, target_date, account, posted_at, kind, metric, "
            " threshold, min_machines, file_path, announce_digest, payload_json, "
            " ingested_at, retroactive) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
            (
                announce_id,
                hall,
                str(target),
                source.get("account"),
                source.get("posted_at"),
                source.get("kind"),
                zentaikei.get("metric"),
                zentaikei.get("threshold"),
                zentaikei.get("min_machines"),
                path,
                payload.get("announce_digest"),
                json.dumps(payload, ensure_ascii=False),
                now,
            ),
        )
        connection.execute("DELETE FROM announce_claims WHERE announce_id = ?", (announce_id,))
        for seq, claim in enumerate(payload.get("claims") or []):
            values = claim.get("values")
            connection.execute(
                "INSERT INTO announce_claims VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    announce_id,
                    seq,
                    claim.get("type") or "?",
                    claim.get("machine_name"),
                    claim.get("n_models"),
                    claim.get("ratio"),
                    claim.get("field"),
                    json.dumps(values, ensure_ascii=False) if values is not None else None,
                    claim.get("segment"),
                    claim.get("category"),
                    claim.get("min_share"),
                    claim.get("note"),
                ),
            )
            claims += 1
        reports += 1

    connection.commit()
    print("予告: %d 件 / claim %d 件 (読めずに飛ばした %d 件)" % (reports, claims, skipped))
    return reports


# 遡及で予告を拾えるアカウントとホールの対応。`速報`（結果報告）は予告ではない。
RETRO_SOURCES = (
    ("楽園蒲田店", "kawasakislot", ("楽園蒲田",)),
    ("マルハンメガシティ2000-蒲田7", "999999Q9Q", ("メガなな", "メガ7", "蒲田7", "蒲田七")),
    ("マルハンメガシティ2000-蒲田1", "999999Q9Q", ("メガいち", "メガ1", "蒲田1", "蒲田一")),
)
RESULT_MARKER = "速報"
# 登録済み29件はすべて 18:23〜23:26 の投稿で、対象日は投稿日の翌日だった（29/29、例外なし）。
# 正午より前の投稿は事例が無いので、対象日を決められないものとして取り込まない。
RETRO_MIN_HOUR = 12


def ingest_retroactive_announces(state_db=None, analysis_db=ANALYSIS_DB):
    """過去の予告投稿を、事前登録とは別レーンで取り込む。

    なぜ分けるか
    ------------
    `backtest/announce/*.json` は**事前登録の証拠**である。`LEDGER.jsonl` が
    登録時刻と digest を保持し、`late_registration` が真のものは的中率・
    ベースレートの集計から外す運用になっている。ここに過去分を流し込むと、
    その仕組みが意味を失う。

    一方で、**予告文とその投稿時刻は第三者による外部タイムスタンプ付きの事実**であり、
    後から読んでも「対象日より前に何が主張されていたか」は変わらない。
    統合フレームの「その日その機種が名指しされていたか」というフラグには使える。

    したがって:

    - 事前登録（`retroactive=0`）… 的中率の測定に使ってよい
    - 遡及（`retroactive=1`）… 名指しの有無を引くだけ。**的中率の分子分母に入れない**

    バイアスの入り口は予告文ではなく **claim の抽出**（どの主張を採点対象にするか、
    閾値をいくつにするか）である。そこは人の判断が入るので、遡及分では一切行わない。
    機種名は `announce.match_machine_names` の完全部分一致だけで機械的に拾い、
    `model_named_mechanical` として記録する。閾値も claim の取捨選択もしない。

    ⚠️ 遡及分から見つけた関係は**仮説にしかならない**。運用に載せる前に、
    以後の事前登録で前向きに検証すること。
    """
    import sqlite3 as _sqlite3

    from backtest.run_backtest import load_frame

    state_db = state_db or os.path.join(ROOT, "scraper", "twitter_monitor", "state.db")
    source = _sqlite3.connect("file:%s?mode=ro" % state_db, uri=True)
    target = sqlite3.connect(analysis_db)
    target.executescript(SCHEMA)
    existing = {row[1] for row in target.execute("PRAGMA table_info(announce_reports)")}
    if "retroactive" not in existing:
        target.execute("ALTER TABLE announce_reports ADD COLUMN retroactive INTEGER DEFAULT 0")
    target.execute("UPDATE announce_reports SET retroactive = 0 WHERE retroactive IS NULL")
    now = datetime.now().astimezone().isoformat(timespec="seconds")

    added = named = skipped_result = skipped_hour = 0
    for hall, account, keywords in RETRO_SOURCES:
        names = sorted(load_frame(hall)["machine_name"].dropna().unique().tolist())
        rows = source.execute(
            "SELECT tweet_id, tweet_url, posted_at_jst, COALESCE(full_text, tweet_text, '') "
            "FROM seen_tweets WHERE handle = ?",
            (account,),
        ).fetchall()
        for tweet_id, url, posted, text in rows:
            if not any(keyword in text for keyword in keywords):
                continue
            if RESULT_MARKER in text:
                skipped_result += 1
                continue
            if not posted:
                skipped_hour += 1
                continue
            stamp = datetime.fromisoformat(posted)
            if stamp.hour < RETRO_MIN_HOUR:
                skipped_hour += 1
                continue
            target_date = (stamp.date() + timedelta(days=1)).strftime("%Y%m%d")
            announce_id = "retro__%s__%s" % (tweet_id, hall)

            target.execute(
                "INSERT OR REPLACE INTO announce_reports "
                "(announce_id, hall_name, target_date, account, posted_at, kind, "
                " metric, threshold, min_machines, file_path, announce_digest, "
                " payload_json, ingested_at, retroactive) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
                (
                    announce_id,
                    hall,
                    target_date,
                    account,
                    posted,
                    "予告(遡及)",
                    None,
                    None,
                    None,
                    "(tweet %s)" % tweet_id,
                    None,
                    json.dumps({"text": text}, ensure_ascii=False),
                    now,
                ),
            )
            target.execute("DELETE FROM announce_claims WHERE announce_id = ?", (announce_id,))
            # 完全部分一致のみ。あいまい照合は取りこぼしより誤検出のほうが害が大きい。
            hits = [name for name in names if name and name in text]
            for seq, name in enumerate(hits):
                target.execute(
                    "INSERT INTO announce_claims (announce_id, seq, claim_type, machine_name, note) VALUES (?,?,?,?,?)",
                    (
                        announce_id,
                        seq,
                        "model_named_mechanical",
                        name,
                        "本文の完全部分一致で機械的に抽出。人の取捨選択を経ていない",
                    ),
                )
                named += 1
            added += 1

    target.commit()
    print("遡及の予告: %d 件 / 機械抽出の名指し %d 件" % (added, named))
    print("  速報なので対象外: %d / 投稿時刻から対象日を決められない: %d" % (skipped_result, skipped_hour))
    for hall, count, days in target.execute(
        "SELECT hall_name, COUNT(*), COUNT(DISTINCT target_date) FROM announce_reports "
        "WHERE retroactive = 1 GROUP BY 1 ORDER BY 2 DESC"
    ):
        print("  %-28s %3d 件 / %3d 日" % (hall, count, days))
    return added


def tracked_halls():
    return sorted(
        os.path.splitext(os.path.basename(p))[0]
        for p in glob.glob(os.path.join(HALL_DIR, "*.db"))
        if os.path.basename(p) not in ("analysis_results.db", "poco_analysis.db")
    )


def _hall_days(hall):
    path = os.path.join(HALL_DIR, hall + ".db")
    if not os.path.exists(path):
        return set()
    connection = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    try:
        return {row[0] for row in connection.execute("SELECT DISTINCT date FROM machine_detailed_results")}
    except sqlite3.Error:
        return set()
    finally:
        connection.close()


def coverage(analysis_db=ANALYSIS_DB, halls=None):
    """ホール別に、3系統がどれだけ重なっているかを出す。

    統合分析ができるのは3つが揃うホール日だけなので、まずここを見る。
    """
    connection = sqlite3.connect("file:%s?mode=ro" % analysis_db, uri=True)
    announce = {}
    retro = {}
    for hall, date, is_retro in connection.execute(
        "SELECT hall_name, target_date, COALESCE(retroactive, 0) FROM announce_reports"
    ):
        (retro if is_retro else announce).setdefault(hall, set()).add(date)
    reported = {}
    for hall, date in connection.execute(
        "SELECT hall_name, business_date FROM external_result_reports "
        "WHERE is_tracked_hall = 1 AND business_date IS NOT NULL"
    ):
        reported.setdefault(hall, set()).add(date)
    labelled = {}
    for hall, date in connection.execute("SELECT DISTINCT hall_name, business_date FROM external_result_machines"):
        labelled.setdefault(hall, set()).add(date)

    print("%-28s%8s%8s%8s%8s%10s%12s" % ("ホール", "実績", "予告", "遡及", "結果", "台ラベル", "3系統(事前/遡及)"))
    rows = []
    for hall in halls or tracked_halls():
        days = _hall_days(hall)
        if not days:
            continue
        a = announce.get(hall, set())
        q = retro.get(hall, set())
        r = reported.get(hall, set())
        m = labelled.get(hall, set())
        triple = days & a & r
        triple_retro = days & (a | q) & r
        rows.append((hall, len(days), len(a), len(q), len(r), len(m), len(triple), len(triple_retro)))
        print(
            "%-28s%8d%8d%8d%8d%8d%10d /%3d"
            % (hall, len(days), len(a), len(q), len(r), len(m), len(triple), len(triple_retro))
        )
    return rows


def machine_frame(hall, start=None, end=None, analysis_db=ANALYSIS_DB):
    """台×日の統合フレームを返す。

    実績・位置・機種属性（`run_backtest.load_frame` と同じ）に、次の列を足す。

    `reported_target`  結果発表の表に載った台か（0/1）。⚠️ 「勝った台」ではない。
                       "+1/7台" の機種でも画像は7台すべてを載せるので、
                       **仕掛けグループに属する台** を意味する
    `reported_group`   その台が載っていた報告の機種名（ラベル元）
    `announced_model`  **事前登録済みの**予告がその機種を名指ししていたか（0/1）
    `announced_model_retro`
                       遡及取り込みの予告が名指ししていたか（0/1）。機械抽出なので
                       探索には使えるが、**的中率の分子分母に入れてはいけない**
    `n_machines`       その日のその機種の設置台数（メイン機種かの判断に使う）
    `model_delta`      前営業日からの増減。**リネームは 0 として扱う**
    `days_since_increase`
                       直近の増台からの経過日数。予告の「直近増台」を裏取りできる
    `announce_id`      その日の予告ID（無ければ None）
    `zentaikei_n`      予告の「全台系N機種」の N（無ければ None）
    """
    import pandas as pd
    from backtest.run_backtest import load_frame

    frame = load_frame(hall)
    frame["date"] = frame["date"].astype(str)
    if start:
        frame = frame[frame["date"] >= str(start)]
    if end:
        frame = frame[frame["date"] <= str(end)]

    connection = sqlite3.connect("file:%s?mode=ro" % analysis_db, uri=True)

    # 3系統は互いに独立に増える。片方をまだ取り込んでいないだけで落ちてはいけない。
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    labels = {}
    if "external_result_machines" in tables:
        for date, number, group in connection.execute(
            "SELECT m.business_date, m.machine_number, m.actual_name "
            "FROM external_result_machines m WHERE m.hall_name = ?",
            (hall,),
        ):
            labels[(date, number)] = group
    keys = list(zip(frame["date"], frame["machine_number"]))
    frame["reported_target"] = [int(k in labels) for k in keys]
    frame["reported_group"] = [labels.get(k) for k in keys]

    # 事前登録と遡及は絶対に混ぜない。前者だけが的中率の測定に使える。
    named = {0: {}, 1: {}}
    zentaikei = {}
    announce_id = {}
    rows = (
        []
        if "announce_reports" not in tables
        else connection.execute(
            "SELECT COALESCE(r.retroactive, 0), r.announce_id, r.target_date, "
            "       c.claim_type, c.machine_name, c.n_models "
            "FROM announce_reports r LEFT JOIN announce_claims c ON c.announce_id = r.announce_id "
            "WHERE r.hall_name = ?",
            (hall,),
        ).fetchall()
    )
    for retro, aid, date, ctype, machine_name, n_models in rows:
        if not retro:
            announce_id[date] = aid
            if ctype == "zentaikei_count" and n_models is not None:
                zentaikei[date] = n_models
        if machine_name and ctype in ("model_named", "model_named_mechanical"):
            named[retro].setdefault(date, set()).add(machine_name)

    # 設置台数と増台。予告が「直近増台：Lカバネリ」を根拠に挙げてくるので、
    # こちらから独立に確認できるようにする（backtest/model_inventory.py）。
    counts = {}
    increases = {}
    if "model_inventory" in tables:
        for date, name, n_machines, delta, kind in connection.execute(
            "SELECT date, machine_name, n_machines, delta, change_kind FROM model_inventory WHERE hall_name = ?",
            (hall,),
        ):
            counts[(date, name)] = (n_machines, delta)
            # rename は見かけの増台なので直近増台に数えない
            if kind == "increase" or (kind == "new" and delta and delta > 0):
                increases.setdefault(name, []).append(date)
    frame["n_machines"] = [counts.get(k, (None, None))[0] for k in zip(frame["date"], frame["machine_name"])]
    frame["model_delta"] = [counts.get(k, (None, None))[1] for k in zip(frame["date"], frame["machine_name"])]

    def _since(date, name):
        past = [d for d in increases.get(name, ()) if d <= date]
        if not past:
            return None
        return (datetime.strptime(date, "%Y%m%d") - datetime.strptime(max(past), "%Y%m%d")).days

    frame["days_since_increase"] = [_since(d, n) for d, n in zip(frame["date"], frame["machine_name"])]

    frame["announce_id"] = [announce_id.get(d) for d in frame["date"]]
    frame["zentaikei_n"] = [zentaikei.get(d) for d in frame["date"]]
    for retro, column in ((0, "announced_model"), (1, "announced_model_retro")):
        lookup = named[retro]
        frame[column] = [int(name in lookup.get(date, ())) for date, name in zip(frame["date"], frame["machine_name"])]
    return frame


def hall_day(hall, date, analysis_db=ANALYSIS_DB):
    """1ホール日について、予告・結果発表・実績を並べて表示する。"""
    connection = sqlite3.connect("file:%s?mode=ro" % analysis_db, uri=True)
    print("=" * 66)
    print("%s  %s" % (hall, date))
    print("=" * 66)

    rows = connection.execute(
        "SELECT announce_id, account, posted_at FROM announce_reports WHERE hall_name = ? AND target_date = ?",
        (hall, date),
    ).fetchall()
    if not rows:
        print("\n■ 予告: なし")
    for announce_id, account, posted_at in rows:
        print("\n■ 予告 %s (%s, %s)" % (announce_id, account, posted_at))
        for ctype, name, n_models, ratio, note in connection.execute(
            "SELECT claim_type, machine_name, n_models, ratio, note FROM announce_claims "
            "WHERE announce_id = ? ORDER BY seq",
            (announce_id,),
        ):
            detail = name or ("%s機種" % n_models if n_models else "") or ratio or ""
            print("   [%s] %s  %s" % (ctype, detail, (note or "")[:60]))

    rows = connection.execute(
        "SELECT report_id, target_machines, total_machines, target_mean_diff, event_name "
        "FROM external_result_reports WHERE hall_name = ? AND business_date = ?",
        (hall, date),
    ).fetchall()
    if not rows:
        print("\n■ 結果発表: なし")
    for report_id, target, total, mean_diff, event in rows:
        print("\n■ 結果発表 %s  %s/%s台  対象平均%s枚  %s" % (report_id, target, total, mean_diff, event or ""))
        for granularity, name, n_target, n_total, group_mean in connection.execute(
            "SELECT granularity, model_name, n_target, n_total, mean_diff "
            "FROM external_result_models WHERE report_id = ? ORDER BY seq",
            (report_id,),
        ):
            counts = "%s/%s" % (n_target, n_total) if n_total else ""
            print("   【%s】%-24s %6s  平均%s枚" % (granularity, name[:24], counts, group_mean))
        labelled = connection.execute(
            "SELECT COUNT(*) FROM external_result_machines WHERE report_id = ?", (report_id,)
        ).fetchone()[0]
        print("   台単位ラベル: %d 台" % labelled)

    frame = machine_frame(hall, start=date, end=date, analysis_db=analysis_db)
    if frame.empty:
        print("\n■ 実績: なし")
        return
    reported = frame[frame["reported_target"] == 1]
    print(
        "\n■ 実績  設置%d台  平均差枚%+.0f  平均G数%.0f"
        % (len(frame), frame["diff_coins_normalized"].mean(), frame["games_normalized"].mean())
    )
    if len(reported):
        print(
            "   該当台 %d台  平均差枚%+.0f  勝率%.0f%%"
            % (
                len(reported),
                reported["diff_coins_normalized"].mean(),
                100 * (reported["diff_coins_normalized"] > 0).mean(),
            )
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ingest-announce", help="announce/*.json をテーブルへ写す")
    sub.add_parser("ingest-retro", help="過去の予告投稿を遡及レーンで取り込む")
    cov = sub.add_parser("coverage", help="3系統の重なりを出す")
    cov.add_argument("--hall", action="append")
    day = sub.add_parser("day", help="1ホール日を並べて表示する")
    day.add_argument("hall")
    day.add_argument("date")
    args = parser.parse_args()

    if args.command == "ingest-announce":
        ingest_announce()
    elif args.command == "ingest-retro":
        ingest_retroactive_announces()
    elif args.command == "coverage":
        coverage(halls=args.hall)
    else:
        hall_day(args.hall, args.date)


if __name__ == "__main__":
    main()
