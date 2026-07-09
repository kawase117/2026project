from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from eda import mitoya_phase10_segment_validation as phase10
import eda.mitoya_prompt_common as common
from eda.mitoya_prompt_common import (
    DEBUT_PHASE_ORDER,
    add_debut_phase,
    add_event_category,
    ensure_results_dir,
    load_mitoya_frame,
    render_markdown_table,
)
from eda.mitoya_prompt_common import DB_PATH as MITOYA_DB_PATH

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "mitoya_phase10g_mixed805_cell_heatmap"
SEGMENT_ORDER = ["mixed_805", "h_nonjug", "h_jug"]
ANALYSIS_EVENT_ORDER = [0, 1]


def _prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    work = add_debut_phase(df)
    work = add_event_category(work)
    work = phase10._prepare_frame(work)  # noqa: SLF001
    if "is_moved" in work.columns:
        work = work.loc[~work["is_moved"].astype(bool)].copy()
    else:
        work = work.copy()
    return work


def _segment_frame(work: pd.DataFrame, segment: str) -> pd.DataFrame:
    return phase10._segment_frame(work, segment)  # noqa: SLF001


def _cell_group_stats(frame: pd.DataFrame, debut_phase: str, is_xdds: int) -> dict[str, object]:
    scoped = frame.loc[
        frame["debut_phase"].astype(str).eq(debut_phase) & frame["is_xdds_day"].astype(int).eq(is_xdds)
    ].copy()
    values = pd.to_numeric(scoped["diff"], errors="coerce").dropna()
    n = int(len(values))
    if n == 0:
        return {
            "n": 0,
            "avg_diff": 0.0,
            "plus_rate": 0.0,
        }
    return {
        "n": n,
        "avg_diff": float(values.mean()),
        "plus_rate": float((values > 0).mean() * 100.0),
    }


