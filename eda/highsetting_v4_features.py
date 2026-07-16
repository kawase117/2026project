# -*- coding: utf-8 -*-
"""v4実験: 複数lag + 差枚履歴 + machine_layout物理位置特徴量の効果検証

呼び出し: venv/Scripts/python.exe eda/highsetting_v4_features.py [track]（track=jug|hana|at、省略時jug）

ユーザー指示（2026-07-16）:
  - 過去の差枚ベース検証で複数lagが一部有用だった → prev_high(lag1)だけでなく複数lag化
  - machine_layout（物理角番・通路距離）も一定の効果が見込める

追加特徴量（すべて対象日より前の情報のみ、リークなし）:
  lag系   : high_lag2, high_lag3, high_sum_7, high_sum_14（is_highの遅延・移動和）
  差枚系  : pay_lag1, pay_mean_7（台の日次ペイアウト率の遅延・移動平均、打たれた日のみ）
  layout系: lx, ly, rank_from_min, rank_from_max, rank_from_aisle, layout_section_size,
            kaku_min, kaku_max（section両端フラグ）

戦略比較（同一walk-forward日程・同一評価プロトコル）:
  v1 / v2(既存FEATURES) / v4(既存+追加) / blend_v1_v4(日内ランク平均)
出力: 集計のみ標準出力。
"""

from __future__ import annotations

import math
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from eda.highsetting_base_rate_phase0 import HALLS  # noqa: E402
from eda.highsetting_predictability_phase0b import carryover_diag  # noqa: E402
from eda.highsetting_v2_scorer import (  # noqa: E402
    FEATURES,
    LGB_PARAMS,
    RETRAIN_BLOCK,
    WARMUP_DAYS,
    build_features,
    build_labeled_panel,
)

PICK_RATIO = 0.10

LAG_FEATURES = ["high_lag2", "high_lag3", "high_sum_7", "high_sum_14", "pay_lag1", "pay_mean_7"]
LAYOUT_FEATURES = [
    "lx",
    "ly",
    "rank_from_min",
    "rank_from_max",
    "rank_from_aisle",
    "layout_section_size",
    "kaku_min",
    "kaku_max",
]
V4_FEATURES = FEATURES + LAG_FEATURES + LAYOUT_FEATURES


def load_diff(hall: str) -> pd.DataFrame:
    con = sqlite3.connect(HALLS[hall])
    df = pd.read_sql_query(
        "select date, machine_number, diff_coins_normalized, games_normalized"
        " from machine_detailed_results where games_normalized > 0",
        con,
    )
    con.close()
    return df


def load_layout(hall: str) -> pd.DataFrame:
    con = sqlite3.connect(HALLS[hall])
    try:
        df = pd.read_sql_query(
            "select machine_number, x, y, section_min, section_max,"
            " rank_from_min, rank_from_max, rank_from_aisle from machine_layout",
            con,
        )
    except Exception:
        df = pd.DataFrame()
    con.close()
    if len(df):
        # 楽園DB等でmachine_numberがTEXT格納のためmerge前に数値化
        df["machine_number"] = pd.to_numeric(df["machine_number"], errors="coerce")
        df = df.dropna(subset=["machine_number"])
        df["machine_number"] = df["machine_number"].astype(int)
    return df


def augment_v4(long: pd.DataFrame, hall: str) -> pd.DataFrame:
    dates = sorted(long["date"].unique())
    # --- lag系（is_highの完全グリッドpivotで日単位shift） ---
    hi = (
        long.assign(hi=(long["evaluable"] & long["is_high"]).astype(float))
        .pivot_table(index="date", columns="machine_number", values="hi", aggfunc="first")
        .reindex(dates)
    )
    feats = {
        "high_lag2": hi.shift(2),
        "high_lag3": hi.shift(3),
        "high_sum_7": hi.rolling(7, min_periods=1).sum().shift(1),
        "high_sum_14": hi.rolling(14, min_periods=1).sum().shift(1),
    }
    # --- 差枚系 ---
    diff = load_diff(hall)
    diff["pay"] = diff["diff_coins_normalized"] / (diff["games_normalized"] * 3.0)
    pay = diff.pivot_table(index="date", columns="machine_number", values="pay", aggfunc="first").reindex(
        index=dates, columns=hi.columns
    )
    feats["pay_lag1"] = pay.shift(1)
    feats["pay_mean_7"] = pay.rolling(7, min_periods=1).mean().shift(1)

    for name, mat in feats.items():
        s = mat.stack().rename(name).reset_index()
        s.columns = ["date", "machine_number", name]
        long = long.merge(s, on=["date", "machine_number"], how="left")

    # --- layout系 ---
    layout = load_layout(hall)
    if len(layout):
        layout = layout.rename(columns={"x": "lx", "y": "ly"})
        layout["layout_section_size"] = layout["section_max"] - layout["section_min"] + 1
        layout["kaku_min"] = (layout["rank_from_min"] == 1).astype(int)
        layout["kaku_max"] = (layout["rank_from_max"] == 1).astype(int)
        long = long.merge(layout[["machine_number"] + LAYOUT_FEATURES], on="machine_number", how="left")
        matched = long["lx"].notna().mean()
        aisle = long["rank_from_aisle"].notna().mean()
        print(f"  (layoutマッチ率={matched:.0%} / rank_from_aisle充足率={aisle:.0%})")
    else:
        for c in LAYOUT_FEATURES:
            long[c] = np.nan
        print("  (machine_layoutなし)")
    # DB側でTEXT型の列があるため数値へ強制変換（既知のsection_size型不一致バグと同族）
    for c in LAYOUT_FEATURES:
        long[c] = pd.to_numeric(long[c], errors="coerce")
    return long


