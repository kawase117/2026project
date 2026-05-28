import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from ml.experiments.store_optimized_pipeline import (
    DatasetSpec,
    ExpandingWindowSplitter,
    FoldTargetEncoder,
    PipelineConfig,
    SlidingWindowSplitter,
    StoreOptimizedFeatureBuilder,
    StoreOptimizedTrainingEngine,
)
from ml.experiments.run_store_optimized_pipeline import main as run_pipeline_main


def _seed_store_db(db_path: Path, store_bias: int) -> None:
    conn = sqlite3.connect(db_path)

    machine_type_rows = []
    last_digit_rows = []
    machine_rows = []
    master_rows = [
        ("Alpha", 1, 0, 0, 0),
        ("Beta", 0, 1, 0, 0),
        ("Gamma", 0, 0, 1, 0),
    ]

    for dt in pd.date_range("2025-01-01", periods=45, freq="D"):
        date_text = dt.strftime("%Y%m%d")
        day = dt.dayofyear
        for idx, machine_name in enumerate(["Alpha", "Beta", "Gamma"], start=1):
            total_games = 1800 + (idx * 120) + (day * 15)
            total_diff = (store_bias * 100) + (idx * 80) - (day * 10)
            if machine_name == "Alpha" and day % 3 == 0:
                total_diff += 450
            if machine_name == "Gamma" and day % 4 == 0:
                total_diff -= 220
            avg_games = total_games / 4.0
            avg_diff = total_diff / 4.0
            win_rate = 42 + (idx * 3)
            machine_type_rows.append(
                (
                    date_text,
                    machine_name,
                    4,
                    total_games,
                    avg_games,
                    total_diff,
                    avg_diff,
                    win_rate,
                )
            )

        for last_digit in range(3):
            machine_count = 3
            total_games = 1500 + (last_digit * 150) + (day * 20)
            total_diff = (store_bias * 70) + (last_digit * 60) - (day * 5)
            if last_digit == 1 and day % 2 == 0:
                total_diff += 320
            if last_digit == 2 and day % 5 == 0:
                total_diff -= 180
            avg_games = total_games / machine_count
            avg_diff = total_diff / machine_count
            win_rate = 40 + last_digit * 5
            high_profit_rate = 12 + last_digit * 2
            last_digit_rows.append(
                (
                    date_text,
                    str(last_digit),
                    machine_count,
                    total_games,
                    avg_games,
                    total_diff,
                    avg_diff,
                    win_rate,
                    high_profit_rate,
                )
            )

        for machine_number in range(1, 13):
            machine_name = ["Alpha", "Beta", "Gamma"][machine_number % 3]
            games = 1900 + machine_number * 20 + day * 8
            diff = (store_bias * 60) + (machine_number * 15) - (day * 12)
            if machine_number <= 3 and day % 2 == 0:
                diff += 260
            if machine_number >= 10 and day % 4 == 0:
                diff -= 140
            machine_rows.append(
                (
                    date_text,
                    machine_number,
                    machine_name,
                    str(machine_number % 10),
                    1 if machine_number in {11, 22, 33} else 0,
                    games,
                    diff,
                )
            )

    conn.execute(
        """
        CREATE TABLE daily_machine_type_summary (
            date TEXT,
            machine_name TEXT,
            machine_count INTEGER,
            total_games INTEGER,
            avg_games REAL,
            total_diff_coins INTEGER,
            avg_diff_coins REAL,
            win_rate REAL
        )
        """
    )
    conn.executemany(
        "INSERT INTO daily_machine_type_summary VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        machine_type_rows,
    )

    conn.execute(
        """
        CREATE TABLE machine_master (
            machine_name_normalized TEXT,
            jug_flag INTEGER,
            hana_flag INTEGER,
            oki_flag INTEGER,
            bt_flag INTEGER
        )
        """
    )
    conn.executemany(
        "INSERT INTO machine_master VALUES (?, ?, ?, ?, ?)",
        master_rows,
    )

    conn.execute(
        """
        CREATE TABLE last_digit_summary_all (
            date TEXT,
            last_digit TEXT,
            machine_count INTEGER,
            total_games INTEGER,
            avg_games REAL,
            total_diff_coins INTEGER,
            avg_diff_coins REAL,
            win_rate REAL,
            high_profit_rate REAL
        )
        """
    )
    conn.executemany(
        "INSERT INTO last_digit_summary_all VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        last_digit_rows,
    )

    conn.execute(
        """
        CREATE TABLE machine_detailed_results (
            date TEXT,
            machine_number INTEGER,
            machine_name TEXT,
            last_digit TEXT,
            is_zorome INTEGER,
            games_normalized INTEGER,
            diff_coins_normalized INTEGER
        )
        """
    )
    conn.executemany(
        "INSERT INTO machine_detailed_results VALUES (?, ?, ?, ?, ?, ?, ?)",
        machine_rows,
    )

    conn.commit()
    conn.close()


