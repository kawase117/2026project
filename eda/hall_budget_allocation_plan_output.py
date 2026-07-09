from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from eda.core import HALL_DBS, load_hall_df
from eda.hall_budget_allocation_light import DEFAULT_PLAN_OUTPUT_ROOT, run_plan_output

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="plan hall budget allocation output")
    parser.add_argument("--halls", nargs="+", default=list(HALL_DBS.keys()))
    parser.add_argument("--output-root", type=Path, default=DEFAULT_PLAN_OUTPUT_ROOT)
    parser.add_argument("--min-games", type=int, default=0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    summary_frames = []

    for hall in args.halls:
        if hall not in HALL_DBS:
            raise ValueError(f"unknown hall: {hall}")
        raw = load_hall_df(hall)
        result = run_plan_output(hall, raw=raw, output_root=output_root, min_games=args.min_games)
        summary_frames.append(result["summary"])

    if summary_frames:
        import pandas as pd

        pd.concat(summary_frames, ignore_index=True).to_csv(
            output_root / "summary_report.csv", index=False, encoding="utf-8-sig"
        )
    print(f"written: {output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
