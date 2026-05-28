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
        wk = df["weekday"].astype(str)
        buckets = {
            "mon_thu": wk.isin(["Monday", "Tuesday", "Thursday"]),
            "wednesday": wk.eq("Wednesday"),
            "fri_sat": wk.isin(["Friday", "Saturday"]),
            "sunday": wk.eq("Sunday"),
        }
        for name, mask in buckets.items():
            sub = df[mask].copy()
            if not sub.empty:
                out[name] = sub
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
        direction = df["anomaly_direction"].astype(str)
        normal = df[direction.eq("normal")].copy()
        anomaly = df[~direction.eq("normal")].copy()
        if not normal.empty:
            out["normal"] = normal
        if not anomaly.empty:
            out["anomaly"] = anomaly
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
