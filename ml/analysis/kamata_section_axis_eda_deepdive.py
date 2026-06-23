from __future__ import annotations

import argparse
import calendar
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kruskal, mannwhitneyu
from statsmodels.stats.multitest import fdrcorrection

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.analysis.kamata_corner_mirror_analysis import _read_coordinates, _read_machine_master_flags, _resolve_hall_label
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
    is_kamata_event_day,
)
from ml.analysis.kamata_weekday_event_axis_payoutrate_deepdive import (
    _ensure_dir,
    _fmt,
    _md_table,
    _mwu,
    _write_csv,
    _write_text,
    compute_payoutrate_pct,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = PROJECT_ROOT / "tmp" / "kamata_section_axis_eda_deepdive"
MASTER_CSV = PROJECT_ROOT / "document" / "machine_master_research" / "machine_list_for_research.csv"
MIN_ENTITY_DATES_DEFAULT = 10
CATEGORY_ORDER = ["A", "AT", "unclassified"]
AXIS_SPECS = [
    ("dd", "DD", [str(i) for i in range(1, 32)]),
    ("weekday", "weekday", ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
    ("is_event_day", "is_event_day", ["0", "1"]),
]


@dataclass(frozen=True)
class HallSpec:
    hall_slug: str
    hall_name: str
    floor: str
    db_path: Path
    coords_path: Path


def _normalize_text(value: object) -> str:
    text = "" if pd.isna(value) else str(value)
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[^\w]+", "", text, flags=re.UNICODE)


def _machine_category(machine_type: object) -> str:
    text = "" if pd.isna(machine_type) else str(machine_type).strip()
    if text in {"ノーマル", "Aタイプ", "A+AT", "A+ART"}:
        return "A"
    if text in {"AT", "ART", "スマスロ", "AT(擬似ノーマル)"}:
        return "AT"
    return "unclassified"


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
    )
    conflict = dup[dup["n_categories"] > 1].copy()
    if not conflict.empty:
        raise ValueError("machine_master_research contains conflicting categories after normalization")

    lookup = work.drop_duplicates("machine_name_key").set_index("machine_name_key")["machine_category"].to_dict()
    return lookup, work


def _attach_fdr(summary: pd.DataFrame, *, p_col: str, q_col: str) -> pd.DataFrame:
    out = summary.copy()
    out[q_col] = np.nan
    valid = pd.to_numeric(out[p_col], errors="coerce").notna()
    if valid.any():
        _reject, qvals = fdrcorrection(pd.to_numeric(out.loc[valid, p_col], errors="coerce").to_numpy(dtype=float))
        out.loc[valid, q_col] = qvals
    return out


def _sort_key(values: pd.Series, axis: str) -> pd.Series:
    if axis == "weekday":
        order = {label: idx for idx, label in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])}
        return values.astype(str).map(lambda x: order.get(x, 99)).astype(float)
    if axis == "dd":
        return pd.to_numeric(values, errors="coerce").fillna(999).astype(float)
    if axis == "is_event_day":
        return values.astype(str).map({"0": 0, "1": 1}).fillna(99).astype(float)
    if axis == "section":
        return values.astype(str)
    return values.astype(str)


def _make_hall_specs(*, include_kamata1: bool) -> list[HallSpec]:
    specs = [
        HallSpec(
            hall_slug="kamata7",
            hall_name=infer_hall_name(Path(DEFAULT_COORDS_7_2F), floor="2F"),
            floor="2F",
            db_path=Path(DEFAULT_DB_7),
            coords_path=Path(DEFAULT_COORDS_7_2F),
        ),
        HallSpec(
            hall_slug="kamata7",
            hall_name=infer_hall_name(Path(DEFAULT_COORDS_7_3F), floor="3F"),
            floor="3F",
            db_path=Path(DEFAULT_DB_7),
            coords_path=Path(DEFAULT_COORDS_7_3F),
        ),
    ]
    if include_kamata1:
        specs.append(
            HallSpec(
                hall_slug="kamata1",
                hall_name=infer_hall_name(Path(DEFAULT_COORDS_1), floor="2F"),
                floor="2F",
                db_path=Path(DEFAULT_DB_1),
                coords_path=Path(DEFAULT_COORDS_1),
            )
        )
    return specs


