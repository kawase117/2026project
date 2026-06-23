from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from eda.kamata7_lastdigit_lr_eda import load_coords  # noqa: E402
from eda.kamata7_verification_common import (  # noqa: E402
    DOW_ORDER,
    KAKUBAN_ORDER,
    REPORT_DIR,
    prepare_base_frame,
    table_to_markdown,
    write_text,
)
from ml.experiments.walkforward_scoring.scoring_model import classify_seg  # noqa: E402

HALL = "蒲田7"
ANNIVERSARY_MMDD = "0707"
OUTPUT_DIR = REPORT_DIR / "kamata7_dow_kakuban_segment"
SUMMARY_REPORT_PATH = OUTPUT_DIR / "summary_report.md"

TASK1_COUNTS_PATH = OUTPUT_DIR / "task1_dow_kakuban_segment.csv"
TASK1_KW_PATH = OUTPUT_DIR / "task1_dow_segment_kw_test.csv"
TASK2_PATH = OUTPUT_DIR / "task2_thursday_oddeven.csv"
TASK3_PATH = OUTPUT_DIR / "task3_friday_section_kakuban.csv"
TASK4_PATH = OUTPUT_DIR / "task4_tuesday_kakuban_detail.csv"
TASK5_PATH = OUTPUT_DIR / "task5_thursday_nibui_candidates.csv"

SEGMENT_ORDER = ["A", "N"]
RANK_SOURCES = ["rank_from_min", "rank_from_max"]


def _normalize_weekday(value: object) -> str:
    text = str(value).strip()
    if text in DOW_ORDER:
        return text
    weekday_aliases = {
        "Monday": "月",
        "Tuesday": "火",
        "Wednesday": "水",
        "Thursday": "木",
        "Friday": "金",
        "Saturday": "土",
        "Sunday": "日",
        "Mon": "月",
        "Tue": "火",
        "Wed": "水",
        "Thu": "木",
        "Fri": "金",
        "Sat": "土",
        "Sun": "日",
        "月曜日": "月",
        "火曜日": "火",
        "水曜日": "水",
        "木曜日": "木",
        "金曜日": "金",
        "土曜日": "土",
        "日曜日": "日",
    }
    return weekday_aliases.get(text, text[:1] if text else "")


def _cohen_d(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]
    if len(a) < 2 or len(b) < 2:
        return np.nan
    va = a.var(ddof=1)
    vb = b.var(ddof=1)
    pooled = ((len(a) - 1) * va + (len(b) - 1) * vb) / (len(a) + len(b) - 2)
    if pooled <= 0:
        return np.nan
    return float((a.mean() - b.mean()) / np.sqrt(pooled))


def _bonferroni(p_value: float, n_tests: int) -> float:
    if pd.isna(p_value):
        return np.nan
    return float(min(1.0, p_value * max(1, n_tests)))


def _prepare_frame() -> pd.DataFrame:
    df = prepare_base_frame(include_coords=False).copy()
    df["date"] = df["date"].astype(str)
    df["day_of_week"] = df["day_of_week"].map(_normalize_weekday)
    df["machine_number"] = pd.to_numeric(df["machine_number"], errors="coerce")
    df["games"] = pd.to_numeric(df["games"], errors="coerce")
    df["diff"] = pd.to_numeric(df["diff"], errors="coerce")
    df = df.dropna(subset=["machine_number", "games", "diff", "day_of_week"]).copy()
    df = df[df["games"] >= 2000].copy()
    df["machine_number"] = df["machine_number"].astype(int)

    coords = load_coords().copy()
    coords = coords.drop_duplicates(subset=["machine_number"], keep="first")
    coords["rank_from_min"] = pd.to_numeric(coords["rank_from_min"], errors="coerce")
    coords["rank_from_max"] = pd.to_numeric(coords["rank_from_max"], errors="coerce")
    df = df.merge(
        coords[["machine_number", "section", "section_min", "section_max", "rank_from_min", "rank_from_max"]],
        on="machine_number",
        how="left",
    )

    df["seg"] = df["machine_name"].map(classify_seg)
    df = df.dropna(subset=["seg", "section"]).copy()
    df = df[df["machine_number"] != 2026].copy()
    df["kakuban_min"] = pd.to_numeric(df["rank_from_min"], errors="coerce").astype("Int64")
    df["kakuban_max"] = pd.to_numeric(df["rank_from_max"], errors="coerce").astype("Int64")

    df["plus"] = (df["diff"] > 0).astype(int)
    df["hit104"] = (((1 + df["diff"] / (df["games"] * 3)) * 100) >= 104.0).astype(int)

    df["day_of_week"] = pd.Categorical(df["day_of_week"], categories=DOW_ORDER, ordered=True)
    df["seg"] = pd.Categorical(df["seg"], categories=SEGMENT_ORDER, ordered=True)
    return df.reset_index(drop=True)


