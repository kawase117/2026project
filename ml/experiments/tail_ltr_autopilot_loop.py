from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Loop runner for tail_ltr_autopilot")
    p.add_argument("--hours", type=float, default=6.0, help="Total loop time budget in hours")
    p.add_argument("--max-rounds", type=int, default=0, help="Max rounds to run (0 = unlimited within hours)")
    p.add_argument("--sleep-seconds", type=int, default=15, help="Sleep between rounds")
    p.add_argument(
        "--max-no-improve-rounds",
        type=int,
        default=0,
        help="Stop after N consecutive rounds without best-lift improvement (0 = disabled)",
    )
    p.add_argument(
        "--min-improve-delta",
        type=float,
        default=1e-4,
        help="Minimum lift improvement to reset no-improve counter",
    )
    p.add_argument(
        "--enable-seed-shift",
        action="store_true",
        help="Shift seed values each round to keep generating new trials",
    )
    p.add_argument(
        "--seed-shift-step",
        type=int,
        default=1000,
        help="Value added to each seed per round when --enable-seed-shift is set",
    )
    p.add_argument("--python-exe", default=sys.executable, help="Python executable used to run autopilot")
    p.add_argument("--db-path", default="", help="Path to DB (default: auto-detect db/*7.db)")
    p.add_argument("--output-prefix", default="db/experiments/tail_ltr_autopilot_loop", help="Output prefix")
    p.add_argument("--targets", default="is_top_2,is_top_3", help="Comma-separated targets")
    p.add_argument("--lambdas-rank1", default="1.0,1.5,2.0,2.5", help="Lambda candidates for Rank1")
    p.add_argument("--lambdas-topk", default="0.5,1.0,1.5,2.0,2.5,3.0,4.0", help="Lambda candidates for TopK")
    p.add_argument("--seeds", default="42,77", help="Comma-separated seed values")
    p.add_argument("--split-filter", default="", help="Optional split filter")
    p.add_argument("--window-filter", default="", help="Optional window filter")
    p.add_argument("--max-trials", type=int, default=0, help="Max new trials for each autopilot run")
    p.add_argument("--verbose", action="store_true", help="Verbose mode for sub-runner")
    return p.parse_args()


def parse_seed_csv(raw: str) -> list[int]:
    values = [token.strip() for token in raw.split(",") if token.strip()]
    if not values:
        raise ValueError("No seeds were provided")
    return [int(token) for token in values]


def shift_seeds(base_seeds: list[int], round_index: int, *, step: int, enabled: bool) -> list[int]:
    if not enabled:
        return list(base_seeds)
    offset = round_index * step
    return [seed + offset for seed in base_seeds]


def read_summary(summary_path: Path) -> dict[str, Any] | None:
    if not summary_path.exists():
        return None
    try:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def extract_best_lift(summary: dict[str, Any] | None) -> float | None:
    if not summary:
        return None
    top = summary.get("top10_by_lift", [])
    if not isinstance(top, list):
        return None
    lifts: list[float] = []
    for row in top:
        if not isinstance(row, dict):
            continue
        value = row.get("lift_vs_random")
        if isinstance(value, (int, float)):
            lifts.append(float(value))
    return max(lifts) if lifts else None


def extract_executed_trials(summary: dict[str, Any] | None) -> int | None:
    if not summary:
        return None
    counts = summary.get("trial_counts", {})
    if not isinstance(counts, dict):
        return None
    value = counts.get("executed_this_run")
    if isinstance(value, int):
        return value
    return None


def append_loop_log(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def main() -> int:
    args = parse_args()
    start_at = datetime.now()
    deadline = start_at + timedelta(hours=max(args.hours, 0.0))
    output_prefix = Path(args.output_prefix)
    summary_path = Path(f"{output_prefix}.summary.json")
    loop_log_path = Path(f"{output_prefix}.loop.jsonl")

    base_seeds = parse_seed_csv(args.seeds)
    best_lift_seen: float | None = None
    no_improve_rounds = 0
    round_index = 0

    while datetime.now() < deadline:
        if args.max_rounds > 0 and round_index >= args.max_rounds:
            break
        round_index += 1
        round_started_at = datetime.now()
        round_seeds = shift_seeds(
            base_seeds,
            round_index - 1,
            step=args.seed_shift_step,
            enabled=args.enable_seed_shift,
        )
        seed_csv = ",".join(str(seed) for seed in round_seeds)

        cmd = [
            args.python_exe,
            "-m",
            "ml.experiments.tail_ltr_autopilot",
            "--output-prefix",
            str(args.output_prefix),
            "--targets",
            args.targets,
            "--lambdas-rank1",
            args.lambdas_rank1,
            "--lambdas-topk",
            args.lambdas_topk,
            "--seeds",
            seed_csv,
            "--max-trials",
            str(args.max_trials),
        ]
        if args.db_path:
            cmd.extend(["--db-path", args.db_path])
        if args.split_filter:
            cmd.extend(["--split-filter", args.split_filter])
        if args.window_filter:
            cmd.extend(["--window-filter", args.window_filter])
        if args.verbose:
            cmd.append("--verbose")

        print(
            f"[loop] round={round_index} start={round_started_at.isoformat(timespec='seconds')} "
            f"seeds={seed_csv}"
        )
        completed = subprocess.run(cmd, check=False)
        round_finished_at = datetime.now()
        summary = read_summary(summary_path)
        best_lift = extract_best_lift(summary)
        executed_trials = extract_executed_trials(summary)

        improved = False
        if best_lift is not None:
            if best_lift_seen is None or best_lift > (best_lift_seen + args.min_improve_delta):
                best_lift_seen = best_lift
                no_improve_rounds = 0
                improved = True
            else:
                no_improve_rounds += 1

        loop_row = {
            "round": round_index,
            "started_at": round_started_at.isoformat(timespec="seconds"),
            "finished_at": round_finished_at.isoformat(timespec="seconds"),
            "duration_sec": int((round_finished_at - round_started_at).total_seconds()),
            "command": cmd,
            "return_code": int(completed.returncode),
            "executed_trials": executed_trials,
            "best_lift": best_lift,
            "best_lift_seen": best_lift_seen,
            "improved": improved,
            "no_improve_rounds": no_improve_rounds,
        }
        append_loop_log(loop_log_path, loop_row)

        if completed.returncode != 0:
            print(f"[loop] stopped: autopilot failed at round={round_index} rc={completed.returncode}")
            return completed.returncode

        if executed_trials == 0 and not args.enable_seed_shift:
            print("[loop] stopped: no pending trials (executed_this_run=0)")
            break

        if args.max_no_improve_rounds > 0 and no_improve_rounds >= args.max_no_improve_rounds:
            print(
                "[loop] stopped: no improvement streak reached "
                f"({no_improve_rounds}/{args.max_no_improve_rounds})"
            )
            break

        if datetime.now() >= deadline:
            break
        if args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)

    ended_at = datetime.now()
    print(
        f"[loop] finished start={start_at.isoformat(timespec='seconds')} "
        f"end={ended_at.isoformat(timespec='seconds')} rounds={round_index} "
        f"best_lift_seen={best_lift_seen}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
