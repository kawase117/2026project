"""
角番位置効果の時系列安定性 + 機種交互作用 EDA

Analysis T: 年別 × kakuban_bin (corner/middle/deep_end)
  - 中間台優位が年をまたいで安定するか検証
  - corner=-80 → middle=+100 のパターンが 2024/2025/2026 各年に共通するか

Analysis S: 機種カテゴリ × kakuban_bin (A-type セグメントのみ)
  - ジャグラー vs ハナハナ vs BT で中間優位の大きさが変わるか
  - 機種によっては端台優遇という可能性を排除する

使用方法:
  python -m ml.analysis.kamata_kakuban_temporal_species_eda
  python -m ml.analysis.kamata_kakuban_temporal_species_eda --min-year 2025
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.analysis.kamata_kakuban_section_residual_eda import (
    SegmentSpec,
    _bh_adjust,
    _expand_dual_kakuban,
    _kruskal_pvalue,
    _prepare_segment_frame,
    _write_csv,
    DEFAULT_COORDS_1,
    DEFAULT_COORDS_7_2F,
    DEFAULT_COORDS_7_3F,
    DEFAULT_DB_1,
    DEFAULT_DB_7,
    DEFAULT_MIN_GAMES_ANALYSIS,
)
from ml.analysis.kamata_corner_mirror_analysis import infer_hall_name


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "ml" / "analysis" / "results" / "kamata_kakuban_temporal_species_eda"
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "report.md"

# kakuban_bin 境界: インスティンクト確定値に合わせる
KAKUBAN_BIN_DEFS = [
    (1, 4, "corner"),
    (5, 11, "middle"),
    (12, 999, "deep_end"),
]

BIN_ORDER = ["corner", "middle", "deep_end"]
SPECIES_PRIORITY = {"ジャグラー": 0, "ハナハナ": 1, "BT": 2, "other": 3}


# ---------------------------------------------------------------------------
# 共通ヘルパー
# ---------------------------------------------------------------------------

def _assign_kakuban_bin(s: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(s, errors="coerce")
    result = pd.Series("unknown", index=s.index, dtype=object)
    for lo, hi, label in KAKUBAN_BIN_DEFS:
        result[numeric.between(lo, hi, inclusive="both")] = label
    return result


def _assign_species(frame: pd.DataFrame) -> pd.Series:
    species = pd.Series("other", index=frame.index, dtype=object)
    for col, label in [("hana_flag", "ハナハナ"), ("jug_flag", "ジャグラー"), ("bt_flag", "BT")]:
        flag = pd.to_numeric(frame.get(col, pd.Series(0, index=frame.index)), errors="coerce").fillna(0)
        species[flag.eq(1)] = label
    return species


def _prepare_expanded(
    frame: pd.DataFrame,
    *,
    segment_label: str | None = None,
) -> pd.DataFrame:
    work = frame.copy()
    if segment_label is not None:
        work = work[work["machine_type_segment"].eq(segment_label)]
    work = work[work["residual_eligible"]].copy()
    work = _expand_dual_kakuban(work).dropna(subset=["kakuban", "residual"]).copy()
    work["kakuban_bin"] = _assign_kakuban_bin(work["kakuban"])
    work = work[work["kakuban_bin"].ne("unknown")].copy()
    return work


def _bin_stats(series: pd.Series) -> dict:
    vals = pd.to_numeric(series, errors="coerce").dropna()
    return {
        "mean_residual": float(vals.mean()) if len(vals) else np.nan,
        "median_residual": float(vals.median()) if len(vals) else np.nan,
        "n": int(len(vals)),
    }


def _middle_minus_corner(rows_for_group: pd.DataFrame) -> float:
    corner = rows_for_group.loc[rows_for_group["kakuban_bin"].eq("corner"), "mean_residual"]
    middle = rows_for_group.loc[rows_for_group["kakuban_bin"].eq("middle"), "mean_residual"]
    if corner.empty or middle.empty:
        return np.nan
    c = float(corner.iloc[0])
    m = float(middle.iloc[0])
    if np.isfinite(c) and np.isfinite(m):
        return m - c
    return np.nan


# ---------------------------------------------------------------------------
# Analysis T: 時系列安定性
# ---------------------------------------------------------------------------

def build_analysis_temporal(
    frame: pd.DataFrame,
    *,
    segment_label: str,
    min_year: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns:
        detail: (year, kakuban_bin) × stats
        summary: year × (kruskal_p, middle_minus_corner)
    """
    work = _prepare_expanded(frame, segment_label=segment_label)
    work["year"] = pd.to_datetime(work["date"], errors="coerce").dt.year.astype("Int64")
    if min_year is not None:
        work = work[work["year"].ge(min_year)]
    work = work[work["year"].notna()].copy()

    years = sorted(work["year"].dropna().unique().tolist())

    detail_rows: list[dict] = []
    summary_rows: list[dict] = []

    for year in years:
        year_df = work[work["year"].eq(year)]
        bin_groups = [
            year_df.loc[year_df["kakuban_bin"].eq(b), "residual"].astype(float).dropna()
            for b in BIN_ORDER
        ]
        kp = _kruskal_pvalue(bin_groups)

        year_detail: list[dict] = []
        for bin_label in BIN_ORDER:
            stats = _bin_stats(year_df.loc[year_df["kakuban_bin"].eq(bin_label), "residual"])
            row = {"year": int(year), "kakuban_bin": bin_label, **stats}
            detail_rows.append(row)
            year_detail.append(row)

        year_det_df = pd.DataFrame(year_detail)
        gap = _middle_minus_corner(year_det_df)

        summary_rows.append({
            "year": int(year),
            "kruskal_p": kp,
            "middle_minus_corner": gap,
            "n_corner": int(bin_groups[0].shape[0]),
            "n_middle": int(bin_groups[1].shape[0]),
            "n_deep_end": int(bin_groups[2].shape[0]),
        })

    detail = pd.DataFrame(detail_rows)
    summary = pd.DataFrame(summary_rows)

    if len(summary) >= 3 and "middle_minus_corner" in summary.columns:
        valid = summary[summary["middle_minus_corner"].notna()]
        if len(valid) >= 3:
            rho, sp = spearmanr(valid["year"], valid["middle_minus_corner"])
            summary["spearman_rho_trend"] = float(rho)
            summary["spearman_p_trend"] = float(sp)

    return detail, summary


