import numpy as np
import pandas as pd
import pytest

from ml.experiments import tail_time_adaptive_ltr_poc_improved as improved


def test_compute_random_baseline_preserves_output_contract() -> None:
    y_true = np.array([1, 0, 0, 1, 0, 0], dtype=int)
    group_ids = np.array(
        [
            np.datetime64("2025-01-01"),
            np.datetime64("2025-01-01"),
            np.datetime64("2025-01-01"),
            np.datetime64("2025-01-02"),
            np.datetime64("2025-01-02"),
            np.datetime64("2025-01-02"),
        ]
    )

    result = improved.compute_random_baseline(
        y_true,
        group_ids,
        np.random.default_rng(42),
        trials=5,
    )

    assert set(result) == {
        "hit_at_1",
        "hit_at_2",
        "hit_at_3",
        "ndcg_at_2",
        "ndcg_at_3",
        "spearman",
        "abstain_coverage",
        "abstain_hit_at_1",
    }
    assert result["abstain_coverage"] == 0.0
    assert result["abstain_hit_at_1"] == 0.0


def test_evaluate_mode_returns_zero_filled_metrics_when_no_folds(monkeypatch) -> None:
    monkeypatch.setattr(improved, "create_date_folds", lambda *args, **kwargs: [])

    dataset = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-01"]),
            "is_rank_1": [1],
        }
    )

    result = improved.evaluate_mode(
        dataset,
        target="is_rank_1",
        features=[],
        n_splits=5,
        valid_days=21,
        random_state=42,
    )

    assert result["metrics"] == {
        "hit_at_1": 0.0,
        "hit_at_2": 0.0,
        "hit_at_3": 0.0,
        "ndcg_at_2": 0.0,
        "ndcg_at_3": 0.0,
        "spearman": 0.0,
        "abstain_coverage": 0.0,
        "abstain_hit_at_1": 0.0,
    }
    assert result["metrics_std"] == {
        "hit_at_1": 0.0,
        "hit_at_2": 0.0,
        "hit_at_3": 0.0,
        "ndcg_at_2": 0.0,
        "ndcg_at_3": 0.0,
        "spearman": 0.0,
        "abstain_coverage": 0.0,
        "abstain_hit_at_1": 0.0,
    }
    assert result["random_baseline"] == {
        "hit_at_1": 0.0,
        "hit_at_2": 0.0,
        "hit_at_3": 0.0,
        "ndcg_at_2": 0.0,
        "ndcg_at_3": 0.0,
        "spearman": 0.0,
        "abstain_coverage": 0.0,
        "abstain_hit_at_1": 0.0,
    }
    assert result["lift_vs_random"] == {
        "hit_at_1": 0.0,
        "hit_at_2": 0.0,
        "hit_at_3": 0.0,
        "ndcg_at_2": 0.0,
        "ndcg_at_3": 0.0,
        "spearman": 0.0,
        "abstain_coverage": 0.0,
        "abstain_hit_at_1": 0.0,
    }


def test_parse_lambda_sweep_values() -> None:
    assert improved.parse_lambda_sweep_values("1.0, 1.5,2.0") == [1.0, 1.5, 2.0]
    assert improved.parse_lambda_sweep_values("") == []


def test_parse_target_values() -> None:
    assert improved.parse_target_values("is_rank_1, is_top_3") == ["is_rank_1", "is_top_3"]
    assert improved.parse_target_values("") == []


def test_spearman_by_group_returns_mean_group_correlation() -> None:
    y_true = np.array([1, 2, 3, 1, 2, 3], dtype=float)
    y_pred = np.array([1, 2, 3, 3, 2, 1], dtype=float)
    group_ids = np.array([0, 0, 0, 1, 1, 1])

    result = improved.spearman_by_group(y_true, y_pred, group_ids)

    assert result == 0.0


