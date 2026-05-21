from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.experiments import tail_time_adaptive_ltr_poc_improved as improved
from ml.experiments.tail_ltr_full_walkforward_ops import bootstrap_ci, build_train_window, topk_day_table, train_and_predict_fold


@dataclass
class Candidate:
    window_name: str
    decay_lambda: float


def parse_csv_ints(raw: str) -> list[int]:
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def parse_csv_floats(raw: str) -> list[float]:
    return [float(x.strip()) for x in raw.split(",") if x.strip()]


def parse_csv_strs(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


def resolve_db_path() -> Path:
    candidates = sorted(Path("db").glob("*7.db"))
    if not candidates:
        raise FileNotFoundError("No '*7.db' under db/")
    return candidates[0]


def normalize_last_digit(x: Any) -> str:
    s = str(x)
    if s in {"11", "ゾロ目", "ｿﾞﾛ目", "ぞろ目"}:
        return "ゾロ目"
    return s


def _days_since_last_positive(series: pd.Series) -> pd.Series:
    out = []
    last_idx = None
    for i, v in enumerate(series.to_numpy()):
        if last_idx is None:
            out.append(999.0)
        else:
            out.append(float(i - last_idx))
        if int(v) == 1:
            last_idx = i
    return pd.Series(out, index=series.index, dtype=float)


def build_base_rows(*, db_path: Path, a_weight: float, non_a_weight: float) -> pd.DataFrame:
    con = sqlite3.connect(db_path)
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

    # Target: top2 across entity_key per date.
    rk = agg.groupby("date", sort=False)["total_diff_coins"].rank(method="first", ascending=False)
    agg["is_top_2"] = (rk <= 2).astype(int)
    return agg


def add_simple_features(df: pd.DataFrame) -> pd.DataFrame:
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
    out["days_since_last_top2"] = (
        out.groupby("entity_key", sort=False)["is_top_2"]
        .transform(_days_since_last_positive)
        .fillna(999.0)
    )
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
        while idx < len(valid_dates):
            test_start = valid_dates[idx]
            block = valid_dates[idx : idx + test_days]
            if not block:
                break
            test_end = block[-1]

            wed_rows = []
            for c in candidates_wed:
                r = eval_candidate_custom(
                    dataset=d,
                    features=features,
                    seed=seed,
                    candidate=c,
                    test_start=test_start,
                    test_end=test_end,
                    q_grid=q_grid_wed,
                    train_is_wed=True,
                    test_is_wed=True,
                    min_train_days=min_train_days_wed,
                    diff_col=diff_col,
                    model_params=model_params,
                )
                if r is not None:
                    wed_rows.append(r)
            non_rows = []
            for c in candidates_nonwed:
                r = eval_candidate_custom(
                    dataset=d,
                    features=features,
                    seed=seed,
                    candidate=c,
                    test_start=test_start,
                    test_end=test_end,
                    q_grid=q_grid_nonwed,
                    train_is_wed=False,
                    test_is_wed=False,
                    min_train_days=min_train_days_nonwed,
                    diff_col=diff_col,
                    model_params=model_params,
                )
                if r is not None:
                    non_rows.append(r)
            if not wed_rows or not non_rows:
                idx += test_days
                continue
            bw = sorted(wed_rows, key=lambda x: x["cal_score"], reverse=True)[0]
            bn = sorted(non_rows, key=lambda x: x["cal_score"], reverse=True)[0]
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
        "overall": {**_summarize(arr), **bootstrap_ci(arr, n_boot=10000, seed=20260527)},
        "wednesday_only": {**_summarize(wed), **bootstrap_ci(wed, n_boot=10000, seed=20260527)},
        "non_wednesday": {**_summarize(non), **bootstrap_ci(non, n_boot=10000, seed=20260527)},
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
        while idx < len(valid_dates):
            test_start = valid_dates[idx]
            block = valid_dates[idx : idx + test_days]
            if not block:
                break
            test_end = block[-1]

            expert_day_rows: list[pd.DataFrame] = []
            for ex in experts:
                ds_ex = d[d["group_key"].astype(str) == ex].copy()

                wed_rows = []
                for c in candidates_wed:
                    r = eval_candidate_custom(
                        dataset=ds_ex,
                        features=features,
                        seed=seed,
                        candidate=c,
                        test_start=test_start,
                        test_end=test_end,
                        q_grid=q_grid_wed,
                        train_is_wed=True,
                        test_is_wed=True,
                        min_train_days=min_train_days_wed,
                        diff_col=diff_col,
                        model_params=model_params,
                    )
                    if r is not None:
                        wed_rows.append(r)
                non_rows = []
                for c in candidates_nonwed:
                    r = eval_candidate_custom(
                        dataset=ds_ex,
                        features=features,
                        seed=seed,
                        candidate=c,
                        test_start=test_start,
                        test_end=test_end,
                        q_grid=q_grid_nonwed,
                        train_is_wed=False,
                        test_is_wed=False,
                        min_train_days=min_train_days_nonwed,
                        diff_col=diff_col,
                        model_params=model_params,
                    )
                    if r is not None:
                        non_rows.append(r)
                if not wed_rows or not non_rows:
                    continue

                bw = sorted(wed_rows, key=lambda x: x["cal_score"], reverse=True)[0]
                bn = sorted(non_rows, key=lambda x: x["cal_score"], reverse=True)[0]
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
        "overall": {**_summarize(arr), **bootstrap_ci(arr, n_boot=10000, seed=20260527)},
        "wednesday_only": {**_summarize(wed), **bootstrap_ci(wed, n_boot=10000, seed=20260527)},
        "non_wednesday": {**_summarize(non), **bootstrap_ci(non, n_boot=10000, seed=20260527)},
    }
    return day_df, summary


