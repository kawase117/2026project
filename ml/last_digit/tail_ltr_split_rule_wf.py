from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.last_digit import tail_time_adaptive_ltr_poc_improved as improved
from ml.last_digit.tail_ltr_full_walkforward_ops import (
    bootstrap_ci,
    build_train_window,
    topk_day_table,
    train_and_predict_fold,
)
from ml.last_digit.utils import (
    BOOTSTRAP_SEED_SPLIT_RULE,
    configure_logging,
    parse_csv_floats,
    parse_csv_ints,
    parse_csv_strs,
    resolve_db_path,
    summarize_array,
)

logger = logging.getLogger(__name__)


@dataclass
class Candidate:
    window_name: str
    decay_lambda: float


def normalize_last_digit(x: Any) -> str:
    s = str(x)
    if s in {"11", "ゾロ目", "ｿﾞﾛ目", "ぞろ目"}:
        return "ゾロ目"
    return s


def _days_since_last_positive(dates: pd.Series, flags: pd.Series) -> pd.Series:
    out: list[float] = []
    last_positive: pd.Timestamp | None = None
    for current_date, flag in zip(pd.to_datetime(dates), flags, strict=False):
        if last_positive is None:
            out.append(999.0)
        else:
            out.append(float((current_date - last_positive).days))
        if int(flag) == 1:
            last_positive = current_date
    return pd.Series(out, index=flags.index, dtype=float)


def build_base_rows(*, db_path: Path, a_weight: float, non_a_weight: float) -> pd.DataFrame:
    con = sqlite3.connect(str(db_path))
    q = """
    SELECT
      m.date,
      m.machine_number,
      m.machine_name,
      m.last_digit,
      m.games_normalized,
      m.diff_coins_normalized,
      COALESCE(mm.jug_flag, 0) AS jug_flag,
      COALESCE(mm.hana_flag, 0) AS hana_flag,
      COALESCE(mm.bt_flag, 0) AS bt_flag,
      COALESCE(dh.is_any_event, 0) AS is_event_day
    FROM machine_detailed_results m
    LEFT JOIN machine_master mm
      ON m.machine_name = mm.machine_name_normalized
    LEFT JOIN daily_hall_summary dh
      ON m.date = dh.date
    """
    df = pd.read_sql_query(q, con)
    con.close()
    if df.empty:
        raise ValueError("No rows from machine_detailed_results")

    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["last_digit"] = df["last_digit"].map(normalize_last_digit)
    df["floor_head"] = df["machine_number"].astype(str).str[0]
    df = df[df["floor_head"].isin(["2", "3"])].copy()
    df["floor_bucket"] = df["floor_head"] + "F"
    df["is_a_type"] = ((df["jug_flag"] == 1) | (df["hana_flag"] == 1) | (df["bt_flag"] == 1)).astype(int)
    df["atype_bucket"] = np.where(df["is_a_type"] == 1, "A", "N")
    df["row_weight"] = np.where(df["is_a_type"] == 1, float(a_weight), float(non_a_weight))
    df["diff_focus"] = pd.to_numeric(df["diff_coins_normalized"], errors="coerce").fillna(0.0) * df["row_weight"]
    df["win_flag"] = (pd.to_numeric(df["diff_coins_normalized"], errors="coerce").fillna(0.0) > 0).astype(float)
    return df


