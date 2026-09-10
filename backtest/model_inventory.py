# -*- coding: utf-8 -*-
"""機種ごとの設置台数の時系列と、その増減を出す。

なぜ要るか
----------
ホールが「扱いを良くしている機種」を判断する材料が、いまどこにも無い。
`machine_master` は jug/hana/oki/bt の4フラグだけで、設置台数も増減も持たない。
予告は「直近増台：Lカバネリ（おすすめ機種）」のように増台を根拠に挙げてくるが、
こちらから独立に確認する手段が無かった。

実績データから導出できる。2026-09-07 の楽園蒲田では
カバネリ 18→26台(+8)・リコリス新設22台・北斗転生2 20→9台(-11) が検出でき、
予告の「直近増台：Lカバネリ」と一致した。

⚠️ 機種名の表記変更を増減と誤検出しない
--------------------------------------
`20260908 LBタコスロ 3→0 / タコスロ 0→3` は同じ台の**リネーム**であって入替ではない。
台番号の集合が一致するかを見て判別する。台番号が一致する減少と増加の組は

- 名前が似ていれば **rename**（同一機種の表記ゆれ。増減として数えない）
- 名前が別物なら **replace**（撤去と設置。増減として数える）

⚠️ 実績DBには書かない
--------------------
`machine_layout` に日付次元を足して約60ファイルの結合が静かに二重計上になった事例が
ある（`database/CLAUDE.md`）。ここは `db/analysis_results.db` に別テーブルとして置く。
"""

import argparse
import os
import re
import sqlite3
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB_DIR = os.path.join(ROOT, "db")
ANALYSIS_DB = os.path.join(DB_DIR, "analysis_results.db")

# 表記ゆれの判定に使う。接頭辞と記号を落として比べる。
RE_PREFIX = re.compile(r"^(LB|L|S|スマスロ|パチスロ)\s*")
RE_SYMBOL = re.compile(r"[\s　・:：\-−ー！!／/（）\(\)。、！？]")

SCHEMA = """
CREATE TABLE IF NOT EXISTS model_inventory (
    hall_name     TEXT NOT NULL,
    date          TEXT NOT NULL,           -- YYYYMMDD
    machine_name  TEXT NOT NULL,
    n_machines    INTEGER NOT NULL,
    delta         INTEGER,                 -- 直前の営業日からの増減（初出は NULL）
    -- 台番号が一致する相手がいる場合の相方。rename なら増減として扱わない
    counterpart   TEXT,
    change_kind   TEXT,                    -- new / gone / increase / decrease / rename / replace
    PRIMARY KEY (hall_name, date, machine_name)
);

CREATE INDEX IF NOT EXISTS idx_mi_hall_name
    ON model_inventory(hall_name, machine_name, date);
"""


def normalize(name):
    return RE_SYMBOL.sub("", RE_PREFIX.sub("", str(name or ""))).lower()


def similar(left, right):
    """リネームとみなせるか。片方がもう片方を含めば同一機種の表記ゆれとみなす。"""
    a, b = normalize(left), normalize(right)
    if not a or not b:
        return False
    return a in b or b in a


def hall_names():
    names = []
    for filename in sorted(os.listdir(DB_DIR)):
        if not filename.endswith(".db"):
            continue
        try:
            with sqlite3.connect("file:%s?mode=ro" % os.path.join(DB_DIR, filename), uri=True) as connection:
                found = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='machine_detailed_results'"
                ).fetchone()
        except sqlite3.Error:
            continue
        if found:
            names.append(os.path.splitext(filename)[0])
    return names


