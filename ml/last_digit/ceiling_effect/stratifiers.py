from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class ConditionEvaluator(ABC):
    condition_name: str

    @abstractmethod
    def stratify(self, df: pd.DataFrame) -> dict[str, pd.DataFrame]:
        raise NotImplementedError


class WeekdayEvaluator(ConditionEvaluator):
    condition_name = "weekday"

    def stratify(self, df: pd.DataFrame) -> dict[str, pd.DataFrame]:
        out: dict[str, pd.DataFrame] = {}
        for w in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]:
            sub = df[df["weekday"] == w].copy()
            if not sub.empty:
                out[w] = sub
        return out


class PredSpanEvaluator(ConditionEvaluator):
    condition_name = "pred_span_quartile"

    def stratify(self, df: pd.DataFrame) -> dict[str, pd.DataFrame]:
        out: dict[str, pd.DataFrame] = {}
        for q in ["Q1", "Q2", "Q3", "Q4"]:
            sub = df[df["pred_span_quartile"] == q].copy()
            if not sub.empty:
                out[q] = sub
        return out


class AnomalyEvaluator(ConditionEvaluator):
    condition_name = "anomaly_direction"

    def stratify(self, df: pd.DataFrame) -> dict[str, pd.DataFrame]:
        out: dict[str, pd.DataFrame] = {}
        for k in ["normal", "high_anomaly", "low_anomaly"]:
            sub = df[df["anomaly_direction"] == k].copy()
            if not sub.empty:
                out[k] = sub
        return out


class FailureDayEvaluator(ConditionEvaluator):
    condition_name = "difficulty_failure"

    def stratify(self, df: pd.DataFrame) -> dict[str, pd.DataFrame]:
        out: dict[str, pd.DataFrame] = {}
        for k in ["hit_day", "miss_day"]:
            sub = df[df["difficulty_failure"] == k].copy()
            if not sub.empty:
                out[k] = sub
        return out


def default_evaluators() -> list[ConditionEvaluator]:
    return [
        WeekdayEvaluator(),
        PredSpanEvaluator(),
        AnomalyEvaluator(),
        FailureDayEvaluator(),
    ]

