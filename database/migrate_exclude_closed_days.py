#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""休業日に取り込まれた壊れたページを DB から外す（2026-10-16 のデータ監査 backfill で発見）。

対象:
  楽園蒲田店 20250421（入替）・20260706（改装）。全台が G数0・BB/RB0・差枚 -6,142 で入っており、
  1日あたり約 -350万枚の偽の差枚がホール集計・機種集計に混ざっていた。
  詳細は document/reviews/2026-10-16-data-audit-backfill.md。

やること（日付ごと）:
  1. DB を <db>.bak-pre-closed-day-<今日> にコピー（初回だけ）
  2. date 列を持つ全テーブルからその日の行を削除
  3. 移動平均（avg_*_7d〜35d。暦日で最大36日窓）を後続37日分だけ再計算
  4. 月次トレンド（monthly_trend_*）をその月について再計算
  5. 元 JSON を data/<ホール>/_excluded/ に移す。置いたままだと翌朝の
     incremental_db_updater が「DB に無い日」として同じゴミを再投入する（glob は直下のみ）
  6. document/registry/KNOWN_CLOSED_DAYS.csv に載っているか確かめる（監査の continuity を INFO に落とす）。
     data/failed_dates_report確認済み.csv は人のメモ（CSV行と自由記述の混在）なので書き込まない。

冪等: 既に行が無い・JSON が移動済みなら何もしない。

使い方:
  venv\\Scripts\\python.exe -m database.migrate_exclude_closed_days --dry-run
  venv\\Scripts\\python.exe -m database.migrate_exclude_closed_days
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "database"))  # rank_calculator は table_config を相対名で import する

CLOSED_DAYS = [
    ("楽園蒲田店", "20250421", "休業日(入替)のページ: 全台G数0・差枚-6142"),
    ("楽園蒲田店", "20260706", "休業日(改装)のページ: 全台G数0・差枚-6142"),
]
HISTORY_DAYS_AFTER = 37
KNOWN_CLOSED_DAYS = PROJECT_ROOT / "document" / "registry" / "KNOWN_CLOSED_DAYS.csv"


def date_tables(conn: sqlite3.Connection) -> list[str]:
    out = []
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        if any(r[1] == "date" for r in conn.execute(f'PRAGMA table_info("{name}")')):
            out.append(name)
    return out


def exclude(db_dir: Path, data_dir: Path, hall: str, day: str, reason: str, dry_run: bool) -> None:
    from monthly_trend_calculator import MonthlyTrendCalculator
    from rank_calculator import RankCalculator

    db_path = db_dir / f"{hall}.db"
    conn = sqlite3.connect(db_path)
    counts = {
        t: conn.execute(f'SELECT COUNT(*) FROM "{t}" WHERE date = ?', (day,)).fetchone()[0] for t in date_tables(conn)
    }
    counts = {t: n for t, n in counts.items() if n}
    print(f"{hall} {day}: 削除対象 {sum(counts.values())}行 {counts}")
    if counts and not dry_run:
        backup = db_path.with_name(db_path.name + f".bak-pre-closed-day-{date.today():%Y%m%d}")
        if not backup.exists():
            conn.close()
            shutil.copy2(db_path, backup)
            print(f"  バックアップ: {backup.name}")
            conn = sqlite3.connect(db_path)
        for t in counts:
            conn.execute(f'DELETE FROM "{t}" WHERE date = ?', (day,))
        conn.commit()
        later = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT date FROM machine_detailed_results WHERE date > ? AND date <= ? ORDER BY date",
                (day, (datetime.strptime(day, "%Y%m%d") + timedelta(days=HISTORY_DAYS_AFTER)).strftime("%Y%m%d")),
            )
        ]
        conn.close()
        ranks = RankCalculator(str(db_path))
        for d in later:
            ranks.calculate_history_for_date(d)
        MonthlyTrendCalculator(str(db_path)).update_month(day)
        print(f"  移動平均を再計算: {len(later)}日、月次トレンド: {day[:6]}")
    else:
        conn.close()

    src = data_dir / hall / f"{day}_{hall}_data.json"
    if src.exists():
        print(f"  JSON を移動: {src.name} -> _excluded/")
        if not dry_run:
            dest = data_dir / hall / "_excluded" / src.name
            dest.parent.mkdir(exist_ok=True)
            shutil.move(str(src), str(dest))

    iso = f"{day[:4]}-{day[4:6]}-{day[6:]}"
    with KNOWN_CLOSED_DAYS.open(encoding="utf-8") as f:
        listed = any(r.get("hall_name") == hall and r.get("date") == iso for r in csv.DictReader(f))
    if not listed:
        print(f"  ⚠️ {KNOWN_CLOSED_DAYS.name} に {hall},{iso} が無い。追記すること（理由: {reason}）")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="休業日に取り込まれた壊れたページを DB から外す")
    ap.add_argument("--db-dir", type=Path, default=PROJECT_ROOT / "db")
    ap.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    for hall, day, reason in CLOSED_DAYS:
        exclude(args.db_dir, args.data_dir, hall, day, reason, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
