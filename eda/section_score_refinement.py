from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.experiments.walkforward_scoring.config import DEFAULT_DB_PATH, EVENT_DDS  # noqa: E402
from ml.experiments.walkforward_scoring.scoring_model import build_score_context, classify_seg  # noqa: E402
from ml.experiments.walkforward_scoring.walk_forward_engine import load_machine_data  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "results" / "section_score_refinement"
DEFAULT_WINDOW_DAYS = 90
DEFAULT_EVAL_DAYS = 60
DEFAULT_MIN_GAMES = 1500
DEFAULT_TOP_SECTIONS = 5
DEFAULT_TOP_MACHINES_PER_SECTION = 5
BASELINE_THRESHOLD_A = 104.0
BASELINE_THRESHOLD_N = 106.0
THRESHOLDS_A = (100.0, 101.0, 102.0, 103.0, 104.0)
THRESHOLDS_N = (104.0, 105.0, 106.0)
ALPHA_GRID = (0.0, 0.1, 0.2, 0.3, 0.5)
BETA_GRID = (0.0, 0.1, 0.2, 0.3, 0.5)


@dataclass
class ComboResult:
    label: str
    section_rows: pd.DataFrame
    day_rows: pd.DataFrame
    summary: dict[str, object]


def _format_value(value: object, *, float_digits: int = 3) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.{float_digits}f}"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    return str(value)


def render_table(frame: pd.DataFrame, *, columns: list[str] | None = None, float_digits: int = 3) -> str:
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


def parse_int_list(raw: str) -> tuple[int, ...]:
    values = [part.strip() for part in str(raw).split(",") if part.strip()]
    return tuple(int(value) for value in values)


def _resolve_date(date_arg: str) -> pd.Timestamp:
    try:
        return pd.to_datetime(date_arg, format="%Y%m%d", errors="raise")
    except Exception as exc:  # pragma: no cover - CLI validation
        raise ValueError(f"invalid --date value: {date_arg}") from exc


def build_candidate_hit_flag(frame: pd.DataFrame, *, threshold_a: float, threshold_n: float) -> pd.Series:
    threshold = np.where(frame["seg"].astype(str).eq("A"), float(threshold_a), float(threshold_n))
    return pd.Series(frame["payout_rate"].to_numpy() >= threshold, index=frame.index, name="candidate_hit_flag")


def blend_section_scores(
    base: pd.Series, dd_adjustment: pd.Series, dow_adjustment: pd.Series, *, alpha: float, beta: float
) -> pd.Series:
    index = base.index.union(dd_adjustment.index).union(dow_adjustment.index)
    work = pd.DataFrame(index=index)
    work["base"] = base.reindex(index)
    work["dd"] = dd_adjustment.reindex(index).fillna(0.0)
    work["dow"] = dow_adjustment.reindex(index).fillna(0.0)
    return work["base"] + float(alpha) * work["dd"] + float(beta) * work["dow"]


def build_section_adjustments(
    frame: pd.DataFrame,
    *,
    target_dd: int,
    target_dow: int,
    hit_col: str = "hit_flag",
    min_dates: int = 3,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "base_rate",
                "base_dates",
                "dd_rate",
                "dd_dates",
                "dd_adjustment",
                "dow_rate",
                "dow_dates",
                "dow_adjustment",
            ]
        )

    base = (
        frame.groupby("section", as_index=True)
        .agg(
            base_rate=(hit_col, "mean"),
            base_dates=("date_dt", "nunique"),
        )
        .copy()
    )
    dd_subset = frame[frame["dd"].eq(int(target_dd))].copy()
    dd_stats = (
        dd_subset.groupby("section", as_index=True)
        .agg(
            dd_rate=(hit_col, "mean"),
            dd_dates=("date_dt", "nunique"),
        )
        .copy()
    )
    dow_subset = frame[frame["dow"].eq(int(target_dow))].copy()
    dow_stats = (
        dow_subset.groupby("section", as_index=True)
        .agg(
            dow_rate=(hit_col, "mean"),
            dow_dates=("date_dt", "nunique"),
        )
        .copy()
    )

    work = base.join(dd_stats, how="outer").join(dow_stats, how="outer")
    work["base_rate"] = pd.to_numeric(work["base_rate"], errors="coerce")
    work["base_dates"] = pd.to_numeric(work["base_dates"], errors="coerce").fillna(0).astype(int)
    work["dd_rate"] = pd.to_numeric(work["dd_rate"], errors="coerce")
    work["dd_dates"] = pd.to_numeric(work["dd_dates"], errors="coerce").fillna(0).astype(int)
    work["dow_rate"] = pd.to_numeric(work["dow_rate"], errors="coerce")
    work["dow_dates"] = pd.to_numeric(work["dow_dates"], errors="coerce").fillna(0).astype(int)

    work["dd_adjustment"] = work["dd_rate"] - work["base_rate"]
    work["dow_adjustment"] = work["dow_rate"] - work["base_rate"]
    work.loc[(work["base_dates"] < min_dates) | work["base_rate"].isna(), "base_rate"] = np.nan
    work.loc[(work["base_dates"] < min_dates) | work["base_rate"].isna(), ["dd_adjustment", "dow_adjustment"]] = 0.0
    work.loc[(work["dd_dates"] < min_dates) | work["dd_rate"].isna(), "dd_adjustment"] = 0.0
    work.loc[(work["dow_dates"] < min_dates) | work["dow_rate"].isna(), "dow_adjustment"] = 0.0
    work["dd_adjustment"] = work["dd_adjustment"].fillna(0.0)
    work["dow_adjustment"] = work["dow_adjustment"].fillna(0.0)
    work.index.name = "section"
    return work.sort_index()