def test_evaluate_mode_reports_metrics_std(monkeypatch) -> None:
    def fake_create_date_folds(*args, **kwargs):
        d1 = pd.Timestamp("2025-01-01")
        d2 = pd.Timestamp("2025-01-02")
        d3 = pd.Timestamp("2025-01-03")
        return [([d1], [d2]), ([d1, d2], [d3])]

    def fake_evaluate_train_valid_split(*args, **kwargs):
        valid = args[1]
        fold_id = int(valid["fold_id"].iloc[0])
        base = 0.1 if fold_id == 1 else 0.3
        return improved.FoldResult(
            hit_at_1=base,
            hit_at_2=base + 0.1,
            hit_at_3=base + 0.2,
            ndcg_at_2=base + 0.3,
            ndcg_at_3=base + 0.4,
            spearman=base + 0.5,
            abstain_coverage=base + 0.6,
            abstain_hit_at_1=base + 0.7,
        ), {
            "hit_at_1": 0.0,
            "hit_at_2": 0.0,
            "hit_at_3": 0.0,
            "ndcg_at_2": 0.0,
            "ndcg_at_3": 0.0,
            "spearman": 0.0,
            "abstain_coverage": 0.0,
            "abstain_hit_at_1": 0.0,
        }

    monkeypatch.setattr(improved, "create_date_folds", fake_create_date_folds)
    monkeypatch.setattr(improved, "evaluate_train_valid_split", fake_evaluate_train_valid_split)

    dataset = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"]),
            "entity_key": ["1", "1", "1"],
            "fold_id": [0, 1, 2],
            "is_rank_1": [0, 1, 0],
        }
    )

    result = improved.evaluate_mode(
        dataset,
        target="is_rank_1",
        features=[],
        n_splits=2,
        valid_days=1,
        random_state=42,
    )

    assert result["metrics"]["hit_at_1"] == 0.2
    assert result["metrics"]["spearman"] == 0.7
    assert result["metrics_std"]["hit_at_1"] == pytest.approx(0.1)
    assert result["metrics_std"]["spearman"] == pytest.approx(0.1)


def test_run_lambda_sweep_selects_best_lambda_by_target_metric(monkeypatch) -> None:
    def fake_evaluate_mode(*args, **kwargs):
        lam = kwargs["decay_lambda"]
        return {
            "target": kwargs["target"],
            "metrics": {
                "hit_at_1": lam / 10.0,
                "hit_at_2": 0.5 - lam / 10.0,
                "hit_at_3": lam / 5.0,
                "ndcg_at_2": 0.0,
                "ndcg_at_3": 0.0,
                "spearman": lam / 20.0,
                "abstain_coverage": 0.0,
                "abstain_hit_at_1": 0.0,
            },
            "metrics_std": {
                "hit_at_1": 0.0,
                "hit_at_2": 0.0,
                "hit_at_3": 0.0,
                "ndcg_at_2": 0.0,
                "ndcg_at_3": 0.0,
                "spearman": 0.0,
                "abstain_coverage": 0.0,
                "abstain_hit_at_1": 0.0,
            },
            "random_baseline": {
                "hit_at_1": 0.0,
                "hit_at_2": 0.0,
                "hit_at_3": 0.0,
                "ndcg_at_2": 0.0,
                "ndcg_at_3": 0.0,
                "spearman": 0.0,
                "abstain_coverage": 0.0,
                "abstain_hit_at_1": 0.0,
            },
            "lift_vs_random": {
                "hit_at_1": lam / 10.0,
                "hit_at_2": 0.5 - lam / 10.0,
                "hit_at_3": lam / 5.0,
                "ndcg_at_2": 0.0,
                "ndcg_at_3": 0.0,
                "spearman": lam / 20.0,
                "abstain_coverage": 0.0,
                "abstain_hit_at_1": 0.0,
            },
            "n_folds": 2,
        }

    monkeypatch.setattr(improved, "evaluate_mode", fake_evaluate_mode)

    dataset = pd.DataFrame({"date": pd.to_datetime(["2025-01-01"]), "is_top_2": [1]})
    result = improved.run_lambda_sweep(
        dataset=dataset,
        target="is_top_2",
        features=[],
        n_splits=2,
        valid_days=7,
        random_state=42,
        calibration_config=improved.CalibrationConfig(),
        lambda_values=[1.0, 2.0, 3.0],
    )

    assert result["selection_metric"] == "hit_at_2"
    assert [row["lambda"] for row in result["candidates"]] == [1.0, 2.0, 3.0]
    assert result["best_lambda"] == 1.0
    assert result["best_score"] == 0.4


def test_split_dataset_by_date_ranges_uses_expected_regime_boundaries() -> None:
    dataset = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2025-07-07", "2025-10-31", "2025-11-01", "2025-12-31", "2026-01-01"]
            ),
            "value": [1, 2, 3, 4, 5],
        }
    )

    train, valid = improved.split_dataset_by_date_ranges(
        dataset,
        train_start="2025-07-07",
        train_end="2025-10-31",
        valid_start="2025-11-01",
        valid_end="2025-12-31",
    )

    assert train["value"].tolist() == [1, 2]
    assert valid["value"].tolist() == [3, 4]


