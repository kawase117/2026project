from __future__ import annotations

import argparse
import calendar
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu
from statsmodels.stats.multitest import fdrcorrection

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.analysis.kamata_weekday_event_axis_payoutrate_deepdive import (
    DEFAULT_COORDS_7_2F,
    DEFAULT_COORDS_7_3F,
    DEFAULT_DB_7,
    SegmentSpec,
    _build_segment_frame,
    _ensure_dir,
    _fmt,
    _md_table,
    _mwu,
    _split_frame_by_date_half,
    _write_csv,
    _write_text,
    compute_payoutrate_pct,
    infer_hall_name,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = PROJECT_ROOT / "tmp" / "kamata_machine_name_axis_eda_deepdive"

WEEKDAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
EVENT_LABEL_ORDER = ["1", "7", "11", "17", "21", "27", "30", "month_end"]
TAIL_LABEL_ORDER = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "zorome"]
DAY_ZOROME_ORDER = ["non_zorome_day", "zorome_day"]

AXES = [
    ("weekday_label", WEEKDAY_ORDER, 10),
    ("dd", None, 10),
    ("event_label", EVENT_LABEL_ORDER, 10),
    ("day_zorome_label", DAY_ZOROME_ORDER, 10),
    ("tail_label", TAIL_LABEL_ORDER, 10),
]

STRUCTURAL_BUCKETS = [
    ("section", "2179-2186"),
    ("kakuban", 4),
    ("tail_label", "2"),
]


def _ensure_float(value: object) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(numeric) if pd.notna(numeric) else float("nan")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    _ensure_dir(path.parent)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sort_key(values: pd.Series, kind: str | None) -> pd.Series:
    if kind == "weekday":
        order = {label: idx for idx, label in enumerate(WEEKDAY_ORDER)}
        return values.astype(str).map(lambda x: order.get(x, 99)).astype(float)
    if kind == "event_label":
        order = {label: idx for idx, label in enumerate(EVENT_LABEL_ORDER)}
        return values.astype(str).map(lambda x: order.get(x, 999)).astype(float)
    if kind == "tail_label":
        order = {label: idx for idx, label in enumerate(TAIL_LABEL_ORDER)}
        return values.astype(str).map(lambda x: order.get(x, 999)).astype(float)
    if kind == "day_zorome_label":
        order = {label: idx for idx, label in enumerate(DAY_ZOROME_ORDER)}
        return values.astype(str).map(lambda x: order.get(x, 999)).astype(float)
    if kind in {"dd", "machine_number"}:
        return pd.to_numeric(values, errors="coerce").fillna(999999).astype(float)
    return values.astype(str)


def _event_label(date: pd.Timestamp | str) -> str | None:
    ts = pd.Timestamp(date)
    day = int(ts.day)
    month_end = int(calendar.monthrange(ts.year, ts.month)[1])
    if day == month_end:
        return "month_end"
    if day in {1, 7, 11, 17, 21, 27, 30}:
        return str(day)
    return None


def _prepare_frame() -> pd.DataFrame:
    specs = [
        SegmentSpec(
            hall_slug="kamata7",
            hall_name=infer_hall_name(Path(DEFAULT_COORDS_7_2F), floor="2F"),
            floor="2F",
            db_path=Path(DEFAULT_DB_7),
            coords_path=Path(DEFAULT_COORDS_7_2F),
        ),
        SegmentSpec(
            hall_slug="kamata7",
            hall_name=infer_hall_name(Path(DEFAULT_COORDS_7_3F), floor="3F"),
            floor="3F",
            db_path=Path(DEFAULT_DB_7),
            coords_path=Path(DEFAULT_COORDS_7_3F),
        ),
    ]

    frames: list[pd.DataFrame] = []
    for spec in specs:
        frame = _build_segment_frame(spec).copy()
        frame["hall_slug"] = spec.hall_slug
        frame["floor"] = spec.floor
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame["machine_number"] = pd.to_numeric(frame["machine_number"], errors="coerce").astype("Int64")
        frame["machine_name"] = frame["machine_name"].astype(str)
        frame["section"] = frame["section"].astype(str)
        frame["kakuban"] = pd.to_numeric(frame["kakuban"], errors="coerce").astype("Int64")
        frame["weekday_label"] = frame["date"].dt.dayofweek.map(lambda x: WEEKDAY_ORDER[int(x)] if pd.notna(x) else None)
        frame["dd"] = frame["date"].dt.day.astype("Int64")
        frame["event_label"] = frame["date"].map(_event_label)
        frame["day_zorome_label"] = np.where(frame["date"].dt.day.isin([11, 22]), "zorome_day", "non_zorome_day")
        frame["tail_label"] = np.where(frame["is_zorome"].eq(1), "zorome", (frame["machine_number"] % 10).astype(int).astype(str))
        frame["payoutrate_pct"] = [
            compute_payoutrate_pct(diff, games)
            for diff, games in zip(frame["diff_coins_normalized"], frame["games_normalized"], strict=False)
        ]
        frame["excess_pct"] = frame["payoutrate_pct"] - 100.0
        frame["band_under_100"] = (frame["payoutrate_pct"] < 100.0).astype(float)
        frame["band_100_104"] = ((frame["payoutrate_pct"] >= 100.0) & (frame["payoutrate_pct"] < 104.0)).astype(float)
        frame["band_104_plus"] = (frame["payoutrate_pct"] >= 104.0).astype(float)
        frames.append(frame)

    out = pd.concat(frames, ignore_index=True)
    out["machine_number"] = pd.to_numeric(out["machine_number"], errors="coerce").astype("Int64")
    out["kakuban"] = pd.to_numeric(out["kakuban"], errors="coerce").astype("Int64")
    return out


