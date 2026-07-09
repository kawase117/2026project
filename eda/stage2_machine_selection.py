from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.experiments.walkforward_scoring.config import DEFAULT_DB_PATH
from ml.experiments.walkforward_scoring.scoring_model import _debut_phase_label, build_score_context, classify_seg
from ml.experiments.walkforward_scoring.walk_forward_engine import load_machine_data

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "results" / "stage2_machine_selection"
DEFAULT_WINDOW_DAYS = 60
DEFAULT_EVAL_DAYS = 60
DEFAULT_MIN_GAMES = 1500
DEFAULT_TOP_SECTIONS = 5
DEFAULT_TOP_MACHINES_PER_SECTION = 5
DEFAULT_WEIGHT = 0.20
FEATURE_COLUMNS = (
    "kakuban_raw",
    "kakuban_group",
    "kakuban_edge",
    "debut_days",
    "debut_phase",
    "trail_7d_hit",
    "trail_14d_hit",
    "trail_diff_7d",
    "momentum",
)
STRATEGY_SCORE_COLUMNS = {
    "kakuban_weighted": "kakuban_score",
    "debut_weighted": "debut_score",
    "trail_weighted": "trail_7d_score",
    "momentum_weighted": "momentum_score",
}
FEATURE_SCORE_COLUMN_MAP = {
    "kakuban_raw": "kakuban_score_rank",
    "kakuban_group": "kakuban_score_rank",
    "kakuban_edge": "kakuban_score_rank",
    "debut_days": "debut_score_rank",
    "debut_phase": "debut_score_rank",
    "trail_7d_hit": "trail_score_rank",
    "trail_14d_hit": "trail_score_rank",
    "trail_diff_7d": "trail_score_rank",
    "momentum": "momentum_score_rank",
}
ORDINAL_KAKUBAN_GROUP = {
    "K1": 1,
    "K2": 2,
    "K3-4": 3,
    "K5-9": 4,
    "K10-14": 5,
    "K15+": 6,
}
ORDINAL_DEBUT_PHASE = {
    "1-14日": 1,
    "15-60日": 2,
    "61-180日": 3,
    "181日+": 4,
    "pre_existing": 5,
    "unknown": 6,
}


@dataclass(frozen=True)
class DayBundle:
    target_date: pd.Timestamp
    roster_date: pd.Timestamp
    section_rows: pd.DataFrame
    candidate_rows: pd.DataFrame
    selected_sections: list[str]
    section_summary: pd.DataFrame


def _format_value(value: object, *, float_digits: int = 3) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.{float_digits}f}"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    return str(value)


def _render_table(frame: pd.DataFrame, *, columns: list[str] | None = None, float_digits: int = 3) -> str:
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


def _safe_qcut(series: pd.Series, q: int) -> pd.Series:
    work = pd.to_numeric(series, errors="coerce")
    out = pd.Series(pd.NA, index=work.index, dtype="Int64")
    valid = work.dropna()
    if valid.empty:
        return out
    if valid.nunique() == 1:
        out.loc[valid.index] = 1
        return out
    try:
        bins = pd.qcut(valid.rank(method="first"), q=min(int(q), int(valid.nunique())), labels=False, duplicates="drop")
    except ValueError:
        ranked = valid.rank(method="first")
        bins = pd.cut(ranked, bins=min(int(q), int(valid.nunique())), labels=False, duplicates="drop")
    out.loc[valid.index] = pd.Series(bins, index=valid.index).astype("Int64") + 1
    return out


def _kakuban_edge_score(kakuban: object, section_size: object) -> float:
    if pd.isna(kakuban) or pd.isna(section_size):
        return float("nan")
    size = int(section_size)
    value = int(kakuban)
    if size <= 1:
        return 1.0
    distance = min(value - 1, size - value)
    max_distance = max(1.0, (size - 1) / 2.0)
    score = 1.0 - (float(distance) / float(max_distance))
    return float(np.clip(score, 0.0, 1.0))


