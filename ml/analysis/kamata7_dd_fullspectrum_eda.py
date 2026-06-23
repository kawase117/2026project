"""
Kamata7 DD Fullspectrum EDA.

DD 1-31 is used directly (no banding). The analysis compares the within-month
date pattern across three axes:

  1. DD x section_size (small / medium / large)
  2. DD x LR (left / right within each section)
  3. DD x segment (2F_A / 2F_N / 3F_A / 3F_N)

Outputs (ml/analysis/results/kamata7_dd_fullspectrum_eda/):
  - kamata7_dd_fullspectrum_summary.csv
  - kamata7_dd_fullspectrum_stats.csv
  - heatmap_dd_section_size.png
  - heatmap_dd_lr.png
  - heatmap_dd_segment.png
  - report.md

LR split is derived from the per-section X-coordinate median already present on
the merged floor frame: machines whose X is below the section median are "L",
the rest "R".
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.analysis.kamata_kakuban_section_residual_eda import (
    _df_to_markdown,
    _section_size_group,
    _write_csv,
)
from ml.analysis.kamata7_kakuban_section_lr_interaction_eda import (
    _build_floor_frames,
    _calc_pay_rate,
    _normalize_segment_frame,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
DEFAULT_COORDS_7_2F = PROJECT_ROOT / "Heatmap" / "2F_floor_coordinates_kamata7.csv"
DEFAULT_COORDS_7_3F = PROJECT_ROOT / "Heatmap" / "3F_floor_coordinates_kamata7.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "ml" / "analysis" / "results" / "kamata7_dd_fullspectrum_eda"
DEFAULT_MIN_GAMES_ANALYSIS = 100

DD_RANGE = list(range(1, 32))
SECTION_SIZE_ORDER = ("small", "medium", "large")
LR_ORDER = ("L", "R")
SEGMENT_ORDER = ("2F_A", "2F_N", "3F_A", "3F_N")

SUMMARY_COLUMNS = [
    "dd",
    "section_size_group",
    "lr",
    "segment",
    "games_sum",
    "diff_sum",
    "pay_rate",
    "n_machines",
    "n_days",
]


def _table_md(df: pd.DataFrame) -> str:
    if df.empty:
        return "No rows."
    return _df_to_markdown(df)


def _format_dd_column(df: pd.DataFrame) -> pd.DataFrame:
    """Render the dd column as a clean integer string for markdown tables.

    pandas widens an int dd to float when a row also holds NaN values, which
    leaks "1.0" into the report. Casting to a nullable string keeps it as "1".
    """
    if df.empty or "dd" not in df.columns:
        return df
    out = df.copy()
    dd = pd.to_numeric(out["dd"], errors="coerce")
    out["dd"] = dd.map(lambda v: "" if pd.isna(v) else str(int(v))).astype("string")
    return out


def _add_lr_split(frame: pd.DataFrame) -> pd.DataFrame:
    """Classify each row as L/R by comparing X with its section X-median.

    X below (or equal to) the section median is "L", strictly above is "R".
    Sections without usable X coordinates are left as "Unknown".
    """
    out = frame.copy()
    out["lr"] = "Unknown"
    if out.empty:
        return out
    if "section" not in out.columns:
        out["section"] = "unknown"
    out["section"] = out["section"].fillna("unknown").astype(str)
    if "X" not in out.columns:
        return out
    x_numeric = pd.to_numeric(out["X"], errors="coerce")
    section_median = x_numeric.groupby(out["section"]).transform("median")
    valid = x_numeric.notna() & section_median.notna()
    out.loc[valid & (x_numeric <= section_median), "lr"] = "L"
    out.loc[valid & (x_numeric > section_median), "lr"] = "R"
    return out


def _build_segment_frames(
    floor_frames: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """Build the 4 segment views (2F_A, 2F_N, 3F_A, 3F_N).

    Each floor frame is normalized, split by ``machine_type_segment`` (A vs N),
    and tagged with an LR column computed per section.
    """
    segments: dict[str, pd.DataFrame] = {}
    for floor in ("2F", "3F"):
        frame = floor_frames.get(floor, pd.DataFrame())
        if frame.empty:
            continue
        frame = _normalize_segment_frame(frame)
        if "machine_type_segment" not in frame.columns:
            continue
        frame = _add_lr_split(frame)
        for type_code in ("A", "N"):
            view = frame[frame["machine_type_segment"].astype(str).eq(type_code)].copy()
            segments[f"{floor}_{type_code}"] = view
    return segments


def _aggregate_segments(segments: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Aggregate every segment to the cell grain and concatenate.

    Grain: (date, segment, section, section_size_group, dd, rank_from_min, lr).
    Rows missing dd / games / diff are dropped before aggregation.
    """
    parts: list[pd.DataFrame] = []
    for segment_name in SEGMENT_ORDER:
        frame = segments.get(segment_name, pd.DataFrame())
        if frame.empty:
            continue
        work = frame.copy()
        work["segment"] = segment_name
        work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.normalize()
        work["dd"] = pd.to_numeric(work["dd"], errors="coerce").astype("Int64")
        work["section"] = work.get("section", "unknown").fillna("unknown").astype(str)
        work["section_size_group"] = work["section_size_group"].astype("string")
        work["rank_from_min"] = pd.to_numeric(work["rank_from_min"], errors="coerce").astype("Int64")
        work["lr"] = work.get("lr", "Unknown").fillna("Unknown").astype(str)
        work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
        work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
        work = work.dropna(
            subset=["date", "dd", "games_normalized", "diff_coins_normalized"]
        ).copy()
        if work.empty:
            continue
        grouped = (
            work.groupby(
                ["date", "segment", "section", "section_size_group", "dd", "rank_from_min", "lr"],
                as_index=False,
                dropna=False,
            )
            .agg(
                games_sum=("games_normalized", "sum"),
                diff_sum=("diff_coins_normalized", "sum"),
                n_machines=("machine_number", "nunique"),
            )
        )
        grouped["pay_rate"] = _calc_pay_rate(grouped["games_sum"], grouped["diff_sum"]).round(2)
        grouped["n_days"] = 1
        parts.append(grouped)

    if not parts:
        return pd.DataFrame(
            columns=[
                "date",
                "segment",
                "section",
                "section_size_group",
                "dd",
                "rank_from_min",
                "lr",
                "games_sum",
                "diff_sum",
                "n_machines",
                "pay_rate",
                "n_days",
            ]
        )
    combined = pd.concat(parts, ignore_index=True)
    combined["dd"] = pd.to_numeric(combined["dd"], errors="coerce").astype("Int64")
    return combined


