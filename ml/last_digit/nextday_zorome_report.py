from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.last_digit.expert_segmentation import add_floor_atype4_columns
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

_CORRECTION_THRESHOLD = 150

_CONFIDENCE_STRATEGY: dict[str, str] = {
    "high":      "アグレッシブ（TOP1集中・長時間）",
    "medium":    "標準（TOP1を1〜2台）",
    "low":       "控えめ（様子見）",
    "undefined": "スキップ推奨",
}


def _span_label(span_val: float | None, confidence_band: str) -> str:
    strategy = _CONFIDENCE_STRATEGY.get(confidence_band, "")
    if span_val is None:
        return "span=N/A  [--]"
    return f"span={span_val:.4f}  [{confidence_band}]  {strategy}"


def attach_confidence_pct(rows: list[dict]) -> list[dict]:
    """Min-max normalize combined_score to 0-100 confidence_pct per row."""
    if not rows:
        return rows
    scores = [float(r["combined_score"]) for r in rows]
    lo, hi = min(scores), max(scores)
    span = hi - lo
    result = []
    for r, s in zip(rows, scores):
        pct = int(round((s - lo) / span * 100)) if span > 0.0 else 0
        result.append({**r, "confidence_pct": pct})
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render a next-day tail forecast with latest zorome machines.")
    parser.add_argument("--nextday-json", required=True, help="Path to existing nextday JSON output.")
    parser.add_argument("--db-path", required=True, help="SQLite DB path used to fetch latest zorome machines.")
    parser.add_argument("--top-n", type=int, default=5, help="Number of top digits to include per segment.")
    parser.add_argument(
        "--output-prefix",
        default="db/experiments/nextday_zorome_report",
        help="Output prefix for generated JSON/TXT artifacts.",
    )
    parser.add_argument("--min-correction-n", type=int, default=3, help="Min observations for correction calculation.")
    parser.add_argument("--unified-top-n", type=int, default=20, help="Rows shown in unified ranking.")
    parser.add_argument("--log-level", default="INFO", help="Logging level.")
    return parser