def _debut_phase_score(days_since_debut: object, pre_existing: bool) -> float:
    if pre_existing:
        return 0.0
    if pd.isna(days_since_debut):
        return 0.0
    days = max(0, int(days_since_debut))
    return float(np.clip(1.0 - (days / 180.0), 0.0, 1.0))


def _percent_rank(series: pd.Series, *, ascending: bool = True) -> pd.Series:
    ranked = pd.to_numeric(series, errors="coerce").rank(method="average", pct=True, ascending=ascending)
    return ranked.fillna(0.0)


def _load_frame(db_path: Path, *, min_games: int) -> pd.DataFrame:
    raw = load_machine_data(db_path).copy()
    raw["date"] = raw["date"].astype(str)
    raw["date_dt"] = pd.to_datetime(raw["date"], format="%Y%m%d", errors="coerce")
    raw["machine_number"] = pd.to_numeric(raw["machine_number"], errors="coerce")
    raw["games_normalized"] = pd.to_numeric(raw["games_normalized"], errors="coerce")
    raw["diff_coins_normalized"] = pd.to_numeric(raw["diff_coins_normalized"], errors="coerce")
    raw = raw.dropna(
        subset=["date_dt", "machine_number", "machine_name", "games_normalized", "diff_coins_normalized"]
    ).copy()
    raw["machine_number"] = raw["machine_number"].astype(int)
    raw = raw[raw["machine_number"].ne(2026)].copy()
    raw = raw[raw["date"].str[4:8].ne("0707")].copy()
    raw = raw[raw["games_normalized"].ge(int(min_games))].copy()
    if raw.empty:
        raise ValueError("No rows remained after applying the Kamata7 filters")

    context = build_score_context()
    coords = context.coords.copy()
    coords["machine_number"] = pd.to_numeric(coords["machine_number"], errors="coerce")
    coords = coords.dropna(subset=["machine_number"]).copy()
    coords["machine_number"] = coords["machine_number"].astype(int)
    coords = coords.drop_duplicates(subset=["machine_number"]).reset_index(drop=True)
    coords = coords.loc[
        :,
        [
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
        ],
    ].copy()

    work = raw.merge(coords, on="machine_number", how="inner", validate="m:1")
    if work.empty:
        raise ValueError("No rows remained after joining coordinates")

    work["seg"] = work["machine_name"].map(classify_seg)
    denom = work["games_normalized"] * 3
    work["payout_rate"] = ((denom + work["diff_coins_normalized"]) / denom) * 100
    work["hit_104"] = work["payout_rate"].ge(104.0)
    work["kakuban_raw"] = work["kakuban_new"].astype("Int64")
    work["kakuban_group_label"] = (
        work["kakuban_raw"]
        .map(
            lambda value: (
                ""
                if pd.isna(value)
                else next(
                    label
                    for label, upper in (
                        ("K1", 1),
                        ("K2", 2),
                        ("K3-4", 4),
                        ("K5-9", 9),
                        ("K10-14", 14),
                        ("K15+", math.inf),
                    )
                    if int(value) <= upper
                )
            )
        )
        .astype("string")
    )
    work["kakuban_group"] = work["kakuban_group_label"].map(ORDINAL_KAKUBAN_GROUP).astype("Int64")
    work["kakuban_edge"] = (work["kakuban_raw"].eq(1) | work["kakuban_raw"].eq(work["section_size"])).astype("Int64")
    work = work.sort_values(["date_dt", "section", "machine_number"]).reset_index(drop=True)
    return work


