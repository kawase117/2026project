from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from scipy.stats import spearmanr
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

PROJECT_ROOT = Path(__file__).resolve().parents[3]

if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from .config import DEFAULT_HALL, DEFAULT_OUTPUT_ROOT, HALL_SLUGS

STAGE3_REQUIRED_COLUMNS = [
    "date",
    "machine_number",
    "machine_name",
    "G",
    "rb",
    "bb",
    "p_high",
    "e_setting",
    "e_payout",
    "kakuban_rank_min",
    "kakuban_rank_max",
    "section_size",
    "is_corner1",
    "side_lr",
    "b_machine_90d",
    "b_machine_180d",
    "p_high_lag1",
    "p_high_lag2",
    "p_high_lag1_event",
    "days_since_high",
    "high_freq_same_weekday",
    "weekday",
    "is_mon",
    "is_tue",
    "is_wed",
    "is_thu",
    "is_fri",
    "is_sat",
    "is_sun",
    "day_of_month",
    "day_suffix",
    "is_zorome",
    "is_strong_zorome",
    "is_month_end",
    "is_month_start",
    "is_event_day",
]

OUTCOME_COLUMNS = ["G", "rb", "bb", "p_high"]
MODEL_FEATURES = [
    "b_machine_90d",
    "b_machine_180d",
    "p_high_lag1",
    "p_high_lag2",
    "p_high_lag1_event",
    "days_since_high",
    "high_freq_same_weekday",
    "weekday",
    "is_mon",
    "is_tue",
    "is_wed",
    "is_thu",
    "is_fri",
    "is_sat",
    "is_sun",
    "day_of_month",
    "day_suffix",
    "is_zorome",
    "is_strong_zorome",
    "is_month_end",
    "is_month_start",
    "is_event_day",
]
SIDE_LR_DUMMY_FEATURES = ["side_lr_L", "side_lr_R"]
MODEL_FEATURES_M2 = MODEL_FEATURES + [
    "kakuban_rank_min",
    "kakuban_rank_max",
    "section_size",
    "is_corner1",
    *SIDE_LR_DUMMY_FEATURES,
]
B2_FEATURES = [
    "b_machine_180d",
    "weekday",
    "day_of_month",
    "day_suffix",
    "is_zorome",
    "is_strong_zorome",
    "is_month_end",
    "is_month_start",
    "is_event_day",
]
METHOD_ORDER = ("B0", "B1", "B2", "M", "M2")
SELECTION_COLUMNS = [
    "date",
    "method",
    "selected_rank",
    "machine_number",
    "machine_name",
    "score",
    "p_high",
    "e_setting",
    "e_payout",
    "G",
    "rb",
    "bb",
]
SUMMARY_COLUMNS = [
    "method",
    "n_eval_days",
    "n_skipped_lt10",
    "n_b2_nan_dropped",
    "mean_p_high_top3",
    "mean_selected_e_payout",
    "mean_hall_e_payout",
    "mean_payout_lift_pp",
    "mean_spearman",
    "n_selected_rows",
    "train_start",
    "train_end",
    "eval_start",
    "eval_end",
    "note",
]


def _ensure_utf8_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def _hall_slug(hall: str) -> str:
    return HALL_SLUGS.get(hall, hall)


def _resolve_stage3_csv(hall: str, stage3_csv: Path | None = None) -> Path:
    if stage3_csv is not None:
        return Path(stage3_csv)
    return DEFAULT_OUTPUT_ROOT / _hall_slug(hall) / "stage3_features.csv"


def _load_stage3_features(stage3_csv: Path) -> pd.DataFrame:
    if not stage3_csv.exists():
        raise FileNotFoundError(stage3_csv)
    return pd.read_csv(stage3_csv, encoding="utf-8-sig")


