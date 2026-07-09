from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest


def test_compute_payout_rate_uses_three_yen_per_game_and_nan_for_zero_games() -> None:
    import dashboard.utils.daily_report as report

    frame = pd.DataFrame(
        {
            "games_normalized": [700, 0],
            "diff_coins_normalized": [300, -100],
        }
    )

    result = report.compute_payout_rate(frame)

    assert result.iloc[0] == pytest.approx(114.2857142857)
    assert pd.isna(result.iloc[1])


def test_add_hit104_flag_marks_boundary_values() -> None:
    import dashboard.utils.daily_report as report

    frame = pd.DataFrame(
        {
            "games_normalized": [1000, 1000, 1000],
            "diff_coins_normalized": [117, 120, 123],
        }
    )

    result = report.add_hit104_flag(frame)

    assert result["payout_rate"].tolist() == pytest.approx([103.9, 104.0, 104.1])
    assert result["hit104"].tolist() == [0, 1, 1]


def test_build_kpi_trend_frame_filters_to_window_and_keeps_target_day() -> None:
    import dashboard.utils.daily_report as report

    target_date = pd.Timestamp("2026-07-01")
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-05-31", "2026-06-02", "2026-06-30", "2026-07-01", "2026-07-02"]),
            "avg_diff_per_machine": [1, 2, 3, 4, 5],
            "win_rate": [0.1, 0.2, 0.3, 0.4, 0.5],
            "avg_games_per_machine": [100, 200, 300, 400, 500],
        }
    )

    result = report.build_kpi_trend_frame(frame, target_date, window_days=30)

    assert list(result["date"]) == list(pd.to_datetime(["2026-06-02", "2026-06-30", "2026-07-01"]))
    assert target_date in set(result["date"])
    assert pd.Timestamp("2026-05-31") not in set(result["date"])


def test_compute_diff_distribution_stats_returns_mean_median_and_count() -> None:
    import dashboard.utils.daily_report as report

    frame = pd.DataFrame({"diff_coins_normalized": [100, -20, 40, None]})

    stats = report.compute_diff_distribution_stats(frame)

    assert stats["mean"] == pytest.approx(40.0)
    assert stats["median"] == pytest.approx(40.0)
    assert stats["n"] == 3

    empty_stats = report.compute_diff_distribution_stats(pd.DataFrame())
    assert pd.isna(empty_stats["mean"])
    assert pd.isna(empty_stats["median"])
    assert empty_stats["n"] == 0


def test_build_kakuban_section_pivot_applies_min_group_size_and_matches_summary() -> None:
    import dashboard.utils.daily_report as report

    daily = pd.DataFrame(
        {
            "machine_number": [101, 102, 201, 202, 203],
            "games_normalized": [1000, 1000, 1000, 1000, 1000],
            "diff_coins_normalized": [100, 120, 50, -20, 200],
        }
    )
    layout = pd.DataFrame(
        {
            "machine_number": [101, 102, 201, 202, 203],
            "rank_from_min": [1, 1, 2, 2, 2],
            "section": ["A", "A", "B", "B", "B"],
        }
    )

    pivot = report.build_kakuban_section_pivot(daily, layout, min_group_size=3)
    small_cell = pivot.loc[(pivot["rank_from_min"] == 1) & (pivot["section"] == "A")].iloc[0]
    large_cell = pivot.loc[(pivot["rank_from_min"] == 2) & (pivot["section"] == "B")].iloc[0]

    assert small_cell["n"] == 2
    assert pd.isna(small_cell["avg_diff"])
    assert pd.isna(small_cell["win_rate"])
    assert pd.isna(small_cell["hit104_rate"])

    joined = daily.merge(layout, on="machine_number", how="inner")
    expected = report.summarize_group_performance(
        joined.loc[joined["rank_from_min"].eq(2) & joined["section"].eq("B")], "section", min_group_size=1
    ).iloc[0]
    assert large_cell["n"] == 3
    assert large_cell["avg_diff"] == pytest.approx(expected["avg_diff"])
    assert large_cell["win_rate"] == pytest.approx(expected["win_rate"])
    assert large_cell["hit104_rate"] == pytest.approx(expected["hit104_rate"])


