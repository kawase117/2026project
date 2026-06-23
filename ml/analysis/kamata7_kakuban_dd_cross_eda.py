from __future__ import annotations

import argparse
import sys
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
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "ml" / "analysis" / "results" / "kamata7_kakuban_dd_cross_eda"
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "report.md"
DEFAULT_MAX_KAKUBAN = 20

DD_BIN_BOUNDS = [
    (1, 6, "1-6"),
    (7, 12, "7-12"),
    (13, 18, "13-18"),
    (19, 24, "19-24"),
    (25, 31, "25-31"),
]


@dataclass(frozen=True)
class SegmentRun:
    spec: SegmentSpec
    segment_label: str
    segment_key: str
    frame: pd.DataFrame
    expanded: pd.DataFrame
    eligible: pd.DataFrame
    support: pd.Series


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


def _build_segment_run(
    spec: SegmentSpec,
    *,
    min_games: int,
    min_section_size: int,
    max_kakuban: int,
    segment_label: str,
) -> SegmentRun:
    base = _prepare_segment_frame(spec, min_games=min_games, min_section_size=min_section_size).copy()
    if base.empty:
        return SegmentRun(
            spec=spec,
            segment_label=segment_label,
            segment_key=f"{spec.hall_slug}_{spec.floor}_{segment_label}",
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
            segment_label=segment_label,
            segment_key=f"{spec.hall_slug}_{spec.floor}_{segment_label}",
        frame=segment_frame,
        expanded=expanded,
        eligible=segment_frame,
        support=pd.Series(dtype=int),
        )

    eligible = segment_frame[segment_frame["residual_eligible"] & segment_frame["residual"].notna()].copy()
    if eligible.empty:
        return SegmentRun(
            spec=spec,
            segment_label=segment_label,
            segment_key=f"{spec.hall_slug}_{spec.floor}_{segment_label}",
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
        segment_label=segment_label,
        segment_key=f"{spec.hall_slug}_{spec.floor}_{segment_label}",
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
    d1_sig: pd.DataFrame,
    d2_sig: pd.DataFrame,
    d3_sig: pd.DataFrame,
    d2_all: pd.DataFrame,
) -> str:
    lines = [
        "# Kamata7 kakuban × DD cross EDA report",
        "",
        "## 1. 分析設計",
        "",
        "- 対象ホールは蒲田7のみ。",
        "- 対象セグメントは `kamata7_2F_N`, `kamata7_3F_A`, `kamata7_3F_N`。",
        "- `kamata7_2F_A` は空ならスキップ。",
        "- `dd` は `date` の日部分（1〜31）。",
        "- 角番は `rank_from_min` と `rank_from_max` を両方使う expanded view で評価する。",
        "- そのため `n` は実台数の重複計上を含む。",
        "- `n < 10` の cell は集計値を残すが、D1-D3 の統計計算から除外する。",
        "",
        "## 2. Segment coverage",
        "",
        _df_to_markdown(coverage),
        "",
        "## 3. Analysis D1: kakuban × DD クロス（有意セルのみ、q < 0.05）",
        "",
    ]
    lines.append(_df_to_markdown(d1_sig))
    lines.append("")
    lines.extend(
        [
            "## 4. Analysis D2: kakuban ごとの DD Spearman 相関（q < 0.05 のみ）",
            "",
            _df_to_markdown(d2_sig),
            "",
            "## 5. Analysis D3: DDビン × kakuban Kruskal-Wallis（q < 0.05 のみ）",
            "",
            _df_to_markdown(d3_sig),
            "",
            "## 6. 結論",
            "",
        ]
    )

    sig_any = not d2_sig.empty
    if sig_any:
        best_pool = d2_sig if not d2_sig.empty else d2_all
        best = best_pool.dropna(subset=["spearman_r"]).copy()
        if best.empty:
            lines.append("Spearman 有意な kakuban × DD ペアはあるが、最大相関の候補を算出できなかった。")
            lines.append("最も DD 依存性が高い kakuban は判定不能。")
            lines.append("実用上は、有意ペアがあっても cell support 条件付きの再確認が必要。")
        else:
            best = best.loc[best["spearman_r"].abs().idxmax()]
            sign_text = "正" if float(best["spearman_r"]) > 0 else "負"
            best_segment = str(best["segment"]) if "segment" in best.index else "unknown"
            lines.append("Spearman 有意な kakuban × DD ペアはある。")
            lines.append(
                f"最も DD 依存性が高いのは {best_segment} の kakuban {int(best['kakuban'])} で、"
                f"r={_format_number(best['spearman_r'])}, q={_format_number(best['spearman_q'], 3)}。"
            )
            if int(best["dd"]) in {1, 25, 31}:
                dd_hint = f"DD={int(best['dd'])}"
            else:
                dd_hint = f"DD={int(best['dd'])}"
            lines.append(
                f"実用上は、{dd_hint} 付近で {sign_text}相関が出ているかを見るのが中心で、"
                "角番優先はこのDD帯での再現性がある場合に限って使うべき。"
            )
    else:
        best = d2_all.dropna(subset=["spearman_r"]).copy()
        if best.empty:
            lines.append("Spearman 有意な kakuban × DD ペアは確認できなかった。")
            lines.append("最も DD 依存性が高い kakuban は判定不能。")
        else:
            best = best.loc[best["spearman_r"].abs().idxmax()]
            best_segment = str(best["segment"]) if "segment" in best.index else "unknown"
            lines.append("Spearman 有意な kakuban × DD ペアは確認できなかった。")
            lines.append(
                f"最も DD 依存性が高いのは {best_segment} の kakuban {int(best['kakuban'])} で、"
                f"r={_format_number(best['spearman_r'])}, p={_format_number(best['spearman_p'], 3)}, "
                f"q={_format_number(best['spearman_q'], 3)}。"
            )
        lines.append("実用上は DD 25 や DD 1/31 の局所的な印象で選ばず、CSV の cross で再確認するのが安全。")

    return "\n".join(lines).rstrip() + "\n"