def _summarize(arr: np.ndarray) -> dict[str, float]:
    if arr.size == 0:
        return {"mean": 0.0, "std": 0.0, "n_days": 0}
    return {"mean": float(arr.mean()), "std": float(arr.std(ddof=0)), "n_days": int(arr.size)}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Split-rule (2F/3F, A/nonA) walk-forward comparison")
    p.add_argument("--output-prefix", default="db/experiments/tail_ltr_split_rule_wf")
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
    p.add_argument("--use-gpu", action="store_true", help="Enable GPU for XGBoost training")
    p.add_argument(
        "--gpu-backend",
        choices=["cuda", "gpu_hist"],
        default="cuda",
        help="GPU backend mode: 'cuda' (tree_method=hist+device=cuda) or 'gpu_hist' (legacy)",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()
    out_prefix = Path(args.output_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)

    seeds = parse_csv_ints(args.seeds)
    c_wed = [Candidate(w, l) for w in parse_csv_strs(args.windows_wed) for l in parse_csv_floats(args.lambdas_wed)]
    c_non = [Candidate(w, l) for w in parse_csv_strs(args.windows_nonwed) for l in parse_csv_floats(args.lambdas_nonwed)]
    q_wed = parse_csv_floats(args.q_grid_wed)
    q_non = parse_csv_floats(args.q_grid_nonwed)

    model_params: dict[str, Any] = {}
    if args.use_gpu:
        if args.gpu_backend == "cuda":
            model_params.update({"tree_method": "hist", "device": "cuda"})
        else:
            model_params.update({"tree_method": "gpu_hist"})

    raw = build_base_rows(db_path=resolve_db_path(), a_weight=float(args.a_weight), non_a_weight=float(args.non_a_weight))

    modes = ["global11", "floor2", "floor_atype4"]
    results: dict[str, Any] = {"config": vars(args), "modes": {}}

    for mode in modes:
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
        )

        day_raw.to_csv(out_prefix.with_name(out_prefix.name + f"_{mode}_raw_days.csv"), index=False, encoding="utf-8-sig")
        day_focus.to_csv(out_prefix.with_name(out_prefix.name + f"_{mode}_focus_days.csv"), index=False, encoding="utf-8-sig")
        results["modes"][mode] = {"raw": s_raw, "focus_nonA": s_focus}
        print(f"[{mode}] raw={s_raw['overall']['mean']:.4f} focus={s_focus['overall']['mean']:.4f}")

        if mode == "floor_atype4":
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
            )
            day_moe.to_csv(out_prefix.with_name(out_prefix.name + "_floor_atype4_moe_focus_days.csv"), index=False, encoding="utf-8-sig")
            results["modes"]["floor_atype4_moe_gate"] = {
                "focus_nonA": s_moe,
                "gate_config": {
                    "a_gate_weight": float(args.a_gate_weight),
                    "non_a_gate_weight": float(args.non_a_gate_weight),
                },
            }
            print(f"[floor_atype4_moe_gate] focus={s_moe['overall']['mean']:.4f}")

    # recommend by non-A focus score
    ranking = []
    for mode in modes:
        ranking.append(
            {
                "mode": mode,
                "focus_overall_mean": float(results["modes"][mode]["focus_nonA"]["overall"]["mean"]),
                "focus_nonwed_mean": float(results["modes"][mode]["focus_nonA"]["non_wednesday"]["mean"]),
                "raw_overall_mean": float(results["modes"][mode]["raw"]["overall"]["mean"]),
            }
        )
    if "floor_atype4_moe_gate" in results["modes"]:
        ranking.append(
            {
                "mode": "floor_atype4_moe_gate",
                "focus_overall_mean": float(results["modes"]["floor_atype4_moe_gate"]["focus_nonA"]["overall"]["mean"]),
                "focus_nonwed_mean": float(results["modes"]["floor_atype4_moe_gate"]["focus_nonA"]["non_wednesday"]["mean"]),
                "raw_overall_mean": float("nan"),
            }
        )
    ranking.sort(key=lambda x: (x["focus_overall_mean"], x["focus_nonwed_mean"]), reverse=True)
    results["ranking_focus_nonA"] = ranking
    results["recommended_mode_focus_nonA"] = ranking[0]["mode"] if ranking else ""

    out_json = out_prefix.with_suffix(".json")
    out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Saved:", out_json)
    print(json.dumps({"recommended_mode_focus_nonA": results["recommended_mode_focus_nonA"], "ranking_focus_nonA": ranking}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
