from __future__ import annotations

import argparse
import csv
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ml.experiments import tail_time_adaptive_ltr_poc_improved as improved

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrialSpec:
    split_name: str
    target: str
    window_name: str
    train_start: str
    train_end: str
    valid_start: str
    valid_end: str
    decay_lambda: float
    random_state: int

    @property
    def trial_key(self) -> str:
        return (
            f"{self.split_name}|{self.target}|{self.window_name}|"
            f"{self.train_start}|{self.train_end}|{self.valid_start}|{self.valid_end}|"
            f"lam={self.decay_lambda:g}|seed={self.random_state}"
        )


def parse_csv_floats(value: str) -> list[float]:
    values = [v.strip() for v in value.split(",") if v.strip()]
    if not values:
        raise ValueError("No numeric values were provided")
    return [float(v) for v in values]


def parse_csv_ints(value: str) -> list[int]:
    values = [v.strip() for v in value.split(",") if v.strip()]
    if not values:
        raise ValueError("No integer values were provided")
    return [int(v) for v in values]


def parse_csv_strs(value: str) -> list[str]:
    values = [v.strip() for v in value.split(",") if v.strip()]
    if not values:
        raise ValueError("No string values were provided")
    return values


def resolve_default_db_path() -> Path:
    candidates = sorted(Path("db").glob("*7.db"))
    if not candidates:
        raise FileNotFoundError("No '*7.db' file found under db/")
    return candidates[0].resolve()


def load_dataset(db_path: Path) -> tuple[pd.DataFrame, list[str]]:
    builder = improved.StoreOptimizedFeatureBuilder()
    dataset = builder.build_store_dataset(db_path=db_path, grouping="last_digit")
    dataset = improved.add_top2_target(dataset)
    dataset = improved.add_regime_and_cluster_features(dataset)
    features = improved.get_numeric_features(dataset)
    return dataset, features


def build_split_windows(dataset: pd.DataFrame) -> dict[str, dict[str, Any]]:
    fixed_splits = improved.build_fixed_split_configs(dataset)
    split_windows: dict[str, dict[str, Any]] = {}
    for split_name, split in fixed_splits.items():
        split_windows[split_name] = {
            "split": split,
            "windows": improved.build_window_sweep_configs(valid_start=split["valid_start"]),
        }
    return split_windows


def build_trial_specs(
    *,
    split_windows: dict[str, dict[str, Any]],
    targets: list[str],
    lambdas_rank1: list[float],
    lambdas_topk: list[float],
    seeds: list[int],
    split_filter: set[str] | None = None,
    window_filter: set[str] | None = None,
) -> list[TrialSpec]:
    trials: list[TrialSpec] = []
    for split_name, payload in split_windows.items():
        if split_filter and split_name not in split_filter:
            continue
        split = payload["split"]
        windows: dict[str, dict[str, str]] = payload["windows"]
        for target in targets:
            lambda_values = lambdas_rank1 if target == "is_rank_1" else lambdas_topk
            for window_name, window in windows.items():
                if window_filter and window_name not in window_filter:
                    continue
                for lam in lambda_values:
                    for seed in seeds:
                        trials.append(
                            TrialSpec(
                                split_name=split_name,
                                target=target,
                                window_name=window_name,
                                train_start=window["train_start"],
                                train_end=window["train_end"],
                                valid_start=split["valid_start"],
                                valid_end=split["valid_end"],
                                decay_lambda=float(lam),
                                random_state=seed,
                            )
                        )
    return trials


def load_done_keys(jsonl_path: Path) -> set[str]:
    if not jsonl_path.exists():
        return set()
    done: set[str] = set()
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = payload.get("trial_key")
            if isinstance(key, str):
                done.add(key)
    return done


def run_trial(
    *,
    dataset: pd.DataFrame,
    features: list[str],
    trial: TrialSpec,
    calibration_config: improved.CalibrationConfig,
    two_stage_config: improved.TwoStageConfig | None,
) -> dict[str, Any]:
    evaluation = improved.evaluate_fixed_split(
        dataset,
        target=trial.target,
        features=features,
        random_state=trial.random_state,
        decay_lambda=trial.decay_lambda,
        calibration_config=calibration_config,
        two_stage_config=two_stage_config,
        train_start=trial.train_start,
        train_end=trial.train_end,
        valid_start=trial.valid_start,
        valid_end=trial.valid_end,
    )
    selection_metric = improved.selection_metric_for_target(trial.target)
    score = float(evaluation["metrics"].get(selection_metric, 0.0))
    random_score = float(evaluation.get("random_baseline", {}).get(selection_metric, 0.0))
    return {
        "trial_key": trial.trial_key,
        "trial": asdict(trial),
        "selection_metric": selection_metric,
        "score": score,
        "random_score": random_score,
        "lift_vs_random": score - random_score,
        "evaluation": evaluation,
    }


