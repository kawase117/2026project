from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda.mitoya_prompt_common import (
    MITOYA_ALL_SECTIONS,
    RESULTS_DIR,
    add_debut_phase,
    ensure_results_dir,
    load_mitoya_frame,
    render_markdown_table,
    section_sort_key,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "mitoya_phase8_row_analysis"
TARGET_SECTIONS = MITOYA_ALL_SECTIONS
CORNER_BUCKETS: list[tuple[int, int | None, str]] = [
    (1, 1, "corner1"),
    (2, 4, "corner2-4"),
    (5, 9, "corner5-9"),
    (10, None, "corner10+"),
]


def _prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    for column in ("machine_number", "x", "y"):
        if column in work.columns:
            work[column] = pd.to_numeric(work[column], errors="coerce")
    if "is_reversed_section" in work.columns:
        work["is_reversed_section"] = pd.to_numeric(work["is_reversed_section"], errors="coerce").fillna(0).astype(int)
    else:
        work["is_reversed_section"] = 0
    return work


def _corner_bucket(rank: object) -> str:
    value = pd.to_numeric(pd.Series([rank]), errors="coerce").iloc[0]
    if pd.isna(value):
        return "unknown"
    int_value = int(value)
    for low, high, label in CORNER_BUCKETS:
        if high is None and int_value >= low:
            return label
        if high is not None and low <= int_value <= high:
            return label
    return "unknown"


def _section_orientation(section_grp: pd.DataFrame) -> str:
    x_nunique = int(section_grp["x"].nunique(dropna=True))
    y_nunique = int(section_grp["y"].nunique(dropna=True))
    if x_nunique == 1 and y_nunique > 1:
        return "vertical"
    return "horizontal"


def build_machine_layout_table(df: pd.DataFrame, *, sections: list[str] | None = None) -> pd.DataFrame:
    work = _prepare_frame(df)
    if sections is not None:
        work = work.loc[work["section"].astype(str).isin([str(section) for section in sections])].copy()
    work = work.dropna(subset=["section", "machine_number", "x", "y"]).copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "section",
                "machine_number",
                "machine_name",
                "x",
                "y",
                "row_order_in_section",
                "row_label",
                "row_corner_rank",
                "corner_bucket",
                "row_machine_count",
                "aisle_side_machine_number",
                "far_side_machine_number",
                "section_orientation",
            ]
        )

    rows: list[pd.DataFrame] = []
    for section, section_grp in work.groupby("section", dropna=False, sort=False):
        orientation = _section_orientation(section_grp)
        if orientation == "vertical":
            row = (
                section_grp.drop_duplicates(subset=["section", "machine_number"])
                .sort_values(
                    ["y", "machine_number"],
                    ascending=[False, True],
                    kind="mergesort",
                )
                .copy()
            )
            row["row_corner_rank"] = np.arange(1, len(row) + 1)
            row["corner_bucket"] = row["row_corner_rank"].map(_corner_bucket)
            row["row_order_in_section"] = 1
            row["row_label"] = str(section)
            row["row_machine_count"] = int(row["machine_number"].nunique())
            row["aisle_side_machine_number"] = int(row.iloc[0]["machine_number"])
            row["far_side_machine_number"] = int(row.iloc[-1]["machine_number"])
            row["section_orientation"] = orientation
            rows.append(
                row[
                    [
                        "section",
                        "machine_number",
                        "machine_name",
                        "x",
                        "y",
                        "row_order_in_section",
                        "row_label",
                        "row_corner_rank",
                        "corner_bucket",
                        "row_machine_count",
                        "aisle_side_machine_number",
                        "far_side_machine_number",
                        "section_orientation",
                    ]
                ]
            )
            continue

        y_order = {
            int(y): idx + 1
            for idx, y in enumerate(sorted(section_grp["y"].dropna().astype(int).unique(), reverse=True))
        }
        for y_value, row_grp in section_grp.groupby("y", dropna=False, sort=False):
            row = (
                row_grp.drop_duplicates(subset=["section", "machine_number"])
                .sort_values(
                    ["x", "machine_number"],
                    ascending=[True, True] if int(row_grp["is_reversed_section"].max()) == 0 else [False, False],
                    kind="mergesort",
                )
                .copy()
            )
            row["row_corner_rank"] = np.arange(1, len(row) + 1)
            row["corner_bucket"] = row["row_corner_rank"].map(_corner_bucket)
            row["row_order_in_section"] = int(y_order[int(y_value)])
            row["row_label"] = f"{int(row['machine_number'].min())}-{int(row['machine_number'].max())}"
            row["row_machine_count"] = int(row["machine_number"].nunique())
            row["aisle_side_machine_number"] = int(row.iloc[0]["machine_number"])
            row["far_side_machine_number"] = int(row.iloc[-1]["machine_number"])
            row["section_orientation"] = orientation
            rows.append(
                row[
                    [
                        "section",
                        "machine_number",
                        "machine_name",
                        "x",
                        "y",
                        "row_order_in_section",
                        "row_label",
                        "row_corner_rank",
                        "corner_bucket",
                        "row_machine_count",
                        "aisle_side_machine_number",
                        "far_side_machine_number",
                        "section_orientation",
                    ]
                ]
            )

    layout = pd.concat(rows, ignore_index=True)
    layout["section"] = layout["section"].astype(str)
    layout["row_label"] = layout["row_label"].astype(str)
    layout = layout.drop_duplicates(subset=["section", "machine_number"]).copy()
    return layout.sort_values(
        ["section", "row_order_in_section", "row_corner_rank", "machine_number"],
        ascending=[True, True, True, True],
        kind="mergesort",
    ).reset_index(drop=True)


