from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.experiments.signal_accuracy_2fn import (
    _HOKUTO_EXACT,
    _MONKEY_EXACT,
    _WEEKDAY_ORDER,
    compute_2fn_best_digit,
    fetch_dates_and_weekdays,
    normalize_db_date,
    normalize_digit,
    resolve_machine_name,
)
from ml.last_digit.utils import configure_logging


logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate single-tail vs multi-tail signal validity for 2FN.")
    parser.add_argument("--db-path", required=True, help="SQLite DB path.")
    parser.add_argument(
        "--signal-source",
        choices=["diff", "rb", "or"],
        default="or",
        help="Signal decision source at the tail level.",
    )
    parser.add_argument(
        "--signal-mode",
        choices=["fixed", "quantile"],
        default="fixed",
        help="Signal selection mode. 'fixed' uses absolute thresholds, 'quantile' uses within-day tail quantiles.",
    )
    parser.add_argument("--diff-threshold", type=float, default=200.0, help="Diff threshold for signal tails.")
    parser.add_argument("--rb-threshold", type=float, default=(1 / 300), help="RB decimal threshold for signal tails.")
    parser.add_argument("--diff-quantile", type=float, default=0.8, help="Upper quantile for avg_diff when signal-mode=quantile.")
    parser.add_argument("--rb-quantile", type=float, default=0.8, help="Upper quantile for avg_rb when signal-mode=quantile.")
    parser.add_argument(
        "--quantile-sweep",
        action="store_true",
        help="When signal-mode=quantile, run a sweep over 0.80/0.90/0.95 and write one comparison JSON.",
    )
    parser.add_argument("--min-games", type=int, default=3000, help="Per-machine minimum games threshold.")
    parser.add_argument(
        "--output-dir",
        default="db/experiments/signal_multi_tail_2fn",
        help="Directory for CSV/JSON outputs.",
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level.")
    return parser


def fetch_machine_rows(conn: sqlite3.Connection, machine_name: str) -> pd.DataFrame:
    df = pd.read_sql(
        """
        SELECT
            date,
            machine_name,
            machine_number,
            last_digit,
            diff_coins_normalized,
            games_normalized,
            rb_probability_decimal
        FROM machine_detailed_results
        WHERE machine_name = ?
          AND CAST(machine_number AS INTEGER) BETWEEN 2000 AND 2999
        """,
        conn,
        params=[machine_name],
    )
    if df.empty:
        return df
    df["date"] = df["date"].map(normalize_db_date)
    df["last_digit"] = df["last_digit"].map(normalize_digit)
    return df


def fetch_other_rows(conn: sqlite3.Connection, excluded_machine_names: list[str]) -> pd.DataFrame:
    placeholders = ",".join("?" * len(excluded_machine_names))
    df = pd.read_sql(
        f"""
        SELECT
            date,
            last_digit,
            diff_coins_normalized
        FROM machine_detailed_results
        WHERE CAST(machine_number AS INTEGER) BETWEEN 2000 AND 2999
          AND machine_name NOT IN ({placeholders})
        """,
        conn,
        params=excluded_machine_names,
    )
    if df.empty:
        return df
    df["date"] = df["date"].map(normalize_db_date)
    df["last_digit"] = df["last_digit"].map(normalize_digit)
    return df


def aggregate_signal_machine_day(df_day: pd.DataFrame, *, min_games: int) -> pd.DataFrame:
    if df_day.empty:
        return pd.DataFrame(columns=["last_digit", "avg_diff", "avg_rb", "n_valid"])
    valid = df_day[pd.to_numeric(df_day["games_normalized"], errors="coerce").fillna(0) >= int(min_games)].copy()
    if valid.empty:
        return pd.DataFrame(columns=["last_digit", "avg_diff", "avg_rb", "n_valid"])
    valid["diff_coins_normalized"] = pd.to_numeric(valid["diff_coins_normalized"], errors="coerce")
    valid["rb_probability_decimal"] = pd.to_numeric(valid["rb_probability_decimal"], errors="coerce")
    agg = valid.groupby("last_digit", dropna=True).agg(
        avg_diff=("diff_coins_normalized", "mean"),
        avg_rb=("rb_probability_decimal", "mean"),
        n_valid=("last_digit", "size"),
    )
    agg = agg.reset_index()
    agg["last_digit"] = agg["last_digit"].map(normalize_digit)
    return agg


def select_signal_tails(
    agg: pd.DataFrame,
    *,
    signal_mode: str,
    signal_source: str = "or",
    diff_threshold: float,
    rb_threshold: float,
    diff_quantile: float,
    rb_quantile: float,
) -> set[str]:
    if agg.empty:
        return set()
    work = agg.copy()
    diff_mask = pd.to_numeric(work["avg_diff"], errors="coerce") > float(diff_threshold)
    rb_mask = pd.to_numeric(work["avg_rb"], errors="coerce") > float(rb_threshold)
    if signal_mode == "fixed":
        if signal_source == "diff":
            signal = work[diff_mask]
        elif signal_source == "rb":
            signal = work[rb_mask]
        else:
            signal = work[diff_mask | rb_mask]
        return {digit for digit in signal["last_digit"].map(normalize_digit).tolist() if digit is not None}

    diff_cut = float(pd.to_numeric(work["avg_diff"], errors="coerce").quantile(float(diff_quantile)))
    rb_cut = float(pd.to_numeric(work["avg_rb"], errors="coerce").quantile(float(rb_quantile)))
    diff_qmask = pd.to_numeric(work["avg_diff"], errors="coerce") >= diff_cut
    rb_qmask = pd.to_numeric(work["avg_rb"], errors="coerce") >= rb_cut
    if signal_source == "diff":
        signal = work[diff_qmask]
    elif signal_source == "rb":
        signal = work[rb_qmask]
    else:
        signal = work[diff_qmask | rb_qmask]
    return {digit for digit in signal["last_digit"].map(normalize_digit).tolist() if digit is not None}


def get_hokuto_signal_tails(
    df_hokuto_day: pd.DataFrame,
    *,
    min_games: int,
    diff_threshold: float,
    rb_threshold: float,
    signal_source: str = "or",
    signal_mode: str = "fixed",
    diff_quantile: float = 0.8,
    rb_quantile: float = 0.8,
) -> set[str]:
    agg = aggregate_signal_machine_day(df_hokuto_day, min_games=min_games)
    return select_signal_tails(
        agg,
        signal_mode=signal_mode,
        signal_source=signal_source,
        diff_threshold=diff_threshold,
        rb_threshold=rb_threshold,
        diff_quantile=diff_quantile,
        rb_quantile=rb_quantile,
    )


def get_monkey_signal_tails(
    df_monkey_day: pd.DataFrame,
    *,
    min_games: int,
    diff_threshold: float,
    rb_threshold: float,
    signal_source: str = "or",
    signal_mode: str = "fixed",
    diff_quantile: float = 0.8,
    rb_quantile: float = 0.8,
) -> set[str]:
    agg = aggregate_signal_machine_day(df_monkey_day, min_games=min_games)
    return select_signal_tails(
        agg,
        signal_mode=signal_mode,
        signal_source=signal_source,
        diff_threshold=diff_threshold,
        rb_threshold=rb_threshold,
        diff_quantile=diff_quantile,
        rb_quantile=rb_quantile,
    )


def build_multi_tail_daily_rows(
    *,
    df_dates: pd.DataFrame,
    df_hokuto: pd.DataFrame,
    df_monkey: pd.DataFrame,
    df_other: pd.DataFrame,
    diff_threshold: float,
    rb_threshold: float,
    min_games: int,
    signal_source: str = "or",
    signal_mode: str = "fixed",
    diff_quantile: float = 0.8,
    rb_quantile: float = 0.8,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    total = len(df_dates)
    grouped_hokuto = {date: sub.copy() for date, sub in df_hokuto.groupby("date", sort=False)} if not df_hokuto.empty else {}
    grouped_monkey = {date: sub.copy() for date, sub in df_monkey.groupby("date", sort=False)} if not df_monkey.empty else {}
    grouped_other = {date: sub.copy() for date, sub in df_other.groupby("date", sort=False)} if not df_other.empty else {}

    for idx, rec in enumerate(df_dates.to_dict(orient="records"), start=1):
        if idx == 1 or idx % 50 == 0 or idx == total:
            logger.info("Processing multi-tail day %s/%s", idx, total)
        date = normalize_db_date(rec["date"])
        weekday = str(rec.get("day_of_week", ""))
        hokuto_tails = get_hokuto_signal_tails(
            grouped_hokuto.get(date, pd.DataFrame()),
            min_games=min_games,
            diff_threshold=diff_threshold,
            rb_threshold=rb_threshold,
            signal_source=signal_source,
            signal_mode=signal_mode,
            diff_quantile=diff_quantile,
            rb_quantile=rb_quantile,
        )
        monkey_tails = get_monkey_signal_tails(
            grouped_monkey.get(date, pd.DataFrame()),
            min_games=min_games,
            diff_threshold=diff_threshold,
            rb_threshold=rb_threshold,
            signal_source=signal_source,
            signal_mode=signal_mode,
            diff_quantile=diff_quantile,
            rb_quantile=rb_quantile,
        )
        signal_tails = sorted(hokuto_tails | monkey_tails)
        other_day = grouped_other.get(date, pd.DataFrame())
        best_2fn = compute_2fn_best_digit(other_day)
        signal_tail_2fn_avgs: dict[str, float | None] = {}
        for tail in signal_tails:
            sub = other_day[other_day["last_digit"].map(normalize_digit) == tail].copy()
            if sub.empty:
                signal_tail_2fn_avgs[tail] = None
                continue
            signal_tail_2fn_avgs[tail] = float(pd.to_numeric(sub["diff_coins_normalized"], errors="coerce").mean())
        n_signal = len(signal_tails)
        category = "no_signal" if n_signal == 0 else ("single" if n_signal == 1 else "multi")
        is_match = bool(best_2fn is not None and best_2fn in signal_tails)
        rows.append(
            {
                "date": date,
                "day_of_week": weekday,
                "n_signal_tails": n_signal,
                "signal_tails": ",".join(signal_tails),
                "best_2fn_digit": best_2fn,
                "is_match": is_match,
                "category": category,
                "signal_tail_2fn_avgs": json.dumps(signal_tail_2fn_avgs, ensure_ascii=False, sort_keys=True),
            }
        )
    return rows


def _hit_rate(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return float("nan")
    return float(sum(bool(row["is_match"]) for row in rows) / len(rows))


def build_summary_payload(
    rows: list[dict[str, Any]],
    *,
    signal_source: str,
    signal_mode: str,
    diff_threshold: float,
    rb_threshold: float,
    diff_quantile: float,
    rb_quantile: float,
    min_games: int,
    n_digits: int,
) -> dict[str, Any]:
    single_rows = [row for row in rows if row["category"] == "single"]
    multi_rows = [row for row in rows if row["category"] == "multi"]
    baseline = (1.0 / float(n_digits)) if n_digits > 0 else float("nan")

    weekday_breakdown: dict[str, dict[str, Any]] = {}
    for weekday in _WEEKDAY_ORDER:
        weekday_rows = [row for row in rows if row["day_of_week"] == weekday]
        weekday_single = [row for row in weekday_rows if row["category"] == "single"]
        weekday_multi = [row for row in weekday_rows if row["category"] == "multi"]
        weekday_breakdown[weekday] = {
            "single_n": int(len(weekday_single)),
            "single_hit": _hit_rate(weekday_single),
            "multi_n": int(len(weekday_multi)),
            "multi_hit": _hit_rate(weekday_multi),
        }

    avg_n_signal = float(np.mean([row["n_signal_tails"] for row in multi_rows])) if multi_rows else float("nan")
    fake_rate = float(sum(not bool(row["is_match"]) for row in multi_rows) / len(multi_rows)) if multi_rows else float("nan")
    return {
        "signal_condition": {
            "signal_source": str(signal_source),
            "signal_mode": str(signal_mode),
            "diff_threshold": float(diff_threshold),
            "rb_threshold": float(rb_threshold),
            "diff_quantile": float(diff_quantile),
            "rb_quantile": float(rb_quantile),
            "rb_direction": ">",
            "min_games": int(min_games),
        },
        "day_counts": {
            "no_signal": int(sum(row["category"] == "no_signal" for row in rows)),
            "single": int(len(single_rows)),
            "multi": int(len(multi_rows)),
        },
        "single_signal_hit_rate": _hit_rate(single_rows),
        "multi_signal_hit_rate": _hit_rate(multi_rows),
        "baseline_random": baseline,
        "multi_signal_detail": {
            "avg_n_signal_tails": avg_n_signal,
            "fake_rate": fake_rate,
        },
        "weekday_breakdown": weekday_breakdown,
    }


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    single_rows = [row for row in rows if row["category"] == "single"]
    multi_rows = [row for row in rows if row["category"] == "multi"]
    return {
        "day_counts": {
            "no_signal": int(sum(row["category"] == "no_signal" for row in rows)),
            "single": int(len(single_rows)),
            "multi": int(len(multi_rows)),
        },
        "single_signal_hit_rate": _hit_rate(single_rows),
        "multi_signal_hit_rate": _hit_rate(multi_rows),
        "fake_rate": (
            float(sum(not bool(row["is_match"]) for row in multi_rows) / len(multi_rows))
            if multi_rows
            else float("nan")
        ),
        "avg_signal_tails_when_multi": (
            float(np.mean([row["n_signal_tails"] for row in multi_rows]))
            if multi_rows
            else float("nan")
        ),
    }


def build_sweep_payload(
    *,
    rows_by_quantile: dict[float, list[dict[str, Any]]],
    signal_source: str,
    sweep_quantiles: list[float],
) -> dict[str, Any]:
    return {
        "signal_source": str(signal_source),
        "signal_mode": "quantile",
        "sweep_quantiles": [float(q) for q in sweep_quantiles],
        "results": {
            f"{q:.2f}": summarize_rows(rows_by_quantile.get(q, []))
            for q in sweep_quantiles
        },
    }


def build_analysis_note(*, signal_mode: str, signal_source: str) -> str:
    return "\n".join(
        [
            "# Analysis Note",
            "",
            "## Hokuto granularity",
            "- Hokuto is aggregated at the last-digit level after per-machine min-games filtering.",
            "- In periods with one Hokuto machine per tail, tail average and tail max are effectively identical.",
            "- In periods with multiple Hokuto machines per tail, tail average is the safer comparison target.",
            "",
            "## Signal mode",
            f"- Current run used signal_mode={signal_mode}.",
            f"- Current run used signal_source={signal_source}.",
            "- fixed: absolute thresholds on tail-level avg_diff / avg_rb.",
            "- quantile: within-day relative thresholds on tail-level avg_diff / avg_rb.",
            "- diff: avg_diff only.",
            "- rb: avg_rb only.",
            "- or: avg_diff or avg_rb.",
        ]
    )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(args.log_level)
    if args.quantile_sweep and str(args.signal_mode) != "quantile":
        parser.error("--quantile-sweep requires --signal-mode quantile")

    db_path = Path(args.db_path).expanduser().resolve()
    out_dir = Path(args.output_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    try:
        hokuto_name = resolve_machine_name(
            conn,
            exact_name=_HOKUTO_EXACT,
            like_pattern="スマスロ北斗%",
            exclude_patterns=("転生",),
        )
        monkey_name = resolve_machine_name(
            conn,
            exact_name=_MONKEY_EXACT,
            like_pattern="モンキーターン%",
        )
        df_dates = fetch_dates_and_weekdays(conn)
        df_hokuto = fetch_machine_rows(conn, machine_name=hokuto_name)
        df_monkey = fetch_machine_rows(conn, machine_name=monkey_name)
        df_other = fetch_other_rows(conn, excluded_machine_names=[hokuto_name, monkey_name])
    finally:
        conn.close()

    if args.quantile_sweep:
        sweep_quantiles = [0.80, 0.90, 0.95]
        rows_by_quantile: dict[float, list[dict[str, Any]]] = {}
        for q in sweep_quantiles:
            logger.info("Running quantile sweep q=%.2f source=%s", q, args.signal_source)
            rows_by_quantile[q] = build_multi_tail_daily_rows(
                df_dates=df_dates,
                df_hokuto=df_hokuto,
                df_monkey=df_monkey,
                df_other=df_other,
                diff_threshold=float(args.diff_threshold),
                rb_threshold=float(args.rb_threshold),
                min_games=int(args.min_games),
                signal_source=str(args.signal_source),
                signal_mode="quantile",
                diff_quantile=float(q),
                rb_quantile=float(q),
            )
        sweep_payload = build_sweep_payload(
            rows_by_quantile=rows_by_quantile,
            signal_source=str(args.signal_source),
            sweep_quantiles=sweep_quantiles,
        )
        sweep_path = out_dir / f"signal_multi_tail_sweep_{args.signal_source}.json"
        sweep_path.write_text(json.dumps(sweep_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        note_path = out_dir / "analysis_note.md"
        note_path.write_text(
            build_analysis_note(signal_mode="quantile-sweep", signal_source=str(args.signal_source)),
            encoding="utf-8",
        )
        logger.info("Wrote sweep JSON: %s", sweep_path)
        logger.info("Wrote analysis note: %s", note_path)
        return 0

    rows = build_multi_tail_daily_rows(
        df_dates=df_dates,
        df_hokuto=df_hokuto,
        df_monkey=df_monkey,
        df_other=df_other,
        diff_threshold=float(args.diff_threshold),
        rb_threshold=float(args.rb_threshold),
        min_games=int(args.min_games),
        signal_source=str(args.signal_source),
        signal_mode=str(args.signal_mode),
        diff_quantile=float(args.diff_quantile),
        rb_quantile=float(args.rb_quantile),
    )
    daily_df = pd.DataFrame(rows)
    n_digits = int(df_other["last_digit"].dropna().nunique()) if not df_other.empty else 0
    payload = build_summary_payload(
        rows,
        signal_source=str(args.signal_source),
        signal_mode=str(args.signal_mode),
        diff_threshold=float(args.diff_threshold),
        rb_threshold=float(args.rb_threshold),
        diff_quantile=float(args.diff_quantile),
        rb_quantile=float(args.rb_quantile),
        min_games=int(args.min_games),
        n_digits=n_digits,
    )

    daily_path = out_dir / "signal_multi_tail_daily.csv"
    summary_path = out_dir / "signal_multi_tail_summary.json"
    note_path = out_dir / "analysis_note.md"
    daily_df.to_csv(daily_path, index=False, encoding="utf-8")
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    note_path.write_text(
        build_analysis_note(signal_mode=str(args.signal_mode), signal_source=str(args.signal_source)),
        encoding="utf-8",
    )

    logger.info("Resolved Hokuto machine name: %s", hokuto_name)
    logger.info("Resolved Monkey machine name: %s", monkey_name)
    logger.info("Wrote daily CSV: %s", daily_path)
    logger.info("Wrote summary JSON: %s", summary_path)
    logger.info("Wrote analysis note: %s", note_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