def write_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def build_leaderboard_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        trial = record["trial"]
        metrics = record["evaluation"]["metrics"]
        rows.append(
            {
                "split_name": trial["split_name"],
                "target": trial["target"],
                "window_name": trial["window_name"],
                "train_start": trial["train_start"],
                "train_end": trial["train_end"],
                "valid_start": trial["valid_start"],
                "valid_end": trial["valid_end"],
                "decay_lambda": trial["decay_lambda"],
                "random_state": trial["random_state"],
                "selection_metric": record["selection_metric"],
                "score": record["score"],
                "random_score": record["random_score"],
                "lift_vs_random": record["lift_vs_random"],
                "hit_at_1": float(metrics["hit_at_1"]),
                "hit_at_2": float(metrics["hit_at_2"]),
                "hit_at_3": float(metrics["hit_at_3"]),
                "ndcg_at_2": float(metrics["ndcg_at_2"]),
                "ndcg_at_3": float(metrics["ndcg_at_3"]),
                "spearman": float(metrics["spearman"]),
            }
        )
    rows.sort(key=lambda r: (r["target"], r["split_name"], -r["lift_vs_random"], -r["score"]))
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        with path.open("w", encoding="utf-8", newline="") as f:
            f.write("")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Auto-pilot runner for tail LTR fixed-split trials")
    p.add_argument("--db-path", default="", help="Path to DB (default: auto-detect db/*7.db)")
    p.add_argument(
        "--output-prefix",
        default="db/experiments/tail_ltr_autopilot",
        help="Prefix for output files (.jsonl/.json/.csv)",
    )
    p.add_argument("--targets", default="is_top_2,is_top_3", help="Comma-separated targets")
    p.add_argument("--lambdas-rank1", default="1.0,1.5,2.0,2.5", help="Lambda candidates for Rank1")
    p.add_argument("--lambdas-topk", default="0.5,1.0,1.5,2.0,2.5,3.0,4.0", help="Lambda candidates for TopK")
    p.add_argument("--seeds", default="42,77", help="Comma-separated random seeds")
    p.add_argument(
        "--split-filter",
        default="",
        help="Optional split filter, e.g. regime_fixed_split,regime_3_fixed_split",
    )
    p.add_argument(
        "--window-filter",
        default="",
        help="Optional window filter, e.g. recent_60d,regime2_only,full_2025",
    )
    p.add_argument("--enable-two-stage-top3", action="store_true", help="Enable two-stage rerank for is_top_3")
    p.add_argument("--two-stage-candidate-factor", type=int, default=2, help="Top3 stage-1 candidate size factor")
    p.add_argument("--max-trials", type=int, default=0, help="Max new trials for this run (0=all)")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    db_path = Path(args.db_path).resolve() if args.db_path else resolve_default_db_path()
    output_prefix = Path(args.output_prefix)
    jsonl_path = Path(f"{output_prefix}.jsonl")
    summary_json_path = Path(f"{output_prefix}.summary.json")
    leaderboard_csv_path = Path(f"{output_prefix}.leaderboard.csv")

    targets = parse_csv_strs(args.targets)
    seeds = parse_csv_ints(args.seeds)
    lambdas_rank1 = parse_csv_floats(args.lambdas_rank1)
    lambdas_topk = parse_csv_floats(args.lambdas_topk)
    split_filter = set(parse_csv_strs(args.split_filter)) if args.split_filter else None
    window_filter = set(parse_csv_strs(args.window_filter)) if args.window_filter else None

    dataset, features = load_dataset(db_path)
    split_windows = build_split_windows(dataset)
    trials = build_trial_specs(
        split_windows=split_windows,
        targets=targets,
        lambdas_rank1=lambdas_rank1,
        lambdas_topk=lambdas_topk,
        seeds=seeds,
        split_filter=split_filter,
        window_filter=window_filter,
    )
    done_keys = load_done_keys(jsonl_path)
    pending = [t for t in trials if t.trial_key not in done_keys]
    if args.max_trials > 0:
        pending = pending[: args.max_trials]

    logger.info("DB: %s", db_path)
    logger.info("Dataset rows=%s features=%s", len(dataset), len(features))
    logger.info("Trials total=%s done=%s pending_this_run=%s", len(trials), len(done_keys), len(pending))

    calibration_config = improved.CalibrationConfig()
    two_stage_config = improved.TwoStageConfig(
        enable_top3=bool(args.enable_two_stage_top3),
        candidate_factor=max(1, int(args.two_stage_candidate_factor)),
    )
    new_records: list[dict[str, Any]] = []
    total_pending = len(pending)
    for idx, trial in enumerate(pending, start=1):
        logger.info(
            "[%s/%s] split=%s target=%s window=%s lambda=%s seed=%s",
            idx,
            total_pending,
            trial.split_name,
            trial.target,
            trial.window_name,
            trial.decay_lambda,
            trial.random_state,
        )
        record = run_trial(
            dataset=dataset,
            features=features,
            trial=trial,
            calibration_config=calibration_config,
            two_stage_config=two_stage_config,
        )
        record["executed_at"] = datetime.now().isoformat(timespec="seconds")
        write_jsonl(jsonl_path, record)
        new_records.append(record)

    all_records: list[dict[str, Any]] = []
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                all_records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    rows = build_leaderboard_rows(all_records)
    write_csv(leaderboard_csv_path, rows)

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "db_path": str(db_path),
        "dataset_rows": int(len(dataset)),
        "feature_count": int(len(features)),
        "trial_config": {
            "targets": targets,
            "seeds": seeds,
            "lambdas_rank1": lambdas_rank1,
            "lambdas_topk": lambdas_topk,
            "split_filter": sorted(split_filter) if split_filter else [],
            "window_filter": sorted(window_filter) if window_filter else [],
            "max_trials": int(args.max_trials),
            "enable_two_stage_top3": bool(two_stage_config.enable_top3),
            "two_stage_candidate_factor": int(two_stage_config.candidate_factor),
        },
        "trial_counts": {
            "total_defined": len(trials),
            "already_done_before_run": len(done_keys),
            "executed_this_run": len(new_records),
            "accumulated_records": len(all_records),
        },
        "leaderboard_csv": str(leaderboard_csv_path),
        "jsonl": str(jsonl_path),
        "top10_by_lift": rows[:10],
    }
    summary_json_path.parent.mkdir(parents=True, exist_ok=True)
    summary_json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info("Saved JSONL: %s", jsonl_path)
    logger.info("Saved leaderboard: %s", leaderboard_csv_path)
    logger.info("Saved summary: %s", summary_json_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