@pytest.fixture()
def seeded_store_dbs(tmp_path: Path) -> list[Path]:
    db_a = tmp_path / "store_a.db"
    db_b = tmp_path / "store_b.db"
    _seed_store_db(db_a, store_bias=2)
    _seed_store_db(db_b, store_bias=5)
    return [db_a, db_b]


def test_expanding_window_splitter_preserves_temporal_order() -> None:
    df = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=18, freq="D")})
    splitter = ExpandingWindowSplitter(n_splits=3)

    folds = list(splitter.split(df, date_column="date"))

    assert len(folds) == 3
    for fold in folds:
        assert fold.train_indices.size > 0
        assert fold.valid_indices.size > 0
        assert max(fold.train_indices) < min(fold.valid_indices)
        assert fold.train_end_date < fold.valid_start_date


def test_sliding_window_splitter_uses_fixed_train_window() -> None:
    df = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=20, freq="D")})
    splitter = SlidingWindowSplitter(n_splits=3, train_window_size=8, valid_window_size=3)

    folds = list(splitter.split(df, date_column="date"))

    assert len(folds) == 3
    assert [len(fold.train_indices) for fold in folds] == [8, 8, 8]
    for fold in folds:
        assert max(fold.train_indices) < min(fold.valid_indices)


def test_fold_target_encoder_fits_only_on_training_rows() -> None:
    train_df = pd.DataFrame(
        {
            "machine_name": ["A", "A", "B", "B"],
            "target": [1, 1, 0, 0],
        }
    )
    valid_df = pd.DataFrame({"machine_name": ["A", "B", "C"], "target": [0, 1, 1]})

    encoder = FoldTargetEncoder(columns=["machine_name"])
    encoder.fit(train_df, target_column="target")
    encoded = encoder.transform(valid_df)

    assert encoded.loc[0, "te_machine_name"] == pytest.approx(1.0)
    assert encoded.loc[1, "te_machine_name"] == pytest.approx(0.0)
    assert encoded.loc[2, "te_machine_name"] == pytest.approx(0.5)


def test_feature_builder_supports_all_groupings(seeded_store_dbs: list[Path]) -> None:
    builder = StoreOptimizedFeatureBuilder()

    machine_type_df = builder.build_store_dataset(
        db_path=seeded_store_dbs[0],
        grouping="machine_type",
    )
    last_digit_df = builder.build_store_dataset(
        db_path=seeded_store_dbs[0],
        grouping="last_digit",
    )
    machine_position_df = builder.build_store_dataset(
        db_path=seeded_store_dbs[0],
        grouping="machine_number_position",
    )

    for dataset in [machine_type_df, last_digit_df, machine_position_df]:
        assert {"store_id", "entity_key", "date", "is_rank_1", "is_top_3", "is_top_5"}.issubset(dataset.columns)
        assert dataset["date"].dtype.kind == "M"

    assert "machine_type" in machine_type_df.columns
    assert "win_rate" in machine_type_df.columns
    assert "last_digit" in last_digit_df.columns
    assert {
        "top10_flag",
        "top30_flag",
        "top100_flag",
        "position_percentile",
        "edge_flag",
        "center_flag",
    }.issubset(machine_position_df.columns)
    assert "machine_number" not in machine_position_df.columns


