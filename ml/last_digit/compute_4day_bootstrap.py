from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compute 4day bootstrap CI from Mitoya walk-forward output.")
    parser.add_argument("--input", default="db/experiments/tail_ltr_mitoya_wf.json")
    parser.add_argument("--output", default="db/experiments/mitoya_4day_bootstrap.csv")
    parser.add_argument("--n-boot", type=int, default=4000)
    parser.add_argument("--seed", type=int, default=42)
    return parser


def bootstrap_mean_ci(values: np.ndarray, *, n_boot: int, seed: int) -> tuple[float, float]:
    if values.size == 0:
        return 0.0, 0.0
    rng = np.random.default_rng(seed)
    draws = rng.choice(values, size=(n_boot, values.size), replace=True).mean(axis=1)
    lo, hi = np.quantile(draws, [0.025, 0.975])
    return float(lo), float(hi)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    input_path = Path(args.input)
    raw_days_path = input_path.with_name(input_path.stem + "_atype3_raw_days.csv")
    df = pd.read_csv(raw_days_path)
    df["date"] = pd.to_datetime(df["date"])
    fourday = df.loc[df["day_bucket"].eq("4day")].copy()
    per_date = fourday.groupby("date", as_index=False)["excess"].mean()
    values = per_date["excess"].to_numpy(dtype=float)
    ci_lower, ci_upper = bootstrap_mean_ci(values, n_boot=args.n_boot, seed=args.seed)

    out = pd.DataFrame(
        [
            {
                "n_dates": int(values.size),
                "mean": float(values.mean()) if values.size else 0.0,
                "median": float(np.median(values)) if values.size else 0.0,
                "ci_lower": ci_lower,
                "ci_upper": ci_upper,
            }
        ]
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
