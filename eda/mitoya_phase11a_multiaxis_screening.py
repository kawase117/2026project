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

from eda import mitoya_phase10_segment_validation as phase10  # noqa: E402
from eda.mitoya_prompt_common import (  # noqa: E402
    DB_PATH,
    EVENT_CATEGORY_ORDER,
    WEEKDAY_ORDER,
    X_DDS,
    add_event_category,
    ensure_results_dir,
    kw_epsilon_squared,
    load_mitoya_frame,
    render_markdown_table,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "mitoya_phase11a_multiaxis_screening"
DD_ORDER = [str(i) for i in range(1, 32)]
ZOROME_ORDER = ["0", "1"]
EVENT_SCOPE_ORDER = ["X_DDS", "非イベント日"]
ANOVA_SOURCE_ORDER = [
    "C(is_xdds_day)",
    "C(day_of_week)",
    "C(is_xdds_day):C(day_of_week)",
    "Residual",
]
SEGMENT_ORDER = list(phase10.SEGMENT_ORDER)
AXIS_ORDER = ["dd_spectrum", "day_of_week", "event_x_weekday", "is_zorome"]
DOW_MAP = {
    "Monday": "月",
    "Tuesday": "火",
    "Wednesday": "水",
    "Thursday": "木",
    "Friday": "金",
    "Saturday": "土",
    "Sunday": "日",
}

STEP1_COLUMNS = ["grain", "segment", "event_scope", "kw_stat", "p_value", "epsilon_sq", "n_groups", "n"]
STEP2_COLUMNS = ["grain", "segment", "event_scope", "dd", "n", "avg_diff", "plus_rate"]
STEP3_COLUMNS = ["grain", "segment", "event_scope", "kw_stat", "p_value", "epsilon_sq", "n_groups", "n"]
STEP4_COLUMNS = ["grain", "segment", "event_scope", "day_of_week", "n", "avg_diff", "plus_rate"]
STEP5_COLUMNS = ["segment", "event_category", "day_of_week", "n", "avg_diff", "plus_rate"]
STEP6_COLUMNS = ["segment", "source", "df", "sum_sq", "F", "p_value", "n"]
STEP7_COLUMNS = ["grain", "segment", "event_scope", "kw_stat", "p_value", "epsilon_sq", "n_groups", "n"]
STEP8_COLUMNS = ["grain", "segment", "event_scope", "is_zorome", "n", "avg_diff", "plus_rate"]
STEP9_COLUMNS = ["axis", "grain", "segment", "event_scope", "p_value", "epsilon_sq", "verdict"]


def _prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    work = add_event_category(df)
    work = phase10._prepare_frame(work)

    if "date_dt" not in work.columns:
        work["date_dt"] = pd.to_datetime(work.get("date"), format="%Y%m%d", errors="coerce")

    if "day_of_week" in work.columns:
        work["day_of_week"] = work["day_of_week"].astype("string").str.strip()
    else:
        work["day_of_week"] = work["date_dt"].dt.day_name().map(DOW_MAP)
    work["day_of_week"] = work["day_of_week"].where(work["day_of_week"].isin(WEEKDAY_ORDER))

    if "is_zorome" in work.columns:
        work["is_zorome"] = pd.to_numeric(work["is_zorome"], errors="coerce").fillna(0).astype(int)
    else:
        machine_number = pd.to_numeric(work.get("machine_number"), errors="coerce")
        work["is_zorome"] = ((machine_number % 100 // 10) == (machine_number % 10)).astype(int)

    work["dd"] = pd.to_numeric(work.get("dd"), errors="coerce").astype("Int64")
    work["day_of_week"] = pd.Categorical(work["day_of_week"], categories=WEEKDAY_ORDER, ordered=True)
    work["event_category"] = pd.Categorical(work["event_category"], categories=EVENT_CATEGORY_ORDER, ordered=True)
    work["is_zorome"] = pd.to_numeric(work["is_zorome"], errors="coerce").fillna(0).astype(int)
    return work


def _ensure_prepared(work: pd.DataFrame) -> pd.DataFrame:
    required = {"diff", "orientation", "jug_flag", "corner_bucket", "event_category", "day_of_week", "is_zorome", "dd"}
    if required.issubset(set(work.columns)):
        return work.copy()
    return _prepare_frame(work)


def _analysis_frames(work: pd.DataFrame) -> list[tuple[str, str, str, pd.DataFrame]]:
    work = _ensure_prepared(work)
    frames: list[tuple[str, str, str, pd.DataFrame]] = [("hall", "", "", work.copy())]
    for segment in SEGMENT_ORDER:
        segment_frame = phase10._segment_frame(work, segment)
        frames.append(("segment", segment, "", segment_frame))
        for event_scope in EVENT_SCOPE_ORDER:
            if event_scope == "X_DDS":
                scope_frame = segment_frame.loc[segment_frame["event_category"].astype(str).eq("X_DDS")].copy()
            else:
                scope_frame = segment_frame.loc[segment_frame["event_category"].astype(str).eq("非イベント日")].copy()
            frames.append(("composite", segment, event_scope, scope_frame))
    return frames


def _hall_and_segments(work: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    work = _ensure_prepared(work)
    frames = [("", work.copy())]
    for segment in SEGMENT_ORDER:
        frames.append((segment, phase10._segment_frame(work, segment)))
    return frames


def _levels(order: list[str] | None, series: pd.Series) -> list[str]:
    values = series.dropna().astype(str).tolist()
    if order is None:
        seen: list[str] = []
        for value in values:
            if value not in seen:
                seen.append(value)
        return seen
    return [level for level in order if level in set(values)]


def _group_stats(frame: pd.DataFrame, group_col: str, *, order: list[str] | None = None) -> pd.DataFrame:
    if frame.empty or group_col not in frame.columns:
        return pd.DataFrame(columns=[group_col, "n", "avg_diff", "plus_rate"])

    work = frame.copy()
    work[group_col] = work[group_col].astype("string").str.strip()
    rows: list[dict[str, object]] = []
    for level in _levels(order, work[group_col]):
        grp = work.loc[work[group_col].eq(level)]
        values = pd.to_numeric(grp["diff"], errors="coerce").dropna()
        if values.empty:
            continue
        rows.append(
            {
                group_col: level,
                "n": int(values.size),
                "avg_diff": float(values.mean()),
                "plus_rate": float((values > 0).mean() * 100),
            }
        )
    return pd.DataFrame(rows, columns=[group_col, "n", "avg_diff", "plus_rate"])


def _kruskal_summary(frame: pd.DataFrame, group_col: str, *, order: list[str] | None = None) -> dict[str, object]:
    if frame.empty or group_col not in frame.columns:
        return {"kw_stat": float("nan"), "p_value": float("nan"), "epsilon_sq": float("nan"), "n_groups": 0, "n": 0}

    work = frame.copy()
    work[group_col] = work[group_col].astype("string").str.strip()
    groups: list[np.ndarray] = []
    total_n = 0
    for level in _levels(order, work[group_col]):
        grp = work.loc[work[group_col].eq(level)]
        values = pd.to_numeric(grp["diff"], errors="coerce").dropna().to_numpy(dtype=float)
        if not len(values):
            continue
        groups.append(values)
        total_n += len(values)

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
        "epsilon_sq": kw_epsilon_squared(float(kw_stat), len(groups), total_n),
        "n_groups": len(groups),
        "n": total_n,
    }


def _one_way_kw_table(work: pd.DataFrame, *, axis: str, group_col: str, order: list[str]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for grain, segment, event_scope, frame in _analysis_frames(work):
        summary = _kruskal_summary(frame, group_col, order=order)
        rows.append(
            {
                "grain": grain,
                "segment": segment,
                "event_scope": event_scope,
                "kw_stat": summary["kw_stat"],
                "p_value": summary["p_value"],
                "epsilon_sq": summary["epsilon_sq"],
                "n_groups": summary["n_groups"],
                "n": summary["n"],
            }
        )
    table = pd.DataFrame(rows, columns=STEP1_COLUMNS if axis == "dd_spectrum" else STEP7_COLUMNS)
    return table


def build_step1_dd_kw(work: pd.DataFrame) -> pd.DataFrame:
    return _one_way_kw_table(work, axis="dd_spectrum", group_col="dd", order=DD_ORDER)


def build_step2_dd_stats(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for grain, segment, event_scope, frame in _analysis_frames(work):
        stats = _group_stats(frame, "dd", order=DD_ORDER)
        for _, row in stats.iterrows():
            rows.append(
                {
                    "grain": grain,
                    "segment": segment,
                    "event_scope": event_scope,
                    "dd": row["dd"],
                    "n": int(row["n"]),
                    "avg_diff": float(row["avg_diff"]),
                    "plus_rate": float(row["plus_rate"]),
                }
            )
    return pd.DataFrame(rows, columns=STEP2_COLUMNS)


def build_step3_weekday_kw(work: pd.DataFrame) -> pd.DataFrame:
    return _one_way_kw_table(work, axis="day_of_week", group_col="day_of_week", order=WEEKDAY_ORDER)


def build_step4_weekday_stats(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for grain, segment, event_scope, frame in _analysis_frames(work):
        stats = _group_stats(frame, "day_of_week", order=WEEKDAY_ORDER)
        for _, row in stats.iterrows():
            rows.append(
                {
                    "grain": grain,
                    "segment": segment,
                    "event_scope": event_scope,
                    "day_of_week": row["day_of_week"],
                    "n": int(row["n"]),
                    "avg_diff": float(row["avg_diff"]),
                    "plus_rate": float(row["plus_rate"]),
                }
            )
    return pd.DataFrame(rows, columns=STEP4_COLUMNS)


def build_step5_event_weekday_cross(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment, frame in _hall_and_segments(work):
        for event_category in EVENT_CATEGORY_ORDER:
            event_frame = frame.loc[frame["event_category"].astype(str).eq(event_category)].copy()
            for day_of_week in WEEKDAY_ORDER:
                cell = event_frame.loc[event_frame["day_of_week"].astype(str).eq(day_of_week)]
                values = pd.to_numeric(cell["diff"], errors="coerce").dropna()
                if values.empty:
                    continue
                rows.append(
                    {
                        "segment": segment,
                        "event_category": event_category,
                        "day_of_week": day_of_week,
                        "n": int(values.size),
                        "avg_diff": float(values.mean()),
                        "plus_rate": float((values > 0).mean() * 100),
                    }
                )
    return pd.DataFrame(rows, columns=STEP5_COLUMNS)


def _anova_for_segment(frame: pd.DataFrame, segment: str) -> pd.DataFrame:
    work = frame.loc[
        frame["event_category"].astype(str).isin({"X_DDS", "非イベント日"}) & frame["day_of_week"].notna()
    ].copy()
    if work.empty:
        return pd.DataFrame(columns=STEP6_COLUMNS)

    work["is_xdds_day"] = work["event_category"].astype(str).eq("X_DDS").astype(int)
    counts = work.groupby(["is_xdds_day", "day_of_week"], observed=True).size()
    if (
        (counts < 10).any()
        or work["is_xdds_day"].nunique(dropna=True) < 2
        or work["day_of_week"].nunique(dropna=True) < 2
    ):
        return pd.DataFrame(columns=STEP6_COLUMNS)

    try:
        model = ols("diff ~ C(is_xdds_day) + C(day_of_week) + C(is_xdds_day):C(day_of_week)", data=work).fit()
        anova = anova_lm(model, typ=2).reset_index().rename(columns={"index": "source", "PR(>F)": "p_value"})
    except Exception:
        return pd.DataFrame(columns=STEP6_COLUMNS)

    anova["segment"] = segment
    anova["n"] = int(len(work))
    anova = anova.loc[:, ["segment", "source", "df", "sum_sq", "F", "p_value", "n"]]
    anova["source"] = pd.Categorical(anova["source"].astype(str), categories=ANOVA_SOURCE_ORDER, ordered=True)
    anova = anova.sort_values("source", kind="mergesort").reset_index(drop=True)
    anova["source"] = anova["source"].astype(str)
    return anova


def build_step6_event_weekday_anova(work: pd.DataFrame) -> pd.DataFrame:
    work = _ensure_prepared(work)
    frames: list[pd.DataFrame] = [_anova_for_segment(work, "")]
    for segment in SEGMENT_ORDER:
        frames.append(_anova_for_segment(phase10._segment_frame(work, segment), segment))
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return pd.DataFrame(columns=STEP6_COLUMNS)
    return pd.concat(frames, ignore_index=True)


def build_step7_zorome_kw(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for grain, segment, event_scope, frame in _analysis_frames(work):
        frame = frame.copy()
        frame["is_zorome"] = pd.to_numeric(frame["is_zorome"], errors="coerce").fillna(0).astype(int).astype(str)
        summary = _kruskal_summary(frame, "is_zorome", order=ZOROME_ORDER)
        rows.append(
            {
                "grain": grain,
                "segment": segment,
                "event_scope": event_scope,
                "kw_stat": summary["kw_stat"],
                "p_value": summary["p_value"],
                "epsilon_sq": summary["epsilon_sq"],
                "n_groups": summary["n_groups"],
                "n": summary["n"],
            }
        )
    return pd.DataFrame(rows, columns=STEP7_COLUMNS)


def build_step8_zorome_stats(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for grain, segment, event_scope, frame in _analysis_frames(work):
        frame = frame.copy()
        frame["is_zorome"] = pd.to_numeric(frame["is_zorome"], errors="coerce").fillna(0).astype(int).astype(str)
        stats = _group_stats(frame, "is_zorome", order=ZOROME_ORDER)
        for _, row in stats.iterrows():
            rows.append(
                {
                    "grain": grain,
                    "segment": segment,
                    "event_scope": event_scope,
                    "is_zorome": row["is_zorome"],
                    "n": int(row["n"]),
                    "avg_diff": float(row["avg_diff"]),
                    "plus_rate": float(row["plus_rate"]),
                }
            )
    return pd.DataFrame(rows, columns=STEP8_COLUMNS)


def _verdict(p_value: object, epsilon_sq: object | None, *, axis: str) -> str:
    p = pd.to_numeric(pd.Series([p_value]), errors="coerce").iloc[0]
    eps = pd.to_numeric(pd.Series([epsilon_sq]), errors="coerce").iloc[0] if epsilon_sq is not None else np.nan
    if pd.isna(p):
        return "skip"
    if axis == "event_x_weekday":
        if p < 0.001:
            return "◎有望"
        if p < 0.01:
            return "○要検討"
        if p < 0.05:
            return "△境界的"
        return "✗脱落"
    if p < 0.001 and pd.notna(eps) and eps >= 0.003:
        return "◎有望"
    if p < 0.01:
        return "○要検討"
    if p < 0.05:
        return "△境界的"
    return "✗脱落"


def build_step9_summary(all_kw_results: dict[str, pd.DataFrame], anova_results: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    for axis, table in [
        ("dd_spectrum", all_kw_results["dd_spectrum"]),
        ("day_of_week", all_kw_results["day_of_week"]),
        ("is_zorome", all_kw_results["is_zorome"]),
    ]:
        for _, row in table.iterrows():
            rows.append(
                {
                    "axis": axis,
                    "grain": row["grain"],
                    "segment": row["segment"],
                    "event_scope": row["event_scope"],
                    "p_value": row["p_value"],
                    "epsilon_sq": row["epsilon_sq"],
                    "verdict": _verdict(row["p_value"], row["epsilon_sq"], axis=axis),
                }
            )

    interaction_source = "C(is_xdds_day):C(day_of_week)"
    for grain, segment in [("", ""), *[(segment, segment) for segment in SEGMENT_ORDER]]:
        if grain == "" and segment == "":
            frame = anova_results.loc[anova_results["segment"].eq("")]
        else:
            frame = anova_results.loc[anova_results["segment"].eq(segment)]
        row = frame.loc[frame["source"].eq(interaction_source)]
        if row.empty:
            p_value = float("nan")
        else:
            p_value = row["p_value"].iloc[0]
        rows.append(
            {
                "axis": "event_x_weekday",
                "grain": "hall" if segment == "" else "segment",
                "segment": segment,
                "event_scope": "",
                "p_value": p_value,
                "epsilon_sq": float("nan"),
                "verdict": _verdict(p_value, None, axis="event_x_weekday"),
            }
        )

    table = pd.DataFrame(rows, columns=STEP9_COLUMNS)
    table["axis"] = pd.Categorical(table["axis"], categories=AXIS_ORDER, ordered=True)
    table["grain"] = pd.Categorical(table["grain"], categories=["hall", "segment", "composite"], ordered=True)
    table = table.sort_values(["axis", "grain", "segment", "event_scope"], kind="mergesort").reset_index(drop=True)
    table["axis"] = table["axis"].astype(str)
    table["grain"] = table["grain"].astype(str)
    return table


def _significant_scope_keys(step_table: pd.DataFrame) -> set[tuple[str, str, str]]:
    sig = step_table.loc[pd.to_numeric(step_table["p_value"], errors="coerce").lt(0.05)].copy()
    return {(str(row["grain"]), str(row["segment"]), str(row["event_scope"])) for _, row in sig.iterrows()}


def build_report(artifacts: dict[str, pd.DataFrame | str], *, source_latest_date: str) -> str:
    step1 = artifacts["step1_dd_kw"]
    step2 = artifacts["step2_dd_stats"]
    step3 = artifacts["step3_weekday_kw"]
    step4 = artifacts["step4_weekday_stats"]
    step5 = artifacts["step5_event_weekday_cross"]
    step6 = artifacts["step6_event_weekday_anova"]
    step7 = artifacts["step7_zorome_kw"]
    step8 = artifacts["step8_zorome_stats"]
    step9 = artifacts["step9_summary"]

    sig_step1 = _significant_scope_keys(step1)
    sig_step3 = _significant_scope_keys(step3)
    sig_step7 = _significant_scope_keys(step7)

    def _filtered_stats(stats: pd.DataFrame, significant: set[tuple[str, str, str]]) -> pd.DataFrame:
        if stats.empty:
            return stats
        mask = stats.apply(
            lambda row: (str(row["grain"]), str(row["segment"]), str(row["event_scope"])) in significant, axis=1
        )
        return stats.loc[mask].copy()

    lines = [
        "# Phase11a: 4軸スクリーニング",
        "",
        f"- source_latest_date: {source_latest_date}",
        f"- db_path: {DB_PATH}",
        "- basic_stats_rule: only grains with KW p < 0.05 are expanded",
        "",
        "## Axis 1: DD full spectrum",
        "### KW検定（3粒度）",
        render_markdown_table(step1) if not step1.empty else "_no rows_",
        "### DD別統計（有意な粒度のみ展開）",
        render_markdown_table(_filtered_stats(step2, sig_step1))
        if not _filtered_stats(step2, sig_step1).empty
        else "KW 非有意のため省略",
        "",
        "## Axis 2: 曜日",
        "### KW検定（3粒度）",
        render_markdown_table(step3) if not step3.empty else "_no rows_",
        "### 曜日別統計（有意な粒度のみ展開）",
        render_markdown_table(_filtered_stats(step4, sig_step3))
        if not _filtered_stats(step4, sig_step3).empty
        else "KW 非有意のため省略",
        "",
        "## Axis 3: イベント日×曜日",
        "### クロス統計",
        render_markdown_table(step5.head(80)) if not step5.empty else "_no rows_",
        "### 2-way ANOVA",
        render_markdown_table(step6) if not step6.empty else "_no rows_",
        "",
        "## Axis 4: ゾロ目（台番号末尾）",
        "### KW検定（3粒度）",
        render_markdown_table(step7) if not step7.empty else "_no rows_",
        "### ゾロ目別統計（有意な粒度のみ展開）",
        render_markdown_table(_filtered_stats(step8, sig_step7))
        if not _filtered_stats(step8, sig_step7).empty
        else "KW 非有意のため省略",
        "",
        "## Summary",
        render_markdown_table(step9) if not step9.empty else "_no rows_",
        "",
        "### 主要 finding",
    ]

    top_findings = step9.loc[step9["verdict"].ne("✗脱落")].copy()
    if top_findings.empty:
        lines.append("- 主要な有意軸はなし")
    else:
        top_findings = top_findings.loc[top_findings["verdict"].ne("skip")].copy()
        if top_findings.empty:
            lines.append("- 主要な有意軸はなし")
        else:
            top_findings["_p"] = pd.to_numeric(top_findings["p_value"], errors="coerce")
            top_findings = top_findings.sort_values(["verdict", "_p"], ascending=[True, True], kind="mergesort")
            for _, row in top_findings.head(8).iterrows():
                lines.append(
                    f"- {row['axis']} / {row['grain']} / {row['segment'] or 'hall'}: p={float(row['p_value']):.4g}, verdict={row['verdict']}"
                )

    return "\n".join(lines).rstrip() + "\n"


def build_all_artifacts(df: pd.DataFrame) -> dict[str, pd.DataFrame | str]:
    work = _prepare_frame(df)
    latest_date = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce").max()
    source_latest_date = latest_date.strftime("%Y%m%d") if pd.notna(latest_date) else "unknown"

    step1 = build_step1_dd_kw(work)
    step2 = build_step2_dd_stats(work)
    step3 = build_step3_weekday_kw(work)
    step4 = build_step4_weekday_stats(work)
    step5 = build_step5_event_weekday_cross(work)
    step6 = build_step6_event_weekday_anova(work)
    step7 = build_step7_zorome_kw(work)
    step8 = build_step8_zorome_stats(work)
    summary = build_step9_summary(
        {
            "dd_spectrum": step1,
            "day_of_week": step3,
            "is_zorome": step7,
        },
        step6,
    )

    artifacts: dict[str, pd.DataFrame | str] = {
        "step1_dd_kw": step1,
        "step2_dd_stats": step2,
        "step3_weekday_kw": step3,
        "step4_weekday_stats": step4,
        "step5_event_weekday_cross": step5,
        "step6_event_weekday_anova": step6,
        "step7_zorome_kw": step7,
        "step8_zorome_stats": step8,
        "step9_summary": summary,
    }
    artifacts["report"] = build_report(artifacts, source_latest_date=source_latest_date)
    return artifacts


def save_outputs(artifacts: dict[str, pd.DataFrame | str], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts["step1_dd_kw"].to_csv(output_dir / "step1_dd_kw.csv", index=False, encoding="utf-8-sig")
    artifacts["step2_dd_stats"].to_csv(output_dir / "step2_dd_stats.csv", index=False, encoding="utf-8-sig")
    artifacts["step3_weekday_kw"].to_csv(output_dir / "step3_weekday_kw.csv", index=False, encoding="utf-8-sig")
    artifacts["step4_weekday_stats"].to_csv(output_dir / "step4_weekday_stats.csv", index=False, encoding="utf-8-sig")
    artifacts["step5_event_weekday_cross"].to_csv(
        output_dir / "step5_event_weekday_cross.csv", index=False, encoding="utf-8-sig"
    )
    artifacts["step6_event_weekday_anova"].to_csv(
        output_dir / "step6_event_weekday_anova.csv", index=False, encoding="utf-8-sig"
    )
    artifacts["step7_zorome_kw"].to_csv(output_dir / "step7_zorome_kw.csv", index=False, encoding="utf-8-sig")
    artifacts["step8_zorome_stats"].to_csv(output_dir / "step8_zorome_stats.csv", index=False, encoding="utf-8-sig")
    artifacts["step9_summary"].to_csv(output_dir / "step9_summary.csv", index=False, encoding="utf-8-sig")
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
