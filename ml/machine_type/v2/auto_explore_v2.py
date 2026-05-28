from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from . import run_machine_type_v2 as v2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Autonomous exploration runner for machine_type v2")
    p.add_argument("--db-path", default="db/マルハンメガシティ2000-蒲田7.db")
    p.add_argument("--output-root", default="ml/machine_type/v2/output")
    p.add_argument("--python-exe", default="venv\\Scripts\\python.exe")
    p.add_argument("--min-train-days", type=int, default=120)
    p.add_argument("--rolling-prior-window", type=int, default=90)
    p.add_argument("--step-days", type=int, default=1)
    p.add_argument("--tune-days", type=int, default=60)
    p.add_argument("--holdout-days", type=int, default=30)
    p.add_argument("--random-state", type=int, default=42)
    return p


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _extract_metrics(result: dict[str, Any]) -> dict[str, Any]:
    top3_combined = result.get("target_is_top3", {}).get("combined", {}) or {}
    layer0 = result.get("layer0", {}) or {}
    seg_2fn_top3 = result.get("target_is_top3", {}).get("2F_N", {}) or {}
    seg_2fn_top5 = result.get("target_is_top5", {}).get("2F_N", {}) or {}
    return {
        "combined_hit_at_1": top3_combined.get("hit_at_1"),
        "combined_hit_at_3": top3_combined.get("hit_at_3"),
        "combined_auc": top3_combined.get("auc"),
        "layer0_hit_at_1": layer0.get("hit_at_1"),
        "layer0_lift_at_1": layer0.get("lift_at_1"),
        "layer0_base_rate": layer0.get("kisyuzen_base_rate"),
        "2F_N_lift_at_3": seg_2fn_top3.get("lift"),
        "2F_N_lift_at_5": seg_2fn_top5.get("lift"),
    }


def _score_result(result: dict[str, Any]) -> float:
    m = _extract_metrics(result)
    hit1 = float(m["combined_hit_at_1"] or 0.0)
    auc = float(m["combined_auc"] or 0.0)
    lift_2fn = float(m["2F_N_lift_at_3"] or 0.0)
    return hit1 + (0.05 * auc) + (0.10 * max(0.0, lift_2fn - 1.0))


def _run_config(
    *,
    python_exe: str,
    workdir: Path,
    db_path: str,
    output_dir: Path,
    min_train_days: int,
    eval_days: int,
    eval_offset_days: int,
    step_days: int,
    rolling_prior_window: int,
    layer0_threshold: float,
    layer0_winrate_threshold: float,
    feature_profile: str,
    target_policy: str,
    combined_lambda: float,
    random_state: int,
) -> dict[str, Any]:
    cmd = [
        python_exe,
        "-m",
        "ml.machine_type.v2.run_machine_type_v2",
        "--db-path",
        db_path,
        "--output-dir",
        str(output_dir),
        "--min-train-days",
        str(min_train_days),
        "--eval-days",
        str(eval_days),
        "--eval-offset-days",
        str(eval_offset_days),
        "--step-days",
        str(step_days),
        "--rolling-prior-window",
        str(rolling_prior_window),
        "--layer0-threshold",
        str(layer0_threshold),
        "--layer0-winrate-threshold",
        str(layer0_winrate_threshold),
        "--feature-profile",
        feature_profile,
        "--target-policy",
        target_policy,
        "--combined-lambda",
        str(combined_lambda),
        "--random-state",
        str(random_state),
    ]
    print("[RUN]", " ".join(cmd))
    subprocess.run(cmd, cwd=str(workdir), check=True)
    return json.loads((output_dir / "layer1_combined_result.json").read_text(encoding="utf-8"))


