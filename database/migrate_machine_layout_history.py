"""machine_layout に日付次元を与える（machine_layout_history の構築）。

解決する問題:
    `machine_layout` は machine_number を主キーとする単一スナップショットで、
    日付次元を持たない。したがって **構造上、常にただ1つの時代についてしか
    正しくありえない**。楽園蒲田の 2026-07-06 の改装で section 定義が
    書き換わった（2223-2240 → 2225-2242 等）結果、工事後の位置が工事前の
    データに遡って適用され、技術介入の端番効果が +1.127pp → +0.211pp と
    「消えた」ように見える事故が起きた。効果の消滅ではなく測定対象の破壊である。
    詳細: backtest/results/regime/FINDINGS.md 追試10。

なぜ machine_layout を作り替えないか:
    このテーブルを参照するコードが約60ファイルあり、いずれも
    `ON r.machine_number = l.machine_number` の単純結合をしている。
    日付次元を足すと1台に複数行が対応し、**全て静かに二重計上になる**。
    そこで `machine_layout` は現行エポックのスナップショットとして温存し、
    日付次元を持つ `machine_layout_history` を正本として別に置く。
    移行は参照側を1つずつ切り替えて進める。

エポックの表現:
    valid_from（含む）〜 valid_to（含む）。valid_to が NULL なら現在まで有効。
    同一 machine_number でエポックが重なってはいけない（重なると結合で行が増える）。
    `verify` サブコマンドがこれを検査する。

使い方:
    # 全ホールに単一エポック（現行 machine_layout の内容）で初期化
    venv\\Scripts\\python.exe -m database.migrate_machine_layout_history bootstrap

    # 楽園だけ2エポックに置き換える
    venv\\Scripts\\python.exe -m database.migrate_machine_layout_history insert-era \\
        --hall 楽園蒲田店 --csv-dir <工事前CSVのディレクトリ> \\
        --valid-from 20250101 --valid-to 20260705 --replace
    venv\\Scripts\\python.exe -m database.migrate_machine_layout_history insert-era \\
        --hall 楽園蒲田店 --csv-dir Heatmap --valid-from 20260706

    venv\\Scripts\\python.exe -m database.migrate_machine_layout_history verify
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_DIR = PROJECT_ROOT / "db"

# 位置列。machine_layout と同じ並びで揃える。
POS_COLUMNS = [
    "x",
    "y",
    "display_y",
    "section",
    "section_min",
    "section_max",
    "rank_from_min",
    "rank_from_max",
    "rank_from_aisle",
]

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS machine_layout_history (
    machine_number  INTEGER NOT NULL,
    hall_name       TEXT,
    valid_from      TEXT NOT NULL,
    valid_to        TEXT,
    x               INTEGER,
    y               INTEGER,
    display_y       INTEGER,
    section         TEXT,
    section_min     INTEGER,
    section_max     INTEGER,
    rank_from_min   INTEGER,
    rank_from_max   INTEGER,
    rank_from_aisle INTEGER,
    PRIMARY KEY (machine_number, valid_from)
)
"""


def hall_dbs() -> list[Path]:
    """ホール DB だけを返す。空ファイルや作業用 DB を除く。"""
    out = []
    for p in sorted(DB_DIR.glob("*.db")):
        if p.stat().st_size == 0:
            continue
        with sqlite3.connect(f"file:{p}?mode=ro", uri=True) as con:
            names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if {"machine_detailed_results", "machine_layout"} <= names:
            out.append(p)
    return out


