from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eda.core import load_hall_df
from ml.analysis.kamata_kakuban_section_residual_eda import _df_to_markdown, _section_size_group


PROJECT_ROOT = Path(__file__).resolve().parents[2]
HALL_NAME = "\u84b2\u75307"
DEFAULT_COORDS_7_2F = PROJECT_ROOT / "Heatmap" / "2F_floor_coordinates_kamata7.csv"
DEFAULT_COORDS_7_3F = PROJECT_ROOT / "Heatmap" / "3F_floor_coordinates_kamata7.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "ml" / "analysis" / "results" / "kamata7_kakuban_floorlr_eda"
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "report.md"

FULL_KAKUBAN_MIN = 1
FULL_KAKUBAN_MAX = 13
VISUAL_KAKUBAN_MIN = 5
VISUAL_KAKUBAN_MAX = 11
MIN_GAMES = 100
SECTION_SIZE_ORDER = ("small", "medium", "large")
SIDE_ORDER = ("L", "R")
SEGMENT_ORDER = ("2F", "3F", "AT")


def _calc_pay_rate(games_sum: pd.Series, diff_sum: pd.Series) -> pd.Series:
    denom = pd.to_numeric(games_sum, errors="coerce") * 3
    denom = denom.replace(0, np.nan)
    return ((denom + pd.to_numeric(diff_sum, errors="coerce")) / denom) * 100


def _table_md(df: pd.DataFrame) -> str:
    if df.empty:
        return "No rows."
    return _df_to_markdown(df)


def _read_coordinates(coords_path: Path, *, floor: str) -> pd.DataFrame:
    coords = pd.read_csv(coords_path)
    required = {
        "hall_name",
        "floor",
        "machine_number",
        "X",
        "Y",
        "section",
        "section_min",
        "section_max",
        "rank_from_min",
        "rank_from_max",
    }
    missing = required - set(coords.columns)
    if missing:
        raise ValueError(f"Missing coordinate columns in {coords_path}: {sorted(missing)}")

    coords = coords[coords["floor"] == floor].copy()
    if coords.empty:
        raise ValueError(f"No coordinates found for floor={floor!r} in {coords_path}")

    for column in ("machine_number", "X", "Y", "section_min", "section_max", "rank_from_min", "rank_from_max"):
        coords[column] = pd.to_numeric(coords[column], errors="coerce")
    coords = coords.dropna(subset=["machine_number", "X", "Y", "rank_from_min"]).copy()
    coords["machine_number"] = coords["machine_number"].astype(int)
    coords["X"] = coords["X"].astype(int)
    coords["Y"] = coords["Y"].astype(int)
    coords["rank_from_min"] = coords["rank_from_min"].astype(int)
    coords["rank_from_max"] = coords["rank_from_max"].astype(int)
    coords["section"] = coords["section"].fillna("unknown").astype(str)
    coords["section_machine_count"] = coords.groupby("section")["machine_number"].transform("nunique").astype("Int64")
    coords["section_size_group"] = coords["section_machine_count"].map(_section_size_group).astype("string")
    return coords.reset_index(drop=True)


