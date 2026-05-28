from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.evaluators.metrics import calculate_hit_at_k
from ml.last_digit.dataset_bridge import build_last_digit_dataset
from ml.last_digit import tail_time_adaptive_ltr_poc_improved as improved
from ml.last_digit.utils import (
    NDCG_RANDOM_STATE_OFFSET,
    configure_logging,
    parse_csv_floats,
    parse_csv_ints,
    parse_csv_strs,
    resolve_db_path,
)

logger = logging.getLogger(__name__)


@dataclass
class TrainRecipe:
    target: str
    window_name: str
    decay_lambda: float
    feature_mode: str
    model_name: str
    model_params: dict[str, Any]


def load_dataset(db_path: Path) -> tuple[pd.DataFrame, list[str]]:
    dataset = build_last_digit_dataset(db_path=db_path)
    dataset = improved.add_top2_target(dataset)
    dataset = improved.add_regime_and_cluster_features(dataset)
    features = improved.get_numeric_features(dataset)
    return dataset, features


def select_features(
    train_df: pd.DataFrame, features: list[str], target: str, feature_mode: str
) -> list[str]:
    if feature_mode == "all":
        return list(features)
    if feature_mode.startswith("topcorr_"):
        k = int(feature_mode.removeprefix("topcorr_"))
        y = train_df[target].astype(float)
        scored: list[tuple[str, float]] = []
        for col in features:
            s = pd.to_numeric(train_df[col], errors="coerce")
            corr = y.corr(s, method="spearman")
            scored.append((col, abs(float(corr)) if pd.notna(corr) else 0.0))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [name for name, _ in scored[:k]]
    return list(features)


def target_k(target: str) -> int:
    if target == "is_rank_1":
        return 1
    if target == "is_top_2":
        return 2
    return 3


def expected_value(hit_rate: float, payout_win: float, payout_loss: float) -> float:
    return float(hit_rate * payout_win + (1.0 - hit_rate) * payout_loss)


def expected_value_with_abstain(
    hit_rate: float, coverage: float, payout_win: float, payout_loss: float
) -> float:
    return float(coverage * expected_value(hit_rate, payout_win, payout_loss))


def realized_diff_topk_per_day(
    diff_values: np.ndarray,
    score: np.ndarray,
    dates: np.ndarray,
    *,
    k: int,
) -> float:
    tmp = pd.DataFrame({"diff": diff_values, "score": score, "date": dates})
    day_sum = (
        tmp.sort_values(["date", "score"], ascending=[True, False])
        .groupby("date", sort=False)
        .apply(lambda g: float(g.head(min(k, len(g)))["diff"].sum()))
    )
    if day_sum.empty:
        return 0.0
    return float(day_sum.mean())


def abstain_hit_at_k(
    y_true: np.ndarray,
    score: np.ndarray,
    dates: np.ndarray,
    *,
    k: int,
    abstain_quantile: float,
) -> tuple[float, float]:
    tmp = pd.DataFrame({"y": y_true, "score": score, "date": dates})
    margins = (
        tmp.sort_values(["date", "score"], ascending=[True, False])
        .groupby("date", sort=False)["score"]
        .apply(lambda s: float(s.iloc[0] - s.iloc[1]) if len(s) >= 2 else 0.0)
    )
    threshold = float(np.quantile(margins.to_numpy(), abstain_quantile))
    keep_dates = margins[margins >= threshold].index
    kept = tmp[tmp["date"].isin(keep_dates)]
    if kept.empty:
        return 0.0, 0.0
    coverage = float(len(keep_dates) / tmp["date"].nunique())
    hit_k = calculate_hit_at_k(
        kept["y"].to_numpy(), kept["score"].to_numpy(), kept["date"].to_numpy(), k=k
    )
    return coverage, float(hit_k)