def build_step1_cell_stats(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    scoped = work.loc[work["event_category"].astype(str).isin({"X_DDS", "非イベント日"})].copy()
    for segment in SEGMENT_ORDER:
        frame = _segment_frame(scoped, segment)
        if frame.empty:
            continue
        for debut_phase in DEBUT_PHASE_ORDER:
            for is_xdds in ANALYSIS_EVENT_ORDER:
                stats = _cell_group_stats(frame, debut_phase, is_xdds)
                rows.append(
                    {
                        "segment": segment,
                        "debut_phase": debut_phase,
                        "is_xdds": int(is_xdds),
                        "n": int(stats["n"]),
                        "avg_diff": float(stats["avg_diff"]),
                        "plus_rate": float(stats["plus_rate"]),
                    }
                )
    table = pd.DataFrame(rows, columns=["segment", "debut_phase", "is_xdds", "n", "avg_diff", "plus_rate"])
    if table.empty:
        return table
    table["segment"] = pd.Categorical(table["segment"], categories=SEGMENT_ORDER, ordered=True)
    table["debut_phase"] = pd.Categorical(table["debut_phase"], categories=DEBUT_PHASE_ORDER, ordered=True)
    table["is_xdds"] = pd.Categorical(table["is_xdds"], categories=ANALYSIS_EVENT_ORDER, ordered=True)
    table = table.sort_values(["segment", "debut_phase", "is_xdds"], kind="mergesort").reset_index(drop=True)
    table["segment"] = table["segment"].astype(str)
    table["debut_phase"] = table["debut_phase"].astype(str)
    table["is_xdds"] = table["is_xdds"].astype(int)
    return table


def build_step2_cell_contrast(cell_stats: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        seg = cell_stats.loc[cell_stats["segment"].astype(str).eq(segment)].copy()
        for debut_phase in DEBUT_PHASE_ORDER:
            phase = seg.loc[seg["debut_phase"].astype(str).eq(debut_phase)].copy()
            xdds_row = phase.loc[phase["is_xdds"].astype(int).eq(1)]
            nonevent_row = phase.loc[phase["is_xdds"].astype(int).eq(0)]
            xdds_avg = float(xdds_row["avg_diff"].iloc[0]) if not xdds_row.empty else 0.0
            nonevent_avg = float(nonevent_row["avg_diff"].iloc[0]) if not nonevent_row.empty else 0.0
            xdds_n = int(xdds_row["n"].iloc[0]) if not xdds_row.empty else 0
            nonevent_n = int(nonevent_row["n"].iloc[0]) if not nonevent_row.empty else 0
            rows.append(
                {
                    "segment": segment,
                    "debut_phase": debut_phase,
                    "xdds_avg_diff": xdds_avg,
                    "nonevent_avg_diff": nonevent_avg,
                    "contrast": float(xdds_avg - nonevent_avg),
                    "xdds_n": xdds_n,
                    "nonevent_n": nonevent_n,
                }
            )
    table = pd.DataFrame(
        rows,
        columns=["segment", "debut_phase", "xdds_avg_diff", "nonevent_avg_diff", "contrast", "xdds_n", "nonevent_n"],
    )
    if table.empty:
        return table
    table["segment"] = pd.Categorical(table["segment"], categories=SEGMENT_ORDER, ordered=True)
    table["debut_phase"] = pd.Categorical(table["debut_phase"], categories=DEBUT_PHASE_ORDER, ordered=True)
    table = table.sort_values(["segment", "debut_phase"], kind="mergesort").reset_index(drop=True)
    table["segment"] = table["segment"].astype(str)
    table["debut_phase"] = table["debut_phase"].astype(str)
    return table


def build_step3_driver_identification(cell_stats: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        seg = cell_stats.loc[cell_stats["segment"].astype(str).eq(segment)].copy()
        valid = seg.loc[seg["n"].astype(int) >= 10].copy()
        if valid.empty:
            continue
        values = pd.to_numeric(valid["avg_diff"], errors="coerce")
        mean = float(values.mean()) if values.notna().any() else 0.0
        std = float(values.std(ddof=0)) if values.notna().sum() >= 2 else 0.0
        if not np.isfinite(std) or std == 0.0:
            std = 0.0
        for _, row in valid.iterrows():
            avg_diff = float(row["avg_diff"])
            z_score = 0.0 if std == 0.0 else float((avg_diff - mean) / std)
            rows.append(
                {
                    "segment": segment,
                    "debut_phase": row["debut_phase"],
                    "is_xdds": int(row["is_xdds"]),
                    "avg_diff": avg_diff,
                    "z_score": z_score,
                    "is_outlier": abs(z_score) > 1.5,
                }
            )
    table = pd.DataFrame(rows, columns=["segment", "debut_phase", "is_xdds", "avg_diff", "z_score", "is_outlier"])
    if table.empty:
        return table
    table["segment"] = pd.Categorical(table["segment"], categories=SEGMENT_ORDER, ordered=True)
    table["debut_phase"] = pd.Categorical(table["debut_phase"], categories=DEBUT_PHASE_ORDER, ordered=True)
    table = table.sort_values(["segment", "debut_phase", "is_xdds"], kind="mergesort").reset_index(drop=True)
    table["segment"] = table["segment"].astype(str)
    table["debut_phase"] = table["debut_phase"].astype(str)
    table["is_xdds"] = table["is_xdds"].astype(int)
    table["is_outlier"] = table["is_outlier"].astype(bool)
    return table


def build_step4_summary(contrast_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        seg = contrast_df.loc[contrast_df["segment"].astype(str).eq(segment)].copy()
        if seg.empty:
            continue
        best = seg.sort_values(["contrast", "debut_phase"], ascending=[False, True], kind="mergesort").iloc[0]
        rows.append(
            {
                "segment": segment,
                "max_contrast_phase": str(best["debut_phase"]),
                "contrast": float(best["contrast"]),
                "xdds_n": int(best["xdds_n"]),
                "nonevent_n": int(best["nonevent_n"]),
            }
        )
    table = pd.DataFrame(rows, columns=["segment", "max_contrast_phase", "contrast", "xdds_n", "nonevent_n"])
    if table.empty:
        return table
    table["segment"] = pd.Categorical(table["segment"], categories=SEGMENT_ORDER, ordered=True)
    table = table.sort_values("segment", kind="mergesort").reset_index(drop=True)
    table["segment"] = table["segment"].astype(str)
    return table


def build_report(artifacts: dict[str, pd.DataFrame | str]) -> str:
    step1 = artifacts["step1_cell_stats"]
    step2 = artifacts["step2_cell_contrast"]
    step3 = artifacts["step3_driver_identification"]
    step4 = artifacts["step4_summary"]

    mixed_summary = step4.loc[step4["segment"].astype(str).eq("mixed_805")]
    if mixed_summary.empty:
        finding = "mixed_805 の優位セルは特定できなかった。"
    else:
        row = mixed_summary.iloc[0]
        finding = f"mixed_805 では {row['max_contrast_phase']} が最大 contrast ({row['contrast']:.3f}) で、X_DDS 優位が最も強い。"

    outlier_text = "outlier は検出されなかった。"
    mixed_outliers = step3.loc[step3["segment"].astype(str).eq("mixed_805") & step3["is_outlier"].astype(bool)]
    if not mixed_outliers.empty:
        top = mixed_outliers.sort_values("z_score", ascending=False, kind="mergesort").iloc[0]
        outlier_text = f"mixed_805 の外れセルは debut_phase={top['debut_phase']}, is_xdds={int(top['is_xdds'])}, z={float(top['z_score']):.3f}。"

    lines = [
        "# Phase10g: mixed_805 debut×X_DDS セル分解",
        "",
        "## Step 1: セル別統計",
        render_markdown_table(step1),
        "",
        "## Step 2: セル間コントラスト",
        render_markdown_table(step2),
        "",
        "## Step 3: 駆動セル特定",
        render_markdown_table(step3.loc[step3["is_outlier"].astype(bool)]),
        "",
        "## Step 4: セグメント横断サマリ",
        render_markdown_table(step4),
        "",
        "## Finding",
        finding,
        outlier_text,
    ]
    return "\n".join(lines)


def build_all_artifacts(df: pd.DataFrame) -> dict[str, pd.DataFrame | str]:
    work = _prepare_frame(df)
    step1 = build_step1_cell_stats(work)
    step2 = build_step2_cell_contrast(step1)
    step3 = build_step3_driver_identification(step1)
    step4 = build_step4_summary(step2)
    artifacts: dict[str, pd.DataFrame | str] = {
        "step1_cell_stats": step1,
        "step2_cell_contrast": step2,
        "step3_driver_identification": step3,
        "step4_summary": step4,
    }
    artifacts["report"] = build_report(artifacts)
    return artifacts


def write_outputs(artifacts: dict[str, pd.DataFrame | str], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    casts = {
        "step1_cell_stats": "step1_cell_stats.csv",
        "step2_cell_contrast": "step2_cell_contrast.csv",
        "step3_driver_identification": "step3_driver_identification.csv",
        "step4_summary": "step4_summary.csv",
    }
    for key, name in casts.items():
        cast_df = artifacts[key]
        if isinstance(cast_df, pd.DataFrame):
            cast_df.to_csv(output_dir / name, index=False, encoding="utf-8-sig")
    (output_dir / "report.md").write_text(str(artifacts["report"]), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase10g: mixed_805 debut x X_DDS cell heatmap analysis")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--db", type=Path, default=MITOYA_DB_PATH)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    ensure_results_dir()
    args = parse_args(argv)
    original_db_path = common.DB_PATH
    try:
        common.DB_PATH = args.db
        df = load_mitoya_frame(join_layout=True)
    finally:
        common.DB_PATH = original_db_path
    artifacts = build_all_artifacts(df)
    write_outputs(artifacts, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
