from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu

import eda.mitoya_prompt_common as common
from eda import mitoya_phase10_segment_validation as phase10
from eda.mitoya_prompt_common import (
    DEBUT_PHASE_ORDER,
    EVENT_CATEGORY_ORDER,
    X_DDS,
    add_debut_phase,
    add_event_category,
    load_mitoya_frame,
    render_markdown_table,
)
from eda.mitoya_prompt_common import DB_PATH as MITOYA_DB_PATH

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "mitoya_phase10f_debut_timeseries"
SEGMENT_ORDER = ["h_jug", "h_nonjug", "v_jug", "v_nonjug", "mixed_805"]
DEBUT_BIN_EDGES = [0, 30, 60, 90, 120, float("inf")]
DEBUT_BIN_LABELS = ["0-30", "31-60", "61-90", "91-120", "121+"]
SURVIVAL_GROUP_ORDER = ["survived", "removed"]
STEP3_SCOPE_ORDER = ["X_DDS", "非イベント日"]


def _prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    work = add_debut_phase(df)
    work = add_event_category(work)
    work = phase10._prepare_frame(work)  # noqa: SLF001
    if "is_moved" in work.columns:
        work = work.loc[~work["is_moved"].astype(bool)].copy()
    return work


def _segment_frame(work: pd.DataFrame, segment: str) -> pd.DataFrame:
    return phase10._segment_frame(work, segment)  # noqa: SLF001


