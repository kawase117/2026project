from __future__ import annotations

from pathlib import Path

import pandas as pd

from eda import kamata7_digit_floor_interaction as mod


def test_floor_classifier_uses_machine_number_ranges() -> None:
    assert mod._floor_from_machine_number(2000) == "2F"
    assert mod._floor_from_machine_number(2999) == "2F"
    assert mod._floor_from_machine_number(3000) == "3F"
    assert mod._floor_from_machine_number(3999) == "3F"
    assert mod._floor_from_machine_number(1999) is None
    assert mod._floor_from_machine_number(4000) is None


def test_run_analysis_writes_report_and_quickref(tmp_path: Path, monkeypatch) -> None:
    frame = pd.DataFrame(
        {
            "date": ["20260601", "20260601", "20260608", "20260608"],
            "machine_number": [2001, 2002, 3001, 3002],
            "machine_name": ["A1", "A2", "B1", "B2"],
            "segment": ["A", "N", "A", "N"],
            "dd": [1, 1, 8, 8],
            "dd_mod10": [1, 1, 8, 8],
            "day_of_week": ["月", "月", "水", "水"],
            "machine_digit": ["1", "2", "1", "2"],
            "diff": [100, -50, 80, -20],
            "plus": [1, 0, 1, 0],
            "hit104": [1, 0, 1, 0],
        }
    )

    monkeypatch.setattr(mod, "_prepare_frame", lambda: frame.copy())

    report_path = tmp_path / "report.md"
    quickref_path = tmp_path / "quickref.csv"

    result = mod.run_analysis(report_path=report_path, quickref_path=quickref_path, min_n_matrix=1)

    assert report_path.exists()
    assert quickref_path.exists()
    assert "Section 1" in report_path.read_text(encoding="utf-8")
    assert "2F" in report_path.read_text(encoding="utf-8")
    assert not result["floor_summary"].empty