def abstain_realized_diff_topk_per_day(
    diff_values: np.ndarray,
    score: np.ndarray,
    dates: np.ndarray,
    *,
    k: int,
    abstain_quantile: float,
) -> tuple[float, float]:
    tmp = pd.DataFrame({"diff": diff_values, "score": score, "date": dates})
    margins = (
        tmp.sort_values(["date", "score"], ascending=[True, False])
        .groupby("date", sort=False)["score"]
        .apply(lambda s: float(s.iloc[0] - s.iloc[1]) if len(s) >= 2 else 0.0)
    )
    threshold = float(np.quantile(margins.to_numpy(), abstain_quantile))
    keep_dates = margins[margins >= threshold].index
    kept = tmp[tmp["date"].isin(keep_dates)]
    if kept.empty:
        return 0.0, 0.0
    coverage = float(len(keep_dates) / tmp["date"].nunique())
    kept_day_sum = (
        kept.sort_values(["date", "score"], ascending=[True, False])
        .groupby("date", sort=False)
        .apply(lambda g: float(g.head(min(k, len(g)))["diff"].sum()))
    )
    if kept_day_sum.empty:
        return coverage, 0.0
    return coverage, float(kept_day_sum.mean())


def train_one_seed(
    *,
    train_df: pd.DataFrame,
    valid_df: pd.DataFrame,
    target: str,
    features: list[str],
    decay_lambda: float,
    random_state: int,
    model_params: dict[str, Any],
    temperature_candidates: tuple[float, ...],
    blend_weights: tuple[float, ...],
    abstain_quantiles: tuple[float, ...],
    payout_win: float,
    payout_loss: float,
    objective_mode: str,
    profit_column: str,
) -> dict[str, Any]:
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
    X_valid = valid_df[features].astype(float)
    y_valid = valid_df[target].astype(int).to_numpy()
    cal_dates_np = cal_df["date"].to_numpy()
    valid_dates_np = valid_df["date"].to_numpy()
    profit_cal = pd.to_numeric(cal_df[profit_column], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    profit_valid = pd.to_numeric(valid_df[profit_column], errors="coerce").fillna(0.0).to_numpy(dtype=float)

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
        random_state=random_state + NDCG_RANDOM_STATE_OFFSET,
        decay_lambda=decay_lambda,
        model_params=model_params,
    )

    raw_cal_pair = pair.predict(X_cal)
    raw_cal_ndcg = ndcg.predict(X_cal)
    raw_val_pair = pair.predict(X_valid)
    raw_val_ndcg = ndcg.predict(X_valid)

    t_pair = improved.find_best_temperature(y_cal, raw_cal_pair, cal_dates_np, temperature_candidates)
    t_ndcg = improved.find_best_temperature(y_cal, raw_cal_ndcg, cal_dates_np, temperature_candidates)

    cal_pair_prob = improved.sigmoid(raw_cal_pair, t_pair)
    cal_ndcg_prob = improved.sigmoid(raw_cal_ndcg, t_ndcg)
    val_pair_prob = improved.sigmoid(raw_val_pair, t_pair)
    val_ndcg_prob = improved.sigmoid(raw_val_ndcg, t_ndcg)

    k = target_k(target)
    best_w = 0.5
    best_q = 0.4
    best_obj = -1e18
    for w in blend_weights:
        cal_pred = w * cal_pair_prob + (1.0 - w) * cal_ndcg_prob
        for q in abstain_quantiles:
            cov, abst_hit = abstain_hit_at_k(y_cal, cal_pred, cal_dates_np, k=k, abstain_quantile=q)
            cov_diff, kept_mean_diff = abstain_realized_diff_topk_per_day(
                profit_cal, cal_pred, cal_dates_np, k=k, abstain_quantile=q
            )
            ev = expected_value_with_abstain(abst_hit, cov, payout_win, payout_loss)
            objective_score = float(cov_diff * kept_mean_diff) if objective_mode == "actual_diff" else float(ev)
            if objective_score > best_obj:
                best_obj = objective_score
                best_w = float(w)
                best_q = float(q)

    pred = best_w * val_pair_prob + (1.0 - best_w) * val_ndcg_prob
    hit1 = float(calculate_hit_at_k(y_valid, pred, valid_dates_np, k=1))
    hit2 = float(calculate_hit_at_k(y_valid, pred, valid_dates_np, k=2))
    hit3 = float(calculate_hit_at_k(y_valid, pred, valid_dates_np, k=3))
    nd2 = float(improved.ndcg_at_k(y_valid, pred, valid_dates_np, k=2))
    nd3 = float(improved.ndcg_at_k(y_valid, pred, valid_dates_np, k=3))
    spr = float(improved.spearman_by_group(y_valid, pred, valid_dates_np))
    cov, abst_hit = abstain_hit_at_k(y_valid, pred, valid_dates_np, k=k, abstain_quantile=best_q)
    cov_diff, kept_mean_diff = abstain_realized_diff_topk_per_day(
        profit_valid, pred, valid_dates_np, k=k, abstain_quantile=best_q
    )
    ev_full = expected_value({1: hit1, 2: hit2, 3: hit3}[k], payout_win, payout_loss)
    ev_abstain = expected_value_with_abstain(abst_hit, cov, payout_win, payout_loss)
    actual_diff_full_day = realized_diff_topk_per_day(profit_valid, pred, valid_dates_np, k=k)
    actual_diff_abstain_kept_day = float(kept_mean_diff)
    actual_diff_abstain_overall = float(cov_diff * kept_mean_diff)

    return {
        "pred": pred,
        "y_valid": y_valid,
        "valid_dates": valid_dates_np,
        "metrics": {
            "hit_at_1": hit1,
            "hit_at_2": hit2,
            "hit_at_3": hit3,
            "ndcg_at_2": nd2,
            "ndcg_at_3": nd3,
            "spearman": spr,
            "abstain_coverage": float(cov),
            "abstain_hit_at_k": float(abst_hit),
            "ev_full": float(ev_full),
            "ev_abstain": float(ev_abstain),
            "actual_diff_full_day": float(actual_diff_full_day),
            "actual_diff_abstain_kept_day": float(actual_diff_abstain_kept_day),
            "actual_diff_abstain_overall": float(actual_diff_abstain_overall),
        },
        "blend_weight": best_w,
        "abstain_quantile": best_q,
    }