def _run_single_segment(
    run: SegmentRun,
) -> dict[str, pd.DataFrame]:
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

    return {
        "cross": cross,
        "cell_vs_rest": cell_vs_rest,
        "spearman": spearman,
        "dd_bin": dd_bin,
    }


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
    all_d1_sig: list[pd.DataFrame] = []
    all_d2: list[pd.DataFrame] = []
    all_d2_sig: list[pd.DataFrame] = []
    all_d3_sig: list[pd.DataFrame] = []

    for spec in specs:
        for segment_label in ("N", "A"):
            segment_key = f"{spec.hall_slug}_{spec.floor}_{segment_label}"
            run = _build_segment_run(
                spec,
                min_games=min_games,
                min_section_size=min_section_size,
                max_kakuban=max_kakuban,
                segment_label=segment_label,
            )
            if run.frame.empty:
                continue

            coverage_rows.append(
                {
                    "segment": segment_key,
                    "hall": spec.hall_slug,
                    "floor": spec.floor,
                    "segment_label": segment_label,
                    "rows": int(len(run.frame)),
                    "expanded_rows": int(len(run.expanded)),
                    "eligible_rows": int(len(run.eligible)),
                    "dates": int(pd.Index(run.frame["date"].dropna().unique()).size) if "date" in run.frame.columns else 0,
                    "sections": int(run.frame["section"].nunique()) if "section" in run.frame.columns else 0,
                }
            )

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
                all_d1_sig.append(sig_cell.assign(segment=segment_key))
            if not spearman.empty:
                all_d2.append(spearman.assign(segment=segment_key))
            if not sig_spear.empty:
                all_d2_sig.append(sig_spear.assign(segment=segment_key))
            if not sig_dd_bin.empty:
                all_d3_sig.append(sig_dd_bin.assign(segment=segment_key))

    coverage = pd.DataFrame(coverage_rows)
    d1_sig = pd.concat(all_d1_sig, ignore_index=True) if all_d1_sig else pd.DataFrame()
    d2_all = pd.concat(all_d2, ignore_index=True) if all_d2 else pd.DataFrame()
    d2_sig = pd.concat(all_d2_sig, ignore_index=True) if all_d2_sig else pd.DataFrame()
    d3_sig = pd.concat(all_d3_sig, ignore_index=True) if all_d3_sig else pd.DataFrame()

    report = _build_report(
        coverage=coverage,
        d1_sig=d1_sig,
        d2_sig=d2_sig,
        d3_sig=d3_sig,
        d2_all=d2_all,
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    return {
        "coverage": coverage,
        "d1_sig": d1_sig,
        "d2_all": d2_all,
        "d2_sig": d2_sig,
        "d3_sig": d3_sig,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kamata7 kakuban × DD cross EDA.")
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
    run_analysis(
        specs=specs,
        output_dir=args.output_dir,
        report_path=DEFAULT_REPORT_PATH if args.output_dir == DEFAULT_OUTPUT_DIR else args.output_dir / "report.md",
        min_games=args.min_games,
        min_section_size=args.min_section_size,
        max_kakuban=args.max_kakuban,
    )
    print(args.output_dir)
    print(DEFAULT_REPORT_PATH if args.output_dir == DEFAULT_OUTPUT_DIR else args.output_dir / "report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