def _debut_binned(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["debut_days"] = pd.to_numeric(work["debut_days"], errors="coerce")
    work = work.loc[work["debut_days"].notna()].copy()
    if work.empty:
        work["debut_bin"] = pd.Series(dtype="string")
        return work
    work["debut_bin"] = pd.cut(
        work["debut_days"],
        bins=DEBUT_BIN_EDGES,
        labels=DEBUT_BIN_LABELS,
        include_lowest=True,
    )
    work = work.loc[work["debut_bin"].notna()].copy()
    work["debut_bin"] = work["debut_bin"].astype(str)
    return work


def _group_stats(frame: pd.DataFrame, group_col: str, *, order: list[str]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for level in order:
        grp = frame.loc[frame[group_col].astype(str).eq(level)].copy()
        values = pd.to_numeric(grp["diff"], errors="coerce").dropna()
        if values.empty:
            continue
        rows.append(
            {
                group_col: level,
                "n": int(len(values)),
                "avg_diff": float(values.mean()),
                "plus_rate": float((values > 0).mean() * 100),
            }
        )
    return pd.DataFrame(rows, columns=[group_col, "n", "avg_diff", "plus_rate"])


def build_step1_cohort_tracking(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        frame = _segment_frame(work, segment)
        frame = _debut_binned(frame)
        if frame.empty:
            continue
        for debut_bin in DEBUT_BIN_LABELS:
            grp = frame.loc[frame["debut_bin"].eq(debut_bin)].copy()
            if grp.empty:
                continue
            values = pd.to_numeric(grp["diff"], errors="coerce").dropna()
            if values.empty:
                continue
            rows.append(
                {
                    "segment": segment,
                    "debut_bin": debut_bin,
                    "n": int(len(values)),
                    "avg_diff": float(values.mean()),
                    "plus_rate": float((values > 0).mean() * 100),
                    "n_machines": int(grp["machine_name"].astype(str).nunique()),
                }
            )
    table = pd.DataFrame(rows, columns=["segment", "debut_bin", "n", "avg_diff", "plus_rate", "n_machines"])
    if table.empty:
        return table
    table["segment"] = pd.Categorical(table["segment"], categories=SEGMENT_ORDER, ordered=True)
    table["debut_bin"] = pd.Categorical(table["debut_bin"], categories=DEBUT_BIN_LABELS, ordered=True)
    table = table.sort_values(["segment", "debut_bin"], kind="mergesort").reset_index(drop=True)
    table["segment"] = table["segment"].astype(str)
    table["debut_bin"] = table["debut_bin"].astype(str)
    return table


def build_step2_survival_bias(work: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary_rows: list[dict[str, object]] = []
    mwu_rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        frame = _segment_frame(work, segment)
        frame = _debut_binned(frame)
        if frame.empty:
            continue
        debut_frame = frame.loc[frame["debut_bin"].eq("0-30")].copy()
        if debut_frame.empty:
            continue
        machine_max = frame.groupby("machine_name", dropna=False)["debut_days"].max().dropna().astype(float)
        machine_names_with_debut = set(debut_frame["machine_name"].astype(str).unique())
        survived_names = [
            name for name, max_day in machine_max.items() if max_day >= 91 and str(name) in machine_names_with_debut
        ]
        removed_names = [
            name for name, max_day in machine_max.items() if max_day <= 90 and str(name) in machine_names_with_debut
        ]

        for group_name, names in (("survived", survived_names), ("removed", removed_names)):
            group_frame = debut_frame.loc[
                debut_frame["machine_name"].astype(str).isin([str(name) for name in names])
            ].copy()
            if group_frame.empty:
                continue
            max_days = machine_max.loc[[name for name in names if name in machine_max.index]]
            values = pd.to_numeric(group_frame["diff"], errors="coerce").dropna()
            if values.empty:
                continue
            summary_rows.append(
                {
                    "segment": segment,
                    "group": group_name,
                    "debut_avg_diff": float(values.mean()),
                    "debut_n": int(len(values)),
                    "max_days_median": float(max_days.median()) if not max_days.empty else float("nan"),
                    "n_machines": int(group_frame["machine_name"].astype(str).nunique()),
                }
            )

        survived_values = pd.to_numeric(
            debut_frame.loc[
                debut_frame["machine_name"].astype(str).isin([str(name) for name in survived_names]), "diff"
            ],
            errors="coerce",
        ).dropna()
        removed_values = pd.to_numeric(
            debut_frame.loc[
                debut_frame["machine_name"].astype(str).isin([str(name) for name in removed_names]), "diff"
            ],
            errors="coerce",
        ).dropna()
        if survived_values.empty or removed_values.empty:
            continue
        try:
            u_stat, p_value = mannwhitneyu(survived_values, removed_values, alternative="two-sided")
        except ValueError:
            u_stat, p_value = float("nan"), float("nan")
        mwu_rows.append(
            {
                "segment": segment,
                "u_stat": float(u_stat),
                "p_value": float(p_value),
                "survived_debut_avg": float(survived_values.mean()),
                "removed_debut_avg": float(removed_values.mean()),
                "diff": float(survived_values.mean() - removed_values.mean()),
            }
        )

    summary = pd.DataFrame(
        summary_rows,
        columns=["segment", "group", "debut_avg_diff", "debut_n", "max_days_median", "n_machines"],
    )
    mwu = pd.DataFrame(
        mwu_rows,
        columns=["segment", "u_stat", "p_value", "survived_debut_avg", "removed_debut_avg", "diff"],
    )
    if not summary.empty:
        summary["segment"] = pd.Categorical(summary["segment"], categories=SEGMENT_ORDER, ordered=True)
        summary["group"] = pd.Categorical(summary["group"], categories=SURVIVAL_GROUP_ORDER, ordered=True)
        summary = summary.sort_values(["segment", "group"], kind="mergesort").reset_index(drop=True)
        summary["segment"] = summary["segment"].astype(str)
        summary["group"] = summary["group"].astype(str)
    if not mwu.empty:
        mwu["segment"] = pd.Categorical(mwu["segment"], categories=SEGMENT_ORDER, ordered=True)
        mwu = mwu.sort_values("segment", kind="mergesort").reset_index(drop=True)
        mwu["segment"] = mwu["segment"].astype(str)
    return summary, mwu


def build_step3_xdds_debut_premium(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    scoped = work.loc[work["event_category"].astype(str).isin(STEP3_SCOPE_ORDER)].copy()
    for segment in SEGMENT_ORDER:
        frame = _segment_frame(scoped, segment)
        frame = _debut_binned(frame)
        if frame.empty:
            continue
        for scope in STEP3_SCOPE_ORDER:
            scoped_frame = frame.loc[frame["event_category"].astype(str).eq(scope)].copy()
            if scoped_frame.empty:
                continue
            for debut_bin in DEBUT_BIN_LABELS:
                grp = scoped_frame.loc[scoped_frame["debut_bin"].eq(debut_bin)].copy()
                if grp.empty:
                    continue
                values = pd.to_numeric(grp["diff"], errors="coerce").dropna()
                if values.empty:
                    continue
                rows.append(
                    {
                        "segment": segment,
                        "scope": scope,
                        "debut_bin": debut_bin,
                        "n": int(len(values)),
                        "avg_diff": float(values.mean()),
                        "plus_rate": float((values > 0).mean() * 100),
                    }
                )
    table = pd.DataFrame(rows, columns=["segment", "scope", "debut_bin", "n", "avg_diff", "plus_rate"])
    if table.empty:
        return table
    table["segment"] = pd.Categorical(table["segment"], categories=SEGMENT_ORDER, ordered=True)
    table["scope"] = pd.Categorical(table["scope"], categories=STEP3_SCOPE_ORDER, ordered=True)
    table["debut_bin"] = pd.Categorical(table["debut_bin"], categories=DEBUT_BIN_LABELS, ordered=True)
    table = table.sort_values(["segment", "scope", "debut_bin"], kind="mergesort").reset_index(drop=True)
    table["segment"] = table["segment"].astype(str)
    table["scope"] = table["scope"].astype(str)
    table["debut_bin"] = table["debut_bin"].astype(str)
    return table


def build_step4_machine_ranking(work: pd.DataFrame) -> pd.DataFrame:
    frame = _segment_frame(work, "h_nonjug")
    frame = _debut_binned(frame)
    rows: list[dict[str, object]] = []
    if frame.empty:
        return pd.DataFrame(
            columns=["machine_name", "debut_avg_diff", "debut_n", "mature_avg_diff", "mature_n", "improvement", "rank"]
        )
    for machine_name, grp in frame.groupby("machine_name", dropna=False, sort=False):
        debut_values = pd.to_numeric(grp.loc[grp["debut_bin"].eq("0-30"), "diff"], errors="coerce").dropna()
        mature_values = pd.to_numeric(grp.loc[grp["debut_days"].ge(91), "diff"], errors="coerce").dropna()
        if len(debut_values) < 30 or len(mature_values) < 30:
            continue
        rows.append(
            {
                "machine_name": str(machine_name),
                "debut_avg_diff": float(debut_values.mean()),
                "debut_n": int(len(debut_values)),
                "mature_avg_diff": float(mature_values.mean()),
                "mature_n": int(len(mature_values)),
                "improvement": float(mature_values.mean() - debut_values.mean()),
            }
        )
    table = pd.DataFrame(
        rows,
        columns=["machine_name", "debut_avg_diff", "debut_n", "mature_avg_diff", "mature_n", "improvement"],
    )
    if table.empty:
        return pd.DataFrame(
            columns=["machine_name", "debut_avg_diff", "debut_n", "mature_avg_diff", "mature_n", "improvement", "rank"]
        )
    table = table.sort_values(["improvement", "machine_name"], ascending=[False, True], kind="mergesort").reset_index(
        drop=True
    )
    table["rank"] = np.arange(1, len(table) + 1)
    return table.loc[
        :, ["machine_name", "debut_avg_diff", "debut_n", "mature_avg_diff", "mature_n", "improvement", "rank"]
    ]


def _judge_hypotheses(
    step1: pd.DataFrame, survival: pd.DataFrame, mwu: pd.DataFrame, step3: pd.DataFrame, ranking: pd.DataFrame
) -> dict[str, str]:
    h_nonjug = step1.loc[step1["segment"].astype(str).eq("h_nonjug")].copy()
    h_nonjug_first = h_nonjug.loc[h_nonjug["debut_bin"].astype(str).eq("0-30"), "avg_diff"]
    h_nonjug_mature = h_nonjug.loc[h_nonjug["debut_bin"].astype(str).isin(["91-120", "121+"]), "avg_diff"]
    h_nonjug_trend = bool(
        not h_nonjug_first.empty
        and not h_nonjug_mature.empty
        and float(h_nonjug_mature.max()) > float(h_nonjug_first.iloc[0])
    )

    surv_row = survival.loc[
        survival["segment"].astype(str).eq("h_nonjug") & survival["group"].astype(str).eq("survived")
    ]
    rem_row = survival.loc[survival["segment"].astype(str).eq("h_nonjug") & survival["group"].astype(str).eq("removed")]
    survival_bias = False
    if not surv_row.empty and not rem_row.empty:
        survival_bias = float(surv_row["debut_avg_diff"].iloc[0]) > float(rem_row["debut_avg_diff"].iloc[0])

    xdds_row = step3.loc[
        step3["segment"].astype(str).eq("h_nonjug")
        & step3["scope"].astype(str).eq("X_DDS")
        & step3["debut_bin"].astype(str).eq("0-30")
    ]
    non_event_row = step3.loc[
        step3["segment"].astype(str).eq("h_nonjug")
        & step3["scope"].astype(str).eq("非イベント日")
        & step3["debut_bin"].astype(str).eq("0-30")
    ]
    xdds_premium = False
    if not xdds_row.empty and not non_event_row.empty:
        xdds_premium = float(xdds_row["avg_diff"].iloc[0]) > float(non_event_row["avg_diff"].iloc[0])

    a_support = (
        "支持" if h_nonjug_trend and not survival_bias and not xdds_premium else ("不明" if h_nonjug_trend else "棄却")
    )
    b_support = "支持" if survival_bias else "棄却"
    c_support = "支持" if xdds_premium else "棄却"
    if not ranking.empty and float(ranking["improvement"].max()) <= 0:
        a_support = "棄却"
    if not mwu.empty:
        mwu_row = mwu.loc[mwu["segment"].astype(str).eq("h_nonjug")]
        if not mwu_row.empty and pd.to_numeric(mwu_row["p_value"], errors="coerce").iloc[0] >= 0.05:
            b_support = "不明" if survival_bias else "棄却"
    return {"A": a_support, "B": b_support, "C": c_support}


def build_report(artifacts: dict[str, pd.DataFrame | str]) -> str:
    judgement = artifacts.get("judgement", {}) if isinstance(artifacts.get("judgement"), dict) else {}
    lines = [
        "# Phase10f: h_nonjug debut→mature 逆転の生存バイアス検証",
        "",
        "- target_hall: みとや大森町",
        "- scope_filter: X_DDS / 非イベント日 only for Step 3",
        "- moved_filter: is_moved == True is excluded from all analyses",
        "- table_rendering: render_markdown_table() only, no to_markdown()",
        "",
        "## Step 1: コホート追跡",
        "",
        render_markdown_table(artifacts["step1_cohort_tracking"]),
        "",
        "## Step 2: 生存バイアス検証",
        "",
        render_markdown_table(artifacts["step2_survival_bias"]),
        "",
        render_markdown_table(artifacts["step2_survival_mwu"]),
        "",
        "## Step 3: X_DDS限定 debut プレミアム",
        "",
        render_markdown_table(artifacts["step3_xdds_debut_premium"]),
        "",
        "## Step 4: 機種別ランキング",
        "",
        render_markdown_table(artifacts["step4_machine_ranking"]),
        "",
        "## 判定",
        f"- 仮説A（ホール戦略）: {judgement.get('A', '不明')}",
        f"- 仮説B（生存バイアス）: {judgement.get('B', '不明')}",
        f"- 仮説C（X_DDS限定）: {judgement.get('C', '不明')}",
    ]
    return "\n".join(lines).rstrip() + "\n"


def build_all_artifacts(df: pd.DataFrame) -> dict[str, pd.DataFrame | str]:
    work = _prepare_frame(df)
    step1 = build_step1_cohort_tracking(work)
    step2_summary, step2_mwu = build_step2_survival_bias(work)
    step3 = build_step3_xdds_debut_premium(work)
    step4 = build_step4_machine_ranking(work)
    artifacts: dict[str, pd.DataFrame | str] = {
        "step1_cohort_tracking": step1,
        "step2_survival_bias": step2_summary,
        "step2_survival_mwu": step2_mwu,
        "step3_xdds_debut_premium": step3,
        "step4_machine_ranking": step4,
    }
    artifacts["judgement"] = _judge_hypotheses(step1, step2_summary, step2_mwu, step3, step4)
    artifacts["report"] = build_report(artifacts)
    return artifacts


def write_outputs(artifacts: dict[str, pd.DataFrame | str], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    casts = {
        "step1_cohort_tracking": "step1_cohort_tracking.csv",
        "step2_survival_bias": "step2_survival_bias.csv",
        "step2_survival_mwu": "step2_survival_mwu.csv",
        "step3_xdds_debut_premium": "step3_xdds_debut_premium.csv",
        "step4_machine_ranking": "step4_machine_ranking.csv",
    }
    for key, name in casts.items():
        cast_df = artifacts[key]
        if isinstance(cast_df, pd.DataFrame):
            cast_df.to_csv(output_dir / name, index=False, encoding="utf-8-sig")
    (output_dir / "report.md").write_text(str(artifacts["report"]), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase10f: debut to mature survival bias analysis")
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
