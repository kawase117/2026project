from __future__ import annotations

import pandas as pd

from eda import kamata7_digit_triplet_analysis as triplet


def test_is_consecutive_ring_handles_wraparound() -> None:
    assert triplet.is_consecutive_ring([3, 4, 5]) is True
    assert triplet.is_consecutive_ring([8, 9, 0]) is True
    assert triplet.is_consecutive_ring([9, 0, 1]) is True
    assert triplet.is_consecutive_ring([0, 1, 9]) is True
    assert triplet.is_consecutive_ring([1, 3, 5]) is False


def test_table_to_md_formats_headers_and_numbers() -> None:
    df = pd.DataFrame(
        [
            {"name": "A", "value": 1.234, "count": 3},
            {"name": "B", "value": 5.678, "count": 4},
        ]
    )

    md = triplet.table_to_md(df, float_digits=1)

    assert md.splitlines()[0] == "| name | value | count |"
    assert "| --- | --- | --- |" in md
    assert "| A | 1.2 | 3 |" in md
    assert "| B | 5.7 | 4 |" in md


def test_build_condition_triplet_table_marks_consecutive_group() -> None:
    rows: list[dict[str, object]] = []
    for digit, avg_diff in [(0, 100), (1, 90), (2, 80), (3, 20)]:
        for i in range(5):
            rows.append(
                {
                    "dow": "水",
                    "dd_mod10": 6,
                    "machine_digit": digit,
                    "diff": avg_diff + i,
                }
            )
    for digit in [4, 5, 6]:
        for i in range(5):
            rows.append(
                {
                    "dow": "木",
                    "dd_mod10": 7,
                    "machine_digit": digit,
                    "diff": 10 + digit + i,
                }
            )

    df = pd.DataFrame(rows)
    result = triplet.build_condition_triplet_table(df, ["dow", "dd_mod10"])

    row = result[(result["dow"] == "水") & (result["dd_mod10"] == 6)].iloc[0]
    assert row["top1"] == 0
    assert row["top2"] == 1
    assert row["top3"] == 2
    assert row["is_consecutive"] is True
    assert row["triplet_label"] == "0-1-2"