def _format_group_summary(df: pd.DataFrame, group_cols: list[str], value_col: str = "diff") -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=[*group_cols, "n", "avg_diff", "std_diff", "plus_rate", "hit104_rate"])
    out = (
        df.groupby(group_cols, observed=True)
        .agg(
            n=(value_col, "size"),
            avg_diff=(value_col, "mean"),
            std_diff=(value_col, "std"),
            plus_rate=("plus", "mean"),
            hit104_rate=("hit104", "mean"),
        )
        .reset_index()
    )
    out["avg_diff"] = out["avg_diff"].round(0)
    out["std_diff"] = out["std_diff"].round(1)
    out["plus_rate"] = (out["plus_rate"] * 100).round(1)
    out["hit104_rate"] = (out["hit104_rate"] * 100).round(1)
    return out


def _kruskal_by_group(df: pd.DataFrame, group_cols: list[str], value_col: str, min_n: int = 5) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for key, grp in df.groupby(group_cols, observed=True):
        if isinstance(key, tuple):
            row = {col: val for col, val in zip(group_cols, key)}
        else:
            row = {group_cols[0]: key}
        groups = [g[value_col].dropna().to_numpy() for _, g in grp.groupby("kakuban_min", observed=True) if len(g) >= min_n]
        if len(groups) < 2:
            row.update({"kw_stat": np.nan, "p_value": np.nan, "n_groups": len(groups), "n_rows": int(len(grp))})
            rows.append(row)
            continue
        stat, p_value = stats.kruskal(*groups)
        row.update(
            {
                "kw_stat": float(stat),
                "p_value": float(p_value),
                "n_groups": len(groups),
                "n_rows": int(sum(len(g) for g in groups)),
            }
        )
        rows.append(row)

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["bonferroni_p"] = out["p_value"].apply(lambda p: _bonferroni(p, int(out["p_value"].notna().sum())))
    return out.sort_values(["bonferroni_p", "p_value"], ascending=[True, True]).reset_index(drop=True)


