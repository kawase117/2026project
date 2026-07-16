# -*- coding: utf-8 -*-
"""v2スコアラー: LightGBM + 位置・カレンダー特徴量による高設定位置予測

呼び出し: venv/Scripts/python.exe eda/highsetting_v2_scorer.py [track]（単体実行、track=jug|at|hana、省略時jug）

v1（経験ベイズ: 台別縮小率×DD倍率×据置倍率）との違い:
  - DD・曜日・末尾・角位置と台効果の交互作用を学習できる（v1のDD倍率は日内全台共通で
    日内ランキングに寄与しないという盲点があった）
  - 位置特徴量: 機種内の台番号順位（端/中）、末尾、台番ゾロ目
評価プロトコルはv1と同一: 毎日、設置台の10%を候補に選び precision@10% をラベルと照合。
walk-forward: ウォームアップ180日、30日ブロックごとに再学習（学習は常にブロック開始日より前のみ）。
出力: 集計のみ標準出力。
"""

from __future__ import annotations

import math
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
from eda.at_semantics_validator import (  # noqa: E402
    AT_SPECS,
    choose_mapping,
    posterior_high,
    validate_hall,
)
from eda.at_semantics_validator import MIN_GAMES as AT_MIN_GAMES  # noqa: E402
from eda.highsetting_predictability_hana_at import SPEC_MASTER  # noqa: E402
from eda.highsetting_predictability_hana_at import (  # noqa: E402
    posterior_p_high as hana_posterior,
)

WARMUP_DAYS = 180
RETRAIN_BLOCK = 30
PICK_RATIO = 0.10
SHRINK_K = 15.0
WINDOWS = (60, 180, 365)

LGB_PARAMS = dict(
    objective="binary",
    n_estimators=300,
    learning_rate=0.05,
    num_leaves=31,
    min_child_samples=50,
    subsample=0.9,
    subsample_freq=1,
    colsample_bytree=0.8,
    verbose=-1,
    n_jobs=-1,
)


def build_labeled_panel(hall: str, track: str) -> pd.DataFrame:
    """(date, machine_number, machine_name, evaluable, is_high) を返す"""
    df, _ = load_hall(HALLS[hall])
    if track == "jug":
        jug = df[df["machine_name"].str.contains("ジャグラー", na=False)].copy()
        jug["family"] = jug["machine_name"].map(match_family)
        jug = jug.dropna(subset=["family"])
        jug["evaluable"] = jug["games_normalized"] >= MIN_GAMES_JUG
        jug["p_high"] = np.nan
        ev = jug[jug["evaluable"]].copy()
        if len(ev):
            jug.loc[ev.index, "p_high"] = jug_posterior_p56(ev).to_numpy()
        jug["is_high"] = (jug["p_high"] >= P56_HIGH).fillna(False)
        return jug[["date", "machine_number", "machine_name", "evaluable", "is_high"]]
    if track == "at":
        chosen = choose_mapping(validate_hall(df))
        parts = []
        for name, r in chosen.items():
            table = AT_SPECS[name]["tables"][r["table"]]
            sub = df[df["machine_name"] == name].copy()
            sub["evaluable"] = sub["games_normalized"] >= AT_MIN_GAMES
            sub["p_high"] = np.nan
            ev = sub[sub["evaluable"]]
            if len(ev):
                sub.loc[ev.index, "p_high"] = posterior_high(ev, r["col"], table)
            sub["is_high"] = (sub["p_high"] >= 0.80).fillna(False)
            parts.append(sub[["date", "machine_number", "machine_name", "evaluable", "is_high"]])
        if not parts:
            return pd.DataFrame(columns=["date", "machine_number", "machine_name", "evaluable", "is_high"])
        return pd.concat(parts, ignore_index=True)
    if track in ("hana", "tech"):
        from eda.highsetting_predictability_hana_at import tech_range_ok

        parts = []
        for name, spec in SPEC_MASTER.items():
            if spec["track"] != track:
                continue
            sub = df[df["machine_name"] == name].copy()
            if sub.empty:
                continue
            sub["evaluable"] = sub["games_normalized"] >= spec["min_games"]
            if track == "tech":
                ok, msg = tech_range_ok(sub[sub["evaluable"]], spec)
                if not ok:
                    print(f"    (レンジ検証NGで除外: {hall} {name} {msg})")
                    continue
            sub["p_high"] = np.nan
            ev = sub[sub["evaluable"]]
            if len(ev):
                sub.loc[ev.index, "p_high"] = hana_posterior(ev, spec)
            sub["is_high"] = (sub["p_high"] >= 0.80).fillna(False)
            parts.append(sub[["date", "machine_number", "machine_name", "evaluable", "is_high"]])
        if not parts:
            return pd.DataFrame(columns=["date", "machine_number", "machine_name", "evaluable", "is_high"])
        return pd.concat(parts, ignore_index=True)
    raise ValueError(track)


