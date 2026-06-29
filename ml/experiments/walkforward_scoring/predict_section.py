from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from .config import DEFAULT_DB_PATH, RESULTS_DIR
from .scoring_model import build_score_context, classify_seg
from .walk_forward_engine import load_machine_data

EVENT_DDS = frozenset({1, 7, 11, 17, 21, 22, 27, 31})
DEFAULT_WINDOW_DAYS = 90
DEFAULT_TOP_SECTIONS = 10
DEFAULT_TOP_MACHINES_PER_SECTION = 5
DEFAULT_EVAL_DAYS = 60
DEFAULT_EVAL_TOP_KS = (1, 3, 5, 10)


@dataclass(frozen=True)
class PredictionBundle:
    target_date: pd.Timestamp
    roster_date: pd.Timestamp
    actual_date_used: bool
    roster: pd.DataFrame
    section_summary: pd.DataFrame
    selected_machines: pd.DataFrame
    global_top_machines: pd.DataFrame


def _format_value(value: object, *, float_digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.{float_digits}f}"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    return str(value)


def _markdown_table(frame: pd.DataFrame, *, columns: list[str] | None = None, float_digits: int = 1) -> str:
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


def _parse_float_list(raw: str) -> tuple[float, ...]:
    values = [part.strip() for part in str(raw).split(",") if part.strip()]
    return tuple(float(value) for value in values)


def _resolve_date(date_arg: str) -> pd.Timestamp:
    try:
        return pd.to_datetime(date_arg, format="%Y%m%d", errors="raise")
    except Exception as exc:  # pragma: no cover - handled in CLI path
        raise ValueError(f"invalid --date value: {date_arg}") from exc


def _prepare_frame(db_path: Path, *, min_games: int) -> pd.DataFrame:
    raw = load_machine_data(db_path).copy()
    raw["date"] = raw["date"].astype(str)
    raw["date_dt"] = pd.to_datetime(raw["date"], format="%Y%m%d", errors="coerce")
    raw["machine_number"] = pd.to_numeric(raw["machine_number"], errors="coerce")
    raw["games_normalized"] = pd.to_numeric(raw["games_normalized"], errors="coerce")
    raw["diff_coins_normalized"] = pd.to_numeric(raw["diff_coins_normalized"], errors="coerce")
    raw = raw.dropna(subset=["date_dt", "machine_number", "machine_name", "games_normalized", "diff_coins_normalized"]).copy()
    raw["machine_number"] = raw["machine_number"].astype(int)
    raw = raw[raw["machine_number"].ne(2026)].copy()
    raw = raw[raw["date"].str[4:8].ne("0707")].copy()
    raw = raw[raw["games_normalized"].ge(min_games)].copy()
    if raw.empty:
        raise ValueError("No rows remained after the Kamata7 filters")

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
    coords["section"] = coords["section"].astype(str)
    coords["floor"] = coords["floor"].astype(str)

    work = raw.merge(coords, on="machine_number", how="inner", validate="m:1")
    if work.empty:
        raise ValueError("No rows remained after joining coordinates")

    work["seg"] = work["machine_name"].map(classify_seg)
    work["hist_threshold"] = np.where(work["seg"].eq("A"), 104.0, 106.0)
    denom = work["games_normalized"] * 3
    work["payout_rate"] = ((denom + work["diff_coins_normalized"]) / denom) * 100
    work["hit_flag"] = work["payout_rate"].ge(work["hist_threshold"])
    work = work.sort_values(["machine_number", "date_dt"]).reset_index(drop=True)
    return work


def _select_roster(frame: pd.DataFrame, target_dt: pd.Timestamp) -> tuple[pd.DataFrame, pd.Timestamp, bool]:
    actual_roster = frame[frame["date_dt"].eq(target_dt)].copy()
    if not actual_roster.empty:
        return actual_roster.reset_index(drop=True), target_dt, True

    candidates = frame[frame["date_dt"].lt(target_dt)]
    if candidates.empty:
        raise ValueError(f"No roster available on or before {target_dt.strftime('%Y-%m-%d')}")
    roster_date = pd.Timestamp(candidates["date_dt"].max())
    roster = frame[frame["date_dt"].eq(roster_date)].copy()
    if roster.empty:
        raise ValueError(f"Roster fallback failed for {roster_date.strftime('%Y-%m-%d')}")
    return roster.reset_index(drop=True), roster_date, False


