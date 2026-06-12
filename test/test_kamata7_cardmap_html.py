"""generate_kamata7_cardmap_html.py の単体テスト"""

from __future__ import annotations

import sqlite3
import sys
from datetime import date
from pathlib import Path

import pandas as pd


sys.path.insert(0, str(Path(__file__).parent.parent / "Heatmap"))

import generate_kamata7_cardmap_html as km7  # noqa: E402
import heatmap_common as hm  # noqa: E402


def test_filter_machine_records_applies_weekday_and_day_filters() -> None:
    """曜日と月内日付の両方で絞り込めること。"""

    raw = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2026-06-01", "2026-06-02", "2026-06-05", "2026-06-08"]
            ),
            "machine_number": [1, 1, 1, 1],
            "diff_coins_normalized": [10, -5, 20, 30],
            "games_normalized": [1000, 1000, 1000, 1000],
        }
    )

    filtered = km7.filter_machine_records(
        raw,
        weekdays=[0, 4],
        day_of_months=[1, 5],
    )

    assert filtered["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-06-01",
        "2026-06-05",
    ]


def test_build_tone_thresholds_spreads_positively_skewed_values() -> None:
    """正に偏った値でも5段階に分散すること。"""

    values = pd.Series([100, 101, 102, 103, 104, 105, 106, 107, 108, 109])
    thresholds = km7.build_tone_thresholds(values)

    classes = [
        km7.classify_metric(value, thresholds)
        for value in [100, 102, 104, 106, 109]
    ]

    assert len(set(classes)) == 5


def test_build_machine_stats_computes_kaiwari_metrics() -> None:
    """平均機械割と機械割104以上率を集計できること。"""

    raw = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2026-06-01", "2026-06-02", "2026-06-03"]
            ),
            "machine_number": [100, 100, 100],
            "machine_name": ["A", "A", "A"],
            "diff_coins_normalized": [120, -60, 30],
            "games_normalized": [1000, 1000, 1000],
        }
    )

    stats = km7.build_machine_stats(raw)
    row = stats.iloc[0]

    assert row["avg_diff"] == 30
    assert row["win_rate"] == 66.66666666666666
    assert row["avg_kaiwari"] == 101.0
    assert row["hit104_rate"] == 33.33333333333333


def test_build_border_legend_reports_games_thresholds() -> None:
    """枠線の判例テキストが生成されること。"""

    legend = km7.build_border_legend((1200.0, 800.0, 400.0))

    assert "枠線" in legend
    assert "高G数" in legend
    assert "1200G" in legend


def test_render_last_digit_floor_section_uses_card_layout() -> None:
    """末尾ハイライト用のカードレイアウトが生成されること。"""

    frame = pd.DataFrame(
        {
            "machine_number": [101, 102],
            "machine_name": ["炎炎ノ消防隊", "カバネリ"],
            "X": [1, 2],
            "Y": [1, 1],
            "display_x": [1, 2],
            "display_y": [1, 1],
            "avg_diff": [10.0, -20.0],
            "win_rate": [60.0, 40.0],
            "avg_games": [1500.0, 800.0],
            "avg_kaiwari": [103.0, 98.5],
            "hit104_rate": [60.0, 0.0],
            "category": ["ゾロ目", "2"],
        }
    )

    html = km7.render_last_digit_floor_section(
        frame,
        floor_label="2F",
        floor_title="蒲田7 2F",
        filter_label="全日",
        selected_categories={"ゾロ目"},
    )

    assert "machine-card" in html
    assert "machine-name" in html
    assert "ゾロ目" in html


def test_render_last_digit_highlight_emits_card_html(tmp_path, monkeypatch) -> None:
    """末尾ハイライト表示が Plotly ではなくカードHTMLを出力すること。"""

    db_path = tmp_path / "kamata7.db"
    coords_path = tmp_path / "coords.csv"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE machine_detailed_results (
                date TEXT,
                machine_number INTEGER,
                machine_name TEXT,
                diff_coins_normalized INTEGER,
                games_normalized INTEGER,
                is_zorome INTEGER
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO machine_detailed_results
            (date, machine_number, machine_name, diff_coins_normalized, games_normalized, is_zorome)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("20260601", 101, "炎炎ノ消防隊", 120, 1000, 1),
                ("20260601", 102, "カバネリ", -60, 800, 0),
            ],
        )
        conn.commit()

    coords_path.write_text(
        "\n".join(
            [
                "hall_name,floor,machine_number,X,Y,display_x,display_y",
                "マルハンメガシティ2000-蒲田7,2F,101,1,1,1,1",
                "マルハンメガシティ2000-蒲田7,2F,102,2,1,2,1",
            ]
        ),
        encoding="utf-8",
    )

    captured: dict[str, str] = {}

    monkeypatch.setattr(hm.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(hm.st, "warning", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("warning called")))
    monkeypatch.setattr(hm.st, "error", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("error called")))
    monkeypatch.setattr(hm.st, "stop", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("stop called")))
    monkeypatch.setattr(hm.st, "multiselect", lambda *args, **kwargs: ["ゾロ目"])

    def fake_html(html: str, **kwargs) -> None:
        captured["html"] = html

    monkeypatch.setattr("streamlit.components.v1.html", fake_html)

    hm.render_last_digit_highlight(
        title="蒲田7 2F 末尾ハイライト",
        coords_file=str(coords_path),
        db_path=str(db_path),
        hall_name="マルハンメガシティ2000-蒲田7",
        floor="2F",
        date_range=(date(2026, 6, 1), date(2026, 6, 1)),
        widget_key_suffix="test_2f",
    )

    assert "machine-card" in captured["html"]
    assert "末尾ハイライト" in captured["html"]
    assert "ゾロ目" in captured["html"]
