from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import mstats, spearmanr

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.experiments.walkforward_scoring.config import DEFAULT_DB_PATH, PROJECT_ROOT
from ml.experiments.walkforward_scoring.scoring_model import load_coords_bundle

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "eda" / "results" / "target_metric_comparison"
DEFAULT_MIN_GAMES = 1500
DEFAULT_HISTORY_DAYS = 90
DEFAULT_EVAL_DAYS = 60
DEFAULT_TOP_K_SECTIONS = 5
DEFAULT_TOP_N_MACHINES = 5
DEFAULT_TOP_STRATEGIES = 3
DEFAULT_METRICS = (
    "hit_104_rate",
    "avg_diff",
    "avg_payout",
    "median_diff",
    "median_payout",
    "winsorized_diff",
    "positive_rate",
)
HIT_THRESHOLD = 104.0
MIN_HISTORY_ROWS = 5
MIN_SECTION_MACHINES = 3


@dataclass(frozen=True)
class ExplorationOutputs:
    metric_summary: pd.DataFrame
    section_summary: pd.DataFrame
    report_exploration: str


@dataclass(frozen=True)
class PipelineOutputs:
    summary: pd.DataFrame
    report_pipeline: str


def _format_value(value: object, *, float_digits: int = 3) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.{float_digits}f}"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    return str(value)


def _format_markdown_table(frame: pd.DataFrame, *, columns: list[str] | None = None, float_digits: int = 3) -> str:
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
        lines.append("| " + " | ".join(_format_value(row[col], float_digits=float_digits) for col in work.columns) + " |")
    return "\n".join(lines)


def _parse_int_list(raw: str) -> tuple[int, ...]:
    values = [part.strip() for part in str(raw).split(",") if part.strip()]
    return tuple(int(value) for value in values)


def _resolve_db_path(db_path: str | Path | None) -> Path:
    if db_path is not None:
        return Path(db_path)
    if DEFAULT_DB_PATH.exists() and DEFAULT_DB_PATH.stat().st_size > 0:
        return DEFAULT_DB_PATH
    candidates = sorted(
        (PROJECT_ROOT / "db").glob("*蒲田7*.db"),
        key=lambda path: path.stat().st_size if path.exists() else 0,
        reverse=True,
    )
    if candidates:
        return candidates[0]
    return DEFAULT_DB_PATH


def _safe_spearman(x: pd.Series, y: pd.Series) -> tuple[float, float]:
    valid = pd.DataFrame({"x": pd.to_numeric(x, errors="coerce"), "y": pd.to_numeric(y, errors="coerce")}).dropna()
    if len(valid) < 3:
        return float("nan"), float("nan")
    if valid["x"].nunique(dropna=True) < 2 or valid["y"].nunique(dropna=True) < 2:
        return float("nan"), float("nan")
    rho, p_value = spearmanr(valid["x"], valid["y"])
    if pd.isna(rho) or pd.isna(p_value):
        return float("nan"), float("nan")
    return float(rho), float(p_value)


def _winsorized_mean(values: pd.Series) -> float:
    series = pd.to_numeric(values, errors="coerce").dropna().astype(float)
    if series.empty:
        return float("nan")
    winsorized = mstats.winsorize(series.to_numpy(), limits=[0.05, 0.05])
    return float(np.asarray(winsorized, dtype=float).mean())