def _compute_hist_metrics(frame: pd.DataFrame, target_dt: pd.Timestamp, window_days: int) -> pd.DataFrame:
    window_start = target_dt - pd.Timedelta(days=window_days)
    history = frame[(frame["date_dt"].lt(target_dt)) & (frame["date_dt"].ge(window_start))].copy()
    if history.empty:
        return pd.DataFrame(columns=["machine_number", "hist_metric", "hist_n"])
    hist = (
        history.groupby("machine_number", as_index=False)
        .agg(hist_metric=("hit_flag", "mean"), hist_n=("hit_flag", "size"))
        .copy()
    )
    return hist


def _rank_sections(roster: pd.DataFrame, hist: pd.DataFrame) -> pd.DataFrame:
    work = roster.merge(hist, on="machine_number", how="left", validate="m:1")
    section_summary = (
        work.groupby(["section", "floor", "section_min", "section_max", "section_size"], dropna=False)
        .agg(
            section_score=("hist_metric", "mean"),
            section_hist_coverage=("hist_metric", lambda s: float(s.notna().mean())),
            n_machines=("machine_number", "nunique"),
        )
        .reset_index()
    )
    section_summary["section_score_pct"] = section_summary["section_score"] * 100.0
    section_summary["section_hist_coverage_pct"] = section_summary["section_hist_coverage"] * 100.0
    section_summary = section_summary.sort_values(
        ["section_score", "section_min", "section"],
        ascending=[False, True, True],
        na_position="last",
    ).reset_index(drop=True)
    section_summary["section_rank"] = range(1, len(section_summary) + 1)
    section_summary["section_score"] = section_summary["section_score"].fillna(np.nan)
    return section_summary, work


def _top_machines_by_section(work: pd.DataFrame, section_names: list[str], top_n: int) -> pd.DataFrame:
    selected = work[work["section"].isin(section_names)].copy()
    if selected.empty:
        return pd.DataFrame()
    selected = selected.sort_values(["section", "hist_metric", "machine_number"], ascending=[True, False, True])
    selected["rank_in_section"] = selected.groupby("section", dropna=False).cumcount() + 1
    selected = selected[selected["rank_in_section"] <= top_n].copy()
    selected["hist_metric_pct"] = selected["hist_metric"] * 100.0
    selected["kakuban"] = selected["kakuban_new"]
    return selected.reset_index(drop=True)


def _top_global_machines(work: pd.DataFrame, top_n: int) -> pd.DataFrame:
    selected = work.sort_values(["hist_metric", "machine_number"], ascending=[False, True]).head(top_n).copy()
    selected["rank_global_hist"] = range(1, len(selected) + 1)
    selected["hist_metric_pct"] = selected["hist_metric"] * 100.0
    selected["kakuban"] = selected["kakuban_new"]
    return selected.reset_index(drop=True)


def _build_prediction_bundle(
    frame: pd.DataFrame,
    *,
    target_dt: pd.Timestamp,
    window_days: int,
    top_sections: int,
    top_machines_per_section: int,
) -> PredictionBundle:
    roster, roster_date, actual_date_used = _select_roster(frame, target_dt)
    hist = _compute_hist_metrics(frame, target_dt, window_days)
    section_summary, work = _rank_sections(roster, hist)
    if section_summary.empty:
        raise ValueError("No section rows could be scored")

    section_summary["selected"] = False
    section_summary.loc[section_summary.index < min(top_sections, len(section_summary)), "selected"] = True
    section_summary["section_score_pct"] = section_summary["section_score_pct"].fillna(0.0)

    detail_sections = section_summary.head(top_sections)["section"].astype(str).tolist()
    selected_machines = _top_machines_by_section(work, detail_sections, top_machines_per_section)
    global_top_machines = _top_global_machines(work, len(selected_machines))
    return PredictionBundle(
        target_date=target_dt,
        roster_date=roster_date,
        actual_date_used=actual_date_used,
        roster=work,
        section_summary=section_summary,
        selected_machines=selected_machines,
        global_top_machines=global_top_machines,
    )


