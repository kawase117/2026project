from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from Heatmap.export_dd_candidates import (
    classify_avg_diff,
    classify_win_rate_border,
    export_dd_candidates,
)


@pytest.mark.parametrize(
    ("value", "expected_class"),
    [
        (-1000, "tone-strong-negative"),
        (-999, "tone-negative"),
        (-500, "tone-negative"),
        (-499, "tone-neutral"),
        (0, "tone-neutral"),
        (1, "tone-positive-soft"),
        (500, "tone-positive-soft"),
        (501, "tone-positive"),
        (1000, "tone-positive"),
        (1001, "tone-strong-positive"),
        (2000, "tone-strong-positive"),
        (2001, "tone-gold"),
    ],
)
def test_classify_avg_diff_boundaries(value: float, expected_class: str) -> None:
    assert classify_avg_diff(value).class_name == expected_class


@pytest.mark.parametrize(
    ("value", "expected_class"),
    [
        (70, "border-gold"),
        (69.9, "border-green"),
        (50, "border-green"),
        (49.9, "border-muted"),
        (30, "border-muted"),
        (29.9, "border-danger"),
    ],
)
def test_classify_win_rate_border_boundaries(value: float, expected_class: str) -> None:
    assert classify_win_rate_border(value).class_name == expected_class


def _pick_real_dd(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT substr(date, 7, 2) AS dd, COUNT(*) AS c
            FROM machine_detailed_results
            GROUP BY dd
            ORDER BY c DESC, dd
            LIMIT 1
            """
        ).fetchone()
    if row is None:
        raise AssertionError(f"No data found in {db_path}")
    return int(row[0])


def _pick_real_db_path() -> Path:
    for path in sorted(Path("db").glob("*2000*7.db")):
        with sqlite3.connect(path) as conn:
            has_table = (
                conn.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table' AND name = 'machine_detailed_results'
                    """
                ).fetchone()
                is not None
            )
        if has_table:
            return path
    raise AssertionError("No real db with machine_detailed_results found")


def test_export_dd_candidates_writes_real_html(tmp_path: Path) -> None:
    db_path = _pick_real_db_path()
    dd = _pick_real_dd(db_path)

    output_dir = tmp_path / "exports"
    written = export_dd_candidates(
        dd=dd,
        halls=["kamata7"],
        output_dir=output_dir,
    )

    assert written
    assert len(written) == 2
    for path in written:
        assert path.exists()
        html = path.read_text(encoding="utf-8")
        assert f"DD{dd} 候補台マップ" in html
        assert "candidate-card" in html
        assert "Download PNG" in html
        assert "html2canvas" in html
