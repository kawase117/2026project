from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace


@dataclass(frozen=True)
class TrialSpec:
    split_name: str
    window_name: str
    target: str
    decay_lambda: float
    seed: int


def _build_fixed_split_configs(_dataset):
    return {}


def _build_window_sweep_configs(*, valid_start: str):
    return {}


improved = SimpleNamespace(
    build_fixed_split_configs=_build_fixed_split_configs,
    build_window_sweep_configs=_build_window_sweep_configs,
)


def build_trial_specs(
    *,
    split_windows: dict,
    targets: list[str],
    lambdas_rank1: list[float],
    lambdas_topk: list[float],
    seeds: list[int],
    split_filter: set[str] | None = None,
    window_filter: set[str] | None = None,
) -> list[TrialSpec]:
    specs: list[TrialSpec] = []
    split_filter = set(split_filter or [])
    window_filter = set(window_filter or [])
    for split_name, payload in split_windows.items():
        if split_filter and split_name not in split_filter:
            continue
        windows = payload.get("windows", {})
        for window_name in windows:
            if window_filter and window_name not in window_filter:
                continue
            for target in targets:
                lambdas = lambdas_rank1 if target == "is_rank_1" else lambdas_topk
                for decay_lambda in lambdas:
                    for seed in seeds:
                        specs.append(
                            TrialSpec(
                                split_name=split_name,
                                window_name=window_name,
                                target=target,
                                decay_lambda=float(decay_lambda),
                                seed=int(seed),
                            )
                        )
    return specs


def load_done_keys(path: str | Path) -> set[str]:
    path = Path(path)
    if not path.exists():
        return set()
    done: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        trial_key = payload.get("trial_key")
        if isinstance(trial_key, str) and trial_key:
            done.add(trial_key)
    return done


def build_split_windows(dataset) -> dict:
    split_windows: dict = {}
    fixed_splits = improved.build_fixed_split_configs(dataset)
    for split_name, split in fixed_splits.items():
        split_windows[split_name] = {
            "split": split,
            "windows": improved.build_window_sweep_configs(valid_start=split.get("valid_start")),
        }
    return split_windows
