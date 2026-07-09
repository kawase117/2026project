from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kruskal

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda.mitoya_phase3_screening import build_screening_tables
from eda.mitoya_prompt_common import (
    RESULTS_DIR,
    add_debut_phase,
    compute_top2_share as _compute_top2_share,
    ensure_results_dir,
    kw_epsilon_squared,
    load_mitoya_frame,
    render_markdown_table,
    section_sort_key,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


OUTPUT_PATH = RESULTS_DIR / "mitoya_phase4_durability.md"


def add_split_half_label(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    unique_dates = sorted(d for d in work["date"].dropna().unique())
    if not unique_dates:
        work["split_half"] = "first"
        return work
    split_index = max(1, len(unique_dates) // 2)
    first_dates = set(unique_dates[:split_index])
    work["split_half"] = np.where(work["date"].isin(first_dates), "first", "second")
    return work


def compute_top2_share(frame: pd.DataFrame | pd.Series) -> float:
    return _compute_top2_share(frame)


def _evaluate_split_half(section_df: pd.DataFrame, variable: str) -> str:
    work = add_split_half_label(section_df)
    if variable == "machine_zorome":
        first = work.loc[work["split_half"] == "first"].groupby(variable)["diff"].mean()
        second = work.loc[work["split_half"] == "second"].groupby(variable)["diff"].mean()
        if first.empty or second.empty:
            return "FAIL"
        common = sorted(set(first.index) & set(second.index))
        if len(common) < 2:
            return "FAIL"
        sign_first = np.sign(float(first.loc[common].iloc[1] - first.loc[common].iloc[0]))
        sign_second = np.sign(float(second.loc[common].iloc[1] - second.loc[common].iloc[0]))
        return "PASS" if sign_first == sign_second else "FAIL"

    first = work.loc[work["split_half"] == "first"].groupby(variable)["diff"].mean().sort_values(ascending=False)
    second = work.loc[work["split_half"] == "second"].groupby(variable)["diff"].mean().sort_values(ascending=False)
    if len(first) < 2 or len(second) < 2:
        return "FAIL"
    overlap = len(set(first.head(3).index) & set(second.head(3).index))
    return "PASS" if overlap >= 2 else "FAIL"


def _evaluate_iron_exclusion(section_df: pd.DataFrame, variable: str) -> str:
    machine_stats = (
        section_df.groupby("machine_number").agg(pos_rate=("diff", lambda s: float((s > 0).mean()))).reset_index()
    )
    iron_machines = set(machine_stats.loc[machine_stats["pos_rate"] >= 0.60, "machine_number"])
    filtered = section_df.loc[~section_df["machine_number"].isin(iron_machines)].copy()
    if filtered.empty:
        return "FAIL"
    grouped = filtered.groupby(variable)["diff"].agg(["count", "mean"])
    valid = grouped[grouped["count"] >= 2]
    if len(valid) < 2:
        return "FAIL"
    samples = [filtered.loc[filtered[variable] == label, "diff"].to_numpy(dtype=float) for label in valid.index]
    if len(samples) < 2:
        return "FAIL"
    _, p_value = kruskal(*samples)
    return "PASS" if p_value < 0.05 else "FAIL"


def build_durability_table(df: pd.DataFrame, screening_summary: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    focus = screening_summary.loc[screening_summary["p_value"] < 0.01, ["variable", "section"]].copy()
    if focus.empty:
        focus = screening_summary.loc[screening_summary["p_value"] < 0.05, ["variable", "section"]].copy()

    rows: list[dict[str, object]] = []
    robust_sections: list[str] = []
    if focus.empty:
        return pd.DataFrame(rows), robust_sections

    work = add_debut_phase(df)
    for item in focus.itertuples(index=False):
        variable = item.variable
        section = item.section
        section_df = work.loc[work["section"].astype(str) == str(section)].copy()
        if section_df.empty or variable not in section_df.columns:
            continue
        split_half = _evaluate_split_half(section_df, variable)
        iron_exclusion = _evaluate_iron_exclusion(section_df, variable)

        machine_means = section_df.groupby("machine_number")["diff"].mean().sort_values(ascending=False)
        top2_share = compute_top2_share(machine_means)
        if pd.isna(top2_share):
            top2_label = "SKIP"
        elif top2_share < 0.10:
            top2_label = "PASS"
        elif top2_share <= 0.30:
            top2_label = "WARN"
        else:
            top2_label = "FAIL"

        total_status = (
            "✅堅牢"
            if split_half == "PASS" and iron_exclusion == "PASS" and top2_label != "FAIL"
            else ("⚠️脆弱" if [split_half, iron_exclusion].count("FAIL") == 1 else "❌却下")
        )
        if total_status == "✅堅牢":
            robust_sections.append(str(section))
        rows.append(
            {
                "variable": variable,
                "section": str(section),
                "split_half": split_half,
                "iron_exclusion": iron_exclusion,
                "top2_share": float(top2_share) * 100 if pd.notna(top2_share) else float("nan"),
                "top2_label": top2_label,
                "総合判定": total_status,
            }
        )

    table = pd.DataFrame(rows)
    if not table.empty:
        table = table.sort_values(
            ["variable", "section"], key=lambda col: col.map(section_sort_key) if col.name == "section" else col
        )
        table = table.reset_index(drop=True)
    return table, sorted(set(robust_sections), key=lambda value: section_sort_key(value))


def build_report(table: pd.DataFrame) -> str:
    lines = [
        "# みとや大森町 Phase 4: 耐久性検証",
        "",
        "## サマリ",
        "",
    ]
    if table.empty:
        lines.append("_no rows_")
    else:
        lines.append(render_markdown_table(table))
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ensure_results_dir()
    df = load_mitoya_frame(join_layout=True)
    screening_summary, _ = build_screening_tables(df)
    table, _ = build_durability_table(df, screening_summary)
    OUTPUT_PATH.write_text(build_report(table), encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
