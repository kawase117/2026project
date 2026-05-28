from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

from ml.last_digit.tail_ltr_split_rule_nextday_gpu import (
    EXPERT_ORDER,
    _gpu_model_params,
    _is_expert_indeterminate,
    _predict_for_date,
    _prepare_split_dataset,
    _should_use_2fn_weekday_patch,
    _should_use_digit_lag_bundle,
    build_parser as base_build_parser,
)
from ml.last_digit.tail_ltr_split_rule_wf import Candidate, parse_csv_floats, parse_csv_strs
from ml.last_digit.utils import configure_logging, resolve_db_path

MIN_PRED_SPAN = 1e-12
MIN_ZOROME_TRAIN_N = 5
MIN_NONZOROME_TRAIN_N = 10
SIM_WINDOW_DAYS = 60

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = base_build_parser()
    parser.description = "Zorome strategy simulation with separated comparison axes."
    parser.add_argument("--window-days", type=int, default=SIM_WINDOW_DAYS, help="Simulation test window length in calendar days.")
    parser.add_argument("--n-iter", type=int, default=1000, help="Monte Carlo iteration count per day.")
    parser.add_argument("--train-window-days", default="60,90,120,180,full", help="Comma-separated training windows used for correction tables.")
    parser.add_argument("--phase2-train-window", default="auto", help="One train window for D/E/F. 'auto' picks best from Phase1.")
    parser.add_argument("--participation-topk", type=int, default=3, help="Top-K predicted digits considered by D/E/F.")
    parser.add_argument("--min-zorome-train-n", type=int, default=MIN_ZOROME_TRAIN_N, help="Minimum zorome samples per correction cell.")
    parser.add_argument("--min-nonzorome-train-n", type=int, default=MIN_NONZOROME_TRAIN_N, help="Minimum non-zorome samples per correction cell.")
    for action in parser._actions:
        if "--db-path" in action.option_strings:
            action.required = True
            action.help = "DB path (required; empty string triggers --db-glob fallback)."
        if "--output-prefix" in action.option_strings:
            action.default = "db/experiments/zorome_sim"
            action.help = "Output prefix for simulation artifacts."
    return parser


def load_machine_level_data(db_path: Path) -> pd.DataFrame:
    query = """
    SELECT
      m.date,
      m.machine_number,
      CAST(m.last_digit AS INTEGER) AS last_digit,
      m.is_zorome,
      m.diff_coins_normalized,
      m.games_normalized,
      COALESCE(mm.jug_flag, 0) AS jug_flag,
      COALESCE(mm.hana_flag, 0) AS hana_flag,
      COALESCE(mm.bt_flag, 0) AS bt_flag
    FROM machine_detailed_results m
    LEFT JOIN machine_master mm
      ON m.machine_name = mm.machine_name_normalized
    WHERE m.games_normalized > 0
    """
    conn = sqlite3.connect(str(db_path))
    try:
        df = pd.read_sql_query(query, conn)
    finally:
        conn.close()

    if df.empty:
        raise ValueError("No rows from machine_detailed_results with games_normalized > 0")

    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["machine_number"] = pd.to_numeric(df["machine_number"], errors="coerce")
    df["last_digit"] = pd.to_numeric(df["last_digit"], errors="coerce")
    df["is_zorome"] = pd.to_numeric(df["is_zorome"], errors="coerce").fillna(0).astype(int)
    df["diff_coins_normalized"] = pd.to_numeric(df["diff_coins_normalized"], errors="coerce").fillna(0.0)

    df = df[df["machine_number"].notna() & df["last_digit"].notna()].copy()
    df["machine_number"] = df["machine_number"].astype(int)
    df["last_digit"] = df["last_digit"].astype(int)
    df = df[df["last_digit"].between(0, 9)].copy()

    df["floor_bucket"] = df["machine_number"].astype(str).str[0] + "F"
    df = df[df["floor_bucket"].isin(["2F", "3F"])].copy()
    df["atype_bucket"] = np.where(
        (df["jug_flag"] == 1) | (df["hana_flag"] == 1) | (df["bt_flag"] == 1),
        "A",
        "N",
    )
    df["group_key"] = df["floor_bucket"] + "_" + df["atype_bucket"]
    df["weekday"] = df["date"].dt.day_name()
    return df


