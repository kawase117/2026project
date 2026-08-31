from __future__ import annotations

import argparse
import calendar
import json
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.analysis.kamata_machine_name_axis_deepdive import (
    _axis_concentration,
    _section_generalization,
    _within_entity_concentration,
)
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
OUTPUT_ROOT = PROJECT_ROOT / "tmp" / "kamata_machine_category_axis_eda_deepdive"

WEEKDAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
WEEKDAY_FOCUS_ORDER = ["Sat", "Thu", "Other"]
EVENT_LABEL_ORDER = ["1", "7", "11", "17", "21", "27", "30", "month_end"]
TAIL_LABEL_ORDER = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "zorome"]
DAY_ZOROME_ORDER = ["non_zorome_day", "zorome_day"]
AXES = [
    ("weekday_label", WEEKDAY_ORDER, "weekday"),
    ("dd", None, "dd"),
    ("event_label", EVENT_LABEL_ORDER, "event_label"),
    ("day_zorome_label", DAY_ZOROME_ORDER, "day_zorome_label"),
    ("tail_label", TAIL_LABEL_ORDER, "tail_label"),
]

A_TYPES = {"ノーマル", "Aタイプ", "A+AT", "A+ART"}
AT_TYPES = {"AT", "ART", "スマスロ", "AT(擬似ノーマル)"}
CATEGORY_ORDER = ["A", "AT", "unclassified"]
FOCUS_WEEKDAYS = ["Sat", "Thu"]


def _normalize_text(value: object) -> str:
    text = "" if pd.isna(value) else str(value)
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[^\w]+", "", text, flags=re.UNICODE)


def _machine_category(machine_type: object) -> str:
    text = "" if pd.isna(machine_type) else str(machine_type).strip()
    if text in A_TYPES:
        return "A"
    if text in AT_TYPES:
        return "AT"
    return "unclassified"


def _mode_or_first(series: pd.Series, default: object = pd.NA) -> object:
    cleaned = series.dropna()
    if cleaned.empty:
        return default
    mode = cleaned.mode()
    if not mode.empty:
        return mode.iloc[0]
    return cleaned.iloc[0]


def _event_label(date: pd.Timestamp | str) -> str | None:
    ts = pd.Timestamp(date)
    day = int(ts.day)
    month_end = int(calendar.monthrange(ts.year, ts.month)[1])
    if day == month_end:
        return "month_end"
    if day in {1, 7, 11, 17, 21, 27, 30}:
        return str(day)
    return None


def _sort_key(values: pd.Series, kind: str | None) -> pd.Series:
    if kind == "weekday":
        order = {label: idx for idx, label in enumerate(WEEKDAY_ORDER)}
        return values.astype(str).map(lambda x: order.get(x, 99)).astype(float)
    if kind == "weekday_focus":
        order = {label: idx for idx, label in enumerate(WEEKDAY_FOCUS_ORDER)}
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


def _write_json(path: Path, payload: dict[str, object]) -> None:
    _ensure_dir(path.parent)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _attach_fdr(summary: pd.DataFrame, *, p_col: str, q_col: str) -> pd.DataFrame:
    from statsmodels.stats.multitest import fdrcorrection

    out = summary.copy()
    out[q_col] = np.nan
    valid = pd.to_numeric(out[p_col], errors="coerce").notna()
    if valid.any():
        _reject, qvals = fdrcorrection(pd.to_numeric(out.loc[valid, p_col], errors="coerce").to_numpy(dtype=float))
        out.loc[valid, q_col] = qvals
    return out


def _build_category_lookup(master_csv: Path) -> tuple[dict[str, str], pd.DataFrame]:
    master = pd.read_csv(master_csv)
    required = {"machine_name", "machine_type"}
    missing = required - set(master.columns)
    if missing:
        raise ValueError(f"{master_csv} is missing required columns: {sorted(missing)}")

    work = master.copy()
    work["machine_name"] = work["machine_name"].astype(str)
    work["machine_type"] = work["machine_type"].astype(str)
    work["machine_name_key"] = work["machine_name"].map(_normalize_text)
    work["machine_category"] = work["machine_type"].map(_machine_category)
    work = work[work["machine_category"].ne("unclassified")].copy()
    work = work[work["machine_name_key"].ne("")].copy()

    dup = work.groupby("machine_name_key", as_index=False).agg(
        n=("machine_name", "size"),
        n_categories=("machine_category", "nunique"),
        categories=("machine_category", lambda s: sorted(set(s.astype(str)))),
        machine_types=("machine_type", lambda s: sorted(set(s.astype(str)))),
        names=("machine_name", lambda s: sorted(set(s.astype(str)))),
    )
    conflict = dup[dup["n_categories"] > 1].copy()
    if not conflict.empty:
        raise ValueError("machine_master_research contains conflicting categories after normalization")

    lookup = work.drop_duplicates("machine_name_key").set_index("machine_name_key")["machine_category"].to_dict()
    return lookup, work


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
        frame["weekday_label"] = frame["date"].dt.dayofweek.map(
            lambda x: WEEKDAY_ORDER[int(x)] if pd.notna(x) else None
        )
        frame["dd"] = frame["date"].dt.day.astype("Int64")
        frame["event_label"] = frame["date"].map(_event_label)
        frame["day_zorome_label"] = np.where(frame["date"].dt.day.isin([11, 22]), "zorome_day", "non_zorome_day")
        frame["tail_label"] = np.where(
            frame["is_zorome"].eq(1), "zorome", (frame["machine_number"] % 10).astype(int).astype(str)
        )
        frame["payoutrate_pct"] = [
            compute_payoutrate_pct(diff, games)
            for diff, games in zip(frame["diff_coins_normalized"], frame["games_normalized"], strict=False)
        ]
        frame["excess_pct"] = frame["payoutrate_pct"] - 100.0
        frames.append(frame)

    out = pd.concat(frames, ignore_index=True)
    out["machine_number"] = pd.to_numeric(out["machine_number"], errors="coerce").astype("Int64")
    out["kakuban"] = pd.to_numeric(out["kakuban"], errors="coerce").astype("Int64")
    return out


