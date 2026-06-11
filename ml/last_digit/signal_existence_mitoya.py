from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import pandas as pd

from ml.last_digit.mitoya_segmentation import EXPERTS_MITOYA, aggregate_mode_mitoya, build_base_rows_mitoya
from ml.last_digit.utils import resolve_db_path


def _load_base_module():
    module_name = "ml.last_digit._signal_existence_mitoya_base"
    module = sys.modules.get(module_name)
    if module is not None:
        return module

    module_path = Path(__file__).with_name("signal_existence_plan.py")
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load base module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_BASE = _load_base_module()
EXPERTS = EXPERTS_MITOYA
_BASE.EXPERTS = EXPERTS

RulePrediction = _BASE.RulePrediction
LAGS = _BASE.LAGS
RULES = _BASE.RULES
RANDOM_HIT2_BASELINE = _BASE.RANDOM_HIT2_BASELINE
RANDOM_PRECISION2_BASELINE = _BASE.RANDOM_PRECISION2_BASELINE


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Signal-existence validation before ML expansion.")
    p.add_argument("--db-path", default="", help="DB path override. Empty uses resolve_db_path.")
    p.add_argument("--db-glob", default="みとや*.db")
    p.add_argument("--selection-start", default="2025-11-01")
    p.add_argument("--selection-end", default="2026-01-27")
    p.add_argument("--holdout-start", default="2026-01-28")
    p.add_argument("--holdout-end", default="2026-05-29")
    p.add_argument("--a-weight", type=float, default=0.4)
    p.add_argument("--non-a-weight", type=float, default=1.3)
    p.add_argument("--momentum-window", type=int, default=14)
    p.add_argument("--drought-window", type=int, default=60)
    p.add_argument("--min-calendar-obs", type=int, default=8)
    p.add_argument("--bootstrap-n", type=int, default=4000)
    p.add_argument("--seed", type=int, default=20260601)
    p.add_argument("--output-prefix", default="db/experiments/signal_existence_mitoya")
    return p


def _load_dataset(args: argparse.Namespace) -> tuple[pd.DataFrame, Path]:
    db_path = resolve_db_path(str(args.db_path), pattern=str(args.db_glob))
    raw = build_base_rows_mitoya(db_path=db_path, a_weight=float(args.a_weight), non_a_weight=float(args.non_a_weight))
    agg = aggregate_mode_mitoya(raw, mode="atype3").copy()
    agg["date"] = pd.to_datetime(agg["date"])
    agg["expert"] = agg["group_key"].astype(str)
    agg["last_digit"] = agg["last_digit"].astype(str)
    agg["total_diff_coins"] = pd.to_numeric(agg["total_diff_coins"], errors="coerce").fillna(0.0)
    agg = agg[agg["expert"].isin(EXPERTS)].copy()
    agg = agg.sort_values(["expert", "date", "last_digit"]).reset_index(drop=True)
    rank_desc = agg.groupby(["expert", "date"], sort=False)["total_diff_coins"].rank(method="first", ascending=False)
    agg["rank"] = pd.to_numeric(rank_desc, errors="coerce").fillna(999).astype(int)
    agg["is_top1"] = (agg["rank"] == 1).astype(int)
    agg["is_top2"] = (agg["rank"] <= 2).astype(int)
    agg["is_positive"] = (agg["total_diff_coins"] > 0.0).astype(int)
    agg["dd"] = agg["date"].dt.day.astype(int)
    agg["weekday"] = agg["date"].dt.weekday.astype(int)
    return agg, db_path


_bootstrap_mean_ci = _BASE._bootstrap_mean_ci
_min_detectable_precision = _BASE._min_detectable_precision
_split_ranges = _BASE._split_ranges
_phase1_autocorr = _BASE._phase1_autocorr
_phase1_repeat_avoidance = _BASE._phase1_repeat_avoidance
_phase1_calendar_digit = _BASE._phase1_calendar_digit
_fixed_tables = _BASE._fixed_tables
_top2_from_scores = _BASE._top2_from_scores
_seed_for = _BASE._seed_for
_predict_rule = _BASE._predict_rule
_phase2_stability = _BASE._phase2_stability
_phase3_rules = _BASE._phase3_rules
_phase3_summary = _BASE._phase3_summary
_phase4_power = _BASE._phase4_power

_BASE.build_parser = build_parser
_BASE._load_dataset = _load_dataset


def main() -> int:
    _BASE.EXPERTS = EXPERTS
    return _BASE.main()


if __name__ == "__main__":
    raise SystemExit(main())