def test_feature_builder_adds_same_weekday_event_and_binning_features(
    seeded_store_dbs: list[Path],
) -> None:
    builder = StoreOptimizedFeatureBuilder()
    dataset = builder.build_store_dataset(
        db_path=seeded_store_dbs[0],
        grouping="machine_type",
    )

    required_columns = {
        "lag_7_games",
        "lag_14_games",
        "lag_21_games",
        "same_weekday_lag_1_diff",
        "same_weekday_lag_1_games",
        "same_weekday_lag_1_efficiency",
        "same_weekday_lag_2_diff",
        "same_weekday_lag_3_diff",
        "same_weekday_rolling_avg_diff_3",
        "same_weekday_rolling_avg_games_3",
        "same_weekday_rolling_avg_efficiency_3",
        "is_event_day",
        "event_group",
        "is_month_end_event",
        "days_since_last_event_any",
        "days_to_next_event_any",
        "event_signed_distance_any",
        "event_distance_abs_any",
        "event_distance_decay_3",
        "event_distance_decay_7",
        "event_phase_after_event",
        "event_phase_before_event",
        "is_event_week",
        "event_proximity_score",
        "same_day_of_month_lag_1_diff",
        "same_day_of_month_lag_1_games",
        "same_day_of_month_lag_2_diff",
        "same_day_of_month_rolling_avg_diff_3",
        "same_day_of_month_rolling_avg_games_3",
        "total_games_bin",
        "avg_games_bin",
        "total_diff_coins_bin",
        "avg_diff_coins_bin",
        "efficiency_bin",
    }
    assert required_columns.issubset(dataset.columns)

    alpha = dataset.loc[dataset["entity_key"] == "Alpha"].sort_values("date").reset_index(drop=True)
    jan_01 = alpha.loc[alpha["date"] == pd.Timestamp("2025-01-01")].iloc[0]
    jan_08 = alpha.loc[alpha["date"] == pd.Timestamp("2025-01-08")].iloc[0]
    jan_15 = alpha.loc[alpha["date"] == pd.Timestamp("2025-01-15")].iloc[0]
    jan_22 = alpha.loc[alpha["date"] == pd.Timestamp("2025-01-22")].iloc[0]
    feb_01 = alpha.loc[alpha["date"] == pd.Timestamp("2025-02-01")].iloc[0]
    jan_02 = alpha.loc[alpha["date"] == pd.Timestamp("2025-01-02")].iloc[0]
    jan_31 = alpha.loc[alpha["date"] == pd.Timestamp("2025-01-31")].iloc[0]

    assert jan_08["lag_7_games"] == pytest.approx(jan_01["total_games"])
    assert jan_15["lag_14_games"] == pytest.approx(jan_01["total_games"])
    assert jan_22["lag_21_games"] == pytest.approx(jan_01["total_games"])
    assert jan_08["same_weekday_lag_1_games"] == pytest.approx(jan_01["total_games"])
    assert jan_08["same_weekday_lag_1_diff"] == pytest.approx(jan_01["total_diff_coins"])
    assert feb_01["same_day_of_month_lag_1_games"] == pytest.approx(jan_01["total_games"])
    assert feb_01["same_day_of_month_lag_1_diff"] == pytest.approx(jan_01["total_diff_coins"])

    assert jan_01["is_event_day"] == 1
    assert jan_01["event_group"] == 1
    assert jan_31["is_month_end_event"] == 1
    assert jan_02["days_since_last_event_any"] == pytest.approx(1.0)
    assert jan_02["days_to_next_event_any"] == pytest.approx(5.0)
    assert jan_02["event_signed_distance_any"] == pytest.approx(-4.0)
    assert jan_02["event_distance_abs_any"] == pytest.approx(1.0)
    assert jan_02["event_phase_after_event"] == 1
    assert jan_02["event_phase_before_event"] == 0
    assert jan_02["is_event_week"] == 1
    assert jan_02["event_proximity_score"] == pytest.approx(1.0 / 6.0)
    assert 0.0 <= jan_02["event_distance_decay_3"] <= 1.0
    assert 0.0 <= jan_02["event_distance_decay_7"] <= 1.0

    for column in [
        "total_games_bin",
        "avg_games_bin",
        "total_diff_coins_bin",
        "avg_diff_coins_bin",
        "efficiency_bin",
    ]:
        assert dataset[column].between(0, 4).all()