def aggregate_mode(raw: pd.DataFrame, *, mode: str) -> pd.DataFrame:
    df = raw.copy()
    if mode == "global11":
        df["group_key"] = "ALL"
    elif mode == "floor2":
        df["group_key"] = df["floor_bucket"]
    elif mode == "floor_atype4":
        df["group_key"] = df["floor_bucket"] + "_" + df["atype_bucket"]
    else:
        raise ValueError(f"Unsupported mode: {mode}")

    df["entity_key"] = df["group_key"] + "|" + df["last_digit"].astype(str)
    agg = (
        df.groupby(["date", "group_key", "entity_key", "last_digit"], sort=True)
        .agg(
            machine_count=("machine_number", "count"),
            total_games=("games_normalized", "sum"),
            avg_games=("games_normalized", "mean"),
            total_diff_coins=("diff_coins_normalized", "sum"),
            total_diff_coins_focus=("diff_focus", "sum"),
            avg_diff_coins=("diff_coins_normalized", "mean"),
            win_rate=("win_flag", "mean"),
            is_event_day=("is_event_day", "max"),
            non_a_ratio=("is_a_type", lambda s: float((1.0 - s.astype(float)).mean())),
        )
        .reset_index()
    )
    agg["efficiency"] = (agg["total_diff_coins"] / agg["total_games"].replace(0, np.nan)).fillna(0.0)
    agg["efficiency_focus"] = (agg["total_diff_coins_focus"] / agg["total_games"].replace(0, np.nan)).fillna(0.0)
    agg = agg.sort_values(["entity_key", "date"]).reset_index(drop=True)

    # Hall-cross digit-level lag signals (complementary to entity_key-level lags).
    # Leakage-safe: use shift(lag), so same-day values are never used as features.
    digit_lags = [1, 2, 5, 6, 7, 14, 15]
    hall_digit_daily = (
        agg.groupby(["date", "last_digit"], sort=True)["total_diff_coins"]
        .mean()
        .reset_index()
        .rename(columns={"total_diff_coins": "hall_digit_mean_diff"})
        .sort_values(["last_digit", "date"])
        .reset_index(drop=True)
    )
    for lag in digit_lags:
        hall_digit_daily[f"lag{lag}_hall_digit_diff"] = (
            hall_digit_daily.groupby("last_digit", sort=False)["hall_digit_mean_diff"]
            .shift(lag)
            .fillna(0.0)
        )
    lag_cols = [f"lag{lag}_hall_digit_diff" for lag in digit_lags]
    agg["last_digit"] = agg["last_digit"].astype(str)
    hall_digit_daily["last_digit"] = hall_digit_daily["last_digit"].astype(str)
    agg = agg.merge(
        hall_digit_daily[["date", "last_digit", *lag_cols]],
        on=["date", "last_digit"],
        how="left",
    )
    for col in lag_cols:
        agg[col] = pd.to_numeric(agg[col], errors="coerce").fillna(0.0)

    # Targets across entity_key per date (descending=best, ascending=worst).
    rk_desc = agg.groupby(["date", "group_key"], sort=False)["total_diff_coins"].rank(method="first", ascending=False)
    rk_asc = agg.groupby(["date", "group_key"], sort=False)["total_diff_coins"].rank(method="first", ascending=True)
    agg["is_rank_1"] = (rk_desc == 1).astype(int)
    agg["is_top_2"] = (rk_desc <= 2).astype(int)
    agg["is_top_3"] = (rk_desc <= 3).astype(int)
    agg["is_worst_1"] = (rk_asc == 1).astype(int)
    agg["is_worst_3"] = (rk_asc <= 3).astype(int)
    return agg


