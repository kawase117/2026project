from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.experiments import tail_time_adaptive_ltr_poc_improved as improved
from ml.experiments import tail_ltr_profit_ops as ops


def parse_csv_ints(raw: str) -> list[int]:
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def parse_csv_floats(raw: str) -> list[float]:
    return [float(x.strip()) for x in raw.split(",") if x.strip()]


def topk_day_table(
    df: pd.DataFrame,
    score_col: str,
    *,
    k: int,
    diff_col: str = "total_diff_coins",
    mc_col: str = "machine_count",
) -> pd.DataFrame:
    day_top = (
        df.sort_values(["date", score_col], ascending=[True, False])
        .groupby("date", sort=False)
        .head(k)
        .groupby("date", sort=False)
        .agg(sel_diff=(diff_col, "sum"), sel_mc=(mc_col, "sum"))
    )
    day_top["pm"] = day_top["sel_diff"] / day_top["sel_mc"].replace(0, np.nan)

    store = df.groupby("date", sort=False).agg(store_diff=(diff_col, "sum"), store_mc=(mc_col, "sum"))
    store["store_pm"] = store["store_diff"] / store["store_mc"].replace(0, np.nan)

    margins = (
        df.sort_values(["date", score_col], ascending=[True, False])
        .groupby("date", sort=False)[score_col]
        .apply(lambda s: float(s.iloc[0] - s.iloc[1]) if len(s) >= 2 else 0.0)
        .rename("margin")
    )

    out = day_top.join(store[["store_pm"]]).join(margins).reset_index().sort_values("date")
    out["excess"] = out["pm"] - out["store_pm"]
    return out


def choose_blend_and_threshold(
    cal_df: pd.DataFrame,
    pair_prob_col: str,
    ndcg_prob_col: str,
    *,
    blend_weights: tuple[float, ...],
    q_grid: list[float],
    k: int,
) -> dict[str, float]:
    best: dict[str, float] | None = None
    for w in blend_weights:
        cal = cal_df.copy()
        cal["pred"] = w * cal[pair_prob_col] + (1.0 - w) * cal[ndcg_prob_col]
        day = topk_day_table(cal, "pred", k=k)
        margins = day["margin"].to_numpy(dtype=float)
        for q in q_grid:
            th = float(np.quantile(margins, q))
            keep = day["margin"] >= th
            overall = np.where(keep.to_numpy(), day["excess"].to_numpy(), 0.0)
            score = float(np.mean(overall)) if len(overall) else -1e18
            if best is None or score > best["score"]:
                best = {
                    "blend_weight": float(w),
                    "q": float(q),
                    "threshold": float(th),
                    "score": score,
                }
    assert best is not None
    return best


def train_and_predict_fold(
    *,
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    target: str,
    features: list[str],
    decay_lambda: float,
    random_state: int,
    model_params: dict[str, Any],
    temperature_candidates: tuple[float, ...],
    blend_weights: tuple[float, ...],
    q_grid: list[float],
    k: int,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float]]:
    train_dates = sorted(pd.to_datetime(train_df["date"].unique()))
    calib_cut = max(1, int(len(train_dates) * 0.85))
    fit_days = set(train_dates[:calib_cut])
    cal_days = set(train_dates[calib_cut:])
    fit_df = train_df[train_df["date"].isin(fit_days)] if cal_days else train_df
    cal_df = train_df[train_df["date"].isin(cal_days)] if cal_days else train_df.tail(min(200, len(train_df)))

    X_fit = fit_df[features].astype(float)
    y_fit = fit_df[target].astype(int).to_numpy()
    X_cal = cal_df[features].astype(float)
    y_cal = cal_df[target].astype(int).to_numpy()
    X_test = test_df[features].astype(float)

    pair = improved.fit_ranker(
        X_fit,
        y_fit,
        fit_df["date"],
        objective="rank:pairwise",
        random_state=random_state,
        decay_lambda=decay_lambda,
        model_params=model_params,
    )
    ndcg = improved.fit_ranker(
        X_fit,
        y_fit,
        fit_df["date"],
        objective="rank:ndcg",
        random_state=random_state + 7,
        decay_lambda=decay_lambda,
        model_params=model_params,
    )

    raw_cal_pair = pair.predict(X_cal)
    raw_cal_ndcg = ndcg.predict(X_cal)
    raw_test_pair = pair.predict(X_test)
    raw_test_ndcg = ndcg.predict(X_test)

    cal_dates_np = cal_df["date"].to_numpy()
    t_pair = improved.find_best_temperature(y_cal, raw_cal_pair, cal_dates_np, temperature_candidates)
    t_ndcg = improved.find_best_temperature(y_cal, raw_cal_ndcg, cal_dates_np, temperature_candidates)

    cal = cal_df[["date", "total_diff_coins", "machine_count"]].copy()
    cal["pair_prob"] = improved.sigmoid(raw_cal_pair, t_pair)
    cal["ndcg_prob"] = improved.sigmoid(raw_cal_ndcg, t_ndcg)

    test = test_df[["date", "total_diff_coins", "machine_count"]].copy()
    test["pair_prob"] = improved.sigmoid(raw_test_pair, t_pair)
    test["ndcg_prob"] = improved.sigmoid(raw_test_ndcg, t_ndcg)

    choice = choose_blend_and_threshold(
        cal,
        "pair_prob",
        "ndcg_prob",
        blend_weights=blend_weights,
        q_grid=q_grid,
        k=k,
    )
    w = choice["blend_weight"]
    cal["pred"] = w * cal["pair_prob"] + (1.0 - w) * cal["ndcg_prob"]
    test["pred"] = w * test["pair_prob"] + (1.0 - w) * test["ndcg_prob"]
    return cal, test, choice