def build_section_row_map(df: pd.DataFrame, *, sections: list[str] | None = None) -> pd.DataFrame:
    layout = build_machine_layout_table(df, sections=sections)
    if layout.empty:
        return pd.DataFrame(
            columns=[
                "section",
                "row_order_in_section",
                "y",
                "row_label",
                "row_machine_count",
                "aisle_side_machine_number",
                "far_side_machine_number",
                "x_min",
                "x_max",
                "section_orientation",
            ]
        )
    rows: list[dict[str, object]] = []
    for section, sec_grp in layout.groupby("section", dropna=False, sort=False):
        orientation = (
            str(sec_grp["section_orientation"].iloc[0]) if "section_orientation" in sec_grp.columns else "horizontal"
        )
        if orientation == "vertical":
            sorted_grp = sec_grp.sort_values(["row_corner_rank", "machine_number"], kind="mergesort")
            rows.append(
                {
                    "section": str(section),
                    "row_order_in_section": 1,
                    "y": int(sorted_grp["y"].max()),
                    "row_label": str(section),
                    "row_machine_count": int(sorted_grp["machine_number"].nunique()),
                    "aisle_side_machine_number": int(sorted_grp.iloc[0]["aisle_side_machine_number"]),
                    "far_side_machine_number": int(sorted_grp.iloc[0]["far_side_machine_number"]),
                    "x_min": int(sorted_grp["x"].min()),
                    "x_max": int(sorted_grp["x"].max()),
                    "section_orientation": orientation,
                }
            )
            continue

        grouped = (
            sec_grp.groupby(["section", "row_order_in_section", "y", "row_label"], as_index=False)
            .agg(
                row_machine_count=("machine_number", "nunique"),
                aisle_side_machine_number=("aisle_side_machine_number", "first"),
                far_side_machine_number=("far_side_machine_number", "first"),
                x_min=("x", "min"),
                x_max=("x", "max"),
                section_orientation=("section_orientation", "first"),
            )
            .sort_values(["section", "row_order_in_section"], kind="mergesort")
            .reset_index(drop=True)
        )
        rows.extend(grouped.to_dict("records"))
    return pd.DataFrame(rows)


def _with_row_metadata(df: pd.DataFrame, *, sections: list[str] | None = None) -> pd.DataFrame:
    work = add_debut_phase(df.copy())
    layout = build_machine_layout_table(df, sections=sections)
    merged = work.merge(
        layout[
            [
                "section",
                "machine_number",
                "row_order_in_section",
                "row_label",
                "row_corner_rank",
                "corner_bucket",
            ]
        ],
        on=["section", "machine_number"],
        how="inner",
        validate="many_to_one",
    )
    return merged


def build_row_machine_phase_table(df: pd.DataFrame, *, sections: list[str] | None = None) -> pd.DataFrame:
    work = _with_row_metadata(df, sections=sections)
    if sections is not None:
        work = work.loc[work["section"].astype(str).isin([str(section) for section in sections])].copy()
    work = work.dropna(subset=["section", "row_label", "machine_name", "debut_phase", "diff"]).copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "section",
                "row_label",
                "machine_name",
                "debut_phase",
                "avg_diff",
                "plus_rate",
                "n",
                "avg_corner_rank",
            ]
        )

    rows: list[dict[str, object]] = []
    for (section, row_label, machine_name, debut_phase), grp in work.groupby(
        ["section", "row_label", "machine_name", "debut_phase"], dropna=False
    ):
        rows.append(
            {
                "section": str(section),
                "row_label": str(row_label),
                "machine_name": str(machine_name),
                "debut_phase": str(debut_phase),
                "avg_diff": float(grp["diff"].mean()),
                "plus_rate": float((grp["diff"] > 0).mean() * 100),
                "n": int(len(grp)),
                "avg_corner_rank": float(grp["row_corner_rank"].mean()),
            }
        )

    table = pd.DataFrame(rows)
    table["avg_diff"] = table["avg_diff"].round(0).astype(int)
    table["plus_rate"] = table["plus_rate"].round(1)
    table["avg_corner_rank"] = table["avg_corner_rank"].round(1)
    return table.sort_values(
        ["section", "row_label", "avg_diff", "plus_rate", "n"],
        ascending=[True, True, False, False, False],
        key=lambda col: col.map(section_sort_key) if col.name == "section" else col,
        kind="mergesort",
    ).reset_index(drop=True)


