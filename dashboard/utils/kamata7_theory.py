"""Kamata7 theory dashboard compatibility helpers."""

from __future__ import annotations

from dashboard.utils.theory_engine import (
    THEORY_MIN_SAMPLE,
    attach_theory_axes,
    build_daily_event_summary,
    build_dd_kakuban_matrix,
    build_event_bucket_summary,
    build_event_kind_summary,
    classify_cooling_zone,
    classify_event_kind,
    classify_setting_family,
    classify_theory_segment,
    filter_theory_frame,
    infer_floor,
    infer_lr,
    is_event_day_series,
    load_hall_config,
    load_theory_frame,
    load_theory_registry,
    prepare_layout_segments,
    refutation_warnings as _refutation_warnings,
    resolve_hall_key,
    summarize_by,
    theory_coverage_rows as _theory_coverage_rows,
)

KAMATA7_CONFIG = load_hall_config("kamata7")
KAMATA7_EVENT_DIGITS = frozenset(KAMATA7_CONFIG.get("event_day", {}).get("digits", []))
KAMATA7_SEGMENT_ORDER = list(KAMATA7_CONFIG.get("segment_scheme", {}).get("order", []))


def _cooling_ranges(name: str) -> tuple[tuple[int, int], ...]:
    for zone in KAMATA7_CONFIG.get("cooling_zones", []):
        if zone.get("name") == name:
            return tuple(tuple(int(value) for value in pair) for pair in zone.get("ranges", []))
    return ()


COOLING_ZONES_VARIABLE = _cooling_ranges("variable")
COOLING_ZONES_STRUCTURAL = _cooling_ranges("structural")
SEGMENT_LABELS = dict(KAMATA7_CONFIG.get("segment_scheme", {}).get("labels", {}))
COOLING_ZONE_LABELS = {
    zone.get("name", "unknown"): zone.get("label", zone.get("name", "unknown"))
    for zone in KAMATA7_CONFIG.get("cooling_zones", [])
}
COOLING_ZONE_LABELS.setdefault("outside", "対象外")
COOLING_ZONE_LABELS.setdefault("unknown", "不明")


def theory_coverage_rows() -> list[dict[str, str]]:
    return _theory_coverage_rows("kamata7")


def refutation_warnings() -> list[dict[str, str]]:
    return _refutation_warnings("kamata7")


__all__ = [
    "THEORY_MIN_SAMPLE",
    "KAMATA7_CONFIG",
    "KAMATA7_EVENT_DIGITS",
    "KAMATA7_SEGMENT_ORDER",
    "COOLING_ZONES_VARIABLE",
    "COOLING_ZONES_STRUCTURAL",
    "SEGMENT_LABELS",
    "COOLING_ZONE_LABELS",
    "attach_theory_axes",
    "build_daily_event_summary",
    "build_dd_kakuban_matrix",
    "build_event_bucket_summary",
    "build_event_kind_summary",
    "classify_cooling_zone",
    "classify_event_kind",
    "classify_setting_family",
    "classify_theory_segment",
    "filter_theory_frame",
    "infer_floor",
    "infer_lr",
    "is_event_day_series",
    "load_hall_config",
    "load_theory_frame",
    "load_theory_registry",
    "prepare_layout_segments",
    "refutation_warnings",
    "resolve_hall_key",
    "summarize_by",
    "theory_coverage_rows",
]
