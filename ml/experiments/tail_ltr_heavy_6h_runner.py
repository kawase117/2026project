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
class Candidate:
    window_name: str
    decay_lambda: float


def parse_csv_ints(raw: str) -> list[int]:
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def parse_csv_floats(raw: str) -> list[float]:
    return [float(x.strip()) for x in raw.split(",") if x.strip()]


def max_drawdown(x: np.ndarray) -> float:
    c = np.cumsum(np.asarray(x, dtype=float))
    peak = np.maximum.accumulate(c)
    dd = peak - c
    return float(np.max(dd)) if dd.size else 0.0


def summarize_series(x: np.ndarray) -> dict[str, float]:
    arr = np.asarray(x, dtype=float)
    if arr.size == 0:
        return {"mean": 0.0, "std": 0.0, "n_days": 0, "max_drawdown": 0.0}
    return {
        "mean": float(arr.mean()),
        "std": float(arr.std(ddof=0)),
        "n_days": int(arr.size),
        "max_drawdown": max_drawdown(arr),
    }


def choose_by_objective(day_excess: np.ndarray, alpha: float, beta: float) -> float:
    arr = np.asarray(day_excess, dtype=float)
    if arr.size == 0:
        return -1e18
    return float(arr.mean() - alpha * arr.std(ddof=0) - beta * max_drawdown(arr))


