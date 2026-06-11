from __future__ import annotations

import pandas as pd

from ml.last_digit.mitoya_dd_rank_candidates import build_dd_candidate_ranking


def test_build_dd_candidate_ranking_prioritizes_spread_and_stability() -> None:
    dd_summary = pd.DataFrame(
        {
            "dd": [4, 19, 30],
            "n_dates": [17, 17, 14],
            "mean_diff_top3": [423.8, 141.9, 270.1],
            "mean_diff_bottom3": [135.6, -161.2, 5.9],
            "dd_spread": [288.2, 303.1, 264.2],
            "top3_digits": ["2,7,4", "4,2,5", "2,4,1"],
            "bottom3_digits": ["6,9,3", "3,6,0", "5,9,0"],
        }
    )

    ranking = build_dd_candidate_ranking(dd_summary)

    assert list(ranking["dd"]) == [19, 4, 30]
    assert ranking.iloc[0]["known_hint"] == "new"
    assert ranking.iloc[1]["known_hint"] == "known"
    assert ranking.iloc[2]["known_hint"] == "known"
    assert ranking.iloc[0]["dd_spread"] > ranking.iloc[1]["dd_spread"]
    assert ranking.iloc[0]["score"] > ranking.iloc[1]["score"]


def test_build_dd_candidate_ranking_handles_empty_input() -> None:
    ranking = build_dd_candidate_ranking(pd.DataFrame())
    assert ranking.empty
    assert set(ranking.columns) == {
        "dd",
        "n_dates",
        "mean_diff_top3",
        "mean_diff_bottom3",
        "dd_spread",
        "top3_abs",
        "bottom3_abs",
        "top3_to_bottom3_ratio",
        "score",
        "known_hint",
    }
