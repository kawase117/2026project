from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from ml.last_digit.utils import configure_logging


logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze Sunday machine-count strategy using daily machine summaries.")
    parser.add_argument("--db-path", required=True, help="SQLite DB path.")
    parser.add_argument(
        "--output-dir",
        default="db/experiments/sunday_machine_analysis",
        help="Directory for CSV/JSON outputs.",
    )
    parser.add_argument("--min-days", type=int, default=10, help="Minimum Sunday observations required per machine.")
    parser.add_argument("--log-level", default="INFO", help="Logging level.")
    return parser


def fetch_sunday_machine_days(db_path: str | Path) -> pd.DataFrame:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    try:
        df = pd.read_sql(
            """
            SELECT
                m.machine_name,
                m.machine_count,
                m.avg_diff_coins,
                m.win_rate,
                m.high_profit_rate,
                m.total_games
            FROM daily_machine_type_summary m
            JOIN daily_hall_summary d ON m.date = d.date
            WHERE d.day_of_week = '日'
              AND m.machine_count > 1
            """,
            conn,
        )
    finally:
        conn.close()
    return df


def _first_non_null(series: pd.Series) -> float:
    non_null = series.dropna()
    if non_null.empty:
        return float("nan")
    return float(non_null.iloc[0])


def build_machine_stats(df_sunday: pd.DataFrame, min_days: int) -> pd.DataFrame:
    if df_sunday.empty:
        return pd.DataFrame(
            columns=[
                "machine_name",
                "num_machines",
                "avg_diff",
                "std_diff",
                "n_days",
                "avg_win_rate",
                "avg_high_profit_rate",
                "avg_total_games",
                "machine_count_category",
            ]
        )
    stats = (
        df_sunday.groupby("machine_name", as_index=False)
        .agg(
            num_machines=("machine_count", _first_non_null),
            avg_diff=("avg_diff_coins", "mean"),
            std_diff=("avg_diff_coins", "std"),
            n_days=("avg_diff_coins", "count"),
            avg_win_rate=("win_rate", "mean"),
            avg_high_profit_rate=("high_profit_rate", "mean"),
            avg_total_games=("total_games", "mean"),
        )
    )
    stats["num_machines"] = pd.to_numeric(stats["num_machines"], errors="coerce")
    stats = stats[stats["n_days"] >= int(min_days)].copy()
    stats["machine_count_category"] = stats["num_machines"].apply(categorize_machine_count)
    return stats.sort_values(["avg_diff", "machine_name"], ascending=[False, True]).reset_index(drop=True)


def categorize_machine_count(count: float | int) -> str:
    value = int(count)
    if 2 <= value <= 5:
        return "2-5台"
    if 6 <= value <= 15:
        return "6-15台"
    if 16 <= value <= 50:
        return "16-50台"
    return "50台超"


def build_category_summary(stats: pd.DataFrame) -> pd.DataFrame:
    if stats.empty:
        return pd.DataFrame(columns=["category", "machine_types", "avg_diff", "win_rate", "high_profit_rate"])
    category_order = ["2-5台", "6-15台", "16-50台", "50台超"]
    summary = (
        stats.groupby("machine_count_category", as_index=False)
        .agg(
            machine_types=("machine_name", "count"),
            avg_diff=("avg_diff", "mean"),
            win_rate=("avg_win_rate", "mean"),
            high_profit_rate=("avg_high_profit_rate", "mean"),
        )
        .rename(columns={"machine_count_category": "category"})
    )
    summary["sort_key"] = summary["category"].map({label: i for i, label in enumerate(category_order)})
    summary = summary.sort_values("sort_key").drop(columns=["sort_key"]).reset_index(drop=True)
    return summary


def compute_spearman(stats: pd.DataFrame) -> dict[str, float]:
    if stats.empty or stats["num_machines"].nunique() < 2:
        return {"rho": float("nan"), "p_value": float("nan")}
    rho, p_value = spearmanr(stats["num_machines"], stats["avg_diff"], nan_policy="omit")
    return {"rho": float(rho), "p_value": float(p_value)}


def build_summary_payload(
    *,
    machine_stats: pd.DataFrame,
    category_summary: pd.DataFrame,
    spearman: dict[str, float],
    min_days: int,
) -> dict[str, Any]:
    top_columns = ["machine_name", "num_machines", "avg_diff", "avg_win_rate", "n_days"]
    top_rows = machine_stats.loc[:, top_columns].head(15).to_dict(orient="records") if not machine_stats.empty else []
    return {
        "min_days": int(min_days),
        "n_machine_types": int(len(machine_stats)),
        "category_summary": category_summary.to_dict(orient="records"),
        "spearman": spearman,
        "top_machine_types": top_rows,
    }


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(args.log_level)

    df_sunday = fetch_sunday_machine_days(args.db_path)
    machine_stats = build_machine_stats(df_sunday, min_days=int(args.min_days))
    category_summary = build_category_summary(machine_stats)
    spearman = compute_spearman(machine_stats)
    payload = build_summary_payload(
        machine_stats=machine_stats,
        category_summary=category_summary,
        spearman=spearman,
        min_days=int(args.min_days),
    )

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    machine_stats.to_csv(out_dir / "sunday_machine_analysis.csv", index=False, encoding="utf-8")
    category_summary.to_csv(out_dir / "sunday_machine_category_summary.csv", index=False, encoding="utf-8")
    (out_dir / "sunday_machine_analysis.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info("Wrote Sunday machine stats: %s", out_dir / "sunday_machine_analysis.csv")
    logger.info("Wrote Sunday machine summary JSON: %s", out_dir / "sunday_machine_analysis.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
