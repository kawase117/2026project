from __future__ import annotations

import pandas as pd

from eda import kamata7_section_relative_digit as mod


def test_assign_side_uses_floor_thresholds() -> None:
    assert mod.assign_side("2F", 2017) == "L"
    assert mod.assign_side("2F", 2018) == "E"
    assert mod.assign_side("2F", 2019) == "R"
    assert mod.assign_side("3F", 3017) == "L"
    assert mod.assign_side("3F", 3022) == "E"
    assert mod.assign_side("3F", 3023) == "R"


def test_assign_sections_by_gap_splits_on_gap_two_or_more() -> None:
    frame = pd.DataFrame(
        {
            "date": ["20260601"] * 6,
            "machine_number": [1, 2, 3, 5, 6, 7],
        }
    )

    out = mod._assign_sections_by_gap(frame)

    assert out["section_id"].tolist() == [1, 1, 1, 2, 2, 2]
    assert out["rank_from_min"].tolist() == [1, 2, 3, 1, 2, 3]
    assert out["rank_from_max"].tolist() == [3, 2, 1, 3, 2, 1]


def test_digit_series_applies_mod_ten_to_raw_and_positions() -> None:
    frame = pd.DataFrame(
        {
            "machine_number": [10, 11, 12],
            "rank_from_min": [1, 10, 11],
            "rank_from_max": [10, 11, 12],
        }
    )

    assert mod._digit_series(frame, "raw_digit").tolist() == ["0", "1", "2"]
    assert mod._digit_series(frame, "pos_from_left").tolist() == ["1", "0", "1"]
    assert mod._digit_series(frame, "pos_from_right").tolist() == ["0", "1", "2"]
