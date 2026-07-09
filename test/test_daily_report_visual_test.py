from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest


def test_prev_next_date_navigation_updates_selected_day(monkeypatch: pytest.MonkeyPatch) -> None:
    from dashboard.pages import page_19_daily_report_visual_test as page

    state = {"target": date(2026, 7, 1)}

    class _Col:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def _button(label: str, **_: object) -> bool:
        return label == "前日へ"

    monkeypatch.setattr(
        page,
        "st",
        SimpleNamespace(
            columns=lambda n: [_Col() for _ in range(n)],
            button=_button,
            session_state=state,
        ),
    )

    result = page._step_target_date("target")

    assert result == date(2026, 6, 30)


def test_build_visual_group_frames_returns_expected_metric_columns() -> None:
    import dashboard.utils.daily_report as report

    daily = pd.DataFrame(
        {
            "machine_number": [101, 102, 201, 202],
            "machine_name": ["A", "A", "B", "B"],
            "last_digit": ["1", "2", "1", "2"],
            "games_normalized": [2000, 1800, 2100, 1900],
            "diff_coins_normalized": [300, 150, -50, 400],
        }
    )
    layout = pd.DataFrame(
        {
            "machine_number": [101, 102, 201, 202],
            "rank_from_min": [1, 2, 1, 2],
            "section": ["S1", "S1", "S2", "S2"],
        }
    )

    frames = report.build_visual_group_frames(daily, layout_frame=layout, master_frame=pd.DataFrame())

    assert set(frames) >= {"machine_name", "last_digit", "rank_from_min", "section"}
    assert list(frames["machine_name"].columns) == [
        "machine_name",
        "n",
        "avg_diff",
        "avg_games",
        "avg_payout_rate",
        "win_rate",
        "hit104_count",
        "hit104_rate",
    ]


def test_render_trend_and_histogram_charts_use_mocked_streamlit(monkeypatch: pytest.MonkeyPatch) -> None:
    from dashboard.pages import page_19_daily_report_visual_test as page

    plot_calls: list[object] = []

    monkeypatch.setattr(
        page,
        "st",
        SimpleNamespace(
            plotly_chart=lambda fig, **kwargs: plot_calls.append(fig),
            markdown=lambda *args, **kwargs: None,
            info=lambda *args, **kwargs: None,
        ),
    )

    trend_frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-29", "2026-06-30", "2026-07-01"]),
            "avg_diff_per_machine": [1.0, 2.0, 3.0],
            "win_rate": [0.1, 0.2, 0.3],
            "avg_games_per_machine": [100.0, 200.0, 300.0],
        }
    )
    daily_frame = pd.DataFrame(
        {
            "machine_number": [101, 102, 103],
            "games_normalized": [1000, 1100, 1200],
            "diff_coins_normalized": [100, -20, 140],
        }
    )

    page._render_kpi_trend_chart(trend_frame, date(2026, 7, 1))
    page._render_diff_histogram(daily_frame)

    assert len(plot_calls) == 2
    assert len(plot_calls[0].data) == 6