def _to_int(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except TypeError, ValueError:
        return None


def bootstrap(con: sqlite3.Connection, hall_name: str) -> int:
    """現行 machine_layout を「データ開始日から現在まで」の単一エポックとして入れる。

    改装が一度も無かった（と分かっている）ホールはこれで正しい。楽園のように
    複数エポックがあるホールは、この後 insert-era で置き換える。
    """
    con.execute(CREATE_SQL)
    first = con.execute("SELECT MIN(date) FROM machine_detailed_results").fetchone()[0]
    if first is None:
        return 0
    cols = ", ".join(POS_COLUMNS)
    rows = con.execute(f"SELECT machine_number, hall_name, {cols} FROM machine_layout").fetchall()
    con.executemany(
        f"""INSERT OR REPLACE INTO machine_layout_history
            (machine_number, hall_name, valid_from, valid_to, {cols})
            VALUES (?, ?, ?, NULL, {", ".join("?" * len(POS_COLUMNS))})""",
        [(r[0], r[1] if r[1] else hall_name, first, *r[2:]) for r in rows],
    )
    return len(rows)


def load_csv_records(csv_dir: Path, hall_name: str, pattern: str) -> list[tuple]:
    """座標CSVからエポック1件分の位置データを読む。

    rank_from_aisle は CSV に無いので NULL のままにする。rank_from_min から
    捏造すると存在しない通路角番シグナルを作ってしまう
    （migrate_import_rakuen_layout.py と同じ方針）。
    """
    records: list[tuple] = []
    for path in sorted(csv_dir.glob(pattern)):
        with path.open("r", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if row.get("hall_name") != hall_name:
                    continue
                mn = _to_int(row.get("machine_number"))
                if mn is None:
                    continue
                records.append(
                    (
                        mn,
                        hall_name,
                        _to_int(row.get("X")),
                        _to_int(row.get("Y")),
                        _to_int(row.get("display_y")),
                        row.get("section"),
                        _to_int(row.get("section_min")),
                        _to_int(row.get("section_max")),
                        _to_int(row.get("rank_from_min")),
                        _to_int(row.get("rank_from_max")),
                        None,  # rank_from_aisle
                    )
                )
    return records


def insert_era(
    db_path: Path, hall_name: str, csv_dir: Path, pattern: str, valid_from: str, valid_to: str | None, replace: bool
) -> int:
    records = load_csv_records(csv_dir, hall_name, pattern)
    if not records:
        raise SystemExit(f"{csv_dir} に {hall_name} の行が無い（pattern={pattern}）")
    with sqlite3.connect(str(db_path)) as con:
        con.execute(CREATE_SQL)
        if replace:
            con.execute("DELETE FROM machine_layout_history WHERE hall_name = ?", (hall_name,))
        cols = ", ".join(POS_COLUMNS)
        con.executemany(
            f"""INSERT OR REPLACE INTO machine_layout_history
                (machine_number, hall_name, valid_from, valid_to, {cols})
                VALUES (?, ?, ?, ?, {", ".join("?" * len(POS_COLUMNS))})""",
            [(r[0], r[1], valid_from, valid_to, *r[2:]) for r in records],
        )
        con.commit()
    return len(records)


def verify(db_path: Path) -> list[str]:
    """エポックの重なりと、データ行のカバレッジを検査する。

    重なりがあると結合で行が増え、全ての集計が静かに二重計上になる。
    ここで落とすのが目的。
    """
    problems: list[str] = []
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
        names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "machine_layout_history" not in names:
            return [f"{db_path.name}: machine_layout_history が無い"]

        overlaps = con.execute(
            """
            SELECT a.machine_number, a.valid_from, a.valid_to, b.valid_from, b.valid_to
            FROM machine_layout_history a
            JOIN machine_layout_history b
              ON a.machine_number = b.machine_number
             AND a.valid_from < b.valid_from
            WHERE a.valid_to IS NULL OR a.valid_to >= b.valid_from
            """
        ).fetchall()
        for mn, af, at, bf, bt in overlaps:
            problems.append(f"{db_path.name}: 台{mn} のエポックが重複 [{af}..{at or '∞'}] と [{bf}..{bt or '∞'}]")

        # カバレッジ: 位置が引けない台×日がどれだけあるか
        total, matched = con.execute(
            """
            SELECT COUNT(*),
                   SUM(CASE WHEN l.machine_number IS NULL THEN 0 ELSE 1 END)
            FROM machine_detailed_results r
            LEFT JOIN machine_layout_history l
                   ON r.machine_number = l.machine_number
                  AND r.date >= l.valid_from
                  AND (l.valid_to IS NULL OR r.date <= l.valid_to)
            """
        ).fetchone()
        rate = (matched or 0) / total * 100 if total else 0
        old = (
            con.execute(
                """
            SELECT SUM(CASE WHEN l.machine_number IS NULL THEN 0 ELSE 1 END)
            FROM machine_detailed_results r
            LEFT JOIN machine_layout l ON r.machine_number = l.machine_number
            """
            ).fetchone()[0]
            or 0
        )
        old_rate = old / total * 100 if total else 0
        print(
            f"{db_path.name}: 行 {total} / history 一致 {matched} ({rate:.1f}%) "
            f"/ 旧 machine_layout 一致 {old} ({old_rate:.1f}%)"
        )
    return problems


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="machine_layout の日付次元化")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("bootstrap", help="全ホールを単一エポックで初期化")

    ie = sub.add_parser("insert-era", help="CSV から1エポック分を投入")
    ie.add_argument("--hall", required=True)
    ie.add_argument("--csv-dir", required=True)
    ie.add_argument("--pattern", default="*_rakuen.csv")
    ie.add_argument("--valid-from", required=True)
    ie.add_argument("--valid-to", default=None)
    ie.add_argument("--replace", action="store_true", help="そのホールの既存エポックを全消ししてから入れる")

    sub.add_parser("verify", help="エポックの重なりとカバレッジを検査")

    args = ap.parse_args()

    if args.cmd == "bootstrap":
        for db in hall_dbs():
            with sqlite3.connect(str(db)) as con:
                n = bootstrap(con, db.stem)
                con.commit()
            print(f"{db.name}: {n} 台を単一エポックで初期化")
        return

    if args.cmd == "insert-era":
        db = DB_DIR / f"{args.hall}.db"
        if not db.exists():
            raise SystemExit(f"DB が無い: {db}")
        n = insert_era(db, args.hall, Path(args.csv_dir), args.pattern, args.valid_from, args.valid_to, args.replace)
        print(f"{db.name}: {n} 台を [{args.valid_from}..{args.valid_to or '∞'}] に投入")
        return

    problems: list[str] = []
    for db in hall_dbs():
        problems.extend(verify(db))
    if problems:
        print("\n--- 問題 ---")
        for p in problems[:50]:
            print(p)
        raise SystemExit(f"{len(problems)} 件の問題がある")
    print("\nエポックの重なりなし")


if __name__ == "__main__":
    main()
