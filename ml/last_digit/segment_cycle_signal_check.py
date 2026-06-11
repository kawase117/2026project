from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from ml.last_digit.tail_ltr_split_rule_wf import aggregate_mode, build_base_rows, resolve_db_path


EXPERTS = ("2F_N", "3F_N", "3F_A", "2F_A")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Cycle hypothesis + segment concentration check (single hall).")
    p.add_argument("--db-path", default="", help="DB path override. Empty uses resolve_db_path.")
    p.add_argument("--db-glob", default="*7.db")
    p.add_argument("--selection-start", default="2025-07-07")
    p.add_argument("--selection-end", default="2025-12-31")
    p.add_argument("--holdout-start", default="2026-01-01")
    p.add_argument("--holdout-end", default="2026-05-30")
    p.add_argument("--a-weight", type=float, default=0.4)
    p.add_argument("--non-a-weight", type=float, default=1.3)
    p.add_argument("--momentum-window", type=int, default=14)
    p.add_argument(
        "--cycle-lags",
        default="1,2,3,5,7,10,14,21,28",
        help="Comma-separated lag candidates for cycle exploration.",
    )
    p.add_argument("--seed", type=int, default=20260601)
    p.add_argument("--output-prefix", default="db/experiments/segment_cycle_signal_check")
    return p


def _seed_for(rule: str, date: pd.Timestamp, base_seed: int) -> int:
    key = f"{rule}|{date.date()}|{base_seed}".encode("utf-8")
    return int(hashlib.sha256(key).hexdigest()[:16], 16) % (2**32 - 1)


def _parse_csv_ints(raw: str) -> list[int]:
    out: list[int] = []
    for x in str(raw).split(","):
        s = x.strip()
        if not s:
            continue
        out.append(int(s))
    return out


def _load_base(args: argparse.Namespace) -> tuple[pd.DataFrame, Path]:
    db_path = resolve_db_path(str(args.db_path), pattern=str(args.db_glob))
    raw = build_base_rows(db_path=db_path, a_weight=float(args.a_weight), non_a_weight=float(args.non_a_weight))
    agg = aggregate_mode(raw, mode="floor_atype4").copy()
    agg["date"] = pd.to_datetime(agg["date"])
    agg["expert"] = agg["group_key"].astype(str)
    agg["last_digit"] = agg["last_digit"].astype(str)
    agg["total_diff_coins"] = pd.to_numeric(agg["total_diff_coins"], errors="coerce").fillna(0.0)
    agg = agg[agg["expert"].isin(EXPERTS)].copy()
    agg["is_positive"] = (agg["total_diff_coins"] > 0.0).astype(int)
    return agg.sort_values(["expert", "last_digit", "date"]).reset_index(drop=True), db_path


def _split_ranges(df: pd.DataFrame, args: argparse.Namespace) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    selection_start = pd.Timestamp(str(args.selection_start))
    selection_end = pd.Timestamp(str(args.selection_end))
    holdout_start = pd.Timestamp(str(args.holdout_start))
    holdout_end = min(pd.Timestamp(str(args.holdout_end)), pd.to_datetime(df["date"]).max())
    return selection_start, selection_end, holdout_start, holdout_end


def _bh_fdr(pvals: np.ndarray) -> np.ndarray:
    p = np.asarray(pvals, dtype=float)
    out = np.full_like(p, np.nan, dtype=float)
    ok = np.isfinite(p)
    if not ok.any():
        return out
    pv = p[ok]
    n = pv.size
    order = np.argsort(pv)
    ranked = pv[order]
    q = np.empty(n, dtype=float)
    prev = 1.0
    for i in range(n - 1, -1, -1):
        rank = i + 1
        val = ranked[i] * n / rank
        prev = min(prev, val)
        q[i] = prev
    q_back = np.empty(n, dtype=float)
    q_back[order] = q
    out[ok] = q_back
    return out


