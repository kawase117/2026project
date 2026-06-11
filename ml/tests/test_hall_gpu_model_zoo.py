from __future__ import annotations

import pandas as pd


def _make_hall_df(store: str, start: str = "2025-07-07") -> pd.DataFrame:
    dates = pd.date_range(start=start, periods=6, freq="D")
    return pd.DataFrame(
        {
            "date": dates,
            "avg_diff_per_machine": [10.0, 20.0, 15.0, 30.0, 25.0, 35.0],
            "avg_games_per_machine": [100, 110, 120, 130, 140, 150],
            "total_machines": [10, 10, 10, 10, 10, 10],
            "win_rate": [40, 45, 50, 55, 60, 65],
            "weekday": dates.weekday,
            "dd": dates.day,
            "mm": dates.month,
            "is_any_event": [0, 0, 0, 0, 0, 0],
            "is_zorome_day": [0, 0, 0, 0, 0, 0],
            "is_strong_zorome_day": [0, 0, 0, 0, 0, 0],
            "is_day_7x": [0, 0, 1, 0, 0, 0],
            "is_day_1x": [1, 0, 0, 0, 0, 0],
        }
    )


def test_backend_params_switch_by_model_family() -> None:
    from ml.hall_rank import hall_gpu_model_zoo as mod

    assert mod.build_backend_params("xgb_ranker", use_gpu=True, gpu_backend="cuda") == {
        "tree_method": "hist",
        "device": "cuda",
    }
    assert mod.build_backend_params("lgbm_ranker", use_gpu=True, gpu_backend="cuda") == {
        "device_type": "gpu",
    }
    assert mod.build_backend_params("catboost_ranker", use_gpu=True, gpu_backend="cuda") == {
        "task_type": "GPU",
        "devices": "0",
    }
    assert mod.build_backend_params("xgb_ranker", use_gpu=False, gpu_backend="cuda") == {
        "tree_method": "hist",
        "device": "cpu",
    }


def test_small_grid_profile_expands_ranker_variants() -> None:
    from ml.hall_rank import hall_gpu_model_zoo as mod

    base = mod.build_model_specs(use_gpu=False, gpu_backend="cuda", grid_profile="none")
    grid = mod.build_model_specs(use_gpu=False, gpu_backend="cuda", grid_profile="small")
    assert len(base) == 3
    assert len(grid) > len(base)
    assert any(spec.name.startswith("xgb_ranker_") for spec in grid)
    assert any(spec.name.startswith("lgbm_ranker_") for spec in grid)
    assert any(spec.name.startswith("catboost_ranker_") for spec in grid)


def test_build_hall_panel_adds_shifted_features() -> None:
    from ml.hall_rank import hall_gpu_model_zoo as mod

    panel = mod.build_hall_panel({"A": _make_hall_df("A"), "B": _make_hall_df("B")})
    assert {"store", "lag1_avg_diff", "lag1_avg_games", "rel_rank_ewm28"}.issubset(panel.columns)
    a = panel[panel["store"] == "A"].sort_values("date").reset_index(drop=True)
    b = panel[panel["store"] == "B"].sort_values("date").reset_index(drop=True)
    assert pd.isna(a.loc[0, "lag1_avg_diff"])
    assert a.loc[1, "lag1_avg_diff"] == 10.0
    assert pd.isna(b.loc[0, "lag1_avg_diff"])
    assert b.loc[1, "lag1_avg_diff"] == 10.0


def test_evaluate_model_zoo_smoke_returns_all_rankers() -> None:
    from ml.hall_rank import hall_gpu_model_zoo as mod

    panel = mod.build_hall_panel(
        {
            "A": _make_hall_df("A"),
            "B": _make_hall_df("B").assign(avg_diff_per_machine=[8.0, 7.0, 6.0, 5.0, 4.0, 3.0]),
            "C": _make_hall_df("C").assign(avg_diff_per_machine=[12.0, 11.0, 10.0, 9.0, 8.0, 7.0]),
        }
    )
    summary, detailed = mod.evaluate_model_zoo(
        panel_df=panel,
        selection_start="2025-07-07",
        selection_end="2025-07-10",
        holdout_start="2025-07-11",
        holdout_end="2025-07-12",
        models=("xgb_ranker", "lgbm_ranker", "catboost_ranker"),
        seeds=(42,),
        use_gpu=False,
        gpu_backend="cuda",
    )
    assert set(summary["model"].tolist()) == {"xgb_ranker", "lgbm_ranker", "catboost_ranker"}
    assert not detailed.empty
    for col in ("chosen_avg_diff_mean", "top1_hit_rate", "top2_inclusion_rate", "spearman_daily_mean", "regret_mean"):
        assert col in summary.columns


def test_compare_model_zoo_backends_reports_cpu_gpu_delta() -> None:
    from ml.hall_rank import hall_gpu_model_zoo as mod

    panel = mod.build_hall_panel(
        {
            "A": _make_hall_df("A"),
            "B": _make_hall_df("B").assign(avg_diff_per_machine=[8.0, 7.0, 6.0, 5.0, 4.0, 3.0]),
            "C": _make_hall_df("C").assign(avg_diff_per_machine=[12.0, 11.0, 10.0, 9.0, 8.0, 7.0]),
        }
    )
    comparison, summaries = mod.compare_model_zoo_backends(
        panel_df=panel,
        selection_start="2025-07-07",
        selection_end="2025-07-10",
        holdout_start="2025-07-11",
        holdout_end="2025-07-12",
        models=("xgb_ranker",),
        seeds=(42,),
        grid_profile="small",
    )
    assert "chosen_avg_diff_mean_delta_gpu_minus_cpu" in comparison.columns
    assert set(summaries["backend_requested"].tolist()) == {"cpu", "gpu"}
    assert "elapsed_sec_mean" in summaries.columns
    assert len(summaries) == 4
    assert len(comparison) == 2


def test_evaluate_model_zoo_small_grid_smoke_returns_variants() -> None:
    from ml.hall_rank import hall_gpu_model_zoo as mod

    panel = mod.build_hall_panel(
        {
            "A": _make_hall_df("A"),
            "B": _make_hall_df("B").assign(avg_diff_per_machine=[8.0, 7.0, 6.0, 5.0, 4.0, 3.0]),
            "C": _make_hall_df("C").assign(avg_diff_per_machine=[12.0, 11.0, 10.0, 9.0, 8.0, 7.0]),
        }
    )
    summary, detailed = mod.evaluate_model_zoo(
        panel_df=panel,
        selection_start="2025-07-07",
        selection_end="2025-07-10",
        holdout_start="2025-07-11",
        holdout_end="2025-07-12",
        models=("xgb_ranker", "lgbm_ranker", "catboost_ranker"),
        seeds=(42,),
        use_gpu=False,
        gpu_backend="cuda",
        grid_profile="small",
    )
    assert len(summary) >= 6
    assert not detailed.empty
