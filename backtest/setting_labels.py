"""確認された台の設定ラベルを追記専用 JSONL で管理する。"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sqlite3
import sys

from backtest.event_days import _normalize_hall


ROOT = Path(__file__).resolve().parents[1]
DB_DIR = ROOT / "db"
LEDGER = ROOT / "document" / "registry" / "SETTING_LABELS.jsonl"
JST = timezone(timedelta(hours=9))
EVIDENCE = ("self_play", "confirmed", "hint", "estimate")
WORDS = {"低設定": (1, 2), "高設定": (5, 6), "中間": (3, 4)}
FIELDS = {
    "label_id",
    "hall",
    "date",
    "machine_number",
    "machine_name",
    "setting_low",
    "setting_high",
    "setting_text",
    "evidence",
    "played",
    "selection_reason",
    "note",
    "source",
    "recorded_at",
    "supersedes",
}


def parse_date(value):
    if not re.fullmatch(r"[0-9]{8}", value):
        raise ValueError("日付は YYYYMMDD で指定してください")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise ValueError("存在しない日付です") from exc
    return value


def parse_setting(value):
    if value in WORDS:
        return *WORDS[value], value
    if re.fullmatch(r"[1-6]", value):
        n = int(value)
        return n, n, value
    match = re.fullmatch(r"([1-6])-([1-6])", value)
    if match and int(match[1]) <= int(match[2]):
        return int(match[1]), int(match[2]), value
    raise ValueError("設定は単一の数字 1～6、範囲 (例: 4-6)、低設定、高設定、中間から指定してください")


def read_rows(path=LEDGER):
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                raise ValueError(f"{number}行目: 空行です")
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{number}行目: JSON が不正です: {exc.msg}") from exc
    return rows


def db_path(hall):
    if not hall or any(c in hall for c in ("/", "\\", "\0")) or hall in (".", ".."):
        raise ValueError("ホール名が不正です")
    path = DB_DIR / f"{hall}.db"
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"DB がありません: {path}")
    return path


def result_row(hall, date, machine_number):
    path = db_path(hall)
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT machine_name, games_normalized, diff_coins_normalized, rb_count, bb_count "
            "FROM machine_detailed_results WHERE date = ? AND machine_number = ? LIMIT 1",
            (date, machine_number),
        ).fetchone()
        exists = (
            con.execute(
                "SELECT 1 FROM machine_detailed_results WHERE machine_number = ? LIMIT 1",
                (machine_number,),
            ).fetchone()
            is not None
        )
    return dict(row) if row else None, exists


def make_id(hall, date, machine_number):
    return f"{date}_{hall}_{machine_number}"


def active_indices(rows):
    """同じ固定 ID の訂正は、先行する同 ID の最終行を閉じる。"""
    closed = set()
    latest = {}
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        target = row.get("supersedes")
        if target in latest:
            closed.add(latest[target])
        if isinstance(row.get("label_id"), str):
            latest[row["label_id"]] = i
    return closed


def cmd_add(args):
    hall = _normalize_hall(args.hall)
    date = parse_date(args.date)
    if args.machine_number <= 0:
        raise ValueError("台番号は正の整数で指定してください")
    low, high, setting_text = parse_setting(args.setting)
    result, exists = result_row(hall, date, args.machine_number)
    if not exists:
        raise ValueError(f"{hall} の DB に台番号 {args.machine_number} は存在しません")
    if result is None:
        print(f"警告: {date} の台番号 {args.machine_number} は実績未収録です。machine_name=null で登録します")

    rows = read_rows(LEDGER)
    label_id = make_id(hall, date, args.machine_number)
    previous = [r for r in rows if isinstance(r, dict) and r.get("label_id") == label_id]
    if previous:
        if args.supersedes != label_id:
            raise ValueError(f"重複: {label_id}。訂正には --supersedes {label_id} を指定してください")
    elif args.supersedes:
        raise ValueError(f"訂正対象が存在しません: {args.supersedes}")
    record = {
        "label_id": label_id,
        "hall": hall,
        "date": date,
        "machine_number": args.machine_number,
        "machine_name": result["machine_name"] if result else None,
        "setting_low": low,
        "setting_high": high,
        "setting_text": setting_text,
        "evidence": args.evidence,
        "played": args.played,
        "selection_reason": args.selection_reason,
        "note": args.note,
        "source": "user",
        "recorded_at": datetime.now(JST).isoformat(timespec="seconds"),
        "supersedes": args.supersedes,
    }
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    if args.dry_run:
        print("DRY-RUN: 書き込みなし")
        print(line)
        return 0
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")
    print(f"登録: {label_id}")
    return 0


def cmd_list(args):
    rows = read_rows(LEDGER)
    closed = active_indices(rows)
    hall = _normalize_hall(args.hall) if args.hall else None
    since = parse_date(args.since) if args.since else None
    count = 0
    for i, row in enumerate(rows):
        if i in closed and not args.all:
            continue
        if hall and row.get("hall") != hall:
            continue
        if since and row.get("date", "") < since:
            continue
        if args.evidence and row.get("evidence") != args.evidence:
            continue
        mark = " 訂正済み" if i in closed else ""
        print(f'{row.get("label_id")} [{row.get("evidence")}] {row.get("setting_low")}-{row.get("setting_high")}{mark}')
        count += 1
    if count == 0:
        print("0件")
    return 0


def cmd_show(args):
    rows = read_rows(LEDGER)
    matches = [(i, r) for i, r in enumerate(rows) if r.get("label_id") == args.label_id]
    if not matches:
        raise ValueError(f"ラベルがありません: {args.label_id}")
    i, row = matches[-1]
    print(json.dumps(row, ensure_ascii=False, indent=2))
    if i in active_indices(rows):
        print("訂正済み")
    result, _ = result_row(row["hall"], row["date"], row["machine_number"])
    if result is None:
        print("実績未収録")
    else:
        for key in ("games_normalized", "diff_coins_normalized", "rb_count", "bb_count"):
            print(f"{key}: {result[key]}")
    return 0


def validate_row(row, number, seen):
    problems = []
    prefix = f"{number}行目"
    if not isinstance(row, dict):
        return [f"{prefix}: JSON オブジェクトではありません"]
    if set(row) != FIELDS:
        problems.append(f"{prefix}: schema 不一致 (不足={sorted(FIELDS - set(row))}, 余分={sorted(set(row) - FIELDS)})")
    hall, date, machine_number = row.get("hall"), row.get("date"), row.get("machine_number")
    if not isinstance(hall, str) or not hall or _normalize_hall(hall) != hall:
        problems.append(f"{prefix}: hall が不正です")
    elif not (DB_DIR / f"{hall}.db").is_file():
        problems.append(f"{prefix}: hall の DB がありません")
    try:
        if not isinstance(date, str):
            raise ValueError
        parse_date(date)
    except ValueError:
        problems.append(f"{prefix}: date が不正です")
    if type(machine_number) is not int or machine_number <= 0:
        problems.append(f"{prefix}: machine_number が不正です")
    if (
        isinstance(date, str)
        and isinstance(hall, str)
        and type(machine_number) is int
        and row.get("label_id") != make_id(hall, date, machine_number)
    ):
        problems.append(f"{prefix}: label_id が不正です")
    for key in ("setting_low", "setting_high"):
        if type(row.get(key)) is not int or not 1 <= row[key] <= 6:
            problems.append(f"{prefix}: {key} が不正です")
    if (
        type(row.get("setting_low")) is int
        and type(row.get("setting_high")) is int
        and row["setting_low"] > row["setting_high"]
    ):
        problems.append(f"{prefix}: 設定の上下限が逆です")
    for key in ("machine_name", "setting_text", "selection_reason", "note"):
        if row.get(key) is not None and not isinstance(row[key], str):
            problems.append(f"{prefix}: {key} が不正です")
    if not isinstance(row.get("evidence"), str) or row["evidence"] not in EVIDENCE:
        problems.append(f"{prefix}: evidence が不正です")
    if type(row.get("played")) is not bool:
        problems.append(f"{prefix}: played が不正です")
    if row.get("source") != "user":
        problems.append(f"{prefix}: source が不正です")
    try:
        stamp = datetime.fromisoformat(row["recorded_at"])
        if stamp.utcoffset() != timedelta(hours=9):
            raise ValueError
    except KeyError, TypeError, ValueError:
        problems.append(f"{prefix}: recorded_at が不正です")
    target = row.get("supersedes")
    label_id = row.get("label_id")
    if target is not None and (not isinstance(target, str) or target not in seen or target != label_id):
        problems.append(f"{prefix}: supersedes の参照が不正です")
    if isinstance(label_id, str):
        if label_id in seen and target != label_id:
            problems.append(f"{prefix}: 重複した label_id に訂正指定がありません")
        seen.add(label_id)
    return problems


def cmd_validate(_args):
    try:
        rows = read_rows(LEDGER)
    except ValueError as exc:
        print(exc)
        return 1
    problems = []
    seen = set()
    for number, row in enumerate(rows, 1):
        problems.extend(validate_row(row, number, seen))
    if problems:
        for problem in problems:
            print(problem)
        return 1
    print("OK")
    return 0


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add")
    add.add_argument("--hall", required=True)
    add.add_argument("--date", required=True)
    add.add_argument("--machine-number", required=True, type=int)
    add.add_argument("--setting", required=True)
    add.add_argument("--evidence", required=True, choices=EVIDENCE)
    played = add.add_mutually_exclusive_group()
    played.add_argument("--played", dest="played", action="store_true")
    played.add_argument("--no-played", dest="played", action="store_false")
    add.set_defaults(played=False, fn=cmd_add)
    add.add_argument("--selection-reason")
    add.add_argument("--note")
    add.add_argument("--supersedes")
    add.add_argument("--dry-run", action="store_true")
    listing = sub.add_parser("list")
    listing.add_argument("--hall")
    listing.add_argument("--since")
    listing.add_argument("--evidence", choices=EVIDENCE)
    listing.add_argument("--all", action="store_true")
    listing.set_defaults(fn=cmd_list)
    show = sub.add_parser("show")
    show.add_argument("label_id")
    show.set_defaults(fn=cmd_show)
    sub.add_parser("validate").set_defaults(fn=cmd_validate)
    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except (ValueError, sqlite3.Error, OSError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
