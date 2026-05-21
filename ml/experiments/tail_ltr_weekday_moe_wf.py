from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.experiments import tail_ltr_profit_ops as ops
from ml.experiments import tail_time_adaptive_ltr_poc_improved as improved
from ml.experiments.tail_ltr_full_walkforward_ops import (
    bootstrap_ci,
    build_train_window,
    topk_day_table,
    train_and_predict_fold,
)


@dataclass
class Expert:
    name: str
    window_name: str
    decay_lambda: float


def parse_csv_ints(raw: str) -> list[int]:
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def parse_csv_floats(raw: str) -> list[float]:
    return [float(x.strip()) for x in raw.split(",") if x.strip()]


def evaluate_expert_fold(
    *,
    dataset: pd.DataFrame,
    all_features: list[str],
    expert: Expert,
    seed: int,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    q_grid: list[float],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float]] | None:
    dts = pd.to_datetime(dataset["date"])
    train_start, train_end = build_train_window(expert.window_name, test_start)
    train_mask = (dts >= train_start) & (dts <= train_end)
    test_mask = (dts >= test_start) & (dts <= test_end)
    train_df = dataset.loc[train_mask].copy()
    test_df = dataset.loc[test_mask].copy()
    if train_df["date"].nunique() < 42 or test_df.empty:
        return None

    features = ops.select_features(train_df, all_features, "is_top_2", "all")
    cal_pred_df, test_pred_df, choice = train_and_predict_fold(
        train_df=train_df,
        test_df=test_df,
        target="is_top_2",
        features=features,
        decay_lambda=expert.decay_lambda,
        random_state=seed,
        model_params={},
        temperature_candidates=improved.CalibrationConfig().temperature_candidates,
        blend_weights=improved.CalibrationConfig().blend_weights,
        q_grid=q_grid,
        k=2,
    )

    cal_day = topk_day_table(cal_pred_df, "pred", k=2)
    test_day = topk_day_table(test_pred_df, "pred", k=2)

    cal_keep = cal_day["margin"] >= choice["threshold"]
    test_keep = test_day["margin"] >= choice["threshold"]
    cal_day["excess_played"] = np.where(cal_keep.to_numpy(), cal_day["excess"].to_numpy(), 0.0)
    test_day["excess_played"] = np.where(test_keep.to_numpy(), test_day["excess"].to_numpy(), 0.0)
    cal_day["weekday"] = pd.to_datetime(cal_day["date"]).dt.day_name()
    test_day["weekday"] = pd.to_datetime(test_day["date"]).dt.day_name()
    return cal_day, test_day, choice


def summarize(arr: np.ndarray) -> dict[str, float]:
    if arr.size == 0:
        return {"mean": 0.0, "std": 0.0, "n_days": 0}
    return {"mean": float(arr.mean()), "std": float(arr.std(ddof=0)), "n_days": int(arr.size)}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Weekday hard-routing MoE for Top2 WF")
    p.add_argument("--output-prefix", default="db/experiments/tail_ltr_weekday_moe_wf")
    p.add_argument("--seeds", default="42,77,123,202,303,404,505,606")
    p.add_argument("--q-grid", default="0.0,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8")
    p.add_argument("--test-days", type=int, default=14)
    return p


