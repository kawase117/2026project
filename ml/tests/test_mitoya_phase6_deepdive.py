from __future__ import annotations

import pandas as pd


def test_build_section_machine_table_limits_target_sections() -> None:
    from eda import mitoya_phase6_deepdive as phase6

    frame = pd.DataFrame(
        [
            {
                "section": "557-573",
                "machine_name": "A",
                "machine_number": 1,
                "date": "20260101",
                "diff": 100,
                "dd": 1,
                "day_of_week": "Mon",
                "rank_from_aisle": 1,
            },
            {
                "section": "557-573",
                "machine_name": "A",
                "machine_number": 1,
                "date": "20260102",
                "diff": 200,
                "dd": 2,
                "day_of_week": "Tue",
                "rank_from_aisle": 1,
            },
            {
                "section": "624-640",
                "machine_name": "B",
                "machine_number": 2,
                "date": "20260101",
                "diff": 300,
                "dd": 1,
                "day_of_week": "Mon",
                "rank_from_aisle": 2,
            },
        ]
    )

    table = phase6.build_section_machine_table(frame, sections=["557-573"])

    assert set(table["section"]) == {"557-573"}
    assert {"machine_name", "debut_phase", "avg_diff", "plus_rate", "n"} <= set(table.columns)


def test_build_interaction_table_uses_dd_buckets() -> None:
    from eda import mitoya_phase6_deepdive as phase6

    frame = pd.DataFrame(
        [
            {
                "section": "557-573",
                "machine_name": "A",
                "machine_number": 1,
                "date": "20260101",
                "diff": 100,
                "dd": 4,
                "day_of_week": "Mon",
                "rank_from_aisle": 1,
            },
            {
                "section": "557-573",
                "machine_name": "A",
                "machine_number": 1,
                "date": "20260102",
                "diff": 200,
                "dd": 14,
                "day_of_week": "Tue",
                "rank_from_aisle": 1,
            },
            {
                "section": "557-573",
                "machine_name": "B",
                "machine_number": 2,
                "date": "20260103",
                "diff": 300,
                "dd": 24,
                "day_of_week": "Wed",
                "rank_from_aisle": 2,
            },
        ]
    )

    table = phase6.build_interaction_table(frame, sections=["557-573"])

    assert set(table["section"]) == {"557-573"}
    assert "dd_bucket" in set(table.columns)
    assert "DD1-6" in set(table["dd_bucket"])
