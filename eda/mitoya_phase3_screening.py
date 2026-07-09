from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kruskal, mannwhitneyu

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda.mitoya_prompt_common import (
    DEBUT_PHASE_ORDER,
    RESULTS_DIR,
    WEEKDAY_ORDER,
    add_debut_phase,
    ensure_results_dir,
    kw_epsilon_squared,
    load_mitoya_frame,
    render_markdown_table,
    section_sort_key,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


OUTPUT_PATH = RESULTS_DIR / "mitoya_phase3_screening.md"


def _section_summary(
    work: pd.DataFrame, variable: str, value_col: str, *, is_binary: bool = False
) -> tuple[float, float, int, int]:
    groups = []
    grouped = work.groupby(variable, dropna=False)
    for key, grp in grouped:
        if len(grp) < 2:
            continue
        groups.append((key, grp["diff"].dropna().to_numpy(dtype=float)))
    if len(groups) < 2:
        return float("nan"), float("nan"), 0, 0
    arrays = [vals for _, vals in groups if len(vals) >= 2]
    if len(arrays) < 2:
        return float("nan"), float("nan"), 0, 0
    if is_binary:
        left = arrays[0]
        right = arrays[1]
        stat, p_value = mannwhitneyu(left, right, alternative="two-sided")
        kw_stat = float(stat)
    else:
        kw_stat, p_value = kruskal(*arrays)
    return float(kw_stat), float(p_value), int(sum(len(vals) for vals in arrays)), int(len(arrays))


def _category_detail(work: pd.DataFrame, variable: str) -> pd.DataFrame:
    rows = []
    for key, grp in work.groupby(variable, dropna=False):
        rows.append(
            {
                variable: key,
                "n": int(len(grp)),
                "mean_diff": float(grp["diff"].mean()),
                "plus_rate": float((grp["diff"] > 0).mean() * 100),
            }
        )
    detail = pd.DataFrame(rows)
    if detail.empty:
        return detail
    if variable == "day_of_week":
        detail[variable] = pd.Categorical(detail[variable], categories=WEEKDAY_ORDER, ordered=True)
    elif variable == "debut_phase":
        detail[variable] = pd.Categorical(detail[variable], categories=DEBUT_PHASE_ORDER, ordered=True)
    detail = detail.sort_values(variable).reset_index(drop=True)
    detail["mean_diff"] = detail["mean_diff"].round(0).astype(int)
    detail["plus_rate"] = detail["plus_rate"].round(1)
    return detail


def build_screening_tables(df: pd.DataFrame) -> tuple[pd.DataFrame, list[tuple[str, str]]]:
    work = df.copy()
    if "section" not in work.columns:
        raise ValueError("df must include section")
    work = add_debut_phase(work)

    rows: list[dict[str, object]] = []
    detail_blocks: list[str] = []
    candidates: list[tuple[str, str]] = []

    variable_specs = [
        ("machine_digit", "last_digit", False),
        ("day_of_week", "day_of_week", False),
        ("machine_zorome", "is_zorome", True),
        ("debut_phase", "debut_phase", False),
    ]

    for section, section_df in work.groupby("section", dropna=False):
        section_label = "" if pd.isna(section) else str(section)
        section_df = section_df.dropna(subset=["diff"]).copy()
        for value_col, variable_label, is_binary in variable_specs:
            if value_col not in section_df.columns:
                continue
            filtered = section_df.dropna(subset=[value_col]).copy()
            if filtered.empty:
                continue
            kw_stat, p_value, n_rows, n_groups = _section_summary(filtered, value_col, "diff", is_binary=is_binary)
            if not np.isfinite(p_value):
                continue
            detail = _category_detail(filtered, value_col)
            epsilon_sq = kw_epsilon_squared(kw_stat, n_groups, n_rows)
            rows.append(
                {
                    "variable": variable_label,
                    "section": section_label,
                    "KW_stat": round(kw_stat, 4) if pd.notna(kw_stat) else float("nan"),
                    "p_value": float(p_value),
                    "epsilon_sq": round(epsilon_sq, 6) if pd.notna(epsilon_sq) else float("nan"),
                    "n": int(n_rows),
                    "判定": "◎有望" if p_value < 0.01 else ("△要注意" if p_value < 0.05 else "✗脱落"),
                }
            )
            if p_value < 0.01:
                candidates.append((variable_label, section_label))
                detail_blocks.append(f"### {variable_label} / {section_label}\n\n{render_markdown_table(detail)}\n")

    summary = pd.DataFrame(rows)
    if not summary.empty:
        summary = summary.sort_values(
            ["variable", "section"], key=lambda col: col.map(section_sort_key) if col.name == "section" else col
        )
        summary = summary.reset_index(drop=True)
    return summary, candidates


def build_report(summary: pd.DataFrame, candidates: list[tuple[str, str]], df: pd.DataFrame) -> str:
    work = add_debut_phase(df.copy())
    lines = [
        "# みとや大森町 Phase 3: 変数スクリーニング",
        "",
        "## 1. 台番号末尾 (last_digit)",
        "",
    ]
    for variable in ["last_digit", "day_of_week", "is_zorome", "debut_phase"]:
        subset = summary.loc[summary["variable"] == variable].copy()
        if subset.empty:
            continue
        lines.append(f"## {variable}")
        lines.append("")
        lines.append(render_markdown_table(subset))
        lines.append("")

    if candidates:
        lines.append("## Phase 4 検証対象リスト")
        lines.append("")
        lines.append("| variable | section |")
        lines.append("|---|---|")
        for variable, section in candidates:
            lines.append(f"| {variable} | {section} |")
        lines.append("")
        lines.append("## 詳細")
        lines.append("")
        for variable, section in candidates:
            value_col = {
                "last_digit": "machine_digit",
                "day_of_week": "day_of_week",
                "is_zorome": "machine_zorome",
                "debut_phase": "debut_phase",
            }.get(variable)
            if value_col is None:
                continue
            section_df = work.loc[work["section"].astype(str) == str(section)].copy()
            detail = _category_detail(section_df, value_col)
            lines.append(f"### {variable} / {section}")
            lines.append("")
            lines.append(render_markdown_table(detail))
            lines.append("")
    else:
        lines.append("## Phase 4 検証対象リスト")
        lines.append("")
        lines.append("_no rows_")

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ensure_results_dir()
    df = load_mitoya_frame(join_layout=True)
    summary, candidates = build_screening_tables(df)
    OUTPUT_PATH.write_text(build_report(summary, candidates, df), encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
