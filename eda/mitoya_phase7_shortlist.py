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
    ensure_results_dir,
    load_mitoya_frame,
    render_markdown_table,
    section_sort_key,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


OUTPUT_PATH = RESULTS_DIR / "mitoya_phase7_shortlist.md"
TARGET_SECTIONS = MITOYA_MAIN_SECTIONS


def build_shortlist_table(
    df: pd.DataFrame,
    sections: list[str] | None = None,
    top_n: int = 3,
    *,
    available_machine_names: set[str] | None = None,
    include_moved: bool = True,
) -> pd.DataFrame:
    work = add_debut_phase(df.copy())
    if sections is not None:
        work = work.loc[work["section"].astype(str).isin([str(section) for section in sections])].copy()
    if available_machine_names is not None:
        work = work.loc[work["machine_name"].astype(str).isin({str(name) for name in available_machine_names})].copy()
    if not include_moved and "is_moved" in work.columns:
        work = work.loc[~work["is_moved"]].copy()
    work = work.dropna(subset=["section", "machine_name", "debut_phase", "diff"]).copy()

    phase_stats = (
        work.groupby(["section", "machine_name", "debut_phase"], dropna=False)
        .agg(
            avg_diff=("diff", "mean"),
            plus_rate=("diff", lambda s: float((s > 0).mean() * 100)),
            n=("diff", "size"),
            avg_rank_from_aisle=("rank_from_aisle", "mean"),
        )
        .reset_index()
    )
    if phase_stats.empty:
        return phase_stats

    phase_stats["support_phase"] = phase_stats["avg_diff"] > 0
    best_rows = []
    for (section, machine_name), grp in phase_stats.groupby(["section", "machine_name"], dropna=False):
        grp = grp.sort_values(
            ["avg_diff", "support_phase", "plus_rate", "n", "avg_rank_from_aisle"],
            ascending=[False, False, False, False, True],
        )
        best = grp.iloc[0]
        best_rows.append(
            {
                "section": str(section),
                "machine_name": str(machine_name),
                "best_phase": str(best["debut_phase"]),
                "best_avg_diff": float(best["avg_diff"]),
                "best_plus_rate": float(best["plus_rate"]),
                "phase_count": int(len(grp)),
                "positive_phase_count": int(grp["support_phase"].sum()),
                "best_n": int(best["n"]),
                "avg_rank_from_aisle": float(best["avg_rank_from_aisle"]),
            }
        )

    shortlist = pd.DataFrame(best_rows)
    shortlist["best_avg_diff"] = shortlist["best_avg_diff"].round(0).astype(int)
    shortlist["best_plus_rate"] = shortlist["best_plus_rate"].round(1)
    shortlist["avg_rank_from_aisle"] = shortlist["avg_rank_from_aisle"].round(1)
    shortlist = shortlist.sort_values(
        ["section", "best_avg_diff", "positive_phase_count", "best_n", "avg_rank_from_aisle"],
        ascending=[True, False, False, False, True],
        key=lambda col: col.map(section_sort_key) if col.name == "section" else col,
    ).reset_index(drop=True)
    shortlist = shortlist.groupby("section", as_index=False, sort=False).head(top_n).reset_index(drop=True)
    shortlist["section"] = shortlist["section"].astype(str)
    shortlist["rank"] = shortlist.groupby("section").cumcount() + 1
    return shortlist


def build_report(shortlist: pd.DataFrame) -> str:
    lines = [
        "# Mitoya Phase 7: machine_name Shortlist",
        "",
        "## 対象セクション",
        "",
        ", ".join(TARGET_SECTIONS),
        "",
        "## 残す machine_name",
        "",
        render_markdown_table(shortlist) if not shortlist.empty else "_no rows_",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ensure_results_dir()
    df = load_mitoya_frame(join_layout=True)
    shortlist = build_shortlist_table(df, TARGET_SECTIONS)
    OUTPUT_PATH.write_text(build_report(shortlist), encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