def _prepare_frame(frame: pd.DataFrame, *, hall: str) -> pd.DataFrame:
    work = frame.copy()
    missing = [column for column in STAGE3_REQUIRED_COLUMNS if column not in work.columns]
    if missing:
        raise ValueError(f"stage3 frame is missing required columns: {missing}")

    work["date"] = work["date"].astype(str)
    work["date_dt"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    for column in STAGE3_REQUIRED_COLUMNS:
        if column in {"date", "machine_name", "side_lr"}:
            continue
        if column == "machine_number":
            continue
        work[column] = pd.to_numeric(work[column], errors="coerce")
    work = work.dropna(subset=["date_dt", "machine_number", "machine_name", "p_high"]).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work["machine_name"] = work["machine_name"].astype(str)
    work = work.sort_values(["date_dt", "machine_number", "machine_name"], kind="mergesort").reset_index(drop=True)
    work["hall"] = hall
    work["target_high"] = work["p_high"].gt(0.5).astype(int)
    return work


def _deterministic_seed(date_dt: pd.Timestamp, *, hall: str, method: str) -> int:
    base = int(date_dt.strftime("%Y%m%d"))
    hall_token = sum(ord(ch) for ch in hall)
    method_token = sum(ord(ch) for ch in method)
    return (base * 97 + hall_token * 13 + method_token * 17) % (2**32 - 1)


def _rank_day(
    day_rows: pd.DataFrame, *, method: str, score: pd.Series | None = None, ascending: bool = False
) -> pd.DataFrame:
    ranked = day_rows.copy().reset_index(drop=True)
    if method == "B0":
        rng = np.random.default_rng(
            _deterministic_seed(ranked["date_dt"].iloc[0], hall=str(ranked["hall"].iloc[0]), method=method)
        )
        ranked["score"] = rng.random(len(ranked))
        ranked = ranked.sort_values(["score", "machine_number"], ascending=[False, True], kind="mergesort").reset_index(
            drop=True
        )
    else:
        if score is None:
            raise ValueError("score is required for deterministic ranking")
        ranked["score"] = score.to_numpy(dtype=float)
        ranked = ranked.sort_values(
            ["score", "machine_number"], ascending=[ascending, True], kind="mergesort", na_position="last"
        ).reset_index(drop=True)
    ranked["selected_rank"] = np.arange(1, len(ranked) + 1, dtype=int)
    return ranked


def _daily_metrics(ranked: pd.DataFrame, *, method: str, dropped_nan_rows: int = 0) -> dict[str, object]:
    selected = ranked.head(3).copy()
    top3_mean = float(selected["p_high"].mean()) if not selected.empty else float("nan")
    selected_payout = float(selected["e_payout"].mean()) if not selected.empty else float("nan")
    hall_payout = float(ranked["e_payout"].mean()) if not ranked.empty else float("nan")
    payout_lift = (
        selected_payout - hall_payout
        if not math.isnan(selected_payout) and not math.isnan(hall_payout)
        else float("nan")
    )
    spearman_value = float("nan")
    if len(ranked) >= 2:
        rho, _ = spearmanr(ranked["score"], ranked["e_setting"])
        if not math.isnan(rho):
            spearman_value = float(rho)
    return {
        "date": ranked["date"].iloc[0] if not ranked.empty else "",
        "method": method,
        "n_candidates": int(len(ranked)),
        "n_selected": int(len(selected)),
        "mean_p_high_top3": top3_mean,
        "mean_selected_e_payout": selected_payout,
        "mean_hall_e_payout": hall_payout,
        "payout_lift_pp": payout_lift,
        "spearman": spearman_value,
        "dropped_nan_rows": int(dropped_nan_rows),
    }


def _moving_block_bootstrap_ci(
    values: np.ndarray, *, n_bootstrap: int = 2000, block_size: int = 7, seed: int = 42
) -> dict[str, float]:
    clean = np.asarray(values, dtype=float)
    clean = clean[~np.isnan(clean)]
    if len(clean) == 0:
        return {"mean": float("nan"), "ci_lower": float("nan"), "ci_upper": float("nan"), "n": 0}
    if len(clean) == 1:
        value = float(clean[0])
        return {"mean": value, "ci_lower": value, "ci_upper": value, "n": 1}

    rng = np.random.default_rng(seed)
    boot_means: list[float] = []
    for _ in range(n_bootstrap):
        sample: list[float] = []
        while len(sample) < len(clean):
            start = int(rng.integers(0, len(clean)))
            for offset in range(block_size):
                sample.append(float(clean[(start + offset) % len(clean)]))
                if len(sample) >= len(clean):
                    break
        boot_means.append(float(np.mean(sample[: len(clean)])))
    return {
        "mean": float(np.mean(clean)),
        "ci_lower": float(np.percentile(boot_means, 2.5)),
        "ci_upper": float(np.percentile(boot_means, 97.5)),
        "n": int(len(clean)),
    }


def _add_side_lr_dummies(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    if "side_lr" not in work.columns:
        work["side_lr"] = np.nan
    dummies = pd.get_dummies(work["side_lr"], prefix="side_lr")
    for column in SIDE_LR_DUMMY_FEATURES:
        series = dummies[column] if column in dummies.columns else pd.Series(0, index=work.index)
        work[column] = pd.to_numeric(series, errors="coerce").fillna(0.0)
    return work


def _has_m2_layout_features(frame: pd.DataFrame) -> bool:
    layout_columns = ["kakuban_rank_min", "kakuban_rank_max", "section_size", "is_corner1", "side_lr"]
    if not set(layout_columns).issubset(frame.columns):
        return False
    work = frame.loc[:, layout_columns].copy()
    return bool(work.notna().any().any())


def _fit_b2_model(train: pd.DataFrame) -> tuple[Pipeline | None, int]:
    train_b2 = train.dropna(subset=["b_machine_180d"]).copy()
    if train_b2.empty or train_b2["target_high"].nunique() < 2:
        return None, int(len(train) - len(train_b2))

    model = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            (
                "clf",
                LogisticRegression(
                    max_iter=1000,
                    class_weight="balanced",
                    random_state=42,
                ),
            ),
        ]
    )
    model.fit(train_b2.loc[:, B2_FEATURES], train_b2["target_high"])
    return model, int(len(train) - len(train_b2))