def _prepare_frame(spec: HallSpec, *, category_lookup: dict[str, str], min_entity_dates: int) -> pd.DataFrame:
    frame = _build_segment_frame(
        SegmentSpec(
            hall_slug=spec.hall_slug,
            hall_name=spec.hall_name,
            floor=spec.floor,
            db_path=spec.db_path,
            coords_path=spec.coords_path,
        )
    ).copy()
    frame["hall_slug"] = spec.hall_slug
    frame["floor"] = spec.floor
    frame["hall_label"] = _resolve_hall_label(spec.hall_name, spec.coords_path)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["machine_number"] = pd.to_numeric(frame["machine_number"], errors="coerce").astype("Int64")
    frame["machine_name"] = frame["machine_name"].astype(str)
    frame["section"] = frame["section"].astype(str)
    frame["machine_name_key"] = frame["machine_name"].map(_normalize_text)
    frame["machine_category"] = frame["machine_name_key"].map(category_lookup).fillna("unclassified")
    frame["machine_type"] = frame["machine_category"]
    frame["matched_master"] = frame["machine_name_key"].isin(category_lookup)
    frame["weekday"] = frame["date"].dt.dayofweek.map(lambda x: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][int(x)] if pd.notna(x) else None)
    frame["dd"] = frame["date"].dt.day.astype("Int64").astype(str)
    frame["is_event_day"] = frame["date"].map(is_kamata_event_day).astype(int).astype(str)
    frame["payoutrate_pct"] = [
        compute_payoutrate_pct(diff, games)
        for diff, games in zip(frame["diff_coins_normalized"], frame["games_normalized"], strict=False)
    ]
    frame["hit_104"] = (pd.to_numeric(frame["payoutrate_pct"], errors="coerce") >= 104.0).astype(float)
    frame["entity_n_dates"] = frame.groupby("machine_number")["date"].transform("nunique").astype(int)
    frame = frame[frame["entity_n_dates"] >= int(min_entity_dates)].copy()
    frame["cell_key"] = frame["section"].astype(str)
    frame["row_id"] = np.arange(len(frame))
    return frame


