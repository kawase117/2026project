from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.last_digit.utils import configure_logging


logger = logging.getLogger(__name__)
_WEEKDAY_ORDER = ["月", "火", "水", "木", "金", "土", "日"]
_HOKUTO_EXACT = "スマスロ北斗の拳"
_MONKEY_EXACT = "モンキーターンV"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate whether Hokuto points to the best 2FN tail.")
    parser.add_argument("--db-path", required=True, help="SQLite DB path.")
    parser.add_argument("--topk-csv", required=True, help="Path to *_testperiod_topk.csv.")
    parser.add_argument("--min-games", type=int, default=3000, help="Per-machine minimum games threshold.")
    parser.add_argument(
        "--output-dir",
        default="db/experiments/signal_accuracy_2fn",
        help="Directory for CSV/JSON outputs.",
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level.")
    return parser


def normalize_digit(value: Any) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith(".0"):
        text = text[:-2]
    return text


def normalize_db_date(value: Any) -> str:
    text = str(value).strip()
    return text.replace("-", "")


def resolve_machine_name(
    conn: sqlite3.Connection,
    *,
    exact_name: str,
    like_pattern: str | None = None,
    exclude_patterns: tuple[str, ...] = (),
) -> str:
    df_exact = pd.read_sql(
        """
        SELECT DISTINCT machine_name
        FROM machine_detailed_results
        WHERE machine_name = ?
        """,
        conn,
        params=[exact_name],
    )
    if not df_exact.empty:
        return str(df_exact.iloc[0]["machine_name"])
    if not like_pattern:
        raise ValueError(f"Machine name not found: {exact_name}")

    df_like = pd.read_sql(
        """
        SELECT DISTINCT machine_name
        FROM machine_detailed_results
        WHERE machine_name LIKE ?
        ORDER BY machine_name
        """,
        conn,
        params=[like_pattern],
    )
    names = [str(x) for x in df_like["machine_name"].tolist()]
    if exclude_patterns:
        names = [name for name in names if not any(pat in name for pat in exclude_patterns)]
    if len(names) == 1:
        return names[0]
    if not names:
        raise ValueError(f"No machine names matched {like_pattern}")
    raise ValueError(f"Ambiguous machine names for {like_pattern}: {names}")


def fetch_dates_and_weekdays(conn: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql(
        """
        SELECT date, day_of_week
        FROM daily_hall_summary
        ORDER BY date
        """,
        conn,
    )
    df["date"] = df["date"].map(normalize_db_date)
    df["day_of_week"] = df["day_of_week"].astype(str)
    return df


def fetch_hokuto_rows(conn: sqlite3.Connection, hokuto_name: str) -> pd.DataFrame:
    df = pd.read_sql(
        """
        SELECT
            date,
            machine_number,
            last_digit,
            diff_coins_normalized,
            games_normalized
        FROM machine_detailed_results
        WHERE machine_name = ?
          AND CAST(machine_number AS INTEGER) BETWEEN 2000 AND 2999
        """,
        conn,
        params=[hokuto_name],
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


def load_prediction_history(topk_csv: str | Path, expert: str = "2F_N") -> tuple[pd.DataFrame, dict[str, dict[str, Any]]]:
    df_topk = pd.read_csv(topk_csv)
    df_pred = df_topk[df_topk["expert"].astype(str) == str(expert)].copy()
    if df_pred.empty:
        return df_pred, {}
    df_pred["date"] = df_pred["date"].astype(str).str.replace("-", "", regex=False)
    df_pred["top1_tail"] = df_pred["top1_tail"].map(normalize_digit)
    df_pred["hit_at_2"] = pd.to_numeric(df_pred["hit_at_2"], errors="coerce")
    df_pred["hard_miss"] = df_pred["hit_at_2"].fillna(0.0) <= 0.0
    pred_map = (
        df_pred.set_index("date")[["top1_tail", "hit_at_2", "hard_miss"]]
        .to_dict(orient="index")
    )
    return df_pred, pred_map


def compute_hokuto_best(df_day: pd.DataFrame, min_games: int) -> dict[str, Any]:
    if df_day.empty:
        return {"best_digit": None, "best_diff": None, "n_valid": 0, "top2_digits": []}
    valid = df_day[pd.to_numeric(df_day["games_normalized"], errors="coerce").fillna(0) >= int(min_games)].copy()
    if valid.empty:
        return {"best_digit": None, "best_diff": None, "n_valid": 0, "top2_digits": []}
    valid["diff_coins_normalized"] = pd.to_numeric(valid["diff_coins_normalized"], errors="coerce")
    agg = (
        valid.groupby("last_digit", dropna=True, as_index=False)
        .agg(avg_diff=("diff_coins_normalized", "mean"))
        .sort_values(["avg_diff", "last_digit"], ascending=[False, True])
    )
    top2 = [digit for digit in agg["last_digit"].map(normalize_digit).head(2).tolist() if digit is not None]
    return {
        "best_digit": normalize_digit(agg.iloc[0]["last_digit"]),
        "best_diff": float(agg.iloc[0]["avg_diff"]),
        "n_valid": int(len(valid)),
        "top2_digits": top2,
    }


def compute_2fn_best_digit(df_day: pd.DataFrame) -> str | None:
    if df_day.empty:
        return None
    work = df_day.copy()
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    agg = work.groupby("last_digit", dropna=True)["diff_coins_normalized"].mean().sort_values(ascending=False)
    if agg.empty:
        return None
    return normalize_digit(agg.index[0])


def build_daily_rows(
    *,
    df_dates: pd.DataFrame,
    df_hokuto: pd.DataFrame,
    df_other: pd.DataFrame,
    pred_map: dict[str, dict[str, Any]],
    min_games: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    total = len(df_dates)
    grouped_hokuto = {date: sub.copy() for date, sub in df_hokuto.groupby("date", sort=False)} if not df_hokuto.empty else {}
    grouped_other = {date: sub.copy() for date, sub in df_other.groupby("date", sort=False)} if not df_other.empty else {}
    for idx, rec in enumerate(df_dates.to_dict(orient="records"), start=1):
        if idx == 1 or idx % 50 == 0 or idx == total:
            logger.info("Processing accuracy day %s/%s", idx, total)
        date = normalize_db_date(rec["date"])
        weekday = str(rec.get("day_of_week", ""))
        hokuto = compute_hokuto_best(grouped_hokuto.get(date, pd.DataFrame()), min_games=min_games)
        best_2fn = compute_2fn_best_digit(grouped_other.get(date, pd.DataFrame()))
        pred_info = pred_map.get(date, {})
        has_pred = bool(pred_info)
        pred_top1 = normalize_digit(pred_info.get("top1_tail")) if has_pred else None
        hit_at_2 = pred_info.get("hit_at_2") if has_pred else np.nan
        hard_miss = bool(pred_info.get("hard_miss")) if has_pred else np.nan
        is_match = bool(hokuto["best_digit"] is not None and best_2fn is not None and hokuto["best_digit"] == best_2fn)
        is_top2_match = bool(best_2fn is not None and best_2fn in hokuto["top2_digits"])
        actual_rank1_digit = best_2fn
        exact_hit = bool(pred_top1 == actual_rank1_digit) if has_pred and actual_rank1_digit is not None else np.nan
        exact_miss = bool(not exact_hit) if has_pred and actual_rank1_digit is not None else np.nan
        soft_miss = bool((not hard_miss) and exact_miss) if has_pred and actual_rank1_digit is not None else np.nan
        rows.append(
            {
                "date": date,
                "day_of_week": weekday,
                "hokuto_best_digit": hokuto["best_digit"],
                "hokuto_best_diff": hokuto["best_diff"],
                "hokuto_n_valid": hokuto["n_valid"],
                "best_2fn_digit": best_2fn,
                "actual_rank1_digit": actual_rank1_digit,
                "is_match": is_match,
                "is_top2_match": is_top2_match,
                "pred_top1_tail": pred_top1,
                "hit_at_2": hit_at_2,
                "hard_miss": hard_miss,
                "exact_hit": exact_hit,
                "exact_miss": exact_miss,
                "soft_miss": soft_miss,
                "has_pred": has_pred,
            }
        )
    return rows


def calc_stats(day_list: list[dict[str, Any]], baseline: float) -> dict[str, Any]:
    if not day_list:
        return {
            "n": 0,
            "hit_rate": float("nan"),
            "top2_hit_rate": float("nan"),
            "lift_over_baseline": float("nan"),
        }
    hit_rate = float(sum(bool(r["is_match"]) for r in day_list) / len(day_list))
    top2_hit_rate = float(sum(bool(r["is_top2_match"]) for r in day_list) / len(day_list))
    lift = float(hit_rate / baseline) if np.isfinite(baseline) and baseline > 0 else float("nan")
    return {
        "n": int(len(day_list)),
        "hit_rate": hit_rate,
        "top2_hit_rate": top2_hit_rate,
        "lift_over_baseline": lift,
    }


def weekday_breakdown(day_list: list[dict[str, Any]], baseline: float) -> dict[str, dict[str, Any]]:
    return {
        weekday: calc_stats([row for row in day_list if row["day_of_week"] == weekday], baseline=baseline)
        for weekday in _WEEKDAY_ORDER
    }


def build_weekday_summary_frame(daily_df: pd.DataFrame, n_digits: int) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    baseline_top1 = (1.0 / float(n_digits)) if n_digits > 0 else float("nan")
    baseline_top2 = (2.0 / float(n_digits)) if n_digits > 0 else float("nan")
    work = daily_df.copy()
    if "exact_miss" not in work.columns:
        work["exact_miss"] = work["exact_hit"].map(
            lambda v: (not bool(v)) if pd.notna(v) else np.nan
        )
    for weekday in _WEEKDAY_ORDER:
        sub = work[(work["day_of_week"].astype(str) == weekday) & work["hokuto_best_digit"].notna()].copy()
        pred_sub = sub[sub["has_pred"] == True].copy()
        rows.append(
            {
                "day_of_week": weekday,
                "n_signal_days": int(len(sub)),
                "hit_rate": float(sub["is_match"].mean()) if len(sub) else float("nan"),
                "top2_hit_rate": float(sub["is_top2_match"].mean()) if len(sub) else float("nan"),
                "pred_days": int(len(pred_sub)),
                "exact_hit_rate_on_pred_days": float(pred_sub["exact_hit"].mean()) if len(pred_sub) else float("nan"),
                "exact_miss_days": int(pred_sub["exact_miss"].fillna(False).sum()) if len(pred_sub) else 0,
                "baseline_top1_random": baseline_top1,
                "baseline_top2_random": baseline_top2,
            }
        )
    return pd.DataFrame(rows)


def build_summary_payload(
    *,
    rows: list[dict[str, Any]],
    topk_csv_used: str,
    min_games_threshold: int,
    n_digits: int,
) -> dict[str, Any]:
    df = pd.DataFrame(rows)
    baseline = (1.0 / float(n_digits)) if n_digits > 0 else float("nan")
    all_valid = [row for row in rows if row["hokuto_best_digit"] is not None]
    hard_miss_rows = [row for row in rows if row["has_pred"] and row["hard_miss"] is True]
    hard_miss_valid = [row for row in hard_miss_rows if row["hokuto_best_digit"] is not None]
    soft_ref_rows = [row for row in rows if row["has_pred"] and pd.notna(row["hit_at_2"]) and float(row["hit_at_2"]) == 1.0]
    soft_ref_valid = [row for row in soft_ref_rows if row["hokuto_best_digit"] is not None]
    exact_rows = [row for row in rows if row["has_pred"] and pd.notna(row["exact_hit"])]
    exact_miss_rows = [row for row in exact_rows if row["exact_miss"] is True]

    all_stats = calc_stats(all_valid, baseline=baseline)
    hard_stats = calc_stats(hard_miss_valid, baseline=baseline)
    soft_stats = calc_stats(soft_ref_valid, baseline=baseline)

    return {
        "topk_csv_used": str(topk_csv_used),
        "expert": "2F_N",
        "miss_definition": "hard_miss (hit_at_2 == 0)",
        "min_games_threshold": int(min_games_threshold),
        "n_digits": int(n_digits),
        "baseline_random": baseline,
        "all_days": {
            "n_total": int(len(df)),
            "n_with_signal": int(len(all_valid)),
            "n_no_signal": int(len(df) - len(all_valid)),
            "hit_rate": all_stats["hit_rate"],
            "top2_hit_rate": all_stats["top2_hit_rate"],
            "lift_over_baseline": all_stats["lift_over_baseline"],
            "weekday": weekday_breakdown(all_valid, baseline=baseline),
        },
        "hard_miss_days": {
            "n_total": int(len(hard_miss_rows)),
            "n_with_signal": int(len(hard_miss_valid)),
            "n_no_signal": int(len(hard_miss_rows) - len(hard_miss_valid)),
            "hit_rate": hard_stats["hit_rate"],
            "top2_hit_rate": hard_stats["top2_hit_rate"],
            "lift_over_baseline": hard_stats["lift_over_baseline"],
            "note": "予測top1がactual top-2に入らなかった日（hard_miss）",
            "weekday": weekday_breakdown(hard_miss_valid, baseline=baseline),
        },
        "soft_miss_reference": {
            "n": int(len(soft_ref_rows)),
            "n_with_signal": int(len(soft_ref_valid)),
            "hit_rate": soft_stats["hit_rate"],
            "top2_hit_rate": soft_stats["top2_hit_rate"],
            "note": "hit_at_2==1 の日。exact rank1 miss とは限らない参考値。",
        },
        "exact_pred_vs_actual_rank1": {
            "n_total": int(len(exact_rows)),
            "exact_hit_rate": float(np.mean([bool(row["exact_hit"]) for row in exact_rows])) if exact_rows else float("nan"),
            "exact_miss_days": int(len(exact_miss_rows)),
            "note": "pred_top1_tail と DB集計の actual_rank1_digit (= best_2fn_digit) の直接比較。",
            "weekday": {
                weekday: {
                    "n": int(len([row for row in exact_rows if row["day_of_week"] == weekday])),
                    "exact_hit_rate": (
                        float(np.mean([bool(row["exact_hit"]) for row in exact_rows if row["day_of_week"] == weekday]))
                        if any(row["day_of_week"] == weekday for row in exact_rows)
                        else float("nan")
                    ),
                }
                for weekday in _WEEKDAY_ORDER
            },
        },
    }


def build_analysis_note(*, hokuto_name: str, monkey_name: str) -> str:
    return "\n".join(
        [
            "# Analysis Note",
            "",
            "## Hokuto granularity",
            f"- Hokuto machine name used: {hokuto_name}",
            f"- Monkey machine name used: {monkey_name}",
            "- This implementation aggregates Hokuto at the last-digit level after per-machine min-games filtering.",
            "- When the hall operates one Hokuto machine per tail, tail average and tail max are effectively identical.",
            "- When historical periods contain multiple Hokuto machines per tail, tail average is the safer representation.",
            "- Therefore, comparisons across periods should treat Hokuto granularity as time-varying, not fixed.",
        ]
    )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(args.log_level)

    db_path = Path(args.db_path).expanduser().resolve()
    topk_csv = Path(args.topk_csv).expanduser().resolve()
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
        df_hokuto = fetch_hokuto_rows(conn, hokuto_name=hokuto_name)
        df_other = fetch_other_rows(conn, excluded_machine_names=[hokuto_name, monkey_name])
    finally:
        conn.close()

    df_pred, pred_map = load_prediction_history(topk_csv, expert="2F_N")
    rows = build_daily_rows(
        df_dates=df_dates,
        df_hokuto=df_hokuto,
        df_other=df_other,
        pred_map=pred_map,
        min_games=int(args.min_games),
    )
    daily_df = pd.DataFrame(rows)
    n_digits = int(df_other["last_digit"].dropna().nunique()) if not df_other.empty else 0
    weekday_df = build_weekday_summary_frame(daily_df, n_digits=n_digits)
    payload = build_summary_payload(
        rows=rows,
        topk_csv_used=str(topk_csv),
        min_games_threshold=int(args.min_games),
        n_digits=n_digits,
    )

    daily_path = out_dir / "signal_accuracy_2fn_daily.csv"
    weekday_path = out_dir / "signal_accuracy_2fn_weekday_summary.csv"
    summary_path = out_dir / "signal_accuracy_2fn_summary.json"
    note_path = out_dir / "analysis_note.md"
    daily_df.to_csv(daily_path, index=False, encoding="utf-8")
    weekday_df.to_csv(weekday_path, index=False, encoding="utf-8")
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    note_path.write_text(build_analysis_note(hokuto_name=hokuto_name, monkey_name=monkey_name), encoding="utf-8")

    logger.info("Resolved Hokuto machine name: %s", hokuto_name)
    logger.info("Resolved Monkey machine name: %s", monkey_name)
    logger.info("Prediction rows loaded: %s", len(df_pred))
    logger.info("Wrote daily CSV: %s", daily_path)
    logger.info("Wrote weekday CSV: %s", weekday_path)
    logger.info("Wrote summary JSON: %s", summary_path)
    logger.info("Wrote analysis note: %s", note_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
