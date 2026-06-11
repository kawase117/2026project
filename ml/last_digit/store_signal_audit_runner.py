from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import binomtest, f_oneway, fisher_exact, spearmanr


RANDOM_PRECISION2_BASELINE = 0.2
RANDOM_HIT2_BASELINE = 1.0 - (28.0 / 45.0)
DEFAULT_RULES = (
    "random",
    "global_fixed",
    "calendar_fixed",
    "anti_repeat",
    "drought_abs",
    "drought_relative",
    "momentum",
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Unified per-store signal audit runner.")
    p.add_argument("--db-dir", default="db")
    p.add_argument("--db-glob", default="*.db")
    p.add_argument("--exclude-db", default="integrated.db", help="Comma-separated DB names to exclude.")
    p.add_argument("--modes", default="global11,type2")
    p.add_argument(
        "--label-focus-modes",
        default="global11,type2",
        help="Modes treated as primary coarse-scan evidence for labels/focus outputs.",
    )
    p.add_argument("--selection-start", default="2025-07-07")
    p.add_argument("--selection-end", default="2025-12-31")
    p.add_argument("--holdout-start", default="2026-01-01")
    p.add_argument("--holdout-end", default="2026-05-30")
    p.add_argument("--cycle-lags", default="1,2,3,5,7,10,14,21,28")
    p.add_argument("--momentum-window", type=int, default=14)
    p.add_argument("--drought-window", type=int, default=60)
    p.add_argument("--min-calendar-obs", type=int, default=8)
    p.add_argument("--min-floor-coverage", type=float, default=0.8, help="Min 2F/3F coverage for floor modes.")
    p.add_argument("--seed", type=int, default=20260601)
    p.add_argument("--output-root", default="db/experiments/store_signal_audit_20260601")
    p.add_argument("--timing-p-threshold", type=float, default=0.05, help="Threshold for Timing Only label.")
    p.add_argument("--timing-min-uplift", type=float, default=0.0, help="Min holdout uplift for Timing Only label.")
    p.add_argument("--cycle-min-sig", type=int, default=1, help="Min cycle_sig_count_fdr_global for Weak Cycle label.")
    p.add_argument("--cycle-min-uplift", type=float, default=0.0, help="Min holdout uplift for Weak Cycle label.")
    return p


def _parse_csv_strs(raw: str) -> list[str]:
    return [x.strip() for x in str(raw).split(",") if x.strip()]


def _parse_csv_ints(raw: str) -> list[int]:
    out: list[int] = []
    for x in str(raw).split(","):
        s = x.strip()
        if s:
            out.append(int(s))
    return out


def _normalize_last_digit(x: Any) -> str:
    s = str(x)
    if s in {"11", "ゾロ目", "・ｿ・橸ｾ帷岼", "縺槭ｍ逶ｮ"}:
        return "ゾロ目"
    return s


def _compute_is_a_type(df: pd.DataFrame) -> pd.Series:
    return (
        (pd.to_numeric(df.get("jug_flag", 0), errors="coerce").fillna(0).astype(int) == 1)
        | (pd.to_numeric(df.get("hana_flag", 0), errors="coerce").fillna(0).astype(int) == 1)
        | (pd.to_numeric(df.get("oki_flag", 0), errors="coerce").fillna(0).astype(int) == 1)
        | (pd.to_numeric(df.get("bt_flag", 0), errors="coerce").fillna(0).astype(int) == 1)
    ).astype(int)


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
    back = np.empty(n, dtype=float)
    back[order] = q
    out[ok] = back
    return out


def _seed_for(parts: list[str], base_seed: int) -> int:
    key = "|".join(parts + [str(base_seed)]).encode("utf-8")
    return int(hashlib.sha256(key).hexdigest()[:16], 16) % (2**32 - 1)


def _load_store_raw(db_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    con = sqlite3.connect(str(db_path))
    q_machine = """
    SELECT
      m.date,
      m.machine_number,
      m.machine_name,
      m.last_digit,
      m.games_normalized,
      m.diff_coins_normalized,
      mm.machine_name_normalized AS mm_hit_key,
      COALESCE(mm.jug_flag, 0) AS jug_flag,
      COALESCE(mm.hana_flag, 0) AS hana_flag,
      COALESCE(mm.oki_flag, 0) AS oki_flag,
      COALESCE(mm.bt_flag, 0) AS bt_flag,
      COALESCE(dh.is_any_event, 0) AS is_any_event
    FROM machine_detailed_results m
    LEFT JOIN machine_master mm
      ON m.machine_name = mm.machine_name_normalized
    LEFT JOIN daily_hall_summary dh
      ON m.date = dh.date
    """
    q_hall = """
    SELECT
      date,
      avg_diff_per_machine,
      avg_games_per_machine,
      total_machines,
      win_rate,
      COALESCE(is_any_event, 0) AS is_any_event
    FROM daily_hall_summary
    ORDER BY date
    """
    machine = pd.read_sql_query(q_machine, con)
    hall = pd.read_sql_query(q_hall, con)
    con.close()
    if machine.empty:
        raise ValueError(f"{db_path.name}: machine_detailed_results empty")
    if hall.empty:
        raise ValueError(f"{db_path.name}: daily_hall_summary empty")

    machine["date"] = pd.to_datetime(machine["date"], format="%Y%m%d", errors="coerce")
    machine = machine[machine["date"].notna()].copy()
    machine["machine_number"] = pd.to_numeric(machine["machine_number"], errors="coerce")
    machine = machine[machine["machine_number"].notna()].copy()
    machine["machine_number"] = machine["machine_number"].astype(int)
    machine["last_digit"] = machine["last_digit"].map(_normalize_last_digit)
    machine["diff_coins_normalized"] = pd.to_numeric(machine["diff_coins_normalized"], errors="coerce").fillna(0.0)
    machine["games_normalized"] = pd.to_numeric(machine["games_normalized"], errors="coerce").fillna(0.0)
    machine["mm_join_hit"] = machine["mm_hit_key"].notna().astype(int)
    machine["is_a_type"] = _compute_is_a_type(machine)
    machine["atype_bucket"] = np.where(machine["is_a_type"] == 1, "A", "N")
    machine["floor_head"] = machine["machine_number"].astype(str).str[0]
    machine["floor_bucket"] = np.where(machine["floor_head"].isin(["2", "3"]), machine["floor_head"] + "F", "UNK")
    machine["expert"] = machine["floor_bucket"] + "_" + machine["atype_bucket"]

    hall["date"] = pd.to_datetime(hall["date"], format="%Y%m%d", errors="coerce")
    hall = hall[hall["date"].notna()].copy()
    for col in ("avg_diff_per_machine", "avg_games_per_machine", "total_machines", "win_rate"):
        hall[col] = pd.to_numeric(hall[col], errors="coerce").fillna(0.0)
    hall["is_any_event"] = pd.to_numeric(hall["is_any_event"], errors="coerce").fillna(0).astype(int)
    hall["weekday"] = hall["date"].dt.weekday.astype(int)
    hall["dd"] = hall["date"].dt.day.astype(int)
    hall["mm"] = hall["date"].dt.month.astype(int)
    hall["is_positive_day"] = (hall["avg_diff_per_machine"] > 0.0).astype(int)
    hall["is_zorome_day"] = hall["dd"].isin([11, 22]).astype(int)
    hall["is_strong_zorome_day"] = (hall["dd"] == hall["mm"]).astype(int)
    hall["is_day_7x"] = hall["dd"].isin([7, 17, 27]).astype(int)
    hall["is_day_1x"] = hall["dd"].isin([1, 11, 21, 31]).astype(int)
    return machine, hall.sort_values("date").reset_index(drop=True)


def _mode_applicability(machine: pd.DataFrame, min_floor_coverage: float) -> pd.DataFrame:
    n = float(len(machine))
    floor_cov = float((machine["floor_bucket"] != "UNK").mean()) if n > 0 else 0.0
    has_2f = bool((machine["floor_bucket"] == "2F").any())
    has_3f = bool((machine["floor_bucket"] == "3F").any())
    type_n = int(machine["atype_bucket"].nunique())
    rows = [
        {
            "mode": "global11",
            "is_applicable": 1,
            "reason": "always",
        },
        {
            "mode": "type2",
            "is_applicable": int(type_n >= 2),
            "reason": f"atype_unique={type_n}",
        },
        {
            "mode": "floor2",
            "is_applicable": int((floor_cov >= float(min_floor_coverage)) and has_2f and has_3f),
            "reason": f"floor_cov={floor_cov:.3f},has_2f={int(has_2f)},has_3f={int(has_3f)}",
        },
        {
            "mode": "floor_atype4",
            "is_applicable": int((floor_cov >= float(min_floor_coverage)) and has_2f and has_3f and type_n >= 2),
            "reason": f"floor_cov={floor_cov:.3f},atype_unique={type_n}",
        },
    ]
    return pd.DataFrame(rows)


def _aggregate_mode(machine: pd.DataFrame, mode: str) -> pd.DataFrame:
    df = machine.copy()
    if mode == "global11":
        df["group_key"] = "ALL"
    elif mode == "type2":
        df["group_key"] = df["atype_bucket"].astype(str)
    elif mode == "floor2":
        df = df[df["floor_bucket"].isin(["2F", "3F"])].copy()
        df["group_key"] = df["floor_bucket"].astype(str)
    elif mode == "floor_atype4":
        df = df[df["floor_bucket"].isin(["2F", "3F"])].copy()
        df["group_key"] = df["floor_bucket"].astype(str) + "_" + df["atype_bucket"].astype(str)
    else:
        raise ValueError(f"Unsupported mode: {mode}")
    if df.empty:
        return pd.DataFrame()
    agg = (
        df.groupby(["date", "group_key", "last_digit"], sort=True)
        .agg(
            total_diff_coins=("diff_coins_normalized", "sum"),
            machine_count=("machine_number", "count"),
            is_any_event=("is_any_event", "max"),
            mm_join_hit_rate=("mm_join_hit", "mean"),
        )
        .reset_index()
    )
    agg["date"] = pd.to_datetime(agg["date"])
    agg["last_digit"] = agg["last_digit"].astype(str)
    agg["rank"] = (
        agg.groupby(["group_key", "date"], sort=False)["total_diff_coins"]
        .rank(method="first", ascending=False)
        .astype(int)
    )
    agg["is_top1"] = (agg["rank"] == 1).astype(int)
    agg["is_top2"] = (agg["rank"] <= 2).astype(int)
    agg["is_positive"] = (agg["total_diff_coins"] > 0.0).astype(int)
    agg["dd"] = agg["date"].dt.day.astype(int)
    agg["weekday"] = agg["date"].dt.weekday.astype(int)
    return agg.sort_values(["group_key", "date", "last_digit"]).reset_index(drop=True)


def _phase1_autocorr(agg: pd.DataFrame, lags: list[int]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for group_key, g0 in agg.groupby("group_key", sort=False):
        for lag in lags:
            x_rank: list[float] = []
            y_rank: list[float] = []
            x_top1: list[float] = []
            y_top1: list[float] = []
            x_pos: list[float] = []
            y_pos: list[float] = []
            for _, g in g0.groupby("last_digit", sort=False):
                g = g.sort_values("date")
                rank = pd.to_numeric(g["rank"], errors="coerce")
                top1 = pd.to_numeric(g["is_top1"], errors="coerce")
                pos = pd.to_numeric(g["is_positive"], errors="coerce")
                r_prev = rank.shift(lag)
                t_prev = top1.shift(lag)
                p_prev = pos.shift(lag)
                m_r = r_prev.notna() & rank.notna()
                m_t = t_prev.notna() & top1.notna()
                m_p = p_prev.notna() & pos.notna()
                x_rank.extend(r_prev[m_r].tolist())
                y_rank.extend(rank[m_r].tolist())
                x_top1.extend(t_prev[m_t].tolist())
                y_top1.extend(top1[m_t].tolist())
                x_pos.extend(p_prev[m_p].tolist())
                y_pos.extend(pos[m_p].tolist())
            rr, rp = spearmanr(x_rank, y_rank) if x_rank else (np.nan, np.nan)
            tr, tp = spearmanr(x_top1, y_top1) if x_top1 else (np.nan, np.nan)
            pr, pp = spearmanr(x_pos, y_pos) if x_pos else (np.nan, np.nan)
            rows.extend(
                [
                    {"group_key": str(group_key), "lag": lag, "metric": "rank_spearman", "rho": rr, "p_value": rp, "n": len(x_rank)},
                    {"group_key": str(group_key), "lag": lag, "metric": "top1_spearman", "rho": tr, "p_value": tp, "n": len(x_top1)},
                    {"group_key": str(group_key), "lag": lag, "metric": "is_positive_spearman", "rho": pr, "p_value": pp, "n": len(x_pos)},
                ]
            )
    out = pd.DataFrame(rows)
    out["rho"] = pd.to_numeric(out["rho"], errors="coerce")
    out["p_value"] = pd.to_numeric(out["p_value"], errors="coerce")
    return out


def _phase1_repeat_avoidance(agg: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for group_key, g0 in agg.groupby("group_key", sort=False):
        a = b = c = d = 0
        for _, g in g0.groupby("last_digit", sort=False):
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
                "group_key": str(group_key),
                "test": "fisher_conditional_top1",
                "p_top1_next_given_top1_prev": p_cond,
                "p_top1_base": p_base,
                "odds_ratio": float(odds),
                "p_value_less": float(p_less),
                "a_prev1_today1": a,
                "b_prev1_today0": b,
                "c_prev0_today1": c,
                "d_prev0_today0": d,
            }
        )
        top1_daily = (
            g0[g0["is_top1"] == 1]
            .sort_values("date")
            .groupby("date", sort=False)["last_digit"]
            .first()
            .reset_index()
            .sort_values("date")
        )
        rep = top1_daily["last_digit"].eq(top1_daily["last_digit"].shift(1))
        n = int(rep.iloc[1:].shape[0]) if len(rep) > 1 else 0
        k = int(rep.iloc[1:].sum()) if len(rep) > 1 else 0
        if n > 0:
            bt = binomtest(k, n=n, p=0.1, alternative="less")
            p_rep = float(bt.pvalue)
            rr = float(k / n)
        else:
            p_rep, rr = np.nan, np.nan
        rows.append(
            {
                "group_key": str(group_key),
                "test": "binom_repeat_rate",
                "repeat_rate": rr,
                "p_value_less": p_rep,
                "n_transitions": n,
                "k_repeat": k,
            }
        )
    return pd.DataFrame(rows)


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
    store_name: str,
    group_key: str,
) -> tuple[str, str]:
    if rule == "random":
        s = _seed_for([store_name, group_key, rule, str(current_date.date())], seed)
        rng = np.random.default_rng(s)
        pick = rng.choice(np.array(digits, dtype=object), size=2, replace=False)
        return str(pick[0]), str(pick[1])

    hist = hist.sort_values("date")
    base = hist.groupby("last_digit", sort=False)["is_top1"].mean().reindex(digits).fillna(0.0)

    def top2_from(series: pd.Series) -> tuple[str, str]:
        if series.empty:
            return "", ""
        s = series.sort_values(ascending=False)
        if len(s) == 1:
            return str(s.index[0]), str(s.index[0])
        return str(s.index[0]), str(s.index[1])

    if rule == "global_fixed":
        return top2_from(selection_global.reindex(digits).fillna(0.0))

    if rule == "calendar_fixed":
        dd = int(current_date.day)
        wd = int(current_date.weekday())
        cal = selection_calendar[(selection_calendar["dd"] == dd) & (selection_calendar["weekday"] == wd)].copy()
        if len(cal) >= int(min_calendar_obs):
            ser = cal.set_index("last_digit")["rate"].reindex(digits).fillna(0.0)
            return top2_from(ser)
        return top2_from(selection_global.reindex(digits).fillna(0.0))

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
        return top2_from(score)

    if rule == "momentum":
        start = current_date - pd.Timedelta(days=max(1, int(momentum_window)))
        recent = hist[hist["date"] >= start]
        score = recent.groupby("last_digit", sort=False)["is_top1"].sum().reindex(digits).fillna(0.0)
        if float(score.sum()) <= 0:
            score = base.copy()
        return top2_from(score)

    if rule == "drought_abs":
        top1_rows = hist[hist["is_top1"] == 1][["date", "last_digit"]].copy()
        last_seen = top1_rows.groupby("last_digit", sort=False)["date"].max().to_dict()
        score = pd.Series(index=digits, dtype=float)
        for d in digits:
            dt = last_seen.get(d)
            score.loc[d] = 9999.0 if dt is None else float((current_date - pd.Timestamp(dt)).days)
        return top2_from(score)

    if rule == "drought_relative":
        start = current_date - pd.Timedelta(days=max(1, int(drought_window)))
        recent = hist[hist["date"] >= start]
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
        score = deficit + tie / 10000.0
        return top2_from(score)

    raise ValueError(f"Unknown rule: {rule}")


def _rule_eval(
    *,
    agg: pd.DataFrame,
    selection_start: pd.Timestamp,
    selection_end: pd.Timestamp,
    holdout_start: pd.Timestamp,
    holdout_end: pd.Timestamp,
    rules: tuple[str, ...],
    momentum_window: int,
    drought_window: int,
    min_calendar_obs: int,
    seed: int,
    store_name: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    sel = agg[(agg["date"] >= selection_start) & (agg["date"] <= selection_end)].copy()
    ho = agg[(agg["date"] >= holdout_start) & (agg["date"] <= holdout_end)].copy()
    daily_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    if sel.empty or ho.empty:
        return pd.DataFrame(), pd.DataFrame()

    digits = sorted(agg["last_digit"].astype(str).unique().tolist())
    for group_key, g_sel in sel.groupby("group_key", sort=False):
        g_all = agg[agg["group_key"] == group_key].copy().sort_values("date")
        g_ho = ho[ho["group_key"] == group_key].copy().sort_values("date")
        global_rates = g_sel.groupby("last_digit", sort=False)["is_top1"].mean().sort_values(ascending=False)
        cal_rates = (
            g_sel.groupby(["dd", "weekday", "last_digit"], sort=False)["is_top1"]
            .mean()
            .reset_index()
            .rename(columns={"is_top1": "rate"})
        )
        for dt in sorted(pd.to_datetime(g_ho["date"]).unique()):
            day = g_ho[g_ho["date"] == dt].copy()
            hist = g_all[g_all["date"] < dt].copy()
            if day.empty or hist.empty:
                continue
            actual_top2 = set(day.sort_values(["total_diff_coins", "last_digit"], ascending=[False, True]).head(2)["last_digit"].astype(str))
            for r in rules:
                p1, p2 = _predict_rule(
                    rule=r,
                    hist=hist,
                    selection_global=global_rates,
                    selection_calendar=cal_rates,
                    current_date=pd.Timestamp(dt),
                    digits=digits,
                    momentum_window=momentum_window,
                    drought_window=drought_window,
                    min_calendar_obs=min_calendar_obs,
                    seed=seed,
                    store_name=store_name,
                    group_key=str(group_key),
                )
                hit = int((p1 in actual_top2) + (p2 in actual_top2))
                daily_rows.append(
                    {
                        "date": pd.Timestamp(dt).strftime("%Y-%m-%d"),
                        "group_key": str(group_key),
                        "rule": r,
                        "pred_top1": p1,
                        "pred_top2": p2,
                        "hit_count": hit,
                        "precision_at_2": float(hit / 2.0),
                        "hit_at_2": float(hit >= 1),
                    }
                )
    daily = pd.DataFrame(daily_rows)
    if daily.empty:
        return daily, pd.DataFrame()
    for (group_key, rule), g in daily.groupby(["group_key", "rule"], sort=False):
        summary_rows.append(
            {
                "group_key": str(group_key),
                "rule": str(rule),
                "n_days": int(g["date"].nunique()),
                "precision_at_2_mean": float(pd.to_numeric(g["precision_at_2"], errors="coerce").mean()),
                "hit_at_2_mean": float(pd.to_numeric(g["hit_at_2"], errors="coerce").mean()),
                "precision_lift_vs_random": float(pd.to_numeric(g["precision_at_2"], errors="coerce").mean() - RANDOM_PRECISION2_BASELINE),
                "hit_lift_vs_random": float(pd.to_numeric(g["hit_at_2"], errors="coerce").mean() - RANDOM_HIT2_BASELINE),
            }
        )
    summary = pd.DataFrame(summary_rows).sort_values(["group_key", "precision_at_2_mean"], ascending=[True, False]).reset_index(drop=True)
    return daily, summary


def _cycle_tests(agg: pd.DataFrame, lags: list[int]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for group_key, g0 in agg.groupby("group_key", sort=False):
        for digit, g in g0.groupby("last_digit", sort=False):
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
                        "group_key": str(group_key),
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
    for key in out["group_key"].astype(str).drop_duplicates():
        m = out["group_key"].astype(str).eq(key).to_numpy()
        q_local[m] = _bh_fdr(out.loc[m, "p_value_raw"].to_numpy(dtype=float))
    out["p_value_fdr_bh_by_group"] = q_local
    out["is_sig_5pct_fdr_by_group"] = (pd.to_numeric(out["p_value_fdr_bh_by_group"], errors="coerce") < 0.05).astype(int)
    return out.sort_values(["p_value_raw", "rho"], ascending=[True, True]).reset_index(drop=True)


def _hall_timing_tests(hall: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    flag_rows: list[dict[str, Any]] = []
    flags = ["is_any_event", "is_zorome_day", "is_strong_zorome_day", "is_day_7x", "is_day_1x"]
    for f in flags:
        a = hall[hall[f] == 1]["avg_diff_per_machine"].to_numpy(dtype=float)
        b = hall[hall[f] == 0]["avg_diff_per_machine"].to_numpy(dtype=float)
        if len(a) >= 2 and len(b) >= 2:
            # Welch t-test fallback without import: use normal approx from means/vars.
            ma, mb = float(np.mean(a)), float(np.mean(b))
            va, vb = float(np.var(a, ddof=1)), float(np.var(b, ddof=1))
            na, nb = len(a), len(b)
            se = np.sqrt((va / na) + (vb / nb)) if na > 1 and nb > 1 else np.nan
            t_stat = (ma - mb) / se if np.isfinite(se) and se > 0 else np.nan
        else:
            t_stat = np.nan
        flag_rows.append(
            {
                "feature": f,
                "n_on": int(len(a)),
                "n_off": int(len(b)),
                "mean_on": float(np.mean(a)) if len(a) else np.nan,
                "mean_off": float(np.mean(b)) if len(b) else np.nan,
                "delta_on_minus_off": (float(np.mean(a)) - float(np.mean(b))) if len(a) and len(b) else np.nan,
                "t_stat_approx": t_stat,
            }
        )

    cat_rows: list[dict[str, Any]] = []
    for cat in ("weekday", "dd"):
        groups = [g["avg_diff_per_machine"].to_numpy(dtype=float) for _, g in hall.groupby(cat, sort=True) if len(g) >= 2]
        if len(groups) >= 2:
            f_stat, p_val = f_oneway(*groups)
        else:
            f_stat, p_val = np.nan, np.nan
        cat_rows.append(
            {
                "category": cat,
                "n_groups": int(len(groups)),
                "f_stat": float(f_stat) if np.isfinite(f_stat) else np.nan,
                "p_value": float(p_val) if np.isfinite(p_val) else np.nan,
            }
        )
    return pd.DataFrame(flag_rows), pd.DataFrame(cat_rows)


def _hall_timing_rule_eval(
    *,
    hall: pd.DataFrame,
    selection_start: pd.Timestamp,
    selection_end: pd.Timestamp,
    holdout_start: pd.Timestamp,
    holdout_end: pd.Timestamp,
    topk_dd: int = 5,
    min_dd_days: int = 6,
) -> pd.DataFrame:
    sel = hall[(hall["date"] >= selection_start) & (hall["date"] <= selection_end)].copy()
    ho = hall[(hall["date"] >= holdout_start) & (hall["date"] <= holdout_end)].copy()
    if sel.empty or ho.empty:
        return pd.DataFrame()

    weekday_mean = sel.groupby("weekday", sort=True)["avg_diff_per_machine"].mean()
    best_weekday = int(weekday_mean.idxmax())
    dd_stats = sel.groupby("dd", sort=True)["avg_diff_per_machine"].agg(["mean", "count"]).reset_index()
    dd_topk = (
        dd_stats[dd_stats["count"] >= int(min_dd_days)]
        .sort_values(["mean", "dd"], ascending=[False, True])
        .head(int(topk_dd))["dd"]
        .astype(int)
        .tolist()
    )

    rule_masks: dict[str, pd.Series] = {
        "all_days": pd.Series(np.ones(len(ho), dtype=int), index=ho.index),
        "event_only": (ho["is_any_event"] == 1).astype(int),
        "strong_zorome_only": (ho["is_strong_zorome_day"] == 1).astype(int),
        "zorome_only": (ho["is_zorome_day"] == 1).astype(int),
        "day_7x_only": (ho["is_day_7x"] == 1).astype(int),
        "day_1x_only": (ho["is_day_1x"] == 1).astype(int),
        "best_weekday_only": (ho["weekday"] == int(best_weekday)).astype(int),
        "dd_topk_only": ho["dd"].isin(dd_topk).astype(int),
    }
    base_mean = float(ho["avg_diff_per_machine"].mean())
    base_pos = float(ho["is_positive_day"].mean())
    rows: list[dict[str, Any]] = []
    for rule_name, mask in rule_masks.items():
        picked = ho[mask == 1].copy()
        vals = picked["avg_diff_per_machine"].to_numpy(dtype=float)
        pos = picked["is_positive_day"].to_numpy(dtype=float)
        mean_val = float(np.mean(vals)) if len(vals) else np.nan
        pos_rate = float(np.mean(pos)) if len(pos) else np.nan
        rows.append(
            {
                "rule": rule_name,
                "n_play_days": int(len(picked)),
                "play_rate": float(len(picked) / len(ho)) if len(ho) else np.nan,
                "avg_diff_mean": mean_val,
                "avg_diff_lift_vs_all": (mean_val - base_mean) if np.isfinite(mean_val) else np.nan,
                "positive_day_rate": pos_rate,
                "positive_rate_lift_vs_all": (pos_rate - base_pos) if np.isfinite(pos_rate) else np.nan,
                "best_weekday": int(best_weekday),
                "dd_topk": ",".join(str(x) for x in dd_topk),
            }
        )
    return pd.DataFrame(rows).sort_values(["avg_diff_lift_vs_all", "avg_diff_mean"], ascending=[False, False]).reset_index(drop=True)


def _cycle_uplift_eval(
    *,
    agg: pd.DataFrame,
    cycle: pd.DataFrame,
    holdout_start: pd.Timestamp,
    holdout_end: pd.Timestamp,
) -> pd.DataFrame:
    if agg.empty or cycle.empty:
        return pd.DataFrame()
    hits = cycle[cycle["is_sig_5pct_fdr_global"] == 1].copy()
    if hits.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for _, hit in hits.iterrows():
        group_key = str(hit["group_key"])
        digit = str(hit["last_digit"])
        lag = int(hit["lag"])
        rho = float(hit["rho"])
        g = agg[(agg["group_key"].astype(str) == group_key) & (agg["last_digit"].astype(str) == digit)].copy().sort_values("date")
        g = g[(g["date"] >= holdout_start) & (g["date"] <= holdout_end)].copy()
        if g.empty:
            continue
        hist_all = agg[(agg["group_key"].astype(str) == group_key) & (agg["last_digit"].astype(str) == digit)].copy().sort_values("date")
        hist_all["lag_is_positive"] = hist_all["is_positive"].shift(lag)
        g = g.merge(hist_all[["date", "lag_is_positive"]], on="date", how="left")
        g = g[g["lag_is_positive"].notna()].copy()
        if g.empty:
            continue
        if rho >= 0:
            signal_mask = g["lag_is_positive"].astype(int) == 1
            signal_direction = "follow_positive"
        else:
            signal_mask = g["lag_is_positive"].astype(int) == 0
            signal_direction = "fade_positive_after_negative"
        played = g[signal_mask].copy()
        all_mean = float(g["total_diff_coins"].mean()) if len(g) else np.nan
        signal_mean = float(played["total_diff_coins"].mean()) if len(played) else np.nan
        all_pos = float(g["is_positive"].mean()) if len(g) else np.nan
        signal_pos = float(played["is_positive"].mean()) if len(played) else np.nan
        rows.append(
            {
                "group_key": group_key,
                "last_digit": digit,
                "lag": lag,
                "rho": rho,
                "signal_direction": signal_direction,
                "n_eval_days": int(len(g)),
                "n_signal_days": int(len(played)),
                "signal_play_rate": float(len(played) / len(g)) if len(g) else np.nan,
                "all_days_mean_diff": all_mean,
                "signal_days_mean_diff": signal_mean,
                "mean_uplift_vs_all": (signal_mean - all_mean) if np.isfinite(signal_mean) and np.isfinite(all_mean) else np.nan,
                "all_days_positive_rate": all_pos,
                "signal_days_positive_rate": signal_pos,
                "positive_rate_uplift_vs_all": (signal_pos - all_pos) if np.isfinite(signal_pos) and np.isfinite(all_pos) else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values(["mean_uplift_vs_all", "rho"], ascending=[False, True]).reset_index(drop=True)


def _run_mode_audit(
    *,
    store_name: str,
    mode: str,
    agg: pd.DataFrame,
    hall: pd.DataFrame,
    selection_start: pd.Timestamp,
    selection_end: pd.Timestamp,
    holdout_start: pd.Timestamp,
    holdout_end: pd.Timestamp,
    cycle_lags: list[int],
    momentum_window: int,
    drought_window: int,
    min_calendar_obs: int,
    seed: int,
    out_dir: Path,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    autocorr = _phase1_autocorr(agg, cycle_lags)
    repeat = _phase1_repeat_avoidance(agg)
    rule_daily, rule_summary = _rule_eval(
        agg=agg,
        selection_start=selection_start,
        selection_end=selection_end,
        holdout_start=holdout_start,
        holdout_end=holdout_end,
        rules=DEFAULT_RULES,
        momentum_window=momentum_window,
        drought_window=drought_window,
        min_calendar_obs=min_calendar_obs,
        seed=seed,
        store_name=store_name,
    )
    cycle = _cycle_tests(agg, cycle_lags)
    hall_flag, hall_cat = _hall_timing_tests(hall)
    hall_rule_eval = _hall_timing_rule_eval(
        hall=hall,
        selection_start=selection_start,
        selection_end=selection_end,
        holdout_start=holdout_start,
        holdout_end=holdout_end,
    )
    cycle_uplift = _cycle_uplift_eval(
        agg=agg,
        cycle=cycle,
        holdout_start=holdout_start,
        holdout_end=holdout_end,
    )

    autocorr_path = out_dir / "phase1_autocorr.csv"
    repeat_path = out_dir / "phase1_repeat.csv"
    rule_daily_path = out_dir / "phase3_rule_daily.csv"
    rule_summary_path = out_dir / "phase3_rule_summary.csv"
    cycle_path = out_dir / "phase_cycle_grid.csv"
    cycle_uplift_path = out_dir / "phase_cycle_uplift.csv"
    hall_flag_path = out_dir / "phase_timing_flag.csv"
    hall_cat_path = out_dir / "phase_timing_category.csv"
    hall_rule_eval_path = out_dir / "phase_timing_rule_eval.csv"

    autocorr.to_csv(autocorr_path, index=False, encoding="utf-8-sig")
    repeat.to_csv(repeat_path, index=False, encoding="utf-8-sig")
    rule_daily.to_csv(rule_daily_path, index=False, encoding="utf-8-sig")
    rule_summary.to_csv(rule_summary_path, index=False, encoding="utf-8-sig")
    cycle.to_csv(cycle_path, index=False, encoding="utf-8-sig")
    cycle_uplift.to_csv(cycle_uplift_path, index=False, encoding="utf-8-sig")
    hall_flag.to_csv(hall_flag_path, index=False, encoding="utf-8-sig")
    hall_cat.to_csv(hall_cat_path, index=False, encoding="utf-8-sig")
    hall_rule_eval.to_csv(hall_rule_eval_path, index=False, encoding="utf-8-sig")

    best_rule = {}
    if not rule_summary.empty:
        b = rule_summary.sort_values("precision_at_2_mean", ascending=False).iloc[0]
        best_rule = {
            "group_key": str(b["group_key"]),
            "rule": str(b["rule"]),
            "precision_at_2_mean": float(b["precision_at_2_mean"]),
            "hit_at_2_mean": float(b["hit_at_2_mean"]),
        }
    cycle_sig = int(pd.to_numeric(cycle["is_sig_5pct_fdr_global"], errors="coerce").fillna(0).sum()) if not cycle.empty else 0
    repeat_min_p = float(pd.to_numeric(repeat["p_value_less"], errors="coerce").min()) if not repeat.empty else np.nan
    max_abs_rho = float(pd.to_numeric(autocorr["rho"], errors="coerce").abs().max()) if not autocorr.empty else np.nan
    timing_weekday_p = float(pd.to_numeric(hall_cat.loc[hall_cat["category"] == "weekday", "p_value"], errors="coerce").iloc[0]) if (not hall_cat.empty and (hall_cat["category"] == "weekday").any()) else np.nan
    timing_dd_p = float(pd.to_numeric(hall_cat.loc[hall_cat["category"] == "dd", "p_value"], errors="coerce").iloc[0]) if (not hall_cat.empty and (hall_cat["category"] == "dd").any()) else np.nan
    timing_best_rule = {}
    if not hall_rule_eval.empty:
        t = hall_rule_eval[hall_rule_eval["rule"].astype(str) != "all_days"].copy()
        if not t.empty:
            tb = t.sort_values(["avg_diff_lift_vs_all", "avg_diff_mean"], ascending=[False, False]).iloc[0]
            timing_best_rule = {
                "rule": str(tb["rule"]),
                "avg_diff_lift_vs_all": float(tb["avg_diff_lift_vs_all"]),
                "play_rate": float(tb["play_rate"]),
            }
    cycle_best_uplift = {}
    if not cycle_uplift.empty:
        cb = cycle_uplift.sort_values(["mean_uplift_vs_all", "rho"], ascending=[False, True]).iloc[0]
        cycle_best_uplift = {
            "group_key": str(cb["group_key"]),
            "last_digit": str(cb["last_digit"]),
            "lag": int(cb["lag"]),
            "mean_uplift_vs_all": float(cb["mean_uplift_vs_all"]),
            "signal_play_rate": float(cb["signal_play_rate"]),
            "signal_direction": str(cb["signal_direction"]),
        }

    return {
        "store": store_name,
        "mode": mode,
        "n_days": int(agg["date"].nunique()),
        "n_groups": int(agg["group_key"].nunique()),
        "n_rows": int(len(agg)),
        "max_abs_autocorr_rho": max_abs_rho,
        "min_repeat_p": repeat_min_p,
        "cycle_sig_count_fdr_global": cycle_sig,
        "timing_weekday_p": timing_weekday_p,
        "timing_dd_p": timing_dd_p,
        "best_rule": best_rule,
        "timing_best_rule": timing_best_rule,
        "cycle_best_uplift": cycle_best_uplift,
        "outputs": {
            "autocorr": str(autocorr_path),
            "repeat": str(repeat_path),
            "rule_daily": str(rule_daily_path),
            "rule_summary": str(rule_summary_path),
            "cycle": str(cycle_path),
            "cycle_uplift": str(cycle_uplift_path),
            "timing_flag": str(hall_flag_path),
            "timing_category": str(hall_cat_path),
            "timing_rule_eval": str(hall_rule_eval_path),
        },
    }


def main() -> int:
    args = build_parser().parse_args()
    db_dir = Path(args.db_dir)
    out_root = Path(args.output_root)
    out_root.mkdir(parents=True, exist_ok=True)

    modes = _parse_csv_strs(args.modes)
    label_focus_modes = set(_parse_csv_strs(args.label_focus_modes))
    cycle_lags = sorted(set(_parse_csv_ints(args.cycle_lags)))
    excluded = set(_parse_csv_strs(args.exclude_db))
    db_files = sorted([p for p in db_dir.glob(args.db_glob) if p.name not in excluded])
    if not db_files:
        raise FileNotFoundError(f"No DB files matched in {db_dir} with glob={args.db_glob}")

    selection_start = pd.Timestamp(str(args.selection_start))
    selection_end = pd.Timestamp(str(args.selection_end))
    holdout_start = pd.Timestamp(str(args.holdout_start))
    global_holdout_end = pd.Timestamp(str(args.holdout_end))

    store_rows: list[dict[str, Any]] = []
    mode_rows: list[dict[str, Any]] = []
    meta_rows: list[dict[str, Any]] = []

    for db_path in db_files:
        store_name = db_path.stem
        store_dir = out_root / store_name
        store_dir.mkdir(parents=True, exist_ok=True)
        machine, hall = _load_store_raw(db_path)
        holdout_end = min(global_holdout_end, pd.to_datetime(hall["date"]).max())
        applicability = _mode_applicability(machine, float(args.min_floor_coverage))
        applicability_path = store_dir / "mode_applicability.csv"
        applicability.to_csv(applicability_path, index=False, encoding="utf-8-sig")

        meta_rows.append(
            {
                "store": store_name,
                "db_path": str(db_path),
                "n_machine_rows": int(len(machine)),
                "n_hall_days": int(hall["date"].nunique()),
                "machine_master_join_hit_rate": float(pd.to_numeric(machine["mm_join_hit"], errors="coerce").mean()),
                "floor_known_ratio": float((machine["floor_bucket"] != "UNK").mean()),
                "atype_unique": int(machine["atype_bucket"].nunique()),
                "applicability_csv": str(applicability_path),
            }
        )

        for mode in modes:
            app = applicability[applicability["mode"] == mode]
            if app.empty or int(app.iloc[0]["is_applicable"]) != 1:
                mode_rows.append(
                    {
                        "store": store_name,
                        "mode": mode,
                        "status": "skipped",
                        "reason": (str(app.iloc[0]["reason"]) if not app.empty else "unknown_mode"),
                    }
                )
                continue
            agg = _aggregate_mode(machine, mode)
            if agg.empty:
                mode_rows.append(
                    {
                        "store": store_name,
                        "mode": mode,
                        "status": "skipped",
                        "reason": "empty_after_aggregate",
                    }
                )
                continue
            mode_dir = store_dir / mode
            summary = _run_mode_audit(
                store_name=store_name,
                mode=mode,
                agg=agg,
                hall=hall,
                selection_start=selection_start,
                selection_end=selection_end,
                holdout_start=holdout_start,
                holdout_end=holdout_end,
                cycle_lags=cycle_lags,
                momentum_window=int(args.momentum_window),
                drought_window=int(args.drought_window),
                min_calendar_obs=int(args.min_calendar_obs),
                seed=int(args.seed),
                out_dir=mode_dir,
            )
            (mode_dir / "mode_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            mode_rows.append(
                {
                    "store": store_name,
                    "mode": mode,
                    "status": "ok",
                    "n_days": summary["n_days"],
                    "n_groups": summary["n_groups"],
                    "max_abs_autocorr_rho": summary["max_abs_autocorr_rho"],
                    "min_repeat_p": summary["min_repeat_p"],
                    "cycle_sig_count_fdr_global": summary["cycle_sig_count_fdr_global"],
                    "cycle_best_uplift": summary["cycle_best_uplift"].get("mean_uplift_vs_all") if summary["cycle_best_uplift"] else np.nan,
                    "cycle_best_play_rate": summary["cycle_best_uplift"].get("signal_play_rate") if summary["cycle_best_uplift"] else np.nan,
                    "timing_weekday_p": summary["timing_weekday_p"],
                    "timing_dd_p": summary["timing_dd_p"],
                    "timing_best_rule_name": summary["timing_best_rule"].get("rule") if summary["timing_best_rule"] else "",
                    "timing_best_uplift": summary["timing_best_rule"].get("avg_diff_lift_vs_all") if summary["timing_best_rule"] else np.nan,
                    "timing_best_play_rate": summary["timing_best_rule"].get("play_rate") if summary["timing_best_rule"] else np.nan,
                    "best_rule_group": summary["best_rule"].get("group_key") if summary["best_rule"] else "",
                    "best_rule_name": summary["best_rule"].get("rule") if summary["best_rule"] else "",
                    "best_rule_precision_at_2": summary["best_rule"].get("precision_at_2_mean") if summary["best_rule"] else np.nan,
                    "mode_summary_json": str(mode_dir / "mode_summary.json"),
                }
            )
        store_rows.append({"store": store_name, "db_path": str(db_path), "store_dir": str(store_dir)})

    store_df = pd.DataFrame(store_rows)
    mode_df = pd.DataFrame(mode_rows)
    meta_df = pd.DataFrame(meta_rows)

    store_csv = out_root / "stores.csv"
    mode_csv = out_root / "mode_results.csv"
    meta_csv = out_root / "store_meta.csv"
    summary_json = out_root / "run_summary.json"

    store_df.to_csv(store_csv, index=False, encoding="utf-8-sig")
    mode_df.to_csv(mode_csv, index=False, encoding="utf-8-sig")
    meta_df.to_csv(meta_csv, index=False, encoding="utf-8-sig")

    cycle_focus_csv = out_root / "cycle_focus_modes.csv"
    store_labels_csv = out_root / "store_labels.csv"
    cycle_focus_top_csv = out_root / "cycle_focus_top_hits.csv"
    focus_mode_csv = out_root / "focus_mode_results.csv"

    if not mode_df.empty:
        mode_ok = mode_df[mode_df["status"].astype(str) == "ok"].copy()
        mode_focus = mode_ok[mode_ok["mode"].astype(str).isin(label_focus_modes)].copy()
        mode_focus.to_csv(focus_mode_csv, index=False, encoding="utf-8-sig")
        cycle_focus = mode_focus[
            pd.to_numeric(mode_focus.get("cycle_sig_count_fdr_global", 0), errors="coerce").fillna(0).astype(int)
            >= int(args.cycle_min_sig)
        ].copy()
        cycle_focus = cycle_focus[
            pd.to_numeric(cycle_focus.get("cycle_best_uplift", np.nan), errors="coerce").fillna(-np.inf)
            > float(args.cycle_min_uplift)
        ].copy()
        cycle_focus.to_csv(cycle_focus_csv, index=False, encoding="utf-8-sig")

        top_rows: list[dict[str, Any]] = []
        for _, r in cycle_focus.iterrows():
            mode_summary_path = Path(str(r.get("mode_summary_json", "")).strip())
            if not mode_summary_path.exists():
                continue
            try:
                obj = json.loads(mode_summary_path.read_text(encoding="utf-8"))
                cyc_path = Path(str(obj.get("outputs", {}).get("cycle", "")).strip())
                uplift_path = Path(str(obj.get("outputs", {}).get("cycle_uplift", "")).strip())
                if not cyc_path.exists():
                    continue
                cyc = pd.read_csv(cyc_path, encoding="utf-8-sig")
                cyc_up = pd.read_csv(uplift_path, encoding="utf-8-sig") if uplift_path.exists() else pd.DataFrame()
                cyc = cyc[cyc["is_sig_5pct_fdr_global"] == 1].copy()
                if cyc.empty:
                    continue
                cyc = cyc.sort_values(["p_value_raw", "rho"], ascending=[True, True]).head(10)
                for _, c in cyc.iterrows():
                    uplift_row = pd.DataFrame()
                    if not cyc_up.empty:
                        uplift_row = cyc_up[
                            cyc_up["group_key"].astype(str).eq(str(c["group_key"]))
                            & cyc_up["last_digit"].astype(str).eq(str(c["last_digit"]))
                            & pd.to_numeric(cyc_up["lag"], errors="coerce").eq(int(c["lag"]))
                        ].head(1)
                    top_rows.append(
                        {
                            "store": str(r["store"]),
                            "mode": str(r["mode"]),
                            "group_key": str(c["group_key"]),
                            "last_digit": str(c["last_digit"]),
                            "lag": int(c["lag"]),
                            "rho": float(c["rho"]),
                            "p_value_raw": float(c["p_value_raw"]),
                            "p_value_fdr_bh_global": float(c["p_value_fdr_bh_global"]),
                            "n_pairs": int(c["n_pairs"]),
                            "mean_uplift_vs_all": (float(uplift_row.iloc[0]["mean_uplift_vs_all"]) if not uplift_row.empty else np.nan),
                            "signal_play_rate": (float(uplift_row.iloc[0]["signal_play_rate"]) if not uplift_row.empty else np.nan),
                            "signal_direction": (str(uplift_row.iloc[0]["signal_direction"]) if not uplift_row.empty else ""),
                        }
                    )
            except Exception:
                continue
        pd.DataFrame(top_rows).to_csv(cycle_focus_top_csv, index=False, encoding="utf-8-sig")

        label_rows: list[dict[str, Any]] = []
        for store, g in mode_focus.groupby("store", sort=False):
            cycle_sig = int(pd.to_numeric(g["cycle_sig_count_fdr_global"], errors="coerce").fillna(0).max())
            cycle_best_uplift = float(pd.to_numeric(g["cycle_best_uplift"], errors="coerce").max())
            timing_weekday_p = float(pd.to_numeric(g["timing_weekday_p"], errors="coerce").min())
            timing_dd_p = float(pd.to_numeric(g["timing_dd_p"], errors="coerce").min())
            timing_best_uplift = float(pd.to_numeric(g["timing_best_uplift"], errors="coerce").max())
            timing_best_rule = (
                g.sort_values(["timing_best_uplift", "timing_best_play_rate"], ascending=[False, False])["timing_best_rule_name"].astype(str).iloc[0]
                if not g.empty
                else ""
            )
            timing_sig = int(
                (
                    (np.isfinite(timing_weekday_p) and timing_weekday_p < float(args.timing_p_threshold))
                    or (np.isfinite(timing_dd_p) and timing_dd_p < float(args.timing_p_threshold))
                )
                and np.isfinite(timing_best_uplift)
                and timing_best_uplift > float(args.timing_min_uplift)
            )
            if cycle_sig >= int(args.cycle_min_sig) and np.isfinite(cycle_best_uplift) and cycle_best_uplift > float(args.cycle_min_uplift):
                label = "Weak Cycle"
            elif timing_sig == 1:
                label = "Timing Only"
            else:
                label = "No Signal"
            label_rows.append(
                {
                    "store": str(store),
                    "label": label,
                    "cycle_sig_count_max": cycle_sig,
                    "cycle_best_uplift_max": cycle_best_uplift,
                    "timing_weekday_p_min": timing_weekday_p,
                    "timing_dd_p_min": timing_dd_p,
                    "timing_best_rule": timing_best_rule,
                    "timing_best_uplift_max": timing_best_uplift,
                    "label_focus_modes": ",".join(sorted(label_focus_modes)),
                    "timing_p_threshold": float(args.timing_p_threshold),
                    "timing_min_uplift": float(args.timing_min_uplift),
                    "cycle_min_uplift": float(args.cycle_min_uplift),
                }
            )
        pd.DataFrame(label_rows).sort_values("store").to_csv(store_labels_csv, index=False, encoding="utf-8-sig")
    else:
        pd.DataFrame().to_csv(cycle_focus_csv, index=False, encoding="utf-8-sig")
        pd.DataFrame().to_csv(cycle_focus_top_csv, index=False, encoding="utf-8-sig")
        pd.DataFrame().to_csv(store_labels_csv, index=False, encoding="utf-8-sig")
        pd.DataFrame().to_csv(focus_mode_csv, index=False, encoding="utf-8-sig")

    run_summary = {
        "output_root": str(out_root),
        "db_count": int(len(db_files)),
        "stores_csv": str(store_csv),
        "mode_results_csv": str(mode_csv),
        "store_meta_csv": str(meta_csv),
        "cycle_focus_modes_csv": str(cycle_focus_csv),
        "cycle_focus_top_hits_csv": str(cycle_focus_top_csv),
        "focus_mode_results_csv": str(focus_mode_csv),
        "store_labels_csv": str(store_labels_csv),
    }
    summary_json.write_text(json.dumps(run_summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[OK] saved: {store_csv}")
    print(f"[OK] saved: {mode_csv}")
    print(f"[OK] saved: {meta_csv}")
    print(f"[OK] saved: {cycle_focus_csv}")
    print(f"[OK] saved: {cycle_focus_top_csv}")
    print(f"[OK] saved: {focus_mode_csv}")
    print(f"[OK] saved: {store_labels_csv}")
    print(f"[OK] saved: {summary_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
