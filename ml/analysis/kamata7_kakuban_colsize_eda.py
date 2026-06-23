from __future__ import annotations

import argparse
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ is None or __package__ == "":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.analysis.kamata_kakuban_section_residual_eda import (
    DEFAULT_MIN_GAMES_ANALYSIS,
    DEFAULT_MIN_SECTION_SIZE,
    SegmentSpec,
    _bh_adjust,
    _df_to_markdown,
    _expand_dual_kakuban,
    _kruskal_pvalue,
    _prepare_segment_frame,
    _write_csv,
    infer_hall_name,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_7 = PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田7.db"
DEFAULT_COORDS_7_2F = PROJECT_ROOT / "Heatmap" / "2F_floor_coordinates_kamata7.csv"
DEFAULT_COORDS_7_3F = PROJECT_ROOT / "Heatmap" / "3F_floor_coordinates_kamata7.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "ml" / "analysis" / "results" / "kamata7_kakuban_colsize_eda"
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "report.md"
DEFAULT_MAX_KAKUBAN = 20

COLUMN_SIZE_BINS = (
    ("short", 3, 10),
    ("medium", 11, 15),
    ("long", 16, 10**9),
)


@dataclass(frozen=True)
class SegmentRun:
    spec: SegmentSpec
    col_size_bin: str
    segment_label: str
    segment_key: str
    frame: pd.DataFrame
    expanded: pd.DataFrame
    eligible: pd.DataFrame
    support: pd.Series


def _column_size_bin(column_size: object) -> str | None:
    if pd.isna(column_size):
        return None
    size = int(column_size)
    if size <= 2:
        return None
    for label, lower, upper in COLUMN_SIZE_BINS:
        if lower <= size <= upper:
            return label
    return None


def _format_number(value: object, digits: int = 3) -> str:
    if pd.isna(value):
        return "nan"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.{digits}f}"
    return str(value)


def _table_md(df: pd.DataFrame) -> str:
    if df.empty:
        return "No rows."
    return _df_to_markdown(df)


def _filter_by_support_sections(df: pd.DataFrame, min_support_sections: int) -> pd.DataFrame:
    if df.empty or "support_sections" not in df.columns:
        return df.copy()
    support = pd.to_numeric(df["support_sections"], errors="coerce")
    return df[support.ge(min_support_sections)].copy()


def _build_segment_key(*, hall_slug: str, floor: str, col_size_bin: str, segment_label: str) -> str:
    return f"{hall_slug}_{floor}_{col_size_bin}_{segment_label}"


