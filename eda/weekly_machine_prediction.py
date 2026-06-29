from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from eda.granularity_shift_common import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    DEFAULT_WEEK_EVAL_WEEKS,
    DEFAULT_WEEK_THRESHOLDS,
    DEFAULT_WEEK_TOP_KS,
    format_markdown_table,
    load_base_frame,
    qcut_extreme_delta,
    resolve_db_path,
    safe_spearman,
    threshold_lift_by_date,
    weekly_machine_aggregates,
)

SCRIPT_NAME = "weekly_machine_prediction"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kamata7 machine x week granularity shift analysis")
    parser.add_argument("--db-path", type=Path, default=None, help="SQLite DB path")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR / SCRIPT_NAME)
    parser.add_argument("--min-games", type=int, default=1500)
    parser.add_argument("--history-days", type=int, default=90)
    parser.add_argument("--eval-weeks", type=int, default=DEFAULT_WEEK_EVAL_WEEKS)
    parser.add_argument("--top-ks", type=str, default="1,3,5", help="Comma-separated top-K list")
    parser.add_argument("--thresholds", type=str, default="100,101,102,103", help="Comma-separated payout thresholds")
    return parser


def _parse_int_list(raw: str) -> tuple[int, ...]:
    values = [item.strip() for item in str(raw).split(",") if item.strip()]
    if not values:
        return ()
    return tuple(int(value) for value in values)


def _parse_float_list(raw: str) -> tuple[float, ...]:
    values = [item.strip() for item in str(raw).split(",") if item.strip()]
    if not values:
        return ()
    return tuple(float(value) for value in values)


def _group_summary(frame: pd.DataFrame, by: str, *, sort_cols: list[str], head: int = 10) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    out = (
        frame.groupby(by, dropna=False)
        .agg(
            n=("week_avg_payout", "size"),
            avg_week_payout=("week_avg_payout", "mean"),
            median_week_payout=("week_avg_payout", "median"),
            avg_positive_days=("week_positive_days", "mean"),
            avg_hist_metric=("hist_metric", "mean"),
        )
        .reset_index()
        .sort_values(sort_cols, ascending=[False] * len(sort_cols))
    )
    return out.head(head).reset_index(drop=True)


