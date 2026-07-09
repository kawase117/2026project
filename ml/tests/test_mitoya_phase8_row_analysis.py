from __future__ import annotations

import pandas as pd


def test_build_machine_layout_table_splits_rows_within_section() -> None:
    from eda import mitoya_phase8_row_analysis as phase8

    frame = pd.DataFrame(
        [
            {
                "section": "557-573",
                "machine_number": 557,
                "machine_name": "A",
                "x": 19,
                "y": 29,
                "is_reversed_section": 0,
            },
            {
                "section": "557-573",
                "machine_number": 573,
                "machine_name": "B",
                "x": 3,
                "y": 29,
                "is_reversed_section": 0,
            },
            {
                "section": "557-573",
                "machine_number": 574,
                "machine_name": "C",
                "x": 3,
                "y": 28,
                "is_reversed_section": 0,
            },
            {
                "section": "557-573",
                "machine_number": 590,
                "machine_name": "D",
                "x": 19,
                "y": 28,
                "is_reversed_section": 0,
            },
        ]
    )

    table = phase8.build_machine_layout_table(frame, sections=["557-573"])

    assert set(table["row_label"]) == {"557-573", "574-590"}
    assert set(table["row_order_in_section"]) == {1, 2}
    assert table.loc[table["machine_number"] == 573, "row_corner_rank"].iloc[0] == 1
    assert table.loc[table["machine_number"] == 574, "row_corner_rank"].iloc[0] == 1


def test_build_row_machine_phase_table_keeps_row_labels() -> None:
    from eda import mitoya_phase8_row_analysis as phase8

    frame = pd.DataFrame(
        [
            {
                "section": "557-573",
                "machine_number": 557,
                "machine_name": "A",
                "date": "20260101",
                "diff": 100,
                "games": 1000,
                "x": 19,
                "y": 29,
            },
            {
                "section": "557-573",
                "machine_number": 557,
                "machine_name": "A",
                "date": "20260102",
                "diff": 200,
                "games": 1000,
                "x": 19,
                "y": 29,
            },
            {
                "section": "557-573",
                "machine_number": 574,
                "machine_name": "B",
                "date": "20260101",
                "diff": -50,
                "games": 1000,
                "x": 3,
                "y": 28,
            },
            {
                "section": "557-573",
                "machine_number": 574,
                "machine_name": "B",
                "date": "20260102",
                "diff": 50,
                "games": 1000,
                "x": 3,
                "y": 28,
            },
        ]
    )

    table = phase8.build_row_machine_phase_table(frame, sections=["557-573"])

    assert set(table["row_label"]) == {"557-557", "574-574"}
    assert {"debut_phase", "avg_diff", "avg_corner_rank"} <= set(table.columns)


def test_build_machine_layout_table_treats_vertical_section_as_one_column() -> None:
    from eda import mitoya_phase8_row_analysis as phase8

    frame = pd.DataFrame(
        [
            {
                "section": "692-700",
                "machine_number": 692,
                "machine_name": "A",
                "x": 1,
                "y": 13,
                "is_reversed_section": 0,
            },
            {
                "section": "692-700",
                "machine_number": 695,
                "machine_name": "B",
                "x": 1,
                "y": 8,
                "is_reversed_section": 0,
            },
            {
                "section": "692-700",
                "machine_number": 700,
                "machine_name": "C",
                "x": 1,
                "y": 3,
                "is_reversed_section": 0,
            },
        ]
    )

    table = phase8.build_machine_layout_table(frame, sections=["692-700"])

    assert set(table["row_label"]) == {"692-700"}
    assert set(table["row_order_in_section"]) == {1}
    assert list(table.sort_values("row_corner_rank")["machine_number"]) == [692, 695, 700]
    assert list(table.sort_values("row_corner_rank")["row_corner_rank"]) == [1, 2, 3]


def test_build_row_corner_bucket_summary_emits_middle_bucket() -> None:
    from eda import mitoya_phase8_row_analysis as phase8

    frame = pd.DataFrame(
        [
            {
                "section": "557-573",
                "machine_number": 501 + idx,
                "machine_name": f"M{idx}",
                "date": "20260101",
                "diff": idx * 10,
                "games": 1000,
                "x": idx + 1,
                "y": 29,
            }
            for idx in range(10)
        ]
    )

    table = phase8.build_row_corner_bucket_summary(frame, sections=["557-573"])

    assert "corner5-9" in set(table["corner_bucket"])
    assert {"section", "row_label", "corner_bucket", "avg_diff", "plus_rate", "n"} <= set(table.columns)
