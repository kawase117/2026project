"""3軸・5次元の予測ブリーフィングをJSONで出力する読み取り専用CLI。

実行例（Windows）：
    PYTHONUTF8=1 venv\\Scripts\\python.exe -m backtest.prediction_axes briefing "みとや大森町店" 20260924

DBは必ず ``db/<hall>.db`` を読み、ダミーの ``database/pachinko.db`` や
``db/pachinko.db`` は参照しない。将来の拡張候補として、新台導入直後0--6日や
鉄台を除外した推定も考えられるが、現状のaxis2は単純平均に限定する。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from backtest.announce import db_max_date, match_machine_names
from backtest.event_days import active, load

ROOT = Path(__file__).resolve().parents[1]
ANNOUNCE_DIR = ROOT / "backtest" / "announce"
CSV_PATH = ROOT / "eda" / "results" / "briefing" / "model_monthly_edge.csv"

TAG_PATTERNS = {
    "narabi_count": re.compile(r"(\d+)\s*台並び"),
    "narabi_spots": re.compile(r"並び.*?(\d+)\s*(?:ヶ所|か所|箇所)"),
    "zentaikei_model_count": re.compile(r"全[⑤⑥①-⑩]{1,2}.*?(\d+)\s*機種"),
    "hanibun_model_count": re.compile(r"1/2.*?(\d+)\s*機種"),
}


def _json_value(value: Any) -> Any:
    """SQLite/CSV由来の値をJSON標準型にする。"""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _tags(text: str | None) -> list[str]:
    if not text:
        return []
    out = []
    for name, pattern in TAG_PATTERNS.items():
        match = pattern.search(text)
        if match:
            out.append(f"{name}={match.group(1)}")
    return out


def _validate_date(value: str) -> str:
    if not re.fullmatch(r"\d{8}", value):
        raise ValueError("date must be YYYYMMDD")
    datetime.strptime(value, "%Y%m%d")
    return value


def _window(target: str, days: int) -> tuple[str, str]:
    end = datetime.strptime(target, "%Y%m%d").date() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def _warn_skip(path: Path, reason: str) -> None:
    print(f"[WARN] skip announce {path.name}: {reason}", file=sys.stderr)


def _announce_records(hall: str, target: str) -> list[dict[str, Any]]:
    records = []
    for path in sorted(ANNOUNCE_DIR.glob("*.json")):
        try:
            with path.open(encoding="utf-8") as handle:
                record = json.load(handle)
            if not isinstance(record, dict) or not record.get("announce_id"):
                raise ValueError("missing announce_id")
            if not isinstance(record.get("raw_text"), str):
                raise ValueError("missing raw_text")
            if not re.fullmatch(r"\d{8}", str(record.get("target_date", ""))):
                raise ValueError("invalid target_date")
            if record["target_date"] >= target or record.get("hall") != hall:
                continue
            records.append(record)
        except (OSError, json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
            _warn_skip(path, str(exc))
    return records


def _machines_from_record(
    record: dict[str, Any], conn: sqlite3.Connection | None, threshold: float, min_machines: int
) -> tuple[list[str], list[str]]:
    hit, miss = [], []
    result = record.get("result")
    claims = result.get("claims", []) if isinstance(result, dict) else []
    for item in claims:
        if not isinstance(item, dict):
            continue
        claim = item.get("claim", item)
        ctype = claim.get("type") if isinstance(claim, dict) else None
        if ctype == "model_named":
            name = claim.get("machine_name")
            status = item.get("hit")
            if name and status is True:
                hit.append(str(name))
            elif name and status is False:
                miss.append(str(name))
        elif ctype == "zentaikei_count":
            models = item.get("models", [])
            parent_hit = item.get("hit")
            for model in models if isinstance(models, list) else []:
                if not isinstance(model, dict) or not model.get("machine_name"):
                    continue
                name = str(model["machine_name"])
                if parent_hit is True:
                    hit.append(name)
                elif parent_hit is False:
                    miss.append(name)
    if hit or miss or not conn:
        return sorted(set(hit)), sorted(set(miss))

    # 未採点の旧形式を、同じDBの当日実績から最小限補完する。
    names = []
    for claim in record.get("claims", []):
        if isinstance(claim, dict) and claim.get("machine_name"):
            names.append(str(claim["machine_name"]))
    for name in names:
        row = conn.execute(
            "SELECT COUNT(*), AVG(diff_coins_normalized) FROM machine_detailed_results WHERE date=? AND machine_name=?",
            (record["target_date"], name),
        ).fetchone()
        if row and row[0] >= min_machines:
            (hit if row[1] >= threshold else miss).append(name)
    return sorted(set(hit)), sorted(set(miss))


def _axis1(
    hall: str,
    target: str,
    promise_text: str | None,
    event_name: str | None,
    conn: sqlite3.Connection,
    threshold: float,
    min_machines: int,
) -> dict[str, Any]:
    # 既存の照合関数を使い、予告本文に含まれる正式機種名を事前に解決する。
    # 出力契約に機種候補欄はないため、タグと過去予告の採用判定にのみ利用する。
    if promise_text:
        match_machine_names(hall, promise_text)
    records = _announce_records(hall, target)
    event_matches, tag_matches = [], []
    promise_tags = _tags(promise_text)
    for record in records:
        shared = sorted(set(promise_tags) & set(_tags(record["raw_text"])))
        if event_name and event_name in record["raw_text"]:
            hit, miss = _machines_from_record(record, conn, threshold, min_machines)
            event_matches.append(
                {
                    "announce_id": record["announce_id"],
                    "target_date": record["target_date"],
                    "hit_machines": hit,
                    "miss_machines": miss,
                }
            )
        if shared:
            hit, miss = _machines_from_record(record, conn, threshold, min_machines)
            tag_matches.append(
                {
                    "announce_id": record["announce_id"],
                    "target_date": record["target_date"],
                    "shared_tags": shared,
                    "hit_machines": hit,
                    "miss_machines": miss,
                }
            )
    return {"promise_tags": promise_tags, "event_name_matches": event_matches, "tag_matches": tag_matches}


def _query_avg(conn: sqlite3.Connection, table: str, key: str, start: str, end: str) -> list[dict[str, Any]] | None:
    rows = conn.execute(
        f"SELECT {key}, AVG(avg_diff_coins) FROM {table} WHERE date BETWEEN ? AND ? GROUP BY {key} ORDER BY {key}",
        (start, end),
    ).fetchall()
    if not rows:
        return None
    return [{key: _json_value(row[0]), "avg_diff_coins": row[1]} for row in rows]


def _axis2(conn: sqlite3.Connection, hall: str, target: str, days: int) -> dict[str, Any]:
    start, end = _window(target, days)
    out: dict[str, Any] = {}
    if CSV_PATH.exists():
        with CSV_PATH.open(encoding="utf-8-sig", newline="") as handle:
            rows = [
                dict(row)
                for row in csv.DictReader(handle)
                if row.get("hall") == hall and row.get("year_month") == target[:6]
            ]
        out["by_machine"] = rows or None
        out["by_machine_reason"] = (
            None if rows else f"model_monthly_edge.csv にhall={hall}, year_month={target[:6]}の行が無い"
        )
    else:
        out["by_machine"] = None
        out["by_machine_reason"] = f"{CSV_PATH} が存在しない"
    for key, table in (("by_last_digit", "last_digit_summary_all"), ("by_kakuban", "daily_position_summary_all")):
        try:
            value = _query_avg(conn, table, "last_digit" if key == "by_last_digit" else "rank_from_min", start, end)
            if key == "by_last_digit" and value is not None:
                value = [row for row in value if str(row["last_digit"]).isdigit()]
            out[key] = value
            if value is None:
                out[key + "_reason"] = f"{table} に{target}-1以前のデータが無い"
        except sqlite3.OperationalError as exc:
            out[key] = None
            out[key + "_reason"] = f"{table} を読めない: {exc}"

    rows = conn.execute(
        "SELECT date,machine_name,COUNT(DISTINCT machine_number) FROM machine_detailed_results WHERE date BETWEEN ? AND ? GROUP BY date,machine_name ORDER BY machine_name,date",
        (start, end),
    ).fetchall()
    if not rows:
        out["by_count"] = None
        out["by_count_reason"] = "machine_detailed_results に対象期間のデータが無い"
    else:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for day, name, count in rows:
            grouped[name].append({"date": str(day), "machine_count": int(count)})
        out["by_count"] = []
        for name, daily in sorted(grouped.items()):
            change = daily[-1]["machine_count"] - daily[0]["machine_count"]
            out["by_count"].append(
                {
                    "machine_name": name,
                    "daily_counts": daily,
                    "change": change,
                    "trend": "増" if change > 0 else "減" if change < 0 else "横ばい",
                }
            )
    rows = conn.execute(
        "SELECT machine_number,SUM(diff_coins_normalized) AS total_diff_coins FROM machine_detailed_results WHERE date BETWEEN ? AND ? GROUP BY machine_number ORDER BY total_diff_coins",
        (start, end),
    ).fetchall()
    if not rows:
        out["by_individual_number"] = None
        out["by_individual_number_reason"] = "machine_detailed_results に対象期間のデータが無い"
    else:
        low, high = rows[:20], list(reversed(rows[-20:]))
        out["by_individual_number"] = {
            "top20": [{"machine_number": r[0], "total_diff_coins": r[1]} for r in high],
            "bottom20": [{"machine_number": r[0], "total_diff_coins": r[1]} for r in low],
        }
    return out


def briefing(
    hall: str,
    target: str,
    days: int,
    min_machines: int,
    threshold: float,
    promise_text: str | None,
    event_name: str | None,
) -> dict[str, Any]:
    target = _validate_date(target)
    db_path = ROOT / "db" / f"{hall}.db"
    if db_path.stat().st_size == 0:
        raise ValueError(f"zero-byte dummy DB is not allowed: {db_path}")
    conn = sqlite3.connect(db_path)
    try:
        # 既存の事前確認関数を再利用する（DB接続失敗等は握りつぶさない）。
        db_max_date(hall)
        day = conn.execute("SELECT day_of_week,weekday_nth FROM daily_hall_summary WHERE date=?", (target,)).fetchone()
        events = []
        for record in active(load()):
            if record.get("date") == target and record.get("hall") == hall:
                events.append(
                    {
                        "event_id": str(record["event_id"]),
                        "kind": str(record.get("kind", "")),
                        "event_name": str(record.get("event_name", "")),
                        "related_halls": list(record.get("related_halls", [])),
                        "note": str(record.get("note", "")),
                    }
                )
        axis2 = _axis2(conn, hall, target, days)
        result = {
            "hall": hall,
            "date": target,
            "axis3_calendar": {
                "day_of_week": day[0] if day else None,
                "weekday_nth": day[1] if day else None,
                "is_date_zorome": int(target[6:]) in (11, 22),
                "is_strong_zorome": int(target[4:6]) == int(target[6:8]),
                "registered_events": events,
            },
            "axis1_similar_events": _axis1(hall, target, promise_text, event_name, conn, threshold, min_machines),
            "axis2_recent_trend": axis2,
        }
        gaps = []
        for field in ("by_machine", "by_last_digit", "by_kakuban", "by_count", "by_individual_number"):
            if result["axis2_recent_trend"].get(field) is None:
                gaps.append(f"axis2_recent_trend.{field}")
        result["matrix_gaps"] = gaps
        return result
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("briefing")
    p.add_argument("hall")
    p.add_argument("date")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--min-machines", type=int, default=3)
    p.add_argument("--threshold", type=float, default=1800.0)
    p.add_argument("--promise-text")
    p.add_argument("--event-name")
    args = parser.parse_args(argv)
    if args.days < 1 or args.min_machines < 1:
        raise ValueError("days and min-machines must be positive")
    print(
        json.dumps(
            briefing(
                args.hall, args.date, args.days, args.min_machines, args.threshold, args.promise_text, args.event_name
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