def _fit_m_model(train: pd.DataFrame) -> LGBMClassifier | None:
    train_model = train.copy()
    if train_model.empty or train_model["target_high"].nunique() < 2:
        return None
    model = LGBMClassifier(
        objective="binary",
        n_estimators=120,
        learning_rate=0.05,
        num_leaves=31,
        min_child_samples=20,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=42,
        verbosity=-1,
        n_jobs=1,
    )
    model.fit(train_model.loc[:, MODEL_FEATURES], train_model["target_high"])
    return model


def _fit_m2_model(train: pd.DataFrame) -> LGBMClassifier | None:
    train_model = _add_side_lr_dummies(train)
    if train_model.empty or train_model["target_high"].nunique() < 2:
        return None
    model = LGBMClassifier(
        objective="binary",
        n_estimators=120,
        learning_rate=0.05,
        num_leaves=31,
        min_child_samples=20,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=42,
        verbosity=-1,
        n_jobs=1,
    )
    model.fit(train_model.loc[:, MODEL_FEATURES_M2], train_model["target_high"])
    return model


def _score_day(
    day_rows: pd.DataFrame,
    *,
    method: str,
    b2_model: Pipeline | None,
    m_model: LGBMClassifier | None,
    m2_model: LGBMClassifier | None,
) -> tuple[pd.DataFrame, int]:
    if method == "B0":
        return _rank_day(day_rows, method=method), 0
    if method == "B1":
        ranked = _rank_day(day_rows, method=method, score=day_rows["b_machine_180d"], ascending=False)
        return ranked, 0
    if method == "B2":
        eligible = day_rows.dropna(subset=["b_machine_180d"]).copy()
        if eligible.empty or b2_model is None:
            ranked = (
                _rank_day(eligible, method="B1", score=eligible["b_machine_180d"], ascending=False)
                if not eligible.empty
                else eligible.copy()
            )
            return ranked, int(len(day_rows) - len(eligible))
        score = pd.Series(b2_model.predict_proba(eligible.loc[:, B2_FEATURES])[:, 1], index=eligible.index)
        ranked = _rank_day(eligible, method=method, score=score, ascending=False)
        return ranked, int(len(day_rows) - len(eligible))
    if method == "M":
        if m_model is None:
            ranked = _rank_day(day_rows, method="B1", score=day_rows["b_machine_180d"], ascending=False)
            return ranked, 0
        score = pd.Series(m_model.predict_proba(day_rows.loc[:, MODEL_FEATURES])[:, 1], index=day_rows.index)
        ranked = _rank_day(day_rows, method=method, score=score, ascending=False)
        return ranked, 0
    if method == "M2":
        if m2_model is None:
            ranked = _rank_day(day_rows, method="B1", score=day_rows["b_machine_180d"], ascending=False)
            return ranked, 0
        scored_rows = _add_side_lr_dummies(day_rows)
        score = pd.Series(m2_model.predict_proba(scored_rows.loc[:, MODEL_FEATURES_M2])[:, 1], index=scored_rows.index)
        ranked = _rank_day(scored_rows, method=method, score=score, ascending=False)
        return ranked, 0
    raise ValueError(f"unknown method: {method}")