def _attach_lr_side(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    section_x_median = out.groupby("section", dropna=False)["X"].median()
    out["section_x_median"] = out["section"].map(section_x_median)
    out["lr_side"] = np.where(out["X"] <= out["section_x_median"], "L", "R")
    out = out[out["lr_side"].isin(SIDE_ORDER)].copy()
    return out


def _normalize_frame(frame: pd.DataFrame, *, segment: str) -> pd.DataFrame:
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["dd"] = out["date"].dt.day.astype("Int64")
    out["machine_number"] = pd.to_numeric(out["machine_number"], errors="coerce").astype("Int64")
    out["diff_coins_normalized"] = pd.to_numeric(out["diff"], errors="coerce")
    out["games_normalized"] = pd.to_numeric(out["games"], errors="coerce")
    out["pay_rate"] = _calc_pay_rate(out["games_normalized"], out["diff_coins_normalized"]).round(2)
    out["rank_from_min"] = pd.to_numeric(out["rank_from_min"], errors="coerce").astype("Int64")
    out["section_machine_count"] = pd.to_numeric(out["section_machine_count"], errors="coerce").astype("Int64")
    out["section_size_group"] = out["section_size_group"].astype("string")
    out["segment"] = segment
    out = out.dropna(
        subset=[
            "date",
            "dd",
            "machine_number",
            "rank_from_min",
            "section_machine_count",
            "section_size_group",
            "diff_coins_normalized",
            "games_normalized",
        ]
    ).copy()
    out = out[out["rank_from_min"].between(FULL_KAKUBAN_MIN, FULL_KAKUBAN_MAX)].copy()
    out = out[out["games_normalized"].ge(MIN_GAMES)].copy()
    out["dd"] = out["dd"].astype(int)
    out["machine_number"] = out["machine_number"].astype(int)
    out["rank_from_min"] = out["rank_from_min"].astype(int)
    return out.reset_index(drop=True)


def _build_floor_frame(*, coords_path: Path, floor: str) -> pd.DataFrame:
    raw = load_hall_df(HALL_NAME).copy()
    if raw.empty:
        return pd.DataFrame()

    coords = _read_coordinates(coords_path, floor=floor)
    merged = raw.merge(coords, on="machine_number", how="inner", validate="many_to_one")
    if merged.empty:
        return pd.DataFrame()
    merged = _attach_lr_side(merged)
    return _normalize_frame(merged, segment=floor)


def _build_segment_frames(*, coords_2f: Path, coords_3f: Path) -> dict[str, pd.DataFrame]:
    frame_2f = _build_floor_frame(coords_path=coords_2f, floor="2F")
    frame_3f = _build_floor_frame(coords_path=coords_3f, floor="3F")
    frame_at = pd.concat([frame_2f, frame_3f], ignore_index=True) if not frame_2f.empty or not frame_3f.empty else pd.DataFrame()
    if not frame_at.empty:
        frame_at = frame_at.copy()
        frame_at["segment"] = "AT"
    return {"2F": frame_2f, "3F": frame_3f, "AT": frame_at}


def _aggregate_segment_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "segment",
                "section_size_group",
                "dd",
                "rank_from_min",
                "lr_side",
                "diff_sum",
                "games_sum",
                "machine_count",
                "pay_rate",
            ]
        )

    work = frame[
        frame["rank_from_min"].between(FULL_KAKUBAN_MIN, FULL_KAKUBAN_MAX)
        & frame["lr_side"].isin(SIDE_ORDER)
        & frame["section_size_group"].isin(SECTION_SIZE_ORDER)
        & frame["games_normalized"].ge(MIN_GAMES)
    ].copy()
    work["section_size_group"] = pd.Categorical(work["section_size_group"], categories=SECTION_SIZE_ORDER, ordered=True)
    if work.empty:
        return pd.DataFrame(
            columns=[
                "segment",
                "section_size_group",
                "dd",
                "rank_from_min",
                "lr_side",
                "diff_sum",
                "games_sum",
                "machine_count",
                "pay_rate",
            ]
        )

    grouped = (
        work.groupby(["segment", "section_size_group", "dd", "rank_from_min", "lr_side"], as_index=False)
        .agg(
            diff_sum=("diff_coins_normalized", "sum"),
            games_sum=("games_normalized", "sum"),
            machine_count=("machine_number", "nunique"),
        )
        .sort_values(["segment", "dd", "section_size_group", "lr_side", "rank_from_min"], na_position="last")
        .reset_index(drop=True)
    )
    grouped["pay_rate"] = _calc_pay_rate(grouped["games_sum"], grouped["diff_sum"]).round(2)
    grouped["dd"] = grouped["dd"].astype(int)
    grouped["rank_from_min"] = grouped["rank_from_min"].astype(int)
    grouped["machine_count"] = grouped["machine_count"].astype(int)
    grouped["section_size_group"] = grouped["section_size_group"].astype(str)
    return grouped