def aggregate_metrics(rows: list[dict[str, float]]) -> dict[str, float]:
    keys = list(rows[0].keys())
    return {k: float(np.mean([r[k] for r in rows])) for k in keys}


def aggregate_metrics_std(rows: list[dict[str, float]]) -> dict[str, float]:
    keys = list(rows[0].keys())
    return {k: float(np.std([r[k] for r in rows])) for k in keys}


def run_recipe(
    *,
    dataset: pd.DataFrame,
    all_features: list[str],
    recipe: TrainRecipe,
    split_cfg: dict[str, str],
    train_window: dict[str, str],
    seeds: list[int],
    temperature_candidates: tuple[float, ...],
    blend_weights: tuple[float, ...],
    abstain_quantiles: tuple[float, ...],
    payout_win: float,
    payout_loss: float,
    objective_mode: str,
    profit_column: str,
) -> dict[str, Any]:
    train_df, valid_df = improved.split_dataset_by_date_ranges(
        dataset,
        train_start=train_window["train_start"],
        train_end=train_window["train_end"],
        valid_start=split_cfg["valid_start"],
        valid_end=split_cfg["valid_end"],
    )
    features = select_features(train_df, all_features, recipe.target, recipe.feature_mode)

    per_seed: list[dict[str, Any]] = []
    for seed in seeds:
        one = train_one_seed(
            train_df=train_df,
            valid_df=valid_df,
            target=recipe.target,
            features=features,
            decay_lambda=recipe.decay_lambda,
            random_state=seed,
            model_params=recipe.model_params,
            temperature_candidates=temperature_candidates,
            blend_weights=blend_weights,
            abstain_quantiles=abstain_quantiles,
            payout_win=payout_win,
            payout_loss=payout_loss,
            objective_mode=objective_mode,
            profit_column=profit_column,
        )
        one["seed"] = seed
        per_seed.append(one)

    metric_rows = [x["metrics"] for x in per_seed]
    metrics_mean = aggregate_metrics(metric_rows)
    metrics_std = aggregate_metrics_std(metric_rows)
    objective_key = "actual_diff_abstain_overall" if objective_mode == "actual_diff" else "ev_abstain"
    robust_score = metrics_mean[objective_key] - 0.5 * metrics_std[objective_key]

    return {
        "recipe": {
            "target": recipe.target,
            "window_name": recipe.window_name,
            "decay_lambda": recipe.decay_lambda,
            "feature_mode": recipe.feature_mode,
            "model_name": recipe.model_name,
            "model_params": recipe.model_params,
            "n_features": len(features),
        },
        "metrics_mean": metrics_mean,
        "metrics_std": metrics_std,
        "objective_mode": objective_mode,
        "objective_key": objective_key,
        "robust_score": float(robust_score),
        "per_seed": [
            {
                "seed": x["seed"],
                "blend_weight": x["blend_weight"],
                "abstain_quantile": x["abstain_quantile"],
                **x["metrics"],
            }
            for x in per_seed
        ],
    }


