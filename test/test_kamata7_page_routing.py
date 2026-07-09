from __future__ import annotations

from dashboard.config.constants import PAGE_DEFS
from dashboard.pages import page_21_kamata7_event_checks, page_22_kamata7_segments


def test_kamata7_split_pages_are_routed():
    assert callable(page_21_kamata7_event_checks.render)
    assert callable(page_22_kamata7_segments.render)
    page_keys = {page["key"] for page in PAGE_DEFS}
    assert "kamata7_event_checks" in page_keys
    assert "kamata7_segments" in page_keys
