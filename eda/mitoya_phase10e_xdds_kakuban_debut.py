from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kruskal, spearmanr
from statsmodels.formula.api import ols
from statsmodels.stats.anova import anova_lm

import eda.mitoya_prompt_common as common
from eda import mitoya_phase10_segment_validation as phase10
from eda.mitoya_prompt_common import (
    DEBUT_PHASE_ORDER,
    EVENT_CATEGORY_ORDER,
    X_DDS,
    add_debut_phase,
    add_event_category,
    ensure_results_dir,
    kw_epsilon_squared,
    load_mitoya_frame,
    render_markdown_table,
)
from eda.mitoya_prompt_common import DB_PATH as MITOYA_DB_PATH

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "mitoya_phase10e_xdds_kakuban_debut"
SEGMENT_ORDER = ["h_jug", "h_nonjug", "v_jug", "v_nonjug", "mixed_805"]
CORNER_BUCKET_ORDER = ["corner1", "corner2-4", "corner5-9", "corner10+"]
ANALYSIS_SCOPE_ORDER = ["X_DDS", "非イベント日"]
SPEARMAN_SCOPE_ORDER = ["all", "X_DDS", "非イベント日"]
ANOVA_SOURCE_ORDER = [
    "C(is_xdds_day)",
    "C(corner_bucket)",
    "C(is_xdds_day):C(corner_bucket)",
    "Residual",
]
DEBUT_ANOVA_SOURCE_ORDER = [
    "C(debut_phase)",
    "C(is_xdds_day)",
    "C(debut_phase):C(is_xdds_day)",
    "Residual",
]


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


