from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import binomtest, chi2_contingency, fisher_exact, norm, spearmanr

from ml.last_digit.tail_ltr_split_rule_wf import aggregate_mode, build_base_rows, resolve_db_path


EXPERTS = ("2F_N", "3F_N", "3F_A", "2F_A")
LAGS = (1, 2, 3, 7, 14)
RULES = (
    "random",
    "global_fixed",
    "calendar_fixed",
    "anti_repeat",
    "drought_abs",
    "drought_relative",
    "momentum",
)
RANDOM_HIT2_BASELINE = 1.0 - (28.0 / 45.0)  # 10C2中、外れる組み合わせ8C2
RANDOM_PRECISION2_BASELINE = 0.2


@dataclass
class RulePrediction:
    rule: str
    top1: str
    top2: str
    source: str


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Signal-existence validation before ML expansion.")
    p.add_argument("--db-path", default="", help="DB path override. Empty uses resolve_db_path.")
    p.add_argument("--db-glob", default="*7.db")
    p.add_argument("--selection-start", default="2025-07-07")
    p.add_argument("--selection-end", default="2025-12-31")
    p.add_argument("--holdout-start", default="2026-01-01")
    p.add_argument("--holdout-end", default="2026-05-30")
    p.add_argument("--a-weight", type=float, default=0.4)
    p.add_argument("--non-a-weight", type=float, default=1.3)
    p.add_argument("--momentum-window", type=int, default=14)
    p.add_argument("--drought-window", type=int, default=60)
    p.add_argument("--min-calendar-obs", type=int, default=8)
    p.add_argument("--bootstrap-n", type=int, default=4000)
    p.add_argument("--seed", type=int, default=20260601)
    p.add_argument("--output-prefix", default="db/experiments/signal_existence_plan")
    return p


def _bootstrap_mean_ci(values: np.ndarray, *, n_boot: int, seed: int, alpha: float = 0.05) -> tuple[float, float]:
    vals = np.asarray(values, dtype=float)
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    boots = np.empty(n_boot, dtype=float)
    n = vals.size
    for i in range(n_boot):
        sample = vals[rng.integers(0, n, size=n)]
        boots[i] = float(np.mean(sample))
    lo = float(np.quantile(boots, alpha / 2.0))
    hi = float(np.quantile(boots, 1.0 - alpha / 2.0))
    return lo, hi


def _min_detectable_precision(
    *,
    n_days: int,
    p0: float = RANDOM_PRECISION2_BASELINE,
    alpha: float = 0.05,
    power: float = 0.8,
) -> float:
    # precision@2 を2*n_daysのBernoulliとみなした正規近似
    n = max(1, int(2 * n_days))
    z_alpha = float(norm.ppf(1.0 - alpha / 2.0))
    z_beta = float(norm.ppf(power))
    grid = np.linspace(p0, 0.8, 3001)
    term0 = z_alpha * np.sqrt(p0 * (1.0 - p0) / n)
    for p1 in grid:
        term1 = z_beta * np.sqrt(p1 * (1.0 - p1) / n)
        if (p1 - p0) >= (term0 + term1):
            return float(p1)
    return float(grid[-1])


def _load_dataset(args: argparse.Namespace) -> tuple[pd.DataFrame, Path]:
    db_path = resolve_db_path(str(args.db_path), pattern=str(args.db_glob))
    raw = build_base_rows(db_path=db_path, a_weight=float(args.a_weight), non_a_weight=float(args.non_a_weight))
    agg = aggregate_mode(raw, mode="floor_atype4").copy()
    agg["date"] = pd.to_datetime(agg["date"])
    agg["expert"] = agg["group_key"].astype(str)
    agg["last_digit"] = agg["last_digit"].astype(str)
    agg["total_diff_coins"] = pd.to_numeric(agg["total_diff_coins"], errors="coerce").fillna(0.0)
    agg = agg[agg["expert"].isin(EXPERTS)].copy()
    agg = agg.sort_values(["expert", "date", "last_digit"]).reset_index(drop=True)
    rank_desc = agg.groupby(["expert", "date"], sort=False)["total_diff_coins"].rank(method="first", ascending=False)
    agg["rank"] = pd.to_numeric(rank_desc, errors="coerce").fillna(999).astype(int)
    agg["is_top1"] = (agg["rank"] == 1).astype(int)
    agg["is_top2"] = (agg["rank"] <= 2).astype(int)
    agg["is_positive"] = (agg["total_diff_coins"] > 0.0).astype(int)
    agg["dd"] = agg["date"].dt.day.astype(int)
    agg["weekday"] = agg["date"].dt.weekday.astype(int)
    return agg, db_path