def test_render_emits_daily_highlight_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    from dashboard.pages import page_19_daily_report_visual_test as page

    written: list[object] = []

    class _Col:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    daily_df = pd.DataFrame(
        {
            "machine_number": [101, 102],
            "machine_name": ["A", "B"],
            "last_digit": ["1", "2"],
            "games_normalized": [2000, 1800],
            "diff_coins_normalized": [300, -100],
        }
    )
    hall_summary = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-30", "2026-07-01"]),
            "avg_diff_per_machine": [1.0, 2.0],
            "win_rate": [0.1, 0.2],
            "avg_games_per_machine": [100.0, 200.0],
        }
    )

    monkeypatch.setattr(
        page,
        "st",
        SimpleNamespace(
            session_state={
                "hall_name": "hall-a",
                "db_path": "dummy.db",
                "min_games": 0,
                "show_low_confidence": False,
            },
            markdown=lambda *args, **kwargs: None,
            caption=lambda *args, **kwargs: None,
            write=lambda value, **kwargs: written.append(value),
            info=lambda *args, **kwargs: None,
            warning=lambda *args, **kwargs: None,
            columns=lambda n: [_Col() for _ in range(n)],
            button=lambda *args, **kwargs: False,
            date_input=lambda *args, **kwargs: date(2026, 7, 1),
            plotly_chart=lambda *args, **kwargs: None,
            dataframe=lambda *args, **kwargs: None,
            text_input=lambda *args, **kwargs: "",
        ),
    )
    monkeypatch.setattr(page, "load_machine_detailed_by_date", lambda *args, **kwargs: daily_df.copy())
    monkeypatch.setattr(page, "load_daily_hall_summary", lambda *args, **kwargs: hall_summary.copy())
    monkeypatch.setattr(page, "apply_machine_filters", lambda frame, *_args, **_kwargs: frame.copy())
    monkeypatch.setattr(page, "find_floor_csvs", lambda *args, **kwargs: [])
    monkeypatch.setattr(page.daily_report_utils, "build_visual_group_frames", lambda *args, **kwargs: {})
    monkeypatch.setattr(page.daily_report_utils, "build_kpi_trend_frame", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(page.daily_report_utils, "load_optional_table", lambda *args, **kwargs: pd.DataFrame())

    page.render()

    assert any("讖溽ｨｮ蛻･" in str(value) for value in written)


def test_render_kakuban_section_heatmap_uses_mocked_streamlit(monkeypatch: pytest.MonkeyPatch) -> None:
    from dashboard.pages import page_19_daily_report_visual_test as page

    plot_calls: list[object] = []

    monkeypatch.setattr(
        page,
        "st",
        SimpleNamespace(
            plotly_chart=lambda fig, **kwargs: plot_calls.append(fig),
            markdown=lambda *args, **kwargs: None,
            info=lambda *args, **kwargs: None,
            selectbox=lambda *args, **kwargs: "avg_diff",
        ),
    )

    daily_frame = pd.DataFrame(
        {
            "machine_number": [101, 102, 201, 202, 203],
            "machine_name": ["A", "A", "B", "B", "B"],
            "games_normalized": [1000, 1000, 1000, 1000, 1000],
            "diff_coins_normalized": [100, 120, 50, -20, 200],
        }
    )
    layout_frame = pd.DataFrame(
        {
            "machine_number": [101, 102, 201, 202, 203],
            "rank_from_min": [1, 1, 2, 2, 2],
            "section": ["A", "A", "B", "B", "B"],
        }
    )

    page._render_kakuban_section_heatmap(daily_frame, layout_frame)

    assert len(plot_calls) == 1
    heatmap = plot_calls[0]
    assert heatmap.data[0].customdata[0][0] == "A"
    assert "機種名=" in heatmap.data[0].hovertemplate


def test_build_scatter_frame_keeps_numeric_axes() -> None:
    import dashboard.utils.daily_report as report

    frame = pd.DataFrame(
        {
            "machine_number": [101, 102],
            "machine_name": ["A", "B"],
            "games_normalized": [2000, 1500],
            "diff_coins_normalized": [300, -100],
        }
    )

    scatter = report.build_daily_scatter_frame(frame)

    assert list(scatter.columns) == [
        "machine_number",
        "machine_name",
        "games_normalized",
        "diff_coins_normalized",
        "payout_rate",
        "hit104",
    ]
    assert scatter["games_normalized"].dtype.kind in "if"
    assert scatter["diff_coins_normalized"].dtype.kind in "if"


def test_build_daily_highlight_summary_mentions_top_machine() -> None:
    import dashboard.utils.daily_report as report

    frame = pd.DataFrame(
        {
            "machine_name": ["A", "A", "B", "B"],
            "games_normalized": [2200, 2000, 1800, 1700],
            "diff_coins_normalized": [450, 300, -50, 80],
        }
    )

    summary = report.build_daily_highlight_summary(frame, machine_label="machine")

    assert "machine" in summary
    assert "A" in summary
    assert "avg_diff" in summary


def test_page_registration_includes_visual_test_page() -> None:
    from dashboard.config.constants import PAGE_DEFS
    from dashboard.pages import __all__ as page_exports

    assert any(page["key"] == "daily_report_visual_test" for page in PAGE_DEFS)
    assert "page_19_daily_report_visual_test" in page_exports