def _section_category_coverage(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (hall_slug, floor, section), group in frame.groupby(["hall_slug", "floor", "section"], dropna=False, sort=False):
        machine_level = (
            group.groupby("machine_number", as_index=False)
            .agg(
                machine_name=("machine_name", "first"),
                machine_category=("machine_category", lambda s: s.dropna().mode().iloc[0] if not s.dropna().mode().empty else s.dropna().iloc[0] if not s.dropna().empty else "unclassified"),
                entity_n_dates=("entity_n_dates", "max"),
            )
            .copy()
        )
        counts = machine_level["machine_category"].value_counts(normalize=True).to_dict()
        row = {
            "hall_slug": hall_slug,
            "floor": floor,
            "section": section,
            "n_machine_numbers": int(machine_level["machine_number"].nunique()),
            "n_a": int((machine_level["machine_category"] == "A").sum()),
            "n_at": int((machine_level["machine_category"] == "AT").sum()),
            "n_unclassified": int((machine_level["machine_category"] == "unclassified").sum()),
            "a_share": float(counts.get("A", 0.0)),
            "at_share": float(counts.get("AT", 0.0)),
            "unclassified_share": float(counts.get("unclassified", 0.0)),
        }
        row["dominant_category"] = max({"A": row["a_share"], "AT": row["at_share"], "unclassified": row["unclassified_share"]}, key=lambda k: row[f"{k.lower()}_share"])
        row["dominant_share"] = float(max(row["a_share"], row["at_share"], row["unclassified_share"]))
        row["near_pure_90"] = bool(row["dominant_share"] >= 0.9)
        rows.append(row)
    return pd.DataFrame(rows)


def _section_category_mixture_summary(coverage: pd.DataFrame) -> pd.DataFrame:
    if coverage.empty:
        return pd.DataFrame(
            columns=[
                "hall_slug",
                "floor",
                "n_sections",
                "pure_90plus_sections",
                "mixed_sections",
                "mixed_share",
                "avg_dominant_share",
            ]
        )
    rows = []
    for (hall_slug, floor), group in coverage.groupby(["hall_slug", "floor"], dropna=False, sort=False):
        rows.append(
            {
                "hall_slug": hall_slug,
                "floor": floor,
                "n_sections": int(len(group)),
                "pure_90plus_sections": int(group["near_pure_90"].sum()),
                "mixed_sections": int((~group["near_pure_90"]).sum()),
                "mixed_share": float((~group["near_pure_90"]).mean()),
                "avg_dominant_share": float(group["dominant_share"].mean()),
            }
        )
    return pd.DataFrame(rows)


def _global_kw(frame: pd.DataFrame, *, axis_col: str, metric_col: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (hall_slug, floor, section), group in frame.groupby(["hall_slug", "floor", "section"], dropna=False, sort=False):
        labels = [label for label in group[axis_col].dropna().astype(str).unique().tolist()]
        labels = sorted(labels, key=lambda value: _sort_key(pd.Series([value]), axis_col).iloc[0])
        groups = [pd.to_numeric(group.loc[group[axis_col].astype(str).eq(label), metric_col], errors="coerce").dropna().astype(float) for label in labels]
        groups = [g for g in groups if len(g) > 0]
        if len(groups) < 2:
            p_value = float("nan")
            h_value = float("nan")
        else:
            try:
                h_value, p_value = kruskal(*groups)
            except ValueError:
                h_value, p_value = float("nan"), float("nan")
        rows.append(
            {
                "hall_slug": hall_slug,
                "floor": floor,
                "section": section,
                "axis": axis_col,
                "metric": metric_col,
                "n_groups": int(len(groups)),
                "n_rows": int(len(group)),
                "h_stat": h_value,
                "p_value": p_value,
            }
        )
    out = pd.DataFrame(rows)
    return _attach_fdr(out, p_col="p_value", q_col="q_value")


def _cell_vs_rest(frame: pd.DataFrame, *, axis_col: str, metric_col: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (hall_slug, floor, section), group in frame.groupby(["hall_slug", "floor", "section"], dropna=False, sort=False):
        labels = [label for label in group[axis_col].dropna().astype(str).unique().tolist()]
        labels = sorted(labels, key=lambda value: _sort_key(pd.Series([value]), axis_col).iloc[0])
        for label in labels:
            cell = pd.to_numeric(group.loc[group[axis_col].astype(str).eq(label), metric_col], errors="coerce").dropna().astype(float)
            rest = pd.to_numeric(group.loc[~group[axis_col].astype(str).eq(label), metric_col], errors="coerce").dropna().astype(float)
            p_value = _mwu(cell, rest)
            cell_mean = float(cell.mean()) if len(cell) else np.nan
            rest_mean = float(rest.mean()) if len(rest) else np.nan
            cell_median = float(cell.median()) if len(cell) else np.nan
            rest_median = float(rest.median()) if len(rest) else np.nan
            delta = cell_mean - rest_mean if np.isfinite(cell_mean) and np.isfinite(rest_mean) else np.nan
            rest_std = float(rest.std(ddof=0)) if len(rest) else np.nan
            zscore = delta / rest_std if np.isfinite(delta) and np.isfinite(rest_std) and not np.isclose(rest_std, 0.0) else np.nan
            rows.append(
                {
                    "hall_slug": hall_slug,
                    "floor": floor,
                    "section": section,
                    "axis": axis_col,
                    "metric": metric_col,
                    "axis_value": label,
                    "cell_mean": cell_mean,
                    "rest_mean": rest_mean,
                    "cell_median": cell_median,
                    "rest_median": rest_median,
                    "delta": delta,
                    "zscore": zscore,
                    "cell_n": int(len(cell)),
                    "rest_n": int(len(rest)),
                    "cell_n_dates": int(group.loc[group[axis_col].astype(str).eq(label), "date"].nunique()),
                    "rest_n_dates": int(group.loc[~group[axis_col].astype(str).eq(label), "date"].nunique()),
                    "p_value": p_value,
                    "direction": "cell_higher" if np.isfinite(delta) and delta > 0 else "cell_lower" if np.isfinite(delta) and delta < 0 else "tie_or_nan",
                }
            )
    out = pd.DataFrame(rows)
    return _attach_fdr(out, p_col="p_value", q_col="q_value")


def _split_half_compare(frame: pd.DataFrame, *, axis_col: str, metric_col: str) -> pd.DataFrame:
    full = _cell_vs_rest(frame, axis_col=axis_col, metric_col=metric_col)
    if full.empty:
        return full

    first_half, second_half, cutoff = _split_frame_by_date_half(frame)
    pieces = [("first_half", first_half), ("second_half", second_half)]
    merged = full.copy()
    for prefix, half in pieces:
        half_table = _cell_vs_rest(half, axis_col=axis_col, metric_col=metric_col)
        if half_table.empty:
            continue
        half_table = half_table.rename(
            columns={
                "cell_mean": f"{prefix}_cell_mean",
                "rest_mean": f"{prefix}_rest_mean",
                "cell_median": f"{prefix}_cell_median",
                "rest_median": f"{prefix}_rest_median",
                "delta": f"{prefix}_delta",
                "zscore": f"{prefix}_zscore",
                "cell_n": f"{prefix}_cell_n",
                "rest_n": f"{prefix}_rest_n",
                "cell_n_dates": f"{prefix}_cell_n_dates",
                "rest_n_dates": f"{prefix}_rest_n_dates",
                "p_value": f"{prefix}_p_value",
                "q_value": f"{prefix}_q_value",
                "direction": f"{prefix}_direction",
            }
        )
        merged = merged.merge(half_table, on=["hall_slug", "floor", "section", "axis", "metric", "axis_value"], how="left", validate="one_to_one")

    def _sig(series: pd.Series | None) -> pd.Series:
        if series is None:
            return pd.Series(False, index=merged.index)
        return pd.to_numeric(series, errors="coerce").lt(0.05)

    merged["full_sig"] = pd.to_numeric(merged["q_value"], errors="coerce").lt(0.05)
    merged["first_half_sig"] = _sig(merged.get("first_half_q_value"))
    merged["second_half_sig"] = _sig(merged.get("second_half_q_value"))
    merged["same_direction"] = (
        merged["direction"].astype(str).eq((merged.get("first_half_direction") if merged.get("first_half_direction") is not None else pd.Series(index=merged.index)).astype(str))
        & merged["direction"].astype(str).eq((merged.get("second_half_direction") if merged.get("second_half_direction") is not None else pd.Series(index=merged.index)).astype(str))
    )
    merged["stable"] = merged["full_sig"] & merged["first_half_sig"] & merged["second_half_sig"] & merged["same_direction"]
    merged["split_half_cutoff"] = cutoff
    return merged


def _cell_summary(frame: pd.DataFrame, *, axis_col: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (hall_slug, floor, section, axis_value), group in frame.groupby(["hall_slug", "floor", "section", axis_col], dropna=False, sort=False):
        machine_level = (
            group.groupby("machine_number", as_index=False)
            .agg(
                machine_name=("machine_name", "first"),
                machine_category=("machine_category", lambda s: s.dropna().mode().iloc[0] if not s.dropna().mode().empty else s.dropna().iloc[0] if not s.dropna().empty else "unclassified"),
                entity_n_dates=("entity_n_dates", "max"),
            )
            .copy()
        )
        entity_n_dates = pd.to_numeric(machine_level["entity_n_dates"], errors="coerce")
        rows.append(
            {
                "hall_slug": hall_slug,
                "floor": floor,
                "section": section,
                "axis": axis_col,
                "axis_value": axis_value,
                "n_rows": int(len(group)),
                "cell_n_dates": int(group["date"].nunique()),
                "n_machine_numbers": int(group["machine_number"].nunique()),
                "entity_n_dates_min": int(entity_n_dates.min()) if entity_n_dates.notna().any() else np.nan,
                "entity_n_dates_median": float(entity_n_dates.median()) if entity_n_dates.notna().any() else np.nan,
                "entity_n_dates_max": int(entity_n_dates.max()) if entity_n_dates.notna().any() else np.nan,
                "machine_category_a_share": float((machine_level["machine_category"] == "A").mean()) if len(machine_level) else np.nan,
                "machine_category_at_share": float((machine_level["machine_category"] == "AT").mean()) if len(machine_level) else np.nan,
                "machine_category_unclassified_share": float((machine_level["machine_category"] == "unclassified").mean()) if len(machine_level) else np.nan,
                "hit_104": float(group["hit_104"].mean()),
                "diff_mean": float(pd.to_numeric(group["diff_coins_normalized"], errors="coerce").mean()),
                "diff_median": float(pd.to_numeric(group["diff_coins_normalized"], errors="coerce").median()),
                "payoutrate_mean": float(pd.to_numeric(group["payoutrate_pct"], errors="coerce").mean()),
                "payoutrate_median": float(pd.to_numeric(group["payoutrate_pct"], errors="coerce").median()),
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out[axis_col] = out["axis_value"]
    out = out.sort_values(["hall_slug", "floor", "section", "axis", axis_col], key=lambda s: _sort_key(s, "section"), na_position="last").reset_index(drop=True)
    return out


def _machine_concentration_check(frame: pd.DataFrame, *, axis_col: str, axis_value: str, section: str, metric_col: str = "diff_coins_normalized") -> dict[str, object]:
    cell = frame[(frame["section"].astype(str).eq(str(section))) & (frame[axis_col].astype(str).eq(str(axis_value)))].copy()
    if cell.empty:
        return {
            "hall_slug": frame["hall_slug"].iloc[0] if len(frame) else "",
            "floor": frame["floor"].iloc[0] if len(frame) else "",
            "section": section,
            "axis": axis_col,
            "axis_value": axis_value,
            "top_machine_share": np.nan,
            "top_machine_number": pd.NA,
            "top_machine_name": pd.NA,
            "top_machine_diff_sum": np.nan,
            "cell_diff_sum": np.nan,
            "flagged": False,
        }
    machine_diff = (
        cell.groupby(["machine_number", "machine_name"], as_index=False)
        .agg(
            machine_diff_sum=(metric_col, "sum"),
            machine_diff_mean=(metric_col, "mean"),
            machine_diff_median=(metric_col, "median"),
            machine_rows=(metric_col, "size"),
        )
        .copy()
    )
    denom = float(machine_diff["machine_diff_sum"].abs().sum())
    top = machine_diff.loc[machine_diff["machine_diff_sum"].abs().idxmax()].to_dict()
    top_share = float(abs(top["machine_diff_sum"]) / denom) if denom > 0 else np.nan
    return {
        "hall_slug": cell["hall_slug"].iloc[0],
        "floor": cell["floor"].iloc[0],
        "section": section,
        "axis": axis_col,
        "axis_value": axis_value,
        "top_machine_share": top_share,
        "top_machine_number": int(top["machine_number"]),
        "top_machine_name": str(top["machine_name"]),
        "top_machine_diff_sum": float(top["machine_diff_sum"]),
        "top_machine_diff_mean": float(top["machine_diff_mean"]),
        "top_machine_diff_median": float(top["machine_diff_median"]),
        "top_machine_rows": int(top["machine_rows"]),
        "cell_diff_sum": float(machine_diff["machine_diff_sum"].sum()),
        "cell_diff_abs_sum": float(denom),
        "flagged": bool(np.isfinite(top_share) and top_share >= 0.35),
    }


def _recompute_without_machine(frame: pd.DataFrame, *, axis_col: str, axis_value: str, section: str, machine_number: int, metric_col: str) -> dict[str, object]:
    cell = frame[(frame["section"].astype(str).eq(str(section))) & (frame[axis_col].astype(str).eq(str(axis_value)))].copy()
    cell = cell[cell["machine_number"].astype(int).ne(int(machine_number))].copy()
    rest = frame[(frame["section"].astype(str).eq(str(section))) & (~frame[axis_col].astype(str).eq(str(axis_value)))].copy()
    cell_series = pd.to_numeric(cell[metric_col], errors="coerce").dropna().astype(float)
    rest_series = pd.to_numeric(rest[metric_col], errors="coerce").dropna().astype(float)
    p_value = _mwu(cell_series, rest_series)
    cell_mean = float(cell_series.mean()) if len(cell_series) else np.nan
    rest_mean = float(rest_series.mean()) if len(rest_series) else np.nan
    delta = cell_mean - rest_mean if np.isfinite(cell_mean) and np.isfinite(rest_mean) else np.nan
    rest_std = float(rest_series.std(ddof=0)) if len(rest_series) else np.nan
    zscore = delta / rest_std if np.isfinite(delta) and np.isfinite(rest_std) and not np.isclose(rest_std, 0.0) else np.nan
    return {
        "cell_rows_after_exclusion": int(len(cell_series)),
        "cell_mean_after_exclusion": cell_mean,
        "cell_median_after_exclusion": float(cell_series.median()) if len(cell_series) else np.nan,
        "delta_after_exclusion": delta,
        "zscore_after_exclusion": zscore,
        "p_value_after_exclusion": p_value,
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    _ensure_dir(path.parent)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_hall(spec: HallSpec, *, category_lookup: dict[str, str], min_entity_dates: int, out_dir: Path) -> dict[str, pd.DataFrame]:
    frame = _prepare_frame(spec, category_lookup=category_lookup, min_entity_dates=min_entity_dates)
    hall_dir = _ensure_dir(out_dir / f"{spec.hall_slug}_{spec.floor}")

    coverage = _section_category_coverage(frame)
    coverage_summary = _section_category_mixture_summary(coverage)
    _write_csv(coverage, hall_dir / "section_category_coverage.csv")
    _write_csv(coverage_summary, hall_dir / "section_category_mixture_summary.csv")

    summary_tables: list[pd.DataFrame] = []
    kw_tables: list[pd.DataFrame] = []
    compare_tables: list[pd.DataFrame] = []
    split_tables: list[pd.DataFrame] = []
    concentration_rows: list[dict[str, object]] = []
    exclusion_rows: list[dict[str, object]] = []

    for axis_col, axis_label, labels in AXIS_SPECS:
        axis_frame = frame[frame[axis_col].notna()].copy()
        if axis_frame.empty:
            continue

        cell_summary = _cell_summary(axis_frame, axis_col=axis_col)
        summary_tables.append(cell_summary)

        kw_diff = _global_kw(axis_frame, axis_col=axis_col, metric_col="diff_coins_normalized")
        kw_pay = _global_kw(axis_frame, axis_col=axis_col, metric_col="payoutrate_pct")
        kw_tables.append(kw_diff.assign(metric_label="diff_coins_normalized"))
        kw_tables.append(kw_pay.assign(metric_label="payoutrate_pct"))

        compare_diff = _cell_vs_rest(axis_frame, axis_col=axis_col, metric_col="diff_coins_normalized")
        compare_pay = _cell_vs_rest(axis_frame, axis_col=axis_col, metric_col="payoutrate_pct")
        compare_diff = compare_diff.assign(metric_label="diff_coins_normalized")
        compare_pay = compare_pay.assign(metric_label="payoutrate_pct")
        compare_tables.extend([compare_diff, compare_pay])

        split_diff = _split_half_compare(axis_frame, axis_col=axis_col, metric_col="diff_coins_normalized")
        split_pay = _split_half_compare(axis_frame, axis_col=axis_col, metric_col="payoutrate_pct")
        split_diff = split_diff.assign(metric_label="diff_coins_normalized")
        split_pay = split_pay.assign(metric_label="payoutrate_pct")
        split_tables.extend([split_diff, split_pay])

        # Concentration checks for diff-sensitive cells only.
        sig_cells = compare_diff[pd.to_numeric(compare_diff["q_value"], errors="coerce").lt(0.05)].copy()
        for _, row in sig_cells.iterrows():
            check = _machine_concentration_check(axis_frame, axis_col=axis_col, axis_value=str(row["axis_value"]), section=str(row["section"]))
            concentration_rows.append(check)
            if check["flagged"]:
                recalc = _recompute_without_machine(
                    axis_frame,
                    axis_col=axis_col,
                    axis_value=str(row["axis_value"]),
                    section=str(row["section"]),
                    machine_number=int(check["top_machine_number"]),
                    metric_col="diff_coins_normalized",
                )
                exclusion_rows.append(
                    {
                        **check,
                        **recalc,
                        "full_q_value": float(row["q_value"]) if pd.notna(row["q_value"]) else np.nan,
                        "full_delta": float(row["delta"]) if pd.notna(row["delta"]) else np.nan,
                        "full_zscore": float(row["zscore"]) if pd.notna(row["zscore"]) else np.nan,
                        "full_direction": str(row["direction"]),
                        "recomputed_sig": bool(pd.notna(recalc["p_value_after_exclusion"]) and pd.notna(row["q_value"]) and float(recalc["p_value_after_exclusion"]) < 0.05),
                    }
                )

    section_category_coverage = coverage
    section_category_mixture_summary = coverage_summary
    summary = pd.concat(summary_tables, ignore_index=True) if summary_tables else pd.DataFrame()
    kw_summary = pd.concat(kw_tables, ignore_index=True) if kw_tables else pd.DataFrame()
    compare = pd.concat(compare_tables, ignore_index=True) if compare_tables else pd.DataFrame()
    split_half = pd.concat(split_tables, ignore_index=True) if split_tables else pd.DataFrame()
    concentration = pd.DataFrame(concentration_rows)
    exclusion = pd.DataFrame(exclusion_rows)

    _write_csv(summary, hall_dir / "section_axis_cell_summary.csv")
    _write_csv(kw_summary, hall_dir / "section_axis_kw_summary.csv")
    _write_csv(compare, hall_dir / "section_axis_compare.csv")
    _write_csv(split_half, hall_dir / "section_axis_split_half.csv")
    _write_csv(concentration, hall_dir / "section_axis_concentration_checks.csv")
    _write_csv(exclusion, hall_dir / "section_axis_concentration_exclusion_recalc.csv")

    report: list[str] = []
    report.append(f"# {spec.hall_slug} {spec.floor} Section axis deepdive")
    report.append("")
    report.append("## Section category composition")
    report.append(_md_table(section_category_mixture_summary))
    report.append("")
    report.append("## Section coverage detail")
    report.append(_md_table(section_category_coverage.head(40)))
    report.append("")
    report.append("## Cell summary")
    report.append(_md_table(summary.head(40)))
    report.append("")
    report.append("## Global KW")
    report.append(_md_table(kw_summary.head(40)))
    report.append("")
    report.append("## Cell compare")
    report.append(_md_table(compare[["hall_slug", "floor", "section", "axis", "axis_value", "metric_label", "cell_mean", "rest_mean", "delta", "zscore", "p_value", "q_value", "direction"]].head(40)))
    report.append("")
    report.append("## Split-half")
    if not split_half.empty:
        cols = [
            "hall_slug",
            "floor",
            "section",
            "axis",
            "axis_value",
            "metric_label",
            "delta",
            "q_value",
            "first_half_delta",
            "first_half_q_value",
            "second_half_delta",
            "second_half_q_value",
            "same_direction",
            "stable",
        ]
        report.append(_md_table(split_half[cols].head(40)))
    else:
        report.append("No rows.")
    report.append("")
    report.append("## Concentration checks")
    if not concentration.empty:
        report.append(_md_table(concentration.head(40)))
    else:
        report.append("No significant cells.")
    report.append("")
    report.append("## Exclusion recalc")
    if not exclusion.empty:
        report.append(_md_table(exclusion.head(40)))
    else:
        report.append("No flagged cells.")
    report.append("")
    report.append("## Hall conclusion")
    near_pure = int(section_category_coverage["near_pure_90"].sum()) if not section_category_coverage.empty else 0
    mixed = int((~section_category_coverage["near_pure_90"]).sum()) if not section_category_coverage.empty else 0
    stable_sig = int(split_half["stable"].sum()) if not split_half.empty else 0
    report.append(
        f"- sections={len(section_category_coverage)}, near_pure_90={near_pure}, mixed={mixed}, stable_sig_cells={stable_sig}."
    )
    _write_text(hall_dir / "report.md", "\n".join(report))
    _write_json(
        hall_dir / "summary.json",
        {
            "hall_slug": spec.hall_slug,
            "floor": spec.floor,
            "hall_label": spec.hall_name,
            "n_rows": int(len(frame)),
            "n_sections": int(section_category_coverage["section"].nunique()) if not section_category_coverage.empty else 0,
            "n_mixed_sections": mixed,
            "n_near_pure_sections": near_pure,
            "n_sig_cells": int(pd.to_numeric(compare["q_value"], errors="coerce").lt(0.05).sum()) if not compare.empty else 0,
            "n_stable_cells": stable_sig,
        },
    )
    return {
        "frame": frame,
        "coverage": section_category_coverage,
        "coverage_summary": section_category_mixture_summary,
        "summary": summary,
        "kw_summary": kw_summary,
        "compare": compare,
        "split_half": split_half,
        "concentration": concentration,
        "exclusion": exclusion,
    }


def _build_overall_report(results: dict[str, dict[str, pd.DataFrame]]) -> str:
    lines: list[str] = ["# kamata section axis deepdive", ""]
    rows = []
    for hall_key, payload in results.items():
        coverage = payload["coverage"]
        summary = payload["summary"]
        compare = payload["compare"]
        split_half = payload["split_half"]
        rows.append(
            {
                "hall": hall_key,
                "sections": int(coverage["section"].nunique()) if not coverage.empty else 0,
                "near_pure_90": int(coverage["near_pure_90"].sum()) if not coverage.empty else 0,
                "mixed": int((~coverage["near_pure_90"]).sum()) if not coverage.empty else 0,
                "sig_cells": int(pd.to_numeric(compare["q_value"], errors="coerce").lt(0.05).sum()) if not compare.empty else 0,
                "stable_cells": int(split_half["stable"].sum()) if not split_half.empty else 0,
            }
        )
    lines.append(_md_table(pd.DataFrame(rows)))
    lines.append("")
    lines.append("Artifacts are written under `tmp/kamata_section_axis_eda_deepdive/`.")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Kamata section-axis deep dive with category prereq checks and split-half stability")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--master-csv", type=Path, default=MASTER_CSV)
    parser.add_argument("--min-entity-dates", type=int, default=MIN_ENTITY_DATES_DEFAULT)
    parser.add_argument("--include-kamata1", action="store_true", default=True)
    parser.add_argument("--skip-kamata1", action="store_true")
    args = parser.parse_args()

    out_dir = _ensure_dir(args.output_dir)
    category_lookup, _master = _build_category_lookup(args.master_csv)
    specs = _make_hall_specs(include_kamata1=bool(args.include_kamata1 and not args.skip_kamata1))

    results: dict[str, dict[str, pd.DataFrame]] = {}
    for spec in specs:
        hall_key = f"{spec.hall_slug}_{spec.floor}"
        results[hall_key] = _run_hall(spec, category_lookup=category_lookup, min_entity_dates=int(args.min_entity_dates), out_dir=out_dir)

    _write_text(out_dir / "report.md", _build_overall_report(results))


if __name__ == "__main__":
    main()
