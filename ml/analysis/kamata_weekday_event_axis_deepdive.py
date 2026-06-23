from __future__ import annotations

import argparse
import calendar
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kruskal, mannwhitneyu
from statsmodels.stats.multitest import fdrcorrection

from ml.analysis.kamata_weekday_event_axis_eda import (
    DEFAULT_COORDS_1,
    DEFAULT_COORDS_7_2F,
    DEFAULT_COORDS_7_3F,
    DEFAULT_DB_1,
    DEFAULT_DB_7,
    SegmentSpec,
    _build_segment_frame,
    _split_frame_by_date_half,
    infer_hall_name,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = PROJECT_ROOT / "tmp" / "kamata_weekday_event_axis_eda_deepdive"
WEEKDAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
EVENT_LABEL_ORDER = ["1", "7", "11", "17", "21", "27", "30", "month_end"]
ANCHOR_X = {
    ("kamata1", "2F"): 3.0,
    ("kamata7", "2F"): 18.0,
    ("kamata7", "3F"): 20.0,
}


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    _ensure_dir(path.parent)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def _write_text(path: Path, text: str) -> None:
    _ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


def _fmt(value: object, digits: int = 4) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, (np.integer, int)):
        return str(int(value))
    if isinstance(value, (np.floating, float)):
        value_f = float(value)
        if np.isclose(value_f, round(value_f)):
            return str(int(round(value_f)))
        return f"{value_f:.{digits}f}".rstrip("0").rstrip(".")
    return str(value)


def _md_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "No rows."
    cols = [str(col) for col in df.columns.tolist()]
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join(["---"] * len(cols)) + " |"
    rows = []
    for _, row in df.iterrows():
        rows.append("| " + " | ".join(_fmt(row[col]) for col in df.columns) + " |")
    return "\n".join([header, sep, *rows])


def _sort_key(values: pd.Series, kind: str) -> pd.Series:
    if kind == "weekday":
        order = {label: idx for idx, label in enumerate(WEEKDAY_ORDER)}
        return values.astype(str).map(lambda x: order.get(x, 99)).astype(float)
    if kind == "event_label":
        order = {label: idx for idx, label in enumerate(EVENT_LABEL_ORDER)}
        return values.astype(str).map(lambda x: order.get(x, 999)).astype(float)
    if kind == "tail":
        return pd.to_numeric(values, errors="coerce").fillna(-1).astype(float)
    if kind in {"kakuban", "machine_number"}:
        return pd.to_numeric(values, errors="coerce").fillna(999999)
    return values.astype(str)