def build(hall, analysis_db=ANALYSIS_DB):
    """1ホール分の設置台数の時系列を作る。"""
    source = sqlite3.connect("file:%s?mode=ro" % os.path.join(DB_DIR, hall + ".db"), uri=True)
    rows = source.execute(
        "SELECT date, machine_name, machine_number FROM machine_detailed_results "
        "WHERE machine_name IS NOT NULL ORDER BY date"
    ).fetchall()
    source.close()
    if not rows:
        return 0

    by_date = {}
    for date, name, number in rows:
        by_date.setdefault(date, {}).setdefault(name, set()).add(number)

    target = sqlite3.connect(analysis_db)
    target.executescript(SCHEMA)
    target.execute("DELETE FROM model_inventory WHERE hall_name = ?", (hall,))

    dates = sorted(by_date)
    written = 0
    for index, date in enumerate(dates):
        today = by_date[date]
        previous = by_date[dates[index - 1]] if index else None
        # 台番号が一致する「消えた機種」と「現れた機種」を突き合わせる
        counterpart = {}
        kinds = {}
        if previous is not None:
            gone = {n: s for n, s in previous.items() if n not in today}
            fresh = {n: s for n, s in today.items() if n not in previous}
            for new_name, new_numbers in fresh.items():
                best, overlap = None, 0
                for old_name, old_numbers in gone.items():
                    shared = len(new_numbers & old_numbers)
                    if shared > overlap:
                        best, overlap = old_name, shared
                if best and overlap >= max(1, len(new_numbers) // 2):
                    kind = "rename" if similar(best, new_name) else "replace"
                    counterpart[new_name] = best
                    kinds[new_name] = kind
                    counterpart[best] = new_name
                    kinds[best] = kind

        for name, numbers in today.items():
            count = len(numbers)
            delta = None
            kind = kinds.get(name)
            if previous is not None:
                before = len(previous.get(name, ()))
                delta = count - before
                if kind is None:
                    if before == 0:
                        kind = "new"
                    elif delta > 0:
                        kind = "increase"
                    elif delta < 0:
                        kind = "decrease"
            target.execute(
                "INSERT OR REPLACE INTO model_inventory VALUES (?,?,?,?,?,?,?)",
                (hall, date, name, count, delta, counterpart.get(name), kind),
            )
            written += 1
        # 消えた機種も記録する。翌日「無い」ことが分からないと減台を追えない
        if previous is not None:
            for name in previous:
                if name in today:
                    continue
                target.execute(
                    "INSERT OR REPLACE INTO model_inventory VALUES (?,?,?,?,?,?,?)",
                    (hall, date, name, 0, -len(previous[name]), counterpart.get(name), kinds.get(name) or "gone"),
                )
                written += 1

    target.commit()
    target.close()
    return written


def recent(hall, days=30, analysis_db=ANALYSIS_DB):
    """直近の増減を出す。リネームは除く。"""
    connection = sqlite3.connect("file:%s?mode=ro" % analysis_db, uri=True)
    dates = [
        row[0]
        for row in connection.execute(
            "SELECT DISTINCT date FROM model_inventory WHERE hall_name = ? ORDER BY date DESC LIMIT ?", (hall, days)
        )
    ]
    if not dates:
        print("%s: データが無い。先に build すること。" % hall)
        return
    since = min(dates)
    print("\n■ %s  %s〜 の増減（リネームを除く）" % (hall, since))
    print("%-10s%-30s%6s%6s%7s  %s" % ("日付", "機種", "前", "後", "増減", "種別"))
    found = False
    for date, name, count, delta, kind, mate in connection.execute(
        "SELECT date, machine_name, n_machines, delta, change_kind, counterpart "
        "FROM model_inventory WHERE hall_name = ? AND date >= ? "
        "  AND change_kind IS NOT NULL AND change_kind <> 'rename' AND ABS(delta) >= 2 "
        "ORDER BY date, delta DESC",
        (hall, since),
    ):
        found = True
        note = kind if not mate else "%s(%s)" % (kind, str(mate)[:16])
        print("%-10s%-30s%6d%6d%+7d  %s" % (date, str(name)[:30], count - delta, count, delta, note))
    if not found:
        print("   （±2台以上の増減なし）")

    print("\n■ 現在の設置台数 上位12（メイン機種の候補）")
    latest = max(dates)
    for name, count in connection.execute(
        "SELECT machine_name, n_machines FROM model_inventory "
        "WHERE hall_name = ? AND date = ? AND n_machines > 0 "
        "ORDER BY n_machines DESC LIMIT 12",
        (hall, latest),
    ):
        print("   %-34s%4d台" % (str(name)[:34], count))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    builder = sub.add_parser("build", help="全ホールの設置台数の時系列を作る")
    builder.add_argument("--hall", action="append")
    viewer = sub.add_parser("recent", help="直近の増減を見る")
    viewer.add_argument("hall")
    viewer.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    if args.command == "build":
        total = 0
        for hall in args.hall or hall_names():
            written = build(hall)
            total += written
            print("  %-28s %6d 行" % (hall, written))
        print("合計 %d 行" % total)
    else:
        recent(args.hall, args.days)


if __name__ == "__main__":
    main()
