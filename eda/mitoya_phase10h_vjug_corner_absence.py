from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kruskal

from eda import mitoya_phase10_segment_validation as phase10
from eda.mitoya_prompt_common import (
    ensure_results_dir,
    kw_epsilon_squared,
    load_mitoya_frame,
    render_markdown_table,
    section_sort_key,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "mitoya_phase10h_vjug_corner_absence"
SEGMENT_ORDER = ["h_jug", "v_jug"]
CORNER_BUCKET_ORDER = ["corner1", "corner2-4", "corner5-9", "corner10+"]
ORIENTATION_ORDER = ["horizontal", "vertical"]
STEP5_NOTE_ORDER = ["raw", "residual"]


def _prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    return phase10._prepare_frame(df)  # noqa: SLF001


def _segment_frame(work: pd.DataFrame, segment: str) -> pd.DataFrame:
    if segment not in SEGMENT_ORDER:
        raise KeyError(segment)
    return phase10._segment_frame(work, segment)  # noqa: SLF001


def _group_stats(frame: pd.DataFrame, group_col: str, *, order: list[str] | None = None) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=[group_col, "n", "avg_diff", "plus_rate"])
    rows: list[dict[str, object]] = []
    for level, grp in frame.groupby(group_col, dropna=False, sort=False):
        values = pd.to_numeric(grp["diff"], errors="coerce").dropna()
        rows.append(
            {
                group_col: str(level),
                "n": int(len(values)),
                "avg_diff": float(values.mean()) if len(values) else float("nan"),
                "plus_rate": float((values > 0).mean() * 100) if len(values) else float("nan"),
            }
        )
    out = pd.DataFrame(rows)
    if order is not None and not out.empty:
        out[group_col] = pd.Categorical(out[group_col], categories=order, ordered=True)
        out = out.sort_values(group_col, kind="mergesort")
        out[group_col] = out[group_col].astype(str)
    return out.reset_index(drop=True)


def _kruskal_summary(
    frame: pd.DataFrame, group_col: str, *, value_col: str, order: list[str] | None = None
) -> dict[str, object]:
    work = frame.dropna(subset=[group_col, value_col]).copy()
    if work.empty:
        return {
            "kw_stat": float("nan"),
            "p_value": float("nan"),
            "epsilon_sq": float("nan"),
            "n_groups": 0,
            "n": 0,
        }
    if order is not None:
        work[group_col] = pd.Categorical(work[group_col].astype(str), categories=order, ordered=True)

    groups: list[np.ndarray] = []
    for _, grp in work.groupby(group_col, dropna=False, sort=False):
        values = pd.to_numeric(grp[value_col], errors="coerce").dropna().to_numpy(dtype=float)
        if len(values):
            groups.append(values)

    total_n = int(sum(len(group) for group in groups))
    if len(groups) < 2:
        return {
            "kw_stat": float("nan"),
            "p_value": float("nan"),
            "epsilon_sq": float("nan"),
            "n_groups": len(groups),
            "n": total_n,
        }

    try:
        kw_stat, p_value = kruskal(*groups)
    except ValueError:
        kw_stat, p_value = float("nan"), float("nan")

    return {
        "kw_stat": float(kw_stat) if pd.notna(kw_stat) else float("nan"),
        "p_value": float(p_value) if pd.notna(p_value) else float("nan"),
        "epsilon_sq": float(kw_epsilon_squared(float(kw_stat), len(groups), total_n)),
        "n_groups": len(groups),
        "n": total_n,
    }