def _build_peak_table(aggregated: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        frame = aggregated.get(segment, pd.DataFrame())
        for section_size_group in SECTION_SIZE_ORDER:
            for lr_side in SIDE_ORDER:
                for dd in range(1, 32):
                    subset = frame[
                        frame["section_size_group"].eq(section_size_group)
                        & frame["lr_side"].eq(lr_side)
                        & frame["dd"].eq(dd)
                    ].copy()
                    if subset.empty:
                        rows.append(
                            {
                                "segment": segment,
                                "section_size_group": section_size_group,
                                "lr_side": lr_side,
                                "DD": dd,
                                "best_rank_from_min": pd.NA,
                                "best_pay_rate": pd.NA,
                                "best_machine_count": pd.NA,
                            }
                        )
                        continue
                    best = subset.sort_values(["pay_rate", "machine_count", "rank_from_min"], ascending=[False, False, True]).iloc[0]
                    rows.append(
                        {
                            "segment": segment,
                            "section_size_group": section_size_group,
                            "lr_side": lr_side,
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
    fig, axes = plt.subplots(len(SIDE_ORDER), len(SECTION_SIZE_ORDER), figsize=(18, 8), sharex=True, sharey=True)
    if viz.empty:
        for ax in np.ravel(axes):
            ax.text(0.5, 0.5, f"No data for {segment_name}", ha="center", va="center", transform=ax.transAxes)
            ax.axis("off")
        fig.tight_layout()
        fig.savefig(output_path, dpi=160, bbox_inches="tight")
        plt.close(fig)
        return

    for row_idx, lr_side in enumerate(SIDE_ORDER):
        for col_idx, section_size_group in enumerate(SECTION_SIZE_ORDER):
            ax = axes[row_idx, col_idx]
            block = viz[viz["lr_side"].eq(lr_side) & viz["section_size_group"].eq(section_size_group)].copy()
            if block.empty:
                ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
                ax.set_title(f"{segment_name} - {lr_side} - {section_size_group}")
                ax.axis("off")
                continue

            pivot = (
                block.pivot_table(index="dd", columns="rank_from_min", values="pay_rate", aggfunc="mean")
                .reindex(index=range(1, 32), columns=range(VISUAL_KAKUBAN_MIN, VISUAL_KAKUBAN_MAX + 1))
            )
            sns.heatmap(pivot, cmap="RdYlGn", center=100, annot=False, cbar_kws={"label": "Pay Rate (%)"}, ax=ax)
            ax.set_title(f"{segment_name} - {lr_side} - {section_size_group}")
            ax.set_xlabel("Rank from min")
            ax.set_ylabel("DD")

    fig.suptitle(f"Kamata7 {segment_name} Kakuban DD Heatmap (rank 5-11 only)", y=1.02)
    fig.tight_layout()
    fig.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def _build_report(*, coverage: pd.DataFrame, aggregated: dict[str, pd.DataFrame], peak_table: pd.DataFrame) -> str:
    lines = [
        "# Kamata7 kakuban floor/LR EDA",
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

    for segment_name in SEGMENT_ORDER:
        frame = aggregated.get(segment_name, pd.DataFrame())
        lines.extend(
            [
                f"## 2. Segment: {segment_name}",
                "",
                f"- rows: `{len(frame)}`",
                f"- dd coverage: `{int(frame['dd'].nunique()) if not frame.empty else 0}`",
                f"- rank coverage: `{int(frame['rank_from_min'].nunique()) if not frame.empty else 0}`",
                f"- side coverage: `{int(frame['lr_side'].nunique()) if not frame.empty else 0}`",
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
            _table_md(peak_table.head(80)),
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def run_analysis(*, coords_2f: Path, coords_3f: Path, output_dir: Path) -> dict[str, pd.DataFrame]:
    output_dir.mkdir(parents=True, exist_ok=True)
    segments = _build_segment_frames(coords_2f=coords_2f, coords_3f=coords_3f)

    coverage_rows: list[dict[str, object]] = []
    aggregated: dict[str, pd.DataFrame] = {}
    for segment_name in SEGMENT_ORDER:
        frame = segments.get(segment_name, pd.DataFrame()).copy()
        agg = _aggregate_segment_frame(frame)
        aggregated[segment_name] = agg
        agg.to_csv(output_dir / f"kamata7_{segment_name}_kakuban_dd_floorlr.csv", index=False, encoding="utf-8-sig")
        coverage_rows.append(
            {
                "segment": segment_name,
                "rows": int(len(frame)),
                "dates": int(frame["date"].nunique()) if not frame.empty else 0,
                "rank_min": int(frame["rank_from_min"].min()) if not frame.empty else pd.NA,
                "rank_max": int(frame["rank_from_min"].max()) if not frame.empty else pd.NA,
                "lr_sides": int(frame["lr_side"].nunique()) if not frame.empty else 0,
                "section_size_groups": int(frame["section_size_group"].nunique()) if not frame.empty else 0,
            }
        )
        _build_heatmap(segment_name, frame, output_dir / f"heatmap_{segment_name}_kakuban_dd_floorlr.png")

    coverage = pd.DataFrame(coverage_rows)
    peak_table = _build_peak_table(aggregated)
    peak_table.to_csv(output_dir / "kamata7_peak_ranks_by_dd_floorlr.csv", index=False, encoding="utf-8-sig")

    report = _build_report(coverage=coverage, aggregated=aggregated, peak_table=peak_table)
    (output_dir / "report.md").write_text(report, encoding="utf-8")

    return {"coverage": coverage, "peak_table": peak_table, **{f"{key}_aggregated": value for key, value in aggregated.items()}}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kamata7 floor/LR kakuban DD EDA.")
    parser.add_argument("--coords-2f", dest="coords_2f", type=Path, default=DEFAULT_COORDS_7_2F)
    parser.add_argument("--coords-3f", dest="coords_3f", type=Path, default=DEFAULT_COORDS_7_3F)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_analysis(coords_2f=args.coords_2f, coords_3f=args.coords_3f, output_dir=args.output_dir)
    print(args.output_dir)
    print(args.output_dir / "report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