def build_section_subset_scores(
    frame: pd.DataFrame,
    *,
    subset_mask: pd.Series,
    hit_col: str = "hit_flag",
    min_dates: int = 5,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "base_rate",
                "base_dates",
                "subset_rate",
                "subset_dates",
                "subset_adjustment",
            ]
        )

    base = (
        frame.groupby("section", as_index=True)
        .agg(
            base_rate=(hit_col, "mean"),
            base_dates=("date_dt", "nunique"),
        )
        .copy()
    )
    subset = frame.loc[subset_mask].copy()
    subset_stats = (
        subset.groupby("section", as_index=True)
        .agg(
            subset_rate=(hit_col, "mean"),
            subset_dates=("date_dt", "nunique"),
        )
        .copy()
    )
    work = base.join(subset_stats, how="outer")
    work["base_rate"] = pd.to_numeric(work["base_rate"], errors="coerce")
    work["base_dates"] = pd.to_numeric(work["base_dates"], errors="coerce").fillna(0).astype(int)
    work["subset_rate"] = pd.to_numeric(work["subset_rate"], errors="coerce")
    work["subset_dates"] = pd.to_numeric(work["subset_dates"], errors="coerce").fillna(0).astype(int)
    work["subset_adjustment"] = work["subset_rate"] - work["base_rate"]
    work.loc[(work["base_dates"] < min_dates) | work["base_rate"].isna(), "base_rate"] = np.nan
    work.loc[(work["base_dates"] < min_dates) | work["base_rate"].isna(), "subset_adjustment"] = 0.0
    work.loc[(work["subset_dates"] < min_dates) | work["subset_rate"].isna(), "subset_adjustment"] = 0.0
    work["subset_adjustment"] = work["subset_adjustment"].fillna(0.0)
    work.index.name = "section"
    return work.sort_index()


def _load_section_frame(db_path: Path, *, min_games: int) -> pd.DataFrame:
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
        raise ValueError("No rows remained after the Kamata7 filters")

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
    work["dd"] = work["date_dt"].dt.day.astype(int)
    work["dow"] = work["date_dt"].dt.dayofweek.astype(int)
    work["is_event"] = work["dd"].isin(EVENT_DDS)
    work = work.sort_values(["machine_number", "date_dt"]).reset_index(drop=True)
    return work


def _train_window(frame: pd.DataFrame, target_dt: pd.Timestamp, *, window_days: int) -> pd.DataFrame:
    window_start = target_dt - pd.Timedelta(days=int(window_days))
    return frame[(frame["date_dt"].lt(target_dt)) & (frame["date_dt"].ge(window_start))].copy()


def _pooled_spearman(frame: pd.DataFrame, score_col: str, actual_col: str) -> float:
    valid = frame.dropna(subset=[score_col, actual_col]).copy()
    if len(valid) < 2:
        return float("nan")
    rho, _ = spearmanr(valid[score_col], valid[actual_col])
    return float(rho)


def _section_type(frame: pd.DataFrame) -> pd.Series:
    return frame.groupby("section")["seg"].apply(
        lambda s: "A-only" if (s == "A").all() else ("N-only" if (s != "A").all() else "mixed")
    )