def define_window(df: pd.DataFrame, window_days: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    sim_end = pd.to_datetime(df["date"].max())
    sim_start = sim_end - pd.Timedelta(days=int(window_days))
    return sim_start, sim_end


def _slice_train(df: pd.DataFrame, sim_start: pd.Timestamp, train_window: str) -> pd.DataFrame:
    if str(train_window).lower() == "full":
        return df[df["date"] < sim_start].copy()
    n = int(train_window)
    start = sim_start - pd.Timedelta(days=n)
    return df[(df["date"] < sim_start) & (df["date"] >= start)].copy()


def compute_zorome_correction_table(df_train: pd.DataFrame, min_zorome_n: int, min_nonzorome_n: int) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    grouped = df_train.groupby(["weekday", "last_digit", "group_key"], sort=True)
    for (weekday, last_digit, group_key), g in grouped:
        z = g.loc[g["is_zorome"] == 1, "diff_coins_normalized"]
        nz = g.loc[g["is_zorome"] == 0, "diff_coins_normalized"]
        n_z = int(len(z))
        n_nz = int(len(nz))
        mean_z = float(z.mean()) if n_z >= int(min_zorome_n) else np.nan
        mean_nz = float(nz.mean()) if n_nz >= int(min_nonzorome_n) else np.nan
        correction = mean_z - mean_nz if (np.isfinite(mean_z) and np.isfinite(mean_nz)) else np.nan
        rows.append(
            {
                "weekday": weekday,
                "last_digit": int(last_digit),
                "group_key": str(group_key),
                "n_zorome": n_z,
                "n_nonzorome": n_nz,
                "mean_zorome_diff": mean_z,
                "mean_nonzorome_diff": mean_nz,
                "correction": correction,
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["weekday", "group_key", "last_digit"]).reset_index(drop=True)


def build_correction_diagnosis(df_corr: pd.DataFrame) -> pd.DataFrame:
    if df_corr.empty:
        return df_corr
    out = df_corr.copy()
    out["signal_strength"] = out["correction"].abs()
    out["data_density"] = out["n_zorome"] + out["n_nonzorome"]
    return out


def build_realized_correction_timeseries(df_test: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (dt, wd, gk, digit), g in df_test.groupby(["date", "weekday", "group_key", "last_digit"], sort=True):
        z = g.loc[g["is_zorome"] == 1, "diff_coins_normalized"]
        nz = g.loc[g["is_zorome"] == 0, "diff_coins_normalized"]
        mean_z = float(z.mean()) if len(z) > 0 else np.nan
        mean_nz = float(nz.mean()) if len(nz) > 0 else np.nan
        corr = (mean_z - mean_nz) if (np.isfinite(mean_z) and np.isfinite(mean_nz)) else np.nan
        sign = "0"
        if np.isfinite(corr):
            if corr > 0:
                sign = "+"
            elif corr < 0:
                sign = "-"
        rows.append(
            {
                "date": pd.to_datetime(dt).strftime("%Y-%m-%d"),
                "weekday": wd,
                "last_digit": int(digit),
                "expert_group": str(gk),
                "n_zorome": int(len(z)),
                "n_nonzorome": int(len(nz)),
                "zorome_avg": mean_z,
                "nonzorome_avg": mean_nz,
                "correction": corr,
                "sign": sign,
            }
        )
    return pd.DataFrame(rows)


def _build_candidates(args: argparse.Namespace) -> tuple[list[Candidate], list[Candidate], list[float], list[float]]:
    cands_wed = [Candidate(w, l) for w in parse_csv_strs(args.windows_wed) for l in parse_csv_floats(args.lambdas_wed)]
    cands_non = [Candidate(w, l) for w in parse_csv_strs(args.windows_nonwed) for l in parse_csv_floats(args.lambdas_nonwed)]
    q_wed = parse_csv_floats(args.q_grid_wed)
    q_non = parse_csv_floats(args.q_grid_nonwed)
    return cands_wed, cands_non, q_wed, q_non


def _parse_model_params(args: argparse.Namespace) -> dict[str, Any]:
    model_params = _gpu_model_params(args.gpu_backend)
    if str(getattr(args, "model", "")).startswith("catboost"):
        model_params = {"task_type": "GPU", "devices": "0"}
    if getattr(args, "model_extra_json", ""):
        extra = json.loads(args.model_extra_json)
        if isinstance(extra, dict):
            model_params.update(extra)
    return model_params


def _target_topk_k(target_label: str) -> int:
    if target_label == "is_rank_1":
        return 1
    if target_label == "is_top_3":
        return 3
    if target_label == "is_worst_1":
        return 1
    return 2


def generate_test_predictions(data: pd.DataFrame, test_dates: list[pd.Timestamp], args: argparse.Namespace, model_params: dict[str, Any]) -> pd.DataFrame:
    if data.empty or not test_dates:
        return pd.DataFrame()

    cands_wed, cands_non, q_wed, q_non = _build_candidates(args)
    digit_lag_bundle_experts = set(parse_csv_strs(args.digit_lag_bundle_experts))
    rows: list[dict[str, Any]] = []

    for expert in EXPERT_ORDER:
        ds = data[data["group_key"].astype(str) == str(expert)].copy()
        if ds.empty:
            for dt in test_dates:
                for d in range(10):
                    rows.append({"date": dt, "expert": expert, "last_digit": d, "pred": 0.0, "status": "skip_no_group_data"})
            continue

        for dt in test_dates:
            is_wed = dt.day_name() == "Wednesday"
            result = _predict_for_date(
                df_expert=ds,
                pred_date=dt,
                candidates=(cands_wed if is_wed else cands_non),
                q_grid=(q_wed if is_wed else q_non),
                seed=int(args.seed),
                train_is_wed=is_wed,
                min_train_days=(args.min_train_days_wed if is_wed else args.min_train_days_nonwed),
                min_train_days_wed_recent60=int(args.min_train_days_wed_recent60),
                model_params=model_params,
                model_name=str(args.model),
                binary_mode=str(args.binary_mode),
                binary_threshold=float(args.binary_threshold),
                binary_c=float(args.binary_c),
                binary_max_iter=int(args.binary_max_iter),
                target_label=str(args.target_label),
                target_topk_k=_target_topk_k(str(args.target_label)),
                use_digit_lag_bundle=_should_use_digit_lag_bundle(enabled=bool(args.enable_digit_lag_bundle), allowed_experts=digit_lag_bundle_experts, expert=expert),
                use_2fn_weekday_patch=_should_use_2fn_weekday_patch(enabled=bool(args.enable_2fn_weekday_patch), expert=expert),
            )

            if result is None:
                rank_df = pd.DataFrame({"last_digit": list(range(10)), "pred": [0.0] * 10})
                status = "skip_no_train"
            else:
                _cand, _scores, rank_df, _span = result
                indeterminate, reason = _is_expert_indeterminate(rank_df, MIN_PRED_SPAN)
                status = f"flat:{reason}" if indeterminate else "ok"

            for _, r in rank_df.iterrows():
                rows.append({"date": dt, "expert": expert, "last_digit": int(r["last_digit"]), "pred": float(r["pred"]), "status": status})

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["date"] = pd.to_datetime(out["date"])
    out["rank"] = out.groupby(["date", "expert"], sort=False)["pred"].rank(ascending=False, method="first").astype(int)
    return out


def select_highest_confidence_expert(df_preds_day: pd.DataFrame) -> tuple[str, int, float] | None:
    candidates: list[tuple[float, float, float, str, int]] = []
    for expert in EXPERT_ORDER:
        ex_preds = df_preds_day[df_preds_day["expert"] == expert]
        if ex_preds.empty:
            continue
        ok_rows = ex_preds[ex_preds["status"] == "ok"].sort_values("pred", ascending=False)
        if ok_rows.empty:
            continue
        top1 = ok_rows.iloc[0]
        top2_pred = float(ok_rows.iloc[1]["pred"]) if len(ok_rows) >= 2 else float(top1["pred"])
        top1_pred = float(top1["pred"])
        margin = float(top1_pred - top2_pred)
        span = float(ok_rows["pred"].max() - ok_rows["pred"].min())
        candidates.append((margin, span, top1_pred, str(expert), int(top1["last_digit"])))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    best_margin, best_span, _best_top1, best_expert, best_digit = candidates[0]
    confidence = float(best_margin if np.isfinite(best_margin) else best_span)
    return best_expert, best_digit, confidence


def _lookup_correction(corr_table: pd.DataFrame, weekday: str, expert: str, digit: int) -> float:
    row = corr_table[
        (corr_table["weekday"] == weekday)
        & (corr_table["group_key"] == expert)
        & (corr_table["last_digit"] == int(digit))
    ]
    if row.empty:
        return float("nan")
    return float(row.iloc[0]["correction"])


def _direction_from_correction(corr: float) -> str:
    if not np.isfinite(corr):
        return "no_data"
    if corr > 0:
        return "prefer_zorome"
    if corr < 0:
        return "avoid_zorome"
    return "neutral"


def _pool_for(df_machines: pd.DataFrame, expert: str, digit: int) -> pd.DataFrame:
    return df_machines[(df_machines["group_key"] == expert) & (df_machines["last_digit"] == int(digit))].copy()


def _expected_return(pool: pd.DataFrame, rng: np.random.Generator, n_iter: int) -> float:
    vals = pool["diff_coins_normalized"].to_numpy(dtype=float)
    if len(vals) == 0:
        return float("nan")
    if n_iter <= 1:
        return float(vals.mean())
    draws = rng.choice(vals, size=int(n_iter), replace=True)
    return float(draws.mean())


def _candidate_digits_for_expert(df_preds_day: pd.DataFrame, expert: str, topk: int) -> list[int]:
    ex = df_preds_day[(df_preds_day["expert"] == expert) & (df_preds_day["status"] == "ok")].sort_values("pred", ascending=False)
    if ex.empty:
        return []
    return [int(x) for x in ex.head(max(1, int(topk)))["last_digit"].tolist()]


def _choose_participation_digit(strategy: str, candidate_digits: list[int], expert: str, weekday: str, corr_table: pd.DataFrame) -> tuple[int | None, float]:
    if not candidate_digits:
        return None, float("nan")
    for d in candidate_digits:
        corr = _lookup_correction(corr_table, weekday=weekday, expert=expert, digit=d)
        if strategy == "D" and np.isfinite(corr) and corr > 0:
            return d, corr
        if strategy == "E" and np.isfinite(corr) and corr >= 0:
            return d, corr
        if strategy == "F" and np.isfinite(corr) and corr <= 0:
            return d, corr
    return None, float("nan")


def _simulate_day(df_machines: pd.DataFrame, df_preds_day: pd.DataFrame, corr_table: pd.DataFrame, n_iter: int, rng: np.random.Generator, topk: int) -> dict[str, Any]:
    date = pd.to_datetime(df_machines["date"].iloc[0])
    weekday = str(df_machines["weekday"].iloc[0])
    base: dict[str, Any] = {
        "date": date,
        "weekday": weekday,
        "status": "ok",
        "expert_used": None,
        "target_digit": None,
        "expert_confidence": np.nan,
    }

    selection = select_highest_confidence_expert(df_preds_day)
    if selection is None:
        base["status"] = "no_valid_expert"
        return base

    expert, target_digit, conf = selection
    base["expert_used"] = expert
    base["target_digit"] = int(target_digit)
    base["expert_confidence"] = float(conf)

    pool_base = _pool_for(df_machines, expert, target_digit)
    if pool_base.empty:
        base["status"] = "no_pool_in_expert_digit"
        return base

    corr = _lookup_correction(corr_table, weekday=weekday, expert=expert, digit=target_digit)
    direction = _direction_from_correction(corr)
    pool_a = pool_base
    if direction == "prefer_zorome":
        pool_b = pool_base[pool_base["is_zorome"] == 1].copy()
        if pool_b.empty:
            pool_b = pool_base
    else:
        pool_b = pool_base
    pool_c = pool_base[pool_base["is_zorome"] == 0].copy()
    if pool_c.empty:
        pool_c = pool_base

    base.update(
        {
            "correction_target": corr,
            "correction_direction": direction,
            "n_machines_A": int(len(pool_a)),
            "n_machines_B": int(len(pool_b)),
            "n_machines_C": int(len(pool_c)),
            "ret_A": _expected_return(pool_a, rng, n_iter),
            "ret_B": _expected_return(pool_b, rng, n_iter),
            "ret_C": _expected_return(pool_c, rng, n_iter),
        }
    )

    cand_digits = _candidate_digits_for_expert(df_preds_day, expert=expert, topk=topk)
    for strategy in ("D", "E", "F"):
        chosen_digit, chosen_corr = _choose_participation_digit(strategy, cand_digits, expert=expert, weekday=weekday, corr_table=corr_table)
        if chosen_digit is None:
            base[f"participated_{strategy}"] = 0
            base[f"digit_{strategy}"] = np.nan
            base[f"correction_{strategy}"] = np.nan
            base[f"ret_{strategy}"] = np.nan
            continue
        pool = _pool_for(df_machines, expert, chosen_digit)
        if pool.empty:
            base[f"participated_{strategy}"] = 0
            base[f"digit_{strategy}"] = chosen_digit
            base[f"correction_{strategy}"] = chosen_corr
            base[f"ret_{strategy}"] = np.nan
            continue
        base[f"participated_{strategy}"] = 1
        base[f"digit_{strategy}"] = int(chosen_digit)
        base[f"correction_{strategy}"] = float(chosen_corr) if np.isfinite(chosen_corr) else np.nan
        base[f"ret_{strategy}"] = _expected_return(pool, rng, n_iter)

    return base


def _paired_cohens_d(x: np.ndarray, y: np.ndarray) -> float:
    d = np.asarray(y, dtype=float) - np.asarray(x, dtype=float)
    d = d[np.isfinite(d)]
    if len(d) < 2:
        return float("nan")
    sd = float(np.std(d, ddof=1))
    if sd <= 0:
        return float("nan")
    return float(np.mean(d) / sd)


def _wilcoxon_paired(x: np.ndarray, y: np.ndarray) -> float:
    dx = np.asarray(y, dtype=float) - np.asarray(x, dtype=float)
    dx = dx[np.isfinite(dx) & (np.abs(dx) > 0)]
    if len(dx) == 0:
        return float("nan")
    try:
        _st, p = wilcoxon(dx, alternative="two-sided", zero_method="wilcox")
        return float(p)
    except ValueError:
        return float("nan")


def _holm_adjust(named_pvalues: dict[str, float]) -> dict[str, float]:
    valid = [(k, v) for k, v in named_pvalues.items() if np.isfinite(v)]
    if not valid:
        return {k: float("nan") for k in named_pvalues}
    valid.sort(key=lambda x: x[1])
    m = len(valid)
    adjusted: dict[str, float] = {}
    running_max = 0.0
    for i, (name, pval) in enumerate(valid, start=1):
        adj = min(1.0, (m - i + 1) * float(pval))
        running_max = max(running_max, adj)
        adjusted[name] = running_max
    out = {k: float("nan") for k in named_pvalues}
    out.update(adjusted)
    return out


def _max_drawdown(series: np.ndarray) -> float:
    if len(series) == 0:
        return float("nan")
    c = np.cumsum(series)
    peak = np.maximum.accumulate(c)
    dd = c - peak
    return float(dd.min())


def _sortino_ratio(series: np.ndarray) -> float:
    if len(series) == 0:
        return float("nan")
    downside = series[series < 0]
    if len(downside) == 0:
        return float("nan")
    denom = float(np.std(downside, ddof=0))
    if denom <= 0:
        return float("nan")
    return float(np.mean(series) / denom)


def summarize_phase1(df_daily: pd.DataFrame, train_window: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    total_days = int(len(df_daily))
    rows: list[dict[str, Any]] = []
    for s in ("A", "B", "C"):
        ret = pd.to_numeric(df_daily[f"ret_{s}"], errors="coerce")
        participated = ret.notna()
        per_bet = ret[participated]
        per_day = ret.fillna(0.0)
        rows.append(
            {
                "train_window": str(train_window),
                "category": "phase1_machine_selection",
                "strategy": s,
                "n_total_days": total_days,
                "n_days_participated": int(participated.sum()),
                "coverage": float(participated.mean()) if total_days > 0 else np.nan,
                "mean_diff_per_bet": float(per_bet.mean()) if len(per_bet) > 0 else np.nan,
                "win_rate_per_bet": float((per_bet > 0).mean()) if len(per_bet) > 0 else np.nan,
                "median_diff_per_bet": float(per_bet.median()) if len(per_bet) > 0 else np.nan,
                "mean_diff_per_day": float(per_day.mean()) if total_days > 0 else np.nan,
                "effective_win_rate": float((per_day > 0).mean()) if total_days > 0 else np.nan,
            }
        )

    a = pd.to_numeric(df_daily["ret_A"], errors="coerce").to_numpy(dtype=float)
    b = pd.to_numeric(df_daily["ret_B"], errors="coerce").to_numpy(dtype=float)
    c = pd.to_numeric(df_daily["ret_C"], errors="coerce").to_numpy(dtype=float)
    pvals = {
        "B_vs_A": _wilcoxon_paired(a, b),
        "C_vs_A": _wilcoxon_paired(a, c),
        "B_vs_C": _wilcoxon_paired(c, b),
    }
    padj = _holm_adjust(pvals)
    pairs = {
        "train_window": str(train_window),
        "wilcoxon_p_B_vs_A": pvals["B_vs_A"],
        "wilcoxon_p_C_vs_A": pvals["C_vs_A"],
        "wilcoxon_p_B_vs_C": pvals["B_vs_C"],
        "holm_adj_p_B_vs_A": padj["B_vs_A"],
        "holm_adj_p_C_vs_A": padj["C_vs_A"],
        "holm_adj_p_B_vs_C": padj["B_vs_C"],
        "cohens_d_B_vs_A": _paired_cohens_d(a, b),
        "cohens_d_C_vs_A": _paired_cohens_d(a, c),
        "cohens_d_B_vs_C": _paired_cohens_d(c, b),
    }
    return rows, pairs


def summarize_phase2(df_daily: pd.DataFrame, train_window: str) -> list[dict[str, Any]]:
    total_days = int(len(df_daily))
    rows: list[dict[str, Any]] = []
    for s in ("D", "E", "F"):
        part = pd.to_numeric(df_daily[f"participated_{s}"], errors="coerce").fillna(0).astype(int)
        ret = pd.to_numeric(df_daily[f"ret_{s}"], errors="coerce")
        per_bet = ret[part == 1].dropna()
        per_day = ret.where(part == 1, 0.0).fillna(0.0)
        rows.append(
            {
                "train_window": str(train_window),
                "category": "phase2_participation",
                "strategy": s,
                "n_total_days": total_days,
                "n_days_participated": int(part.sum()),
                "coverage": float(part.mean()) if total_days > 0 else np.nan,
                "mean_diff_per_bet": float(per_bet.mean()) if len(per_bet) > 0 else np.nan,
                "win_rate_per_bet": float((per_bet > 0).mean()) if len(per_bet) > 0 else np.nan,
                "median_diff_per_bet": float(per_bet.median()) if len(per_bet) > 0 else np.nan,
                "mean_diff_per_calendar_day": float(per_day.mean()) if total_days > 0 else np.nan,
                "effective_win_rate": float((per_day > 0).mean()) if total_days > 0 else np.nan,
                "max_drawdown": _max_drawdown(per_day.to_numpy(dtype=float)),
                "sortino_ratio": _sortino_ratio(per_day.to_numpy(dtype=float)),
            }
        )
    return rows


def _resolve_db_path_with_fallback(args: argparse.Namespace) -> Path:
    raw = str(args.db_path).strip()
    if raw:
        p = Path(raw)
        if not p.exists():
            raise FileNotFoundError(f"DB path does not exist: {p}")
        return p
    logger.warning("--db-path is empty, falling back to --db-glob=%s", args.db_glob)
    return resolve_db_path("", pattern=str(args.db_glob))


def _format_num(v: Any) -> str:
    if v is None:
        return "NA"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v)
    if not np.isfinite(x):
        return "NA"
    return f"{x:.4f}"


def _print_phase1_window_summary(train_window: str, strategy_rows: list[dict[str, Any]], pair: dict[str, Any]) -> None:
    s_map = {r["strategy"]: r for r in strategy_rows}
    print(f"[Phase1 window={train_window}] A/B/C")
    for s in ("A", "B", "C"):
        r = s_map[s]
        print(
            f"  {s}: mean/day={_format_num(r['mean_diff_per_day'])} "
            f"mean/bet={_format_num(r['mean_diff_per_bet'])} coverage={_format_num(100.0 * r['coverage'])}%"
        )
    print(
        "  p(raw): "
        f"BvsA={_format_num(pair['wilcoxon_p_B_vs_A'])}, "
        f"CvsA={_format_num(pair['wilcoxon_p_C_vs_A'])}, "
        f"BvsC={_format_num(pair['wilcoxon_p_B_vs_C'])}"
    )


def run_simulation(args: argparse.Namespace) -> dict[str, Path]:
    db_path = _resolve_db_path_with_fallback(args)
    logger.info("DB path: %s", db_path)

    df_m = load_machine_level_data(db_path)
    sim_start, sim_end = define_window(df_m, window_days=int(args.window_days))
    logger.info("Simulation window: %s - %s", sim_start.date(), sim_end.date())
    df_test = df_m[(df_m["date"] >= sim_start) & (df_m["date"] <= sim_end)].copy()
    if df_test.empty:
        raise ValueError("No test rows in simulation window.")

    split_data, source_latest, target_date = _prepare_split_dataset(
        db_path=str(db_path),
        db_glob=str(args.db_glob),
        a_weight=float(args.a_weight),
        non_a_weight=float(args.non_a_weight),
        enable_digit_lag_bundle=bool(args.enable_digit_lag_bundle),
    )
    logger.info("Prepared split dataset: source_latest=%s target_date=%s", source_latest.date(), target_date.date())

    test_dates = sorted(pd.to_datetime(df_test["date"]).drop_duplicates().tolist())
    model_params = _parse_model_params(args)
    logger.info("Model params (GPU-priority): %s", model_params)
    preds = generate_test_predictions(split_data, test_dates=test_dates, args=args, model_params=model_params)

    train_windows = [w.strip() for w in str(args.train_window_days).split(",") if w.strip()]
    if not train_windows:
        train_windows = ["60"]

    start_s = sim_start.strftime("%Y%m%d")
    end_s = sim_end.strftime("%Y%m%d")
    out_base = Path(f"{args.output_prefix}_{start_s}_{end_s}")
    out_base.parent.mkdir(parents=True, exist_ok=True)

    realized_ts = build_realized_correction_timeseries(df_test)
    realized_ts_path = out_base.with_name(out_base.name + "_realized_correction_timeseries.csv")
    realized_ts.to_csv(realized_ts_path, index=False, encoding="utf-8")

    phase1_all_daily: list[pd.DataFrame] = []
    phase1_summary_rows: list[dict[str, Any]] = []
    phase1_pairs_rows: list[dict[str, Any]] = []
    window_to_corr: dict[str, pd.DataFrame] = {}

    for tw in train_windows:
        df_train = _slice_train(df_m, sim_start=sim_start, train_window=tw)
        corr = compute_zorome_correction_table(df_train, min_zorome_n=int(args.min_zorome_train_n), min_nonzorome_n=int(args.min_nonzorome_train_n))
        window_to_corr[tw] = corr
        diag = build_correction_diagnosis(corr)
        diag_path = out_base.with_name(out_base.name + f"_correction_table_diagnosis_{tw}.csv")
        diag.to_csv(diag_path, index=False, encoding="utf-8")

        rng = np.random.default_rng(int(args.seed))
        daily_rows: list[dict[str, Any]] = []
        for dt in test_dates:
            day_m = df_test[df_test["date"] == dt].copy()
            day_p = preds[preds["date"] == dt].copy() if not preds.empty else pd.DataFrame()
            daily_rows.append(_simulate_day(day_m, day_p, corr, int(args.n_iter), rng, int(args.participation_topk)))

        daily = pd.DataFrame(daily_rows)
        daily["date"] = pd.to_datetime(daily["date"]).dt.strftime("%Y-%m-%d")
        daily["train_window"] = str(tw)
        phase1_all_daily.append(daily)
        s_rows, p_row = summarize_phase1(daily, tw)
        phase1_summary_rows.extend(s_rows)
        phase1_pairs_rows.append(p_row)
        _print_phase1_window_summary(tw, s_rows, p_row)

    phase1_daily = pd.concat(phase1_all_daily, ignore_index=True) if phase1_all_daily else pd.DataFrame()
    phase1_summary = pd.DataFrame(phase1_summary_rows)
    phase1_pairs = pd.DataFrame(phase1_pairs_rows)

    phase2_window = str(args.phase2_train_window)
    if phase2_window.lower() == "auto":
        b_rows = phase1_summary[phase1_summary["strategy"] == "B"].copy().sort_values("mean_diff_per_day", ascending=False)
        phase2_window = str(b_rows.iloc[0]["train_window"]) if not b_rows.empty else str(train_windows[0])
    logger.info("Phase2 selected train window: %s", phase2_window)

    corr_phase2 = window_to_corr.get(phase2_window)
    if corr_phase2 is None:
        corr_phase2 = compute_zorome_correction_table(
            _slice_train(df_m, sim_start=sim_start, train_window=phase2_window),
            min_zorome_n=int(args.min_zorome_train_n),
            min_nonzorome_n=int(args.min_nonzorome_train_n),
        )

    rng2 = np.random.default_rng(int(args.seed))
    phase2_daily_rows: list[dict[str, Any]] = []
    for dt in test_dates:
        day_m = df_test[df_test["date"] == dt].copy()
        day_p = preds[preds["date"] == dt].copy() if not preds.empty else pd.DataFrame()
        phase2_daily_rows.append(_simulate_day(day_m, day_p, corr_phase2, int(args.n_iter), rng2, int(args.participation_topk)))
    phase2_daily = pd.DataFrame(phase2_daily_rows)
    phase2_daily["date"] = pd.to_datetime(phase2_daily["date"]).dt.strftime("%Y-%m-%d")
    phase2_daily["train_window"] = phase2_window
    phase2_summary = pd.DataFrame(summarize_phase2(phase2_daily, phase2_window))

    phase1_matrix = phase1_summary.pivot(index="train_window", columns="strategy", values="mean_diff_per_day").reset_index()

    out_paths = {
        "phase1_daily": out_base.with_name(out_base.name + "_phase1_daily.csv"),
        "phase1_summary": out_base.with_name(out_base.name + "_phase1_summary.csv"),
        "phase1_pairs": out_base.with_name(out_base.name + "_phase1_pairwise.csv"),
        "phase1_matrix": out_base.with_name(out_base.name + "_phase1_strategy_matrix.csv"),
        "phase2_daily": out_base.with_name(out_base.name + "_phase2_daily.csv"),
        "phase2_summary": out_base.with_name(out_base.name + "_phase2_summary.csv"),
        "realized_ts": realized_ts_path,
    }
    phase1_daily.to_csv(out_paths["phase1_daily"], index=False, encoding="utf-8")
    phase1_summary.to_csv(out_paths["phase1_summary"], index=False, encoding="utf-8")
    phase1_pairs.to_csv(out_paths["phase1_pairs"], index=False, encoding="utf-8")
    phase1_matrix.to_csv(out_paths["phase1_matrix"], index=False, encoding="utf-8")
    phase2_daily.to_csv(out_paths["phase2_daily"], index=False, encoding="utf-8")
    phase2_summary.to_csv(out_paths["phase2_summary"], index=False, encoding="utf-8")

    for key, p in out_paths.items():
        logger.info("Wrote %s: %s", key, p)
    return out_paths


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.log_level)
    run_simulation(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
