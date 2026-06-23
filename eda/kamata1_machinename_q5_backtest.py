from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda.cross_hall_pattern_verification import (
    COINS_PER_GAME,
    WINDOW_MONTHS,
    assign_period,
    load_data as base_load_data,
    quintile,
)
from eda.kamata7_machinename_q5_backtest import (
    MIN_GAMES,
    SUMMARY_COLUMNS,
    XDAY_DAYS,
    _empty_metrics,
    _fmt,
    _mean_metrics,
    _skip_row,
    _summarize_group,
    build_backtest_outputs,
    build_period_summary,
    build_training_table,
    save_outputs,
    summarize_pair,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


DB_PATH = Path(__file__).resolve().parents[1] / "db" / "マルハンメガシティ2000-蒲田1.db"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "kamata1_machinename_q5_backtest"
HALL_NAME = "蒲田1"
FLOOR_BOUNDARY = 3000


def load_data(db_path: Path, min_games: int = MIN_GAMES) -> pd.DataFrame:
    df = base_load_data(db_path)
    df = df[df["games_normalized"] >= min_games].copy()
    df["period"] = assign_period(df["date"], WINDOW_MONTHS)
    df["floor"] = df["machine_number"].apply(
        lambda x: "2F" if x < FLOOR_BOUNDARY else "3F"
    )
    df["is_xday7"] = df["date"].dt.day.isin(XDAY_DAYS)
    return df


def build_report(outputs: dict[str, pd.DataFrame]) -> str:
    scopes = [
        ("全体", outputs["period_summary"]),
        ("2F", outputs["period_summary_2F"]),
        ("3F", outputs["period_summary_3F"]),
        ("7系日", outputs["xday7_overlay"]),
    ]
    header = [
        "| scope | pairs | Q5_avg_diff | Q1_avg_diff | All_avg_diff | Q5_vs_All_diff | Q5_vs_Q1_diff | Q5_payout | Q1_payout | All_payout | Q5_win | Q1_win | All_win |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    rows: list[str] = []
    means_by_scope: dict[str, dict[str, float]] = {}
    for name, df in scopes:
        means = _mean_metrics(df)
        means_by_scope[name] = means
        rows.append(
            "| "
            + " | ".join(
                [
                    name,
                    str(len(df)),
                    _fmt(means.get("Q5_avg_diff")),
                    _fmt(means.get("Q1_avg_diff")),
                    _fmt(means.get("All_avg_diff")),
                    _fmt(means.get("Q5_vs_All_diff")),
                    _fmt(means.get("Q5_vs_Q1_diff")),
                    _fmt(means.get("Q5_payout_rate")),
                    _fmt(means.get("Q1_payout_rate")),
                    _fmt(means.get("All_payout_rate")),
                    _fmt(means.get("Q5_win_rate")),
                    _fmt(means.get("Q1_win_rate")),
                    _fmt(means.get("All_win_rate")),
                ]
            )
            + " |"
        )

    overall = means_by_scope.get("全体", {})
    xday = means_by_scope.get("7系日", {})
    q5_boost = xday.get("Q5_avg_diff", float("nan")) - overall.get("Q5_avg_diff", float("nan"))
    all_boost = xday.get("All_avg_diff", float("nan")) - overall.get("All_avg_diff", float("nan"))
    excess_boost = xday.get("Q5_vs_All_diff", float("nan")) - overall.get("Q5_vs_All_diff", float("nan"))

    report_lines = [
        f"# {HALL_NAME} machine_name Q5継続バックテスト",
        "",
        "## 全ペア平均比較",
        *header,
        *rows,
        "",
        "## 主要差分",
        f"- 全体 Q5 vs All excess: {_fmt(overall.get('Q5_vs_All_diff'))}",
        f"- 全体 Q5 vs Q1 spread: {_fmt(overall.get('Q5_vs_Q1_diff'))}",
        f"- 7系日 Q5 boost vs 全体: {_fmt(q5_boost)}",
        f"- 7系日 All boost vs 全体: {_fmt(all_boost)}",
        f"- 7系日 excess boost vs 全体: {_fmt(excess_boost)}",
    ]
    if "n_xday_dates" in outputs["xday7_overlay"].columns:
        report_lines.append(
            f"- 7系日の平均対象日数/ペア: {_fmt(_mean_metrics(outputs['xday7_overlay']).get('n_xday_dates'))}"
        )
    return "\n".join(report_lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", type=Path, default=DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--min-games", type=int, default=MIN_GAMES)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    df = load_data(args.db_path, min_games=args.min_games)
    outputs = build_backtest_outputs(df)
    save_outputs(outputs, args.output_dir)
    # save_outputs uses kamata7's build_report; overwrite with local version
    (args.output_dir / "report.md").write_text(build_report(outputs), encoding="utf-8")
    print(f"saved outputs to {args.output_dir}")


if __name__ == "__main__":
    main()