def _qcut_extreme_delta(frame: pd.DataFrame, feature_col: str, target_col: str) -> dict[str, object]:
    valid = frame[[feature_col, target_col]].dropna().copy()
    if valid.empty:
        return {
            "metric": feature_col,
            "n": 0,
            "n_bins": 0,
            "d0_mean": float("nan"),
            "d9_mean": float("nan"),
            "delta_pp": float("nan"),
        }
    if valid[feature_col].nunique(dropna=True) < 3:
        return {
            "metric": feature_col,
            "n": int(len(valid)),
            "n_bins": 0,
            "d0_mean": float("nan"),
            "d9_mean": float("nan"),
            "delta_pp": float("nan"),
        }
    try:
        bins = pd.qcut(valid[feature_col], 10, labels=False, duplicates="drop")
    except Exception:
        return {
            "metric": feature_col,
            "n": int(len(valid)),
            "n_bins": 0,
            "d0_mean": float("nan"),
            "d9_mean": float("nan"),
            "delta_pp": float("nan"),
        }
    if bins.isna().all():
        return {
            "metric": feature_col,
            "n": int(len(valid)),
            "n_bins": 0,
            "d0_mean": float("nan"),
            "d9_mean": float("nan"),
            "delta_pp": float("nan"),
        }
    valid = valid.assign(_bin=bins)
    grouped = valid.groupby("_bin", dropna=False)[target_col].mean().sort_index()
    if len(grouped) < 3:
        return {
            "metric": feature_col,
            "n": int(len(valid)),
            "n_bins": int(len(grouped)),
            "d0_mean": float("nan"),
            "d9_mean": float("nan"),
            "delta_pp": float("nan"),
        }
    first = float(grouped.iloc[0])
    last = float(grouped.iloc[-1])
    return {
        "metric": feature_col,
        "n": int(len(valid)),
        "n_bins": int(len(grouped)),
        "d0_mean": first,
        "d9_mean": last,
        "delta_pp": last - first,
    }


def _ensure_required_columns(frame: pd.DataFrame, *, min_games: int) -> pd.DataFrame:
    required = {"date_dt", "machine_number", "machine_name", "games_normalized", "diff_coins_normalized"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"missing required columns: {', '.join(sorted(missing))}")
    work = frame.copy()
    work["date_dt"] = pd.to_datetime(work["date_dt"], errors="coerce")
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work = work.dropna(subset=["date_dt", "machine_number", "machine_name", "games_normalized", "diff_coins_normalized"]).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    if "date" not in work.columns:
        work["date"] = work["date_dt"].dt.strftime("%Y%m%d")
    work["date"] = work["date"].astype(str)
    if "payout_rate" not in work.columns:
        denom = work["games_normalized"] * 3
        work["payout_rate"] = ((denom + work["diff_coins_normalized"]) / denom) * 100
    work["payout_rate"] = pd.to_numeric(work["payout_rate"], errors="coerce")
    if "hit104" not in work.columns:
        work["hit104"] = work["payout_rate"].ge(HIT_THRESHOLD)
    else:
        work["hit104"] = work["hit104"].astype(bool)
    if "section" not in work.columns or "floor" not in work.columns:
        coords = load_coords_bundle().copy()
        coords["machine_number"] = pd.to_numeric(coords["machine_number"], errors="coerce")
        coords = coords.dropna(subset=["machine_number"]).copy()
        coords["machine_number"] = coords["machine_number"].astype(int)
        work = work.merge(coords, on="machine_number", how="left", validate="m:1")
    if "section" not in work.columns or "floor" not in work.columns:
        raise ValueError("section and floor columns are required")
    work["section"] = work["section"].astype(str)
    work["floor"] = work["floor"].astype(str)
    work = work[work["machine_number"].ne(2026)].copy()
    work = work[work["date"].str[4:8].ne("0707")].copy()
    work = work[work["games_normalized"].ge(min_games)].copy()
    return work.sort_values(["date_dt", "machine_number"]).reset_index(drop=True)