def test_feature_builder_adds_phase2_weekday_interaction_and_antipattern_features(
    seeded_store_dbs: list[Path],
) -> None:
    builder = StoreOptimizedFeatureBuilder()

    last_digit_df = builder.build_store_dataset(
        db_path=seeded_store_dbs[0],
        grouping="last_digit",
    )
    machine_type_df = builder.build_store_dataset(
        db_path=seeded_store_dbs[0],
        grouping="machine_type",
    )

    last_digit_columns = {
        "dow_lastdigit_rank1_rate",
        "same_weekday_rolling_rank_sum_3",
        "weekday_digit_bias",
        "anti_pattern_rank1_rate",
        "weekday_non_consecutive_rank1_rate",
        "consecutive_suppression_score",
        "prior_worst1_rate",
        "prior_worst3_rate",
        "prior_worst5_rate",
        "prior_top3_rate",
        "prior_top5_rate",
        "prior_rank1_rate",
        "same_weekday_top3_rate",
        "same_day_of_month_top3_gap",
        "same_weekday_rank1_rate",
        "same_day_of_month_rank1_rate",
        "same_weekday_rank1_gap",
        "same_day_of_month_rank1_gap",
        "days_since_last_rank1_same_weekday",
        "days_since_last_rank1_same_day_of_month",
        "rank1_streak_prev",
        "rank1_rebound_score",
        "days_since_last_top3",
        "days_since_last_top5",
        "lag_14_diff",
        "lag_21_diff",
        "lag_14_games",
        "lag_21_games",
        "lag_14_diff_signed_bin",
        "lag_21_diff_signed_bin",
        "lag_14_games_level_bin",
        "lag_21_games_level_bin",
        "days_since_last_top3_age_bin",
        "days_since_last_top5_age_bin",
        "prior_top3_rate_level_bin",
        "prior_top5_rate_level_bin",
        "lag_1_diff_signed_bin",
        "lag_7_diff_signed_bin",
        "lag_1_games_level_bin",
        "rolling_avg_diff_7d_signed_bin",
        "days_since_last_rank1_age_bin",
        "anti_pattern_rank1_rate_level_bin",
        "lag_1_diff_minus_rolling_avg_diff_7d",
        "lag_1_diff_to_rolling_avg_diff_7d_ratio",
        "lag_1_games_minus_rolling_avg_games_7d",
        "same_day_of_month_diff_gap",
        "same_weekday_diff_gap",
        "weekday_bias_x_days_since_rank1",
        "anti_pattern_x_weekday_non_consecutive",
        "dow_lastdigit_x_anti_pattern",
        "days_since_rank1_x_event_proximity",
        "rank1_streak_x_event_decay_3",
        "rank1_rotation_context_gap",
        "rank1_same_cycle_recency_gap",
    }
    machine_type_columns = {
        "dow_machine_name_rank1_rate",
        "prior_worst1_rate",
        "prior_worst3_rate",
        "prior_worst5_rate",
    }
    assert last_digit_columns.issubset(last_digit_df.columns)
    assert machine_type_columns.issubset(machine_type_df.columns)

    digit_one = last_digit_df.loc[last_digit_df["entity_key"] == "1"].sort_values("date").reset_index(drop=True)
    later_digit_one = digit_one.loc[digit_one["date"] >= pd.Timestamp("2025-01-15")]
    assert later_digit_one["dow_lastdigit_rank1_rate"].max() > 0.0
    assert later_digit_one["same_weekday_rolling_rank_sum_3"].max() > 0.0
    assert later_digit_one["anti_pattern_rank1_rate"].max() >= 0.0
    assert later_digit_one["weekday_non_consecutive_rank1_rate"].max() >= 0.0
    assert later_digit_one["prior_top3_rate"].max() > 0.0
    assert later_digit_one["prior_top5_rate"].max() > 0.0
    assert later_digit_one["prior_rank1_rate"].max() >= 0.0
    assert later_digit_one["same_weekday_top3_rate"].max() > 0.0
    assert later_digit_one["same_day_of_month_top3_gap"].abs().max() >= 0.0
    assert later_digit_one["same_weekday_rank1_rate"].max() >= 0.0
    assert later_digit_one["same_day_of_month_rank1_rate"].max() >= 0.0
    assert later_digit_one["days_since_last_rank1_same_weekday"].max() >= 0.0
    assert later_digit_one["days_since_last_rank1_same_day_of_month"].max() >= 0.0
    assert later_digit_one["days_since_last_top3"].max() >= 0.0
    assert later_digit_one["days_since_last_top5"].max() >= 0.0
    assert later_digit_one["rank1_streak_prev"].max() >= 0.0
    assert later_digit_one["rank1_rebound_score"].abs().max() >= 0.0
    assert later_digit_one["lag_1_diff_minus_rolling_avg_diff_7d"].abs().max() > 0.0
    assert later_digit_one["lag_1_diff_to_rolling_avg_diff_7d_ratio"].abs().max() >= 0.0
    assert later_digit_one["weekday_bias_x_days_since_rank1"].abs().max() >= 0.0
    assert later_digit_one["anti_pattern_x_weekday_non_consecutive"].abs().max() >= 0.0

    gamma = machine_type_df.loc[machine_type_df["entity_key"] == "Gamma"].sort_values("date").reset_index(drop=True)
    later_gamma = gamma.loc[gamma["date"] >= pd.Timestamp("2025-01-15")]
    assert later_gamma["dow_machine_name_rank1_rate"].max() >= 0.0
    assert later_gamma["prior_worst1_rate"].max() > 0.0
    assert later_gamma["prior_worst3_rate"].max() > 0.0

    for column in [
        "prior_worst1_rate",
        "prior_worst3_rate",
        "prior_worst5_rate",
    ]:
        assert machine_type_df[column].between(0.0, 1.0).all()
        assert last_digit_df[column].between(0.0, 1.0).all()

    for column in [
        "lag_1_games_level_bin",
        "days_since_last_rank1_age_bin",
        "anti_pattern_rank1_rate_level_bin",
    ]:
        assert (last_digit_df[column] >= 0).all()


