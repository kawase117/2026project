"""Training engine for store-optimized pipeline."""

from __future__ import annotations

import copy
import json
import logging
import pickle
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import optuna
import pandas as pd
from catboost import CatBoostClassifier
from lightgbm import LGBMClassifier
from sklearn.feature_selection import RFECV
from sklearn.inspection import permutation_importance
from sklearn.model_selection import StratifiedKFold
from xgboost import XGBClassifier

from ml.evaluators.metrics import calculate_hit_at_k, evaluate_model
from ml.experiments.result_format import render_html_page, write_json, write_text
from ml.experiments._pipeline_config import (
    PipelineConfig,
    DatasetSpec,
    FoldEvaluation,
    FoldTargetEncoder,
    META_COLUMNS,
    FORECAST_EXCLUDED_COLUMNS,
    ABLATION_WORST_FEATURE_KEYWORDS,
    ABLATION_WORST_RECENCY_PREFIXES,
    ABLATION_WORST_STREAK_PREFIXES,
    ABLATION_WORST_RATE_KEYWORDS,
    ABLATION_MOMVOL_FEATURE_PREFIXES,
    ABLATION_SAME_DAY_OF_MONTH_PREFIXES,
    ABLATION_SAME_WEEKDAY_PREFIXES,
    ABLATION_RANK1_SPECIAL_PREFIXES,
    ABLATION_EVENT_DISTANCE_REDESIGN_COLUMNS,
    ABLATION_EVENT_FEATURE_COLUMNS,
)
from ml.experiments._pipeline_cv import ExpandingWindowSplitter, SlidingWindowSplitter
from ml.experiments._pipeline_features import StoreOptimizedFeatureBuilder, _infer_store_id


logger = logging.getLogger(__name__)

