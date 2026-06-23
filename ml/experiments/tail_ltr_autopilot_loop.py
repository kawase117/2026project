from __future__ import annotations


def shift_seeds(seeds: list[int], round_idx: int, *, step: int = 1000, enabled: bool = True) -> list[int]:
    if not enabled:
        return list(seeds)
    return [int(seed) + int(round_idx) * int(step) for seed in seeds]


def extract_best_lift(summary: dict) -> float:
    rows = summary.get("top10_by_lift", [])
    lifts = [float(row.get("lift_vs_random", 0.0)) for row in rows if isinstance(row, dict)]
    return max(lifts) if lifts else 0.0


def extract_executed_trials(summary: dict) -> int:
    counts = summary.get("trial_counts", {})
    return int(counts.get("executed_this_run", 0))
