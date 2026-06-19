from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.analysis.kamata_kakuban_section_residual_eda import (
    DEFAULT_MIN_GAMES_ANALYSIS,
    DEFAULT_MIN_SECTION_SIZE,
    _bh_adjust,
    _df_to_markdown,
    _section_size_group,
    infer_hall_name,
)
from ml.analysis.kamata_corner_mirror_analysis import _build_merged_frame


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_7 = PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田7.db"
DEFAULT_COORDS_7_2F = PROJECT_ROOT / "Heatmap" / "2F_floor_coordinates_kamata7.csv"
DEFAULT_COORDS_7_3F = PROJECT_ROOT / "Heatmap" / "3F_floor_coordinates_kamata7.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "ml" / "analysis" / "results" / "kamata7_kakuban_dd_precision_eda"
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "report.md"


def _resolve_default_db7() -> Path:
    candidates = [
        path
        for path in (PROJECT_ROOT / "db").glob("*蒲田7*.db")
        if path.is_file() and path.stat().st_size > 0
    ]
    if candidates:
        return sorted(candidates, key=lambda path: path.stat().st_size, reverse=True)[0]
    return PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田7.db"


DEFAULT_DB_7 = _resolve_default_db7()

DEFAULT_MIN_CELL_GAMES = 100
FULL_KAKUBAN_MIN = 1
FULL_KAKUBAN_MAX = 13
VISUAL_KAKUBAN_MIN = 5
VISUAL_KAKUBAN_MAX = 11
SECTION_SIZE_ORDER = ("small", "medium", "large")
SEGMENT_NAMES = ("2F", "3F", "AT")


@dataclass(frozen=True)
class SegmentFrame:
    segment_name: str
    frame: pd.DataFrame


def _format_number(value: object, digits: int = 2) -> str:
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


def _calc_pay_rate(games_sum: pd.Series, diff_sum: pd.Series) -> pd.Series:
    denom = pd.to_numeric(games_sum, errors="coerce") * 3
    denom = denom.replace(0, np.nan)
    return ((denom + pd.to_numeric(diff_sum, errors="coerce")) / denom) * 100


