from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.experiments import tail_ltr_profit_ops as ops
from ml.experiments import tail_time_adaptive_ltr_poc_improved as improved
from ml.experiments.tail_ltr_full_walkforward_ops import topk_day_table, train_and_predict_fold
from ml.experiments.tail_ltr_split_rule_wf import (
    Candidate,
    add_simple_features,
    aggregate_mode,
    build_base_rows,
    parse_csv_floats,
    parse_csv_strs,
    resolve_db_path,
)


EXPERT_ORDER = ["2F_N", "3F_N", "3F_A", "2F_A"]
EXPERT_PRIORITY_WEIGHT = {"2F_N": 1.00, "3F_N": 0.85, "3F_A": 0.70, "2F_A": 0.55}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Next-day forecast for 4-way split experts + priority combined ranking")
    p.add_argument("--output-prefix", default="db/experiments/tail_ltr_split4_nextday_prediction")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--windows-wed", default="full_2025")
    p.add_argument("--lambdas-wed", default="0.75,1.0,1.25")
    p.add_argument("--q-grid-wed", default="0.0,0.1,0.2,0.3,0.4")
    p.add_argument("--windows-nonwed", default="recent_60d,full_2025")
    p.add_argument("--lambdas-nonwed", default="0.75,1.0,1.25")
    p.add_argument("--q-grid-nonwed", default="0.0,0.1,0.2,0.3,0.4,0.5,0.6")
    p.add_argument("--min-train-days-wed", type=int, default=12)
    p.add_argument("--min-train-days-nonwed", type=int, default=42)
    p.add_argument("--a-weight", type=float, default=0.4)
    p.add_argument("--non-a-weight", type=float, default=1.3)
    return p


def _prepare_split_dataset(*, a_weight: float, non_a_weight: float) -> pd.DataFrame:
    raw = build_base_rows(db_path=resolve_db_path(), a_weight=float(a_weight), non_a_weight=float(non_a_weight))
    base = aggregate_mode(raw, mode="floor_atype4").sort_values(["entity_key", "date"]).reset_index(drop=True)
    latest = pd.to_datetime(base["date"]).max()
    next_date = latest + pd.Timedelta(days=1)

    # Append placeholder rows for next day (one row per entity_key/last_digit) to compute causal lag features.
    tpl = base[base["date"] == latest].copy()
    tpl["date"] = next_date
    for col in ("total_diff_coins", "total_diff_coins_focus", "avg_diff_coins", "win_rate", "efficiency", "efficiency_focus"):
        tpl[col] = 0.0
    tpl["is_top_2"] = 0
    ext = pd.concat([base, tpl], ignore_index=True, sort=False)
    ext = add_simple_features(ext)
    return ext


def _choose_best_candidate_for_expert(
    *,
    df_expert: pd.DataFrame,
    test_date: pd.Timestamp,
    candidates: list[Candidate],
    q_grid: list[float],
    seed: int,
    train_is_wed: bool,
    min_train_days: int,
) -> tuple[Candidate, dict[str, float], pd.DataFrame]:
    rows: list[tuple[float, Candidate, dict[str, float], pd.DataFrame]] = []
    all_features = improved.get_numeric_features(df_expert)
    all_features = [f for f in all_features if f != "is_top_2"]
    dts = pd.to_datetime(df_expert["date"])
    for cand in candidates:
        tr_start, tr_end = improved.build_window_sweep_configs(valid_start=test_date.strftime("%Y-%m-%d"))[cand.window_name]["train_start"], improved.build_window_sweep_configs(valid_start=test_date.strftime("%Y-%m-%d"))[cand.window_name]["train_end"]
        train = df_expert[(dts >= pd.Timestamp(tr_start)) & (dts <= pd.Timestamp(tr_end))].copy()
        test = df_expert[dts == test_date].copy()
        if train_is_wed:
            train = train[pd.to_datetime(train["date"]).dt.day_name().eq("Wednesday")]
            test = test[pd.to_datetime(test["date"]).dt.day_name().eq("Wednesday")]
        else:
            train = train[~pd.to_datetime(train["date"]).dt.day_name().eq("Wednesday")]
            test = test[~pd.to_datetime(test["date"]).dt.day_name().eq("Wednesday")]
        if train["date"].nunique() < min_train_days or test.empty:
            continue

        # Non-A重視に合わせて目的差枚は focus 列を利用（学習用 diffとして置換）
        train = train.copy()
        test = test.copy()
        train["total_diff_coins"] = train["total_diff_coins_focus"]
        test["total_diff_coins"] = test["total_diff_coins_focus"]

        feats = ops.select_features(train, all_features, "is_top_2", "all")
        cal_df, test_df, choice = train_and_predict_fold(
            train_df=train,
            test_df=test,
            target="is_top_2",
            features=feats,
            decay_lambda=cand.decay_lambda,
            random_state=seed,
            model_params={},
            temperature_candidates=improved.CalibrationConfig().temperature_candidates,
            blend_weights=improved.CalibrationConfig().blend_weights,
            q_grid=q_grid,
            k=2,
        )
        cal_day = topk_day_table(cal_df, "pred", k=2)
        keep = cal_day["margin"] >= choice["threshold"]
        cal_ex = np.where(keep.to_numpy(), cal_day["excess"].to_numpy(), 0.0)
        score = float(np.mean(cal_ex)) if len(cal_ex) else -1e18
        rows.append((score, cand, choice, test_df))

    if not rows:
        raise RuntimeError("No valid candidate for expert")
    score, best_cand, best_choice, best_test = sorted(rows, key=lambda x: x[0], reverse=True)[0]
    _ = score
    return best_cand, best_choice, best_test