def _build_summary_csv(cell: pd.DataFrame) -> pd.DataFrame:
    """Collapse the cell grain to (dd, section_size_group, lr, segment)."""
    if cell.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)
    summary = (
        cell.groupby(
            ["dd", "section_size_group", "lr", "segment"],
            as_index=False,
            dropna=False,
        )
        .agg(
            games_sum=("games_sum", "sum"),
            diff_sum=("diff_sum", "sum"),
            n_machines=("n_machines", "sum"),
            n_days=("date", "nunique"),
        )
    )
    summary["pay_rate"] = _calc_pay_rate(summary["games_sum"], summary["diff_sum"]).round(2)
    summary["dd"] = pd.to_numeric(summary["dd"], errors="coerce").astype("Int64")
    summary = summary.sort_values(
        ["dd", "section_size_group", "lr", "segment"], na_position="last"
    ).reset_index(drop=True)
    return summary[SUMMARY_COLUMNS]


def _build_stats_csv(cell: pd.DataFrame) -> pd.DataFrame:
    """Per-DD stats with a one-way ANOVA across section_size_group on pay_rate.

    For each DD we compare the daily pay_rate distributions of the small /
    medium / large groups. The F-value / p-value test whether section size
    matters on that specific date.
    """
    columns = [
        "dd",
        "mean_pay_rate",
        "std_pay_rate",
        "n_days",
        "small_mean",
        "medium_mean",
        "large_mean",
        "f_value",
        "p_value",
    ]
    if cell.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, object]] = []
    for dd, group in cell.groupby("dd", dropna=True):
        pay = pd.to_numeric(group["pay_rate"], errors="coerce").dropna().astype(float)
        size_means: dict[str, float] = {}
        groups_for_test: list[np.ndarray] = []
        for size in SECTION_SIZE_ORDER:
            series = (
                pd.to_numeric(
                    group.loc[group["section_size_group"].astype(str).eq(size), "pay_rate"],
                    errors="coerce",
                )
                .dropna()
                .astype(float)
            )
            size_means[size] = float(series.mean()) if len(series) else np.nan
            if len(series) >= 2:
                groups_for_test.append(series.to_numpy())

        f_value, p_value = np.nan, np.nan
        if len(groups_for_test) >= 2:
            try:
                result = stats.f_oneway(*groups_for_test)
                f_value, p_value = float(result.statistic), float(result.pvalue)
            except Exception:
                f_value, p_value = np.nan, np.nan

        rows.append(
            {
                "dd": int(dd),
                "mean_pay_rate": round(float(pay.mean()), 2) if len(pay) else np.nan,
                "std_pay_rate": round(float(pay.std(ddof=1)), 2) if len(pay) > 1 else np.nan,
                "n_days": int(group["date"].nunique()),
                "small_mean": round(size_means["small"], 2) if np.isfinite(size_means["small"]) else np.nan,
                "medium_mean": round(size_means["medium"], 2) if np.isfinite(size_means["medium"]) else np.nan,
                "large_mean": round(size_means["large"], 2) if np.isfinite(size_means["large"]) else np.nan,
                "f_value": round(f_value, 4) if np.isfinite(f_value) else np.nan,
                "p_value": round(p_value, 6) if np.isfinite(p_value) else np.nan,
            }
        )

    out = pd.DataFrame(rows, columns=columns)
    return out.sort_values("dd").reset_index(drop=True)