def _attach_section_size_metadata(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "section" not in out.columns:
        out["section"] = "unknown"
    out["section"] = out["section"].fillna("unknown").astype(str)
    section_machine_count = out.groupby("section", dropna=False)["machine_number"].transform("nunique")
    out["section_machine_count"] = pd.to_numeric(section_machine_count, errors="coerce").astype("Int64")
    out["section_size"] = out["section_machine_count"]
    out["section_size_group"] = out["section_size"].map(_section_size_group)
    return out


def _normalize_segment_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["dd"] = out["date"].dt.day.astype("Int64")
    out["rank_from_min"] = pd.to_numeric(out["rank_from_min"], errors="coerce").astype("Int64")
    if "section_machine_count" not in out.columns:
        out["section_machine_count"] = pd.to_numeric(out.get("section_size"), errors="coerce").astype("Int64")
    if "section_size" not in out.columns or out["section_size"].isna().all():
        out["section_size"] = out["section_machine_count"]
    out["section_size"] = pd.to_numeric(out["section_size"], errors="coerce").astype("Int64")
    if "section_size_group" not in out.columns:
        out["section_size_group"] = pd.Series(pd.NA, index=out.index, dtype="string")
    out["section_size_group"] = out["section_size_group"].astype("string")
    missing_group = out["section_size_group"].isna() | out["section_size_group"].eq("<NA>")
    if missing_group.any():
        out.loc[missing_group, "section_size_group"] = out.loc[missing_group, "section_size"].map(_section_size_group)
    out["diff_coins_normalized"] = pd.to_numeric(out["diff_coins_normalized"], errors="coerce")
    out["games_normalized"] = pd.to_numeric(out["games_normalized"], errors="coerce")
    out["pay_rate"] = _calc_pay_rate(out["games_normalized"], out["diff_coins_normalized"]).round(2)
    out["machine_number"] = pd.to_numeric(out["machine_number"], errors="coerce").astype("Int64")
    out["machine_type_segment"] = out["machine_type_segment"].astype("string")
    out["floor"] = out["floor"].astype("string")
    out = out.dropna(
        subset=[
            "date",
            "dd",
            "rank_from_min",
            "section_size",
            "diff_coins_normalized",
            "games_normalized",
            "machine_number",
        ]
    ).copy()
    out["dd"] = out["dd"].astype(int)
    out["rank_from_min"] = out["rank_from_min"].astype(int)
    out["machine_number"] = out["machine_number"].astype(int)
    out = out[out["rank_from_min"].between(FULL_KAKUBAN_MIN, FULL_KAKUBAN_MAX)].copy()
    return out.reset_index(drop=True)


def _build_floor_frames(
    *,
    db_path: Path,
    coords_2f: Path,
    coords_3f: Path,
    min_games: int,
    min_section_size: int,
) -> dict[str, pd.DataFrame]:
    hall_name_2f = infer_hall_name(coords_2f, floor="2F")
    hall_name_3f = infer_hall_name(coords_3f, floor="3F")
    frame_2f = _build_merged_frame(
        db_path=db_path,
        coords_path=coords_2f,
        hall_name=hall_name_2f,
        floor="2F",
        min_games=min_games,
    )
    frame_3f = _build_merged_frame(
        db_path=db_path,
        coords_path=coords_3f,
        hall_name=hall_name_3f,
        floor="3F",
        min_games=min_games,
    )
    frame_2f = _attach_section_size_metadata(frame_2f)
    frame_3f = _attach_section_size_metadata(frame_3f)
    if min_section_size > 0:
        frame_2f = frame_2f[frame_2f["section_machine_count"].ge(min_section_size)].copy()
        frame_3f = frame_3f[frame_3f["section_machine_count"].ge(min_section_size)].copy()
    return {
        "2F": _normalize_segment_frame(frame_2f),
        "3F": _normalize_segment_frame(frame_3f),
    }


def _build_segment_views(floor_frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {
        "2F": floor_frames.get("2F", pd.DataFrame()).copy(),
        "3F": floor_frames.get("3F", pd.DataFrame()).copy(),
    }
    at_parts = []
    for floor in ("2F", "3F"):
        frame = floor_frames.get(floor, pd.DataFrame())
        if frame.empty:
            continue
        at_parts.append(frame[frame["machine_type_segment"].eq("N")].copy())
    frames["AT"] = pd.concat(at_parts, ignore_index=True) if at_parts else pd.DataFrame()
    return frames


def _aggregate_segment_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "dd",
                "rank_from_min",
                "section_size",
                "section_machine_count",
                "diff_sum",
                "games_sum",
                "machine_count",
                "pay_rate",
            ]
        )

    work = frame.copy()
    work = work[
        work["section_size_group"].isin(list(SECTION_SIZE_ORDER))
        & work["rank_from_min"].between(FULL_KAKUBAN_MIN, FULL_KAKUBAN_MAX)
        & work["games_normalized"].gt(0)
    ].copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "dd",
                "rank_from_min",
                "section_size",
                "section_machine_count",
                "diff_sum",
                "games_sum",
                "machine_count",
                "pay_rate",
            ]
        )

    grouped = (
        work.groupby(["dd", "rank_from_min", "section_size_group"], as_index=False)
        .agg(
            section_machine_count=("section_machine_count", "max"),
            diff_sum=("diff_coins_normalized", "sum"),
            games_sum=("games_normalized", "sum"),
            machine_count=("machine_number", "nunique"),
        )
        .sort_values(["dd", "rank_from_min", "section_size_group"], na_position="last")
        .reset_index(drop=True)
    )
    grouped["pay_rate"] = _calc_pay_rate(grouped["games_sum"], grouped["diff_sum"]).round(2)
    grouped["dd"] = grouped["dd"].astype(int)
    grouped["rank_from_min"] = grouped["rank_from_min"].astype(int)
    grouped["machine_count"] = grouped["machine_count"].astype(int)
    grouped["section_machine_count"] = grouped["section_machine_count"].astype("Int64")
    return grouped.reset_index(drop=True)


