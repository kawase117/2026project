from __future__ import annotations

import argparse
import sqlite3
import string
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr, wilcoxon

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.experiments.walkforward_scoring.config import PROJECT_ROOT  # noqa: E402
from ml.experiments.walkforward_scoring.scoring_model import build_score_context, classify_seg  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田7.db"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "results" / "window_stability_test"
DEFAULT_WINDOW_DAYS = (60, 90)
DEFAULT_EVAL_DAYS = 30
DEFAULT_MAX_PERIODS = 6
DEFAULT_MIN_GAMES = 1500
DEFAULT_TOP_SECTIONS = 5
DEFAULT_TOP_MACHINES_PER_SECTION = 5
EXCLUDED_MMDD = "0707"
EXCLUDED_MACHINE_NUMBER = 2026


def _format_value(value: object, *, float_digits: int = 3) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.{float_digits}f}"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    return str(value)


def _markdown_table(frame: pd.DataFrame, *, columns: list[str] | None = None, float_digits: int = 3) -> str:
    work = frame.copy()
    if columns is not None:
        work = work.loc[:, columns]
    if work.empty:
        return "No rows."
    headers = [str(col) for col in work.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for _, row in work.iterrows():
        lines.append(
            "| " + " | ".join(_format_value(row[col], float_digits=float_digits) for col in work.columns) + " |"
        )
    return "\n".join(lines)


def _parse_int_list(raw: str) -> tuple[int, ...]:
    values = [part.strip() for part in str(raw).split(",") if part.strip()]
    return tuple(int(value) for value in values)


def _resolve_db_path(db_path: Path | None) -> Path:
    if db_path is not None:
        return Path(db_path)
    return DEFAULT_DB_PATH


def _load_frame(db_path: Path, *, min_games: int) -> pd.DataFrame:
    query = """
        SELECT
            date,
            machine_number,
            machine_name,
            games_normalized,
            diff_coins_normalized
        FROM machine_detailed_results
    """
    with sqlite3.connect(str(db_path)) as conn:
        raw = pd.read_sql_query(query, conn)

    raw["date"] = raw["date"].astype(str)
    raw["date_dt"] = pd.to_datetime(raw["date"], format="%Y%m%d", errors="coerce")
    raw["machine_number"] = pd.to_numeric(raw["machine_number"], errors="coerce")
    raw["games_normalized"] = pd.to_numeric(raw["games_normalized"], errors="coerce")
    raw["diff_coins_normalized"] = pd.to_numeric(raw["diff_coins_normalized"], errors="coerce")
    raw = raw.dropna(
        subset=["date_dt", "machine_number", "machine_name", "games_normalized", "diff_coins_normalized"]
    ).copy()
    raw["machine_number"] = raw["machine_number"].astype(int)
    raw = raw[raw["machine_number"].ne(EXCLUDED_MACHINE_NUMBER)].copy()
    raw = raw[raw["date"].str[4:8].ne(EXCLUDED_MMDD)].copy()
    raw = raw[raw["games_normalized"].ge(int(min_games))].copy()
    if raw.empty:
        raise ValueError("No rows remained after filtering the Kamata7 DB")

    context = build_score_context()
    coords = context.coords.copy()
    coords["machine_number"] = pd.to_numeric(coords["machine_number"], errors="coerce")
    coords = coords.dropna(subset=["machine_number"]).copy()
    coords["machine_number"] = coords["machine_number"].astype(int)
    coords = coords.drop_duplicates(subset=["machine_number"]).reset_index(drop=True)
    keep_cols = [
        "machine_number",
        "floor",
        "section",
        "section_min",
        "section_max",
        "rank_from_min",
        "rank_from_max",
        "section_size",
        "section_size_group",
        "lr",
        "kakuban_old",
        "kakuban_new",
    ]
    coords = coords.loc[:, keep_cols].copy()

    work = raw.merge(coords, on="machine_number", how="inner", validate="m:1")
    if work.empty:
        raise ValueError("No rows remained after joining coordinates")

    work["seg"] = work["machine_name"].map(classify_seg)
    work["hist_threshold"] = np.where(work["seg"].eq("A"), 104.0, 106.0)
    denom = work["games_normalized"] * 3.0
    work["payout_rate"] = ((denom + work["diff_coins_normalized"]) / denom) * 100.0
    work["hit_flag"] = work["payout_rate"].ge(work["hist_threshold"]).astype(int)
    work["win_flag"] = work["diff_coins_normalized"].gt(0).astype(int)
    work = work.sort_values(["date_dt", "section", "machine_number"]).reset_index(drop=True)
    return work


def _build_periods(unique_dates: pd.Index, *, eval_days: int, max_periods: int) -> list[dict[str, object]]:
    dates = [pd.Timestamp(value).normalize() for value in unique_dates]
    dates = sorted(dict.fromkeys(dates))
    if not dates:
        return []

    periods: list[dict[str, object]] = []
    period_idx = 0
    for end_pos in range(len(dates), 0, -eval_days):
        start_pos = max(0, end_pos - eval_days)
        block = dates[start_pos:end_pos]
        if len(block) != eval_days:
            continue
        period_idx += 1
        period_id = string.ascii_uppercase[period_idx - 1] if period_idx <= 26 else f"P{period_idx}"
        periods.append(
            {
                "period_id": period_id,
                "start": pd.Timestamp(block[0]),
                "end": pd.Timestamp(block[-1]),
                "dates": block,
            }
        )
        if len(periods) >= max_periods:
            break
    return periods


def _build_history_scores(train: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    section_scores = (
        train.groupby(["section", "floor", "section_min", "section_max"], as_index=False)
        .agg(
            section_score=("hit_flag", "mean"),
            section_train_n=("date_dt", "nunique"),
            section_train_machines=("machine_number", "nunique"),
        )
        .copy()
    )
    machine_scores = (
        train.groupby(["section", "machine_number", "machine_name"], as_index=False)
        .agg(
            machine_score=("hit_flag", "mean"),
            machine_train_n=("date_dt", "nunique"),
            machine_train_avg_diff=("diff_coins_normalized", "mean"),
            machine_train_win_rate=("win_flag", "mean"),
        )
        .copy()
    )
    return section_scores, machine_scores


def _safe_spearman(x: pd.Series, y: pd.Series) -> float:
    valid = pd.concat([pd.to_numeric(x, errors="coerce"), pd.to_numeric(y, errors="coerce")], axis=1).dropna()
    if len(valid) < 2:
        return float("nan")
    rho, _ = spearmanr(valid.iloc[:, 0], valid.iloc[:, 1])
    return float(rho)


def _evaluate_day(
    frame: pd.DataFrame,
    target_dt: pd.Timestamp,
    *,
    window_days: int,
    top_sections: int,
    top_machines_per_section: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    actual = frame[frame["date_dt"].eq(target_dt)].copy()
    if actual.empty:
        return pd.DataFrame(), pd.DataFrame()

    window_start = target_dt - pd.Timedelta(days=int(window_days))
    train = frame[(frame["date_dt"].lt(target_dt)) & (frame["date_dt"].ge(window_start))].copy()
    if train.empty:
        return pd.DataFrame(), pd.DataFrame()

    section_scores, machine_scores = _build_history_scores(train)
    actual_sections = (
        actual.groupby(["section", "floor", "section_min", "section_max"], as_index=False)
        .agg(
            section_hit_rate=("hit_flag", "mean"),
            section_hit_count=("hit_flag", "sum"),
            section_actual_n=("machine_number", "size"),
            section_avg_diff=("diff_coins_normalized", "mean"),
            section_win_rate=("win_flag", "mean"),
        )
        .copy()
    )

    section_eval = actual_sections.merge(
        section_scores, on=["section", "floor", "section_min", "section_max"], how="left", validate="1:1"
    )
    section_eval["test_date"] = target_dt.strftime("%Y-%m-%d")
    section_eval["window_days"] = int(window_days)
    section_eval["section_rho"] = _safe_spearman(section_eval["section_score"], section_eval["section_hit_rate"])
    section_eval["section_delta_pp"] = (section_eval["section_hit_rate"] - section_eval["section_score"]) * 100.0
    section_eval = section_eval.sort_values(
        ["section_score", "section_min", "section"],
        ascending=[False, True, True],
        na_position="last",
    ).reset_index(drop=True)
    section_eval["section_rank"] = np.arange(1, len(section_eval) + 1)

    selected_sections = section_eval.head(int(top_sections)).copy()
    selected_section_names = selected_sections["section"].astype(str).tolist()

    machine_eval = actual.merge(
        machine_scores, on=["section", "machine_number", "machine_name"], how="left", validate="1:1"
    )
    machine_eval = machine_eval[machine_eval["section"].isin(selected_section_names)].copy()
    if machine_eval.empty:
        return section_eval, pd.DataFrame()

    machine_eval = machine_eval.sort_values(
        ["section", "machine_score", "machine_number"],
        ascending=[True, False, True],
        na_position="last",
    ).copy()
    machine_eval["machine_rank_in_section"] = machine_eval.groupby("section", dropna=False).cumcount() + 1
    machine_eval = machine_eval[machine_eval["machine_rank_in_section"] <= int(top_machines_per_section)].copy()
    machine_eval["test_date"] = target_dt.strftime("%Y-%m-%d")
    machine_eval["window_days"] = int(window_days)
    machine_eval["selected_section_rank"] = machine_eval["section"].map(
        selected_sections.set_index("section")["section_rank"].to_dict()
    )

    machine_eval["machine_hit_rate"] = machine_eval["hit_flag"].astype(float)
    machine_eval["machine_avg_diff"] = machine_eval["diff_coins_normalized"].astype(float)
    machine_eval["machine_win_rate"] = machine_eval["win_flag"].astype(float)
    machine_eval["selected_section_hit_rate"] = machine_eval["section"].map(
        selected_sections.set_index("section")["section_hit_rate"].to_dict()
    )
    machine_eval["selected_section_score"] = machine_eval["section"].map(
        selected_sections.set_index("section")["section_score"].to_dict()
    )

    return section_eval, machine_eval.reset_index(drop=True)


def _aggregate_daily_metrics(day_rows: pd.DataFrame) -> pd.DataFrame:
    if day_rows.empty:
        return pd.DataFrame(
            columns=[
                "period_id",
                "window_days",
                "start",
                "end",
                "n_days",
                "section_rho",
                "section_hit_rate",
                "hit_rate",
                "avg_diff",
                "win_rate",
            ]
        )

    grouped = (
        day_rows.groupby(["period_id", "window_days", "start", "end"], as_index=False)
        .agg(
            n_days=("test_date", "nunique"),
            section_rho=("section_rho", "mean"),
            section_hit_rate=("section_hit_rate", "mean"),
            hit_rate=("hit_rate", "mean"),
            avg_diff=("avg_diff", "mean"),
            win_rate=("win_rate", "mean"),
        )
        .sort_values(["period_id", "window_days"])
        .reset_index(drop=True)
    )
    return grouped


def _build_period_comparison(summary: pd.DataFrame) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame(
            columns=[
                "metric",
                "60d_wins",
                "90d_wins",
                "ties",
                "total_periods",
                "60d_mean",
                "90d_mean",
                "diff",
                "wilcoxon_p",
            ]
        )

    rows: list[dict[str, object]] = []
    for metric in ["section_rho", "section_hit_rate", "hit_rate", "avg_diff", "win_rate"]:
        metric_rows = summary.loc[:, ["period_id", "window_days", metric]].copy()
        pivot = metric_rows.pivot(index="period_id", columns="window_days", values=metric).rename(
            columns={60: "60d", 90: "90d"}
        )
        pivot = pivot.dropna(subset=["60d", "90d"], how="any")
        if pivot.empty:
            rows.append(
                {
                    "metric": metric,
                    "60d_wins": 0,
                    "90d_wins": 0,
                    "ties": 0,
                    "total_periods": 0,
                    "60d_mean": float("nan"),
                    "90d_mean": float("nan"),
                    "diff": float("nan"),
                    "wilcoxon_p": float("nan"),
                }
            )
            continue

        diff = pivot["60d"] - pivot["90d"]
        wins_60 = int((diff > 0).sum())
        wins_90 = int((diff < 0).sum())
        ties = int((diff == 0).sum())
        total = int(len(pivot))
        try:
            if total >= 1 and not np.allclose(diff.to_numpy(dtype=float), 0.0, equal_nan=True):
                _, p_value = wilcoxon(pivot["60d"], pivot["90d"], zero_method="wilcox", alternative="two-sided")
                wilcoxon_p = float(p_value)
            else:
                wilcoxon_p = float("nan")
        except Exception:
            wilcoxon_p = float("nan")
        rows.append(
            {
                "metric": metric,
                "60d_wins": wins_60,
                "90d_wins": wins_90,
                "ties": ties,
                "total_periods": total,
                "60d_mean": float(pivot["60d"].mean()),
                "90d_mean": float(pivot["90d"].mean()),
                "diff": float((pivot["60d"] - pivot["90d"]).mean()),
                "wilcoxon_p": wilcoxon_p,
            }
        )
    return pd.DataFrame(rows)


def _build_report(
    *,
    db_path: Path,
    min_games: int,
    window_days: tuple[int, ...],
    eval_days: int,
    max_periods: int,
    top_sections: int,
    top_machines_per_section: int,
    daily_rows: pd.DataFrame,
    period_summary: pd.DataFrame,
    comparison: pd.DataFrame,
) -> str:
    lines: list[str] = []
    lines.append("# Window Stability Test")
    lines.append("")
    lines.append("## Settings")
    lines.append(f"- DB: `{db_path}`")
    lines.append(f"- min_games: `{min_games}`")
    lines.append(f"- window_days: `{', '.join(str(value) for value in window_days)}`")
    lines.append(f"- eval_days: `{eval_days}`")
    lines.append(f"- max_periods: `{max_periods}`")
    lines.append(f"- top_sections: `{top_sections}`")
    lines.append(f"- top_machines_per_section: `{top_machines_per_section}`")
    lines.append(f"- filters: `machine_number != {EXCLUDED_MACHINE_NUMBER}`, `date[4:8] != {EXCLUDED_MMDD}`")
    lines.append("")
    lines.append("## Daily Rows")
    lines.append(
        _markdown_table(
            daily_rows.loc[
                :,
                [
                    "period_id",
                    "test_date",
                    "window_days",
                    "section_rho",
                    "section_hit_rate",
                    "hit_rate",
                    "avg_diff",
                    "win_rate",
                ],
            ].head(40),
            float_digits=4,
        )
    )
    lines.append("")
    lines.append("## Period Summary")
    lines.append(
        _markdown_table(
            period_summary.loc[
                :,
                [
                    "period_id",
                    "window_days",
                    "start",
                    "end",
                    "n_days",
                    "section_rho",
                    "section_hit_rate",
                    "hit_rate",
                    "avg_diff",
                    "win_rate",
                ],
            ],
            float_digits=4,
        )
    )
    lines.append("")
    lines.append("## 60d vs 90d")
    lines.append(
        _markdown_table(
            comparison.loc[
                :,
                [
                    "metric",
                    "60d_wins",
                    "90d_wins",
                    "ties",
                    "total_periods",
                    "60d_mean",
                    "90d_mean",
                    "diff",
                    "wilcoxon_p",
                ],
            ],
            float_digits=4,
        )
    )
    lines.append("")
    lines.append("## Interpretation")
    if not comparison.empty:
        for _, row in comparison.iterrows():
            metric = str(row["metric"])
            wins_60 = int(row["60d_wins"])
            wins_90 = int(row["90d_wins"])
            total = int(row["total_periods"])
            if total == 0:
                lines.append(f"- {metric}: no paired periods.")
                continue
            winner = "60d" if wins_60 > wins_90 else "90d" if wins_90 > wins_60 else "tie"
            lines.append(
                f"- {metric}: {winner} wins {wins_60}-{wins_90} over {total} paired periods "
                f"(wilcoxon_p={_format_value(row['wilcoxon_p'], float_digits=4)})"
            )
    lines.append("")
    return "\n".join(lines)


def build_outputs(
    *,
    db_path: Path | None,
    output_dir: Path,
    min_games: int,
    window_days: tuple[int, ...],
    eval_days: int,
    max_periods: int,
    top_sections: int,
    top_machines_per_section: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str]:
    resolved_db_path = _resolve_db_path(db_path)
    frame = _load_frame(resolved_db_path, min_games=min_games)

    unique_dates = pd.Index(sorted(pd.Timestamp(value).normalize() for value in frame["date_dt"].dropna().unique()))
    periods = _build_periods(unique_dates, eval_days=eval_days, max_periods=max_periods)
    if not periods:
        raise ValueError("No evaluation periods could be constructed from the DB dates")

    daily_rows: list[pd.DataFrame] = []
    detail_rows: list[pd.DataFrame] = []
    required_history = max(window_days)
    min_date = pd.Timestamp(frame["date_dt"].min()).normalize()

    for period in periods:
        period_start = pd.Timestamp(period["start"]).normalize()
        if min_date > (period_start - pd.Timedelta(days=required_history)):
            continue
        for target_dt in period["dates"]:
            target_dt = pd.Timestamp(target_dt).normalize()
            for window in window_days:
                section_eval, machine_eval = _evaluate_day(
                    frame,
                    target_dt,
                    window_days=int(window),
                    top_sections=int(top_sections),
                    top_machines_per_section=int(top_machines_per_section),
                )
                if section_eval.empty or machine_eval.empty:
                    continue
                selected_sections = section_eval.head(int(top_sections)).copy()
                daily_rows.append(
                    pd.DataFrame(
                        [
                            {
                                "period_id": period["period_id"],
                                "start": pd.Timestamp(period["start"]).strftime("%Y-%m-%d"),
                                "end": pd.Timestamp(period["end"]).strftime("%Y-%m-%d"),
                                "test_date": target_dt.strftime("%Y-%m-%d"),
                                "window_days": int(window),
                                "section_rho": float(selected_sections["section_rho"].iloc[0])
                                if "section_rho" in selected_sections.columns and not selected_sections.empty
                                else float("nan"),
                                "section_hit_rate": float(selected_sections["section_hit_rate"].mean())
                                if not selected_sections.empty
                                else float("nan"),
                                "hit_rate": float(machine_eval["machine_hit_rate"].mean())
                                if not machine_eval.empty
                                else float("nan"),
                                "avg_diff": float(machine_eval["machine_avg_diff"].mean())
                                if not machine_eval.empty
                                else float("nan"),
                                "win_rate": float(machine_eval["machine_win_rate"].mean())
                                if not machine_eval.empty
                                else float("nan"),
                                "selected_sections": int(len(selected_sections)),
                                "selected_machines": int(len(machine_eval)),
                            }
                        ]
                    )
                )
                detail_rows.append(
                    machine_eval.assign(
                        period_id=period["period_id"],
                        section_rho=float(selected_sections["section_rho"].iloc[0])
                        if not selected_sections.empty
                        else float("nan"),
                        selected_section_count=int(len(selected_sections)),
                    )
                )

    daily_df = pd.concat(daily_rows, ignore_index=True) if daily_rows else pd.DataFrame()
    detail_df = pd.concat(detail_rows, ignore_index=True) if detail_rows else pd.DataFrame()
    if daily_df.empty:
        raise ValueError("No daily evaluation rows were produced")

    period_summary = _aggregate_daily_metrics(daily_df)
    comparison = _build_period_comparison(period_summary)

    output_dir.mkdir(parents=True, exist_ok=True)
    daily_path = output_dir / "window_stability_daily.csv"
    period_path = output_dir / "window_stability_period_summary.csv"
    detail_path = output_dir / "window_stability_selected_machines.csv"
    report_path = output_dir / "report.md"

    daily_df.to_csv(daily_path, index=False, encoding="utf-8-sig")
    period_summary.to_csv(period_path, index=False, encoding="utf-8-sig")
    detail_df.to_csv(detail_path, index=False, encoding="utf-8-sig")
    report = _build_report(
        db_path=resolved_db_path,
        min_games=min_games,
        window_days=window_days,
        eval_days=eval_days,
        max_periods=max_periods,
        top_sections=top_sections,
        top_machines_per_section=top_machines_per_section,
        daily_rows=daily_df,
        period_summary=period_summary,
        comparison=comparison,
    )
    report_path.write_text(report, encoding="utf-8")
    return daily_df, period_summary, comparison, report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kamata7 window stability test")
    parser.add_argument("--db-path", type=Path, default=None, help="SQLite DB path")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Output directory")
    parser.add_argument("--min-games", type=int, default=DEFAULT_MIN_GAMES, help="Minimum normalized games filter")
    parser.add_argument("--window-days", type=str, default="60,90", help="Comma-separated history window days")
    parser.add_argument("--eval-days", type=int, default=DEFAULT_EVAL_DAYS, help="Days per eval period")
    parser.add_argument("--max-periods", type=int, default=DEFAULT_MAX_PERIODS, help="Maximum number of periods")
    parser.add_argument("--top-sections", type=int, default=DEFAULT_TOP_SECTIONS, help="Sections selected per day")
    parser.add_argument(
        "--top-machines-per-section",
        type=int,
        default=DEFAULT_TOP_MACHINES_PER_SECTION,
        help="Machines selected per section",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    window_days = _parse_int_list(args.window_days) or DEFAULT_WINDOW_DAYS
    try:
        daily_df, period_summary, comparison, _ = build_outputs(
            db_path=args.db_path,
            output_dir=Path(args.output_dir),
            min_games=int(args.min_games),
            window_days=window_days,
            eval_days=int(args.eval_days),
            max_periods=int(args.max_periods),
            top_sections=int(args.top_sections),
            top_machines_per_section=int(args.top_machines_per_section),
        )
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    print(f"[OK] daily rows: {len(daily_df)}")
    print(f"[OK] period rows: {len(period_summary)}")
    print(f"[OK] comparison rows: {len(comparison)}")
    print(f"[OK] report saved: {Path(args.output_dir) / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
