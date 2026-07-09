from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


def test_render_markdown_table_handles_empty_and_numbers() -> None:
    from eda import mitoya_prompt_common as common

    empty = pd.DataFrame(columns=["section", "avg_diff"])
    assert common.render_markdown_table(empty) == "_no rows_"

    frame = pd.DataFrame([{"section": "501-522", "avg_diff": 12.3456, "n": 7}])
    rendered = common.render_markdown_table(frame)

    assert "| section | avg_diff | n |" in rendered
    assert "12.346" in rendered
    assert "7" in rendered


def test_assign_debut_phase_separates_pre_existing_from_later_runs() -> None:
    from eda import mitoya_prompt_common as common

    frame = pd.DataFrame(
        [
            {"machine_number": 1, "date": "20260101", "machine_name": "A"},
            {"machine_number": 1, "date": "20260102", "machine_name": "A"},
            {"machine_number": 1, "date": "20260103", "machine_name": "B"},
            {"machine_number": 1, "date": "20260104", "machine_name": "B"},
        ]
    )

    enriched = common.assign_debut_phase(frame)

    assert enriched["debut_phase"].tolist() == ["pre_existing", "pre_existing", "debut", "debut"]
    assert enriched["debut_days"].tolist() == [None, None, 0, 1]
    assert enriched["is_moved"].tolist() == [False, False, False, False]


def test_assign_debut_phase_marks_later_machine_number_for_same_name_as_moved() -> None:
    from eda import mitoya_prompt_common as common

    frame = pd.DataFrame(
        [
            {"machine_number": 1, "date": "20260101", "machine_name": "A"},
            {"machine_number": 2, "date": "20260102", "machine_name": "A"},
            {"machine_number": 2, "date": "20260103", "machine_name": "A"},
        ]
    )

    enriched = common.assign_debut_phase(frame)

    assert enriched["is_moved"].tolist() == [False, True, True]
    assert enriched["debut_phase"].tolist() == ["pre_existing", "moved", "moved"]


def test_bucket_rank_from_aisle_uses_section_max_thirds() -> None:
    from eda import mitoya_prompt_common as common

    assert common.bucket_rank_from_aisle(1, 11) == 1
    assert common.bucket_rank_from_aisle(3, 11) == 1
    assert common.bucket_rank_from_aisle(4, 11) == 2
    assert common.bucket_rank_from_aisle(7, 11) == 2
    assert common.bucket_rank_from_aisle(8, 11) == 3
    assert common.bucket_rank_from_aisle(11, 11) == 3


def test_compute_top2_share_skips_small_denominator() -> None:
    from eda import mitoya_prompt_common as common

    assert pd.isna(common.compute_top2_share(pd.Series([40.0, -30.0, -15.0])))
    assert common.compute_top2_share(pd.Series([200.0, 100.0, -50.0])) == pytest.approx(1.2)
