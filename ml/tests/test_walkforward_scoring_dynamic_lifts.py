from __future__ import annotations

import pandas as pd


def test_compute_dynamic_lifts_uses_raw_train_features_when_component_columns_are_missing() -> None:
    from ml.experiments.walkforward_scoring import scoring_model as sm

    rows: list[dict[str, object]] = []
    base_dates = pd.to_datetime(["2026-01-05", "2026-01-06"])

    for idx in range(30):
        rows.append(
            {
                "date": base_dates[idx % 2].strftime("%Y%m%d"),
                "date_dt": base_dates[idx % 2],
                "machine_number": 1000 + idx,
                "machine_name": "Sample A",
                "floor": "3F",
                "section": "3F_L",
                "segment": "3F_L_N",
                "section_size_group": "large",
                "kakuban_new": 11,
                "kakuban_old": 11,
                "last_digit": "9",
                "is_zorome": 0,
                "games_normalized": 4000,
                "diff_coins_normalized": 200.0,
            }
        )

    for idx in range(30):
        rows.append(
            {
                "date": base_dates[idx % 2].strftime("%Y%m%d"),
                "date_dt": base_dates[idx % 2],
                "machine_number": 2000 + idx,
                "machine_name": "Sample A",
                "floor": "3F",
                "section": "3F_L",
                "segment": "3F_L_N",
                "section_size_group": "large",
                "kakuban_new": 1,
                "kakuban_old": 1,
                "last_digit": "1",
                "is_zorome": 0,
                "games_normalized": 4000,
                "diff_coins_normalized": -50.0,
            }
        )

    train = pd.DataFrame(rows)

    lifts = sm._compute_dynamic_lifts(train, "3F_L_N")

    assert lifts["c2"] > 1.0
    assert max(lifts.values()) > 1.02
