from datetime import date
from types import SimpleNamespace

import pytest

from dashboard.pages import page_17_heatmap


class _Tab:
    def __init__(self, label: str, seen: list[str]) -> None:
        self.label = label
        self._seen = seen

    def __enter__(self):
        self._seen.append(f"enter:{self.label}")
        return self

    def __exit__(self, exc_type, exc, tb):
        self._seen.append(f"exit:{self.label}")
        return False


def test_render_uses_outer_tabs_and_forwards_date_range(monkeypatch) -> None:
    outer_labels: list[list[str]] = []
    helper_calls: list[tuple[str, tuple[date, date]]] = []

    def _tabs(labels):
        outer_labels.append(list(labels))
        return [_Tab(label, []) for label in labels]

    class _Col:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        page_17_heatmap,
        "st",
        SimpleNamespace(
            session_state={"hall_name": "Target Hall", "db_path": "db/path.db"},
            warning=lambda msg: pytest.fail(msg),
            info=lambda msg: pytest.fail(msg),
            caption=lambda msg: None,
            tabs=_tabs,
            date_input=lambda *args, **kwargs: (date(2026, 1, 1), date(2026, 1, 2)),
            multiselect=lambda *args, **kwargs: [],
            columns=lambda n: [_Col() for _ in range(n)],
        ),
    )
    monkeypatch.setattr(
        page_17_heatmap,
        "find_floor_csvs",
        lambda hall_name, project_root: [
            {"path": "Heatmap/a.csv", "floor": "2F"},
        ],
    )
    monkeypatch.setattr(
        page_17_heatmap,
        "_render_heatmap_views",
        lambda csvs, db_path, hall_name, hall_safe, date_range, weekdays, day_of_months: helper_calls.append(
            ("heatmap", date_range)
        ),
    )
    monkeypatch.setattr(
        page_17_heatmap,
        "_render_digit_views",
        lambda csvs, db_path, hall_name, hall_safe, date_range, weekdays, day_of_months: helper_calls.append(
            ("digit", date_range)
        ),
    )

    page_17_heatmap.render()

    assert outer_labels == [["ヒートマップ", "末尾ハイライト"]]
    assert helper_calls == [
        ("heatmap", (date(2026, 1, 1), date(2026, 1, 2))),
        ("digit", (date(2026, 1, 1), date(2026, 1, 2))),
    ]


def test_floor_helpers_use_inner_tabs_for_multiple_floors(monkeypatch) -> None:
    heatmap_calls: list[tuple] = []
    digit_calls: list[tuple] = []
    seen: list[str] = []
    tab_labels: list[list[str]] = []

    def _tabs(labels):
        tab_labels.append(list(labels))
        return [_Tab(label, seen) for label in labels]

    monkeypatch.setattr(
        page_17_heatmap,
        "st",
        SimpleNamespace(
            tabs=_tabs,
            warning=lambda msg: pytest.fail(msg),
            info=lambda msg: pytest.fail(msg),
            caption=lambda msg: None,
        ),
    )
    monkeypatch.setattr(
        page_17_heatmap,
        "_render_one_floor_heat",
        lambda csv_info, db_path, hall_name, hall_safe, date_range, weekdays, day_of_months: heatmap_calls.append(
            (csv_info, db_path, hall_name, hall_safe, date_range, weekdays, day_of_months)
        ),
    )
    monkeypatch.setattr(
        page_17_heatmap,
        "_render_one_floor_digit",
        lambda csv_info, db_path, hall_name, hall_safe, date_range, weekdays, day_of_months: digit_calls.append(
            (csv_info, db_path, hall_name, hall_safe, date_range, weekdays, day_of_months)
        ),
    )

    csvs = [
        {"path": "Heatmap/a.csv", "floor": "2F"},
        {"path": "Heatmap/b.csv", "floor": "3F"},
    ]
    date_range = (date(2026, 1, 1), date(2026, 1, 2))
    weekdays = None
    day_of_months = None

    page_17_heatmap._render_heatmap_views(csvs, "db/path.db", "Target Hall", "Target_Hall", date_range, weekdays, day_of_months)
    page_17_heatmap._render_digit_views(csvs, "db/path.db", "Target Hall", "Target_Hall", date_range, weekdays, day_of_months)

    assert tab_labels == [["2F", "3F"], ["2F", "3F"]]
    assert seen == ["enter:2F", "exit:2F", "enter:3F", "exit:3F", "enter:2F", "exit:2F", "enter:3F", "exit:3F"]
    assert heatmap_calls == [
        ({"path": "Heatmap/a.csv", "floor": "2F"}, "db/path.db", "Target Hall", "Target_Hall", date_range, weekdays, day_of_months),
        ({"path": "Heatmap/b.csv", "floor": "3F"}, "db/path.db", "Target Hall", "Target_Hall", date_range, weekdays, day_of_months),
    ]
    assert digit_calls == [
        ({"path": "Heatmap/a.csv", "floor": "2F"}, "db/path.db", "Target Hall", "Target_Hall", date_range, weekdays, day_of_months),
        ({"path": "Heatmap/b.csv", "floor": "3F"}, "db/path.db", "Target Hall", "Target_Hall", date_range, weekdays, day_of_months),
    ]