def main() -> int:
    args = build_parser().parse_args()
    out_prefix = Path(args.output_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)

    seeds = parse_csv_ints(args.seeds)
    q_grid = parse_csv_floats(args.q_grid)

    experts = [
        Expert(name="recent60_l075", window_name="recent_60d", decay_lambda=0.75),
        Expert(name="regime2_l075", window_name="regime2_only", decay_lambda=0.75),
        Expert(name="full2025_l10", window_name="full_2025", decay_lambda=1.0),
    ]

    dataset, all_features = ops.load_dataset(ops.resolve_db_path(""))
    dataset = dataset.sort_values("date").reset_index(drop=True)

    split_cfg = improved.build_fixed_split_configs(dataset)["regime_3_fixed_split"]
    valid_start = pd.Timestamp(split_cfg["valid_start"])
    valid_end = pd.Timestamp(split_cfg["valid_end"])
    valid_dates = sorted(pd.to_datetime(dataset["date"].unique()))
    valid_dates = [d for d in valid_dates if valid_start <= d <= valid_end]

    baseline_best: list[float] = []
    baseline_uniform: list[float] = []
    moe_weekday: list[float] = []
    routing_rows: list[dict[str, Any]] = []
    day_rows: list[dict[str, Any]] = []

    for seed in seeds:
        idx = 56
        fold = 0
        while idx < len(valid_dates):
            test_start = valid_dates[idx]
            test_block = valid_dates[idx : idx + args.test_days]
            if not test_block:
                break
            test_end = test_block[-1]

            evals = {}
            for ex in experts:
                row = evaluate_expert_fold(
                    dataset=dataset,
                    all_features=all_features,
                    expert=ex,
                    seed=seed,
                    test_start=test_start,
                    test_end=test_end,
                    q_grid=q_grid,
                )
                if row is not None:
                    evals[ex.name] = row
            if len(evals) < 2:
                idx += args.test_days
                continue

            # Baseline A: best single expert by calibration mean.
            cal_means = {
                name: float(v[0]["excess_played"].mean())
                for name, v in evals.items()
            }
            best_name = sorted(cal_means.items(), key=lambda x: x[1], reverse=True)[0][0]
            best_test = evals[best_name][1]
            baseline_best.extend(best_test["excess_played"].to_numpy(dtype=float).tolist())

            # Baseline B: uniform average across experts (reference)
            merged = None
            for name, (_, t_day, _) in evals.items():
                c = t_day[["date", "excess_played", "weekday"]].rename(columns={"excess_played": f"ex_{name}"})
                merged = c if merged is None else merged.merge(c[["date", f"ex_{name}"]], on="date", how="inner")
            ex_cols = [c for c in merged.columns if c.startswith("ex_")]
            merged["uniform"] = merged[ex_cols].mean(axis=1)
            baseline_uniform.extend(merged["uniform"].to_numpy(dtype=float).tolist())

            # Weekday hard routing.
            weekday_choice: dict[str, str] = {}
            weekdays = sorted(merged["weekday"].unique().tolist())
            for wd in weekdays:
                wd_scores = {}
                for name, (c_day, _, _) in evals.items():
                    s = c_day.loc[c_day["weekday"] == wd, "excess_played"]
                    wd_scores[name] = float(s.mean()) if len(s) else -1e18
                weekday_choice[wd] = sorted(wd_scores.items(), key=lambda x: x[1], reverse=True)[0][0]

            routed = []
            for _, r in merged.iterrows():
                pick = weekday_choice.get(r["weekday"], best_name)
                routed.append(float(r[f"ex_{pick}"]))
                day_rows.append(
                    {
                        "seed": seed,
                        "fold": fold,
                        "date": str(r["date"]),
                        "weekday": r["weekday"],
                        "selected_expert": pick,
                        "excess": float(r[f"ex_{pick}"]),
                    }
                )
            moe_weekday.extend(routed)

            for wd, pick in weekday_choice.items():
                routing_rows.append(
                    {
                        "seed": seed,
                        "fold": fold,
                        "test_start": str(test_start.date()),
                        "test_end": str(test_end.date()),
                        "weekday": wd,
                        "selected_expert": pick,
                    }
                )

            fold += 1
            idx += args.test_days

    arr_best = np.asarray(baseline_best, dtype=float)
    arr_uni = np.asarray(baseline_uniform, dtype=float)
    arr_moe = np.asarray(moe_weekday, dtype=float)

    summary = {
        "baseline_best_single": {**summarize(arr_best), **bootstrap_ci(arr_best, n_boot=10000, seed=20260524)},
        "baseline_uniform_avg": {**summarize(arr_uni), **bootstrap_ci(arr_uni, n_boot=10000, seed=20260524)},
        "moe_weekday_hard": {**summarize(arr_moe), **bootstrap_ci(arr_moe, n_boot=10000, seed=20260524)},
    }

    day_df = pd.DataFrame(day_rows)
    route_df = pd.DataFrame(routing_rows)

    out_json = out_prefix.with_suffix(".json")
    out_days = out_prefix.with_name(out_prefix.name + "_days.csv")
    out_routes = out_prefix.with_name(out_prefix.name + "_routes.csv")
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    day_df.to_csv(out_days, index=False, encoding="utf-8-sig")
    route_df.to_csv(out_routes, index=False, encoding="utf-8-sig")

    print("Saved:", out_json)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("Saved:", out_days)
    print("Saved:", out_routes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
