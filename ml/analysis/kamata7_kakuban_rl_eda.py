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
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "ml" / "analysis" / "results" / "kamata7_kakuban_rl_eda"
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "report.md"
DEFAULT_MAX_KAKUBAN = 20

DD_BIN_BOUNDS = [
    (1, 6, "1-6"),
    (7, 12, "7-12"),
    (13, 18, "13-18"),
    (19, 24, "19-24"),
    (25, 31, "25-31"),
]

EXCLUDED_SECTION_RANGES: dict[str, list[tuple[int, int]]] = {
    "2F": [(2187, 2195)],
    "3F": [(3191, 3208), (3209, 3217), (3400, 3401)],
}


@dataclass(frozen=True)
class SegmentRun:
    spec: SegmentSpec
    side: str
    segment_label: str
    segment_key: str
    frame: pd.DataFrame
    expanded: pd.DataFrame
    eligible: pd.DataFrame
    support: pd.Series


def assign_side(floor: str, x: float) -> str:
    """X座標でL/R/E(edge)を判定する。"""
    if floor == "2F":
        if x <= 17:
            return "L"
        if x >= 19:
            return "R"
    elif floor == "3F":
        if x <= 17:
            return "L"
        if x >= 23:
            return "R"
    return "E"


def _dd_bin(dd: object) -> str | None:
    if pd.isna(dd):
        return None
    dd_int = int(dd)
    for start, end, label in DD_BIN_BOUNDS:
        if start <= dd_int <= end:
            return label
    return None


def _safe_int(value: object) -> int | None:
    if pd.isna(value):
        return None
    return int(value)


def _section_is_excluded(section_min: object, section_max: object, floor: str) -> bool:
    if pd.isna(section_min) or pd.isna(section_max):
        return False
    try:
        sec_min = int(section_min)
        sec_max = int(section_max)
    except (TypeError, ValueError):
        return False

    for start, end in EXCLUDED_SECTION_RANGES.get(floor, []):
        if sec_min >= start and sec_max <= end:
            return True
    return False


