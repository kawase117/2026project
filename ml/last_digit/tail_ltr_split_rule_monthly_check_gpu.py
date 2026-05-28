from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ml.last_digit.tail_ltr_split_rule_nextday_gpu import _build_reliability_daily, _build_reliability_monthly
from ml.last_digit import tail_ltr_split_rule_wf as split_rule_wf
from ml.last_digit.utils import configure_logging, parse_csv_strs

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Monthly GPU check for split-rule model comparison")
    p.add_argument("--output-prefix", default="db/experiments/tail_ltr_split_rule_monthly_gpu_check")
    p.add_argument("--db-path", default="", help="DB path (optional)")
    p.add_argument("--db-glob", default="*7.db", help="DB auto-detect glob pattern used when --db-path is empty")
    p.add_argument("--run-date", default="", help="YYYY-MM-DD (default: today)")
    p.add_argument("--seeds", default="42,77,123,202,303,404,505,606")
    p.add_argument("--test-days", type=int, default=14)
    p.add_argument("--warmup-days", type=int, default=56)
    p.add_argument("--min-train-days-wed", type=int, default=12)
    p.add_argument("--min-train-days-nonwed", type=int, default=42)
    p.add_argument("--windows-wed", default="full_2025")
    p.add_argument("--lambdas-wed", default="0.75,1.0,1.25")
    p.add_argument("--q-grid-wed", default="0.0,0.1,0.2,0.3,0.4")
    p.add_argument("--windows-nonwed", default="recent_60d,full_2025")
    p.add_argument("--lambdas-nonwed", default="0.75,1.0,1.25")
    p.add_argument("--q-grid-nonwed", default="0.0,0.1,0.2,0.3,0.4,0.5,0.6")
    p.add_argument("--a-weight", type=float, default=0.4)
    p.add_argument("--non-a-weight", type=float, default=1.3)
    p.add_argument("--a-gate-weight", type=float, default=1.0)
    p.add_argument("--non-a-gate-weight", type=float, default=1.15)
    p.add_argument("--gpu-backend", choices=["cuda", "gpu_hist"], default="cuda")
    p.add_argument("--reliability-history-path", default="db/experiments/tail_ltr_split4_reliability_history.csv")
    p.add_argument("--reliability-exclude-experts", default="2F_A")
    p.add_argument("--log-level", default="INFO", help="Logging level (DEBUG/INFO/WARNING/ERROR)")
    return p


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_raw_ranking(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    modes = payload.get("modes", {})
    for mode_name in ("global11", "floor2", "floor_atype4"):
        mode_payload = modes.get(mode_name)
        if not isinstance(mode_payload, dict):
            continue
        raw_overall = (((mode_payload.get("raw") or {}).get("overall")) or {})
        raw_nonwed = (((mode_payload.get("raw") or {}).get("non_wednesday")) or {})
        rows.append(
            {
                "mode": mode_name,
                "raw_overall_mean": float(raw_overall.get("mean", 0.0)),
                "raw_nonwed_mean": float(raw_nonwed.get("mean", 0.0)),
            }
        )
    rows.sort(key=lambda x: (x["raw_overall_mean"], x["raw_nonwed_mean"]), reverse=True)
    return rows


def main() -> int:
    args = build_parser().parse_args()
    configure_logging(args.log_level)
    run_date = args.run_date or datetime.now().strftime("%Y-%m-%d")
    out_prefix = Path(f"{args.output_prefix}_{run_date}")
    out_prefix.parent.mkdir(parents=True, exist_ok=True)

    wf_argv = [
        "--output-prefix",
        str(out_prefix),
        "--db-path",
        args.db_path,
        "--db-glob",
        args.db_glob,
        "--seeds",
        args.seeds,
        "--test-days",
        str(args.test_days),
        "--warmup-days",
        str(args.warmup_days),
        "--min-train-days-wed",
        str(args.min_train_days_wed),
        "--min-train-days-nonwed",
        str(args.min_train_days_nonwed),
        "--windows-wed",
        args.windows_wed,
        "--lambdas-wed",
        args.lambdas_wed,
        "--q-grid-wed",
        args.q_grid_wed,
        "--windows-nonwed",
        args.windows_nonwed,
        "--lambdas-nonwed",
        args.lambdas_nonwed,
        "--q-grid-nonwed",
        args.q_grid_nonwed,
        "--a-weight",
        str(args.a_weight),
        "--non-a-weight",
        str(args.non_a_weight),
        "--a-gate-weight",
        str(args.a_gate_weight),
        "--non-a-gate-weight",
        str(args.non_a_gate_weight),
        "--use-gpu",
        "--gpu-backend",
        args.gpu_backend,
    ]
    completed_code = split_rule_wf.main(wf_argv)
    if completed_code != 0:
        return int(completed_code)

    result_json = out_prefix.with_suffix(".json")
    payload = _load_json(result_json)
    raw_ranking = _build_raw_ranking(payload)
    reliability_history = Path(args.reliability_history_path)
    reliability_daily = pd.DataFrame()
    reliability_monthly = pd.DataFrame()
    if reliability_history.exists():
        history_df = pd.read_csv(reliability_history, encoding="utf-8-sig")
        exclude = set(parse_csv_strs(args.reliability_exclude_experts))
        reliability_daily = _build_reliability_daily(history_df, exclude)
        reliability_monthly = _build_reliability_monthly(reliability_daily)

    rel_daily_path = out_prefix.with_name(out_prefix.name + "_reliability_daily.csv")
    rel_monthly_path = out_prefix.with_name(out_prefix.name + "_reliability_monthly.csv")
    if not reliability_daily.empty:
        reliability_daily.to_csv(rel_daily_path, index=False, encoding="utf-8-sig")
    if not reliability_monthly.empty:
        reliability_monthly.to_csv(rel_monthly_path, index=False, encoding="utf-8-sig")

    reliability_overall = (
        reliability_daily.groupby("expert", sort=True)
        .agg(
            precision=("precision", "mean"),
            recall=("recall", "mean"),
            f1=("f1", "mean"),
            hit_at_2=("hit_at_2", "mean"),
            hit_at_3=("hit_at_3", "mean"),
            n_days=("date", "nunique"),
        )
        .reset_index()
        .to_dict(orient="records")
        if not reliability_daily.empty
        else []
    )
    compact = {
        "run_date": run_date,
        "device": "gpu",
        "gpu_backend": args.gpu_backend,
        "result_json": str(result_json),
        "recommended_mode_raw": (raw_ranking[0]["mode"] if raw_ranking else ""),
        "ranking_raw": raw_ranking,
        "reliability_history_path": str(reliability_history),
        "reliability_overall_by_expert": reliability_overall,
        "reliability_daily_csv": str(rel_daily_path) if not reliability_daily.empty else "",
        "reliability_monthly_csv": str(rel_monthly_path) if not reliability_monthly.empty else "",
    }
    summary_path = out_prefix.with_name(out_prefix.name + "_summary.json")
    summary_path.write_text(json.dumps(compact, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Saved: %s", summary_path)
    logger.info("%s", json.dumps(compact, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