# ---------------------------------------------------------------------------
# Analysis S: 機種 × 角番 交互作用
# ---------------------------------------------------------------------------

def build_analysis_species(frame: pd.DataFrame, *, segment_label: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns:
        detail: (machine_species, kakuban_bin) × stats
        summary: machine_species × (kruskal_p, middle_minus_corner)
    """
    work = _prepare_expanded(frame, segment_label=segment_label)
    work["machine_species"] = _assign_species(work)

    species_list = sorted(
        work["machine_species"].unique(),
        key=lambda x: SPECIES_PRIORITY.get(x, 99),
    )

    detail_rows: list[dict] = []
    summary_rows: list[dict] = []

    for sp in species_list:
        sp_df = work[work["machine_species"].eq(sp)]
        if len(sp_df) < 30:
            continue

        bin_groups = [
            sp_df.loc[sp_df["kakuban_bin"].eq(b), "residual"].astype(float).dropna()
            for b in BIN_ORDER
        ]
        kp = _kruskal_pvalue(bin_groups)

        sp_detail: list[dict] = []
        for bin_label in BIN_ORDER:
            stats = _bin_stats(sp_df.loc[sp_df["kakuban_bin"].eq(bin_label), "residual"])
            row = {"machine_species": sp, "kakuban_bin": bin_label, **stats}
            detail_rows.append(row)
            sp_detail.append(row)

        sp_det_df = pd.DataFrame(sp_detail)
        gap = _middle_minus_corner(sp_det_df)

        summary_rows.append({
            "machine_species": sp,
            "kruskal_p": kp,
            "middle_minus_corner": gap,
            "n_corner": int(bin_groups[0].shape[0]),
            "n_middle": int(bin_groups[1].shape[0]),
            "n_deep_end": int(bin_groups[2].shape[0]),
        })

    detail = pd.DataFrame(detail_rows)
    summary = pd.DataFrame(summary_rows)

    if not summary.empty and "kruskal_p" in summary.columns:
        summary["kruskal_q"] = _bh_adjust(summary["kruskal_p"])

    return detail, summary


# ---------------------------------------------------------------------------
# レポート生成
# ---------------------------------------------------------------------------

def _df_to_md(df: pd.DataFrame, float_fmt: str = ".1f") -> str:
    if df.empty:
        return "No data."
    frame = df.copy()
    for col in frame.select_dtypes(include="float").columns:
        frame[col] = frame[col].apply(
            lambda v: f"{v:{float_fmt}}" if pd.notna(v) else ""
        )
    cols = [str(c) for c in frame.columns]
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join(["---"] * len(cols)) + " |"
    body = [
        "| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |"
        for _, row in frame.iterrows()
    ]
    return "\n".join([header, sep] + body)


def _build_report(results: dict[str, dict]) -> str:
    lines = [
        "# Kamata kakuban 時系列安定性 + 機種交互作用 EDA",
        "",
        "kakuban_bin: corner=1-4, middle=5-11, deep_end=12+",
        "残差 = diff_coins_normalized - セクション日次平均（セクション台数 >= 3 の日のみ有効）",
        "",
    ]

    for seg_key, seg_data in sorted(results.items()):
        lines.append(f"## セグメント: {seg_key}")
        lines.append("")

        lines.append("### Analysis T: 年別 kakuban_bin 残差（時系列安定性）")
        lines.append("")
        lines.append("#### 詳細（year × kakuban_bin）")
        lines.append(_df_to_md(seg_data.get("temporal_detail", pd.DataFrame())))
        lines.append("")
        lines.append("#### サマリー（year）")
        lines.append(_df_to_md(seg_data.get("temporal_summary", pd.DataFrame())))
        lines.append("")

        ts = seg_data.get("temporal_summary", pd.DataFrame())
        if not ts.empty and "middle_minus_corner" in ts.columns:
            valid_gaps = ts["middle_minus_corner"].dropna()
            if len(valid_gaps):
                consistent = bool((valid_gaps > 0).all())
                trend_col = "spearman_rho_trend"
                rho_str = ""
                if trend_col in ts.columns and ts[trend_col].notna().any():
                    rho = float(ts[trend_col].iloc[0])
                    rho_str = f"  Spearman ρ={rho:+.3f}（{'増加傾向' if rho > 0.3 else '減少傾向' if rho < -0.3 else '安定'}）"
                lines.append(
                    f"**結論**: middle-corner gap が全年プラス → {'安定' if consistent else '不安定（一部年でギャップが逆転）'}{rho_str}"
                )
                lines.append("")

        lines.append("### Analysis S: 機種別 kakuban_bin 残差（A-type のみ）")
        lines.append("")
        lines.append("#### 詳細（machine_species × kakuban_bin）")
        lines.append(_df_to_md(seg_data.get("species_detail", pd.DataFrame())))
        lines.append("")
        lines.append("#### サマリー（machine_species）")
        lines.append(_df_to_md(seg_data.get("species_summary", pd.DataFrame())))
        lines.append("")

        ss = seg_data.get("species_summary", pd.DataFrame())
        if not ss.empty and "middle_minus_corner" in ss.columns:
            valid = ss.dropna(subset=["middle_minus_corner"])
            if not valid.empty:
                consistent = bool((valid["middle_minus_corner"] > 0).all())
                lines.append(
                    f"**結論**: 全機種でmiddle優位 → {'Yes（機種問わず中間優位は安定）' if consistent else 'No（機種によって差異あり）'}"
                )
                lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def run(
    *,
    specs: list[SegmentSpec],
    output_dir: Path,
    report_path: Path,
    min_year: int | None = None,
    min_games: int = DEFAULT_MIN_GAMES_ANALYSIS,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict] = {}

    for spec in specs:
        try:
            frame = _prepare_segment_frame(spec, min_games=min_games)
        except ValueError as exc:
            print(f"[SKIP] {spec.hall_slug} {spec.floor}: {exc}")
            continue

        for segment_label in ("A", "N"):
            seg_key = f"{spec.hall_slug}_{spec.floor}_{segment_label}"
            seg_frame = frame[frame["machine_type_segment"].eq(segment_label)].copy()

            n_rows = len(seg_frame[seg_frame["residual_eligible"]])
            if n_rows < 100:
                print(f"[SKIP] {seg_key}: eligible rows={n_rows}")
                results[seg_key] = {}
                continue

            print(f"[RUN]  {seg_key}: eligible rows={n_rows}")

            t_detail, t_summary = build_analysis_temporal(
                seg_frame, segment_label=segment_label, min_year=min_year
            )
            s_detail, s_summary = build_analysis_species(seg_frame, segment_label=segment_label)

            prefix = output_dir / seg_key
            _write_csv(t_detail, Path(str(prefix) + "_temporal_detail.csv"))
            _write_csv(t_summary, Path(str(prefix) + "_temporal_summary.csv"))
            _write_csv(s_detail, Path(str(prefix) + "_species_detail.csv"))
            _write_csv(s_summary, Path(str(prefix) + "_species_summary.csv"))

            results[seg_key] = {
                "temporal_detail": t_detail,
                "temporal_summary": t_summary,
                "species_detail": s_detail,
                "species_summary": s_summary,
            }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_build_report(results), encoding="utf-8")
    print(f"\nReport: {report_path}")
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="角番位置効果の時系列安定性・機種交互作用 EDA")
    parser.add_argument("--db1", type=Path, default=DEFAULT_DB_1)
    parser.add_argument("--db7", type=Path, default=DEFAULT_DB_7)
    parser.add_argument("--coords1", type=Path, default=DEFAULT_COORDS_1)
    parser.add_argument("--coords7-2f", dest="coords7_2f", type=Path, default=DEFAULT_COORDS_7_2F)
    parser.add_argument("--coords7-3f", dest="coords7_3f", type=Path, default=DEFAULT_COORDS_7_3F)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--min-year", type=int, default=None, help="この年以降のデータのみ使用")
    parser.add_argument("--min-games", type=int, default=DEFAULT_MIN_GAMES_ANALYSIS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    specs = [
        SegmentSpec(
            hall_slug="kamata1",
            hall_name=infer_hall_name(args.coords1, floor="2F"),
            floor="2F",
            db_path=args.db1,
            coords_path=args.coords1,
        ),
        SegmentSpec(
            hall_slug="kamata7",
            hall_name=infer_hall_name(args.coords7_2f, floor="2F"),
            floor="2F",
            db_path=args.db7,
            coords_path=args.coords7_2f,
        ),
        SegmentSpec(
            hall_slug="kamata7",
            hall_name=infer_hall_name(args.coords7_3f, floor="3F"),
            floor="3F",
            db_path=args.db7,
            coords_path=args.coords7_3f,
        ),
    ]
    run(
        specs=specs,
        output_dir=args.output_dir,
        report_path=args.report_path,
        min_year=args.min_year,
        min_games=args.min_games,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