def build_row_corner_summary(df: pd.DataFrame, *, sections: list[str] | None = None) -> pd.DataFrame:
    work = _with_row_metadata(df, sections=sections)
    if sections is not None:
        work = work.loc[work["section"].astype(str).isin([str(section) for section in sections])].copy()
    work = work.dropna(subset=["section", "row_label", "row_corner_rank", "diff"]).copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "section",
                "row_label",
                "corner_rank",
                "avg_diff",
                "plus_rate",
                "n",
            ]
        )

    rows: list[dict[str, object]] = []
    for (section, row_label, corner_rank), grp in work.groupby(
        ["section", "row_label", "row_corner_rank"], dropna=False
    ):
        rows.append(
            {
                "section": str(section),
                "row_label": str(row_label),
                "corner_rank": int(corner_rank),
                "avg_diff": float(grp["diff"].mean()),
                "plus_rate": float((grp["diff"] > 0).mean() * 100),
                "n": int(len(grp)),
            }
        )
    table = pd.DataFrame(rows)
    table["avg_diff"] = table["avg_diff"].round(0).astype(int)
    table["plus_rate"] = table["plus_rate"].round(1)
    return table.sort_values(
        ["section", "row_label", "corner_rank"],
        ascending=[True, True, True],
        key=lambda col: col.map(section_sort_key) if col.name == "section" else col,
        kind="mergesort",
    ).reset_index(drop=True)


def build_row_corner_bucket_summary(df: pd.DataFrame, *, sections: list[str] | None = None) -> pd.DataFrame:
    work = _with_row_metadata(df, sections=sections)
    if sections is not None:
        work = work.loc[work["section"].astype(str).isin([str(section) for section in sections])].copy()
    work = work.dropna(subset=["section", "row_label", "corner_bucket", "diff"]).copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "section",
                "row_label",
                "corner_bucket",
                "avg_diff",
                "plus_rate",
                "n",
            ]
        )

    rows: list[dict[str, object]] = []
    for (section, row_label, corner_bucket), grp in work.groupby(
        ["section", "row_label", "corner_bucket"], dropna=False
    ):
        rows.append(
            {
                "section": str(section),
                "row_label": str(row_label),
                "corner_bucket": str(corner_bucket),
                "avg_diff": float(grp["diff"].mean()),
                "plus_rate": float((grp["diff"] > 0).mean() * 100),
                "n": int(len(grp)),
            }
        )
    table = pd.DataFrame(rows)
    table["avg_diff"] = table["avg_diff"].round(0).astype(int)
    table["plus_rate"] = table["plus_rate"].round(1)
    bucket_order = {label: idx for idx, (_, _, label) in enumerate(CORNER_BUCKETS, start=1)}
    table["corner_bucket"] = pd.Categorical(
        table["corner_bucket"], categories=[label for _, _, label in CORNER_BUCKETS], ordered=True
    )
    table = table.sort_values(
        ["section", "row_label", "corner_bucket"],
        ascending=[True, True, True],
        key=lambda col: col.map(section_sort_key) if col.name == "section" else col,
        kind="mergesort",
    ).reset_index(drop=True)
    table["corner_bucket"] = table["corner_bucket"].astype(str)
    return table


def build_machine_corner_interaction(df: pd.DataFrame, *, sections: list[str] | None = None) -> pd.DataFrame:
    work = _with_row_metadata(df, sections=sections)
    if sections is not None:
        work = work.loc[work["section"].astype(str).isin([str(section) for section in sections])].copy()
    work = work.dropna(subset=["section", "row_label", "machine_name", "corner_bucket", "diff"]).copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "section",
                "row_label",
                "machine_name",
                "corner_bucket",
                "avg_diff",
                "plus_rate",
                "n",
            ]
        )

    rows: list[dict[str, object]] = []
    for (section, row_label, machine_name, corner_bucket), grp in work.groupby(
        ["section", "row_label", "machine_name", "corner_bucket"], dropna=False
    ):
        rows.append(
            {
                "section": str(section),
                "row_label": str(row_label),
                "machine_name": str(machine_name),
                "corner_bucket": str(corner_bucket),
                "avg_diff": float(grp["diff"].mean()),
                "plus_rate": float((grp["diff"] > 0).mean() * 100),
                "n": int(len(grp)),
            }
        )
    table = pd.DataFrame(rows)
    table["avg_diff"] = table["avg_diff"].round(0).astype(int)
    table["plus_rate"] = table["plus_rate"].round(1)
    return table.sort_values(
        ["section", "row_label", "avg_diff", "plus_rate", "n"],
        ascending=[True, True, False, False, False],
        key=lambda col: col.map(section_sort_key) if col.name == "section" else col,
        kind="mergesort",
    ).reset_index(drop=True)


