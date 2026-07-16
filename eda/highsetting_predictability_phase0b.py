# -*- coding: utf-8 -*-
"""Phase 0b: 高設定位置の翌日予測可能性（walk-forwardバックテスト）

呼び出し: venv/Scripts/python.exe eda/highsetting_predictability_phase0b.py（単体実行）
データ: db/<ホール>.db machine_detailed_results
  (date TEXT "YYYYMMDD", machine_number INTEGER, machine_name TEXT,
   games_normalized INTEGER, diff_coins_normalized INTEGER, bb_count/rb_count INTEGER)

手法(v1 経験ベイズランキング):
  score(台, 翌日) = 縮小推定した台別高設定率(直近180日)
                  × DD倍率(翌日のDD, 全履歴)
                  × 据え置き倍率(前日高設定なら P(high|前日high)/base)
評価: 毎日、設置台数の10%を候補に選び precision@10% を実測ラベルと照合。
      ベースレート(ランダム選択の期待精度)との lift を報告。
補助: 据え置き診断 P(high_d | high_{d-1})、AT厳格閾値のベースレート。
出力: 集計のみ標準出力。
"""

from __future__ import annotations

import math
import sqlite3  # noqa: F401  (load_hall経由で使用)
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from eda.highsetting_base_rate_phase0 import (  # noqa: E402
    HALLS,
    MIN_GAMES_JUG,
    P56_HIGH,
    jug_posterior_p56,
    load_hall,
    match_family,
)

TRAIL_DAYS = 180  # 台別率の遡及窓
MIN_HISTORY_DAYS = 90  # 評価開始までのウォームアップ
SHRINK_K = 15.0  # 経験ベイズ縮小強度
PICK_RATIO = 0.10  # 候補リスト = 設置台数の10%


def build_jug_panel(hall: str, path: Path) -> pd.DataFrame:
    df, _ = load_hall(path)
    jug = df[df["machine_name"].str.contains("ジャグラー", na=False)].copy()
    jug["family"] = jug["machine_name"].map(match_family)
    jug = jug.dropna(subset=["family"])
    jug["evaluable"] = jug["games_normalized"] >= MIN_GAMES_JUG
    jug["p56"] = np.nan
    ev = jug[jug["evaluable"]].copy()
    jug.loc[ev.index, "p56"] = jug_posterior_p56(ev).to_numpy()
    jug["is_high"] = (jug["p56"] >= P56_HIGH).fillna(False)
    return jug[["date", "machine_number", "evaluable", "is_high"]]


def carryover_diag(panel: pd.DataFrame) -> tuple[float, float]:
    """P(high_d | high_{d-1}) と base を返す（両日evaluableの台のみ）"""
    p = panel[panel["evaluable"]].copy()
    dates = sorted(p["date"].unique())
    date_idx = {d: i for i, d in enumerate(dates)}
    p["di"] = p["date"].map(date_idx)
    prev = p[["di", "machine_number", "is_high"]].copy()
    prev["di"] += 1
    merged = p.merge(prev, on=["di", "machine_number"], suffixes=("", "_prev"), how="inner")
    base = merged["is_high"].mean()
    cond = merged.loc[merged["is_high_prev"], "is_high"].mean()
    return float(cond), float(base)