def test_last_digit_antipattern_features_follow_expected_definitions(
    seeded_store_dbs: list[Path],
) -> None:
    builder = StoreOptimizedFeatureBuilder()
    dataset = builder.build_store_dataset(
        db_path=seeded_store_dbs[0],
        grouping="last_digit",
    )
    ranked = dataset.copy()
    ranked["digit_rank"] = ranked.groupby("date")["total_diff_coins"].rank(method="first", ascending=False)
    digit_one = ranked.loc[ranked["entity_key"] == "1"].sort_values("date").reset_index(drop=True)

    for idx, row in digit_one.iterrows():
        history = digit_one.iloc[:idx]
        same_weekday_history = history.loc[history["day_of_week"] == row["day_of_week"]]

        expected_same_weekday_sum = float(same_weekday_history["digit_rank"].tail(3).sum()) if not same_weekday_history.empty else 0.0
        assert row["same_weekday_rolling_rank_sum_3"] == pytest.approx(expected_same_weekday_sum)

        if history.empty or same_weekday_history.empty:
            expected_weekday_bias = 0.0
        else:
            expected_weekday_bias = float(same_weekday_history["digit_rank"].mean() - history["digit_rank"].mean())
        assert row["weekday_digit_bias"] == pytest.approx(expected_weekday_bias)

        if idx == 0:
            prev_rank1 = 0
        else:
            prev_rank1 = int(digit_one.iloc[idx - 1]["is_rank_1"])

        eligible_history = history.copy()
        eligible_history["prev_rank1"] = history["is_rank_1"].shift(1).fillna(0).astype(int)
        eligible_non_consecutive = eligible_history.loc[eligible_history["prev_rank1"] == 0]
        weekday_eligible_non_consecutive = eligible_non_consecutive.loc[
            eligible_non_consecutive["day_of_week"] == row["day_of_week"]
        ]

        if prev_rank1 == 0 and not eligible_non_consecutive.empty:
            expected_anti_pattern = float(eligible_non_consecutive["is_rank_1"].mean())
        else:
            expected_anti_pattern = 0.0
        if prev_rank1 == 0 and not weekday_eligible_non_consecutive.empty:
            expected_weekday_non_consecutive = float(weekday_eligible_non_consecutive["is_rank_1"].mean())
        else:
            expected_weekday_non_consecutive = 0.0

        assert row["anti_pattern_rank1_rate"] == pytest.approx(expected_anti_pattern)
        assert row["weekday_non_consecutive_rank1_rate"] == pytest.approx(expected_weekday_non_consecutive)
        assert 0.0 <= row["anti_pattern_rank1_rate"] <= 1.0
        assert 0.0 <= row["weekday_non_consecutive_rank1_rate"] <= 1.0

    assert digit_one["consecutive_suppression_score"].notna().all()
    assert pd.api.types.is_float_dtype(digit_one["consecutive_suppression_score"])


