from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import DEFAULT_DB_PATH, RESULTS_DIR
from .report_generator import build_report
from .walk_forward_engine import _debut_phase_best_variant, _segment_best_variant, load_machine_data, run_backtest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kamata7 walk-forward scoring backtest")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--variants", type=str, default="all")
    parser.add_argument("--windows", type=str, default="90,180,365")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--min-actual-machines", type=int, default=50)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    variants = (
        None if args.variants == "all" else tuple(value.strip() for value in args.variants.split(",") if value.strip())
    )
    windows = tuple(int(value) for value in args.windows.split(",") if value.strip())

    if args.report_only:
        daily_path = args.output_dir / "daily_results.csv"
        summary_path = args.output_dir / "summary.csv"
        component_path = args.output_dir / "component_analysis.csv"
        weight_path = args.output_dir / "weight_optimization.csv"
        correlation_path = args.output_dir / "correlation_matrix.csv"
        segment_path = args.output_dir / "segment_daily_results.csv"
        debut_path = args.output_dir / "debut_phase_daily_results.csv"
        if not all(path.exists() for path in [daily_path, summary_path, component_path, weight_path, correlation_path]):
            raise SystemExit("report-only requires existing result CSV files")
        import pandas as pd

        summary = pd.read_csv(summary_path, encoding="utf-8-sig")
        daily = pd.read_csv(daily_path, encoding="utf-8-sig")
        component = pd.read_csv(component_path, encoding="utf-8-sig")
        weights = pd.read_csv(weight_path, encoding="utf-8-sig")
        correlation = pd.read_csv(correlation_path, encoding="utf-8-sig")
        extra_checks = {}
        if segment_path.exists():
            segment_raw = pd.read_csv(segment_path, encoding="utf-8-sig")
            segment_top = (
                segment_raw[segment_raw.get("selection", pd.Series("top50")).eq("top50")]
                if not segment_raw.empty
                else segment_raw
            )
            extra_checks["Segment Best Variant"] = _segment_best_variant(segment_top)
        if debut_path.exists():
            debut_raw = pd.read_csv(debut_path, encoding="utf-8-sig")
            debut_top = (
                debut_raw[debut_raw.get("selection", pd.Series("top50")).eq("top50")]
                if not debut_raw.empty
                else debut_raw
            )
            extra_checks["Debut Phase Best Variant"] = _debut_phase_best_variant(debut_top)
        report = build_report(
            summary=summary,
            daily_results=daily,
            component_analysis=component,
            weight_optimization=weights,
            correlation_matrix=correlation.set_index("component"),
            extra_checks=extra_checks,
            output_dir=args.output_dir,
        )
        (args.output_dir / "report.md").write_text(report, encoding="utf-8")
        print(args.output_dir / "report.md")
        return 0

    data = load_machine_data(args.db_path)
    run_backtest(
        data,
        output_dir=args.output_dir,
        variants=variants,
        windows=windows,
        resume=args.resume,
        min_actual_machines=args.min_actual_machines,
    )
    print(args.output_dir)
    print(args.output_dir / "report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
