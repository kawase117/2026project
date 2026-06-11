from pathlib import Path

import pandas as pd


def test_pick_candidates_requires_both_200_and_300_strength() -> None:
    from ml.hall_rank import hall_practical_strategy_analysis as mod

    best = pd.DataFrame(
        [
            {"store": "A", "threshold": 200, "best_success_rate_lift_vs_all": 0.30, "best_n_play_days": 8},
            {"store": "A", "threshold": 300, "best_success_rate_lift_vs_all": 0.25, "best_n_play_days": 5},
            {"store": "B", "threshold": 200, "best_success_rate_lift_vs_all": 0.22, "best_n_play_days": 8},
            {"store": "B", "threshold": 300, "best_success_rate_lift_vs_all": 0.05, "best_n_play_days": 5},
            {"store": "C", "threshold": 200, "best_success_rate_lift_vs_all": 0.35, "best_n_play_days": 8},
        ]
    )
    out = mod.pick_practical_candidates(
        best_df=best,
        required_thresholds=[200, 300],
        min_lift=0.2,
        min_play_days=5,
    )
    assert out["store"].tolist() == ["A"]


def test_overlap_distribution_counts_multi_hall_days() -> None:
    from ml.hall_rank import hall_practical_strategy_analysis as mod

    signals = pd.DataFrame(
        [
            {"date": "2026-01-01", "store": "A"},
            {"date": "2026-01-01", "store": "B"},
            {"date": "2026-01-02", "store": "A"},
            {"date": "2026-01-03", "store": "C"},
        ]
    )
    out = mod.compute_overlap_distribution(signals)
    row1 = out[out["n_halls_signaled"] == 1].iloc[0]
    row2 = out[out["n_halls_signaled"] == 2].iloc[0]
    assert row1["n_days"] == 2
    assert row2["n_days"] == 1


def test_gpu_backend_flag_wires_xgboost_params() -> None:
    from ml.hall_rank import hall_practical_strategy_analysis as mod

    params = mod.build_model_params(use_gpu=True, gpu_backend="cuda")

    assert params["device"] == "cuda"
    assert params["tree_method"] == "hist"


def test_parser_exposes_gpu_flags() -> None:
    from ml.hall_rank import hall_practical_strategy_analysis as mod

    parser = mod.build_parser()
    args = parser.parse_args(["--use-gpu", "--gpu-backend", "cuda"])

    assert args.use_gpu is True
    assert args.gpu_backend == "cuda"


def test_policy_grid_can_be_smaller_for_gpu_runs() -> None:
    from ml.hall_rank import hall_practical_strategy_analysis as mod

    grid = mod.build_policy_grid(use_gpu=True)

    assert len(grid) < 7680


def test_add_timing_features_is_shifted_no_leak() -> None:
    from ml.hall_rank import hall_practical_strategy_analysis as mod

    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]),
            "avg_diff_per_machine": [10.0, 20.0, 30.0, 40.0],
            "avg_games_per_machine": [100, 100, 100, 100],
            "total_machines": [10, 10, 10, 10],
            "win_rate": [50, 50, 50, 50],
            "weekday": [3, 4, 5, 6],
            "dd": [1, 2, 3, 4],
            "is_any_event": [0, 0, 0, 0],
            "is_zorome_day": [0, 0, 0, 0],
            "is_strong_zorome_day": [0, 0, 0, 0],
            "is_day_7x": [0, 0, 0, 0],
            "is_day_1x": [1, 0, 0, 0],
        }
    )
    out = mod._add_timing_features(df)
    assert pd.isna(out.loc[0, "lag1_avg_diff"])
    assert out.loc[1, "lag1_avg_diff"] == 10.0
    assert out.loc[3, "lag1_avg_diff"] == 30.0
    assert pd.isna(out.loc[0, "lag1_avg_games"])
    assert out.loc[1, "lag1_avg_games"] == 100.0
    assert out.loc[3, "lag1_avg_games"] == 100.0


def test_predict_binary_probabilities_single_class_fallback() -> None:
    from ml.hall_rank import hall_practical_strategy_analysis as mod

    train_x = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [0.0, 0.0, 1.0]})
    train_y = pd.Series([1, 1, 1])
    test_x = pd.DataFrame({"a": [4.0, 5.0], "b": [1.0, 0.0]})
    out = mod._predict_binary_probabilities(train_x, train_y, test_x)
    assert len(out) == 2
    assert float(out[0]) == 1.0
    assert float(out[1]) == 1.0