def _section_summary(actual: pd.DataFrame, machine_hist: pd.DataFrame) -> pd.DataFrame:
    work = actual.merge(machine_hist, on="machine_number", how="left", validate="m:1")
    summary = (
        work.groupby(["section", "floor", "section_min", "section_max", "section_size"], dropna=False)
        .agg(
            section_score=("hist_metric", "mean"),
            section_hist_coverage=("hist_metric", lambda s: float(s.notna().mean())),
            n_machines=("machine_number", "nunique"),
        )
        .reset_index()
    )
    summary["section_score_pct"] = summary["section_score"] * 100.0
    summary["section_hist_coverage_pct"] = summary["section_hist_coverage"] * 100.0
    summary = summary.sort_values(
        ["section_score", "section_min", "section"],
        ascending=[False, True, True],
        na_position="last",
    ).reset_index(drop=True)
    summary["section_rank"] = range(1, len(summary) + 1)
    return summary


def _machine_history_metrics(history: pd.DataFrame) -> pd.DataFrame:
    if history.empty:
        return pd.DataFrame(columns=["machine_number", "hist_metric", "hist_n", "hist_diff"])
    return (
        history.groupby("machine_number", as_index=False)
        .agg(
            hist_metric=("hit_104", "mean"),
            hist_n=("hit_104", "size"),
            hist_diff=("diff_coins_normalized", "mean"),
        )
        .copy()
    )


def _trailing_metrics(history: pd.DataFrame, *, target_dt: pd.Timestamp, days: int) -> pd.DataFrame:
    window_start = target_dt - pd.Timedelta(days=days)
    sub = history[(history["date_dt"].lt(target_dt)) & (history["date_dt"].ge(window_start))].copy()
    if sub.empty:
        return pd.DataFrame(columns=["machine_number", f"trail_{days}d_hit", f"trail_{days}d_diff"])
    return (
        sub.groupby("machine_number", as_index=False)
        .agg(
            **{
                f"trail_{days}d_hit": ("hit_104", "mean"),
                f"trail_{days}d_diff": ("diff_coins_normalized", "mean"),
            }
        )
        .copy()
    )


