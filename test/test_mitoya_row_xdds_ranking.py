from __future__ import annotations

import pandas as pd

from eda.mitoya_row_xdds_ranking import build_row_ranking


def test_build_row_ranking_uses_section_y_row_key_and_computes_lift() -> None:
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2025-01-04",
                    "2025-01-07",
                    "2025-01-08",
                    "2025-01-11",
                    "2025-01-14",
                    "2025-01-24",
                ]
            ),
            "machine_number": [624, 624, 624, 641, 641, 641],
            "machine_name": [
                "AT machine",
                "AT machine",
                "AT machine",
                "Juggler",
                "Juggler",
                "Juggler",
            ],
            "section": ["624-657"] * 6,
            "y": [21, 21, 21, 20, 20, 20],
            "diff_coins_normalized": [300, 200, 100, 20, 10, 0],
            "games_normalized": [1000] * 6,
        }
    )

    out = build_row_ranking(df, min_n_xdds=2)

    assert "row_key" in out.columns
    assert set(out["row_key"]) == {"624-657_y21", "624-657_y20"}
    assert "lift" in out.columns
    assert out.loc[out["row_key"].eq("624-657_y21"), "lift"].iloc[0] > out.loc[
        out["row_key"].eq("624-657_y20"), "lift"
    ].iloc[0]
    assert (out["n_xdds"] >= 2).all()