def _compute_history_metrics(history: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for machine_number, group in history.groupby("machine_number", sort=False):
        if len(group) < MIN_HISTORY_ROWS:
            rows.append(
                {
                    "machine_number": machine_number,
                    "hit_104_rate": float("nan"),
                    "avg_diff": float("nan"),
                    "avg_payout": float("nan"),
                    "median_diff": float("nan"),
                    "median_payout": float("nan"),
                    "winsorized_diff": float("nan"),
                    "positive_rate": float("nan"),
                    "hist_n": int(len(group)),
                }
            )
            continue
        denom = group["games_normalized"] * 3
        payout = ((denom + group["diff_coins_normalized"]) / denom) * 100
        rows.append(
            {
                "machine_number": machine_number,
                "hit_104_rate": float(group["hit104"].mean()),
                "avg_diff": float(group["diff_coins_normalized"].mean()),
                "avg_payout": float(payout.mean()),
                "median_diff": float(group["diff_coins_normalized"].median()),
                "median_payout": float(payout.median()),
                "winsorized_diff": _winsorized_mean(group["diff_coins_normalized"]),
                "positive_rate": float(group["diff_coins_normalized"].gt(0).mean()),
                "hist_n": int(len(group)),
            }
        )
    return pd.DataFrame(rows)


def _evaluate_date(frame: pd.DataFrame, target_dt: pd.Timestamp, *, history_days: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    window_start = target_dt - pd.Timedelta(days=history_days)
    history = frame[(frame["date_dt"].lt(target_dt)) & (frame["date_dt"].ge(window_start))].copy()
    actual = frame[frame["date_dt"].eq(target_dt)].copy()
    if history.empty or actual.empty:
        return pd.DataFrame(), pd.DataFrame()
    hist_metrics = _compute_history_metrics(history)
    actual = actual.merge(hist_metrics, on="machine_number", how="left", validate="m:1")
    actual["section_machine_count"] = actual.groupby("section")["machine_number"].transform("nunique")
    section_actual = (
        actual.groupby(["date_dt", "date", "floor", "section"], dropna=False)
        .agg(
            section_hit_rate=("hit104", "mean"),
            section_machine_count=("machine_number", "nunique"),
            section_avg_hit_104_rate=("hit_104_rate", "mean"),
            section_avg_avg_diff=("avg_diff", "mean"),
            section_avg_avg_payout=("avg_payout", "mean"),
            section_avg_median_diff=("median_diff", "mean"),
            section_avg_median_payout=("median_payout", "mean"),
            section_avg_winsorized_diff=("winsorized_diff", "mean"),
            section_avg_positive_rate=("positive_rate", "mean"),
        )
        .reset_index()
    )
    section_actual = section_actual[section_actual["section_machine_count"].ge(MIN_SECTION_MACHINES)].copy()
    if section_actual.empty:
        return actual, section_actual
    actual["section_avg_hit_104_rate"] = actual.groupby("section")["hit_104_rate"].transform("mean")
    actual["section_avg_avg_diff"] = actual.groupby("section")["avg_diff"].transform("mean")
    actual["section_avg_avg_payout"] = actual.groupby("section")["avg_payout"].transform("mean")
    actual["section_avg_median_diff"] = actual.groupby("section")["median_diff"].transform("mean")
    actual["section_avg_median_payout"] = actual.groupby("section")["median_payout"].transform("mean")
    actual["section_avg_winsorized_diff"] = actual.groupby("section")["winsorized_diff"].transform("mean")
    actual["section_avg_positive_rate"] = actual.groupby("section")["positive_rate"].transform("mean")
    return actual, section_actual


def _build_long_tables(frame: pd.DataFrame, *, eval_days: int, history_days: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    unique_dates = pd.Index(sorted(pd.Timestamp(value) for value in frame["date_dt"].dropna().unique()))
    eval_dates = unique_dates[-eval_days:] if len(unique_dates) > eval_days else unique_dates
    machine_rows: list[pd.DataFrame] = []
    section_rows: list[pd.DataFrame] = []
    for target_dt in eval_dates:
        machine_day, section_day = _evaluate_date(frame, target_dt, history_days=history_days)
        if machine_day.empty or section_day.empty:
            continue
        machine_rows.append(machine_day)
        section_rows.append(section_day)
    machine_table = pd.concat(machine_rows, ignore_index=True) if machine_rows else pd.DataFrame()
    section_table = pd.concat(section_rows, ignore_index=True) if section_rows else pd.DataFrame()
    return machine_table, section_table


def _metric_summary_from_table(table: pd.DataFrame, *, metric_names: tuple[str, ...], target_col: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for metric in metric_names:
        rho, p_value = _safe_spearman(table[metric], table[target_col]) if not table.empty else (float("nan"), float("nan"))
        delta = _qcut_extreme_delta(table, metric, target_col) if not table.empty else {
            "n": 0,
            "n_bins": 0,
            "d0_mean": float("nan"),
            "d9_mean": float("nan"),
            "delta_pp": float("nan"),
        }
        rows.append(
            {
                "metric": metric,
                "spearman_rho": rho,
                "p_value": p_value,
                "d0_hit104" if target_col == "hit104" else "d0_section_hit_rate": float(delta["d0_mean"]),
                "d9_hit104" if target_col == "hit104" else "d9_section_hit_rate": float(delta["d9_mean"]),
                "delta_pp": float(delta["delta_pp"]),
            }
        )
    return pd.DataFrame(rows).sort_values(["spearman_rho", "delta_pp"], ascending=[False, False]).reset_index(drop=True)


def _build_strategy_rows(section_table: pd.DataFrame, machine_table: pd.DataFrame, *, top_k_sections: int, top_n_machines: int, strategy_metrics: list[str]) -> pd.DataFrame:
    baseline_metric = "hit_104_rate"
    strategies = [baseline_metric, *[metric for metric in strategy_metrics if metric != baseline_metric]]
    rows: list[dict[str, object]] = []
    for metric in strategies:
        section_metric = f"section_avg_{metric}"
        if section_metric not in section_table.columns or metric not in machine_table.columns:
            continue
        selected_dates = sorted(pd.Timestamp(value) for value in machine_table["date_dt"].dropna().unique())
        selected_hits: list[float] = []
        selected_n = 0
        for target_dt in selected_dates:
            day_sections = section_table[section_table["date_dt"].eq(target_dt)].copy()
            day_machines = machine_table[machine_table["date_dt"].eq(target_dt)].copy()
            day_sections = day_sections[day_sections[section_metric].notna()].sort_values([section_metric, "section"], ascending=[False, True])
            top_sections = day_sections.head(top_k_sections)["section"].astype(str).tolist()
            if not top_sections:
                continue
            day_selected = day_machines[day_machines["section"].isin(top_sections)].copy()
            day_selected = day_selected[day_selected[metric].notna()].sort_values(["section", metric, "machine_number"], ascending=[True, False, True])
            day_selected = day_selected.groupby("section", dropna=False).head(top_n_machines).copy()
            if day_selected.empty:
                continue
            selected_hits.extend(day_selected["hit104"].astype(float).tolist())
            selected_n += int(len(day_selected))
        hit_rate = float(np.mean(selected_hits)) if selected_hits else float("nan")
        rows.append(
            {
                "strategy": f"section_avg_{metric} × {metric}",
                "top_k_sec": int(top_k_sections),
                "top_n_machine": int(top_n_machines),
                "total_n": int(selected_n),
                "hit_104_rate": hit_rate,
                "baseline": float("nan"),
                "lift": float("nan"),
            }
        )
    return pd.DataFrame(rows)


def build_outputs_from_frame(
    frame: pd.DataFrame,
    *,
    db_path: Path | None = None,
    min_games: int = DEFAULT_MIN_GAMES,
    eval_days: int = DEFAULT_EVAL_DAYS,
    history_days: int = DEFAULT_HISTORY_DAYS,
    top_k_sections: int = DEFAULT_TOP_K_SECTIONS,
    top_n_machines: int = DEFAULT_TOP_N_MACHINES,
    top_strategies: int = DEFAULT_TOP_STRATEGIES,
) -> tuple[ExplorationOutputs, PipelineOutputs]:
    work = _ensure_required_columns(frame, min_games=min_games)
    machine_table, section_table = _build_long_tables(work, eval_days=eval_days, history_days=history_days)
    metric_summary = _metric_summary_from_table(machine_table, metric_names=DEFAULT_METRICS, target_col="hit104")
    section_summary = _metric_summary_from_table(
        section_table,
        metric_names=tuple(f"section_avg_{metric}" for metric in DEFAULT_METRICS),
        target_col="section_hit_rate",
    )
    top_metrics = metric_summary.head(top_strategies)["metric"].tolist()
    pipeline_summary = _build_strategy_rows(
        section_table,
        machine_table,
        top_k_sections=top_k_sections,
        top_n_machines=top_n_machines,
        strategy_metrics=top_metrics,
    )
    if not pipeline_summary.empty:
        baseline_row = pipeline_summary[pipeline_summary["strategy"].eq("section_avg_hit_104_rate × hit_104_rate")].head(1)
        if not baseline_row.empty and pd.notna(baseline_row.iloc[0]["hit_104_rate"]):
            baseline_value = float(baseline_row.iloc[0]["hit_104_rate"])
            pipeline_summary["baseline"] = baseline_value
            pipeline_summary["lift"] = pipeline_summary["hit_104_rate"] / baseline_value if baseline_value > 0 else float("nan")
    exploration = ExplorationOutputs(
        metric_summary=metric_summary,
        section_summary=section_summary,
        report_exploration=_build_exploration_report(
            db_path if db_path is not None else Path("<in-memory>"),
            machine_table,
            section_table,
            metric_summary,
            section_summary,
            min_games,
            eval_days,
            history_days,
        ),
    )
    pipeline = PipelineOutputs(
        summary=pipeline_summary.reset_index(drop=True),
        report_pipeline=_build_pipeline_report(work, pipeline_summary, top_k_sections, top_n_machines, top_metrics),
    )
    return exploration, pipeline


def _build_exploration_report(
    db_path: Path,
    machine_table: pd.DataFrame,
    section_table: pd.DataFrame,
    metric_summary: pd.DataFrame,
    section_summary: pd.DataFrame,
    min_games: int,
    eval_days: int,
    history_days: int,
) -> str:
    lines: list[str] = []
    lines.append("# Part 1: Exploration")
    lines.append("")
    lines.append("## Fixed Conditions")
    lines.append(f"- DB: `{db_path}`")
    lines.append(f"- min_games: `{min_games}`")
    lines.append(f"- history_days: `{history_days}`")
    lines.append(f"- eval_days: `{eval_days}`")
    lines.append(f"- eval_rows: `{len(machine_table)}`")
    lines.append(f"- section_rows: `{len(section_table)}`")
    lines.append("")
    lines.append("## Machine Metrics")
    lines.append(_format_markdown_table(metric_summary))
    lines.append("")
    lines.append("## Section Metrics")
    lines.append(_format_markdown_table(section_summary))
    lines.append("")
    lines.append("## Baseline")
    if not metric_summary.empty and "hit_104_rate" in metric_summary["metric"].values:
        baseline_row = metric_summary[metric_summary["metric"].eq("hit_104_rate")].head(1)
        lines.append(_format_markdown_table(baseline_row))
    if not section_summary.empty and "section_avg_hit_104_rate" in section_summary["metric"].values:
        baseline_row = section_summary[section_summary["metric"].eq("section_avg_hit_104_rate")].head(1)
        lines.append(_format_markdown_table(baseline_row))
    lines.append("")
    lines.append("Outputs written to `eda/results/target_metric_comparison`")
    return "\n".join(lines) + "\n"


def _build_pipeline_report(
    work: pd.DataFrame,
    pipeline_summary: pd.DataFrame,
    top_k_sections: int,
    top_n_machines: int,
    top_metrics: list[str],
) -> str:
    lines: list[str] = []
    lines.append("# Part 2: Pipeline")
    lines.append("")
    lines.append("## Fixed Conditions")
    lines.append(f"- top_k_sections: `{top_k_sections}`")
    lines.append(f"- top_n_machines: `{top_n_machines}`")
    lines.append(f"- chosen_metrics: `{', '.join(top_metrics)}`")
    lines.append("")
    lines.append("## Strategy Comparison")
    lines.append(_format_markdown_table(pipeline_summary))
    lines.append("")
    lines.append("Outputs written to `eda/results/target_metric_comparison`")
    return "\n".join(lines) + "\n"


def _load_frame_from_db(db_path: Path, *, min_games: int) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        raw = pd.read_sql_query(
            """
            SELECT
                date,
                machine_number,
                machine_name,
                games_normalized,
                diff_coins_normalized
            FROM machine_detailed_results
            """,
            conn,
        )
    if raw.empty:
        raise ValueError(f"machine_detailed_results returned no rows in {db_path}")
    work = raw.copy()
    work["date_dt"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work = work.dropna(subset=["date_dt", "machine_number", "machine_name", "games_normalized", "diff_coins_normalized"]).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    if "payout_rate" not in work.columns:
        denom = work["games_normalized"] * 3
        work["payout_rate"] = ((denom + work["diff_coins_normalized"]) / denom) * 100
    work["hit104"] = work["payout_rate"].ge(HIT_THRESHOLD)
    work = work[work["machine_number"].ne(2026)].copy()
    work = work[work["date"].astype(str).str[4:8].ne("0707")].copy()
    work = work[work["games_normalized"].ge(min_games)].copy()
    coords = load_coords_bundle().copy()
    coords["machine_number"] = pd.to_numeric(coords["machine_number"], errors="coerce")
    coords = coords.dropna(subset=["machine_number"]).copy()
    coords["machine_number"] = coords["machine_number"].astype(int)
    work = work.merge(coords, on="machine_number", how="inner", validate="m:1")
    return work.sort_values(["date_dt", "machine_number"]).reset_index(drop=True)


def build_outputs(
    *,
    db_path: Path | None,
    output_dir: Path,
    min_games: int = DEFAULT_MIN_GAMES,
    history_days: int = DEFAULT_HISTORY_DAYS,
    eval_days: int = DEFAULT_EVAL_DAYS,
    top_k_sections: int = DEFAULT_TOP_K_SECTIONS,
    top_n_machines: int = DEFAULT_TOP_N_MACHINES,
    top_strategies: int = DEFAULT_TOP_STRATEGIES,
) -> tuple[ExplorationOutputs, PipelineOutputs]:
    work = _load_frame_from_db(_resolve_db_path(db_path), min_games=min_games)
    return build_outputs_from_frame(
        work,
        db_path=_resolve_db_path(db_path),
        min_games=min_games,
        eval_days=eval_days,
        history_days=history_days,
        top_k_sections=top_k_sections,
        top_n_machines=top_n_machines,
        top_strategies=top_strategies,
    )


def _write_outputs(output_dir: Path, exploration: ExplorationOutputs, pipeline: PipelineOutputs) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    exploration.metric_summary.to_csv(output_dir / "metric_summary.csv", index=False, encoding="utf-8-sig")
    exploration.section_summary.to_csv(output_dir / "section_summary.csv", index=False, encoding="utf-8-sig")
    pipeline.summary.to_csv(output_dir / "pipeline_summary.csv", index=False, encoding="utf-8-sig")
    (output_dir / "report_exploration.md").write_text(exploration.report_exploration, encoding="utf-8")
    (output_dir / "report_pipeline.md").write_text(pipeline.report_pipeline, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Target metric comparison for Kamata7")
    parser.add_argument("--db-path", type=Path, default=None, help="SQLite DB path")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--min-games", type=int, default=DEFAULT_MIN_GAMES)
    parser.add_argument("--history-days", type=int, default=DEFAULT_HISTORY_DAYS)
    parser.add_argument("--eval-days", type=int, default=DEFAULT_EVAL_DAYS)
    parser.add_argument("--top-k-sections", type=int, default=DEFAULT_TOP_K_SECTIONS)
    parser.add_argument("--top-n-machines", type=int, default=DEFAULT_TOP_N_MACHINES)
    parser.add_argument("--top-strategies", type=int, default=DEFAULT_TOP_STRATEGIES)
    args = parser.parse_args(argv)

    try:
        exploration, pipeline = build_outputs(
            db_path=args.db_path,
            output_dir=args.output_dir,
            min_games=args.min_games,
            history_days=args.history_days,
            eval_days=args.eval_days,
            top_k_sections=args.top_k_sections,
            top_n_machines=args.top_n_machines,
            top_strategies=args.top_strategies,
        )
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1

    _write_outputs(args.output_dir, exploration, pipeline)
    print(f"[OK] exploration rows: {len(exploration.metric_summary)}")
    print(f"[OK] section rows: {len(exploration.section_summary)}")
    print(f"[OK] pipeline rows: {len(pipeline.summary)}")
    print(f"[OK] report saved: {args.output_dir / 'report_exploration.md'}")
    print(f"[OK] report saved: {args.output_dir / 'report_pipeline.md'}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
