from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from ml.last_digit.mitoya_segmentation import build_base_rows_mitoya
from ml.last_digit.utils import resolve_db_path


def _prepare_base(raw: pd.DataFrame) -> pd.DataFrame:
    work = raw.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.normalize()
    work["last_digit"] = work["last_digit"].astype(str).str.strip()
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work["is_a_type"] = pd.to_numeric(work["is_a_type"], errors="coerce").fillna(0).astype(int)
    work = work.dropna(subset=["date", "diff_coins_normalized"]).copy()
    work = work[work["last_digit"].str.fullmatch(r"\d+")].copy()
    work["last_digit"] = pd.to_numeric(work["last_digit"], errors="coerce")
    work = work[work["last_digit"].between(0, 9, inclusive="both")].copy()
    work["last_digit"] = work["last_digit"].astype(int).astype(str)
    work["dd"] = work["date"].dt.day.astype(int)
    return work


def build_dd_last_digit_cross(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = _prepare_base(raw)
    if work.empty:
        cross_cols = ["dd", "last_digit", "mean_diff", "n_dates", "n_machines", "n_A_machines"]
        summary_cols = ["dd", "n_dates", "mean_diff_top3", "mean_diff_bottom3", "dd_spread", "top3_digits", "bottom3_digits"]
        return pd.DataFrame(columns=cross_cols), pd.DataFrame(columns=summary_cols)

    daily = (
        work.groupby(["date", "dd", "last_digit"], sort=True)
        .agg(
            daily_mean_diff=("diff_coins_normalized", "mean"),
            n_machines=("diff_coins_normalized", "size"),
            n_A_machines=("is_a_type", "sum"),
        )
        .reset_index()
    )

    cross = (
        daily.groupby(["dd", "last_digit"], sort=True)
        .agg(
            mean_diff=("daily_mean_diff", "mean"),
            n_dates=("date", "nunique"),
            n_machines=("n_machines", "sum"),
            n_A_machines=("n_A_machines", "sum"),
        )
        .reset_index()
    )

    cross["dd"] = pd.to_numeric(cross["dd"], errors="coerce").fillna(0).astype(int)
    cross["last_digit"] = pd.to_numeric(cross["last_digit"], errors="coerce").fillna(0).astype(int).astype(str)
    cross = cross.sort_values(["dd", "last_digit"], key=lambda col: pd.to_numeric(col, errors="coerce")).reset_index(drop=True)
    cross = cross.reindex(columns=["dd", "last_digit", "mean_diff", "n_dates", "n_machines", "n_A_machines"])

    summary_rows: list[dict[str, object]] = []
    for dd_value, dd_df in cross.groupby("dd", sort=True):
        ordered = dd_df.copy()
        ordered["last_digit_num"] = pd.to_numeric(ordered["last_digit"], errors="coerce")
        ordered = ordered.sort_values(["mean_diff", "last_digit_num"], ascending=[False, True]).reset_index(drop=True)
        top3 = ordered.head(3)
        bottom3 = ordered.tail(3)
        top3_mean = float(top3["mean_diff"].mean()) if not top3.empty else 0.0
        bottom3_mean = float(bottom3["mean_diff"].mean()) if not bottom3.empty else 0.0
        summary_rows.append(
            {
                "dd": int(dd_value),
                "n_dates": int(ordered["n_dates"].max()) if not ordered.empty else 0,
                "mean_diff_top3": top3_mean,
                "mean_diff_bottom3": bottom3_mean,
                "dd_spread": top3_mean - bottom3_mean,
                "top3_digits": ",".join(top3["last_digit"].astype(str).tolist()),
                "bottom3_digits": ",".join(bottom3["last_digit"].astype(str).tolist()),
            }
        )

    summary = pd.DataFrame(summary_rows)
    summary = summary.reindex(
        columns=[
            "dd",
            "n_dates",
            "mean_diff_top3",
            "mean_diff_bottom3",
            "dd_spread",
            "top3_digits",
            "bottom3_digits",
        ]
    )
    return cross, summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cross-tab Mitoya DD and last digit raw payout structure.")
    parser.add_argument("--db-path", default="", help="DB path override. Empty uses resolve_db_path.")
    parser.add_argument("--db-glob", default="みとや大森町店.db", help="DB auto-detect glob pattern used when --db-path is empty")
    parser.add_argument("--output-prefix", default="db/experiments/mitoya_dd_last_digit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db_path = resolve_db_path(str(args.db_path), pattern=str(args.db_glob))
    raw = build_base_rows_mitoya(db_path=db_path, a_weight=1.0, non_a_weight=1.0)
    cross, summary = build_dd_last_digit_cross(raw)

    out_prefix = Path(args.output_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    cross_path = out_prefix.with_name(out_prefix.name + "_cross.csv")
    summary_path = out_prefix.with_name(out_prefix.name + "_dd_summary.csv")
    cross.to_csv(cross_path, index=False, encoding="utf-8-sig")
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    print(cross_path)
    print(summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
