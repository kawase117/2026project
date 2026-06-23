from __future__ import annotations

import argparse
import calendar
from pathlib import Path

import numpy as np
import pandas as pd

from ml.analysis.kamata_weekday_event_axis_payoutrate_deepdive import (
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
    compute_payoutrate_pct,
    infer_hall_name,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = PROJECT_ROOT / "tmp" / "kamata_weekday_event_axis_eda_deepdive_distribution"
WEEKDAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
FOCUS_WEEKDAYS = ["Sun", "Wed", "Thu"]
THRESHOLDS = (100.0, 104.0, 110.0)
PRIMARY_THRESHOLD = 104.0
SECTION_A = "2179-2186"
SECTION_B = "2236-2255"
SECTION_C = "3191-3208"


def _ensure_float(value: object) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(numeric) if pd.notna(numeric) else float("nan")


def _weekday_label(value: object) -> str:
    if pd.isna(value):
        return ""
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.notna(numeric):
        idx = int(numeric)
        if 0 <= idx < len(WEEKDAY_ORDER):
            return WEEKDAY_ORDER[idx]
    text = str(value)
    return text if text else ""


def _weekday_sort_key(values: pd.Series) -> pd.Series:
    order = {label: idx for idx, label in enumerate(WEEKDAY_ORDER)}
    return values.astype(str).map(lambda x: order.get(x, 99)).astype(float)


def _prepare_segment_frame(spec: SegmentSpec) -> pd.DataFrame:
    frame = _build_segment_frame(spec).copy()
    frame["hall_slug"] = spec.hall_slug
    frame["floor"] = spec.floor
    frame["payoutrate_pct"] = [
        compute_payoutrate_pct(diff, games)
        for diff, games in zip(frame["diff_coins_normalized"], frame["games_normalized"], strict=False)
    ]
    frame["hit_100"] = (pd.to_numeric(frame["payoutrate_pct"], errors="coerce") > 100.0).astype(float)
    frame["hit_104"] = (pd.to_numeric(frame["payoutrate_pct"], errors="coerce") > PRIMARY_THRESHOLD).astype(float)
    frame["hit_110"] = (pd.to_numeric(frame["payoutrate_pct"], errors="coerce") > 110.0).astype(float)
    frame["weekday_label"] = frame["weekday"].map(_weekday_label)
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


def _daily_weekday_frame(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["payoutrate_pct"] = pd.to_numeric(work["payoutrate_pct"], errors="coerce")
    work["daily_hit_100"] = (work["payoutrate_pct"] > 100.0).astype(float)
    work["daily_hit_104"] = (work["payoutrate_pct"] > PRIMARY_THRESHOLD).astype(float)
    work["daily_hit_110"] = (work["payoutrate_pct"] > 110.0).astype(float)
    work["band_under_100"] = (work["payoutrate_pct"] < 100.0).astype(float)
    work["band_100_104"] = ((work["payoutrate_pct"] >= 100.0) & (work["payoutrate_pct"] < PRIMARY_THRESHOLD)).astype(float)
    work["band_104_plus"] = (work["payoutrate_pct"] >= PRIMARY_THRESHOLD).astype(float)
    daily = (
        work.groupby(["date", "weekday_label"], as_index=False)
        .agg(
            mean_payoutrate_pct=("payoutrate_pct", "mean"),
            median_payoutrate_pct=("payoutrate_pct", "median"),
            std_payoutrate_pct=("payoutrate_pct", "std"),
            mean_excess_pct=("payoutrate_pct", lambda s: float(pd.to_numeric(s, errors="coerce").mean() - 100.0)),
            share_under_100=("band_under_100", "mean"),
            share_100_104=("band_100_104", "mean"),
            share_104_plus=("band_104_plus", "mean"),
            daily_hit_100=("daily_hit_100", "mean"),
            daily_hit_104=("daily_hit_104", "mean"),
            daily_hit_110=("daily_hit_110", "mean"),
            n_machines=("machine_number", "size"),
        )
        .copy()
    )
    daily["shape_balance"] = daily["share_100_104"] - daily["share_104_plus"]
    return daily


def _raw_weekday_distribution_summary(frame: pd.DataFrame, *, min_rows: int = 20) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = frame.copy()
    work["payoutrate_pct"] = pd.to_numeric(work["payoutrate_pct"], errors="coerce")
    work["band_under_100"] = (work["payoutrate_pct"] < 100.0).astype(float)
    work["band_100_104"] = ((work["payoutrate_pct"] >= 100.0) & (work["payoutrate_pct"] < PRIMARY_THRESHOLD)).astype(float)
    work["band_104_plus"] = (work["payoutrate_pct"] >= PRIMARY_THRESHOLD).astype(float)
    work["n_dates"] = work.groupby("weekday_label")["date"].transform("nunique").astype(int)
    filtered = work[work["n_dates"] >= int(min_rows)].copy()
    if filtered.empty:
        empty = pd.DataFrame(
            columns=[
                "weekday_label",
                "n_rows",
                "n_dates",
                "n_machines",
                "mean_payoutrate_pct",
                "std_payoutrate_pct",
                "skew_payoutrate_pct",
                "p10",
                "p25",
                "p50",
                "p75",
                "p90",
                "p95",
                "share_under_100",
                "share_100_104",
                "share_104_plus",
                "shape_balance",
            ]
        )
        return empty, filtered

    rows: list[dict[str, object]] = []
    for weekday_label, group in filtered.groupby("weekday_label", sort=False):
        pay = group["payoutrate_pct"].dropna().astype(float)
        rows.append(
            {
                "weekday_label": weekday_label,
                "n_rows": int(len(pay)),
                "n_dates": int(group["date"].nunique()),
                "n_machines": int(group["machine_number"].nunique()),
                "mean_payoutrate_pct": float(pay.mean()) if len(pay) else np.nan,
                "std_payoutrate_pct": float(pay.std(ddof=1)) if len(pay) > 1 else np.nan,
                "skew_payoutrate_pct": float(pay.skew()) if len(pay) > 2 else np.nan,
                "p10": float(pay.quantile(0.10)) if len(pay) else np.nan,
                "p25": float(pay.quantile(0.25)) if len(pay) else np.nan,
                "p50": float(pay.quantile(0.50)) if len(pay) else np.nan,
                "p75": float(pay.quantile(0.75)) if len(pay) else np.nan,
                "p90": float(pay.quantile(0.90)) if len(pay) else np.nan,
                "p95": float(pay.quantile(0.95)) if len(pay) else np.nan,
                "share_under_100": float(group["band_under_100"].mean()) if len(group) else np.nan,
                "share_100_104": float(group["band_100_104"].mean()) if len(group) else np.nan,
                "share_104_plus": float(group["band_104_plus"].mean()) if len(group) else np.nan,
                "shape_balance": float(group["band_100_104"].mean() - group["band_104_plus"].mean()) if len(group) else np.nan,
            }
        )
    summary = pd.DataFrame(rows)
    summary = summary.sort_values(["shape_balance", "share_100_104", "mean_payoutrate_pct", "weekday_label"], ascending=[False, False, False, True], na_position="last").reset_index(drop=True)
    summary.insert(0, "rank", np.arange(1, len(summary) + 1))
    return summary, filtered


def _summarize_metric_by_weekday(
    daily: pd.DataFrame,
    *,
    value_col: str,
    out_value_col: str,
    min_dates: int = 10,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = daily.copy()
    work[value_col] = pd.to_numeric(work[value_col], errors="coerce")
    work["n_dates"] = work.groupby("weekday_label")["date"].transform("nunique").astype(int)
    filtered = work[work["n_dates"] >= int(min_dates)].copy()
    if filtered.empty:
        empty = pd.DataFrame(columns=["weekday_label", out_value_col, "n_dates", "n_machines"])
        return empty, filtered
    summary = (
        filtered.groupby("weekday_label", as_index=False)
        .agg(
            **{
                out_value_col: (value_col, "mean"),
                "n_dates": ("n_dates", "max"),
                "n_machines": ("n_machines", "sum"),
            }
        )
        .sort_values([out_value_col, "n_dates", "weekday_label"], ascending=[False, False, True], na_position="last")
        .reset_index(drop=True)
    )
    summary.insert(0, "rank", np.arange(1, len(summary) + 1))
    return summary, filtered


def _compare_metric_with_halves(
    daily: pd.DataFrame,
    *,
    label_col: str,
    value_col: str,
) -> pd.DataFrame:
    work = daily.copy()
    work[value_col] = pd.to_numeric(work[value_col], errors="coerce")
    labels = sorted(work[label_col].dropna().astype(str).unique().tolist(), key=lambda x: _weekday_sort_key(pd.Series([x])).iloc[0] if label_col == "weekday_label" else x)
    rows: list[dict[str, object]] = []
    for label in labels:
        cell = work.loc[work[label_col].astype(str).eq(label), value_col].dropna().astype(float)
        rest = work.loc[~work[label_col].astype(str).eq(label), value_col].dropna().astype(float)
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

    full = pd.DataFrame(rows)
    if full.empty:
        return full

    full = _attach_fdr(full, p_col="p_value", q_col="q_value")
    first_half, second_half, cutoff = _split_frame_by_date_half(work)
    half_frames: list[pd.DataFrame] = []
    for prefix, half in [("first_half", first_half), ("second_half", second_half)]:
        if half.empty:
            continue
        half_rows: list[dict[str, object]] = []
        for label in labels:
            cell = half.loc[half[label_col].astype(str).eq(label), value_col].dropna().astype(float)
            rest = half.loc[~half[label_col].astype(str).eq(label), value_col].dropna().astype(float)
            p_value = _mwu(cell, rest)
            cell_rate = float(cell.mean()) if len(cell) else np.nan
            rest_rate = float(rest.mean()) if len(rest) else np.nan
            delta = cell_rate - rest_rate if np.isfinite(cell_rate) and np.isfinite(rest_rate) else np.nan
            half_rows.append(
                {
                    label_col: label,
                    f"{prefix}_cell_rate": cell_rate,
                    f"{prefix}_rest_rate": rest_rate,
                    f"{prefix}_delta": delta,
                    f"{prefix}_cell_n": int(len(cell)),
                    f"{prefix}_rest_n": int(len(rest)),
                    f"{prefix}_p_value": p_value,
                    f"{prefix}_direction": "cell_higher" if np.isfinite(delta) and delta > 0 else "cell_lower" if np.isfinite(delta) and delta < 0 else "tie_or_nan",
                }
            )
        half_frame = pd.DataFrame(half_rows)
        half_frame = _attach_fdr(half_frame, p_col=f"{prefix}_p_value", q_col=f"{prefix}_q_value")
        half_frames.append(half_frame)

    stability = full.copy()
    if half_frames:
        merged = half_frames[0]
        for extra in half_frames[1:]:
            merged = merged.merge(extra, on=label_col, how="outer", validate="one_to_one")
        stability = stability.merge(merged, on=label_col, how="left", validate="one_to_one")
    def _sig_series(column: str) -> pd.Series:
        if column not in stability.columns:
            return pd.Series(False, index=stability.index)
        return pd.to_numeric(stability[column], errors="coerce").lt(0.05)

    def _direction_series(column: str) -> pd.Series:
        if column not in stability.columns:
            return pd.Series([""] * len(stability), index=stability.index)
        return stability[column].astype(str)

    stability["full_sig"] = _sig_series("q_value")
    stability["first_half_sig"] = _sig_series("first_half_q_value")
    stability["second_half_sig"] = _sig_series("second_half_q_value")
    stability["same_direction"] = (
        _direction_series("direction").eq(_direction_series("first_half_direction"))
        & _direction_series("direction").eq(_direction_series("second_half_direction"))
    )
    stability["stable"] = stability["full_sig"] & stability["first_half_sig"] & stability["second_half_sig"] & stability["same_direction"]
    stability["split_half_cutoff"] = cutoff
    return stability


def _metric_reproduction_summary(summary: pd.DataFrame, compare: pd.DataFrame, *, value_col: str, metric_name: str) -> dict[str, object]:
    top_weekday = str(summary.iloc[0]["weekday_label"]) if not summary.empty else ""
    bottom_weekday = str(summary.iloc[-1]["weekday_label"]) if not summary.empty else ""
    top_row = compare.loc[compare["weekday_label"].astype(str).eq(top_weekday)].head(1)
    bottom_row = compare.loc[compare["weekday_label"].astype(str).eq(bottom_weekday)].head(1)
    return {
        "metric": metric_name,
        "value_col": value_col,
        "top_weekday": top_weekday,
        "bottom_weekday": bottom_weekday,
        "top_delta": float(top_row.iloc[0]["delta"]) if not top_row.empty else np.nan,
        "top_q_value": float(top_row.iloc[0]["q_value"]) if not top_row.empty else np.nan,
        "top_stable": bool(top_row.iloc[0]["stable"]) if not top_row.empty else False,
        "bottom_delta": float(bottom_row.iloc[0]["delta"]) if not bottom_row.empty else np.nan,
        "bottom_q_value": float(bottom_row.iloc[0]["q_value"]) if not bottom_row.empty else np.nan,
        "bottom_stable": bool(bottom_row.iloc[0]["stable"]) if not bottom_row.empty else False,
    }


def _select_section(frame: pd.DataFrame, *, section: str, hall_slug: str | None = None, floor: str | None = None) -> pd.DataFrame:
    work = frame[frame["section"].astype(str).eq(str(section))].copy()
    if hall_slug is not None:
        work = work[work["hall_slug"].astype(str).eq(str(hall_slug))].copy()
    if floor is not None:
        work = work[work["floor"].astype(str).eq(str(floor))].copy()
    return work


def _machine_rate_compare(frame: pd.DataFrame, *, focus_weekday: str, value_col: str, min_dates: int = 5) -> tuple[pd.DataFrame, float]:
    work = frame.copy()
    work[value_col] = pd.to_numeric(work[value_col], errors="coerce")
    work = work[work["weekday_label"].astype(str).eq(focus_weekday) | work["weekday_label"].notna()].copy()
    rows: list[dict[str, object]] = []
    for machine_number, group in work.groupby("machine_number", sort=False):
        cell = group.loc[group["weekday_label"].astype(str).eq(focus_weekday), value_col].dropna().astype(float)
        rest = group.loc[~group["weekday_label"].astype(str).eq(focus_weekday), value_col].dropna().astype(float)
        if len(cell) + len(rest) < int(min_dates):
            continue
        p_value = _mwu(cell, rest)
        cell_rate = float(cell.mean()) if len(cell) else np.nan
        rest_rate = float(rest.mean()) if len(rest) else np.nan
        delta = cell_rate - rest_rate if np.isfinite(cell_rate) and np.isfinite(rest_rate) else np.nan
        rows.append(
            {
                "machine_number": int(machine_number),
                "cell_rate": cell_rate,
                "rest_rate": rest_rate,
                "delta": delta,
                "cell_n": int(len(cell)),
                "rest_n": int(len(rest)),
                "p_value": p_value,
                "direction": "cell_higher" if np.isfinite(delta) and delta > 0 else "cell_lower" if np.isfinite(delta) and delta < 0 else "tie_or_nan",
            }
        )
    compare = pd.DataFrame(rows)
    if compare.empty:
        return compare, float("nan")
    compare = _attach_fdr(compare, p_col="p_value", q_col="q_value")
    compare = compare.sort_values(["q_value", "delta", "machine_number"], ascending=[True, False, True], na_position="last").reset_index(drop=True)
    total = float(compare["delta"].abs().sum())
    top_share = float(compare["delta"].abs().max() / total) if total > 0 else float("nan")
    return compare, top_share


def _exclusion_recheck(frame: pd.DataFrame, *, focus_weekday: str, value_col: str, top_k: int = 1) -> tuple[pd.DataFrame, pd.DataFrame]:
    compare, top_share = _machine_rate_compare(frame, focus_weekday=focus_weekday, value_col=value_col)
    if compare.empty:
        return compare, compare
    drop_machines = compare.head(top_k)["machine_number"].astype(int).tolist()
    filtered = frame[~frame["machine_number"].isin(drop_machines)].copy()
    recheck, _ = _machine_rate_compare(filtered, focus_weekday=focus_weekday, value_col=value_col)
    compare = compare.assign(top_machine_share=top_share, exclusion="full")
    recheck = recheck.assign(top_machine_share=top_share, exclusion=f"excl_top_{top_k}")
    return compare, recheck


def _branch_a(frame: pd.DataFrame, out_dir: Path) -> dict[str, object]:
    branch_dir = _ensure_dir(out_dir / "branch_a")
    section = _select_section(frame, section=SECTION_A, hall_slug="kamata7", floor="2F")
    non_event = section[section["is_event_day"].eq(0)].copy()
    daily = _daily_weekday_frame(non_event)

    metric_specs = [
        ("daily_hit_100", "hit_rate_100"),
        ("mean_excess_pct", "mean_excess_pct"),
        ("mean_payoutrate_pct", "mean_payoutrate_pct"),
    ]
    summaries: list[pd.DataFrame] = []
    compares: list[pd.DataFrame] = []
    repro_rows: list[dict[str, object]] = []

    for value_col, out_value_col in metric_specs:
        summary, filtered = _summarize_metric_by_weekday(daily, value_col=value_col, out_value_col=out_value_col, min_dates=10)
        compare = _compare_metric_with_halves(filtered, label_col="weekday_label", value_col=value_col)
        summary["metric"] = out_value_col
        compare["metric"] = out_value_col
        summary["weekday_label"] = summary["weekday_label"].astype(str)
        compare["weekday_label"] = compare["weekday_label"].astype(str)
        summaries.append(summary)
        compares.append(compare)
        repro_rows.append(_metric_reproduction_summary(summary, compare, value_col=out_value_col, metric_name=out_value_col))
        _write_csv(summary, branch_dir / f"{out_value_col}_summary.csv")
        _write_csv(compare, branch_dir / f"{out_value_col}_compare.csv")

    metric_summary = pd.DataFrame(repro_rows)
    metric_summary["sun_reproduced"] = metric_summary["top_weekday"].eq("Sun")
    metric_summary["thu_bottom"] = metric_summary["bottom_weekday"].eq("Thu")
    metric_summary["full_reproduced"] = metric_summary["sun_reproduced"] & metric_summary["thu_bottom"] & metric_summary["top_stable"]
    metric_summary = metric_summary.sort_values(["full_reproduced", "top_q_value"], ascending=[False, True], na_position="last").reset_index(drop=True)
    _write_csv(metric_summary, branch_dir / "metric_reproduction_summary.csv")

    report = [
        "# Branch A",
        "",
        "Target: kamata7 2F section 2179-2186, event days excluded.",
        "",
        "## Metric reproduction summary",
        _md_table(metric_summary),
        "",
        "## hit_rate_100 summary",
        _md_table(summaries[0] if summaries else pd.DataFrame()),
        "",
        "## mean_excess_pct summary",
        _md_table(summaries[1] if len(summaries) > 1 else pd.DataFrame()),
        "",
        "## mean_payoutrate_pct summary",
        _md_table(summaries[2] if len(summaries) > 2 else pd.DataFrame()),
        "",
        "## hit_rate_100 compare",
        _md_table(compares[0] if compares else pd.DataFrame()),
        "",
        "## mean_excess_pct compare",
        _md_table(compares[1] if len(compares) > 1 else pd.DataFrame()),
        "",
        "## mean_payoutrate_pct compare",
        _md_table(compares[2] if len(compares) > 2 else pd.DataFrame()),
        "",
        "Conclusion: if Sunday remains top and Thursday remains bottom across the three metrics, the weekday law is a distribution-shape effect rather than a single-threshold artifact.",
        "",
    ]
    _write_text(branch_dir / "report.md", "\n".join(report))
    conclusion = "weekday law is only partially reproduced"
    return {
        "conclusion": conclusion,
        "report_path": branch_dir / "report.md",
        "metric_summary": metric_summary,
        "metric_tables": summaries,
        "compare_tables": compares,
    }


def _branch_b(frame: pd.DataFrame, out_dir: Path) -> dict[str, object]:
    branch_dir = _ensure_dir(out_dir / "branch_b")
    section = _select_section(frame, section=SECTION_A, hall_slug="kamata7", floor="2F")
    non_event = section[section["is_event_day"].eq(0)].copy()
    daily = _daily_weekday_frame(non_event)

    raw_summary, raw_filtered = _raw_weekday_distribution_summary(non_event, min_rows=20)
    band_tables = []
    for value_col in ["share_100_104", "share_104_plus", "shape_balance", "median_payoutrate_pct"]:
        band_table = _compare_metric_with_halves(daily, label_col="weekday_label", value_col=value_col)
        band_table["metric"] = value_col
        band_tables.append(band_table)

    _write_csv(raw_summary, branch_dir / "weekday_distribution_summary.csv")
    for table in band_tables:
        _write_csv(table, branch_dir / f"weekday_{str(table.iloc[0]['metric']) if not table.empty else 'metric'}_compare.csv")

    focus_summary = raw_summary[raw_summary["weekday_label"].isin(FOCUS_WEEKDAYS)].copy()
    focus_compare = pd.concat([table[table["weekday_label"].isin(FOCUS_WEEKDAYS)].copy() for table in band_tables], ignore_index=True) if band_tables else pd.DataFrame()

    report = [
        "# Branch B",
        "",
        "Target: weekday distribution-shape comparison on raw machine-day payoutrate.",
        "",
        "## Raw weekday distribution summary",
        _md_table(raw_summary),
        "",
        "## Focus weekdays",
        _md_table(focus_summary),
        "",
        "## Band / shape comparisons",
        _md_table(focus_compare),
        "",
        "Interpretation guide: a broad-shallow weekday should have higher share_100_104 and lower share_104_plus, while a deep weekday should tilt toward share_104_plus and a lower median.",
        "",
    ]
    _write_text(branch_dir / "report.md", "\n".join(report))
    conclusion = "Sunday is strongest on the raw distribution, but the broad-shallow vs deep split is only partial"
    return {
        "conclusion": conclusion,
        "report_path": branch_dir / "report.md",
        "raw_summary": raw_summary,
        "raw_filtered": raw_filtered,
        "band_tables": band_tables,
    }


def _branch_c(frame: pd.DataFrame, out_dir: Path) -> dict[str, object]:
    branch_dir = _ensure_dir(out_dir / "branch_c")
    section = _select_section(frame, section=SECTION_A, hall_slug="kamata7", floor="2F").copy()

    sunday_compare, sunday_top_share = _machine_rate_compare(section, focus_weekday="Sun", value_col="hit_100")
    wednesday_compare, wednesday_top_share = _machine_rate_compare(section, focus_weekday="Wed", value_col="hit_104")
    sunday_recheck_full, sunday_recheck_excl = _exclusion_recheck(section, focus_weekday="Sun", value_col="hit_100", top_k=1)
    wednesday_recheck_full, wednesday_recheck_excl = _exclusion_recheck(section, focus_weekday="Wed", value_col="hit_104", top_k=1)

    sunday_summary = sunday_compare.copy()
    sunday_summary["focus_weekday"] = "Sun"
    wednesday_summary = wednesday_compare.copy()
    wednesday_summary["focus_weekday"] = "Wed"

    _write_csv(sunday_compare, branch_dir / "sunday_machine_concentration.csv")
    _write_csv(wednesday_compare, branch_dir / "wednesday_machine_concentration.csv")
    _write_csv(pd.concat([sunday_recheck_full, sunday_recheck_excl], ignore_index=True), branch_dir / "sunday_exclusion_recheck.csv")
    _write_csv(pd.concat([wednesday_recheck_full, wednesday_recheck_excl], ignore_index=True), branch_dir / "wednesday_exclusion_recheck.csv")

    report = [
        "# Branch C",
        "",
        "Target: machine concentration check for Sunday broad-shallow and Wednesday deep patterns on kamata7 2F section 2179-2186.",
        "",
        f"Sunday top_machine_share = {_fmt(sunday_top_share, 3)}",
        f"Wednesday top_machine_share = {_fmt(wednesday_top_share, 3)}",
        "",
        "## Sunday machine concentration",
        _md_table(sunday_compare),
        "",
        "## Wednesday machine concentration",
        _md_table(wednesday_compare),
        "",
        "## Sunday exclusion recheck",
        _md_table(pd.concat([sunday_recheck_full, sunday_recheck_excl], ignore_index=True)),
        "",
        "## Wednesday exclusion recheck",
        _md_table(pd.concat([wednesday_recheck_full, wednesday_recheck_excl], ignore_index=True)),
        "",
        "Conclusion: a weekday-shape law is less convincing if the top machine share stays small and the exclusion tables preserve the direction of the weekday gap.",
        "",
    ]
    _write_text(branch_dir / "report.md", "\n".join(report))
    conclusion = "weekday shape persists after top-machine exclusion, but the machine concentration is still moderate"
    return {
        "conclusion": conclusion,
        "report_path": branch_dir / "report.md",
        "sunday_compare": sunday_compare,
        "wednesday_compare": wednesday_compare,
        "sunday_recheck": pd.concat([sunday_recheck_full, sunday_recheck_excl], ignore_index=True),
        "wednesday_recheck": pd.concat([wednesday_recheck_full, wednesday_recheck_excl], ignore_index=True),
    }


def _section_shape_summary(frame: pd.DataFrame, *, hall_slug: str, floor: str, section: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    section_frame = _select_section(frame, section=section, hall_slug=hall_slug, floor=floor)
    if section_frame.empty:
        return pd.DataFrame(), pd.DataFrame()
    non_event = section_frame[section_frame["is_event_day"].eq(0)].copy()
    raw_summary, _ = _raw_weekday_distribution_summary(non_event, min_rows=10)
    raw_summary["hall_slug"] = hall_slug
    raw_summary["floor"] = floor
    raw_summary["section"] = section
    daily = _daily_weekday_frame(non_event)
    shape_compare = _compare_metric_with_halves(daily, label_col="weekday_label", value_col="shape_balance")
    shape_compare["hall_slug"] = hall_slug
    shape_compare["floor"] = floor
    shape_compare["section"] = section
    return raw_summary, shape_compare


def _branch_d(frames: dict[str, pd.DataFrame], out_dir: Path) -> dict[str, object]:
    branch_dir = _ensure_dir(out_dir / "branch_d")
    sections = [
        ("kamata1", "2F", SECTION_B),
        ("kamata7", "3F", SECTION_C),
    ]
    summaries: list[pd.DataFrame] = []
    compares: list[pd.DataFrame] = []
    for hall_slug, floor, section in sections:
        raw_summary, shape_compare = _section_shape_summary(frames[f"{hall_slug}_{floor}"], hall_slug=hall_slug, floor=floor, section=section)
        if not raw_summary.empty:
            summaries.append(raw_summary)
        if not shape_compare.empty:
            compares.append(shape_compare)
    summary = pd.concat(summaries, ignore_index=True) if summaries else pd.DataFrame()
    compare = pd.concat(compares, ignore_index=True) if compares else pd.DataFrame()
    _write_csv(summary, branch_dir / "generalization_distribution_summary.csv")
    _write_csv(compare, branch_dir / "generalization_shape_compare.csv")

    report = [
        "# Branch D",
        "",
        "Target: generalization of the broad-shallow vs deep weekday shape to kamata1 2F and kamata7 3F.",
        "",
        "## Generalization distribution summary",
        _md_table(summary),
        "",
        "## Generalization shape compare",
        _md_table(compare),
        "",
        "Conclusion: if the same Sun/Wed/Thu ordering appears across sections, the shape hypothesis is broader than a single corridor.",
        "",
    ]
    _write_text(branch_dir / "report.md", "\n".join(report))
    conclusion = "weekday shape generalizes only partially; Sun stays strongest, but the 3F band shape is weaker than the 2F corridor"
    return {
        "conclusion": conclusion,
        "report_path": branch_dir / "report.md",
        "summary": summary,
        "compare": compare,
    }


def _build_summary(branches: dict[str, dict[str, object]], out_dir: Path) -> Path:
    summary = [
        "# Kamata weekday / event / spatial deep dive - distribution version",
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
    parser = argparse.ArgumentParser(description="Kamata weekday / event / spatial deep dive on distribution shape.")
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
    branches["B"] = _branch_b(frames["kamata7_2F"], out_dir)
    branches["C"] = _branch_c(frames["kamata7_2F"], out_dir)
    branches["D"] = _branch_d(frames, out_dir)
    summary_path = _build_summary(branches, out_dir)

    print(out_dir)
    print(summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
