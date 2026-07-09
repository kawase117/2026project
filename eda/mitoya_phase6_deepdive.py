from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda.mitoya_prompt_common import (
    MITOYA_MAIN_SECTIONS,
    RESULTS_DIR,
    add_debut_phase,
    bucket_rank_from_aisle,
    ensure_results_dir,
    load_mitoya_frame,
    render_markdown_table,
    section_sort_key,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


OUTPUT_PATH = RESULTS_DIR / "mitoya_phase6_deepdive.md"
TARGET_SECTIONS = MITOYA_MAIN_SECTIONS
DD_BUCKETS = ["DD1-6", "DD7-12", "DD13-18", "DD19-24", "DD25-31"]


def _phase_order(series: pd.Series) -> pd.Categorical:
    return pd.Categorical(series, categories=["pre_existing", "debut", "growth", "mature"], ordered=True)


def _make_dd_bucket(series: pd.Series) -> pd.Series:
    return pd.cut(
        series,
        bins=[0, 6, 12, 18, 24, 31],
        labels=DD_BUCKETS,
        include_lowest=True,
        right=True,
    )


def build_section_machine_table(df: pd.DataFrame, sections: list[str] | None = None) -> pd.DataFrame:
    work = add_debut_phase(df.copy())
    if sections is not None:
        work = work.loc[work["section"].astype(str).isin([str(section) for section in sections])].copy()
    work = work.dropna(subset=["section", "machine_name", "debut_phase", "diff"]).copy()
    work["debut_phase"] = _phase_order(work["debut_phase"])

    rows: list[dict[str, object]] = []
    for (section, machine_name, phase), grp in work.groupby(["section", "machine_name", "debut_phase"], dropna=False):
        if pd.isna(phase):
            continue
        rows.append(
            {
                "section": str(section),
                "machine_name": str(machine_name),
                "debut_phase": str(phase),
                "n": int(len(grp)),
                "avg_diff": float(grp["diff"].mean()),
                "plus_rate": float((grp["diff"] > 0).mean() * 100),
                "avg_rank_from_aisle": float(grp["rank_from_aisle"].mean())
                if "rank_from_aisle" in grp.columns
                else float("nan"),
            }
        )

    table = pd.DataFrame(rows)
    if table.empty:
        return table
    table["avg_diff"] = table["avg_diff"].round(0).astype(int)
    table["plus_rate"] = table["plus_rate"].round(1)
    table["avg_rank_from_aisle"] = table["avg_rank_from_aisle"].round(1)
    table = table.sort_values(
        ["section", "avg_diff", "plus_rate", "n"],
        ascending=[True, False, False, False],
        key=lambda col: col.map(section_sort_key) if col.name == "section" else col,
    ).reset_index(drop=True)
    return table.groupby("section", as_index=False, sort=False).head(8).reset_index(drop=True)


def build_interaction_table(df: pd.DataFrame, sections: list[str] | None = None) -> pd.DataFrame:
    work = add_debut_phase(df.copy())
    if sections is not None:
        work = work.loc[work["section"].astype(str).isin([str(section) for section in sections])].copy()
    work = work.dropna(subset=["section", "debut_phase", "dd", "diff", "day_of_week"]).copy()
    work["debut_phase"] = _phase_order(work["debut_phase"])
    work["dd_bucket"] = _make_dd_bucket(pd.to_numeric(work["dd"], errors="coerce"))

    rows: list[dict[str, object]] = []
    for (section, phase, dd_bucket), grp in work.groupby(["section", "debut_phase", "dd_bucket"], dropna=False):
        if pd.isna(phase) or pd.isna(dd_bucket):
            continue
        rows.append(
            {
                "section": str(section),
                "debut_phase": str(phase),
                "dd_bucket": str(dd_bucket),
                "n": int(len(grp)),
                "avg_diff": float(grp["diff"].mean()),
                "plus_rate": float((grp["diff"] > 0).mean() * 100),
            }
        )
    table = pd.DataFrame(rows)
    if table.empty:
        return table
    table["avg_diff"] = table["avg_diff"].round(0).astype(int)
    table["plus_rate"] = table["plus_rate"].round(1)
    table = table.sort_values(
        ["section", "debut_phase", "dd_bucket"],
        key=lambda col: col.map(section_sort_key) if col.name == "section" else col,
    ).reset_index(drop=True)
    return table


def build_report(section_table: pd.DataFrame, interaction_table: pd.DataFrame) -> str:
    lines = [
        "# Mitoya Phase 6: 強セクション深掘り",
        "",
        "## 対象セクション",
        "",
        ", ".join(TARGET_SECTIONS),
        "",
        "## 機種別ランキング",
        "",
        render_markdown_table(section_table) if not section_table.empty else "_no rows_",
        "",
        "## debut_phase × DD",
        "",
        render_markdown_table(interaction_table) if not interaction_table.empty else "_no rows_",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ensure_results_dir()
    df = load_mitoya_frame(join_layout=True)
    section_table = build_section_machine_table(df, TARGET_SECTIONS)
    interaction_table = build_interaction_table(df, TARGET_SECTIONS)
    OUTPUT_PATH.write_text(build_report(section_table, interaction_table), encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