def test_training_engine_runs_single_store_and_pooled_modes(
    seeded_store_dbs: list[Path],
    tmp_path: Path,
) -> None:
    config = PipelineConfig(
        db_paths=seeded_store_dbs,
        groupings=["last_digit"],
        targets=["is_rank_1"],
        base_cv="expanding",
        compare_cv=["sliding"],
        models=["lgbm", "xgb", "catboost"],
        merge_modes=["single_store", "pooled_store_aware"],
        optuna_enabled=True,
        optuna_trials=1,
        optuna_top_k_models=1,
        n_splits=3,
        train_window_size=6,
        valid_window_size=2,
        feature_selection_enabled=True,
        feature_selection_top_k=4,
        feature_selection_strategy="rfecv_boruta",
        feature_selection_rfecv_cv_splits=2,
        feature_selection_permutation_repeats=2,
    )
    engine = StoreOptimizedTrainingEngine(config=config)

    result = engine.run(output_root=tmp_path)

    assert len(result["stores"]) == 2
    summary_path = (
        tmp_path
        / "store_a_exp"
        / "last_digit"
        / "pipeline"
        / "reports"
        / "summary.json"
    )
    leaderboard_path = (
        tmp_path
        / "store_a_exp"
        / "last_digit"
        / "pipeline"
        / "reports"
        / "leaderboard.csv"
    )
    assert summary_path.exists()
    assert leaderboard_path.exists()

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    merge_modes = {row["merge_mode"] for row in summary["runs"]}
    cv_modes = {row["cv_mode"] for row in summary["runs"]}
    assert {"single_store", "pooled_store_aware"} <= merge_modes
    assert {"expanding", "sliding"} <= cv_modes

    optuna_dir = tmp_path / "store_a_exp" / "last_digit" / "pipeline" / "optuna"
    model_dir = tmp_path / "store_a_exp" / "last_digit" / "pipeline" / "models"
    feature_selection_dir = tmp_path / "store_a_exp" / "last_digit" / "pipeline" / "feature_selection"
    summary_html_path = tmp_path / "store_a_exp" / "last_digit" / "pipeline" / "reports" / "summary.html"
    feature_catalog_path = tmp_path / "store_a_exp" / "last_digit" / "pipeline" / "reports" / "feature_catalog.md"
    feature_importance_report_path = (
        tmp_path / "store_a_exp" / "last_digit" / "pipeline" / "reports" / "feature_importance.md"
    )
    assert any(optuna_dir.glob("*.json"))
    assert any(model_dir.glob("*.pkl"))
    assert any(feature_selection_dir.glob("*.json"))
    assert summary_html_path.exists()
    assert feature_catalog_path.exists()
    assert feature_importance_report_path.exists()

    leaderboard = pd.read_csv(leaderboard_path)
    assert {
        "target",
        "merge_mode",
        "model",
        "mean_auc",
        "mean_pr_auc",
        "mean_objective_score",
        "mean_zero_recall_penalty",
        "selection_metric",
        "selection_score",
        "mean_hit_at_1",
        "mean_hit_at_3",
        "mean_threshold_optimized_f1",
        "mean_threshold_optimized_recall",
        "mean_threshold_optimized_precision",
        "mean_base_rate",
        "mean_precision_lift_at_0_5",
        "mean_optimized_precision_lift",
        "mean_lift_penalty",
    }.issubset(leaderboard.columns)
    assert not leaderboard.empty
    first_run = summary["runs"][0]
    assert "mean_pr_auc" in first_run
    assert "mean_objective_score" in first_run
    assert "mean_zero_recall_penalty" in first_run
    assert "mean_hit_at_1" in first_run
    assert "mean_hit_at_3" in first_run
    assert "mean_threshold_optimized_f1" in first_run
    assert "mean_best_threshold" in first_run
    assert "mean_lift_penalty" in first_run
    assert "mean_optimized_precision_lift" in first_run
    assert first_run["mean_objective_score"] == pytest.approx(
        first_run["mean_auc"]
        + first_run["mean_pr_auc"]
        - first_run["mean_zero_recall_penalty"]
        - first_run["mean_lift_penalty"]
    )

    selection_files = list(feature_selection_dir.glob("*.json"))
    selection_payload = json.loads(selection_files[0].read_text(encoding="utf-8"))
    assert selection_payload["selector_model"] == "lgbm"
    assert selection_payload["selector_strategy"] == "rfecv_boruta"
    assert selection_payload["selected_features"]
    assert "boruta_like_features" in selection_payload
    assert "rfecv_selected_features" in selection_payload
    assert "permutation_importances" in selection_payload

    summary_html = summary_html_path.read_text(encoding="utf-8")
    assert "<html" in summary_html.lower()
    assert "Best Configuration" in summary_html
    assert "Feature Importance" in summary_html
    assert "Hit@1" in summary_html
    assert "Opt F1" in summary_html

    feature_catalog = feature_catalog_path.read_text(encoding="utf-8")
    assert "# Feature Catalog" in feature_catalog
    assert "same_weekday_rolling_rank_sum_3" in feature_catalog
    assert "consecutive_suppression_score" in feature_catalog
    assert "自動生成" in feature_catalog

    feature_importance_report = feature_importance_report_path.read_text(encoding="utf-8")
    assert "# Feature Importance Report" in feature_importance_report
    assert "Stable Features" in feature_importance_report
    assert "Permutation Importance" in feature_importance_report


