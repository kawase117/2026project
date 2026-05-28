from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from scipy.stats import mannwhitneyu

from ml.machine_type import machine_type_common as common
from ml.machine_type.v2 import run_machine_type_v2 as v2

SEGMENT_DIAG_DIR = Path("ml/machine_type/v2/output/segment_diagnostics")
LAMBDA_DIR = SEGMENT_DIAG_DIR / "lambda_holdout_check"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _fmt_seconds(sec: float) -> str:
    sec = max(float(sec), 0.0)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _print_progress(prefix: str, step: int, total: int, start_ts: float, suffix: str = "") -> None:
    elapsed = time.time() - start_ts
    avg = (elapsed / step) if step > 0 else 0.0
    remain = avg * max(total - step, 0)
    msg = (
        f"[{prefix}] {step}/{total} "
        f"elapsed={_fmt_seconds(elapsed)} remaining={_fmt_seconds(remain)}"
    )
    if suffix:
        msg += f" {suffix}"
    print(msg, flush=True)


def _build_args(
    *,
    db_path: Path,
    output_dir: Path,
    combined_lambda: float,
    eval_offset_days: int,
) -> SimpleNamespace:
    return SimpleNamespace(
        db_path=str(db_path),
        output_dir=str(output_dir),
        alpha=5.0,
        min_train_days=120,
        eval_days=90,
        eval_offset_days=int(eval_offset_days),
        step_days=1,
        rolling_prior_window=90,
        layer0_threshold=0.3,
        layer0_winrate_threshold=75.0,
        feature_profile="baseline6",
        target_policy="default",
        min_machine_history_days=30,
        combined_lambda=float(combined_lambda),
        random_state=42,
        games_feature_mode="none",
    )