def build_outputs(
    *,
    db_path: Path | None,
    output_dir: Path,
    min_games: int,
    history_days: int,
    eval_weeks: int,
    top_ks: tuple[int, ...],
    thresholds: tuple[float, ...],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, str]:
    frame = load_base_frame(db_path, min_games=min_games, history_days=history_days)
    weekly = weekly_machine_aggregates(frame, history_days=history_days)
    if weekly.empty:
        raise ValueError("No machine/week rows were produced")

    weekly = weekly.copy()
    weekly["week_avg_payout_pct"] = weekly["week_avg_payout"]
    weekly["hist_metric_pct"] = weekly["hist_metric"] * 100.0
    weekly["prev_week_avg_payout_pct"] = weekly["prev_week_avg_payout"]
    weekly["week_start"] = pd.to_datetime(weekly["week_start"])

    unique_weeks = pd.Index(sorted(pd.Timestamp(value) for value in weekly["week_start"].dropna().unique()))
    eval_weeks_idx = unique_weeks[-eval_weeks:] if len(unique_weeks) > eval_weeks else unique_weeks
    eval_weekly = weekly[weekly["week_start"].isin(eval_weeks_idx)].copy()
    if eval_weekly.empty:
        raise ValueError("No evaluation weeks remained after filtering")

    numeric_features = [
        "hist_metric_pct",
        "prev_week_avg_payout_pct",
        "prev_week_positive_days",
        "debut_days_since",
    ]
    feature_rows: list[dict[str, object]] = []
    for feature in numeric_features:
        rho, p_value = safe_spearman(eval_weekly[feature], eval_weekly["week_avg_payout_pct"])
        delta = qcut_extreme_delta(eval_weekly, feature, "week_avg_payout_pct")
        feature_rows.append(
            {
                "feature": feature,
                "n": int(delta["n"]),
                "n_bins": int(delta["n_bins"]),
                "spearman_rho": rho,
                "p_value": p_value,
                "d0_mean_pct": float(delta["d0_mean"]),
                "d9_mean_pct": float(delta["d9_mean"]),
                "delta_pp": float(delta["delta_pp"]),
            }
        )
    feature_summary = pd.DataFrame(feature_rows).sort_values(["spearman_rho", "delta_pp"], ascending=[False, False]).reset_index(drop=True)

    lift_tables: list[pd.DataFrame] = []
    for feature in numeric_features:
        lift = threshold_lift_by_date(
            eval_weekly,
            score_col=feature,
            target_col="week_avg_payout_pct",
            date_col="week_start",
            thresholds=thresholds,
            top_ks=top_ks,
        )
        lift.insert(0, "feature", feature)
        lift_tables.append(lift)
    lift_table = pd.concat(lift_tables, ignore_index=True) if lift_tables else pd.DataFrame()

    section_summary = _group_summary(eval_weekly, "section", sort_cols=["avg_week_payout", "n"], head=15)
    segment_summary = _group_summary(eval_weekly, "segment", sort_cols=["avg_week_payout", "n"], head=15)
    debut_summary = _group_summary(eval_weekly, "debut_phase", sort_cols=["avg_week_payout", "n"], head=10)

    baseline = pd.DataFrame(
        [
            {
                "metric": "week_avg_payout_pct",
                "mean_pct": float(eval_weekly["week_avg_payout_pct"].mean()),
                "median_pct": float(eval_weekly["week_avg_payout_pct"].median()),
                "n_rows": int(len(eval_weekly)),
                "n_weeks": int(eval_weekly["week_start"].nunique()),
                "n_machines": int(eval_weekly["machine_number"].nunique()),
            }
        ]
    )

    eval_path = output_dir / "weekly_eval_rows.csv"
    feature_summary_path = output_dir / "weekly_feature_summary.csv"
    lift_path = output_dir / "weekly_lift_table.csv"
    section_path = output_dir / "section_group_summary.csv"
    segment_path = output_dir / "segment_group_summary.csv"
    debut_path = output_dir / "debut_phase_group_summary.csv"
    report_path = output_dir / "report.md"

    eval_weekly.to_csv(eval_path, index=False, encoding="utf-8-sig")
    feature_summary.to_csv(feature_summary_path, index=False, encoding="utf-8-sig")
    lift_table.to_csv(lift_path, index=False, encoding="utf-8-sig")
    section_summary.to_csv(section_path, index=False, encoding="utf-8-sig")
    segment_summary.to_csv(segment_path, index=False, encoding="utf-8-sig")
    debut_summary.to_csv(debut_path, index=False, encoding="utf-8-sig")

    report_lines: list[str] = []
    report_lines.append("# 予測粒度シフト実験: 台×週")
    report_lines.append("")
    report_lines.append("## 固定前提")
    report_lines.append(f"- DB: `{resolve_db_path(db_path)}`")
    report_lines.append(f"- min_games: `{min_games}`")
    report_lines.append(f"- history_days: `{history_days}`")
    report_lines.append(f"- eval_weeks: `{eval_weeks}`")
    report_lines.append(f"- thresholds: `{', '.join(str(v) for v in thresholds)}`")
    report_lines.append(f"- top_k: `{', '.join(str(v) for v in top_ks)}`")
    report_lines.append("")
    report_lines.append("## データ概要")
    report_lines.append(format_markdown_table(baseline))
    report_lines.append("")
    report_lines.append("## 数値特徴量")
    report_lines.append(format_markdown_table(feature_summary))
    report_lines.append("")
    report_lines.append("## Lift テーブル")
    report_lines.append(format_markdown_table(lift_table))
    report_lines.append("")
    report_lines.append("## 固定効果の要約")
    report_lines.append("### section")
    report_lines.append(format_markdown_table(section_summary))
    report_lines.append("")
    report_lines.append("### segment")
    report_lines.append(format_markdown_table(segment_summary))
    report_lines.append("")
    report_lines.append("### debut_phase")
    report_lines.append(format_markdown_table(debut_summary))
    report_lines.append("")
    report_lines.append(f"Outputs written to `{output_dir}`")
    report = "\n".join(report_lines) + "\n"
    report_path.write_text(report, encoding="utf-8")
    return eval_weekly, feature_summary, lift_table, baseline, report


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    top_ks = _parse_int_list(args.top_ks) or DEFAULT_WEEK_TOP_KS
    thresholds = _parse_float_list(args.thresholds) or DEFAULT_WEEK_THRESHOLDS
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    eval_weekly, feature_summary, lift_table, baseline, _ = build_outputs(
        db_path=args.db_path,
        output_dir=output_dir,
        min_games=args.min_games,
        history_days=args.history_days,
        eval_weeks=args.eval_weeks,
        top_ks=top_ks,
        thresholds=thresholds,
    )
    print(f"[OK] weekly eval rows: {len(eval_weekly)}")
    print(f"[OK] baseline rows: {len(baseline)}")
    print(f"[OK] feature summary rows: {len(feature_summary)}")
    print(f"[OK] lift rows: {len(lift_table)}")
    print(f"[OK] report saved: {output_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