def add_simple_features(df: pd.DataFrame, *, enable_digit_lag_bundle: bool = False) -> pd.DataFrame:
    out = df.copy()
    out["weekday"] = out["date"].dt.weekday.astype(int)
    out["weekday_sin"] = np.sin(2.0 * np.pi * out["weekday"] / 7.0)
    out["weekday_cos"] = np.cos(2.0 * np.pi * out["weekday"] / 7.0)
    out["is_wed"] = (out["weekday"] == 2).astype(int)

    for col in ("total_diff_coins", "total_diff_coins_focus", "total_games", "efficiency", "efficiency_focus", "win_rate"):
        out[f"lag1_{col}"] = out.groupby("entity_key", sort=False)[col].shift(1).fillna(0.0)
        out[f"lag7_{col}"] = out.groupby("entity_key", sort=False)[col].shift(7).fillna(0.0)
        out[f"lag14_{col}"] = out.groupby("entity_key", sort=False)[col].shift(14).fillna(0.0)
        out[f"roll7_{col}"] = (
            out.groupby("entity_key", sort=False)[col]
            .transform(lambda s: s.shift(1).rolling(7, min_periods=1).mean())
            .fillna(0.0)
        )
        out[f"roll14_{col}"] = (
            out.groupby("entity_key", sort=False)[col]
            .transform(lambda s: s.shift(1).rolling(14, min_periods=1).mean())
            .fillna(0.0)
        )
        out[f"roll28_{col}"] = (
            out.groupby("entity_key", sort=False)[col]
            .transform(lambda s: s.shift(1).rolling(28, min_periods=1).mean())
            .fillna(0.0)
        )

    out["prior_top2_rate"] = (
        out.groupby("entity_key", sort=False)["is_top_2"]
        .transform(lambda s: s.shift(1).expanding(min_periods=1).mean())
        .fillna(0.0)
    )
    day_gap_parts: list[pd.Series] = []
    for _, group in out.groupby("entity_key", sort=False):
        day_gap_parts.append(_days_since_last_positive(group["date"], group["is_top_2"]))
    out["days_since_last_top2"] = pd.concat(day_gap_parts).sort_index().fillna(999.0)
    out["weekday_prior_top2_rate"] = (
        out.groupby(["entity_key", "weekday"], sort=False)["is_top_2"]
        .transform(lambda s: s.shift(1).expanding(min_periods=1).mean())
        .fillna(0.0)
    )
    out["prior_mean_diff"] = (
        out.groupby("entity_key", sort=False)["total_diff_coins"]
        .transform(lambda s: s.shift(1).expanding(min_periods=1).mean())
        .fillna(0.0)
    )
    out["weekday_delta_from_mean"] = out["weekday_prior_top2_rate"] - out["prior_top2_rate"]
    # Lightweight weekday interaction candidates (used optionally per-expert).
    out["wed_x_weekday_delta"] = out["is_wed"] * out["weekday_delta_from_mean"]
    out["wed_x_days_since_last_top2"] = out["is_wed"] * out["days_since_last_top2"]

    # total_diff_coins_deficit: 直近7日の累積差枚 vs 長期28日ペースの乖離
    # 負の大きな値 = 出玉不足の蓄積 = 仕込み候補シグナル
    # roll7/roll28 はすでに shift(1) 済みのためリーク不要
    out["total_diff_coins_deficit"] = (
        out["roll7_total_diff_coins_focus"]
        - out["roll28_total_diff_coins_focus"] / 28.0 * 7.0
    ).fillna(0.0)

    if enable_digit_lag_bundle:
        # Optional hall-cross digit lag bundle (leakage-safe by construction in aggregate_mode shift).
        # Keep default OFF to preserve strict v2 baseline behavior.
        for lag in (1, 5, 7):
            src = f"lag{lag}_hall_digit_diff"
            dst = f"lag{lag}_digit_diff"
            out[dst] = pd.to_numeric(out.get(src, 0.0), errors="coerce").fillna(0.0)

    return out