def _mw_oddeven(df: pd.DataFrame, *, rank_col: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if df.empty:
        return pd.DataFrame(columns=["seg", "rank_source", "even_n", "odd_n", "even_avg_diff", "odd_avg_diff", "delta_diff", "cohen_d", "u_stat", "p_value"])

    work = df.copy()
    work = work.dropna(subset=[rank_col])
    work["kakuban_min"] = pd.to_numeric(work[rank_col], errors="coerce").astype("Int64")
    work = work.dropna(subset=["kakuban_min"]).copy()
    work["kakuban_min"] = work["kakuban_min"].astype(int)
    work["parity"] = np.where(work["kakuban_min"] % 2 == 0, "even", "odd")

    for seg in SEGMENT_ORDER:
        sub = work[work["seg"] == seg].copy()
        even = sub[sub["parity"] == "even"]["diff"].dropna().to_numpy()
        odd = sub[sub["parity"] == "odd"]["diff"].dropna().to_numpy()
        if len(even) < 5 or len(odd) < 5:
            rows.append(
                {
                    "seg": seg,
                    "rank_source": rank_col,
                    "even_n": int(len(even)),
                    "odd_n": int(len(odd)),
                    "even_avg_diff": float(np.mean(even)) if len(even) else np.nan,
                    "odd_avg_diff": float(np.mean(odd)) if len(odd) else np.nan,
                    "delta_diff": float(np.mean(even) - np.mean(odd)) if len(even) and len(odd) else np.nan,
                    "cohen_d": _cohen_d(even, odd),
                    "u_stat": np.nan,
                    "p_value": np.nan,
                }
            )
            continue
        u_stat, p_value = stats.mannwhitneyu(even, odd, alternative="two-sided")
        rows.append(
            {
                "seg": seg,
                "rank_source": rank_col,
                "even_n": int(len(even)),
                "odd_n": int(len(odd)),
                "even_avg_diff": float(np.mean(even)),
                "odd_avg_diff": float(np.mean(odd)),
                "delta_diff": float(np.mean(even) - np.mean(odd)),
                "cohen_d": _cohen_d(even, odd),
                "u_stat": float(u_stat),
                "p_value": float(p_value),
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["bonferroni_p"] = out["p_value"].apply(lambda p: _bonferroni(p, int(out["p_value"].notna().sum())))
    return out.sort_values(["bonferroni_p", "p_value", "seg"], ascending=[True, True, True]).reset_index(drop=True)


def _section_pivot(df: pd.DataFrame, weekday: str) -> pd.DataFrame:
    sub = df[df["day_of_week"] == weekday].copy()
    if sub.empty:
        return pd.DataFrame(columns=["section", "kakuban_min", "n", "avg_diff", "std_diff", "plus_rate", "hit104_rate"])
    sub["kakuban_min"] = pd.to_numeric(sub["rank_from_min"], errors="coerce").astype("Int64")
    sub = sub.dropna(subset=["kakuban_min"]).copy()
    sub["kakuban_min"] = sub["kakuban_min"].astype(int)
    summary = _format_group_summary(sub, ["section", "kakuban_min"])
    summary["section"] = summary["section"].astype(str)
    return summary.sort_values(["section", "kakuban_min"]).reset_index(drop=True)


def _rank_detail(df: pd.DataFrame, *, weekday: str, rank_source: str) -> pd.DataFrame:
    sub = df[df["day_of_week"] == weekday].copy()
    sub = sub.dropna(subset=[rank_source]).copy()
    sub["kakuban_min"] = pd.to_numeric(sub[rank_source], errors="coerce").astype("Int64")
    sub = sub.dropna(subset=["kakuban_min"]).copy()
    sub["kakuban_min"] = sub["kakuban_min"].astype(int)
    summary = _format_group_summary(sub, ["seg", "kakuban_min"])
    summary["rank_source"] = rank_source
    return summary.sort_values(["seg", "kakuban_min"]).reset_index(drop=True)


def _thursday_nibui_candidates(df: pd.DataFrame) -> pd.DataFrame:
    sub = df[df["day_of_week"] == "木"].copy()
    if sub.empty:
        return pd.DataFrame(columns=["machine_name", "seg", "n_rows", "plus_rate", "avg_diff", "is_candidate"])
    summary = (
        sub.groupby(["machine_name", "seg"], observed=True)
        .agg(
            n_rows=("diff", "size"),
            plus_rate=("plus", "mean"),
            avg_diff=("diff", "mean"),
        )
        .reset_index()
    )
    summary["plus_rate"] = (summary["plus_rate"] * 100).round(1)
    summary["avg_diff"] = summary["avg_diff"].round(0)
    summary["is_candidate"] = summary["plus_rate"].between(45, 55, inclusive="both")
    return summary.sort_values(["is_candidate", "plus_rate", "avg_diff"], ascending=[False, False, False]).reset_index(drop=True)


def _triplet_day_frame(df: pd.DataFrame) -> pd.DataFrame:
    n_df = df[df["seg"] == "N"].copy()
    daily = (
        n_df.groupby(["date", "day_of_week", "machine_digit"], observed=True)
        .agg(avg_diff=("diff", "mean"), n=("diff", "size"))
        .reset_index()
    )
    pivot = (
        daily.pivot(index=["date", "day_of_week"], columns="machine_digit", values="avg_diff")
        .reindex(columns=[str(i) for i in range(10)])
        .reset_index()
    )

    rows: list[dict[str, object]] = []
    for _, row in pivot.iterrows():
        digit_values = {int(col): row[col] for col in [str(i) for i in range(10)] if pd.notna(row[col])}
        if len(digit_values) < 3:
            continue
        ranked = sorted(digit_values.items(), key=lambda item: (-float(item[1]), int(item[0])))
        top_digits = [digit for digit, _ in ranked[:3]]
        if len(top_digits) < 3:
            continue
        rows.append(
            {
                "date": str(row["date"]),
                "day_of_week": row["day_of_week"],
                "top1": top_digits[0],
                "top2": top_digits[1],
                "top3": top_digits[2],
                "triplet_label": "-".join(str(d) for d in sorted(top_digits)),
                "contains_7": 7 in top_digits,
                "is_consecutive": _is_consecutive_ring(top_digits),
                "top3_avg_diff": float(np.mean([digit_values[d] for d in top_digits])),
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["day_of_week"] = pd.Categorical(out["day_of_week"], categories=DOW_ORDER, ordered=True)
    return out.sort_values(["day_of_week", "date"]).reset_index(drop=True)


def _is_consecutive_ring(digits: list[int] | tuple[int, ...]) -> bool:
    values = [int(d) % 10 for d in digits]
    if len(values) != len(set(values)):
        return False
    if len(values) < 2:
        return True
    sorted_values = sorted(values)
    if sorted_values[-1] - sorted_values[0] == len(sorted_values) - 1:
        return True
    for offset in range(10):
        rotated = sorted(((d - offset) % 10 for d in values))
        if rotated[-1] - rotated[0] == len(rotated) - 1:
            return True
    return False


def _triplet_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["day_of_week", "n_days", "avg_top3_diff", "consecutive_rate", "with7_rate", "top_triplet"])
    rows: list[dict[str, object]] = []
    for weekday in DOW_ORDER:
        sub = df[df["day_of_week"] == weekday]
        if sub.empty:
            continue
        top_triplet = sub["triplet_label"].value_counts().index[0]
        rows.append(
            {
                "day_of_week": weekday,
                "n_days": int(len(sub)),
                "avg_top3_diff": float(sub["top3_avg_diff"].mean()),
                "consecutive_rate": float(sub["is_consecutive"].mean() * 100),
                "with7_rate": float(sub["contains_7"].mean() * 100),
                "top_triplet": top_triplet,
            }
        )
    return pd.DataFrame(rows)


def _write_table(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def build_outputs(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    # Task 1
    task1_counts = _format_group_summary(df, ["day_of_week", "seg", "kakuban_min"])
    task1_counts = task1_counts.sort_values(["day_of_week", "seg", "kakuban_min"]).reset_index(drop=True)
    task1_kw = _kruskal_by_group(df, ["day_of_week", "seg"], "diff", min_n=5)
    task1_kw["analysis_name"] = task1_kw.apply(lambda r: f"{r['day_of_week']}×{r['seg']}", axis=1)
    task1_kw = task1_kw[
        [
            "analysis_name",
            "day_of_week",
            "seg",
            "kw_stat",
            "p_value",
            "bonferroni_p",
            "n_groups",
            "n_rows",
        ]
    ].sort_values(["bonferroni_p", "p_value"]).reset_index(drop=True)

    # Task 2
    task2_df = df[df["day_of_week"] == "木"].copy()
    task2 = pd.concat([_mw_oddeven(task2_df, rank_col=col) for col in RANK_SOURCES], ignore_index=True)
    if not task2.empty:
        task2["weekday"] = "木"
        task2 = task2[
            [
                "weekday",
                "seg",
                "rank_source",
                "even_n",
                "odd_n",
                "even_avg_diff",
                "odd_avg_diff",
                "delta_diff",
                "cohen_d",
                "u_stat",
                "p_value",
                "bonferroni_p",
            ]
        ].sort_values(["bonferroni_p", "p_value"], ascending=[True, True]).reset_index(drop=True)

    # Task 3
    friday_pivot = _section_pivot(df, "金")

    # Task 4
    tuesday_detail_parts = []
    for rank_source in RANK_SOURCES:
        tuesday_detail_parts.append(_rank_detail(df, weekday="火", rank_source=rank_source))
    task4 = pd.concat(tuesday_detail_parts, ignore_index=True) if tuesday_detail_parts else pd.DataFrame()
    if not task4.empty:
        task4["weekday"] = "火"
        task4 = task4[
            [
                "weekday",
                "seg",
                "rank_source",
                "kakuban_min",
                "n",
                "avg_diff",
                "std_diff",
                "plus_rate",
                "hit104_rate",
            ]
        ].sort_values(["rank_source", "seg", "kakuban_min"]).reset_index(drop=True)

    # Task 5
    task5 = _thursday_nibui_candidates(df)
    if not task5.empty:
        task5 = task5[["machine_name", "seg", "n_rows", "plus_rate", "avg_diff", "is_candidate"]].reset_index(drop=True)

    triplet_df = _triplet_day_frame(df)
    triplet_summary = _triplet_summary(triplet_df)
    return task1_counts, task1_kw, task2, friday_pivot, task4, task5, triplet_summary


def build_summary_report(
    task1_counts: pd.DataFrame,
    task1_kw: pd.DataFrame,
    task2: pd.DataFrame,
    friday_pivot: pd.DataFrame,
    task4: pd.DataFrame,
    task5: pd.DataFrame,
    triplet_summary: pd.DataFrame,
) -> str:
    lines: list[str] = []
    lines.append("# 蒲田7 曜日別角番・セグメント分解レポート")
    lines.append("")
    lines.append("- 前処理: 7/7除外、台番号2026除外、games>=2000")
    lines.append("- seg判定: `ml.experiments.walkforward_scoring.scoring_model.classify_seg` を使用")
    lines.append("")

    lines.append("## Task 1: 曜日 × セグメント × 角番")
    lines.append(table_to_markdown(task1_counts.head(40)))
    lines.append("")
    lines.append("### Kruskal-Wallis")
    lines.append(table_to_markdown(task1_kw.head(20)))
    lines.append("")

    lines.append("## Task 2: 木曜 偶奇検定")
    lines.append(table_to_markdown(task2))
    lines.append("")

    lines.append("## Task 3: 金曜 section × 角番")
    lines.append(table_to_markdown(friday_pivot.head(40)))
    lines.append("")

    lines.append("## Task 4: 火曜 角番詳細")
    lines.append(table_to_markdown(task4.head(60)))
    lines.append("")

    lines.append("## Task 5: 木曜 ニブイチ候補")
    lines.append(table_to_markdown(task5.head(40)))
    lines.append("")

    lines.append("## 補足")
    lines.append(table_to_markdown(triplet_summary))
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    df = _prepare_frame()
    task1_counts, task1_kw, task2, friday_pivot, task4, task5, triplet_summary = build_outputs(df)

    _write_table(TASK1_COUNTS_PATH, task1_counts)
    _write_table(TASK1_KW_PATH, task1_kw)
    _write_table(TASK2_PATH, task2)
    _write_table(TASK3_PATH, friday_pivot)
    _write_table(TASK4_PATH, task4)
    _write_table(TASK5_PATH, task5)

    SUMMARY_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = build_summary_report(task1_counts, task1_kw, task2, friday_pivot, task4, task5, triplet_summary)
    write_text(SUMMARY_REPORT_PATH, report)

    print(f"[OK] report saved: {SUMMARY_REPORT_PATH}")
    print(f"[OK] csv saved: {TASK1_COUNTS_PATH}")
    print(f"[OK] csv saved: {TASK1_KW_PATH}")
    print(f"[OK] csv saved: {TASK2_PATH}")
    print(f"[OK] csv saved: {TASK3_PATH}")
    print(f"[OK] csv saved: {TASK4_PATH}")
    print(f"[OK] csv saved: {TASK5_PATH}")


if __name__ == "__main__":
    main()
