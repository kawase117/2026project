from __future__ import annotations

import pandas as pd


def test_bucket_rank_from_aisle_uses_layout_maximum() -> None:
    from eda import mitoya_phase5a_analysis as phase5a

    assert phase5a.bucket_rank_from_aisle(1, 8) == 1
    assert phase5a.bucket_rank_from_aisle(3, 8) == 2
    assert phase5a.bucket_rank_from_aisle(8, 8) == 3


def test_build_dd_kakuban_heatmap_has_all_section_bucket_rows() -> None:
    from eda import mitoya_phase5a_analysis as phase5a

    frame = pd.DataFrame(
        [
            {"section": "501-522", "rank_from_aisle": 1, "dd": 4, "diff": 100},
            {"section": "501-522", "rank_from_aisle": 4, "dd": 14, "diff": 200},
            {"section": "501-522", "rank_from_aisle": 8, "dd": 24, "diff": 300},
        ]
    )

    heatmap = phase5a.build_dd_kakuban_heatmap(frame)

    assert set(heatmap["section"]) == {"ALL", "501-522"}
    assert {"dd_bucket", "kakuban_bucket", "mean_diff", "n"} <= set(heatmap.columns)
