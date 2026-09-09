"""日次・月次で追う分析結果の保管庫。

なぜ要るか:
    角番のピーク、並びの箇所数、予告の採点といった結果が、これまで
    scratchpad の使い捨てスクリプトの標準出力にしか残っていなかった。
    「9月の蒲田7ノーマルの角番ピークを日次で」と聞かれるたびに全部
    計算し直すことになり、しかも計算し直した値が前回と同じ定義とは限らない。

定義のバージョンを値と一緒に持つ:
    2026-09-08 の一日だけでも、並びの閾値を +1800 で凍結し、角番の最小台数を
    8 から 25 に変え、並べ替え検定の入替単位を機種内へ直した。同じ metric 名の
    列に違う定義の値が混ざると、後から見分けられない。よって全ての値が
    definition_id を持ち、定義そのものを definitions テーブルに凍結する。
    定義を変えたら新しい version を切る。既存行は書き換えない。

再計算できるものと、できないものを分ける:
    metric_values は raw データから作り直せる（定義を変えれば作り直すべき）。
    observed_facts は作り直せない。速報が公表した角番、予告が主張した内容は
    ツイートが消えたら二度と手に入らない。こちらが本体で、metric_values は
    それと突き合わせるための派生物である。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STORE_PATH = PROJECT_ROOT / "db" / "analysis_results.db"
JST = ZoneInfo("Asia/Tokyo")

SCHEMA = """
CREATE TABLE IF NOT EXISTS definitions (
    definition_id TEXT PRIMARY KEY,   -- metric + version + params のハッシュ
    metric        TEXT NOT NULL,
    version       TEXT NOT NULL,
    params_json   TEXT NOT NULL,
    description   TEXT,
    frozen_at     TEXT NOT NULL,
    UNIQUE(metric, version)
);

-- 再計算できる派生値。定義を変えたら新しい definition_id で入れ直す。
CREATE TABLE IF NOT EXISTS metric_values (
    hall          TEXT NOT NULL,
    business_date TEXT NOT NULL,      -- YYYYMMDD
    definition_id TEXT NOT NULL REFERENCES definitions(definition_id),
    segment       TEXT NOT NULL DEFAULT '',   -- AT等 / ノーマル / 2F全体 など
    item          TEXT NOT NULL DEFAULT '',   -- 角番、機種名、ブロック起点など
    value_num     REAL,
    value_text    TEXT,
    n             INTEGER,            -- その値の母数。無いと比較できない
    computed_at   TEXT NOT NULL,
    PRIMARY KEY (hall, business_date, definition_id, segment, item)
);

-- 再計算できない観測。ツイートが消えたら復元不能なので、これが本体。
CREATE TABLE IF NOT EXISTS observed_facts (
    hall          TEXT NOT NULL,
    business_date TEXT NOT NULL,
    kind          TEXT NOT NULL,      -- announced_kakuban / announce_claim / result_report
    source        TEXT NOT NULL,      -- アカウント名など
    source_url    TEXT,
    posted_at     TEXT,
    payload_json  TEXT NOT NULL,
    recorded_at   TEXT NOT NULL,
    PRIMARY KEY (hall, business_date, kind, source, source_url)
);

CREATE INDEX IF NOT EXISTS idx_metric_date ON metric_values(business_date);
CREATE INDEX IF NOT EXISTS idx_metric_hall_metric ON metric_values(hall, definition_id);
CREATE INDEX IF NOT EXISTS idx_facts_date ON observed_facts(business_date);
"""


def connect(path: Path = STORE_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA)
    return connection


def now() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")


def register_definition(connection, metric: str, version: str, params: dict, description: str = "") -> str:
    """定義を凍結して definition_id を返す。同じ (metric, version) の再登録で
    params が違えば拒否する。値を入れ直したいなら version を上げること。"""
    payload = json.dumps(params, ensure_ascii=False, sort_keys=True)
    definition_id = hashlib.sha1(("%s|%s|%s" % (metric, version, payload)).encode()).hexdigest()[:16]
    existing = connection.execute(
        "SELECT definition_id, params_json FROM definitions WHERE metric=? AND version=?", (metric, version)
    ).fetchone()
    if existing:
        if existing[1] != payload:
            raise ValueError(
                "定義 %s %s は既に別の params で凍結されている。version を上げること。\n"
                "  既存: %s\n  今回: %s" % (metric, version, existing[1], payload)
            )
        return existing[0]
    connection.execute(
        "INSERT INTO definitions VALUES (?,?,?,?,?,?)", (definition_id, metric, version, payload, description, now())
    )
    connection.commit()
    return definition_id


def put_values(connection, hall: str, business_date: str, definition_id: str, rows: list[dict]) -> int:
    """rows: [{segment, item, value_num, value_text, n}]"""
    stamp = now()
    connection.executemany(
        "INSERT OR REPLACE INTO metric_values VALUES (?,?,?,?,?,?,?,?,?)",
        [
            (
                hall,
                business_date,
                definition_id,
                r.get("segment", ""),
                r.get("item", ""),
                r.get("value_num"),
                r.get("value_text"),
                r.get("n"),
                stamp,
            )
            for r in rows
        ],
    )
    connection.commit()
    return len(rows)


def put_fact(
    connection,
    hall: str,
    business_date: str,
    kind: str,
    source: str,
    payload: dict,
    source_url: str = "",
    posted_at: str = "",
) -> None:
    connection.execute(
        "INSERT OR REPLACE INTO observed_facts VALUES (?,?,?,?,?,?,?,?)",
        (hall, business_date, kind, source, source_url, posted_at, json.dumps(payload, ensure_ascii=False), now()),
    )
    connection.commit()


def daily(connection, metric: str, hall: str = "", since: str = "", segment: str = "") -> list[tuple]:
    """metric の日次推移。定義が複数あれば definition_id ごとに分けて返す
    （混ぜると別定義の値が同じ系列に並ぶため）。"""
    sql = [
        "SELECT v.business_date, v.hall, d.version, v.segment, v.item, v.value_num, v.n",
        "FROM metric_values v JOIN definitions d ON d.definition_id = v.definition_id",
        "WHERE d.metric = ?",
    ]
    params = [metric]
    if hall:
        sql.append("AND v.hall = ?")
        params.append(hall)
    if since:
        sql.append("AND v.business_date >= ?")
        params.append(since)
    if segment:
        sql.append("AND v.segment = ?")
        params.append(segment)
    sql.append("ORDER BY v.business_date, v.hall, v.segment")
    return connection.execute(" ".join(sql), params).fetchall()


def monthly(connection, metric: str, hall: str = "", segment: str = "") -> list[tuple]:
    """月次の集約。件数を必ず返す（n を見ずに平均だけ見ると少数月に振り回される）。"""
    sql = [
        "SELECT substr(v.business_date,1,6) AS ym, v.hall, d.version, v.segment,",
        "COUNT(*) AS days, ROUND(AVG(v.value_num),1), MIN(v.value_num), MAX(v.value_num)",
        "FROM metric_values v JOIN definitions d ON d.definition_id = v.definition_id",
        "WHERE d.metric = ? AND v.value_num IS NOT NULL",
    ]
    params = [metric]
    if hall:
        sql.append("AND v.hall = ?")
        params.append(hall)
    if segment:
        sql.append("AND v.segment = ?")
        params.append(segment)
    sql.append("GROUP BY ym, v.hall, d.version, v.segment ORDER BY ym, v.hall, v.segment")
    return connection.execute(" ".join(sql), params).fetchall()