def evaluate_candidates_on_fold(
    *,
    dataset: pd.DataFrame,
    all_features: list[str],
    candidates: list[Candidate],
    seed: int,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    q_grid: list[float],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    temp_candidates = improved.CalibrationConfig().temperature_candidates
    blend_weights = improved.CalibrationConfig().blend_weights
    dts = pd.to_datetime(dataset["date"])

    for cand in candidates:
        train_start, train_end = build_train_window(cand.window_name, test_start)
        train_mask = (dts >= train_start) & (dts <= train_end)
        test_mask = (dts >= test_start) & (dts <= test_end)
        train_df = dataset.loc[train_mask].copy()
        test_df = dataset.loc[test_mask].copy()
        if train_df["date"].nunique() < 42 or test_df.empty:
            continue

        features = ops.select_features(train_df, all_features, "is_top_2", "all")
        cal_pred_df, test_pred_df, choice = train_and_predict_fold(
            train_df=train_df,
            test_df=test_df,
            target="is_top_2",
            features=features,
            decay_lambda=cand.decay_lambda,
            random_state=seed,
            model_params={},
            temperature_candidates=temp_candidates,
            blend_weights=blend_weights,
            q_grid=q_grid,
            k=2,
        )

        cal_day = topk_day_table(cal_pred_df, "pred", k=2)
        test_day = topk_day_table(test_pred_df, "pred", k=2)
        cal_keep = cal_day["margin"] >= choice["threshold"]
        test_keep = test_day["margin"] >= choice["threshold"]
        cal_ex = np.where(cal_keep.to_numpy(), cal_day["excess"].to_numpy(), 0.0)
        test_ex = np.where(test_keep.to_numpy(), test_day["excess"].to_numpy(), 0.0)

        out.append(
            {
                "window_name": cand.window_name,
                "decay_lambda": cand.decay_lambda,
                "q": float(choice["q"]),
                "threshold": float(choice["threshold"]),
                "cal_excess_daily": cal_ex,
                "test_excess_daily": test_ex,
                "test_dates": test_day["date"].astype(str).tolist(),
                "cal_mean": float(np.mean(cal_ex)),
                "test_mean": float(np.mean(test_ex)),
                "cal_std": float(np.std(cal_ex, ddof=0)),
                "cal_mdd": max_drawdown(cal_ex),
            }
        )
    return out


def run_policy(
    *,
    dataset: pd.DataFrame,
    all_features: list[str],
    seeds: list[int],
    candidates: list[Candidate],
    q_grid: list[float],
    test_days: int,
    objective_alpha: float,
    objective_beta: float,
) -> dict[str, Any]:
    split_cfg = improved.build_fixed_split_configs(dataset)["regime_3_fixed_split"]
    valid_start = pd.Timestamp(split_cfg["valid_start"])
    valid_end = pd.Timestamp(split_cfg["valid_end"])
    valid_dates = sorted(pd.to_datetime(dataset["date"].unique()))
    valid_dates = [d for d in valid_dates if valid_start <= d <= valid_end]

    all_daily: list[dict[str, Any]] = []
    fold_details: list[dict[str, Any]] = []

    for seed in seeds:
        idx = 56
        fold = 0
        while idx < len(valid_dates):
            test_start = valid_dates[idx]
            test_block = valid_dates[idx : idx + test_days]
            if not test_block:
                break
            test_end = test_block[-1]

            cand_rows = evaluate_candidates_on_fold(
                dataset=dataset,
                all_features=all_features,
                candidates=candidates,
                seed=seed,
                test_start=test_start,
                test_end=test_end,
                q_grid=q_grid,
            )
            if not cand_rows:
                idx += test_days
                continue

            best = sorted(
                cand_rows,
                key=lambda r: choose_by_objective(r["cal_excess_daily"], objective_alpha, objective_beta),
                reverse=True,
            )[0]
            chosen_score = choose_by_objective(best["cal_excess_daily"], objective_alpha, objective_beta)
            for d, ex in zip(best["test_dates"], best["test_excess_daily"]):
                all_daily.append(
                    {
                        "seed": seed,
                        "fold": fold,
                        "date": d,
                        "window_name": best["window_name"],
                        "decay_lambda": best["decay_lambda"],
                        "q": best["q"],
                        "excess": float(ex),
                    }
                )
            fold_details.append(
                {
                    "seed": seed,
                    "fold": fold,
                    "test_start": str(test_start.date()),
                    "test_end": str(test_end.date()),
                    "window_name": best["window_name"],
                    "decay_lambda": best["decay_lambda"],
                    "q": best["q"],
                    "cal_objective": float(chosen_score),
                    "test_mean": float(best["test_mean"]),
                }
            )
            fold += 1
            idx += test_days

    df = pd.DataFrame(all_daily).sort_values(["seed", "date"])
    arr = df["excess"].to_numpy(dtype=float) if not df.empty else np.array([], dtype=float)
    return {
        "objective_alpha": objective_alpha,
        "objective_beta": objective_beta,
        "summary": {**summarize_series(arr), **bootstrap_ci(arr, n_boot=10000, seed=20260522)},
        "daily": df,
        "fold_details": fold_details,
    }


def simulate_retrain_trigger(daily_df: pd.DataFrame, *, rolling_days: int, cooldown_days: int) -> dict[str, Any]:
    if daily_df.empty:
        return {"triggers": 0, "mean_excess_with_trigger": 0.0, "mean_excess_raw": 0.0}
    out_rows: list[pd.DataFrame] = []
    trigger_count = 0
    for seed, grp in daily_df.groupby("seed", sort=False):
        g = grp.sort_values("date").copy().reset_index(drop=True)
        ex = g["excess"].to_numpy(dtype=float)
        played = np.ones_like(ex, dtype=int)
        cooldown = 0
        for i in range(len(ex)):
            if cooldown > 0:
                played[i] = 0
                cooldown -= 1
                continue
            # Causal trigger: decide today's play/skip using past results only.
            st = max(0, i - rolling_days)
            w = ex[st:i]
            if len(w) >= rolling_days:
                mean = float(np.mean(w))
                std = float(np.std(w, ddof=1))
                se = std / np.sqrt(len(w)) if len(w) > 1 else 0.0
                ci_low = mean - 1.96 * se
                if mean < 0.0 or ci_low < 0.0:
                    trigger_count += 1
                    cooldown = cooldown_days
                    played[i] = 0
        g["played"] = played
        g["excess_triggered"] = g["excess"] * g["played"]
        out_rows.append(g)
    merged = pd.concat(out_rows, ignore_index=True)
    return {
        "rolling_days": rolling_days,
        "cooldown_days": cooldown_days,
        "triggers": int(trigger_count),
        "mean_excess_raw": float(merged["excess"].mean()),
        "mean_excess_with_trigger": float(merged["excess_triggered"].mean()),
        "play_rate": float(merged["played"].mean()),
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Heavy 6h runner for top2 operational improvements")
    p.add_argument("--seeds", default="42,77,123,202,303,404,505,606")
    p.add_argument("--windows", default="recent_60d,regime2_only,full_2025")
    p.add_argument("--lambdas", default="0.75,1.0,1.25")
    p.add_argument("--q-grid", default="0.0,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8")
    p.add_argument("--test-days", type=int, default=14)
    p.add_argument("--output-dir", default="db/experiments")
    return p


def main() -> int:
    args = build_parser().parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    seeds = parse_csv_ints(args.seeds)
    windows = [w.strip() for w in args.windows.split(",") if w.strip()]
    lambdas = parse_csv_floats(args.lambdas)
    q_grid = parse_csv_floats(args.q_grid)
    candidates = [Candidate(window_name=w, decay_lambda=lam) for w in windows for lam in lambdas]

    dataset, all_features = ops.load_dataset(ops.resolve_db_path(""))
    dataset = dataset.sort_values("date").reset_index(drop=True)

    # 1) Regime switch WF (alpha=0,beta=0: mean excess objective)
    regime_policy = run_policy(
        dataset=dataset,
        all_features=all_features,
        seeds=seeds,
        candidates=candidates,
        q_grid=q_grid,
        test_days=args.test_days,
        objective_alpha=0.0,
        objective_beta=0.0,
    )
    regime_daily = regime_policy["daily"].copy()
    regime_csv = out_dir / "tail_ltr_regime_switch_wf.csv"
    regime_daily.to_csv(regime_csv, index=False, encoding="utf-8-sig")

    # 2) Objective-direct optimization WF (alpha,beta sweep)
    objective_rows: list[dict[str, Any]] = []
    objective_results: list[dict[str, Any]] = []
    for alpha in [0.10, 0.25, 0.40]:
        for beta in [0.0005, 0.0010, 0.0020]:
            pol = run_policy(
                dataset=dataset,
                all_features=all_features,
                seeds=seeds,
                candidates=candidates,
                q_grid=q_grid,
                test_days=args.test_days,
                objective_alpha=alpha,
                objective_beta=beta,
            )
            s = pol["summary"]
            objective_rows.append(
                {
                    "alpha": alpha,
                    "beta": beta,
                    "mean_excess": s["mean"],
                    "std_excess": s["std"],
                    "ci_low": s["ci_low"],
                    "ci_high": s["ci_high"],
                    "p_gt_0": s["p_gt_0"],
                    "max_drawdown": s["max_drawdown"],
                    "n_days": s["n_days"],
                    "robust_score": s["mean"] - alpha * s["std"] - beta * s["max_drawdown"],
                }
            )
            objective_results.append(pol)
            print(
                f"[objective] alpha={alpha:.2f} beta={beta:.4f} "
                f"mean={s['mean']:.4f} ci=[{s['ci_low']:.4f},{s['ci_high']:.4f}]"
            )
    obj_df = pd.DataFrame(objective_rows).sort_values("robust_score", ascending=False)
    obj_csv = out_dir / "tail_ltr_excess_objective_wf.csv"
    obj_df.to_csv(obj_csv, index=False, encoding="utf-8-sig")

    best_alpha = float(obj_df.iloc[0]["alpha"])
    best_beta = float(obj_df.iloc[0]["beta"])
    best_policy = next(
        p for p in objective_results if p["objective_alpha"] == best_alpha and p["objective_beta"] == best_beta
    )

    # 3) Retrain-trigger simulation on best objective policy
    trigger_stats = []
    for rolling_days, cooldown_days in [(21, 3), (28, 3), (28, 7), (35, 7)]:
        st = simulate_retrain_trigger(best_policy["daily"], rolling_days=rolling_days, cooldown_days=cooldown_days)
        trigger_stats.append(st)
        print(
            f"[trigger] roll={rolling_days} cool={cooldown_days} "
            f"raw={st['mean_excess_raw']:.4f} with_trigger={st['mean_excess_with_trigger']:.4f}"
        )

    trigger_json = out_dir / "tail_ltr_retrain_trigger_simulation.json"
    trigger_payload = {
        "base_policy": {
            "alpha": best_alpha,
            "beta": best_beta,
            "summary": best_policy["summary"],
        },
        "trigger_stats": trigger_stats,
    }
    trigger_json.write_text(json.dumps(trigger_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # 4) Final operational spec
    best_trigger = sorted(trigger_stats, key=lambda x: x["mean_excess_with_trigger"], reverse=True)[0]
    spec_path = out_dir / "tail_ltr_final_operational_spec.md"
    spec = (
        "# Tail LTR Final Operational Spec\n\n"
        "## Regime Switching\n"
        f"- Candidate windows: `{windows}`\n"
        f"- Candidate lambdas: `{lambdas}`\n"
        f"- Seeds: `{seeds}`\n"
        f"- Test block size: `{args.test_days}` days\n\n"
        "## Best Objective\n"
        f"- alpha: `{best_alpha}`\n"
        f"- beta: `{best_beta}`\n"
        f"- mean excess: `{best_policy['summary']['mean']:.4f}`\n"
        f"- 95% CI: `[{best_policy['summary']['ci_low']:.4f}, {best_policy['summary']['ci_high']:.4f}]`\n"
        f"- p(excess>0): `{best_policy['summary']['p_gt_0']:.4f}`\n\n"
        "## Trigger Policy\n"
        f"- rolling_days: `{best_trigger['rolling_days']}`\n"
        f"- cooldown_days: `{best_trigger['cooldown_days']}`\n"
        f"- mean excess (raw): `{best_trigger['mean_excess_raw']:.4f}`\n"
        f"- mean excess (with trigger): `{best_trigger['mean_excess_with_trigger']:.4f}`\n"
        f"- play_rate: `{best_trigger['play_rate']:.4f}`\n"
    )
    spec_path.write_text(spec, encoding="utf-8")

    print(f"Saved: {regime_csv}")
    print(f"Saved: {obj_csv}")
    print(f"Saved: {trigger_json}")
    print(f"Saved: {spec_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