def test_run_fixed_lambda_sweep_selects_best_lambda(monkeypatch) -> None:
    def fake_evaluate_fixed_split(*args, **kwargs):
        lam = kwargs["decay_lambda"]
        return {
            "target": kwargs["target"],
            "metrics": {
                "hit_at_1": lam / 10.0,
                "hit_at_2": 0.0,
                "hit_at_3": lam / 5.0,
                "ndcg_at_2": 0.0,
                "ndcg_at_3": 0.0,
                "spearman": lam / 20.0,
                "abstain_coverage": 0.0,
                "abstain_hit_at_1": 0.0,
            },
            "metrics_std": {
                "hit_at_1": 0.0,
                "hit_at_2": 0.0,
                "hit_at_3": 0.0,
                "ndcg_at_2": 0.0,
                "ndcg_at_3": 0.0,
                "spearman": 0.0,
                "abstain_coverage": 0.0,
                "abstain_hit_at_1": 0.0,
            },
            "random_baseline": {
                "hit_at_1": 0.0,
                "hit_at_2": 0.0,
                "hit_at_3": 0.0,
                "ndcg_at_2": 0.0,
                "ndcg_at_3": 0.0,
                "spearman": 0.0,
                "abstain_coverage": 0.0,
                "abstain_hit_at_1": 0.0,
            },
            "lift_vs_random": {
                "hit_at_1": lam / 10.0,
                "hit_at_2": 0.0,
                "hit_at_3": lam / 5.0,
                "ndcg_at_2": 0.0,
                "ndcg_at_3": 0.0,
                "spearman": lam / 20.0,
                "abstain_coverage": 0.0,
                "abstain_hit_at_1": 0.0,
            },
            "n_folds": 1,
            "split_summary": {"train_days": 10, "valid_days": 5},
        }

    monkeypatch.setattr(improved, "evaluate_fixed_split", fake_evaluate_fixed_split)

    dataset = pd.DataFrame({"date": pd.to_datetime(["2025-01-01"]), "is_top_3": [1]})
    result = improved.run_fixed_lambda_sweep(
        dataset=dataset,
        target="is_top_3",
        features=[],
        random_state=42,
        calibration_config=improved.CalibrationConfig(),
        lambda_values=[1.0, 2.0, 3.0],
        train_start="2025-07-07",
        train_end="2025-10-31",
        valid_start="2025-11-01",
        valid_end="2025-12-31",
    )

    assert result["selection_metric"] == "hit_at_3"
    assert result["best_lambda"] == 3.0
    assert result["best_score"] == 0.6


def test_build_fixed_split_configs_adds_regime_3_until_latest_date() -> None:
    dataset = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2025-07-07", "2025-12-31", "2026-01-01", "2026-05-12"]
            ),
            "value": [1, 2, 3, 4],
        }
    )

    result = improved.build_fixed_split_configs(dataset)

    assert result["regime_fixed_split"] == {
        "train_start": "2025-07-07",
        "train_end": "2025-10-31",
        "valid_start": "2025-11-01",
        "valid_end": "2025-12-31",
    }
    assert result["regime_3_fixed_split"] == {
        "train_start": "2025-07-07",
        "train_end": "2025-12-31",
        "valid_start": "2026-01-01",
        "valid_end": "2026-05-12",
    }


def test_build_window_sweep_configs_filters_future_windows() -> None:
    result_regime2 = improved.build_window_sweep_configs(valid_start="2025-11-01")
    result_regime3 = improved.build_window_sweep_configs(valid_start="2026-01-01")

    assert "opening_early" in result_regime2
    assert "regime1_full" in result_regime2
    assert "regime2_only" not in result_regime2
    assert "full_2025" not in result_regime2

    assert "regime2_only" in result_regime3
    assert result_regime3["regime2_only"] == {
        "train_start": "2025-11-01",
        "train_end": "2025-12-31",
    }
    assert result_regime3["full_2025"] == {
        "train_start": "2025-07-07",
        "train_end": "2025-12-31",
    }


