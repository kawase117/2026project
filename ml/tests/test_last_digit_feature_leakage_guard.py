from __future__ import annotations

import pandas as pd
import pytest

from ml.last_digit.core_features import get_numeric_features
from ml.last_digit import tail_ltr_split_rule_nextday_gpu as nextday_gpu


def test_get_numeric_features_excludes_same_day_outcome_columns() -> None:
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-05-30"]),
            "entity_key": ["2F_N|1"],
            "store_id": ["kamata7"],
            "total_diff_coins_focus": [12345.0],
            "efficiency_focus": [0.91],
            "total_diff_coins": [11000.0],
            "efficiency": [0.55],
            "lag1_total_diff_coins_focus": [8000.0],
            "roll7_efficiency_focus": [0.33],
            "weekday": [5],
            "is_top_2": [1],
        }
    )

    features = get_numeric_features(df)

    assert "total_diff_coins_focus" not in features
    assert "efficiency_focus" not in features
    assert "total_diff_coins" not in features
    assert "efficiency" not in features
    assert "lag1_total_diff_coins_focus" in features
    assert "roll7_efficiency_focus" in features
    assert "weekday" in features


def test_predict_for_date_raises_if_forbidden_same_day_features_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_numeric_features(_: pd.DataFrame) -> list[str]:
        return ["total_diff_coins_focus", "lag1_total_diff_coins_focus"]

    monkeypatch.setattr(nextday_gpu.improved, "get_numeric_features", _fake_numeric_features)

    df_expert = pd.DataFrame(
        {
            "date": [pd.Timestamp("2026-05-30")],
            "group_key": ["2F_N"],
            "last_digit": ["1"],
        }
    )

    with pytest.raises(ValueError, match="Forbidden same-day outcome features leaked"):
        nextday_gpu._predict_for_date(
            df_expert=df_expert,
            pred_date=pd.Timestamp("2026-05-30"),
            candidates=[],
            q_grid=[0.0],
            seed=42,
            train_is_wed=False,
            min_train_days=1,
            min_train_days_wed_recent60=1,
            model_params={},
            model_name="xgb_ranker_ndcg",
            binary_mode="off",
            binary_threshold=0.5,
            binary_c=0.1,
            binary_max_iter=100,
            target_label="is_top_2",
            target_topk_k=2,
            use_digit_lag_bundle=False,
            use_2fn_weekday_patch=False,
        )