def load_nextday_result(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def attach_combined_score(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    copied = [dict(row) for row in rows]
    for row in copied:
        row["combined_score"] = float(row["combined_score"])
    return copied


# ---------------------------------------------------------------------------
# DB fetchers (kept for backward compatibility — imported by nextday_gpu)
# ---------------------------------------------------------------------------

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
        .apply(
            lambda g: list(zip(g["machine_number"].astype(int), g["machine_name"].astype(str))),
            include_groups=False,
        )
        .to_dict()
    )
    return str(latest_date), {str(k): v for k, v in grouped.items()}


def fetch_latest_zorome_by_expert_digit(
    db_path: str | Path,
) -> tuple[str, dict[str, dict[str, list[tuple[int, str]]]]]:
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
              COALESCE(mm.oki_flag, 0) AS oki_flag,
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

    work = add_floor_atype4_columns(df)
    if work.empty:
        return str(latest_date), {}
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


# ---------------------------------------------------------------------------
# Segment detail: correction + machine counts
# ---------------------------------------------------------------------------

def _load_full_df_with_segments(db_path: str | Path) -> pd.DataFrame:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    try:
        df = pd.read_sql(
            """
            SELECT m.date, m.machine_number, m.machine_name, m.last_digit,
                   m.is_zorome, m.games_normalized, m.diff_coins_normalized,
                   COALESCE(mm.jug_flag, 0)  AS jug_flag,
                   COALESCE(mm.hana_flag, 0) AS hana_flag,
                   COALESCE(mm.oki_flag, 0)  AS oki_flag,
                   COALESCE(mm.bt_flag, 0)   AS bt_flag
            FROM machine_detailed_results m
            LEFT JOIN machine_master mm ON m.machine_name = mm.machine_name_normalized
            ORDER BY m.date, m.machine_number
            """,
            conn,
        )
    finally:
        conn.close()

    df["date_dt"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["weekday"] = df["date_dt"].dt.day_name()
    df["is_zorome"] = df["is_zorome"].astype(int)
    df = add_floor_atype4_columns(df).rename(columns={"expert": "group_key"})
    df["last_digit"] = df["last_digit"].astype(str)
    return df


def build_correction_lookup(
    df_seg: pd.DataFrame,
    target_weekday: str,
    min_n: int,
) -> dict[tuple[str, str], int | None]:
    """Return {(expert, digit): correction} for target_weekday."""
    from ml.last_digit import zorome_strategy_simulation as zsim  # lazy import to avoid circular
    corr_table = zsim.compute_zorome_correction_table(df_seg, min_zorome_n=min_n, min_nonzorome_n=min_n)
    subset = corr_table[corr_table["weekday"] == target_weekday].copy()
    subset["last_digit"] = subset["last_digit"].astype(str)
    lookup: dict[tuple[str, str], int | None] = {}
    for _, row in subset.iterrows():
        val = row["correction"]
        lookup[(str(row["group_key"]), str(row["last_digit"]))] = (
            int(round(val)) if (val is not None and np.isfinite(float(val))) else None
        )
    return lookup


def build_latest_machine_info(
    df_seg: pd.DataFrame,
) -> tuple[dict[tuple[str, str], int], dict[tuple[str, str], list[tuple[int, str]]]]:
    """Return (total_count_lookup, zorome_machine_lookup) keyed by (expert, digit)."""
    latest_date = df_seg["date"].max()
    df_latest = df_seg[df_seg["date"] == latest_date].copy()

    count_lookup: dict[tuple[str, str], int] = {}
    for (expert, digit), g in df_latest.groupby(["group_key", "last_digit"]):
        count_lookup[(str(expert), str(digit))] = len(g)

    zorome_lookup: dict[tuple[str, str], list[tuple[int, str]]] = {}
    for (expert, digit), g in df_latest[df_latest["is_zorome"] == 1].groupby(["group_key", "last_digit"]):
        zorome_lookup[(str(expert), str(digit))] = [
            (int(r["machine_number"]), str(r["machine_name"])) for _, r in g.iterrows()
        ]
    return count_lookup, zorome_lookup


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _fmt_correction(val: int | None) -> str:
    if val is None:
        return "データ不足"
    if val > _CORRECTION_THRESHOLD:
        return f"+{val} [狙い]"
    if val < -_CORRECTION_THRESHOLD:
        return f"{val} [避ける]"
    return f"+{val} [中立]" if val >= 0 else f"{val} [中立]"


def _fmt_machines(machines: list[tuple[int, str]]) -> str:
    if not machines:
        return "(なし)"
    return " / ".join(f"{num} {name}" for num, name in machines)


def render_segment_detail_report(
    *,
    nextday_result: dict[str, Any],
    correction_lookup: dict[tuple[str, str], int | None],
    count_lookup: dict[tuple[str, str], int],
    zorome_lookup: dict[tuple[str, str], list[tuple[int, str]]],
    top_n: int,
    unified_top_n: int,
    hall_name: str,
) -> str:
    target_date = str(nextday_result.get("target_date", ""))
    target_weekday = str(nextday_result.get("target_weekday", ""))
    weekday_label = _WEEKDAY_EN.get(target_weekday, target_weekday)
    expert_preds: dict[str, Any] = nextday_result.get("expert_predictions", {})
    expert_order = ["2F_N", "3F_N", "3F_A", "2F_A"]

    lines: list[str] = [
        f"翌日予測 ({hall_name}, {target_date} {weekday_label})",
        f"ゾロ目スコア = correction（ゾロ目台平均差枚 - 非ゾロ目台平均差枚, {weekday_label}×末尾×セグメント別）",
        f"閾値: >+{_CORRECTION_THRESHOLD}[狙い] / -{_CORRECTION_THRESHOLD}〜+{_CORRECTION_THRESHOLD}[中立] / <-{_CORRECTION_THRESHOLD}[避ける]",
    ]

    col_w = (4, 4, 5, 70, 25, 12)
    header = (
        f"{'順位':<{col_w[0]}} {'末尾':<{col_w[1]}} {'台数':<{col_w[2]}} "
        f"{'ゾロ目台':<{col_w[3]}} {'ゾロ目スコア':<{col_w[4]}} {'モデルスコア'}"
    )
    sep = "-" * (sum(col_w) + 5)

    for expert in expert_order:
        if expert not in expert_preds:
            continue
        info = expert_preds[expert]
        span_val = info.get("pred_span_top12")
        cband = str(info.get("confidence_band", ""))
        lines.append(f"\n【{expert}】  {_span_label(span_val, cband)}")
        lines.append(header)
        lines.append(sep)
        for ri in expert_preds[expert].get("ranking", [])[:top_n]:
            rank = ri["rank"]
            digit = str(ri["last_digit"])
            model_score = ri["pred"]
            total_cnt = count_lookup.get((expert, digit), 0)
            corr = correction_lookup.get((expert, digit))
            machines = zorome_lookup.get((expert, digit), [])
            lines.append(
                f"{rank:<{col_w[0]}} {digit:<{col_w[1]}} {total_cnt:<{col_w[2]}} "
                f"{_fmt_machines(machines):<{col_w[3]}} {_fmt_correction(corr):<{col_w[4]}} {model_score:.6f}"
            )

    # unified ranking
    all_rows: list[dict[str, Any]] = []
    for expert in expert_order:
        if expert not in expert_preds:
            continue
        for ri in expert_preds[expert].get("ranking", []):
            digit = str(ri["last_digit"])
            all_rows.append(
                {
                    "seg_digit": f"{expert}_{digit}",
                    "total_cnt": count_lookup.get((expert, digit), 0),
                    "corr": correction_lookup.get((expert, digit)),
                    "machines": zorome_lookup.get((expert, digit), []),
                    "model_score": ri["pred"],
                }
            )
    all_rows.sort(key=lambda x: -x["model_score"])

    col_u = (5, 18, 5, 70, 25, 12)
    rule = "=" * (sum(col_u) + 5)
    lines.append(f"\n\n{rule}")
    lines.append(f"全セグメント統合ランキング（モデルスコア順, TOP{unified_top_n}）")
    lines.append(rule)
    lines.append(
        f"{'順位':<{col_u[0]}} {'末尾 (セグ_末尾)':<{col_u[1]}} {'台数':<{col_u[2]}} "
        f"{'ゾロ目台':<{col_u[3]}} {'ゾロ目スコア':<{col_u[4]}} {'モデルスコア'}"
    )
    lines.append("-" * (sum(col_u) + 5))
    for i, row in enumerate(all_rows[:unified_top_n], 1):
        lines.append(
            f"{i:<{col_u[0]}} {row['seg_digit']:<{col_u[1]}} {row['total_cnt']:<{col_u[2]}} "
            f"{_fmt_machines(row['machines']):<{col_u[3]}} {_fmt_correction(row['corr']):<{col_u[4]}} {row['model_score']:.6f}"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Legacy text report (kept for callers that import render_text_report)
# ---------------------------------------------------------------------------

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
        f"Next-day forecast ({hall_name}, {target_date} {weekday_label})".rstrip(),
        "-" * 60,
    ]
    for row in ranked_rows[: max(int(top_n), 0)]:
        digit = str(row["last_digit"])
        lines.append(f"Rank {int(row['rank'])}: tail {digit}  combined_score {float(row['combined_score']):.4f}")
        lines.append("  Zorome machines:")
        machines = zorome_by_digit.get(digit, [])
        if not machines:
            lines.append("    (none)")
            continue
        for machine_number, machine_name in machines:
            lines.append(f"    {machine_number} {machine_name}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Output payload
# ---------------------------------------------------------------------------

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
                "zorome_machines": [
                    {"machine_number": int(mn), "machine_name": str(mname)}
                    for mn, mname in zorome_by_digit.get(digit, [])
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


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(args.log_level)

    nextday_result = load_nextday_result(args.nextday_json)
    combined_rows = (
        nextday_result.get("combined_ranking")
        or nextday_result.get("combined_priority_ranking")
        or []
    )
    if not isinstance(combined_rows, list) or not combined_rows:
        raise ValueError("combined_ranking / combined_priority_ranking is missing from input JSON.")

    ranked_rows = attach_combined_score(combined_rows)
    hall_name = _hall_name_from_result(nextday_result, args.db_path)
    target_date = str(nextday_result.get("target_date", ""))
    target_weekday = str(nextday_result.get("target_weekday", ""))
    date_suffix = _date_suffix(target_date)

    # segment detail report (new default output)
    logger.info("Loading full DB snapshot for correction table ...")
    df_seg = _load_full_df_with_segments(args.db_path)
    correction_lookup = build_correction_lookup(df_seg, target_weekday, args.min_correction_n)
    count_lookup, zorome_lookup = build_latest_machine_info(df_seg)

    segment_report = render_segment_detail_report(
        nextday_result=nextday_result,
        correction_lookup=correction_lookup,
        count_lookup=count_lookup,
        zorome_lookup=zorome_lookup,
        top_n=args.top_n,
        unified_top_n=args.unified_top_n,
        hall_name=hall_name,
    )

    # legacy combined payload (for pipeline compat)
    latest_machine_date, zorome_by_digit = fetch_latest_zorome_by_digit(args.db_path)
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
    txt_path.write_text(segment_report, encoding="utf-8")

    logger.info("Wrote zorome report JSON: %s", json_path)
    logger.info("Wrote segment detail TXT: %s", txt_path)

    print(segment_report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
