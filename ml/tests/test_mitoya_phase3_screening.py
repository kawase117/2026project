from __future__ import annotations

import pandas as pd


def test_build_screening_tables_includes_expected_columns() -> None:
    from eda import mitoya_phase3_screening as phase3

    frame = pd.DataFrame(
        [
            {
                "section": "501-522",
                "machine_digit": "0",
                "machine_zorome": 0,
                "day_of_week": "月",
                "diff": 100,
                "machine_name": "A",
                "machine_number": 1,
                "date": "20260101",
            },
            {
                "section": "501-522",
                "machine_digit": "1",
                "machine_zorome": 0,
                "day_of_week": "月",
                "diff": -20,
                "machine_name": "A",
                "machine_number": 1,
                "date": "20260102",
            },
            {
                "section": "501-522",
                "machine_digit": "0",
                "machine_zorome": 1,
                "day_of_week": "火",
                "diff": 300,
                "machine_name": "B",
                "machine_number": 1,
                "date": "20260103",
            },
            {
                "section": "501-522",
                "machine_digit": "1",
                "machine_zorome": 1,
                "day_of_week": "火",
                "diff": 50,
                "machine_name": "B",
                "machine_number": 1,
                "date": "20260104",
            },
        ]
    )

    summary, candidates = phase3.build_screening_tables(frame)

    assert {"variable", "section", "p_value", "epsilon_sq", "n"} <= set(summary.columns)
    assert "debut_phase" in set(summary["variable"])
    assert isinstance(candidates, list)