def test_build_kakuban_section_pivot_defaults_to_single_cell_groups() -> None:
    import dashboard.utils.daily_report as report

    daily = pd.DataFrame(
        {
            "machine_number": [101, 102, 201, 202],
            "games_normalized": [1000, 1000, 1000, 1000],
            "diff_coins_normalized": [100, 120, 50, -20],
        }
    )
    layout = pd.DataFrame(
        {
            "machine_number": [101, 102, 201, 202],
            "rank_from_min": [1, 2, 1, 2],
            "section": ["A", "A", "B", "B"],
        }
    )

    pivot = report.build_kakuban_section_pivot(daily, layout)

    assert pivot["avg_diff"].notna().all()
    assert pivot["win_rate"].notna().all()
    assert pivot["hit104_rate"].notna().all()
    assert set(pivot["n"]) == {1}


def test_summarize_group_performance_excludes_small_groups() -> None:
    import dashboard.utils.daily_report as report

    frame = pd.DataFrame(
        {
            "machine_name": ["A", "A", "A", "B", "B"],
            "games_normalized": [1000, 1000, 1000, 1000, 1000],
            "diff_coins_normalized": [0, 0, 120, 400, 500],
        }
    )
    frame = report.add_hit104_flag(frame)

    result = report.summarize_group_performance(frame, "machine_name")

    assert list(result["machine_name"]) == ["B", "A"]
    row = result.loc[result["machine_name"].eq("A")].iloc[0]
    assert row["n"] == 3
    assert row["avg_diff"] == pytest.approx(40.0)
    assert row["avg_games"] == pytest.approx(1000.0)
    assert row["avg_payout_rate"] == pytest.approx(101.3333333333)
    assert row["win_rate"] == pytest.approx(1 / 3)
    assert row["hit104_rate"] == pytest.approx(1 / 3)

    ranking = report.summarize_group_performance(frame, "machine_name", min_group_size=3)
    assert list(ranking["machine_name"]) == ["A"]


def test_search_all_table_matches_machine_number_and_machine_name() -> None:
    import dashboard.utils.daily_report as report

    frame = pd.DataFrame(
        {
            "machine_number": [123, 456, 789],
            "machine_name": ["Alpha", "Beta 23", "Gamma"],
            "last_digit": ["3", "6", "9"],
            "diff_coins_normalized": [10, 20, 30],
            "games_normalized": [1000, 1000, 1000],
        }
    )

    result = report.filter_search_query(frame, "23")

    assert list(result["machine_number"]) == [123, 456]


def test_table_helpers_return_empty_frames_when_tables_are_missing(tmp_path: Path) -> None:
    import dashboard.utils.daily_report as report

    db_path = tmp_path / "sample.db"
    with sqlite3.connect(db_path) as con:
        con.execute(
            "CREATE TABLE machine_detailed_results (date TEXT, machine_number INTEGER, machine_name TEXT, last_digit TEXT, games_normalized INTEGER, diff_coins_normalized INTEGER)"
        )
        con.execute("INSERT INTO machine_detailed_results VALUES ('20260101', 101, 'A', '1', 1000, 100)")

    daily_frame = pd.DataFrame(
        {
            "machine_number": [101],
            "machine_name": ["A"],
            "games_normalized": [1000],
            "diff_coins_normalized": [100],
        }
    )
    layout = report.load_optional_table(str(db_path), "machine_layout")
    master = report.load_optional_table(str(db_path), "machine_master")

    assert layout.empty
    assert master.empty
    assert report.has_table(str(db_path), "machine_detailed_results") is True
    assert report.has_table(str(db_path), "machine_layout") is False
    assert report.build_layout_summary(daily_frame, layout, group_column="rank_from_min").empty
    assert report.build_segment_summary(daily_frame, master).empty


def test_format_rate_columns_renders_percent_and_integers() -> None:
    import dashboard.utils.daily_report as report

    frame = pd.DataFrame(
        {
            "n": [3],
            "avg_diff": [12.7],
            "avg_games": [1000.2],
            "avg_payout_rate": [104.1],
            "payout_rate": [103.9],
            "win_rate": [0.5],
            "hit104_count": [2],
            "hit104_rate": [0.75],
        }
    )

    formatted = report.format_rate_columns(frame)

    assert formatted.loc[0, "n"] == "3"
    assert formatted.loc[0, "avg_diff"] == "13"
    assert formatted.loc[0, "avg_games"] == "1000"
    assert formatted.loc[0, "avg_payout_rate"] == "104.1%"
    assert formatted.loc[0, "payout_rate"] == "103.9%"
    assert formatted.loc[0, "win_rate"] == "50.0%"
    assert formatted.loc[0, "hit104_count"] == "2"
    assert formatted.loc[0, "hit104_rate"] == "75.0%"


