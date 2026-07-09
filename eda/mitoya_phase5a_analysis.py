from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda.mitoya_phase3_screening import build_screening_tables
from eda.mitoya_phase4_durability import build_durability_table
from eda.mitoya_prompt_common import (
    RESULTS_DIR,
    bucket_rank_from_aisle,
    ensure_results_dir,
    load_mitoya_frame,
    render_markdown_table,
    section_sort_key,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


WEEKDAY_OUTPUT = RESULTS_DIR / "mitoya_phase5a_weekday.md"
INTERACTION_OUTPUT = RESULTS_DIR / "mitoya_phase5a_interactions.md"
HEATMAP_OUTPUT = RESULTS_DIR / "mitoya_dd_kakuban_heatmap.csv"


def _weekday_label_order(series: pd.Series) -> pd.Categorical:
    return pd.Categorical(series, categories=["月", "火", "水", "木", "金", "土", "日"], ordered=True)


def build_weekday_profile(df: pd.DataFrame, *, xday_only: bool) -> pd.DataFrame:
    work = df.copy()
    if xday_only:
        work = work.loc[~work["is_x_day"].eq(1)].copy()
    rows: list[dict[str, object]] = []
    scopes = [("ALL", work)] + [
        (str(section), section_df.copy()) for section, section_df in work.groupby("section", dropna=False)
    ]
    for section_label, scope in scopes:
        for weekday, weekday_df in scope.groupby("day_of_week", dropna=False):
            rows.append(
                {
                    "section": section_label,
                    "day_of_week": weekday,
                    "avg_payout": float(
                        ((weekday_df["games"] * 3 + weekday_df["diff"]) / (weekday_df["games"] * 3) * 100).mean()
                    ),
                    "avg_diff": float(weekday_df["diff"].mean()),
                    "rate_104": float(
                        (((weekday_df["games"] * 3 + weekday_df["diff"]) / (weekday_df["games"] * 3)) >= 1.04).mean()
                        * 100
                    ),
                    "n": int(len(weekday_df)),
                }
            )
    profile = pd.DataFrame(rows)
    if profile.empty:
        return profile
    profile["day_of_week"] = _weekday_label_order(profile["day_of_week"])
    profile = profile.sort_values(
        ["section", "day_of_week"], key=lambda col: col.map(section_sort_key) if col.name == "section" else col
    ).reset_index(drop=True)
    profile["avg_payout"] = profile["avg_payout"].round(2)
    profile["avg_diff"] = profile["avg_diff"].round(0).astype(int)
    profile["rate_104"] = profile["rate_104"].round(1)
    return profile


def build_dd_kakuban_heatmap(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work = work.dropna(subset=["section", "rank_from_aisle", "diff", "dd"]).copy()
    work["section_max_aisle"] = work.groupby("section")["rank_from_aisle"].transform("max")
    work["kakuban_bucket"] = work.apply(
        lambda row: bucket_rank_from_aisle(row["rank_from_aisle"], row["section_max_aisle"]), axis=1
    )
    work["dd_bucket"] = pd.cut(
        work["dd"],
        bins=[0, 6, 12, 18, 24, 31],
        labels=["DD1-6", "DD7-12", "DD13-18", "DD19-24", "DD25-31"],
        include_lowest=True,
        right=True,
    )
    rows: list[dict[str, object]] = []
    for section_label, section_df in [("ALL", work)] + [
        (str(section), part) for section, part in work.groupby("section", dropna=False)
    ]:
        for (dd_bucket, kakuban_bucket), grp in section_df.groupby(["dd_bucket", "kakuban_bucket"], dropna=False):
            if grp.empty:
                continue
            rows.append(
                {
                    "section": section_label,
                    "dd_bucket": str(dd_bucket),
                    "kakuban_bucket": int(kakuban_bucket) if pd.notna(kakuban_bucket) else None,
                    "mean_diff": float(grp["diff"].mean()),
                    "n": int(len(grp)),
                }
            )
    heatmap = pd.DataFrame(rows)
    if not heatmap.empty:
        heatmap["mean_diff"] = heatmap["mean_diff"].round(0).astype(int)
        heatmap["n"] = heatmap["n"].astype(int)
        heatmap = heatmap.sort_values(
            ["section", "dd_bucket", "kakuban_bucket"],
            key=lambda col: col.map(section_sort_key) if col.name == "section" else col,
        ).reset_index(drop=True)
    return heatmap


def build_last_digit_section_table(df: pd.DataFrame, robust_sections: list[str]) -> pd.DataFrame:
    work = df.copy()
    if robust_sections:
        work = work.loc[work["section"].astype(str).isin(robust_sections)].copy()
    if work.empty:
        work = df.copy()
    rows: list[dict[str, object]] = []
    for section, section_df in work.groupby("section", dropna=False):
        section_label = str(section)
        for digit, digit_df in section_df.groupby("machine_digit", dropna=False):
            rows.append(
                {
                    "section": section_label,
                    "machine_digit": digit,
                    "mean_diff": float(digit_df["diff"].mean()),
                    "n": int(len(digit_df)),
                }
            )
    table = pd.DataFrame(rows)
    if not table.empty:
        table["mean_diff"] = table["mean_diff"].round(0).astype(int)
        table["n"] = table["n"].astype(int)
        table = table.sort_values(
            ["section", "mean_diff"],
            ascending=[True, False],
            key=lambda col: col.map(section_sort_key) if col.name == "section" else col,
        ).reset_index(drop=True)
    return table


def build_reports(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    screening_summary, _ = build_screening_tables(df)
    durability_table, robust_sections = build_durability_table(df, screening_summary)
    weekday_all = build_weekday_profile(df, xday_only=False)
    weekday_non_event = build_weekday_profile(df, xday_only=True)
    heatmap = build_dd_kakuban_heatmap(df)
    last_digit = build_last_digit_section_table(df, robust_sections)
    return weekday_all, weekday_non_event, heatmap, last_digit


def build_report_text(title: str, table: pd.DataFrame, *, subtitle: str = "") -> str:
    lines = [f"# {title}", ""]
    if subtitle:
        lines.extend([subtitle, ""])
    lines.append(render_markdown_table(table) if not table.empty else "_no rows_")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ensure_results_dir()
    df = load_mitoya_frame(join_layout=True)
    screening_summary, _ = build_screening_tables(df)
    durability_table, robust_sections = build_durability_table(df, screening_summary)
    weekday_all = build_weekday_profile(df, xday_only=False)
    weekday_non_event = build_weekday_profile(df, xday_only=True)
    heatmap = build_dd_kakuban_heatmap(df)
    last_digit = build_last_digit_section_table(df, robust_sections)

    WEEKDAY_OUTPUT.write_text(
        "\n".join(
            [
                "# みとや大森町 Phase 5a: 曜日プロファイル",
                "",
                "## 全日版",
                "",
                render_markdown_table(weekday_all),
                "",
                "## イベント日除外版",
                "",
                render_markdown_table(weekday_non_event),
                "",
            ]
        ).rstrip()
        + "\n",
        encoding="utf-8",
    )
    INTERACTION_OUTPUT.write_text(
        "\n".join(
            [
                "# みとや大森町 Phase 5a: 交互作用分析",
                "",
                "## DD × 角番",
                "",
                render_markdown_table(heatmap),
                "",
                "## 末尾 × section",
                "",
                render_markdown_table(last_digit),
                "",
            ]
        ).rstrip()
        + "\n",
        encoding="utf-8",
    )
    heatmap.to_csv(HEATMAP_OUTPUT, index=False, encoding="utf-8-sig")
    print(f"Wrote {WEEKDAY_OUTPUT}")
    print(f"Wrote {INTERACTION_OUTPUT}")
    print(f"Wrote {HEATMAP_OUTPUT}")


if __name__ == "__main__":
    main()
