from __future__ import annotations

from importlib import import_module

from .config import DEFAULT_DB_FALLBACK, RESULTS_DIR, SEGMENT_ORDER

__all__ = [
    "DEFAULT_DB_FALLBACK",
    "DEFAULT_DB_PATH",
    "RESULTS_DIR",
    "SEGMENT_ORDER",
    "build_gate_sensitivity",
    "build_report",
    "build_segment_daily_counts",
    "classify_seg",
    "is_event_day",
    "resolve_default_db_path",
    "run_gate_analysis",
]


def __getattr__(name: str):
    if name in {
        "DEFAULT_DB_PATH",
        "build_gate_sensitivity",
        "build_report",
        "build_segment_daily_counts",
        "classify_seg",
        "is_event_day",
        "resolve_default_db_path",
        "run_gate_analysis",
    }:
        _run_gate_analysis = import_module(".run_gate_analysis", __name__)
        return getattr(_run_gate_analysis, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
