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
class EvalConfig:
    window_name: str
    decay_lambda: float
    feature_mode: str = "all"
    model_params: dict[str, Any] | None = None


def parse_csv_floats(raw: str) -> list[float]:
    return [float(x.strip()) for x in raw.split(",") if x.strip()]


def parse_csv_ints(raw: str) -> list[int]:
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def eval_top2_config(
    *,
    dataset: pd.DataFrame,
    all_features: list[str],
    seeds: list[int],
    eval_cfg: EvalConfig,
    q_grid: list[float],
    cal_days: int,
    test_days: int,
    min_cal_days: int,
) -> dict[str, Any]:
    split_cfg = improved.build_fixed_split_configs(dataset)["regime_3_fixed_split"]
    valid_start = pd.Timestamp(split_cfg["valid_start"])
    valid_end = pd.Timestamp(split_cfg["valid_end"])

    all_valid_dates = sorted(pd.to_datetime(dataset["date"].unique()))
    all_valid_dates = [d for d in all_valid_dates if valid_start <= d <= valid_end]

    temp_candidates = improved.CalibrationConfig().temperature_candidates
    blend_weights = improved.CalibrationConfig().blend_weights

    excess_all: list[float] = []
    q_selected: list[float] = []
    fold_rows: list[dict[str, Any]] = []

    for seed in seeds:
        idx = max(cal_days, min_cal_days)
        fold_no = 0
        while idx < len(all_valid_dates):
            test_start = all_valid_dates[idx]
            test_dates = all_valid_dates[idx : idx + test_days]
            if not test_dates:
                break
            test_end = test_dates[-1]

            train_start, train_end = build_train_window(eval_cfg.window_name, test_start)

            dts = pd.to_datetime(dataset["date"])
            train_mask = (dts >= train_start) & (dts <= train_end)
            test_mask = (dts >= test_start) & (dts <= test_end)

            train_df = dataset.loc[train_mask].copy()
            test_df = dataset.loc[test_mask].copy()
            if train_df["date"].nunique() < min_cal_days or test_df.empty:
                idx += test_days
                continue

            features = ops.select_features(train_df, all_features, "is_top_2", eval_cfg.feature_mode)
            _, test_pred_df, choice = train_and_predict_fold(
                train_df=train_df,
                test_df=test_df,
                target="is_top_2",
                features=features,
                decay_lambda=eval_cfg.decay_lambda,
                random_state=seed,
                model_params=eval_cfg.model_params or {},
                temperature_candidates=temp_candidates,
                blend_weights=blend_weights,
                q_grid=q_grid,
                k=2,
            )
            day_tst = topk_day_table(test_pred_df, "pred", k=2)
            keep = day_tst["margin"] >= choice["threshold"]
            ex = np.where(keep.to_numpy(), day_tst["excess"].to_numpy(), 0.0)

            excess_all.extend(ex.tolist())
            q_selected.append(float(choice["q"]))

            fold_rows.append(
                {
                    "seed": seed,
                    "fold": fold_no,
                    "test_start": str(test_start.date()),
                    "test_end": str(test_end.date()),
                    "train_days": int(train_df["date"].nunique()),
                    "q": float(choice["q"]),
                    "threshold": float(choice["threshold"]),
                    "excess_mean": float(np.mean(ex)),
                }
            )
            fold_no += 1
            idx += test_days

    arr = np.asarray(excess_all, dtype=float)
    mean = float(arr.mean()) if arr.size else 0.0
    std = float(arr.std(ddof=0)) if arr.size else 0.0
    ci = bootstrap_ci(arr, n_boot=12000, seed=20260521)
    robust = mean - 0.25 * std
    return {
        "window_name": eval_cfg.window_name,
        "decay_lambda": eval_cfg.decay_lambda,
        "feature_mode": eval_cfg.feature_mode,
        "seeds": seeds,
        "n_days": int(arr.size),
        "mean_excess": mean,
        "std_excess": std,
        "ci_low": ci["ci_low"],
        "ci_high": ci["ci_high"],
        "p_gt_0": ci["p_gt_0"],
        "robust_score": robust,
        "q_selected_mean": float(np.mean(q_selected)) if q_selected else 0.0,
        "q_selected_std": float(np.std(q_selected, ddof=0)) if q_selected else 0.0,
        "fold_details": fold_rows,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Top2 6h plan runner")
    p.add_argument("--output-prefix", default="db/experiments/tail_ltr_top2_6h")
    p.add_argument("--seeds-base", default="42,77,123")
    p.add_argument("--seeds-extended", default="42,77,123,202,303,404")
    p.add_argument("--windows", default="recent_60d,regime2_only,full_2025")
    p.add_argument("--lambdas", default="0.75,1.0")
    p.add_argument("--q-coarse", default="0.0,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8")
    p.add_argument("--q-fine-start", type=float, default=0.0)
    p.add_argument("--q-fine-end", type=float, default=0.9)
    p.add_argument("--q-fine-step", type=float, default=0.02)
    p.add_argument("--cal-days", type=int, default=56)
    p.add_argument("--test-days", type=int, default=14)
    p.add_argument("--min-cal-days", type=int, default=42)
    return p


def run() -> int:
    args = build_parser().parse_args()
    output_prefix = Path(args.output_prefix)
    output_prefix.parent.mkdir(parents=True, exist_ok=True)

    seeds_base = parse_csv_ints(args.seeds_base)
    seeds_ext = parse_csv_ints(args.seeds_extended)
    windows = [w.strip() for w in args.windows.split(",") if w.strip()]
    lambdas = parse_csv_floats(args.lambdas)
    q_coarse = parse_csv_floats(args.q_coarse)
    q_fine = list(
        np.round(
            np.arange(args.q_fine_start, args.q_fine_end + args.q_fine_step * 0.5, args.q_fine_step),
            4,
        )
    )

    dataset, all_features = ops.load_dataset(ops.resolve_db_path(""))
    dataset = dataset.sort_values("date").reset_index(drop=True)

    # Step 1: 6-run matrix
    matrix_rows: list[dict[str, Any]] = []
    for window_name in windows:
        for lam in lambdas:
            cfg = EvalConfig(window_name=window_name, decay_lambda=lam, feature_mode="all", model_params={})
            res = eval_top2_config(
                dataset=dataset,
                all_features=all_features,
                seeds=seeds_base,
                eval_cfg=cfg,
                q_grid=q_coarse,
                cal_days=args.cal_days,
                test_days=args.test_days,
                min_cal_days=args.min_cal_days,
            )
            matrix_rows.append(res)
            print(
                f"[matrix] window={window_name} lambda={lam} "
                f"mean={res['mean_excess']:.4f} ci=[{res['ci_low']:.4f},{res['ci_high']:.4f}]"
            )

    matrix_df = pd.DataFrame(
        [
            {
                "window_name": r["window_name"],
                "decay_lambda": r["decay_lambda"],
                "mean_excess": r["mean_excess"],
                "std_excess": r["std_excess"],
                "ci_low": r["ci_low"],
                "ci_high": r["ci_high"],
                "p_gt_0": r["p_gt_0"],
                "robust_score": r["robust_score"],
                "n_days": r["n_days"],
                "q_selected_mean": r["q_selected_mean"],
                "q_selected_std": r["q_selected_std"],
            }
            for r in matrix_rows
        ]
    ).sort_values("robust_score", ascending=False)
    matrix_csv = output_prefix.with_name(output_prefix.name + "_matrix.csv")
    matrix_df.to_csv(matrix_csv, index=False, encoding="utf-8-sig")

    # Step 2: fine q search for top3 configs
    top3 = matrix_df.head(3).to_dict("records")
    refined_rows: list[dict[str, Any]] = []
    for row in top3:
        cfg = EvalConfig(
            window_name=str(row["window_name"]),
            decay_lambda=float(row["decay_lambda"]),
            feature_mode="all",
            model_params={},
        )
        res = eval_top2_config(
            dataset=dataset,
            all_features=all_features,
            seeds=seeds_base,
            eval_cfg=cfg,
            q_grid=q_fine,
            cal_days=args.cal_days,
            test_days=args.test_days,
            min_cal_days=args.min_cal_days,
        )
        refined_rows.append(res)
        print(
            f"[refine] window={cfg.window_name} lambda={cfg.decay_lambda} "
            f"mean={res['mean_excess']:.4f} ci=[{res['ci_low']:.4f},{res['ci_high']:.4f}]"
        )

    refined_df = pd.DataFrame(
        [
            {
                "window_name": r["window_name"],
                "decay_lambda": r["decay_lambda"],
                "mean_excess": r["mean_excess"],
                "std_excess": r["std_excess"],
                "ci_low": r["ci_low"],
                "ci_high": r["ci_high"],
                "p_gt_0": r["p_gt_0"],
                "robust_score": r["robust_score"],
                "n_days": r["n_days"],
                "q_selected_mean": r["q_selected_mean"],
                "q_selected_std": r["q_selected_std"],
            }
            for r in refined_rows
        ]
    ).sort_values("robust_score", ascending=False)
    refined_csv = output_prefix.with_name(output_prefix.name + "_refined_top3.csv")
    refined_df.to_csv(refined_csv, index=False, encoding="utf-8-sig")

    # Step 3: seed-extended rerun for top2 refined settings
    top2_refined = refined_df.head(2).to_dict("records")
    extended_rows: list[dict[str, Any]] = []
    for row in top2_refined:
        cfg = EvalConfig(
            window_name=str(row["window_name"]),
            decay_lambda=float(row["decay_lambda"]),
            feature_mode="all",
            model_params={},
        )
        res = eval_top2_config(
            dataset=dataset,
            all_features=all_features,
            seeds=seeds_ext,
            eval_cfg=cfg,
            q_grid=q_fine,
            cal_days=args.cal_days,
            test_days=args.test_days,
            min_cal_days=args.min_cal_days,
        )
        extended_rows.append(res)
        print(
            f"[extended] window={cfg.window_name} lambda={cfg.decay_lambda} "
            f"mean={res['mean_excess']:.4f} ci=[{res['ci_low']:.4f},{res['ci_high']:.4f}]"
        )

    extended_df = pd.DataFrame(
        [
            {
                "window_name": r["window_name"],
                "decay_lambda": r["decay_lambda"],
                "mean_excess": r["mean_excess"],
                "std_excess": r["std_excess"],
                "ci_low": r["ci_low"],
                "ci_high": r["ci_high"],
                "p_gt_0": r["p_gt_0"],
                "robust_score": r["robust_score"],
                "n_days": r["n_days"],
                "q_selected_mean": r["q_selected_mean"],
                "q_selected_std": r["q_selected_std"],
            }
            for r in extended_rows
        ]
    ).sort_values("robust_score", ascending=False)
    extended_csv = output_prefix.with_name(output_prefix.name + "_extended_top2.csv")
    extended_df.to_csv(extended_csv, index=False, encoding="utf-8-sig")

    best = extended_rows[0] if len(extended_rows) == 1 else sorted(extended_rows, key=lambda x: x["robust_score"], reverse=True)[0]

    # Step 4: stability split (first/second half) on best run
    folds_df = pd.DataFrame(best["fold_details"]).sort_values("test_start")
    mid = len(folds_df) // 2
    first_half = folds_df.iloc[:mid]["excess_mean"]
    second_half = folds_df.iloc[mid:]["excess_mean"]
    stability = {
        "first_half_mean": float(first_half.mean()) if len(first_half) else 0.0,
        "second_half_mean": float(second_half.mean()) if len(second_half) else 0.0,
        "delta_second_minus_first": float(second_half.mean() - first_half.mean()) if len(first_half) and len(second_half) else 0.0,
    }

    summary = {
        "config": {
            "seeds_base": seeds_base,
            "seeds_extended": seeds_ext,
            "windows": windows,
            "lambdas": lambdas,
            "q_coarse": q_coarse,
            "q_fine_range": [args.q_fine_start, args.q_fine_end, args.q_fine_step],
            "cal_days": args.cal_days,
            "test_days": args.test_days,
            "min_cal_days": args.min_cal_days,
        },
        "artifacts": {
            "matrix_csv": str(matrix_csv),
            "refined_csv": str(refined_csv),
            "extended_csv": str(extended_csv),
        },
        "best_config": {
            "window_name": best["window_name"],
            "decay_lambda": best["decay_lambda"],
            "mean_excess": best["mean_excess"],
            "ci_low": best["ci_low"],
            "ci_high": best["ci_high"],
            "p_gt_0": best["p_gt_0"],
            "q_selected_mean": best["q_selected_mean"],
        },
        "stability": stability,
    }
    summary_path = output_prefix.with_name(output_prefix.name + "_best.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # short operation playbook
    playbook_path = output_prefix.with_name(output_prefix.name + "_operation_playbook.md")
    playbook = (
        "# Top2 Operation Playbook\n\n"
        f"- Window: `{best['window_name']}`\n"
        f"- Lambda: `{best['decay_lambda']}`\n"
        f"- Threshold policy: fold-trained q mean `{best['q_selected_mean']:.3f}`\n"
        f"- Expected excess: `{best['mean_excess']:.3f}` coins/machine/day vs store mean\n"
        f"- 95% CI: `[{best['ci_low']:.3f}, {best['ci_high']:.3f}]`\n"
        f"- p(excess>0): `{best['p_gt_0']:.3f}`\n"
        "- Fallback: if daily model confidence is unstable or data missing, skip play.\n"
    )
    playbook_path.write_text(playbook, encoding="utf-8")

    print(f"Saved matrix: {matrix_csv}")
    print(f"Saved refined: {refined_csv}")
    print(f"Saved extended: {extended_csv}")
    print(f"Saved summary: {summary_path}")
    print(f"Saved playbook: {playbook_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
