import pandas as pd

from ml.last_digit.expert_segmentation import add_floor_atype4_columns
from ml.last_digit.tail_ltr_split_rule_nextday_gpu import _build_forecast_summary


def test_add_floor_atype4_columns_treats_oki_as_a_type():
    raw = pd.DataFrame(
        [
            {"machine_number": 3022, "jug_flag": 0, "hana_flag": 0, "oki_flag": 1, "bt_flag": 0},
            {"machine_number": 2177, "jug_flag": 0, "hana_flag": 0, "oki_flag": 0, "bt_flag": 1},
            {"machine_number": 2100, "jug_flag": 0, "hana_flag": 0, "oki_flag": 0, "bt_flag": 0},
        ]
    )

    out = add_floor_atype4_columns(raw)
    got = out[["machine_number", "expert"]].sort_values("machine_number").to_dict(orient="records")

    assert got == [
        {"machine_number": 2100, "expert": "2F_N"},
        {"machine_number": 2177, "expert": "2F_A"},
        {"machine_number": 3022, "expert": "3F_A"},
    ]


def test_build_forecast_summary_uses_absolute_scores_and_strict_segment_lists():
    summary = _build_forecast_summary(
        combined_ranking=[
            {"rank": 1, "last_digit": "1", "combined_score": 3.2},
            {"rank": 2, "last_digit": "7", "combined_score": 2.8},
        ],
        expert_outputs={
            "2F_N": {
                "status": "ok",
                "ranking": [
                    {"rank": 1, "last_digit": "1", "pred": 0.12, "final_score": 0.12},
                    {"rank": 2, "last_digit": "7", "pred": 0.08, "final_score": 0.08},
                ],
            }
        },
        zorome_by_digit={
            "1": [(2011, "global-one")],
            "7": [(2077, "global-seven")],
        },
        zorome_by_expert_digit={
            "2F_N": {
                "7": [(2077, "seg-seven")],
            }
        },
        top_n=2,
    )

    first = summary["by_expert"]["2F_N"][0]
    second = summary["by_expert"]["2F_N"][1]

    assert first["model_score"] == 0.12
    assert "confidence_pct" not in first
    assert first["zorome_machines"] == []
    assert second["zorome_machines"] == [
        {"machine_number": 2077, "machine_name": "seg-seven"},
    ]
    assert summary["machine_list_by_expert"]["2F_N"] == [
        {"machine_number": 2077, "machine_name": "seg-seven", "last_digit": "7"},
    ]
    assert summary["score_scale"] == "absolute_model_score"
    assert "confidence_scale" not in summary