def _rank_to_points(rank: int, n: int) -> float:
    return float((n - rank + 1) / n)


def main() -> int:
    args = build_parser().parse_args()
    out_prefix = Path(args.output_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)

    data = _prepare_split_dataset(a_weight=args.a_weight, non_a_weight=args.non_a_weight)
    target_date = pd.to_datetime(data["date"]).max()
    weekday = target_date.day_name()
    train_is_wed = weekday == "Wednesday"

    cands_wed = [Candidate(w, l) for w in parse_csv_strs(args.windows_wed) for l in parse_csv_floats(args.lambdas_wed)]
    cands_non = [Candidate(w, l) for w in parse_csv_strs(args.windows_nonwed) for l in parse_csv_floats(args.lambdas_nonwed)]
    active_cands = cands_wed if train_is_wed else cands_non
    active_q = parse_csv_floats(args.q_grid_wed if train_is_wed else args.q_grid_nonwed)
    min_days = args.min_train_days_wed if train_is_wed else args.min_train_days_nonwed

    expert_outputs: dict[str, Any] = {}
    combined_accumulator: dict[str, float] = {}

    for expert in EXPERT_ORDER:
        ds = data[data["group_key"].astype(str) == expert].copy()
        if ds.empty:
            expert_outputs[expert] = {
                "status": "unavailable",
                "reason": "no_rows_for_expert",
                "priority_weight": EXPERT_PRIORITY_WEIGHT.get(expert, 1.0),
                "selected_candidate": None,
                "ranking": [],
            }
            continue
        try:
            cand, choice, pred_df = _choose_best_candidate_for_expert(
                df_expert=ds,
                test_date=target_date,
                candidates=active_cands,
                q_grid=active_q,
                seed=int(args.seed),
                train_is_wed=train_is_wed,
                min_train_days=int(min_days),
            )
        except RuntimeError as exc:
            expert_outputs[expert] = {
                "status": "unavailable",
                "reason": str(exc),
                "priority_weight": EXPERT_PRIORITY_WEIGHT.get(expert, 1.0),
                "selected_candidate": None,
                "ranking": [],
            }
            continue
        rank_df = pred_df.copy()
        rank_df["last_digit"] = ds[ds["date"] == target_date]["last_digit"].values
        rank_df = rank_df.sort_values("pred", ascending=False).reset_index(drop=True)
        rank_df["rank"] = np.arange(1, len(rank_df) + 1)
        rank_df = rank_df[["rank", "last_digit", "pred"]]

        # priority-weighted rank aggregation
        ew = EXPERT_PRIORITY_WEIGHT.get(expert, 1.0)
        n = len(rank_df)
        for r in rank_df.itertuples(index=False):
            key = str(r.last_digit)
            points = _rank_to_points(int(r.rank), n)
            combined_accumulator[key] = combined_accumulator.get(key, 0.0) + ew * points

        expert_outputs[expert] = {
            "status": "ok",
            "priority_weight": ew,
            "selected_candidate": {
                "window": cand.window_name,
                "lambda": cand.decay_lambda,
                "q": float(choice["q"]),
                "threshold": float(choice["threshold"]),
                "blend_weight": float(choice["blend_weight"]),
            },
            "ranking": rank_df.to_dict(orient="records"),
        }

    combined = (
        pd.DataFrame([{"last_digit": k, "combined_score": v} for k, v in combined_accumulator.items()])
        .sort_values("combined_score", ascending=False)
        .reset_index(drop=True)
    )
    if not combined.empty:
        combined["rank"] = np.arange(1, len(combined) + 1)
        combined = combined[["rank", "last_digit", "combined_score"]]

    priority_top1 = []
    for ex in EXPERT_ORDER:
        if ex not in expert_outputs or not expert_outputs[ex]["ranking"]:
            continue
        top = expert_outputs[ex]["ranking"][0]
        priority_top1.append({"expert": ex, "rank": int(top["rank"]), "last_digit": top["last_digit"], "pred": float(top["pred"])})

    payload = {
        "target_date": str(target_date.date()),
        "target_weekday": weekday,
        "model_mode": "floor_atype4",
        "priority_order": EXPERT_ORDER,
        "priority_weights": EXPERT_PRIORITY_WEIGHT,
        "expert_predictions": expert_outputs,
        "priority_top1_list": priority_top1,
        "combined_priority_ranking": combined.to_dict(orient="records") if not combined.empty else [],
        "notes": "combined_priority_ranking uses weighted-rank aggregation by expert priority.",
    }

    out_json = out_prefix.with_suffix(".json")
    out_csv = out_prefix.with_suffix(".csv")
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if not combined.empty:
        combined.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print("Saved:", out_json)
    if not combined.empty:
        print("Saved:", out_csv)
        print(combined.head(5).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
