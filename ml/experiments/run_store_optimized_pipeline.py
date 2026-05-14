from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Sequence

from ml.experiments.result_format import render_html_page, write_json, write_text
from ml.experiments.store_optimized_pipeline import (
    PipelineConfig,
    StoreOptimizedTrainingEngine,
    _render_overview_feature_catalog_markdown,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_ROOT = PROJECT_ROOT / "db"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "db" / "experiments"


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.enable_optuna and args.disable_optuna:
        parser.error("Specify either --enable-optuna or --disable-optuna, not both.")
    output_root = Path(args.output_root)

    source_db_paths = _resolve_db_paths(args)
    if not source_db_paths:
        parser.error("No database files matched the provided arguments.")
    db_paths = _prepare_working_db_paths(
        source_db_paths=source_db_paths,
        output_root=output_root,
        args=args,
    )

    config = PipelineConfig(
        db_paths=db_paths,
        groupings=args.groupings,
        targets=args.targets,
        base_cv=args.base_cv,
        compare_cv=args.compare_cv,
        models=args.models,
        merge_modes=args.merge_modes,
        optuna_enabled=args.enable_optuna and not args.disable_optuna,
        optuna_trials=args.optuna_trials,
        optuna_top_k_models=args.optuna_top_k_models,
        n_splits=args.n_splits,
        train_window_size=args.train_window_size,
        valid_window_size=args.valid_window_size,
        random_state=args.random_state,
        feature_selection_enabled=not args.disable_feature_selection,
        feature_selection_selector_model=args.feature_selection_selector_model,
        feature_selection_strategy=args.feature_selection_strategy,
        feature_selection_top_k=args.feature_selection_top_k,
        feature_selection_min_features=args.feature_selection_min_features,
        feature_selection_keep_ratio=args.feature_selection_keep_ratio,
        feature_selection_rfecv_cv_splits=args.feature_selection_rfecv_cv_splits,
        feature_selection_permutation_repeats=args.feature_selection_permutation_repeats,
        feature_selection_shadow_quantile=args.feature_selection_shadow_quantile,
        forecast_mode=args.forecast_mode,
        feature_ablation_mode=args.feature_ablation_mode,
    )

    engine = StoreOptimizedTrainingEngine(config=config)
    result = engine.run(output_root=output_root)

    overview = {
        "generated_at": datetime.now().isoformat(),
        "source_db_paths": [str(path) for path in source_db_paths],
        "working_db_paths": [str(path) for path in db_paths],
        "db_paths": [str(path) for path in db_paths],
        "output_root": str(output_root),
        "config": {
            "groupings": args.groupings,
            "targets": args.targets,
            "base_cv": args.base_cv,
            "compare_cv": args.compare_cv,
            "models": args.models,
            "merge_modes": args.merge_modes,
            "optuna_enabled": args.enable_optuna and not args.disable_optuna,
            "feature_selection_enabled": not args.disable_feature_selection,
            "feature_selection_selector_model": args.feature_selection_selector_model,
            "feature_selection_strategy": args.feature_selection_strategy,
            "forecast_mode": args.forecast_mode,
            "feature_ablation_mode": args.feature_ablation_mode,
            "copy_db_before_run": args.copy_db_before_run,
            "working_db_root": args.working_db_root,
            "working_db_suffix": args.working_db_suffix,
        },
        "stores": result["stores"],
    }
    write_json(output_root / "store_optimized_pipeline_overview.json", overview)
    write_text(
        output_root / "store_optimized_pipeline_overview.html",
        _render_overview_html(output_root=output_root, overview=overview),
    )
    write_text(
        output_root / "store_optimized_pipeline_overview_feature_catalog.md",
        _render_overview_feature_catalog_markdown(overview),
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the store-optimized ML pipeline over one or more SQLite DBs.")
    parser.add_argument("--db-root", default=str(DEFAULT_DB_ROOT), help="Directory containing source .db files.")
    parser.add_argument("--db-pattern", default="*.db", help="Glob pattern used under --db-root when --db-path is omitted.")
    parser.add_argument("--db-path", action="append", default=[], help="Explicit DB path. Repeatable.")
    parser.add_argument("--copy-db-before-run", action="store_true", help="Copy source DBs before running and use working copies.")
    parser.add_argument("--working-db-root", default=None, help="Root directory for copied working DB files.")
    parser.add_argument("--working-db-suffix", default="_working", help="Suffix appended to copied DB filename stem.")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT), help="Root directory for pipeline outputs.")
    parser.add_argument("--groupings", nargs="+", default=["machine_type", "last_digit", "machine_number_position"])
    parser.add_argument("--targets", nargs="+", default=["is_rank_1", "is_top_3", "is_top_5"])
    parser.add_argument("--base-cv", default="expanding")
    parser.add_argument("--compare-cv", nargs="*", default=["sliding"])
    parser.add_argument("--models", nargs="+", default=["lgbm", "xgb", "catboost"])
    parser.add_argument("--merge-modes", nargs="+", default=["single_store"])
    parser.add_argument("--n-splits", type=int, default=5)
    parser.add_argument("--train-window-size", type=int, default=None)
    parser.add_argument("--valid-window-size", type=int, default=None)
    parser.add_argument("--optuna-trials", type=int, default=10)
    parser.add_argument("--optuna-top-k-models", type=int, default=1)
    parser.add_argument("--enable-optuna", action="store_true")
    parser.add_argument("--disable-optuna", action="store_true")
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--disable-feature-selection", action="store_true")
    parser.add_argument("--feature-selection-selector-model", default="lgbm")
    parser.add_argument("--feature-selection-strategy", default="rfecv_boruta")
    parser.add_argument("--feature-selection-top-k", type=int, default=None)
    parser.add_argument("--feature-selection-min-features", type=int, default=6)
    parser.add_argument("--feature-selection-keep-ratio", type=float, default=0.6)
    parser.add_argument("--feature-selection-rfecv-cv-splits", type=int, default=3)
    parser.add_argument("--feature-selection-permutation-repeats", type=int, default=3)
    parser.add_argument("--feature-selection-shadow-quantile", type=float, default=1.0)
    parser.add_argument("--forecast-mode", action="store_true", help="Train only on historical-safe features and emit next-day forecasts.")
    parser.add_argument(
        "--feature-ablation-mode",
        choices=[
            "none",
            "worst_off",
            "momvol_off",
            "both_off",
            "worst_rate_off",
            "worst_streak_off",
            "worst_only_recency",
            "same_day_of_month_off",
            "worst_rate_off_same_day_of_month_off",
            "same_weekday_off",
            "worst_rate_off_same_weekday_off",
            "event_off",
            "worst_rate_off_event_off",
            "rank1_special_off",
            "event_distance_redesign_off",
            "rank1_special_off_event_distance_redesign_off",
        ],
        default="none",
        help="Ablation toggle for last_digit feature families.",
    )
    return parser


