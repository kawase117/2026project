from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kruskal
from statsmodels.formula.api import ols
from statsmodels.stats.anova import anova_lm

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda.mitoya_prompt_common import (  # noqa: E402
    MITOYA_ALL_SECTIONS,
    ensure_results_dir,
    kw_epsilon_squared,
    load_mitoya_frame,
    render_markdown_table,
    section_sort_key,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "mitoya_phase10_segment_validation"
SECTION_ORDER = list(MITOYA_ALL_SECTIONS)
LAST_DIGIT_ORDER = [str(i) for i in range(10)]
CORNER_BUCKET_ORDER = ["corner1", "corner2-4", "corner5-9", "corner10+"]
ORIENTATION_ORDER = ["horizontal", "vertical"]
JUG_ORDER = ["jug", "non_jug"]
SEGMENT_ORDER = ["h_jug", "h_nonjug", "v_jug", "v_nonjug", "mixed_805"]
STEP1_COLUMNS = [
    "step",
    "axis",
    "level",
    "n",
    "avg_diff",
    "plus_rate",
    "kw_stat",
    "p_value",
    "epsilon_sq",
    "n_groups",
    "total_n",
]
STEP2_COLUMNS = [
    "analysis",
    "kind",
    "axis_a",
    "axis_b",
    "level_a",
    "level_b",
    "n",
    "avg_diff",
    "plus_rate",
    "statistic",
    "p_value",
    "epsilon_sq",
    "df_num",
    "df_den",
    "note",
]
STEP3_COLUMNS = ["segment", "metric", "level", "n", "avg_diff", "plus_rate"]
STEP4_COLUMNS = ["segment", "test_name", "n_groups", "total_n", "kw_stat", "p_value", "epsilon_sq"]


def _numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([pd.NA] * len(frame), index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce")


def _prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["section"] = work.get("section", pd.Series(["unknown"] * len(work), index=work.index)).astype(str)

    for column in ("diff", "games", "x", "y", "rank_from_aisle", "dd", "dd_mod10", "machine_number"):
        if column in work.columns:
            work[column] = pd.to_numeric(work[column], errors="coerce")

    if "date_dt" not in work.columns:
        if "date" in work.columns:
            work["date_dt"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
        else:
            work["date_dt"] = pd.NaT

    if "dd" not in work.columns:
        work["dd"] = work["date_dt"].dt.day
    work["dd"] = pd.to_numeric(work["dd"], errors="coerce").astype("Int64")

    if "dd_mod10" not in work.columns:
        work["dd_mod10"] = work["dd"] % 10
    work["dd_mod10"] = pd.to_numeric(work["dd_mod10"], errors="coerce").astype("Int64")

    if "machine_digit" in work.columns:
        work["machine_digit"] = work["machine_digit"].astype("string").str.strip()
    else:
        fallback_digit = pd.Series(pd.NA, index=work.index, dtype="string")
        if "machine_number" in work.columns:
            fallback_digit = (
                (pd.to_numeric(work["machine_number"], errors="coerce") % 10).astype("Int64").astype("string")
            )
        work["machine_digit"] = fallback_digit

    if "last_digit" in work.columns:
        work["last_digit"] = work["last_digit"].astype("string").str.strip()
    else:
        work["last_digit"] = work["machine_digit"].copy()
    if work["last_digit"].isna().any() and "machine_number" in work.columns:
        fallback_last = (pd.to_numeric(work["machine_number"], errors="coerce") % 10).astype("Int64").astype("string")
        work["last_digit"] = work["last_digit"].fillna(fallback_last)
    work["last_digit"] = work["last_digit"].where(work["last_digit"].isin(LAST_DIGIT_ORDER))

    if "machine_name" not in work.columns:
        work["machine_name"] = ""
    machine_name = work["machine_name"].fillna("").astype(str)
    work["jug_flag"] = np.where(machine_name.str.contains("ジャグラー", na=False), "jug", "non_jug")

    if "corner_bucket" in work.columns:
        work["corner_bucket"] = work["corner_bucket"].fillna("unknown").astype(str)
    else:
        work["corner_bucket"] = work.get("rank_from_aisle", pd.Series([pd.NA] * len(work), index=work.index))
        work["corner_bucket"] = work["corner_bucket"].apply(_corner_bucket_from_rank).astype(str)

    if "games" not in work.columns:
        work["games"] = np.nan
    work["games"] = pd.to_numeric(work["games"], errors="coerce")
    work = work.loc[work["games"].ge(1000).fillna(False)].copy()

    orientation_map: dict[str, str] = {}
    for section, grp in work.groupby("section", dropna=False, sort=False):
        orientation_map[str(section)] = _section_orientation(grp)
    work["orientation"] = work["section"].map(orientation_map).astype("string")
    work = work.loc[work["orientation"].isin(ORIENTATION_ORDER)].copy()

    work["plus"] = work["diff"].gt(0)
    return work


def _corner_bucket_from_rank(rank: object) -> str:
    value = pd.to_numeric(pd.Series([rank]), errors="coerce").iloc[0]
    if pd.isna(value):
        return "unknown"
    int_value = int(value)
    if int_value <= 1:
        return "corner1"
    if int_value <= 4:
        return "corner2-4"
    if int_value <= 9:
        return "corner5-9"
    return "corner10+"


def _section_orientation(section_grp: pd.DataFrame) -> str:
    section = str(section_grp["section"].iloc[0]) if not section_grp.empty else "unknown"
    if section == "805-815":
        return "horizontal"
    x_nunique = int(section_grp["x"].nunique(dropna=True)) if "x" in section_grp.columns else 0
    y_nunique = int(section_grp["y"].nunique(dropna=True)) if "y" in section_grp.columns else 0
    if y_nunique == 1 and x_nunique >= 1:
        return "horizontal"
    if x_nunique == 1 and y_nunique >= 1:
        return "vertical"
    return "unknown"


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
    if order is not None:
        out[group_col] = pd.Categorical(out[group_col], categories=order, ordered=True)
        out = out.sort_values(group_col, kind="mergesort")
        out[group_col] = out[group_col].astype(str)
    return out.reset_index(drop=True)


def _kruskal_summary(frame: pd.DataFrame, group_col: str, *, order: list[str] | None = None) -> dict[str, object]:
    work = frame.dropna(subset=[group_col, "diff"]).copy()
    if order is not None:
        work[group_col] = pd.Categorical(work[group_col].astype(str), categories=order, ordered=True)
    groups: list[np.ndarray] = []
    for _, grp in work.groupby(group_col, dropna=False, sort=False):
        values = pd.to_numeric(grp["diff"], errors="coerce").dropna().to_numpy(dtype=float)
        if len(values):
            groups.append(values)
    total_n = int(sum(len(group) for group in groups))
    if len(groups) < 2:
        return {
            "kw_stat": float("nan"),
            "p_value": float("nan"),
            "epsilon_sq": float("nan"),
            "n_groups": len(groups),
            "total_n": total_n,
        }
    try:
        kw_stat, p_value = kruskal(*groups)
    except ValueError:
        kw_stat, p_value = float("nan"), float("nan")
    return {
        "kw_stat": float(kw_stat) if pd.notna(kw_stat) else float("nan"),
        "p_value": float(p_value) if pd.notna(p_value) else float("nan"),
        "epsilon_sq": kw_epsilon_squared(float(kw_stat), len(groups), total_n),
        "n_groups": len(groups),
        "total_n": total_n,
    }


def _anova_interaction_summary(frame: pd.DataFrame, axis_a: str, axis_b: str) -> dict[str, object]:
    work = frame.dropna(subset=[axis_a, axis_b, "diff"]).copy()
    if work.empty or work[axis_a].nunique(dropna=True) < 2 or work[axis_b].nunique(dropna=True) < 2:
        return {
            "statistic": float("nan"),
            "p_value": float("nan"),
            "df_num": float("nan"),
            "df_den": float("nan"),
        }
    formula_reduced = f"diff ~ C({axis_a}) + C({axis_b})"
    formula_full = f"diff ~ C({axis_a}) * C({axis_b})"
    try:
        reduced = ols(formula_reduced, data=work).fit()
        full = ols(formula_full, data=work).fit()
        comparison = anova_lm(reduced, full)
        row = comparison.iloc[1]
        return {
            "statistic": float(row.get("F", np.nan)),
            "p_value": float(row.get("Pr(>F)", np.nan)),
            "df_num": float(row.get("df_diff", np.nan)),
            "df_den": float(row.get("df_resid", np.nan)),
        }
    except Exception:
        return {
            "statistic": float("nan"),
            "p_value": float("nan"),
            "df_num": float("nan"),
            "df_den": float("nan"),
        }


def _segment_frame(work: pd.DataFrame, segment: str) -> pd.DataFrame:
    if segment == "h_jug":
        return work.loc[work["orientation"].eq("horizontal") & work["jug_flag"].eq("jug")].copy()
    if segment == "h_nonjug":
        return work.loc[work["orientation"].eq("horizontal") & work["jug_flag"].eq("non_jug")].copy()
    if segment == "v_jug":
        return work.loc[work["orientation"].eq("vertical") & work["jug_flag"].eq("jug")].copy()
    if segment == "v_nonjug":
        return work.loc[work["orientation"].eq("vertical") & work["jug_flag"].eq("non_jug")].copy()
    if segment == "mixed_805":
        return work.loc[work["section"].eq("805-815")].copy()
    raise KeyError(segment)


def _segment_metrics(work: pd.DataFrame, segment: str, metric: str) -> pd.DataFrame:
    frame = _segment_frame(work, segment)
    if metric == "last_digit":
        return _group_stats(frame, "last_digit", order=LAST_DIGIT_ORDER)
    if metric == "corner_bucket":
        return _group_stats(frame, "corner_bucket", order=CORNER_BUCKET_ORDER)
    if metric == "dd":
        frame = frame.copy()
        frame["dd"] = pd.to_numeric(frame["dd"], errors="coerce").astype("Int64")
        return _group_stats(
            frame.dropna(subset=["dd"]).assign(dd=lambda x: x["dd"].astype(int).astype(str)),
            "dd",
            order=[str(i) for i in range(1, 32)],
        )
    if metric == "dd_mod10":
        frame = frame.copy()
        frame["dd_mod10"] = pd.to_numeric(frame["dd_mod10"], errors="coerce").astype("Int64")
        return _group_stats(
            frame.dropna(subset=["dd_mod10"]).assign(dd_mod10=lambda x: x["dd_mod10"].astype(int).astype(str)),
            "dd_mod10",
            order=[str(i) for i in range(10)],
        )
    if metric == "jug_flag":
        return _group_stats(frame, "jug_flag", order=JUG_ORDER)
    raise KeyError(metric)


def _format_step1(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    section_stats = _group_stats(work, "section", order=SECTION_ORDER)
    for _, row in section_stats.iterrows():
        rows.append(
            {
                "step": "1a",
                "axis": "section",
                "level": row["section"],
                "n": int(row["n"]),
                "avg_diff": float(row["avg_diff"]),
                "plus_rate": float(row["plus_rate"]),
                "kw_stat": np.nan,
                "p_value": np.nan,
                "epsilon_sq": np.nan,
                "n_groups": np.nan,
                "total_n": np.nan,
            }
        )

    for step, axis, order in [("1b", "jug_flag", JUG_ORDER), ("1c", "orientation", ORIENTATION_ORDER)]:
        stats = _group_stats(work, axis, order=order)
        kw = _kruskal_summary(work, axis, order=order)
        for _, row in stats.iterrows():
            rows.append(
                {
                    "step": step,
                    "axis": axis,
                    "level": row[axis],
                    "n": int(row["n"]),
                    "avg_diff": float(row["avg_diff"]),
                    "plus_rate": float(row["plus_rate"]),
                    "kw_stat": kw["kw_stat"],
                    "p_value": kw["p_value"],
                    "epsilon_sq": kw["epsilon_sq"],
                    "n_groups": kw["n_groups"],
                    "total_n": kw["total_n"],
                }
            )

    table = pd.DataFrame(rows, columns=STEP1_COLUMNS)
    table["step"] = pd.Categorical(table["step"], categories=["1a", "1b", "1c"], ordered=True)
    table["axis"] = pd.Categorical(table["axis"], categories=["section", "jug_flag", "orientation"], ordered=True)
    table["level"] = table["level"].astype(str)
    table = table.sort_values(
        ["step", "axis", "level"],
        key=lambda col: col.map(section_sort_key) if col.name == "level" else col,
        kind="mergesort",
    )
    return table.reset_index(drop=True)


def _format_step2(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    # Orientation x jug_flag
    interaction_frame = work.loc[work["orientation"].isin(ORIENTATION_ORDER) & work["jug_flag"].isin(JUG_ORDER)].copy()
    for orientation in ORIENTATION_ORDER:
        for jug_flag in JUG_ORDER:
            grp = interaction_frame.loc[
                interaction_frame["orientation"].eq(orientation) & interaction_frame["jug_flag"].eq(jug_flag)
            ].copy()
            stats = _group_stats(grp.assign(bucket=f"{orientation} × {jug_flag}"), "bucket")
            row = stats.iloc[0] if not stats.empty else {"n": 0, "avg_diff": float("nan"), "plus_rate": float("nan")}
            rows.append(
                {
                    "analysis": "orientation_x_jug_flag",
                    "kind": "cell",
                    "axis_a": "orientation",
                    "axis_b": "jug_flag",
                    "level_a": orientation,
                    "level_b": jug_flag,
                    "n": int(row["n"]),
                    "avg_diff": float(row["avg_diff"]),
                    "plus_rate": float(row["plus_rate"]),
                    "statistic": np.nan,
                    "p_value": np.nan,
                    "epsilon_sq": np.nan,
                    "df_num": np.nan,
                    "df_den": np.nan,
                    "note": "",
                }
            )
    anova = _anova_interaction_summary(interaction_frame, "orientation", "jug_flag")
    rows.append(
        {
            "analysis": "orientation_x_jug_flag",
            "kind": "anova",
            "axis_a": "orientation",
            "axis_b": "jug_flag",
            "level_a": "",
            "level_b": "",
            "n": int(len(interaction_frame)),
            "avg_diff": float(pd.to_numeric(interaction_frame["diff"], errors="coerce").mean()),
            "plus_rate": float(interaction_frame["diff"].gt(0).mean() * 100),
            "statistic": anova["statistic"],
            "p_value": anova["p_value"],
            "epsilon_sq": np.nan,
            "df_num": anova["df_num"],
            "df_den": anova["df_den"],
            "note": "interaction term after main effects",
        }
    )

    # Mixed 805 section split
    mixed = work.loc[work["section"].eq("805-815")].copy()
    for jug_flag in JUG_ORDER:
        grp = mixed.loc[mixed["jug_flag"].eq(jug_flag)].copy()
        stats = _group_stats(grp.assign(bucket=jug_flag), "bucket")
        row = stats.iloc[0] if not stats.empty else {"n": 0, "avg_diff": float("nan"), "plus_rate": float("nan")}
        rows.append(
            {
                "analysis": "section805_x_jug_flag",
                "kind": "cell",
                "axis_a": "section",
                "axis_b": "jug_flag",
                "level_a": "805-815",
                "level_b": jug_flag,
                "n": int(row["n"]),
                "avg_diff": float(row["avg_diff"]),
                "plus_rate": float(row["plus_rate"]),
                "statistic": np.nan,
                "p_value": np.nan,
                "epsilon_sq": np.nan,
                "df_num": np.nan,
                "df_den": np.nan,
                "note": "only section 805-815 is mixed",
            }
        )
    mixed_kw = _kruskal_summary(mixed, "jug_flag", order=JUG_ORDER)
    rows.append(
        {
            "analysis": "section805_x_jug_flag",
            "kind": "kw",
            "axis_a": "section",
            "axis_b": "jug_flag",
            "level_a": "805-815",
            "level_b": "",
            "n": int(len(mixed)),
            "avg_diff": float(pd.to_numeric(mixed["diff"], errors="coerce").mean()),
            "plus_rate": float(mixed["diff"].gt(0).mean() * 100),
            "statistic": mixed_kw["kw_stat"],
            "p_value": mixed_kw["p_value"],
            "epsilon_sq": mixed_kw["epsilon_sq"],
            "df_num": np.nan,
            "df_den": np.nan,
            "note": "proxy test within the only mixed section",
        }
    )

    table = pd.DataFrame(rows, columns=STEP2_COLUMNS)
    return table.reset_index(drop=True)


def _format_step3(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    metric_plan = [
        ("last_digit", LAST_DIGIT_ORDER),
        ("corner_bucket", CORNER_BUCKET_ORDER),
        ("dd", [str(i) for i in range(1, 32)]),
        ("dd_mod10", [str(i) for i in range(10)]),
    ]
    for segment in SEGMENT_ORDER:
        for metric, order in metric_plan:
            stats = _segment_metrics(work, segment, metric)
            if stats.empty:
                continue
            stats[metric] = pd.Categorical(stats[metric], categories=order, ordered=True)
            stats = stats.sort_values(metric, kind="mergesort").reset_index(drop=True)
            for _, row in stats.iterrows():
                rows.append(
                    {
                        "segment": segment,
                        "metric": metric,
                        "level": row[metric],
                        "n": int(row["n"]),
                        "avg_diff": float(row["avg_diff"]),
                        "plus_rate": float(row["plus_rate"]),
                    }
                )
        if segment == "mixed_805":
            stats = _segment_metrics(work, segment, "jug_flag")
            for _, row in stats.iterrows():
                rows.append(
                    {
                        "segment": segment,
                        "metric": "jug_flag",
                        "level": row["jug_flag"],
                        "n": int(row["n"]),
                        "avg_diff": float(row["avg_diff"]),
                        "plus_rate": float(row["plus_rate"]),
                    }
                )

    table = pd.DataFrame(rows, columns=STEP3_COLUMNS)
    if table.empty:
        return table
    table["segment"] = pd.Categorical(table["segment"], categories=SEGMENT_ORDER, ordered=True)
    table["metric"] = pd.Categorical(
        table["metric"], categories=["last_digit", "corner_bucket", "dd", "dd_mod10", "jug_flag"], ordered=True
    )
    sort_helper = {"last_digit": 0, "corner_bucket": 1, "dd": 2, "dd_mod10": 3, "jug_flag": 4}
    table["_metric_sort"] = table["metric"].astype(str).map(sort_helper)
    table["_level_sort"] = pd.to_numeric(table["level"], errors="coerce")
    table = table.sort_values(["segment", "_metric_sort", "_level_sort", "level"], kind="mergesort").reset_index(
        drop=True
    )
    table["segment"] = table["segment"].astype(str)
    table["metric"] = table["metric"].astype(str)
    table = table.drop(columns=["_metric_sort", "_level_sort"])
    return table


def _format_step4(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        frame = _segment_frame(work, segment)
        kw = _kruskal_summary(frame, "last_digit", order=LAST_DIGIT_ORDER)
        rows.append(
            {
                "segment": segment,
                "test_name": "last_digit_kw",
                "n_groups": kw["n_groups"],
                "total_n": kw["total_n"],
                "kw_stat": kw["kw_stat"],
                "p_value": kw["p_value"],
                "epsilon_sq": kw["epsilon_sq"],
            }
        )
    return pd.DataFrame(rows, columns=STEP4_COLUMNS)


def build_report(artifacts: dict[str, pd.DataFrame | str], *, source_latest_date: str) -> str:
    lines = [
        "# Mitoya Phase 10: segment validation",
        "",
        f"- source_latest_date: {source_latest_date}",
        "- min_games_filter: games >= 1000",
        "- orientation_rule: y unique == 1 => horizontal, x unique == 1 => vertical, 805-815 forced horizontal",
        "",
        "## Step 1",
        "",
        render_markdown_table(artifacts["step1_single_axis"].head(30))
        if not artifacts["step1_single_axis"].empty
        else "_no rows_",
        "",
        "## Step 2",
        "",
        render_markdown_table(artifacts["step2_interaction"])
        if not artifacts["step2_interaction"].empty
        else "_no rows_",
        "",
        "## Step 3",
        "",
        render_markdown_table(artifacts["step3_segment_basics"].head(60))
        if not artifacts["step3_segment_basics"].empty
        else "_no rows_",
        "",
        "## Step 4",
        "",
        render_markdown_table(artifacts["step4_digit_kw"]) if not artifacts["step4_digit_kw"].empty else "_no rows_",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def build_all_artifacts(df: pd.DataFrame) -> dict[str, pd.DataFrame | str]:
    work = _prepare_frame(df)
    date_series = (
        pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
        if "date" in work.columns
        else pd.Series(dtype="datetime64[ns]")
    )
    latest_date = date_series.max() if not date_series.empty else pd.NaT
    source_latest_date = latest_date.strftime("%Y%m%d") if pd.notna(latest_date) else "unknown"

    artifacts: dict[str, pd.DataFrame | str] = {
        "step1_single_axis": _format_step1(work),
        "step2_interaction": _format_step2(work),
        "step3_segment_basics": _format_step3(work),
        "step4_digit_kw": _format_step4(work),
    }
    artifacts["report"] = build_report(artifacts, source_latest_date=source_latest_date)
    return artifacts


def save_outputs(artifacts: dict[str, pd.DataFrame | str], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts["step1_single_axis"].to_csv(output_dir / "step1_single_axis.csv", index=False, encoding="utf-8-sig")
    artifacts["step2_interaction"].to_csv(output_dir / "step2_interaction.csv", index=False, encoding="utf-8-sig")
    artifacts["step3_segment_basics"].to_csv(output_dir / "step3_segment_basics.csv", index=False, encoding="utf-8-sig")
    artifacts["step4_digit_kw"].to_csv(output_dir / "step4_digit_kw.csv", index=False, encoding="utf-8-sig")
    (output_dir / "report.md").write_text(str(artifacts["report"]), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    ensure_results_dir()
    args = parse_args(argv)
    df = load_mitoya_frame(join_layout=True)
    artifacts = build_all_artifacts(df)
    save_outputs(artifacts, args.output_dir)
    print(f"Wrote {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