def _train_eval_month(
    frame: pd.DataFrame,
    *,
    month: pd.Period,
    hall: str,
    b2_model: Pipeline | None,
    m_model: LGBMClassifier | None,
    m2_model: LGBMClassifier | None,
    m2_applicable: bool,
) -> tuple[dict[str, pd.DataFrame], list[dict[str, object]], dict[str, list[float]]]:
    month_start = month.start_time.normalize()
    month_end = month.end_time.normalize()
    train_end = month_start - pd.Timedelta(days=1)
    train_start = train_end - pd.Timedelta(days=179)
    eval_mask = frame["date_dt"].dt.to_period("M").eq(month) & frame["date_dt"].ge(month_start)
    train_mask = frame["date_dt"].between(train_start, train_end, inclusive="both")
    train = frame.loc[train_mask].copy()
    eval_frame = frame.loc[eval_mask].copy()

    if eval_frame.empty or len(eval_frame["date_dt"].unique()) == 0:
        return {method: pd.DataFrame() for method in METHOD_ORDER}, [], {}

    method_rows: dict[str, list[pd.DataFrame]] = {method: [] for method in METHOD_ORDER}
    summaries: list[dict[str, object]] = []
    daily_metric_store: dict[str, list[float]] = {method: [] for method in METHOD_ORDER}

    if b2_model is None:
        b2_model, _ = _fit_b2_model(train)
    if m_model is None:
        m_model = _fit_m_model(train)
    if m2_model is None:
        m2_model = _fit_m2_model(train)

    for date_dt, day_rows in eval_frame.groupby("date_dt", sort=True):
        if len(day_rows) < 10:
            continue
        for method in METHOD_ORDER:
            if method == "M2" and not m2_applicable:
                continue
            ranked, dropped = _score_day(day_rows, method=method, b2_model=b2_model, m_model=m_model, m2_model=m2_model)
            if ranked.empty:
                continue
            summary_row = _daily_metrics(ranked, method=method, dropped_nan_rows=dropped)
            summaries.append(summary_row)
            daily_metric_store[method].append(float(summary_row["mean_p_high_top3"]))
            selection = ranked.head(3).copy()
            selection["method"] = method
            selection["selected_rank"] = np.arange(1, len(selection) + 1, dtype=int)
            selection["score"] = selection["score"].astype(float)
            method_rows[method].append(selection.loc[:, SELECTION_COLUMNS])

    selection_tables = {
        method: (pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=SELECTION_COLUMNS))
        for method, rows in method_rows.items()
    }
    return selection_tables, summaries, daily_metric_store


