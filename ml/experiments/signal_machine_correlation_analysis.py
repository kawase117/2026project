from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu
from statsmodels.stats.multitest import multipletests

from ml.last_digit.utils import configure_logging


logger = logging.getLogger(__name__)

_WEEKDAY_ORDER = ["月", "火", "水", "木", "金", "土", "日"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze cross-machine correlation for signal machines.")
    parser.add_argument("--db-path", required=True, help="SQLite DB path.")
    parser.add_argument(
        "--output-dir",
        default="db/experiments/signal_machine_correlation",
        help="Directory for CSV/JSON outputs.",
    )
    parser.add_argument("--diff-threshold", type=float, default=200.0, help="Diff-coins threshold for a signal.")
    parser.add_argument("--rb-threshold", type=float, default=(1 / 300), help="RB probability threshold for a signal.")
    parser.add_argument("--log-level", default="INFO", help="Logging level.")
    return parser


def fetch_signal_machine_names(conn: sqlite3.Connection) -> list[str]:
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT machine_name FROM machine_detailed_results WHERE machine_name LIKE 'スマスロ北斗%'")
    hokuto_names = [str(row[0]) for row in cursor.fetchall()]
    cursor.execute("SELECT DISTINCT machine_name FROM machine_detailed_results WHERE machine_name LIKE 'モンキーターン%'")
    monkey_names = [str(row[0]) for row in cursor.fetchall()]
    return hokuto_names + monkey_names


def _placeholders(n: int) -> str:
    return ",".join("?" * n)


def fetch_signal_rows(conn: sqlite3.Connection, signal_machines: list[str]) -> pd.DataFrame:
    return pd.read_sql(
        f"""
        SELECT
            date,
            machine_name,
            last_digit,
            AVG(diff_coins_normalized) AS avg_diff,
            AVG(rb_probability_decimal) AS avg_rb_prob,
            COUNT(*) AS n_machines
        FROM machine_detailed_results
        WHERE machine_name IN ({_placeholders(len(signal_machines))})
        GROUP BY date, machine_name, last_digit
        """,
        conn,
        params=signal_machines,
    )


def fetch_other_rows(conn: sqlite3.Connection, signal_machines: list[str]) -> pd.DataFrame:
    return pd.read_sql(
        f"""
        SELECT
            m.date,
            m.last_digit,
            m.machine_name,
            m.diff_coins_normalized,
            d.day_of_week
        FROM machine_detailed_results m
        JOIN daily_hall_summary d ON m.date = d.date
        WHERE m.machine_name NOT IN ({_placeholders(len(signal_machines))})
        """,
        conn,
        params=signal_machines,
    )


def attach_signal_flags(signal_rows: pd.DataFrame, diff_threshold: float, rb_threshold: float) -> pd.DataFrame:
    df = signal_rows.copy()
    df["signal_diff"] = pd.to_numeric(df["avg_diff"], errors="coerce").fillna(0.0) > float(diff_threshold)
    df["signal_rb"] = pd.to_numeric(df["avg_rb_prob"], errors="coerce").fillna(0.0) > float(rb_threshold)
    df["signal"] = df["signal_diff"] | df["signal_rb"]
    return df


def extract_signal_pairs(signal_rows: pd.DataFrame, flag_column: str) -> pd.DataFrame:
    if signal_rows.empty:
        return pd.DataFrame(columns=["date", "last_digit"])
    return signal_rows.loc[signal_rows[flag_column], ["date", "last_digit"]].drop_duplicates().reset_index(drop=True)


def mark_signal_membership(other_df: pd.DataFrame, signal_pairs: pd.DataFrame, output_column: str) -> pd.DataFrame:
    df = other_df.copy()
    if signal_pairs.empty:
        df[output_column] = False
        return df
    signal_index = pd.MultiIndex.from_frame(signal_pairs.loc[:, ["date", "last_digit"]])
    row_index = pd.MultiIndex.from_frame(df.loc[:, ["date", "last_digit"]])
    df[output_column] = row_index.isin(signal_index)
    return df


def compute_group_comparison(df: pd.DataFrame, flag_column: str) -> dict[str, float]:
    signal_vals = pd.to_numeric(df.loc[df[flag_column], "diff_coins_normalized"], errors="coerce").dropna().to_numpy(dtype=float)
    nonsignal_vals = pd.to_numeric(df.loc[~df[flag_column], "diff_coins_normalized"], errors="coerce").dropna().to_numpy(dtype=float)
    out = {
        "signal_mean": float(np.mean(signal_vals)) if signal_vals.size else float("nan"),
        "signal_std": float(np.std(signal_vals, ddof=0)) if signal_vals.size else float("nan"),
        "signal_n": int(signal_vals.size),
        "nonsignal_mean": float(np.mean(nonsignal_vals)) if nonsignal_vals.size else float("nan"),
        "nonsignal_std": float(np.std(nonsignal_vals, ddof=0)) if nonsignal_vals.size else float("nan"),
        "nonsignal_n": int(nonsignal_vals.size),
        "delta": float(np.mean(signal_vals) - np.mean(nonsignal_vals)) if signal_vals.size and nonsignal_vals.size else float("nan"),
        "p_value": float("nan"),
    }
    if signal_vals.size and nonsignal_vals.size:
        try:
            _, p_value = mannwhitneyu(signal_vals, nonsignal_vals, alternative="two-sided")
            out["p_value"] = float(p_value)
        except ValueError:
            out["p_value"] = float("nan")
    return out


def build_weekday_stats(df: pd.DataFrame, flag_column: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for weekday in _WEEKDAY_ORDER:
        sub = df[df["day_of_week"].astype(str) == weekday].copy()
        stats = compute_group_comparison(sub, flag_column)
        rows.append(
            {
                "day_of_week": weekday,
                "signal_n": stats["signal_n"],
                "nonsignal_n": stats["nonsignal_n"],
                "signal_mean": stats["signal_mean"],
                "nonsignal_mean": stats["nonsignal_mean"],
                "delta": stats["delta"],
                "p_raw": stats["p_value"],
            }
        )
    out = pd.DataFrame(rows)
    valid = out["p_raw"].notna()
    out["p_adj"] = np.nan
    out["reject_fdr_bh"] = False
    if valid.any():
        reject, p_adj, _, _ = multipletests(out.loc[valid, "p_raw"], method="fdr_bh")
        out.loc[valid, "p_adj"] = p_adj
        out.loc[valid, "reject_fdr_bh"] = reject
    return out


def build_fake_tail_check(df: pd.DataFrame, flag_column: str) -> dict[str, float]:
    pair_df = (
        df.groupby(["date", "last_digit", flag_column], as_index=False)
        .agg(avg_diff=("diff_coins_normalized", "mean"))
        .rename(columns={flag_column: "in_signal"})
    )
    signal_vals = pair_df.loc[pair_df["in_signal"], "avg_diff"].to_numpy(dtype=float)
    nonsignal_vals = pair_df.loc[~pair_df["in_signal"], "avg_diff"].to_numpy(dtype=float)
    return {
        "signal_tail_avg_diff": float(np.mean(signal_vals)) if signal_vals.size else float("nan"),
        "nonsignal_tail_avg_diff": float(np.mean(nonsignal_vals)) if nonsignal_vals.size else float("nan"),
        "delta": float(np.mean(signal_vals) - np.mean(nonsignal_vals)) if signal_vals.size and nonsignal_vals.size else float("nan"),
    }


def _pair_counts(other_df: pd.DataFrame, flag_column: str) -> dict[str, int]:
    pair_flags = other_df.loc[:, ["date", "last_digit", flag_column]].drop_duplicates()
    return {
        "signal_pairs": int(pair_flags[flag_column].sum()),
        "nonsignal_pairs": int((~pair_flags[flag_column]).sum()),
    }


def build_summary_payload(
    *,
    signal_machines: list[str],
    diff_threshold: float,
    rb_threshold: float,
    diff_stats: dict[str, float],
    rb_stats: dict[str, float],
    any_stats: dict[str, float],
    pair_counts_any: dict[str, int],
    fake_check: dict[str, float],
) -> dict[str, Any]:
    return {
        "signal_machines": signal_machines,
        "signal_condition": {
            "diff_threshold": float(diff_threshold),
            "rb_threshold": float(rb_threshold),
            "rb_direction": ">",
        },
        "pair_counts": pair_counts_any,
        "diff_signal_only": diff_stats,
        "rb_signal_only": rb_stats,
        "signal_or": any_stats,
        "fake_tail_check": fake_check,
    }


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(args.log_level)

    conn = sqlite3.connect(str(args.db_path), check_same_thread=False)
    try:
        signal_machines = fetch_signal_machine_names(conn)
        if not signal_machines:
            raise ValueError("No signal machines matched the DB.")
        signal_rows = fetch_signal_rows(conn, signal_machines)
        other_df = fetch_other_rows(conn, signal_machines)
    finally:
        conn.close()

    signal_rows = attach_signal_flags(signal_rows, diff_threshold=float(args.diff_threshold), rb_threshold=float(args.rb_threshold))
    diff_pairs = extract_signal_pairs(signal_rows, "signal_diff")
    rb_pairs = extract_signal_pairs(signal_rows, "signal_rb")
    any_pairs = extract_signal_pairs(signal_rows, "signal")

    other_df = mark_signal_membership(other_df, diff_pairs, "in_signal_diff")
    other_df = mark_signal_membership(other_df, rb_pairs, "in_signal_rb")
    other_df = mark_signal_membership(other_df, any_pairs, "in_signal")

    diff_stats = compute_group_comparison(other_df, "in_signal_diff")
    rb_stats = compute_group_comparison(other_df, "in_signal_rb")
    any_stats = compute_group_comparison(other_df, "in_signal")
    weekday_stats = build_weekday_stats(other_df, "in_signal")
    fake_check = build_fake_tail_check(other_df, "in_signal")
    pair_counts_any = _pair_counts(other_df, "in_signal")

    payload = build_summary_payload(
        signal_machines=signal_machines,
        diff_threshold=float(args.diff_threshold),
        rb_threshold=float(args.rb_threshold),
        diff_stats=diff_stats,
        rb_stats=rb_stats,
        any_stats=any_stats,
        pair_counts_any=pair_counts_any,
        fake_check=fake_check,
    )

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    signal_rows.to_csv(out_dir / "signal_machine_rows.csv", index=False, encoding="utf-8")
    weekday_stats.to_csv(out_dir / "signal_machine_weekday_stats.csv", index=False, encoding="utf-8")
    (out_dir / "signal_machine_correlation_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.info("Wrote signal machine rows: %s", out_dir / "signal_machine_rows.csv")
    logger.info("Wrote signal machine weekday stats: %s", out_dir / "signal_machine_weekday_stats.csv")
    logger.info("Wrote signal machine summary JSON: %s", out_dir / "signal_machine_correlation_summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