def test_build_table_display_keeps_numeric_sortable_columns_numeric() -> None:
    from dashboard.pages import page_18_daily_report

    frame = pd.DataFrame(
        {
            "machine_number": [101],
            "machine_name": ["A"],
            "payout_rate": [103.9],
            "win_rate": [0.5],
            "avg_diff": [12.7],
            "avg_games": [1000.2],
            "hit104_count": [2],
            "hit104_rate": [0.75],
        }
    )

    display_frame, column_config = page_18_daily_report._build_table_display(frame)

    assert display_frame["machine_number"].dtype.kind in "if"
    assert display_frame["payout_rate"].dtype.kind in "if"
    assert display_frame["win_rate"].dtype.kind in "if"
    assert display_frame.loc[0, "payout_rate"] == pytest.approx(103.9)
    assert display_frame.loc[0, "win_rate"] == pytest.approx(0.5)
    assert column_config["payout_rate"]["type_config"]["format"] == "%.1f%%"
    assert column_config["win_rate"]["type_config"]["format"] == "percent"
    assert column_config["avg_diff"]["type_config"]["format"] == "%d"


def test_render_heatmap_views_mirrors_multi_floor_tabs(monkeypatch: pytest.MonkeyPatch) -> None:
    from dashboard.pages import page_18_daily_report

    tab_log: list[list[str]] = []
    render_calls: list[tuple[str, tuple[date, date]]] = []

    class _Tab:
        def __init__(self, label: str) -> None:
            self.label = label

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        page_18_daily_report,
        "st",
        SimpleNamespace(
            tabs=lambda labels: tab_log.append(list(labels)) or [_Tab(label) for label in labels],
        ),
    )
    monkeypatch.setattr(
        page_18_daily_report,
        "_render_one_floor_heat",
        lambda csv_info, db_path, hall_name, hall_safe, target_date: render_calls.append(
            (csv_info["floor"], (target_date, target_date))
        ),
    )

    page_18_daily_report._render_heatmap_views(
        [{"path": "Heatmap/a.csv", "floor": "2F"}, {"path": "Heatmap/b.csv", "floor": "3F"}],
        "db/path.db",
        "Target Hall",
        "Target_Hall",
        __import__("datetime").date(2026, 1, 2),
    )

    assert tab_log == [["2F", "3F"]]
    assert render_calls == [
        ("2F", (__import__("datetime").date(2026, 1, 2), __import__("datetime").date(2026, 1, 2))),
        ("3F", (__import__("datetime").date(2026, 1, 2), __import__("datetime").date(2026, 1, 2))),
    ]


def test_page_registration_includes_daily_report() -> None:
    from dashboard.config.constants import PAGES
    from dashboard.pages import __all__ as page_exports

    assert any(page["key"] == "daily_report" for page in PAGES)
    assert "page_18_daily_report" in page_exports


def test_default_target_date_uses_jst(monkeypatch: pytest.MonkeyPatch) -> None:
    from dashboard.pages import page_18_daily_report
    from datetime import datetime as real_datetime, timezone
    from zoneinfo import ZoneInfo

    class _FakeDateTime:
        @staticmethod
        def now(tz=None):
            assert tz == ZoneInfo("Asia/Tokyo")
            return real_datetime(2026, 7, 2, 0, 30, tzinfo=timezone.utc)

        @staticmethod
        def combine(*args, **kwargs):
            return real_datetime.combine(*args, **kwargs)

    monkeypatch.setattr(page_18_daily_report, "datetime", _FakeDateTime)

    assert page_18_daily_report._default_target_date() == date(2026, 7, 1)


def test_render_metric_triplet_scales_percent_deltas(monkeypatch: pytest.MonkeyPatch) -> None:
    from dashboard.pages import page_18_daily_report

    calls: list[tuple[str, str, float, str]] = []

    class _Col:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        page_18_daily_report,
        "st",
        SimpleNamespace(
            columns=lambda n: [_Col() for _ in range(n)],
        ),
    )
    monkeypatch.setattr(
        page_18_daily_report,
        "metric_card_with_delta",
        lambda label, value, delta_value, delta_label, icon: calls.append((label, value, delta_value, delta_label)),
    )
    monkeypatch.setattr(
        page_18_daily_report,
        "metric_card",
        lambda label, value, icon: calls.append((label, value, 0.0, icon)),
    )

    page_18_daily_report._render_metric_triplet("勝率", 50.0, 40.0, 30.0, icon="📊", percent=True)

    assert calls[0] == ("勝率", "50.0%", 10.0, "pp vs 7日平均")
    assert calls[1] == ("勝率", "40.0%", 10.0, "pp vs 30日平均")