def _build_day_bundle(
    frame: pd.DataFrame,
    *,
    target_dt: pd.Timestamp,
    window_days: int,
    top_sections: int,
    top_machines_per_section: int,
) -> DayBundle | None:
    actual = frame[frame["date_dt"].eq(target_dt)].copy()
    if actual.empty:
        return None
    window_start = target_dt - pd.Timedelta(days=window_days)
    history = frame[(frame["date_dt"].lt(target_dt)) & (frame["date_dt"].ge(window_start))].copy()
    if history.empty:
        return None

    machine_hist = _machine_history_metrics(history)
    section_summary = _section_summary(actual, machine_hist)
    if section_summary.empty:
        return None

    section_summary = section_summary[section_summary["n_machines"].ge(5)].copy()
    if section_summary.empty:
        return None

    selected_sections: list[str] = []
    for section in section_summary["section"].astype(str).tolist():
        if section not in selected_sections:
            selected_sections.append(section)
        if len(selected_sections) >= int(top_sections):
            break

    if not selected_sections:
        return None

    debut_lookup = frame.loc[frame["date_dt"].lt(target_dt)].groupby("machine_number")["date_dt"].min()
    window_first = history["date_dt"].min().normalize()
    trail_7 = _trailing_metrics(history, target_dt=target_dt, days=7)
    trail_14 = _trailing_metrics(history, target_dt=target_dt, days=14)

    candidate = actual[actual["section"].astype(str).isin(selected_sections)].copy()
    if candidate.empty:
        return None

    candidate = candidate.merge(machine_hist, on="machine_number", how="left", validate="m:1")
    candidate = candidate.merge(trail_7, on="machine_number", how="left", validate="m:1")
    candidate = candidate.merge(trail_14, on="machine_number", how="left", validate="m:1")
    candidate["trail_diff_7d"] = candidate["trail_7d_diff"]

    debut_date = pd.to_datetime(candidate["machine_number"].map(debut_lookup), errors="coerce")
    candidate["debut_date"] = debut_date
    candidate["debut_days"] = (target_dt.normalize() - debut_date).dt.days
    candidate["pre_existing"] = debut_date.notna() & debut_date.le(window_first)
    candidate["debut_phase_label"] = [
        _debut_phase_label(days, pre_existing)
        for days, pre_existing in zip(candidate["debut_days"], candidate["pre_existing"], strict=False)
    ]
    candidate["debut_phase"] = candidate["debut_phase_label"].map(ORDINAL_DEBUT_PHASE).astype("Int64")
    candidate["debut_score"] = [
        _debut_phase_score(days, bool(pre_existing))
        for days, pre_existing in zip(candidate["debut_days"], candidate["pre_existing"], strict=False)
    ]

    candidate["kakuban_score"] = candidate.apply(
        lambda row: _kakuban_edge_score(row["kakuban_raw"], row["section_size"]),
        axis=1,
    )
    candidate["trail_7d_score"] = candidate["trail_7d_hit"].fillna(0.0)
    candidate["trail_14d_score"] = candidate["trail_14d_hit"].fillna(0.0)
    candidate["momentum"] = candidate["trail_7d_hit"] - candidate["hist_metric"]
    candidate["momentum_score"] = _percent_rank(candidate["momentum"], ascending=True)

    candidate["kakuban_raw_rank_score"] = (
        candidate.groupby("section", dropna=False)["kakuban_score"]
        .transform(lambda s: s.rank(pct=True, method="average", ascending=False))
        .fillna(0.0)
    )
    candidate["debut_rank_score"] = (
        candidate.groupby("section", dropna=False)["debut_score"]
        .transform(lambda s: s.rank(pct=True, method="average", ascending=False))
        .fillna(0.0)
    )
    candidate["trail_rank_score"] = (
        candidate.groupby("section", dropna=False)["trail_7d_score"]
        .transform(lambda s: s.rank(pct=True, method="average", ascending=False))
        .fillna(0.0)
    )
    candidate["momentum_rank_score"] = (
        candidate.groupby("section", dropna=False)["momentum_score"]
        .transform(lambda s: s.rank(pct=True, method="average", ascending=False))
        .fillna(0.0)
    )

    candidate["target_date"] = target_dt
    candidate["section_rank"] = candidate["section"].map(section_summary.set_index("section")["section_rank"].to_dict())
    candidate["section_score"] = candidate["section"].map(
        section_summary.set_index("section")["section_score"].to_dict()
    )
    candidate["section_hist_coverage"] = candidate["section"].map(
        section_summary.set_index("section")["section_hist_coverage"].to_dict()
    )
    candidate["section_selected"] = candidate["section"].isin(selected_sections)
    candidate["hist_metric"] = candidate["hist_metric"].fillna(0.0)
    candidate["hist_n"] = candidate["hist_n"].fillna(0).astype(int)
    candidate["hist_diff"] = candidate["hist_diff"].fillna(0.0)
    candidate["section"] = candidate["section"].astype(str)

    selected_section_rows = section_summary[section_summary["section"].isin(selected_sections)].copy()
    selected_section_rows["target_date"] = target_dt
    selected_section_rows["roster_date"] = target_dt

    return DayBundle(
        target_date=target_dt,
        roster_date=target_dt,
        section_rows=selected_section_rows,
        candidate_rows=candidate.reset_index(drop=True),
        selected_sections=selected_sections,
        section_summary=section_summary.reset_index(drop=True),
    )


def _evaluation_dates(frame: pd.DataFrame, eval_days: int) -> list[pd.Timestamp]:
    unique_dates = sorted(pd.Timestamp(value) for value in frame["date_dt"].dropna().unique())
    if not unique_dates:
        return []
    return unique_dates[-int(eval_days) :] if len(unique_dates) > int(eval_days) else unique_dates


def _pooled_spearman(frame: pd.DataFrame, score_col: str, actual_col: str) -> tuple[float, float]:
    valid = frame.dropna(subset=[score_col, actual_col]).copy()
    if len(valid) < 2:
        return float("nan"), float("nan")
    if valid[score_col].nunique(dropna=True) < 2 or valid[actual_col].nunique(dropna=True) < 2:
        return float("nan"), float("nan")
    rho, p_value = spearmanr(valid[score_col], valid[actual_col])
    return float(rho), float(p_value)