def eval_candidate_custom(
    *,
    dataset: pd.DataFrame,
    features: list[str],
    seed: int,
    candidate: Candidate,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    q_grid: list[float],
    train_is_wed: bool,
    test_is_wed: bool,
    min_train_days: int,
    diff_col: str,
    model_params: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    dts = pd.to_datetime(dataset["date"])
    tr_start, tr_end = build_train_window(candidate.window_name, test_start)
    train = dataset[(dts >= tr_start) & (dts <= tr_end)].copy()
    test = dataset[(dts >= test_start) & (dts <= test_end)].copy()

    train_w = pd.to_datetime(train["date"]).dt.day_name().eq("Wednesday")
    test_w = pd.to_datetime(test["date"]).dt.day_name().eq("Wednesday")
    train = train[train_w if train_is_wed else ~train_w].copy()
    test = test[test_w if test_is_wed else ~test_w].copy()
    if train["date"].nunique() < min_train_days or test.empty:
        return None

    # Align evaluation payoff column with topk_day_table's expected diff column.
    if diff_col != "total_diff_coins":
        if diff_col not in train.columns or diff_col not in test.columns:
            return None
        train["total_diff_coins"] = pd.to_numeric(train[diff_col], errors="coerce").fillna(0.0)
        test["total_diff_coins"] = pd.to_numeric(test[diff_col], errors="coerce").fillna(0.0)

    cal_df, tst_df, choice = train_and_predict_fold(
        train_df=train,
        test_df=test,
        target="is_top_2",
        features=features,
        decay_lambda=candidate.decay_lambda,
        random_state=seed,
        model_params=model_params or {},
        temperature_candidates=improved.CalibrationConfig().temperature_candidates,
        blend_weights=improved.CalibrationConfig().blend_weights,
        q_grid=q_grid,
        k=2,
    )
    cal_day = topk_day_table(cal_df, "pred", k=2, diff_col="total_diff_coins", mc_col="machine_count")
    tst_day = topk_day_table(tst_df, "pred", k=2, diff_col="total_diff_coins", mc_col="machine_count")
    keep_c = cal_day["margin"] >= choice["threshold"]
    keep_t = tst_day["margin"] >= choice["threshold"]
    cal_ex = np.where(keep_c.to_numpy(), cal_day["excess"].to_numpy(), 0.0)
    tst_ex = np.where(keep_t.to_numpy(), tst_day["excess"].to_numpy(), 0.0)
    tst_day = tst_day.copy()
    tst_day["excess_played"] = tst_ex
    return {
        "candidate": candidate,
        "choice": choice,
        "cal_score": float(np.mean(cal_ex)),
        "test_day": tst_day,
    }


def _select_best_wed_non_candidates(
    *,
    dataset: pd.DataFrame,
    features: list[str],
    seed: int,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    candidates_wed: list[Candidate],
    candidates_nonwed: list[Candidate],
    q_grid_wed: list[float],
    q_grid_nonwed: list[float],
    min_train_days_wed: int,
    min_train_days_nonwed: int,
    diff_col: str,
    model_params: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    wed_rows = []
    for cand in candidates_wed:
        result = eval_candidate_custom(
            dataset=dataset,
            features=features,
            seed=seed,
            candidate=cand,
            test_start=test_start,
            test_end=test_end,
            q_grid=q_grid_wed,
            train_is_wed=True,
            test_is_wed=True,
            min_train_days=min_train_days_wed,
            diff_col=diff_col,
            model_params=model_params,
        )
        if result is not None:
            wed_rows.append(result)

    non_rows = []
    for cand in candidates_nonwed:
        result = eval_candidate_custom(
            dataset=dataset,
            features=features,
            seed=seed,
            candidate=cand,
            test_start=test_start,
            test_end=test_end,
            q_grid=q_grid_nonwed,
            train_is_wed=False,
            test_is_wed=False,
            min_train_days=min_train_days_nonwed,
            diff_col=diff_col,
            model_params=model_params,
        )
        if result is not None:
            non_rows.append(result)

    if not wed_rows or not non_rows:
        return None, None
    best_wed = sorted(wed_rows, key=lambda x: x["cal_score"], reverse=True)[0]
    best_non = sorted(non_rows, key=lambda x: x["cal_score"], reverse=True)[0]
    return best_wed, best_non


def run_mode(
    *,
    dataset: pd.DataFrame,
    seeds: list[int],
    test_days: int,
    warmup_days: int,
    min_train_days_wed: int,
    min_train_days_nonwed: int,
    candidates_wed: list[Candidate],
    candidates_nonwed: list[Candidate],
    q_grid_wed: list[float],
    q_grid_nonwed: list[float],
    diff_col: str,
    model_params: dict[str, Any] | None = None,
    max_blocks: int = 0,
    n_boot: int = 10000,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    d = dataset.sort_values("date").reset_index(drop=True)
    valid_cfg = improved.build_fixed_split_configs(d)["regime_3_fixed_split"]
    valid_dates = sorted(pd.to_datetime(d["date"].unique()))
    valid_dates = [x for x in valid_dates if pd.Timestamp(valid_cfg["valid_start"]) <= x <= pd.Timestamp(valid_cfg["valid_end"])]
    features = improved.get_numeric_features(d)
    features = [f for f in features if f not in {"is_top_2"}]

    rows: list[dict[str, Any]] = []
    for seed in seeds:
        idx = max(0, warmup_days)
        block_count = 0
        while idx < len(valid_dates):
            if max_blocks > 0 and block_count >= max_blocks:
                break
            test_start = valid_dates[idx]
            block = valid_dates[idx : idx + test_days]
            if not block:
                break
            test_end = block[-1]

            bw, bn = _select_best_wed_non_candidates(
                dataset=d,
                features=features,
                seed=seed,
                test_start=test_start,
                test_end=test_end,
                candidates_wed=candidates_wed,
                candidates_nonwed=candidates_nonwed,
                q_grid_wed=q_grid_wed,
                q_grid_nonwed=q_grid_nonwed,
                min_train_days_wed=min_train_days_wed,
                min_train_days_nonwed=min_train_days_nonwed,
                diff_col=diff_col,
                model_params=model_params,
            )
            if bw is None or bn is None:
                idx += test_days
                continue
            td = pd.concat([bw["test_day"], bn["test_day"]], ignore_index=True).sort_values("date")
            td["weekday"] = pd.to_datetime(td["date"]).dt.day_name()
            for _, r in td.iterrows():
                rows.append(
                    {
                        "seed": seed,
                        "date": str(r["date"]),
                        "weekday": r["weekday"],
                        "excess": float(r["excess_played"]),
                    }
                )
            idx += test_days
            block_count += 1

    day_df = pd.DataFrame(rows)
    if day_df.empty:
        summary = {
            "overall": {"mean": 0.0, "std": 0.0, "n_days": 0, "ci_low": 0.0, "ci_high": 0.0, "p_gt_0": 0.5},
            "wednesday_only": {"mean": 0.0, "std": 0.0, "n_days": 0, "ci_low": 0.0, "ci_high": 0.0, "p_gt_0": 0.5},
            "non_wednesday": {"mean": 0.0, "std": 0.0, "n_days": 0, "ci_low": 0.0, "ci_high": 0.0, "p_gt_0": 0.5},
        }
        return day_df, summary

    arr = day_df["excess"].to_numpy(dtype=float)
    wed = day_df.loc[day_df["weekday"].eq("Wednesday"), "excess"].to_numpy(dtype=float)
    non = day_df.loc[~day_df["weekday"].eq("Wednesday"), "excess"].to_numpy(dtype=float)
    summary = {
        "overall": {**summarize_array(arr), **bootstrap_ci(arr, n_boot=n_boot, seed=BOOTSTRAP_SEED_SPLIT_RULE)},
        "wednesday_only": {**summarize_array(wed), **bootstrap_ci(wed, n_boot=n_boot, seed=BOOTSTRAP_SEED_SPLIT_RULE)},
        "non_wednesday": {**summarize_array(non), **bootstrap_ci(non, n_boot=n_boot, seed=BOOTSTRAP_SEED_SPLIT_RULE)},
    }
    return day_df, summary


def run_mode_moe4_gate(
    *,
    dataset: pd.DataFrame,
    seeds: list[int],
    test_days: int,
    warmup_days: int,
    min_train_days_wed: int,
    min_train_days_nonwed: int,
    candidates_wed: list[Candidate],
    candidates_nonwed: list[Candidate],
    q_grid_wed: list[float],
    q_grid_nonwed: list[float],
    diff_col: str,
    non_a_gate_weight: float,
    a_gate_weight: float,
    model_params: dict[str, Any] | None = None,
    max_blocks: int = 0,
    n_boot: int = 10000,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    d = dataset.sort_values("date").reset_index(drop=True)
    if "group_key" not in d.columns:
        raise ValueError("run_mode_moe4_gate requires group_key column (use floor_atype4 dataset).")
    experts = sorted(d["group_key"].dropna().astype(str).unique().tolist())

    valid_cfg = improved.build_fixed_split_configs(d)["regime_3_fixed_split"]
    valid_dates = sorted(pd.to_datetime(d["date"].unique()))
    valid_dates = [x for x in valid_dates if pd.Timestamp(valid_cfg["valid_start"]) <= x <= pd.Timestamp(valid_cfg["valid_end"])]
    features = improved.get_numeric_features(d)
    features = [f for f in features if f not in {"is_top_2"}]

    rows: list[dict[str, Any]] = []
    for seed in seeds:
        idx = max(0, warmup_days)
        block_count = 0
        while idx < len(valid_dates):
            if max_blocks > 0 and block_count >= max_blocks:
                break
            test_start = valid_dates[idx]
            block = valid_dates[idx : idx + test_days]
            if not block:
                break
            test_end = block[-1]

            expert_day_rows: list[pd.DataFrame] = []
            for ex in experts:
                ds_ex = d[d["group_key"].astype(str) == ex].copy()

                bw, bn = _select_best_wed_non_candidates(
                    dataset=ds_ex,
                    features=features,
                    seed=seed,
                    test_start=test_start,
                    test_end=test_end,
                    candidates_wed=candidates_wed,
                    candidates_nonwed=candidates_nonwed,
                    q_grid_wed=q_grid_wed,
                    q_grid_nonwed=q_grid_nonwed,
                    min_train_days_wed=min_train_days_wed,
                    min_train_days_nonwed=min_train_days_nonwed,
                    diff_col=diff_col,
                    model_params=model_params,
                )
                if bw is None or bn is None:
                    continue
                td = pd.concat([bw["test_day"], bn["test_day"]], ignore_index=True).sort_values("date")
                td["expert"] = ex
                td["weekday"] = pd.to_datetime(td["date"]).dt.day_name()
                td["gate_weight"] = float(non_a_gate_weight) if ex.endswith("_N") else float(a_gate_weight)
                td["gate_score"] = td["margin"] * td["gate_weight"]
                expert_day_rows.append(td[["date", "weekday", "expert", "gate_weight", "gate_score", "excess_played"]])

            if not expert_day_rows:
                idx += test_days
                continue

            merged = pd.concat(expert_day_rows, ignore_index=True)
            for dt, g in merged.groupby("date", sort=False):
                pick = g.sort_values("gate_score", ascending=False).iloc[0]
                rows.append(
                    {
                        "seed": seed,
                        "date": str(dt),
                        "weekday": str(pick["weekday"]),
                        "expert": str(pick["expert"]),
                        "gate_score": float(pick["gate_score"]),
                        "excess": float(pick["excess_played"]),
                    }
                )
            idx += test_days
            block_count += 1

    day_df = pd.DataFrame(rows)
    if day_df.empty:
        summary = {
            "overall": {"mean": 0.0, "std": 0.0, "n_days": 0, "ci_low": 0.0, "ci_high": 0.0, "p_gt_0": 0.5},
            "wednesday_only": {"mean": 0.0, "std": 0.0, "n_days": 0, "ci_low": 0.0, "ci_high": 0.0, "p_gt_0": 0.5},
            "non_wednesday": {"mean": 0.0, "std": 0.0, "n_days": 0, "ci_low": 0.0, "ci_high": 0.0, "p_gt_0": 0.5},
        }
        return day_df, summary

    arr = day_df["excess"].to_numpy(dtype=float)
    wed = day_df.loc[day_df["weekday"].eq("Wednesday"), "excess"].to_numpy(dtype=float)
    non = day_df.loc[~day_df["weekday"].eq("Wednesday"), "excess"].to_numpy(dtype=float)
    summary = {
        "overall": {**summarize_array(arr), **bootstrap_ci(arr, n_boot=n_boot, seed=BOOTSTRAP_SEED_SPLIT_RULE)},
        "wednesday_only": {**summarize_array(wed), **bootstrap_ci(wed, n_boot=n_boot, seed=BOOTSTRAP_SEED_SPLIT_RULE)},
        "non_wednesday": {**summarize_array(non), **bootstrap_ci(non, n_boot=n_boot, seed=BOOTSTRAP_SEED_SPLIT_RULE)},
    }
    return day_df, summary


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Split-rule (2F/3F, A/nonA) walk-forward comparison")
    p.add_argument("--output-prefix", default="db/experiments/tail_ltr_split_rule_wf")
    p.add_argument("--db-path", default="", help="DB path (optional)")
    p.add_argument("--db-glob", default="*7.db", help="DB auto-detect glob pattern used when --db-path is empty")
    p.add_argument("--seeds", default="42,77,123,202,303,404,505,606")
    p.add_argument("--test-days", type=int, default=14)
    p.add_argument("--warmup-days", type=int, default=56)
    p.add_argument("--min-train-days-wed", type=int, default=12)
    p.add_argument("--min-train-days-nonwed", type=int, default=42)
    p.add_argument("--windows-wed", default="full_2025")
    p.add_argument("--lambdas-wed", default="0.75,1.0,1.25")
    p.add_argument("--q-grid-wed", default="0.0,0.1,0.2,0.3,0.4")
    p.add_argument("--windows-nonwed", default="recent_60d,full_2025")
    p.add_argument("--lambdas-nonwed", default="0.75,1.0,1.25")
    p.add_argument("--q-grid-nonwed", default="0.0,0.1,0.2,0.3,0.4,0.5,0.6")
    p.add_argument("--a-weight", type=float, default=0.7, help="A-type weight for focus objective")
    p.add_argument("--non-a-weight", type=float, default=1.0, help="Non-A weight for focus objective")
    p.add_argument("--a-gate-weight", type=float, default=1.0, help="MoE gate weight for A experts")
    p.add_argument("--non-a-gate-weight", type=float, default=1.15, help="MoE gate weight for non-A experts")
    p.add_argument(
        "--modes",
        default="global11,floor2,floor_atype4",
        help="Comma-separated modes to evaluate (global11,floor2,floor_atype4)",
    )
    p.add_argument("--enable-moe", action="store_true", help="Enable additional floor_atype4 MoE gate evaluation")
    p.add_argument(
        "--max-blocks",
        type=int,
        default=0,
        help="Max number of test blocks per seed (0=unlimited)",
    )
    p.add_argument(
        "--n-boot",
        type=int,
        default=10000,
        help="Bootstrap resample count for CI (smaller is faster)",
    )
    p.add_argument("--use-gpu", action="store_true", help="Enable GPU for XGBoost training")
    p.add_argument(
        "--gpu-backend",
        choices=["cuda", "gpu_hist"],
        default="cuda",
        help="GPU backend mode: 'cuda' (tree_method=hist+device=cuda) or 'gpu_hist' (legacy)",
    )
    p.add_argument("--log-level", default="INFO", help="Logging level (DEBUG/INFO/WARNING/ERROR)")
    return p


def _build_model_params(*, use_gpu: bool, gpu_backend: str) -> dict[str, Any]:
    if not use_gpu:
        return {}
    if gpu_backend == "cuda":
        return {"tree_method": "hist", "device": "cuda"}
    return {"tree_method": "gpu_hist"}


def _evaluate_one_mode(
    *,
    mode: str,
    raw: pd.DataFrame,
    out_prefix: Path,
    seeds: list[int],
    args: argparse.Namespace,
    c_wed: list[Candidate],
    c_non: list[Candidate],
    q_wed: list[float],
    q_non: list[float],
    model_params: dict[str, Any],
) -> dict[str, Any]:
    d = add_simple_features(aggregate_mode(raw, mode=mode))
    day_raw, s_raw = run_mode(
        dataset=d,
        seeds=seeds,
        test_days=args.test_days,
        warmup_days=args.warmup_days,
        min_train_days_wed=args.min_train_days_wed,
        min_train_days_nonwed=args.min_train_days_nonwed,
        candidates_wed=c_wed,
        candidates_nonwed=c_non,
        q_grid_wed=q_wed,
        q_grid_nonwed=q_non,
        diff_col="total_diff_coins",
        model_params=model_params,
        max_blocks=int(args.max_blocks),
        n_boot=int(args.n_boot),
    )
    day_focus, s_focus = run_mode(
        dataset=d,
        seeds=seeds,
        test_days=args.test_days,
        warmup_days=args.warmup_days,
        min_train_days_wed=args.min_train_days_wed,
        min_train_days_nonwed=args.min_train_days_nonwed,
        candidates_wed=c_wed,
        candidates_nonwed=c_non,
        q_grid_wed=q_wed,
        q_grid_nonwed=q_non,
        diff_col="total_diff_coins_focus",
        model_params=model_params,
        max_blocks=int(args.max_blocks),
        n_boot=int(args.n_boot),
    )
    day_raw.to_csv(out_prefix.with_name(out_prefix.name + f"_{mode}_raw_days.csv"), index=False, encoding="utf-8-sig")
    day_focus.to_csv(out_prefix.with_name(out_prefix.name + f"_{mode}_focus_days.csv"), index=False, encoding="utf-8-sig")

    payload: dict[str, Any] = {"raw": s_raw, "focus_nonA": s_focus}
    logger.info("[%s] raw=%.4f focus=%.4f", mode, s_raw["overall"]["mean"], s_focus["overall"]["mean"])
    if mode == "floor_atype4" and bool(args.enable_moe):
        day_moe, s_moe = run_mode_moe4_gate(
            dataset=d,
            seeds=seeds,
            test_days=args.test_days,
            warmup_days=args.warmup_days,
            min_train_days_wed=args.min_train_days_wed,
            min_train_days_nonwed=args.min_train_days_nonwed,
            candidates_wed=c_wed,
            candidates_nonwed=c_non,
            q_grid_wed=q_wed,
            q_grid_nonwed=q_non,
            diff_col="total_diff_coins_focus",
            non_a_gate_weight=float(args.non_a_gate_weight),
            a_gate_weight=float(args.a_gate_weight),
            model_params=model_params,
            max_blocks=int(args.max_blocks),
            n_boot=int(args.n_boot),
        )
        day_moe.to_csv(
            out_prefix.with_name(out_prefix.name + "_floor_atype4_moe_focus_days.csv"),
            index=False,
            encoding="utf-8-sig",
        )
        payload["moe_gate"] = {
            "focus_nonA": s_moe,
            "gate_config": {
                "a_gate_weight": float(args.a_gate_weight),
                "non_a_gate_weight": float(args.non_a_gate_weight),
            },
        }
        logger.info("[floor_atype4_moe_gate] focus=%.4f", s_moe["overall"]["mean"])
    return payload


def _build_focus_ranking(results: dict[str, Any], modes: list[str]) -> list[dict[str, float | str]]:
    ranking: list[dict[str, float | str]] = []
    for mode in modes:
        mode_payload = results["modes"][mode]
        ranking.append(
            {
                "mode": mode,
                "focus_overall_mean": float(mode_payload["focus_nonA"]["overall"]["mean"]),
                "focus_nonwed_mean": float(mode_payload["focus_nonA"]["non_wednesday"]["mean"]),
                "raw_overall_mean": float(mode_payload["raw"]["overall"]["mean"]),
            }
        )
        moe_payload = mode_payload.get("moe_gate")
        if moe_payload:
            ranking.append(
                {
                    "mode": "floor_atype4_moe_gate",
                    "focus_overall_mean": float(moe_payload["focus_nonA"]["overall"]["mean"]),
                    "focus_nonwed_mean": float(moe_payload["focus_nonA"]["non_wednesday"]["mean"]),
                    "raw_overall_mean": float("nan"),
                }
            )
    ranking.sort(key=lambda x: (x["focus_overall_mean"], x["focus_nonwed_mean"]), reverse=True)
    return ranking


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.log_level)
    out_prefix = Path(args.output_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)

    seeds = parse_csv_ints(args.seeds)
    c_wed = [Candidate(w, l) for w in parse_csv_strs(args.windows_wed) for l in parse_csv_floats(args.lambdas_wed)]
    c_non = [Candidate(w, l) for w in parse_csv_strs(args.windows_nonwed) for l in parse_csv_floats(args.lambdas_nonwed)]
    q_wed = parse_csv_floats(args.q_grid_wed)
    q_non = parse_csv_floats(args.q_grid_nonwed)

    model_params = _build_model_params(use_gpu=args.use_gpu, gpu_backend=args.gpu_backend)

    raw = build_base_rows(
        db_path=resolve_db_path(args.db_path, pattern=args.db_glob),
        a_weight=float(args.a_weight),
        non_a_weight=float(args.non_a_weight),
    )

    allowed_modes = {"global11", "floor2", "floor_atype4"}
    modes = parse_csv_strs(args.modes)
    if not modes:
        modes = ["global11", "floor2", "floor_atype4"]
    unknown_modes = [m for m in modes if m not in allowed_modes]
    if unknown_modes:
        raise ValueError(f"Unknown modes: {unknown_modes}. Allowed: {sorted(allowed_modes)}")
    results: dict[str, Any] = {"config": vars(args), "modes": {}}

    for mode in modes:
        results["modes"][mode] = _evaluate_one_mode(
            mode=mode,
            raw=raw,
            out_prefix=out_prefix,
            seeds=seeds,
            args=args,
            c_wed=c_wed,
            c_non=c_non,
            q_wed=q_wed,
            q_non=q_non,
            model_params=model_params,
        )

    # recommend by non-A focus score
    ranking = _build_focus_ranking(results, modes)
    results["ranking_focus_nonA"] = ranking
    results["recommended_mode_focus_nonA"] = ranking[0]["mode"] if ranking else ""

    out_json = out_prefix.with_suffix(".json")
    out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Saved: %s", out_json)
    logger.info(
        "%s",
        json.dumps(
            {
                "recommended_mode_focus_nonA": results["recommended_mode_focus_nonA"],
                "ranking_focus_nonA": ranking,
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
