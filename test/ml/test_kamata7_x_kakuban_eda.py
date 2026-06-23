from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ml.analysis import kamata7_kakuban_colsize_eda as colsize_mod


def _make_segment_frame(*, floor: str, machine_type_segment: str, machine_numbers: list[int], x_values: list[int]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = ["20260601", "20260602"]
    y_values = [1, 2]
    residuals = [10.0, 20.0, 30.0, 40.0]
    for idx, machine_number in enumerate(machine_numbers):
        x_value = x_values[idx]
        y_value = y_values[idx % len(y_values)]
        rows.append(
            {
                "date": dates[idx % len(dates)],
                "floor": floor,
                "machine_number": machine_number,
                "machine_name": f"M{machine_number}",
                "machine_type_segment": machine_type_segment,
                "section": "S1" if machine_number < 200 else "S2",
                "X": x_value,
                "Y": y_value,
                "section_min": 1,
                "section_max": 2,
                "rank_from_min": machine_number - machine_numbers[0] + 1,
                "rank_from_max": len(machine_numbers) - (machine_number - machine_numbers[0]),
                "diff_coins_normalized": residuals[idx],
                "games_normalized": 1600,
                "residual": residuals[idx],
                "residual_eligible": True,
                "kakuban_min": machine_number - machine_numbers[0] + 1,
                "kakuban_max": len(machine_numbers) - (machine_number - machine_numbers[0]),
            }
        )
    return pd.DataFrame(rows)


def test_default_db_matches_colsize_script() -> None:
    from ml.analysis import kamata7_x_kakuban_eda as x_mod

    assert x_mod.DEFAULT_DB_7 == colsize_mod.DEFAULT_DB_7


def test_attach_x_kakuban_frame_assigns_rank_within_each_x_column() -> None:
    from ml.analysis import kamata7_x_kakuban_eda as x_mod

    frame = pd.DataFrame(
        {
            "floor": ["2F", "2F", "2F", "2F", "2F", "2F"],
            "machine_number": [101, 101, 102, 102, 103, 103],
            "X": [10, 10, 10, 10, 20, 20],
            "Y": [3, 3, 1, 1, 2, 2],
            "rank_from_min": [1, 1, 2, 2, 3, 3],
        }
    )

    out = x_mod._attach_x_kakuban_frame(frame)

    assert out["x_kakuban"].tolist() == [2, 2, 1, 1, 1, 1]
    assert out["x_col_size"].tolist() == [2, 2, 2, 2, 1, 1]
    assert out["section_kakuban"].tolist() == [1, 1, 2, 2, 3, 3]


def test_build_x_kakuban_table_tracks_support_x_columns() -> None:
    from ml.analysis import kamata7_x_kakuban_eda as x_mod

    frame = pd.DataFrame(
        {
            "x_kakuban": [1, 1, 2, 2],
            "X": [10, 20, 10, 20],
            "residual": [10.0, 12.0, -4.0, -2.0],
        }
    )

    table = x_mod._build_x_kakuban_table(frame)

    assert list(table.columns) == [
        "x_kakuban",
        "mean_residual",
        "median_residual",
        "n",
        "support_x_columns",
        "kruskal_p",
        "kruskal_q",
    ]
    assert table["support_x_columns"].tolist() == [2, 2]
    assert table["kruskal_q"].notna().all()


def test_run_analysis_writes_report_with_expected_sections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ml.analysis import kamata7_x_kakuban_eda as x_mod

    frame_2f_a = _make_segment_frame(
        floor="2F",
        machine_type_segment="A",
        machine_numbers=[101, 102, 103, 104],
        x_values=[10, 10, 20, 20],
    )
    frame_2f_n = _make_segment_frame(
        floor="2F",
        machine_type_segment="N",
        machine_numbers=[201, 202, 203, 204],
        x_values=[10, 10, 20, 20],
    )
    frame_3f_a = _make_segment_frame(
        floor="3F",
        machine_type_segment="A",
        machine_numbers=[301, 302, 303, 304],
        x_values=[11, 11, 21, 21],
    )
    frame_3f_n = _make_segment_frame(
        floor="3F",
        machine_type_segment="N",
        machine_numbers=[401, 402, 403, 404],
        x_values=[11, 11, 21, 21],
    )

    def fake_prepare_segment_frame(spec, min_games=0, min_section_size=0):
        if spec.floor == "2F" and spec.hall_slug == "kamata7":
            return pd.concat([frame_2f_a, frame_2f_n], ignore_index=True)
        return pd.concat([frame_3f_a, frame_3f_n], ignore_index=True)

    monkeypatch.setattr(x_mod, "_prepare_segment_frame", fake_prepare_segment_frame)
    monkeypatch.setattr(x_mod, "infer_hall_name", lambda coords_path, floor: f"hall-{floor}")

    output_dir = tmp_path / "out"
    report_path = output_dir / "report.md"
    specs = [
        x_mod.SegmentSpec(
            hall_slug="kamata7",
            hall_name="hall-2F",
            floor="2F",
            db_path=tmp_path / "dummy.db",
            coords_path=tmp_path / "coords-2f.csv",
        ),
        x_mod.SegmentSpec(
            hall_slug="kamata7",
            hall_name="hall-3F",
            floor="3F",
            db_path=tmp_path / "dummy.db",
            coords_path=tmp_path / "coords-3f.csv",
        ),
    ]

    result = x_mod.run_analysis(
        specs=specs,
        output_dir=output_dir,
        report_path=report_path,
        min_games=0,
        min_section_size=0,
    )

    assert report_path.exists()
    report = report_path.read_text(encoding="utf-8")
    assert "## 1. Segment coverage" in report
    assert "## 2. X-column size map by floor" in report
    assert "## 3. Segment:" in report
    assert "support_x_columns" in report
    assert "## 4. Cross-segment comparison" in report
    assert "## 5. Correlation with section kakuban" in report
    assert not result["coverage"].empty
    assert not result["segment_summary"].empty
