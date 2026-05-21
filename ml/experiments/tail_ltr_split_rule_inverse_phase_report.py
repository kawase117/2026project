from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.experiments import tail_ltr_profit_ops as ops
from ml.experiments import tail_time_adaptive_ltr_poc_improved as improved
from ml.experiments.tail_ltr_full_walkforward_ops import build_train_window, topk_day_table, train_and_predict_fold
from ml.experiments.tail_ltr_split_rule_wf import Candidate, add_simple_features, aggregate_mode, build_base_rows, parse_csv_floats, parse_csv_ints, parse_csv_strs, resolve_db_path


NON_A_EXPERTS = ["2F_N", "3F_N"]
A_EXPERTS = ["2F_A", "3F_A"]
ALL_EXPERTS = NON_A_EXPERTS + A_EXPERTS


def _pick_best_candidate_for_block(
    *,
    df_expert: pd.DataFrame,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    seed: int,
    candidates: list[Candidate],
    q_grid: list[float],
    train_is_wed: bool,
    min_train_days: int,
) -> tuple[Candidate, pd.DataFrame, float] | None:
    dts = pd.to_datetime(df_expert["date"])
    features = improved.get_numeric_features(df_expert)
    features = [f for f in features if f != "is_top_2"]
    best: tuple[float, Candidate, pd.DataFrame] | None = None

    for cand in candidates:
        tr_start, tr_end = build_train_window(cand.window_name, test_start)
        train = df_expert[(dts >= tr_start) & (dts <= tr_end)].copy()
        test = df_expert[(dts >= test_start) & (dts <= test_end)].copy()

        tr_wed = pd.to_datetime(train["date"]).dt.day_name().eq("Wednesday")
        te_wed = pd.to_datetime(test["date"]).dt.day_name().eq("Wednesday")
        train = train[tr_wed if train_is_wed else ~tr_wed].copy()
        test = test[te_wed if train_is_wed else ~te_wed].copy()
        if train["date"].nunique() < min_train_days or test.empty:
            continue

        train = train.copy()
        test = test.copy()
        # 非A重視の実差枚で評価
        train["total_diff_coins"] = train["total_diff_coins_focus"]
        test["total_diff_coins"] = test["total_diff_coins_focus"]

        feats = ops.select_features(train, features, "is_top_2", "all")
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
        cal_score = float(np.mean(cal_ex)) if len(cal_ex) else -1e18

        t = test_df.copy().reset_index(drop=True)
        meta = test[["date", "last_digit", "group_key", "total_diff_coins_focus", "machine_count"]].reset_index(drop=True)
        t["last_digit"] = meta["last_digit"].astype(str).values
        t["group_key"] = meta["group_key"].astype(str).values
        t["actual_focus_diff"] = pd.to_numeric(meta["total_diff_coins_focus"], errors="coerce").fillna(0.0).values
        t["machine_count"] = pd.to_numeric(meta["machine_count"], errors="coerce").fillna(0.0).values
        t["margin"] = (
            t.sort_values(["date", "pred"], ascending=[True, False])
            .groupby("date", sort=False)["pred"]
            .transform(lambda s: float(s.iloc[0] - s.iloc[1]) if len(s) >= 2 else 0.0)
        )
        t["selected"] = (t["margin"] >= float(choice["threshold"])).astype(int)

        if best is None or cal_score > best[0]:
            best = (cal_score, cand, t)

    if best is None:
        return None
    return best[1], best[2], float(best[0])


