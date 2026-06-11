from __future__ import annotations

import argparse
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.last_digit.utils import configure_logging

REGIME_CUTOFF = pd.Timestamp("2026-05-30")
TASK4_FIRST_HALF_START = pd.Timestamp("2026-05-01")
TASK4_FIRST_HALF_END = pd.Timestamp("2026-05-15")
TASK4_SECOND_HALF_START = pd.Timestamp("2026-05-16")
TASK4_SECOND_HALF_END = pd.Timestamp("2026-05-31")
TASK4_FOLLOW_UP_START = pd.Timestamp("2026-06-01")

FOCUS_AT_PATTERNS = (
    "東京喰種",
    "北斗",
    "モンキー",
    "ToLOVEる",
    "ミリオンゴッド",
)
OUTPUT_BASENAME = "report"


@dataclass(slots=True)
class NotebookLMSources:
    db_path: Path
    machine_day: pd.DataFrame
    hall_daily: pd.DataFrame
    db_start_date: pd.Timestamp
    db_end_date: pd.Timestamp


@dataclass(slots=True)
class NotebookLMReport:
    markdown: str
    tables: dict[str, pd.DataFrame]
    summary: dict[str, Any]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kamata7 NotebookLM DB verification runner.")
    parser.add_argument("--db-path", required=True, help="Kamata7 SQLite DB path.")
    parser.add_argument(
        "--output-dir",
        default="ml/last_digit/reports/kamata7_notebooklm_verification",
        help="Directory for markdown and CSV outputs.",
    )
    parser.add_argument("--min-games", type=int, default=1000, help="Minimum games threshold for summary rows.")
    parser.add_argument("--log-level", default="INFO")
    return parser


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _load_machine_detail_frame(conn: sqlite3.Connection) -> pd.DataFrame:
    query = """
    SELECT
      m.date,
      m.machine_name,
      m.machine_number,
      m.games_normalized,
      m.diff_coins_normalized,
      m.is_zorome,
      COALESCE(mm.jug_flag, 0) AS jug_flag,
      COALESCE(mm.hana_flag, 0) AS hana_flag,
      COALESCE(mm.oki_flag, 0) AS oki_flag,
      COALESCE(mm.bt_flag, 0) AS bt_flag
    FROM machine_detailed_results m
    LEFT JOIN machine_master mm
      ON m.machine_name = mm.machine_name_normalized
    WHERE COALESCE(m.games_normalized, 0) > 0
    ORDER BY m.date, m.machine_number
    """
    df = pd.read_sql_query(query, conn)
    if df.empty:
        raise ValueError("machine_detailed_results returned no usable rows")
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["date", "machine_name"]).copy()
    numeric_cols = [
        "machine_number",
        "games_normalized",
        "diff_coins_normalized",
        "is_zorome",
        "jug_flag",
        "hana_flag",
        "oki_flag",
        "bt_flag",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    return df.sort_values(["date", "machine_number", "machine_name"]).reset_index(drop=True)


def _load_hall_daily_frame(conn: sqlite3.Connection) -> pd.DataFrame:
    if not _table_exists(conn, "daily_hall_summary"):
        return pd.DataFrame(
            columns=[
                "date",
                "day_of_week",
                "last_digit",
                "weekday_nth",
                "is_any_event",
                "is_zorome_day",
                "avg_diff_per_machine",
                "avg_games_per_machine",
                "win_rate",
            ]
        )

    df = pd.read_sql_query(
        """
        SELECT
          date,
          day_of_week,
          last_digit,
          weekday_nth,
          COALESCE(is_any_event, 0) AS is_any_event,
          COALESCE(is_zorome, 0) AS is_zorome_day,
          avg_diff_per_machine,
          avg_games_per_machine,
          win_rate
        FROM daily_hall_summary
        ORDER BY date
        """,
        conn,
    )
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["date"]).copy()
    for col in ("last_digit", "is_any_event", "is_zorome_day"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    for col in ("avg_diff_per_machine", "avg_games_per_machine", "win_rate"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def load_sources(db_path: Path | str) -> NotebookLMSources:
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"DB not found: {path}")

    with sqlite3.connect(str(path)) as conn:
        machine_day = _load_machine_detail_frame(conn)
        hall_daily = _load_hall_daily_frame(conn)

    start_date = pd.to_datetime(machine_day["date"]).min()
    end_date = pd.to_datetime(machine_day["date"]).max()
    if pd.isna(start_date) or pd.isna(end_date):
        raise ValueError("Unable to determine DB date range")

    if not hall_daily.empty:
        hall_daily = hall_daily.sort_values("date").reset_index(drop=True)

    return NotebookLMSources(
        db_path=path,
        machine_day=machine_day.reset_index(drop=True),
        hall_daily=hall_daily.reset_index(drop=True),
        db_start_date=pd.Timestamp(start_date),
        db_end_date=pd.Timestamp(end_date),
    )


def _classify_category(frame: pd.DataFrame) -> pd.Series:
    joined_patterns = "|".join(re.escape(pattern) for pattern in FOCUS_AT_PATTERNS)
    is_jug = pd.to_numeric(frame.get("jug_flag", 0), errors="coerce").fillna(0).astype(int).eq(1)
    is_focus_at = frame["machine_name"].astype(str).str.contains(joined_patterns, regex=True, na=False)
    return pd.Series(
        np.where(is_jug, "juggler", np.where(is_focus_at, "candidate_at", "other")),
        index=frame.index,
        dtype="object",
    )


def _add_derived_columns(sources: NotebookLMSources, min_games: int) -> pd.DataFrame:
    df = sources.machine_day.copy()
    df["category"] = _classify_category(df)
    df["games_normalized"] = pd.to_numeric(df["games_normalized"], errors="coerce").fillna(0).astype(int)
    df["diff_coins_normalized"] = pd.to_numeric(df["diff_coins_normalized"], errors="coerce").fillna(0).astype(int)
    df["efficiency"] = np.divide(
        df["diff_coins_normalized"].astype(float),
        df["games_normalized"].replace(0, np.nan).astype(float),
    ).fillna(0.0)
    df["kaiwari_pct"] = 100.0 + (df["efficiency"] / 3.0) * 100.0
    df["hit104"] = (df["kaiwari_pct"] >= 104.0).astype(int)
    df["first_seen"] = df.groupby("machine_name", sort=False)["date"].transform("min")
    df["days_since_debut"] = (df["date"] - df["first_seen"]).dt.days.astype(int)
    df["debut_bucket"] = df["days_since_debut"].map(_bucket_days_since_debut)
    df["is_pre_existing"] = (df["first_seen"] == sources.db_start_date).astype(int)
    df["meets_min_games"] = (df["games_normalized"] >= int(min_games)).astype(int)

    if not sources.hall_daily.empty:
        hall = sources.hall_daily[
            ["date", "day_of_week", "last_digit", "weekday_nth", "is_any_event", "is_zorome_day"]
        ].copy()
        df = df.merge(hall, on="date", how="left")
    else:
        df["day_of_week"] = pd.NA
        df["last_digit"] = pd.NA
        df["weekday_nth"] = pd.NA
        df["is_any_event"] = 0
        df["is_zorome_day"] = 0

    for col in ("is_any_event", "is_zorome_day"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    return df[df["meets_min_games"].eq(1)].copy().reset_index(drop=True)


def _summarize_rows(
    df: pd.DataFrame,
    *,
    group_cols: list[str],
    include_machine_count: bool = True,
) -> pd.DataFrame:
    base_columns = [*group_cols, "sample_count", "avg_diff", "median_diff", "win_rate", "hit104_rate", "avg_kaiwari_pct", "avg_games"]
    if include_machine_count:
        base_columns.insert(len(group_cols) + 1, "machine_count")
    if df.empty:
        return pd.DataFrame(columns=base_columns)

    grouped = df.groupby(group_cols, dropna=False, sort=True)
    rows: list[dict[str, Any]] = []
    for keys, group in grouped:
        if not isinstance(keys, tuple):
            keys = (keys,)
        row: dict[str, Any] = {col: value for col, value in zip(group_cols, keys, strict=False)}
        row["sample_count"] = int(len(group))
        if include_machine_count:
            row["machine_count"] = int(group["machine_name"].nunique())
        diff = pd.to_numeric(group["diff_coins_normalized"], errors="coerce")
        row["avg_diff"] = float(diff.mean())
        row["median_diff"] = float(diff.median())
        row["win_rate"] = float((diff > 0).mean())
        row["hit104_rate"] = float(pd.to_numeric(group["hit104"], errors="coerce").mean())
        row["avg_kaiwari_pct"] = float(pd.to_numeric(group["kaiwari_pct"], errors="coerce").mean())
        row["avg_games"] = float(pd.to_numeric(group["games_normalized"], errors="coerce").mean())
        rows.append(row)

    out = pd.DataFrame(rows)
    sort_cols = [col for col in ("sample_count", "avg_diff") if col in out.columns]
    if sort_cols:
        ascending = [False] * len(sort_cols)
        out = out.sort_values(sort_cols, ascending=ascending)
    return out.reset_index(drop=True)


def _bucket_days_since_debut(days: int) -> str:
    if days < 0:
        return "pre_debut"
    if days <= 2:
        return "0-2"
    if days <= 6:
        return "3-6"
    if days <= 13:
        return "7-13"
    if days <= 29:
        return "14-29"
    return "30+"


def _format_value(value: Any) -> str:
    if value is None or value is pd.NA:
        return ""
    if isinstance(value, float):
        if np.isnan(value):
            return ""
        return f"{value:.3f}"
    if isinstance(value, (np.integer, int)):
        return str(int(value))
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _table_to_markdown(df: pd.DataFrame, *, max_rows: int = 10) -> str:
    if df.empty:
        return "_no rows_\n"
    view = df.head(max_rows).copy()
    headers = list(view.columns)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for _, row in view.iterrows():
        lines.append("| " + " | ".join(_format_value(row[col]) for col in headers) + " |")
    return "\n".join(lines) + "\n"


def _task_1_regime_summary(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = df.copy()
    work["period"] = np.where(work["date"] < REGIME_CUTOFF, "pre_2026-05-30", "post_2026-05-30")
    period_summary = _summarize_rows(work, group_cols=["period", "category"])
    daily_summary = _summarize_rows(work, group_cols=["date", "category"])
    return period_summary, daily_summary


def _task_2_debut_summary(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["debut_scope"] = np.where(work["is_pre_existing"] == 1, "pre_existing", "new_or_late")
    return _summarize_rows(work, group_cols=["debut_scope", "debut_bucket"])


def _task_3_variance_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for machine_name, group in df.groupby("machine_name", sort=True):
        diff = pd.to_numeric(group["diff_coins_normalized"], errors="coerce")
        games = pd.to_numeric(group["games_normalized"], errors="coerce")
        kaiwari = pd.to_numeric(group["kaiwari_pct"], errors="coerce")
        rows.append(
            {
                "machine_name": machine_name,
                "category": group["category"].iloc[0],
                "sample_count": int(len(group)),
                "days": int(group["date"].nunique()),
                "avg_diff": float(diff.mean()),
                "median_diff": float(diff.median()),
                "std_diff": float(diff.std(ddof=0)) if len(diff) else 0.0,
                "min_diff": float(diff.min()),
                "max_diff": float(diff.max()),
                "win_rate": float((diff > 0).mean()),
                "hit104_rate": float(pd.to_numeric(group["hit104"], errors="coerce").mean()),
                "avg_kaiwari_pct": float(kaiwari.mean()),
                "avg_games": float(games.mean()),
                "total_diff": float(diff.sum()),
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["abs_mean_gap"] = out["avg_diff"].abs()
    out["variance_to_mean_ratio"] = np.divide(out["std_diff"], out["abs_mean_gap"] + 1.0)
    return out.sort_values(["std_diff", "sample_count"], ascending=[False, False]).reset_index(drop=True)


def _task_4_reproducibility_summary(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = df.copy()
    periods = [
        ("2026-05-early", TASK4_FIRST_HALF_START, TASK4_FIRST_HALF_END),
        ("2026-05-late", TASK4_SECOND_HALF_START, TASK4_SECOND_HALF_END),
        ("2026-06-early", TASK4_FOLLOW_UP_START, work["date"].max()),
    ]
    rows: list[pd.DataFrame] = []
    for period_name, start, end in periods:
        period_df = work[(work["date"] >= start) & (work["date"] <= end)].copy()
        if period_df.empty:
            continue
        period_df["period"] = period_name
        rows.append(period_df)
    if not rows:
        return pd.DataFrame(), pd.DataFrame()

    period_work = pd.concat(rows, ignore_index=True)
    machine_summary = _summarize_rows(period_work, group_cols=["period", "machine_name", "category"])
    category_summary = _summarize_rows(period_work, group_cols=["period", "category"])
    return machine_summary, category_summary


def build_report(*, sources: NotebookLMSources, min_games: int = 1000) -> NotebookLMReport:
    df = _add_derived_columns(sources, min_games=min_games)
    task1_period, task1_daily = _task_1_regime_summary(df)
    task2_debut = _task_2_debut_summary(df)
    task3_variance = _task_3_variance_summary(df)
    task4_machine, task4_category = _task_4_reproducibility_summary(df)

    tables: dict[str, pd.DataFrame] = {
        "task1_period_summary": task1_period,
        "task1_daily_summary": task1_daily,
        "task2_debut_buckets": task2_debut,
        "task3_variance_summary": task3_variance,
        "task4_machine_period_summary": task4_machine,
        "task4_category_period_summary": task4_category,
    }
    summary = {
        "db_path": str(sources.db_path),
        "db_start_date": sources.db_start_date.strftime("%Y-%m-%d"),
        "db_end_date": sources.db_end_date.strftime("%Y-%m-%d"),
        "rows_used": int(len(df)),
        "min_games": int(min_games),
    }
    return NotebookLMReport(markdown=_render_markdown(summary, tables), tables=tables, summary=summary)


def _render_markdown(summary: dict[str, Any], tables: dict[str, pd.DataFrame]) -> str:
    lines = [
        "# Kamata7 NotebookLM DB Verification",
        "",
        f"- DB: `{summary['db_path']}`",
        f"- Date range: `{summary['db_start_date']}` to `{summary['db_end_date']}`",
        f"- Rows used: `{summary['rows_used']}`",
        f"- Minimum games filter: `{summary['min_games']}`",
        "",
        "## Task 1. 2026-05-30 前後の配分変化の検証",
        "",
        _table_to_markdown(tables["task1_period_summary"]),
        "### 日別比較",
        "",
        _table_to_markdown(tables["task1_daily_summary"]),
        "## Task 2. 新台導入後の初動パターン検証",
        "",
        _table_to_markdown(tables["task2_debut_buckets"]),
        "## Task 3. 機種ごとのばらつき検証",
        "",
        _table_to_markdown(tables["task3_variance_summary"]),
        "## Task 4. 5月後半から6月初旬への持続性チェック",
        "",
        "### 機種別",
        "",
        _table_to_markdown(tables["task4_machine_period_summary"]),
        "### カテゴリ別",
        "",
        _table_to_markdown(tables["task4_category_period_summary"]),
    ]
    return "\n".join(lines).strip() + "\n"


def _write_outputs(report: NotebookLMReport, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{OUTPUT_BASENAME}.md").write_text(report.markdown, encoding="utf-8")
    for name, table in report.tables.items():
        table.to_csv(output_dir / f"{name}.csv", index=False, encoding="utf-8-sig")
    (output_dir / f"{OUTPUT_BASENAME}.json").write_text(
        json.dumps(report.summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.log_level)
    sources = load_sources(args.db_path)
    report = build_report(sources=sources, min_games=int(args.min_games))
    output_dir = Path(args.output_dir)
    _write_outputs(report, output_dir)
    print(output_dir / f"{OUTPUT_BASENAME}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
