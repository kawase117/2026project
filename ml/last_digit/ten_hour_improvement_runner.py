from __future__ import annotations

import argparse
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class Experiment:
    name: str
    model: str
    output_prefix: str
    model_extra_json: str = ""
    timeout_sec: int = 7200


def _metrics_from_daily_csv(path: Path) -> dict[str, float]:
    df = pd.read_csv(path, encoding="utf-8-sig")
    ok = df[df["status"] == "ok"].copy()
    if ok.empty:
        return {
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
            "hit_at_2": 0.0,
            "hit_at_3": 0.0,
            "n_days": 0,
            "n_rows": 0,
        }
    return {
        "precision": float(ok["precision"].mean()),
        "recall": float(ok["recall"].mean()),
        "f1": float(ok["f1"].mean()),
        "hit_at_2": float(ok["hit_at_2"].mean()),
        "hit_at_3": float(ok["hit_at_3"].mean()),
        "n_days": int(pd.to_datetime(ok["date"]).nunique()),
        "n_rows": int(len(ok)),
    }


def _build_experiments(out_dir: Path) -> list[Experiment]:
    return [
        Experiment(
            name="xgb_ndcg_default",
            model="xgb_ranker_ndcg",
            output_prefix=str(out_dir / "xgb_ndcg_default"),
            timeout_sec=4500,
        ),
        Experiment(
            name="xgb_pairwise_default",
            model="xgb_ranker_pairwise",
            output_prefix=str(out_dir / "xgb_pairwise_default"),
            timeout_sec=4500,
        ),
        Experiment(
            name="xgb_pairwise_tuned_depth6",
            model="xgb_ranker_pairwise",
            output_prefix=str(out_dir / "xgb_pairwise_tuned_depth6"),
            model_extra_json=json.dumps({"max_depth": 6, "learning_rate": 0.05, "n_estimators": 600}),
            timeout_sec=5000,
        ),
        Experiment(
            name="catboost_default_cpu_or_auto",
            model="catboost_ranker_pairlogit",
            output_prefix=str(out_dir / "catboost_default"),
            timeout_sec=15000,
        ),
        Experiment(
            name="catboost_gpu_fast_250",
            model="catboost_ranker_pairlogit",
            output_prefix=str(out_dir / "catboost_gpu_fast_250"),
            model_extra_json=json.dumps(
                {"task_type": "GPU", "devices": "0", "iterations": 250, "depth": 6, "learning_rate": 0.06}
            ),
            timeout_sec=12000,
        ),
        Experiment(
            name="catboost_gpu_deep_400",
            model="catboost_ranker_pairlogit",
            output_prefix=str(out_dir / "catboost_gpu_deep_400"),
            model_extra_json=json.dumps(
                {"task_type": "GPU", "devices": "0", "iterations": 400, "depth": 8, "learning_rate": 0.04}
            ),
            timeout_sec=16000,
        ),
    ]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Autonomous long-run improvement runner (target: ~10 hours)")
    p.add_argument("--hours", type=float, default=10.0, help="Budget in hours")
    p.add_argument("--output-dir", default="db/experiments/model_comparison/longrun")
    p.add_argument("--python", default="python")
    return p


def main() -> int:
    args = build_parser().parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    experiments = _build_experiments(out_dir)
    started_at = time.time()
    deadline = started_at + float(args.hours) * 3600.0
    results: list[dict[str, Any]] = []

    for exp in experiments:
        now = time.time()
        if now >= deadline:
            results.append(
                {
                    "name": exp.name,
                    "model": exp.model,
                    "status": "skipped_budget_exhausted",
                }
            )
            continue

        cmd = [
            args.python,
            "-m",
            "ml.last_digit.tail_ltr_split_rule_nextday_gpu",
            "--model",
            exp.model,
            "--enable-test-period-report",
            "--output-prefix",
            exp.output_prefix,
        ]
        if exp.model_extra_json:
            cmd.extend(["--model-extra-json", exp.model_extra_json])

        time_left = int(deadline - now)
        timeout = min(exp.timeout_sec, max(300, time_left))
        t0 = time.time()
        try:
            completed = subprocess.run(cmd, check=False, timeout=timeout)
            elapsed = time.time() - t0
            row: dict[str, Any] = {
                "name": exp.name,
                "model": exp.model,
                "returncode": int(completed.returncode),
                "elapsed_sec": float(elapsed),
                "output_prefix": exp.output_prefix,
                "model_extra_json": exp.model_extra_json,
            }

            daily_csv = Path(f"{exp.output_prefix}_{exp.model}_testperiod_daily.csv")
            if daily_csv.exists():
                row["daily_csv"] = str(daily_csv)
                row["status"] = "ok" if completed.returncode == 0 else "completed_with_nonzero_rc"
                row.update(_metrics_from_daily_csv(daily_csv))
            else:
                row["status"] = "no_daily_csv"
            results.append(row)
        except subprocess.TimeoutExpired:
            elapsed = time.time() - t0
            results.append(
                {
                    "name": exp.name,
                    "model": exp.model,
                    "status": "timeout",
                    "elapsed_sec": float(elapsed),
                    "output_prefix": exp.output_prefix,
                    "model_extra_json": exp.model_extra_json,
                }
            )

    results_df = pd.DataFrame(results)
    summary_csv = out_dir / "ten_hour_summary.csv"
    summary_json = out_dir / "ten_hour_summary.json"
    if not results_df.empty:
        sort_cols = [c for c in ["hit_at_2", "f1", "status"] if c in results_df.columns]
        if "hit_at_2" in results_df.columns and "f1" in results_df.columns:
            results_df = results_df.sort_values(["hit_at_2", "f1"], ascending=False, na_position="last")
        results_df.to_csv(summary_csv, index=False, encoding="utf-8-sig")
    summary_json.write_text(
        json.dumps(
            {
                "hours_budget": float(args.hours),
                "started_at_unix": float(started_at),
                "finished_at_unix": float(time.time()),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Saved: {summary_csv}")
    print(f"Saved: {summary_json}")
    if not results_df.empty:
        cols = [c for c in ["name", "model", "status", "hit_at_2", "f1", "elapsed_sec"] if c in results_df.columns]
        print(results_df[cols].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