def _pivot_for_axis(cell: pd.DataFrame, index_col: str, index_order: tuple[str, ...]) -> pd.DataFrame:
    """Pivot to index_order rows x DD 1-31 columns with games-weighted pay_rate.

    Empty cells are preserved as NaN (no DDs are forced to exist if absent).
    """
    if cell.empty:
        return pd.DataFrame(index=list(index_order), columns=DD_RANGE, dtype=float)
    weighted = (
        cell.groupby([index_col, "dd"], as_index=False, dropna=False)
        .agg(games_sum=("games_sum", "sum"), diff_sum=("diff_sum", "sum"))
    )
    weighted["pay_rate"] = _calc_pay_rate(weighted["games_sum"], weighted["diff_sum"])
    pivot = weighted.pivot_table(index=index_col, columns="dd", values="pay_rate", aggfunc="first")
    pivot = pivot.reindex(index=list(index_order), columns=DD_RANGE)
    return pivot


def _draw_heatmap(pivot: pd.DataFrame, title: str, ylabel: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if pivot.empty or pivot.dropna(how="all").empty:
        fig, ax = plt.subplots(figsize=(10, 3.5))
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        ax.axis("off")
        fig.tight_layout()
        fig.savefig(output_path, dpi=160)
        plt.close(fig)
        return

    data = pivot.to_numpy(dtype=float)
    finite = data[np.isfinite(data)]
    spread = max(np.nanmax(np.abs(finite - 100.0)), 1.0) if finite.size else 10.0

    fig, ax = plt.subplots(figsize=(13, 0.9 * len(pivot.index) + 2.0))
    im = ax.imshow(
        data,
        aspect="auto",
        cmap="RdBu_r",
        vmin=100 - spread,
        vmax=100 + spread,
    )
    ax.set_xticks(np.arange(len(pivot.columns)))
    ax.set_xticklabels([str(col) for col in pivot.columns.tolist()], fontsize=8)
    ax.set_yticks(np.arange(len(pivot.index)))
    ax.set_yticklabels([str(idx) for idx in pivot.index.tolist()])
    ax.set_xlabel("DD (day of month)")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            value = data[i, j]
            if np.isfinite(value):
                ax.text(j, i, f"{value:.1f}", ha="center", va="center", fontsize=6, color="#222222")
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("pay_rate (%)")
    fig.tight_layout()
    fig.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def _build_report(
    *,
    cell: pd.DataFrame,
    summary: pd.DataFrame,
    stats_df: pd.DataFrame,
    pivot_size: pd.DataFrame,
    pivot_lr: pd.DataFrame,
    pivot_segment: pd.DataFrame,
) -> str:
    n_dd = int(cell["dd"].nunique()) if not cell.empty else 0
    n_dates = int(cell["date"].nunique()) if not cell.empty else 0
    segments_present = sorted(cell["segment"].unique().tolist()) if not cell.empty else []

    def _axis_table(pivot: pd.DataFrame, label: str) -> pd.DataFrame:
        if pivot.empty:
            return pd.DataFrame(columns=[label, "mean_pay_rate", "n_dd_with_data"])
        rows = []
        for idx in pivot.index:
            series = pd.to_numeric(pivot.loc[idx], errors="coerce")
            rows.append(
                {
                    label: str(idx),
                    "mean_pay_rate": round(float(series.mean()), 2) if series.notna().any() else np.nan,
                    "n_dd_with_data": int(series.notna().sum()),
                }
            )
        return pd.DataFrame(rows)

    sig = stats_df[pd.to_numeric(stats_df.get("p_value"), errors="coerce").lt(0.05)].copy() if not stats_df.empty else pd.DataFrame()

    top_dd = (
        stats_df.dropna(subset=["mean_pay_rate"]).nlargest(5, "mean_pay_rate")[["dd", "mean_pay_rate", "n_days"]]
        if not stats_df.empty
        else pd.DataFrame()
    )
    bottom_dd = (
        stats_df.dropna(subset=["mean_pay_rate"]).nsmallest(5, "mean_pay_rate")[["dd", "mean_pay_rate", "n_days"]]
        if not stats_df.empty
        else pd.DataFrame()
    )

    lines = [
        "# Kamata7 DD Fullspectrum EDA",
        "",
        "DD 1-31 is used directly without banding. Cell grain is",
        "`(date, segment, section, section_size_group, dd, rank_from_min, lr)`.",
        "pay_rate uses `((games_sum * 3 + diff_sum) / (games_sum * 3)) * 100`.",
        "",
        "## 1. Overview",
        "",
        f"- cell rows: `{len(cell)}`",
        f"- distinct DD: `{n_dd}` / 31",
        f"- distinct dates: `{n_dates}`",
        f"- segments: `{', '.join(segments_present) if segments_present else 'none'}`",
        "",
        "## 2. Axis means",
        "",
        "### DD x section_size",
        "",
        _table_md(_axis_table(pivot_size, "section_size_group")),
        "",
        "### DD x LR",
        "",
        _table_md(_axis_table(pivot_lr, "lr")),
        "",
        "### DD x segment",
        "",
        _table_md(_axis_table(pivot_segment, "segment")),
        "",
        "## 3. Per-DD stats (section_size ANOVA)",
        "",
        _table_md(_format_dd_column(stats_df)),
        "",
        "## 4. Key findings",
        "",
        "### Top 5 DD by mean pay_rate",
        "",
        _table_md(_format_dd_column(top_dd)),
        "",
        "### Bottom 5 DD by mean pay_rate",
        "",
        _table_md(_format_dd_column(bottom_dd)),
        "",
        "### Significant section_size effect (p < 0.05)",
        "",
    ]
    if sig.empty:
        lines.append("No DD reached p < 0.05 for the section_size comparison.")
    else:
        lines.append(f"DDs with significant section_size effect: `{len(sig)}`")
        lines.append("")
        lines.append(_table_md(_format_dd_column(sig[["dd", "f_value", "p_value", "small_mean", "medium_mean", "large_mean"]])))
    lines.extend(
        [
            "",
            "## 5. Summary sample (first 30 rows)",
            "",
            _table_md(summary.head(30)),
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def run_analysis(
    *,
    db_path: Path,
    coords_2f: Path,
    coords_3f: Path,
    output_dir: Path,
    min_games: int = DEFAULT_MIN_GAMES_ANALYSIS,
) -> dict[str, pd.DataFrame]:
    output_dir.mkdir(parents=True, exist_ok=True)

    floor_frames = _build_floor_frames(
        db_path=db_path,
        coords_2f=coords_2f,
        coords_3f=coords_3f,
        min_games=min_games,
    )
    segments = _build_segment_frames(floor_frames)
    cell = _aggregate_segments(segments)

    summary = _build_summary_csv(cell)
    stats_df = _build_stats_csv(cell)

    pivot_size = _pivot_for_axis(cell, "section_size_group", SECTION_SIZE_ORDER)
    pivot_lr = _pivot_for_axis(cell[cell["lr"].isin(LR_ORDER)], "lr", LR_ORDER)
    pivot_segment = _pivot_for_axis(cell, "segment", SEGMENT_ORDER)

    _write_csv(summary, output_dir / "kamata7_dd_fullspectrum_summary.csv")
    _write_csv(stats_df, output_dir / "kamata7_dd_fullspectrum_stats.csv")

    _draw_heatmap(
        pivot_size,
        "Kamata7 DD x section_size pay_rate",
        "section_size_group",
        output_dir / "heatmap_dd_section_size.png",
    )
    _draw_heatmap(
        pivot_lr,
        "Kamata7 DD x LR pay_rate",
        "lr",
        output_dir / "heatmap_dd_lr.png",
    )
    _draw_heatmap(
        pivot_segment,
        "Kamata7 DD x segment pay_rate",
        "segment",
        output_dir / "heatmap_dd_segment.png",
    )

    report = _build_report(
        cell=cell,
        summary=summary,
        stats_df=stats_df,
        pivot_size=pivot_size,
        pivot_lr=pivot_lr,
        pivot_segment=pivot_segment,
    )
    (output_dir / "report.md").write_text(report, encoding="utf-8")

    return {
        "cell": cell,
        "summary": summary,
        "stats": stats_df,
        "pivot_size": pivot_size,
        "pivot_lr": pivot_lr,
        "pivot_segment": pivot_segment,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kamata7 DD fullspectrum EDA")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_7)
    parser.add_argument("--coords-2f", dest="coords_2f", type=Path, default=DEFAULT_COORDS_7_2F)
    parser.add_argument("--coords-3f", dest="coords_3f", type=Path, default=DEFAULT_COORDS_7_3F)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--min-games", type=int, default=DEFAULT_MIN_GAMES_ANALYSIS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_analysis(
        db_path=args.db,
        coords_2f=args.coords_2f,
        coords_3f=args.coords_3f,
        output_dir=args.output_dir,
        min_games=args.min_games,
    )
    print(args.output_dir)
    print(args.output_dir / "report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