def build_step1_corner_distribution(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    frame = work.dropna(subset=["section", "orientation", "corner_bucket"]).copy()
    if frame.empty:
        return pd.DataFrame(columns=["section", "orientation", "corner_bucket", "n", "pct"])

    for section, section_grp in frame.groupby("section", dropna=False, sort=False):
        total = int(len(section_grp))
        orientation = str(section_grp["orientation"].iloc[0]) if total else ""
        for corner_bucket in CORNER_BUCKET_ORDER:
            n = int(section_grp["corner_bucket"].astype(str).eq(corner_bucket).sum())
            rows.append(
                {
                    "section": str(section),
                    "orientation": orientation,
                    "corner_bucket": corner_bucket,
                    "n": n,
                    "pct": float((n / total) * 100) if total else float("nan"),
                }
            )

    table = pd.DataFrame(rows, columns=["section", "orientation", "corner_bucket", "n", "pct"])
    table["section"] = pd.Categorical(
        table["section"], categories=sorted(table["section"].unique(), key=section_sort_key), ordered=True
    )
    table["orientation"] = pd.Categorical(table["orientation"], categories=ORIENTATION_ORDER, ordered=True)
    table["corner_bucket"] = pd.Categorical(table["corner_bucket"], categories=CORNER_BUCKET_ORDER, ordered=True)
    table = table.sort_values(["section", "orientation", "corner_bucket"], kind="mergesort").reset_index(drop=True)
    table["section"] = table["section"].astype(str)
    table["orientation"] = table["orientation"].astype(str)
    table["corner_bucket"] = table["corner_bucket"].astype(str)
    return table


def build_step2_layout_stats(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        frame = _segment_frame(work, segment)
        if frame.empty:
            rows.append(
                {
                    "segment": segment,
                    "rank_from_aisle_mean": np.nan,
                    "rank_from_aisle_std": np.nan,
                    "section_size_mean": np.nan,
                    "section_size_std": np.nan,
                    "n_sections": 0,
                    "n": 0,
                }
            )
            continue

        rank_series = pd.to_numeric(frame["rank_from_aisle"], errors="coerce").dropna()
        section_sizes = frame.groupby("section", dropna=False)["machine_number"].nunique(dropna=True)
        rows.append(
            {
                "segment": segment,
                "rank_from_aisle_mean": float(rank_series.mean()) if not rank_series.empty else float("nan"),
                "rank_from_aisle_std": float(rank_series.std(ddof=1)) if len(rank_series) >= 2 else float("nan"),
                "section_size_mean": float(section_sizes.mean()) if not section_sizes.empty else float("nan"),
                "section_size_std": float(section_sizes.std(ddof=1)) if len(section_sizes) >= 2 else float("nan"),
                "n_sections": int(section_sizes.size),
                "n": int(len(frame)),
            }
        )

    table = pd.DataFrame(
        rows,
        columns=[
            "segment",
            "rank_from_aisle_mean",
            "rank_from_aisle_std",
            "section_size_mean",
            "section_size_std",
            "n_sections",
            "n",
        ],
    )
    table["segment"] = pd.Categorical(table["segment"], categories=SEGMENT_ORDER, ordered=True)
    table = table.sort_values("segment", kind="mergesort").reset_index(drop=True)
    table["segment"] = table["segment"].astype(str)
    return table


def build_step3_corner_comparison(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for corner_bucket in CORNER_BUCKET_ORDER:
        row: dict[str, object] = {"corner_bucket": corner_bucket}
        for segment in SEGMENT_ORDER:
            frame = _segment_frame(work, segment)
            scoped = frame.loc[frame["corner_bucket"].astype(str).eq(corner_bucket)].copy()
            values = pd.to_numeric(scoped["diff"], errors="coerce").dropna()
            row[f"{segment}_avg_diff"] = float(values.mean()) if len(values) else float("nan")
            row[f"{segment}_n"] = int(len(values))
            row[f"{segment}_plus_rate"] = float((values > 0).mean() * 100) if len(values) else float("nan")
        rows.append(row)
    table = pd.DataFrame(
        rows,
        columns=[
            "corner_bucket",
            "h_jug_avg_diff",
            "h_jug_n",
            "h_jug_plus_rate",
            "v_jug_avg_diff",
            "v_jug_n",
            "v_jug_plus_rate",
        ],
    )
    table["corner_bucket"] = pd.Categorical(table["corner_bucket"], categories=CORNER_BUCKET_ORDER, ordered=True)
    table = table.sort_values("corner_bucket", kind="mergesort").reset_index(drop=True)
    table["corner_bucket"] = table["corner_bucket"].astype(str)
    return table


def build_step4_machine_composition(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        frame = _segment_frame(work, segment)
        if frame.empty:
            continue
        segment_n = int(len(frame))
        stats = (
            frame.groupby("machine_name", dropna=False, sort=False)
            .agg(
                n=("diff", "size"),
                avg_diff=("diff", "mean"),
                plus_rate=("diff", lambda s: float(pd.to_numeric(s, errors="coerce").gt(0).mean() * 100)),
            )
            .reset_index()
        )
        stats["share_pct"] = stats["n"].astype(float) / float(segment_n) * 100.0
        stats = stats.sort_values(
            ["n", "avg_diff", "machine_name"], ascending=[False, False, True], kind="mergesort"
        ).head(10)
        for _, row in stats.iterrows():
            rows.append(
                {
                    "segment": segment,
                    "machine_name": str(row["machine_name"]),
                    "n": int(row["n"]),
                    "avg_diff": float(row["avg_diff"]),
                    "plus_rate": float(row["plus_rate"]),
                    "share_pct": float(row["share_pct"]),
                }
            )

    table = pd.DataFrame(rows, columns=["segment", "machine_name", "n", "avg_diff", "plus_rate", "share_pct"])
    if table.empty:
        return table
    table["segment"] = pd.Categorical(table["segment"], categories=SEGMENT_ORDER, ordered=True)
    table = table.sort_values(
        ["segment", "n", "avg_diff", "machine_name"], ascending=[True, False, False, True], kind="mergesort"
    ).reset_index(drop=True)
    table["segment"] = table["segment"].astype(str)
    return table


def build_step5_residual_corner(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        frame = _segment_frame(work, segment).copy()
        if frame.empty:
            for note in STEP5_NOTE_ORDER:
                rows.append(
                    {
                        "segment": segment,
                        "kw_stat": np.nan,
                        "p_value": np.nan,
                        "epsilon_sq": np.nan,
                        "n_groups": 0,
                        "n": 0,
                        "note": note,
                    }
                )
            continue

        raw = _kruskal_summary(frame, "corner_bucket", value_col="diff", order=CORNER_BUCKET_ORDER)
        frame["machine_mean_diff"] = frame.groupby("machine_name", dropna=False)["diff"].transform(
            lambda s: pd.to_numeric(s, errors="coerce").mean()
        )
        frame["residual"] = pd.to_numeric(frame["diff"], errors="coerce") - pd.to_numeric(
            frame["machine_mean_diff"], errors="coerce"
        )
        residual = _kruskal_summary(frame, "corner_bucket", value_col="residual", order=CORNER_BUCKET_ORDER)

        rows.append({"segment": segment, **raw, "note": "raw"})
        rows.append({"segment": segment, **residual, "note": "residual"})

    table = pd.DataFrame(rows, columns=["segment", "kw_stat", "p_value", "epsilon_sq", "n_groups", "n", "note"])
    if table.empty:
        return table
    table["segment"] = pd.Categorical(table["segment"], categories=SEGMENT_ORDER, ordered=True)
    table["note"] = pd.Categorical(table["note"], categories=STEP5_NOTE_ORDER, ordered=True)
    table = table.sort_values(["segment", "note"], kind="mergesort").reset_index(drop=True)
    table["segment"] = table["segment"].astype(str)
    table["note"] = table["note"].astype(str)
    return table


def build_report(artifacts: dict[str, pd.DataFrame | str]) -> str:
    lines = [
        "# Phase10h: v_jug corner absence analysis",
        "",
        "- scope: h_jug and v_jug only",
        "- corner_bucket: derived from rank_from_aisle via phase10._prepare_frame()",
        "- residual_definition: diff minus per-machine mean diff within each segment",
        "",
        "## Step 1: section corner distribution",
        "",
        render_markdown_table(artifacts["step1_corner_distribution"]),
        "",
        "## Step 2: layout stats",
        "",
        render_markdown_table(artifacts["step2_layout_stats"]),
        "",
        "## Step 3: corner comparison",
        "",
        render_markdown_table(artifacts["step3_corner_comparison"]),
        "",
        "## Step 4: machine composition",
        "",
        render_markdown_table(artifacts["step4_machine_composition"]),
        "",
        "## Step 5: residual corner test",
        "",
        render_markdown_table(artifacts["step5_residual_corner"]),
        "",
        "## Notes",
        "",
        "- raw uses diff directly",
        "- residual removes per-machine level effects before Kruskal-Wallis",
    ]
    return "\n".join(lines).rstrip() + "\n"


def build_all_artifacts(df: pd.DataFrame) -> dict[str, pd.DataFrame | str]:
    work = _prepare_frame(df)
    artifacts: dict[str, pd.DataFrame | str] = {
        "step1_corner_distribution": build_step1_corner_distribution(work),
        "step2_layout_stats": build_step2_layout_stats(work),
        "step3_corner_comparison": build_step3_corner_comparison(work),
        "step4_machine_composition": build_step4_machine_composition(work),
        "step5_residual_corner": build_step5_residual_corner(work),
    }
    artifacts["report"] = build_report(artifacts)
    return artifacts


def write_outputs(artifacts: dict[str, pd.DataFrame | str], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts["step1_corner_distribution"].to_csv(
        output_dir / "step1_corner_distribution.csv", index=False, encoding="utf-8-sig"
    )
    artifacts["step2_layout_stats"].to_csv(output_dir / "step2_layout_stats.csv", index=False, encoding="utf-8-sig")
    artifacts["step3_corner_comparison"].to_csv(
        output_dir / "step3_corner_comparison.csv", index=False, encoding="utf-8-sig"
    )
    artifacts["step4_machine_composition"].to_csv(
        output_dir / "step4_machine_composition.csv", index=False, encoding="utf-8-sig"
    )
    artifacts["step5_residual_corner"].to_csv(
        output_dir / "step5_residual_corner.csv", index=False, encoding="utf-8-sig"
    )
    (output_dir / "report.md").write_text(str(artifacts["report"]), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase10h: v_jug corner absence analysis")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--db", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    ensure_results_dir()
    args = parse_args(argv)
    original_db_path = None
    if args.db is not None:
        import eda.mitoya_prompt_common as common

        original_db_path = common.DB_PATH
        common.DB_PATH = args.db
    try:
        df = load_mitoya_frame(join_layout=True)
    finally:
        if original_db_path is not None:
            import eda.mitoya_prompt_common as common

            common.DB_PATH = original_db_path
    artifacts = build_all_artifacts(df)
    write_outputs(artifacts, args.output_dir)
    print(f"Wrote {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