def test_predict_rank_scores_small_sample_fallback() -> None:
    from ml.hall_rank import hall_practical_strategy_analysis as mod

    train_x = pd.DataFrame({"a": [1.0, 2.0], "b": [0.0, 1.0]})
    train_y = pd.Series([100.0, 200.0])
    test_x = pd.DataFrame({"a": [3.0, 4.0], "b": [1.0, 0.0]})
    out = mod._predict_rank_scores(train_x, train_y, test_x)
    assert len(out) == 2
    assert float(out[0]) == 150.0
    assert float(out[1]) == 150.0


def test_expected_strength_score_exclusive_bins_uses_ge0() -> None:
    from ml.hall_rank import hall_practical_strategy_analysis as mod

    p0 = pd.Series([0.5, 0.2]).to_numpy()
    p100 = pd.Series([0.3, 0.1]).to_numpy()
    p200 = pd.Series([0.1, 0.0]).to_numpy()
    p300 = pd.Series([0.0, 0.0]).to_numpy()
    out = mod._expected_strength_score(p100, p200, p300, p0)
    assert abs(float(out[0]) - 15.0) < 1e-9
    assert abs(float(out[1]) - (-60.0)) < 1e-9


def test_parse_weight_grid() -> None:
    from ml.hall_rank import hall_practical_strategy_analysis as mod

    out = mod._parse_weight_grid("1,1,1;1,2,3")
    assert out == [(1.0, 1.0, 1.0), (1.0, 2.0, 3.0)]


def test_parse_csv_bools() -> None:
    from ml.hall_rank import hall_practical_strategy_analysis as mod

    out = mod._parse_csv_bools("false,true,1,0,yes,no")
    assert out == [False, True, True, False, True, False]


def test_build_hybrid_feature_columns_can_toggle_lag1_avg_games() -> None:
    from ml.hall_rank import hall_practical_strategy_analysis as mod

    base_cols = mod._build_hybrid_feature_columns(include_lag1_avg_games=False)
    lag_cols = mod._build_hybrid_feature_columns(include_lag1_avg_games=True)
    assert "lag1_avg_games" not in base_cols
    assert "lag1_avg_games" in lag_cols


def test_load_no_signal_stores() -> None:
    from ml.hall_rank import hall_practical_strategy_analysis as mod

    p = Path("ml/tests/_tmp_signal_judgment_table.csv")
    try:
        pd.DataFrame(
            [
                {"store": "A", "judgment": "NO_SIGNAL"},
                {"store": "B", "judgment": "SIGNAL_DETECTED"},
            ]
        ).to_csv(p, index=False, encoding="utf-8-sig")
        out = mod._load_no_signal_stores(str(p))
        assert out == {"A"}
    finally:
        if p.exists():
            p.unlink()


def test_apply_allhall_policy_respects_no_signal_penalty_and_dd_bonus() -> None:
    from ml.hall_rank import hall_practical_strategy_analysis as mod

    pred = pd.DataFrame(
        [
            {
                "date": "2026-01-01",
                "store": "A",
                "base_rate_ge_100_train": 0.2,
                "p_ge_0": 0.95,
                "p_ge_100": 0.9,
                "p_ge_200": 0.7,
                "p_ge_300": 0.6,
                "actual_avg_diff_per_machine": 100.0,
                "is_dd_topk_train": 0,
                "is_strong_zorome_day": 0,
            },
            {
                "date": "2026-01-01",
                "store": "B",
                "base_rate_ge_100_train": 0.2,
                "p_ge_0": 0.90,
                "p_ge_100": 0.8,
                "p_ge_200": 0.6,
                "p_ge_300": 0.5,
                "actual_avg_diff_per_machine": 90.0,
                "is_dd_topk_train": 1,
                "is_strong_zorome_day": 0,
            },
        ]
    )
    daily, _ = mod._apply_allhall_policy(
        pred_df=pred,
        ml_min_edge=0.0,
        weights=(1.0, 1.0, 1.0),
        no_signal_stores={"A"},
        no_signal_penalty=20.0,
        dd_topk_bonus=40.0,
        strong_zorome_bonus=0.0,
        share_cap=1.0,
        share_penalty_scale=0.0,
    )
    assert daily.iloc[0]["chosen_store"] == "B"