def test_run_fixed_window_sweep_selects_best_window(monkeypatch) -> None:
    def fake_evaluate_fixed_split(*args, **kwargs):
        train_start = kwargs["train_start"]
        score = 0.2 if train_start == "2025-07-07" else 0.4
        return {
            "target": kwargs["target"],
            "metrics": {
                "hit_at_1": score,
                "hit_at_2": score,
                "hit_at_3": score,
                "ndcg_at_2": score,
                "ndcg_at_3": score,
                "spearman": score / 10.0,
                "abstain_coverage": 0.0,
                "abstain_hit_at_1": 0.0,
            },
            "metrics_std": improved.zero_metrics(),
            "random_baseline": improved.zero_metrics(),
            "lift_vs_random": {
                key: (score if key not in {"spearman", "abstain_coverage", "abstain_hit_at_1"} else 0.0)
                for key in improved.zero_metrics().keys()
            },
            "n_folds": 1,
            "split_summary": {"train_days": 10, "valid_days": 5},
        }

    monkeypatch.setattr(improved, "evaluate_fixed_split", fake_evaluate_fixed_split)

    result = improved.run_fixed_window_sweep(
        dataset=pd.DataFrame({"date": pd.to_datetime(["2025-01-01"])}),
        target="is_top_3",
        features=[],
        random_state=42,
        decay_lambda=1.5,
        calibration_config=improved.CalibrationConfig(),
        train_windows={
            "window_a": {"train_start": "2025-07-07", "train_end": "2025-10-31"},
            "window_b": {"train_start": "2025-09-01", "train_end": "2025-10-31"},
        },
        valid_start="2025-11-01",
        valid_end="2025-12-31",
    )

    assert result["selection_metric"] == "hit_at_3"
    assert result["best_window"] == "window_b"
    assert result["best_score"] == 0.4


def test_add_regime_and_cluster_features_adds_new_feature_columns() -> None:
    dataset = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2025-07-07", "2025-07-08", "2025-07-09", "2025-07-10"]
            ),
            "entity_key": ["1", "1", "2", "2"],
            "total_diff_coins": [100.0, -50.0, 200.0, 0.0],
            "efficiency": [1.1, 0.9, 1.2, 1.0],
            "win_rate": [0.60, 0.20, 0.80, 0.40],
            "is_event_day": [0, 1, 0, 0],
            "is_rank_1": [1, 0, 0, 1],
            "is_top_2": [1, 1, 0, 1],
            "is_top_3": [1, 1, 1, 1],
        }
    )
    result = improved.add_regime_and_cluster_features(dataset)

    expected_cols = {
        "hall_event_rate_14",
        "hall_event_rate_30",
        "hall_days_since_event",
        "weekday",
        "weekday_sin",
        "weekday_cos",
        "tail_prior_mean_diff",
        "tail_weekday_prior_mean_diff",
        "tail_weekday_delta_from_tail_mean",
        "tail_prior_top_3_win_rate",
        "tail_prior_top_3_samples",
        "tail_prior_top_3_win_rate_ge_60",
        "tail_prior_top_3_win_rate_ge_70",
        "tail_prior_top_3_win_rate_ge_80",
        "tail_prior_top_3_win_rate_ge_80_confident",
        "tail_prior_machine_win_rate_samples",
        "tail_prior_machine_win_rate_mean",
        "tail_prior_machine_win_rate_ewm_7",
        "tail_prior_machine_win_rate_ewm_21",
        "tail_prior_machine_win_rate_ge_30",
        "tail_prior_machine_win_rate_ge_40",
        "tail_prior_machine_win_rate_ge_50",
        "tail_prior_machine_win_rate_ge_60_over",
        "tail_prior_machine_win_rate_ge_60_over_confident",
    }
    assert expected_cols.issubset(set(result.columns))
    assert result[list(expected_cols)].isna().sum().sum() == 0
    first_row = result.iloc[0]
    assert first_row["tail_prior_top_3_samples"] == 0.0
    assert first_row["tail_prior_top_3_win_rate"] == 0.5
    assert first_row["tail_prior_machine_win_rate_samples"] == 0.0
    assert first_row["tail_prior_machine_win_rate_mean"] == 0.0
    second_row = result.iloc[1]
    assert second_row["tail_prior_machine_win_rate_samples"] == 1.0
    assert second_row["tail_prior_machine_win_rate_mean"] == pytest.approx(0.60)
    assert second_row["tail_prior_machine_win_rate_ge_50"] == 1.0


def test_two_stage_candidate_rerank_keeps_only_stage1_candidates() -> None:
    stage1 = np.array([0.9, 0.1, 0.8, 0.2, 0.3, 0.4], dtype=float)
    stage2 = np.array([0.1, 0.9, 0.8, 0.7, 0.2, 0.6], dtype=float)
    groups = np.array([1, 1, 1, 2, 2, 2])

    result = improved.two_stage_candidate_rerank(
        stage1_score=stage1,
        stage2_score=stage2,
        group_ids=groups,
        top_k=1,
        candidate_factor=2,
    )

    # group=1 candidates should be indices 0 and 2; index 1 must be filtered
    assert result[1] < -1e8
    # group=2 candidates should be indices 5 and 4; index 3 must be filtered
    assert result[3] < -1e8
    # kept candidates preserve stage2 scores
    assert result[0] == stage2[0]
    assert result[2] == stage2[2]
