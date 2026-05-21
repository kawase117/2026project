from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ml.experiments.tail_ltr_split_rule_wf import add_simple_features, aggregate_mode, build_base_rows, resolve_db_path


@dataclass(frozen=True)
class HealthCheckConfig:
    expected_groups: list[str]
    allowed_missing_groups: list[str]
    min_group_days: int
    a_weight: float
    non_a_weight: float


def parse_csv_strs(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


def run_health_check(db_path: Path, cfg: HealthCheckConfig) -> dict[str, Any]:
    raw = build_base_rows(db_path=db_path, a_weight=float(cfg.a_weight), non_a_weight=float(cfg.non_a_weight))
    data = add_simple_features(aggregate_mode(raw, mode="floor_atype4")).sort_values("date").reset_index(drop=True)

    dates = sorted(pd.to_datetime(data["date"].unique()))
    day_count = len(dates)
    max_gap_days = 0
    if len(dates) >= 2:
        max_gap_days = int(max((dates[i] - dates[i - 1]).days for i in range(1, len(dates))))

    group_days = data.groupby("group_key")["date"].nunique().sort_index()
    group_rows = data.groupby("group_key").size().sort_index()
    available_groups = sorted(group_days.index.astype(str).tolist())

    expected = set(cfg.expected_groups)
    allowed_missing = set(cfg.allowed_missing_groups)
    missing_expected = sorted(list(expected - set(available_groups)))
    disallowed_missing = sorted(list((expected - allowed_missing) - set(available_groups)))
    sparse_groups = sorted([g for g, d in group_days.items() if int(d) < int(cfg.min_group_days)])

    null_mc = int(pd.to_numeric(data["machine_count"], errors="coerce").isna().sum())
    zero_or_neg_mc = int((pd.to_numeric(data["machine_count"], errors="coerce").fillna(0.0) <= 0).sum())

    alerts: list[dict[str, Any]] = []
    if disallowed_missing:
        alerts.append(
            {
                "level": "error",
                "code": "missing_expected_groups",
                "message": f"Missing expected groups (disallowed): {disallowed_missing}",
            }
        )
    if missing_expected and not disallowed_missing:
        alerts.append(
            {
                "level": "warn",
                "code": "missing_expected_groups_allowed",
                "message": f"Missing expected groups (allowed): {missing_expected}",
            }
        )
    if sparse_groups:
        alerts.append(
            {
                "level": "warn",
                "code": "sparse_groups",
                "message": f"Sparse groups below min_group_days={cfg.min_group_days}: {sparse_groups}",
            }
        )
    if max_gap_days > 3:
        alerts.append(
            {
                "level": "warn",
                "code": "date_gap_large",
                "message": f"Maximum date gap is large: {max_gap_days} days",
            }
        )
    if null_mc > 0 or zero_or_neg_mc > 0:
        alerts.append(
            {
                "level": "warn",
                "code": "machine_count_anomaly",
                "message": f"machine_count anomalies: null={null_mc}, <=0={zero_or_neg_mc}",
            }
        )

    return {
        "db_path": str(db_path),
        "range": {
            "start": str(dates[0].date()) if dates else "",
            "end": str(dates[-1].date()) if dates else "",
            "n_days": int(day_count),
            "max_gap_days": int(max_gap_days),
        },
        "available_groups": available_groups,
        "group_days": {str(k): int(v) for k, v in group_days.to_dict().items()},
        "group_rows": {str(k): int(v) for k, v in group_rows.to_dict().items()},
        "expected_groups": cfg.expected_groups,
        "allowed_missing_groups": cfg.allowed_missing_groups,
        "missing_expected_groups": missing_expected,
        "sparse_groups": sparse_groups,
        "anomalies": {
            "machine_count_null_rows": int(null_mc),
            "machine_count_non_positive_rows": int(zero_or_neg_mc),
        },
        "alerts": alerts,
        "ok": all(a["level"] != "error" for a in alerts),
    }


def run_module(module: str, args: list[str]) -> dict[str, Any]:
    cmd = [sys.executable, "-m", module, *args]
    started_at = datetime.now().isoformat(timespec="seconds")
    completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    finished_at = datetime.now().isoformat(timespec="seconds")
    return {
        "module": module,
        "args": args,
        "return_code": int(completed.returncode),
        "started_at": started_at,
        "finished_at": finished_at,
        "stdout_tail": "\n".join(completed.stdout.splitlines()[-30:]),
        "stderr_tail": "\n".join(completed.stderr.splitlines()[-30:]),
    }


def cmd_health_check(args: argparse.Namespace) -> int:
    db_path = Path(args.db_path).resolve() if args.db_path else Path(resolve_db_path()).resolve()
    cfg = HealthCheckConfig(
        expected_groups=parse_csv_strs(args.expected_groups),
        allowed_missing_groups=parse_csv_strs(args.allowed_missing_groups),
        min_group_days=int(args.min_group_days),
        a_weight=float(args.a_weight),
        non_a_weight=float(args.non_a_weight),
    )
    payload = run_health_check(db_path, cfg)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Saved:", out)
    print(json.dumps({"ok": payload["ok"], "alerts": payload["alerts"]}, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 2


def _safe_load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def cmd_run_maintenance(args: argparse.Namespace) -> int:
    run_at = datetime.now()
    run_tag = run_at.strftime("%Y-%m-%d")
    out_prefix = Path(args.output_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)

    db_path = Path(args.db_path).resolve() if args.db_path else Path(resolve_db_path()).resolve()
    health_json = out_prefix.with_name(f"{out_prefix.name}_{run_tag}_health.json")
    nextday_prefix = out_prefix.with_name(f"{out_prefix.name}_{run_tag}_nextday")
    inverse_prefix = out_prefix.with_name(f"{out_prefix.name}_{run_tag}_inverse")
    summary_json = out_prefix.with_name(f"{out_prefix.name}_{run_tag}_summary.json")

    health_cfg = HealthCheckConfig(
        expected_groups=parse_csv_strs(args.expected_groups),
        allowed_missing_groups=parse_csv_strs(args.allowed_missing_groups),
        min_group_days=int(args.min_group_days),
        a_weight=float(args.a_weight),
        non_a_weight=float(args.non_a_weight),
    )
    health_payload = run_health_check(db_path, health_cfg)
    health_json.write_text(json.dumps(health_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    run_nextday = bool(args.run_nextday)
    run_inverse = bool(args.run_inverse)
    # If no explicit flags are provided, run both by default for one-shot maintenance.
    if not run_nextday and not run_inverse:
        run_nextday = True
        run_inverse = True

    jobs: list[dict[str, Any]] = []
    if run_nextday:
        jobs.append(
            run_module(
                "ml.experiments.tail_ltr_split_rule_nextday",
                [
                    "--output-prefix",
                    str(nextday_prefix),
                    "--seed",
                    str(args.seed),
                    "--a-weight",
                    str(args.a_weight),
                    "--non-a-weight",
                    str(args.non_a_weight),
                ],
            )
        )
    if run_inverse:
        jobs.append(
            run_module(
                "ml.experiments.tail_ltr_split_rule_inverse_phase_report",
                [
                    "--output-prefix",
                    str(inverse_prefix),
                    "--seeds",
                    args.inverse_seeds,
                    "--test-days",
                    str(args.inverse_test_days),
                    "--warmup-days",
                    str(args.inverse_warmup_days),
                    "--a-weight",
                    str(args.a_weight),
                    "--non-a-weight",
                    str(args.non_a_weight),
                ],
            )
        )

    nextday_json = _safe_load_json(nextday_prefix.with_suffix(".json")) if run_nextday else None
    inverse_json = _safe_load_json(inverse_prefix.with_suffix(".json")) if run_inverse else None
    job_errors = [j for j in jobs if int(j["return_code"]) != 0]

    summary = {
        "run_at": run_at.isoformat(timespec="seconds"),
        "db_path": str(db_path),
        "health_check_path": str(health_json),
        "health_ok": bool(health_payload.get("ok", False)),
        "health_alerts": health_payload.get("alerts", []),
        "jobs": jobs,
        "job_error_count": len(job_errors),
        "outputs": {
            "nextday_json": str(nextday_prefix.with_suffix(".json")) if run_nextday else "",
            "nextday_csv": str(nextday_prefix.with_suffix(".csv")) if run_nextday else "",
            "inverse_json": str(inverse_prefix.with_suffix(".json")) if run_inverse else "",
            "inverse_days_csv": str(inverse_prefix.with_name(inverse_prefix.name + "_days.csv")) if run_inverse else "",
            "inverse_cross_aggregated_csv": str(inverse_prefix.with_name(inverse_prefix.name + "_cross_aggregated.csv")) if run_inverse else "",
            "inverse_cross_split4_csv": str(inverse_prefix.with_name(inverse_prefix.name + "_cross_split4.csv")) if run_inverse else "",
        },
        "quick_metrics": {
            "target_date": (nextday_json or {}).get("target_date", ""),
            "target_weekday": (nextday_json or {}).get("target_weekday", ""),
            "combined_top3": (nextday_json or {}).get("combined_priority_ranking", [])[:3],
            "inverse_rate": ((inverse_json or {}).get("overall") or {}).get("inverse_rate"),
            "cross_any_rate_aggregated": ((inverse_json or {}).get("overall_cross_match_aggregated") or {}).get("cross_any_rate"),
            "cross_both_rate_aggregated": ((inverse_json or {}).get("overall_cross_match_aggregated") or {}).get("cross_both_rate"),
        },
        "ok": bool(health_payload.get("ok", False)) and len(job_errors) == 0,
    }
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Saved:", health_json)
    print("Saved:", summary_json)
    print(
        json.dumps(
            {
                "ok": summary["ok"],
                "job_error_count": summary["job_error_count"],
                "health_alerts": summary["health_alerts"],
                "quick_metrics": summary["quick_metrics"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if summary["ok"] else 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Operational/maintenance suite for split-rule tail LTR")
    sub = p.add_subparsers(dest="command", required=True)

    p1 = sub.add_parser("health-check", help="Run split-rule data health checks only")
    p1.add_argument("--db-path", default="")
    p1.add_argument("--output", default="db/experiments/tail_ltr_split_rule_health_check.json")
    p1.add_argument("--expected-groups", default="2F_N,3F_N,3F_A,2F_A")
    p1.add_argument("--allowed-missing-groups", default="2F_A")
    p1.add_argument("--min-group-days", type=int, default=60)
    p1.add_argument("--a-weight", type=float, default=0.4)
    p1.add_argument("--non-a-weight", type=float, default=1.3)

    p2 = sub.add_parser("run-maintenance", help="Run health-check + nextday + inverse report")
    p2.add_argument("--db-path", default="")
    p2.add_argument("--output-prefix", default="db/experiments/tail_ltr_split_rule_maintenance")
    p2.add_argument("--expected-groups", default="2F_N,3F_N,3F_A,2F_A")
    p2.add_argument("--allowed-missing-groups", default="2F_A")
    p2.add_argument("--min-group-days", type=int, default=60)
    p2.add_argument("--a-weight", type=float, default=0.4)
    p2.add_argument("--non-a-weight", type=float, default=1.3)
    p2.add_argument("--seed", type=int, default=42)
    p2.add_argument("--run-nextday", action="store_true")
    p2.add_argument("--run-inverse", action="store_true")
    p2.add_argument("--inverse-seeds", default="42")
    p2.add_argument("--inverse-test-days", type=int, default=14)
    p2.add_argument("--inverse-warmup-days", type=int, default=56)

    return p


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "health-check":
        return cmd_health_check(args)
    if args.command == "run-maintenance":
        return cmd_run_maintenance(args)
    raise ValueError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