def _apply_category_lookup(frame: pd.DataFrame, lookup: dict[str, str]) -> pd.DataFrame:
    out = frame.copy()
    out["machine_name_key"] = out["machine_name"].map(_normalize_text)
    out["machine_category"] = out["machine_name_key"].map(lookup).fillna("unclassified")
    out["machine_type"] = out["machine_category"]
    out["matched_master"] = out["machine_name_key"].isin(lookup)
    return out


def _category_coverage(frame: pd.DataFrame) -> pd.DataFrame:
    names = frame[["machine_name", "machine_category", "matched_master"]].drop_duplicates().copy()
    names["match_status"] = np.where(names["matched_master"], "matched", "unclassified")
    rows = []
    for category in CATEGORY_ORDER:
        sub = names[names["machine_category"].eq(category)].copy()
        row_sub = frame[frame["machine_category"].eq(category)].copy()
        rows.append(
            {
                "machine_category": category,
                "unique_machine_names": int(sub["machine_name"].nunique()),
                "unique_machine_numbers": int(row_sub["machine_number"].nunique()),
                "row_count": int(len(row_sub)),
                "matched_machine_names": int(sub["matched_master"].sum()),
                "row_share": float(len(row_sub) / len(frame)) if len(frame) else np.nan,
            }
        )
    coverage = pd.DataFrame(rows)
    return coverage


def _weekday_focus_label(weekday_label: str) -> str:
    return weekday_label if weekday_label in FOCUS_WEEKDAYS else "Other"


def _weekday_profile(daily: pd.DataFrame) -> pd.DataFrame:
    work = daily.copy()
    work["weekday_focus"] = work["weekday_label"].map(_weekday_focus_label)
    rows = []
    for category, cat_daily in work.groupby("machine_category", sort=False):
        for label in WEEKDAY_FOCUS_ORDER:
            if label == "Other":
                cell = cat_daily[cat_daily["weekday_focus"].eq("Other")]["mean_excess_pct"].dropna().astype(float)
                rest = cat_daily[~cat_daily["weekday_focus"].eq("Other")]["mean_excess_pct"].dropna().astype(float)
            else:
                cell = cat_daily[cat_daily["weekday_focus"].eq(label)]["mean_excess_pct"].dropna().astype(float)
                rest = cat_daily[~cat_daily["weekday_focus"].eq(label)]["mean_excess_pct"].dropna().astype(float)
            if len(cell) < 1:
                continue
            rows.append(
                {
                    "machine_category": category,
                    "weekday_focus": label,
                    "entity_n_dates": int(cat_daily["date"].nunique()),
                    "cell_n_dates": int(len(cell)),
                    "cell_mean_excess_pct": float(cell.mean()) if len(cell) else np.nan,
                    "cell_median_excess_pct": float(cell.median()) if len(cell) else np.nan,
                    "cell_mean_payoutrate_pct": float((cell + 100.0).mean()) if len(cell) else np.nan,
                    "cell_p10_payoutrate_pct": float((cell + 100.0).quantile(0.10)) if len(cell) else np.nan,
                    "cell_p25_payoutrate_pct": float((cell + 100.0).quantile(0.25)) if len(cell) else np.nan,
                    "cell_p50_payoutrate_pct": float((cell + 100.0).quantile(0.50)) if len(cell) else np.nan,
                    "cell_p75_payoutrate_pct": float((cell + 100.0).quantile(0.75)) if len(cell) else np.nan,
                    "cell_p90_payoutrate_pct": float((cell + 100.0).quantile(0.90)) if len(cell) else np.nan,
                    "cell_p95_payoutrate_pct": float((cell + 100.0).quantile(0.95)) if len(cell) else np.nan,
                    "cell_share_100_104": float((((cell + 100.0) >= 100.0) & ((cell + 100.0) < 104.0)).mean())
                    if len(cell)
                    else np.nan,
                    "cell_share_104_plus": float(((cell + 100.0) >= 104.0).mean()) if len(cell) else np.nan,
                    "rest_n_dates": int(len(rest)),
                    "rest_mean_excess_pct": float(rest.mean()) if len(rest) else np.nan,
                    "rest_median_excess_pct": float(rest.median()) if len(rest) else np.nan,
                    "rest_mean_payoutrate_pct": float((rest + 100.0).mean()) if len(rest) else np.nan,
                }
            )
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(
            ["machine_category", "weekday_focus"], key=lambda s: _sort_key(s, "weekday_focus"), na_position="last"
        ).reset_index(drop=True)
    return out