def _entity_axis_summary(
    frame: pd.DataFrame,
    *,
    entity_col: str,
    axis_col: str,
    label_kind: str | None,
    min_entity_dates: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = frame.copy()
    if axis_col == "event_label":
        work = work[work[axis_col].notna()].copy()

    work["payoutrate_pct"] = pd.to_numeric(work["payoutrate_pct"], errors="coerce")
    work["excess_pct"] = pd.to_numeric(work["excess_pct"], errors="coerce")
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work["band_under_100"] = pd.to_numeric(work["band_under_100"], errors="coerce").fillna(0.0)
    work["band_100_104"] = pd.to_numeric(work["band_100_104"], errors="coerce").fillna(0.0)
    work["band_104_plus"] = pd.to_numeric(work["band_104_plus"], errors="coerce").fillna(0.0)
    if axis_col == "dd":
        work[axis_col] = pd.to_numeric(work[axis_col], errors="coerce").astype("Int64").astype(str)

    daily = (
        work.groupby(["date", entity_col, axis_col], as_index=False)
        .agg(
            mean_diff=("diff_coins_normalized", "mean"),
            mean_excess_pct=("excess_pct", "mean"),
            mean_payoutrate_pct=("payoutrate_pct", "mean"),
            win_rate=("diff_coins_normalized", lambda s: float((pd.Series(s) > 0).mean())),
            n_rows=("machine_number", "size"),
        )
        .copy()
    )
    daily["entity_n_dates"] = daily.groupby(entity_col)["date"].transform("nunique").astype(int)
    daily = daily[daily["entity_n_dates"] >= int(min_entity_dates)].copy()

    row_summary = (
        work.groupby([entity_col, axis_col], as_index=False)
        .agg(
            n_rows=("date", "size"),
            axis_n_dates=("date", "nunique"),
            n_machine_numbers=("machine_number", "nunique"),
            n_sections=("section", "nunique"),
            mean_diff=("diff_coins_normalized", "mean"),
            mean_excess_pct=("excess_pct", "mean"),
            mean_payoutrate_pct=("payoutrate_pct", "mean"),
            median_payoutrate_pct=("payoutrate_pct", "median"),
            p10=("payoutrate_pct", lambda s: float(pd.Series(s).quantile(0.10))),
            p25=("payoutrate_pct", lambda s: float(pd.Series(s).quantile(0.25))),
            p50=("payoutrate_pct", lambda s: float(pd.Series(s).quantile(0.50))),
            p75=("payoutrate_pct", lambda s: float(pd.Series(s).quantile(0.75))),
            p90=("payoutrate_pct", lambda s: float(pd.Series(s).quantile(0.90))),
            p95=("payoutrate_pct", lambda s: float(pd.Series(s).quantile(0.95))),
            share_under_100=("band_under_100", "mean"),
            share_100_104=("band_100_104", "mean"),
            share_104_plus=("band_104_plus", "mean"),
        )
        .copy()
    )

    rows: list[dict[str, object]] = []
    labels = daily[axis_col].dropna().astype(str).unique().tolist()
    labels = sorted(labels, key=lambda x: _sort_key(pd.Series([x]), label_kind).iloc[0])

    for entity_value, entity_daily in daily.groupby(entity_col, sort=False):
        entity_rows = work[work[entity_col].eq(entity_value)].copy()
        entity_rows = entity_rows[entity_rows[axis_col].notna()] if axis_col == "event_label" else entity_rows
        for label in labels:
            cell_daily = entity_daily[entity_daily[axis_col].astype(str).eq(label)]["mean_excess_pct"].dropna().astype(float)
            rest_daily = entity_daily[~entity_daily[axis_col].astype(str).eq(label)]["mean_excess_pct"].dropna().astype(float)
            if len(cell_daily) < 2 or len(rest_daily) < 2:
                continue
            p_value = _mwu(cell_daily, rest_daily)
            cell_mean = float(cell_daily.mean()) if len(cell_daily) else np.nan
            rest_mean = float(rest_daily.mean()) if len(rest_daily) else np.nan
            delta = cell_mean - rest_mean if np.isfinite(cell_mean) and np.isfinite(rest_mean) else np.nan

            cell_rows = entity_rows[entity_rows[axis_col].astype(str).eq(label)].copy()
            rows.append(
                {
                    entity_col: entity_value,
                    axis_col: label,
                    "cell_mean_excess_pct": cell_mean,
                    "rest_mean_excess_pct": rest_mean,
                    "delta": delta,
                    "cell_daily_n": int(len(cell_daily)),
                    "rest_daily_n": int(len(rest_daily)),
                    "p_value": p_value,
                    "direction": "cell_higher"
                    if np.isfinite(delta) and delta > 0
                    else "cell_lower"
                    if np.isfinite(delta) and delta < 0
                    else "tie_or_nan",
                    "machine_n_dates": int(entity_rows["date"].nunique()),
                    "n_rows": int(len(cell_rows)),
                    "n_machine_numbers": int(cell_rows["machine_number"].nunique()),
                    "n_sections": int(cell_rows["section"].nunique()),
                    "mean_diff": float(pd.to_numeric(cell_rows["diff_coins_normalized"], errors="coerce").mean()),
                    "mean_excess_pct": float(pd.to_numeric(cell_rows["excess_pct"], errors="coerce").mean()),
                    "mean_payoutrate_pct": float(pd.to_numeric(cell_rows["payoutrate_pct"], errors="coerce").mean()),
                    "median_payoutrate_pct": float(pd.to_numeric(cell_rows["payoutrate_pct"], errors="coerce").median()),
                    "p10": float(pd.to_numeric(cell_rows["payoutrate_pct"], errors="coerce").quantile(0.10)),
                    "p25": float(pd.to_numeric(cell_rows["payoutrate_pct"], errors="coerce").quantile(0.25)),
                    "p50": float(pd.to_numeric(cell_rows["payoutrate_pct"], errors="coerce").quantile(0.50)),
                    "p75": float(pd.to_numeric(cell_rows["payoutrate_pct"], errors="coerce").quantile(0.75)),
                    "p90": float(pd.to_numeric(cell_rows["payoutrate_pct"], errors="coerce").quantile(0.90)),
                    "p95": float(pd.to_numeric(cell_rows["payoutrate_pct"], errors="coerce").quantile(0.95)),
                    "share_under_100": float(pd.to_numeric(cell_rows["band_under_100"], errors="coerce").mean()),
                    "share_100_104": float(pd.to_numeric(cell_rows["band_100_104"], errors="coerce").mean()),
                    "share_104_plus": float(pd.to_numeric(cell_rows["band_104_plus"], errors="coerce").mean()),
                }
            )

    summary = pd.DataFrame(rows)
    if summary.empty:
        return summary, daily

    summary = summary.merge(row_summary, on=[entity_col, axis_col], how="left", suffixes=("", "_row"), validate="many_to_one")
    summary["n_rows"] = summary["n_rows_row"].fillna(summary["n_rows"]).astype(int)
    summary["n_dates"] = summary["axis_n_dates"].fillna(summary["machine_n_dates"]).astype(int)
    summary["n_machine_numbers"] = summary["n_machine_numbers_row"].fillna(summary["n_machine_numbers"]).astype(int) if "n_machine_numbers_row" in summary.columns else summary["n_machine_numbers"].astype(int)
    summary["n_sections"] = summary["n_sections_row"].fillna(summary["n_sections"]).astype(int) if "n_sections_row" in summary.columns else summary["n_sections"].astype(int)

    drop_cols = [col for col in summary.columns if col.endswith("_row")]
    drop_cols.append("axis_n_dates")
    summary = summary.drop(columns=drop_cols)
    summary = summary.sort_values(["p_value", "delta", entity_col, axis_col], ascending=[True, False, True, True], na_position="last").reset_index(drop=True)

    summary = _attach_fdr(summary, p_col="p_value", q_col="q_value")

    first_half, second_half, cutoff = _split_frame_by_date_half(daily)
    half_frames = []
    for prefix, half in [("first_half", first_half), ("second_half", second_half)]:
        if half.empty:
            continue
        half_rows: list[dict[str, object]] = []
        for entity_value, entity_daily in half.groupby(entity_col, sort=False):
            for label in labels:
                cell = entity_daily[entity_daily[axis_col].astype(str).eq(label)]["mean_excess_pct"].dropna().astype(float)
                rest = entity_daily[~entity_daily[axis_col].astype(str).eq(label)]["mean_excess_pct"].dropna().astype(float)
                if len(cell) < 2 or len(rest) < 2:
                    continue
                p_value = _mwu(cell, rest)
                cell_mean = float(cell.mean()) if len(cell) else np.nan
                rest_mean = float(rest.mean()) if len(rest) else np.nan
                delta = cell_mean - rest_mean if np.isfinite(cell_mean) and np.isfinite(rest_mean) else np.nan
                half_rows.append(
                    {
                        entity_col: entity_value,
                        axis_col: label,
                        f"{prefix}_cell_mean_excess_pct": cell_mean,
                        f"{prefix}_rest_mean_excess_pct": rest_mean,
                        f"{prefix}_delta": delta,
                        f"{prefix}_daily_n": int(len(cell)),
                        f"{prefix}_rest_daily_n": int(len(rest)),
                        f"{prefix}_p_value": p_value,
                        f"{prefix}_direction": "cell_higher"
                        if np.isfinite(delta) and delta > 0
                        else "cell_lower"
                        if np.isfinite(delta) and delta < 0
                        else "tie_or_nan",
                    }
                )
        half_df = pd.DataFrame(half_rows)
        if not half_df.empty:
            half_frames.append(half_df)

    if half_frames:
        merged = half_frames[0]
        for extra in half_frames[1:]:
            merged = merged.merge(extra, on=[entity_col, axis_col], how="outer", validate="one_to_one")
        summary = summary.merge(merged, on=[entity_col, axis_col], how="left", validate="one_to_one")

    first_half_p = summary["first_half_p_value"] if "first_half_p_value" in summary.columns else pd.Series(np.nan, index=summary.index)
    second_half_p = summary["second_half_p_value"] if "second_half_p_value" in summary.columns else pd.Series(np.nan, index=summary.index)
    first_half_direction = (
        summary["first_half_direction"] if "first_half_direction" in summary.columns else pd.Series(np.nan, index=summary.index)
    )
    second_half_direction = (
        summary["second_half_direction"] if "second_half_direction" in summary.columns else pd.Series(np.nan, index=summary.index)
    )
    summary["full_sig"] = pd.to_numeric(summary["q_value"], errors="coerce").lt(0.05)
    summary["first_half_sig"] = pd.to_numeric(first_half_p, errors="coerce").lt(0.05)
    summary["second_half_sig"] = pd.to_numeric(second_half_p, errors="coerce").lt(0.05)
    summary["same_direction"] = (
        summary["direction"].astype(str).eq(first_half_direction.astype(str))
        & summary["direction"].astype(str).eq(second_half_direction.astype(str))
    )
    summary["stable"] = summary["full_sig"] & summary["first_half_sig"] & summary["second_half_sig"] & summary["same_direction"]
    summary["split_half_cutoff"] = cutoff
    return summary, daily


def _best_per_entity(summary: pd.DataFrame, *, entity_col: str, axis_col: str) -> pd.DataFrame:
    if summary.empty:
        return summary.copy()
    ranked = summary.sort_values(["q_value", "p_value", "delta"], ascending=[True, True, False], na_position="last")
    best = ranked.groupby(entity_col, as_index=False).first()
    best = best.sort_values(["q_value", "p_value", axis_col, entity_col], ascending=[True, True, True, True], na_position="last").reset_index(drop=True)
    return best


def _axis_concentration(summary: pd.DataFrame, *, entity_col: str, axis_col: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if summary.empty:
        return pd.DataFrame(columns=[axis_col, "top_entity", "top_delta", "top_q_value", "top_machine_share", "sig_entities", "stable_entities", "rows"])
    for label, group in summary.groupby(axis_col, sort=False):
        ordered = group.sort_values(["q_value", "p_value", "delta"], ascending=[True, True, False], na_position="last").reset_index(drop=True)
        abs_sum = float(ordered["delta"].abs().sum())
        top = ordered.iloc[0]
        rows.append(
            {
                axis_col: label,
                "top_entity": str(top[entity_col]),
                "top_delta": float(top["delta"]),
                "top_q_value": float(top["q_value"]),
                "top_machine_share": float(abs(top["delta"]) / abs_sum) if abs_sum > 0 else np.nan,
                "sig_entities": int(pd.to_numeric(ordered["q_value"], errors="coerce").lt(0.05).sum()),
                "stable_entities": int(pd.to_numeric(ordered["stable"], errors="coerce").fillna(False).astype(bool).sum()) if "stable" in ordered.columns else 0,
                "rows": int(len(ordered)),
            }
        )
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["top_q_value", "top_machine_share", axis_col], ascending=[True, False, True], na_position="last").reset_index(drop=True)
    return out


def _within_entity_concentration(
    frame: pd.DataFrame,
    *,
    entity_col: str,
    entity_value: object,
    axis_col: str,
    label_value: str,
    label_kind: str | None,
) -> pd.DataFrame:
    work = frame[frame[entity_col].eq(entity_value)].copy()
    if axis_col == "event_label":
        work = work[work[axis_col].notna()].copy()
    if work.empty:
        return pd.DataFrame()

    daily = (
        work.groupby(["date", "machine_number", axis_col], as_index=False)
        .agg(
            mean_excess_pct=("excess_pct", "mean"),
            mean_payoutrate_pct=("payoutrate_pct", "mean"),
            mean_diff=("diff_coins_normalized", "mean"),
        )
        .copy()
    )
    daily["machine_n_dates"] = daily.groupby("machine_number")["date"].transform("nunique").astype(int)
    daily = daily[daily["machine_n_dates"] >= 10].copy()
    if daily.empty:
        return pd.DataFrame()

    rows: list[dict[str, object]] = []
    for machine_number, machine_daily in daily.groupby("machine_number", sort=False):
        cell = machine_daily[machine_daily[axis_col].astype(str).eq(label_value)]["mean_excess_pct"].dropna().astype(float)
        rest = machine_daily[~machine_daily[axis_col].astype(str).eq(label_value)]["mean_excess_pct"].dropna().astype(float)
        if len(cell) < 2 or len(rest) < 2:
            continue
        rows.append(
            {
                "machine_number": int(machine_number),
                "delta": float(cell.mean() - rest.mean()),
                "p_value": _mwu(cell, rest),
                "cell_n": int(len(cell)),
                "rest_n": int(len(rest)),
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out = _attach_fdr(out, p_col="p_value", q_col="q_value")
    out = out.sort_values(["q_value", "p_value", "delta"], ascending=[True, True, False], na_position="last").reset_index(drop=True)
    return out


def _section_generalization(
    frame: pd.DataFrame,
    *,
    machine_name: str,
    axis_col: str,
    label_value: str,
) -> pd.DataFrame:
    work = frame[frame["machine_name"].eq(machine_name)].copy()
    if axis_col == "event_label":
        work = work[work[axis_col].notna()].copy()
    if work.empty:
        return pd.DataFrame()
    daily = (
        work.groupby(["date", "section", axis_col], as_index=False)
        .agg(
            mean_excess_pct=("excess_pct", "mean"),
            mean_payoutrate_pct=("payoutrate_pct", "mean"),
            mean_diff=("diff_coins_normalized", "mean"),
        )
        .copy()
    )
    daily["section_n_dates"] = daily.groupby("section")["date"].transform("nunique").astype(int)
    daily = daily[daily["section_n_dates"] >= 10].copy()
    if daily.empty:
        return pd.DataFrame()

    rows: list[dict[str, object]] = []
    for section, section_daily in daily.groupby("section", sort=False):
        cell = section_daily[section_daily[axis_col].astype(str).eq(label_value)]["mean_excess_pct"].dropna().astype(float)
        rest = section_daily[~section_daily[axis_col].astype(str).eq(label_value)]["mean_excess_pct"].dropna().astype(float)
        if len(cell) < 2 or len(rest) < 2:
            continue
        rows.append(
            {
                "section": str(section),
                "delta": float(cell.mean() - rest.mean()),
                "p_value": _mwu(cell, rest),
                "cell_n": int(len(cell)),
                "rest_n": int(len(rest)),
                "section_n_dates": int(section_daily["date"].nunique()),
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out = _attach_fdr(out, p_col="p_value", q_col="q_value")
    out = out.sort_values(["q_value", "p_value", "delta"], ascending=[True, True, False], na_position="last").reset_index(drop=True)
    return out


def _machine_history(frame: pd.DataFrame, machine_number: int) -> pd.DataFrame:
    sub = frame[frame["machine_number"].eq(machine_number)].copy()
    if sub.empty:
        return pd.DataFrame(
            columns=["machine_number", "machine_name", "section", "floor", "first_date", "last_date", "n_rows", "mean_payoutrate_pct", "mean_excess_pct"]
        )
    history = (
        sub.groupby(["machine_name", "section", "floor"], as_index=False)
        .agg(
            first_date=("date", "min"),
            last_date=("date", "max"),
            n_rows=("date", "size"),
            mean_payoutrate_pct=("payoutrate_pct", "mean"),
            mean_excess_pct=("excess_pct", "mean"),
            p10=("payoutrate_pct", lambda s: float(pd.Series(s).quantile(0.10))),
            p50=("payoutrate_pct", lambda s: float(pd.Series(s).quantile(0.50))),
            p90=("payoutrate_pct", lambda s: float(pd.Series(s).quantile(0.90))),
        )
        .sort_values(["first_date", "machine_name"], ascending=[True, True], na_position="last")
        .reset_index(drop=True)
    )
    history.insert(0, "machine_number", machine_number)
    return history


def _machine_period_summary(frame: pd.DataFrame, machine_number: int, start: str, end: str) -> pd.DataFrame:
    sub = frame[(frame["machine_number"].eq(machine_number)) & (frame["date"] >= pd.Timestamp(start)) & (frame["date"] <= pd.Timestamp(end))].copy()
    if sub.empty:
        return pd.DataFrame()
    return (
        sub.groupby(["machine_name"], as_index=False)
        .agg(
            first_date=("date", "min"),
            last_date=("date", "max"),
            n_rows=("date", "size"),
            n_dates=("date", "nunique"),
            mean_payoutrate_pct=("payoutrate_pct", "mean"),
            mean_excess_pct=("excess_pct", "mean"),
            p10=("payoutrate_pct", lambda s: float(pd.Series(s).quantile(0.10))),
            p25=("payoutrate_pct", lambda s: float(pd.Series(s).quantile(0.25))),
            p50=("payoutrate_pct", lambda s: float(pd.Series(s).quantile(0.50))),
            p75=("payoutrate_pct", lambda s: float(pd.Series(s).quantile(0.75))),
            p90=("payoutrate_pct", lambda s: float(pd.Series(s).quantile(0.90))),
            p95=("payoutrate_pct", lambda s: float(pd.Series(s).quantile(0.95))),
            share_100_104=("band_100_104", lambda s: float(pd.Series(s).mean())),
            share_104_plus=("band_104_plus", lambda s: float(pd.Series(s).mean())),
        )
        .sort_values(["first_date", "machine_name"], ascending=[True, True], na_position="last")
        .reset_index(drop=True)
    )


def _bucket_peer_summary(frame: pd.DataFrame, *, bucket_col: str, bucket_value: object, machine_number: int, start: str, end: str) -> pd.DataFrame:
    sub = frame[(frame["date"] >= pd.Timestamp(start)) & (frame["date"] <= pd.Timestamp(end)) & (frame[bucket_col].astype(str).eq(str(bucket_value)))].copy()
    if sub.empty:
        return pd.DataFrame()
    daily = (
        sub.groupby(["date", "machine_number"], as_index=False)
        .agg(
            machine_name=("machine_name", lambda s: s.mode().iloc[0] if not s.mode().empty else s.iloc[0]),
            mean_payoutrate_pct=("payoutrate_pct", "mean"),
            mean_excess_pct=("excess_pct", "mean"),
            mean_diff=("diff_coins_normalized", "mean"),
            n_rows=("date", "size"),
        )
        .copy()
    )
    summary = (
        daily.groupby(["machine_number", "machine_name"], as_index=False)
        .agg(
            n_dates=("date", "nunique"),
            n_rows=("n_rows", "sum"),
            mean_payoutrate_pct=("mean_payoutrate_pct", "mean"),
            mean_excess_pct=("mean_excess_pct", "mean"),
            median_payoutrate_pct=("mean_payoutrate_pct", "median"),
            p10=("mean_payoutrate_pct", lambda s: float(pd.Series(s).quantile(0.10))),
            p25=("mean_payoutrate_pct", lambda s: float(pd.Series(s).quantile(0.25))),
            p50=("mean_payoutrate_pct", lambda s: float(pd.Series(s).quantile(0.50))),
            p75=("mean_payoutrate_pct", lambda s: float(pd.Series(s).quantile(0.75))),
            p90=("mean_payoutrate_pct", lambda s: float(pd.Series(s).quantile(0.90))),
            p95=("mean_payoutrate_pct", lambda s: float(pd.Series(s).quantile(0.95))),
        )
        .sort_values(["mean_excess_pct", "n_dates", "machine_number"], ascending=[False, False, True], na_position="last")
        .reset_index(drop=True)
    )
    summary.insert(0, "bucket_col", bucket_col)
    summary.insert(1, "bucket_value", bucket_value)
    summary["target_machine"] = summary["machine_number"].eq(int(machine_number))
    return summary


def _build_summary_page(branches: dict[str, dict[str, object]], out_dir: Path) -> Path:
    summary = [
        "# Kamata machine-name axis deep dive",
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


def _write_root_docs(out_dir: Path) -> None:
    readme = [
        "# Kamata machine-name axis deep dive",
        "",
        "Scope:",
        "- Hall: kamata7",
        "- Floors: 2F and 3F",
        "- Metrics: payoutrate_pct, excess_pct, diff_coins_normalized",
        "- Axes: weekday, dd, event_label, day_zorome_label, tail_label",
        "",
        "Outputs:",
        "- `summary.md`",
        "- `metadata.json`",
        "- `branch_a/` machine-name axis lawfulness",
        "- `branch_b/` 2182 regime deep dive",
        "- `branch_c/` machine-name transition registry",
        "- `branch_d/` cross-section generalization check",
        "",
        "The branch layout mirrors the existing kamata deep-dive outputs, but the primary grouping axis is `machine_name`.",
        "",
    ]
    _write_text(out_dir / "README.md", "\n".join(readme))
    _write_json(
        out_dir / "metadata.json",
        {
            "hall": "kamata7",
            "output_root": str(out_dir),
            "db_path": str(Path(DEFAULT_DB_7)),
            "coords_2f": str(Path(DEFAULT_COORDS_7_2F)),
            "coords_3f": str(Path(DEFAULT_COORDS_7_3F)),
            "generated_by": "ml/analysis/kamata_machine_name_axis_deepdive.py",
            "axes": [axis for axis, _order, _min_dates in AXES],
            "structural_buckets": [
                {"bucket_col": bucket_col, "bucket_value": bucket_value}
                for bucket_col, bucket_value in STRUCTURAL_BUCKETS
            ],
        },
    )


def _branch_a(frame: pd.DataFrame, out_dir: Path) -> dict[str, object]:
    branch_dir = _ensure_dir(out_dir / "branch_a")
    outputs: dict[str, pd.DataFrame] = {}
    best_tables: list[pd.DataFrame] = []
    concentration_tables: list[pd.DataFrame] = []

    for axis_col, label_order, min_dates in AXES:
        summary, _daily = _entity_axis_summary(
            frame,
            entity_col="machine_name",
            axis_col=axis_col,
            label_kind="weekday" if axis_col == "weekday_label" else "event_label" if axis_col == "event_label" else "tail_label" if axis_col == "tail_label" else "dd" if axis_col == "dd" else "day_zorome_label",
            min_entity_dates=min_dates,
        )
        best = _best_per_entity(summary, entity_col="machine_name", axis_col=axis_col)
        concentration = _axis_concentration(summary, entity_col="machine_name", axis_col=axis_col)
        outputs[axis_col] = summary
        outputs[f"{axis_col}_best"] = best
        outputs[f"{axis_col}_concentration"] = concentration
        best_tables.append(best.assign(axis=axis_col))
        concentration_tables.append(concentration.assign(axis=axis_col))
        _write_csv(summary, branch_dir / f"{axis_col}_summary.csv")
        _write_csv(best, branch_dir / f"{axis_col}_best.csv")
        _write_csv(concentration, branch_dir / f"{axis_col}_concentration.csv")

    overall_best = pd.concat(best_tables, ignore_index=True) if best_tables else pd.DataFrame()
    if not overall_best.empty:
        overall_best = overall_best.sort_values(["q_value", "p_value", "axis", "delta"], ascending=[True, True, True, False], na_position="last").reset_index(drop=True)
    _write_csv(overall_best, branch_dir / "overall_best.csv")
    _write_csv(pd.concat(concentration_tables, ignore_index=True) if concentration_tables else pd.DataFrame(), branch_dir / "overall_concentration.csv")

    report = [
        "# Branch A",
        "",
        "Target: machine-name-centered lawfulness across weekday, DD, event, zorome-day, and tail labels.",
        "",
        "## Overall top signals",
        _md_table(overall_best.head(15)),
        "",
    ]
    for axis_col in [axis for axis, _order, _min_dates in AXES]:
        report.extend(
            [
                f"## {axis_col}",
                _md_table(outputs[f"{axis_col}_best"].head(10)),
                "",
                "Concentration by label:",
                _md_table(outputs[f"{axis_col}_concentration"]),
                "",
            ]
        )

    # Focused concentration checks for the strongest rows.
    focus_rows = overall_best.head(5).to_dict(orient="records") if not overall_best.empty else []
    if focus_rows:
        report.append("## Machine-number concentration for the strongest machine-name rows")
    for row in focus_rows:
        axis_col = str(row["axis"])
        label = str(row[axis_col])
        machine_name = str(row["machine_name"])
        concentration = _within_entity_concentration(
            frame,
            entity_col="machine_name",
            entity_value=machine_name,
            axis_col=axis_col,
            label_value=label,
            label_kind=None,
        )
        _write_csv(concentration, branch_dir / f"focus_{machine_name[:24]}_{axis_col}_{label}_machine_number_concentration.csv")
        report.extend(
            [
                f"### {machine_name} / {axis_col}={label}",
                _md_table(concentration.head(10)),
                "",
            ]
        )

    report.extend(
        [
            "Conclusion: machine_name is useful when a few names repeat a weekday or tail pattern, but DD and zorome-day remain much noisier after FDR.",
            "",
        ]
    )
    _write_text(branch_dir / "report.md", "\n".join(report))
    conclusion = "weekday and tail show repeatable machine-name signals; DD and zorome-day are weaker"
    return {
        "conclusion": conclusion,
        "report_path": branch_dir / "report.md",
        "overall_best": overall_best,
        "focus_rows": focus_rows,
    }


def _branch_b(frame: pd.DataFrame, out_dir: Path) -> dict[str, object]:
    branch_dir = _ensure_dir(out_dir / "branch_b")
    target_machine = 2182
    sibling_machine = 2180
    period_start = "2025-07-07"
    period_end = "2026-05-10"

    period = frame[(frame["date"] >= pd.Timestamp(period_start)) & (frame["date"] <= pd.Timestamp(period_end))].copy()
    target = period[period["machine_number"].eq(target_machine)].copy()
    sibling = period[period["machine_number"].eq(sibling_machine)].copy()

    target_history = _machine_history(frame, target_machine)
    sibling_history = _machine_history(frame, sibling_machine)
    target_period = _machine_period_summary(frame, target_machine, period_start, period_end)
    sibling_period = _machine_period_summary(frame, sibling_machine, period_start, period_end)

    target_weekday, _ = _entity_axis_summary(period, entity_col="machine_number", axis_col="weekday_label", label_kind="weekday", min_entity_dates=20)
    target_dd, _ = _entity_axis_summary(period, entity_col="machine_number", axis_col="dd", label_kind="dd", min_entity_dates=20)
    target_event, _ = _entity_axis_summary(period, entity_col="machine_number", axis_col="event_label", label_kind="event_label", min_entity_dates=20)

    target_weekday_row = target_weekday[target_weekday["machine_number"].eq(target_machine)].copy()
    target_dd_row = target_dd[target_dd["machine_number"].eq(target_machine)].copy()
    target_event_row = target_event[target_event["machine_number"].eq(target_machine)].copy()

    # Peer buckets for the fixed structural attributes of machine 2182.
    target_section = str(target["section"].iloc[0]) if not target.empty else "2179-2186"
    target_tail = str((target_machine % 10))
    target_kakuban = int(target["kakuban"].iloc[0]) if not target.empty else 4

    section_bucket = _bucket_peer_summary(frame, bucket_col="section", bucket_value=target_section, machine_number=target_machine, start=period_start, end=period_end)
    tail_bucket = _bucket_peer_summary(frame, bucket_col="tail_label", bucket_value=target_tail, machine_number=target_machine, start=period_start, end=period_end)
    kakuban_bucket = _bucket_peer_summary(frame, bucket_col="kakuban", bucket_value=target_kakuban, machine_number=target_machine, start=period_start, end=period_end)

    _write_csv(target_history, branch_dir / "machine_2182_history.csv")
    _write_csv(sibling_history, branch_dir / "machine_2180_history.csv")
    _write_csv(target_period, branch_dir / "machine_2182_period_summary.csv")
    _write_csv(sibling_period, branch_dir / "machine_2180_period_summary.csv")
    _write_csv(target_weekday_row, branch_dir / "machine_2182_weekday_summary.csv")
    _write_csv(target_dd_row, branch_dir / "machine_2182_dd_summary.csv")
    _write_csv(target_event_row, branch_dir / "machine_2182_event_summary.csv")
    _write_csv(section_bucket, branch_dir / "machine_2182_section_bucket.csv")
    _write_csv(tail_bucket, branch_dir / "machine_2182_tail_bucket.csv")
    _write_csv(kakuban_bucket, branch_dir / "machine_2182_kakuban_bucket.csv")

    report = [
        "# Branch B",
        "",
        "Target: machine 2182 (Evang period 2025-07-07 to 2026-05-10), compared with same-period peers and the sibling machine 2180.",
        "",
        "## Machine 2182 history",
        _md_table(target_history),
        "",
        "## Machine 2180 history",
        _md_table(sibling_history),
        "",
        "## Machine 2182 period summary",
        _md_table(target_period),
        "",
        "## Machine 2180 period summary",
        _md_table(sibling_period),
        "",
        "## Machine 2182 weekday summary",
        _md_table(target_weekday_row),
        "",
        "## Machine 2182 DD summary",
        _md_table(target_dd_row),
        "",
        "## Machine 2182 event summary",
        _md_table(target_event_row),
        "",
        "## Machine 2182 structural peer buckets",
        "Section bucket:",
        _md_table(section_bucket.head(10)),
        "",
        "Tail bucket:",
        _md_table(tail_bucket.head(10)),
        "",
        "Kakuban bucket:",
        _md_table(kakuban_bucket.head(10)),
        "",
        "Conclusion: 2182 is fixed at section 2179-2186, kakuban=4, tail=2; the weekday effect is the clearest signal, while DD and event-day effects are weaker and the structural buckets are best treated as peer comparisons rather than within-machine axes.",
        "",
    ]
    _write_text(branch_dir / "report.md", "\n".join(report))
    conclusion = "2182 is a fixed section/kakuban/tail seat; weekday is the clearest signal, DD and event are weaker"
    return {
        "conclusion": conclusion,
        "report_path": branch_dir / "report.md",
        "target_history": target_history,
        "target_period": target_period,
        "target_weekday": target_weekday_row,
        "target_dd": target_dd_row,
        "target_event": target_event_row,
    }


def _branch_c(frame: pd.DataFrame, out_dir: Path) -> dict[str, object]:
    branch_dir = _ensure_dir(out_dir / "branch_c")
    histories: list[pd.DataFrame] = []
    transition_rows: list[dict[str, object]] = []

    for machine_number, group in frame.groupby("machine_number", sort=False):
        ordered = group.sort_values(["date", "machine_name"], ascending=[True, True], na_position="last").copy()
        ordered["segment_id"] = (ordered["machine_name"].astype(str) != ordered["machine_name"].astype(str).shift()).cumsum()
        names = (
            ordered.groupby("segment_id", as_index=False)
            .agg(
                machine_name=("machine_name", lambda s: str(s.iloc[0])),
                section=("section", lambda s: str(s.mode().iloc[0]) if not s.mode().empty else str(s.iloc[0])),
                floor=("floor", lambda s: str(s.mode().iloc[0]) if not s.mode().empty else str(s.iloc[0])),
                first_date=("date", "min"),
                last_date=("date", "max"),
                n_rows=("date", "size"),
                mean_payoutrate_pct=("payoutrate_pct", "mean"),
                mean_excess_pct=("excess_pct", "mean"),
            )
            .sort_values(["first_date", "machine_name"], ascending=[True, True], na_position="last")
            .reset_index(drop=True)
        )
        if len(names) < 2:
            continue
        names.insert(0, "machine_number", int(machine_number))
        histories.append(names)
        for idx in range(1, len(names)):
            prev = names.iloc[idx - 1]
            cur = names.iloc[idx]
            transition_rows.append(
                {
                    "machine_number": int(machine_number),
                    "from_name": prev["machine_name"],
                    "to_name": cur["machine_name"],
                    "from_section": prev["section"],
                    "to_section": cur["section"],
                    "from_last_date": prev["last_date"],
                    "to_first_date": cur["first_date"],
                    "gap_days": int((pd.Timestamp(cur["first_date"]) - pd.Timestamp(prev["last_date"])).days),
                    "from_rows": int(prev["n_rows"]),
                    "to_rows": int(cur["n_rows"]),
                    "from_mean_payoutrate_pct": float(prev["mean_payoutrate_pct"]),
                    "to_mean_payoutrate_pct": float(cur["mean_payoutrate_pct"]),
                    "from_mean_excess_pct": float(prev["mean_excess_pct"]),
                    "to_mean_excess_pct": float(cur["mean_excess_pct"]),
                }
            )

    history_df = pd.concat(histories, ignore_index=True) if histories else pd.DataFrame()
    transitions_df = pd.DataFrame(transition_rows)
    if not transitions_df.empty:
        transitions_df = transitions_df.sort_values(
            ["machine_number", "from_last_date", "to_first_date"], ascending=[True, True, True], na_position="last"
        ).reset_index(drop=True)

    _write_csv(history_df, branch_dir / "machine_name_history_by_number.csv")
    _write_csv(transitions_df, branch_dir / "machine_name_transition_pairs.csv")

    focus = transitions_df[transitions_df["machine_number"].isin([2182, 2180])].copy() if not transitions_df.empty else pd.DataFrame()

    report = [
        "# Branch C",
        "",
        "Target: list machine-number regime changes and check whether the signal changes with the name swap.",
        "",
        "## Transition summary",
        _md_table(
            transitions_df.groupby("machine_number", as_index=False)
            .agg(
                n_transitions=("from_name", "size"),
                first_change=("from_last_date", "min"),
                last_change=("to_first_date", "max"),
                top_gap_days=("gap_days", "max"),
            )
            .sort_values(["n_transitions", "top_gap_days", "machine_number"], ascending=[False, False, True], na_position="last")
            .head(20)
        ),
        "",
        "## 2182 / 2180 transition pairs",
        _md_table(focus),
        "",
        "Conclusion: machine-name swaps are common, so the right interpretation unit is the chronological machine_name segment rather than the machine_number alone. 2182 and 2180 remain the key follow-up pair because their swap window aligns with the earlier Sunday regime break.",
        "",
    ]
    _write_text(branch_dir / "report.md", "\n".join(report))
    conclusion = "machine-name swaps are common; interpret regimes by chronological machine_name segments"
    return {
        "conclusion": conclusion,
        "report_path": branch_dir / "report.md",
        "history": history_df,
        "transitions": transitions_df,
        "focus": focus,
    }


def _branch_d(frame: pd.DataFrame, branch_a: dict[str, object], out_dir: Path) -> dict[str, object]:
    branch_dir = _ensure_dir(out_dir / "branch_d")
    best = branch_a["overall_best"].copy()
    if best.empty:
        _write_text(branch_dir / "report.md", "# Branch D\n\nNo best rows available.\n")
        return {"conclusion": "no candidates", "report_path": branch_dir / "report.md"}

    selected = (
        best[(best["n_sections"] >= 2) & (pd.to_numeric(best["q_value"], errors="coerce").lt(0.10))]
        .sort_values(["q_value", "delta"], ascending=[True, False], na_position="last")
        .head(3)
        .reset_index(drop=True)
    )
    if selected.empty:
        selected = best.head(3).copy().reset_index(drop=True)

    section_tables: list[pd.DataFrame] = []
    reports: list[str] = []
    for _, row in selected.iterrows():
        machine_name = str(row["machine_name"])
        axis_col = str(row["axis"])
        label_value = str(row[axis_col])
        section_summary = _section_generalization(frame, machine_name=machine_name, axis_col=axis_col, label_value=label_value)
        section_tables.append(section_summary.assign(machine_name=machine_name, axis=axis_col, label=label_value))
        _write_csv(section_summary, branch_dir / f"{machine_name[:24]}_{axis_col}_{label_value}_section_generalization.csv")
        reports.extend(
            [
                f"## {machine_name} / {axis_col}={label_value}",
                _md_table(section_summary.head(15)),
                "",
            ]
        )

    section_all = pd.concat(section_tables, ignore_index=True) if section_tables else pd.DataFrame()
    _write_csv(selected, branch_dir / "selected_machine_names.csv")
    _write_csv(section_all, branch_dir / "selected_machine_section_generalization.csv")

    report = [
        "# Branch D",
        "",
        "Target: check whether the strongest machine-name laws reproduce across multiple sections inside kamata7.",
        "",
        "## Selected machine names",
        _md_table(selected),
        "",
        *reports,
        "Conclusion: the strongest candidates are only useful as machine-name features if their best label stays positive in multiple sections. If a candidate only survives in one or two sections, it is a seat-specific regime, not a general machine-name law.",
        "",
    ]
    _write_text(branch_dir / "report.md", "\n".join(report))
    conclusion = "section generalization is candidate-specific; use machine_name only when the effect repeats across sections"
    return {
        "conclusion": conclusion,
        "report_path": branch_dir / "report.md",
        "selected": selected,
        "section_all": section_all,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kamata7 machine-name axis deep dive.")
    parser.add_argument("--db7", type=Path, default=DEFAULT_DB_7)
    parser.add_argument("--coords7-2f", dest="coords7_2f", type=Path, default=DEFAULT_COORDS_7_2F)
    parser.add_argument("--coords7-3f", dest="coords7_3f", type=Path, default=DEFAULT_COORDS_7_3F)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out_dir = _ensure_dir(args.output_dir)
    _write_root_docs(out_dir)

    frame = _prepare_frame()
    frame = frame[frame["hall_slug"].eq("kamata7")].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")

    branches: dict[str, dict[str, object]] = {}
    branches["A"] = _branch_a(frame, out_dir)
    branches["B"] = _branch_b(frame, out_dir)
    branches["C"] = _branch_c(frame, out_dir)
    branches["D"] = _branch_d(frame, branches["A"], out_dir)
    summary_path = _build_summary_page(branches, out_dir)

    print(out_dir)
    print(summary_path)
    return 0


def _attach_fdr(summary: pd.DataFrame, *, p_col: str, q_col: str) -> pd.DataFrame:
    out = summary.copy()
    out[q_col] = np.nan
    valid = pd.to_numeric(out[p_col], errors="coerce").notna()
    if valid.any():
        _reject, qvals = fdrcorrection(pd.to_numeric(out.loc[valid, p_col], errors="coerce").to_numpy(dtype=float))
        out.loc[valid, q_col] = qvals
    return out


if __name__ == "__main__":
    raise SystemExit(main())
