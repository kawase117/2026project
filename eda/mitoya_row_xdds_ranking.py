"""
Mitoya row-level X_DDS ranking.

Flow:
  join machine_layout
  -> row_key = section + "_y" + y
  -> average by row_key x date
  -> split dates into X_DDS / non_X_DDS
  -> compute lift and rank rows
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

DB_PATH = Path(__file__).resolve().parents[1] / "db" / "みとや大森町店.db"
OUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "mitoya_row_xdds_ranking"
X_DDS = {4, 7, 14, 17, 24, 27}


def load_data(db_path: Path = DB_PATH) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(
            """
            SELECT
                r.date,
                r.machine_number,
                r.machine_name,
                r.diff_coins_normalized,
                r.games_normalized,
                l.section,
                l.y
            FROM machine_detailed_results AS r
            LEFT JOIN machine_layout AS l
                ON r.machine_number = l.machine_number
            """,
            conn,
        )

    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    return df


def _make_row_key(df: pd.DataFrame) -> pd.Series:
    section = df["section"].astype(str)
    y = pd.to_numeric(df["y"], errors="coerce")
    return section + "_y" + y.astype("Int64").astype(str)


def build_row_ranking(df: pd.DataFrame, min_n_xdds: int = 20) -> pd.DataFrame:
    work = df.copy()
    if "date" not in work.columns:
        raise ValueError("df must include date")
    work["date"] = pd.to_datetime(work["date"])
    if "section" not in work.columns or "y" not in work.columns:
        raise ValueError("df must include section and y from machine_layout join")

    work["row_key"] = _make_row_key(work)
    work["dd"] = work["date"].dt.day
    work["day_type"] = np.where(work["dd"].isin(X_DDS), "X_DDS", "non_X_DDS")
    denom = (work["games_normalized"] * 3).replace(0, np.nan)
    work["payout_pct"] = ((denom + work["diff_coins_normalized"]) / denom) * 100

    daily = (
        work.groupby(["row_key", "date", "day_type"], as_index=False)
        .agg(
            payout_pct=("payout_pct", "mean"),
            section=("section", "first"),
            y=("y", "first"),
            n_machines=("machine_number", "nunique"),
        )
    )

    summary = (
        daily.groupby("row_key")
        .apply(
            lambda g: pd.Series(
                {
                    "section": g["section"].iloc[0],
                    "y": int(pd.to_numeric(g["y"], errors="coerce").iloc[0]),
                    "n_dates": int(g["date"].nunique()),
                    "n_xdds": int((g["day_type"] == "X_DDS").sum()),
                    "n_non_xdds": int((g["day_type"] == "non_X_DDS").sum()),
                    "xdds_mean": float(g.loc[g["day_type"] == "X_DDS", "payout_pct"].mean()),
                    "non_xdds_mean": float(g.loc[g["day_type"] == "non_X_DDS", "payout_pct"].mean()),
                }
            )
        )
        .reset_index()
    )

    summary["lift"] = summary["xdds_mean"] - summary["non_xdds_mean"]
    summary = summary[summary["n_xdds"] >= min_n_xdds].copy()
    summary = summary.sort_values(["lift", "n_xdds", "row_key"], ascending=[False, False, True]).reset_index(drop=True)
    summary.insert(0, "rank", np.arange(1, len(summary) + 1))
    return summary


def _markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_no rows_"
    frame = df.copy()
    headers = list(frame.columns)
    rows = [headers]
    for _, row in frame.iterrows():
        rows.append([str(row[col]) for col in headers])
    widths = [max(len(str(row[i])) for row in rows) for i in range(len(headers))]
    lines = [
        "| " + " | ".join(headers[i].ljust(widths[i]) for i in range(len(headers))) + " |",
        "| " + " | ".join("-" * widths[i] for i in range(len(headers))) + " |",
    ]
    for row in rows[1:]:
        lines.append("| " + " | ".join(str(row[i]).ljust(widths[i]) for i in range(len(headers))) + " |")
    return "\n".join(lines)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = load_data()
    ranking = build_row_ranking(df, min_n_xdds=20)
    report = [
        "# Mitoya Row X_DDS Ranking",
        "",
        f"- rows: {len(ranking)}",
        f"- date range: {df['date'].min().date()} ~ {df['date'].max().date()}",
        "",
        _markdown_table(
            ranking.loc[
                :,
                [
                    "rank",
                    "row_key",
                    "section",
                    "y",
                    "n_xdds",
                    "n_non_xdds",
                    "xdds_mean",
                    "non_xdds_mean",
                    "lift",
                ],
            ].round(
                {
                    "xdds_mean": 3,
                    "non_xdds_mean": 3,
                    "lift": 3,
                }
            )
        ),
        "",
    ]
    (OUT_DIR / "row_ranking.md").write_text("\n".join(report), encoding="utf-8")
    ranking.to_csv(OUT_DIR / "row_ranking.csv", index=False, encoding="utf-8-sig")
    print(f"Wrote {OUT_DIR / 'row_ranking.md'}")


if __name__ == "__main__":
    main()