class StoreOptimizedTrainingEngine:
    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self.feature_builder = StoreOptimizedFeatureBuilder()
        self._feature_selection_cache: dict[tuple[Any, ...], dict[str, Any]] = {}

    def run(self, output_root: Path) -> dict[str, Any]:
        output_root = Path(output_root)
        output_root.mkdir(parents=True, exist_ok=True)

        datasets_by_grouping: dict[str, dict[str, pd.DataFrame]] = {
            grouping: {} for grouping in self.config.groupings
        }
        forecast_datasets_by_grouping: dict[str, dict[str, pd.DataFrame]] = {
            grouping: {} for grouping in self.config.groupings
        }
        for db_path in self.config.db_paths:
            for grouping in self.config.groupings:
                dataset = self.feature_builder.build_store_dataset(db_path=db_path, grouping=grouping)
                datasets_by_grouping[grouping][dataset["store_id"].iat[0]] = dataset
                if self.config.forecast_mode:
                    forecast_dataset = self.feature_builder.build_store_forecast_dataset(
                        db_path=db_path,
                        grouping=grouping,
                    )
                    forecast_datasets_by_grouping[grouping][forecast_dataset["store_id"].iat[0]] = forecast_dataset

        pooled_by_grouping: dict[str, pd.DataFrame] = {
            grouping: pd.concat(datasets_by_grouping[grouping].values(), ignore_index=True)
            for grouping in self.config.groupings
        }

        all_store_summaries: list[dict[str, Any]] = []
        for db_path in self.config.db_paths:
            store_id = _infer_store_id(db_path)
            store_summary = {"store_id": store_id, "groupings": [], "errors": []}
            for grouping in self.config.groupings:
                try:
                    grouping_summary = self._run_grouping(
                        store_id=store_id,
                        grouping=grouping,
                        store_df=datasets_by_grouping[grouping][store_id],
                        pooled_df=pooled_by_grouping[grouping],
                        forecast_df=forecast_datasets_by_grouping[grouping].get(store_id),
                        output_root=output_root,
                    )
                    store_summary["groupings"].append(grouping_summary)
                except Exception as exc:  # pragma: no cover - defensive branch
                    store_summary["errors"].append({"grouping": grouping, "error": str(exc)})
            all_store_summaries.append(store_summary)

        return {"stores": all_store_summaries}

    def _run_grouping(
        self,
        store_id: str,
        grouping: str,
        store_df: pd.DataFrame,
        pooled_df: pd.DataFrame,
        forecast_df: pd.DataFrame | None,
        output_root: Path,
    ) -> dict[str, Any]:
        pipeline_dir = output_root / store_id / grouping / "pipeline"
        features_dir = pipeline_dir / "features"
        cv_dir = pipeline_dir / "cv_runs"
        optuna_dir = pipeline_dir / "optuna"
        models_dir = pipeline_dir / "models"
        feature_selection_dir = pipeline_dir / "feature_selection"
        reports_dir = pipeline_dir / "reports"
        for path in (features_dir, cv_dir, optuna_dir, models_dir, feature_selection_dir, reports_dir):
            path.mkdir(parents=True, exist_ok=True)

        store_df.to_csv(features_dir / f"{store_id}_{grouping}_single_store.csv", index=False)
        pooled_df.to_csv(features_dir / f"{grouping}_pooled_store_aware.csv", index=False)

        leaderboard_rows: list[dict[str, Any]] = []
        summary_runs: list[dict[str, Any]] = []
        best_by_target: dict[str, dict[str, Any]] = {}
        deployable_models_by_target: dict[str, dict[str, Any]] = {}

        for target in self.config.targets:
            if target not in store_df.columns:
                continue

            evaluations: list[dict[str, Any]] = []
            for merge_mode in self.config.merge_modes:
                candidate_df = store_df if merge_mode == "single_store" else pooled_df
                cv_modes = [self.config.base_cv, *self.config.compare_cv]
                for cv_mode in cv_modes:
                    model_rows = []
                    for model_name in self.config.models:
                        result = self._evaluate_model(
                            target_store_id=store_id,
                            grouping=grouping,
                            target=target,
                            merge_mode=merge_mode,
                            cv_mode=cv_mode,
                            candidate_df=candidate_df,
                            target_df=store_df,
                            model_name=model_name,
                            params=self._default_model_params(model_name),
                        )
                        if result is None:
                            continue
                        model_rows.append(result)
                        leaderboard_rows.append(
                            {
                                "target": target,
                                "merge_mode": merge_mode,
                                "cv_mode": cv_mode,
                                "model": model_name,
                                "selection_metric": result["selection_metric"],
                                "selection_score": result["selection_score"],
                                "mean_hit_at_1": result["mean_hit_at_1"],
                                "mean_hit_at_3": result["mean_hit_at_3"],
                                "mean_threshold_optimized_precision": result["mean_threshold_optimized_precision"],
                                "mean_threshold_optimized_recall": result["mean_threshold_optimized_recall"],
                                "mean_threshold_optimized_f1": result["mean_threshold_optimized_f1"],
                                "mean_base_rate": result["mean_base_rate"],
                                "mean_precision_lift_at_0_5": result["mean_precision_lift_at_0_5"],
                                "mean_optimized_precision_lift": result["mean_optimized_precision_lift"],
                                "mean_auc": result["mean_auc"],
                                "mean_pr_auc": result["mean_pr_auc"],
                                "mean_zero_recall_penalty": result["mean_zero_recall_penalty"],
                                "mean_lift_penalty": result["mean_lift_penalty"],
                                "mean_objective_score": result["mean_objective_score"],
                                "fold_count": len(result["folds"]),
                            }
                        )
                        summary_runs.append(result)
                        write_json(
                            cv_dir / f"{target}__{merge_mode}__{cv_mode}__{model_name}.json",
                            result,
                        )
                        if result.get("feature_selection"):
                            write_json(
                                feature_selection_dir / f"{target}__{merge_mode}__{cv_mode}__{model_name}.json",
                                result["feature_selection"],
                            )

                    model_rows.sort(key=lambda row: self._model_sort_key(row, target), reverse=True)
                    evaluations.extend(model_rows)
                    if cv_mode == self.config.base_cv and model_rows:
                        for row in model_rows[: max(1, self.config.optuna_top_k_models)]:
                            final_params = row["params"]
                            if self.config.optuna_enabled:
                                tuned = self._run_optuna(
                                    target_store_id=store_id,
                                    grouping=grouping,
                                    target=target,
                                    merge_mode=merge_mode,
                                    candidate_df=candidate_df,
                                    target_df=store_df,
                                    model_name=row["model"],
                                )
                                write_json(
                                    optuna_dir / f"{target}__{merge_mode}__{row['model']}.json",
                                    tuned,
                                )
                                final_params = tuned.get("best_params") or row["params"]

                            artifact = self._train_final_model(
                                candidate_df=candidate_df,
                                model_name=row["model"],
                                target=target,
                                grouping=grouping,
                                merge_mode=merge_mode,
                                params=final_params,
                            )
                            model_path = models_dir / f"{target}__{merge_mode}__{row['model']}.pkl"
                            with open(model_path, "wb") as f:
                                pickle.dump(artifact, f)

                            current_best = deployable_models_by_target.get(target)
                            if current_best is None or self._model_sort_key(row, target) > self._model_sort_key(current_best, target):
                                deployable_models_by_target[target] = {
                                    "artifact": artifact,
                                    "model_path": str(model_path),
                                    "model": row["model"],
                                    "merge_mode": merge_mode,
                                    "cv_mode": cv_mode,
                                    "selection_metric": row["selection_metric"],
                                    "selection_score": row["selection_score"],
                                    "mean_hit_at_1": row["mean_hit_at_1"],
                                    "mean_hit_at_3": row["mean_hit_at_3"],
                                    "mean_threshold_optimized_precision": row["mean_threshold_optimized_precision"],
                                    "mean_threshold_optimized_recall": row["mean_threshold_optimized_recall"],
                                    "mean_threshold_optimized_f1": row["mean_threshold_optimized_f1"],
                                    "mean_base_rate": row["mean_base_rate"],
                                    "mean_precision_lift_at_0_5": row["mean_precision_lift_at_0_5"],
                                    "mean_optimized_precision_lift": row["mean_optimized_precision_lift"],
                                    "mean_auc": row["mean_auc"],
                                    "mean_pr_auc": row["mean_pr_auc"],
                                    "mean_lift_penalty": row["mean_lift_penalty"],
                                    "mean_objective_score": row["mean_objective_score"],
                                    "params": final_params,
                                }

            if evaluations:
                evaluations.sort(key=lambda row: self._model_sort_key(row, target), reverse=True)
                best_by_target[target] = {
                    "model": evaluations[0]["model"],
                    "merge_mode": evaluations[0]["merge_mode"],
                    "cv_mode": evaluations[0]["cv_mode"],
                    "selection_metric": evaluations[0]["selection_metric"],
                    "selection_score": evaluations[0]["selection_score"],
                    "mean_hit_at_1": evaluations[0]["mean_hit_at_1"],
                    "mean_hit_at_3": evaluations[0]["mean_hit_at_3"],
                    "mean_threshold_optimized_precision": evaluations[0]["mean_threshold_optimized_precision"],
                    "mean_threshold_optimized_recall": evaluations[0]["mean_threshold_optimized_recall"],
                    "mean_threshold_optimized_f1": evaluations[0]["mean_threshold_optimized_f1"],
                    "mean_base_rate": evaluations[0]["mean_base_rate"],
                    "mean_precision_lift_at_0_5": evaluations[0]["mean_precision_lift_at_0_5"],
                    "mean_optimized_precision_lift": evaluations[0]["mean_optimized_precision_lift"],
                    "mean_auc": evaluations[0]["mean_auc"],
                    "mean_pr_auc": evaluations[0]["mean_pr_auc"],
                    "mean_lift_penalty": evaluations[0]["mean_lift_penalty"],
                    "mean_objective_score": evaluations[0]["mean_objective_score"],
                }

        leaderboard_df = pd.DataFrame(leaderboard_rows)
        if not leaderboard_df.empty:
            leaderboard_df.to_csv(reports_dir / "leaderboard.csv", index=False)
        else:
            pd.DataFrame(
                columns=[
                    "target",
                    "merge_mode",
                    "cv_mode",
                    "model",
                    "selection_metric",
                    "selection_score",
                    "mean_hit_at_1",
                    "mean_hit_at_3",
                    "mean_threshold_optimized_precision",
                    "mean_threshold_optimized_recall",
                    "mean_threshold_optimized_f1",
                    "mean_base_rate",
                    "mean_precision_lift_at_0_5",
                    "mean_optimized_precision_lift",
                    "mean_auc",
                    "mean_pr_auc",
                    "mean_zero_recall_penalty",
                    "mean_lift_penalty",
                    "mean_objective_score",
                ]
            ).to_csv(reports_dir / "leaderboard.csv", index=False)

        summary_payload = {
            "store_id": store_id,
            "grouping": grouping,
            "config": {
                "models": self.config.models,
                "merge_modes": self.config.merge_modes,
                "base_cv": self.config.base_cv,
                "compare_cv": self.config.compare_cv,
                "optuna_enabled": self.config.optuna_enabled,
                "feature_selection_enabled": self.config.feature_selection_enabled,
                "feature_selection_selector_model": self.config.feature_selection_selector_model,
                "feature_selection_strategy": self.config.feature_selection_strategy,
                "forecast_mode": self.config.forecast_mode,
                "lift_penalty_weight": self.config.lift_penalty_weight,
                "lift_floor_rank1": self.config.lift_floor_rank1,
                "lift_floor_top3": self.config.lift_floor_top3,
                "lift_floor_top5": self.config.lift_floor_top5,
            },
            "runs": summary_runs,
            "best_by_target": best_by_target,
        }
        if self.config.forecast_mode and forecast_df is not None and deployable_models_by_target:
            forecast_payload = self._build_next_day_forecast_payload(
                store_id=store_id,
                grouping=grouping,
                forecast_df=forecast_df,
                deployable_models_by_target=deployable_models_by_target,
            )
            summary_payload["next_day_forecast"] = {
                "target_date": forecast_payload["target_date"],
                "prediction_count": len(forecast_payload["predictions"]),
            }
            write_json(reports_dir / "next_day_forecast.json", forecast_payload)
            pd.DataFrame(_flatten_forecast_rows(forecast_payload)).to_csv(
                reports_dir / "next_day_forecast.csv",
                index=False,
            )
            write_text(
                reports_dir / "next_day_forecast.html",
                self._render_next_day_forecast_html(forecast_payload),
            )
        feature_catalog_payload = _build_feature_catalog_payload(
            store_id=store_id,
            grouping=grouping,
            dataset=store_df,
        )
        summary_payload["feature_catalog"] = feature_catalog_payload
        write_json(reports_dir / "summary.json", summary_payload)
        write_text(
            reports_dir / "summary.html",
            self._render_grouping_summary_html(
                store_id=store_id,
                grouping=grouping,
                summary_payload=summary_payload,
                leaderboard_df=leaderboard_df,
            ),
        )
        write_text(
            reports_dir / "feature_catalog.md",
            _render_feature_catalog_markdown(feature_catalog_payload),
        )
        feature_importance_payload = _build_feature_importance_payload(summary_payload)
        write_json(reports_dir / "feature_importance.json", feature_importance_payload)
        write_text(
            reports_dir / "feature_importance.md",
            _render_feature_importance_markdown(
                store_id=store_id,
                grouping=grouping,
                feature_importance_payload=feature_importance_payload,
            ),
        )
        return summary_payload

    def _evaluate_model(
        self,
        target_store_id: str,
        grouping: str,
        target: str,
        merge_mode: str,
        cv_mode: str,
        candidate_df: pd.DataFrame,
        target_df: pd.DataFrame,
        model_name: str,
        params: dict[str, Any],
    ) -> dict[str, Any] | None:
        folds = self._select_splitter(cv_mode).split(target_df, date_column="date")
        fold_results: list[dict[str, Any]] = []
        selection_summaries: list[dict[str, Any]] = []

        for fold in folds:
            train_frame = candidate_df[
                (candidate_df["date"] >= fold.train_start_date) & (candidate_df["date"] <= fold.train_end_date)
            ].copy()
            valid_frame = target_df.iloc[fold.valid_indices].copy()
            if train_frame.empty or valid_frame.empty:
                continue
            if train_frame[target].nunique() < 2 or valid_frame[target].nunique() < 2:
                continue

            artifact = self._fit_model_for_fold(
                train_frame=train_frame,
                valid_frame=valid_frame,
                target=target,
                grouping=grouping,
                merge_mode=merge_mode,
                model_name=model_name,
                params=params,
            )
            y_true = valid_frame[target].to_numpy()
            y_pred_proba = artifact["predict_proba"]
            y_pred = (y_pred_proba >= 0.5).astype(int)
            lift_floor = self._lift_floor_for_target(target)
            metrics = evaluate_model(
                y_true,
                y_pred_proba,
                y_pred,
                lift_floor=lift_floor,
                lift_penalty_weight=self.config.lift_penalty_weight,
            )
            hit_at_1 = calculate_hit_at_k(y_true, y_pred_proba, valid_frame["date"].to_numpy(), k=1)
            hit_at_3 = calculate_hit_at_k(y_true, y_pred_proba, valid_frame["date"].to_numpy(), k=3)
            selection_score = hit_at_1 if target == "is_rank_1" else hit_at_3
            seen_category_rate = float(valid_frame["entity_key"].isin(set(train_frame["entity_key"])).mean())
            selection_summaries.append(artifact["selection_summary"])
            fold_result = FoldEvaluation(
                fold_index=fold.fold_index,
                auc=float(metrics["auc"]),
                pr_auc=float(metrics["pr_auc"]),
                brier_score=float(metrics["brier_score"]),
                accuracy=float(metrics["accuracy"]),
                precision=float(metrics["precision"]),
                recall=float(metrics["recall"]),
                f1=float(metrics["f1"]),
                base_rate=float(metrics["base_rate"]),
                precision_lift_at_0_5=float(metrics["precision_lift_at_0_5"]),
                optimized_precision_lift=float(metrics["optimized_precision_lift"]),
                zero_recall_penalty=float(metrics["zero_recall_penalty"]),
                lift_penalty=float(metrics["lift_penalty"]),
                objective_score=float(metrics["objective_score"]),
                best_threshold=float(metrics["best_threshold"]),
                threshold_optimized_precision=float(metrics["optimized_precision"]),
                threshold_optimized_recall=float(metrics["optimized_recall"]),
                threshold_optimized_f1=float(metrics["optimized_f1"]),
                hit_at_1=float(hit_at_1),
                hit_at_3=float(hit_at_3),
                selection_score=float(selection_score),
                seen_category_rate=seen_category_rate,
                new_machine_rate=1.0 - seen_category_rate,
                train_rows=len(train_frame),
                valid_rows=len(valid_frame),
                train_start_date=fold.train_start_date.strftime("%Y-%m-%d"),
                train_end_date=fold.train_end_date.strftime("%Y-%m-%d"),
                valid_start_date=fold.valid_start_date.strftime("%Y-%m-%d"),
                valid_end_date=fold.valid_end_date.strftime("%Y-%m-%d"),
            )
            fold_results.append(asdict(fold_result))

        if not fold_results:
            return None

        aucs = [fold["auc"] for fold in fold_results]
        pr_aucs = [fold["pr_auc"] for fold in fold_results]
        zero_recall_penalties = [fold["zero_recall_penalty"] for fold in fold_results]
        lift_penalties = [fold["lift_penalty"] for fold in fold_results]
        base_rates = [fold["base_rate"] for fold in fold_results]
        precision_lifts_at_0_5 = [fold["precision_lift_at_0_5"] for fold in fold_results]
        optimized_precision_lifts = [fold["optimized_precision_lift"] for fold in fold_results]
        objective_scores = [fold["objective_score"] for fold in fold_results]
        best_thresholds = [fold["best_threshold"] for fold in fold_results]
        optimized_precisions = [fold["threshold_optimized_precision"] for fold in fold_results]
        optimized_recalls = [fold["threshold_optimized_recall"] for fold in fold_results]
        optimized_f1s = [fold["threshold_optimized_f1"] for fold in fold_results]
        hit_at_1_values = [fold["hit_at_1"] for fold in fold_results]
        hit_at_3_values = [fold["hit_at_3"] for fold in fold_results]
        selection_scores = [fold["selection_score"] for fold in fold_results]
        return {
            "target_store_id": target_store_id,
            "grouping": grouping,
            "target": target,
            "merge_mode": merge_mode,
            "cv_mode": cv_mode,
            "model": model_name,
            "params": params,
            "mean_auc": float(np.mean(aucs)),
            "mean_pr_auc": float(np.mean(pr_aucs)),
            "mean_zero_recall_penalty": float(np.mean(zero_recall_penalties)),
            "mean_objective_score": float(np.mean(objective_scores)),
            "mean_best_threshold": float(np.mean(best_thresholds)),
            "mean_threshold_optimized_precision": float(np.mean(optimized_precisions)),
            "mean_threshold_optimized_recall": float(np.mean(optimized_recalls)),
            "mean_threshold_optimized_f1": float(np.mean(optimized_f1s)),
            "mean_base_rate": float(np.mean(base_rates)),
            "mean_precision_lift_at_0_5": float(np.mean(precision_lifts_at_0_5)),
            "mean_optimized_precision_lift": float(np.mean(optimized_precision_lifts)),
            "mean_hit_at_1": float(np.mean(hit_at_1_values)),
            "mean_hit_at_3": float(np.mean(hit_at_3_values)),
            "mean_lift_penalty": float(np.mean(lift_penalties)),
            "selection_metric": self._selection_metric_name(target),
            "selection_score": float(np.mean(selection_scores)),
            "std_auc": float(np.std(aucs)),
            "folds": fold_results,
            "feature_selection": self._aggregate_feature_selection(selection_summaries),
        }

    def _fit_model_for_fold(
        self,
        train_frame: pd.DataFrame,
        valid_frame: pd.DataFrame,
        target: str,
        grouping: str,
        merge_mode: str,
        model_name: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        categorical_columns = _categorical_columns_for_grouping(grouping, merge_mode)
        available_cat_cols = [column for column in categorical_columns if column in train_frame.columns]
        numeric_columns = self._numeric_feature_columns(train_frame, available_cat_cols)
        encoder = FoldTargetEncoder(columns=available_cat_cols).fit(train_frame, target)
        train_encoded = encoder.transform(train_frame)
        valid_encoded = encoder.transform(valid_frame)
        encoded_columns = [f"te_{column}" for column in available_cat_cols]
        base_model_columns = numeric_columns + encoded_columns
        selection_cache_key = (
            "fold",
            grouping,
            merge_mode,
            target,
            train_frame["date"].min().strftime("%Y-%m-%d"),
            train_frame["date"].max().strftime("%Y-%m-%d"),
            len(train_frame),
            tuple(base_model_columns),
        )
        selection_summary = self._select_feature_columns(
            train_matrix=train_encoded[base_model_columns],
            y_train=train_frame[target],
            feature_columns=base_model_columns,
            cache_key=selection_cache_key,
        )
        selected_model_columns = selection_summary["selected_features"]

        if model_name == "catboost":
            train_data = train_encoded[selected_model_columns + available_cat_cols].copy()
            valid_data = valid_encoded[selected_model_columns + available_cat_cols].copy()
            model = self._build_model(model_name, params)
            model.fit(train_data, train_frame[target], cat_features=available_cat_cols, verbose=False)
            predict_proba = model.predict_proba(valid_data)[:, 1]
            return {
                "model": model,
                "predict_proba": predict_proba,
                "encoder": encoder,
                "numeric_columns": numeric_columns,
                "encoded_columns": encoded_columns,
                "selection_summary": selection_summary,
            }

        train_matrix = train_encoded[selected_model_columns]
        valid_matrix = valid_encoded[selected_model_columns]
        model = self._build_model(model_name, params)
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="X does not have valid feature names, but LGBMClassifier was fitted with feature names",
                category=UserWarning,
            )
            model.fit(train_matrix, train_frame[target])
            predict_proba = model.predict_proba(valid_matrix)[:, 1]
        return {
            "model": model,
            "predict_proba": predict_proba,
            "encoder": encoder,
            "numeric_columns": numeric_columns,
            "encoded_columns": encoded_columns,
            "selection_summary": selection_summary,
        }

    def _train_final_model(
        self,
        candidate_df: pd.DataFrame,
        model_name: str,
        target: str,
        grouping: str,
        merge_mode: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        categorical_columns = _categorical_columns_for_grouping(grouping, merge_mode)
        available_cat_cols = [column for column in categorical_columns if column in candidate_df.columns]
        numeric_columns = self._numeric_feature_columns(candidate_df, available_cat_cols)
        encoder = FoldTargetEncoder(columns=available_cat_cols).fit(candidate_df, target)
        encoded = encoder.transform(candidate_df)
        encoded_columns = [f"te_{column}" for column in available_cat_cols]
        base_model_columns = numeric_columns + encoded_columns
        selection_cache_key = (
            "final",
            grouping,
            merge_mode,
            target,
            candidate_df["date"].min().strftime("%Y-%m-%d"),
            candidate_df["date"].max().strftime("%Y-%m-%d"),
            len(candidate_df),
            tuple(base_model_columns),
        )
        selection_summary = self._select_feature_columns(
            train_matrix=encoded[base_model_columns],
            y_train=candidate_df[target],
            feature_columns=base_model_columns,
            cache_key=selection_cache_key,
        )
        selected_model_columns = selection_summary["selected_features"]

        artifact: dict[str, Any] = {
            "model_name": model_name,
            "params": params,
            "target": target,
            "grouping": grouping,
            "merge_mode": merge_mode,
            "numeric_columns": numeric_columns,
            "categorical_columns": available_cat_cols,
            "feature_selection": selection_summary,
        }

        if model_name == "catboost":
            train_data = encoded[selected_model_columns + available_cat_cols].copy()
            model = self._build_model(model_name, params)
            model.fit(train_data, candidate_df[target], cat_features=available_cat_cols, verbose=False)
            artifact["model"] = model
            artifact["encoder"] = encoder
            artifact["selected_model_columns"] = selected_model_columns
            return artifact

        model = self._build_model(model_name, params)
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="X does not have valid feature names, but LGBMClassifier was fitted with feature names",
                category=UserWarning,
            )
            model.fit(encoded[selected_model_columns], candidate_df[target])
        artifact["model"] = model
        artifact["encoder"] = encoder
        artifact["encoded_columns"] = encoded_columns
        artifact["selected_model_columns"] = selected_model_columns
        return artifact

    def _run_optuna(
        self,
        target_store_id: str,
        grouping: str,
        target: str,
        merge_mode: str,
        candidate_df: pd.DataFrame,
        target_df: pd.DataFrame,
        model_name: str,
    ) -> dict[str, Any]:
        def objective(trial: optuna.Trial) -> float:
            params = self._suggest_params(model_name, trial)
            result = self._evaluate_model(
                target_store_id=target_store_id,
                grouping=grouping,
                target=target,
                merge_mode=merge_mode,
                cv_mode=self.config.base_cv,
                candidate_df=candidate_df,
                target_df=target_df,
                model_name=model_name,
                params=params,
            )
            if result is None:
                return 0.0
            return result["mean_objective_score"]

        sampler = optuna.samplers.TPESampler(seed=self.config.random_state)
        study = optuna.create_study(direction="maximize", sampler=sampler)
        study.optimize(objective, n_trials=self.config.optuna_trials, show_progress_bar=False)
        return {
            "target": target,
            "merge_mode": merge_mode,
            "model": model_name,
            "best_value": float(study.best_value),
            "best_params": study.best_params,
            "trials": [
                {
                    "number": trial.number,
                    "value": None if trial.value is None else float(trial.value),
                    "params": trial.params,
                }
                for trial in study.trials
            ],
        }

    def _select_splitter(self, cv_mode: str) -> ExpandingWindowSplitter | SlidingWindowSplitter:
        if cv_mode == "expanding":
            return ExpandingWindowSplitter(
                n_splits=self.config.n_splits,
                valid_window_size=self.config.valid_window_size,
            )
        if cv_mode == "sliding":
            return SlidingWindowSplitter(
                n_splits=self.config.n_splits,
                train_window_size=self.config.train_window_size,
                valid_window_size=self.config.valid_window_size,
            )
        raise ValueError(f"Unsupported cv_mode: {cv_mode}")

    def _selection_metric_name(self, target: str) -> str:
        return "hit_at_1" if target == "is_rank_1" else "hit_at_3"

    def _lift_floor_for_target(self, target: str) -> float:
        if target == "is_rank_1":
            return self.config.lift_floor_rank1
        if target == "is_top_3":
            return self.config.lift_floor_top3
        if target == "is_top_5":
            return self.config.lift_floor_top5
        return 1.0

    def _model_sort_key(self, result: dict[str, Any], target: str) -> tuple[float, float, float, float]:
        return (
            float(result["selection_score"]),
            float(result["mean_threshold_optimized_f1"]),
            float(result["mean_objective_score"]),
            float(result["mean_auc"]),
        )

    def _numeric_feature_columns(self, df: pd.DataFrame, categorical_columns: list[str]) -> list[str]:
        numeric_columns = _numeric_feature_columns(df, categorical_columns)
        if not self.config.forecast_mode:
            filtered = numeric_columns
        else:
            filtered = [column for column in numeric_columns if column not in FORECAST_EXCLUDED_COLUMNS]
        return self._apply_feature_ablation(filtered)

    def _apply_feature_ablation(self, columns: list[str]) -> list[str]:
        mode = self.config.feature_ablation_mode
        if mode == "none":
            return columns

        def is_worst_feature(name: str) -> bool:
            lower = name.lower()
            return any(keyword in lower for keyword in ABLATION_WORST_FEATURE_KEYWORDS)

        def is_momvol_feature(name: str) -> bool:
            lower = name.lower()
            return any(lower.startswith(prefix) for prefix in ABLATION_MOMVOL_FEATURE_PREFIXES)

        def is_same_day_of_month_feature(name: str) -> bool:
            lower = name.lower()
            return any(lower.startswith(prefix) for prefix in ABLATION_SAME_DAY_OF_MONTH_PREFIXES)

        def is_same_weekday_feature(name: str) -> bool:
            lower = name.lower()
            return any(lower.startswith(prefix) for prefix in ABLATION_SAME_WEEKDAY_PREFIXES)

        def is_event_feature(name: str) -> bool:
            return name in ABLATION_EVENT_FEATURE_COLUMNS

        def is_rank1_special_feature(name: str) -> bool:
            lower = name.lower()
            return any(lower.startswith(prefix) for prefix in ABLATION_RANK1_SPECIAL_PREFIXES)

        def is_event_distance_redesign_feature(name: str) -> bool:
            return name in ABLATION_EVENT_DISTANCE_REDESIGN_COLUMNS

        def is_worst_recency_feature(name: str) -> bool:
            lower = name.lower()
            return any(lower.startswith(prefix) for prefix in ABLATION_WORST_RECENCY_PREFIXES)

        def is_worst_streak_feature(name: str) -> bool:
            lower = name.lower()
            return any(lower.startswith(prefix) for prefix in ABLATION_WORST_STREAK_PREFIXES)

        def is_worst_rate_feature(name: str) -> bool:
            lower = name.lower()
            if is_worst_recency_feature(name) or is_worst_streak_feature(name):
                return False
            return any(keyword in lower for keyword in ABLATION_WORST_RATE_KEYWORDS)

        if mode == "worst_off":
            return [column for column in columns if not is_worst_feature(column)]
        if mode == "momvol_off":
            return [column for column in columns if not is_momvol_feature(column)]
        if mode == "both_off":
            return [
                column
                for column in columns
                if not is_worst_feature(column) and not is_momvol_feature(column)
            ]
        if mode == "worst_rate_off":
            return [column for column in columns if not is_worst_rate_feature(column)]
        if mode == "worst_streak_off":
            return [column for column in columns if not is_worst_streak_feature(column)]
        if mode == "worst_only_recency":
            return [
                column
                for column in columns
                if not is_worst_feature(column) or is_worst_recency_feature(column)
            ]
        if mode == "same_day_of_month_off":
            return [column for column in columns if not is_same_day_of_month_feature(column)]
        if mode == "worst_rate_off_same_day_of_month_off":
            return [
                column
                for column in columns
                if not is_worst_rate_feature(column) and not is_same_day_of_month_feature(column)
            ]
        if mode == "same_weekday_off":
            return [column for column in columns if not is_same_weekday_feature(column)]
        if mode == "worst_rate_off_same_weekday_off":
            return [
                column
                for column in columns
                if not is_worst_rate_feature(column) and not is_same_weekday_feature(column)
            ]
        if mode == "event_off":
            return [column for column in columns if not is_event_feature(column)]
        if mode == "worst_rate_off_event_off":
            return [
                column
                for column in columns
                if not is_worst_rate_feature(column) and not is_event_feature(column)
            ]
        if mode == "rank1_special_off":
            return [column for column in columns if not is_rank1_special_feature(column)]
        if mode == "event_distance_redesign_off":
            return [column for column in columns if not is_event_distance_redesign_feature(column)]
        if mode == "rank1_special_off_event_distance_redesign_off":
            return [
                column
                for column in columns
                if not is_rank1_special_feature(column) and not is_event_distance_redesign_feature(column)
            ]
        raise ValueError(f"Unknown feature_ablation_mode: {mode}")

    def _build_model(self, model_name: str, params: dict[str, Any]) -> Any:
        if model_name == "lgbm":
            return LGBMClassifier(random_state=self.config.random_state, verbosity=-1, **params)
        if model_name == "xgb":
            return XGBClassifier(
                random_state=self.config.random_state,
                eval_metric="logloss",
                verbosity=0,
                **params,
            )
        if model_name == "catboost":
            return CatBoostClassifier(
                random_seed=self.config.random_state,
                verbose=False,
                allow_writing_files=False,
                **params,
            )
        raise ValueError(f"Unsupported model: {model_name}")

    def _default_model_params(self, model_name: str) -> dict[str, Any]:
        if model_name == "lgbm":
            return {"n_estimators": 60, "learning_rate": 0.05, "max_depth": 4, "num_leaves": 31}
        if model_name == "xgb":
            return {"n_estimators": 60, "learning_rate": 0.05, "max_depth": 4, "subsample": 0.9, "colsample_bytree": 0.9}
        if model_name == "catboost":
            return {"iterations": 60, "learning_rate": 0.05, "depth": 4, "l2_leaf_reg": 3.0}
        raise ValueError(f"Unsupported model: {model_name}")

    def _suggest_params(self, model_name: str, trial: optuna.Trial) -> dict[str, Any]:
        if model_name == "lgbm":
            return {
                "n_estimators": trial.suggest_int("n_estimators", 40, 90),
                "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.10),
                "max_depth": trial.suggest_int("max_depth", 3, 6),
                "num_leaves": trial.suggest_int("num_leaves", 15, 63),
            }
        if model_name == "xgb":
            return {
                "n_estimators": trial.suggest_int("n_estimators", 40, 90),
                "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.10),
                "max_depth": trial.suggest_int("max_depth", 3, 6),
                "subsample": trial.suggest_float("subsample", 0.7, 1.0),
                "colsample_bytree": trial.suggest_float("colsample_bytree", 0.7, 1.0),
            }
        if model_name == "catboost":
            return {
                "iterations": trial.suggest_int("iterations", 40, 90),
                "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.10),
                "depth": trial.suggest_int("depth", 3, 6),
                "l2_leaf_reg": trial.suggest_float("l2_leaf_reg", 1.0, 5.0),
            }
        raise ValueError(f"Unsupported model: {model_name}")

    def _select_feature_columns(
        self,
        train_matrix: pd.DataFrame,
        y_train: pd.Series,
        feature_columns: list[str],
        cache_key: tuple[Any, ...] | None = None,
    ) -> dict[str, Any]:
        if not self.config.feature_selection_enabled or not feature_columns:
            return {
                "selector_model": self.config.feature_selection_selector_model,
                "selector_strategy": self.config.feature_selection_strategy,
                "selected_features": feature_columns,
                "dropped_features": [],
                "feature_importances": {},
                "permutation_importances": {},
            }

        if cache_key is not None and cache_key in self._feature_selection_cache:
            return copy.deepcopy(self._feature_selection_cache[cache_key])

        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="X does not have valid feature names, but LGBMClassifier was fitted with feature names",
                category=UserWarning,
            )
            selector = self._build_selector_model()
            selector.fit(train_matrix[feature_columns], y_train)
            base_importances = _extract_named_importances(selector, feature_columns)

            keep_count = self.config.feature_selection_top_k
            if keep_count is None:
                keep_count = ceil(len(feature_columns) * self.config.feature_selection_keep_ratio)
            keep_count = max(1, min(len(feature_columns), max(self.config.feature_selection_min_features, keep_count)))

            base_ranking = sorted(
                base_importances.items(),
                key=lambda item: (float(item[1]), item[0]),
                reverse=True,
            )
            fallback_features = [name for name, _ in base_ranking[:keep_count]]

            strategy = self.config.feature_selection_strategy
            boruta_selected = feature_columns
            rfecv_selected = feature_columns
            rfecv_ranking: dict[str, int] = {feature: 1 for feature in feature_columns}
            rfecv_scores: list[float] = []
            shadow_threshold = 0.0

            if strategy == "importance":
                selected_features = fallback_features
            elif strategy == "rfecv_boruta":
                boruta_summary = self._run_boruta_like_selection(
                    train_matrix=train_matrix,
                    y_train=y_train,
                    feature_columns=feature_columns,
                )
                boruta_selected = boruta_summary["selected_features"]
                shadow_threshold = boruta_summary["shadow_threshold"]
                rfecv_summary = self._run_rfecv_selection(
                    train_matrix=train_matrix,
                    y_train=y_train,
                    feature_columns=boruta_selected or fallback_features,
                )
                rfecv_selected = rfecv_summary["selected_features"]
                rfecv_ranking = rfecv_summary["ranking"]
                rfecv_scores = rfecv_summary["cv_scores"]
                selected_features = rfecv_selected or boruta_selected or fallback_features
            else:
                raise ValueError(f"Unsupported feature selection strategy: {strategy}")

            permutation_importances = self._compute_permutation_importances(
                train_matrix=train_matrix,
                y_train=y_train,
                feature_columns=feature_columns,
            )
        dropped_features = [name for name in feature_columns if name not in selected_features]

        feature_scorecard = []
        for feature in feature_columns:
            feature_scorecard.append(
                {
                    "feature": feature,
                    "model_importance": float(base_importances.get(feature, 0.0)),
                    "permutation_importance": float(permutation_importances.get(feature, 0.0)),
                    "selected": feature in selected_features,
                    "boruta_like_selected": feature in boruta_selected,
                    "rfecv_selected": feature in rfecv_selected,
                    "rfecv_rank": int(rfecv_ranking.get(feature, 999)),
                }
            )
        feature_scorecard.sort(
            key=lambda item: (
                not item["selected"],
                -item["permutation_importance"],
                -item["model_importance"],
                item["rfecv_rank"],
                item["feature"],
            )
        )

        summary = {
            "selector_model": self.config.feature_selection_selector_model,
            "selector_strategy": strategy,
            "selected_features": selected_features,
            "dropped_features": dropped_features,
            "feature_importances": base_importances,
            "permutation_importances": permutation_importances,
            "boruta_like_features": boruta_selected,
            "rfecv_selected_features": rfecv_selected,
            "rfecv_ranking": rfecv_ranking,
            "rfecv_cv_scores": rfecv_scores,
            "shadow_threshold": float(shadow_threshold),
            "feature_scorecard": feature_scorecard,
        }
        if cache_key is not None:
            self._feature_selection_cache[cache_key] = copy.deepcopy(summary)
        return summary

    def _aggregate_feature_selection(self, selection_summaries: list[dict[str, Any]]) -> dict[str, Any]:
        if not selection_summaries:
            return {}

        frequency: dict[str, int] = {}
        selector_model = selection_summaries[0].get("selector_model")
        selector_strategy = selection_summaries[0].get("selector_strategy")
        model_importance_totals: dict[str, float] = {}
        permutation_totals: dict[str, float] = {}
        boruta_frequency: dict[str, int] = {}
        rfecv_frequency: dict[str, int] = {}
        latest_importances = selection_summaries[-1].get("feature_importances", {})
        latest_permutation_importances = selection_summaries[-1].get("permutation_importances", {})
        for selection in selection_summaries:
            for feature in selection.get("selected_features", []):
                frequency[feature] = frequency.get(feature, 0) + 1
            for feature, value in selection.get("feature_importances", {}).items():
                model_importance_totals[feature] = model_importance_totals.get(feature, 0.0) + float(value)
            for feature, value in selection.get("permutation_importances", {}).items():
                permutation_totals[feature] = permutation_totals.get(feature, 0.0) + float(value)
            for feature in selection.get("boruta_like_features", []):
                boruta_frequency[feature] = boruta_frequency.get(feature, 0) + 1
            for feature in selection.get("rfecv_selected_features", []):
                rfecv_frequency[feature] = rfecv_frequency.get(feature, 0) + 1

        ordered_frequency = sorted(frequency.items(), key=lambda item: (-item[1], item[0]))
        stable_features = [
            feature
            for feature, count in ordered_frequency
            if count == len(selection_summaries)
        ]
        consensus_features = [
            feature
            for feature, count in ordered_frequency
            if count >= ceil(len(selection_summaries) / 2)
        ]
        mean_model_importances = {
            feature: value / len(selection_summaries)
            for feature, value in model_importance_totals.items()
        }
        mean_permutation_importances = {
            feature: value / len(selection_summaries)
            for feature, value in permutation_totals.items()
        }
        top_features = sorted(
            (
                {
                    "feature": feature,
                    "selected_in_folds": count,
                    "mean_model_importance": float(mean_model_importances.get(feature, 0.0)),
                    "mean_permutation_importance": float(mean_permutation_importances.get(feature, 0.0)),
                    "boruta_selected_in_folds": boruta_frequency.get(feature, 0),
                    "rfecv_selected_in_folds": rfecv_frequency.get(feature, 0),
                }
                for feature, count in ordered_frequency
            ),
            key=lambda item: (
                -item["selected_in_folds"],
                -item["mean_permutation_importance"],
                -item["mean_model_importance"],
                item["feature"],
            ),
        )
        return {
            "selector_model": selector_model,
            "selector_strategy": selector_strategy,
            "fold_count": len(selection_summaries),
            "selected_features": selection_summaries[-1].get("selected_features", []),
            "boruta_like_features": selection_summaries[-1].get("boruta_like_features", []),
            "rfecv_selected_features": selection_summaries[-1].get("rfecv_selected_features", []),
            "stable_features": stable_features,
            "consensus_features": consensus_features,
            "feature_frequency": [
                {"feature": feature, "selected_in_folds": count}
                for feature, count in ordered_frequency
            ],
            "latest_feature_importances": latest_importances,
            "permutation_importances": latest_permutation_importances,
            "mean_model_importances": mean_model_importances,
            "mean_permutation_importances": mean_permutation_importances,
            "top_features": top_features[:20],
            "top_features_by_permutation": sorted(
                top_features,
                key=lambda item: (
                    -item["mean_permutation_importance"],
                    -item["mean_model_importance"],
                    -item["selected_in_folds"],
                    item["feature"],
                ),
            )[:20],
        }

    def _build_selector_model(self) -> Any:
        selector_model = self.config.feature_selection_selector_model
        if selector_model == "lgbm":
            return LGBMClassifier(
                random_state=self.config.random_state,
                verbosity=-1,
                n_estimators=50,
                learning_rate=0.05,
                max_depth=3,
                num_leaves=15,
            )
        if selector_model == "xgb":
            return XGBClassifier(
                random_state=self.config.random_state,
                eval_metric="logloss",
                verbosity=0,
                n_estimators=50,
                learning_rate=0.05,
                max_depth=3,
                subsample=0.9,
                colsample_bytree=0.9,
            )
        raise ValueError(f"Unsupported feature selection selector model: {selector_model}")

    def _run_boruta_like_selection(
        self,
        *,
        train_matrix: pd.DataFrame,
        y_train: pd.Series,
        feature_columns: list[str],
    ) -> dict[str, Any]:
        if len(feature_columns) <= self.config.feature_selection_min_features:
            return {"selected_features": feature_columns, "shadow_threshold": 0.0}

        selector = self._build_selector_model()
        rng = np.random.default_rng(self.config.random_state)
        shadow_matrix = pd.DataFrame(index=train_matrix.index)
        shadow_columns = []
        for column in feature_columns:
            shadow_name = f"shadow__{column}"
            shadow_columns.append(shadow_name)
            shadow_matrix[shadow_name] = rng.permutation(train_matrix[column].to_numpy())

        combined = pd.concat([train_matrix[feature_columns], shadow_matrix], axis=1)
        selector.fit(combined.to_numpy(), y_train.to_numpy())
        importances = _extract_named_importances(selector, combined.columns.tolist())
        shadow_values = [float(importances.get(column, 0.0)) for column in shadow_columns]
        shadow_threshold = float(np.quantile(shadow_values, self.config.feature_selection_shadow_quantile)) if shadow_values else 0.0
        selected_features = [
            column
            for column in feature_columns
            if float(importances.get(column, 0.0)) > shadow_threshold
        ]
        if len(selected_features) < min(self.config.feature_selection_min_features, len(feature_columns)):
            base_importances = _extract_named_importances(self._fit_selector(train_matrix[feature_columns], y_train), feature_columns)
            fallback_ranking = sorted(base_importances.items(), key=lambda item: (float(item[1]), item[0]), reverse=True)
            keep_count = min(
                len(feature_columns),
                max(self.config.feature_selection_min_features, self.config.feature_selection_top_k or self.config.feature_selection_min_features),
            )
            selected_features = [name for name, _ in fallback_ranking[:keep_count]]

        return {
            "selected_features": selected_features,
            "shadow_threshold": shadow_threshold,
        }

    def _run_rfecv_selection(
        self,
        *,
        train_matrix: pd.DataFrame,
        y_train: pd.Series,
        feature_columns: list[str],
    ) -> dict[str, Any]:
        if len(feature_columns) <= self.config.feature_selection_min_features:
            return {
                "selected_features": feature_columns,
                "ranking": {feature: 1 for feature in feature_columns},
                "cv_scores": [],
            }

        class_counts = y_train.value_counts()
        min_class_count = int(class_counts.min()) if not class_counts.empty else 0
        cv_splits = min(self.config.feature_selection_rfecv_cv_splits, max(2, min_class_count))
        if cv_splits < 2:
            return {
                "selected_features": feature_columns,
                "ranking": {feature: 1 for feature in feature_columns},
                "cv_scores": [],
            }

        selector = self._build_selector_model()
        cv_splitter = list(self._make_date_aware_cv(train_matrix["date"], n_splits=cv_splits))
        rfecv = RFECV(
            estimator=selector,
            step=max(1, len(feature_columns) // 5),
            cv=cv_splitter,
            scoring="roc_auc",
            min_features_to_select=min(self.config.feature_selection_min_features, len(feature_columns)),
        )
        rfecv.fit(train_matrix[feature_columns].to_numpy(), y_train.to_numpy())
        selected_features = [
            feature
            for feature, keep in zip(feature_columns, rfecv.support_, strict=True)
            if bool(keep)
        ]
        ranking = {
            feature: int(rank)
            for feature, rank in zip(feature_columns, rfecv.ranking_, strict=True)
        }
        cv_scores = [
            float(score)
            for score in rfecv.cv_results_.get("mean_test_score", [])
            if score is not None
        ]
        return {
            "selected_features": selected_features or feature_columns,
            "ranking": ranking,
            "cv_scores": cv_scores,
        }

    def _compute_permutation_importances(
        self,
        *,
        train_matrix: pd.DataFrame,
        y_train: pd.Series,
        feature_columns: list[str],
    ) -> dict[str, float]:
        if not feature_columns:
            return {}
        if y_train.nunique() < 2:
            return {feature: 0.0 for feature in feature_columns}

        selector = self._fit_selector(train_matrix[feature_columns], y_train)
        try:
            result = permutation_importance(
                selector,
                train_matrix[feature_columns].to_numpy(),
                y_train.to_numpy(),
                scoring="roc_auc",
                n_repeats=self.config.feature_selection_permutation_repeats,
                random_state=self.config.random_state,
            )
            return {
                feature: float(importance)
                for feature, importance in zip(feature_columns, result.importances_mean, strict=False)
            }
        except ValueError as e:
            logger.warning(
                "permutation_importance failed for %d features: %s – filling with 0.0",
                len(feature_columns),
                e,
            )
            return {feature: 0.0 for feature in feature_columns}
        except Exception as e:
            logger.error(
                "unexpected error computing permutation_importance for %d features: %s",
                len(feature_columns),
                e,
            )
            raise

    def _fit_selector(self, train_matrix: pd.DataFrame, y_train: pd.Series) -> Any:
        selector = self._build_selector_model()
        selector.fit(train_matrix.to_numpy(), y_train.to_numpy())
        return selector

    def _make_date_aware_cv(self, dates: pd.Series, n_splits: int) -> Iterable[tuple[np.ndarray, np.ndarray]]:
        unique_dates = np.sort(dates.unique())
        if len(unique_dates) < n_splits + 1:
            logger.warning(
                "not enough unique dates (%d) for %d inner CV splits; using StratifiedKFold fallback",
                len(unique_dates),
                n_splits,
            )
            skf = StratifiedKFold(n_splits=min(n_splits, 2), shuffle=False)
            for train_idx, valid_idx in skf.split(dates, np.ones(len(dates))):
                yield train_idx, valid_idx
            return

        fold_size = max(1, len(unique_dates) // (n_splits + 1))
        for i in range(n_splits):
            valid_start = fold_size * (i + 1)
            valid_end = min(valid_start + fold_size, len(unique_dates))
            train_mask = np.isin(dates.to_numpy(), unique_dates[:valid_start])
            valid_mask = np.isin(dates.to_numpy(), unique_dates[valid_start:valid_end])
            train_idx = np.flatnonzero(train_mask)
            valid_idx = np.flatnonzero(valid_mask)
            if len(train_idx) > 0 and len(valid_idx) > 0:
                yield train_idx, valid_idx

    def _predict_with_artifact(
        self,
        *,
        forecast_df: pd.DataFrame,
        artifact: dict[str, Any],
    ) -> np.ndarray:
        encoded = artifact["encoder"].transform(forecast_df.copy())
        selected_model_columns = artifact["selected_model_columns"]
        if artifact["model_name"] == "catboost":
            categorical_columns = artifact["categorical_columns"]
            predict_frame = encoded[selected_model_columns + categorical_columns].copy()
            return artifact["model"].predict_proba(predict_frame)[:, 1]
        predict_frame = encoded[selected_model_columns]
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="X does not have valid feature names, but LGBMClassifier was fitted with feature names",
                category=UserWarning,
            )
            return artifact["model"].predict_proba(predict_frame)[:, 1]

    def _build_next_day_forecast_payload(
        self,
        *,
        store_id: str,
        grouping: str,
        forecast_df: pd.DataFrame,
        deployable_models_by_target: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        target_date = pd.Timestamp(forecast_df["date"].max()).strftime("%Y-%m-%d")
        source_latest_date = (
            pd.Timestamp(forecast_df["date"].max()) - pd.Timedelta(days=1)
        ).strftime("%Y-%m-%d")
        predictions = []

        for target, model_info in sorted(deployable_models_by_target.items()):
            probabilities = self._predict_with_artifact(
                forecast_df=forecast_df,
                artifact=model_info["artifact"],
            )
            rows = []
            for row, probability in zip(forecast_df.itertuples(index=False), probabilities, strict=False):
                payload = {
                    "entity_key": str(row.entity_key),
                    "date": pd.Timestamp(row.date).strftime("%Y-%m-%d"),
                    "probability": float(probability),
                }
                for column in ("machine_name", "machine_type", "last_digit", "is_zorome"):
                    if hasattr(row, column):
                        payload[column] = getattr(row, column)
                rows.append(payload)
            rows.sort(key=lambda item: (-item["probability"], item["entity_key"]))
            predictions.append(
                {
                    "target": target,
                    "model": model_info["model"],
                    "merge_mode": model_info["merge_mode"],
                    "cv_mode": model_info["cv_mode"],
                    "selection_metric": model_info["selection_metric"],
                    "selection_score": float(model_info["selection_score"]),
                    "mean_hit_at_1": float(model_info["mean_hit_at_1"]),
                    "mean_hit_at_3": float(model_info["mean_hit_at_3"]),
                    "mean_threshold_optimized_precision": float(model_info["mean_threshold_optimized_precision"]),
                    "mean_threshold_optimized_recall": float(model_info["mean_threshold_optimized_recall"]),
                    "mean_threshold_optimized_f1": float(model_info["mean_threshold_optimized_f1"]),
                    "mean_base_rate": float(model_info["mean_base_rate"]),
                    "mean_precision_lift_at_0_5": float(model_info["mean_precision_lift_at_0_5"]),
                    "mean_optimized_precision_lift": float(model_info["mean_optimized_precision_lift"]),
                    "mean_auc": float(model_info["mean_auc"]),
                    "mean_pr_auc": float(model_info["mean_pr_auc"]),
                    "mean_lift_penalty": float(model_info["mean_lift_penalty"]),
                    "mean_objective_score": float(model_info["mean_objective_score"]),
                    "rows": rows,
                }
            )

        return {
            "store_id": store_id,
            "grouping": grouping,
            "source_latest_date": source_latest_date,
            "target_date": target_date,
            "predictions": predictions,
        }

    def _render_next_day_forecast_html(self, forecast_payload: dict[str, Any]) -> str:
        sections = []
        for prediction in forecast_payload.get("predictions", []):
            rows_html = "".join(
                f"<tr><td>{escape(str(row.get('entity_key')))}</td>"
                f"<td>{escape(_format_html_value(row.get('probability')))}</td>"
                f"<td>{escape(str(row.get('machine_name', row.get('machine_type', row.get('last_digit', '-')))))}</td></tr>"
                for row in prediction.get("rows", [])
            )
            sections.append(
                f"""
                <section>
                  <h2>{escape(str(prediction['target']))} / {escape(str(prediction['model']))}</h2>
                  <p>Merge Mode: {escape(str(prediction['merge_mode']))} | Selection: {escape(str(prediction['selection_metric']))}={escape(_format_html_value(prediction['selection_score']))} | Hit@1: {escape(_format_html_value(prediction['mean_hit_at_1']))} | Hit@3: {escape(_format_html_value(prediction['mean_hit_at_3']))} | Opt F1: {escape(_format_html_value(prediction['mean_threshold_optimized_f1']))} | Objective: {escape(_format_html_value(prediction['mean_objective_score']))} | AUC: {escape(_format_html_value(prediction['mean_auc']))} | PR-AUC: {escape(_format_html_value(prediction['mean_pr_auc']))}</p>
                  <table>
                    <tr><th>Entity</th><th>Probability</th><th>Label</th></tr>
                    {rows_html}
                  </table>
                </section>
                """
            )

        body = f"""
        <section class="hero">
          <p class="eyebrow">Store Optimized Pipeline</p>
          <h1>{escape(str(forecast_payload['store_id']))} / {escape(str(forecast_payload['grouping']))}</h1>
          <p class="lede">Next-day forecast generated from historical features only.</p>
          <p>Source latest date: {escape(str(forecast_payload['source_latest_date']))}</p>
          <p>Target date: {escape(str(forecast_payload['target_date']))}</p>
        </section>
        {''.join(sections)}
        """
        return render_html_page(
            title=f"{forecast_payload['store_id']} / {forecast_payload['grouping']} forecast",
            body=body,
        )

    def _render_grouping_summary_html(
        self,
        *,
        store_id: str,
        grouping: str,
        summary_payload: dict[str, Any],
        leaderboard_df: pd.DataFrame,
    ) -> str:
        best_rows = "".join(
            f"<tr><th>{target}</th><td>{escape(str(best.get('model', '-')))}</td>"
            f"<td>{escape(str(best.get('merge_mode', '-')))}</td>"
            f"<td>{escape(str(best.get('cv_mode', '-')))}</td>"
            f"<td>{escape(str(best.get('selection_metric', '-')))}</td>"
            f"<td>{escape(_format_html_value(best.get('selection_score')))}</td>"
            f"<td>{escape(_format_html_value(best.get('mean_hit_at_1')))}</td>"
            f"<td>{escape(_format_html_value(best.get('mean_hit_at_3')))}</td>"
            f"<td>{escape(_format_html_value(best.get('mean_threshold_optimized_f1')))}</td>"
            f"<td>{escape(_format_html_value(best.get('mean_threshold_optimized_recall')))}</td>"
            f"<td>{escape(_format_html_value(best.get('mean_threshold_optimized_precision')))}</td>"
            f"<td>{escape(_format_html_value(best.get('mean_objective_score')))}</td>"
            f"<td>{escape(_format_html_value(best.get('mean_auc')))}</td>"
            f"<td>{escape(_format_html_value(best.get('mean_pr_auc')))}</td></tr>"
            for target, best in summary_payload.get("best_by_target", {}).items()
        ) or "<tr><th>No data</th><td colspan='12'>-</td></tr>"

        leaderboard_rows = "".join(
            f"<tr><td>{escape(str(row.target))}</td><td>{escape(str(row.merge_mode))}</td>"
            f"<td>{escape(str(row.cv_mode))}</td><td>{escape(str(row.model))}</td>"
            f"<td>{escape(str(row.selection_metric))}</td>"
            f"<td>{escape(_format_html_value(row.selection_score))}</td>"
            f"<td>{escape(_format_html_value(row.mean_hit_at_1))}</td>"
            f"<td>{escape(_format_html_value(row.mean_hit_at_3))}</td>"
            f"<td>{escape(_format_html_value(row.mean_threshold_optimized_f1))}</td>"
            f"<td>{escape(_format_html_value(row.mean_threshold_optimized_recall))}</td>"
            f"<td>{escape(_format_html_value(row.mean_threshold_optimized_precision))}</td>"
            f"<td>{escape(_format_html_value(row.mean_objective_score))}</td>"
            f"<td>{escape(_format_html_value(row.mean_auc))}</td>"
            f"<td>{escape(_format_html_value(row.mean_pr_auc))}</td>"
            f"<td>{escape(_format_html_value(row.mean_zero_recall_penalty))}</td></tr>"
            for row in leaderboard_df.itertuples(index=False)
        ) or "<tr><td colspan='15'>No evaluations</td></tr>"

        selection_cards = []
        importance_cards = []
        for run in summary_payload.get("runs", []):
            selection = run.get("feature_selection") or {}
            stable = selection.get("stable_features") or selection.get("selected_features") or []
            if not stable:
                continue
            card = (
                f"<section><h2>{escape(str(run['target']))} / {escape(str(run['model']))} / "
                f"{escape(str(run['merge_mode']))} / {escape(str(run['cv_mode']))}</h2>"
                f"<p>Selected Features: {escape(', '.join(stable[:12]))}</p></section>"
            )
            selection_cards.append(card)

            top_importance_rows = selection.get("top_features_by_permutation") or selection.get("top_features") or []
            if top_importance_rows:
                importance_cards.append(
                    "<section><h2>"
                    + escape(str(run["target"]))
                    + " / "
                    + escape(str(run["model"]))
                    + " / "
                    + escape(str(run["merge_mode"]))
                    + " / "
                    + escape(str(run["cv_mode"]))
                    + "</h2><p>Feature Importance: "
                    + escape(", ".join(item["feature"] for item in top_importance_rows[:8]))
                    + "</p></section>"
                )

        body = f"""
        <section class="hero">
          <p class="eyebrow">Store Optimized Pipeline</p>
          <h1>{escape(store_id)} / {escape(grouping)}</h1>
          <p class="lede">Human-facing overview of best model configurations, comparison leaderboard, and automatically selected features.</p>
        </section>

        <section>
          <h2>Best Configuration</h2>
          <table>
            <tr><th>Target</th><th>Model</th><th>Merge Mode</th><th>CV</th><th>Metric</th><th>Score</th><th>Hit@1</th><th>Hit@3</th><th>Opt F1</th><th>Opt Recall</th><th>Opt Precision</th><th>Objective</th><th>AUC</th><th>PR-AUC</th></tr>
            {best_rows}
          </table>
        </section>

        <section>
          <h2>Leaderboard</h2>
          <table>
            <tr><th>Target</th><th>Merge Mode</th><th>CV</th><th>Model</th><th>Metric</th><th>Score</th><th>Hit@1</th><th>Hit@3</th><th>Opt F1</th><th>Opt Recall</th><th>Opt Precision</th><th>Objective</th><th>AUC</th><th>PR-AUC</th><th>Zero Recall Penalty</th></tr>
            {leaderboard_rows}
          </table>
        </section>

        <section>
          <h2>Feature Importance</h2>
          {''.join(importance_cards) or '<p>No feature-importance summaries available.</p>'}
        </section>

        {''.join(selection_cards)}
        """
        return render_html_page(title=f"{store_id} / {grouping}", body=body)


