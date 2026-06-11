from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


KNOWN_STRONG_DD = {4, 7, 11, 14, 17, 24, 27, 30}


def build_dd_candidate_ranking(dd_summary: pd.DataFrame) -> pd.DataFrame:
    work = dd_summary.copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "dd",
                "n_dates",
                "mean_diff_top3",
                "mean_diff_bottom3",
                "dd_spread",
                "top3_abs",
                "bottom3_abs",
                "top3_to_bottom3_ratio",
                "score",
                "known_hint",
            ]
        )

    work["dd"] = pd.to_numeric(work["dd"], errors="coerce")
    work["n_dates"] = pd.to_numeric(work["n_dates"], errors="coerce")
    work["mean_diff_top3"] = pd.to_numeric(work["mean_diff_top3"], errors="coerce")
    work["mean_diff_bottom3"] = pd.to_numeric(work["mean_diff_bottom3"], errors="coerce")
    work["dd_spread"] = pd.to_numeric(work["dd_spread"], errors="coerce")
    work = work.dropna(subset=["dd", "n_dates", "mean_diff_top3", "mean_diff_bottom3", "dd_spread"]).copy()
    work["dd"] = work["dd"].astype(int)
    work["top3_abs"] = work["mean_diff_top3"].abs()
    work["bottom3_abs"] = work["mean_diff_bottom3"].abs()
    work["top3_to_bottom3_ratio"] = np.where(
        work["bottom3_abs"] > 0,
        work["top3_abs"] / work["bottom3_abs"],
        work["top3_abs"],
    )
    work["stability_weight"] = np.log1p(work["n_dates"].clip(lower=0.0))
    work["score"] = (
        work["dd_spread"].clip(lower=0.0) * work["stability_weight"]
        + 0.10 * work["top3_abs"]
        + 0.05 * work["top3_to_bottom3_ratio"]
    )
    work["known_hint"] = np.where(work["dd"].isin(KNOWN_STRONG_DD), "known", "new")
    work = work.sort_values(
        ["score", "dd_spread", "top3_abs", "n_dates", "dd"],
        ascending=[False, False, False, False, True],
    ).reset_index(drop=True)
    work["score_rank"] = np.arange(1, len(work) + 1, dtype=int)
    return work[
        [
            "score_rank",
            "dd",
            "known_hint",
            "n_dates",
            "mean_diff_top3",
            "mean_diff_bottom3",
            "dd_spread",
            "top3_abs",
            "bottom3_abs",
            "top3_to_bottom3_ratio",
            "score",
            "top3_digits",
            "bottom3_digits",
        ]
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rank Mitoya DD candidates from raw DD x last-digit summary.")
    parser.add_argument(
        "--dd-summary-csv",
        default="db/experiments/mitoya_dd_last_digit_dd_summary.csv",
        help="Input DD summary CSV produced by mitoya_dd_last_digit_cross_analysis.py",
    )
    parser.add_argument(
        "--output-csv",
        default="db/experiments/mitoya_dd_last_digit_candidate_ranking.csv",
        help="Output ranking CSV.",
    )
    parser.add_argument("--top-n", type=int, default=20, help="Print the top N rows to stdout.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    dd_summary = pd.read_csv(args.dd_summary_csv)
    ranking = build_dd_candidate_ranking(dd_summary)

    output_csv = Path(args.output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    ranking.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(output_csv)
    if not ranking.empty:
        print(ranking.head(max(int(args.top_n), 0)).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
