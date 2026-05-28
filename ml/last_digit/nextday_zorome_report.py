from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

from ml.last_digit.utils import configure_logging


logger = logging.getLogger(__name__)

_WEEKDAY_EN = {
    "Monday": "月曜日",
    "Tuesday": "火曜日",
    "Wednesday": "水曜日",
    "Thursday": "木曜日",
    "Friday": "金曜日",
    "Saturday": "土曜日",
    "Sunday": "日曜日",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render a next-day tail forecast with latest zorome machines.")
    parser.add_argument("--nextday-json", required=True, help="Path to existing nextday JSON output.")
    parser.add_argument("--db-path", required=True, help="SQLite DB path used to fetch latest zorome machines.")
    parser.add_argument("--top-n", type=int, default=3, help="Number of top digits to include in the report.")
    parser.add_argument(
        "--output-prefix",
        default="db/experiments/nextday_zorome_report",
        help="Output prefix for generated JSON/TXT artifacts.",
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level.")
    return parser


def load_nextday_result(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def attach_confidence_pct(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    copied = [dict(row) for row in rows]
    if not copied:
        return copied
    scores = [float(row["combined_score"]) for row in copied]
    min_score = min(scores)
    max_score = max(scores)
    for row in copied:
        score = float(row["combined_score"])
        if max_score > min_score:
            confidence = round((score - min_score) / (max_score - min_score) * 100)
        else:
            confidence = 100
        row["confidence_pct"] = int(confidence)
    return copied


def fetch_latest_zorome_by_digit(db_path: str | Path) -> tuple[str, dict[str, list[tuple[int, str]]]]:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    try:
        latest_date = conn.execute("SELECT MAX(date) FROM machine_detailed_results").fetchone()[0]
        if not latest_date:
            return "", {}
        df = pd.read_sql(
            """
            SELECT machine_number, machine_name, last_digit
            FROM machine_detailed_results
            WHERE date = ? AND is_zorome = 1
            ORDER BY machine_number
            """,
            conn,
            params=[latest_date],
        )
    finally:
        conn.close()
    if df.empty:
        return str(latest_date), {}
    grouped = (
        df.groupby("last_digit", sort=True)
        .apply(lambda g: list(zip(g["machine_number"].astype(int), g["machine_name"].astype(str))), include_groups=False)
        .to_dict()
    )
    return str(latest_date), {str(k): v for k, v in grouped.items()}


def fetch_latest_zorome_by_expert_digit(
    db_path: str | Path,
) -> tuple[str, dict[str, dict[str, list[tuple[int, str]]]]]:
    """Return zorome machines keyed by expert(2F_N/3F_N/3F_A/2F_A) and last_digit."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    try:
        latest_date = conn.execute("SELECT MAX(date) FROM machine_detailed_results").fetchone()[0]
        if not latest_date:
            return "", {}
        df = pd.read_sql(
            """
            SELECT
              m.machine_number,
              m.machine_name,
              m.last_digit,
              COALESCE(mm.jug_flag, 0) AS jug_flag,
              COALESCE(mm.hana_flag, 0) AS hana_flag,
              COALESCE(mm.bt_flag, 0) AS bt_flag
            FROM machine_detailed_results m
            LEFT JOIN machine_master mm
              ON m.machine_name = mm.machine_name_normalized
            WHERE m.date = ? AND m.is_zorome = 1
            ORDER BY m.machine_number
            """,
            conn,
            params=[latest_date],
        )
    finally:
        conn.close()
    if df.empty:
        return str(latest_date), {}

    work = df.copy()
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work = work[work["machine_number"].notna()].copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work["floor_head"] = work["machine_number"].astype(str).str[0]
    work = work[work["floor_head"].isin(["2", "3"])].copy()
    if work.empty:
        return str(latest_date), {}

    work["is_a_type"] = (
        (pd.to_numeric(work["jug_flag"], errors="coerce").fillna(0).astype(int) == 1)
        | (pd.to_numeric(work["hana_flag"], errors="coerce").fillna(0).astype(int) == 1)
        | (pd.to_numeric(work["bt_flag"], errors="coerce").fillna(0).astype(int) == 1)
    )
    work["expert"] = work["floor_head"] + "F_" + work["is_a_type"].map({True: "A", False: "N"})
    work["last_digit"] = work["last_digit"].astype(str)

    result: dict[str, dict[str, list[tuple[int, str]]]] = {}
    for expert, g_expert in work.groupby("expert", sort=True):
        by_digit: dict[str, list[tuple[int, str]]] = {}
        for digit, g_digit in g_expert.groupby("last_digit", sort=True):
            by_digit[str(digit)] = list(
                zip(
                    g_digit["machine_number"].astype(int).tolist(),
                    g_digit["machine_name"].astype(str).tolist(),
                )
            )
        result[str(expert)] = by_digit
    return str(latest_date), result


def _weekday_label(target_weekday: str, target_date: str) -> str:
    if target_weekday:
        return _WEEKDAY_EN.get(str(target_weekday), str(target_weekday))
    if not target_date:
        return ""
    return _WEEKDAY_EN.get(pd.Timestamp(target_date).day_name(), "")


def render_text_report(
    *,
    hall_name: str,
    target_date: str,
    target_weekday: str,
    ranked_rows: list[dict[str, Any]],
    zorome_by_digit: dict[str, list[tuple[int, str]]],
    top_n: int,
) -> str:
    weekday_label = _weekday_label(target_weekday, target_date)
    lines = [
        f"翌日予測 ({hall_name}, {target_date} {weekday_label})".rstrip(),
        "─────────────────────────────────────────",
    ]
    for row in ranked_rows[: max(int(top_n), 0)]:
        digit = str(row["last_digit"])
        lines.append(f"Rank {int(row['rank'])}: 末尾 {digit}  確信度 {int(row['confidence_pct'])}%")
        lines.append("  台末尾ゾロ目:")
        machines = zorome_by_digit.get(digit, [])
        if not machines:
            lines.append("    なし")
            continue
        for machine_number, machine_name in machines:
            lines.append(f"    {machine_number} {machine_name}")
    return "\n".join(lines)


def _hall_name_from_result(nextday_result: dict[str, Any], db_path: str | Path) -> str:
    for key in ("hall_name", "store_name", "store_id"):
        value = nextday_result.get(key)
        if value:
            return str(value)
    return Path(db_path).stem


def _date_suffix(target_date: str) -> str:
    return str(target_date).replace("-", "")


def build_output_payload(
    *,
    nextday_result: dict[str, Any],
    ranked_rows: list[dict[str, Any]],
    zorome_by_digit: dict[str, list[tuple[int, str]]],
    hall_name: str,
    latest_machine_date: str,
    nextday_json_path: str | Path,
    top_n: int,
) -> dict[str, Any]:
    payload_rows: list[dict[str, Any]] = []
    for row in ranked_rows[: max(int(top_n), 0)]:
        digit = str(row["last_digit"])
        payload_rows.append(
            {
                "rank": int(row["rank"]),
                "last_digit": digit,
                "combined_score": float(row["combined_score"]),
                "confidence_pct": int(row["confidence_pct"]),
                "zorome_machines": [
                    {"machine_number": int(machine_number), "machine_name": str(machine_name)}
                    for machine_number, machine_name in zorome_by_digit.get(digit, [])
                ],
            }
        )
    return {
        "hall_name": hall_name,
        "source_latest_date": nextday_result.get("source_latest_date", ""),
        "target_date": nextday_result.get("target_date", ""),
        "target_weekday": nextday_result.get("target_weekday", ""),
        "latest_machine_date": latest_machine_date,
        "nextday_json_path": str(nextday_json_path),
        "top_n": int(top_n),
        "combined_ranking": payload_rows,
    }


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(args.log_level)

    nextday_result = load_nextday_result(args.nextday_json)
    # JSONキーは "combined_ranking" または "combined_priority_ranking" のどちらかを許容
    combined_rows = (
        nextday_result.get("combined_ranking")
        or nextday_result.get("combined_priority_ranking")
        or []
    )
    if not isinstance(combined_rows, list) or not combined_rows:
        raise ValueError(
            "combined_ranking / combined_priority_ranking が JSON に見つからないか空です。"
        )

    ranked_rows = attach_confidence_pct(combined_rows)
    latest_machine_date, zorome_by_digit = fetch_latest_zorome_by_digit(args.db_path)
    hall_name = _hall_name_from_result(nextday_result, args.db_path)
    target_date = str(nextday_result.get("target_date", ""))
    date_suffix = _date_suffix(target_date or latest_machine_date)

    text_report = render_text_report(
        hall_name=hall_name,
        target_date=target_date,
        target_weekday=str(nextday_result.get("target_weekday", "")),
        ranked_rows=ranked_rows,
        zorome_by_digit=zorome_by_digit,
        top_n=int(args.top_n),
    )
    payload = build_output_payload(
        nextday_result=nextday_result,
        ranked_rows=ranked_rows,
        zorome_by_digit=zorome_by_digit,
        hall_name=hall_name,
        latest_machine_date=latest_machine_date,
        nextday_json_path=args.nextday_json,
        top_n=int(args.top_n),
    )

    out_prefix = Path(args.output_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    json_path = out_prefix.with_name(f"{out_prefix.name}_{date_suffix}.json")
    txt_path = out_prefix.with_name(f"{out_prefix.name}_{date_suffix}.txt")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    txt_path.write_text(text_report, encoding="utf-8")

    logger.info("Wrote zorome report JSON: %s", json_path)
    logger.info("Wrote zorome report TXT: %s", txt_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
