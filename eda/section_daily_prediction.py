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
    DEFAULT_SECTION_EVAL_DAYS,
    DEFAULT_SECTION_THRESHOLDS,
    DEFAULT_SECTION_TOP_KS,
    format_markdown_table,
    load_base_frame,
    qcut_extreme_delta,
    resolve_db_path,
    safe_spearman,
    section_daily_aggregates,
    threshold_lift_by_date,
)

SCRIPT_NAME = "section_daily_prediction"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kamata7 section x day granularity shift analysis")
    parser.add_argument("--db-path", type=Path, default=None, help="SQLite DB path")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR / SCRIPT_NAME)
    parser.add_argument("--min-games", type=int, default=1500)
    parser.add_argument("--history-days", type=int, default=90)
    parser.add_argument("--eval-days", type=int, default=DEFAULT_SECTION_EVAL_DAYS)
    parser.add_argument("--top-ks", type=str, default="1,3,5", help="Comma-separated top-K list")
    parser.add_argument("--thresholds", type=str, default="30,35,40,45", help="Comma-separated section hit thresholds")
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


def build_outputs(
    *,
    db_path: Path | None,
    output_dir: Path,
    min_games: int,
    history_days: int,
    eval_days: int,
    top_ks: tuple[int, ...],
    thresholds: tuple[float, ...],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str]:
    frame = load_base_frame(db_path, min_games=min_games, history_days=history_days)
    daily = section_daily_aggregates(frame, history_days=history_days)
    if daily.empty:
        raise ValueError("No section/day rows were produced")

    daily = daily.copy()
    daily["dd"] = daily["date_dt"].dt.day.astype(int)
    daily["dow"] = daily["date_dt"].dt.dayofweek.astype(int)
    daily["is_event"] = daily["dd"].isin({1, 7, 11, 17, 21, 22, 27, 31})
    daily["section_hit_rate_pct"] = daily["section_hit_rate"] * 100.0
    daily["hist_section_hit_rate_pct"] = daily["hist_section_hit_rate"] * 100.0
    daily["prev_day_section_hot_pct"] = daily["prev_day_section_hot"] * 100.0

    unique_dates = pd.Index(sorted(pd.Timestamp(value) for value in daily["date_dt"].dropna().unique()))
    eval_dates = unique_dates[-eval_days:] if len(unique_dates) > eval_days else unique_dates
    eval_daily = daily[daily["date_dt"].isin(eval_dates)].copy()
    if eval_daily.empty:
        raise ValueError("No evaluation dates remained after filtering")

    feature_cols = [
        "hist_section_hit_rate_pct",
        "dd",
        "dow",
        "is_event",
        "section_debut_ratio",
        "section_avg_hist",
        "prev_day_section_hot_pct",
    ]
    rows: list[dict[str, object]] = []
    for feature in feature_cols:
        rho, p_value = safe_spearman(eval_daily[feature], eval_daily["section_hit_rate_pct"])
        delta = qcut_extreme_delta(eval_daily, feature, "section_hit_rate_pct")
        rows.append(
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
    feature_summary = pd.DataFrame(rows).sort_values(["spearman_rho", "delta_pp"], ascending=[False, False]).reset_index(drop=True)

    lift_tables: list[pd.DataFrame] = []
    for feature in feature_cols:
        lift = threshold_lift_by_date(
            eval_daily,
            score_col=feature,
            target_col="section_hit_rate_pct",
            date_col="date_dt",
            thresholds=thresholds,
            top_ks=top_ks,
        )
        lift.insert(0, "feature", feature)
        lift_tables.append(lift)
    lift_table = pd.concat(lift_tables, ignore_index=True) if lift_tables else pd.DataFrame()

    baseline = pd.DataFrame(
        [
            {
                "metric": "section_hit_rate_pct",
                "mean_pct": float(eval_daily["section_hit_rate_pct"].mean()),
                "median_pct": float(eval_daily["section_hit_rate_pct"].median()),
                "n_rows": int(len(eval_daily)),
                "n_dates": int(eval_daily["date_dt"].nunique()),
                "n_sections": int(eval_daily["section"].nunique()),
            }
        ]
    )

    feature_summary_path = output_dir / "section_feature_summary.csv"
    lift_path = output_dir / "section_lift_table.csv"
    eval_path = output_dir / "section_eval_rows.csv"
    report_path = output_dir / "report.md"

    eval_daily.to_csv(eval_path, index=False, encoding="utf-8-sig")
    feature_summary.to_csv(feature_summary_path, index=False, encoding="utf-8-sig")
    lift_table.to_csv(lift_path, index=False, encoding="utf-8-sig")

    report_lines: list[str] = []
    report_lines.append("# 予測粒度シフト実験: セクション×日")
    report_lines.append("")
    report_lines.append("## 固定前提")
    report_lines.append(f"- DB: `{resolve_db_path(db_path)}`")
    report_lines.append(f"- min_games: `{min_games}`")
    report_lines.append(f"- history_days: `{history_days}`")
    report_lines.append(f"- eval_days: `{eval_days}`")
    report_lines.append(f"- thresholds: `{', '.join(str(v) for v in thresholds)}`")
    report_lines.append(f"- top_k: `{', '.join(str(v) for v in top_ks)}`")
    report_lines.append("")
    report_lines.append("## データ概要")
    report_lines.append(format_markdown_table(baseline))
    report_lines.append("")
    report_lines.append("## 特徴量評価")
    report_lines.append(format_markdown_table(feature_summary))
    report_lines.append("")
    report_lines.append("## Lift テーブル")
    report_lines.append(format_markdown_table(lift_table))
    report_lines.append("")
    report_lines.append(f"Outputs written to `{output_dir}`")
    report = "\n".join(report_lines) + "\n"
    report_path.write_text(report, encoding="utf-8")
    return eval_daily, feature_summary, lift_table, report


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    top_ks = _parse_int_list(args.top_ks) or DEFAULT_SECTION_TOP_KS
    thresholds = _parse_float_list(args.thresholds) or DEFAULT_SECTION_THRESHOLDS
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    eval_daily, feature_summary, lift_table, _ = build_outputs(
        db_path=args.db_path,
        output_dir=output_dir,
        min_games=args.min_games,
        history_days=args.history_days,
        eval_days=args.eval_days,
        top_ks=top_ks,
        thresholds=thresholds,
    )
    print(f"[OK] section eval rows: {len(eval_daily)}")
    print(f"[OK] feature summary rows: {len(feature_summary)}")
    print(f"[OK] lift rows: {len(lift_table)}")
    print(f"[OK] report saved: {output_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