def test_apply_allhall_policy_soft_share_cap_forces_rotation() -> None:
    from ml.hall_rank import hall_practical_strategy_analysis as mod

    pred = pd.DataFrame(
        [
            {"date": "2026-01-01", "store": "A", "base_rate_ge_100_train": 0.2, "p_ge_0": 0.95, "p_ge_100": 0.9, "p_ge_200": 0.8, "p_ge_300": 0.7, "actual_avg_diff_per_machine": 100.0, "is_dd_topk_train": 0, "is_strong_zorome_day": 0},
            {"date": "2026-01-01", "store": "B", "base_rate_ge_100_train": 0.2, "p_ge_0": 0.90, "p_ge_100": 0.8, "p_ge_200": 0.7, "p_ge_300": 0.6, "actual_avg_diff_per_machine": 90.0, "is_dd_topk_train": 0, "is_strong_zorome_day": 0},
            {"date": "2026-01-02", "store": "A", "base_rate_ge_100_train": 0.2, "p_ge_0": 0.95, "p_ge_100": 0.9, "p_ge_200": 0.8, "p_ge_300": 0.7, "actual_avg_diff_per_machine": 100.0, "is_dd_topk_train": 0, "is_strong_zorome_day": 0},
            {"date": "2026-01-02", "store": "B", "base_rate_ge_100_train": 0.2, "p_ge_0": 0.90, "p_ge_100": 0.8, "p_ge_200": 0.7, "p_ge_300": 0.6, "actual_avg_diff_per_machine": 90.0, "is_dd_topk_train": 0, "is_strong_zorome_day": 0},
        ]
    )
    daily, _ = mod._apply_allhall_policy(
        pred_df=pred,
        ml_min_edge=0.0,
        weights=(1.0, 1.0, 1.0),
        no_signal_stores=set(),
        no_signal_penalty=0.0,
        dd_topk_bonus=0.0,
        strong_zorome_bonus=0.0,
        share_cap=0.5,
        share_penalty_scale=100.0,
    )
    assert daily["chosen_store"].tolist() == ["A", "B"]


def test_projected_share_penalty_scales_with_excess_share() -> None:
    from ml.hall_rank import hall_practical_strategy_analysis as mod

    penalty = mod._projected_share_penalty(
        chosen_counts={"A": 3},
        day_index=5,
        candidate_store="A",
        share_cap=0.5,
        share_penalty_scale=100.0,
    )
    assert abs(penalty - 30.0) < 1e-9


def test_load_hall_judgment_map_and_per_hall_prediction_table() -> None:
    from ml.hall_rank import hall_practical_strategy_analysis as mod

    p = Path("ml/tests/_tmp_hall_judgment_table.csv")
    try:
        pd.DataFrame(
            [
                {"store": "A", "judgment": "SIGNAL_DETECTED"},
                {"store": "B", "judgment": "NO_SIGNAL"},
            ]
        ).to_csv(p, index=False, encoding="utf-8-sig")
        hall_judgments = mod._load_hall_judgment_map(str(p))
        assert hall_judgments == {"A": "SIGNAL_DETECTED", "B": "NO_SIGNAL"}

        base = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]),
                "avg_diff_per_machine": [10.0, 20.0, 30.0, 40.0],
                "avg_games_per_machine": [100, 110, 120, 130],
                "total_machines": [10, 10, 10, 10],
                "win_rate": [40, 50, 60, 70],
                "weekday": [3, 4, 5, 6],
                "dd": [1, 2, 3, 4],
                "is_any_event": [0, 0, 0, 0],
                "is_zorome_day": [0, 0, 0, 0],
                "is_strong_zorome_day": [0, 0, 0, 0],
                "is_day_7x": [0, 0, 0, 0],
                "is_day_1x": [1, 0, 0, 0],
                "is_ge_0": [1, 1, 1, 1],
                "is_ge_100": [0, 1, 0, 1],
                "is_ge_200": [0, 0, 0, 0],
                "is_ge_300": [0, 0, 0, 0],
            }
        )
        panel = mod._build_multihall_panel(
            store_to_hall_df={
                "A": base.copy(),
                "B": base.assign(avg_diff_per_machine=[8.0, 7.0, 6.0, 5.0], is_ge_0=[1, 1, 1, 1], is_ge_100=[0, 0, 0, 0]),
            }
        )
        out = mod._build_hall_specific_prediction_table(
            panel_df=panel,
            hall_judgments=hall_judgments,
            selection_start="2026-01-01",
            eval_start="2026-01-04",
            eval_end="2026-01-04",
            dd_topk_k=2,
            dd_topk_min_days=1,
        )
        assert set(out["signal_class"].tolist()) == {"SIGNAL_DETECTED", "NO_SIGNAL"}
        assert set(out["store"].tolist()) == {"A", "B"}
    finally:
        if p.exists():
            p.unlink()


