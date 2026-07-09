from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from eda.mitoya_umj_mister_common import (
    RESULT_DIR,
    TARGET_MODELS,
    analyze_dd_candidate,
    load_frame,
    summarize_model_rankings,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


MODELS = [
    "\u30a6\u30eb\u30c8\u30e9\u30df\u30e9\u30af\u30eb\u30b8\u30e3\u30b0\u30e9\u30fc",
    "\u30df\u30b9\u30bf\u30fc\u30b8\u30e3\u30b0\u30e9\u30fc",
]
TOP_N = 3


def _rate_from_lookup(table: pd.DataFrame, key_col: str, value_col: str) -> dict[str, float]:
    if table.empty:
        return {}
    return {str(row[key_col]): float(row[value_col]) for _, row in table.iterrows()}


def _candidate_row(model: str, rank_row: pd.Series, candidate: dict[str, object]) -> dict[str, object]:
    row: dict[str, object] = {
        "model": model,
        "dd": int(rank_row["dd"]),
        "rank": int(rank_row["rank"]),
        "rows": int(rank_row["rows"]),
        "dates": int(rank_row["dates"]),
        "games_sum": float(rank_row["games_sum"]),
        "rb_sum": float(rank_row["rb_sum"]),
        "pooled_rb_rate": float(rank_row["pooled_rb_rate"]),
        "target_rows": int(candidate["target_rows"]),
        "target_dates": int(candidate["target_dates"]),
        "target_games_sum": float(candidate["target_games_sum"]),
        "target_rb_sum": float(candidate["target_rb_sum"]),
        "target_pooled_rb_rate": float(candidate["target_pooled_rb_rate"]),
        "rest_rows": int(candidate["rest_rows"]),
        "rest_dates": int(candidate["rest_dates"]),
        "rest_games_sum": float(candidate["rest_games_sum"]),
        "rest_rb_sum": float(candidate["rest_rb_sum"]),
        "rest_pooled_rb_rate": float(candidate["rest_pooled_rb_rate"]),
        "rate_diff_pp": float(candidate["rate_diff_pp"]),
        "dd_vs_rest_chi2": float(candidate["dd_vs_rest_chi2"]),
        "dd_vs_rest_p": float(candidate["dd_vs_rest_p"]),
        "dd_vs_rest_cramers_v": float(candidate["dd_vs_rest_cramers_v"]),
        "weekday_weekend_chi2": float(candidate["weekday_weekend_chi2"]),
        "weekday_weekend_p": float(candidate["weekday_weekend_p"]),
        "weekday_weekend_cramers_v": float(candidate["weekday_weekend_cramers_v"]),
        "date_games_pearson_r": float(candidate["date_games_pearson_r"]),
        "date_games_pearson_p": float(candidate["date_games_pearson_p"]),
        "date_games_pearson_n": int(candidate["date_games_pearson_n"]),
        "year_chi2": float(candidate["year_chi2"]),
        "year_p": float(candidate["year_p"]),
        "year_cramers_v": float(candidate["year_cramers_v"]),
        "top_date": candidate["top_date"],
        "top_date_rb_sum": float(candidate["top_date_rb_sum"]) if pd.notna(candidate["top_date_rb_sum"]) else pd.NA,
        "top_date_share": float(candidate["top_date_share"]) if pd.notna(candidate["top_date_share"]) else pd.NA,
        "weekday_verdict": candidate["weekday_verdict"],
        "concentration_verdict": candidate["concentration_verdict"],
        "games_verdict": candidate["games_verdict"],
        "period_verdict": candidate["period_verdict"],
        "overall_verdict": candidate["overall_verdict"],
    }

    weekday_rates = _rate_from_lookup(candidate["weekday_df"], "weekday_name", "pooled_rb_rate")
    for code, label in [(0, "mon"), (1, "tue"), (2, "wed"), (3, "thu"), (4, "fri"), (5, "sat"), (6, "sun")]:
        row[f"weekday_{label}_rate"] = weekday_rates.get(
            {"mon": "月", "tue": "火", "wed": "水", "thu": "木", "fri": "金", "sat": "土", "sun": "日"}[label], pd.NA
        )
    row["weekday_weekend_rate"] = _rate_from_lookup(candidate["weekday_weekend_df"], "bucket", "pooled_rb_rate").get(
        "weekend", pd.NA
    )
    row["weekday_weekday_rate"] = _rate_from_lookup(candidate["weekday_weekend_df"], "bucket", "pooled_rb_rate").get(
        "weekday", pd.NA
    )

    tier_rates = _rate_from_lookup(candidate["tier_df"], "games_tier", "pooled_rb_rate")
    for label in ["100-500", "500-1k", "1k-2k", "2k+"]:
        row[f"tier_{label.replace('-', '_').replace('+', 'plus')}_rate"] = tier_rates.get(label, pd.NA)

    year_rates = _rate_from_lookup(candidate["year_df"], "period", "pooled_rb_rate")
    for period in sorted(year_rates):
        row[f"year_{period}_rate"] = year_rates.get(period, pd.NA)
    if len(year_rates) >= 2:
        periods = list(sorted(year_rates))
        first = year_rates[periods[0]]
        second = year_rates[periods[-1]]
        row["year_rate_diff_pp"] = (second - first) * 100.0 if pd.notna(first) and pd.notna(second) else pd.NA
        row["year_rate_rel_change"] = (
            ((second - first) / first) if pd.notna(first) and pd.notna(second) and first != 0 else pd.NA
        )
    else:
        row["year_rate_diff_pp"] = pd.NA
        row["year_rate_rel_change"] = pd.NA

    return row


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def main() -> int:
    result_dir = RESULT_DIR
    result_dir.mkdir(parents=True, exist_ok=True)

    ranking_rows: list[pd.DataFrame] = []
    candidate_rows: list[dict[str, object]] = []

    for model in MODELS:
        frame = load_frame(machine_names=[model])
        ranking, top = summarize_model_rankings(frame, top_n=TOP_N)
        ranking["model"] = model
        ranking_rows.append(ranking)

        print(f"=== {model} ===")
        print(f"rows={len(frame)}, dates={frame['date'].nunique()}, machines={frame['machine_number'].nunique()}")
        if ranking.empty:
            print("no dd data")
            continue

        print(
            top.loc[:, ["rank", "dd", "rows", "dates", "games_sum", "rb_sum", "pooled_rb_rate"]].to_string(index=False)
        )

        for _, rank_row in top.iterrows():
            candidate = analyze_dd_candidate(frame, int(rank_row["dd"]))
            candidate_rows.append(_candidate_row(model, rank_row, candidate))

    ranking_df = pd.concat(ranking_rows, ignore_index=True) if ranking_rows else pd.DataFrame()
    candidate_df = pd.DataFrame(candidate_rows)

    _write_csv(ranking_df, result_dir / "task_ab_dd_ranking.csv")
    _write_csv(candidate_df, result_dir / "task_ab_candidate_summary.csv")

    print(f"written: {result_dir / 'task_ab_dd_ranking.csv'}")
    print(f"written: {result_dir / 'task_ab_candidate_summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