def _scope_frame(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.loc[frame["event_category"].astype(str).isin(ANALYSIS_SCOPE_ORDER)].copy()


def _group_stats(frame: pd.DataFrame, group_col: str, *, order: list[str] | None = None) -> pd.DataFrame:
    return phase10._group_stats(frame, group_col, order=order)  # noqa: SLF001


def _ordered_group_stats(frame: pd.DataFrame, group_col: str, order: list[str]) -> pd.DataFrame:
    stats = _group_stats(frame, group_col, order=order)
    if stats.empty:
        return pd.DataFrame(columns=[group_col, "n", "avg_diff", "plus_rate"])
    stats[group_col] = pd.Categorical(stats[group_col], categories=order, ordered=True)
    stats = stats.sort_values(group_col, kind="mergesort").reset_index(drop=True)
    stats[group_col] = stats[group_col].astype(str)
    return stats


def _anova_table(frame: pd.DataFrame, formula: str, source_order: list[str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["source", "df", "sum_sq", "F", "p_value", "note"])
    try:
        model = ols(formula, data=frame).fit()
        table = anova_lm(model, typ=2).reset_index().rename(columns={"index": "source", "PR(>F)": "p_value"})
    except Exception as exc:  # pragma: no cover - defensive path
        return pd.DataFrame(
            [
                {
                    "source": "skipped",
                    "df": np.nan,
                    "sum_sq": np.nan,
                    "F": np.nan,
                    "p_value": np.nan,
                    "note": f"anova_error: {exc.__class__.__name__}",
                }
            ]
        )

    table = table.rename(columns={"df": "df", "sum_sq": "sum_sq", "F": "F"})
    if "p_value" not in table.columns and "PR(>F)" in table.columns:
        table = table.rename(columns={"PR(>F)": "p_value"})
    table["note"] = ""
    table["source"] = table["source"].astype(str)
    table["source"] = pd.Categorical(table["source"], categories=source_order, ordered=True)
    table = table.sort_values("source", kind="mergesort").reset_index(drop=True)
    table["source"] = table["source"].astype(str)
    columns = ["source", "df", "sum_sq", "F", "p_value", "note"]
    for column in columns:
        if column not in table.columns:
            table[column] = np.nan if column != "note" else ""
    return table.loc[:, columns]


def _anova_for_segment(frame: pd.DataFrame, formula: str, source_order: list[str], *, min_cell_n: int) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            [{"source": "skipped", "df": np.nan, "sum_sq": np.nan, "F": np.nan, "p_value": np.nan, "note": "empty"}]
        )
    lhs = formula.split("~", 1)[1]
    cell_cols = []
    for part in lhs.split("+")[:2]:
        text = part.strip()
        if text.startswith("C("):
            text = text[2:]
        if text.endswith(")"):
            text = text[:-1]
        cell_cols.append(text.split(":", 1)[0])
    work = frame.copy()
    for column in cell_cols:
        work[column] = work[column].astype(str)
    counts = work.groupby(cell_cols, dropna=False).size()
    all_cells = pd.MultiIndex.from_product(
        [sorted(work[cell_cols[0]].dropna().unique()), sorted(work[cell_cols[1]].dropna().unique())]
    )
    counts = counts.reindex(all_cells, fill_value=0)
    if counts.empty or (counts < min_cell_n).any():
        return pd.DataFrame(
            [
                {
                    "source": "skipped",
                    "df": np.nan,
                    "sum_sq": np.nan,
                    "F": np.nan,
                    "p_value": np.nan,
                    "note": f"skipped: cell n<{min_cell_n}",
                }
            ]
        )
    out = _anova_table(frame, formula, source_order)
    if out.empty:
        return pd.DataFrame(
            [
                {
                    "source": "skipped",
                    "df": np.nan,
                    "sum_sq": np.nan,
                    "F": np.nan,
                    "p_value": np.nan,
                    "note": "anova_failed",
                }
            ]
        )
    return out


def build_step1_cross_stats(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    scoped = _scope_frame(work)
    for segment in SEGMENT_ORDER:
        frame = _segment_frame(scoped, segment)
        if frame.empty:
            continue
        frame = frame.copy()
        frame["scope"] = frame["event_category"].astype(str)
        stats = _group_stats(frame, "corner_bucket", order=CORNER_BUCKET_ORDER)
        for scope in ANALYSIS_SCOPE_ORDER:
            scoped_frame = frame.loc[frame["scope"].eq(scope)].copy()
            scoped_stats = _ordered_group_stats(scoped_frame, "corner_bucket", CORNER_BUCKET_ORDER)
            for _, row in scoped_stats.iterrows():
                rows.append(
                    {
                        "segment": segment,
                        "scope": scope,
                        "corner_bucket": row["corner_bucket"],
                        "n": int(row["n"]),
                        "avg_diff": float(row["avg_diff"]),
                        "plus_rate": float(row["plus_rate"]),
                    }
                )
    table = pd.DataFrame(rows, columns=["segment", "scope", "corner_bucket", "n", "avg_diff", "plus_rate"])
    if table.empty:
        return table
    table["segment"] = pd.Categorical(table["segment"], categories=SEGMENT_ORDER, ordered=True)
    table["scope"] = pd.Categorical(table["scope"], categories=ANALYSIS_SCOPE_ORDER, ordered=True)
    table["corner_bucket"] = pd.Categorical(table["corner_bucket"], categories=CORNER_BUCKET_ORDER, ordered=True)
    table = table.sort_values(["segment", "scope", "corner_bucket"], kind="mergesort").reset_index(drop=True)
    table["segment"] = table["segment"].astype(str)
    table["scope"] = table["scope"].astype(str)
    table["corner_bucket"] = table["corner_bucket"].astype(str)
    return table


def build_step2_anova(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    scoped = _scope_frame(work)
    for segment in SEGMENT_ORDER:
        frame = _segment_frame(scoped, segment).copy()
        if frame.empty:
            rows.append(
                {
                    "segment": segment,
                    "n": 0,
                    "source": "skipped",
                    "df": np.nan,
                    "sum_sq": np.nan,
                    "F": np.nan,
                    "p_value": np.nan,
                    "note": "empty",
                }
            )
            continue
        frame["is_xdds_day"] = pd.to_numeric(frame["is_xdds_day"], errors="coerce").fillna(0).astype(int)
        frame["corner_bucket"] = frame["corner_bucket"].astype(str)
        frame = frame.loc[frame["corner_bucket"].isin(CORNER_BUCKET_ORDER)].copy()
        if frame.empty:
            rows.append(
                {
                    "segment": segment,
                    "n": int(len(frame)),
                    "source": "skipped",
                    "df": np.nan,
                    "sum_sq": np.nan,
                    "F": np.nan,
                    "p_value": np.nan,
                    "note": "no corner data",
                }
            )
            continue
        anova = _anova_for_segment(
            frame,
            "diff ~ C(is_xdds_day) + C(corner_bucket) + C(is_xdds_day):C(corner_bucket)",
            ANOVA_SOURCE_ORDER,
            min_cell_n=10,
        )
        for _, row in anova.iterrows():
            rows.append(
                {
                    "segment": segment,
                    "n": int(len(frame)),
                    "source": row["source"],
                    "df": row["df"],
                    "sum_sq": row["sum_sq"],
                    "F": row["F"],
                    "p_value": row["p_value"],
                    "note": row["note"],
                }
            )
    table = pd.DataFrame(rows, columns=["segment", "n", "source", "df", "sum_sq", "F", "p_value", "note"])
    if table.empty:
        return table
    table["segment"] = pd.Categorical(table["segment"], categories=SEGMENT_ORDER, ordered=True)
    table = table.sort_values(["segment", "source"], kind="mergesort").reset_index(drop=True)
    table["segment"] = table["segment"].astype(str)
    table["source"] = table["source"].astype(str)
    return table


def build_step3_interaction_summary(anova_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        seg = anova_df.loc[anova_df["segment"].astype(str).eq(segment)].copy()
        interaction = seg.loc[seg["source"].astype(str).eq("C(is_xdds_day):C(corner_bucket)")]
        xdds = seg.loc[seg["source"].astype(str).eq("C(is_xdds_day)")]
        corner = seg.loc[seg["source"].astype(str).eq("C(corner_bucket)")]
        if interaction.empty:
            rows.append(
                {
                    "segment": segment,
                    "n": int(seg["n"].dropna().iloc[0])
                    if "n" in seg.columns and not seg["n"].dropna().empty
                    else int(seg.shape[0]),
                    "interaction_F": np.nan,
                    "interaction_p": np.nan,
                    "xdds_F": xdds["F"].iloc[0] if not xdds.empty else np.nan,
                    "xdds_p": xdds["p_value"].iloc[0] if not xdds.empty else np.nan,
                    "corner_F": corner["F"].iloc[0] if not corner.empty else np.nan,
                    "corner_p": corner["p_value"].iloc[0] if not corner.empty else np.nan,
                    "note": "skipped or missing interaction",
                }
            )
            continue
        rows.append(
            {
                "segment": segment,
                "n": int(seg["n"].dropna().iloc[0])
                if "n" in seg.columns and not seg["n"].dropna().empty
                else int(seg.shape[0]),
                "interaction_F": interaction["F"].iloc[0],
                "interaction_p": interaction["p_value"].iloc[0],
                "xdds_F": xdds["F"].iloc[0] if not xdds.empty else np.nan,
                "xdds_p": xdds["p_value"].iloc[0] if not xdds.empty else np.nan,
                "corner_F": corner["F"].iloc[0] if not corner.empty else np.nan,
                "corner_p": corner["p_value"].iloc[0] if not corner.empty else np.nan,
                "note": "",
            }
        )
    table = pd.DataFrame(
        rows,
        columns=["segment", "n", "interaction_F", "interaction_p", "xdds_F", "xdds_p", "corner_F", "corner_p", "note"],
    )
    table["segment"] = pd.Categorical(table["segment"], categories=SEGMENT_ORDER, ordered=True)
    table = table.sort_values("segment", kind="mergesort").reset_index(drop=True)
    table["segment"] = table["segment"].astype(str)
    return table


def build_step4_debut_stats(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        frame = _segment_frame(work, segment)
        if frame.empty:
            continue
        stats = _group_stats(frame, "debut_phase", order=DEBUT_PHASE_ORDER)
        for _, row in stats.iterrows():
            rows.append(
                {
                    "segment": segment,
                    "debut_phase": row["debut_phase"],
                    "n": int(row["n"]),
                    "avg_diff": float(row["avg_diff"]),
                    "plus_rate": float(row["plus_rate"]),
                }
            )
    table = pd.DataFrame(rows, columns=["segment", "debut_phase", "n", "avg_diff", "plus_rate"])
    if table.empty:
        return table
    table["segment"] = pd.Categorical(table["segment"], categories=SEGMENT_ORDER, ordered=True)
    table["debut_phase"] = pd.Categorical(table["debut_phase"], categories=DEBUT_PHASE_ORDER, ordered=True)
    table = table.sort_values(["segment", "debut_phase"], kind="mergesort").reset_index(drop=True)
    table["segment"] = table["segment"].astype(str)
    table["debut_phase"] = table["debut_phase"].astype(str)
    return table


def build_step5_debut_kw(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        frame = _segment_frame(work, segment)
        work_frame = frame.dropna(subset=["debut_phase", "diff"]).copy()
        groups = [
            pd.to_numeric(grp["diff"], errors="coerce").dropna().to_numpy(dtype=float)
            for _, grp in work_frame.groupby("debut_phase", dropna=False, sort=False)
            if len(grp)
        ]
        total_n = int(sum(len(group) for group in groups))
        if len(groups) < 2:
            rows.append(
                {
                    "segment": segment,
                    "kw_stat": np.nan,
                    "p_value": np.nan,
                    "epsilon_sq": np.nan,
                    "n_groups": len(groups),
                    "n": total_n,
                }
            )
            continue
        kw_stat, p_value = kruskal(*groups)
        rows.append(
            {
                "segment": segment,
                "kw_stat": float(kw_stat),
                "p_value": float(p_value),
                "epsilon_sq": float(kw_epsilon_squared(float(kw_stat), len(groups), total_n)),
                "n_groups": len(groups),
                "n": total_n,
            }
        )
    table = pd.DataFrame(rows, columns=["segment", "kw_stat", "p_value", "epsilon_sq", "n_groups", "n"])
    if table.empty:
        return table
    table["segment"] = pd.Categorical(table["segment"], categories=SEGMENT_ORDER, ordered=True)
    table = table.sort_values("segment", kind="mergesort").reset_index(drop=True)
    table["segment"] = table["segment"].astype(str)
    return table


def build_step6_anova_debut_event(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    scoped = _scope_frame(work)
    scoped = scoped.loc[scoped["debut_phase"].astype(str).isin(DEBUT_PHASE_ORDER)].copy()
    for segment in SEGMENT_ORDER:
        frame = _segment_frame(scoped, segment).copy()
        if frame.empty:
            rows.append(
                {
                    "segment": segment,
                    "source": "skipped",
                    "df": np.nan,
                    "sum_sq": np.nan,
                    "F": np.nan,
                    "p_value": np.nan,
                    "note": "empty",
                }
            )
            continue
        frame["is_xdds_day"] = pd.to_numeric(frame["is_xdds_day"], errors="coerce").fillna(0).astype(int)
        frame["debut_phase"] = frame["debut_phase"].astype(str)
        frame = frame.loc[frame["debut_phase"].isin(DEBUT_PHASE_ORDER)].copy()
        anova = _anova_for_segment(
            frame,
            "diff ~ C(debut_phase) + C(is_xdds_day) + C(debut_phase):C(is_xdds_day)",
            DEBUT_ANOVA_SOURCE_ORDER,
            min_cell_n=10,
        )
        for _, row in anova.iterrows():
            rows.append(
                {
                    "segment": segment,
                    "source": row["source"],
                    "df": row["df"],
                    "sum_sq": row["sum_sq"],
                    "F": row["F"],
                    "p_value": row["p_value"],
                    "note": row["note"],
                }
            )
    table = pd.DataFrame(rows, columns=["segment", "source", "df", "sum_sq", "F", "p_value", "note"])
    if table.empty:
        return table
    table["segment"] = pd.Categorical(table["segment"], categories=SEGMENT_ORDER, ordered=True)
    table = table.sort_values(["segment", "source"], kind="mergesort").reset_index(drop=True)
    table["segment"] = table["segment"].astype(str)
    table["source"] = table["source"].astype(str)
    return table


def build_step7_spearman(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        frame = _segment_frame(work, segment).copy()
        frame = frame.loc[frame["debut_phase"].astype(str).isin(["debut", "growth", "mature"])].copy()
        for scope in SPEARMAN_SCOPE_ORDER:
            scoped = frame.copy()
            if scope == "X_DDS":
                scoped = scoped.loc[scoped["event_category"].astype(str).eq("X_DDS")].copy()
            elif scope == "非イベント日":
                scoped = scoped.loc[scoped["event_category"].astype(str).eq("非イベント日")].copy()
            scoped = scoped.dropna(subset=["debut_days", "diff"]).copy()
            x = pd.to_numeric(scoped["debut_days"], errors="coerce")
            y = pd.to_numeric(scoped["diff"], errors="coerce")
            valid = x.notna() & y.notna()
            x = x.loc[valid]
            y = y.loc[valid]
            if len(x) < 10 or x.nunique(dropna=True) < 2 or y.nunique(dropna=True) < 2:
                rows.append(
                    {"segment": segment, "scope": scope, "spearman_rho": np.nan, "p_value": np.nan, "n": int(len(x))}
                )
                continue
            rho, p_value = spearmanr(x, y)
            rows.append(
                {
                    "segment": segment,
                    "scope": scope,
                    "spearman_rho": float(rho),
                    "p_value": float(p_value),
                    "n": int(len(x)),
                }
            )
    table = pd.DataFrame(rows, columns=["segment", "scope", "spearman_rho", "p_value", "n"])
    if table.empty:
        return table
    table["segment"] = pd.Categorical(table["segment"], categories=SEGMENT_ORDER, ordered=True)
    table["scope"] = pd.Categorical(table["scope"], categories=SPEARMAN_SCOPE_ORDER, ordered=True)
    table = table.sort_values(["segment", "scope"], kind="mergesort").reset_index(drop=True)
    table["segment"] = table["segment"].astype(str)
    table["scope"] = table["scope"].astype(str)
    return table


def build_report(artifacts: dict[str, pd.DataFrame | str]) -> str:
    lines = [
        "# Phase10e: X_DDS×角番 交互作用 & 経過日数×プレミアム検証",
        "",
        "- target_hall: みとや大森町",
        "- scope_filter: X_DDS / 非イベント日 only for interaction steps",
        "- moved_filter: is_moved == True is excluded from all analyses",
        "- table_rendering: render_markdown_table() only, no to_markdown()",
        "- date_format: YYYYMMDD",
        "",
        "## Analysis 1: X_DDS × 角番 交互作用",
        "",
        "### Step 1: 基本統計",
        "",
        render_markdown_table(artifacts["step1_cross_stats"]),
        "",
        "### Step 2: 2-way ANOVA",
        "",
        render_markdown_table(artifacts["step2_anova_xdds_corner"]),
        "",
        "### Step 3: セグメント横断比較",
        "",
        render_markdown_table(artifacts["step3_interaction_summary"]),
        "",
        "## Analysis 2: 経過日数 × プレミアム検証",
        "",
        "### Step 4: debut_phase別 基本統計",
        "",
        render_markdown_table(artifacts["step4_debut_phase_stats"]),
        "",
        "### Step 5: debut_phase KW検定",
        "",
        render_markdown_table(artifacts["step5_debut_kw"]),
        "",
        "### Step 6: debut × event_category 交互作用",
        "",
        render_markdown_table(artifacts["step6_anova_debut_event"]),
        "",
        "### Step 7: debut_days Spearman相関",
        "",
        render_markdown_table(artifacts["step7_debut_spearman"]),
        "",
        "## Summary",
        "",
        "- step1/step2/step6 only use X_DDS and non-event rows",
        "- step2/step6 skip a segment when any cell has n < 10",
        "- step7 uses debut/growth/mature only; pre_existing is excluded because debut_days is None",
    ]
    return "\n".join(lines).rstrip() + "\n"


def build_all_artifacts(df: pd.DataFrame) -> dict[str, pd.DataFrame | str]:
    work = _prepare_frame(df)
    step1 = build_step1_cross_stats(work)
    step2 = build_step2_anova(work)
    step3 = build_step3_interaction_summary(step2)
    step4 = build_step4_debut_stats(work)
    step5 = build_step5_debut_kw(work)
    step6 = build_step6_anova_debut_event(work)
    step7 = build_step7_spearman(work)
    artifacts: dict[str, pd.DataFrame | str] = {
        "step1_cross_stats": step1,
        "step2_anova_xdds_corner": step2,
        "step3_interaction_summary": step3,
        "step4_debut_phase_stats": step4,
        "step5_debut_kw": step5,
        "step6_anova_debut_event": step6,
        "step7_debut_spearman": step7,
    }
    artifacts["report"] = build_report(artifacts)
    return artifacts


def write_outputs(artifacts: dict[str, pd.DataFrame | str], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    casts = {
        "step1_cross_stats": "step1_cross_stats.csv",
        "step2_anova_xdds_corner": "step2_anova_xdds_corner.csv",
        "step3_interaction_summary": "step3_interaction_summary.csv",
        "step4_debut_phase_stats": "step4_debut_phase_stats.csv",
        "step5_debut_kw": "step5_debut_kw.csv",
        "step6_anova_debut_event": "step6_anova_debut_event.csv",
        "step7_debut_spearman": "step7_debut_spearman.csv",
    }
    for key, name in casts.items():
        cast_df = artifacts[key]
        if isinstance(cast_df, pd.DataFrame):
            cast_df.to_csv(output_dir / name, index=False, encoding="utf-8-sig")
    (output_dir / "report.md").write_text(str(artifacts["report"]), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase10e: X_DDS x corner and debut premium analysis")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--db", type=Path, default=MITOYA_DB_PATH)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
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