def choose_best(results: list[dict[str, Any]], objective_key: str) -> dict[str, Any]:
    return sorted(
        results,
        key=lambda r: (r["robust_score"], r["metrics_mean"][objective_key]),
        reverse=True,
    )[0]


def run_ensemble_report(
    *,
    best_result: dict[str, Any],
    target_results: list[dict[str, Any]],
    objective_key: str,
) -> dict[str, Any]:
    # Seed ensemble proxy: average EV across seeds of the same best recipe.
    seed_rows = best_result["per_seed"]
    seed_mean_ev = float(np.mean([r[objective_key] for r in seed_rows]))
    seed_std_ev = float(np.std([r[objective_key] for r in seed_rows]))

    # Window ensemble proxy: weighted average of EV between two best windows for same target.
    by_window: dict[str, dict[str, Any]] = {}
    for row in target_results:
        name = row["recipe"]["window_name"]
        cur = by_window.get(name)
        if cur is None or row["robust_score"] > cur["robust_score"]:
            by_window[name] = row
    window_candidates = list(by_window.values())
    window_mix: dict[str, Any] = {"enabled": False}
    if len(window_candidates) >= 2:
        w1, w2 = sorted(window_candidates, key=lambda r: r["robust_score"], reverse=True)[:2]
        weights = [0.0, 0.25, 0.5, 0.75, 1.0]
        best_mix = None
        for a in weights:
            ev = a * w1["metrics_mean"][objective_key] + (1.0 - a) * w2["metrics_mean"][objective_key]
            if best_mix is None or ev > best_mix["objective_score"]:
                best_mix = {
                    "weight_first": a,
                    "objective_score": float(ev),
                    "first_window": w1["recipe"]["window_name"],
                    "second_window": w2["recipe"]["window_name"],
                }
        window_mix = {"enabled": True, **best_mix}

    return {
        "seed_ensemble": {
            "objective_key": objective_key,
            "objective_mean": seed_mean_ev,
            "objective_std": seed_std_ev,
        },
        "window_mix_proxy": window_mix,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Profit-first operations optimizer for tail LTR")
    p.add_argument("--db-path", default="", help="DB path (optional)")
    p.add_argument("--db-glob", default="*7.db", help="DB auto-detect glob pattern used when --db-path is empty")
    p.add_argument("--output", default="db/experiments/tail_ltr_profit_ops_report.json", help="Output report JSON")
    p.add_argument("--targets", default="is_top_2,is_top_3")
    p.add_argument("--windows", default="recent_60d,regime2_only")
    p.add_argument("--lambdas", default="0.5,0.75,1.0,1.25,1.5,1.75")
    p.add_argument("--seeds", default="42,77,123")
    p.add_argument("--feature-modes", default="all,topcorr_160")
    p.add_argument("--payout-win", type=float, default=10000.0)
    p.add_argument("--payout-loss", type=float, default=-20000.0)
    p.add_argument(
        "--objective-mode",
        choices=["fixed_payout", "actual_diff"],
        default="fixed_payout",
        help="Optimization objective mode",
    )
    p.add_argument(
        "--profit-column",
        default="total_diff_coins",
        help="Column used when objective-mode=actual_diff",
    )
    p.add_argument("--quick", action="store_true", help="Use smaller search grid for quick iteration")
    p.add_argument("--log-level", default="INFO", help="Logging level (DEBUG/INFO/WARNING/ERROR)")
    return p


def main() -> int:
    args = build_arg_parser().parse_args()
    configure_logging(args.log_level)
    db_path = resolve_db_path(args.db_path, pattern=args.db_glob)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    targets = parse_csv_strs(args.targets)
    windows = parse_csv_strs(args.windows)
    lambdas = parse_csv_floats(args.lambdas)
    seeds = parse_csv_ints(args.seeds)
    feature_modes = parse_csv_strs(args.feature_modes)

    model_grid = [
        ("base", {}),
        ("reg_small", {"max_depth": 3, "min_child_weight": 4, "reg_lambda": 2.0, "subsample": 0.85, "colsample_bytree": 0.85}),
    ]
    if args.quick:
        lambdas = lambdas[:3]
        seeds = seeds[:2]
        feature_modes = feature_modes[:1]
        model_grid = model_grid[:1]

    dataset, features = load_dataset(db_path)
    if args.objective_mode == "actual_diff" and args.profit_column not in dataset.columns:
        raise KeyError(f"Profit column not found: {args.profit_column}")
    split_cfg = improved.build_fixed_split_configs(dataset)["regime_3_fixed_split"]
    window_cfgs = improved.build_window_sweep_configs(valid_start=split_cfg["valid_start"])
    selected_windows = {k: window_cfgs[k] for k in windows}

    report: dict[str, Any] = {
        "db_path": str(db_path),
        "dataset_rows": int(len(dataset)),
        "feature_count": int(len(features)),
        "objective_mode": args.objective_mode,
        "profit_column": args.profit_column,
        "split_cfg": split_cfg,
        "search_space": {
            "targets": targets,
            "windows": windows,
            "lambdas": lambdas,
            "seeds": seeds,
            "feature_modes": feature_modes,
            "model_grid": [{"name": n, "params": p} for n, p in model_grid],
        },
        "results_by_target": {},
    }

    temperature_candidates = improved.CalibrationConfig().temperature_candidates
    blend_weights = improved.CalibrationConfig().blend_weights
    abstain_quantiles = improved.CalibrationConfig().abstain_quantiles

    for target in targets:
        results: list[dict[str, Any]] = []
        recipes: list[TrainRecipe] = []
        for window_name, cfg in selected_windows.items():
            for lam in lambdas:
                for feature_mode in feature_modes:
                    for model_name, model_params in model_grid:
                        recipes.append(
                            TrainRecipe(
                                target=target,
                                window_name=window_name,
                                decay_lambda=lam,
                                feature_mode=feature_mode,
                                model_name=model_name,
                                model_params=model_params,
                            )
                        )

        for i, recipe in enumerate(recipes, start=1):
            logger.info(
                "[%s] %d/%d window=%s lambda=%s feat=%s model=%s",
                target,
                i,
                len(recipes),
                recipe.window_name,
                recipe.decay_lambda,
                recipe.feature_mode,
                recipe.model_name,
            )
            result = run_recipe(
                dataset=dataset,
                all_features=features,
                recipe=recipe,
                split_cfg=split_cfg,
                train_window=selected_windows[recipe.window_name],
                seeds=seeds,
                temperature_candidates=temperature_candidates,
                blend_weights=blend_weights,
                abstain_quantiles=abstain_quantiles,
                payout_win=args.payout_win,
                payout_loss=args.payout_loss,
                objective_mode=args.objective_mode,
                profit_column=args.profit_column,
            )
            results.append(result)

        objective_key = "actual_diff_abstain_overall" if args.objective_mode == "actual_diff" else "ev_abstain"
        best = choose_best(results, objective_key=objective_key)
        ensemble = run_ensemble_report(
            best_result=best,
            target_results=results,
            objective_key=objective_key,
        )
        report["results_by_target"][target] = {
            "objective_key": objective_key,
            "best": best,
            "ensemble_report": ensemble,
        }

    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Saved report: %s", output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