def backtest(panel: pd.DataFrame) -> dict:
    dates = sorted(panel["date"].unique())
    by_date = {d: g for d, g in panel.groupby("date")}
    cond_prev, base_prev = carryover_diag(panel)
    carry_mult_global = cond_prev / base_prev if base_prev > 0 else 1.0

    hist = panel.copy()
    hist["dd"] = hist["date"].str[6:8].astype(int)

    recs = []
    for i in range(MIN_HISTORY_DAYS, len(dates)):
        d = dates[i]
        today = by_date[d]
        trail_dates = set(dates[max(0, i - TRAIL_DAYS) : i])
        trail = hist[hist["date"].isin(trail_dates) & hist["evaluable"]]
        if trail.empty:
            continue
        base = trail["is_high"].mean()
        g = trail.groupby("machine_number")["is_high"].agg(["sum", "count"])
        g["rate"] = (g["sum"] + SHRINK_K * base) / (g["count"] + SHRINK_K)
        # DD倍率（当日より前の全履歴）
        dd_today = int(d[6:8])
        past_ev = hist[(hist["date"] < d) & hist["evaluable"]]
        dd_rate = past_ev.loc[past_ev["dd"] == dd_today, "is_high"].mean()
        all_rate = past_ev["is_high"].mean()
        dd_mult = dd_rate / all_rate if (all_rate and all_rate > 0 and not math.isnan(dd_rate)) else 1.0
        d_prev = dates[i - 1]
        prev_df = by_date[d_prev]
        prev_high = set(prev_df.loc[prev_df["evaluable"] & prev_df["is_high"], "machine_number"])
        cand = today[["machine_number", "evaluable", "is_high"]].copy()
        cand["score"] = cand["machine_number"].map(g["rate"]).fillna(base)
        cand["score"] *= dd_mult
        cand.loc[cand["machine_number"].isin(prev_high), "score"] *= carry_mult_global
        n_pick = max(1, math.ceil(len(cand) * PICK_RATIO))
        picks = cand.nlargest(n_pick, "score")
        ev_picks = picks[picks["evaluable"]]
        day_pool = today[today["evaluable"]]
        recs.append(
            {
                "date": d,
                "n_pick": n_pick,
                "n_pick_eval": len(ev_picks),
                "hits": int(ev_picks["is_high"].sum()),
                "precision": ev_picks["is_high"].mean() if len(ev_picks) else np.nan,
                "day_base": day_pool["is_high"].mean() if len(day_pool) else np.nan,
            }
        )
    res = pd.DataFrame(recs)
    prec = res["precision"].mean()
    base = res["day_base"].mean()
    rand_hit = (1 - (1 - res["day_base"]).pow(res["n_pick_eval"].clip(lower=0))).mean()
    return {
        "eval_days": len(res),
        "precision": prec,
        "base_rate": base,
        "lift": prec / base if base else np.nan,
        "avg_hits": res["hits"].mean(),
        "hit_ge1": (res["hits"] >= 1).mean(),
        "rand_hit_ge1": rand_hit,
        "pick_eval_share": (res["n_pick_eval"] / res["n_pick"]).mean(),
        "carry_cond": cond_prev,
        "carry_base": base_prev,
    }


def at_strict_base_rates(path: Path) -> list[str]:
    df, master = load_hall(path)
    df = df.merge(master, left_on="machine_name", right_on="machine_name_normalized", how="left")
    at = df[df["bt_flag"] == 1].copy()
    at["payout"] = 100.0 + at["diff_coins_normalized"] / (at["games_normalized"] * 3.0) * 100.0
    lines = []
    all_dates = sorted(df["date"].unique())
    for gmin, pmin in [(5000, 106.0), (5000, 108.0), (6000, 110.0)]:
        sub = at[at["games_normalized"] >= gmin]
        if not len(sub):
            lines.append(f"  AT[>={gmin}G, >={pmin}%]: 該当なし")
            continue
        daily = sub.assign(hi=sub["payout"] >= pmin).groupby("date")["hi"].sum().reindex(all_dates).fillna(0)
        lines.append(
            f"  AT[>={gmin}G, 機械割>={pmin}%]: 平均{daily.mean():.2f}台/日, 0台の日={(daily == 0).mean():.0%}"
        )
    return lines


def main() -> None:
    for hall, path in HALLS.items():
        print(f"\n{'=' * 70}\n[{hall}] ジャグ高設定 位置予測 walk-forward")
        panel = build_jug_panel(hall, path)
        r = backtest(panel)
        print(
            f"  評価日数={r['eval_days']}  precision@10%={r['precision']:.3f} "
            f"vs base={r['base_rate']:.3f}  lift={r['lift']:.2f}x"
        )
        print(
            f"  平均的中台数/日={r['avg_hits']:.2f}  >=1台的中の日={r['hit_ge1']:.1%} "
            f"(ランダム期待={r['rand_hit_ge1']:.1%})  "
            f"候補の評価可能率={r['pick_eval_share']:.1%}"
        )
        print(
            f"  据え置き診断: P(high|前日high)={r['carry_cond']:.3f} "
            f"vs base={r['carry_base']:.3f} (倍率{r['carry_cond'] / r['carry_base']:.2f}x)"
        )
        for line in at_strict_base_rates(path):
            print(line)


if __name__ == "__main__":
    main()