def _feature_summary(feature_rows: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for feature in FEATURE_COLUMNS:
        valid = feature_rows.dropna(subset=[feature, "hit_104"]).copy()
        rho, p_value = _pooled_spearman(valid, feature, "hit_104") if not valid.empty else (float("nan"), float("nan"))
        if valid.empty:
            q0_hit = float("nan")
            q4_hit = float("nan")
        else:
            bins = _safe_qcut(valid[feature], 5)
            valid = valid.assign(feature_bin=bins)
            grouped = valid.groupby("feature_bin", dropna=True)["hit_104"].mean().sort_index()
            if grouped.empty:
                q0_hit = float("nan")
                q4_hit = float("nan")
            else:
                q0_hit = float(grouped.iloc[0])
                q4_hit = float(grouped.iloc[-1])
        rows.append(
            {
                "feature": feature,
                "rho_in_section": rho,
                "p_value": p_value,
                "q0_hit": q0_hit,
                "q4_hit": q4_hit,
                "delta_pp": (q4_hit - q0_hit) * 100.0 if not pd.isna(q0_hit) and not pd.isna(q4_hit) else float("nan"),
                "n_rows": int(len(valid)),
            }
        )
    summary = pd.DataFrame(rows)
    summary["signal_flag"] = (summary["rho_in_section"].gt(0)) & (summary["p_value"].lt(0.1))
    return summary.sort_values(["signal_flag", "rho_in_section"], ascending=[False, False]).reset_index(drop=True)


def _add_strategy_scores(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["hist_score"] = work["hist_metric"].fillna(0.0)
    work["kakuban_score_rank"] = (
        work.groupby("section", dropna=False)["kakuban_score"]
        .transform(lambda s: s.rank(pct=True, method="average", ascending=False))
        .fillna(0.0)
    )
    work["debut_score_rank"] = (
        work.groupby("section", dropna=False)["debut_score"]
        .transform(lambda s: s.rank(pct=True, method="average", ascending=False))
        .fillna(0.0)
    )
    work["trail_score_rank"] = (
        work.groupby("section", dropna=False)["trail_7d_score"]
        .transform(lambda s: s.rank(pct=True, method="average", ascending=False))
        .fillna(0.0)
    )
    work["momentum_score_rank"] = (
        work.groupby("section", dropna=False)["momentum_score"]
        .transform(lambda s: s.rank(pct=True, method="average", ascending=False))
        .fillna(0.0)
    )
    return work


def _select_top_machines(frame: pd.DataFrame, *, score_col: str, top_per_section: int) -> pd.DataFrame:
    selected_rows: list[pd.DataFrame] = []
    for section, section_frame in frame.groupby("section", dropna=False):
        ranked = section_frame.sort_values(
            [score_col, "hist_score", "machine_number"],
            ascending=[False, False, True],
            na_position="last",
        ).head(int(top_per_section))
        ranked = ranked.copy()
        ranked["rank_in_section"] = range(1, len(ranked) + 1)
        selected_rows.append(ranked)
    if not selected_rows:
        return pd.DataFrame()
    return pd.concat(selected_rows, ignore_index=True)


def _strategy_output(day_frames: list[pd.DataFrame], *, selected_feature_names: list[str]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for frame in day_frames:
        if frame.empty:
            continue
        base = _add_strategy_scores(frame)
        baseline_hits = int(base["hit_104"].sum())
        baseline_rows = int(len(base))
        baseline = float(baseline_hits / baseline_rows) if baseline_rows else float("nan")
        strategy_configs = {
            "hist_only": [],
            "kakuban_weighted": ["kakuban_score_rank"],
            "debut_weighted": ["debut_score_rank"],
            "trail_weighted": ["trail_score_rank"],
            "momentum_weighted": ["momentum_score_rank"],
            "combined": [
                name
                for name in selected_feature_names
                if name
                in {
                    "kakuban_score_rank",
                    "debut_score_rank",
                    "trail_score_rank",
                    "momentum_score_rank",
                }
            ],
        }
        for strategy, component_cols in strategy_configs.items():
            work = base.copy()
            if component_cols:
                work["strategy_score"] = work["hist_score"] + DEFAULT_WEIGHT * work.loc[:, component_cols].mean(axis=1)
            else:
                work["strategy_score"] = work["hist_score"]
            selected = _select_top_machines(
                work, score_col="strategy_score", top_per_section=DEFAULT_TOP_MACHINES_PER_SECTION
            )
            selected_hits = int(selected["hit_104"].sum()) if not selected.empty else 0
            selected_rows = int(len(selected))
            selected_diff_sum = float(selected["diff_coins_normalized"].sum()) if not selected.empty else 0.0
            candidate_hits = baseline_hits
            candidate_rows = baseline_rows
            rows.append(
                {
                    "target_date": frame["target_date"].iloc[0],
                    "strategy": strategy,
                    "selected_rows": selected_rows,
                    "selected_hits": selected_hits,
                    "selected_diff_sum": selected_diff_sum,
                    "hit_rate": float(selected_hits / selected_rows) if selected_rows else float("nan"),
                    "baseline": baseline,
                    "lift": float((selected_hits / selected_rows) / baseline)
                    if selected_rows and baseline > 0
                    else float("nan"),
                    "avg_diff": float(selected_diff_sum / selected_rows) if selected_rows else float("nan"),
                    "candidate_rows": candidate_rows,
                    "candidate_hits": candidate_hits,
                    "candidate_hit_rate": baseline,
                }
            )
    summary = pd.DataFrame(rows)
    if summary.empty:
        return summary
    aggregated = (
        summary.groupby("strategy", as_index=False)
        .agg(
            selected_hits=("selected_hits", "sum"),
            selected_rows=("selected_rows", "sum"),
            selected_diff_sum=("selected_diff_sum", "sum"),
            candidate_rows=("candidate_rows", "sum"),
            candidate_hits=("candidate_hits", "sum"),
            candidate_hit_rate=("candidate_hit_rate", "mean"),
            n_days=("target_date", "nunique"),
        )
        .copy()
    )
    aggregated["hit_rate"] = aggregated["selected_hits"] / aggregated["selected_rows"]
    aggregated["baseline"] = aggregated["candidate_hits"] / aggregated["candidate_rows"]
    aggregated["lift"] = aggregated["hit_rate"] / aggregated["baseline"]
    aggregated["avg_diff"] = aggregated["selected_diff_sum"] / aggregated["selected_rows"]
    hist_only_avg = (
        float(aggregated.loc[aggregated["strategy"].eq("hist_only"), "avg_diff"].iloc[0])
        if not aggregated.empty and aggregated["strategy"].eq("hist_only").any()
        else float("nan")
    )
    aggregated["vs_hist_only"] = aggregated["avg_diff"] - hist_only_avg
    return aggregated.sort_values(["strategy"]).reset_index(drop=True)


def _write_report(
    path: Path, *, title: str, intro: list[str], table: pd.DataFrame, columns: list[str], float_digits: int = 3
) -> None:
    lines = [f"# {title}", ""]
    lines.extend(intro)
    if intro:
        lines.append("")
    lines.append(_render_table(table, columns=columns, float_digits=float_digits))
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def run(
    *,
    db_path: Path,
    output_dir: Path,
    window_days: int,
    eval_days: int,
    min_games: int,
    top_sections: int,
    top_machines_per_section: int,
) -> dict[str, Path]:
    frame = _load_frame(db_path, min_games=min_games)
    eval_dates = _evaluation_dates(frame, eval_days)
    if not eval_dates:
        raise ValueError("No evaluation dates available after filtering")

    day_bundles: list[DayBundle] = []
    for target_dt in eval_dates:
        bundle = _build_day_bundle(
            frame,
            target_dt=target_dt,
            window_days=window_days,
            top_sections=top_sections,
            top_machines_per_section=top_machines_per_section,
        )
        if bundle is not None:
            day_bundles.append(bundle)

    if not day_bundles:
        raise ValueError("No valid walk-forward days were produced")

    feature_rows = pd.concat([bundle.candidate_rows for bundle in day_bundles], ignore_index=True)
    feature_summary = _feature_summary(feature_rows)
    selected_feature_names = [
        FEATURE_SCORE_COLUMN_MAP[feature]
        for feature in feature_summary.loc[feature_summary["signal_flag"], "feature"].tolist()
        if feature in FEATURE_SCORE_COLUMN_MAP
    ]
    selected_feature_names = list(dict.fromkeys(selected_feature_names))

    strategy_summary = _strategy_output(
        [bundle.candidate_rows for bundle in day_bundles],
        selected_feature_names=selected_feature_names,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    feature_rows_path = output_dir / "feature_rows.csv"
    feature_summary_path = output_dir / "feature_summary.csv"
    strategy_summary_path = output_dir / "strategy_summary.csv"
    feature_rows.to_csv(feature_rows_path, index=False, encoding="utf-8")
    feature_summary.to_csv(feature_summary_path, index=False, encoding="utf-8")
    strategy_summary.to_csv(strategy_summary_path, index=False, encoding="utf-8")

    source_min_date = frame["date_dt"].min().strftime("%Y-%m-%d")
    source_max_date = frame["date_dt"].max().strftime("%Y-%m-%d")
    eval_min_date = eval_dates[0].strftime("%Y-%m-%d")
    eval_max_date = eval_dates[-1].strftime("%Y-%m-%d")
    feature_note = [
        f"- DB: `{db_path}`",
        f"- Source date range: `{source_min_date}` to `{source_max_date}`",
        f"- Evaluation dates: `{eval_min_date}` to `{eval_max_date}` ({len(eval_dates)} days)",
        f"- Filters: `games_normalized >= {min_games}`, `0707` excluded, machine `2026` excluded",
        f"- Stage 1: top `{top_sections}` sections per day",
        f"- Stage 2: top `{top_machines_per_section}` machines per selected section",
    ]
    strategy_note = [
        f"- Combined strategy keeps only features with `rho > 0` and `p < 0.1`.",
        f"- Strategy scores use within-section percentile ranks to stay comparable to `hist_metric`.",
    ]
    _write_report(
        output_dir / "report_features.md",
        title="Stage 2 Machine Selection Feature Report",
        intro=feature_note,
        table=feature_summary,
        columns=["feature", "rho_in_section", "p_value", "delta_pp", "signal_flag"],
        float_digits=4,
    )
    _write_report(
        output_dir / "report_strategies.md",
        title="Stage 2 Machine Selection Strategy Report",
        intro=strategy_note,
        table=strategy_summary,
        columns=["strategy", "hit_rate", "lift", "avg_diff", "vs_hist_only"],
        float_digits=4,
    )

    return {
        "feature_rows": feature_rows_path,
        "feature_summary": feature_summary_path,
        "strategy_summary": strategy_summary_path,
        "report_features": output_dir / "report_features.md",
        "report_strategies": output_dir / "report_strategies.md",
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 2 machine selection analysis.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument("--eval-days", type=int, default=DEFAULT_EVAL_DAYS)
    parser.add_argument("--min-games", type=int, default=DEFAULT_MIN_GAMES)
    parser.add_argument("--top-sections", type=int, default=DEFAULT_TOP_SECTIONS)
    parser.add_argument("--top-machines-per-section", type=int, default=DEFAULT_TOP_MACHINES_PER_SECTION)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    outputs = run(
        db_path=args.db_path,
        output_dir=args.output_dir,
        window_days=args.window_days,
        eval_days=args.eval_days,
        min_games=args.min_games,
        top_sections=args.top_sections,
        top_machines_per_section=args.top_machines_per_section,
    )
    for name, path in outputs.items():
        print(f"[OK] {name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
