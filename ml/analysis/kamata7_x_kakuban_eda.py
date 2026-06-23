from __future__ import annotations

import argparse
import sys
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.analysis.kamata_kakuban_section_residual_eda import (
    DEFAULT_MIN_GAMES_ANALYSIS,
    DEFAULT_MIN_SECTION_SIZE,
    SegmentSpec,
    _bh_adjust,
    _df_to_markdown,
    _kruskal_pvalue,
    _prepare_segment_frame,
    infer_hall_name,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_7 = PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田7.db"
DEFAULT_COORDS_7_2F = PROJECT_ROOT / "Heatmap" / "2F_floor_coordinates_kamata7.csv"
DEFAULT_COORDS_7_3F = PROJECT_ROOT / "Heatmap" / "3F_floor_coordinates_kamata7.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "ml" / "analysis" / "results" / "kamata7_x_kakuban_eda"
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "report.md"


@dataclass(frozen=True)
class SegmentRun:
    spec: SegmentSpec
    segment_label: str
    segment_key: str
    frame: pd.DataFrame
    eligible: pd.DataFrame


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


def _attach_x_kakuban_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for column in ("X", "Y"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out = out.dropna(subset=["X", "Y"]).copy()
    out["X"] = out["X"].astype(int)
    out["Y"] = out["Y"].astype(int)

    machine_coords = out[["machine_number", "floor", "X", "Y"]].drop_duplicates(subset=["machine_number"]).copy()
    machine_coords["x_kakuban"] = (
        machine_coords.groupby(["floor", "X"])["Y"]
        .rank(method="first", ascending=True)
        .astype("Int64")
    )
    machine_coords["x_col_size"] = (
        machine_coords.groupby(["floor", "X"])["machine_number"]
        .transform("nunique")
        .astype("Int64")
    )
    out = out.merge(
        machine_coords[["machine_number", "x_kakuban", "x_col_size"]],
        on="machine_number",
        how="left",
        validate="many_to_one",
    )
    if "rank_from_min" in out.columns:
        out["section_kakuban"] = pd.to_numeric(out["rank_from_min"], errors="coerce").astype("Int64")
    elif "kakuban_min" in out.columns:
        out["section_kakuban"] = pd.to_numeric(out["kakuban_min"], errors="coerce").astype("Int64")
    else:
        out["section_kakuban"] = pd.NA
    return out


def _build_segment_run(
    spec: SegmentSpec,
    *,
    segment_label: str,
    min_games: int,
    min_section_size: int,
    base: pd.DataFrame | None = None,
) -> SegmentRun:
    if base is None:
        base = _prepare_segment_frame(spec, min_games=min_games, min_section_size=min_section_size).copy()
    else:
        base = base.copy()
    segment_key = f"{spec.hall_slug}_{spec.floor}_{segment_label}"
    if base.empty:
        return SegmentRun(spec=spec, segment_label=segment_label, segment_key=segment_key, frame=base, eligible=base)

    if "x_kakuban" not in base.columns or "x_col_size" not in base.columns:
        base = _attach_x_kakuban_frame(base)
    segment_frame = base[base["machine_type_segment"].eq(segment_label)].copy()
    if segment_frame.empty:
        return SegmentRun(spec=spec, segment_label=segment_label, segment_key=segment_key, frame=segment_frame, eligible=segment_frame)

    segment_frame["residual"] = pd.to_numeric(segment_frame["residual"], errors="coerce")
    segment_frame["residual_eligible"] = segment_frame["residual_eligible"].astype(bool)
    segment_frame["x_kakuban"] = pd.to_numeric(segment_frame["x_kakuban"], errors="coerce").astype("Int64")
    segment_frame["section_kakuban"] = pd.to_numeric(segment_frame["section_kakuban"], errors="coerce").astype("Int64")

    eligible = segment_frame[
        segment_frame["residual_eligible"] & segment_frame["residual"].notna() & segment_frame["x_kakuban"].notna()
    ].copy()
    return SegmentRun(spec=spec, segment_label=segment_label, segment_key=segment_key, frame=segment_frame, eligible=eligible)


def _build_x_kakuban_table(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=["x_kakuban", "mean_residual", "median_residual", "n", "support_x_columns", "kruskal_p", "kruskal_q"]
        )

    rows: list[dict[str, object]] = []
    support = frame.groupby("x_kakuban")["X"].nunique()
    for x_kakuban_value, x_df in frame.groupby("x_kakuban", sort=True):
        own = x_df["residual"].astype(float)
        rest = frame.loc[~frame["x_kakuban"].eq(x_kakuban_value), "residual"].astype(float)
        p_value = _kruskal_pvalue([own, rest])
        rows.append(
            {
                "x_kakuban": int(x_kakuban_value),
                "mean_residual": float(own.mean()),
                "median_residual": float(own.median()),
                "n": int(len(own)),
                "support_x_columns": int(support.get(x_kakuban_value, 0)),
                "kruskal_p": p_value,
            }
        )

    out = pd.DataFrame(rows)
    out["kruskal_q"] = _bh_adjust(out["kruskal_p"])
    out = out.sort_values(["kruskal_q", "x_kakuban"], na_position="last").reset_index(drop=True)
    return out


def _build_section_spearman_table(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["segment", "spearman_r", "spearman_p", "spearman_q", "n"])

    rows: list[dict[str, object]] = []
    for segment_label, segment_df in frame.groupby("segment_label", sort=True):
        work = segment_df.dropna(subset=["x_kakuban", "section_kakuban", "residual"]).copy()
        if work.empty or work["x_kakuban"].nunique() < 2 or work["section_kakuban"].nunique() < 2:
            spearman_r = np.nan
            spearman_p = np.nan
        else:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                result = spearmanr(work["x_kakuban"].astype(float), work["section_kakuban"].astype(float))
            spearman_r = float(result.correlation) if result.correlation is not None else np.nan
            spearman_p = float(result.pvalue) if result.pvalue is not None else np.nan
        rows.append(
            {
                "segment": segment_df["segment_key"].iloc[0],
                "spearman_r": spearman_r,
                "spearman_p": spearman_p,
                "n": int(len(work)),
            }
        )

    out = pd.DataFrame(rows)
    out["spearman_q"] = _bh_adjust(out["spearman_p"])
    out = out.sort_values(["spearman_q", "segment"], na_position="last").reset_index(drop=True)
    return out


def _floor_x_column_summary(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["floor", "x_col_size", "x_columns", "machines", "summary"])

    rows: list[dict[str, object]] = []
    for (floor, x_col_size), group in frame.groupby(["floor", "x_col_size"], sort=True):
        x_columns = int(group["X"].nunique())
        machines = int(group["machine_number"].nunique())
        rows.append(
            {
                "floor": floor,
                "x_col_size": int(x_col_size),
                "x_columns": x_columns,
                "machines": machines,
                "summary": f"{x_columns} columns / {machines} machines",
            }
        )

    out = pd.DataFrame(rows)
    out = out.sort_values(["floor", "x_col_size"], na_position="last").reset_index(drop=True)
    return out


def _summarize_segment(run: SegmentRun, table: pd.DataFrame) -> dict[str, object]:
    if run.frame.empty or table.empty:
        return {
            "segment": run.segment_key,
            "floor": run.spec.floor,
            "machine_type": run.segment_label,
            "rows": int(len(run.frame)),
            "eligible_rows": int(len(run.eligible)),
            "x_kakuban_rows": int(run.frame["x_kakuban"].notna().sum()) if "x_kakuban" in run.frame.columns else 0,
            "dates": int(pd.Index(run.frame["date"].dropna().unique()).size) if "date" in run.frame.columns else 0,
            "x_columns": int(run.frame["X"].nunique()) if "X" in run.frame.columns else 0,
            "significant_x_kakuban": 0,
            "mean_abs_mean_residual": np.nan,
        }

    significant = table[pd.to_numeric(table["kruskal_q"], errors="coerce").lt(0.05)].copy()
    return {
        "segment": run.segment_key,
        "floor": run.spec.floor,
        "machine_type": run.segment_label,
        "rows": int(len(run.frame)),
        "eligible_rows": int(len(run.eligible)),
        "x_kakuban_rows": int(run.frame["x_kakuban"].notna().sum()) if "x_kakuban" in run.frame.columns else 0,
        "dates": int(pd.Index(run.frame["date"].dropna().unique()).size) if "date" in run.frame.columns else 0,
        "x_columns": int(run.frame["X"].nunique()) if "X" in run.frame.columns else 0,
        "significant_x_kakuban": int(len(significant)),
        "mean_abs_mean_residual": float(table["mean_residual"].abs().mean()),
    }


def _build_report(
    *,
    coverage: pd.DataFrame,
    x_column_map: pd.DataFrame,
    segment_tables: dict[str, pd.DataFrame],
    segment_summary: pd.DataFrame,
    section_spearman: pd.DataFrame,
) -> str:
    lines = [
        "# Kamata7 x_kakuban EDA report",
        "",
        "Section residual = `diff_coins_normalized - section_mean`.",
        "x_kakuban is defined as the Y-order rank inside each `floor` + `X` column.",
        "Section kakuban uses `rank_from_min` from the coordinate CSV when available.",
        "",
        "## 1. Segment coverage",
        "",
        _table_md(coverage),
        "",
        "## 2. X-column size map by floor",
        "",
        _table_md(x_column_map),
        "",
    ]

    for _, row in segment_summary.iterrows():
        segment_key = str(row["segment"])
        table = segment_tables.get(segment_key, pd.DataFrame())
        lines.extend(
            [
                f"## 3. Segment: {segment_key}",
                "",
                f"- rows: `{int(row['rows'])}`",
                f"- eligible_rows: `{int(row['eligible_rows'])}`",
                f"- x_kakuban_rows: `{int(row['x_kakuban_rows'])}`",
                f"- x_columns: `{int(row['x_columns'])}`",
                f"- significant_x_kakuban: `{int(row['significant_x_kakuban'])}`",
                f"- mean_abs_mean_residual: `{_format_number(row['mean_abs_mean_residual'])}`",
                "",
                "### x_kakuban distribution",
                "",
                _table_md(table),
                "",
                "### significant x_kakuban rows (q < 0.05)",
                "",
                _table_md(table[pd.to_numeric(table["kruskal_q"], errors="coerce").lt(0.05)].copy()) if not table.empty else "No rows.",
                "",
            ]
        )

    lines.extend(
        [
            "## 4. Cross-segment comparison",
            "",
            _table_md(segment_summary[["segment", "significant_x_kakuban", "mean_abs_mean_residual"]].copy()),
            "",
            "## 5. Correlation with section kakuban",
            "",
            _table_md(section_spearman),
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def run_analysis(
    *,
    specs: list[SegmentSpec],
    output_dir: Path,
    report_path: Path,
    min_games: int,
    min_section_size: int,
) -> dict[str, pd.DataFrame]:
    output_dir.mkdir(parents=True, exist_ok=True)

    coverage_rows: list[dict[str, object]] = []
    floor_map_frames: list[pd.DataFrame] = []
    segment_summary_rows: list[dict[str, object]] = []
    segment_tables: dict[str, pd.DataFrame] = {}
    section_spearman_frames: list[pd.DataFrame] = []

    with tempfile.TemporaryDirectory(prefix="kamata7_x_kakuban_", dir=output_dir) as _tmp_dir:
        for spec in specs:
            base = _prepare_segment_frame(spec, min_games=min_games, min_section_size=min_section_size).copy()
            if base.empty:
                for segment_label in ("A", "N"):
                    segment_key = f"{spec.hall_slug}_{spec.floor}_{segment_label}"
                    empty_table = pd.DataFrame(
                        columns=[
                            "x_kakuban",
                            "mean_residual",
                            "median_residual",
                            "n",
                            "support_x_columns",
                            "kruskal_p",
                            "kruskal_q",
                        ]
                    )
                    segment_tables[segment_key] = empty_table
                    segment_summary_rows.append(
                        {
                            "segment": segment_key,
                            "floor": spec.floor,
                            "machine_type": segment_label,
                            "rows": 0,
                            "eligible_rows": 0,
                            "x_kakuban_rows": 0,
                            "dates": 0,
                            "x_columns": 0,
                            "significant_x_kakuban": 0,
                            "mean_abs_mean_residual": np.nan,
                        }
                    )
                    coverage_rows.append(
                        {
                            "segment": segment_key,
                            "hall": spec.hall_slug,
                            "floor": spec.floor,
                            "machine_type": segment_label,
                            "rows": 0,
                            "eligible_rows": 0,
                            "x_kakuban_rows": 0,
                            "dates": 0,
                            "x_columns": 0,
                        }
                    )
                floor_map_frames.append(pd.DataFrame(columns=["floor", "x_col_size", "x_columns", "machines", "summary"]))
                section_spearman_frames.append(pd.DataFrame(columns=["segment", "spearman_r", "spearman_p", "spearman_q", "n"]))
                continue

            base = _attach_x_kakuban_frame(base)
            floor_map_frames.append(_floor_x_column_summary(base))

            for segment_label in ("A", "N"):
                run = _build_segment_run(
                    spec,
                    segment_label=segment_label,
                    min_games=min_games,
                    min_section_size=min_section_size,
                    base=base,
                )
                table = _build_x_kakuban_table(run.eligible)
                segment_tables[run.segment_key] = table
                segment_summary_rows.append(_summarize_segment(run, table))
                coverage_rows.append(
                    {
                        "segment": run.segment_key,
                        "hall": spec.hall_slug,
                        "floor": spec.floor,
                        "machine_type": segment_label,
                        "rows": int(len(run.frame)),
                        "eligible_rows": int(len(run.eligible)),
                        "x_kakuban_rows": int(run.frame["x_kakuban"].notna().sum()) if "x_kakuban" in run.frame.columns else 0,
                        "dates": int(pd.Index(run.frame["date"].dropna().unique()).size) if "date" in run.frame.columns else 0,
                        "x_columns": int(run.frame["X"].nunique()) if "X" in run.frame.columns else 0,
                    }
                )
                section_spearman_frames.append(_build_section_spearman_table(run.frame.assign(segment_label=segment_label, segment_key=run.segment_key)))

    coverage = pd.DataFrame(coverage_rows)
    x_column_map = pd.concat(floor_map_frames, ignore_index=True) if floor_map_frames else pd.DataFrame()
    segment_summary = pd.DataFrame(segment_summary_rows)
    section_spearman = pd.concat(section_spearman_frames, ignore_index=True) if section_spearman_frames else pd.DataFrame()

    if not section_spearman.empty:
        section_spearman["spearman_q"] = _bh_adjust(section_spearman["spearman_p"])

    report = _build_report(
        coverage=coverage,
        x_column_map=x_column_map,
        segment_tables=segment_tables,
        segment_summary=segment_summary,
        section_spearman=section_spearman,
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    return {
        "coverage": coverage,
        "x_column_map": x_column_map,
        "segment_summary": segment_summary,
        "section_spearman": section_spearman,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kamata7 x_kakuban EDA.")
    parser.add_argument("--db7", type=Path, default=DEFAULT_DB_7)
    parser.add_argument("--coords-2f", dest="coords_2f", type=Path, default=DEFAULT_COORDS_7_2F)
    parser.add_argument("--coords-3f", dest="coords_3f", type=Path, default=DEFAULT_COORDS_7_3F)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--floor", choices=["2F", "3F"], default=None)
    parser.add_argument("--min-games", type=int, default=DEFAULT_MIN_GAMES_ANALYSIS)
    parser.add_argument("--min-section-size", type=int, default=DEFAULT_MIN_SECTION_SIZE)
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
    )
    print(args.output_dir)
    print(report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