def _build_peak_table(aggregated: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment_name in SEGMENT_NAMES:
        frame = aggregated.get(segment_name, pd.DataFrame())
        for section_size in SECTION_SIZE_ORDER:
            for dd in range(1, 32):
                subset = frame[(frame["section_size_group"].eq(section_size)) & (frame["dd"].eq(dd))].copy()
                if subset.empty:
                    rows.append(
                        {
                            "segment": segment_name,
                            "section_size": section_size,
                            "DD": dd,
                            "best_rank_from_min": np.nan,
                            "best_pay_rate": np.nan,
                            "best_machine_count": np.nan,
                        }
                    )
                    continue
                best = subset.sort_values(
                    ["pay_rate", "machine_count", "rank_from_min"], ascending=[False, False, True]
                ).iloc[0]
                rows.append(
                    {
                        "segment": segment_name,
                        "section_size": section_size,
                        "DD": dd,
                        "best_rank_from_min": int(best["rank_from_min"]),
                        "best_pay_rate": float(best["pay_rate"]),
                        "best_machine_count": int(best["machine_count"]),
                    }
                )

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["best_rank_from_min"] = out["best_rank_from_min"].astype("Int64")
    out["best_machine_count"] = out["best_machine_count"].astype("Int64")
    out["best_pay_rate"] = pd.to_numeric(out["best_pay_rate"], errors="coerce")
    return out


def _build_heatmap(segment_name: str, frame: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    viz = frame[frame["rank_from_min"].between(VISUAL_KAKUBAN_MIN, VISUAL_KAKUBAN_MAX)].copy()
    if viz.empty:
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.text(0.5, 0.5, f"No data for {segment_name}", ha="center", va="center", transform=ax.transAxes)
        ax.axis("off")
        fig.tight_layout()
        fig.savefig(output_path, dpi=160)
        plt.close(fig)
        return

    fig, axes = plt.subplots(1, 3, figsize=(18, 9), sharey=True)
    for ax, section_size in zip(axes, SECTION_SIZE_ORDER, strict=True):
        block = viz[viz["section_size_group"].eq(section_size)].copy()
        if block.empty:
            ax.text(0.5, 0.5, f"No data for {section_size}", ha="center", va="center", transform=ax.transAxes)
            ax.set_title(f"{segment_name} - {section_size}")
            ax.axis("off")
            continue

        pivot = (
            block.pivot_table(index="dd", columns="rank_from_min", values="pay_rate", aggfunc="mean")
            .reindex(index=range(1, 32), columns=range(VISUAL_KAKUBAN_MIN, VISUAL_KAKUBAN_MAX + 1))
        )
        sns.heatmap(
            pivot,
            cmap="RdYlGn",
            center=100,
            annot=False,
            cbar_kws={"label": "Pay Rate (%)"},
            ax=ax,
        )
        ax.set_title(f"{segment_name} - {section_size}")
        ax.set_xlabel("角番 (rank_from_min)")
        ax.set_ylabel("DD (month day)")

    fig.suptitle(f"Kamata7 {segment_name} Kakuban DD Heatmap (rank 5-11 only)", y=1.02)
    fig.tight_layout()
    fig.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def _build_report(
    *,
    coverage: pd.DataFrame,
    aggregated: dict[str, pd.DataFrame],
    peak_table: pd.DataFrame,
) -> str:
    lines = [
        "# Kamata7 kakuban DD precision EDA",
        "",
        "Phase 3-4 uses all kakuban ranks (1-13).",
        "Phase 6 visualizations are limited to ranks 5-11.",
        "section_size means the actual machine count per island section, binned into small/medium/large.",
        "",
        "## 1. Coverage",
        "",
        _table_md(coverage),
        "",
    ]

    for segment_name in SEGMENT_NAMES:
        frame = aggregated.get(segment_name, pd.DataFrame())
        lines.extend(
            [
                f"## 2. Segment: {segment_name}",
                "",
                f"- rows: `{len(frame)}`",
                f"- dd coverage: `{int(frame['dd'].nunique()) if not frame.empty else 0}`",
                f"- rank coverage: `{int(frame['rank_from_min'].nunique()) if not frame.empty else 0}`",
                "",
                "### Aggregated table",
                "",
                _table_md(frame.head(40)),
                "",
            ]
        )

    lines.extend(
        [
            "## 3. Peak table",
            "",
            _table_md(peak_table.head(60)),
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def run_analysis(
    *,
    db_path: Path,
    coords_2f: Path,
    coords_3f: Path,
    output_dir: Path,
    min_games: int,
    min_section_size: int,
    min_cell_games: int,
) -> dict[str, pd.DataFrame]:
    output_dir.mkdir(parents=True, exist_ok=True)

    floor_frames = _build_floor_frames(
        db_path=db_path,
        coords_2f=coords_2f,
        coords_3f=coords_3f,
        min_games=min_games,
        min_section_size=min_section_size,
    )
    segment_frames = _build_segment_views(floor_frames)

    coverage_rows: list[dict[str, object]] = []
    aggregated: dict[str, pd.DataFrame] = {}
    for segment_name in SEGMENT_NAMES:
        frame = segment_frames.get(segment_name, pd.DataFrame()).copy()
        if not frame.empty and "pay_rate" not in frame.columns:
            frame["pay_rate"] = _calc_pay_rate(frame["games_normalized"], frame["diff_coins_normalized"]).round(2)
        agg = _aggregate_segment_frame(frame)
        agg = agg[agg["games_sum"].ge(min_cell_games)].copy()
        aggregated[segment_name] = agg
        out_path = output_dir / f"kamata7_{segment_name}_kakuban_dd_sectionsize.csv"
        agg.to_csv(out_path, index=False, encoding="utf-8-sig")
        coverage_rows.append(
            {
                "segment": segment_name,
                "rows": int(len(frame)),
                "eligible_rows": int(len(agg)),
                "dates": int(frame["date"].nunique()) if not frame.empty else 0,
                "rank_min": int(frame["rank_from_min"].min()) if not frame.empty else np.nan,
                "rank_max": int(frame["rank_from_min"].max()) if not frame.empty else np.nan,
                "section_size_groups": int(frame["section_size"].nunique()) if not frame.empty else 0,
            }
        )
        _build_heatmap(segment_name, frame, output_dir / f"heatmap_{segment_name}_kakuban_dd_sectionsize.png")

    coverage = pd.DataFrame(coverage_rows)
    peak_table = _build_peak_table(aggregated)
    peak_table_path = output_dir / "kamata7_peak_ranks_by_dd_sectionsize.csv"
    peak_table.to_csv(peak_table_path, index=False, encoding="utf-8-sig")

    report = _build_report(coverage=coverage, aggregated=aggregated, peak_table=peak_table)
    (output_dir / "report.md").write_text(report, encoding="utf-8")

    return {
        "coverage": coverage,
        "peak_table": peak_table,
        **{f"{key}_aggregated": value for key, value in aggregated.items()},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kamata7 kakuban DD precision EDA.")
    parser.add_argument("--db7", type=Path, default=DEFAULT_DB_7)
    parser.add_argument("--coords-2f", dest="coords_2f", type=Path, default=DEFAULT_COORDS_7_2F)
    parser.add_argument("--coords-3f", dest="coords_3f", type=Path, default=DEFAULT_COORDS_7_3F)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--min-games", type=int, default=DEFAULT_MIN_GAMES_ANALYSIS)
    parser.add_argument("--min-section-size", type=int, default=DEFAULT_MIN_SECTION_SIZE)
    parser.add_argument("--min-cell-games", type=int, default=DEFAULT_MIN_CELL_GAMES)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_analysis(
        db_path=args.db7,
        coords_2f=args.coords_2f,
        coords_3f=args.coords_3f,
        output_dir=args.output_dir,
        min_games=args.min_games,
        min_section_size=args.min_section_size,
        min_cell_games=args.min_cell_games,
    )
    print(args.output_dir)
    print(args.output_dir / "report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