def _cycle_lag14_tests(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for expert in EXPERTS:
        ex = df[df["expert"] == expert]
        for digit, g in ex.groupby("last_digit", sort=True):
            g = g.sort_values("date")
            y = pd.to_numeric(g["is_positive"], errors="coerce")
            x = y.shift(14)
            m = x.notna() & y.notna()
            if int(m.sum()) < 30:
                rho, p_val = np.nan, np.nan
            else:
                rho, p_val = spearmanr(x[m], y[m])
            rows.append(
                {
                    "expert": expert,
                    "last_digit": str(digit),
                    "lag": 14,
                    "rho": float(rho) if np.isfinite(rho) else np.nan,
                    "p_value_raw": float(p_val) if np.isfinite(p_val) else np.nan,
                    "n_pairs": int(m.sum()),
                }
            )
    out = pd.DataFrame(rows)
    out["p_value_fdr_bh"] = _bh_fdr(out["p_value_raw"].to_numpy(dtype=float))
    out["is_sig_5pct_fdr"] = (pd.to_numeric(out["p_value_fdr_bh"], errors="coerce") < 0.05).astype(int)
    out = out.sort_values(["p_value_raw", "rho"], ascending=[True, True]).reset_index(drop=True)
    return out


def _cycle_lag_grid_tests(df: pd.DataFrame, lags: list[int]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for expert in EXPERTS:
        ex = df[df["expert"] == expert]
        for digit, g in ex.groupby("last_digit", sort=True):
            g = g.sort_values("date")
            y = pd.to_numeric(g["is_positive"], errors="coerce")
            for lag in lags:
                x = y.shift(int(lag))
                m = x.notna() & y.notna()
                if int(m.sum()) < 30:
                    rho, p_val = np.nan, np.nan
                else:
                    rho, p_val = spearmanr(x[m], y[m])
                rows.append(
                    {
                        "expert": expert,
                        "last_digit": str(digit),
                        "lag": int(lag),
                        "rho": float(rho) if np.isfinite(rho) else np.nan,
                        "p_value_raw": float(p_val) if np.isfinite(p_val) else np.nan,
                        "n_pairs": int(m.sum()),
                    }
                )
    out = pd.DataFrame(rows)
    out["p_value_fdr_bh_global"] = _bh_fdr(out["p_value_raw"].to_numpy(dtype=float))
    out["is_sig_5pct_fdr_global"] = (pd.to_numeric(out["p_value_fdr_bh_global"], errors="coerce") < 0.05).astype(int)

    q_local = np.full(len(out), np.nan, dtype=float)
    for ex in EXPERTS:
        m = out["expert"].astype(str).eq(ex).to_numpy()
        q_local[m] = _bh_fdr(out.loc[m, "p_value_raw"].to_numpy(dtype=float))
    out["p_value_fdr_bh_by_expert"] = q_local
    out["is_sig_5pct_fdr_by_expert"] = (pd.to_numeric(out["p_value_fdr_bh_by_expert"], errors="coerce") < 0.05).astype(int)
    out = out.sort_values(["p_value_raw", "rho"], ascending=[True, True]).reset_index(drop=True)
    return out


def _cycle_target_sign_stability(df: pd.DataFrame, *, expert: str = "2F_N", digit: str = "8", lag: int = 14) -> pd.DataFrame:
    use = df[(df["expert"] == expert) & (df["last_digit"] == str(digit))].copy().sort_values("date")
    dates = sorted(pd.to_datetime(use["date"]).unique())
    rows: list[dict[str, Any]] = []
    if len(dates) < 120:
        return pd.DataFrame(rows)
    for start_i in range(0, len(dates) - 89, 30):
        w_start = pd.Timestamp(dates[start_i])
        w_end = pd.Timestamp(dates[start_i + 89])
        w = use[(use["date"] >= w_start) & (use["date"] <= w_end)].copy().sort_values("date")
        y = pd.to_numeric(w["is_positive"], errors="coerce")
        x = y.shift(int(lag))
        m = x.notna() & y.notna()
        if int(m.sum()) < 30:
            rho, p_val = np.nan, np.nan
        else:
            rho, p_val = spearmanr(x[m], y[m])
        rows.append(
            {
                "expert": expert,
                "last_digit": str(digit),
                "lag": int(lag),
                "window_start": str(w_start.date()),
                "window_end": str(w_end.date()),
                "n_days": int(w["date"].nunique()),
                "n_pairs": int(m.sum()),
                "rho": float(rho) if np.isfinite(rho) else np.nan,
                "p_value_raw": float(p_val) if np.isfinite(p_val) else np.nan,
                "sign": "negative" if np.isfinite(rho) and rho < 0 else ("positive" if np.isfinite(rho) and rho > 0 else "na"),
            }
        )
    return pd.DataFrame(rows)


def _segment_daily_table(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (date, expert), g in df.groupby(["date", "expert"], sort=True):
        gg = g.sort_values(["total_diff_coins", "last_digit"], ascending=[False, True]).reset_index(drop=True)
        top1 = float(gg.iloc[0]["total_diff_coins"]) if len(gg) >= 1 else np.nan
        top2_mean = float(gg.head(2)["total_diff_coins"].mean()) if len(gg) >= 2 else np.nan
        seg_mean = float(gg["total_diff_coins"].mean()) if len(gg) >= 1 else np.nan
        rows.append(
            {
                "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
                "expert": str(expert),
                "seg_top1_diff": top1,
                "seg_top2_mean_diff": top2_mean,
                "seg_mean_diff": seg_mean,
            }
        )
    daily = pd.DataFrame(rows)
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.sort_values(["date", "expert"]).reset_index(drop=True)
    return daily


def _segment_labels(daily: pd.DataFrame) -> pd.DataFrame:
    out = daily.copy()
    out["realized_best_segment"] = (
        out.groupby("date", sort=False)["seg_top1_diff"]
        .rank(method="first", ascending=False)
        .eq(1)
        .astype(int)
    )
    out["dd"] = out["date"].dt.day.astype(int)
    out["weekday"] = out["date"].dt.weekday.astype(int)
    out["is_wed"] = (out["weekday"] == 2).astype(int)
    out["is_day_7x"] = out["dd"].isin([7, 17, 27]).astype(int)
    out["is_day_1x"] = out["dd"].isin([1, 11, 21, 31]).astype(int)
    out["is_zorome_day"] = out["dd"].isin([11, 22]).astype(int)
    out["is_strong_zorome_day"] = (out["dd"] == out["date"].dt.month.astype(int)).astype(int)
    return out


def _predict_segment(
    *,
    rule: str,
    hist: pd.DataFrame,
    date: pd.Timestamp,
    global_mean: pd.Series,
    momentum_window: int,
    seed: int,
) -> str:
    experts = list(global_mean.index.astype(str))
    if rule == "random":
        rng = np.random.default_rng(_seed_for(rule, date, seed))
        return str(rng.choice(np.array(experts, dtype=object)))
    if rule == "global_fixed":
        return str(global_mean.sort_values(ascending=False).index[0])
    if rule == "momentum":
        start = date - pd.Timedelta(days=max(1, int(momentum_window)))
        recent = hist[hist["date"] >= start]
        if recent.empty:
            return str(global_mean.sort_values(ascending=False).index[0])
        m = recent.groupby("expert", sort=False)["seg_top1_diff"].mean().reindex(experts).fillna(-1e18)
        return str(m.sort_values(ascending=False).index[0])
    if rule == "anti_repeat":
        prev_day = hist["date"].max()
        prev_best = (
            hist[(hist["date"] == prev_day) & (hist["realized_best_segment"] == 1)]["expert"].astype(str).iloc[0]
            if hist["date"].notna().any()
            else ""
        )
        score = global_mean.copy()
        if prev_best in score.index:
            score.loc[prev_best] = -1e18
        return str(score.sort_values(ascending=False).index[0])
    if rule == "drought_abs":
        winners = hist[hist["realized_best_segment"] == 1][["date", "expert"]].copy()
        last_seen = winners.groupby("expert", sort=False)["date"].max().to_dict()
        score = pd.Series(index=global_mean.index, dtype=float)
        for ex in score.index:
            dt = last_seen.get(ex)
            score.loc[ex] = 9999.0 if dt is None else float((date - pd.Timestamp(dt)).days)
        return str(score.sort_values(ascending=False).index[0])
    raise ValueError(f"Unknown rule: {rule}")


def _segment_rule_eval(
    *,
    labeled_daily: pd.DataFrame,
    selection_start: pd.Timestamp,
    selection_end: pd.Timestamp,
    holdout_start: pd.Timestamp,
    holdout_end: pd.Timestamp,
    momentum_window: int,
    seed: int,
) -> pd.DataFrame:
    sel = labeled_daily[(labeled_daily["date"] >= selection_start) & (labeled_daily["date"] <= selection_end)].copy()
    ho = labeled_daily[(labeled_daily["date"] >= holdout_start) & (labeled_daily["date"] <= holdout_end)].copy()
    if sel.empty or ho.empty:
        return pd.DataFrame()

    global_mean = sel.groupby("expert", sort=False)["seg_top1_diff"].mean()
    rules = ("random", "global_fixed", "momentum", "anti_repeat", "drought_abs")

    rows: list[dict[str, Any]] = []
    for dt in sorted(pd.to_datetime(ho["date"]).unique()):
        hist = labeled_daily[labeled_daily["date"] < dt].copy()
        day = ho[ho["date"] == dt].copy()
        if hist.empty or day.empty:
            continue
        actual_best = day.sort_values(["seg_top1_diff", "expert"], ascending=[False, True]).iloc[0]
        for r in rules:
            pred_seg = _predict_segment(
                rule=r,
                hist=hist,
                date=pd.Timestamp(dt),
                global_mean=global_mean,
                momentum_window=int(momentum_window),
                seed=int(seed),
            )
            pred_row = day[day["expert"] == pred_seg]
            if pred_row.empty:
                continue
            pred_top1 = float(pred_row.iloc[0]["seg_top1_diff"])
            baseline_day_mean = float(day["seg_top1_diff"].mean())
            rows.append(
                {
                    "date": pd.Timestamp(dt).strftime("%Y-%m-%d"),
                    "rule": r,
                    "pred_segment": str(pred_seg),
                    "actual_best_segment": str(actual_best["expert"]),
                    "hit_at_1": int(str(pred_seg) == str(actual_best["expert"])),
                    "pred_segment_top1_diff": pred_top1,
                    "day_segment_top1_mean": baseline_day_mean,
                    "uplift_vs_day_mean": pred_top1 - baseline_day_mean,
                }
            )
    return pd.DataFrame(rows).sort_values(["date", "rule"]).reset_index(drop=True)


def _segment_rule_summary(rule_daily: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if rule_daily.empty:
        return pd.DataFrame(), pd.DataFrame()
    day_actual = rule_daily[["date", "actual_best_segment"]].drop_duplicates().copy()
    dist = (
        day_actual["actual_best_segment"]
        .value_counts(normalize=True)
        .rename_axis("actual_best_segment")
        .reset_index(name="share")
    )
    majority_rate = float(dist["share"].max()) if not dist.empty else np.nan
    rows: list[dict[str, Any]] = []
    for rule, g in rule_daily.groupby("rule", sort=False):
        hit = float(pd.to_numeric(g["hit_at_1"], errors="coerce").mean())
        rows.append(
            {
                "rule": str(rule),
                "n_days": int(g["date"].nunique()),
                "hit_at_1_mean": hit,
                "hit_lift_vs_random25": float(hit - 0.25),
                "hit_lift_vs_majority": float(hit - majority_rate) if np.isfinite(majority_rate) else np.nan,
                "pred_segment_top1_diff_mean": float(pd.to_numeric(g["pred_segment_top1_diff"], errors="coerce").mean()),
                "uplift_vs_day_mean": float(pd.to_numeric(g["uplift_vs_day_mean"], errors="coerce").mean()),
            }
        )
    summary = pd.DataFrame(rows).sort_values("hit_at_1_mean", ascending=False).reset_index(drop=True)
    return summary, dist


def _build_deviation_daily(seg_labeled: pd.DataFrame) -> pd.DataFrame:
    day_best = (
        seg_labeled[seg_labeled["realized_best_segment"] == 1]
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="first")
        .copy()
    )
    day_best["best_segment"] = day_best["expert"].astype(str)
    day_best["is_2fn_deviation"] = (day_best["best_segment"] != "2F_N").astype(int)
    return day_best[
        [
            "date",
            "dd",
            "weekday",
            "is_wed",
            "is_day_7x",
            "is_day_1x",
            "is_zorome_day",
            "is_strong_zorome_day",
            "best_segment",
            "is_2fn_deviation",
        ]
    ].sort_values("date").reset_index(drop=True)


def _deviation_rules_from_selection(sel_daily: pd.DataFrame) -> dict[str, Any]:
    base = float(sel_daily["is_2fn_deviation"].mean())
    wd_rate = sel_daily.groupby("weekday", sort=True)["is_2fn_deviation"].mean()
    wd_high = wd_rate[wd_rate > base].index.astype(int).tolist()

    dd_stat = (
        sel_daily.groupby("dd", sort=True)["is_2fn_deviation"]
        .agg(["mean", "count"])
        .reset_index()
    )
    dd_high = (
        dd_stat[(dd_stat["count"] >= 6) & (dd_stat["mean"] > base)]
        .sort_values(["mean", "dd"], ascending=[False, True])["dd"]
        .astype(int)
        .tolist()
    )
    dd_topk = dd_high[:6]

    pair_stat = (
        sel_daily.groupby(["weekday", "dd"], sort=True)["is_2fn_deviation"]
        .agg(["mean", "count"])
        .reset_index()
    )
    pair_high = pair_stat[(pair_stat["count"] >= 4) & (pair_stat["mean"] > base)].copy()
    pair_set = set((int(r["weekday"]), int(r["dd"])) for _, r in pair_high.iterrows())

    return {
        "base_rate": base,
        "weekday_high": wd_high,
        "dd_topk": dd_topk,
        "weekday_dd_high_pairs": sorted(list(pair_set)),
    }


def _predict_deviation(rule: str, row: pd.Series, meta: dict[str, Any]) -> int:
    if rule == "always_no":
        return 0
    if rule == "always_yes":
        return 1
    if rule == "weekday_high":
        return int(int(row["weekday"]) in set(meta["weekday_high"]))
    if rule == "dd_topk":
        return int(int(row["dd"]) in set(meta["dd_topk"]))
    if rule == "weekday_dd_combo":
        key = (int(row["weekday"]), int(row["dd"]))
        return int(key in set(tuple(x) for x in meta["weekday_dd_high_pairs"]))
    if rule == "calendar_union":
        a = int(int(row["weekday"]) in set(meta["weekday_high"]))
        b = int(int(row["dd"]) in set(meta["dd_topk"]))
        return int((a + b) > 0)
    raise ValueError(f"Unknown deviation rule: {rule}")


def _deviation_eval_holdout(
    holdout_daily: pd.DataFrame,
    meta: dict[str, Any],
    *,
    day_segment_diff: pd.DataFrame,
    fallback_segment_when_deviation: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rules = ("always_no", "always_yes", "weekday_high", "dd_topk", "weekday_dd_combo", "calendar_union")
    y = pd.to_numeric(holdout_daily["is_2fn_deviation"], errors="coerce").fillna(0).astype(int).to_numpy()
    day_seg = day_segment_diff.copy()
    day_seg["date"] = pd.to_datetime(day_seg["date"])
    day_seg = day_seg.set_index("date")
    baseline_segment = "2F_N"

    rows: list[dict[str, Any]] = []
    daily_rows: list[dict[str, Any]] = []

    for r in rules:
        pred = holdout_daily.apply(lambda row: _predict_deviation(r, row, meta), axis=1).to_numpy(dtype=int)
        tp = int(((pred == 1) & (y == 1)).sum())
        fp = int(((pred == 1) & (y == 0)).sum())
        fn = int(((pred == 0) & (y == 1)).sum())
        tn = int(((pred == 0) & (y == 0)).sum())

        precision = float(tp / (tp + fp)) if (tp + fp) > 0 else np.nan
        recall = float(tp / (tp + fn)) if (tp + fn) > 0 else np.nan
        f1 = float((2.0 * precision * recall) / (precision + recall)) if np.isfinite(precision) and np.isfinite(recall) and (precision + recall) > 0 else np.nan
        pred_rate = float((pred == 1).mean())
        acc = float((pred == y).mean())
        bal_acc = float(0.5 * ((tp / (tp + fn) if (tp + fn) > 0 else 0.0) + (tn / (tn + fp) if (tn + fp) > 0 else 0.0)))

        rule_df = holdout_daily.copy().reset_index(drop=True)
        rule_df["rule"] = r
        rule_df["pred_deviation"] = pred
        rule_df["chosen_segment"] = np.where(rule_df["pred_deviation"] == 1, fallback_segment_when_deviation, baseline_segment)
        rule_df["baseline_segment"] = baseline_segment
        chosen_vals: list[float] = []
        base_vals: list[float] = []
        case_vals: list[str] = []
        for _, row in rule_df.iterrows():
            dt = pd.Timestamp(row["date"])
            true_dev = int(row["is_2fn_deviation"])
            pred_dev = int(row["pred_deviation"])
            if (pred_dev == 1) and (true_dev == 1):
                case_vals.append("TP")
            elif (pred_dev == 1) and (true_dev == 0):
                case_vals.append("FP")
            elif (pred_dev == 0) and (true_dev == 1):
                case_vals.append("FN")
            else:
                case_vals.append("TN")
            seg_row = day_seg.loc[dt]
            if isinstance(seg_row, pd.DataFrame):
                seg_row = seg_row.iloc[0]
            chosen_vals.append(float(seg_row[row["chosen_segment"]]))
            base_vals.append(float(seg_row[baseline_segment]))
        rule_df["chosen_diff"] = chosen_vals
        rule_df["baseline_2fn_diff"] = base_vals
        rule_df["uplift_vs_2fn"] = rule_df["chosen_diff"] - rule_df["baseline_2fn_diff"]
        rule_df["case"] = case_vals

        tp_uplift = pd.to_numeric(rule_df.loc[rule_df["case"] == "TP", "uplift_vs_2fn"], errors="coerce")
        fp_uplift = pd.to_numeric(rule_df.loc[rule_df["case"] == "FP", "uplift_vs_2fn"], errors="coerce")
        moved_uplift = pd.to_numeric(rule_df.loc[rule_df["pred_deviation"] == 1, "uplift_vs_2fn"], errors="coerce")
        total_uplift = pd.to_numeric(rule_df["uplift_vs_2fn"], errors="coerce")
        chosen_mean = pd.to_numeric(rule_df["chosen_diff"], errors="coerce")
        base_mean = pd.to_numeric(rule_df["baseline_2fn_diff"], errors="coerce")

        rows.append(
            {
                "rule": r,
                "n_days": int(len(holdout_daily)),
                "pred_positive_rate": pred_rate,
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "tn": tn,
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "accuracy": acc,
                "balanced_accuracy": bal_acc,
                "chosen_diff_mean": float(chosen_mean.mean()),
                "baseline_2fn_diff_mean": float(base_mean.mean()),
                "mean_uplift_vs_2fn": float(total_uplift.mean()),
                "mean_uplift_on_predicted_deviation_days": float(moved_uplift.mean()) if len(moved_uplift) > 0 else np.nan,
                "tp_mean_uplift_vs_2fn": float(tp_uplift.mean()) if len(tp_uplift) > 0 else np.nan,
                "fp_mean_uplift_vs_2fn": float(fp_uplift.mean()) if len(fp_uplift) > 0 else np.nan,
            }
        )
        daily_rows.extend(
            rule_df[
                [
                    "date",
                    "rule",
                    "best_segment",
                    "is_2fn_deviation",
                    "pred_deviation",
                    "chosen_segment",
                    "baseline_segment",
                    "chosen_diff",
                    "baseline_2fn_diff",
                    "uplift_vs_2fn",
                    "case",
                ]
            ].to_dict(orient="records")
        )

    summary = pd.DataFrame(rows).sort_values(["mean_uplift_vs_2fn", "f1"], ascending=[False, False]).reset_index(drop=True)
    daily = pd.DataFrame(daily_rows).sort_values(["date", "rule"]).reset_index(drop=True)
    return summary, daily


def main() -> int:
    args = build_parser().parse_args()
    out_prefix = Path(str(args.output_prefix))
    out_prefix.parent.mkdir(parents=True, exist_ok=True)

    df, db_path = _load_base(args)
    cycle_lags = sorted(set(_parse_csv_ints(args.cycle_lags)))
    sel_s, sel_e, ho_s, ho_e = _split_ranges(df, args)

    cycle_tests = _cycle_lag14_tests(df)
    cycle_grid_tests = _cycle_lag_grid_tests(df, cycle_lags)
    cycle_stability = _cycle_target_sign_stability(df, expert="2F_N", digit="8", lag=14)

    seg_daily = _segment_daily_table(df)
    seg_labeled = _segment_labels(seg_daily)
    seg_rule_daily = _segment_rule_eval(
        labeled_daily=seg_labeled,
        selection_start=sel_s,
        selection_end=sel_e,
        holdout_start=ho_s,
        holdout_end=ho_e,
        momentum_window=int(args.momentum_window),
        seed=int(args.seed),
    )
    seg_rule_summary, seg_actual_dist = _segment_rule_summary(seg_rule_daily)
    dev_daily = _build_deviation_daily(seg_labeled)
    dev_sel = dev_daily[(dev_daily["date"] >= sel_s) & (dev_daily["date"] <= sel_e)].copy()
    dev_ho = dev_daily[(dev_daily["date"] >= ho_s) & (dev_daily["date"] <= ho_e)].copy()
    dev_meta = _deviation_rules_from_selection(dev_sel)
    sel_seg_means = (
        seg_labeled[(seg_labeled["date"] >= sel_s) & (seg_labeled["date"] <= sel_e)]
        .groupby("expert", sort=False)["seg_top1_diff"]
        .mean()
    )
    non2fn = sel_seg_means[sel_seg_means.index != "2F_N"].sort_values(ascending=False)
    fallback_non2fn = str(non2fn.index[0]) if len(non2fn) > 0 else "3F_N"
    day_segment_diff = (
        seg_labeled.pivot_table(index="date", columns="expert", values="seg_top1_diff", aggfunc="first")
        .reset_index()
    )
    dev_eval, dev_rule_daily = _deviation_eval_holdout(
        dev_ho,
        dev_meta,
        day_segment_diff=day_segment_diff,
        fallback_segment_when_deviation=fallback_non2fn,
    )

    out_cycle = out_prefix.with_name(out_prefix.name + "_cycle_lag14_tests.csv")
    out_cycle_grid = out_prefix.with_name(out_prefix.name + "_cycle_lag_grid_tests.csv")
    out_cycle_stability = out_prefix.with_name(out_prefix.name + "_cycle_target_stability_2FN_digit8_lag14.csv")
    out_seg_daily = out_prefix.with_name(out_prefix.name + "_segment_rule_daily.csv")
    out_seg_summary = out_prefix.with_name(out_prefix.name + "_segment_rule_summary.csv")
    out_seg_dist = out_prefix.with_name(out_prefix.name + "_segment_actual_distribution.csv")
    out_dev_daily = out_prefix.with_name(out_prefix.name + "_deviation_daily.csv")
    out_dev_eval = out_prefix.with_name(out_prefix.name + "_deviation_rule_eval.csv")
    out_dev_rule_daily = out_prefix.with_name(out_prefix.name + "_deviation_rule_daily.csv")
    out_json = out_prefix.with_name(out_prefix.name + "_summary.json")

    cycle_tests.to_csv(out_cycle, index=False, encoding="utf-8-sig")
    cycle_grid_tests.to_csv(out_cycle_grid, index=False, encoding="utf-8-sig")
    cycle_stability.to_csv(out_cycle_stability, index=False, encoding="utf-8-sig")
    seg_rule_daily.to_csv(out_seg_daily, index=False, encoding="utf-8-sig")
    seg_rule_summary.to_csv(out_seg_summary, index=False, encoding="utf-8-sig")
    seg_actual_dist.to_csv(out_seg_dist, index=False, encoding="utf-8-sig")
    dev_daily.to_csv(out_dev_daily, index=False, encoding="utf-8-sig")
    dev_eval.to_csv(out_dev_eval, index=False, encoding="utf-8-sig")
    dev_rule_daily.to_csv(out_dev_rule_daily, index=False, encoding="utf-8-sig")

    summary = {
        "db_path": str(db_path),
        "selection_range": {"start": str(sel_s.date()), "end": str(sel_e.date())},
        "holdout_range": {"start": str(ho_s.date()), "end": str(ho_e.date())},
        "baselines": {
            "segment_hit_at_1_random": 0.25,
        },
        "outputs": {
            "cycle_lag14_tests": str(out_cycle),
            "cycle_lag_grid_tests": str(out_cycle_grid),
            "cycle_target_stability_2FN_digit8_lag14": str(out_cycle_stability),
            "segment_rule_daily": str(out_seg_daily),
            "segment_rule_summary": str(out_seg_summary),
            "segment_actual_distribution": str(out_seg_dist),
            "deviation_daily": str(out_dev_daily),
            "deviation_rule_eval": str(out_dev_eval),
            "deviation_rule_daily": str(out_dev_rule_daily),
        },
        "deviation_meta": dev_meta,
        "deviation_policy": {
            "baseline_segment_when_no_deviation": "2F_N",
            "fallback_segment_when_deviation": fallback_non2fn,
        },
    }
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[OK] saved: {out_cycle}")
    print(f"[OK] saved: {out_cycle_grid}")
    print(f"[OK] saved: {out_cycle_stability}")
    print(f"[OK] saved: {out_seg_daily}")
    print(f"[OK] saved: {out_seg_summary}")
    print(f"[OK] saved: {out_seg_dist}")
    print(f"[OK] saved: {out_dev_daily}")
    print(f"[OK] saved: {out_dev_eval}")
    print(f"[OK] saved: {out_dev_rule_daily}")
    print(f"[OK] saved: {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