def _section_report_table(section_summary: pd.DataFrame) -> pd.DataFrame:
    out = section_summary.copy()
    out["section_score_pct"] = out["section_score_pct"].round(1)
    out["section_hist_coverage_pct"] = out["section_hist_coverage_pct"].round(1)
    return out.loc[:, ["section_rank", "section", "section_score_pct", "section_hist_coverage_pct", "n_machines"]]


def _machine_report_table(machines: pd.DataFrame) -> pd.DataFrame:
    if machines.empty:
        return machines
    out = machines.copy()
    out["hist_metric_pct"] = out["hist_metric_pct"].round(1)
    cols = [
        "section",
        "rank_in_section" if "rank_in_section" in out.columns else "rank_global_hist",
        "machine_number",
        "machine_name",
        "hist_metric_pct",
        "kakuban",
    ]
    return out.loc[:, cols]


def _build_prediction_report(bundle: PredictionBundle, *, top_sections: int, top_machines_per_section: int) -> str:
    section_table = _section_report_table(bundle.section_summary)
    detail_sections = bundle.section_summary.head(top_sections)
    lines: list[str] = []
    lines.append(f"# Section Prediction: {bundle.target_date.strftime('%Y-%m-%d')}")
    lines.append("")
    lines.append("## Settings")
    lines.append(f"- Roster date: `{bundle.roster_date.strftime('%Y-%m-%d')}`")
    lines.append(f"- Roster source: `{ 'actual' if bundle.actual_date_used else 'latest fallback' }`")
    lines.append(f"- Window days: `{DEFAULT_WINDOW_DAYS}`")
    lines.append(f"- Top sections: `{top_sections}`")
    lines.append(f"- Top machines per section: `{top_machines_per_section}`")
    lines.append("")
    lines.append("## Section Ranking")
    lines.append(_markdown_table(section_table))
    lines.append("")
    lines.append("## Top Sections")
    for _, section_row in detail_sections.iterrows():
        section_name = str(section_row["section"])
        section_score_pct = float(section_row["section_score_pct"])
        section_rank = int(section_row["section_rank"])
        section_machines = bundle.selected_machines[bundle.selected_machines["section"].eq(section_name)].copy()
        lines.append(
            f"### Section {section_name} "
            f"(section_score={section_score_pct:.1f}, rank={section_rank}/{len(bundle.section_summary)})"
        )
        lines.append(_markdown_table(_machine_report_table(section_machines)))
        lines.append("")
    lines.append("## Global Hist Top")
    lines.append(_markdown_table(_machine_report_table(bundle.global_top_machines)))
    lines.append("")
    return "\n".join(lines) + "\n"


def _section_spearman(section_rows: pd.DataFrame) -> tuple[float, float]:
    valid = section_rows.dropna(subset=["section_score", "section_hit_rate"])
    if len(valid) < 2:
        return float("nan"), float("nan")
    rho, p_value = spearmanr(valid["section_score"], valid["section_hit_rate"])
    return float(rho), float(p_value)


