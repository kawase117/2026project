import pandas as pd


def test_add_strength_targets_creates_expected_binary_columns() -> None:
    from ml.last_digit import hall_day_strength_audit as audit

    df = pd.DataFrame(
        {
            "avg_diff_per_machine": [-50, 0, 99, 100, 250, 300],
        }
    )

    out = audit.add_strength_targets(df, thresholds=[0, 100, 200, 300])

    assert out["is_ge_0"].tolist() == [0, 1, 1, 1, 1, 1]
    assert out["is_ge_100"].tolist() == [0, 0, 0, 1, 1, 1]
    assert out["is_ge_200"].tolist() == [0, 0, 0, 0, 1, 1]
    assert out["is_ge_300"].tolist() == [0, 0, 0, 0, 0, 1]


def test_evaluate_target_rules_reports_base_rate_and_lift() -> None:
    from ml.last_digit import hall_day_strength_audit as audit

    holdout = pd.DataFrame(
        [
            {"date": "2026-01-01", "weekday": 0, "dd": 1, "is_any_event": 0, "is_zorome_day": 0, "is_strong_zorome_day": 0, "is_day_7x": 0, "is_day_1x": 1, "avg_diff_per_machine": 50, "is_ge_100": 0},
            {"date": "2026-01-02", "weekday": 1, "dd": 2, "is_any_event": 0, "is_zorome_day": 0, "is_strong_zorome_day": 0, "is_day_7x": 0, "is_day_1x": 0, "avg_diff_per_machine": 150, "is_ge_100": 1},
            {"date": "2026-01-03", "weekday": 2, "dd": 3, "is_any_event": 0, "is_zorome_day": 0, "is_strong_zorome_day": 0, "is_day_7x": 0, "is_day_1x": 0, "avg_diff_per_machine": 200, "is_ge_100": 1},
            {"date": "2026-01-04", "weekday": 3, "dd": 4, "is_any_event": 0, "is_zorome_day": 0, "is_strong_zorome_day": 0, "is_day_7x": 0, "is_day_1x": 0, "avg_diff_per_machine": -100, "is_ge_100": 0},
        ]
    )
    rule_meta = {"best_weekday": 2, "dd_topk": [2, 3]}

    out = audit.evaluate_target_rules(holdout, rule_meta=rule_meta, target_col="is_ge_100")

    all_days = out.loc[out["rule"] == "all_days"].iloc[0]
    dd_topk = out.loc[out["rule"] == "dd_topk_only"].iloc[0]

    assert all_days["base_rate_all"] == 0.5
    assert dd_topk["n_play_days"] == 2
    assert dd_topk["success_rate"] == 1.0
    assert dd_topk["success_rate_lift_vs_all"] == 0.5