def test_forecast_mode_emits_next_day_predictions_without_same_day_leakage(
    seeded_store_dbs: list[Path],
    tmp_path: Path,
    recwarn: pytest.WarningsRecorder,
) -> None:
    config = PipelineConfig(
        db_paths=[seeded_store_dbs[0]],
        groupings=["last_digit"],
        targets=["is_rank_1"],
        base_cv="expanding",
        compare_cv=[],
        models=["lgbm"],
        merge_modes=["single_store"],
        optuna_enabled=False,
        n_splits=3,
        train_window_size=6,
        valid_window_size=2,
        feature_selection_enabled=True,
        feature_selection_top_k=4,
        feature_selection_strategy="rfecv_boruta",
        feature_selection_rfecv_cv_splits=2,
        feature_selection_permutation_repeats=2,
        forecast_mode=True,
    )
    engine = StoreOptimizedTrainingEngine(config=config)

    engine.run(output_root=tmp_path)

    reports_dir = tmp_path / "store_a_exp" / "last_digit" / "pipeline" / "reports"
    feature_selection_dir = tmp_path / "store_a_exp" / "last_digit" / "pipeline" / "feature_selection"
    forecast_json_path = reports_dir / "next_day_forecast.json"
    forecast_csv_path = reports_dir / "next_day_forecast.csv"
    forecast_html_path = reports_dir / "next_day_forecast.html"
    summary_json_path = reports_dir / "summary.json"

    assert forecast_json_path.exists()
    assert forecast_csv_path.exists()
    assert forecast_html_path.exists()
    assert summary_json_path.exists()

    summary_payload = json.loads(summary_json_path.read_text(encoding="utf-8"))
    assert summary_payload["config"]["forecast_mode"] is True

    forecast_payload = json.loads(forecast_json_path.read_text(encoding="utf-8"))
    assert forecast_payload["target_date"] == "2025-02-15"
    assert forecast_payload["grouping"] == "last_digit"
    assert forecast_payload["store_id"] == "store_a_exp"
    assert len(forecast_payload["predictions"]) == 1
    prediction_block = forecast_payload["predictions"][0]
    assert prediction_block["target"] == "is_rank_1"
    assert prediction_block["model"] == "lgbm"
    assert prediction_block["merge_mode"] == "single_store"
    assert "mean_objective_score" in prediction_block
    assert "mean_hit_at_1" in prediction_block
    assert len(prediction_block["rows"]) == 3
    assert {row["entity_key"] for row in prediction_block["rows"]} == {"0", "1", "2"}

    selection_files = list(feature_selection_dir.glob("*.json"))
    assert selection_files
    selection_payload = json.loads(selection_files[0].read_text(encoding="utf-8"))
    selected_features = set(selection_payload["selected_features"])
    forbidden_same_day_features = {
        "total_games",
        "avg_games",
        "total_diff_coins",
        "avg_diff_coins",
        "win_rate",
        "high_profit_rate",
        "efficiency",
        "total_games_bin",
        "avg_games_bin",
        "total_diff_coins_bin",
        "avg_diff_coins_bin",
        "efficiency_bin",
    }
    assert selected_features.isdisjoint(forbidden_same_day_features)

    warning_messages = [str(warning.message) for warning in recwarn]
    assert not any("X does not have valid feature names" in message for message in warning_messages)


