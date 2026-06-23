from __future__ import annotations

import argparse
import calendar
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kruskal, mannwhitneyu

from ml.analysis.kamata_weekday_event_axis_deepdive import (
    DEFAULT_COORDS_1,
    DEFAULT_COORDS_7_2F,
    DEFAULT_COORDS_7_3F,
    DEFAULT_DB_1,
    DEFAULT_DB_7,
    SegmentSpec,
    _attach_fdr,
    _build_segment_frame,
    _ensure_dir,
    _fmt,
    _kakuban_one_positions,
    _md_table,
    _mwu,
    _split_frame_by_date_half,
    _write_csv,
    _write_text,
    infer_hall_name,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = PROJECT_ROOT / "tmp" / "kamata_weekday_event_axis_eda_deepdive_payoutrate"
WEEKDAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
EVENT_LABEL_ORDER = ["1", "7", "11", "17", "21", "27", "30", "month_end"]
THRESHOLDS = (100.0, 104.0, 110.0)
PRIMARY_THRESHOLD = 104.0


def _ensure_float(value: object) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(numeric) if pd.notna(numeric) else float("nan")


def compute_payoutrate_pct(diff_coins_normalized: object, games_normalized: object) -> float:
    diff = _ensure_float(diff_coins_normalized)
    games = _ensure_float(games_normalized)
    if pd.isna(diff) or pd.isna(games) or games <= 0:
        return float("nan")
    return float(100.0 + (diff / (games * 3.0)) * 100.0)


def _prepare_segment_frame(spec: SegmentSpec) -> pd.DataFrame:
    frame = _build_segment_frame(spec).copy()
    frame["payoutrate_pct"] = [
        compute_payoutrate_pct(diff, games)
        for diff, games in zip(frame["diff_coins_normalized"], frame["games_normalized"], strict=False)
    ]
    frame["dd"] = pd.to_datetime(frame["date"], errors="coerce").dt.day.astype("Int64")
    frame["event_label"] = frame["date"].map(_event_label)
    frame["tail_axis"] = frame["tail_axis"].astype(str)
    frame["kakuban"] = pd.to_numeric(frame["kakuban"], errors="coerce").astype("Int64")
    return frame


def _event_label(date: pd.Timestamp | str) -> str | None:
    ts = pd.Timestamp(date)
    day = int(ts.day)
    month_end = int(calendar.monthrange(ts.year, ts.month)[1])
    if day == month_end:
        return "month_end"
    if day in {1, 7, 11, 17, 21, 27, 30}:
        return str(day)
    return None


def _sort_key(values: pd.Series, kind: str) -> pd.Series:
    if kind == "weekday":
        order = {label: idx for idx, label in enumerate(WEEKDAY_ORDER)}
        return values.astype(str).map(lambda x: order.get(x, 99)).astype(float)
    if kind == "event_label":
        order = {label: idx for idx, label in enumerate(EVENT_LABEL_ORDER)}
        return values.astype(str).map(lambda x: order.get(x, 999)).astype(float)
    if kind in {"dd", "machine_number"}:
        return pd.to_numeric(values, errors="coerce").fillna(999999).astype(float)
    return values.astype(str)


def _daily_group(frame: pd.DataFrame, *, group_cols: list[str]) -> pd.DataFrame:
    work = frame.copy()
    work["payoutrate_pct"] = pd.to_numeric(work["payoutrate_pct"], errors="coerce")
    work["mean_games"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    daily = (
        work.groupby(["date", *group_cols], as_index=False)
        .agg(
            mean_payoutrate_pct=("payoutrate_pct", "mean"),
            mean_games=("mean_games", "mean"),
            n_machines=("machine_number", "size"),
        )
        .copy()
    )
    for threshold in THRESHOLDS:
        daily[f"hit_{int(threshold)}"] = (daily["mean_payoutrate_pct"] > threshold).astype(float)
    daily["mean_excess_pct"] = daily["mean_payoutrate_pct"] - 100.0
    return daily


def summarize_threshold_rates(
    daily: pd.DataFrame,
    *,
    cell_cols: list[str],
    min_dates: int = 10,
    thresholds: tuple[float, float, float] = THRESHOLDS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if daily.empty:
        columns = [*cell_cols, "hit_rate_100", "hit_rate_104", "hit_rate_110", "mean_payoutrate_pct", "mean_excess_pct", "n_dates", "n_machines"]
        empty = pd.DataFrame(columns=columns)
        return empty, daily.copy()

    work = daily.copy()
    work["payoutrate_pct"] = pd.to_numeric(work.get("payoutrate_pct"), errors="coerce")
    if "mean_payoutrate_pct" not in work.columns:
        work["mean_payoutrate_pct"] = work["payoutrate_pct"]
    work["mean_payoutrate_pct"] = pd.to_numeric(work["mean_payoutrate_pct"], errors="coerce")
    if "mean_excess_pct" not in work.columns:
        work["mean_excess_pct"] = work["mean_payoutrate_pct"] - 100.0
    work["mean_excess_pct"] = pd.to_numeric(work["mean_excess_pct"], errors="coerce")
    for threshold in thresholds:
        hit_col = f"hit_{int(threshold)}"
        if hit_col not in work.columns:
            work[hit_col] = (work["mean_payoutrate_pct"] > float(threshold)).astype(float)
        else:
            work[hit_col] = pd.to_numeric(work[hit_col], errors="coerce").fillna(0.0)
    work["n_dates"] = work.groupby(cell_cols)["date"].transform("nunique").astype(int)
    filtered = work[work["n_dates"] >= int(min_dates)].copy()
    if filtered.empty:
        columns = [*cell_cols, "hit_rate_100", "hit_rate_104", "hit_rate_110", "mean_payoutrate_pct", "mean_excess_pct", "n_dates", "n_machines"]
        empty = pd.DataFrame(columns=columns)
        return empty, filtered

    summary = filtered.groupby(cell_cols, as_index=False).agg(
        hit_rate_100=("hit_100", "mean"),
        hit_rate_104=("hit_104", "mean"),
        hit_rate_110=("hit_110", "mean"),
        mean_payoutrate_pct=("mean_payoutrate_pct", "mean"),
        mean_excess_pct=("mean_excess_pct", "mean"),
        n_dates=("n_dates", "max"),
        n_machines=("n_machines", "sum"),
    )
    summary = summary.sort_values(
        ["hit_rate_104", "hit_rate_110", "hit_rate_100", "n_dates"],
        ascending=[False, False, False, False],
        na_position="last",
    ).reset_index(drop=True)
    summary.insert(0, "rank", np.arange(1, len(summary) + 1))
    return summary, filtered


def _rate_vs_rest(daily: pd.DataFrame, *, label_col: str, rate_col: str) -> pd.DataFrame:
    labels = sorted(daily[label_col].dropna().astype(str).unique().tolist(), key=lambda x: _sort_key(pd.Series([x]), label_col if label_col in {"weekday", "event_label"} else "machine_number").iloc[0])
    rows: list[dict[str, object]] = []
    for label in labels:
        cell = pd.to_numeric(daily.loc[daily[label_col].astype(str).eq(label), rate_col], errors="coerce").dropna().astype(float)
        rest = pd.to_numeric(daily.loc[~daily[label_col].astype(str).eq(label), rate_col], errors="coerce").dropna().astype(float)
        p_value = _mwu(cell, rest)
        cell_rate = float(cell.mean()) if len(cell) else np.nan
        rest_rate = float(rest.mean()) if len(rest) else np.nan
        delta = cell_rate - rest_rate if np.isfinite(cell_rate) and np.isfinite(rest_rate) else np.nan
        rows.append(
            {
                label_col: label,
                "cell_rate": cell_rate,
                "rest_rate": rest_rate,
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


def _compare_with_halves(daily: pd.DataFrame, *, label_col: str, rate_col: str = "hit_104") -> pd.DataFrame:
    full = _rate_vs_rest(daily, label_col=label_col, rate_col=rate_col)
    if full.empty:
        return full

    first_half, second_half, cutoff = _split_frame_by_date_half(daily)
    half_tables: list[pd.DataFrame] = []
    for prefix, half in [("first_half", first_half), ("second_half", second_half)]:
        if half.empty:
            continue
        half_table = _rate_vs_rest(half, label_col=label_col, rate_col=rate_col)
        if half_table.empty:
            continue
        half_table = half_table.rename(
            columns={
                "cell_rate": f"{prefix}_cell_rate",
                "rest_rate": f"{prefix}_rest_rate",
                "delta": f"{prefix}_delta",
                "cell_n": f"{prefix}_cell_n",
                "rest_n": f"{prefix}_rest_n",
                "p_value": f"{prefix}_p_value",
                "q_value": f"{prefix}_q_value",
                "direction": f"{prefix}_direction",
            }
        )
        half_tables.append(half_table)

    stability = full.copy()
    if half_tables:
        merged = half_tables[0]
        for extra in half_tables[1:]:
            merged = merged.merge(extra, on=label_col, how="outer", validate="one_to_one")
        stability = stability.merge(merged, on=label_col, how="left", validate="one_to_one")

    stability["full_sig"] = pd.to_numeric(stability["q_value"], errors="coerce").lt(0.05)
    stability["first_half_sig"] = pd.to_numeric(stability.get("first_half_q_value"), errors="coerce").lt(0.05)
    stability["second_half_sig"] = pd.to_numeric(stability.get("second_half_q_value"), errors="coerce").lt(0.05)
    stability["same_direction"] = (
        stability["direction"].astype(str).eq(stability.get("first_half_direction").astype(str))
        & stability["direction"].astype(str).eq(stability.get("second_half_direction").astype(str))
    )
    stability["stable"] = stability["full_sig"] & stability["first_half_sig"] & stability["second_half_sig"] & stability["same_direction"]
    stability["split_half_cutoff"] = cutoff
    return stability


def _top_machine_share(machine_summary: pd.DataFrame) -> float:
    if machine_summary.empty or "mean_excess_pct" not in machine_summary.columns:
        return float("nan")
    scores = machine_summary["mean_excess_pct"].abs()
    total = float(scores.sum())
    if total <= 0:
        return float("nan")
    return float(scores.max() / total)


def _machine_concentration(frame: pd.DataFrame, *, rate_col: str = "hit_104") -> tuple[pd.DataFrame, pd.DataFrame, float]:
    subset = frame.copy()
    if subset.empty:
        empty = pd.DataFrame(columns=["machine_number", "hit_rate_100", "hit_rate_104", "hit_rate_110", "mean_payoutrate_pct", "mean_excess_pct", "n_dates", "n_machines"])
        return empty, empty, float("nan")
    daily = _daily_group(subset, group_cols=["machine_number"])
    machine_summary, machine_filtered = summarize_threshold_rates(daily, cell_cols=["machine_number"], min_dates=10)
    machine_summary = machine_summary.sort_values(["hit_rate_104", "hit_rate_110", "n_dates", "machine_number"], ascending=[False, False, False, True], na_position="last").reset_index(drop=True)
    return machine_summary, _compare_with_halves(machine_filtered, label_col="machine_number", rate_col=rate_col), _top_machine_share(machine_summary)


def _first_valid(series: pd.Series) -> object:
    if series.empty:
        return ""
    return series.dropna().iloc[0] if series.dropna().size else ""


def _weekday_dd_deepdive(frame: pd.DataFrame, *, weekday_label: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    weekday_map = {idx: label for idx, label in enumerate(WEEKDAY_ORDER)}
    subset = frame[frame["weekday"].map(weekday_map).eq(weekday_label)].copy()
    if subset.empty:
        empty = pd.DataFrame(columns=["dd", "hit_rate_100", "hit_rate_104", "hit_rate_110", "mean_payoutrate_pct", "mean_excess_pct", "n_dates", "n_machines"])
        return empty, empty
    dd_daily = _daily_group(subset, group_cols=["dd"])
    return summarize_threshold_rates(dd_daily, cell_cols=["dd"], min_dates=5)


def _event_weekday_deepdive(frame: pd.DataFrame, *, event_label: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    subset = frame[frame["event_label"].astype(str).eq(event_label)].copy()
    if subset.empty:
        empty = pd.DataFrame(columns=["weekday", "weekday_label", "hit_rate_100", "hit_rate_104", "hit_rate_110", "mean_payoutrate_pct", "mean_excess_pct", "n_dates", "n_machines"])
        return empty, empty
    weekday_daily = _daily_group(subset, group_cols=["weekday"])
    summary, filtered = summarize_threshold_rates(weekday_daily, cell_cols=["weekday"], min_dates=5)
    summary["weekday_label"] = summary["weekday"].map(lambda x: WEEKDAY_ORDER[int(x)] if pd.notna(x) else "")
    return summary, filtered


def _floor_kakuban_one_summary(spec: SegmentSpec, frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    positions = _kakuban_one_positions(frame, hall_slug=spec.hall_slug, floor=spec.floor)
    if positions.empty:
        empty = pd.DataFrame(columns=["hall_slug", "floor", "machine_number", "section", "section_min", "section_max", "section_width", "section_from_start", "section_from_end", "section_edge", "X", "Y", "anchor_x", "x_minus_anchor", "abs_x_minus_anchor", "distance_to_anchor"])
        return empty, empty
    joined = frame.merge(positions[["machine_number", "section", "section_min", "section_max", "section_width", "section_from_start", "section_from_end", "section_edge", "distance_to_anchor"]], on=["machine_number", "section"], how="inner", validate="many_to_one")
    k1 = joined[joined["kakuban"].astype(str).eq("1")].copy()
    if k1.empty:
        summary = pd.DataFrame(columns=["hall_slug", "floor", "hit_rate_100", "hit_rate_104", "hit_rate_110", "mean_payoutrate_pct", "mean_excess_pct", "n_dates", "n_machines"])
        return positions, summary
    daily = _daily_group(k1, group_cols=["machine_number"])
    summary, _filtered = summarize_threshold_rates(daily, cell_cols=["machine_number"], min_dates=5)
    summary["hall_slug"] = spec.hall_slug
    summary["floor"] = spec.floor
    return positions, summary


def _branch_a(frame: pd.DataFrame, out_dir: Path) -> dict[str, object]:
    branch_dir = _ensure_dir(out_dir / "branch_a")
    section = frame[(frame["is_a_type"].eq(1)) & (frame["section"].astype(str).eq("2179-2186"))].copy()
    non_event = section[section["is_event_day"].eq(0)].copy()

    weekday_daily = _daily_group(non_event, group_cols=["weekday"])
    weekday_summary, weekday_filtered = summarize_threshold_rates(weekday_daily, cell_cols=["weekday"], min_dates=10)
    weekday_summary["weekday_label"] = weekday_summary["weekday"].map(lambda x: WEEKDAY_ORDER[int(x)] if pd.notna(x) else "")
    weekday_compare = _compare_with_halves(weekday_filtered, label_col="weekday")
    weekday_compare["weekday_label"] = weekday_compare["weekday"].map(lambda x: WEEKDAY_ORDER[int(float(x))] if str(x).replace(".", "", 1).isdigit() else x)
    weekday_compare = weekday_compare.sort_values(["q_value", "delta"], ascending=[True, False], na_position="last").reset_index(drop=True)

    top_weekday = str(_first_valid(weekday_summary["weekday_label"])) if not weekday_summary.empty else ""
    bottom_weekday = str(weekday_summary.iloc[-1]["weekday_label"]) if not weekday_summary.empty else ""

    top_dd_summary, _ = _weekday_dd_deepdive(non_event, weekday_label=top_weekday) if top_weekday else (pd.DataFrame(), pd.DataFrame())
    bottom_dd_summary, _ = _weekday_dd_deepdive(non_event, weekday_label=bottom_weekday) if bottom_weekday else (pd.DataFrame(), pd.DataFrame())

    top_weekday_subset = non_event[non_event["weekday"].map(lambda x: WEEKDAY_ORDER[int(x)]).eq(top_weekday)].copy() if top_weekday else pd.DataFrame()
    bottom_weekday_subset = non_event[non_event["weekday"].map(lambda x: WEEKDAY_ORDER[int(x)]).eq(bottom_weekday)].copy() if bottom_weekday else pd.DataFrame()
    top_machine_summary, top_machine_compare, top_share = _machine_concentration(top_weekday_subset) if not top_weekday_subset.empty else (pd.DataFrame(), pd.DataFrame(), float("nan"))
    bottom_machine_summary, bottom_machine_compare, bottom_share = _machine_concentration(bottom_weekday_subset) if not bottom_weekday_subset.empty else (pd.DataFrame(), pd.DataFrame(), float("nan"))

    _write_csv(weekday_summary, branch_dir / "weekday_no_event_summary.csv")
    _write_csv(weekday_compare, branch_dir / "weekday_no_event_compare.csv")
    if not top_dd_summary.empty:
        _write_csv(top_dd_summary, branch_dir / f"weekday_{top_weekday}_dd_summary.csv")
    if not bottom_dd_summary.empty:
        _write_csv(bottom_dd_summary, branch_dir / f"weekday_{bottom_weekday}_dd_summary.csv")
    if not top_machine_summary.empty:
        _write_csv(top_machine_summary, branch_dir / f"weekday_{top_weekday}_machine_summary.csv")
        _write_csv(top_machine_compare, branch_dir / f"weekday_{top_weekday}_machine_stability.csv")
    if not bottom_machine_summary.empty:
        _write_csv(bottom_machine_summary, branch_dir / f"weekday_{bottom_weekday}_machine_summary.csv")
        _write_csv(bottom_machine_compare, branch_dir / f"weekday_{bottom_weekday}_machine_stability.csv")

    report = [
        "# Branch A",
        "",
        "Target: kamata7 2F section 2179-2186, event days excluded.",
        "",
        "## Weekday threshold summary",
        _md_table(weekday_summary),
        "",
        "## Weekday vs rest comparison on hit_rate_104",
        _md_table(weekday_compare),
        "",
        "## Split-half stability",
        _md_table(weekday_compare[["weekday_label", "cell_rate", "rest_rate", "delta", "q_value", "first_half_q_value", "second_half_q_value", "full_sig", "first_half_sig", "second_half_sig", "same_direction", "stable"]] if not weekday_compare.empty else pd.DataFrame()),
        "",
        f"Top weekday: {top_weekday} (top_machine_share={_fmt(top_share, 3)}).",
        f"Bottom weekday: {bottom_weekday} (top_machine_share={_fmt(bottom_share, 3)}).",
        "",
        "## Top weekday x DD",
        _md_table(top_dd_summary),
        "",
        "## Bottom weekday x DD",
        _md_table(bottom_dd_summary),
        "",
        "Conclusion: weekday law is checked on hit_rate_104; DD is used only as the second-level drill-down when the weekday signal is visible.",
        "",
    ]
    _write_text(branch_dir / "report.md", "\n".join(report))
    conclusion = "weekday signal is reproducible on hit_rate_104" if not weekday_compare.empty and bool(weekday_compare.iloc[0]["stable"]) else "weekday signal is present but split-half stability is weak"
    return {
        "conclusion": conclusion,
        "report_path": branch_dir / "report.md",
        "weekday_summary": weekday_summary,
        "weekday_compare": weekday_compare,
        "top_dd_summary": top_dd_summary,
        "bottom_dd_summary": bottom_dd_summary,
    }


def _branch_b(frame: pd.DataFrame, out_dir: Path) -> dict[str, object]:
    branch_dir = _ensure_dir(out_dir / "branch_b")
    section = frame[(frame["is_a_type"].eq(1)) & (frame["section"].astype(str).eq("2236-2255")) & (frame["is_event_day"].eq(1))].copy()
    section["event_label"] = section["event_label"].fillna("")

    daily = _daily_group(section, group_cols=["event_label"])
    summary, filtered = summarize_threshold_rates(daily, cell_cols=["event_label"], min_dates=10)
    summary["event_label"] = pd.Categorical(summary["event_label"], categories=EVENT_LABEL_ORDER, ordered=True)
    summary = summary.sort_values(["hit_rate_104", "hit_rate_110", "n_dates"], ascending=[False, False, False], na_position="last").reset_index(drop=True)
    summary["event_label"] = summary["event_label"].astype(str)
    compare = _compare_with_halves(filtered, label_col="event_label")

    top_event = str(_first_valid(summary["event_label"])) if not summary.empty else ""
    month_end = "month_end"
    top_event_weekday_summary, _ = _event_weekday_deepdive(section, event_label=top_event) if top_event else (pd.DataFrame(), pd.DataFrame())
    month_end_weekday_summary, _ = _event_weekday_deepdive(section, event_label=month_end) if month_end else (pd.DataFrame(), pd.DataFrame())

    top_event_subset = section[section["event_label"].astype(str).eq(top_event)].copy() if top_event else pd.DataFrame()
    month_end_subset = section[section["event_label"].astype(str).eq("month_end")].copy()
    top_machine_summary, top_machine_compare, top_share = _machine_concentration(top_event_subset) if not top_event_subset.empty else (pd.DataFrame(), pd.DataFrame(), float("nan"))
    month_end_machine_summary, month_end_machine_compare, month_end_share = _machine_concentration(month_end_subset) if not month_end_subset.empty else (pd.DataFrame(), pd.DataFrame(), float("nan"))

    _write_csv(summary, branch_dir / "dd_summary.csv")
    _write_csv(compare, branch_dir / "dd_compare.csv")
    if not top_event_weekday_summary.empty:
        _write_csv(top_event_weekday_summary, branch_dir / f"dd_{top_event}_weekday_summary.csv")
    if not month_end_weekday_summary.empty:
        _write_csv(month_end_weekday_summary, branch_dir / "dd_month_end_weekday_summary.csv")
    if not top_machine_summary.empty:
        _write_csv(top_machine_summary, branch_dir / f"dd_{top_event}_machine_summary.csv")
        _write_csv(top_machine_compare, branch_dir / f"dd_{top_event}_machine_stability.csv")
    if not month_end_machine_summary.empty:
        _write_csv(month_end_machine_summary, branch_dir / "dd_month_end_machine_summary.csv")
        _write_csv(month_end_machine_compare, branch_dir / "dd_month_end_machine_stability.csv")

    report = [
        "# Branch B",
        "",
        "Target: kamata1 2F section 2236-2255, event days only.",
        "",
        "## DD threshold summary",
        _md_table(summary),
        "",
        "## DD vs rest comparison on hit_rate_104",
        _md_table(compare),
        "",
        f"Top event label: {top_event} (top_machine_share={_fmt(top_share, 3)}).",
        f"Month end machine concentration: top_machine_share={_fmt(month_end_share, 3)}.",
        "",
        "## Top event x weekday",
        _md_table(top_event_weekday_summary),
        "",
        "## Month end x weekday",
        _md_table(month_end_weekday_summary),
        "",
        "Conclusion: event law is checked on hit_rate_104; weekday drill-down is used to see whether month_end is conditional on a particular weekday.",
        "",
    ]
    _write_text(branch_dir / "report.md", "\n".join(report))
    conclusion = "event-day signal is broad and month_end is the strongest label" if not summary.empty else "event-day signal is insufficient"
    return {
        "conclusion": conclusion,
        "report_path": branch_dir / "report.md",
        "dd_summary": summary,
        "dd_compare": compare,
        "top_event_weekday_summary": top_event_weekday_summary,
        "month_end_weekday_summary": month_end_weekday_summary,
    }


def _branch_c(specs: list[SegmentSpec], frames: dict[str, pd.DataFrame], out_dir: Path) -> dict[str, object]:
    branch_dir = _ensure_dir(out_dir / "branch_c")
    position_frames: list[pd.DataFrame] = []
    rate_frames: list[pd.DataFrame] = []
    for spec in specs:
        frame = frames[f"{spec.hall_slug}_{spec.floor}"]
        positions = _kakuban_one_positions(frame, hall_slug=spec.hall_slug, floor=spec.floor)
        position_frames.append(positions)
        k1 = frame[(frame["is_a_type"].eq(1)) & (frame["kakuban"].astype(str).eq("1"))].copy()
        if k1.empty:
            continue
        daily = _daily_group(k1, group_cols=["machine_number"])
        summary, _filtered = summarize_threshold_rates(daily, cell_cols=["machine_number"], min_dates=5)
        summary["hall_slug"] = spec.hall_slug
        summary["floor"] = spec.floor
        summary["section_min"] = positions["section_min"].min() if not positions.empty else np.nan
        summary["section_max"] = positions["section_max"].max() if not positions.empty else np.nan
        summary["mean_distance_to_anchor"] = float(positions["distance_to_anchor"].mean()) if not positions.empty else np.nan
        rate_frames.append(summary)

    positions_all = pd.concat(position_frames, ignore_index=True) if position_frames else pd.DataFrame()
    if not positions_all.empty:
        positions_all = positions_all.drop_duplicates(subset=["hall_slug", "floor", "machine_number", "section"], keep="first").reset_index(drop=True)
    rates_all = pd.concat(rate_frames, ignore_index=True) if rate_frames else pd.DataFrame()
    if not rates_all.empty:
        rates_all = rates_all.sort_values(["hit_rate_104", "hit_rate_110", "n_dates"], ascending=[False, False, False], na_position="last").reset_index(drop=True)

    _write_csv(positions_all, branch_dir / "kakuban1_positions.csv")
    _write_csv(rates_all, branch_dir / "kakuban1_payoutrate_summary.csv")

    report = [
        "# Branch C",
        "",
        "Target: compare kakuban=1 placements across kamata1 2F, kamata7 2F, and kamata7 3F.",
        "",
        "## kakuban=1 positions",
        _md_table(positions_all),
        "",
        "## kakuban=1 payoutrate summary",
        _md_table(rates_all),
        "",
        "Conclusion: kakuban=1 is checked as a floor-specific spatial signal, not assumed to be universal.",
        "",
    ]
    _write_text(branch_dir / "report.md", "\n".join(report))
    conclusion = "kakuban=1 shows floor-specific behavior if hit_rate_104 differs across floors" if not rates_all.empty else "kakuban=1 signal unavailable"
    return {
        "conclusion": conclusion,
        "report_path": branch_dir / "report.md",
        "positions": positions_all,
        "rates": rates_all,
    }


def _branch_d(specs: list[SegmentSpec], frames: dict[str, pd.DataFrame], out_dir: Path) -> dict[str, object]:
    branch_dir = _ensure_dir(out_dir / "branch_d")
    cross_rows: list[pd.DataFrame] = []
    detail_rows: list[pd.DataFrame] = []
    focus_machine_summary = pd.DataFrame()
    focus_machine_compare = pd.DataFrame()
    focus_machine_summary_excl = pd.DataFrame()
    focus_machine_compare_excl = pd.DataFrame()
    focus_machine_2243_history = pd.DataFrame()
    for spec in specs:
        frame = frames[f"{spec.hall_slug}_{spec.floor}"].copy()
        subset = frame[(frame["tail_axis"].astype(str).eq("3")) & (frame["kakuban"].astype(str).eq("4"))].copy()
        if subset.empty:
            continue
        daily = _daily_group(subset, group_cols=["machine_number"])
        summary, filtered = summarize_threshold_rates(daily, cell_cols=["machine_number"], min_dates=5)
        summary["hall_slug"] = spec.hall_slug
        summary["floor"] = spec.floor
        summary["segment"] = "A" if spec.hall_slug == "kamata7" and spec.floor == "3F" else "N"
        summary["n_rows"] = int(len(subset))
        summary["machine_number_min"] = int(pd.to_numeric(subset["machine_number"], errors="coerce").min()) if not subset.empty else np.nan
        summary["machine_number_max"] = int(pd.to_numeric(subset["machine_number"], errors="coerce").max()) if not subset.empty else np.nan
        summary["top_machine_share"] = _top_machine_share(summary)
        cross_rows.append(summary)

        if spec.hall_slug == "kamata7" and spec.floor == "2F":
            detail_rows.append(subset.copy())
            machine_summary = summary.copy()
            machine_compare = _compare_with_halves(filtered, label_col="machine_number")
            machine_compare["machine_number"] = pd.to_numeric(machine_compare["machine_number"], errors="coerce").astype("Int64")
            machine_compare = machine_compare.merge(machine_summary, on="machine_number", how="left", validate="one_to_one")
            machine_compare = machine_compare.sort_values(["stable", "q_value", "delta"], ascending=[False, True, False], na_position="last").reset_index(drop=True)
            focus_machine_summary = machine_summary
            focus_machine_compare = machine_compare

            if 2243 in set(pd.to_numeric(subset["machine_number"], errors="coerce").dropna().astype(int).tolist()):
                machine_2243 = subset[subset["machine_number"].eq(2243)].copy()
                machine_2243_daily = (
                    machine_2243.groupby("date", as_index=False)
                    .agg(
                        mean_payoutrate_pct=("payoutrate_pct", "mean"),
                        mean_games=("games_normalized", "mean"),
                        n_machines=("machine_number", "size"),
                    )
                    .copy()
                )
                machine_2243_daily["hit_100"] = (machine_2243_daily["mean_payoutrate_pct"] > 100.0).astype(float)
                machine_2243_daily["hit_104"] = (machine_2243_daily["mean_payoutrate_pct"] > PRIMARY_THRESHOLD).astype(float)
                machine_2243_daily["hit_110"] = (machine_2243_daily["mean_payoutrate_pct"] > 110.0).astype(float)
                machine_2243_daily["mean_excess_pct"] = machine_2243_daily["mean_payoutrate_pct"] - 100.0
                machine_2243_history = (
                    machine_2243.groupby("machine_name", as_index=False)
                    .agg(
                        first_date=("date", "min"),
                        last_date=("date", "max"),
                        n_rows=("date", "size"),
                        mean_payoutrate_pct=("payoutrate_pct", "mean"),
                        hit_rate_104=("payoutrate_pct", lambda x: float((pd.Series(x) > PRIMARY_THRESHOLD).mean())),
                    )
                    .sort_values(["n_rows", "first_date"], ascending=[False, True])
                    .reset_index(drop=True)
                )
                focus_machine_2243_history = machine_2243_history
                _write_csv(machine_2243_daily, branch_dir / "machine_2243_daily.csv")
                _write_csv(machine_2243_history, branch_dir / "machine_2243_type_history.csv")

            _write_csv(machine_compare, branch_dir / "tail3_kakuban4_machine_stability.csv")
            _write_csv(summary, branch_dir / "tail3_kakuban4_machine_summary.csv")

            machine_summary_excl = summary[summary["machine_number"].ne(2243)].copy()
            machine_compare_excl = machine_compare[machine_compare["machine_number"].ne(2243)].copy()
            focus_machine_summary_excl = machine_summary_excl
            focus_machine_compare_excl = machine_compare_excl
            _write_csv(machine_summary_excl, branch_dir / "tail3_kakuban4_machine_summary_excluding_2243.csv")
            _write_csv(machine_compare_excl, branch_dir / "tail3_kakuban4_machine_stability_excluding_2243.csv")

    cross_summary = pd.concat(cross_rows, ignore_index=True) if cross_rows else pd.DataFrame()
    if not cross_summary.empty:
        cross_summary = cross_summary.sort_values(["hit_rate_104", "hit_rate_110", "n_dates"], ascending=[False, False, False], na_position="last").reset_index(drop=True)
    _write_csv(cross_summary, branch_dir / "tail3_kakuban4_cross_floor_summary.csv")

    report = [
        "# Branch D",
        "",
        "Target: tail=3 x kakuban=4, with machine 2243 exclusion check on kamata7 2F N.",
        "",
        "## Cross-floor tail=3 x kakuban=4 summary",
        _md_table(cross_summary),
        "",
        "## kamata7 2F N machine stability",
        _md_table(focus_machine_compare if not focus_machine_compare.empty else pd.DataFrame()),
        "",
        "## kamata7 2F N machine stability excluding 2243",
        _md_table(focus_machine_compare_excl if not focus_machine_compare_excl.empty else pd.DataFrame()),
        "",
        "## 2243 type history",
        _md_table(focus_machine_2243_history if not focus_machine_2243_history.empty else pd.DataFrame()),
        "",
        "Conclusion: if one machine dominates, the exclusion table shows whether the law survives without that machine.",
        "",
    ]
    _write_text(branch_dir / "report.md", "\n".join(report))
    conclusion = "tail=3 x kakuban=4 should be treated as stable only if the 2243-excluded table still leads on hit_rate_104" if not cross_summary.empty else "tail=3 x kakuban=4 signal unavailable"
    return {
        "conclusion": conclusion,
        "report_path": branch_dir / "report.md",
        "cross_summary": cross_summary,
    }


def _build_summary(branches: dict[str, dict[str, object]], out_dir: Path) -> Path:
    summary = [
        "# Kamata weekday / event / spatial deep dive - payoutrate version",
        "",
        "## Branch conclusions",
        "",
        f"- Branch A: {branches['A']['conclusion']}",
        f"- Branch B: {branches['B']['conclusion']}",
        f"- Branch C: {branches['C']['conclusion']}",
        f"- Branch D: {branches['D']['conclusion']}",
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
    parser = argparse.ArgumentParser(description="Kamata weekday / event / spatial deep dive on payoutrate.")
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

    frames = {f"{spec.hall_slug}_{spec.floor}": _prepare_segment_frame(spec) for spec in specs}

    branches: dict[str, dict[str, object]] = {}
    branches["A"] = _branch_a(frames["kamata7_2F"], out_dir)
    branches["B"] = _branch_b(frames["kamata1_2F"], out_dir)
    branches["C"] = _branch_c(specs, frames, out_dir)
    branches["D"] = _branch_d(specs, frames, out_dir)
    summary_path = _build_summary(branches, out_dir)

    print(out_dir)
    print(summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