def build_features(panel: pd.DataFrame) -> pd.DataFrame:
    """リークなし特徴量（すべて当日より前の情報のみ）を付与した学習フレームを返す"""
    panel = panel.copy()
    dates = sorted(panel["date"].unique())
    didx = {d: i for i, d in enumerate(dates)}
    panel["di"] = panel["date"].map(didx)
    machines = sorted(panel["machine_number"].unique())
    midx = {m: j for j, m in enumerate(machines)}
    panel["mi"] = panel["machine_number"].map(midx)

    n_d, n_m = len(dates), len(machines)
    E = np.zeros((n_d, n_m))
    H = np.zeros((n_d, n_m))
    for di, mi, ev, hi in zip(panel["di"], panel["mi"], panel["evaluable"], panel["is_high"]):
        E[di, mi] = 1.0 if ev else 0.0
        H[di, mi] = 1.0 if (ev and hi) else 0.0

    cumE = np.vstack([np.zeros(n_m), E.cumsum(axis=0)])  # cumE[i] = 0..i-1日の合計
    cumH = np.vstack([np.zeros(n_m), H.cumsum(axis=0)])

    feats = {}
    for w in WINDOWS:
        lo = np.maximum(0, np.arange(n_d) - w)
        sumE = cumE[np.arange(n_d)] - cumE[lo]
        sumH = cumH[np.arange(n_d)] - cumH[lo]
        base = sumH.sum(axis=1, keepdims=True) / np.maximum(sumE.sum(axis=1, keepdims=True), 1)
        feats[f"m_rate_{w}"] = (sumH + SHRINK_K * base) / (sumE + SHRINK_K)
        if w == WINDOWS[1]:
            feats["day_base"] = np.repeat(base, n_m, axis=1)

    prev_high = np.vstack([np.zeros(n_m), H[:-1]])
    feats["prev_high"] = prev_high
    # days_since_high（前日までの情報、上限60）
    dsl = np.full((n_d, n_m), 60.0)
    last = np.full(n_m, -1.0)
    for i in range(n_d):
        dsl[i] = np.where(last >= 0, np.minimum(i - last, 60.0), 60.0)
        last = np.where(H[i] > 0, i, last)
    feats["days_since_high"] = dsl

    long = panel[["date", "machine_number", "machine_name", "evaluable", "is_high", "di", "mi"]].copy()
    di_arr = long["di"].to_numpy()
    mi_arr = long["mi"].to_numpy()
    for k, arr in feats.items():
        long[k] = arr[di_arr, mi_arr]

    # カレンダー
    dt = pd.to_datetime(long["date"], format="%Y%m%d")
    long["dd"] = dt.dt.day
    long["weekday"] = dt.dt.weekday
    # 台番号系
    mn = long["machine_number"].astype(int)
    long["last_digit"] = mn % 10
    long["zorome"] = ((mn % 10) == ((mn // 10) % 10)).astype(int)
    # 機種内位置（当日の同機種設置の中での順位）
    g = long.groupby(["date", "machine_name"])["machine_number"]
    long["pos_rank_min"] = g.rank(method="min").astype(int)
    long["group_size"] = g.transform("size")
    long["pos_rank_max"] = long["group_size"] - long["pos_rank_min"] + 1
    long["is_edge"] = ((long["pos_rank_min"] == 1) | (long["pos_rank_max"] == 1)).astype(int)
    long["machine_cat"] = long["machine_name"].astype("category").cat.codes
    return long


FEATURES = [
    "m_rate_60",
    "m_rate_180",
    "m_rate_365",
    "day_base",
    "prev_high",
    "days_since_high",
    "dd",
    "weekday",
    "last_digit",
    "zorome",
    "pos_rank_min",
    "pos_rank_max",
    "group_size",
    "is_edge",
    "machine_cat",
]


def walkforward_v2(long: pd.DataFrame) -> dict:
    import lightgbm as lgb

    dates = sorted(long["date"].unique())
    if len(dates) <= WARMUP_DAYS + RETRAIN_BLOCK:
        return {}
    long = long.sort_values(["date", "machine_number"]).reset_index(drop=True)
    scores = np.full(len(long), np.nan)

    for start in range(WARMUP_DAYS, len(dates), RETRAIN_BLOCK):
        block_dates = set(dates[start : start + RETRAIN_BLOCK])
        train = long[(long["date"] < dates[start]) & long["evaluable"]]
        if train["is_high"].sum() < 20:
            continue
        model = lgb.LGBMClassifier(**LGB_PARAMS)
        model.fit(
            train[FEATURES],
            train["is_high"].astype(int),
            categorical_feature=["dd", "weekday", "last_digit", "machine_cat"],
        )
        pmask = long["date"].isin(block_dates).to_numpy()
        scores[pmask] = model.predict_proba(long.loc[pmask, FEATURES])[:, 1]

    long["score"] = scores
    eval_rows = long[long["score"].notna()]
    recs = []
    for _, day in eval_rows.groupby("date"):
        n_pick = max(1, math.ceil(len(day) * PICK_RATIO))
        picks = day.nlargest(n_pick, "score")
        ev_picks = picks[picks["evaluable"]]
        pool = day[day["evaluable"]]
        if not len(pool):
            continue
        recs.append(
            {
                "hits": int(ev_picks["is_high"].sum()),
                "precision": ev_picks["is_high"].mean() if len(ev_picks) else np.nan,
                "day_base": pool["is_high"].mean(),
                "n_eval_picks": len(ev_picks),
            }
        )
    res = pd.DataFrame(recs)
    prec = res["precision"].mean()
    base = res["day_base"].mean()
    return {
        "eval_days": len(res),
        "precision": prec,
        "base": base,
        "lift": prec / base if base else np.nan,
        "avg_hits": res["hits"].mean(),
        "hit_ge1": (res["hits"] >= 1).mean(),
        "rand_hit_ge1": (1 - (1 - res["day_base"]).pow(res["n_eval_picks"].clip(lower=0))).mean(),
    }


def main() -> None:
    track = sys.argv[1] if len(sys.argv) > 1 else "jug"
    print(f"track={track} (walk-forward: warmup {WARMUP_DAYS}日 / 再学習 {RETRAIN_BLOCK}日ごと)")
    for hall in HALLS:
        panel = build_labeled_panel(hall, track)
        if panel.empty or panel.groupby("date")["machine_number"].size().mean() < 5:
            print(f"[{hall}] 対象台不足によりスキップ")
            continue
        long = build_features(panel)
        r = walkforward_v2(long)
        if not r:
            print(f"[{hall}] 学習データ不足によりスキップ")
            continue
        print(
            f"[{hall}] 評価日数={r['eval_days']} precision@10%={r['precision']:.3f} "
            f"vs base={r['base']:.3f} lift={r['lift']:.2f}x  "
            f"平均的中={r['avg_hits']:.2f}台/日 >=1台的中={r['hit_ge1']:.1%}"
            f"(rand {r['rand_hit_ge1']:.1%})"
        )


if __name__ == "__main__":
    main()