def _weekday_tests(daily: pd.DataFrame, *, min_entity_dates: int = 20) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = daily.copy()
    rows: list[dict[str, object]] = []
    focus_profile_rows: list[dict[str, object]] = []
    for category, cat_daily in work.groupby("machine_category", sort=False):
        cat_daily = cat_daily.copy()
        cat_daily["weekday_focus"] = cat_daily["weekday_label"].map(_weekday_focus_label)
        entity_n_dates = int(cat_daily["date"].nunique())
        if entity_n_dates < min_entity_dates:
            continue
        for label in FOCUS_WEEKDAYS:
            cell = cat_daily[cat_daily["weekday_label"].eq(label)]["mean_excess_pct"].dropna().astype(float)
            rest = cat_daily[~cat_daily["weekday_label"].eq(label)]["mean_excess_pct"].dropna().astype(float)
            if len(cell) < 2 or len(rest) < 2:
                continue
            cell_payoutrate = cell + 100.0
            rest_payoutrate = rest + 100.0
            rows.append(
                {
                    "machine_category": category,
                    "weekday_label": label,
                    "entity_n_dates": entity_n_dates,
                    "cell_n_dates": int(len(cell)),
                    "rest_n_dates": int(len(rest)),
                    "cell_mean_excess_pct": float(cell.mean()),
                    "rest_mean_excess_pct": float(rest.mean()),
                    "delta": float(cell.mean() - rest.mean()),
                    "cell_mean_payoutrate_pct": float(cell_payoutrate.mean()),
                    "rest_mean_payoutrate_pct": float(rest_payoutrate.mean()),
                    "median_payoutrate_pct": float(cell_payoutrate.median()),
                    "p10": float(cell_payoutrate.quantile(0.10)),
                    "p25": float(cell_payoutrate.quantile(0.25)),
                    "p50": float(cell_payoutrate.quantile(0.50)),
                    "p75": float(cell_payoutrate.quantile(0.75)),
                    "p90": float(cell_payoutrate.quantile(0.90)),
                    "p95": float(cell_payoutrate.quantile(0.95)),
                    "share_100_104": float(((cell_payoutrate >= 100.0) & (cell_payoutrate < 104.0)).mean()),
                    "share_104_plus": float((cell_payoutrate >= 104.0).mean()),
                    "p_value": _mwu(cell, rest),
                    "direction": "cell_higher"
                    if cell.mean() > rest.mean()
                    else "cell_lower"
                    if cell.mean() < rest.mean()
                    else "tie_or_nan",
                }
            )
        focus = cat_daily.groupby("weekday_focus", as_index=False).agg(
            entity_n_dates=("date", "nunique"),
            mean_excess_pct=("mean_excess_pct", "mean"),
            median_excess_pct=("mean_excess_pct", "median"),
            mean_payoutrate_pct=("mean_payoutrate_pct", "mean"),
            median_payoutrate_pct=("mean_payoutrate_pct", "median"),
            p10_payoutrate_pct=("mean_payoutrate_pct", lambda s: float(pd.Series(s).quantile(0.10))),
            p25_payoutrate_pct=("mean_payoutrate_pct", lambda s: float(pd.Series(s).quantile(0.25))),
            p50_payoutrate_pct=("mean_payoutrate_pct", lambda s: float(pd.Series(s).quantile(0.50))),
            p75_payoutrate_pct=("mean_payoutrate_pct", lambda s: float(pd.Series(s).quantile(0.75))),
            p90_payoutrate_pct=("mean_payoutrate_pct", lambda s: float(pd.Series(s).quantile(0.90))),
            p95_payoutrate_pct=("mean_payoutrate_pct", lambda s: float(pd.Series(s).quantile(0.95))),
        )
        focus.insert(0, "machine_category", category)
        focus_profile_rows.append(focus)

    summary = pd.DataFrame(rows)
    if summary.empty:
        return summary, pd.DataFrame()
    summary = _attach_fdr(summary, p_col="p_value", q_col="q_value")
    first_half, second_half, cutoff = _split_frame_by_date_half(work)
    half_frames = []
    for prefix, half in [("first_half", first_half), ("second_half", second_half)]:
        if half.empty:
            continue
        half_rows: list[dict[str, object]] = []
        for category, cat_daily in half.groupby("machine_category", sort=False):
            entity_n_dates = int(cat_daily["date"].nunique())
            if entity_n_dates < min_entity_dates:
                continue
            for label in FOCUS_WEEKDAYS:
                cell = cat_daily[cat_daily["weekday_label"].eq(label)]["mean_excess_pct"].dropna().astype(float)
                rest = cat_daily[~cat_daily["weekday_label"].eq(label)]["mean_excess_pct"].dropna().astype(float)
                if len(cell) < 2 or len(rest) < 2:
                    continue
                p_value = _mwu(cell, rest)
                delta = float(cell.mean() - rest.mean())
                half_rows.append(
                    {
                        "machine_category": category,
                        "weekday_label": label,
                        f"{prefix}_cell_mean_excess_pct": float(cell.mean()),
                        f"{prefix}_rest_mean_excess_pct": float(rest.mean()),
                        f"{prefix}_delta": delta,
                        f"{prefix}_cell_n_dates": int(len(cell)),
                        f"{prefix}_rest_n_dates": int(len(rest)),
                        f"{prefix}_p_value": p_value,
                        f"{prefix}_direction": "cell_higher"
                        if delta > 0
                        else "cell_lower"
                        if delta < 0
                        else "tie_or_nan",
                    }
                )
        half_df = pd.DataFrame(half_rows)
        if not half_df.empty:
            half_frames.append(half_df)

    if half_frames:
        merged = half_frames[0]
        for extra in half_frames[1:]:
            merged = merged.merge(extra, on=["machine_category", "weekday_label"], how="outer", validate="one_to_one")
        summary = summary.merge(merged, on=["machine_category", "weekday_label"], how="left", validate="one_to_one")

    first_half_p = (
        summary["first_half_p_value"]
        if "first_half_p_value" in summary.columns
        else pd.Series(np.nan, index=summary.index)
    )
    second_half_p = (
        summary["second_half_p_value"]
        if "second_half_p_value" in summary.columns
        else pd.Series(np.nan, index=summary.index)
    )
    first_half_direction = (
        summary["first_half_direction"]
        if "first_half_direction" in summary.columns
        else pd.Series(np.nan, index=summary.index)
    )
    second_half_direction = (
        summary["second_half_direction"]
        if "second_half_direction" in summary.columns
        else pd.Series(np.nan, index=summary.index)
    )
    summary["full_sig"] = pd.to_numeric(summary["q_value"], errors="coerce").lt(0.05)
    summary["first_half_sig"] = pd.to_numeric(first_half_p, errors="coerce").lt(0.05)
    summary["second_half_sig"] = pd.to_numeric(second_half_p, errors="coerce").lt(0.05)
    summary["same_direction"] = summary["direction"].astype(str).eq(first_half_direction.astype(str)) & summary[
        "direction"
    ].astype(str).eq(second_half_direction.astype(str))
    summary["stable"] = (
        summary["full_sig"] & summary["first_half_sig"] & summary["second_half_sig"] & summary["same_direction"]
    )
    summary["split_half_cutoff"] = cutoff
    focus_profile = pd.concat(focus_profile_rows, ignore_index=True) if focus_profile_rows else pd.DataFrame()
    if not focus_profile.empty:
        focus_profile = focus_profile.sort_values(
            ["machine_category", "weekday_focus"], key=lambda s: _sort_key(s, "weekday_focus"), na_position="last"
        ).reset_index(drop=True)
    return summary, focus_profile


