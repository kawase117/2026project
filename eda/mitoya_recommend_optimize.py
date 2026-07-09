from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda.mitoya_prompt_common import ensure_results_dir, render_markdown_table  # noqa: E402
from eda import mitoya_recommend_backtest as backtest_mod  # noqa: E402
from eda.mitoya_recommend_backtest import (  # noqa: E402
    DEFAULT_RANDOM_SAMPLES,
    DEFAULT_SPLIT_DATE,
    DEFAULT_TOP_N,
    WalkForwardCase,
    build_section_baselines,
    current_weight_vector,
    prepare_backtest_frame,
    score_features,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


STAGE1_GRID = {
    "h_jug_corner1": [200, 300, 400, 500, 600],
    "h_jug_corner24": [50, 100, 150, 200, 250],
    "h_jug_corner59": [0, 15, 30, 50],
}
STAGE2_GRID = {
    "h_nonjug_xdds": [100, 150, 200, 250, 300],
    "h_nonjug_corner1_xdds": [150, 200, 300, 400, 500],
    "h_nonjug_corner1_nonevent_penalty": [-200, -150, -100, -50, 0],
}
STAGE3_GRID = {
    "dd24_boost": [200, 300, 400, 500, 600, 700],
    "section_baseline_scale": [0.0, 0.05, 0.1, 0.15, 0.2],
}


def prepare_optimization_frame(frame: pd.DataFrame | None = None, *, min_games: int = 1000) -> pd.DataFrame:
    return prepare_backtest_frame(frame, min_games=min_games)


def build_feature_frame(
    df: pd.DataFrame,
    *,
    dd: int,
    section_baselines: dict[str, float],
) -> pd.DataFrame:
    return backtest_mod.build_feature_frame(df, dd=dd, section_baselines=section_baselines)


def build_section_baselines_for(train: pd.DataFrame) -> dict[str, float]:
    return build_section_baselines(train)


def score_features_for(feature_frame: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    return score_features(feature_frame, weights)


def _build_cases(prepared: pd.DataFrame, *, split_date: str = DEFAULT_SPLIT_DATE) -> list[WalkForwardCase]:
    return backtest_mod._build_cases(prepared, split_date=split_date)


FEATURE_KEYS = [
    "h_jug_corner1",
    "h_jug_corner24",
    "h_jug_corner59",
    "h_jug_xdds",
    "h_jug_section_641_657",
    "h_jug_section_675_691",
    "h_jug_section_658_674",
    "h_nonjug_xdds",
    "h_nonjug_corner1_xdds",
    "h_nonjug_corner1_nonevent_penalty",
    "dd24_boost",
    "v_jug_xdds",
    "v_jug_section_723_733",
    "v_jug_section_734_744",
    "v_jug_section_712_722",
    "mixed_805_debut_xdds",
    "mixed_805_growth_xdds_penalty",
]


def _weights_to_vector(weights: dict[str, float]) -> tuple[np.ndarray, float]:
    """重み dict → (feature_weights_array, baseline_scale) に変換"""
    w = np.array([float(weights.get(k, 0.0)) for k in FEATURE_KEYS], dtype=np.float64)
    return w, float(weights.get("section_baseline_scale", 0.0))


def _precompute_cases(
    cases: list[WalkForwardCase],
    *,
    top_n: int,
    random_samples: int,
) -> list[dict]:
    """v_nonjug 除外・特徴量行列・diff 配列・random baseline を事前計算してキャッシュ"""
    precomputed = []
    for case in cases:
        eligible = case.feature_frame.loc[case.feature_frame["segment"] != "v_nonjug"]
        if eligible.empty:
            continue
        diff_values = pd.to_numeric(eligible["diff"], errors="coerce").dropna().to_numpy().astype(np.float64)
        if len(diff_values) == 0:
            continue
        rng = np.random.default_rng(int(case.test_date))
        n_draw = min(top_n, len(diff_values))
        replace = len(diff_values) < n_draw
        random_avg = float(
            np.mean(
                [float(np.mean(rng.choice(diff_values, size=n_draw, replace=replace))) for _ in range(random_samples)]
            )
        )
        feat_cols = [k for k in FEATURE_KEYS if k in eligible.columns]
        feat_matrix = eligible[feat_cols].to_numpy(dtype=np.float64)
        baseline_raw = eligible["section_baseline_raw"].to_numpy(dtype=np.float64)
        all_diff = eligible["diff"].to_numpy(dtype=np.float64)
        precomputed.append(
            {
                "case": case,
                "feat_matrix": feat_matrix,
                "baseline_raw": baseline_raw,
                "all_diff": all_diff,
                "random_avg": random_avg,
                "n_draw": n_draw,
            }
        )
    return precomputed


def _window_lift_fast(
    pre: dict,
    weight_vec: np.ndarray,
    baseline_scale: float,
    *,
    top_n: int,
) -> float:
    """numpy 行列演算で score -> top-N の lift を返す"""
    scores = pre["feat_matrix"] @ weight_vec + pre["baseline_raw"] * baseline_scale
    top_idx = np.argpartition(scores, -min(top_n, len(scores)))[-top_n:]
    top_diff = float(np.mean(pre["all_diff"][top_idx]))
    return top_diff - pre["random_avg"]


def _evaluate_weights(
    precomputed: list[dict],
    weights: dict[str, float],
    *,
    top_n: int,
    random_samples: int = 0,
) -> dict[str, float]:
    weight_vec, baseline_scale = _weights_to_vector(weights)
    by_window: dict[str, list[float]] = {"pre": [], "post": []}
    for pre in precomputed:
        lift = _window_lift_fast(pre, weight_vec, baseline_scale, top_n=top_n)
        if np.isfinite(lift):
            by_window[pre["case"].window].append(float(lift))

    lift_a = float(np.mean(by_window["pre"])) if by_window["pre"] else float("nan")
    lift_b = float(np.mean(by_window["post"])) if by_window["post"] else float("nan")
    lift_avg = float(np.nanmean([lift_a, lift_b])) if np.isfinite([lift_a, lift_b]).any() else float("nan")
    return {"lift@10_A": lift_a, "lift@10_B": lift_b, "lift@10_avg": lift_avg}


def _grid_rows(
    precomputed: list[dict],
    *,
    base_weights: dict[str, float],
    grid: dict[str, list[float]],
    stage: str,
    top_n: int,
) -> tuple[pd.DataFrame, dict[str, float], dict[str, float]]:
    rows: list[dict[str, object]] = []
    best_weights = dict(base_weights)
    best_metrics = {"lift@10_A": float("nan"), "lift@10_B": float("nan"), "lift@10_avg": float("-inf")}

    names = list(grid.keys())
    for values in product(*[grid[name] for name in names]):
        candidate = dict(base_weights)
        candidate.update(dict(zip(names, values, strict=True)))
        metrics = _evaluate_weights(precomputed, candidate, top_n=top_n)
        rows.append(
            {
                "stage": stage,
                "param_name": ",".join(names),
                "param_value": json.dumps(
                    {name: value for name, value in zip(names, values, strict=True)}, ensure_ascii=False
                ),
                **metrics,
            }
        )
        if pd.notna(metrics["lift@10_avg"]) and metrics["lift@10_avg"] > best_metrics["lift@10_avg"]:
            best_metrics = metrics
            best_weights = candidate

    return pd.DataFrame(rows), best_weights, best_metrics


def _fine_tune_candidates(best_weights: dict[str, float]) -> dict[str, list[float]]:
    return {
        "h_jug_corner1": sorted(
            {
                max(0.0, best_weights["h_jug_corner1"] - 50),
                best_weights["h_jug_corner1"],
                best_weights["h_jug_corner1"] + 50,
            }
        ),
        "h_jug_corner24": sorted(
            {
                max(0.0, best_weights["h_jug_corner24"] - 25),
                best_weights["h_jug_corner24"],
                best_weights["h_jug_corner24"] + 25,
            }
        ),
        "h_jug_corner59": sorted(
            {
                max(0.0, best_weights["h_jug_corner59"] - 15),
                best_weights["h_jug_corner59"],
                best_weights["h_jug_corner59"] + 15,
            }
        ),
        "h_nonjug_xdds": sorted(
            {
                max(0.0, best_weights["h_nonjug_xdds"] - 50),
                best_weights["h_nonjug_xdds"],
                best_weights["h_nonjug_xdds"] + 50,
            }
        ),
        "h_nonjug_corner1_xdds": sorted(
            {
                max(0.0, best_weights["h_nonjug_corner1_xdds"] - 50),
                best_weights["h_nonjug_corner1_xdds"],
                best_weights["h_nonjug_corner1_xdds"] + 50,
            }
        ),
        "h_nonjug_corner1_nonevent_penalty": sorted(
            {
                best_weights["h_nonjug_corner1_nonevent_penalty"] - 50,
                best_weights["h_nonjug_corner1_nonevent_penalty"],
                best_weights["h_nonjug_corner1_nonevent_penalty"] + 50,
            }
        ),
        "dd24_boost": sorted(
            {max(0.0, best_weights["dd24_boost"] - 50), best_weights["dd24_boost"], best_weights["dd24_boost"] + 50}
        ),
        "section_baseline_scale": sorted(
            {
                max(0.0, best_weights["section_baseline_scale"] - 0.05),
                best_weights["section_baseline_scale"],
                best_weights["section_baseline_scale"] + 0.05,
            }
        ),
    }


def _format_best_json(
    weights: dict[str, float], metrics: dict[str, float], stage_results: dict[str, dict[str, float]]
) -> str:
    payload = {
        "best_weights": weights,
        "best_metrics": metrics,
        "stage_results": stage_results,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def build_optimization_outputs(
    frame: pd.DataFrame | None = None,
    *,
    top_n: int = DEFAULT_TOP_N,
    random_samples: int = DEFAULT_RANDOM_SAMPLES,
    min_games: int = 1000,
    split_date: str = DEFAULT_SPLIT_DATE,
) -> dict[str, object]:
    prepared = prepare_optimization_frame(frame, min_games=min_games)
    cases = _build_cases(prepared, split_date=split_date)
    base_weights = current_weight_vector()

    precomputed = _precompute_cases(cases, top_n=top_n, random_samples=random_samples)
    print(f"Precomputed {len(precomputed)} cases (random baseline cached)")

    grid_frames: list[pd.DataFrame] = []
    stage_results: dict[str, dict[str, float]] = {}

    stage1_grid, stage1_weights, stage1_metrics = _grid_rows(
        precomputed,
        base_weights=base_weights,
        grid=STAGE1_GRID,
        stage="stage1",
        top_n=top_n,
    )
    grid_frames.append(stage1_grid)
    stage_results["stage1"] = stage1_metrics
    print(f"Stage1 done: lift@10_avg={stage1_metrics['lift@10_avg']:.1f}")

    stage2_base = dict(stage1_weights)
    stage2_grid, stage2_weights, stage2_metrics = _grid_rows(
        precomputed,
        base_weights=stage2_base,
        grid=STAGE2_GRID,
        stage="stage2",
        top_n=top_n,
    )
    grid_frames.append(stage2_grid)
    stage_results["stage2"] = stage2_metrics
    print(f"Stage2 done: lift@10_avg={stage2_metrics['lift@10_avg']:.1f}")

    stage3_base = dict(stage2_weights)
    stage3_grid, stage3_weights, stage3_metrics = _grid_rows(
        precomputed,
        base_weights=stage3_base,
        grid=STAGE3_GRID,
        stage="stage3",
        top_n=top_n,
    )
    grid_frames.append(stage3_grid)
    stage_results["stage3"] = stage3_metrics
    print(f"Stage3 done: lift@10_avg={stage3_metrics['lift@10_avg']:.1f}")

    fine_rows: list[dict[str, object]] = []
    fine_tune_weights = dict(stage3_weights)
    fine_tune_metrics = _evaluate_weights(precomputed, fine_tune_weights, top_n=top_n)
    for name, candidates in _fine_tune_candidates(stage3_weights).items():
        local_best = dict(fine_tune_weights)
        local_metrics = dict(fine_tune_metrics)
        for value in candidates:
            candidate = dict(fine_tune_weights)
            candidate[name] = value
            metrics = _evaluate_weights(precomputed, candidate, top_n=top_n)
            fine_rows.append(
                {
                    "stage": "fine_tune",
                    "param_name": name,
                    "param_value": json.dumps({name: value}, ensure_ascii=False),
                    **metrics,
                }
            )
            if pd.notna(metrics["lift@10_avg"]) and metrics["lift@10_avg"] > local_metrics["lift@10_avg"]:
                local_best = candidate
                local_metrics = metrics
        fine_tune_weights = local_best
        fine_tune_metrics = local_metrics
    grid_frames.append(pd.DataFrame(fine_rows))
    stage_results["fine_tune"] = fine_tune_metrics
    print(f"Fine-tune done: lift@10_avg={fine_tune_metrics['lift@10_avg']:.1f}")

    all_grid = pd.concat(grid_frames, ignore_index=True)
    best_weights = fine_tune_weights
    best_metrics = fine_tune_metrics
    report = build_optimization_report(all_grid, base_weights, best_weights, stage_results)

    return {
        "grid": all_grid,
        "best": {
            "best_weights": best_weights,
            "best_metrics": best_metrics,
            "stage_results": stage_results,
            "stage1": stage_results.get("stage1", {}),
            "stage2": stage_results.get("stage2", {}),
            "stage3": stage_results.get("stage3", {}),
            "fine_tune": stage_results.get("fine_tune", {}),
        },
        "report": report,
    }


def build_optimization_report(
    grid: pd.DataFrame,
    base_weights: dict[str, float],
    best_weights: dict[str, float],
    stage_results: dict[str, dict[str, float]],
) -> str:
    comparison = pd.DataFrame(
        [
            {"label": "current", **base_weights},
            {"label": "optimized", **best_weights},
        ]
    )
    lines = [
        "# みとや大森町 推薦重み最適化",
        "",
        "## Stage Results",
        "",
        render_markdown_table(pd.DataFrame([{"stage": stage, **metrics} for stage, metrics in stage_results.items()])),
        "",
        "## Current vs Optimized",
        "",
        render_markdown_table(comparison),
        "",
        "## Grid Preview",
        "",
        render_markdown_table(grid.head(30)),
    ]
    return "\n".join(lines).strip() + "\n"


def run_optimization(
    frame: pd.DataFrame | None = None,
    *,
    output_dir: Path | None = None,
    top_n: int = DEFAULT_TOP_N,
    random_samples: int = DEFAULT_RANDOM_SAMPLES,
    min_games: int = 1000,
    split_date: str = DEFAULT_SPLIT_DATE,
) -> dict[str, object]:
    outputs = build_optimization_outputs(
        frame,
        top_n=top_n,
        random_samples=random_samples,
        min_games=min_games,
        split_date=split_date,
    )
    outdir = output_dir or ensure_results_dir()
    outdir.mkdir(parents=True, exist_ok=True)
    outputs["grid"].to_csv(outdir / "mitoya_optimize_grid.csv", index=False, encoding="utf-8-sig")
    (outdir / "mitoya_optimize_best.json").write_text(
        json.dumps(outputs["best"], ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (outdir / "mitoya_optimize_report.md").write_text(outputs["report"], encoding="utf-8")
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="みとや大森町 推薦重み最適化")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    parser.add_argument("--random-samples", type=int, default=DEFAULT_RANDOM_SAMPLES)
    parser.add_argument("--min-games", type=int, default=1000)
    parser.add_argument("--split-date", type=str, default=DEFAULT_SPLIT_DATE)
    args = parser.parse_args()

    run_optimization(
        frame=None,
        output_dir=args.output_dir,
        top_n=args.top_n,
        random_samples=args.random_samples,
        min_games=args.min_games,
        split_date=args.split_date,
    )


if __name__ == "__main__":
    main()