def build_report(
    row_map: pd.DataFrame,
    row_machine_phase: pd.DataFrame,
    row_corner_summary: pd.DataFrame,
    row_corner_bucket_summary: pd.DataFrame,
    machine_corner_interaction: pd.DataFrame,
    *,
    source_latest_date: str,
) -> str:
    lines = [
        "# Mitoya Phase 8: row / corner analysis",
        "",
        f"- source_latest_date: {source_latest_date}",
        f"- target_sections: {', '.join(TARGET_SECTIONS)}",
        "",
        "## row map",
        "",
        render_markdown_table(row_map) if not row_map.empty else "_no rows_",
        "",
        "## machine_name x debut_phase",
        "",
        render_markdown_table(row_machine_phase.head(40)) if not row_machine_phase.empty else "_no rows_",
        "",
        "## corner rank",
        "",
        render_markdown_table(row_corner_summary.head(40)) if not row_corner_summary.empty else "_no rows_",
        "",
        "## corner bucket",
        "",
        render_markdown_table(row_corner_bucket_summary.head(40))
        if not row_corner_bucket_summary.empty
        else "_no rows_",
        "",
        "## machine_name x corner bucket",
        "",
        render_markdown_table(machine_corner_interaction.head(40))
        if not machine_corner_interaction.empty
        else "_no rows_",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def build_all_artifacts(df: pd.DataFrame, *, sections: list[str] | None = None) -> dict[str, pd.DataFrame | str]:
    work = _prepare_frame(df)
    if "date" in work.columns:
        work["date_dt"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
        latest_date = work["date_dt"].max()
        source_latest_date = latest_date.strftime("%Y%m%d") if pd.notna(latest_date) else "unknown"
    else:
        source_latest_date = "unknown"
    section_rows = build_section_row_map(work, sections=sections)
    row_machine_phase = build_row_machine_phase_table(work, sections=sections)
    row_corner_summary = build_row_corner_summary(work, sections=sections)
    row_corner_bucket_summary = build_row_corner_bucket_summary(work, sections=sections)
    machine_corner_interaction = build_machine_corner_interaction(work, sections=sections)
    report = build_report(
        section_rows,
        row_machine_phase,
        row_corner_summary,
        row_corner_bucket_summary,
        machine_corner_interaction,
        source_latest_date=source_latest_date,
    )
    return {
        "section_row_map": section_rows,
        "row_machine_phase": row_machine_phase,
        "row_corner_summary": row_corner_summary,
        "row_corner_bucket_summary": row_corner_bucket_summary,
        "machine_corner_interaction": machine_corner_interaction,
        "report": report,
    }


def save_outputs(artifacts: dict[str, pd.DataFrame | str], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    cast = artifacts  # local alias for readability
    cast["section_row_map"].to_csv(output_dir / "section_row_map.csv", index=False, encoding="utf-8-sig")
    cast["row_machine_phase"].to_csv(output_dir / "row_machine_phase.csv", index=False, encoding="utf-8-sig")
    cast["row_corner_summary"].to_csv(output_dir / "row_corner_summary.csv", index=False, encoding="utf-8-sig")
    cast["row_corner_bucket_summary"].to_csv(
        output_dir / "row_corner_bucket_summary.csv", index=False, encoding="utf-8-sig"
    )
    cast["machine_corner_interaction"].to_csv(
        output_dir / "machine_corner_interaction.csv", index=False, encoding="utf-8-sig"
    )
    (output_dir / "report.md").write_text(str(cast["report"]), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--sections", nargs="*", default=TARGET_SECTIONS)
    return parser.parse_args()


def main() -> None:
    ensure_results_dir()
    args = parse_args()
    df = load_mitoya_frame(join_layout=True)
    artifacts = build_all_artifacts(df, sections=[str(section) for section in args.sections])
    save_outputs(artifacts, args.output_dir)
    print(f"Wrote {args.output_dir}")


if __name__ == "__main__":
    main()