def _summarize_inverse_days(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {
            "n_days": 0,
            "inverse_days": 0,
            "inverse_rate": 0.0,
            "non_a_positive_a_negative_days": 0,
            "a_positive_non_a_negative_days": 0,
        }
    inv = (df["non_a_sum"] * df["a_sum"] < 0).astype(int)
    na_pos_a_neg = ((df["non_a_sum"] > 0) & (df["a_sum"] < 0)).astype(int)
    a_pos_na_neg = ((df["a_sum"] > 0) & (df["non_a_sum"] < 0)).astype(int)
    return {
        "n_days": int(len(df)),
        "inverse_days": int(inv.sum()),
        "inverse_rate": float(inv.mean()),
        "non_a_positive_a_negative_days": int(na_pos_a_neg.sum()),
        "a_positive_non_a_negative_days": int(a_pos_na_neg.sum()),
    }


def _summarize_cross_days(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {
            "n_days": 0,
            "cross_both_days": 0,
            "cross_both_rate": 0.0,
            "cross_any_days": 0,
            "cross_any_rate": 0.0,
            "a_pred_hits_non_a_actual_days": 0,
            "non_a_pred_hits_a_actual_days": 0,
        }
    a_to_non = (df["a_pred_digit"] == df["non_a_actual_digit"]).astype(int)
    non_to_a = (df["non_a_pred_digit"] == df["a_actual_digit"]).astype(int)
    cross_both = (a_to_non & non_to_a).astype(int)
    cross_any = ((a_to_non | non_to_a)).astype(int)
    return {
        "n_days": int(len(df)),
        "cross_both_days": int(cross_both.sum()),
        "cross_both_rate": float(cross_both.mean()),
        "cross_any_days": int(cross_any.sum()),
        "cross_any_rate": float(cross_any.mean()),
        "a_pred_hits_non_a_actual_days": int(a_to_non.sum()),
        "non_a_pred_hits_a_actual_days": int(non_to_a.sum()),
    }


def _summarize_split4_cross_days(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {
            "n_floor_days": 0,
            "cross_both_rate_floor_day": 0.0,
            "cross_any_rate_floor_day": 0.0,
            "n_days": 0,
            "day_any_floor_cross_both_rate": 0.0,
            "day_any_floor_cross_any_rate": 0.0,
            "day_both_floors_cross_both_rate": 0.0,
            "day_both_floors_cross_any_rate": 0.0,
            "per_floor": {},
        }

    tmp = df.copy()
    tmp["cross_a_to_non"] = (tmp["a_pred_digit"] == tmp["non_a_actual_digit"]).astype(int)
    tmp["cross_non_to_a"] = (tmp["non_a_pred_digit"] == tmp["a_actual_digit"]).astype(int)
    tmp["cross_both"] = (tmp["cross_a_to_non"] & tmp["cross_non_to_a"]).astype(int)
    tmp["cross_any"] = ((tmp["cross_a_to_non"] | tmp["cross_non_to_a"])).astype(int)

    per_floor: dict[str, Any] = {}
    for fl, g in tmp.groupby("floor", sort=False):
        per_floor[str(fl)] = _summarize_cross_days(
            g[["a_pred_digit", "non_a_pred_digit", "a_actual_digit", "non_a_actual_digit"]]
        )

    by_day = (
        tmp.groupby(["seed", "date"], as_index=False)
        .agg(
            cross_both_max=("cross_both", "max"),
            cross_any_max=("cross_any", "max"),
            cross_both_sum=("cross_both", "sum"),
            cross_any_sum=("cross_any", "sum"),
        )
    )
    both_floor_both = (by_day["cross_both_sum"] >= 2).astype(int)
    both_floor_any = (by_day["cross_any_sum"] >= 2).astype(int)
    return {
        "n_floor_days": int(len(tmp)),
        "cross_both_rate_floor_day": float(tmp["cross_both"].mean()),
        "cross_any_rate_floor_day": float(tmp["cross_any"].mean()),
        "n_days": int(len(by_day)),
        "day_any_floor_cross_both_rate": float(by_day["cross_both_max"].mean()),
        "day_any_floor_cross_any_rate": float(by_day["cross_any_max"].mean()),
        "day_both_floors_cross_both_rate": float(both_floor_both.mean()),
        "day_both_floors_cross_any_rate": float(both_floor_any.mean()),
        "per_floor": per_floor,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Inverse-phase report between A and non-A in split4 model")
    p.add_argument("--output-prefix", default="db/experiments/tail_ltr_split_rule_inverse_phase")
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
    p.add_argument("--a-weight", type=float, default=0.4)
    p.add_argument("--non-a-weight", type=float, default=1.3)
    return p


def main() -> int:
    args = build_parser().parse_args()
    out_prefix = Path(args.output_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)

    raw = build_base_rows(db_path=Path(resolve_db_path()), a_weight=float(args.a_weight), non_a_weight=float(args.non_a_weight))
    data = add_simple_features(aggregate_mode(raw, mode="floor_atype4")).sort_values("date").reset_index(drop=True)
    valid_cfg = improved.build_fixed_split_configs(data)["regime_3_fixed_split"]
    valid_dates = sorted(pd.to_datetime(data["date"].unique()))
    valid_dates = [x for x in valid_dates if pd.Timestamp(valid_cfg["valid_start"]) <= x <= pd.Timestamp(valid_cfg["valid_end"])]
    if not valid_dates:
        raise ValueError("No valid dates in regime_3_fixed_split for inverse-phase report")

    seeds = parse_csv_ints(args.seeds)
    c_wed = [Candidate(w, l) for w in parse_csv_strs(args.windows_wed) for l in parse_csv_floats(args.lambdas_wed)]
    c_non = [Candidate(w, l) for w in parse_csv_strs(args.windows_nonwed) for l in parse_csv_floats(args.lambdas_nonwed)]
    q_wed = parse_csv_floats(args.q_grid_wed)
    q_non = parse_csv_floats(args.q_grid_nonwed)

    expert_frames = {ex: data[data["group_key"].astype(str) == ex].copy() for ex in ALL_EXPERTS}
    available_group_days = (
        data.groupby("group_key")["date"].nunique().sort_index().to_dict()
        if not data.empty
        else {}
    )
    day_rows: list[dict[str, Any]] = []
    detail_rows: list[dict[str, Any]] = []
    agg_cross_rows: list[dict[str, Any]] = []
    split4_cross_rows: list[dict[str, Any]] = []

    for seed in seeds:
        idx = max(0, args.warmup_days)
        while idx < len(valid_dates):
            test_start = valid_dates[idx]
            block = valid_dates[idx : idx + args.test_days]
            if not block:
                break
            test_end = block[-1]

            pred_by_expert: dict[str, pd.DataFrame] = {}
            for ex in ALL_EXPERTS:
                ds = expert_frames.get(ex)
                if ds is None or ds.empty:
                    continue
                # this fold has both Wednesday and non-Wednesday days; we produce unified block prediction
                # by running twice and concatenating.
                part_wed = _pick_best_candidate_for_block(
                    df_expert=ds,
                    test_start=test_start,
                    test_end=test_end,
                    seed=seed,
                    candidates=c_wed,
                    q_grid=q_wed,
                    train_is_wed=True,
                    min_train_days=int(args.min_train_days_wed),
                )
                part_non = _pick_best_candidate_for_block(
                    df_expert=ds,
                    test_start=test_start,
                    test_end=test_end,
                    seed=seed,
                    candidates=c_non,
                    q_grid=q_non,
                    train_is_wed=False,
                    min_train_days=int(args.min_train_days_nonwed),
                )
                pieces = []
                if part_wed is not None:
                    pieces.append(part_wed[1])
                if part_non is not None:
                    pieces.append(part_non[1])
                if not pieces:
                    continue
                pred_by_expert[ex] = pd.concat(pieces, ignore_index=True)

            if not pred_by_expert:
                idx += args.test_days
                continue

            fold_all_rows = []
            for ex, pdf in pred_by_expert.items():
                if pdf.empty:
                    continue
                tmp = pdf.copy()
                tmp["expert"] = ex
                tmp["side"] = "NON_A" if ex in NON_A_EXPERTS else "A"
                fold_all_rows.append(
                    tmp[["date", "expert", "side", "last_digit", "pred", "actual_focus_diff", "selected"]]
                )
            if not fold_all_rows:
                idx += args.test_days
                continue
            fold_all_df = pd.concat(fold_all_rows, ignore_index=True)

            # per day / expert: top1 predicted tail and its actual focused diff
            per_expert_top = []
            for ex, pdf in pred_by_expert.items():
                if pdf.empty:
                    continue
                top = (
                    pdf.sort_values(["date", "pred"], ascending=[True, False])
                    .groupby("date", sort=False)
                    .head(1)
                    .copy()
                )
                top["expert"] = ex
                per_expert_top.append(top[["date", "expert", "last_digit", "pred", "actual_focus_diff", "selected"]])
            if not per_expert_top:
                idx += args.test_days
                continue
            top_df = pd.concat(per_expert_top, ignore_index=True)

            for dt, g in top_df.groupby("date", sort=False):
                na = g[g["expert"].isin(NON_A_EXPERTS)]["actual_focus_diff"].sum()
                a = g[g["expert"].isin(A_EXPERTS)]["actual_focus_diff"].sum()
                day_rows.append(
                    {
                        "seed": seed,
                        "date": str(dt),
                        "non_a_sum": float(na),
                        "a_sum": float(a),
                        "inverse": int(float(na) * float(a) < 0.0),
                    }
                )
                for _, r in g.iterrows():
                    detail_rows.append(
                        {
                            "seed": seed,
                            "date": str(dt),
                            "expert": str(r["expert"]),
                            "last_digit": str(r["last_digit"]),
                            "pred": float(r["pred"]),
                            "actual_focus_diff": float(r["actual_focus_diff"]),
                            "selected": int(r["selected"]),
                        }
                    )

            # Per-day cross match:
            # - A_pred_digit: last_digit with max summed pred in A side
            # - NON_A_pred_digit: last_digit with max summed pred in NON_A side
            # - A_actual_digit / NON_A_actual_digit: last_digit with max summed actual_focus_diff in each side
            pred_side_digit = (
                fold_all_df.groupby(["date", "side", "last_digit"], sort=False)["pred"]
                .sum()
                .reset_index()
                .sort_values(["date", "side", "pred", "last_digit"], ascending=[True, True, False, True])
                .groupby(["date", "side"], sort=False)
                .head(1)
                .rename(columns={"last_digit": "pred_digit"})
            )
            actual_side_digit = (
                fold_all_df.groupby(["date", "side", "last_digit"], sort=False)["actual_focus_diff"]
                .sum()
                .reset_index()
                .sort_values(["date", "side", "actual_focus_diff", "last_digit"], ascending=[True, True, False, True])
                .groupby(["date", "side"], sort=False)
                .head(1)
                .rename(columns={"last_digit": "actual_digit"})
            )
            side_summary = pred_side_digit.merge(
                actual_side_digit[["date", "side", "actual_digit"]],
                on=["date", "side"],
                how="inner",
            )
            for dt, g in side_summary.groupby("date", sort=False):
                row_a = g[g["side"] == "A"]
                row_n = g[g["side"] == "NON_A"]
                if row_a.empty or row_n.empty:
                    continue
                a_pred = str(row_a["pred_digit"].iloc[0])
                n_pred = str(row_n["pred_digit"].iloc[0])
                a_act = str(row_a["actual_digit"].iloc[0])
                n_act = str(row_n["actual_digit"].iloc[0])
                cross_a_to_non = int(a_pred == n_act)
                cross_non_to_a = int(n_pred == a_act)
                cross_both = int(cross_a_to_non == 1 and cross_non_to_a == 1)
                cross_any = int(cross_a_to_non == 1 or cross_non_to_a == 1)
                agg_cross_rows.append(
                    {
                        "seed": seed,
                        "date": str(dt),
                        "a_pred_digit": a_pred,
                        "non_a_pred_digit": n_pred,
                        "a_actual_digit": a_act,
                        "non_a_actual_digit": n_act,
                        "cross_a_pred_hits_non_a_actual": cross_a_to_non,
                        "cross_non_a_pred_hits_a_actual": cross_non_to_a,
                        "cross_both": cross_both,
                        "cross_any": cross_any,
                    }
                )

            # Per-day / floor cross match (2F and 3F separately)
            fold_all_df["floor"] = fold_all_df["expert"].astype(str).str.extract(r"^([23]F)_", expand=False).fillna("")
            floor_side = fold_all_df[
                fold_all_df["floor"].isin(["2F", "3F"]) & fold_all_df["side"].isin(["A", "NON_A"])
            ].copy()
            if not floor_side.empty:
                pred_floor_side_digit = (
                    floor_side.groupby(["date", "floor", "side", "last_digit"], sort=False)["pred"]
                    .sum()
                    .reset_index()
                    .sort_values(
                        ["date", "floor", "side", "pred", "last_digit"],
                        ascending=[True, True, True, False, True],
                    )
                    .groupby(["date", "floor", "side"], sort=False)
                    .head(1)
                    .rename(columns={"last_digit": "pred_digit"})
                )
                actual_floor_side_digit = (
                    floor_side.groupby(["date", "floor", "side", "last_digit"], sort=False)["actual_focus_diff"]
                    .sum()
                    .reset_index()
                    .sort_values(
                        ["date", "floor", "side", "actual_focus_diff", "last_digit"],
                        ascending=[True, True, True, False, True],
                    )
                    .groupby(["date", "floor", "side"], sort=False)
                    .head(1)
                    .rename(columns={"last_digit": "actual_digit"})
                )
                floor_summary = pred_floor_side_digit.merge(
                    actual_floor_side_digit[["date", "floor", "side", "actual_digit"]],
                    on=["date", "floor", "side"],
                    how="inner",
                )
                for (dt, fl), g in floor_summary.groupby(["date", "floor"], sort=False):
                    row_a = g[g["side"] == "A"]
                    row_n = g[g["side"] == "NON_A"]
                    if row_a.empty or row_n.empty:
                        continue
                    a_pred = str(row_a["pred_digit"].iloc[0])
                    n_pred = str(row_n["pred_digit"].iloc[0])
                    a_act = str(row_a["actual_digit"].iloc[0])
                    n_act = str(row_n["actual_digit"].iloc[0])
                    split4_cross_rows.append(
                        {
                            "seed": seed,
                            "date": str(dt),
                            "floor": str(fl),
                            "a_pred_digit": a_pred,
                            "non_a_pred_digit": n_pred,
                            "a_actual_digit": a_act,
                            "non_a_actual_digit": n_act,
                            "cross_a_pred_hits_non_a_actual": int(a_pred == n_act),
                            "cross_non_a_pred_hits_a_actual": int(n_pred == a_act),
                            "cross_both": int((a_pred == n_act) and (n_pred == a_act)),
                            "cross_any": int((a_pred == n_act) or (n_pred == a_act)),
                        }
                    )
            idx += args.test_days

    day_df = pd.DataFrame(day_rows)
    detail_df = pd.DataFrame(detail_rows)
    agg_cross_df = pd.DataFrame(agg_cross_rows)
    split4_cross_df = pd.DataFrame(split4_cross_rows)
    if not day_df.empty:
        day_df = day_df.sort_values(["seed", "date"]).reset_index(drop=True)
    if not agg_cross_df.empty:
        agg_cross_df = agg_cross_df.sort_values(["seed", "date"]).reset_index(drop=True)
    if not split4_cross_df.empty:
        split4_cross_df = split4_cross_df.sort_values(["seed", "date", "floor"]).reset_index(drop=True)
    if not detail_df.empty:
        detail_df = detail_df.sort_values(["seed", "date", "expert"]).reset_index(drop=True)

    overall = _summarize_inverse_days(day_df)
    overall_cross = _summarize_cross_days(
        agg_cross_df[
            [
                "a_pred_digit",
                "non_a_pred_digit",
                "a_actual_digit",
                "non_a_actual_digit",
            ]
        ]
    )
    overall_split4_cross = _summarize_split4_cross_days(split4_cross_df)
    by_weekday = {}
    by_weekday_cross = {}
    by_weekday_split4_cross = {}
    if not day_df.empty:
        tmp = day_df.copy()
        tmp["weekday"] = pd.to_datetime(tmp["date"]).dt.day_name()
        for wd, g in tmp.groupby("weekday", sort=False):
            by_weekday[str(wd)] = _summarize_inverse_days(g[["non_a_sum", "a_sum"]])
    if not agg_cross_df.empty:
        tmp_cross = agg_cross_df.copy()
        tmp_cross["weekday"] = pd.to_datetime(tmp_cross["date"]).dt.day_name()
        for wd, g in tmp_cross.groupby("weekday", sort=False):
            by_weekday_cross[str(wd)] = _summarize_cross_days(
                g[
                    [
                        "a_pred_digit",
                        "non_a_pred_digit",
                        "a_actual_digit",
                        "non_a_actual_digit",
                    ]
                ]
            )
    if not split4_cross_df.empty:
        tmp_split4 = split4_cross_df.copy()
        tmp_split4["weekday"] = pd.to_datetime(tmp_split4["date"]).dt.day_name()
        for wd, g in tmp_split4.groupby("weekday", sort=False):
            by_weekday_split4_cross[str(wd)] = _summarize_split4_cross_days(g)

    payload = {
        "config": vars(args),
        "period": {"start": str(valid_dates[0].date()) if valid_dates else "", "end": str(valid_dates[-1].date()) if valid_dates else ""},
        "available_groups": {str(k): int(v) for k, v in available_group_days.items()},
        "overall": overall,
        "overall_cross_match_aggregated": overall_cross,
        "overall_cross_match_split4": overall_split4_cross,
        "by_weekday": by_weekday,
        "by_weekday_cross_match_aggregated": by_weekday_cross,
        "by_weekday_cross_match_split4": by_weekday_split4_cross,
        "notes": "inverse = sign(non_a_sum) != sign(a_sum) using top1 predicted tail per expert/day.",
    }

    out_json = out_prefix.with_suffix(".json")
    out_days = out_prefix.with_name(out_prefix.name + "_days.csv")
    out_detail = out_prefix.with_name(out_prefix.name + "_detail.csv")
    out_agg_cross = out_prefix.with_name(out_prefix.name + "_cross_aggregated.csv")
    out_split4_cross = out_prefix.with_name(out_prefix.name + "_cross_split4.csv")
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    day_df.to_csv(out_days, index=False, encoding="utf-8-sig")
    detail_df.to_csv(out_detail, index=False, encoding="utf-8-sig")
    agg_cross_df.to_csv(out_agg_cross, index=False, encoding="utf-8-sig")
    split4_cross_df.to_csv(out_split4_cross, index=False, encoding="utf-8-sig")
    print("Saved:", out_json)
    print("Saved:", out_days)
    print("Saved:", out_detail)
    print("Saved:", out_agg_cross)
    print("Saved:", out_split4_cross)
    print(json.dumps(payload["overall"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