def _resolve_db_paths(args: argparse.Namespace) -> list[Path]:
    explicit_paths = [Path(path) for path in args.db_path]
    if explicit_paths:
        missing = [path for path in explicit_paths if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"DB file(s) not found: {', '.join(str(p) for p in missing)}")
        return sorted(explicit_paths)
    db_root = Path(args.db_root)
    return sorted(path for path in db_root.glob(args.db_pattern) if path.is_file())


def _prepare_working_db_paths(
    *,
    source_db_paths: list[Path],
    output_root: Path,
    args: argparse.Namespace,
) -> list[Path]:
    if not args.copy_db_before_run:
        return source_db_paths

    working_root = Path(args.working_db_root) if args.working_db_root else output_root / "working_dbs"
    working_root.mkdir(parents=True, exist_ok=True)
    copied_paths: list[Path] = []
    for source_path in source_db_paths:
        target_name = f"{source_path.stem}{args.working_db_suffix}{source_path.suffix}"
        target_path = working_root / target_name
        shutil.copy2(source_path, target_path)
        copied_paths.append(target_path)
    return copied_paths


def _render_overview_html(*, output_root: Path, overview: dict[str, object]) -> str:
    store_cards = []
    for store in overview.get("stores", []):
        group_links = []
        for grouping_summary in store.get("groupings", []):
            store_id = grouping_summary.get("store_id")
            grouping = grouping_summary.get("grouping")
            report_path = Path(str(store_id)) / str(grouping) / "pipeline" / "reports" / "summary.html"
            group_links.append(
                f"<li><a href=\"{report_path.as_posix()}\">{grouping}</a></li>"
            )
        errors = store.get("errors", [])
        error_html = ""
        if errors:
            error_html = "<p>Errors: " + ", ".join(f"{item['grouping']}: {item['error']}" for item in errors) + "</p>"
        store_cards.append(
            f"""
            <section>
              <h2>{store.get('store_id')}</h2>
              <p>Available grouping reports:</p>
              <ul>{''.join(group_links) or '<li>No grouping results</li>'}</ul>
              {error_html}
            </section>
            """
        )

    body = f"""
    <section class="hero">
      <p class="eyebrow">Store Optimized Pipeline</p>
      <h1>Pipeline Overview</h1>
      <p class="lede">Human-facing dashboard. Structured machine-readable outputs are stored beside this file as JSON, CSV, and per-group artifacts.</p>
      <p>Generated at: {overview.get('generated_at')}</p>
      <p>Output root: {output_root}</p>
    </section>
    {''.join(store_cards)}
    """
    return render_html_page(title="Store Optimized Pipeline Overview", body=body)


if __name__ == "__main__":
    raise SystemExit(main())