def test_runner_script_creates_overview_reports(
    seeded_store_dbs: list[Path],
    tmp_path: Path,
) -> None:
    db_root = tmp_path / "dbs"
    db_root.mkdir()
    for source_db in seeded_store_dbs:
        target = db_root / source_db.name
        target.write_bytes(source_db.read_bytes())

    output_root = tmp_path / "outputs"
    working_db_root = tmp_path / "working_dbs"
    exit_code = run_pipeline_main(
        [
            "--db-root",
            str(db_root),
            "--db-pattern",
            "*.db",
            "--copy-db-before-run",
            "--working-db-root",
            str(working_db_root),
            "--working-db-suffix",
            "_sandbox",
            "--output-root",
            str(output_root),
            "--groupings",
            "last_digit",
            "--targets",
            "is_rank_1",
            "--n-splits",
            "3",
            "--valid-window-size",
            "2",
            "--train-window-size",
            "6",
            "--optuna-trials",
            "1",
        ]
    )

    assert exit_code == 0
    assert (output_root / "store_optimized_pipeline_overview.json").exists()
    assert (output_root / "store_optimized_pipeline_overview.html").exists()
    overview_catalog_path = output_root / "store_optimized_pipeline_overview_feature_catalog.md"
    assert overview_catalog_path.exists()
    copied_db_files = sorted(working_db_root.glob("*.db"))
    assert len(copied_db_files) == len(seeded_store_dbs)
    assert all(path.stem.endswith("_sandbox") for path in copied_db_files)

    overview_catalog = overview_catalog_path.read_text(encoding="utf-8")
    assert "# Store Optimized Pipeline Feature Catalog" in overview_catalog
    assert "## Grouping: last_digit" in overview_catalog
    assert "same_weekday_rolling_rank_sum_3" in overview_catalog

    overview_payload = json.loads((output_root / "store_optimized_pipeline_overview.json").read_text(encoding="utf-8"))
    assert len(overview_payload["source_db_paths"]) == len(seeded_store_dbs)
    assert len(overview_payload["working_db_paths"]) == len(seeded_store_dbs)
    assert all("_sandbox.db" in path for path in overview_payload["working_db_paths"])