def load_coords_with_side(coords_path: Path, floor: str) -> pd.DataFrame:
    df = pd.read_csv(coords_path)
    required = {"hall_name", "floor", "machine_number", "X", "Y", "section", "section_min", "section_max"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing coordinate columns in {coords_path}: {sorted(missing)}")

    df = df[df["floor"] == floor].copy()
    if df.empty:
        raise ValueError(f"No coordinates found for floor={floor!r} in {coords_path}")

    for column in ("machine_number", "X", "Y", "section_min", "section_max"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["machine_number", "X", "Y", "section_min", "section_max"]).copy()
    df["machine_number"] = df["machine_number"].astype(int)
    df["section"] = df["section"].fillna("unknown").astype(str)

    section_x_span = df.groupby("section")["X"].nunique()
    vertical_sections = set(section_x_span[section_x_span == 1].index)
    excluded_ranges = df.apply(
        lambda row: _section_is_excluded(row["section_min"], row["section_max"], floor), axis=1
    )
    df = df.loc[~df["section"].isin(vertical_sections) & ~excluded_ranges].copy()
    if df.empty:
        raise ValueError(f"All coordinates were excluded for floor={floor!r} in {coords_path}")

    df["side"] = df["X"].map(lambda x: assign_side(floor, float(x)))
    df = df[df["side"].isin(["L", "R"])].copy()
    if df.empty:
        raise ValueError(f"No L/R coordinates remained for floor={floor!r} in {coords_path}")

    df["section_min"] = df["section_min"].astype(int)
    df["section_max"] = df["section_max"].astype(int)
    df["X"] = pd.to_numeric(df["X"], errors="coerce")
    df["Y"] = pd.to_numeric(df["Y"], errors="coerce")
    df = df.dropna(subset=["X", "Y"]).copy()
    df["X"] = df["X"].astype(int)
    df["Y"] = df["Y"].astype(int)
    return df.reset_index(drop=True)


def _build_segment_key(*, hall_slug: str, floor: str, side: str, segment_label: str) -> str:
    return f"{hall_slug}_{floor}_{side}_{segment_label}"


def _write_side_coords(
    *,
    coords_path: Path,
    floor: str,
    side: str,
    temp_dir: Path,
) -> Path:
    coords = load_coords_with_side(coords_path, floor)
    side_coords = coords.loc[coords["side"].eq(side)].copy()
    if side_coords.empty:
        raise ValueError(f"No coordinates remained for floor={floor!r}, side={side!r} in {coords_path}")
    temp_path = temp_dir / f"{coords_path.stem}_{floor}_{side}.csv"
    side_coords.to_csv(temp_path, index=False, encoding="utf-8-sig")
    return temp_path


def _build_segment_run(
    spec: SegmentSpec,
    *,
    side: str,
    segment_label: str,
    min_games: int,
    min_section_size: int,
    max_kakuban: int,
    coords_path: Path,
) -> SegmentRun:
    side_spec = SegmentSpec(
        hall_slug=spec.hall_slug,
        hall_name=spec.hall_name,
        floor=spec.floor,
        db_path=spec.db_path,
        coords_path=coords_path,
    )
    base = _prepare_segment_frame(side_spec, min_games=min_games, min_section_size=min_section_size).copy()
    segment_key = _build_segment_key(
        hall_slug=spec.hall_slug,
        floor=spec.floor,
        side=side,
        segment_label=segment_label,
    )
    if base.empty:
        return SegmentRun(
            spec=spec,
            side=side,
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
    expanded["kakuban"] = expanded["kakuban"].astype(int)
    expanded["dd"] = pd.to_numeric(expanded["dd"], errors="coerce").astype("Int64")
    expanded = expanded[expanded["dd"].notna()].copy()
    expanded["dd"] = expanded["dd"].astype(int)
    expanded["residual"] = pd.to_numeric(expanded["residual"], errors="coerce")
    expanded["residual_eligible"] = expanded["residual_eligible"].astype(bool)

    segment_frame = expanded[expanded["machine_type_segment"].eq(segment_label)].copy()
    if segment_frame.empty:
        return SegmentRun(
            spec=spec,
            side=side,
            segment_label=segment_label,
            segment_key=segment_key,
            frame=segment_frame,
            expanded=expanded,
            eligible=segment_frame,
            support=pd.Series(dtype=int),
        )

    eligible = segment_frame[segment_frame["residual_eligible"] & segment_frame["residual"].notna()].copy()
    if eligible.empty:
        return SegmentRun(
            spec=spec,
            side=side,
            segment_label=segment_label,
            segment_key=segment_key,
            frame=segment_frame,
            expanded=expanded,
            eligible=eligible,
            support=pd.Series(dtype=int),
        )

    support = eligible.groupby(["kakuban", "dd"], dropna=False).size()
    eligible = eligible.merge(
        support.rename("cell_n").reset_index(),
        on=["kakuban", "dd"],
        how="left",
        validate="many_to_one",
    )
    eligible["cell_n"] = pd.to_numeric(eligible["cell_n"], errors="coerce").fillna(0).astype(int)
    return SegmentRun(
        spec=spec,
        side=side,
        segment_label=segment_label,
        segment_key=segment_key,
        frame=segment_frame,
        expanded=expanded,
        eligible=eligible,
        support=support,
    )


def _build_cross_table(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["kakuban", "dd", "mean_residual", "median_residual", "n"])
    out = (
        frame.groupby(["kakuban", "dd"], as_index=False)
        .agg(
            mean_residual=("residual", "mean"),
            median_residual=("residual", "median"),
            n=("residual", "size"),
        )
        .sort_values(["kakuban", "dd"], ascending=[True, True], na_position="last")
        .reset_index(drop=True)
    )
    out["kakuban"] = out["kakuban"].astype(int)
    out["dd"] = out["dd"].astype(int)
    out["n"] = out["n"].astype(int)
    return out


def _build_cell_vs_rest(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=["kakuban", "dd", "mean_residual", "median_residual", "n", "kruskal_p", "kruskal_q"]
        )

    work = frame[frame["cell_n"].ge(10)].copy()
    if work.empty:
        return pd.DataFrame(
            columns=["kakuban", "dd", "mean_residual", "median_residual", "n", "kruskal_p", "kruskal_q"]
        )

    rows: list[dict[str, object]] = []
    for (kakuban_value, dd_value), cell_df in work.groupby(["kakuban", "dd"], sort=True):
        own = cell_df["residual"].astype(float)
        rest = work.loc[~((work["kakuban"].eq(kakuban_value)) & (work["dd"].eq(dd_value))), "residual"].astype(float)
        p_value = _kruskal_pvalue([own, rest]) if len(own) >= 2 else float("nan")
        rows.append(
            {
                "kakuban": int(kakuban_value),
                "dd": int(dd_value),
                "mean_residual": float(own.mean()),
                "median_residual": float(own.median()),
                "n": int(len(own)),
                "kruskal_p": p_value,
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["kruskal_q"] = _bh_adjust(out["kruskal_p"])
    out = out.sort_values(["kruskal_q", "kakuban", "dd"], na_position="last").reset_index(drop=True)
    return out


def _build_spearman(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["kakuban", "spearman_r", "spearman_p", "n", "spearman_q"])

    work = frame[frame["cell_n"].ge(10)].copy()
    if work.empty:
        return pd.DataFrame(columns=["kakuban", "spearman_r", "spearman_p", "n", "spearman_q"])

    rows: list[dict[str, object]] = []
    for kakuban_value, kakuban_df in work.groupby("kakuban", sort=True):
        dd = kakuban_df["dd"].astype(float)
        residual = kakuban_df["residual"].astype(float)
        if len(dd) < 3 or dd.nunique() < 2 or residual.nunique() < 2:
            spearman_r = np.nan
            spearman_p = np.nan
        else:
            from scipy.stats import spearmanr
            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                result = spearmanr(dd, residual)
            spearman_r = float(result.correlation) if result.correlation is not None else np.nan
            spearman_p = float(result.pvalue) if result.pvalue is not None else np.nan
        rows.append(
            {
                "kakuban": int(kakuban_value),
                "spearman_r": spearman_r,
                "spearman_p": spearman_p,
                "n": int(len(kakuban_df)),
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["spearman_q"] = _bh_adjust(out["spearman_p"])
    out = out.sort_values(["spearman_q", "kakuban"], na_position="last").reset_index(drop=True)
    return out


def _build_dd_bin_kruskal(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["dd_bin", "kruskal_p", "kruskal_q", "n_groups", "top_kakuban"])

    work = frame[frame["cell_n"].ge(10)].copy()
    if work.empty:
        return pd.DataFrame(columns=["dd_bin", "kruskal_p", "kruskal_q", "n_groups", "top_kakuban"])

    work["dd_bin"] = work["dd"].map(_dd_bin)
    work = work[work["dd_bin"].notna()].copy()
    if work.empty:
        return pd.DataFrame(columns=["dd_bin", "kruskal_p", "kruskal_q", "n_groups", "top_kakuban"])

    rows: list[dict[str, object]] = []
    for _, _, bin_label in DD_BIN_BOUNDS:
        block = work[work["dd_bin"].eq(bin_label)].copy()
        if block.empty:
            rows.append({"dd_bin": bin_label, "kruskal_p": np.nan, "n_groups": 0, "top_kakuban": np.nan})
            continue

        groups = [group["residual"].astype(float) for _, group in block.groupby("kakuban", sort=True)]
        p_value = _kruskal_pvalue(groups)
        group_means = (
            block.groupby("kakuban", as_index=False)
            .agg(mean_residual=("residual", "mean"), n=("residual", "size"))
            .sort_values(["mean_residual", "kakuban"], ascending=[False, True], na_position="last")
        )
        top_kakuban = _safe_int(group_means.iloc[0]["kakuban"]) if not group_means.empty else None
        rows.append(
            {
                "dd_bin": bin_label,
                "kruskal_p": p_value,
                "n_groups": int(block["kakuban"].nunique()),
                "top_kakuban": top_kakuban,
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["kruskal_q"] = _bh_adjust(out["kruskal_p"])
    out = out[["dd_bin", "kruskal_p", "kruskal_q", "n_groups", "top_kakuban"]]
    return out


def _make_heatmap(segment_key: str, cross_table: pd.DataFrame, output_path: Path) -> bool:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.colors import TwoSlopeNorm
    except ImportError:
        return False

    if cross_table.empty:
        return False

    pivot_mean = cross_table.pivot(index="kakuban", columns="dd", values="mean_residual").sort_index()
    pivot_n = cross_table.pivot(index="kakuban", columns="dd", values="n").reindex_like(pivot_mean)
    dd_values = list(range(1, 32))
    kakuban_values = list(range(1, min(int(pivot_mean.index.max()), DEFAULT_MAX_KAKUBAN) + 1)) if not pivot_mean.empty else []
    if not kakuban_values:
        return False

    pivot_mean = pivot_mean.reindex(index=kakuban_values, columns=dd_values)
    pivot_n = pivot_n.reindex(index=kakuban_values, columns=dd_values)
    plot_values = pivot_mean.where(pivot_n.ge(10))
    finite = plot_values.to_numpy(dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return False

    vlim = float(np.nanpercentile(np.abs(finite), 95))
    if not np.isfinite(vlim) or vlim <= 0:
        vlim = float(np.nanmax(np.abs(finite)))
    if not np.isfinite(vlim) or vlim <= 0:
        vlim = 1.0

    cmap = plt.get_cmap("coolwarm").copy()
    cmap.set_bad("#d9d9d9")
    norm = TwoSlopeNorm(vcenter=0.0, vmin=-vlim, vmax=vlim)

    fig, ax = plt.subplots(figsize=(18, max(5, 0.45 * len(kakuban_values) + 1.5)))
    im = ax.imshow(plot_values.to_numpy(dtype=float), aspect="auto", cmap=cmap, norm=norm)
    ax.set_xticks(np.arange(len(dd_values)))
    ax.set_xticklabels(dd_values, fontsize=8)
    ax.set_yticks(np.arange(len(kakuban_values)))
    ax.set_yticklabels(kakuban_values, fontsize=8)
    ax.set_xlabel("DD")
    ax.set_ylabel("kakuban")
    ax.set_title(f"{segment_key} mean residual heatmap (n >= 10 shown)")
    ax.set_xlim(-0.5, len(dd_values) - 0.5)
    ax.set_ylim(len(kakuban_values) - 0.5, -0.5)
    ax.grid(False)
    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("mean_residual")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return True


def _sig_only(df: pd.DataFrame, q_col: str) -> pd.DataFrame:
    if df.empty or q_col not in df.columns:
        return df.iloc[0:0].copy()
    return df[pd.to_numeric(df[q_col], errors="coerce").lt(0.05)].copy()


def _format_number(value: object, digits: int = 3) -> str:
    if pd.isna(value):
        return "nan"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.{digits}f}"
    return str(value)


def _build_report(
    *,
    coverage: pd.DataFrame,
    significant_cells: pd.DataFrame,
    significant_spearman: pd.DataFrame,
    significant_dd_bin: pd.DataFrame,
    all_dd_bin: pd.DataFrame,
) -> str:
    lines = [
        "# Kamata7 kakuban L/R residual EDA report",
        "",
        "Section residual = `diff_coins_normalized - section_mean`.",
        "Rows from section-days with fewer than 3 machines are excluded from residual analysis by setting the residual to NaN.",
        "L/R split uses X-coordinate rules and removes edge / vertical wall columns before analysis.",
        "",
        "## 1. Segment coverage",
        "",
        _df_to_markdown(coverage),
        "",
        "## 2. Significant cell-vs-rest rows (q < 0.05)",
        "",
        _df_to_markdown(significant_cells),
        "",
        "## 3. Significant Spearman rows (q < 0.05)",
        "",
        _df_to_markdown(significant_spearman),
        "",
        "## 4. Significant DD-bin rows (q < 0.05)",
        "",
        _df_to_markdown(significant_dd_bin),
        "",
        "## 5. R-side conclusion",
        "",
    ]

    if all_dd_bin.empty or "segment" not in all_dd_bin.columns:
        lines.append("No R-side DD-bin results were produced.")
    else:
        r_bins = all_dd_bin[all_dd_bin["segment"].astype(str).str.contains("_R_", na=False)].copy()
        if r_bins.empty:
            lines.append("No R-side DD-bin results were produced.")
            lines.append("")
            return "\n".join(lines).rstrip() + "\n"
        sig_r_bins = r_bins[pd.to_numeric(r_bins["kruskal_q"], errors="coerce").lt(0.05)].copy()
        if sig_r_bins.empty:
            lines.append("No R-side DD bin survived q < 0.05.")
        else:
            best = sig_r_bins.sort_values(["kruskal_q", "dd_bin"], na_position="last").iloc[0]
            lines.append(
                f"R-side strongest DD-bin signal: dd_bin={best['dd_bin']}, q={_format_number(best['kruskal_q'])}, "
                f"top_kakuban={_safe_int(best['top_kakuban'])}."
            )
            lines.append(
                "Interpretation: the R side is the cleaner block for reading kakuban position, "
                "so any surviving DD-bin signal there is the most defensible structural result in this run."
            )
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _run_single_segment(run: SegmentRun) -> dict[str, pd.DataFrame]:
    eligible = run.eligible.copy()
    if eligible.empty:
        cross = pd.DataFrame(columns=["kakuban", "dd", "mean_residual", "median_residual", "n"])
        cell_vs_rest = pd.DataFrame(columns=["kakuban", "dd", "mean_residual", "median_residual", "n", "kruskal_p", "kruskal_q"])
        spearman = pd.DataFrame(columns=["kakuban", "spearman_r", "spearman_p", "n", "spearman_q"])
        dd_bin = pd.DataFrame(columns=["dd_bin", "kruskal_p", "kruskal_q", "n_groups", "top_kakuban"])
    else:
        cross = _build_cross_table(eligible)
        cell_vs_rest = _build_cell_vs_rest(eligible)
        spearman = _build_spearman(eligible)
        dd_bin = _build_dd_bin_kruskal(eligible)

    return {"cross": cross, "cell_vs_rest": cell_vs_rest, "spearman": spearman, "dd_bin": dd_bin}


def run_analysis(
    *,
    specs: list[SegmentSpec],
    output_dir: Path,
    report_path: Path,
    min_games: int,
    min_section_size: int,
    max_kakuban: int,
) -> dict[str, pd.DataFrame]:
    output_dir.mkdir(parents=True, exist_ok=True)

    coverage_rows: list[dict[str, object]] = []
    all_cell_sig: list[pd.DataFrame] = []
    all_spearman: list[pd.DataFrame] = []
    all_spearman_sig: list[pd.DataFrame] = []
    all_dd_bin_sig: list[pd.DataFrame] = []
    all_dd_bin: list[pd.DataFrame] = []

    with tempfile.TemporaryDirectory(prefix="kamata7_kakuban_rl_", dir=output_dir) as tmp_dir:
        temp_dir = Path(tmp_dir)
        for spec in specs:
            for side in ("L", "R"):
                coords_path = _write_side_coords(
                    coords_path=spec.coords_path,
                    floor=spec.floor,
                    side=side,
                    temp_dir=temp_dir,
                )
                for segment_label in ("N", "A"):
                    run = _build_segment_run(
                        spec,
                        side=side,
                        segment_label=segment_label,
                        min_games=min_games,
                        min_section_size=min_section_size,
                        max_kakuban=max_kakuban,
                        coords_path=coords_path,
                    )
                    segment_key = run.segment_key

                    coverage_rows.append(
                        {
                            "segment": segment_key,
                            "hall": spec.hall_slug,
                            "floor": spec.floor,
                            "side": side,
                            "machine_type": segment_label,
                            "rows": int(len(run.frame)),
                            "expanded_rows": int(len(run.expanded)),
                            "eligible_rows": int(len(run.eligible)),
                            "dates": int(pd.Index(run.frame["date"].dropna().unique()).size) if "date" in run.frame.columns else 0,
                            "sections": int(run.frame["section"].nunique()) if "section" in run.frame.columns else 0,
                        }
                    )

                    if run.frame.empty and run.eligible.empty:
                        continue

                    results = _run_single_segment(run)
                    cross = results["cross"]
                    cell_vs_rest = results["cell_vs_rest"]
                    spearman = results["spearman"]
                    dd_bin = results["dd_bin"]

                    _write_csv(cross, output_dir / f"{segment_key}_kakuban_dd_cross.csv")
                    _write_csv(cell_vs_rest, output_dir / f"{segment_key}_kakuban_dd_cell_vs_rest.csv")
                    _write_csv(spearman, output_dir / f"{segment_key}_kakuban_dd_spearman.csv")
                    _write_csv(dd_bin, output_dir / f"{segment_key}_dd_bin_kakuban_kruskal.csv")
                    _make_heatmap(segment_key, cross, output_dir / f"{segment_key}_kakuban_dd_heatmap.png")

                    sig_cell = _sig_only(cell_vs_rest, "kruskal_q")
                    sig_spear = _sig_only(spearman, "spearman_q")
                    sig_dd_bin = _sig_only(dd_bin, "kruskal_q")

                    if not sig_cell.empty:
                        all_cell_sig.append(sig_cell.assign(segment=segment_key))
                    if not spearman.empty:
                        all_spearman.append(spearman.assign(segment=segment_key))
                    if not sig_spear.empty:
                        all_spearman_sig.append(sig_spear.assign(segment=segment_key))
                    if not sig_dd_bin.empty:
                        all_dd_bin_sig.append(sig_dd_bin.assign(segment=segment_key))
                    if not dd_bin.empty:
                        all_dd_bin.append(dd_bin.assign(segment=segment_key))

    coverage = pd.DataFrame(coverage_rows)
    cell_sig = pd.concat(all_cell_sig, ignore_index=True) if all_cell_sig else pd.DataFrame()
    spearman_all = pd.concat(all_spearman, ignore_index=True) if all_spearman else pd.DataFrame()
    spearman_sig = pd.concat(all_spearman_sig, ignore_index=True) if all_spearman_sig else pd.DataFrame()
    dd_bin_sig = pd.concat(all_dd_bin_sig, ignore_index=True) if all_dd_bin_sig else pd.DataFrame()
    dd_bin_all = pd.concat(all_dd_bin, ignore_index=True) if all_dd_bin else pd.DataFrame()

    report = _build_report(
        coverage=coverage,
        significant_cells=cell_sig,
        significant_spearman=spearman_sig,
        significant_dd_bin=dd_bin_sig,
        all_dd_bin=dd_bin_all,
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    return {
        "coverage": coverage,
        "cell_sig": cell_sig,
        "spearman_all": spearman_all,
        "spearman_sig": spearman_sig,
        "dd_bin_sig": dd_bin_sig,
        "dd_bin_all": dd_bin_all,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kamata7 kakuban L/R cross EDA.")
    parser.add_argument("--db7", type=Path, default=DEFAULT_DB_7)
    parser.add_argument("--coords-2f", dest="coords_2f", type=Path, default=DEFAULT_COORDS_7_2F)
    parser.add_argument("--coords-3f", dest="coords_3f", type=Path, default=DEFAULT_COORDS_7_3F)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--min-games", type=int, default=DEFAULT_MIN_GAMES_ANALYSIS)
    parser.add_argument("--min-section-size", type=int, default=DEFAULT_MIN_SECTION_SIZE)
    parser.add_argument("--max-kakuban", type=int, default=DEFAULT_MAX_KAKUBAN)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    specs = [
        SegmentSpec(
            hall_slug="kamata7",
            hall_name=infer_hall_name(args.coords_2f, floor="2F"),
            floor="2F",
            db_path=args.db7,
            coords_path=args.coords_2f,
        ),
        SegmentSpec(
            hall_slug="kamata7",
            hall_name=infer_hall_name(args.coords_3f, floor="3F"),
            floor="3F",
            db_path=args.db7,
            coords_path=args.coords_3f,
        ),
    ]
    report_path = DEFAULT_REPORT_PATH if args.output_dir == DEFAULT_OUTPUT_DIR else args.output_dir / "report.md"
    run_analysis(
        specs=specs,
        output_dir=args.output_dir,
        report_path=report_path,
        min_games=args.min_games,
        min_section_size=args.min_section_size,
        max_kakuban=args.max_kakuban,
    )
    print(args.output_dir)
    print(report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