def _load_coords_with_colsize(coords_path: Path, floor: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    coords = pd.read_csv(coords_path)
    required = {"hall_name", "floor", "machine_number", "X", "Y", "section", "section_min", "section_max"}
    missing = required - set(coords.columns)
    if missing:
        raise ValueError(f"Missing coordinate columns in {coords_path}: {sorted(missing)}")

    coords = coords[coords["floor"] == floor].copy()
    if coords.empty:
        raise ValueError(f"No coordinates found for floor={floor!r} in {coords_path}")

    for column in ("machine_number", "X", "Y", "section_min", "section_max"):
        coords[column] = pd.to_numeric(coords[column], errors="coerce")
    coords = coords.dropna(subset=["machine_number", "X", "Y", "section_min", "section_max"]).copy()
    coords["machine_number"] = coords["machine_number"].astype(int)
    coords["X"] = coords["X"].astype(int)
    coords["Y"] = coords["Y"].astype(int)
    coords["section_min"] = coords["section_min"].astype(int)
    coords["section_max"] = coords["section_max"].astype(int)
    coords["section"] = coords["section"].fillna("unknown").astype(str)

    coords["column_size"] = coords["section_max"] - coords["section_min"] + 1
    coords = coords[coords["column_size"].gt(2)].copy()
    if coords.empty:
        raise ValueError(f"All coordinates were excluded by column_size <= 2 for floor={floor!r}")

    coords["column_size"] = coords["column_size"].astype(int)
    coords["column_size_bin"] = coords["column_size"].map(_column_size_bin)
    coords = coords[coords["column_size_bin"].notna()].copy()
    if coords.empty:
        raise ValueError(f"No coordinates remained after column_size binning for floor={floor!r}")

    summary = (
        coords.groupby("column_size_bin", as_index=False)
        .agg(
            column_size_values=("column_size", lambda s: ",".join(str(v) for v in sorted(pd.unique(s.astype(int))))),
            sections=("section", "nunique"),
            machines=("machine_number", "nunique"),
        )
        .sort_values("column_size_bin", key=lambda s: s.map({"short": 0, "medium": 1, "long": 2}))
        .reset_index(drop=True)
    )

    return coords.reset_index(drop=True), summary


def _write_augmented_coords(*, coords_path: Path, floor: str, temp_dir: Path) -> tuple[Path, pd.DataFrame]:
    coords, summary = _load_coords_with_colsize(coords_path, floor)
    temp_path = temp_dir / f"{coords_path.stem}_{floor}_colsize.csv"
    coords.to_csv(temp_path, index=False, encoding="utf-8-sig")
    return temp_path, summary


def _build_segment_run(
    spec: SegmentSpec,
    *,
    col_size_bin: str,
    segment_label: str,
    min_games: int,
    min_section_size: int,
    max_kakuban: int,
    coords_path: Path,
) -> SegmentRun:
    frame_spec = SegmentSpec(
        hall_slug=spec.hall_slug,
        hall_name=spec.hall_name,
        floor=spec.floor,
        db_path=spec.db_path,
        coords_path=coords_path,
    )
    base = _prepare_segment_frame(frame_spec, min_games=min_games, min_section_size=min_section_size).copy()
    segment_key = _build_segment_key(
        hall_slug=spec.hall_slug,
        floor=spec.floor,
        col_size_bin=col_size_bin,
        segment_label=segment_label,
    )
    if base.empty:
        return SegmentRun(
            spec=spec,
            col_size_bin=col_size_bin,
            segment_label=segment_label,
            segment_key=segment_key,
            frame=base,
            expanded=base,
            eligible=base,
            support=pd.Series(dtype=int),
        )

    base["column_size_bin"] = base["column_size_bin"].astype(str)
    base["machine_type_segment"] = base["machine_type_segment"].astype(str)
    base = base[base["column_size_bin"].eq(col_size_bin) & base["machine_type_segment"].eq(segment_label)].copy()
    if base.empty:
        return SegmentRun(
            spec=spec,
            col_size_bin=col_size_bin,
            segment_label=segment_label,
            segment_key=segment_key,
            frame=base,
            expanded=base,
            eligible=base,
            support=pd.Series(dtype=int),
        )

    base["dd"] = pd.to_datetime(base["date"], errors="coerce").dt.day.astype("Int64")
    base = base[base["dd"].notna()].copy()
    base["dd"] = base["dd"].astype(int)

    expanded = _expand_dual_kakuban(base)
    expanded["kakuban"] = pd.to_numeric(expanded["kakuban"], errors="coerce").astype("Int64")
    expanded = expanded[expanded["kakuban"].notna() & expanded["kakuban"].le(max_kakuban)].copy()
    if expanded.empty:
        return SegmentRun(
            spec=spec,
            col_size_bin=col_size_bin,
            segment_label=segment_label,
            segment_key=segment_key,
            frame=base,
            expanded=expanded,
            eligible=expanded,
            support=pd.Series(dtype=int),
        )

    expanded["kakuban"] = expanded["kakuban"].astype(int)
    expanded["dd"] = pd.to_numeric(expanded["dd"], errors="coerce").astype("Int64")
    expanded = expanded[expanded["dd"].notna()].copy()
    expanded["dd"] = expanded["dd"].astype(int)
    expanded["residual"] = pd.to_numeric(expanded["residual"], errors="coerce")
    expanded["residual_eligible"] = expanded["residual_eligible"].astype(bool)

    segment_frame = expanded[expanded["residual_eligible"]].copy()
    if segment_frame.empty:
        return SegmentRun(
            spec=spec,
            col_size_bin=col_size_bin,
            segment_label=segment_label,
            segment_key=segment_key,
            frame=base,
            expanded=expanded,
            eligible=segment_frame,
            support=pd.Series(dtype=int),
        )

    eligible = segment_frame[segment_frame["residual"].notna()].copy()
    if eligible.empty:
        return SegmentRun(
            spec=spec,
            col_size_bin=col_size_bin,
            segment_label=segment_label,
            segment_key=segment_key,
            frame=base,
            expanded=expanded,
            eligible=eligible,
            support=pd.Series(dtype=int),
        )

    support = eligible.groupby("kakuban")["section"].nunique()
    eligible = eligible.merge(
        support.rename("support_sections").reset_index(),
        on="kakuban",
        how="left",
        validate="many_to_one",
    )
    eligible["support_sections"] = pd.to_numeric(eligible["support_sections"], errors="coerce").fillna(0).astype(int)
    return SegmentRun(
        spec=spec,
        col_size_bin=col_size_bin,
        segment_label=segment_label,
        segment_key=segment_key,
        frame=base,
        expanded=expanded,
        eligible=eligible,
        support=support,
    )


def _build_kakuban_table(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=["kakuban", "mean_residual", "median_residual", "n", "support_sections", "kruskal_p", "kruskal_q"]
        )

    rows: list[dict[str, object]] = []
    support = frame.groupby("kakuban")["section"].nunique()
    for kakuban_value, kakuban_df in frame.groupby("kakuban", sort=True):
        own = kakuban_df["residual"].astype(float)
        rest = frame.loc[~frame["kakuban"].eq(kakuban_value), "residual"].astype(float)
        p_value = _kruskal_pvalue([own, rest])
        rows.append(
            {
                "kakuban": int(kakuban_value),
                "mean_residual": float(own.mean()),
                "median_residual": float(own.median()),
                "n": int(len(own)),
                "support_sections": int(support.get(kakuban_value, 0)),
                "kruskal_p": p_value,
            }
        )

    out = pd.DataFrame(rows)
    out["kruskal_q"] = _bh_adjust(out["kruskal_p"])
    out = out.sort_values(["kruskal_q", "kakuban"], na_position="last").reset_index(drop=True)
    return out


def _summarize_segment(run: SegmentRun, table: pd.DataFrame) -> dict[str, object]:
    if run.eligible.empty or table.empty:
        return {
            "segment": run.segment_key,
            "floor": run.spec.floor,
            "column_size_bin": run.col_size_bin,
            "machine_type": run.segment_label,
            "rows": int(len(run.frame)),
            "expanded_rows": int(len(run.expanded)),
            "eligible_rows": int(len(run.eligible)),
            "sections": int(run.frame["section"].nunique()) if "section" in run.frame.columns else 0,
            "dates": int(pd.Index(run.frame["date"].dropna().unique()).size) if "date" in run.frame.columns else 0,
            "kakuban_rows": 0,
            "significant_kakuban": 0,
            "mean_abs_residual": np.nan,
            "mean_abs_mean_residual": np.nan,
            "median_abs_mean_residual": np.nan,
            "top_kakuban": np.nan,
            "top_support_sections": np.nan,
            "top_mean_residual": np.nan,
            "top_kruskal_q": np.nan,
            "column_sizes": "",
        }

    significant = table[pd.to_numeric(table["kruskal_q"], errors="coerce").lt(0.05)].copy()
    top_row = table.loc[table["mean_residual"].abs().sort_values(ascending=False).index].iloc[0]
    return {
        "segment": run.segment_key,
        "floor": run.spec.floor,
        "column_size_bin": run.col_size_bin,
        "machine_type": run.segment_label,
        "rows": int(len(run.frame)),
        "expanded_rows": int(len(run.expanded)),
        "eligible_rows": int(len(run.eligible)),
        "sections": int(run.frame["section"].nunique()) if "section" in run.frame.columns else 0,
        "dates": int(pd.Index(run.frame["date"].dropna().unique()).size) if "date" in run.frame.columns else 0,
        "kakuban_rows": int(len(table)),
        "significant_kakuban": int(len(significant)),
        "mean_abs_residual": float(run.eligible["residual"].abs().mean()),
        "mean_abs_mean_residual": float(table["mean_residual"].abs().mean()),
        "median_abs_mean_residual": float(table["mean_residual"].abs().median()),
        "top_kakuban": int(top_row["kakuban"]),
        "top_support_sections": int(top_row["support_sections"]),
        "top_mean_residual": float(top_row["mean_residual"]),
        "top_kruskal_q": float(top_row["kruskal_q"]),
        "column_sizes": "",
    }


def _format_column_sizes(summary: pd.DataFrame) -> dict[str, str]:
    if summary.empty:
        return {}
    return {
        str(row["column_size_bin"]): f'{row["column_size_values"]} (sections={int(row["sections"])}, machines={int(row["machines"])})'
        for _, row in summary.iterrows()
    }


def _build_report(
    *,
    coverage: pd.DataFrame,
    segment_tables: dict[str, pd.DataFrame],
    segment_meta: pd.DataFrame,
    all_rows: pd.DataFrame,
    segment_summary: pd.DataFrame,
    bin_summary: pd.DataFrame,
    min_support_sections: int,
) -> str:
    lines: list[str] = []
    lines.extend(
        [
            "# Kamata7 kakuban column-size residual EDA report",
            "",
            "Section residual = `diff_coins_normalized - section_mean`.",
            "Rows from section-days with fewer than 3 machines are excluded from residual analysis by setting the residual to NaN.",
            "Column-size bins are built from section size (`section_max - section_min + 1`) after removing special sections with `column_size <= 2`.",
            f"support_sections filter: `>= {min_support_sections}`",
            "",
            "## 1. Segment coverage",
            "",
            _table_md(coverage),
            "",
            "## 2. Section-size map by floor",
            "",
            _table_md(segment_meta),
            "",
        ]
    )

    for _, row in segment_summary.iterrows():
        segment_key = str(row["segment"])
        table = _filter_by_support_sections(segment_tables.get(segment_key, pd.DataFrame()), min_support_sections)
        sig = table[pd.to_numeric(table["kruskal_q"], errors="coerce").lt(0.05)].copy() if not table.empty else table
        lines.extend(
            [
                f"## 3. Segment: {segment_key}",
                "",
                f"- rows: `{int(row['rows'])}`",
                f"- eligible_rows: `{int(row['eligible_rows'])}`",
                f"- kakuban_rows: `{int(row['kakuban_rows'])}`",
                f"- significant_kakuban: `{int(row['significant_kakuban'])}`",
                f"- mean_abs_residual: `{_format_number(row['mean_abs_residual'])}`",
                f"- mean_abs_mean_residual: `{_format_number(row['mean_abs_mean_residual'])}`",
                f"- top_kakuban: `{_format_number(row['top_kakuban'])}`",
                f"- top_support_sections: `{_format_number(row['top_support_sections'])}`",
                f"- top_mean_residual: `{_format_number(row['top_mean_residual'])}`",
                f"- top_kruskal_q: `{_format_number(row['top_kruskal_q'])}`",
                "",
                "### kakuban distribution",
                "",
                _table_md(table),
                "",
                "### significant kakuban rows (q < 0.05)",
                "",
            ]
        )
        lines.append(_table_md(sig))
        lines.append("")

    lines.extend(
        [
            "## 4. Cross-bin comparison",
            "",
            _table_md(bin_summary),
            "",
            "## 5. All significant kakuban rows",
            "",
            _df_to_markdown(all_rows[pd.to_numeric(all_rows["kruskal_q"], errors="coerce").lt(0.05)].copy())
            if not all_rows.empty
            else "No significant rows.",
            "",
        ]
    )

    long_only_note = ""
    if not all_rows.empty and "column_size_bin" in all_rows.columns:
        high = all_rows[pd.to_numeric(all_rows["kakuban"], errors="coerce").ge(15)].copy()
        if not high.empty and set(high["column_size_bin"].dropna().astype(str).unique().tolist()) == {"long"}:
            long_only_note = (
                "kakuban >= 15 appeared only in long bins in this run, so the long-bin signal may be "
                "partly dependent on a single-column regime rather than a shared short/medium pattern."
            )

    lines.extend(
        [
            "## 6. Notes",
            "",
            "- short / medium / long rows are all included above at segment coverage level.",
            "- The primary cross-bin comparison uses row-level `mean_abs_residual`; `mean_abs_mean_residual` is shown alongside it as a kakuban-summary check.",
        ]
    )
    if long_only_note:
        lines.append(f"- {long_only_note}")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def run_analysis(
    *,
    specs: list[SegmentSpec],
    output_dir: Path,
    report_path: Path,
    min_games: int,
    min_section_size: int,
    max_kakuban: int,
    min_support_sections: int,
) -> dict[str, pd.DataFrame]:
    output_dir.mkdir(parents=True, exist_ok=True)

    coverage_rows: list[dict[str, object]] = []
    segment_meta_rows: list[dict[str, object]] = []
    segment_summary_rows: list[dict[str, object]] = []
    all_tables: list[pd.DataFrame] = []
    segment_tables: dict[str, pd.DataFrame] = {}

    with tempfile.TemporaryDirectory(prefix="kamata7_kakuban_colsize_", dir=output_dir) as tmp_dir:
        temp_dir = Path(tmp_dir)
        for spec in specs:
            coords_path, column_size_summary = _write_augmented_coords(coords_path=spec.coords_path, floor=spec.floor, temp_dir=temp_dir)
            size_map = _format_column_sizes(column_size_summary)
            segment_meta_rows.append(
                {
                    "floor": spec.floor,
                    "column_size_bin": "short",
                    "column_sizes": size_map.get("short", ""),
                }
            )
            segment_meta_rows.append(
                {
                    "floor": spec.floor,
                    "column_size_bin": "medium",
                    "column_sizes": size_map.get("medium", ""),
                }
            )
            segment_meta_rows.append(
                {
                    "floor": spec.floor,
                    "column_size_bin": "long",
                    "column_sizes": size_map.get("long", ""),
                }
            )

            for col_size_bin in ("short", "medium", "long"):
                for segment_label in ("N", "A"):
                    run = _build_segment_run(
                        spec,
                        col_size_bin=col_size_bin,
                        segment_label=segment_label,
                        min_games=min_games,
                        min_section_size=min_section_size,
                        max_kakuban=max_kakuban,
                        coords_path=coords_path,
                    )

                    coverage_rows.append(
                        {
                            "segment": run.segment_key,
                            "hall": spec.hall_slug,
                            "floor": spec.floor,
                            "column_size_bin": col_size_bin,
                            "machine_type": segment_label,
                            "rows": int(len(run.frame)),
                            "expanded_rows": int(len(run.expanded)),
                            "eligible_rows": int(len(run.eligible)),
                            "dates": int(pd.Index(run.frame["date"].dropna().unique()).size) if "date" in run.frame.columns else 0,
                            "sections": int(run.frame["section"].nunique()) if "section" in run.frame.columns else 0,
                        }
                    )

                    table = _filter_by_support_sections(_build_kakuban_table(run.eligible), min_support_sections)
                    segment_tables[run.segment_key] = table
                    segment_summary_rows.append(_summarize_segment(run, table) | {"column_sizes": size_map.get(col_size_bin, "")})
                    if not table.empty:
                        all_tables.append(table.assign(segment=run.segment_key, floor=spec.floor, column_size_bin=col_size_bin, machine_type=segment_label))

    coverage = pd.DataFrame(coverage_rows)
    segment_meta = pd.DataFrame(segment_meta_rows)
    segment_summary = pd.DataFrame(segment_summary_rows)
    all_rows = pd.concat(all_tables, ignore_index=True) if all_tables else pd.DataFrame(
        columns=[
            "kakuban",
            "mean_residual",
            "median_residual",
            "n",
            "support_sections",
            "kruskal_p",
            "kruskal_q",
            "segment",
            "floor",
            "column_size_bin",
            "machine_type",
        ]
    )

    if all_rows.empty:
        bin_summary = pd.DataFrame(
            columns=[
                "column_size_bin",
                "rows",
                "eligible_rows",
                "kakuban_rows",
                "significant_kakuban",
                "mean_abs_residual",
                "mean_abs_mean_residual",
                "median_abs_mean_residual",
                "top_kakuban",
                "note",
            ]
        )
    else:
        bin_rows: list[dict[str, object]] = []
        for bin_label in ("short", "medium", "long"):
            block = segment_summary[segment_summary["column_size_bin"].eq(bin_label)].copy()
            if block.empty:
                bin_rows.append(
                    {
                        "column_size_bin": bin_label,
                        "rows": 0,
                        "eligible_rows": 0,
                        "kakuban_rows": 0,
                        "significant_kakuban": 0,
                        "mean_abs_residual": np.nan,
                        "mean_abs_mean_residual": np.nan,
                        "median_abs_mean_residual": np.nan,
                        "top_kakuban": np.nan,
                        "note": "",
                    }
                )
                continue

            valid_block = block[pd.to_numeric(block["mean_abs_residual"], errors="coerce").notna()].copy()
            if valid_block.empty:
                top = block.iloc[0]
                weighted_mean_abs = np.nan
                mean_abs_mean_residual = np.nan
            else:
                top = valid_block.loc[valid_block["mean_abs_residual"].sort_values(ascending=False).index].iloc[0]
                row_weights = valid_block["eligible_rows"].astype(float)
                weighted_mean_abs = (
                    float(np.average(valid_block["mean_abs_residual"], weights=row_weights))
                    if row_weights.sum()
                    else np.nan
                )
                kakuban_weights = valid_block["kakuban_rows"].astype(float)
                mean_abs_mean_residual = (
                    float(np.average(valid_block["mean_abs_mean_residual"], weights=kakuban_weights))
                    if kakuban_weights.sum()
                    else np.nan
                )
            eligible_rows = int(block["eligible_rows"].sum())
            note = ""
            if bin_label == "long":
                note = "high-kakuban concentration requires caution"
            bin_rows.append(
                {
                    "column_size_bin": bin_label,
                    "rows": int(block["rows"].sum()),
                    "eligible_rows": eligible_rows,
                    "kakuban_rows": int(block["kakuban_rows"].sum()),
                    "significant_kakuban": int(block["significant_kakuban"].sum()),
                    "mean_abs_residual": weighted_mean_abs,
                    "mean_abs_mean_residual": mean_abs_mean_residual,
                    "median_abs_mean_residual": float(block["median_abs_mean_residual"].median()),
                    "top_kakuban": int(top["top_kakuban"]),
                    "note": note,
                }
            )
        bin_summary = pd.DataFrame(bin_rows)

    report = _build_report(
        coverage=coverage,
        segment_tables=segment_tables,
        segment_meta=segment_meta,
        all_rows=all_rows,
        segment_summary=segment_summary,
        bin_summary=bin_summary,
        min_support_sections=min_support_sections,
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    return {
        "coverage": coverage,
        "segment_meta": segment_meta,
        "segment_summary": segment_summary,
        "all_rows": all_rows,
        "bin_summary": bin_summary,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kamata7 kakuban column-size residual EDA.")
    parser.add_argument("--db7", type=Path, default=DEFAULT_DB_7)
    parser.add_argument("--coords-2f", dest="coords_2f", type=Path, default=DEFAULT_COORDS_7_2F)
    parser.add_argument("--coords-3f", dest="coords_3f", type=Path, default=DEFAULT_COORDS_7_3F)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--floor", choices=["2F", "3F"], default=None)
    parser.add_argument("--min-games", type=int, default=DEFAULT_MIN_GAMES_ANALYSIS)
    parser.add_argument("--min-section-size", type=int, default=DEFAULT_MIN_SECTION_SIZE)
    parser.add_argument("--max-kakuban", type=int, default=DEFAULT_MAX_KAKUBAN)
    parser.add_argument("--min-support-sections", type=int, default=1)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    selected_floors = [args.floor] if args.floor else ["2F", "3F"]
    specs: list[SegmentSpec] = []
    for floor in selected_floors:
        coords_path = args.coords_2f if floor == "2F" else args.coords_3f
        specs.append(
            SegmentSpec(
                hall_slug="kamata7",
                hall_name=infer_hall_name(coords_path, floor=floor),
                floor=floor,
                db_path=args.db7,
                coords_path=coords_path,
            )
        )

    report_path = DEFAULT_REPORT_PATH if args.output_dir == DEFAULT_OUTPUT_DIR else args.output_dir / "report.md"
    run_analysis(
        specs=specs,
        output_dir=args.output_dir,
        report_path=report_path,
        min_games=args.min_games,
        min_section_size=args.min_section_size,
        max_kakuban=args.max_kakuban,
        min_support_sections=args.min_support_sections,
    )
    print(args.output_dir)
    print(report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