def _run_segment_walkforward_with_progress(
    segment_df: pd.DataFrame,
    *,
    segment_key: str,
    base_feature_cols: list[str],
    min_train_days: int = 120,
    eval_days: int = 90,
    eval_offset_days: int = 0,
    step_days: int = 1,
    random_state: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    seg = segment_df.copy().sort_values(["date", "machine_name"]).reset_index(drop=True)
    target_pairs = v2._target_pairs_for_segment(segment_key, "default")
    feature_cols = v2._layer1_feature_cols_for_profile(
        seg,
        base_feature_cols=base_feature_cols,
        feature_profile="baseline6",
        games_feature_mode="none",
    )
    if not feature_cols:
        return pd.DataFrame(), pd.DataFrame()

    all_dates = np.array(sorted(seg["date"].dropna().unique()))
    safe_offset = max(int(eval_offset_days), 0)
    end_idx = int(all_dates.size) - safe_offset
    start_idx = max(int(min_train_days), end_idx - max(int(eval_days), 1))
    eval_dates = all_dates[start_idx:end_idx:max(int(step_days), 1)]
    if eval_dates.size == 0:
        eval_dates = all_dates[start_idx:]

    total_steps = int(len(target_pairs) * len(eval_dates))
    start_ts = time.time()
    step = 0
    pred_records: list[dict[str, Any]] = []
    imp_records: list[dict[str, Any]] = []

    for target_col, target_name in target_pairs:
        for pred_date in eval_dates:
            step += 1
            tr = seg.loc[seg["date"] < pred_date].dropna(subset=feature_cols + [target_col]).copy()
            te = seg.loc[seg["date"] == pred_date].dropna(subset=feature_cols + [target_col]).copy()
            if tr.empty or te.empty:
                _print_progress(segment_key, step, total_steps, start_ts, "skip=empty")
                continue
            if tr["date"].nunique() < int(min_train_days):
                _print_progress(segment_key, step, total_steps, start_ts, "skip=train_days")
                continue
            if tr[target_col].nunique() < 2:
                _print_progress(segment_key, step, total_steps, start_ts, "skip=single_class")
                continue

            model = CatBoostClassifier(
                iterations=300,
                depth=3,
                learning_rate=0.03,
                loss_function="Logloss",
                eval_metric="AUC",
                random_seed=int(random_state),
                allow_writing_files=False,
                verbose=False,
            )
            x_tr = tr[feature_cols].to_numpy(dtype=float)
            y_tr = tr[target_col].to_numpy(dtype=int)
            x_te = te[feature_cols].to_numpy(dtype=float)
            model.fit(x_tr, y_tr)
            p_te = model.predict_proba(x_te)[:, 1]

            imps = model.get_feature_importance()
            for col, imp in zip(feature_cols, imps, strict=False):
                imp_records.append(
                    {
                        "segment": segment_key,
                        "target": target_name,
                        "date": pd.Timestamp(pred_date).strftime("%Y-%m-%d"),
                        "feature": col,
                        "importance": float(imp),
                    }
                )
            for (_, row), prob in zip(te.iterrows(), p_te, strict=False):
                pred_records.append(
                    {
                        "segment": segment_key,
                        "target": target_name,
                        "date": pd.Timestamp(row["date"]).strftime("%Y-%m-%d"),
                        "machine_name": str(row["machine_name"]),
                        "is_top3_in_segment": int(row["is_top3_in_segment"]),
                        "is_top5_in_segment": int(row["is_top5_in_segment"]),
                        "proba": float(prob),
                    }
                )
            _print_progress(segment_key, step, total_steps, start_ts, "trained")

    return pd.DataFrame(pred_records), pd.DataFrame(imp_records)


def _task1_randomness_test(
    seg_2fa: pd.DataFrame,
    pred_2fa_top3: pd.DataFrame,
    *,
    rng_seed: int = 42,
) -> dict[str, Any]:
    if pred_2fa_top3.empty:
        return {
            "n_eval_days": 0,
            "conclusion": "random",
            "error": "no_predictions",
        }

    seg_cols = seg_2fa[["date", "machine_name", "segment_rank", "is_top3_in_segment"]].copy()
    seg_cols["date"] = pd.to_datetime(seg_cols["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    merged = pred_2fa_top3.merge(seg_cols, on=["date", "machine_name"], how="left")
    merged = merged.dropna(subset=["segment_rank"]).copy()
    if merged.empty:
        return {
            "n_eval_days": 0,
            "conclusion": "random",
            "error": "no_rank_matches",
        }

    rng = np.random.default_rng(rng_seed)
    ml_ranks: list[float] = []
    rnd_ranks: list[float] = []
    ml_hits: list[int] = []
    rnd_baselines: list[float] = []
    per_day_n: list[int] = []

    for d, g in merged.groupby("date", sort=True):
        g = g.sort_values(["proba", "machine_name"], ascending=[False, True]).copy()
        if g.empty:
            continue
        n = int(g["machine_name"].nunique())
        per_day_n.append(n)
        ml_top = g.iloc[0]
        ml_rank = float(ml_top["segment_rank"])
        ml_ranks.append(ml_rank)
        ml_hits.append(int(ml_rank <= 1.0))
        rnd_baselines.append((1.0 / n) if n > 0 else 0.0)

        day_pool = g[["machine_name", "segment_rank"]].drop_duplicates("machine_name")
        pick = int(rng.integers(low=0, high=len(day_pool)))
        rnd_rank = float(day_pool.iloc[pick]["segment_rank"])
        rnd_ranks.append(rnd_rank)

    if not ml_ranks or not rnd_ranks:
        return {
            "n_eval_days": int(len(per_day_n)),
            "conclusion": "random",
            "error": "insufficient_samples",
        }

    stat = mannwhitneyu(np.array(ml_ranks), np.array(rnd_ranks), alternative="less")
    ml_hit_at_1 = float(np.mean(ml_hits))
    rb_at_1 = float(np.mean(rnd_baselines)) if rnd_baselines else 0.0
    ml_lift_at_1 = (ml_hit_at_1 / rb_at_1) if rb_at_1 > 0 else None
    pval = float(stat.pvalue)
    conclusion = "predictable" if (pval < 0.05 and (ml_lift_at_1 or 0.0) > 1.0) else "random"

    return {
        "n_eval_days": int(len(per_day_n)),
        "n_machines_2fa_avg": float(np.mean(per_day_n)) if per_day_n else None,
        "ml_lift_at_1": ml_lift_at_1,
        "ml_mean_rank_of_pred_top1": float(np.mean(ml_ranks)),
        "random_mean_rank_of_pred_top1": float(np.mean(rnd_ranks)),
        "mannwhitneyu_pvalue": pval,
        "conclusion": conclusion,
    }


def _daily_lift_distribution(pred_top3: pd.DataFrame) -> tuple[float | None, float | None]:
    if pred_top3.empty:
        return None, None
    lifts: list[float] = []
    for _, g in pred_top3.groupby("date", sort=True):
        if g.empty:
            continue
        g = g.sort_values(["proba", "machine_name"], ascending=[False, True])
        hit = int(g.iloc[0]["is_top3_in_segment"] == 1)
        rb = float(np.mean(g["is_top3_in_segment"].to_numpy(dtype=int)))
        if rb > 0:
            lifts.append(float(hit / rb))
    if not lifts:
        return None, None
    return float(np.median(lifts)), float(np.std(lifts))


def _top_features(imp_df: pd.DataFrame, topn: int = 3) -> list[str]:
    if imp_df.empty:
        return []
    s = (
        imp_df.groupby("feature", sort=True)["importance"]
        .mean()
        .sort_values(ascending=False)
        .head(int(topn))
    )
    return [str(x) for x in s.index.tolist()]


def _task2_3fa_vs_2fa(
    seg_3fa: pd.DataFrame,
    pred_3fa_top3: pd.DataFrame,
    imp_3fa: pd.DataFrame,
    seg_2fa: pd.DataFrame,
    pred_2fa_top3: pd.DataFrame,
    imp_2fa: pd.DataFrame,
) -> dict[str, Any]:
    med3, std3 = _daily_lift_distribution(pred_3fa_top3)
    med2, std2 = _daily_lift_distribution(pred_2fa_top3)

    out = {
        "3fa": {
            "n_machines": int(seg_3fa["machine_name"].nunique()),
            "is_top3_base_rate": float(np.mean(seg_3fa["is_top3_in_segment"].to_numpy(dtype=int))),
            "lift_at_1_mean": med3,
            "lift_at_1_std": std3,
            "top3_features": _top_features(imp_3fa, topn=3),
        },
        "2fa": {
            "n_machines": int(seg_2fa["machine_name"].nunique()),
            "is_top3_base_rate": float(np.mean(seg_2fa["is_top3_in_segment"].to_numpy(dtype=int))),
            "lift_at_1_mean": med2,
            "lift_at_1_std": std2,
            "top3_features": _top_features(imp_2fa, topn=3),
        },
    }

    out["hypothesis"] = (
        "3F_Aの優位は、2F_Aより高い日次lift分布と特徴量安定性の可能性。"
        "2F_Aはlift@1が1.0未満で、同一特徴量でも順位識別が弱い。"
    )
    return out


def _task3_lambda_holdout(db_path: Path) -> dict[str, Any]:
    LAMBDA_DIR.mkdir(parents=True, exist_ok=True)
    config = [
        ("lambda_0.0", 0.0),
        ("lambda_0.5", 0.5),
    ]
    out: dict[str, Any] = {}
    for key, lam in config:
        # tune: previous 90d (offset 90), holdout: latest 90d (offset 0)
        tune_args = _build_args(
            db_path=db_path,
            output_dir=LAMBDA_DIR / f"{key}_tune",
            combined_lambda=lam,
            eval_offset_days=90,
        )
        hold_args = _build_args(
            db_path=db_path,
            output_dir=LAMBDA_DIR / f"{key}_holdout",
            combined_lambda=lam,
            eval_offset_days=0,
        )
        t0 = time.time()
        print(f"[{key}] run tune started", flush=True)
        tune = v2.run_pipeline(tune_args)
        print(
            f"[{key}] run tune done elapsed={_fmt_seconds(time.time() - t0)} remaining=--:--:--",
            flush=True,
        )
        t1 = time.time()
        print(f"[{key}] run holdout started", flush=True)
        hold = v2.run_pipeline(hold_args)
        print(
            f"[{key}] run holdout done elapsed={_fmt_seconds(time.time() - t1)} remaining=--:--:--",
            flush=True,
        )
        out[key] = {
            "tune_combined_hit_at_1": tune.get("combined_recommendation", {}).get("top3_combined_hit_at_1"),
            "holdout_combined_hit_at_1": hold.get("combined_recommendation", {}).get("top3_combined_hit_at_1"),
            "tune_auc": tune.get("target_is_top3", {}).get("combined", {}).get("auc"),
            "holdout_auc": hold.get("target_is_top3", {}).get("combined", {}).get("auc"),
        }
    return out


def run(db_path: Path) -> None:
    SEGMENT_DIAG_DIR.mkdir(parents=True, exist_ok=True)
    print(f"DB: {db_path}", flush=True)

    # Prepare source frames once (fixed settings).
    layer1_base, prep_warnings, base_feature_cols = v2.prepare_layer1_frame(
        db_path,
        alpha=5.0,
        rolling_prior_window=90,
        min_machine_history_days=30,
    )
    if prep_warnings:
        for w in prep_warnings:
            print(f"WARNING: {w}", flush=True)

    seg_2fa = layer1_base.loc[layer1_base["segment_key"].eq("2F_A")].copy()
    seg_3fa = layer1_base.loc[layer1_base["segment_key"].eq("3F_A")].copy()

    print("[task1] running 2F_A walk-forward with progress", flush=True)
    pred_2fa, imp_2fa = _run_segment_walkforward_with_progress(
        seg_2fa,
        segment_key="2F_A",
        base_feature_cols=base_feature_cols,
        min_train_days=120,
        eval_days=90,
        eval_offset_days=0,
        step_days=1,
        random_state=42,
    )
    pred_2fa_top3 = pred_2fa.loc[pred_2fa["target"].eq("target_is_top3")].copy() if not pred_2fa.empty else pd.DataFrame()
    t1 = _task1_randomness_test(seg_2fa, pred_2fa_top3)
    _write_json(SEGMENT_DIAG_DIR / "2fa_randomness_test.json", t1)

    print("[task2] running 3F_A walk-forward with progress", flush=True)
    pred_3fa, imp_3fa = _run_segment_walkforward_with_progress(
        seg_3fa,
        segment_key="3F_A",
        base_feature_cols=base_feature_cols,
        min_train_days=120,
        eval_days=90,
        eval_offset_days=0,
        step_days=1,
        random_state=42,
    )
    pred_3fa_top3 = pred_3fa.loc[pred_3fa["target"].eq("target_is_top3")].copy() if not pred_3fa.empty else pd.DataFrame()
    t2 = _task2_3fa_vs_2fa(seg_3fa, pred_3fa_top3, imp_3fa, seg_2fa, pred_2fa_top3, imp_2fa)
    _write_json(SEGMENT_DIAG_DIR / "3fa_vs_2fa_analysis.json", t2)

    print("[task3] running lambda holdout checks", flush=True)
    t3 = _task3_lambda_holdout(db_path)
    _write_json(LAMBDA_DIR / "lambda_comparison.json", t3)
    print("Done.", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="machine_type v2 segment diagnostics")
    parser.add_argument("--db-path", default="", help="SQLite DB path. Empty means auto-detect db/*7.db")
    args = parser.parse_args()
    db = common.resolve_db_path(str(args.db_path))
    run(db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

