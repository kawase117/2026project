from __future__ import annotations

import pandas as pd


def test_build_shortlist_table_limits_to_top_n_per_section() -> None:
    from eda import mitoya_phase7_shortlist as phase7

    frame = pd.DataFrame(
        [
            {
                "section": "557-573",
                "machine_name": "A",
                "machine_number": 1,
                "date": "20260101",
                "diff": 100,
                "rank_from_aisle": 1,
            },
            {
                "section": "557-573",
                "machine_name": "A",
                "machine_number": 1,
                "date": "20260102",
                "diff": 200,
                "rank_from_aisle": 1,
            },
            {
                "section": "557-573",
                "machine_name": "B",
                "machine_number": 2,
                "date": "20260101",
                "diff": 300,
                "rank_from_aisle": 2,
            },
            {
                "section": "557-573",
                "machine_name": "C",
                "machine_number": 3,
                "date": "20260101",
                "diff": -50,
                "rank_from_aisle": 3,
            },
            {
                "section": "557-573",
                "machine_name": "D",
                "machine_number": 4,
                "date": "20260101",
                "diff": 400,
                "rank_from_aisle": 4,
            },
            {
                "section": "591-607",
                "machine_name": "E",
                "machine_number": 5,
                "date": "20260101",
                "diff": 500,
                "rank_from_aisle": 1,
            },
            {
                "section": "591-607",
                "machine_name": "F",
                "machine_number": 6,
                "date": "20260101",
                "diff": 100,
                "rank_from_aisle": 2,
            },
            {
                "section": "591-607",
                "machine_name": "G",
                "machine_number": 7,
                "date": "20260101",
                "diff": 50,
                "rank_from_aisle": 3,
            },
            {
                "section": "591-607",
                "machine_name": "H",
                "machine_number": 8,
                "date": "20260101",
                "diff": -10,
                "rank_from_aisle": 4,
            },
        ]
    )

    shortlist = phase7.build_shortlist_table(frame, sections=["557-573", "591-607"], top_n=3)

    assert set(shortlist["section"]) == {"557-573", "591-607"}
    assert shortlist.groupby("section").size().max() == 3
    assert {"machine_name", "best_phase", "best_avg_diff", "positive_phase_count", "rank"} <= set(shortlist.columns)


def test_build_report_mentions_shortlist_title() -> None:
    from eda import mitoya_phase7_shortlist as phase7

    table = pd.DataFrame(
        [
            {
                "section": "557-573",
                "machine_name": "A",
                "best_phase": "growth",
                "best_avg_diff": 100,
                "best_plus_rate": 50.0,
                "phase_count": 2,
                "positive_phase_count": 1,
                "best_n": 10,
                "avg_rank_from_aisle": 2.0,
                "rank": 1,
            }
        ]
    )
    text = phase7.build_report(table)

    assert "Mitoya Phase 7" in text
    assert "machine_name" in text


def test_available_machine_names_filter_excludes_missing_test_window_names() -> None:
    from eda import mitoya_phase7_shortlist as phase7

    frame = pd.DataFrame(
        [
            {
                "section": "557-573",
                "machine_name": "A",
                "machine_number": 1,
                "date": "20260101",
                "diff": 100,
                "rank_from_aisle": 1,
            },
            {
                "section": "557-573",
                "machine_name": "A",
                "machine_number": 1,
                "date": "20260102",
                "diff": 120,
                "rank_from_aisle": 1,
            },
            {
                "section": "557-573",
                "machine_name": "B",
                "machine_number": 2,
                "date": "20260101",
                "diff": 200,
                "rank_from_aisle": 2,
            },
            {
                "section": "557-573",
                "machine_name": "B",
                "machine_number": 2,
                "date": "20260102",
                "diff": 220,
                "rank_from_aisle": 2,
            },
        ]
    )

    shortlist = phase7.build_shortlist_table(
        frame,
        sections=["557-573"],
        top_n=3,
        available_machine_names={"A"},
    )
    assert set(shortlist["machine_name"]) == {"A"}
