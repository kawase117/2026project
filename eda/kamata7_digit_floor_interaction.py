"""
Kamata7: 台番号末尾(0-9) × フロア(2F/3F) interaction analysis.

Inputs:
  - eda.kamata7_dd_internal_structure._prepare_frame
  - eda.kamata7_dd_internal_structure._agg_metrics
  - eda.kamata7_dd_internal_structure._table_to_markdown

Outputs:
  - eda/reports/kamata7_digit_floor_interaction_report.md
  - eda/reports/kamata7_digit_floor_quickref.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda.kamata7_dd_internal_structure import _agg_metrics, _prepare_frame, _table_to_markdown

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


FLOOR_ORDER = ["2F", "3F"]
DIGIT_ORDER = [str(i) for i in range(10)]
WEEKDAY_ORDER = ["月", "火", "水", "木", "金", "土", "日"]
FOCUS_WEEKDAYS = ["水", "土"]

REPORT_PATH = Path(__file__).parent / "reports" / "kamata7_digit_floor_interaction_report.md"
QUICKREF_PATH = Path(__file__).parent / "reports" / "kamata7_digit_floor_quickref.csv"

MIN_MATRIX_N = 30


def _floor_from_machine_number(machine_number: object) -> str | None:
    try:
        value = int(machine_number)
    except (TypeError, ValueError):
        return None
    if 2000 <= value <= 2999:
        return "2F"
    if 3000 <= value <= 3999:
        return "3F"
    return None


def _with_floor(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["floor"] = work["machine_number"].map(_floor_from_machine_number)
    work["dd_mod10"] = pd.to_numeric(work.get("dd_mod10"), errors="coerce").astype("Int64")
    work["machine_digit"] = work["machine_digit"].astype("string")
    work["segment"] = work["segment"].astype("string")
    work["day_of_week"] = work["day_of_week"].astype("string")
    work = work.dropna(subset=["floor", "dd_mod10", "machine_digit", "segment", "day_of_week"]).copy()
    work["floor"] = pd.Categorical(work["floor"], categories=FLOOR_ORDER, ordered=True)
    work["dd_mod10"] = pd.Categorical(work["dd_mod10"].astype(int), categories=list(range(10)), ordered=True)
    work["machine_digit"] = pd.Categorical(work["machine_digit"], categories=DIGIT_ORDER, ordered=True)
    work["segment"] = pd.Categorical(work["segment"], categories=["A", "N"], ordered=True)
    work["day_of_week"] = pd.Categorical(work["day_of_week"], categories=WEEKDAY_ORDER, ordered=True)
    return work[work["floor"].notna()].copy()


def _safe_md(df: pd.DataFrame) -> str:
    return "(no data)" if df.empty else _table_to_markdown(df)


def _matrix_to_md(matrix: pd.DataFrame, index_name: str) -> str:
    if matrix.empty:
        return "(no data)"
    return _table_to_markdown(matrix.reset_index().rename(columns={"index": index_name}))


def _rank_within_group(stats: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    work = stats.copy()
    work["rank"] = np.nan
    valid = work["avg_diff"].notna()
    if valid.any():
        work.loc[valid, "rank"] = (
            work.loc[valid]
            .groupby(group_cols, observed=False)["avg_diff"]
            .rank(method="first", ascending=False)
        )
    return work


def _add_dev_columns(stats: pd.DataFrame, baseline: pd.DataFrame, category_col: str) -> pd.DataFrame:
    work = stats.copy()
    base = baseline.set_index(category_col)
    work["avg_diff_dev"] = work.apply(
        lambda r: r["avg_diff"] - base.loc[r[category_col], "avg_diff"]
        if r[category_col] in base.index and pd.notna(base.loc[r[category_col], "avg_diff"])
        else np.nan,
        axis=1,
    )
    work["plus_rate_dev"] = work.apply(
        lambda r: r["plus_rate"] - base.loc[r[category_col], "plus_rate"]
        if r[category_col] in base.index and pd.notna(base.loc[r[category_col], "plus_rate"])
        else np.nan,
        axis=1,
    )
    work["hit104_rate_dev"] = work.apply(
        lambda r: r["hit104_rate"] - base.loc[r[category_col], "hit104_rate"]
        if r[category_col] in base.index and pd.notna(base.loc[r[category_col], "hit104_rate"])
        else np.nan,
        axis=1,
    )
    return work


def _floor_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["floor", "n_machines", "n_machine_days", "n_dates", "avg_diff", "plus_rate", "hit104_rate"])

    rows = []
    for floor, group in df.groupby("floor", observed=False):
        rows.append(
            {
                "floor": floor,
                "n_machines": int(group["machine_number"].nunique()),
                "n_machine_days": int(len(group)),
                "n_dates": int(group["date"].nunique()),
                "avg_diff": round(float(group["diff"].mean()), 0),
                "plus_rate": round(float(group["plus"].mean() * 100), 1),
                "hit104_rate": round(float(group["hit104"].mean() * 100), 1),
            }
        )
    out = pd.DataFrame(rows)
    out["floor"] = pd.Categorical(out["floor"], categories=FLOOR_ORDER, ordered=True)
    return out.sort_values("floor").reset_index(drop=True)


def _floor_segment_distribution(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["floor", "segment", "n_machines", "share_pct"])
    unique = df[["floor", "machine_number", "segment"]].drop_duplicates()
    out = (
        unique.groupby(["floor", "segment"], observed=False)
        .size()
        .reset_index(name="n_machines")
    )
    totals = out.groupby("floor", observed=False)["n_machines"].transform("sum")
    out["share_pct"] = (out["n_machines"] / totals * 100).round(1)
    out["floor"] = pd.Categorical(out["floor"], categories=FLOOR_ORDER, ordered=True)
    out["segment"] = pd.Categorical(out["segment"], categories=["A", "N"], ordered=True)
    return out.sort_values(["floor", "segment"]).reset_index(drop=True)


def _tail_floor_baseline(df: pd.DataFrame) -> pd.DataFrame:
    stats = _agg_metrics(df, ["floor", "machine_digit"])
    if stats.empty:
        return pd.DataFrame(columns=["floor", "machine_digit", "n", "avg_diff", "plus_rate", "hit104_rate", "rank"])
    stats = stats.copy()
    stats["floor"] = pd.Categorical(stats["floor"], categories=FLOOR_ORDER, ordered=True)
    stats["machine_digit"] = pd.Categorical(stats["machine_digit"], categories=DIGIT_ORDER, ordered=True)
    stats = _rank_within_group(stats, ["floor"])
    return stats.sort_values(["floor", "rank", "machine_digit"]).reset_index(drop=True)


def _spearman_floor_corr(baseline: pd.DataFrame) -> pd.DataFrame:
    if baseline.empty:
        return pd.DataFrame(columns=["metric", "spearman_rho", "n_shared_digits"])

    pivot = baseline.pivot(index="machine_digit", columns="floor", values="rank").reindex(columns=FLOOR_ORDER)
    common = pivot.dropna(subset=FLOOR_ORDER, how="any")
    rho = np.nan
    n_shared = int(len(common))
    if n_shared >= 3:
        rho = float(spearmanr(common["2F"].astype(float), common["3F"].astype(float)).correlation)
    return pd.DataFrame(
        [{
            "metric": "floor_rank_spearman",
            "spearman_rho": rho,
            "n_shared_digits": n_shared,
        }]
    )


def _group_cell_matrices(
    df: pd.DataFrame,
    *,
    group_cols: list[str],
    min_n: int,
) -> pd.DataFrame:
    stats = _agg_metrics(df, group_cols + ["machine_digit"])
    if stats.empty:
        return stats
    stats = stats[stats["n"] >= min_n].copy()
    if stats.empty:
        return stats
    stats["machine_digit"] = pd.Categorical(stats["machine_digit"], categories=DIGIT_ORDER, ordered=True)
    stats = _rank_within_group(stats, group_cols)
    stats["rank"] = stats["rank"].round(0).astype("Int64")
    return stats


def _pivot_matrix(stats: pd.DataFrame, index_cols: list[str], value_col: str) -> pd.DataFrame:
    if stats.empty:
        return pd.DataFrame()
    if len(index_cols) == 1:
        matrix = stats.pivot(index=index_cols[0], columns="machine_digit", values=value_col)
    else:
        matrix = stats.pivot_table(index=index_cols, columns="machine_digit", values=value_col, aggfunc="first")
    return matrix.reindex(columns=DIGIT_ORDER)


def _tail_list(group: pd.DataFrame, top_n: int = 3, bottom_n: int = 2) -> tuple[str, str]:
    ranked = group.dropna(subset=["avg_diff"]).sort_values(["avg_diff", "machine_digit"], ascending=[False, True])
    if ranked.empty:
        return "", ""
    top = ranked.head(top_n)
    bottom = ranked.tail(bottom_n).sort_values(["avg_diff", "machine_digit"], ascending=[True, True])

    def fmt(row: pd.Series) -> str:
        diff = float(row["avg_diff"])
        sign = "+" if diff >= 0 else ""
        return f"d{row['machine_digit']}({sign}{diff:.0f})"

    return ",".join(top.apply(fmt, axis=1).tolist()), ",".join(bottom.apply(fmt, axis=1).tolist())


def _build_quickref(df: pd.DataFrame, *, min_n: int) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (floor, day_of_week, dd_mod10), group in df.groupby(["floor", "day_of_week", "dd_mod10"], observed=False):
        stats = _agg_metrics(group, ["machine_digit"])
        stats = stats[stats["n"] >= min_n].copy()
        if stats.empty:
            continue
        stats["machine_digit"] = pd.Categorical(stats["machine_digit"], categories=DIGIT_ORDER, ordered=True)
        top3, avoid2 = _tail_list(stats)
        rows.append(
            {
                "floor": floor,
                "day_of_week": day_of_week,
                "dd_mod10": int(dd_mod10),
                "n_cells": int(len(stats)),
                "top3": top3,
                "avoid2": avoid2,
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["floor"] = pd.Categorical(out["floor"], categories=FLOOR_ORDER, ordered=True)
    out["day_of_week"] = pd.Categorical(out["day_of_week"], categories=FOCUS_WEEKDAYS, ordered=True)
    out = out.sort_values(["floor", "day_of_week", "dd_mod10"]).reset_index(drop=True)
    return out


def _report_section(title: str, parts: list[str]) -> str:
    body = "\n\n".join(parts).rstrip()
    return f"## {title}\n\n{body}\n"


def run_analysis(
    *,
    report_path: Path = REPORT_PATH,
    quickref_path: Path = QUICKREF_PATH,
    min_n_matrix: int = MIN_MATRIX_N,
) -> dict[str, pd.DataFrame]:
    df = _with_floor(_prepare_frame())
    df = df[df["floor"].notna()].copy()
    df["floor"] = pd.Categorical(df["floor"], categories=FLOOR_ORDER, ordered=True)

    floor_summary = _floor_summary(df)
    floor_segment = _floor_segment_distribution(df)

    tail_baseline = _tail_floor_baseline(df)
    floor_spearman = _spearman_floor_corr(tail_baseline)

    dd_floor_tail = _group_cell_matrices(
        df,
        group_cols=["floor", "dd_mod10"],
        min_n=min_n_matrix,
    )
    wed_sat = df[df["day_of_week"].isin(FOCUS_WEEKDAYS)].copy()
    weekday_dd_tail = _group_cell_matrices(
        wed_sat,
        group_cols=["floor", "day_of_week", "dd_mod10"],
        min_n=min_n_matrix,
    )
    quickref = _build_quickref(wed_sat, min_n=min_n_matrix)

    report_parts: list[str] = []
    report_parts.append(
        "# Kamata7 台番号末尾 × フロア 交互作用レポート\n"
        f"- floor axis: 2F / 3F\n"
        f"- tail axis: machine_digit 0-9\n"
        f"- dd axis: dd_mod10 0-9\n"
        f"- weekday focus: {', '.join(FOCUS_WEEKDAYS)}\n"
        f"- matrix threshold: n >= {min_n_matrix}\n"
    )

    report_parts.append(
        _report_section(
            "Section 1: フロア別 基本統計",
            [
                "**floor summary**",
                _safe_md(floor_summary),
                "",
                "**floor × segment distribution**",
                _safe_md(floor_segment),
            ],
        )
    )

    report_parts.append(
        _report_section(
            "Section 2: フロア別 末尾ベースライン",
            [
                "**floor tail ranking**",
                _safe_md(tail_baseline[["floor", "machine_digit", "rank", "n", "avg_diff", "plus_rate", "hit104_rate"]]),
                "",
                "**floor rank Spearman**",
                _safe_md(floor_spearman),
            ],
        )
    )

    sec3_parts: list[str] = []
    for floor in FLOOR_ORDER:
        sub = dd_floor_tail[dd_floor_tail["floor"] == floor].copy()
        sec3_parts.extend(
            [
                f"### {floor}",
                "**avg_diff matrix**",
                _matrix_to_md(
                    sub.pivot(index="dd_mod10", columns="machine_digit", values="avg_diff").reindex(index=list(range(10)), columns=DIGIT_ORDER),
                    "dd_mod10",
                ),
                "",
                "**rank matrix**",
                _matrix_to_md(
                    sub.pivot(index="dd_mod10", columns="machine_digit", values="rank").reindex(index=list(range(10)), columns=DIGIT_ORDER),
                    "dd_mod10",
                ),
                "",
                "**cell detail**",
                _safe_md(sub[["dd_mod10", "machine_digit", "n", "avg_diff", "plus_rate", "hit104_rate", "rank"]]),
                "",
            ]
        )
    report_parts.append(
        _report_section(
            "Section 3: フロア × dd_mod10 × 末尾 マトリクス",
            sec3_parts,
        )
    )

    sec4_parts: list[str] = []
    for day_of_week in FOCUS_WEEKDAYS:
        sec4_parts.append(f"### {day_of_week}")
        for floor in FLOOR_ORDER:
            sub = weekday_dd_tail[(weekday_dd_tail["floor"] == floor) & (weekday_dd_tail["day_of_week"] == day_of_week)].copy()
            sec4_parts.extend(
                [
                    f"#### {floor}",
                    "**avg_diff matrix**",
                    _matrix_to_md(
                        sub.pivot(index="dd_mod10", columns="machine_digit", values="avg_diff").reindex(index=list(range(10)), columns=DIGIT_ORDER),
                        "dd_mod10",
                    ),
                    "",
                    "**rank matrix**",
                    _matrix_to_md(
                        sub.pivot(index="dd_mod10", columns="machine_digit", values="rank").reindex(index=list(range(10)), columns=DIGIT_ORDER),
                        "dd_mod10",
                    ),
                    "",
                    "**cell detail**",
                    _safe_md(sub[["dd_mod10", "machine_digit", "n", "avg_diff", "plus_rate", "hit104_rate", "rank"]]),
                    "",
                ]
            )
    report_parts.append(
        _report_section(
            "Section 4: フロア × 曜日 × 末尾（水曜・土曜限定）",
            sec4_parts,
        )
    )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    quickref_path.parent.mkdir(parents=True, exist_ok=True)
    quickref.to_csv(quickref_path, index=False, encoding="utf-8-sig")
    report_parts.append(
        _report_section(
            "Section 5: フロア別早見表",
            [
                f"CSV saved: `{quickref_path.name}`",
                "",
                _safe_md(quickref if not quickref.empty else pd.DataFrame(columns=["floor", "day_of_week", "dd_mod10", "n_cells", "top3", "avoid2"])),
            ],
        )
    )

    report_path.write_text("\n".join(report_parts).rstrip() + "\n", encoding="utf-8")
    print(f"[OK] report saved: {report_path}")
    print(f"[OK] quickref saved: {quickref_path}")

    return {
        "floor_summary": floor_summary,
        "floor_segment_distribution": floor_segment,
        "floor_tail_baseline": tail_baseline,
        "floor_spearman": floor_spearman,
        "dd_floor_tail": dd_floor_tail,
        "weekday_dd_tail": weekday_dd_tail,
        "quickref": quickref,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--quickref-path", type=Path, default=QUICKREF_PATH)
    parser.add_argument("--min-n-matrix", type=int, default=MIN_MATRIX_N)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_analysis(
        report_path=args.report_path,
        quickref_path=args.quickref_path,
        min_n_matrix=args.min_n_matrix,
    )


if __name__ == "__main__":
    main()
