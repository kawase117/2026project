from __future__ import annotations

from pathlib import Path

import pandas as pd


def _make_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for dd in range(1, 32):
        for section, machine_number, machine_name, rank_from_aisle, is_reversed_section in [
            ("501-522", 501 + dd, f"A{dd:02d}", (dd % 4) + 1, 0),
            ("523-539", 700 + dd, f"B{dd:02d}", (dd % 5) + 1, 1),
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
    rows.append(
        {
            "date": "20260711",
            "dd": 11,
            "section": "501-522",
            "machine_number": 811,
            "machine_name": "ZZ",
            "diff": 700.0,
            "games": 1000,
            "last_digit": "1",
            "is_zorome": 1,
            "is_reversed_section": 0,
            "rank_from_aisle": 2,
        }
    )
    return pd.DataFrame(rows)


def test_build_all_artifacts_returns_all_phase9b_outputs() -> None:
    from eda import mitoya_phase9b_digit_deep as phase9b

    artifacts = phase9b.build_all_artifacts(_make_frame(), sections=["501-522", "523-539"], main_sections=["501-522"])

    assert {
        "digit_by_corner_bucket",
        "dd_digit_cross",
        "dd_mod10_digit_match",
        "zorome_date_machine_interaction",
        "event_category_digit",
        "report",
    } <= set(artifacts)

    digit = artifacts["digit_by_corner_bucket"]
    assert {"corner_bucket", "last_digit", "n", "avg_diff", "plus_rate"} <= set(digit.columns)
    assert int(digit["n"].sum()) == len(_make_frame()) - 1

    dd_cross = artifacts["dd_digit_cross"]
    assert {"corner_bucket", "dd", "last_digit", "n", "avg_diff", "plus_rate"} <= set(dd_cross.columns)
    assert dd_cross["dd"].min() == 1 and dd_cross["dd"].max() == 31

    match = artifacts["dd_mod10_digit_match"]
    assert {"corner_bucket", "dd_mod10", "is_dd_digit_match", "n", "avg_diff", "plus_rate"} <= set(match.columns)
    assert set(match["is_dd_digit_match"]) <= {0, 1}

    zorome = artifacts["zorome_date_machine_interaction"]
    assert {"record_type", "date_scope", "corner_bucket", "n", "avg_diff", "plus_rate"} <= set(zorome.columns)
    assert {"interaction_2x2", "digit_detail"} <= set(zorome["record_type"])

    event_digit = artifacts["event_category_digit"]
    assert set(event_digit["event_category"]) == {"xdds_day", "zorome_day", "strong_zorome", "month_end", "non_event"}
    assert {"corner_bucket", "event_category", "last_digit", "n", "avg_diff", "plus_rate"} <= set(event_digit.columns)


def test_main_writes_requested_csvs(tmp_path: Path, monkeypatch) -> None:
    from eda import mitoya_phase9b_digit_deep as phase9b

    monkeypatch.setattr(phase9b, "load_mitoya_frame", lambda join_layout=True: _make_frame())

    exit_code = phase9b.main(
        ["--output-dir", str(tmp_path), "--sections", "501-522", "523-539", "--main-sections", "501-522"]
    )

    assert exit_code == 0
    for name in [
        "digit_by_corner_bucket.csv",
        "dd_digit_cross.csv",
        "dd_mod10_digit_match.csv",
        "zorome_date_machine_interaction.csv",
        "event_category_digit.csv",
        "report.md",
    ]:
        assert (tmp_path / name).exists()