def evaluate(long: pd.DataFrame, score_col: str) -> dict:
    rows = long[long[score_col].notna()]
    recs = []
    for _, day in rows.groupby("date"):
        n_pick = max(1, math.ceil(len(day) * PICK_RATIO))
        picks = day.nlargest(n_pick, score_col)
        ev = picks[picks["evaluable"]]
        pool = day[day["evaluable"]]
        if not len(pool):
            continue
        recs.append(
            {
                "precision": ev["is_high"].mean() if len(ev) else np.nan,
                "base": pool["is_high"].mean(),
                "hit": int(ev["is_high"].sum()) >= 1,
            }
        )
    res = pd.DataFrame(recs)
    prec, base = res["precision"].mean(), res["base"].mean()
    return {
        "days": len(res),
        "prec": prec,
        "base": base,
        "lift": prec / base if base else np.nan,
        "hit_ge1": res["hit"].mean(),
    }


def main() -> None:
    import lightgbm as lgb

    track = sys.argv[1] if len(sys.argv) > 1 else "jug"
    print(f"track={track}")
    for hall in HALLS:
        panel = build_labeled_panel(hall, track)
        if panel.empty or panel.groupby("date")["machine_number"].size().mean() < 5:
            print(f"\n[{hall}] 対象台不足によりスキップ")
            continue
        long = build_features(panel).sort_values(["date", "machine_number"]).reset_index(drop=True)
        print(f"\n[{hall}] {track} v4特徴量比較")
        long = augment_v4(long, hall)
        cond, base0 = carryover_diag(panel[["date", "machine_number", "evaluable", "is_high"]])
        carry = cond / base0 if base0 else 1.0
        long["s_v1"] = long["m_rate_180"] * np.where(long["prev_high"] > 0, carry, 1.0)

        dates = sorted(long["date"].unique())
        s_v2 = np.full(len(long), np.nan)
        s_v4 = np.full(len(long), np.nan)
        cat = ["dd", "weekday", "last_digit", "machine_cat"]
        for start in range(WARMUP_DAYS, len(dates), RETRAIN_BLOCK):
            block = set(dates[start : start + RETRAIN_BLOCK])
            train = long[(long["date"] < dates[start]) & long["evaluable"]]
            if train["is_high"].sum() < 20:
                continue
            pmask = long["date"].isin(block).to_numpy()
            m2 = lgb.LGBMClassifier(**LGB_PARAMS)
            m2.fit(train[FEATURES], train["is_high"].astype(int), categorical_feature=cat)
            s_v2[pmask] = m2.predict_proba(long.loc[pmask, FEATURES])[:, 1]
            m4 = lgb.LGBMClassifier(**LGB_PARAMS)
            m4.fit(train[V4_FEATURES], train["is_high"].astype(int), categorical_feature=cat)
            s_v4[pmask] = m4.predict_proba(long.loc[pmask, V4_FEATURES])[:, 1]

        long["s_v2"] = s_v2
        long["s_v4"] = s_v4
        long["s_v1"] = np.where(np.isnan(s_v2), np.nan, long["s_v1"])
        mask = long["s_v4"].notna()
        r1 = long.loc[mask].groupby("date")["s_v1"].rank(pct=True)
        r4 = long.loc[mask].groupby("date")["s_v4"].rank(pct=True)
        long["s_blend14"] = np.nan
        long.loc[mask, "s_blend14"] = (r1 + r4) / 2

        for col, label in (
            ("s_v1", "v1"),
            ("s_v2", "v2"),
            ("s_v4", "v4(lag+layout)"),
            ("s_blend14", "blend v1+v4"),
        ):
            r = evaluate(long, col)
            print(
                f"  {label:15s} lift={r['lift']:.2f}x prec={r['prec']:.3f}/base={r['base']:.3f} "
                f">=1台的中={r['hit_ge1']:.1%} (評価{r['days']}日)"
            )


if __name__ == "__main__":
    main()
