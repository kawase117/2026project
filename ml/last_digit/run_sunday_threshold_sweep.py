from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from ml.last_digit import tail_ltr_mitoya_wf as wf


def collapse_unique_dates(day_df: pd.DataFrame) -> pd.DataFrame:
    if day_df.empty:
        return pd.DataFrame(columns=["date", "mean_excess", "hit_at_2", "played_rate"])
    work = day_df.copy()
    work["date"] = pd.to_datetime(work["date"])
    work["played_flag"] = pd.to_numeric(work["excess"], errors="coerce").fillna(0.0).ne(0.0).astype(float)
    return (
        work.groupby("date", as_index=False)
        .agg(
            mean_excess=("excess", "mean"),
            hit_at_2=("hit_at_2", "mean"),
            played_rate=("played_flag", "mean"),
        )
        .sort_values("date")
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Sunday-only margin-threshold sweep for Mitoya.")
    parser.add_argument("--output", default="db/experiments/mitoya_sunday_threshold_sweep.csv")
    parser.add_argument("--db-path", default="")
    parser.add_argument("--db-glob", default="みとや*.db")
    parser.add_argument("--q-values", default="0.40,0.50,0.55,0.60,0.65")
    parser.add_argument("--seeds", default="42,77,123,202,303,404,505,606")
    parser.add_argument("--test-days", type=int, default=14)
    parser.add_argument("--warmup-days", type=int, default=56)
    parser.add_argument("--min-train-days-sunday", type=int, default=14)
    parser.add_argument("--windows-sunday", default="full_2025")
    parser.add_argument("--lambdas-sunday", default="0.75,1.0,1.25")
    parser.add_argument("--q-grid-sunday", default="0.0,0.1,0.2,0.3,0.4")
    parser.add_argument("--max-blocks", type=int, default=0)
    parser.add_argument("--n-boot", type=int, default=10000)
    parser.add_argument("--use-gpu", action="store_true")
    parser.add_argument("--gpu-backend", choices=["cuda", "gpu_hist"], default="cuda")
    parser.add_argument("--log-level", default="INFO")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    wf._BASE.configure_logging(args.log_level)

    base_args = wf.build_parser().parse_args([])
    base_args.db_path = args.db_path
    base_args.db_glob = args.db_glob
    base_args.seeds = args.seeds
    base_args.test_days = args.test_days
    base_args.warmup_days = args.warmup_days
    base_args.min_train_days_sunday = args.min_train_days_sunday
    base_args.windows_sunday = args.windows_sunday
    base_args.lambdas_sunday = args.lambdas_sunday
    base_args.q_grid_sunday = args.q_grid_sunday
    base_args.max_blocks = args.max_blocks
    base_args.n_boot = args.n_boot
    base_args.use_gpu = args.use_gpu
    base_args.gpu_backend = args.gpu_backend

    db_path = wf._BASE.resolve_db_path(args.db_path, pattern=args.db_glob)
    raw = wf.build_base_rows_mitoya(db_path=db_path, a_weight=1.0, non_a_weight=1.0)
    dataset = wf.add_mitoya_bucket_features(wf.aggregate_mode(raw, mode="atype3"))
    seeds = wf._BASE.parse_csv_ints(args.seeds)
    model_params = wf._BASE._build_model_params(use_gpu=args.use_gpu, gpu_backend=args.gpu_backend)
    q_values = wf._BASE.parse_csv_floats(args.q_values)

    rows: list[dict[str, float]] = []
    for q_override in q_values:
        base_args.sunday_q_override = float(q_override)
        sunday_cfg = {"Sunday": wf._build_bucket_configs(base_args)["Sunday"]}
        day_df, _ = wf.run_mode_bucketed(
            dataset=dataset,
            seeds=seeds,
            test_days=args.test_days,
            warmup_days=args.warmup_days,
            bucket_configs=sunday_cfg,
            diff_col="total_diff_coins",
            model_params=model_params,
            max_blocks=args.max_blocks,
            n_boot=args.n_boot,
        )
        date_level = collapse_unique_dates(day_df)
        rows.append(
            {
                "q_override": float(q_override),
                "mean_diff": float(date_level["mean_excess"].mean()) if not date_level.empty else 0.0,
                "hit_at_2": float(date_level["hit_at_2"].mean()) if not date_level.empty else 0.0,
                "played_rate": float(date_level["played_rate"].mean()) if not date_level.empty else 0.0,
                "n_days": int(date_level["date"].nunique()),
            }
        )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out_path, index=False, encoding="utf-8-sig")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