def _evaluate_day(
    frame: pd.DataFrame,
    target_dt: pd.Timestamp,
    *,
    window_days: int,
    top_sections_list: tuple[int, ...],
    top_machines_per_section: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    actual = frame[frame["date_dt"].eq(target_dt)].copy()
    if actual.empty:
        return pd.DataFrame(), pd.DataFrame()

    bundle = _build_prediction_bundle(
        frame,
        target_dt=target_dt,
        window_days=window_days,
        top_sections=max(top_sections_list),
        top_machines_per_section=top_machines_per_section,
    )
    section_actual = (
        actual.groupby("section", as_index=False)
        .agg(section_hit_rate=("hit_flag", "mean"), section_actual_n=("machine_number", "size"))
        .copy()
    )
    section_eval = bundle.section_summary.merge(section_actual, on="section", how="left", validate="1:1")
    section_eval["test_date"] = target_dt.strftime("%Y-%m-%d")
    section_eval["section_hit_rate_pct"] = section_eval["section_hit_rate"] * 100.0
    section_eval["section_delta_pp"] = (section_eval["section_hit_rate"] - section_eval["section_score"]) * 100.0
    section_rho, section_p = _section_spearman(section_eval)

    summary_rows: list[dict[str, object]] = []
    for top_k in top_sections_list:
        top_sections = section_eval.sort_values(
            ["section_score", "section_min", "section"],
            ascending=[False, True, True],
            na_position="last",
        ).head(top_k)
        baseline_section_rate = float(section_eval["section_hit_rate"].mean())
        top_section_rate = float(top_sections["section_hit_rate"].mean()) if not top_sections.empty else float("nan")
        section_lift = float(top_section_rate / baseline_section_rate) if baseline_section_rate > 0 else float("nan")

        selected_machines = bundle.selected_machines[bundle.selected_machines["section"].isin(top_sections["section"])].copy()
        selected_actual = actual[actual["machine_number"].isin(selected_machines["machine_number"])].copy()
        global_selected = bundle.global_top_machines.head(len(selected_machines)).copy()
        global_actual = actual[actual["machine_number"].isin(global_selected["machine_number"])].copy()

        machine_baseline_rate = float(actual["hit_flag"].mean())
        selected_rate = float(selected_actual["hit_flag"].mean()) if not selected_actual.empty else float("nan")
        selected_lift = float(selected_rate / machine_baseline_rate) if machine_baseline_rate > 0 else float("nan")
        global_rate = float(global_actual["hit_flag"].mean()) if not global_actual.empty else float("nan")
        global_lift = float(global_rate / machine_baseline_rate) if machine_baseline_rate > 0 else float("nan")

        summary_rows.append(
            {
                "test_date": target_dt.strftime("%Y-%m-%d"),
                "top_k": top_k,
                "section_rho_day": section_rho,
                "section_p_day": section_p,
                "section_baseline_rate": baseline_section_rate,
                "section_top_rate": top_section_rate,
                "section_lift": section_lift,
                "selected_machine_count": int(len(selected_machines)),
                "machine_baseline_rate": machine_baseline_rate,
                "selected_machine_rate": selected_rate,
                "selected_machine_lift": selected_lift,
                "global_hist_rate": global_rate,
                "global_hist_lift": global_lift,
                "roster_date": bundle.roster_date.strftime("%Y-%m-%d"),
                "actual_date_used": bundle.actual_date_used,
            }
        )

    return section_eval, pd.DataFrame(summary_rows)


def _evaluate_walkforward(
    frame: pd.DataFrame,
    *,
    eval_days: int,
    window_days: int,
    top_sections_list: tuple[int, ...],
    top_machines_per_section: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    unique_dates = pd.Index(sorted(pd.Timestamp(value) for value in frame["date_dt"].dropna().unique()))
    eval_dates = unique_dates[-eval_days:] if len(unique_dates) > eval_days else unique_dates

    section_rows: list[pd.DataFrame] = []
    summary_rows: list[pd.DataFrame] = []
    machine_rows: list[pd.DataFrame] = []

    for target_dt in eval_dates:
        section_eval, summary_eval = _evaluate_day(
            frame,
            target_dt,
            window_days=window_days,
            top_sections_list=top_sections_list,
            top_machines_per_section=top_machines_per_section,
        )
        if section_eval.empty or summary_eval.empty:
            continue
        section_rows.append(section_eval)
        summary_rows.append(summary_eval)
        roster = frame[frame["date_dt"].eq(target_dt)].copy()
        roster = roster if not roster.empty else frame[frame["date_dt"].eq(summary_eval["roster_date"].iloc[0])].copy()
        bundle = _build_prediction_bundle(
            frame,
            target_dt=target_dt,
            window_days=window_days,
            top_sections=max(top_sections_list),
            top_machines_per_section=top_machines_per_section,
        )
        machine_eval = bundle.selected_machines.drop(columns=["hit_flag"], errors="ignore").merge(
            roster.loc[:, ["machine_number", "hit_flag"]].rename(columns={"hit_flag": "actual_hit_flag"}),
            on="machine_number",
            how="left",
            validate="m:1",
        )
        machine_eval["test_date"] = target_dt.strftime("%Y-%m-%d")
        machine_eval["section_hit_rate_pct"] = np.nan
        machine_eval["global_hist_flag"] = machine_eval["machine_number"].isin(bundle.global_top_machines["machine_number"])
        machine_rows.append(machine_eval)

    section_eval_all = pd.concat(section_rows, ignore_index=True) if section_rows else pd.DataFrame()
    summary_all = pd.concat(summary_rows, ignore_index=True) if summary_rows else pd.DataFrame()
    machine_all = pd.concat(machine_rows, ignore_index=True) if machine_rows else pd.DataFrame()
    return section_eval_all, summary_all, machine_all


def _build_eval_report(section_eval_all: pd.DataFrame, summary_all: pd.DataFrame, machine_all: pd.DataFrame) -> str:
    section_rho, section_p = _section_spearman(section_eval_all) if not section_eval_all.empty else (float("nan"), float("nan"))
    machine_eval = machine_all.dropna(subset=["actual_hit_flag"]).copy() if not machine_all.empty else pd.DataFrame()
    machine_rho, machine_p = (float("nan"), float("nan"))
    if not machine_eval.empty and machine_eval["hist_metric"].notna().sum() >= 2:
        rho, p_value = spearmanr(machine_eval["hist_metric"], machine_eval["actual_hit_flag"].astype(float))
        machine_rho, machine_p = float(rho), float(p_value)

    summary = (
        summary_all.groupby("top_k", as_index=False)
        .agg(
            section_baseline_rate=("section_baseline_rate", "mean"),
            section_top_rate=("section_top_rate", "mean"),
            section_lift=("section_lift", "mean"),
            machine_baseline_rate=("machine_baseline_rate", "mean"),
            selected_machine_rate=("selected_machine_rate", "mean"),
            selected_machine_lift=("selected_machine_lift", "mean"),
            global_hist_rate=("global_hist_rate", "mean"),
            global_hist_lift=("global_hist_lift", "mean"),
            selected_machine_count=("selected_machine_count", "mean"),
        )
        .sort_values("top_k")
        .reset_index(drop=True)
    ) if not summary_all.empty else pd.DataFrame()

    summary["section_baseline_rate_pct"] = summary.get("section_baseline_rate", pd.Series(dtype="float64")) * 100.0
    summary["section_top_rate_pct"] = summary.get("section_top_rate", pd.Series(dtype="float64")) * 100.0
    summary["machine_baseline_rate_pct"] = summary.get("machine_baseline_rate", pd.Series(dtype="float64")) * 100.0
    summary["selected_machine_rate_pct"] = summary.get("selected_machine_rate", pd.Series(dtype="float64")) * 100.0
    summary["global_hist_rate_pct"] = summary.get("global_hist_rate", pd.Series(dtype="float64")) * 100.0

    lines: list[str] = []
    lines.append("# Section Prediction Evaluation")
    lines.append("")
    lines.append("## Pooled Correlation")
    lines.append(f"- Section score vs section hit rate: rho={section_rho:.3f}, p={section_p:.4f}")
    lines.append(f"- Machine hist_metric vs hit flag: rho={machine_rho:.3f}, p={machine_p:.4f}")
    lines.append("")
    lines.append("## Summary by Top-K Sections")
    if summary.empty:
        lines.append("No evaluation rows.")
    else:
        display = summary.loc[
            :,
            [
                "top_k",
                "section_baseline_rate_pct",
                "section_top_rate_pct",
                "section_lift",
                "selected_machine_count",
                "machine_baseline_rate_pct",
                "selected_machine_rate_pct",
                "selected_machine_lift",
                "global_hist_rate_pct",
                "global_hist_lift",
            ],
        ].copy()
        for col in ["section_baseline_rate_pct", "section_top_rate_pct", "machine_baseline_rate_pct", "selected_machine_rate_pct", "global_hist_rate_pct"]:
            display[col] = display[col].round(1)
        for col in ["section_lift", "selected_machine_lift", "global_hist_lift", "selected_machine_count"]:
            display[col] = display[col].round(3)
        lines.append(_markdown_table(display))
    lines.append("")
    lines.append("## Evaluation Files")
    lines.append(f"- Section rows: {len(section_eval_all)}")
    lines.append(f"- Summary rows: {len(summary_all)}")
    lines.append(f"- Machine rows: {len(machine_all)}")
    lines.append("")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kamata7 section x day two-stage recommendation pipeline")
    parser.add_argument("--date", help="Target date in YYYYMMDD format")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help="SQLite DB path")
    parser.add_argument("--output-dir", type=Path, default=RESULTS_DIR, help="Output directory")
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS, help="History window in days")
    parser.add_argument("--top-sections", type=int, default=DEFAULT_TOP_SECTIONS, help="Number of sections to detail")
    parser.add_argument(
        "--top-machines-per-section",
        type=int,
        default=DEFAULT_TOP_MACHINES_PER_SECTION,
        help="Machines to list per section",
    )
    parser.add_argument(
        "--eval",
        action="store_true",
        help="Run walk-forward evaluation over the latest eval-days dates",
    )
    parser.add_argument("--eval-days", type=int, default=DEFAULT_EVAL_DAYS, help="Evaluation window in days")
    parser.add_argument(
        "--eval-top-ks",
        type=str,
        default="1,3,5,10",
        help="Comma-separated top-K section values for eval summary",
    )
    parser.add_argument("--min-games", type=int, default=1500, help="Minimum normalized games filter")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)

    try:
        frame = _prepare_frame(args.db_path, min_games=args.min_games)
        args.output_dir.mkdir(parents=True, exist_ok=True)

        if args.eval:
            eval_top_ks = _parse_int_list(args.eval_top_ks) or DEFAULT_EVAL_TOP_KS
            section_eval_all, summary_all, machine_all = _evaluate_walkforward(
                frame,
                eval_days=args.eval_days,
                window_days=args.window_days,
                top_sections_list=eval_top_ks,
                top_machines_per_section=args.top_machines_per_section,
            )
            summary_path = args.output_dir / "predict_section_eval_summary.csv"
            section_path = args.output_dir / "predict_section_eval_sections.csv"
            machine_path = args.output_dir / "predict_section_eval_machines.csv"
            report_path = args.output_dir / "evaluation_report.md"
            section_eval_all.to_csv(section_path, index=False, encoding="utf-8-sig")
            summary_all.to_csv(summary_path, index=False, encoding="utf-8-sig")
            machine_all.to_csv(machine_path, index=False, encoding="utf-8-sig")
            report_path.write_text(_build_eval_report(section_eval_all, summary_all, machine_all), encoding="utf-8")
            print(f"[OK] eval sections: {len(section_eval_all)}")
            print(f"[OK] eval summary: {len(summary_all)}")
            print(f"[OK] eval machines: {len(machine_all)}")
            print(f"[OK] report saved: {report_path}")
            return 0

        if not args.date:
            raise ValueError("--date is required unless --eval is set")
        target_dt = _resolve_date(args.date)
        bundle = _build_prediction_bundle(
            frame,
            target_dt=target_dt,
            window_days=args.window_days,
            top_sections=args.top_sections,
            top_machines_per_section=args.top_machines_per_section,
        )
        date_str = target_dt.strftime("%Y%m%d")
        section_csv = args.output_dir / f"predict_section_{date_str}.csv"
        machine_csv = args.output_dir / f"predict_section_{date_str}_machines.csv"
        report_path = args.output_dir / f"predict_section_{date_str}.md"
        section_table = _section_report_table(bundle.section_summary)
        section_table.to_csv(section_csv, index=False, encoding="utf-8-sig")
        bundle.selected_machines.to_csv(machine_csv, index=False, encoding="utf-8-sig")
        report_path.write_text(
            _build_prediction_report(bundle, top_sections=args.top_sections, top_machines_per_section=args.top_machines_per_section),
            encoding="utf-8",
        )
        print(f"[OK] sections: {len(section_table)}")
        print(f"[OK] selected machines: {len(bundle.selected_machines)}")
        print(f"[OK] report saved: {report_path}")
        return 0
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