def build_train_window(window_name: str, test_start: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    test_prev = test_start - pd.Timedelta(days=1)
    if window_name == "recent_60d":
        return test_start - pd.Timedelta(days=60), test_prev
    if window_name == "regime2_only":
        return pd.Timestamp(improved.REGIME_2_START), pd.Timestamp(improved.REGIME_2_END)
    if window_name == "full_2025":
        return pd.Timestamp(improved.REGIME_1_START), pd.Timestamp(improved.REGIME_2_END)
    return pd.Timestamp(improved.REGIME_1_START), min(test_prev, pd.Timestamp(improved.REGIME_2_END))


def summarize(arr: np.ndarray) -> dict[str, float]:
    if arr.size == 0:
        return {"mean": 0.0, "std": 0.0, "n_days": 0}
    return {"mean": float(arr.mean()), "std": float(arr.std(ddof=0)), "n_days": int(arr.size)}


def bootstrap_ci(arr: np.ndarray, *, n_boot: int = 12000, seed: int = 20260520) -> dict[str, float]:
    if arr.size == 0:
        return {"ci_low": 0.0, "ci_high": 0.0, "p_gt_0": 0.5}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, arr.size, size=(n_boot, arr.size))
    means = arr[idx].mean(axis=1)
    return {
        "ci_low": float(np.quantile(means, 0.025)),
        "ci_high": float(np.quantile(means, 0.975)),
        "p_gt_0": float((means > 0).mean()),
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Full walk-forward threshold + retrain evaluation for tail LTR")
    p.add_argument("--output", default="db/experiments/tail_ltr_full_walkforward_ops_report.json")
    p.add_argument("--seeds", default="42,77,123")
    p.add_argument("--test-days", type=int, default=14)
    p.add_argument("--cal-days", type=int, default=56)
    p.add_argument("--min-cal-days", type=int, default=42)
    p.add_argument("--q-single", default="0.0,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8")
    p.add_argument("--q2-grid", default="0.55,0.65,0.75,0.85,0.9")
    p.add_argument("--q3-grid", default="0.25,0.35,0.45,0.55,0.65,0.75")
    return p


def main() -> int:
    args = build_parser().parse_args()
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    seeds = parse_csv_ints(args.seeds)
    q_single = parse_csv_floats(args.q_single)
    q2_grid = parse_csv_floats(args.q2_grid)
    q3_grid = parse_csv_floats(args.q3_grid)

    dataset, all_features = ops.load_dataset(ops.resolve_db_path(""))
    dataset = dataset.sort_values("date").reset_index(drop=True)

    split_cfg = improved.build_fixed_split_configs(dataset)["regime_3_fixed_split"]
    valid_start = pd.Timestamp(split_cfg["valid_start"])
    valid_end = pd.Timestamp(split_cfg["valid_end"])
    all_valid_dates = sorted(pd.to_datetime(dataset["date"].unique()))
    all_valid_dates = [d for d in all_valid_dates if valid_start <= d <= valid_end]

    top2_recipe = {
        "target": "is_top_2",
        "window_name": "regime2_only",
        "decay_lambda": 1.0,
        "model_params": {},
    }
    top3_recipe = {
        "target": "is_top_3",
        "window_name": "recent_60d",
        "decay_lambda": 1.5,
        "model_params": {},
    }

    top2_excess_all: list[float] = []
    top3_excess_all: list[float] = []
    gate_excess_all: list[float] = []
    fold_rows: list[dict[str, Any]] = []

    temp_candidates = improved.CalibrationConfig().temperature_candidates
    blend_weights = improved.CalibrationConfig().blend_weights

    for seed in seeds:
        idx = max(args.cal_days, args.min_cal_days)
        fold_no = 0
        while idx < len(all_valid_dates):
            test_start = all_valid_dates[idx]
            test_dates = all_valid_dates[idx : idx + args.test_days]
            if not test_dates:
                break
            test_end = test_dates[-1]

            # Build train windows per target.
            t2_start, t2_end = build_train_window(top2_recipe["window_name"], test_start)
            t3_start, t3_end = build_train_window(top3_recipe["window_name"], test_start)

            train2_mask = (pd.to_datetime(dataset["date"]) >= t2_start) & (pd.to_datetime(dataset["date"]) <= t2_end)
            train3_mask = (pd.to_datetime(dataset["date"]) >= t3_start) & (pd.to_datetime(dataset["date"]) <= t3_end)
            test_mask = (pd.to_datetime(dataset["date"]) >= test_start) & (pd.to_datetime(dataset["date"]) <= test_end)

            train2 = dataset.loc[train2_mask].copy()
            train3 = dataset.loc[train3_mask].copy()
            test = dataset.loc[test_mask].copy()

            if train2["date"].nunique() < args.min_cal_days or train3["date"].nunique() < args.min_cal_days:
                idx += args.test_days
                continue
            if test.empty:
                break

            feat2 = ops.select_features(train2, all_features, top2_recipe["target"], "all")
            feat3 = ops.select_features(train3, all_features, top3_recipe["target"], "all")

            cal2, test2, choice2 = train_and_predict_fold(
                train_df=train2,
                test_df=test,
                target=top2_recipe["target"],
                features=feat2,
                decay_lambda=top2_recipe["decay_lambda"],
                random_state=seed,
                model_params=top2_recipe["model_params"],
                temperature_candidates=temp_candidates,
                blend_weights=blend_weights,
                q_grid=q_single,
                k=2,
            )
            cal3, test3, choice3 = train_and_predict_fold(
                train_df=train3,
                test_df=test,
                target=top3_recipe["target"],
                features=feat3,
                decay_lambda=top3_recipe["decay_lambda"],
                random_state=seed,
                model_params=top3_recipe["model_params"],
                temperature_candidates=temp_candidates,
                blend_weights=blend_weights,
                q_grid=q_single,
                k=3,
            )

            day2_tst = topk_day_table(test2, "pred", k=2)
            day3_tst = topk_day_table(test3, "pred", k=3)

            keep2 = day2_tst["margin"] >= choice2["threshold"]
            keep3 = day3_tst["margin"] >= choice3["threshold"]
            ex2 = np.where(keep2.to_numpy(), day2_tst["excess"].to_numpy(), 0.0)
            ex3 = np.where(keep3.to_numpy(), day3_tst["excess"].to_numpy(), 0.0)

            merge_tst = day2_tst[["date", "margin", "excess"]].rename(columns={"margin": "m2", "excess": "ex2"})
            merge_tst = merge_tst.merge(
                day3_tst[["date", "margin", "excess"]].rename(columns={"margin": "m3", "excess": "ex3"}),
                on="date",
                how="inner",
            )
            # Sequential gate with fold-trained thresholds:
            # 1) if Top2 confidence passes its threshold, use Top2
            # 2) else if Top3 confidence passes its threshold, use Top3
            c2 = merge_tst["m2"] >= choice2["threshold"]
            c3 = (~c2) & (merge_tst["m3"] >= choice3["threshold"])
            exg = np.where(c2.to_numpy(), merge_tst["ex2"].to_numpy(), np.where(c3.to_numpy(), merge_tst["ex3"].to_numpy(), 0.0))

            top2_excess_all.extend(ex2.tolist())
            top3_excess_all.extend(ex3.tolist())
            gate_excess_all.extend(exg.tolist())

            fold_rows.append(
                {
                    "seed": seed,
                    "fold": fold_no,
                    "test_start": str(test_start.date()),
                    "test_end": str(test_end.date()),
                    "top2_train_days": int(train2["date"].nunique()),
                    "top3_train_days": int(train3["date"].nunique()),
                    "top2_q": choice2["q"],
                    "top3_q": choice3["q"],
                    "gate_threshold_from_top2_q": choice2["q"],
                    "gate_threshold_from_top3_q": choice3["q"],
                    "top2_excess_mean": float(np.mean(ex2)),
                    "top3_excess_mean": float(np.mean(ex3)),
                    "gate_excess_mean": float(np.mean(exg)),
                }
            )

            fold_no += 1
            idx += args.test_days

    arr2 = np.asarray(top2_excess_all, dtype=float)
    arr3 = np.asarray(top3_excess_all, dtype=float)
    arrg = np.asarray(gate_excess_all, dtype=float)

    result = {
        "config": {
            "cal_days": args.cal_days,
            "min_cal_days": args.min_cal_days,
            "test_days": args.test_days,
            "q_single": q_single,
            "q2_grid": q2_grid,
            "q3_grid": q3_grid,
            "seeds": seeds,
            "split_cfg": split_cfg,
        },
        "n_folds_total": len(fold_rows),
        "fold_details": fold_rows,
        "results": {
            "top2_single": {**summarize(arr2), **bootstrap_ci(arr2)},
            "top3_single": {**summarize(arr3), **bootstrap_ci(arr3)},
            "gate_top2_top3": {**summarize(arrg), **bootstrap_ci(arrg)},
        },
    }
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved: {out_path}")
    print(json.dumps(result["results"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
