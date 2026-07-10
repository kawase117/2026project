from __future__ import annotations

from dashboard.config.constants import PAGE_DEFS
from dashboard.pages import page_20_theory_verification


def test_theory_verification_page_is_routed():
    assert callable(page_20_theory_verification.render)
    page_keys = {page["key"] for page in PAGE_DEFS}
    assert "theory_verification" in page_keys
    assert "kamata7_event_checks" not in page_keys
    assert "kamata7_segments" not in page_keys
