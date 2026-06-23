from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_metric(fn, *args: Any, default: float = 0.0, **kwargs: Any) -> float:
    try:
        return float(fn(*args, **kwargs))
    except Exception:
        return float(default)


@dataclass(frozen=True)
class ExperimentResult:
    experiment_id: str
    timestamp: str
    phase: int
    hypothesis: str
    groupby_strategy: str
    task: str
    ml_model: str
    interpretation: str
    next_step: str
    metrics: dict[str, float]


class ExperimentRunner:
    """Small compatibility experiment logger used by legacy tests and scripts."""

    def __init__(self, results_dir: str | Path | None = None):
        base_dir = (
            Path(results_dir)
            if results_dir is not None
            else Path("scratch/experiment_runner_results")
        )
        self.results_dir = base_dir.resolve()
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def run_experiment(
        self,
        *,
        experiment_id: str,
        phase: int,
        hypothesis: str,
        groupby_strategy: str,
        task: str,
        ml_model: str,
        X_train,
        y_train,
        X_test,
        y_test,
        model,
        interpretation: str,
        next_step: str,
    ) -> str:
        model.fit(X_train, y_train)
        proba = np.asarray(model.predict_proba(X_test))[:, 1]
        pred = (proba >= 0.5).astype(int)
        y_true = np.asarray(y_test)

        auc = _safe_metric(roc_auc_score, y_true, proba, default=0.5)
        pr_auc = _safe_metric(average_precision_score, y_true, proba, default=0.0)
        brier = _safe_metric(brier_score_loss, y_true, proba, default=1.0)
        accuracy = _safe_metric(accuracy_score, y_true, pred)
        precision = _safe_metric(precision_score, y_true, pred, zero_division=0)
        recall = _safe_metric(recall_score, y_true, pred, zero_division=0)
        f1 = _safe_metric(f1_score, y_true, pred, zero_division=0)
        zero_recall_penalty = 0.0 if recall > 0 else 1.0
        objective_score = float(max(0.0, min(2.0, auc + pr_auc - zero_recall_penalty)))

        metrics = {
            "auc": auc,
            "pr_auc": pr_auc,
            "brier_score": brier,
            "accuracy": accuracy,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "zero_recall_penalty": zero_recall_penalty,
            "objective_score": objective_score,
        }

        result = ExperimentResult(
            experiment_id=experiment_id,
            timestamp=_utc_timestamp(),
            phase=int(phase),
            hypothesis=hypothesis,
            groupby_strategy=groupby_strategy,
            task=task,
            ml_model=ml_model,
            interpretation=interpretation,
            next_step=next_step,
            metrics=metrics,
        )
        payload = asdict(result)

        legacy_path = self.results_dir / f"{experiment_id}.json"
        legacy_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        run_dir = self.results_dir / experiment_id
        run_dir.mkdir(parents=True, exist_ok=True)
        run_json_path = run_dir / "run.json"
        bundle = {
            **payload,
            "result": {
                "primary_metric": "auc",
                "primary_value": auc,
            },
        }
        run_json_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        summary_html = run_dir / "summary.html"
        summary_html.write_text(
            "\n".join(
                [
                    "<html><body>",
                    f"<h1>{experiment_id}</h1>",
                    f"<p>{hypothesis}</p>",
                    f"<p>Primary metric: auc={auc:.4f}</p>",
                    "</body></html>",
                ]
            ),
            encoding="utf-8",
        )

        index_path = self.results_dir / "index.jsonl"
        with index_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "experiment_id": experiment_id,
                        "timestamp": payload["timestamp"],
                        "path": f"{experiment_id}/run.json",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

        return experiment_id

    def load_all_experiments(self) -> list[dict[str, Any]]:
        experiments: list[dict[str, Any]] = []
        for path in sorted(self.results_dir.glob("*.json")):
            try:
                experiments.append(json.loads(path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
        return experiments
