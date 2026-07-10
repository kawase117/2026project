from __future__ import annotations


def test_new_explore_pages_are_registered_everywhere() -> None:
    from dashboard.config.constants import PAGE_DEFS
    from dashboard.main import PAGE_ROUTER as dashboard_router
    from dashboard.pages import __all__ as page_exports
    from dashboard.pages import page_11b_interaction_explorer, page_11c_axis_screening
    from main_app import PAGE_ROUTER as app_router

    page_keys = {page["key"] for page in PAGE_DEFS}
    assert {"interaction_explorer", "axis_screening"} <= page_keys
    assert "page_11b_interaction_explorer" in page_exports
    assert "page_11c_axis_screening" in page_exports
    assert callable(page_11b_interaction_explorer.render)
    assert callable(page_11c_axis_screening.render)
    assert set(dashboard_router) == set(app_router)
    assert "interaction_explorer" in dashboard_router
    assert "axis_screening" in dashboard_router
