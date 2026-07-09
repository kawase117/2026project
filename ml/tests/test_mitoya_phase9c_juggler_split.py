from __future__ import annotations

from pathlib import Path

import pandas as pd


def _make_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for dd in range(1, 32):
        for section, machine_number, machine_name, rank_from_aisle, is_reversed_section in [
            ("501-522", 501 + dd, f"ジャグラー{dd:02d}", (dd % 4) + 1, 0),
            ("523-539", 700 + dd, f"AT{dd:02d}", (dd % 5) + 1, 1),
        ]:
            rows.append(
                {
                    "date": f"202607{dd:02d}",
                    "dd": dd,
                    "section": section,
                    "machine_number": machine_number,
                    "machine_name": machine_name,
                    "diff": float(dd * (10 if is_reversed_section == 0 else 5)),
                    "games": 1000,
                    "last_digit": str(dd % 10),
                    "is_zorome": 1 if str(machine_number)[-2:] in {f"{i}{i}" for i in range(10)} else 0,
                    "is_reversed_section": is_reversed_section,
                    "rank_from_aisle": rank_from_aisle,
                }
            )
    rows.append(
        {
            "date": "20260704",
            "dd": 4,
            "section": "501-522",
            "machine_number": 745,
            "machine_name": "DiscUp",
            "diff": 5000.0,
            "games": 1000,
            "last_digit": "5",
            "is_zorome": 0,
            "is_reversed_section": 0,
            "rank_from_aisle": 1,
        }
    )
    return pd.DataFrame(rows)


def test_build_all_artifacts_returns_all_phase9c_outputs() -> None:
    from eda import mitoya_phase9c_juggler_split as phase9c

    artifacts = phase9c.build_all_artifacts(_make_frame(), sections=["501-522", "523-539"], main_sections=["501-522"])

    assert {
        "jug_distribution",
        "jug_digit_effect",
        "jug_dd_effect",
        "jug_corner_effect",
        "jug_event_digit",
        "jug_zorome",
        "report",
    } <= set(artifacts)
    assert {"section", "jug_flag", "n", "machine_days"} <= set(artifacts["jug_distribution"].columns)
    assert {"corner_bucket", "jug_flag", "last_digit", "n", "avg_diff", "plus_rate"} <= set(
        artifacts["jug_digit_effect"].columns
    )
    assert {"dd", "jug_flag", "n", "avg_diff"} <= set(artifacts["jug_dd_effect"].columns)
    assert {"corner_bucket", "jug_flag", "n", "avg_diff"} <= set(artifacts["jug_corner_effect"].columns)
    assert {"event_category", "jug_flag", "last_digit", "n", "avg_diff", "plus_rate"} <= set(
        artifacts["jug_event_digit"].columns
    )
    assert {"date_scope", "corner_bucket", "jug_flag", "is_zorome_machine", "n", "avg_diff"} <= set(
        artifacts["jug_zorome"].columns
    )


def test_main_writes_requested_csvs(tmp_path: Path, monkeypatch) -> None:
    from eda import mitoya_phase9c_juggler_split as phase9c

    monkeypatch.setattr(phase9c, "load_mitoya_frame", lambda join_layout=True: _make_frame())

    exit_code = phase9c.main(
        ["--output-dir", str(tmp_path), "--sections", "501-522", "523-539", "--main-sections", "501-522"]
    )

    assert exit_code == 0
    for name in [
        "jug_distribution.csv",
        "jug_digit_effect.csv",
        "jug_dd_effect.csv",
        "jug_corner_effect.csv",
        "jug_event_digit.csv",
        "jug_zorome.csv",
        "report.md",
    ]:
        assert (tmp_path / name).exists()