def test_hall_specific_weight_optimization_and_comparison_table() -> None:
    from ml.hall_rank import hall_practical_strategy_analysis as mod

    tune = pd.DataFrame(
        [
            {"date": "2026-01-01", "store": "A", "signal_class": "SIGNAL_DETECTED", "p_ge_0": 0.95, "p_ge_100": 0.9, "p_ge_200": 0.1, "p_ge_300": 0.1, "actual_avg_diff_per_machine": 100.0},
            {"date": "2026-01-01", "store": "B", "signal_class": "NO_SIGNAL", "p_ge_0": 0.85, "p_ge_100": 0.4, "p_ge_200": 0.4, "p_ge_300": 0.4, "actual_avg_diff_per_machine": 80.0},
            {"date": "2026-01-02", "store": "A", "signal_class": "SIGNAL_DETECTED", "p_ge_0": 0.90, "p_ge_100": 0.2, "p_ge_200": 0.9, "p_ge_300": 0.1, "actual_avg_diff_per_machine": 50.0},
            {"date": "2026-01-02", "store": "B", "signal_class": "NO_SIGNAL", "p_ge_0": 0.80, "p_ge_100": 0.6, "p_ge_200": 0.2, "p_ge_300": 0.2, "actual_avg_diff_per_machine": 120.0},
        ]
    )
    best_policy, table = mod._optimize_hall_specific_weights(
        pred_df_tune=tune,
        weight_grid=[(1.0, 1.0, 1.0), (1.0, 2.0, 3.0)],
        objective="avg_diff",
    )
    assert len(table) == 2
    assert best_policy["weights"] in [(1.0, 1.0, 1.0), (1.0, 2.0, 3.0)]

    comparison = mod._build_strategy_comparison_table(
        {
            "pooled": pd.DataFrame(
                [
                    {
                        "chosen_avg_diff_mean": 100.0,
                        "oracle_avg_diff_mean": 120.0,
                        "top1_hit_rate": 0.3,
                        "top2_inclusion_rate": 0.5,
                        "spearman_daily_mean": 0.2,
                        "regret_mean": 15.0,
                        "regret_sum": 30.0,
                    }
                ]
            ),
            "per_hall": pd.DataFrame(
                [
                    {
                        "chosen_avg_diff_mean": 110.0,
                        "oracle_avg_diff_mean": 130.0,
                        "top1_hit_rate": 0.4,
                        "top2_inclusion_rate": 0.6,
                        "spearman_daily_mean": 0.3,
                        "regret_mean": 12.0,
                        "regret_sum": 24.0,
                    }
                ]
            ),
        }
    )
    assert comparison.iloc[0]["strategy"] == "per_hall"


def test_hybrid_prediction_table_and_leakage_safe_dd_topk_feature() -> None:
    from ml.hall_rank import hall_practical_strategy_analysis as mod

    base = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]),
            "avg_diff_per_machine": [10.0, 20.0, 30.0, 40.0],
            "avg_games_per_machine": [100, 110, 120, 130],
            "total_machines": [10, 10, 10, 10],
            "win_rate": [40, 50, 60, 70],
            "weekday": [3, 4, 5, 6],
            "dd": [1, 2, 3, 4],
            "is_any_event": [0, 0, 0, 0],
            "is_zorome_day": [0, 0, 0, 0],
            "is_strong_zorome_day": [0, 0, 0, 0],
            "is_day_7x": [0, 0, 0, 0],
            "is_day_1x": [1, 0, 0, 0],
            "is_ge_0": [1, 1, 1, 1],
            "is_ge_100": [0, 1, 0, 1],
            "is_ge_200": [0, 0, 1, 1],
            "is_ge_300": [0, 0, 0, 1],
        }
    )
    panel = mod._build_multihall_panel(
        store_to_hall_df={
            "A": base.copy(),
            "B": base.assign(avg_diff_per_machine=[8.0, 7.0, 6.0, 5.0], is_ge_0=[1, 1, 1, 1], is_ge_100=[0, 0, 0, 0]),
        }
    )
    dd_feat = mod._add_leakage_safe_dd_topk_feature(panel, topk=2, min_days=1)
    assert "is_dd_topk_train" in dd_feat.columns
    assert dd_feat["is_dd_topk_train"].isin([0, 1]).all()

    hall_judgments = {"A": "SIGNAL_DETECTED", "B": "NO_SIGNAL"}
    out = mod._build_hybrid_prediction_table(
        panel_df=panel,
        hall_judgments=hall_judgments,
        selection_start="2026-01-01",
        eval_start="2026-01-04",
        eval_end="2026-01-04",
        dd_topk_k=2,
        dd_topk_min_days=1,
        logreg_c=1.0,
    )
    assert not out.empty
    assert set(out["signal_class"].tolist()) == {"SIGNAL_DETECTED", "NO_SIGNAL"}