def _restrict_to_current_machines(train: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if train.empty:
        return train.copy(), 0
    latest_date = pd.Timestamp(train["date_dt"].max())
    current_machines = (
        train.loc[train["date_dt"].eq(latest_date), "machine_number"].dropna().astype(int).drop_duplicates().tolist()
    )
    if not current_machines:
        return train.copy(), 0
    filtered = train[train["machine_number"].isin(current_machines)].copy()
    return filtered, int(len(current_machines))


def _build_section_score_bundle(
    history: pd.DataFrame,
    *,
    threshold_a: float,
    threshold_n: float,
    target_dd: int,
    target_dow: int,
    score_mode: str = "base",
    gamma: float = 0.5,
    min_dates: int = 3,
    target_is_event: bool | None = None,
) -> tuple[pd.Series, pd.Series, pd.DataFrame]:
    if history.empty:
        empty_series = pd.Series(dtype=float)
        return empty_series, empty_series, pd.DataFrame()

    work = history.copy()
    work["candidate_hit_flag"] = build_candidate_hit_flag(
        work, threshold_a=threshold_a, threshold_n=threshold_n
    ).astype(float)

    adjustments = build_section_adjustments(
        work.rename(columns={"candidate_hit_flag": "hit_flag"}),
        target_dd=target_dd,
        target_dow=target_dow,
        hit_col="hit_flag",
        min_dates=min_dates,
    )
    event_adjustments = build_section_subset_scores(
        work.rename(columns={"candidate_hit_flag": "hit_flag"}),
        subset_mask=work["is_event"].astype(bool) if "is_event" in work.columns else pd.Series(False, index=work.index),
        hit_col="hit_flag",
        min_dates=5,
    )
    nonevent_adjustments = build_section_subset_scores(
        work.rename(columns={"candidate_hit_flag": "hit_flag"}),
        subset_mask=~work["is_event"].astype(bool)
        if "is_event" in work.columns
        else pd.Series(False, index=work.index),
        hit_col="hit_flag",
        min_dates=5,
    )
    if adjustments.empty:
        empty_series = pd.Series(dtype=float)
        return empty_series, empty_series, adjustments

    base_score = adjustments["base_rate"].copy()
    dd_only_score = (adjustments["base_rate"] + adjustments["dd_adjustment"]).copy()
    dow_only_score = (adjustments["base_rate"] + adjustments["dow_adjustment"]).copy()
    event_only_score = event_adjustments["base_rate"].copy() + event_adjustments["subset_adjustment"].copy()
    nonevent_only_score = nonevent_adjustments["base_rate"].copy() + nonevent_adjustments["subset_adjustment"].copy()

    if score_mode == "base":
        section_scores = base_score
    elif score_mode == "dd_only":
        section_scores = dd_only_score
    elif score_mode == "dow_only":
        section_scores = dow_only_score
    elif score_mode == "blend_dd":
        section_scores = float(gamma) * base_score + (1.0 - float(gamma)) * dd_only_score
    elif score_mode == "event_only":
        section_scores = event_only_score
    elif score_mode == "nonevent_only":
        section_scores = nonevent_only_score
    elif score_mode == "event_blend":
        section_scores = (
            float(gamma) * base_score + (1.0 - float(gamma)) * event_only_score if target_is_event else base_score
        )
    elif score_mode == "nonevent_blend":
        section_scores = (
            float(gamma) * base_score + (1.0 - float(gamma)) * nonevent_only_score
            if target_is_event is False
            else base_score
        )
    elif score_mode == "adaptive":
        if target_is_event is True:
            section_scores = float(gamma) * base_score + (1.0 - float(gamma)) * event_only_score
        elif target_is_event is False:
            section_scores = float(gamma) * base_score + (1.0 - float(gamma)) * nonevent_only_score
        else:
            section_scores = base_score
    else:  # pragma: no cover - defensive
        raise ValueError(f"unknown score_mode: {score_mode}")

    machine_scores = work.groupby(["section", "machine_number"])["candidate_hit_flag"].mean().rename("machine_score")
    return section_scores, machine_scores, adjustments


def _score_one_day(
    frame: pd.DataFrame,
    target_dt: pd.Timestamp,
    *,
    window_days: int,
    threshold_a: float,
    threshold_n: float,
    alpha: float,
    beta: float,
    top_sections: int,
    top_machines_per_section: int,
    score_mode: str = "base",
    gamma: float = 0.5,
    current_machines_only: bool = False,
) -> tuple[pd.DataFrame, dict[str, object]]:
    actual = frame[frame["date_dt"].eq(target_dt)].copy()
    if actual.empty:
        return pd.DataFrame(), {}

    train_raw = _train_window(frame, target_dt, window_days=window_days)
    if train_raw.empty:
        return pd.DataFrame(), {}

    if current_machines_only:
        train, current_machine_count = _restrict_to_current_machines(train_raw)
    else:
        train = train_raw.copy()
        current_machine_count = int(train["machine_number"].nunique())
    if train.empty:
        return pd.DataFrame(), {}

    section_scores, machine_scores, adjustments = _build_section_score_bundle(
        train,
        threshold_a=threshold_a,
        threshold_n=threshold_n,
        target_dd=int(target_dt.day),
        target_dow=int(target_dt.dayofweek),
        score_mode=score_mode,
        gamma=gamma,
        target_is_event=bool(target_dt.day in EVENT_DDS),
    )
    if section_scores.empty:
        return pd.DataFrame(), {}

    roster = actual.loc[
        :,
        [
            "section",
            "machine_number",
            "machine_name",
            "seg",
            "payout_rate",
            "hit_104",
            "diff_coins_normalized",
        ],
    ].copy()
    roster["section_type"] = _section_type(actual).reindex(roster["section"]).to_numpy()
    roster = roster.merge(
        machine_scores.reset_index(),
        on=["section", "machine_number"],
        how="left",
        validate="m:1",
    )

    section_actual = (
        actual.groupby("section", as_index=False)
        .agg(
            section_hit_rate=("hit_104", "mean"),
            actual_n=("machine_number", "size"),
            actual_diff_sum=("diff_coins_normalized", "sum"),
        )
        .copy()
    )
    section_eval = section_actual.merge(
        adjustments.loc[:, ["base_rate", "base_dates", "dd_adjustment", "dow_adjustment"]].reset_index(),
        on="section",
        how="left",
        validate="1:1",
    )
    section_eval["section_score"] = section_eval["section"].map(section_scores)
    section_eval["section_type"] = section_eval["section"].map(_section_type(actual))
    section_eval["target_date"] = target_dt
    section_eval["is_event"] = int(target_dt.day in EVENT_DDS)
    section_eval = section_eval.sort_values(
        ["section_score", "section"], ascending=[False, True], na_position="last"
    ).reset_index(drop=True)
    section_eval["section_rank"] = range(1, len(section_eval) + 1)

    top_sections_df = section_eval.head(int(top_sections)).copy()
    selected = roster[roster["section"].isin(top_sections_df["section"])].copy()
    selected = selected.sort_values(
        ["section", "machine_score", "machine_number"], ascending=[True, False, True], na_position="last"
    )
    selected["rank_in_section"] = selected.groupby("section", dropna=False).cumcount() + 1
    selected = selected[selected["rank_in_section"] <= int(top_machines_per_section)].copy()

    overall_rate = float(actual["hit_104"].mean())
    selected_rate = float(selected["hit_104"].mean()) if not selected.empty else float("nan")
    selected_lift = float(selected_rate / overall_rate) if overall_rate > 0 else float("nan")
    avg_diff_per_machine = float(selected["diff_coins_normalized"].mean()) if not selected.empty else float("nan")
    sample_reduction_pct = float(0.0 if len(train_raw) == 0 else (1.0 - (len(train) / len(train_raw))) * 100.0)

    summary = {
        "target_date": target_dt,
        "is_event": int(target_dt.day in EVENT_DDS),
        "overall_hit_rate": overall_rate,
        "selected_hit_rate": selected_rate,
        "selected_lift": selected_lift,
        "avg_diff_per_machine": avg_diff_per_machine,
        "selected_count": int(len(selected)),
        "section_count": int(len(section_eval)),
        "train_rows": int(len(train_raw)),
        "history_rows": int(len(train)),
        "history_machines": int(train["machine_number"].nunique()),
        "current_machine_count": int(current_machine_count),
        "sample_reduction_pct": sample_reduction_pct,
    }
    return section_eval, summary


def _evaluate_combo(
    frame: pd.DataFrame,
    *,
    eval_dates: list[pd.Timestamp],
    window_days: int,
    threshold_a: float,
    threshold_n: float,
    alpha: float,
    beta: float,
    top_sections: int,
    top_machines_per_section: int,
    score_mode: str = "base",
    gamma: float = 0.5,
    current_machines_only: bool = False,
) -> ComboResult:
    section_rows: list[pd.DataFrame] = []
    day_rows: list[dict[str, object]] = []
    for target_dt in eval_dates:
        section_eval, summary = _score_one_day(
            frame,
            target_dt,
            window_days=window_days,
            threshold_a=threshold_a,
            threshold_n=threshold_n,
            alpha=alpha,
            beta=beta,
            top_sections=top_sections,
            top_machines_per_section=top_machines_per_section,
            score_mode=score_mode,
            gamma=gamma,
            current_machines_only=current_machines_only,
        )
        if section_eval.empty:
            continue
        section_rows.append(section_eval)
        day_rows.append(summary)

    pooled = pd.concat(section_rows, ignore_index=True) if section_rows else pd.DataFrame()
    day_frame = pd.DataFrame(day_rows)
    summary = {
        "rho_all": _pooled_spearman(pooled, "section_score", "section_hit_rate") if not pooled.empty else float("nan"),
        "rho_A_only": _pooled_spearman(
            pooled.loc[pooled["section_type"].eq("A-only")], "section_score", "section_hit_rate"
        )
        if not pooled.empty
        else float("nan"),
        "rho_N_only": _pooled_spearman(
            pooled.loc[pooled["section_type"].eq("N-only")], "section_score", "section_hit_rate"
        )
        if not pooled.empty
        else float("nan"),
        "rho_event": _pooled_spearman(pooled.loc[pooled["is_event"].eq(1)], "section_score", "section_hit_rate")
        if not pooled.empty
        else float("nan"),
        "rho_nonevent": _pooled_spearman(pooled.loc[pooled["is_event"].eq(0)], "section_score", "section_hit_rate")
        if not pooled.empty
        else float("nan"),
        "lift_5x5": float(day_frame["selected_lift"].mean()) if not day_frame.empty else float("nan"),
        "lift_5x5_event": float(day_frame.loc[day_frame["is_event"].eq(1), "selected_lift"].mean())
        if not day_frame.empty
        else float("nan"),
        "lift_5x5_nonevent": float(day_frame.loc[day_frame["is_event"].eq(0), "selected_lift"].mean())
        if not day_frame.empty
        else float("nan"),
        "avg_diff_per_machine": float(day_frame["avg_diff_per_machine"].mean())
        if not day_frame.empty
        else float("nan"),
        "selected_count_mean": float(day_frame["selected_count"].mean()) if not day_frame.empty else float("nan"),
        "section_count_mean": float(day_frame["section_count"].mean()) if not day_frame.empty else float("nan"),
        "history_rows_mean": float(day_frame["history_rows"].mean()) if not day_frame.empty else float("nan"),
        "history_machines_mean": float(day_frame["history_machines"].mean()) if not day_frame.empty else float("nan"),
        "sample_reduction_pct": float(day_frame["sample_reduction_pct"].mean())
        if not day_frame.empty
        else float("nan"),
        "n_days": int(len(day_frame)),
    }
    return ComboResult(label="", section_rows=pooled, day_rows=day_frame, summary=summary)


def _evaluation_dates(frame: pd.DataFrame, eval_days: int) -> list[pd.Timestamp]:
    unique_dates = sorted(pd.Timestamp(value) for value in frame["date_dt"].dropna().unique())
    if not unique_dates:
        return []
    return unique_dates[-int(eval_days) :] if len(unique_dates) > int(eval_days) else unique_dates


def _summarize_part1_grid(
    frame: pd.DataFrame,
    *,
    eval_dates: list[pd.Timestamp],
    window_days: int,
    top_sections: int,
    top_machines_per_section: int,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for threshold_a, threshold_n in product(THRESHOLDS_A, THRESHOLDS_N):
        combo = _evaluate_combo(
            frame,
            eval_dates=eval_dates,
            window_days=window_days,
            threshold_a=threshold_a,
            threshold_n=threshold_n,
            alpha=0.0,
            beta=0.0,
            top_sections=top_sections,
            top_machines_per_section=top_machines_per_section,
        )
        rows.append(
            {
                "threshold_A": float(threshold_a),
                "threshold_N": float(threshold_n),
                "rho_all": combo.summary["rho_all"],
                "rho_A_only": combo.summary["rho_A_only"],
                "rho_N_only": combo.summary["rho_N_only"],
                "lift_5x5": combo.summary["lift_5x5"],
                "avg_diff_per_machine": combo.summary["avg_diff_per_machine"],
                "n_days": combo.summary["n_days"],
            }
        )
    return (
        pd.DataFrame(rows)
        .sort_values(
            ["rho_all", "lift_5x5", "threshold_A", "threshold_N"],
            ascending=[False, False, True, True],
            na_position="last",
        )
        .reset_index(drop=True)
    )


def _summarize_part2_grid(
    frame: pd.DataFrame,
    *,
    eval_dates: list[pd.Timestamp],
    window_days: int,
    top_sections: int,
    top_machines_per_section: int,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for alpha, beta in product(ALPHA_GRID, BETA_GRID):
        combo = _evaluate_combo(
            frame,
            eval_dates=eval_dates,
            window_days=window_days,
            threshold_a=BASELINE_THRESHOLD_A,
            threshold_n=BASELINE_THRESHOLD_N,
            alpha=alpha,
            beta=beta,
            top_sections=top_sections,
            top_machines_per_section=top_machines_per_section,
        )
        rows.append(
            {
                "alpha": float(alpha),
                "beta": float(beta),
                "rho": combo.summary["rho_all"],
                "rho_event": combo.summary["rho_event"],
                "rho_nonevent": combo.summary["rho_nonevent"],
                "lift_5x5": combo.summary["lift_5x5"],
                "lift_5x5_event": combo.summary["lift_5x5_event"],
                "lift_5x5_nonevent": combo.summary["lift_5x5_nonevent"],
                "avg_diff_per_machine": combo.summary["avg_diff_per_machine"],
                "n_days": combo.summary["n_days"],
            }
        )
    return (
        pd.DataFrame(rows)
        .sort_values(
            ["rho", "lift_5x5", "alpha", "beta"],
            ascending=[False, False, True, True],
            na_position="last",
        )
        .reset_index(drop=True)
    )


def _load_or_build_part1(
    frame: pd.DataFrame,
    *,
    output_dir: Path,
    eval_dates: list[pd.Timestamp],
    window_days: int,
    top_sections: int,
    top_machines_per_section: int,
) -> pd.DataFrame:
    path = output_dir / "part1_threshold_grid.csv"
    if path.exists():
        return pd.read_csv(path)
    part1 = _summarize_part1_grid(
        frame,
        eval_dates=eval_dates,
        window_days=window_days,
        top_sections=top_sections,
        top_machines_per_section=top_machines_per_section,
    )
    path.write_text(part1.to_csv(index=False, encoding="utf-8-sig"), encoding="utf-8")
    return part1


def _load_or_build_part2(
    frame: pd.DataFrame,
    *,
    output_dir: Path,
    eval_dates: list[pd.Timestamp],
    window_days: int,
    top_sections: int,
    top_machines_per_section: int,
) -> pd.DataFrame:
    path = output_dir / "part2_adjustment_grid.csv"
    if path.exists():
        return pd.read_csv(path)
    part2 = _summarize_part2_grid(
        frame,
        eval_dates=eval_dates,
        window_days=window_days,
        top_sections=top_sections,
        top_machines_per_section=top_machines_per_section,
    )
    path.write_text(part2.to_csv(index=False, encoding="utf-8-sig"), encoding="utf-8")
    return part2


def _write_report(path: Path, report: str) -> None:
    path.write_text(report, encoding="utf-8")


def _build_part1_report(part1: pd.DataFrame) -> str:
    best = part1.head(1)
    lines = [
        "# Section Score Refinement - Part 1",
        "",
        "## Grid Summary",
        "",
        render_table(
            part1,
            columns=[
                "threshold_A",
                "threshold_N",
                "rho_all",
                "rho_A_only",
                "rho_N_only",
                "lift_5x5",
                "avg_diff_per_machine",
            ],
            float_digits=4,
        ),
        "",
    ]
    if not best.empty:
        row = best.iloc[0]
        lines.append("## Best Thresholds")
        lines.append("")
        lines.append(
            f"- threshold_A: `{row['threshold_A']:.1f}`"
            f", threshold_N: `{row['threshold_N']:.1f}`"
            f", rho_all: `{row['rho_all']:.4f}`"
            f", lift_5x5: `{row['lift_5x5']:.4f}`"
        )
        lines.append("")
    return "\n".join(lines) + "\n"


def _build_part2_report(part2: pd.DataFrame) -> str:
    best = part2.head(1)
    lines = [
        "# Section Score Refinement - Part 2",
        "",
        "## Grid Summary",
        "",
        render_table(
            part2,
            columns=[
                "alpha",
                "beta",
                "rho",
                "rho_event",
                "rho_nonevent",
                "lift_5x5",
                "lift_5x5_event",
                "lift_5x5_nonevent",
                "avg_diff_per_machine",
            ],
            float_digits=4,
        ),
        "",
    ]
    if not best.empty:
        row = best.iloc[0]
        lines.append("## Best Adjustment")
        lines.append("")
        lines.append(
            f"- alpha: `{row['alpha']:.1f}`"
            f", beta: `{row['beta']:.1f}`"
            f", rho: `{row['rho']:.4f}`"
            f", lift_5x5: `{row['lift_5x5']:.4f}`"
        )
        lines.append("")
    return "\n".join(lines) + "\n"


def _build_part3_report(part1: pd.DataFrame, part2: pd.DataFrame, baseline: ComboResult, combined: ComboResult) -> str:
    best_threshold = part1.head(1).iloc[0]
    best_adjustment = part2.head(1).iloc[0]
    combined_row = pd.DataFrame([combined.summary])
    combined_row.insert(0, "threshold_A", float(best_threshold["threshold_A"]))
    combined_row.insert(1, "threshold_N", float(best_threshold["threshold_N"]))
    combined_row.insert(2, "alpha", float(best_adjustment["alpha"]))
    combined_row.insert(3, "beta", float(best_adjustment["beta"]))
    combined_table = combined_row.loc[
        :,
        [
            "threshold_A",
            "threshold_N",
            "alpha",
            "beta",
            "rho_all",
            "rho_event",
            "rho_nonevent",
            "lift_5x5",
            "lift_5x5_event",
            "lift_5x5_nonevent",
            "avg_diff_per_machine",
        ],
    ].copy()
    lines = [
        "# Section Score Refinement - Part 3",
        "",
        "## Selected Parameters",
        "",
        f"- threshold_A: `{best_threshold['threshold_A']:.1f}`",
        f"- threshold_N: `{best_threshold['threshold_N']:.1f}`",
        f"- alpha: `{best_adjustment['alpha']:.1f}`",
        f"- beta: `{best_adjustment['beta']:.1f}`",
        "",
        "## Combined Re-Evaluation",
        "",
        render_table(combined_table, float_digits=4),
        "",
        "## Baseline vs Combined",
        "",
        render_table(
            pd.DataFrame(
                [
                    {
                        "label": "baseline",
                        "threshold_A": BASELINE_THRESHOLD_A,
                        "threshold_N": BASELINE_THRESHOLD_N,
                        "alpha": 0.0,
                        "beta": 0.0,
                        "rho_all": baseline.summary["rho_all"],
                        "lift_5x5": baseline.summary["lift_5x5"],
                        "avg_diff_per_machine": baseline.summary["avg_diff_per_machine"],
                    },
                    {
                        "label": "combined",
                        "threshold_A": float(best_threshold["threshold_A"]),
                        "threshold_N": float(best_threshold["threshold_N"]),
                        "alpha": float(best_adjustment["alpha"]),
                        "beta": float(best_adjustment["beta"]),
                        "rho_all": combined.summary["rho_all"],
                        "lift_5x5": combined.summary["lift_5x5"],
                        "avg_diff_per_machine": combined.summary["avg_diff_per_machine"],
                    },
                ]
            ),
            float_digits=4,
        ),
        "",
    ]
    return "\n".join(lines) + "\n"


def _summarize_part4_grid(
    frame: pd.DataFrame,
    *,
    eval_dates: list[pd.Timestamp],
    window_days: int,
    top_sections: int,
    top_machines_per_section: int,
) -> pd.DataFrame:
    variants: list[dict[str, object]] = [
        {
            "score_type": "base_only",
            "score_mode": "base",
            "gamma": np.nan,
        },
        {
            "score_type": "dd_only",
            "score_mode": "dd_only",
            "gamma": np.nan,
        },
        {
            "score_type": "dow_only",
            "score_mode": "dow_only",
            "gamma": np.nan,
        },
        {
            "score_type": "event_only",
            "score_mode": "event_only",
            "gamma": np.nan,
        },
        {
            "score_type": "nonevent_only",
            "score_mode": "nonevent_only",
            "gamma": np.nan,
        },
    ]
    for gamma in (0.3, 0.5, 0.7, 1.0):
        variants.append(
            {
                "score_type": f"event_blend_gamma_{gamma:.1f}",
                "score_mode": "event_blend",
                "gamma": float(gamma),
            }
        )
    for gamma in (0.3, 0.5, 0.7, 1.0):
        variants.append(
            {
                "score_type": f"nonevent_blend_gamma_{gamma:.1f}",
                "score_mode": "nonevent_blend",
                "gamma": float(gamma),
            }
        )
    variants.append(
        {
            "score_type": "adaptive",
            "score_mode": "adaptive",
            "gamma": 0.5,
        }
    )

    rows: list[dict[str, object]] = []
    for variant in variants:
        combo = _evaluate_combo(
            frame,
            eval_dates=eval_dates,
            window_days=window_days,
            threshold_a=BASELINE_THRESHOLD_A,
            threshold_n=BASELINE_THRESHOLD_N,
            alpha=0.0,
            beta=0.0,
            top_sections=top_sections,
            top_machines_per_section=top_machines_per_section,
            score_mode=str(variant["score_mode"]),
            gamma=float(variant["gamma"]) if pd.notna(variant["gamma"]) else 0.5,
        )
        rows.append(
            {
                "score_type": str(variant["score_type"]),
                "gamma": float(variant["gamma"]) if pd.notna(variant["gamma"]) else np.nan,
                "rho": combo.summary["rho_all"],
                "rho_event": combo.summary["rho_event"],
                "rho_nonevent": combo.summary["rho_nonevent"],
                "lift_5x5": combo.summary["lift_5x5"],
                "lift_5x5_event": combo.summary["lift_5x5_event"],
                "lift_5x5_nonevent": combo.summary["lift_5x5_nonevent"],
                "avg_diff_per_machine": combo.summary["avg_diff_per_machine"],
                "n_days": combo.summary["n_days"],
            }
        )
    return (
        pd.DataFrame(rows)
        .sort_values(
            ["rho", "lift_5x5", "score_type"],
            ascending=[False, False, True],
            na_position="last",
        )
        .reset_index(drop=True)
    )


def _summarize_part5_grid(
    frame: pd.DataFrame,
    *,
    eval_dates: list[pd.Timestamp],
    window_days: int,
    top_sections: int,
    top_machines_per_section: int,
) -> pd.DataFrame:
    variants = [
        {"score_type": "all_machines", "current_machines_only": False},
        {"score_type": "current_machines", "current_machines_only": True},
    ]
    rows: list[dict[str, object]] = []
    for variant in variants:
        combo = _evaluate_combo(
            frame,
            eval_dates=eval_dates,
            window_days=window_days,
            threshold_a=BASELINE_THRESHOLD_A,
            threshold_n=BASELINE_THRESHOLD_N,
            alpha=0.0,
            beta=0.0,
            top_sections=top_sections,
            top_machines_per_section=top_machines_per_section,
            score_mode="base",
            current_machines_only=bool(variant["current_machines_only"]),
        )
        rows.append(
            {
                "score_type": str(variant["score_type"]),
                "rho": combo.summary["rho_all"],
                "n_machines_avg": combo.summary["history_machines_mean"],
                "sample_reduction_pct": combo.summary["sample_reduction_pct"],
                "lift_5x5": combo.summary["lift_5x5"],
                "avg_diff_per_machine": combo.summary["avg_diff_per_machine"],
                "n_days": combo.summary["n_days"],
            }
        )
    return (
        pd.DataFrame(rows)
        .sort_values(
            ["rho", "lift_5x5", "score_type"],
            ascending=[False, False, True],
            na_position="last",
        )
        .reset_index(drop=True)
    )


def _build_part4_report(part4: pd.DataFrame) -> str:
    best = part4.head(1)
    lines = [
        "# Section Score Refinement - Part 4",
        "",
        "## DD/DOW Direct Scores",
        "",
        render_table(
            part4,
            columns=[
                "score_type",
                "gamma",
                "rho",
                "rho_event",
                "rho_nonevent",
                "lift_5x5",
                "lift_5x5_event",
                "lift_5x5_nonevent",
                "avg_diff_per_machine",
            ],
            float_digits=4,
        ),
        "",
    ]
    if not best.empty:
        row = best.iloc[0]
        lines.append("## Best Score Type")
        lines.append("")
        lines.append(f"- score_type: `{row['score_type']}`, rho: `{row['rho']:.4f}`, lift_5x5: `{row['lift_5x5']:.4f}`")
        lines.append("")
    return "\n".join(lines) + "\n"


def _build_part5_report(part5: pd.DataFrame) -> str:
    best = part5.head(1)
    lines = [
        "# Section Score Refinement - Part 5",
        "",
        "## Current Machine Restriction",
        "",
        render_table(
            part5,
            columns=["score_type", "rho", "n_machines_avg", "sample_reduction_pct", "lift_5x5", "avg_diff_per_machine"],
            float_digits=4,
        ),
        "",
    ]
    if not best.empty:
        row = best.iloc[0]
        lines.append("## Best Scope")
        lines.append("")
        lines.append(
            f"- score_type: `{row['score_type']}`"
            f", rho: `{row['rho']:.4f}`"
            f", sample_reduction_pct: `{row['sample_reduction_pct']:.2f}`"
        )
        lines.append("")
    return "\n".join(lines) + "\n"


def run_part1(
    frame: pd.DataFrame,
    *,
    output_dir: Path,
    eval_dates: list[pd.Timestamp],
    window_days: int,
    top_sections: int,
    top_machines_per_section: int,
) -> pd.DataFrame:
    part1 = _summarize_part1_grid(
        frame,
        eval_dates=eval_dates,
        window_days=window_days,
        top_sections=top_sections,
        top_machines_per_section=top_machines_per_section,
    )
    part1.to_csv(output_dir / "part1_threshold_grid.csv", index=False, encoding="utf-8-sig")
    _write_report(output_dir / "report_threshold.md", _build_part1_report(part1))
    return part1


def run_part2(
    frame: pd.DataFrame,
    *,
    output_dir: Path,
    eval_dates: list[pd.Timestamp],
    window_days: int,
    top_sections: int,
    top_machines_per_section: int,
) -> pd.DataFrame:
    part2 = _summarize_part2_grid(
        frame,
        eval_dates=eval_dates,
        window_days=window_days,
        top_sections=top_sections,
        top_machines_per_section=top_machines_per_section,
    )
    part2.to_csv(output_dir / "part2_adjustment_grid.csv", index=False, encoding="utf-8-sig")
    _write_report(output_dir / "report_adjustment.md", _build_part2_report(part2))
    return part2


def run_part3(
    frame: pd.DataFrame,
    *,
    output_dir: Path,
    eval_dates: list[pd.Timestamp],
    window_days: int,
    top_sections: int,
    top_machines_per_section: int,
    part1: pd.DataFrame | None = None,
    part2: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, ComboResult]:
    if part1 is None:
        part1 = _load_or_build_part1(
            frame,
            output_dir=output_dir,
            eval_dates=eval_dates,
            window_days=window_days,
            top_sections=top_sections,
            top_machines_per_section=top_machines_per_section,
        )
    if part2 is None:
        part2 = _load_or_build_part2(
            frame,
            output_dir=output_dir,
            eval_dates=eval_dates,
            window_days=window_days,
            top_sections=top_sections,
            top_machines_per_section=top_machines_per_section,
        )

    best_threshold = part1.head(1).iloc[0]
    best_adjustment = part2.head(1).iloc[0]
    baseline = _evaluate_combo(
        frame,
        eval_dates=eval_dates,
        window_days=window_days,
        threshold_a=BASELINE_THRESHOLD_A,
        threshold_n=BASELINE_THRESHOLD_N,
        alpha=0.0,
        beta=0.0,
        top_sections=top_sections,
        top_machines_per_section=top_machines_per_section,
    )
    combined = _evaluate_combo(
        frame,
        eval_dates=eval_dates,
        window_days=window_days,
        threshold_a=float(best_threshold["threshold_A"]),
        threshold_n=float(best_threshold["threshold_N"]),
        alpha=float(best_adjustment["alpha"]),
        beta=float(best_adjustment["beta"]),
        top_sections=top_sections,
        top_machines_per_section=top_machines_per_section,
    )
    combined_day = combined.day_rows.copy()
    combined_day.insert(0, "threshold_A", float(best_threshold["threshold_A"]))
    combined_day.insert(1, "threshold_N", float(best_threshold["threshold_N"]))
    combined_day.insert(2, "alpha", float(best_adjustment["alpha"]))
    combined_day.insert(3, "beta", float(best_adjustment["beta"]))
    combined_day.to_csv(output_dir / "part3_best_comparison.csv", index=False, encoding="utf-8-sig")

    comparison = pd.DataFrame(
        [
            {
                "label": "baseline",
                "threshold_A": BASELINE_THRESHOLD_A,
                "threshold_N": BASELINE_THRESHOLD_N,
                "alpha": 0.0,
                "beta": 0.0,
                "rho_all": baseline.summary["rho_all"],
                "lift_5x5": baseline.summary["lift_5x5"],
            },
            {
                "label": "combined",
                "threshold_A": float(best_threshold["threshold_A"]),
                "threshold_N": float(best_threshold["threshold_N"]),
                "alpha": float(best_adjustment["alpha"]),
                "beta": float(best_adjustment["beta"]),
                "rho_all": combined.summary["rho_all"],
                "lift_5x5": combined.summary["lift_5x5"],
            },
        ]
    )
    comparison.to_csv(output_dir / "part3_comparison.csv", index=False, encoding="utf-8-sig")
    _write_report(output_dir / "report_best.md", _build_part3_report(part1, part2, baseline, combined))
    return part1, part2, combined


def run_part4(
    frame: pd.DataFrame,
    *,
    output_dir: Path,
    eval_dates: list[pd.Timestamp],
    window_days: int,
    top_sections: int,
    top_machines_per_section: int,
) -> pd.DataFrame:
    part4 = _summarize_part4_grid(
        frame,
        eval_dates=eval_dates,
        window_days=window_days,
        top_sections=top_sections,
        top_machines_per_section=top_machines_per_section,
    )
    part4.to_csv(output_dir / "part4_dd_direct_grid.csv", index=False, encoding="utf-8-sig")
    _write_report(output_dir / "report_dd_direct.md", _build_part4_report(part4))
    return part4


def run_part5(
    frame: pd.DataFrame,
    *,
    output_dir: Path,
    eval_dates: list[pd.Timestamp],
    window_days: int,
    top_sections: int,
    top_machines_per_section: int,
) -> pd.DataFrame:
    part5 = _summarize_part5_grid(
        frame,
        eval_dates=eval_dates,
        window_days=window_days,
        top_sections=top_sections,
        top_machines_per_section=top_machines_per_section,
    )
    part5.to_csv(output_dir / "part5_current_machines_grid.csv", index=False, encoding="utf-8-sig")
    _write_report(output_dir / "report_current_machines.md", _build_part5_report(part5))
    return part5


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kamata7 section score refinement experiment")
    parser.add_argument("--part", choices=("1", "2", "3", "4", "5", "all"), default="all")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument("--eval-days", type=int, default=DEFAULT_EVAL_DAYS)
    parser.add_argument("--min-games", type=int, default=DEFAULT_MIN_GAMES)
    parser.add_argument("--top-sections", type=int, default=DEFAULT_TOP_SECTIONS)
    parser.add_argument("--top-machines-per-section", type=int, default=DEFAULT_TOP_MACHINES_PER_SECTION)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    frame = _load_section_frame(args.db_path, min_games=args.min_games)
    eval_dates = _evaluation_dates(frame, args.eval_days)
    if not eval_dates:
        raise ValueError("No evaluation dates remained after filtering")

    print(f"[INFO] DB: {args.db_path}")
    print(f"[INFO] eval dates: {len(eval_dates)}")
    print(f"[INFO] window_days: {args.window_days}")
    print(f"[INFO] output_dir: {args.output_dir}")

    part1 = part2 = None
    if args.part in {"1", "all", "3"}:
        part1 = run_part1(
            frame,
            output_dir=args.output_dir,
            eval_dates=eval_dates,
            window_days=args.window_days,
            top_sections=args.top_sections,
            top_machines_per_section=args.top_machines_per_section,
        )
        print(f"[OK] part1 rows: {len(part1)}")
        print(f"[OK] report saved: {args.output_dir / 'report_threshold.md'}")

    if args.part in {"2", "all", "3"}:
        part2 = run_part2(
            frame,
            output_dir=args.output_dir,
            eval_dates=eval_dates,
            window_days=args.window_days,
            top_sections=args.top_sections,
            top_machines_per_section=args.top_machines_per_section,
        )
        print(f"[OK] part2 rows: {len(part2)}")
        print(f"[OK] report saved: {args.output_dir / 'report_adjustment.md'}")

    if args.part in {"3", "all"}:
        part1, part2, combined = run_part3(
            frame,
            output_dir=args.output_dir,
            eval_dates=eval_dates,
            window_days=args.window_days,
            top_sections=args.top_sections,
            top_machines_per_section=args.top_machines_per_section,
            part1=part1,
            part2=part2,
        )
        print(f"[OK] combined days: {len(combined.day_rows)}")
        print(f"[OK] report saved: {args.output_dir / 'report_best.md'}")

    if args.part in {"4", "all"}:
        part4 = run_part4(
            frame,
            output_dir=args.output_dir,
            eval_dates=eval_dates,
            window_days=args.window_days,
            top_sections=args.top_sections,
            top_machines_per_section=args.top_machines_per_section,
        )
        print(f"[OK] part4 rows: {len(part4)}")
        print(f"[OK] report saved: {args.output_dir / 'report_dd_direct.md'}")

    if args.part in {"5", "all"}:
        part5 = run_part5(
            frame,
            output_dir=args.output_dir,
            eval_dates=eval_dates,
            window_days=args.window_days,
            top_sections=args.top_sections,
            top_machines_per_section=args.top_machines_per_section,
        )
        print(f"[OK] part5 rows: {len(part5)}")
        print(f"[OK] report saved: {args.output_dir / 'report_current_machines.md'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
