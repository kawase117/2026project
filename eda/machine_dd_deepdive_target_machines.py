from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from eda.core import HALL_DBS, load_hall_df
from eda.machine_name_significance_scan import (
    DEFAULT_SHINDAI_EXCLUDE_DAYS,
    _prepare_frame,
)
from eda.machine_axis_pattern_scan import (
    MIN_CELL_N,
    _axis_breakdown,
    _scan_binary_outcome,
    _scan_diff_outcome,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

OUTPUT_DIR = PROJECT_ROOT / "eda" / "results" / "machine_dd_deepdive"
MIN_MACHINE_DAYS_TOTAL = 100  # 対象機種は既知なので閾値を下げる（軸pattern_scanの200より緩和）

TARGET_MACHINES = [
    "甲鉄城のカバネリ",
    "甲鉄城のカバネリ 海門(うなと)決戦",
    "ジャグラーガールズ",
    "クレアの秘宝伝 ～はじまりの扉と太陽の石～ ボーナストリガーver.",
]


def build_machine_hall_report(hall: str, machine_name: str, machine_frame: pd.DataFrame) -> dict:
    n_machine_days = int(len(machine_frame))
    baseline_plus = float(pd.to_numeric(machine_frame["plus"], errors="coerce").mean() * 100.0)
    baseline_hit104 = float(pd.to_numeric(machine_frame["hit104"], errors="coerce").mean() * 100.0)

    diff_stats = _scan_diff_outcome(machine_frame, axis="dd", min_cell_n=MIN_CELL_N)
    plus_stats = _scan_binary_outcome(machine_frame, axis="dd", outcome_col="plus")
    hit104_stats = _scan_binary_outcome(machine_frame, axis="dd", outcome_col="hit104")

    breakdown = _axis_breakdown(hall, machine_name, machine_frame, axis="dd", outcome="hit104")

    return {
        "hall": hall,
        "machine_name": machine_name,
        "n_machine_days": n_machine_days,
        "baseline_plus_rate": round(baseline_plus, 2),
        "baseline_hit104_rate": round(baseline_hit104, 2),
        "diff_p": diff_stats["p_value"],
        "diff_effect": diff_stats["effect_size"],
        "plus_p": plus_stats["p_value"],
        "plus_effect": plus_stats["effect_size"],
        "hit104_p": hit104_stats["p_value"],
        "hit104_effect": hit104_stats["effect_size"],
        "breakdown": breakdown,
    }


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    summary_rows: list[dict] = []
    all_breakdowns: list[pd.DataFrame] = []

    for hall in HALL_DBS:
        raw = load_hall_df(hall)
        frame = _prepare_frame(raw, shindai_exclude_days=DEFAULT_SHINDAI_EXCLUDE_DAYS)
        if "hall" not in frame.columns:
            frame["hall"] = hall

        for machine_name in TARGET_MACHINES:
            machine_frame = frame.loc[frame["machine_name"].astype(str).eq(machine_name)].copy()
            if len(machine_frame) < MIN_MACHINE_DAYS_TOTAL:
                summary_rows.append(
                    {
                        "hall": hall,
                        "machine_name": machine_name,
                        "n_machine_days": int(len(machine_frame)),
                        "note": f"insufficient (<{MIN_MACHINE_DAYS_TOTAL})",
                    }
                )
                continue

            report = build_machine_hall_report(hall, machine_name, machine_frame)
            breakdown = report.pop("breakdown")
            breakdown["baseline_hit104_rate"] = report["baseline_hit104_rate"]
            breakdown["baseline_plus_rate"] = report["baseline_plus_rate"]
            all_breakdowns.append(breakdown)
            summary_rows.append(report)

    summary_df = pd.DataFrame(summary_rows)
    breakdown_df = pd.concat(all_breakdowns, ignore_index=True) if all_breakdowns else pd.DataFrame()

    summary_df.to_csv(OUTPUT_DIR / "summary.csv", index=False, encoding="utf-8-sig")
    breakdown_df.to_csv(OUTPUT_DIR / "dd_breakdown.csv", index=False, encoding="utf-8-sig")

    print(f"written: {OUTPUT_DIR}")
    print(summary_df.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
