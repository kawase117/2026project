"""generate_kamata1_cardmap_html.py の単体テスト"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent / "Heatmap"))

import generate_kamata1_cardmap_html as km1  # noqa: E402
import generate_kamata7_cardmap_html as km7  # noqa: E402


def test_build_kamata1_cardmap_html_uses_kamata1_hall_name(tmp_path, monkeypatch) -> None:
    """蒲田1の単独フロア版が hall 名を正しく反映すること。"""

    db_path = tmp_path / "kamata1.db"
    coords_path = tmp_path / "coords.csv"
    output_path = tmp_path / "kamata1_preview.html"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE machine_detailed_results (
                date TEXT,
                machine_number INTEGER,
                machine_name TEXT,
                diff_coins_normalized INTEGER,
                games_normalized INTEGER
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO machine_detailed_results
            (date, machine_number, machine_name, diff_coins_normalized, games_normalized)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("20260601", 2001, "スマスロ炎炎ノ消防隊", 120, 1000),
                ("20260602", 2002, "甲鉄城のカバネリ", -60, 800),
            ],
        )
        conn.commit()

    coords_path.write_text(
        "\n".join(
            [
                "hall_name,floor,machine_number,X,Y,display_x,display_y",
                "マルハンメガシティ2000-蒲田1,2F,2001,1,1,1,1",
                "マルハンメガシティ2000-蒲田1,2F,2002,2,1,2,1",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(km1, "DB_PATH", db_path)
    monkeypatch.setattr(
        km1,
        "FLOOR_SPECS",
        (
            km7.FloorSpec(
                floor="2F",
                title="蒲田1 2F",
                coords_path=coords_path,
            ),
        ),
    )

    html = km1.build_kamata1_cardmap_html(output_path=output_path)

    assert output_path.exists()
    assert "マルハンメガシティ2000-蒲田1" in html
    assert "蒲田7" not in html
    assert "machine-card" in html
    assert 'data-floor-tab="' not in html