def test_optimize_hybrid_c_and_policy_selects_best_c() -> None:
    from ml.hall_rank import hall_practical_strategy_analysis as mod

    pred_low_c = pd.DataFrame(
        [
            {
                "date": "2026-01-01",
                "store": "A",
                "signal_class": "SIGNAL_DETECTED",
                "base_rate_ge_100_train": 0.2,
                "p_ge_0": 0.95,
                "p_ge_100": 0.9,
                "p_ge_200": 0.8,
                "p_ge_300": 0.7,
                "actual_avg_diff_per_machine": 120.0,
                "actual_hit_ge_100": 1,
                "actual_hit_ge_200": 1,
                "actual_hit_ge_300": 1,
                "is_dd_topk_train": 1,
                "is_strong_zorome_day": 0,
            },
            {
                "date": "2026-01-01",
                "store": "B",
                "signal_class": "NO_SIGNAL",
                "base_rate_ge_100_train": 0.2,
                "p_ge_0": 0.90,
                "p_ge_100": 0.3,
                "p_ge_200": 0.2,
                "p_ge_300": 0.1,
                "actual_avg_diff_per_machine": 40.0,
                "actual_hit_ge_100": 0,
                "actual_hit_ge_200": 0,
                "actual_hit_ge_300": 0,
                "is_dd_topk_train": 0,
                "is_strong_zorome_day": 0,
            },
            {
                "date": "2026-01-02",
                "store": "A",
                "signal_class": "SIGNAL_DETECTED",
                "base_rate_ge_100_train": 0.2,
                "p_ge_0": 0.95,
                "p_ge_100": 0.85,
                "p_ge_200": 0.75,
                "p_ge_300": 0.65,
                "actual_avg_diff_per_machine": 130.0,
                "actual_hit_ge_100": 1,
                "actual_hit_ge_200": 1,
                "actual_hit_ge_300": 1,
                "is_dd_topk_train": 1,
                "is_strong_zorome_day": 0,
            },
            {
                "date": "2026-01-02",
                "store": "B",
                "signal_class": "NO_SIGNAL",
                "base_rate_ge_100_train": 0.2,
                "p_ge_0": 0.85,
                "p_ge_100": 0.25,
                "p_ge_200": 0.15,
                "p_ge_300": 0.05,
                "actual_avg_diff_per_machine": 20.0,
                "actual_hit_ge_100": 0,
                "actual_hit_ge_200": 0,
                "actual_hit_ge_300": 0,
                "is_dd_topk_train": 0,
                "is_strong_zorome_day": 0,
            },
        ]
    )
    pred_high_c = pred_low_c.copy()
    pred_high_c.loc[pred_high_c["store"] == "A", ["p_ge_100", "p_ge_200", "p_ge_300"]] = [0.2, 0.1, 0.1]
    pred_high_c.loc[pred_high_c["store"] == "B", ["p_ge_100", "p_ge_200", "p_ge_300"]] = [0.95, 0.9, 0.85]
    pred_high_c.loc[pred_high_c["store"] == "A", "p_ge_0"] = 0.95
    pred_high_c.loc[pred_high_c["store"] == "B", "p_ge_0"] = 0.98
    best_policy, table = mod._optimize_hybrid_c_and_policy(
        pred_tables_by_c={0.1: pred_low_c, 1.0: pred_high_c},
        edge_grid=[0.0],
        weight_grid=[(1.0, 1.0, 1.0)],
        no_signal_stores=set(),
        no_signal_penalty_grid=[0.0],
        dd_topk_bonus_grid=[0.0],
        strong_zorome_bonus_grid=[0.0],
        share_cap_grid=[1.0],
        share_penalty_scale=0.0,
        objective="avg_diff",
    )
    assert len(table) == 2
    assert best_policy["logreg_c"] in {0.1, 1.0}
    assert best_policy["logreg_c"] == 0.1