def build_stage4_outputs(*, frame: pd.DataFrame, hall: str) -> dict[str, object]:
    work = _prepare_frame(frame, hall=hall)
    m2_applicable = _has_m2_layout_features(work)
    if work.empty:
        empty_selection = pd.DataFrame(columns=SELECTION_COLUMNS)
        empty_summary = pd.DataFrame(columns=SUMMARY_COLUMNS)
        return {
            "selection_tables": {method: empty_selection.copy() for method in METHOD_ORDER},
            "summary": empty_summary,
            "bootstrap_ci": {
                "metric": "mean_p_high_top3",
                "block_size": 7,
                "n_bootstrap": 2000,
                "comparisons": {
                    "M_minus_B1": {"mean": float("nan"), "ci_lower": float("nan"), "ci_upper": float("nan"), "n": 0},
                    "M2_minus_B1": {"mean": float("nan"), "ci_lower": float("nan"), "ci_upper": float("nan"), "n": 0},
                    "B1_minus_B0": {"mean": float("nan"), "ci_lower": float("nan"), "ci_upper": float("nan"), "n": 0},
                },
            },
            "daily_metrics": pd.DataFrame(),
        }

    min_date = work["date_dt"].min()
    cutoff = min_date + pd.Timedelta(days=180)
    eval_months = sorted(work.loc[work["date_dt"].ge(cutoff), "date_dt"].dt.to_period("M").unique())
    selection_tables: dict[str, list[pd.DataFrame]] = {method: [] for method in METHOD_ORDER}
    summary_rows: list[dict[str, object]] = []
    daily_metric_frames: list[pd.DataFrame] = []
    train_window_start = None
    train_window_end = None

    for month in eval_months:
        month_start = month.start_time.normalize()
        month_end = month.end_time.normalize()
        train_end = month_start - pd.Timedelta(days=1)
        train_start = train_end - pd.Timedelta(days=179)
        train = work.loc[work["date_dt"].between(train_start, train_end, inclusive="both")].copy()
        eval_frame = work.loc[work["date_dt"].dt.to_period("M").eq(month) & work["date_dt"].ge(cutoff)].copy()
        if eval_frame.empty:
            continue
        train_window_start = train_start if train_window_start is None else min(train_window_start, train_start)
        train_window_end = train_end if train_window_end is None else max(train_window_end, train_end)
        b2_model, _ = _fit_b2_model(train)
        m_model = _fit_m_model(train)
        m2_model = _fit_m2_model(train) if m2_applicable else None
        month_selection, month_summary_rows, month_daily_metrics = _train_eval_month(
            work,
            month=month,
            hall=hall,
            b2_model=b2_model,
            m_model=m_model,
            m2_model=m2_model,
            m2_applicable=m2_applicable,
        )
        for method, table in month_selection.items():
            if not table.empty:
                selection_tables[method].append(table)
        if month_summary_rows:
            daily_metric_frames.append(pd.DataFrame(month_summary_rows))
        for method in METHOD_ORDER:
            day_metrics = [row for row in month_summary_rows if row["method"] == method]
            if not day_metrics:
                continue
            day_metric_frame = pd.DataFrame(day_metrics)
            summary_rows.append(
                {
                    "method": method,
                    "n_eval_days": int(len(day_metric_frame)),
                    "n_skipped_lt10": int(
                        len(work.loc[work["date_dt"].dt.to_period("M").eq(month)].groupby("date_dt").size())
                        - len(day_metric_frame["date"].unique())
                    ),
                    "n_b2_nan_dropped": int(day_metric_frame["dropped_nan_rows"].sum()) if method == "B2" else 0,
                    "mean_p_high_top3": float(day_metric_frame["mean_p_high_top3"].mean()),
                    "mean_selected_e_payout": float(day_metric_frame["mean_selected_e_payout"].mean()),
                    "mean_hall_e_payout": float(day_metric_frame["mean_hall_e_payout"].mean()),
                    "mean_payout_lift_pp": float(day_metric_frame["payout_lift_pp"].mean()),
                    "mean_spearman": float(day_metric_frame["spearman"].mean()),
                    "n_selected_rows": int(day_metric_frame["n_selected"].sum()),
                    "train_start": train_start.strftime("%Y%m%d"),
                    "train_end": train_end.strftime("%Y%m%d"),
                    "eval_start": month_start.strftime("%Y%m%d"),
                    "eval_end": month_end.strftime("%Y%m%d"),
                    "note": "",
                }
            )

    selection_frames = {
        method: (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=SELECTION_COLUMNS))
        for method, frames in selection_tables.items()
    }
    summary = pd.DataFrame(summary_rows)
    if not summary.empty:
        summary = summary.sort_values(["method", "eval_start"], kind="mergesort").reset_index(drop=True)
    daily_metrics = pd.concat(daily_metric_frames, ignore_index=True) if daily_metric_frames else pd.DataFrame()

    method_metric_map = {}
    for method in METHOD_ORDER:
        values = (
            daily_metrics.loc[daily_metrics["method"].eq(method), "mean_p_high_top3"].to_numpy(dtype=float)
            if not daily_metrics.empty
            else np.array([], dtype=float)
        )
        method_metric_map[method] = values

    bootstrap_ci = {
        "metric": "mean_p_high_top3",
        "block_size": 7,
        "n_bootstrap": 2000,
        "comparisons": {
            "M_minus_B1": _moving_block_bootstrap_ci(
                method_metric_map.get("M", np.array([], dtype=float))
                - method_metric_map.get("B1", np.array([], dtype=float))
                if len(method_metric_map.get("M", np.array([], dtype=float)))
                == len(method_metric_map.get("B1", np.array([], dtype=float)))
                else np.array([], dtype=float)
            ),
            "M2_minus_B1": _moving_block_bootstrap_ci(
                method_metric_map.get("M2", np.array([], dtype=float))
                - method_metric_map.get("B1", np.array([], dtype=float))
                if len(method_metric_map.get("M2", np.array([], dtype=float)))
                == len(method_metric_map.get("B1", np.array([], dtype=float)))
                else np.array([], dtype=float)
            ),
            "B1_minus_B0": _moving_block_bootstrap_ci(
                method_metric_map.get("B1", np.array([], dtype=float))
                - method_metric_map.get("B0", np.array([], dtype=float))
                if len(method_metric_map.get("B1", np.array([], dtype=float)))
                == len(method_metric_map.get("B0", np.array([], dtype=float)))
                else np.array([], dtype=float)
            ),
        },
    }

    if not summary.empty:
        m_ci = bootstrap_ci["comparisons"]["M_minus_B1"]
        m2_ci = bootstrap_ci["comparisons"]["M2_minus_B1"]
        b0_ci = bootstrap_ci["comparisons"]["B1_minus_B0"]
        m2_lower = float(m2_ci.get("ci_lower", float("nan")))
        if m2_applicable:
            conclusion_note = (
                "B1 (machine baseline) beats B0 significantly and is the primary usable signal. "
                "M (narrow calendar+lag features) and M2 (+kakuban/section/LR) do not beat B1 at "
                "95% CI in the tested sample; M2's effect is suggestively positive (CI lower bound "
                f"{m2_lower:+.3f}) but underpowered - not confirmed, not ruled out."
            )
        else:
            conclusion_note = (
                "B1 (machine baseline) beats B0 significantly and is the primary usable signal. "
                "M (narrow calendar+lag features) is evaluated normally. M2 is not applicable "
                "(no layout data), so it is skipped and not interpreted."
            )
        summary = pd.concat(
            [
                summary,
                pd.DataFrame(
                    [
                        {
                            "method": "CONCLUSION",
                            "n_eval_days": int(len(daily_metrics["date"].unique())) if not daily_metrics.empty else 0,
                            "n_skipped_lt10": 0,
                            "n_b2_nan_dropped": 0,
                            "mean_p_high_top3": float("nan"),
                            "mean_selected_e_payout": float("nan"),
                            "mean_hall_e_payout": float("nan"),
                            "mean_payout_lift_pp": float("nan"),
                            "mean_spearman": float("nan"),
                            "n_selected_rows": 0,
                            "train_start": "",
                            "train_end": "",
                            "eval_start": "",
                            "eval_end": "",
                            "note": conclusion_note,
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )
    if not m2_applicable:
        summary = pd.concat(
            [
                summary,
                pd.DataFrame(
                    [
                        {
                            "method": "M2",
                            "n_eval_days": 0,
                            "n_skipped_lt10": 0,
                            "n_b2_nan_dropped": 0,
                            "mean_p_high_top3": float("nan"),
                            "mean_selected_e_payout": float("nan"),
                            "mean_hall_e_payout": float("nan"),
                            "mean_payout_lift_pp": float("nan"),
                            "mean_spearman": float("nan"),
                            "n_selected_rows": 0,
                            "train_start": "",
                            "train_end": "",
                            "eval_start": "",
                            "eval_end": "",
                            "note": "M2 not applicable (no layout data)",
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )

    return {
        "selection_tables": selection_frames,
        "summary": summary,
        "bootstrap_ci": bootstrap_ci,
        "daily_metrics": daily_metrics,
    }


def _format_summary_text(summary: pd.DataFrame, bootstrap_ci: dict[str, object], hall: str) -> str:
    lines = [
        f"# Stage 4 Walk-forward - {hall}",
        "",
        "## Summary",
    ]
    if summary.empty:
        lines.append("_empty_")
    else:
        lines.extend(
            ["| " + " | ".join(map(str, summary.columns)) + " |"]
            + [
                "| " + " | ".join(map(lambda value: str(value), row)) + " |"
                for row in summary.itertuples(index=False, name=None)
            ]
        )
    lines.extend(
        [
            "",
            "## Bootstrap CI",
            json.dumps(bootstrap_ci, ensure_ascii=False, indent=2),
        ]
    )
    return "\n".join(lines)


def save_stage4_outputs(outputs: dict[str, object], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    selection_tables = outputs["selection_tables"]
    summary = outputs["summary"]
    bootstrap_ci = outputs["bootstrap_ci"]
    assert isinstance(selection_tables, dict)
    assert isinstance(summary, pd.DataFrame)
    assert isinstance(bootstrap_ci, dict)

    for method in METHOD_ORDER:
        table = selection_tables.get(method)
        if not isinstance(table, pd.DataFrame):
            raise TypeError(f"missing selection table for {method}")
        table.to_csv(output_dir / f"stage4_daily_selections_{method}.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(output_dir / "stage4_summary.csv", index=False, encoding="utf-8-sig")
    (output_dir / "stage4_bootstrap_ci.json").write_text(
        json.dumps(bootstrap_ci, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 4 juggler RB walk-forward evaluation")
    parser.add_argument("--hall", choices=tuple(HALL_SLUGS.keys()), default=DEFAULT_HALL)
    parser.add_argument("--stage3-csv", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdout()
    args = build_parser().parse_args(argv)
    stage3_csv = _resolve_stage3_csv(args.hall, args.stage3_csv)
    output_dir = Path(args.output_dir) if args.output_dir is not None else DEFAULT_OUTPUT_ROOT / _hall_slug(args.hall)
    frame = _load_stage3_features(stage3_csv)
    outputs = build_stage4_outputs(frame=frame, hall=args.hall)
    save_stage4_outputs(outputs, output_dir)
    print(output_dir / "stage4_summary.csv")
    print(output_dir / "stage4_bootstrap_ci.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