def _entity_axis_summary(
    frame: pd.DataFrame,
    *,
    entity_col: str,
    axis_col: str,
    label_kind: str | None,
    min_entity_dates: int,
    label_filter: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = frame.copy()
    if axis_col == "event_label":
        work = work[work[axis_col].notna()].copy()
    if axis_col == "dd":
        work[axis_col] = pd.to_numeric(work[axis_col], errors="coerce").astype("Int64").astype(str)

    work["mean_excess_pct"] = pd.to_numeric(work["excess_pct"], errors="coerce")
    work["mean_payoutrate_pct"] = pd.to_numeric(work["payoutrate_pct"], errors="coerce")
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")

    daily = (
        work.groupby(["date", entity_col, axis_col], as_index=False)
        .agg(
            mean_diff=("diff_coins_normalized", "mean"),
            mean_excess_pct=("mean_excess_pct", "mean"),
            mean_payoutrate_pct=("mean_payoutrate_pct", "mean"),
            n_rows=("machine_number", "size"),
            n_machine_numbers=("machine_number", "nunique"),
            n_sections=("section", "nunique"),
        )
        .copy()
    )
    daily["entity_n_dates"] = daily.groupby(entity_col)["date"].transform("nunique").astype(int)
    daily = daily[daily["entity_n_dates"] >= int(min_entity_dates)].copy()

    if label_filter is not None:
        daily = daily[daily[axis_col].astype(str).isin([str(label) for label in label_filter])].copy()

    rows: list[dict[str, object]] = []
    labels = daily[axis_col].dropna().astype(str).unique().tolist()
    labels = sorted(labels, key=lambda x: _sort_key(pd.Series([x]), label_kind).iloc[0])

    for entity_value, entity_daily in daily.groupby(entity_col, sort=False):
        entity_rows = work[work[entity_col].eq(entity_value)].copy()
        if axis_col == "event_label":
            entity_rows = entity_rows[entity_rows[axis_col].notna()].copy()
        for label in labels:
            cell_daily = (
                entity_daily[entity_daily[axis_col].astype(str).eq(label)]["mean_excess_pct"].dropna().astype(float)
            )
            rest_daily = (
                entity_daily[~entity_daily[axis_col].astype(str).eq(label)]["mean_excess_pct"].dropna().astype(float)
            )
            if len(cell_daily) < 2 or len(rest_daily) < 2:
                continue
            cell_rows = entity_rows[entity_rows[axis_col].astype(str).eq(label)].copy()
            cell_payoutrate = pd.to_numeric(cell_rows["payoutrate_pct"], errors="coerce")
            rows.append(
                {
                    entity_col: entity_value,
                    axis_col: label,
                    "entity_n_dates": int(entity_rows["date"].nunique()),
                    "cell_n_dates": int(len(cell_daily)),
                    "rest_n_dates": int(len(rest_daily)),
                    "cell_mean_excess_pct": float(cell_daily.mean()),
                    "rest_mean_excess_pct": float(rest_daily.mean()),
                    "delta": float(cell_daily.mean() - rest_daily.mean()),
                    "cell_mean_payoutrate_pct": float((cell_daily + 100.0).mean()),
                    "rest_mean_payoutrate_pct": float((rest_daily + 100.0).mean()),
                    "cell_sample_n_rows": int(len(cell_rows)),
                    "cell_sample_n_machine_numbers": int(cell_rows["machine_number"].nunique()),
                    "cell_sample_n_sections": int(cell_rows["section"].nunique()),
                    "n_rows": int(len(cell_rows)),
                    "n_machine_numbers": int(cell_rows["machine_number"].nunique()),
                    "n_sections": int(cell_rows["section"].nunique()),
                    "cell_sample_mean_diff": float(
                        pd.to_numeric(cell_rows["diff_coins_normalized"], errors="coerce").mean()
                    ),
                    "cell_sample_mean_excess_pct": float(
                        pd.to_numeric(cell_rows["excess_pct"], errors="coerce").mean()
                    ),
                    "cell_sample_mean_payoutrate_pct": float(cell_payoutrate.mean()),
                    "cell_sample_median_payoutrate_pct": float(cell_payoutrate.median()),
                    "cell_sample_p10": float(cell_payoutrate.quantile(0.10)),
                    "cell_sample_p25": float(cell_payoutrate.quantile(0.25)),
                    "cell_sample_p50": float(cell_payoutrate.quantile(0.50)),
                    "cell_sample_p75": float(cell_payoutrate.quantile(0.75)),
                    "cell_sample_p90": float(cell_payoutrate.quantile(0.90)),
                    "cell_sample_p95": float(cell_payoutrate.quantile(0.95)),
                    "cell_sample_share_100_104": float(((cell_payoutrate >= 100.0) & (cell_payoutrate < 104.0)).mean()),
                    "cell_sample_share_104_plus": float((cell_payoutrate >= 104.0).mean()),
                    "p_value": _mwu(cell_daily, rest_daily),
                    "direction": "cell_higher"
                    if np.isfinite(cell_daily.mean())
                    and np.isfinite(rest_daily.mean())
                    and cell_daily.mean() > rest_daily.mean()
                    else "cell_lower"
                    if np.isfinite(cell_daily.mean())
                    and np.isfinite(rest_daily.mean())
                    and cell_daily.mean() < rest_daily.mean()
                    else "tie_or_nan",
                }
            )

    summary = pd.DataFrame(rows)
    if summary.empty:
        return summary, daily

    summary = _attach_fdr(summary, p_col="p_value", q_col="q_value")
    first_half, second_half, cutoff = _split_frame_by_date_half(daily)
    half_frames = []
    for prefix, half in [("first_half", first_half), ("second_half", second_half)]:
        if half.empty:
            continue
        half_rows: list[dict[str, object]] = []
        for entity_value, entity_daily in half.groupby(entity_col, sort=False):
            for label in labels:
                cell = (
                    entity_daily[entity_daily[axis_col].astype(str).eq(label)]["mean_excess_pct"].dropna().astype(float)
                )
                rest = (
                    entity_daily[~entity_daily[axis_col].astype(str).eq(label)]["mean_excess_pct"]
                    .dropna()
                    .astype(float)
                )
                if len(cell) < 2 or len(rest) < 2:
                    continue
                delta = float(cell.mean() - rest.mean())
                half_rows.append(
                    {
                        entity_col: entity_value,
                        axis_col: label,
                        f"{prefix}_cell_mean_excess_pct": float(cell.mean()),
                        f"{prefix}_rest_mean_excess_pct": float(rest.mean()),
                        f"{prefix}_delta": delta,
                        f"{prefix}_cell_n_dates": int(len(cell)),
                        f"{prefix}_rest_n_dates": int(len(rest)),
                        f"{prefix}_p_value": _mwu(cell, rest),
                        f"{prefix}_direction": "cell_higher"
                        if delta > 0
                        else "cell_lower"
                        if delta < 0
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

    first_half_p = (
        summary["first_half_p_value"]
        if "first_half_p_value" in summary.columns
        else pd.Series(np.nan, index=summary.index)
    )
    second_half_p = (
        summary["second_half_p_value"]
        if "second_half_p_value" in summary.columns
        else pd.Series(np.nan, index=summary.index)
    )
    first_half_direction = (
        summary["first_half_direction"]
        if "first_half_direction" in summary.columns
        else pd.Series(np.nan, index=summary.index)
    )
    second_half_direction = (
        summary["second_half_direction"]
        if "second_half_direction" in summary.columns
        else pd.Series(np.nan, index=summary.index)
    )
    summary["full_sig"] = pd.to_numeric(summary["q_value"], errors="coerce").lt(0.05)
    summary["first_half_sig"] = pd.to_numeric(first_half_p, errors="coerce").lt(0.05)
    summary["second_half_sig"] = pd.to_numeric(second_half_p, errors="coerce").lt(0.05)
    summary["same_direction"] = summary["direction"].astype(str).eq(first_half_direction.astype(str)) & summary[
        "direction"
    ].astype(str).eq(second_half_direction.astype(str))
    summary["stable"] = (
        summary["full_sig"] & summary["first_half_sig"] & summary["second_half_sig"] & summary["same_direction"]
    )
    summary["split_half_cutoff"] = cutoff
    return summary, daily


def _write_root_docs(
    out_dir: Path,
    *,
    coverage: pd.DataFrame,
    coverage_report_path: Path,
) -> None:
    readme = [
        "# Kamata category axis deep dive",
        "",
        "Scope:",
        "- Hall: kamata7",
        "- Floors: 2F and 3F",
        "- Categories: A, AT, unclassified",
        "- Axes: weekday, dd, event_label, day_zorome_label, tail_label",
        "",
        "Outputs:",
        "- `summary.md`",
        "- `classification_report.md`",
        "- `classification_report.csv`",
        "- `branch_e/` weekday effect by machine category",
        "- `branch_f/` AT-group machine_name deep dive",
        "",
        "The machine_type lookup comes from `document/machine_master_research/machine_master.csv` and uses normalized `machine_name` matching.",
        "",
    ]
    _write_text(out_dir / "README.md", "\n".join(readme))
    _write_csv(coverage, coverage_report_path.with_suffix(".csv"))


def _branch_e(frame: pd.DataFrame, out_dir: Path) -> dict[str, object]:
    branch_dir = _ensure_dir(out_dir / "branch_e")
    profile = _weekday_profile(
        frame.groupby(["date", "machine_category"], as_index=False)
        .agg(
            mean_excess_pct=("excess_pct", "mean"),
            mean_payoutrate_pct=("payoutrate_pct", "mean"),
            n_rows=("machine_number", "size"),
            n_machine_numbers=("machine_number", "nunique"),
            n_sections=("section", "nunique"),
        )
        .assign(
            date=lambda df: pd.to_datetime(df["date"], errors="coerce"),
            weekday_label=lambda df: df["date"].dt.dayofweek.map(
                lambda x: WEEKDAY_ORDER[int(x)] if pd.notna(x) else None
            ),
        )
    )

    tests, focus_profile = _weekday_tests(
        frame.groupby(["date", "machine_category"], as_index=False)
        .agg(
            mean_excess_pct=("excess_pct", "mean"),
            mean_payoutrate_pct=("payoutrate_pct", "mean"),
            n_rows=("machine_number", "size"),
            n_machine_numbers=("machine_number", "nunique"),
            n_sections=("section", "nunique"),
        )
        .assign(
            date=lambda df: pd.to_datetime(df["date"], errors="coerce"),
            weekday_label=lambda df: df["date"].dt.dayofweek.map(
                lambda x: WEEKDAY_ORDER[int(x)] if pd.notna(x) else None
            ),
        )
    )

    _write_csv(profile, branch_dir / "weekday_profile.csv")
    _write_csv(focus_profile, branch_dir / "weekday_focus_profile.csv")
    _write_csv(tests, branch_dir / "weekday_tests.csv")

    report = [
        "# Branch E",
        "",
        "Target: check whether Saturday/Thursday effects depend on machine category (A vs AT) after collapsing each day into a category-average sample.",
        "",
        "## Weekday profile",
        _md_table(profile.head(24)),
        "",
        "## Focus profile",
        _md_table(focus_profile),
        "",
        "## Saturday / Thursday tests",
        _md_table(tests),
        "",
        "Conclusion: if Saturday stays positive and Thursday stays negative in A but not AT, the effect is category-specific; if both categories move together, it is a hall-wide level shift.",
        "",
    ]
    _write_text(branch_dir / "report.md", "\n".join(report))

    a_rows = tests[tests["machine_category"].eq("A")].copy()
    at_rows = tests[tests["machine_category"].eq("AT")].copy()
    unclassified_rows = tests[tests["machine_category"].eq("unclassified")].copy()
    conclusion = "pending"
    if not a_rows.empty and not at_rows.empty:
        sat_a = a_rows[a_rows["weekday_label"].eq("Sat")].head(1)
        thu_a = a_rows[a_rows["weekday_label"].eq("Thu")].head(1)
        sat_at = at_rows[at_rows["weekday_label"].eq("Sat")].head(1)
        thu_at = at_rows[at_rows["weekday_label"].eq("Thu")].head(1)
        if not sat_a.empty and not thu_a.empty and not sat_at.empty and not thu_at.empty:
            if (
                sat_a.iloc[0]["q_value"] < 0.05
                and thu_a.iloc[0]["q_value"] < 0.05
                and sat_at.iloc[0]["q_value"] >= 0.05
                and thu_at.iloc[0]["q_value"] >= 0.05
            ):
                conclusion = "A群にSaturday positive / Thursday negativeが寄っており、AT群では同効果が弱い"
            elif (
                sat_a.iloc[0]["q_value"] < 0.05
                and thu_a.iloc[0]["q_value"] < 0.05
                and sat_at.iloc[0]["q_value"] < 0.05
                and thu_at.iloc[0]["q_value"] < 0.05
            ):
                conclusion = "A群とAT群の双方に曜日効果があり、ホール全体のレベルシフト寄り"
            elif sat_at.iloc[0]["q_value"] < 0.05 or thu_at.iloc[0]["q_value"] < 0.05:
                conclusion = "AT群側にも曜日効果が残るため、A群特異ではない"
            else:
                conclusion = "曜日効果は主にA群側で、AT群は弱い"

    return {
        "conclusion": conclusion,
        "report_path": branch_dir / "report.md",
        "tests": tests,
        "profile": profile,
        "focus_profile": focus_profile,
        "unclassified_rows": unclassified_rows,
    }


def _branch_f(frame: pd.DataFrame, out_dir: Path) -> dict[str, object]:
    branch_dir = _ensure_dir(out_dir / "branch_f")
    at_frame = frame[frame["machine_category"].eq("AT")].copy()
    if at_frame.empty:
        _write_text(branch_dir / "report.md", "# Branch F\n\nNo AT-group rows available.\n")
        return {"conclusion": "no AT rows", "report_path": branch_dir / "report.md"}

    outputs: dict[str, pd.DataFrame] = {}
    best_tables: list[pd.DataFrame] = []
    concentration_tables: list[pd.DataFrame] = []

    for axis_col, label_order, label_kind in AXES:
        summary, daily = _entity_axis_summary(
            at_frame,
            entity_col="machine_name",
            axis_col=axis_col,
            label_kind=label_kind,
            min_entity_dates=10,
        )
        best = (
            summary.sort_values(["q_value", "p_value", "delta"], ascending=[True, True, False], na_position="last")
            .groupby("machine_name", as_index=False)
            .first()
        )
        best = best.sort_values(
            ["q_value", "p_value", axis_col, "machine_name"], ascending=[True, True, True, True], na_position="last"
        ).reset_index(drop=True)
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
        overall_best = overall_best.sort_values(
            ["q_value", "p_value", "axis", "delta"], ascending=[True, True, True, False], na_position="last"
        ).reset_index(drop=True)
    overall_concentration = (
        pd.concat(concentration_tables, ignore_index=True) if concentration_tables else pd.DataFrame()
    )

    _write_csv(overall_best, branch_dir / "overall_best.csv")
    _write_csv(overall_concentration, branch_dir / "overall_concentration.csv")

    selected = (
        overall_best[
            (overall_best["n_sections"] >= 2) & (pd.to_numeric(overall_best["q_value"], errors="coerce").lt(0.10))
        ]
        .sort_values(["q_value", "delta"], ascending=[True, False], na_position="last")
        .head(4)
        .reset_index(drop=True)
    )
    if selected.empty:
        selected = overall_best.head(4).copy().reset_index(drop=True)

    section_tables: list[pd.DataFrame] = []
    reports: list[str] = []
    for idx, row in selected.iterrows():
        machine_name = str(row["machine_name"])
        axis_col = str(row["axis"])
        label_value = str(row[axis_col])
        section_summary = _section_generalization(
            at_frame, machine_name=machine_name, axis_col=axis_col, label_value=label_value
        )
        section_tables.append(section_summary.assign(machine_name=machine_name, axis=axis_col, label=label_value))
        _write_csv(
            section_summary, branch_dir / f"candidate_{idx + 1:02d}_{axis_col}_{label_value}_section_generalization.csv"
        )

        concentration = _within_entity_concentration(
            at_frame,
            entity_col="machine_name",
            entity_value=machine_name,
            axis_col=axis_col,
            label_value=label_value,
            label_kind=None,
        )
        _write_csv(
            concentration,
            branch_dir / f"candidate_{idx + 1:02d}_{axis_col}_{label_value}_machine_number_concentration.csv",
        )

        reports.extend(
            [
                f"### {idx + 1}. {machine_name} / {axis_col}={label_value}",
                "Section generalization:",
                _md_table(section_summary.head(12)),
                "",
                "Machine-number concentration:",
                _md_table(concentration.head(12)),
                "",
            ]
        )

    section_all = pd.concat(section_tables, ignore_index=True) if section_tables else pd.DataFrame()
    _write_csv(selected, branch_dir / "selected_machine_names.csv")
    _write_csv(section_all, branch_dir / "selected_machine_section_generalization.csv")

    report = [
        "# Branch F",
        "",
        "Target: AT-group only machine_name laws, using the same weekday/DD/event/day-zorome/tail axes as the earlier machine_name deep dive.",
        "",
        "## Overall top signals",
        _md_table(overall_best.head(15)),
        "",
        "## Concentration by label",
        _md_table(overall_concentration),
        "",
        "## Selected candidates",
        _md_table(selected),
        "",
        *reports,
        "Conclusion: AT-group machine_name laws are only useful when the signal repeats across multiple sections and is not driven by one machine_number; otherwise they are seat-specific or transient.",
        "",
    ]
    _write_text(branch_dir / "report.md", "\n".join(report))

    conclusion = "AT-group machine_name laws are candidate-specific; use them only when section generalization repeats"
    return {
        "conclusion": conclusion,
        "report_path": branch_dir / "report.md",
        "overall_best": overall_best,
        "overall_concentration": overall_concentration,
        "selected": selected,
        "section_all": section_all,
    }


def _build_summary_page(branches: dict[str, dict[str, object]], out_dir: Path) -> Path:
    summary = [
        "# Kamata category axis deep dive",
        "",
        "## Branch conclusions",
        "",
        f"- Coverage: {branches['coverage']}",
        f"- Branch E: {branches['E']['conclusion']}",
        f"- Branch F: {branches['F']['conclusion']}",
        "",
        "## Report paths",
        "",
        f"- [Classification report]({(out_dir / 'classification_report.md').resolve()})",
        f"- [Branch E]({(out_dir / 'branch_e' / 'report.md').resolve()})",
        f"- [Branch F]({(out_dir / 'branch_f' / 'report.md').resolve()})",
        "",
    ]
    summary_path = out_dir / "summary.md"
    _write_text(summary_path, "\n".join(summary))
    return summary_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kamata7 machine category axis deep dive.")
    parser.add_argument("--db7", type=Path, default=DEFAULT_DB_7)
    parser.add_argument("--coords7-2f", dest="coords7_2f", type=Path, default=DEFAULT_COORDS_7_2F)
    parser.add_argument("--coords7-3f", dest="coords7_3f", type=Path, default=DEFAULT_COORDS_7_3F)
    parser.add_argument(
        "--master-csv", type=Path, default=PROJECT_ROOT / "document" / "machine_master_research" / "machine_master.csv"
    )
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out_dir = _ensure_dir(args.output_dir)

    lookup, master = _build_category_lookup(args.master_csv)
    frame = _prepare_frame()
    frame = frame[frame["hall_slug"].eq("kamata7")].copy()
    frame = _apply_category_lookup(frame, lookup)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")

    coverage = _category_coverage(frame)
    match_report = (
        frame.groupby("machine_name", as_index=False)
        .agg(
            machine_name_key=("machine_name_key", "first"),
            machine_type=("machine_type", _mode_or_first),
            machine_category=("machine_category", _mode_or_first),
            matched_master=("matched_master", "max"),
            n_machine_numbers=("machine_number", "nunique"),
            n_rows=("date", "size"),
            first_date=("date", "min"),
            last_date=("date", "max"),
        )
        .copy()
    )
    match_report["match_status"] = np.where(match_report["matched_master"], "matched", "unclassified")
    _write_csv(match_report, out_dir / "classification_report.csv")
    coverage_report_path = out_dir / "classification_report"
    _write_text(
        coverage_report_path.with_suffix(".md"),
        "\n".join(
            [
                "# Classification report",
                "",
                "## Coverage",
                _md_table(coverage),
                "",
                "## Unclassified samples",
                _md_table(match_report[match_report["match_status"].eq("unclassified")].head(30)),
                "",
            ]
        ),
    )

    branches: dict[str, dict[str, object]] = {}
    branches["coverage"] = (
        f"unique machine_names matched={int(match_report['matched_master'].sum())}/{int(match_report['machine_name'].nunique())} "
        f"({match_report['matched_master'].mean():.1%}), rows matched={frame['matched_master'].mean():.1%}, "
        f"unclassified unique_names={int((~match_report['matched_master']).sum())}"
    )
    branches["E"] = _branch_e(frame, out_dir)
    branches["F"] = _branch_f(frame, out_dir)
    summary_path = _build_summary_page(branches, out_dir)

    _write_root_docs(out_dir, coverage=coverage, coverage_report_path=coverage_report_path)

    print(out_dir)
    print(summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