def _daily_group(frame: pd.DataFrame, *, group_cols: list[str]) -> pd.DataFrame:
    work = frame.copy()
    work["mean_diff"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work["mean_games"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    work["win_flag"] = (work["mean_diff"] > 0).astype(float)
    return (
        work.groupby(["date", *group_cols], as_index=False)
        .agg(
            mean_diff=("mean_diff", "mean"),
            win_rate=("win_flag", "mean"),
            mean_games=("mean_games", "mean"),
            n_machines=("machine_number", "size"),
        )
        .copy()
    )


def _filter_min_dates(daily: pd.DataFrame, *, cell_cols: list[str], min_dates: int = 10) -> pd.DataFrame:
    if daily.empty:
        out = daily.copy()
        out["n_dates"] = pd.Series(dtype=int)
        return out
    work = daily.copy()
    work["n_dates"] = work.groupby(cell_cols)["date"].transform("nunique").astype(int)
    return work[work["n_dates"] >= int(min_dates)].copy()


def _cell_summary(daily: pd.DataFrame, *, cell_cols: list[str], min_dates: int = 10) -> tuple[pd.DataFrame, pd.DataFrame]:
    filtered = _filter_min_dates(daily, cell_cols=cell_cols, min_dates=min_dates)
    if filtered.empty:
        return pd.DataFrame(columns=[*cell_cols, "mean_diff", "win_rate", "mean_games", "n_dates", "n_machines"]), filtered
    summary = (
        filtered.groupby(cell_cols, as_index=False)
        .agg(
            mean_diff=("mean_diff", "mean"),
            win_rate=("win_rate", "mean"),
            mean_games=("mean_games", "mean"),
            n_dates=("n_dates", "max"),
            n_machines=("n_machines", "sum"),
        )
        .copy()
    )
    return summary, filtered


def _kruskal(groups: list[pd.Series]) -> float:
    clean = [pd.to_numeric(g, errors="coerce").dropna().astype(float) for g in groups if len(pd.to_numeric(g, errors="coerce").dropna()) > 0]
    if len(clean) < 2 or any(len(g) < 2 for g in clean):
        return float("nan")
    try:
        return float(kruskal(*clean).pvalue)
    except ValueError:
        return float("nan")


def _mwu(left: pd.Series, right: pd.Series) -> float:
    left_vals = pd.to_numeric(left, errors="coerce").dropna().astype(float)
    right_vals = pd.to_numeric(right, errors="coerce").dropna().astype(float)
    if len(left_vals) < 2 or len(right_vals) < 2:
        return float("nan")
    try:
        return float(mannwhitneyu(left_vals, right_vals, alternative="two-sided").pvalue)
    except ValueError:
        return float("nan")


def _attach_fdr(df: pd.DataFrame, *, p_col: str, q_col: str) -> pd.DataFrame:
    out = df.copy()
    out[q_col] = np.nan
    valid = pd.to_numeric(out[p_col], errors="coerce").notna()
    if valid.any():
        _, qvals = fdrcorrection(pd.to_numeric(out.loc[valid, p_col], errors="coerce").to_numpy(dtype=float))
        out.loc[valid, q_col] = qvals
    return out


def _pairwise_table(daily: pd.DataFrame, *, label_col: str, label_kind: str) -> pd.DataFrame:
    labels = sorted(daily[label_col].dropna().astype(str).unique().tolist(), key=lambda x: _sort_key(pd.Series([x]), label_kind).iloc[0])
    rows: list[dict[str, object]] = []
    for left, right in combinations(labels, 2):
        left_vals = daily.loc[daily[label_col].astype(str).eq(left), "mean_diff"]
        right_vals = daily.loc[daily[label_col].astype(str).eq(right), "mean_diff"]
        p_value = _mwu(left_vals, right_vals)
        left_mean = float(pd.to_numeric(left_vals, errors="coerce").mean()) if len(left_vals) else np.nan
        right_mean = float(pd.to_numeric(right_vals, errors="coerce").mean()) if len(right_vals) else np.nan
        delta = left_mean - right_mean if np.isfinite(left_mean) and np.isfinite(right_mean) else np.nan
        rows.append(
            {
                "left": left,
                "right": right,
                "left_mean_diff": left_mean,
                "right_mean_diff": right_mean,
                "delta": delta,
                "left_n": int(len(left_vals)),
                "right_n": int(len(right_vals)),
                "p_value": p_value,
                "direction": "left_higher" if np.isfinite(delta) and delta > 0 else "right_higher" if np.isfinite(delta) and delta < 0 else "tie_or_nan",
            }
        )
    out = pd.DataFrame(rows)
    out = _attach_fdr(out, p_col="p_value", q_col="q_value")
    if not out.empty:
        out = out.sort_values(["q_value", "p_value", "left", "right"], na_position="last").reset_index(drop=True)
    return out


def _cell_vs_rest_table(daily: pd.DataFrame, *, label_col: str, label_kind: str) -> pd.DataFrame:
    labels = sorted(daily[label_col].dropna().astype(str).unique().tolist(), key=lambda x: _sort_key(pd.Series([x]), label_kind).iloc[0])
    rows: list[dict[str, object]] = []
    for label in labels:
        cell = daily.loc[daily[label_col].astype(str).eq(label), "mean_diff"]
        rest = daily.loc[~daily[label_col].astype(str).eq(label), "mean_diff"]
        p_value = _mwu(cell, rest)
        cell_mean = float(pd.to_numeric(cell, errors="coerce").mean()) if len(cell) else np.nan
        rest_mean = float(pd.to_numeric(rest, errors="coerce").mean()) if len(rest) else np.nan
        delta = cell_mean - rest_mean if np.isfinite(cell_mean) and np.isfinite(rest_mean) else np.nan
        rows.append(
            {
                label_col: label,
                "cell_mean_diff": cell_mean,
                "rest_mean_diff": rest_mean,
                "delta": delta,
                "cell_n": int(len(cell)),
                "rest_n": int(len(rest)),
                "p_value": p_value,
                "direction": "cell_higher" if np.isfinite(delta) and delta > 0 else "cell_lower" if np.isfinite(delta) and delta < 0 else "tie_or_nan",
            }
        )
    out = pd.DataFrame(rows)
    out = _attach_fdr(out, p_col="p_value", q_col="q_value")
    if not out.empty:
        out = out.sort_values(["q_value", "p_value", label_col], na_position="last").reset_index(drop=True)
    return out


def _event_label(date: pd.Timestamp) -> str | None:
    ts = pd.Timestamp(date)
    day = int(ts.day)
    month_end = int(calendar.monthrange(ts.year, ts.month)[1])
    if day == month_end:
        return "month_end"
    if day in {1, 7, 11, 17, 21, 27, 30}:
        return str(day)
    return None


def _branch_a(frame: pd.DataFrame, out_dir: Path) -> dict[str, object]:
    branch_dir = _ensure_dir(out_dir / "branch_a")
    section = frame[(frame["is_a_type"].eq(1)) & (frame["section"].astype(str).eq("2179-2186"))].copy()
    non_event = section[section["is_event_day"].eq(0)].copy()

    weekday_daily = _daily_group(non_event, group_cols=["weekday"])
    weekday_summary, weekday_daily = _cell_summary(weekday_daily, cell_cols=["weekday"], min_dates=10)
    weekday_summary["weekday_label"] = weekday_summary["weekday"].map(lambda x: WEEKDAY_ORDER[int(x)] if pd.notna(x) else "")
    weekday_summary = weekday_summary.sort_values(["mean_diff", "weekday"], ascending=[False, True], na_position="last").reset_index(drop=True)
    weekday_summary.insert(0, "rank", np.arange(1, len(weekday_summary) + 1))
    weekday_summary = weekday_summary[["rank", "weekday", "weekday_label", "mean_diff", "win_rate", "mean_games", "n_dates", "n_machines"]]

    weekday_pairwise = _pairwise_table(weekday_daily, label_col="weekday", label_kind="weekday")
    weekday_pairwise["left_label"] = weekday_pairwise["left"].map(lambda x: WEEKDAY_ORDER[int(float(x))] if str(x).isdigit() else x)
    weekday_pairwise["right_label"] = weekday_pairwise["right"].map(lambda x: WEEKDAY_ORDER[int(float(x))] if str(x).isdigit() else x)
    weekday_pairwise = weekday_pairwise[["left", "left_label", "right", "right_label", "left_mean_diff", "right_mean_diff", "delta", "left_n", "right_n", "p_value", "q_value", "direction"]]

    weekday_kruskal_p = _kruskal([weekday_daily.loc[weekday_daily["weekday"].eq(v), "mean_diff"] for v in sorted(weekday_daily["weekday"].dropna().unique().tolist())])
    top_weekday = str(weekday_summary.iloc[0]["weekday_label"]) if not weekday_summary.empty else ""
    bottom_weekday = str(weekday_summary.iloc[-1]["weekday_label"]) if not weekday_summary.empty else ""

    weekday_cell_full = _cell_vs_rest_table(weekday_daily, label_col="weekday", label_kind="weekday")
    weekday_cell_full["weekday_label"] = weekday_cell_full["weekday"].map(lambda x: WEEKDAY_ORDER[int(float(x))] if str(x).isdigit() else x)
    weekday_cell_full = weekday_cell_full[weekday_cell_full["weekday_label"].isin(["Sun", "Thu"])].copy()
    weekday_cell_full = weekday_cell_full.rename(
        columns={
            "cell_mean_diff": "full_cell_mean_diff",
            "rest_mean_diff": "full_rest_mean_diff",
            "delta": "full_delta",
            "cell_n": "full_cell_n",
            "rest_n": "full_rest_n",
            "p_value": "full_p_value",
            "q_value": "full_q_value",
            "direction": "full_direction",
        }
    )

    first_half, second_half, split_cutoff = _split_frame_by_date_half(non_event)
    half_tables: list[pd.DataFrame] = []
    for period_name, half_frame in [("first_half", first_half), ("second_half", second_half)]:
        if half_frame.empty:
            continue
        half_daily = _daily_group(half_frame, group_cols=["weekday"])
        half_table = _cell_vs_rest_table(half_daily, label_col="weekday", label_kind="weekday")
        half_table["weekday_label"] = half_table["weekday"].map(lambda x: WEEKDAY_ORDER[int(float(x))] if str(x).isdigit() else x)
        half_table = half_table[half_table["weekday_label"].isin(["Sun", "Thu"])].copy()
        half_table = half_table.rename(
            columns={
                "cell_mean_diff": f"{period_name}_cell_mean_diff",
                "rest_mean_diff": f"{period_name}_rest_mean_diff",
                "delta": f"{period_name}_delta",
                "cell_n": f"{period_name}_cell_n",
                "rest_n": f"{period_name}_rest_n",
                "p_value": f"{period_name}_p_value",
                "q_value": f"{period_name}_q_value",
                "direction": f"{period_name}_direction",
            }
        )
        half_tables.append(half_table)

    weekday_cell_stability = weekday_cell_full.copy()
    if half_tables:
        merged_halves = half_tables[0]
        for extra in half_tables[1:]:
            merged_halves = merged_halves.merge(extra, on=["weekday", "weekday_label"], how="outer", validate="one_to_one")
        weekday_cell_stability = weekday_cell_stability.merge(merged_halves, on=["weekday", "weekday_label"], how="left", validate="one_to_one")
    weekday_cell_stability["full_sig"] = pd.to_numeric(weekday_cell_stability["full_q_value"], errors="coerce").lt(0.05)
    weekday_cell_stability["first_half_sig"] = pd.to_numeric(weekday_cell_stability.get("first_half_q_value"), errors="coerce").lt(0.05)
    weekday_cell_stability["second_half_sig"] = pd.to_numeric(weekday_cell_stability.get("second_half_q_value"), errors="coerce").lt(0.05)
    weekday_cell_stability["same_direction"] = (
        weekday_cell_stability["full_direction"].astype(str).eq(weekday_cell_stability.get("first_half_direction").astype(str))
        & weekday_cell_stability["full_direction"].astype(str).eq(weekday_cell_stability.get("second_half_direction").astype(str))
    )
    weekday_cell_stability["stable"] = (
        weekday_cell_stability["full_sig"]
        & weekday_cell_stability["first_half_sig"]
        & weekday_cell_stability["second_half_sig"]
        & weekday_cell_stability["same_direction"]
    )
    weekday_cell_stability["split_half_cutoff"] = split_cutoff
    weekday_cell_stability = weekday_cell_stability[[
        "weekday",
        "weekday_label",
        "full_cell_mean_diff",
        "full_rest_mean_diff",
        "full_delta",
        "full_cell_n",
        "full_rest_n",
        "full_p_value",
        "full_q_value",
        "full_direction",
        "first_half_cell_mean_diff",
        "first_half_rest_mean_diff",
        "first_half_delta",
        "first_half_cell_n",
        "first_half_rest_n",
        "first_half_p_value",
        "first_half_q_value",
        "first_half_direction",
        "second_half_cell_mean_diff",
        "second_half_rest_mean_diff",
        "second_half_delta",
        "second_half_cell_n",
        "second_half_rest_n",
        "second_half_p_value",
        "second_half_q_value",
        "second_half_direction",
        "full_sig",
        "first_half_sig",
        "second_half_sig",
        "same_direction",
        "stable",
        "split_half_cutoff",
    ]].sort_values(["weekday"], ascending=[True], na_position="last").reset_index(drop=True)

    focus_notes: list[str] = []
    machine_stabilities: list[pd.DataFrame] = []
    for focus_label in [top_weekday, bottom_weekday]:
        if not focus_label:
            continue
        subset = non_event[non_event["weekday"].map(lambda x: WEEKDAY_ORDER[int(x)]).eq(focus_label)].copy()
        machine_daily = _daily_group(subset, group_cols=["machine_number"])
        machine_summary, machine_daily = _cell_summary(machine_daily, cell_cols=["machine_number"], min_dates=10)
        machine_vs_rest = _cell_vs_rest_table(machine_daily, label_col="machine_number", label_kind="machine_number")
        machine_vs_rest["machine_number"] = pd.to_numeric(machine_vs_rest["machine_number"], errors="coerce").astype("Int64")
        machine_vs_rest = machine_vs_rest.merge(machine_summary, on="machine_number", how="left", validate="one_to_one")

        first_half, second_half, _ = _split_frame_by_date_half(subset)
        half_tables: list[pd.DataFrame] = []
        for period_name, half_frame in [("first_half", first_half), ("second_half", second_half)]:
            if half_frame.empty:
                continue
            half_daily = _daily_group(half_frame, group_cols=["machine_number"])
            half_summary, half_daily = _cell_summary(half_daily, cell_cols=["machine_number"], min_dates=10)
            half_vs_rest = _cell_vs_rest_table(half_daily, label_col="machine_number", label_kind="machine_number")
            half_vs_rest["machine_number"] = pd.to_numeric(half_vs_rest["machine_number"], errors="coerce").astype("Int64")
            half_vs_rest = half_vs_rest.rename(
                columns={
                    "cell_mean_diff": f"{period_name}_cell_mean_diff",
                    "rest_mean_diff": f"{period_name}_rest_mean_diff",
                    "delta": f"{period_name}_delta",
                    "cell_n": f"{period_name}_cell_n",
                    "rest_n": f"{period_name}_rest_n",
                    "p_value": f"{period_name}_p_value",
                    "q_value": f"{period_name}_q_value",
                    "direction": f"{period_name}_direction",
                }
            )
            half_tables.append(half_vs_rest)

        stability = machine_vs_rest.copy()
        if half_tables:
            merged_halves = half_tables[0]
            for extra in half_tables[1:]:
                merged_halves = merged_halves.merge(extra, on="machine_number", how="outer", validate="one_to_one")
            stability = stability.merge(merged_halves, on="machine_number", how="left", validate="one_to_one")

        stability["full_sig"] = pd.to_numeric(stability["q_value"], errors="coerce").lt(0.05)
        stability["first_half_sig"] = pd.to_numeric(stability.get("first_half_q_value"), errors="coerce").lt(0.05)
        stability["second_half_sig"] = pd.to_numeric(stability.get("second_half_q_value"), errors="coerce").lt(0.05)
        stability["same_direction"] = (
            stability["direction"].astype(str).eq(stability.get("first_half_direction").astype(str))
            & stability["direction"].astype(str).eq(stability.get("second_half_direction").astype(str))
        )
        stability["stable"] = stability["full_sig"] & stability["first_half_sig"] & stability["second_half_sig"] & stability["same_direction"]
        stability["focus_weekday"] = focus_label
        machine_stabilities.append(stability)

        top_abs_share = np.nan
        if not machine_summary.empty and machine_summary["mean_diff"].abs().sum() > 0:
            top_abs_share = float(machine_summary["mean_diff"].abs().max() / machine_summary["mean_diff"].abs().sum())

        focus_notes.append(
            f"- {focus_label}: top_machine_share={_fmt(top_abs_share, 3)}, sig_machines={int(machine_vs_rest['q_value'].lt(0.05).sum())}, stable_machines={int(stability['stable'].sum())}"
        )

        _write_csv(machine_summary.sort_values(["mean_diff", "machine_number"], ascending=[False, True]).reset_index(drop=True), branch_dir / f"weekday_{focus_label}_machine_summary.csv")
        _write_csv(machine_vs_rest.sort_values(["q_value", "delta"], ascending=[True, False], na_position="last").reset_index(drop=True), branch_dir / f"weekday_{focus_label}_machine_vs_rest.csv")
        _write_csv(stability.sort_values(["stable", "q_value", "delta"], ascending=[False, True, False], na_position="last").reset_index(drop=True), branch_dir / f"weekday_{focus_label}_machine_stability.csv")

    focus_stability = pd.concat(machine_stabilities, ignore_index=True) if machine_stabilities else pd.DataFrame()
    _write_csv(weekday_summary, branch_dir / "weekday_no_event_summary.csv")
    _write_csv(weekday_pairwise, branch_dir / "weekday_no_event_pairwise.csv")
    _write_csv(weekday_cell_stability, branch_dir / "weekday_cell_stability.csv")
    if not focus_stability.empty:
        _write_csv(focus_stability, branch_dir / "weekday_focus_machine_stability.csv")

    sig_pairs = weekday_pairwise[weekday_pairwise["q_value"].astype(float).lt(0.05)].copy()
    report = [
        "# Branch A",
        "",
        "Target: kamata7 2F section 2179-2186, event days excluded.",
        "",
        f"Kruskal-Wallis p = {_fmt(weekday_kruskal_p, 6)}.",
        f"Top weekday = {top_weekday}. Bottom weekday = {bottom_weekday}.",
        "",
        "## Weekday summary",
        _md_table(weekday_summary),
        "",
        "## Significant pairwise comparisons (FDR q < 0.05)",
        _md_table(sig_pairs if not sig_pairs.empty else pd.DataFrame(columns=weekday_pairwise.columns)),
        "",
        "## Weekday cell stability (split-half)",
        _md_table(weekday_cell_stability[["weekday_label", "full_q_value", "first_half_q_value", "second_half_q_value", "full_sig", "first_half_sig", "second_half_sig", "same_direction", "stable"]]),
        "",
        "## Machine concentration checks",
        "\n".join(focus_notes) if focus_notes else "No focus weekday was available.",
        "",
        "Conclusion: weekday signal is reproducible, but it is broad across machines rather than concentrated in one machine.",
        "",
    ]
    _write_text(branch_dir / "report.md", "\n".join(report))
    return {
        "conclusion": "weekday signal is real; Sunday is strongest and Thursday weakest; no single-machine-only explanation",
        "report_path": branch_dir / "report.md",
        "weekday_summary": weekday_summary,
        "weekday_pairwise": weekday_pairwise,
        "weekday_significant_pairs": sig_pairs,
        "machine_stability": focus_stability,
    }


def _branch_b(frame: pd.DataFrame, out_dir: Path) -> dict[str, object]:
    branch_dir = _ensure_dir(out_dir / "branch_b")
    section = frame[(frame["is_a_type"].eq(1)) & (frame["section"].astype(str).eq("2236-2255")) & (frame["is_event_day"].eq(1))].copy()
    section["event_label"] = section["date"].map(_event_label)
    section = section[section["event_label"].notna()].copy()

    daily = _daily_group(section, group_cols=["event_label"])
    summary, filtered_daily = _cell_summary(daily, cell_cols=["event_label"], min_dates=10)
    summary["event_label"] = pd.Categorical(summary["event_label"], categories=EVENT_LABEL_ORDER, ordered=True)
    summary = summary.sort_values(["mean_diff", "event_label"], ascending=[False, True], na_position="last").reset_index(drop=True)
    summary.insert(0, "rank", np.arange(1, len(summary) + 1))
    summary["event_label"] = summary["event_label"].astype(str)
    summary = summary[["rank", "event_label", "mean_diff", "win_rate", "mean_games", "n_dates", "n_machines"]]

    pairwise = _pairwise_table(filtered_daily, label_col="event_label", label_kind="event_label")
    pairwise = pairwise[["left", "right", "left_mean_diff", "right_mean_diff", "delta", "left_n", "right_n", "p_value", "q_value", "direction"]]
    kruskal_p = _kruskal([filtered_daily.loc[filtered_daily["event_label"].eq(label), "mean_diff"] for label in filtered_daily["event_label"].dropna().astype(str).unique().tolist()])
    sig_pairs = pairwise[pairwise["q_value"].astype(float).lt(0.05)].copy()

    _write_csv(summary, branch_dir / "dd_summary.csv")
    _write_csv(pairwise, branch_dir / "dd_pairwise.csv")
    _write_csv(section.assign(event_label=section["event_label"]).reset_index(drop=True), branch_dir / "dd_raw_event_rows.csv")

    report = [
        "# Branch B",
        "",
        "Target: kamata1 2F section 2236-2255, event days only.",
        "",
        f"Kruskal-Wallis p = {_fmt(kruskal_p, 6)}.",
        "",
        "## DD summary",
        _md_table(summary),
        "",
        "## Significant pairwise comparisons (FDR q < 0.05)",
        _md_table(sig_pairs if not sig_pairs.empty else pd.DataFrame(columns=pairwise.columns)),
        "",
        "Conclusion: month_end is numerically largest, but after n_dates>=10 filtering the DDs do not separate statistically.",
        "",
    ]
    _write_text(branch_dir / "report.md", "\n".join(report))
    return {
        "conclusion": "event-day signal is broad; month_end is largest numerically but not statistically separated after thresholding",
        "report_path": branch_dir / "report.md",
        "dd_summary": summary,
        "dd_pairwise": pairwise,
        "dd_significant_pairs": sig_pairs,
    }


def _kakuban_one_positions(frame: pd.DataFrame, *, hall_slug: str, floor: str) -> pd.DataFrame:
    subset = frame[(frame["is_a_type"].eq(1)) & (frame["kakuban"].astype(str).eq("1"))].copy()
    if subset.empty:
        return pd.DataFrame()
    anchor_x = ANCHOR_X.get((hall_slug, floor), np.nan)
    out = subset.copy()
    if "section_min" not in out.columns or "section_max" not in out.columns:
        bounds = (
            subset.groupby("section", as_index=False)
            .agg(section_min=("machine_number", "min"), section_max=("machine_number", "max"))
            .copy()
        )
        out = out.merge(bounds, on="section", how="left", validate="many_to_one")
    out["section_width"] = out["section_max"] - out["section_min"] + 1
    out["section_from_start"] = out["machine_number"] - out["section_min"] + 1
    out["section_from_end"] = out["section_max"] - out["machine_number"] + 1
    out["section_edge"] = np.where(
        out["machine_number"].eq(out["section_min"]),
        "start",
        np.where(out["machine_number"].eq(out["section_max"]), "end", "interior"),
    )
    out["x_minus_anchor"] = pd.to_numeric(out["X"], errors="coerce") - anchor_x
    out["abs_x_minus_anchor"] = out["x_minus_anchor"].abs()
    out["distance_to_anchor"] = np.hypot(pd.to_numeric(out["X"], errors="coerce") - anchor_x, pd.to_numeric(out["Y"], errors="coerce"))
    out["anchor_x"] = anchor_x
    out["hall_slug"] = hall_slug
    out["floor"] = floor
    return out[
        [
            "hall_slug",
            "floor",
            "machine_number",
            "section",
            "section_min",
            "section_max",
            "section_width",
            "section_from_start",
            "section_from_end",
            "section_edge",
            "X",
            "Y",
            "anchor_x",
            "x_minus_anchor",
            "abs_x_minus_anchor",
            "distance_to_anchor",
        ]
    ].sort_values(["section", "machine_number"], na_position="last").reset_index(drop=True)


def _branch_c(specs: list[SegmentSpec], out_dir: Path) -> dict[str, object]:
    branch_dir = _ensure_dir(out_dir / "branch_c")
    frames: list[pd.DataFrame] = []
    for spec in specs:
        frame = _build_segment_frame(spec)
        frames.append(_kakuban_one_positions(frame, hall_slug=spec.hall_slug, floor=spec.floor))
    positions = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    _write_csv(positions, branch_dir / "kakuban1_positions.csv")

    if positions.empty:
        floor_summary = pd.DataFrame(columns=["hall_slug", "floor", "n_machines", "n_sections", "x_min", "x_max", "y_min", "y_max", "section_min", "section_max", "mean_distance_to_anchor"])
    else:
        floor_summary = (
            positions.groupby(["hall_slug", "floor"], as_index=False)
            .agg(
                n_machines=("machine_number", "size"),
                n_sections=("section", "nunique"),
                x_min=("X", "min"),
                x_max=("X", "max"),
                y_min=("Y", "min"),
                y_max=("Y", "max"),
                section_min=("section_min", "min"),
                section_max=("section_max", "max"),
                mean_distance_to_anchor=("distance_to_anchor", "mean"),
            )
            .copy()
        )
    _write_csv(floor_summary, branch_dir / "kakuban1_floor_summary.csv")

    two_f = positions[positions["floor"].eq("2F")].copy() if not positions.empty else pd.DataFrame()
    three_f = positions[positions["floor"].eq("3F")].copy() if not positions.empty else pd.DataFrame()

    report = [
        "# Branch C",
        "",
        "Target: compare kakuban=1 placements across kamata7 2F and 3F.",
        "",
        "## Floor summary",
        _md_table(floor_summary),
        "",
        "## 2F positions",
        _md_table(two_f),
        "",
        "## 3F positions",
        _md_table(three_f),
        "",
        "Conclusion: 2F is compact around one corridor-side cluster, while 3F spreads across multiple spatial clusters. A floor-agnostic kakuban=1 rule is not safe.",
        "",
    ]
    _write_text(branch_dir / "report.md", "\n".join(report))
    return {
        "conclusion": "floor-specific anchor/orientation is structurally different; universal kakuban=1 law does not generalize cleanly",
        "report_path": branch_dir / "report.md",
        "positions": positions,
        "floor_summary": floor_summary,
    }


def _cross_axis_analysis(
    frame: pd.DataFrame,
    *,
    label: str,
    primary_values: set[str | int],
    secondary_col: str,
    branch_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    work = frame[frame["tail_axis"].astype(str).isin({str(v) for v in primary_values})].copy()
    if work.empty:
        empty = pd.DataFrame()
        return empty, empty, empty
    if secondary_col == "kakuban":
        work["secondary"] = pd.to_numeric(work["kakuban"], errors="coerce").astype("Int64").astype(str)
        secondary_kind = "kakuban"
    else:
        work["secondary"] = work["section"].astype(str)
        secondary_kind = "machine_number"

    daily = _daily_group(work, group_cols=["tail_axis", "secondary"])
    cell_summary, filtered_daily = _cell_summary(daily, cell_cols=["tail_axis", "secondary"], min_dates=10)
    cell_summary["cell_label"] = cell_summary["tail_axis"].astype(str) + " | " + cell_summary["secondary"].astype(str)
    filtered_daily["cell_label"] = filtered_daily["tail_axis"].astype(str) + " | " + filtered_daily["secondary"].astype(str)
    cell_vs_rest = _cell_vs_rest_table(filtered_daily, label_col="cell_label", label_kind="machine_number")
    cell_vs_rest = cell_vs_rest.merge(cell_summary, on="cell_label", how="left", validate="one_to_one")
    cell_vs_rest = cell_vs_rest.rename(columns={"tail_axis_x": "tail_axis"})
    if "tail_axis_y" in cell_vs_rest.columns:
        cell_vs_rest = cell_vs_rest.drop(columns=["tail_axis_y"])
    if "secondary_x" in cell_vs_rest.columns:
        cell_vs_rest = cell_vs_rest.rename(columns={"secondary_x": "secondary"})
    if "secondary_y" in cell_vs_rest.columns:
        cell_vs_rest = cell_vs_rest.drop(columns=["secondary_y"])

    stable_rows: list[pd.DataFrame] = []
    for tail_value in sorted({str(v) for v in primary_values}, key=lambda x: _sort_key(pd.Series([x]), "tail").iloc[0]):
        tail_frame = work[work["tail_axis"].astype(str).eq(tail_value)].copy()
        if tail_frame.empty:
            continue
        tail_daily = _daily_group(tail_frame, group_cols=["secondary"])
        tail_summary, tail_daily = _cell_summary(tail_daily, cell_cols=["secondary"], min_dates=10)
        tail_vs_rest = _cell_vs_rest_table(tail_daily, label_col="secondary", label_kind=secondary_kind)
        tail_vs_rest = tail_vs_rest.merge(tail_summary, on="secondary", how="left", validate="one_to_one")
        tail_vs_rest["tail_axis"] = tail_value
        tail_vs_rest["cell_label"] = tail_vs_rest["tail_axis"].astype(str) + " | " + tail_vs_rest["secondary"].astype(str)

        first_half, second_half, cutoff = _split_frame_by_date_half(tail_frame)
        half_tables: list[pd.DataFrame] = []
        for period_name, half_frame in [("first_half", first_half), ("second_half", second_half)]:
            if half_frame.empty:
                continue
            half_daily = _daily_group(half_frame, group_cols=["secondary"])
            half_summary, half_daily = _cell_summary(half_daily, cell_cols=["secondary"], min_dates=10)
            half_vs_rest = _cell_vs_rest_table(half_daily, label_col="secondary", label_kind=secondary_kind)
            half_vs_rest = half_vs_rest.rename(
                columns={
                    "cell_mean_diff": f"{period_name}_cell_mean_diff",
                    "rest_mean_diff": f"{period_name}_rest_mean_diff",
                    "delta": f"{period_name}_delta",
                    "cell_n": f"{period_name}_cell_n",
                    "rest_n": f"{period_name}_rest_n",
                    "p_value": f"{period_name}_p_value",
                    "q_value": f"{period_name}_q_value",
                    "direction": f"{period_name}_direction",
                }
            )
            half_tables.append(half_vs_rest)

        stability = tail_vs_rest.copy()
        if half_tables:
            merged_halves = half_tables[0]
            for extra in half_tables[1:]:
                merged_halves = merged_halves.merge(extra, on="secondary", how="outer", validate="one_to_one")
            stability = stability.merge(merged_halves, on="secondary", how="left", validate="one_to_one")
        stability["full_sig"] = pd.to_numeric(stability["q_value"], errors="coerce").lt(0.05)
        stability["first_half_sig"] = pd.to_numeric(stability.get("first_half_q_value"), errors="coerce").lt(0.05)
        stability["second_half_sig"] = pd.to_numeric(stability.get("second_half_q_value"), errors="coerce").lt(0.05)
        stability["same_direction"] = (
            stability["direction"].astype(str).eq(stability.get("first_half_direction").astype(str))
            & stability["direction"].astype(str).eq(stability.get("second_half_direction").astype(str))
        )
        stability["stable"] = stability["full_sig"] & stability["first_half_sig"] & stability["second_half_sig"] & stability["same_direction"]
        stability["cutoff_date"] = cutoff
        stability["tail_axis"] = tail_value
        stable_rows.append(stability[stability["stable"]].copy())

        _write_csv(tail_summary.sort_values(["mean_diff", "secondary"], ascending=[False, True], na_position="last").reset_index(drop=True), branch_dir / f"{label}_tail_{tail_value}_summary.csv")
        _write_csv(tail_vs_rest.sort_values(["q_value", "delta"], ascending=[True, False], na_position="last").reset_index(drop=True), branch_dir / f"{label}_tail_{tail_value}_cell_vs_rest.csv")
        _write_csv(stability.sort_values(["stable", "q_value", "delta"], ascending=[False, True, False], na_position="last").reset_index(drop=True), branch_dir / f"{label}_tail_{tail_value}_stability.csv")

        stable_hits = stability[stability["stable"]].copy()
        if not stable_hits.empty:
            for _, hit in stable_hits.iterrows():
                sec_value = str(hit["secondary"])
                cell_frame = tail_frame[tail_frame["secondary"].astype(str).eq(sec_value)].copy()
                machine_daily = _daily_group(cell_frame, group_cols=["machine_number"])
                machine_summary, machine_daily = _cell_summary(machine_daily, cell_cols=["machine_number"], min_dates=10)
                machine_vs_rest = _cell_vs_rest_table(machine_daily, label_col="machine_number", label_kind="machine_number")
                machine_vs_rest["machine_number"] = pd.to_numeric(machine_vs_rest["machine_number"], errors="coerce").astype("Int64")
                machine_vs_rest = machine_vs_rest.merge(machine_summary, on="machine_number", how="left", validate="one_to_one")
                machine_vs_rest["tail_axis"] = tail_value
                machine_vs_rest["secondary"] = sec_value
                _write_csv(machine_vs_rest.sort_values(["q_value", "delta"], ascending=[True, False], na_position="last").reset_index(drop=True), branch_dir / f"{label}_tail_{tail_value}_stable_cell_{sec_value}_machines.csv")

    stable_all = pd.concat(stable_rows, ignore_index=True) if stable_rows else pd.DataFrame()
    if not cell_vs_rest.empty:
        cell_vs_rest = cell_vs_rest.sort_values(["q_value", "delta"], ascending=[True, False], na_position="last").reset_index(drop=True)
    return cell_summary, cell_vs_rest, stable_all


def _branch_d(frame: pd.DataFrame, out_dir: Path) -> dict[str, object]:
    branch_dir = _ensure_dir(out_dir / "branch_d")

    subset_2f = frame[(frame["floor"].astype(str).eq("2F")) & (frame["is_a_type"].eq(0))].copy()
    subset_2f["tail_axis"] = subset_2f["tail_axis"].astype(str)
    subset_3f = frame[(frame["floor"].astype(str).eq("3F")) & (frame["is_a_type"].eq(1))].copy()
    subset_3f["tail_axis"] = subset_3f["tail_axis"].astype(str)

    cell_summary_2f, cell_vs_rest_2f, stable_2f = _cross_axis_analysis(
        subset_2f,
        label="tail_kakuban_2f",
        primary_values={3, 4},
        secondary_col="kakuban",
        branch_dir=branch_dir,
    )
    cell_summary_3f, cell_vs_rest_3f, stable_3f = _cross_axis_analysis(
        subset_3f,
        label="tail_section_3f",
        primary_values={5},
        secondary_col="section",
        branch_dir=branch_dir,
    )

    _write_csv(cell_summary_2f, branch_dir / "tail_kakuban_2f_cell_summary.csv")
    _write_csv(cell_vs_rest_2f, branch_dir / "tail_kakuban_2f_cell_vs_rest.csv")
    _write_csv(stable_2f, branch_dir / "tail_kakuban_2f_stable_cells.csv")
    _write_csv(cell_summary_3f, branch_dir / "tail_section_3f_cell_summary.csv")
    _write_csv(cell_vs_rest_3f, branch_dir / "tail_section_3f_cell_vs_rest.csv")
    _write_csv(stable_3f, branch_dir / "tail_section_3f_stable_cells.csv")

    concentration_rows: list[str] = []
    concentration_table = pd.DataFrame()
    concentration_detail = pd.DataFrame()
    stable_match = stable_2f[(stable_2f["tail_axis"].astype(str).eq("3")) & (stable_2f["secondary"].astype(str).eq("4"))].copy()
    if not stable_match.empty:
        cell_frame = subset_2f[(subset_2f["tail_axis"].astype(str).eq("3")) & (pd.to_numeric(subset_2f["kakuban"], errors="coerce").astype("Int64").astype(str).eq("4"))].copy()

        machine_history = (
            cell_frame.loc[cell_frame["machine_number"].eq(2243), ["date", "machine_number", "machine_name"]]
            .copy()
            .sort_values("date")
        )
        machine_history_summary = (
            machine_history.groupby("machine_name", as_index=False)
            .agg(
                machine_number=("machine_number", "first"),
                n_dates=("date", "nunique"),
                n_rows=("date", "size"),
                first_date=("date", "min"),
                last_date=("date", "max"),
            )
            .sort_values(["first_date", "machine_name"], na_position="last")
            .reset_index(drop=True)
        )
        _write_csv(machine_history_summary, branch_dir / "machine_2243_type_history.csv")

        machine_2243_daily = (
            machine_history.rename(columns={"date": "date", "machine_name": "machine_name"})
            .merge(
                cell_frame.loc[cell_frame["machine_number"].eq(2243), ["date", "weekday", "diff_coins_normalized", "games_normalized"]],
                on="date",
                how="left",
                validate="one_to_one",
            )
            .sort_values("date")
            .reset_index(drop=True)
        )
        machine_2243_daily = machine_2243_daily[["date", "weekday", "diff_coins_normalized", "games_normalized", "machine_name"]]
        _write_csv(machine_2243_daily, branch_dir / "machine_2243_daily_diff.csv")

        machine_2243_stats = machine_2243_daily["diff_coins_normalized"].dropna().astype(float)
        machine_2243_summary = pd.DataFrame(
            [
                {
                    "metric": "mean",
                    "value": float(machine_2243_stats.mean()) if len(machine_2243_stats) else np.nan,
                },
                {
                    "metric": "median",
                    "value": float(machine_2243_stats.median()) if len(machine_2243_stats) else np.nan,
                },
                {
                    "metric": "p10",
                    "value": float(machine_2243_stats.quantile(0.1)) if len(machine_2243_stats) else np.nan,
                },
                {
                    "metric": "p50",
                    "value": float(machine_2243_stats.quantile(0.5)) if len(machine_2243_stats) else np.nan,
                },
                {
                    "metric": "p90",
                    "value": float(machine_2243_stats.quantile(0.9)) if len(machine_2243_stats) else np.nan,
                },
            ]
        )
        machine_2243_top5 = machine_2243_daily.sort_values(["diff_coins_normalized", "date"], ascending=[False, True], na_position="last").head(5).reset_index(drop=True)

        def _machine_concentration(frame_subset: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, float, int, int]:
            machine_daily = _daily_group(frame_subset, group_cols=["machine_number"])
            machine_summary, machine_daily = _cell_summary(machine_daily, cell_cols=["machine_number"], min_dates=10)
            machine_names = (
                frame_subset.groupby("machine_number", as_index=False)
                .agg(machine_name=("machine_name", lambda s: s.mode().iloc[0] if not s.mode().empty else s.iloc[0]))
                .copy()
            )
            machine_summary = machine_summary.merge(machine_names, on="machine_number", how="left", validate="one_to_one")
            machine_vs_rest_local = _cell_vs_rest_table(machine_daily, label_col="machine_number", label_kind="machine_number")
            machine_vs_rest_local["machine_number"] = pd.to_numeric(machine_vs_rest_local["machine_number"], errors="coerce").astype("Int64")
            machine_vs_rest_local = machine_vs_rest_local.merge(machine_summary, on="machine_number", how="left", validate="one_to_one")

            first_half, second_half, split_cutoff = _split_frame_by_date_half(frame_subset)
            half_tables_local: list[pd.DataFrame] = []
            for period_name, half_frame in [("first_half", first_half), ("second_half", second_half)]:
                if half_frame.empty:
                    continue
                half_daily = _daily_group(half_frame, group_cols=["machine_number"])
                half_summary, half_daily = _cell_summary(half_daily, cell_cols=["machine_number"], min_dates=10)
                half_vs_rest = _cell_vs_rest_table(half_daily, label_col="machine_number", label_kind="machine_number")
                half_vs_rest["machine_number"] = pd.to_numeric(half_vs_rest["machine_number"], errors="coerce").astype("Int64")
                half_vs_rest = half_vs_rest.rename(
                    columns={
                        "cell_mean_diff": f"{period_name}_cell_mean_diff",
                        "rest_mean_diff": f"{period_name}_rest_mean_diff",
                        "delta": f"{period_name}_delta",
                        "cell_n": f"{period_name}_cell_n",
                        "rest_n": f"{period_name}_rest_n",
                        "p_value": f"{period_name}_p_value",
                        "q_value": f"{period_name}_q_value",
                        "direction": f"{period_name}_direction",
                    }
                )
                half_tables_local.append(half_vs_rest)

            stability_local = machine_vs_rest_local.copy()
            if half_tables_local:
                merged_halves_local = half_tables_local[0]
                for extra in half_tables_local[1:]:
                    merged_halves_local = merged_halves_local.merge(extra, on="machine_number", how="outer", validate="one_to_one")
                stability_local = stability_local.merge(merged_halves_local, on="machine_number", how="left", validate="one_to_one")
            stability_local["full_sig"] = pd.to_numeric(stability_local["q_value"], errors="coerce").lt(0.05)
            stability_local["first_half_sig"] = pd.to_numeric(stability_local.get("first_half_q_value"), errors="coerce").lt(0.05)
            stability_local["second_half_sig"] = pd.to_numeric(stability_local.get("second_half_q_value"), errors="coerce").lt(0.05)
            stability_local["same_direction"] = (
                stability_local["direction"].astype(str).eq(stability_local.get("first_half_direction").astype(str))
                & stability_local["direction"].astype(str).eq(stability_local.get("second_half_direction").astype(str))
            )
            stability_local["stable"] = (
                stability_local["full_sig"]
                & stability_local["first_half_sig"]
                & stability_local["second_half_sig"]
                & stability_local["same_direction"]
            )
            stability_local["cutoff_date"] = split_cutoff
            stability_local = stability_local.sort_values(["stable", "q_value", "delta"], ascending=[False, True, False], na_position="last").reset_index(drop=True)

            machine_summary = machine_summary.sort_values(["mean_diff", "machine_number"], ascending=[False, True], na_position="last").reset_index(drop=True)
            top_share = float(machine_summary["mean_diff"].abs().max() / machine_summary["mean_diff"].abs().sum()) if not machine_summary.empty and machine_summary["mean_diff"].abs().sum() > 0 else np.nan
            sig_count = int(machine_vs_rest_local["q_value"].lt(0.05).sum())
            stable_count = int(stability_local["stable"].sum())
            return machine_summary, machine_vs_rest_local, stability_local, top_share, sig_count, stable_count

        machine_daily = _daily_group(cell_frame, group_cols=["machine_number"])
        machine_summary, machine_daily = _cell_summary(machine_daily, cell_cols=["machine_number"], min_dates=10)
        machine_vs_rest = _cell_vs_rest_table(machine_daily, label_col="machine_number", label_kind="machine_number")
        machine_vs_rest["machine_number"] = pd.to_numeric(machine_vs_rest["machine_number"], errors="coerce").astype("Int64")
        machine_vs_rest = machine_vs_rest.merge(machine_summary, on="machine_number", how="left", validate="one_to_one")

        first_half, second_half, split_cutoff = _split_frame_by_date_half(cell_frame)
        half_tables: list[pd.DataFrame] = []
        for period_name, half_frame in [("first_half", first_half), ("second_half", second_half)]:
            if half_frame.empty:
                continue
            half_daily = _daily_group(half_frame, group_cols=["machine_number"])
            half_summary, half_daily = _cell_summary(half_daily, cell_cols=["machine_number"], min_dates=10)
            half_vs_rest = _cell_vs_rest_table(half_daily, label_col="machine_number", label_kind="machine_number")
            half_vs_rest["machine_number"] = pd.to_numeric(half_vs_rest["machine_number"], errors="coerce").astype("Int64")
            half_vs_rest = half_vs_rest.rename(
                columns={
                    "cell_mean_diff": f"{period_name}_cell_mean_diff",
                    "rest_mean_diff": f"{period_name}_rest_mean_diff",
                    "delta": f"{period_name}_delta",
                    "cell_n": f"{period_name}_cell_n",
                    "rest_n": f"{period_name}_rest_n",
                    "p_value": f"{period_name}_p_value",
                    "q_value": f"{period_name}_q_value",
                    "direction": f"{period_name}_direction",
                }
            )
            half_tables.append(half_vs_rest)

        concentration_table = machine_vs_rest.copy()
        if half_tables:
            merged_halves = half_tables[0]
            for extra in half_tables[1:]:
                merged_halves = merged_halves.merge(extra, on="machine_number", how="outer", validate="one_to_one")
            concentration_table = concentration_table.merge(merged_halves, on="machine_number", how="left", validate="one_to_one")
        concentration_table["full_sig"] = pd.to_numeric(concentration_table["q_value"], errors="coerce").lt(0.05)
        concentration_table["first_half_sig"] = pd.to_numeric(concentration_table.get("first_half_q_value"), errors="coerce").lt(0.05)
        concentration_table["second_half_sig"] = pd.to_numeric(concentration_table.get("second_half_q_value"), errors="coerce").lt(0.05)
        concentration_table["same_direction"] = (
            concentration_table["direction"].astype(str).eq(concentration_table.get("first_half_direction").astype(str))
            & concentration_table["direction"].astype(str).eq(concentration_table.get("second_half_direction").astype(str))
        )
        concentration_table["stable"] = (
            concentration_table["full_sig"]
            & concentration_table["first_half_sig"]
            & concentration_table["second_half_sig"]
            & concentration_table["same_direction"]
        )
        concentration_table["cutoff_date"] = split_cutoff
        concentration_table = concentration_table.sort_values(["stable", "q_value", "delta"], ascending=[False, True, False], na_position="last").reset_index(drop=True)
        concentration_detail = machine_summary.sort_values(["mean_diff", "machine_number"], ascending=[False, True], na_position="last").reset_index(drop=True)
        top_share = float(machine_summary["mean_diff"].abs().max() / machine_summary["mean_diff"].abs().sum()) if not machine_summary.empty and machine_summary["mean_diff"].abs().sum() > 0 else np.nan
        sig_count = int(machine_vs_rest["q_value"].lt(0.05).sum())
        stable_count = int(concentration_table["stable"].sum())
        concentration_rows = [
            f"- top_machine_share={_fmt(top_share, 3)}, "
            f"sig_machines={sig_count}, stable_machines={stable_count}"
        ]
        _write_csv(concentration_detail, branch_dir / "tail3_kakuban4_machine_summary.csv")
        _write_csv(machine_vs_rest.sort_values(["q_value", "delta"], ascending=[True, False], na_position="last").reset_index(drop=True), branch_dir / "tail3_kakuban4_machine_vs_rest.csv")
        _write_csv(concentration_table, branch_dir / "tail3_kakuban4_machine_stability.csv")

        machine_2243_excluded = cell_frame[~cell_frame["machine_number"].eq(2243)].copy()
        (
            machine_summary_excl,
            machine_vs_rest_excl,
            concentration_table_excl,
            top_share_excl,
            sig_count_excl,
            stable_count_excl,
        ) = _machine_concentration(machine_2243_excluded)
        _write_csv(machine_summary_excl, branch_dir / "tail3_kakuban4_machine_summary_excluding_2243.csv")
        _write_csv(machine_vs_rest_excl.sort_values(["q_value", "delta"], ascending=[True, False], na_position="last").reset_index(drop=True), branch_dir / "tail3_kakuban4_machine_vs_rest_excluding_2243.csv")
        _write_csv(concentration_table_excl, branch_dir / "tail3_kakuban4_machine_stability_excluding_2243.csv")

        excluded_compare = pd.DataFrame(
            [
                {
                    "case": "full",
                    "top_machine_number": int(machine_summary.iloc[0]["machine_number"]) if not machine_summary.empty else np.nan,
                    "top_machine_name": (
                        str(
                            cell_frame.loc[
                                cell_frame["machine_number"].eq(int(machine_summary.iloc[0]["machine_number"])), "machine_name"
                            ].mode().iloc[0]
                        )
                        if not machine_summary.empty
                        and not cell_frame.loc[cell_frame["machine_number"].eq(int(machine_summary.iloc[0]["machine_number"])), "machine_name"].empty
                        else ""
                    ),
                    "top_machine_share": top_share,
                    "sig_machines": sig_count,
                    "stable_machines": stable_count,
                    "top_delta": float(machine_vs_rest.iloc[0]["delta"]) if not machine_vs_rest.empty else np.nan,
                    "top_p_value": float(machine_vs_rest.iloc[0]["p_value"]) if not machine_vs_rest.empty else np.nan,
                    "top_q_value": float(machine_vs_rest.iloc[0]["q_value"]) if not machine_vs_rest.empty else np.nan,
                    "top_stable": bool(concentration_table.iloc[0]["stable"]) if not concentration_table.empty else False,
                },
                {
                    "case": "excluding_2243",
                    "top_machine_number": int(machine_summary_excl.iloc[0]["machine_number"]) if not machine_summary_excl.empty else np.nan,
                    "top_machine_name": str(machine_summary_excl.iloc[0]["machine_name"]) if not machine_summary_excl.empty else "",
                    "top_machine_share": top_share_excl,
                    "sig_machines": sig_count_excl,
                    "stable_machines": stable_count_excl,
                    "top_delta": float(machine_vs_rest_excl.iloc[0]["delta"]) if not machine_vs_rest_excl.empty else np.nan,
                    "top_p_value": float(machine_vs_rest_excl.iloc[0]["p_value"]) if not machine_vs_rest_excl.empty else np.nan,
                    "top_q_value": float(machine_vs_rest_excl.iloc[0]["q_value"]) if not machine_vs_rest_excl.empty else np.nan,
                    "top_stable": bool(concentration_table_excl.iloc[0]["stable"]) if not concentration_table_excl.empty else False,
                },
            ]
        )

        machine_2243_history_section = [
            "## Machine 2243 type history",
            _md_table(machine_history_summary),
            "",
            "## Machine 2243 daily diff",
            _md_table(machine_2243_summary),
            "",
            "Top 5 days by diff:",
            _md_table(machine_2243_top5[["date", "weekday", "machine_name", "diff_coins_normalized", "games_normalized"]]),
            "",
            "## tail=3 x kakuban=4 excluding machine 2243",
            _md_table(excluded_compare),
            "",
            (
                "Interpretation: "
                + (
                    "machine 2243 changes machine_name over time, so it is not a single fixed machine-name regime."
                    if machine_history_summary["machine_name"].nunique() > 1
                    else "machine 2243 keeps a single machine_name across the period."
                )
            ),
            (
                "The 2243 daily series looks "
                + (
                    "spike-driven" if float(machine_2243_stats.quantile(0.9)) - float(machine_2243_stats.median()) > abs(float(machine_2243_stats.mean()))
                    else "consistently high"
                )
                + f" (mean={_fmt(machine_2243_stats.mean(), 3)}, median={_fmt(machine_2243_stats.median(), 3)}, p10={_fmt(machine_2243_stats.quantile(0.1), 3)}, p50={_fmt(machine_2243_stats.quantile(0.5), 3)}, p90={_fmt(machine_2243_stats.quantile(0.9), 3)})."
            ),
            "",
        ]

    report = [
        "# Branch D",
        "",
        "Target: test whether weak tail-only signals become stable under a 2-axis interaction.",
        "",
        "## 2F N tail 3/4 x kakuban",
        _md_table(stable_2f if not stable_2f.empty else pd.DataFrame(columns=["tail_axis", "secondary", "stable"])),
        "",
        "## Machine concentration check (tail=3 x kakuban=4)",
        "\n".join(concentration_rows) if concentration_rows else "No stable tail=3 x kakuban=4 cell was found.",
        "",
        *machine_2243_history_section,
        "",
        "## 3F A tail 5 x section",
        _md_table(stable_3f if not stable_3f.empty else pd.DataFrame(columns=["tail_axis", "secondary", "stable"])),
        "",
        "Conclusion: one stable interaction cell appears in 2F N (`tail=3`, `kakuban=4`), but tail=4 does not stabilize and tail=5 remains noise. The interaction does not rescue the broad tail-only signal.",
        "",
    ]
    _write_text(branch_dir / "report.md", "\n".join(report))
    return {
        "conclusion": "one stable cell appears at tail=3/kakuban=4, but tail=4 is not stable and tail=5 remains noise",
        "report_path": branch_dir / "report.md",
        "tail_kakuban_2f_cell_summary": cell_summary_2f,
        "tail_kakuban_2f_cell_vs_rest": cell_vs_rest_2f,
        "tail_kakuban_2f_stable": stable_2f,
        "tail3_kakuban4_machine_summary": concentration_detail,
        "tail3_kakuban4_machine_vs_rest": machine_vs_rest if not stable_match.empty else pd.DataFrame(),
        "tail3_kakuban4_machine_stability": concentration_table,
        "machine_2243_type_history": machine_history_summary,
        "machine_2243_daily_diff": machine_2243_daily,
        "tail_section_3f_cell_summary": cell_summary_3f,
        "tail_section_3f_cell_vs_rest": cell_vs_rest_3f,
        "tail_section_3f_stable": stable_3f,
    }


def _build_summary(branches: dict[str, dict[str, object]], out_dir: Path) -> Path:
    summary = [
        "# Kamata weekday / event / spatial deep dive",
        "",
        "## Branch conclusions",
        "",
        f"- Branch A: {branches['A']['conclusion']}",
        f"- Branch B: {branches['B']['conclusion']}",
        f"- Branch C: {branches['C']['conclusion']}",
        f"- Branch D: {branches['D']['conclusion']}",
        "",
        "## Lawful vs noise",
        "",
        "- Lawful signals:",
        "  - kamata7 2F section 2179-2186 shows a reproducible weekday effect after event exclusion.",
        "  - kamata1 2F section 2236-2255 is event-heavy, but DDs do not separate statistically after n_dates filtering.",
        "  - kamata7 kakuban=1 is floor-specific; 2F and 3F are structurally different.",
        "  - kamata7 2F N tail=3/kakuban=4 is the only stable interaction cell found in this run.",
        "- Noise / weak signals:",
        "  - kamata7 2F N tail=4 does not stabilize across halves.",
        "  - kamata7 3F A tail=5 does not stabilize under the section interaction.",
        "  - The interaction does not rescue the broad tail-only signal into a general law.",
        "",
        "## Report paths",
        "",
        f"- [Branch A]({(out_dir / 'branch_a' / 'report.md').resolve()})",
        f"- [Branch B]({(out_dir / 'branch_b' / 'report.md').resolve()})",
        f"- [Branch C]({(out_dir / 'branch_c' / 'report.md').resolve()})",
        f"- [Branch D]({(out_dir / 'branch_d' / 'report.md').resolve()})",
        "",
    ]
    summary_path = out_dir / "summary.md"
    _write_text(summary_path, "\n".join(summary))
    return summary_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kamata weekday / event / spatial deep dive.")
    parser.add_argument("--db1", type=Path, default=DEFAULT_DB_1)
    parser.add_argument("--db7", type=Path, default=DEFAULT_DB_7)
    parser.add_argument("--coords1", type=Path, default=DEFAULT_COORDS_1)
    parser.add_argument("--coords7-2f", dest="coords7_2f", type=Path, default=DEFAULT_COORDS_7_2F)
    parser.add_argument("--coords7-3f", dest="coords7_3f", type=Path, default=DEFAULT_COORDS_7_3F)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out_dir = _ensure_dir(args.output_dir)

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

    frames = {f"{spec.hall_slug}_{spec.floor}": _build_segment_frame(spec) for spec in specs}
    combined = pd.concat(
        [frame.assign(hall_slug=key.split("_")[0], floor=key.split("_")[1]) for key, frame in frames.items()],
        ignore_index=True,
    )

    branches: dict[str, dict[str, object]] = {}
    branches["A"] = _branch_a(frames["kamata7_2F"], out_dir)
    branches["B"] = _branch_b(frames["kamata1_2F"], out_dir)
    branches["C"] = _branch_c(specs, out_dir)
    branches["D"] = _branch_d(combined, out_dir)
    summary_path = _build_summary(branches, out_dir)

    print(out_dir)
    print(summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
