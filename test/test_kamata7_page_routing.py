from __future__ import annotations

from dashboard.config.constants import PAGE_REGISTRY
from dashboard.pages import page_21_kamata7_event_checks, page_22_kamata7_segments


def test_kamata7_split_pages_are_routed():
    assert callable(page_21_kamata7_event_checks.render)
    assert callable(page_22_kamata7_segments.render)
    assert PAGE_REGISTRY[21]["file"] == "page_21_kamata7_event_checks"
    assert PAGE_REGISTRY[22]["file"] == "page_22_kamata7_segments"