def _split_ranges(df: pd.DataFrame, args: argparse.Namespace) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    selection_start = pd.Timestamp(str(args.selection_start))
    selection_end = pd.Timestamp(str(args.selection_end))
    holdout_start = pd.Timestamp(str(args.holdout_start))
    holdout_end = min(pd.Timestamp(str(args.holdout_end)), pd.to_datetime(df["date"]).max())
    return selection_start, selection_end, holdout_start, holdout_end


def _phase1_autocorr(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for expert in ("ALL", *EXPERTS):
        use = df if expert == "ALL" else df[df["expert"] == expert]
        for lag in LAGS:
            x_all: list[float] = []
            y_all: list[float] = []
            t_all: list[float] = []
            pt_all: list[float] = []
            for (_, digit), g in use.groupby(["expert", "last_digit"], sort=False):
                g = g.sort_values("date")
                rank_vals = pd.to_numeric(g["rank"], errors="coerce")
                top1_vals = pd.to_numeric(g["is_top1"], errors="coerce")
                pos_vals = pd.to_numeric(g["is_positive"], errors="coerce")
                prev_rank = rank_vals.shift(lag)
                prev_top1 = top1_vals.shift(lag)
                prev_pos = pos_vals.shift(lag)
                m_rank = prev_rank.notna() & rank_vals.notna()
                m_top1 = prev_top1.notna() & top1_vals.notna()
                m_pos = prev_pos.notna() & pos_vals.notna()
                x_all.extend(prev_rank[m_rank].tolist())
                y_all.extend(rank_vals[m_rank].tolist())
                t_all.extend(prev_top1[m_top1].tolist())
                pt_all.extend(top1_vals[m_top1].tolist())
                if m_pos.any():
                    rho_pos, p_pos = spearmanr(prev_pos[m_pos], pos_vals[m_pos])
                else:
                    rho_pos, p_pos = np.nan, np.nan
                rows.append(
                    {
                        "scope": "digitwise",
                        "expert": expert,
                        "lag": lag,
                        "metric": "is_positive_spearman",
                        "rho": float(rho_pos) if np.isfinite(rho_pos) else np.nan,
                        "p_value": float(p_pos) if np.isfinite(p_pos) else np.nan,
                        "n": int(m_pos.sum()),
                        "digit": str(digit),
                    }
                )
            if x_all:
                rho_rank, p_rank = spearmanr(x_all, y_all)
            else:
                rho_rank, p_rank = np.nan, np.nan
            if t_all:
                rho_top1, p_top1 = spearmanr(t_all, pt_all)
            else:
                rho_top1, p_top1 = np.nan, np.nan
            rows.append(
                {
                    "scope": "pooled",
                    "expert": expert,
                    "lag": lag,
                    "metric": "rank_spearman",
                    "rho": float(rho_rank) if np.isfinite(rho_rank) else np.nan,
                    "p_value": float(p_rank) if np.isfinite(p_rank) else np.nan,
                    "n": int(len(x_all)),
                    "digit": "",
                }
            )
            rows.append(
                {
                    "scope": "pooled",
                    "expert": expert,
                    "lag": lag,
                    "metric": "top1_spearman",
                    "rho": float(rho_top1) if np.isfinite(rho_top1) else np.nan,
                    "p_value": float(p_top1) if np.isfinite(p_top1) else np.nan,
                    "n": int(len(t_all)),
                    "digit": "",
                }
            )
    return pd.DataFrame(rows)


def _phase1_repeat_avoidance(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for expert in ("ALL", *EXPERTS):
        use = df if expert == "ALL" else df[df["expert"] == expert]
        a = b = c = d = 0
        for (_, digit), g in use.groupby(["expert", "last_digit"], sort=False):
            g = g.sort_values("date")
            cur = pd.to_numeric(g["is_top1"], errors="coerce").fillna(0).astype(int)
            prev = cur.shift(1)
            m = prev.notna()
            if not m.any():
                continue
            pv = prev[m].astype(int)
            cv = cur[m].astype(int)
            a += int(((pv == 1) & (cv == 1)).sum())
            b += int(((pv == 1) & (cv == 0)).sum())
            c += int(((pv == 0) & (cv == 1)).sum())
            d += int(((pv == 0) & (cv == 0)).sum())
        table = np.array([[a, b], [c, d]], dtype=int)
        odds, p_less = fisher_exact(table, alternative="less")
        p_cond = (a / (a + b)) if (a + b) > 0 else np.nan
        p_base = ((a + c) / (a + b + c + d)) if (a + b + c + d) > 0 else np.nan
        rows.append(
            {
                "expert": expert,
                "test": "fisher_conditional_top1",
                "a_prev1_today1": a,
                "b_prev1_today0": b,
                "c_prev0_today1": c,
                "d_prev0_today0": d,
                "p_top1_next_given_top1_prev": p_cond,
                "p_top1_base": p_base,
                "odds_ratio": float(odds),
                "p_value_less": float(p_less),
            }
        )

        top1_daily = (
            use[use["is_top1"] == 1]
            .sort_values(["expert", "date"])
            .groupby(["expert", "date"], sort=False)["last_digit"]
            .first()
            .reset_index()
            .sort_values(["expert", "date"])
        )
        rep = (
            top1_daily.groupby("expert", sort=False)["last_digit"]
            .apply(lambda s: s.eq(s.shift(1)))
            .reset_index(level=0, drop=True)
        )
        n = int(rep.iloc[1:].shape[0]) if len(rep) > 1 else 0
        k = int(rep.iloc[1:].sum()) if len(rep) > 1 else 0
        if n > 0:
            bt = binomtest(k, n=n, p=0.1, alternative="less")
            rep_rate = k / n
            p_rep = float(bt.pvalue)
        else:
            rep_rate = np.nan
            p_rep = np.nan
        rows.append(
            {
                "expert": expert,
                "test": "binom_repeat_rate",
                "n_transitions": n,
                "k_repeat": k,
                "repeat_rate": rep_rate,
                "random_repeat_base": 0.1,
                "p_value_less": p_rep,
            }
        )
    return pd.DataFrame(rows)


def _phase1_calendar_digit(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for expert in EXPERTS:
        use = df[df["expert"] == expert].copy()
        n_tests = 31 * 10
        for dd in range(1, 32):
            dd_use = use[use["dd"] == dd]
            if dd_use.empty:
                continue
            for digit in sorted(use["last_digit"].unique()):
                part = dd_use[dd_use["last_digit"] == digit]
                n = int(len(part))
                k = int(part["is_top2"].sum())
                if n <= 0:
                    continue
                p_hat = float(k / n)
                bt = binomtest(k, n=n, p=RANDOM_PRECISION2_BASELINE, alternative="two-sided")
                p_raw = float(bt.pvalue)
                p_bonf = min(1.0, p_raw * n_tests)
                rows.append(
                    {
                        "expert": expert,
                        "dd": dd,
                        "last_digit": str(digit),
                        "n_days": n,
                        "top2_rate": p_hat,
                        "base_rate": RANDOM_PRECISION2_BASELINE,
                        "lift": (p_hat / RANDOM_PRECISION2_BASELINE) if RANDOM_PRECISION2_BASELINE > 0 else np.nan,
                        "p_value_raw": p_raw,
                        "p_value_bonferroni": p_bonf,
                        "is_significant_bonf": int(p_bonf < 0.05),
                    }
                )
    return pd.DataFrame(rows)


def _fixed_tables(selection_df: pd.DataFrame) -> tuple[dict[str, pd.Series], dict[str, pd.DataFrame]]:
    global_rates: dict[str, pd.Series] = {}
    calendar_rates: dict[str, pd.DataFrame] = {}
    for expert, g in selection_df.groupby("expert", sort=False):
        global_rates[str(expert)] = (
            g.groupby("last_digit", sort=False)["is_top1"].mean().sort_values(ascending=False)
        )
        cal = (
            g.groupby(["dd", "weekday", "last_digit"], sort=False)["is_top1"]
            .mean()
            .reset_index()
            .rename(columns={"is_top1": "rate"})
        )
        calendar_rates[str(expert)] = cal
    return global_rates, calendar_rates


def _top2_from_scores(scores: pd.Series) -> tuple[str, str]:
    if scores.empty:
        return "", ""
    s = scores.sort_values(ascending=False)
    if len(s) == 1:
        return str(s.index[0]), str(s.index[0])
    return str(s.index[0]), str(s.index[1])


def _seed_for(rule: str, expert: str, date: pd.Timestamp, base_seed: int) -> int:
    key = f"{rule}|{expert}|{date.date()}|{base_seed}".encode("utf-8")
    return int(hashlib.sha256(key).hexdigest()[:16], 16) % (2**32 - 1)


def _predict_rule(
    *,
    rule: str,
    hist: pd.DataFrame,
    selection_global: pd.Series,
    selection_calendar: pd.DataFrame,
    current_date: pd.Timestamp,
    digits: list[str],
    momentum_window: int,
    drought_window: int,
    min_calendar_obs: int,
    seed: int,
    expert: str,
) -> RulePrediction:
    if rule == "random":
        rng = np.random.default_rng(_seed_for(rule, expert, current_date, seed))
        pick = rng.choice(np.array(digits, dtype=object), size=2, replace=False)
        return RulePrediction(rule=rule, top1=str(pick[0]), top2=str(pick[1]), source="random")

    if rule == "global_fixed":
        p1, p2 = _top2_from_scores(selection_global.reindex(digits).fillna(0.0))
        return RulePrediction(rule=rule, top1=p1, top2=p2, source="selection_global")

    if rule == "calendar_fixed":
        dd = int(current_date.day)
        wd = int(current_date.weekday())
        cal = selection_calendar[(selection_calendar["dd"] == dd) & (selection_calendar["weekday"] == wd)].copy()
        if len(cal) >= int(min_calendar_obs):
            ser = cal.set_index("last_digit")["rate"].reindex(digits).fillna(0.0)
            p1, p2 = _top2_from_scores(ser)
            return RulePrediction(rule=rule, top1=p1, top2=p2, source="selection_calendar")
        p1, p2 = _top2_from_scores(selection_global.reindex(digits).fillna(0.0))
        return RulePrediction(rule=rule, top1=p1, top2=p2, source="selection_global_fallback")

    hist = hist.sort_values("date").copy()
    base = hist.groupby("last_digit", sort=False)["is_top1"].mean().reindex(digits).fillna(0.0)

    if rule == "anti_repeat":
        prev_day = hist["date"].max()
        prev_top1 = (
            hist[(hist["date"] == prev_day) & (hist["is_top1"] == 1)]["last_digit"].astype(str).iloc[0]
            if hist["date"].notna().any()
            else ""
        )
        score = base.copy()
        if prev_top1 in score.index:
            score.loc[prev_top1] = -1e9
        p1, p2 = _top2_from_scores(score)
        return RulePrediction(rule=rule, top1=p1, top2=p2, source=f"exclude_prev_top1={prev_top1}")

    if rule == "momentum":
        recent_start = current_date - pd.Timedelta(days=max(1, int(momentum_window)))
        recent = hist[hist["date"] >= recent_start]
        score = recent.groupby("last_digit", sort=False)["is_top1"].sum().reindex(digits).fillna(0.0)
        if float(score.sum()) <= 0.0:
            score = base.copy()
        p1, p2 = _top2_from_scores(score)
        return RulePrediction(rule=rule, top1=p1, top2=p2, source=f"recent_{momentum_window}d")

    if rule == "drought_abs":
        top1_rows = hist[hist["is_top1"] == 1][["date", "last_digit"]].copy()
        last_seen = top1_rows.groupby("last_digit", sort=False)["date"].max().to_dict()
        drought = pd.Series(index=digits, dtype=float)
        for d in digits:
            dt = last_seen.get(d)
            drought.loc[d] = 9999.0 if dt is None else float((current_date - pd.Timestamp(dt)).days)
        p1, p2 = _top2_from_scores(drought)
        return RulePrediction(rule=rule, top1=p1, top2=p2, source="days_since_top1")

    if rule == "drought_relative":
        recent_start = current_date - pd.Timedelta(days=max(1, int(drought_window)))
        recent = hist[hist["date"] >= recent_start]
        days = max(1, int(recent["date"].nunique()))
        observed = recent.groupby("last_digit", sort=False)["is_top1"].sum().reindex(digits).fillna(0.0)
        expected = float(days) * 0.1
        deficit = expected - observed
        top1_rows = hist[hist["is_top1"] == 1][["date", "last_digit"]].copy()
        last_seen = top1_rows.groupby("last_digit", sort=False)["date"].max().to_dict()
        tie = pd.Series(index=digits, dtype=float)
        for d in digits:
            dt = last_seen.get(d)
            tie.loc[d] = 9999.0 if dt is None else float((current_date - pd.Timestamp(dt)).days)
        score = deficit + (tie / 10000.0)
        p1, p2 = _top2_from_scores(score)
        return RulePrediction(rule=rule, top1=p1, top2=p2, source=f"deficit_{drought_window}d")

    raise ValueError(f"Unknown rule: {rule}")


def _phase2_stability(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for expert in EXPERTS:
        use = df[df["expert"] == expert].copy()
        dates = sorted(pd.to_datetime(use["date"]).unique())
        if len(dates) < 100:
            continue
        for start_i in range(0, len(dates) - 89, 30):
            w_start = pd.Timestamp(dates[start_i])
            w_end = pd.Timestamp(dates[start_i + 89])
            w = use[(use["date"] >= w_start) & (use["date"] <= w_end)].copy()
            top1_daily = (
                w[w["is_top1"] == 1]
                .sort_values("date")
                .groupby("date", sort=False)["last_digit"]
                .first()
                .reset_index()
                .sort_values("date")
            )
            repeat = top1_daily["last_digit"].eq(top1_daily["last_digit"].shift(1)).iloc[1:]
            repeat_rate = float(repeat.mean()) if len(repeat) > 0 else np.nan
            rows.append(
                {
                    "expert": expert,
                    "window_start": str(w_start.date()),
                    "window_end": str(w_end.date()),
                    "n_days": int(w["date"].nunique()),
                    "repeat_rate": repeat_rate,
                    "random_repeat_base": 0.1,
                    "repeat_rate_minus_base": (repeat_rate - 0.1) if np.isfinite(repeat_rate) else np.nan,
                }
            )
    return pd.DataFrame(rows)


def _phase3_rules(
    *,
    full_df: pd.DataFrame,
    selection_df: pd.DataFrame,
    holdout_df: pd.DataFrame,
    args: argparse.Namespace,
) -> pd.DataFrame:
    digits = sorted(full_df["last_digit"].astype(str).unique().tolist())
    global_rates, calendar_rates = _fixed_tables(selection_df)
    rows: list[dict[str, Any]] = []
    for expert in EXPERTS:
        ex_all = full_df[full_df["expert"] == expert].copy().sort_values("date")
        ex_hold = holdout_df[holdout_df["expert"] == expert].copy().sort_values("date")
        if ex_hold.empty:
            continue
        for dt in sorted(pd.to_datetime(ex_hold["date"]).unique()):
            day = ex_hold[ex_hold["date"] == dt].copy()
            hist = ex_all[ex_all["date"] < dt].copy()
            if hist.empty:
                continue
            actual_top2 = set(day.sort_values(["total_diff_coins", "last_digit"], ascending=[False, True]).head(2)["last_digit"].astype(str))
            day_map = day.set_index("last_digit")["total_diff_coins"].to_dict()
            for rule in RULES:
                pred = _predict_rule(
                    rule=rule,
                    hist=hist,
                    selection_global=global_rates.get(expert, pd.Series(dtype=float)),
                    selection_calendar=calendar_rates.get(expert, pd.DataFrame(columns=["dd", "weekday", "last_digit", "rate"])),
                    current_date=pd.Timestamp(dt),
                    digits=digits,
                    momentum_window=int(args.momentum_window),
                    drought_window=int(args.drought_window),
                    min_calendar_obs=int(args.min_calendar_obs),
                    seed=int(args.seed),
                    expert=expert,
                )
                pred_pair = [pred.top1, pred.top2]
                hit_count = int(sum(1 for d in pred_pair if d in actual_top2))
                p1_diff = float(day_map.get(pred.top1, np.nan))
                p2_diff = float(day_map.get(pred.top2, np.nan))
                rows.append(
                    {
                        "date": pd.Timestamp(dt).strftime("%Y-%m-%d"),
                        "expert": expert,
                        "rule": rule,
                        "source": pred.source,
                        "pred_top1": pred.top1,
                        "pred_top2": pred.top2,
                        "actual_top2": ",".join(sorted(actual_top2)),
                        "hit_count": hit_count,
                        "precision_at_2": float(hit_count / 2.0),
                        "hit_at_2": float(hit_count >= 1),
                        "operational_pick_actual_raw_diff": p1_diff,
                        "pred_top2_avg_actual_raw_diff": float(np.nanmean([p1_diff, p2_diff])),
                        "pred_top1_minus_top2_actual_diff": float(p1_diff - p2_diff) if np.isfinite(p1_diff) and np.isfinite(p2_diff) else np.nan,
                        "pred_top1_in_actual_top2": int(pred.top1 in actual_top2),
                    }
                )
    return pd.DataFrame(rows).sort_values(["date", "expert", "rule"]).reset_index(drop=True)


def _phase3_summary(df_rule_daily: pd.DataFrame, *, n_boot: int, seed: int) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if df_rule_daily.empty:
        return pd.DataFrame()
    for expert in ("ALL", *EXPERTS):
        use_ex = df_rule_daily if expert == "ALL" else df_rule_daily[df_rule_daily["expert"] == expert]
        for rule, g in use_ex.groupby("rule", sort=False):
            p = pd.to_numeric(g["precision_at_2"], errors="coerce").to_numpy(dtype=float)
            h = pd.to_numeric(g["hit_at_2"], errors="coerce").to_numpy(dtype=float)
            op = pd.to_numeric(g["operational_pick_actual_raw_diff"], errors="coerce").to_numpy(dtype=float)
            p_lo, p_hi = _bootstrap_mean_ci(p, n_boot=n_boot, seed=seed + 11)
            h_lo, h_hi = _bootstrap_mean_ci(h, n_boot=n_boot, seed=seed + 22)
            op_lo, op_hi = _bootstrap_mean_ci(op, n_boot=n_boot, seed=seed + 33)
            rows.append(
                {
                    "expert": expert,
                    "rule": str(rule),
                    "n_days": int(len(g)),
                    "precision_at_2_mean": float(np.nanmean(p)),
                    "precision_at_2_ci_low": p_lo,
                    "precision_at_2_ci_high": p_hi,
                    "precision_lift_vs_random": float(np.nanmean(p) - RANDOM_PRECISION2_BASELINE),
                    "hit_at_2_mean": float(np.nanmean(h)),
                    "hit_at_2_ci_low": h_lo,
                    "hit_at_2_ci_high": h_hi,
                    "hit_lift_vs_random": float(np.nanmean(h) - RANDOM_HIT2_BASELINE),
                    "operational_pick_actual_raw_diff_mean": float(np.nanmean(op)),
                    "operational_pick_ci_low": op_lo,
                    "operational_pick_ci_high": op_hi,
                }
            )
    return pd.DataFrame(rows).sort_values(["expert", "precision_at_2_mean"], ascending=[True, False]).reset_index(drop=True)


def _phase4_power(holdout_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for expert in EXPERTS:
        n_days = int(holdout_df[holdout_df["expert"] == expert]["date"].nunique())
        p1 = _min_detectable_precision(n_days=n_days)
        rows.append(
            {
                "expert": expert,
                "holdout_days": n_days,
                "random_precision_base": RANDOM_PRECISION2_BASELINE,
                "min_detectable_precision_80pct_power": p1,
                "min_detectable_lift_points": float((p1 - RANDOM_PRECISION2_BASELINE) * 100.0),
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    args = build_parser().parse_args()
    out_prefix = Path(str(args.output_prefix))
    out_prefix.parent.mkdir(parents=True, exist_ok=True)

    df, db_path = _load_dataset(args)
    sel_s, sel_e, ho_s, ho_e = _split_ranges(df, args)
    selection_df = df[(df["date"] >= sel_s) & (df["date"] <= sel_e)].copy()
    holdout_df = df[(df["date"] >= ho_s) & (df["date"] <= ho_e)].copy()

    phase1_autocorr = _phase1_autocorr(df)
    phase1_repeat = _phase1_repeat_avoidance(df)
    phase1_calendar = _phase1_calendar_digit(df)
    phase2_stability = _phase2_stability(df)
    phase3_daily = _phase3_rules(full_df=df, selection_df=selection_df, holdout_df=holdout_df, args=args)
    phase3_summary = _phase3_summary(phase3_daily, n_boot=int(args.bootstrap_n), seed=int(args.seed))
    phase4_power = _phase4_power(holdout_df)

    out_autocorr = out_prefix.with_name(out_prefix.name + "_phase1_autocorr.csv")
    out_repeat = out_prefix.with_name(out_prefix.name + "_phase1_repeat_avoidance.csv")
    out_calendar = out_prefix.with_name(out_prefix.name + "_phase1_calendar_dd_digit.csv")
    out_stability = out_prefix.with_name(out_prefix.name + "_phase2_stability.csv")
    out_rule_daily = out_prefix.with_name(out_prefix.name + "_phase3_rule_daily.csv")
    out_rule_summary = out_prefix.with_name(out_prefix.name + "_phase3_rule_summary.csv")
    out_power = out_prefix.with_name(out_prefix.name + "_phase4_power.csv")
    out_json = out_prefix.with_name(out_prefix.name + "_summary.json")

    phase1_autocorr.to_csv(out_autocorr, index=False, encoding="utf-8-sig")
    phase1_repeat.to_csv(out_repeat, index=False, encoding="utf-8-sig")
    phase1_calendar.to_csv(out_calendar, index=False, encoding="utf-8-sig")
    phase2_stability.to_csv(out_stability, index=False, encoding="utf-8-sig")
    phase3_daily.to_csv(out_rule_daily, index=False, encoding="utf-8-sig")
    phase3_summary.to_csv(out_rule_summary, index=False, encoding="utf-8-sig")
    phase4_power.to_csv(out_power, index=False, encoding="utf-8-sig")

    summary = {
        "db_path": str(db_path),
        "selection_range": {"start": str(sel_s.date()), "end": str(sel_e.date())},
        "holdout_range": {"start": str(ho_s.date()), "end": str(ho_e.date())},
        "n_days_total": int(df["date"].nunique()),
        "n_days_selection": int(selection_df["date"].nunique()),
        "n_days_holdout": int(holdout_df["date"].nunique()),
        "random_baseline": {
            "precision_at_2": RANDOM_PRECISION2_BASELINE,
            "hit_at_2": RANDOM_HIT2_BASELINE,
        },
        "files": {
            "phase1_autocorr": str(out_autocorr),
            "phase1_repeat_avoidance": str(out_repeat),
            "phase1_calendar_dd_digit": str(out_calendar),
            "phase2_stability": str(out_stability),
            "phase3_rule_daily": str(out_rule_daily),
            "phase3_rule_summary": str(out_rule_summary),
            "phase4_power": str(out_power),
        },
    }
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[OK] saved: {out_autocorr}")
    print(f"[OK] saved: {out_repeat}")
    print(f"[OK] saved: {out_calendar}")
    print(f"[OK] saved: {out_stability}")
    print(f"[OK] saved: {out_rule_daily}")
    print(f"[OK] saved: {out_rule_summary}")
    print(f"[OK] saved: {out_power}")
    print(f"[OK] saved: {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

