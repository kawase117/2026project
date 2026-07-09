from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DB_PATH = PROJECT_ROOT / "db" / "楽園蒲田店.db"
COORD_PATH = PROJECT_ROOT / "Heatmap" / "shinkan2F_floor_coordinates_rakuen.csv"
OUTPUT_DIR = SCRIPT_DIR / "results" / "rakuen_2004_2007"
TARGET_MACHINES = (2004, 2005, 2006, 2007)
EVENT_DDS = frozenset({1, 4, 7, 14, 17, 24, 27, 30})
HIT_THRESHOLD = 106.0
DOW_LABELS = ["月", "火", "水", "木", "金", "土", "日"]


def _format_cell(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.1f}"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    return str(value)


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "No rows."
    work = frame.copy()
    headers = [str(col) for col in work.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for _, row in work.iterrows():
        lines.append("| " + " | ".join(_format_cell(row[col]) for col in work.columns) + " |")
    return "\n".join(lines)


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fetch_machine_frame(machine_numbers: list[int] | tuple[int, ...]) -> pd.DataFrame:
    if not machine_numbers:
        return pd.DataFrame(
            columns=[
                "date",
                "machine_name",
                "machine_number",
                "games_normalized",
                "diff_coins_normalized",
            ]
        )

    placeholders = ",".join(["?"] * len(machine_numbers))
    query = f"""
        SELECT date, machine_name, machine_number, games_normalized, diff_coins_normalized
        FROM machine_detailed_results
        WHERE machine_number IN ({placeholders})
    """
    with sqlite3.connect(DB_PATH) as conn:
        frame = pd.read_sql_query(query, conn, params=list(machine_numbers))
    return frame


def _prepare_frame(raw: pd.DataFrame) -> pd.DataFrame:
    frame = raw.copy()
    frame["date"] = frame["date"].astype(str)
    frame["date_dt"] = pd.to_datetime(frame["date"], format="%Y%m%d", errors="coerce")
    frame["machine_number"] = pd.to_numeric(frame["machine_number"], errors="coerce")
    frame["games_normalized"] = pd.to_numeric(frame["games_normalized"], errors="coerce")
    frame["diff_coins_normalized"] = pd.to_numeric(frame["diff_coins_normalized"], errors="coerce")
    frame = frame.dropna(
        subset=["date_dt", "machine_number", "machine_name", "games_normalized", "diff_coins_normalized"]
    ).copy()
    frame["machine_number"] = frame["machine_number"].astype(int)
    frame["games_normalized"] = frame["games_normalized"].astype(int)
    frame["diff_coins_normalized"] = frame["diff_coins_normalized"].astype(int)
    frame["dd"] = frame["date_dt"].dt.day.astype(int)
    frame["dow"] = frame["date_dt"].dt.dayofweek.astype(int)
    frame["dow_label"] = frame["dow"].map(dict(enumerate(DOW_LABELS)))
    frame["year_month"] = frame["date_dt"].dt.strftime("%Y%m")
    return frame


def _add_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work = work[work["games_normalized"] > 0].copy()
    if work.empty:
        work["payout_rate"] = pd.Series(dtype="float64")
        work["win_flag"] = pd.Series(dtype="float64")
        work["hit_flag"] = pd.Series(dtype="float64")
        return work
    work["payout_rate"] = (
        (work["games_normalized"] * 3 + work["diff_coins_normalized"]) / (work["games_normalized"] * 3)
    ) * 100
    work["win_flag"] = (work["diff_coins_normalized"] > 0).astype(int)
    work["hit_flag"] = (work["payout_rate"] >= HIT_THRESHOLD).astype(int)
    work["is_event_dd"] = work["dd"].isin(EVENT_DDS)
    return work


def _scope_tables(
    raw_scope: pd.DataFrame, filtered_scope: pd.DataFrame, scope_name: str
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dd_days = raw_scope.groupby("dd")["date"].nunique().reset_index(name="n_days")
    dd_metric = (
        filtered_scope.groupby("dd")
        .agg(
            avg_games=("games_normalized", "mean"),
            avg_diff=("diff_coins_normalized", "mean"),
            win_rate=("win_flag", "mean"),
            hit_rate=("hit_flag", "mean"),
            avg_payout_rate=("payout_rate", "mean"),
        )
        .reset_index()
    )
    for col in ["avg_games", "avg_diff", "avg_payout_rate"]:
        dd_metric[col] = dd_metric[col].round(1)
    for col in ["win_rate", "hit_rate"]:
        dd_metric[col] = (dd_metric[col] * 100).round(1)
    dd_table = dd_days.merge(dd_metric, on="dd", how="left")
    dd_table["is_event_dd"] = dd_table["dd"].isin(EVENT_DDS)
    dd_table.insert(0, "scope", scope_name)
    dd_table = dd_table[
        ["scope", "dd", "is_event_dd", "n_days", "avg_games", "avg_diff", "win_rate", "hit_rate", "avg_payout_rate"]
    ]
    dd_table = dd_table[dd_table["n_days"] > 0].sort_values("dd").reset_index(drop=True)

    dow_days = raw_scope.groupby(["dow", "dow_label"])["date"].nunique().reset_index(name="n_days")
    dow_metric = (
        filtered_scope.groupby(["dow", "dow_label"])
        .agg(
            avg_games=("games_normalized", "mean"),
            avg_diff=("diff_coins_normalized", "mean"),
            win_rate=("win_flag", "mean"),
            hit_rate=("hit_flag", "mean"),
            avg_payout_rate=("payout_rate", "mean"),
        )
        .reset_index()
    )
    for col in ["avg_games", "avg_diff", "avg_payout_rate"]:
        dow_metric[col] = dow_metric[col].round(1)
    for col in ["win_rate", "hit_rate"]:
        dow_metric[col] = (dow_metric[col] * 100).round(1)
    dow_table = dow_days.merge(dow_metric, on=["dow", "dow_label"], how="left")
    dow_table.insert(0, "scope", scope_name)
    dow_table = dow_table[
        ["scope", "dow", "dow_label", "n_days", "avg_games", "avg_diff", "win_rate", "hit_rate", "avg_payout_rate"]
    ]
    dow_table = dow_table[dow_table["n_days"] > 0].sort_values("dow").reset_index(drop=True)

    monthly_days = raw_scope.groupby("year_month")["date"].nunique().reset_index(name="n_days")
    monthly_metric = (
        filtered_scope.groupby("year_month")
        .agg(
            avg_games=("games_normalized", "mean"),
            avg_diff=("diff_coins_normalized", "mean"),
            win_rate=("win_flag", "mean"),
            hit_rate=("hit_flag", "mean"),
            avg_payout_rate=("payout_rate", "mean"),
        )
        .reset_index()
    )
    for col in ["avg_games", "avg_diff", "avg_payout_rate"]:
        monthly_metric[col] = monthly_metric[col].round(1)
    for col in ["win_rate", "hit_rate"]:
        monthly_metric[col] = (monthly_metric[col] * 100).round(1)
    primary = (
        raw_scope.groupby(["year_month", "machine_name"], as_index=False)
        .agg(
            n_days=("date", "nunique"),
            first_date=("date_dt", "min"),
        )
        .sort_values(["year_month", "n_days", "first_date", "machine_name"], ascending=[True, False, True, True])
        .drop_duplicates(subset=["year_month"], keep="first")
        .loc[:, ["year_month", "machine_name"]]
        .rename(columns={"machine_name": "machine_name_primary"})
    )
    monthly_table = monthly_days.merge(monthly_metric, on="year_month", how="left").merge(
        primary, on="year_month", how="left"
    )
    monthly_table.insert(0, "scope", scope_name)
    monthly_table = monthly_table[
        [
            "scope",
            "year_month",
            "machine_name_primary",
            "n_days",
            "avg_games",
            "avg_diff",
            "win_rate",
            "hit_rate",
            "avg_payout_rate",
        ]
    ]
    monthly_table = monthly_table[monthly_table["n_days"] > 0].sort_values("year_month").reset_index(drop=True)

    return dd_table, dow_table, monthly_table


def _scope_summary(raw_scope: pd.DataFrame, filtered_scope: pd.DataFrame, scope_name: str) -> pd.DataFrame:
    row = {
        "scope": scope_name,
        "total_days": int(raw_scope["date"].nunique()),
        "avg_games": round(float(filtered_scope["games_normalized"].mean()), 1) if not filtered_scope.empty else np.nan,
        "avg_diff": round(float(filtered_scope["diff_coins_normalized"].mean()), 1)
        if not filtered_scope.empty
        else np.nan,
        "win_rate": round(float(filtered_scope["win_flag"].mean() * 100), 1) if not filtered_scope.empty else np.nan,
        "hit_rate": round(float(filtered_scope["hit_flag"].mean() * 100), 1) if not filtered_scope.empty else np.nan,
    }
    return pd.DataFrame([row])


def _machine_summary(raw: pd.DataFrame, filtered: pd.DataFrame, machine_numbers: list[int]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for machine_number in machine_numbers:
        raw_machine = raw[raw["machine_number"] == machine_number]
        filtered_machine = filtered[filtered["machine_number"] == machine_number]
        rows.append(
            {
                "machine_number": machine_number,
                "total_days": int(raw_machine["date"].nunique()),
                "avg_games": round(float(filtered_machine["games_normalized"].mean()), 1)
                if not filtered_machine.empty
                else np.nan,
                "avg_diff": round(float(filtered_machine["diff_coins_normalized"].mean()), 1)
                if not filtered_machine.empty
                else np.nan,
                "win_rate": round(float(filtered_machine["win_flag"].mean() * 100), 1)
                if not filtered_machine.empty
                else np.nan,
                "hit_rate": round(float(filtered_machine["hit_flag"].mean() * 100), 1)
                if not filtered_machine.empty
                else np.nan,
            }
        )
    table = pd.DataFrame(rows)
    return table.sort_values("machine_number").reset_index(drop=True)


def _comparison_table(
    raw_all: pd.DataFrame, filtered_all: pd.DataFrame, all_machine_numbers: list[int]
) -> pd.DataFrame:
    target = set(TARGET_MACHINES)
    existing = [
        machine_number
        for machine_number in all_machine_numbers
        if machine_number in set(raw_all["machine_number"].unique())
    ]
    groups = {
        "2004-2007": [machine_number for machine_number in existing if machine_number in target],
        "shinkan2F_other": [machine_number for machine_number in existing if machine_number not in target],
        "shinkan2F_all": existing,
    }
    rows: list[dict[str, object]] = []
    for group_name, machines in groups.items():
        raw_group = raw_all[raw_all["machine_number"].isin(machines)]
        filtered_group = filtered_all[filtered_all["machine_number"].isin(machines)]
        rows.append(
            {
                "group": group_name,
                "n_machines": int(pd.Index(raw_group["machine_number"].unique()).size),
                "n_days": int(raw_group["date"].nunique()),
                "avg_games": round(float(filtered_group["games_normalized"].mean()), 1)
                if not filtered_group.empty
                else np.nan,
                "avg_diff": round(float(filtered_group["diff_coins_normalized"].mean()), 1)
                if not filtered_group.empty
                else np.nan,
                "win_rate": round(float(filtered_group["win_flag"].mean() * 100), 1)
                if not filtered_group.empty
                else np.nan,
                "hit_rate": round(float(filtered_group["hit_flag"].mean() * 100), 1)
                if not filtered_group.empty
                else np.nan,
                "avg_payout_rate": round(float(filtered_group["payout_rate"].mean()), 1)
                if not filtered_group.empty
                else np.nan,
            }
        )
    table = pd.DataFrame(rows)
    return table[["group", "n_machines", "n_days", "avg_games", "avg_diff", "win_rate", "hit_rate", "avg_payout_rate"]]


def _format_table_for_report(df: pd.DataFrame, *, columns: list[str] | None = None) -> str:
    work = df.copy()
    if columns is not None:
        work = work.loc[:, columns]
    return _markdown_table(work)


def _top_bottom_dd(dd_section: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if dd_section.empty:
        empty = pd.DataFrame(columns=dd_section.columns)
        return empty, empty
    top = (
        dd_section.sort_values(["hit_rate", "avg_diff", "dd"], ascending=[False, False, True])
        .head(5)
        .reset_index(drop=True)
    )
    bottom = (
        dd_section.sort_values(["hit_rate", "avg_diff", "dd"], ascending=[True, True, True])
        .head(5)
        .reset_index(drop=True)
    )
    return top, bottom


def _event_comparison(dd_section: pd.DataFrame, raw_scope: pd.DataFrame, filtered_scope: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for label, flag in [("event", True), ("non_event", False)]:
        raw_part = raw_scope[raw_scope["dd"].isin(EVENT_DDS)] if flag else raw_scope[~raw_scope["dd"].isin(EVENT_DDS)]
        filtered_part = (
            filtered_scope[filtered_scope["dd"].isin(EVENT_DDS)]
            if flag
            else filtered_scope[~filtered_scope["dd"].isin(EVENT_DDS)]
        )
        rows.append(
            {
                "type": label,
                "n_days": int(raw_part["date"].nunique()),
                "avg_games": round(float(filtered_part["games_normalized"].mean()), 1)
                if not filtered_part.empty
                else np.nan,
                "avg_diff": round(float(filtered_part["diff_coins_normalized"].mean()), 1)
                if not filtered_part.empty
                else np.nan,
                "win_rate": round(float(filtered_part["win_flag"].mean() * 100), 1)
                if not filtered_part.empty
                else np.nan,
                "hit_rate": round(float(filtered_part["hit_flag"].mean() * 100), 1)
                if not filtered_part.empty
                else np.nan,
                "avg_payout_rate": round(float(filtered_part["payout_rate"].mean()), 1)
                if not filtered_part.empty
                else np.nan,
            }
        )
    return pd.DataFrame(rows)


def _trend_label(monthly_section: pd.DataFrame) -> str:
    if monthly_section.empty or monthly_section["avg_payout_rate"].dropna().size < 2:
        return "判定保留"
    values = monthly_section["avg_payout_rate"].dropna().to_list()
    first = float(np.mean(values[: max(1, min(3, len(values)))]))
    last = float(np.mean(values[-max(1, min(3, len(values))) :]))
    delta = last - first
    if delta >= 1.0:
        return "改善傾向"
    if delta <= -1.0:
        return "悪化傾向"
    return "概ね安定"


def _build_report(
    section_summary: pd.DataFrame,
    machine_summary: pd.DataFrame,
    dd_section: pd.DataFrame,
    dow_section: pd.DataFrame,
    monthly_section: pd.DataFrame,
    event_compare: pd.DataFrame,
    machine_dd_tables: dict[int, pd.DataFrame],
    machine_dow_tables: dict[int, pd.DataFrame],
    comparison: pd.DataFrame,
) -> str:
    top_dd, bottom_dd = _top_bottom_dd(dd_section)
    trend = _trend_label(monthly_section)
    summary = section_summary.iloc[0]
    lines: list[str] = []
    lines.append("# 楽園蒲田店 2004-2007 セクション深掘り分析")
    lines.append("")
    lines.append("## 1. 概要")
    lines.append(f"- 対象: 新館2F 台番号 2004-2007（4台）")
    lines.append(f"- 期間: 2025-01-01 〜 2026-06-28（542日）")
    lines.append(
        f"- 全期間平均: G数={summary['avg_games']:.1f}, 差枚={summary['avg_diff']:.1f}, "
        f"勝率={summary['win_rate']:.1f}%, hit_rate={summary['hit_rate']:.1f}%"
    )
    lines.append(f"- 月次トレンド判定: {trend}")
    lines.append("")

    lines.append("## 2. DD別分析（セクション全体）")
    lines.append(_format_table_for_report(dd_section))
    lines.append("")
    lines.append("- 強いDD Top5")
    lines.append(_format_table_for_report(top_dd))
    lines.append("")
    lines.append("- 弱いDD Top5")
    lines.append(_format_table_for_report(bottom_dd))
    lines.append("")
    lines.append("- イベントDD vs 非イベントDD")
    lines.append(_format_table_for_report(event_compare))
    lines.append("")

    lines.append("## 3. 曜日別分析（セクション全体）")
    lines.append(_format_table_for_report(dow_section))
    lines.append("")

    lines.append("## 4. 月別推移（セクション全体）")
    lines.append(_format_table_for_report(monthly_section))
    lines.append("")

    lines.append("## 5. 台番号別比較")
    lines.append(_format_table_for_report(machine_summary))
    lines.append("")

    lines.append("## 6. 台番号別 DD分析")
    for machine_number in TARGET_MACHINES:
        lines.append(f"### {machine_number}")
        lines.append(_format_table_for_report(machine_dd_tables[machine_number]))
        lines.append("")

    lines.append("## 7. 台番号別 曜日分析")
    for machine_number in TARGET_MACHINES:
        lines.append(f"### {machine_number}")
        lines.append(_format_table_for_report(machine_dow_tables[machine_number]))
        lines.append("")

    lines.append("## 8. 新館2F 全体との比較")
    lines.append(_format_table_for_report(comparison))
    lines.append("")
    lines.append("## 9. 結論")
    if not dd_section.empty:
        best_dd = dd_section.sort_values(["hit_rate", "avg_diff", "dd"], ascending=[False, False, True]).iloc[0]
        worst_dd = dd_section.sort_values(["hit_rate", "avg_diff", "dd"], ascending=[True, True, True]).iloc[0]
        lines.append(f"- 最強DDは {int(best_dd['dd'])}、最弱DDは {int(worst_dd['dd'])}。")
    if not dow_section.empty:
        best_dow = dow_section.sort_values(["hit_rate", "avg_diff", "dow"], ascending=[False, False, True]).iloc[0]
        worst_dow = dow_section.sort_values(["hit_rate", "avg_diff", "dow"], ascending=[True, True, True]).iloc[0]
        lines.append(f"- 最強曜日は {best_dow['dow_label']}、最弱曜日は {worst_dow['dow_label']}。")
    if not comparison.empty:
        section_row = comparison[comparison["group"] == "2004-2007"].iloc[0]
        other_row = comparison[comparison["group"] == "shinkan2F_other"].iloc[0]
        lines.append(
            f"- 2004-2007 の hit_rate は {section_row['hit_rate']:.1f}%、新館2F その他は {other_row['hit_rate']:.1f}%。"
        )
    lines.append("- DD×曜日と機種変遷を合わせると、強さはセクション固有というより期間依存の可能性が高い。")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="楽園蒲田店 2004-2007 セクション深掘り分析")
    parser.parse_args()

    coords = pd.read_csv(COORD_PATH, encoding="utf-8-sig")
    coords["machine_number"] = pd.to_numeric(coords["machine_number"], errors="coerce")
    coords = coords.dropna(subset=["machine_number"]).copy()
    coords["machine_number"] = coords["machine_number"].astype(int)
    all_machine_numbers = coords["machine_number"].drop_duplicates().tolist()

    raw_all = _prepare_frame(_fetch_machine_frame(all_machine_numbers))
    raw_target_all = raw_all[raw_all["machine_number"].isin(TARGET_MACHINES)].copy()
    filtered_target = _add_metrics(raw_target_all)

    section_summary = _scope_summary(raw_target_all, filtered_target, "section")
    dd_section, dow_section, monthly_section = _scope_tables(raw_target_all, filtered_target, "section")
    event_compare = _event_comparison(dd_section, raw_target_all, filtered_target)
    machine_summary = _machine_summary(raw_target_all, filtered_target, list(TARGET_MACHINES))

    machine_dd_tables: dict[int, pd.DataFrame] = {}
    machine_dow_tables: dict[int, pd.DataFrame] = {}
    dd_rows: list[pd.DataFrame] = []
    dow_rows: list[pd.DataFrame] = []
    monthly_rows: list[pd.DataFrame] = []

    for machine_number in TARGET_MACHINES:
        raw_machine = raw_target_all[raw_target_all["machine_number"] == machine_number].copy()
        filtered_machine = filtered_target[filtered_target["machine_number"] == machine_number].copy()
        dd_table, dow_table, monthly_table = _scope_tables(raw_machine, filtered_machine, str(machine_number))
        machine_dd_tables[machine_number] = dd_table
        machine_dow_tables[machine_number] = dow_table
        dd_rows.append(dd_table)
        dow_rows.append(dow_table)
        monthly_rows.append(monthly_table)

    dd_analysis = pd.concat([dd_section, *dd_rows], ignore_index=True)
    dow_analysis = pd.concat([dow_section, *dow_rows], ignore_index=True)
    monthly_analysis = pd.concat([monthly_section, *monthly_rows], ignore_index=True)

    comparison = _comparison_table(raw_all, _add_metrics(raw_all), all_machine_numbers)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_csv(dd_analysis, OUTPUT_DIR / "dd_analysis.csv")
    _write_csv(dow_analysis, OUTPUT_DIR / "dow_analysis.csv")
    _write_csv(monthly_analysis, OUTPUT_DIR / "monthly_analysis.csv")
    _write_csv(comparison, OUTPUT_DIR / "shinkan2f_comparison.csv")

    report = _build_report(
        section_summary=section_summary,
        machine_summary=machine_summary,
        dd_section=dd_section,
        dow_section=dow_section,
        monthly_section=monthly_section,
        event_compare=event_compare,
        machine_dd_tables=machine_dd_tables,
        machine_dow_tables=machine_dow_tables,
        comparison=comparison,
    )
    _write_text(OUTPUT_DIR / "report.md", report.rstrip() + "\n")


if __name__ == "__main__":
    main()