def _layer0_threshold_sweep(
    *,
    db_path: Path,
    eval_days: int,
    eval_offset_days: int,
    rolling_prior_window: int,
    random_state: int,
    layer0_threshold: float,
    thresholds: list[float],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    best_key = ""
    best_score = -1.0
    for th in thresholds:
        frame = v2.load_layer0_kisyuzen_frame(
            db_path,
            rolling_prior_window=rolling_prior_window,
            winrate_threshold=float(th),
        )
        result, _ = v2.run_layer0_walkforward(
            frame,
            eval_days=eval_days,
            eval_offset_days=eval_offset_days,
            random_state=random_state,
            layer0_threshold=layer0_threshold,
        )
        s = result.get("layer0", {})
        base_rate = float(s.get("kisyuzen_base_rate") or 0.0)
        lift1 = float(s.get("lift_at_1") or 0.0)
        coverage = float(lift1 * np.sqrt(base_rate)) if base_rate > 0 else 0.0
        key = f"threshold_{int(th)}"
        out[key] = {
            "base_rate": base_rate,
            "auc": s.get("auc"),
            "hit_at_1": s.get("hit_at_1"),
            "lift_at_1": s.get("lift_at_1"),
            "coverage_score": coverage,
        }
        if coverage > best_score:
            best_score = coverage
            best_key = key
    out["recommended_threshold"] = int(best_key.split("_")[-1]) if best_key else None
    return out


def _md_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    hdr = "| config | split | hit@1 | hit@3 | auc | 2F_N lift@3 | 2F_N lift@5 |"
    sep = "|---|---:|---:|---:|---:|---:|---:|"
    body = []
    for r in rows:
        body.append(
            "| {config} | {split} | {h1:.4f} | {h3:.4f} | {auc:.4f} | {l3:.4f} | {l5:.4f} |".format(
                config=r["config"],
                split=r["split"],
                h1=float(r.get("combined_hit_at_1") or 0.0),
                h3=float(r.get("combined_hit_at_3") or 0.0),
                auc=float(r.get("combined_auc") or 0.0),
                l3=float(r.get("2F_N_lift_at_3") or 0.0),
                l5=float(r.get("2F_N_lift_at_5") or 0.0),
            )
        )
    return "\n".join([hdr, sep, *body])


def main() -> int:
    args = build_parser().parse_args()
    workdir = Path(__file__).resolve().parents[3]
    now = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    root = Path(args.output_root) / f"auto_explore_{now}"
    root.mkdir(parents=True, exist_ok=True)
    db_path = Path(args.db_path)
    tune_offset = int(args.holdout_days)

    # Baseline on tune/holdout
    baseline_tune = _run_config(
        python_exe=args.python_exe,
        workdir=workdir,
        db_path=str(db_path),
        output_dir=root / "baseline_tune",
        min_train_days=args.min_train_days,
        eval_days=args.tune_days,
        eval_offset_days=tune_offset,
        step_days=args.step_days,
        rolling_prior_window=args.rolling_prior_window,
        layer0_threshold=0.3,
        layer0_winrate_threshold=80.0,
        feature_profile="baseline6",
        target_policy="default",
        combined_lambda=0.5,
        random_state=args.random_state,
    )
    baseline_holdout = _run_config(
        python_exe=args.python_exe,
        workdir=workdir,
        db_path=str(db_path),
        output_dir=root / "baseline_holdout",
        min_train_days=args.min_train_days,
        eval_days=args.holdout_days,
        eval_offset_days=0,
        step_days=args.step_days,
        rolling_prior_window=args.rolling_prior_window,
        layer0_threshold=0.3,
        layer0_winrate_threshold=80.0,
        feature_profile="baseline6",
        target_policy="default",
        combined_lambda=0.5,
        random_state=args.random_state,
    )

    # Task 1: feature profiles (tune), then holdout for best
    profile_results: dict[str, dict[str, Any]] = {}
    for profile in ("baseline6", "rich_no_ranktrend", "rich_all"):
        res = _run_config(
            python_exe=args.python_exe,
            workdir=workdir,
            db_path=str(db_path),
            output_dir=root / f"task1_tune_{profile}",
            min_train_days=args.min_train_days,
            eval_days=args.tune_days,
            eval_offset_days=tune_offset,
            step_days=args.step_days,
            rolling_prior_window=args.rolling_prior_window,
            layer0_threshold=0.3,
            layer0_winrate_threshold=80.0,
            feature_profile=profile,
            target_policy="default",
            combined_lambda=0.5,
            random_state=args.random_state,
        )
        profile_results[profile] = {
            "score": _score_result(res),
            "metrics": _extract_metrics(res),
        }
    best_profile = max(profile_results.items(), key=lambda x: x[1]["score"])[0]
    best_profile_holdout = _run_config(
        python_exe=args.python_exe,
        workdir=workdir,
        db_path=str(db_path),
        output_dir=root / f"task1_holdout_{best_profile}",
        min_train_days=args.min_train_days,
        eval_days=args.holdout_days,
        eval_offset_days=0,
        step_days=args.step_days,
        rolling_prior_window=args.rolling_prior_window,
        layer0_threshold=0.3,
        layer0_winrate_threshold=80.0,
        feature_profile=best_profile,
        target_policy="default",
        combined_lambda=0.5,
        random_state=args.random_state,
    )
    task1_summary = {
        "tune_results": profile_results,
        "best_profile": best_profile,
        "best_holdout_metrics": _extract_metrics(best_profile_holdout),
    }
    _write_json(root / "task1_rich_features_result.json", task1_summary)

    # Task 2: layer0 win-rate threshold sweep (tune split)
    task2 = _layer0_threshold_sweep(
        db_path=db_path,
        eval_days=args.tune_days,
        eval_offset_days=tune_offset,
        rolling_prior_window=args.rolling_prior_window,
        random_state=args.random_state,
        layer0_threshold=0.3,
        thresholds=[50, 55, 60, 65, 70, 75, 80],
    )
    _write_json(root / "task2_layer0_threshold_sweep.json", task2)
    best_layer0_threshold = float(task2.get("recommended_threshold") or 80)

    # Task 3: 2F_N target policy test
    task3_res: dict[str, Any] = {}
    for policy in ("default", "2fn_top5"):
        res = _run_config(
            python_exe=args.python_exe,
            workdir=workdir,
            db_path=str(db_path),
            output_dir=root / f"task3_tune_{policy}",
            min_train_days=args.min_train_days,
            eval_days=args.tune_days,
            eval_offset_days=tune_offset,
            step_days=args.step_days,
            rolling_prior_window=args.rolling_prior_window,
            layer0_threshold=0.3,
            layer0_winrate_threshold=best_layer0_threshold,
            feature_profile=best_profile,
            target_policy=policy,
            combined_lambda=0.5,
            random_state=args.random_state,
        )
        task3_res[policy] = _extract_metrics(res)
    best_policy = max(task3_res.items(), key=lambda x: float(x[1].get("combined_hit_at_1") or 0.0))[0]
    task3_holdout = _run_config(
        python_exe=args.python_exe,
        workdir=workdir,
        db_path=str(db_path),
        output_dir=root / f"task3_holdout_{best_policy}",
        min_train_days=args.min_train_days,
        eval_days=args.holdout_days,
        eval_offset_days=0,
        step_days=args.step_days,
        rolling_prior_window=args.rolling_prior_window,
        layer0_threshold=0.3,
        layer0_winrate_threshold=best_layer0_threshold,
        feature_profile=best_profile,
        target_policy=best_policy,
        combined_lambda=0.5,
        random_state=args.random_state,
    )
    task3_summary = {
        "tune_results": task3_res,
        "recommended_policy": best_policy,
        "holdout_metrics": _extract_metrics(task3_holdout),
    }
    _write_json(root / "task3_2fn_top5_result.json", task3_summary)

    # Task 4: lambda sweep on tune split
    lambda_results: dict[str, Any] = {}
    for lam in (0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0):
        res = _run_config(
            python_exe=args.python_exe,
            workdir=workdir,
            db_path=str(db_path),
            output_dir=root / f"task4_tune_lambda_{str(lam).replace('.', '_')}",
            min_train_days=args.min_train_days,
            eval_days=args.tune_days,
            eval_offset_days=tune_offset,
            step_days=args.step_days,
            rolling_prior_window=args.rolling_prior_window,
            layer0_threshold=0.3,
            layer0_winrate_threshold=best_layer0_threshold,
            feature_profile=best_profile,
            target_policy=best_policy,
            combined_lambda=float(lam),
            random_state=args.random_state,
        )
        reco = res.get("combined_recommendation", {})
        h1 = float(reco.get("top3_combined_hit_at_1") or 0.0)
        h3 = float(reco.get("top3_combined_hit_at_3") or 0.0)
        score = h1 * h3
        lambda_results[str(lam)] = {"score": score, "combined_recommendation": reco}
    best_lambda = float(max(lambda_results.items(), key=lambda x: float(x[1]["score"]))[0])
    task4_holdout = _run_config(
        python_exe=args.python_exe,
        workdir=workdir,
        db_path=str(db_path),
        output_dir=root / f"task4_holdout_lambda_{str(best_lambda).replace('.', '_')}",
        min_train_days=args.min_train_days,
        eval_days=args.holdout_days,
        eval_offset_days=0,
        step_days=args.step_days,
        rolling_prior_window=args.rolling_prior_window,
        layer0_threshold=0.3,
        layer0_winrate_threshold=best_layer0_threshold,
        feature_profile=best_profile,
        target_policy=best_policy,
        combined_lambda=best_lambda,
        random_state=args.random_state,
    )
    task4_summary = {
        "tune_results": lambda_results,
        "recommended_lambda": best_lambda,
        "holdout_combined_recommendation": task4_holdout.get("combined_recommendation", {}),
        "holdout_metrics": _extract_metrics(task4_holdout),
    }
    _write_json(root / "task4_lambda_sweep.json", task4_summary)

    # Final summary
    rows = [
        {"config": "baseline6/default/l0=80/lambda=0.5", "split": "tune", **_extract_metrics(baseline_tune)},
        {"config": "baseline6/default/l0=80/lambda=0.5", "split": "holdout", **_extract_metrics(baseline_holdout)},
        {"config": f"{best_profile}/{best_policy}/l0={int(best_layer0_threshold)}/lambda={best_lambda}", "split": "holdout", **task4_summary["holdout_metrics"]},
    ]
    md = [
        "# 10時間探索サマリー（自動実行）",
        "",
        "## ベースライン vs 推奨設定",
        "",
        _md_table(rows),
        "",
        "## 推奨設定",
        f"- feature_profile: `{best_profile}`",
        f"- target_policy: `{best_policy}`",
        f"- layer0 win_rate threshold: `{int(best_layer0_threshold)}`",
        f"- combined_lambda: `{best_lambda}`",
        "",
        "## タスク別成果物",
        "- task1_rich_features_result.json",
        "- task2_layer0_threshold_sweep.json",
        "- task3_2fn_top5_result.json",
        "- task4_lambda_sweep.json",
    ]
    (root / "EXPLORATION_SUMMARY.md").write_text("\n".join(md), encoding="utf-8")

    master = {
        "output_root": str(root),
        "baseline_tune": _extract_metrics(baseline_tune),
        "baseline_holdout": _extract_metrics(baseline_holdout),
        "task1": task1_summary,
        "task2": task2,
        "task3": task3_summary,
        "task4": task4_summary,
        "recommended": {
            "feature_profile": best_profile,
            "target_policy": best_policy,
            "layer0_winrate_threshold": best_layer0_threshold,
            "combined_lambda": best_lambda,
        },
    }
    _write_json(root / "EXPLORATION_SUMMARY.json", master)
    print(f"Exploration finished: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

