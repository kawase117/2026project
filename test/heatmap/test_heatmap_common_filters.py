import sqlite3
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import Heatmap.heatmap_common as heatmap_common
from Heatmap.heatmap_common import load_coordinate_frame


def test_load_coordinate_frame_filters_by_hall_and_floor(tmp_path: Path) -> None:
    coords_path = tmp_path / "coords.csv"
    coords_path.write_text(
        "\n".join(
            [
                "hall_name,floor,machine_number,X,Y,display_x,display_y",
                "Target Hall,2F,1001,1,1,1,1",
                "Target Hall,3F,1002,2,2,2,2",
                "Other Hall,2F,2001,3,3,3,3",
            ]
        ),
        encoding="utf-8",
    )

    df = load_coordinate_frame(
        coords_path,
        hall_name="Target Hall",
        floor="3F",
    )

    assert list(df["machine_number"]) == [1002]
    assert df["hall_name"].tolist() == ["Target Hall"]
    assert df["floor"].tolist() == ["3F"]
    assert pd.api.types.is_integer_dtype(df["machine_number"])


def test_render_heatmap_page_stops_when_only_one_date_is_selected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    coords_path = tmp_path / "coords.csv"
    coords_path.write_text(
        "\n".join(
            [
                "hall_name,floor,machine_number,X,Y,display_x,display_y",
                "Target Hall,2F,1001,1,1,1,1",
            ]
        ),
        encoding="utf-8",
    )

    db_path = tmp_path / "sample.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE machine_detailed_results (
                date TEXT,
                machine_number INTEGER,
                machine_name TEXT,
                diff_coins_normalized REAL,
                games_normalized REAL,
                is_zorome INTEGER
            )
            """
        )
        conn.execute(
            """
            INSERT INTO machine_detailed_results
            VALUES ('20260101', 1001, 'Alpha', 123.0, 456.0, 0)
            """
        )
        conn.commit()

    warnings: list[str] = []

    class _DummyColumn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def _columns(widths):
        count = widths if isinstance(widths, int) else len(widths)
        return tuple(_DummyColumn() for _ in range(count))

    monkeypatch.setattr(
        heatmap_common,
        "st",
        SimpleNamespace(
            markdown=lambda *args, **kwargs: None,
            error=lambda *args, **kwargs: pytest.fail("error() should not be called"),
            warning=lambda msg: warnings.append(msg),
            caption=lambda *args, **kwargs: None,
            stop=lambda: (_ for _ in ()).throw(RuntimeError("stopped")),
            columns=_columns,
            date_input=lambda *args, **kwargs: date(2026, 1, 1),
            radio=lambda *args, **kwargs: pytest.fail("radio() should not be called"),
            plotly_chart=lambda *args, **kwargs: pytest.fail("plotly_chart() should not be called"),
            metric=lambda *args, **kwargs: None,
            tabs=lambda *args, **kwargs: pytest.fail("tabs() should not be called"),
            dataframe=lambda *args, **kwargs: pytest.fail("dataframe() should not be called"),
            multiselect=lambda *args, **kwargs: [],
        ),
    )

    heatmap_common.render_heatmap_page(
        title="Target Hall 2F 驟咲ｽｮ蝗ｳ",
        subtitle="test",
        coords_file=str(coords_path),
        db_path=str(db_path),
        date_key="date_key",
        metric_key="metric_key",
        default_start_date=date(2026, 1, 1),
        hall_name="Target Hall",
        floor="2F",
    )

    assert warnings == ["開始日と終了日を両方選択してください"]


def test_render_heatmap_page_uses_provided_date_range_without_date_input(
    tmp_path: Path,
    monkeypatch,
) -> None:
    coords_path = tmp_path / "coords.csv"
    coords_path.write_text(
        "\n".join(
            [
                "hall_name,floor,machine_number,X,Y,display_x,display_y",
                "Target Hall,2F,1001,1,1,1,1",
            ]
        ),
        encoding="utf-8",
    )

    db_path = tmp_path / "sample.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE machine_detailed_results (
                date TEXT,
                machine_number INTEGER,
                machine_name TEXT,
                diff_coins_normalized REAL,
                games_normalized REAL,
                is_zorome INTEGER
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO machine_detailed_results
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("20260101", 1001, "Alpha", 10.0, 100.0, 0),
                ("20260102", 1001, "Alpha", 30.0, 120.0, 0),
            ],
        )
        conn.commit()

    class _DummyColumn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _DummyTab:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    captured = {}

    def _columns(widths):
        count = widths if isinstance(widths, int) else len(widths)
        return tuple(_DummyColumn() for _ in range(count))

    monkeypatch.setattr(
        heatmap_common,
        "st",
        SimpleNamespace(
            markdown=lambda *args, **kwargs: None,
            error=lambda *args, **kwargs: pytest.fail("error() should not be called"),
            warning=lambda *args, **kwargs: pytest.fail("warning() should not be called"),
            caption=lambda *args, **kwargs: None,
            stop=lambda: (_ for _ in ()).throw(RuntimeError("stopped")),
            columns=_columns,
            date_input=lambda *args, **kwargs: pytest.fail("date_input() should not be called"),
            radio=lambda *args, **kwargs: "勝率(%)",
            metric=lambda *args, **kwargs: None,
            tabs=lambda labels: [_DummyTab(), _DummyTab(), _DummyTab()],
            dataframe=lambda *args, **kwargs: None,
            multiselect=lambda *args, **kwargs: [],
        ),
    )

    def fake_html(html: str, **kwargs) -> None:
        captured["html"] = html

    monkeypatch.setattr("streamlit.components.v1.html", fake_html)

    heatmap_common.render_heatmap_page(
        title="Target Hall 2F フロアヒートマップ",
        subtitle="test",
        coords_file=str(coords_path),
        db_path=str(db_path),
        date_key="date_key",
        metric_key="metric_key",
        default_start_date=date(2026, 1, 1),
        hall_name="Target Hall",
        floor="2F",
        date_range=(date(2026, 1, 1), date(2026, 1, 2)),
    )

    assert "machine-card" in captured["html"]
    assert "1001" in captured["html"]


def test_render_last_digit_highlight_renders_selected_and_missing_data(
    tmp_path: Path,
    monkeypatch,
) -> None:
    coords_path = tmp_path / "coords.csv"
    coords_path.write_text(
        "\n".join(
            [
                "hall_name,floor,machine_number,X,Y,display_x,display_y",
                "Target Hall,2F,1001,1,1,1,1",
                "Target Hall,2F,1100,2,1,2,1",
            ]
        ),
        encoding="utf-8",
    )

    db_path = tmp_path / "sample.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE machine_detailed_results (
                date TEXT,
                machine_number INTEGER,
                machine_name TEXT,
                diff_coins_normalized REAL,
                games_normalized REAL,
                is_zorome INTEGER
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO machine_detailed_results
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("20260105", 1001, "Alpha Latest", 50.0, 100.0, 0),
                ("20260105", 1100, "Beta Latest", -10.0, 90.0, 1),
                ("20251231", 1100, "Beta Old", 40.0, 80.0, 1),
            ],
        )
        conn.commit()

    captured = {}

    monkeypatch.setattr(
        heatmap_common,
        "st",
        SimpleNamespace(
            markdown=lambda *args, **kwargs: None,
            error=lambda *args, **kwargs: pytest.fail("error() should not be called"),
            warning=lambda *args, **kwargs: pytest.fail("warning() should not be called"),
            caption=lambda *args, **kwargs: None,
            stop=lambda: (_ for _ in ()).throw(RuntimeError("stopped")),
            multiselect=lambda *args, **kwargs: ["1"],
            columns=lambda *args, **kwargs: pytest.fail("columns() should not be called"),
            tabs=lambda *args, **kwargs: pytest.fail("tabs() should not be called"),
            dataframe=lambda *args, **kwargs: pytest.fail("dataframe() should not be called"),
            metric=lambda *args, **kwargs: None,
            radio=lambda *args, **kwargs: pytest.fail("radio() should not be called"),
        ),
    )

    def fake_html(html: str, **kwargs) -> None:
        captured["html"] = html

    monkeypatch.setattr("streamlit.components.v1.html", fake_html)

    heatmap_common.render_last_digit_highlight(
        title="Target Hall 2F 末尾ハイライト",
        coords_file=str(coords_path),
        db_path=str(db_path),
        hall_name="Target Hall",
        floor="2F",
        date_range=(date(2025, 12, 31), date(2026, 1, 5)),
        widget_key_suffix="target_2f",
    )

    assert "machine-card" in captured["html"]
    assert "1001" in captured["html"]
    assert "1100" in captured["html"]


def test_render_last_digit_highlight_mixes_real_and_missing_period_stats(
    tmp_path: Path,
    monkeypatch,
) -> None:
    coords_path = tmp_path / "coords.csv"
    coords_path.write_text(
        "\n".join(
            [
                "hall_name,floor,machine_number,X,Y,display_x,display_y",
                "Target Hall,2F,1001,1,1,1,1",
                "Target Hall,2F,1100,2,1,2,1",
            ]
        ),
        encoding="utf-8",
    )

    db_path = tmp_path / "sample.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE machine_detailed_results (
                date TEXT,
                machine_number INTEGER,
                machine_name TEXT,
                diff_coins_normalized REAL,
                games_normalized REAL,
                is_zorome INTEGER
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO machine_detailed_results
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("20260102", 1001, "Alpha Latest", 50.0, 100.0, 0),
                ("20251231", 1100, "Beta Latest", -20.0, 90.0, 1),
            ],
        )
        conn.commit()

    captured = {}

    monkeypatch.setattr(
        heatmap_common,
        "st",
        SimpleNamespace(
            markdown=lambda *args, **kwargs: None,
            error=lambda *args, **kwargs: pytest.fail("error() should not be called"),
            warning=lambda *args, **kwargs: pytest.fail("warning() should not be called"),
            caption=lambda *args, **kwargs: None,
            stop=lambda: (_ for _ in ()).throw(RuntimeError("stopped")),
            multiselect=lambda *args, **kwargs: [],
            columns=lambda *args, **kwargs: pytest.fail("columns() should not be called"),
            tabs=lambda *args, **kwargs: pytest.fail("tabs() should not be called"),
            dataframe=lambda *args, **kwargs: pytest.fail("dataframe() should not be called"),
            metric=lambda *args, **kwargs: None,
            radio=lambda *args, **kwargs: pytest.fail("radio() should not be called"),
        ),
    )

    def fake_html(html: str, **kwargs) -> None:
        captured["html"] = html

    monkeypatch.setattr("streamlit.components.v1.html", fake_html)

    heatmap_common.render_last_digit_highlight(
        title="Target Hall 2F 末尾ハイライト",
        coords_file=str(coords_path),
        db_path=str(db_path),
        hall_name="Target Hall",
        floor="2F",
        date_range=(date(2026, 1, 1), date(2026, 1, 2)),
        widget_key_suffix="target_2f_mixed",
    )

    html = captured["html"]
    assert "machine-card" in html
    assert "1001" in html
    assert "1100" in html
    assert "N/A" in html
