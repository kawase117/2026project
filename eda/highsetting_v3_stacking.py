# -*- coding: utf-8 -*-
"""v3実験: ジャグトラックのスタッキング/ブレンド比較

呼び出し: venv/Scripts/python.exe eda/highsetting_v3_stacking.py（単体実行）

背景: 蒲田7ジャグはv1（台効果×据置）1.81x > v2（LGBM）1.34x — LGBMが強い単純シグナルを
希釈する。v1スコアを特徴量としてLGBMに与える（stacked）、またはv1/v2のランク平均（blend）で
両者の長所を取れるか検証する。

戦略（同一walk-forward日程・同一評価プロトコルで比較）:
  v1     : m_rate_180 ×（前日高設定なら据置倍率）
  v2     : LGBM(既存FEATURES)
  stacked: LGBM(既存FEATURES + v1_score)
  blend  : 日内ランク百分位の平均 (v1 + v2) / 2
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

    for hall in HALLS:
        panel = build_labeled_panel(hall, "jug")
        long = build_features(panel).sort_values(["date", "machine_number"]).reset_index(drop=True)
        cond, base0 = carryover_diag(panel[["date", "machine_number", "evaluable", "is_high"]])
        carry = cond / base0 if base0 else 1.0
        long["v1_score"] = long["m_rate_180"] * np.where(long["prev_high"] > 0, carry, 1.0)

        dates = sorted(long["date"].unique())
        s_v2 = np.full(len(long), np.nan)
        s_st = np.full(len(long), np.nan)
        for start in range(WARMUP_DAYS, len(dates), RETRAIN_BLOCK):
            block = set(dates[start : start + RETRAIN_BLOCK])
            train = long[(long["date"] < dates[start]) & long["evaluable"]]
            if train["is_high"].sum() < 20:
                continue
            pmask = long["date"].isin(block).to_numpy()
            cat = ["dd", "weekday", "last_digit", "machine_cat"]
            m2 = lgb.LGBMClassifier(**LGB_PARAMS)
            m2.fit(train[FEATURES], train["is_high"].astype(int), categorical_feature=cat)
            s_v2[pmask] = m2.predict_proba(long.loc[pmask, FEATURES])[:, 1]
            feats_st = FEATURES + ["v1_score"]
            ms = lgb.LGBMClassifier(**LGB_PARAMS)
            ms.fit(train[feats_st], train["is_high"].astype(int), categorical_feature=cat)
            s_st[pmask] = ms.predict_proba(long.loc[pmask, feats_st])[:, 1]

        long["s_v2"] = s_v2
        long["s_st"] = s_st
        # v1は学習不要だが、評価日をv2と揃える
        long["s_v1"] = np.where(np.isnan(s_v2), np.nan, long["v1_score"])
        # blend: 日内ランク百分位の平均
        mask = long["s_v2"].notna()
        r1 = long.loc[mask].groupby("date")["s_v1"].rank(pct=True)
        r2 = long.loc[mask].groupby("date")["s_v2"].rank(pct=True)
        long["s_blend"] = np.nan
        long.loc[mask, "s_blend"] = (r1 + r2) / 2

        print(f"\n[{hall}] ジャグ 戦略比較（同一評価日程）")
        for col, label in (
            ("s_v1", "v1"),
            ("s_v2", "v2"),
            ("s_st", "stacked"),
            ("s_blend", "blend"),
        ):
            r = evaluate(long, col)
            print(
                f"  {label:8s} lift={r['lift']:.2f}x prec={r['prec']:.3f}/base={r['base']:.3f} "
                f">=1台的中={r['hit_ge1']:.1%} (評価{r['days']}日)"
            )


if __name__ == "__main__":
    main()
