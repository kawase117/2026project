# -*- coding: utf-8 -*-
"""Phase 1a: ハナハナ・ATトラックのスペックベース高設定ラベル + 位置予測バックテスト

呼び出し: venv/Scripts/python.exe eda/highsetting_predictability_hana_at.py（単体実行）
再利用: eda/highsetting_predictability_phase0b.backtest(), eda/highsetting_base_rate_phase0.load_hall()

ラベル設計:
  - ハナハナ(キングハナハナ-30): BB確率+RB確率の二項尤度 → P(設定4以上)>=0.8
  - AT(モンキーターンV / スマスロ北斗の拳): RB回数=AT初当り（ユーザー確認済み・設定差あり）
    設定構成は{1,2,4,5,6}（スマスロは設定3なし）。RB単独の二項尤度 → P(設定4以上)>=0.8
スペック出典: 1geki.jp（2026-07-15取得）
  - キングハナハナ-30: https://1geki.jp/slot/s_kinghanahana2023/
  - スマスロ北斗の拳: https://1geki.jp/slot/s_sma_hokutonoken/
  - モンキーターンV: https://1geki.jp/slot/l_monkeyturn5/0/
出力: 集計のみ標準出力。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from eda.highsetting_base_rate_phase0 import HALLS, load_hall  # noqa: E402
from eda.highsetting_predictability_phase0b import backtest  # noqa: E402

P56_HIGH = 0.80

# 機種名は machine_detailed_results.machine_name と完全一致で照合
# （部分一致は「ニューキングハナハナ」「北斗の拳 転生の章2」等の誤マッチを生むため禁止）
SPEC_MASTER = {
    "キングハナハナ-30": {
        "track": "hana",
        "min_games": 2500,
        "high_settings": {4, 5, 6},
        # 設定: (BB確率, RB確率)
        "settings": {
            1: (1 / 292.0, 1 / 489.0),
            2: (1 / 280.0, 1 / 452.0),
            3: (1 / 268.0, 1 / 420.0),
            4: (1 / 257.0, 1 / 390.0),
            5: (1 / 244.0, 1 / 360.0),
            6: (1 / 232.0, 1 / 332.0),
        },
    },
    "スマスロ北斗の拳": {
        "track": "at",
        "min_games": 3000,
        "high_settings": {4, 5, 6},
        # 設定: RB(=AT初当り)確率のみ。BBは連チャン回数で設定差なしのため不使用
        "settings": {
            1: (None, 1 / 383.4),
            2: (None, 1 / 370.5),
            4: (None, 1 / 297.8),
            5: (None, 1 / 258.7),
            6: (None, 1 / 235.1),
        },
    },
    "モンキーターンV": {
        "track": "at",
        "min_games": 3000,
        "high_settings": {4, 5, 6},
        "settings": {
            1: (None, 1 / 299.8),
            2: (None, 1 / 295.5),
            4: (None, 1 / 258.8),
            5: (None, 1 / 235.7),
            6: (None, 1 / 222.9),
        },
    },
    # --- 技術介入機トラック（2026-07-16追加、1geki.jp収集） ---
    # 高設定定義: 4段階設定機は{5,6}（技術介入込みで機械割104%+）、6段階機は{4,5,6}
    # エウレカZERO TYPE-Aはスペック表の信頼できる取得ができず保留（要手動検証）
    "ディスクアップ2": {
        # https://1geki.jp/slot/s_discup2/ 設定3・4非搭載
        "track": "tech",
        "min_games": 2500,
        "high_settings": {5, 6},
        "settings": {
            1: (1 / 287.4, 1 / 496.5),
            2: (1 / 286.2, 1 / 436.9),
            5: (1 / 278.9, 1 / 422.8),
            6: (1 / 276.5, 1 / 397.2),
        },
    },
    "ディスクアップ ULTRAREMIX": {
        # https://1geki.jp/slot/l_discup_ur/ 設定3・4非搭載
        "track": "tech",
        "min_games": 2500,
        "high_settings": {5, 6},
        "settings": {
            1: (1 / 287.2, 1 / 495.3),
            2: (1 / 284.3, 1 / 477.2),
            5: (1 / 273.8, 1 / 398.6),
            6: (1 / 260.9, 1 / 334.1),
        },
    },
    "新ハナビ": {
        # https://1geki.jp/slot/s_shinhanabi/ 設定3・4非搭載
        "track": "tech",
        "min_games": 2500,
        "high_settings": {5, 6},
        "settings": {
            1: (1 / 277.7, 1 / 356.2),
            2: (1 / 268.6, 1 / 331.0),
            5: (1 / 256.0, 1 / 306.2),
            6: (1 / 248.2, 1 / 280.1),
        },
    },
    "スマスロ ハナビ": {
        # https://1geki.jp/slot/l_hanabi/ 設定3・4非搭載
        "track": "tech",
        "min_games": 2500,
        "high_settings": {5, 6},
        "settings": {
            1: (1 / 297.9, 1 / 394.8),
            2: (1 / 292.6, 1 / 358.1),
            5: (1 / 284.9, 1 / 313.6),
            6: (1 / 273.1, 1 / 282.5),
        },
    },
    "うみねこのなく頃に2": {
        # https://1geki.jp/slot/l_umineko2/ 6段階。完走型ARTのため観測合算が公表値より低く見える点に注意
        "track": "tech",
        "min_games": 2500,
        "high_settings": {4, 5, 6},
        "settings": {
            1: (1 / 362.1, 1 / 397.2),
            2: (1 / 350.5, 1 / 390.1),
            3: (1 / 337.8, 1 / 381.0),
            4: (1 / 327.7, 1 / 374.5),
            5: (1 / 319.7, 1 / 366.1),
            6: (1 / 313.6, 1 / 360.1),
        },
    },
}


def tech_range_ok(sub, spec) -> tuple[bool, str]:
    """ホール×機種のプール観測BB/RB率が公表レンジ内か（カウンター定義差の検出）"""
    g = float(sub["games_normalized"].sum())
    if g <= 0:
        return False, "no data"
    msgs = []
    for idx, col in ((0, "bb_count"), (1, "rb_count")):
        probs = [t[idx] for t in spec["settings"].values() if t[idx] is not None]
        if not probs:
            continue
        cnt = float(sub[col].sum())
        rate = cnt / g if cnt else 0.0
        lo, hi = min(probs) * 0.88, max(probs) * 1.06
        ok = bool(cnt) and lo <= rate <= hi
        msgs.append(f"{col[:2]}=1/{g / cnt:.0f}({'OK' if ok else 'NG'})" if cnt else f"{col[:2]}=N/A(NG)")
        if not ok:
            return False, " ".join(msgs)
    return True, " ".join(msgs)


def posterior_p_high(sub: pd.DataFrame, spec: dict) -> np.ndarray:
    """一様事前・二項尤度（BBはspecにあれば使用、RBは常時使用）で P(高設定) を返す"""
    n = sub["games_normalized"].to_numpy(dtype=float)
    bb = sub["bb_count"].to_numpy(dtype=float)
    rb = sub["rb_count"].to_numpy(dtype=float)
    settings = sorted(spec["settings"])
    logliks = []
    for s in settings:
        pb, pr = spec["settings"][s]
        ll = rb * np.log(pr) + (n - rb) * np.log1p(-pr)
        if pb is not None:
            ll = ll + bb * np.log(pb) + (n - bb) * np.log1p(-pb)
        logliks.append(ll)
    ll = np.vstack(logliks)
    ll -= ll.max(axis=0, keepdims=True)
    post = np.exp(ll)
    post /= post.sum(axis=0, keepdims=True)
    hi_idx = [i for i, s in enumerate(settings) if s in spec["high_settings"]]
    return post[hi_idx].sum(axis=0)


def build_panel(df: pd.DataFrame, names: list[str]) -> pd.DataFrame:
    """指定機種群のパネル（date, machine_number, evaluable, is_high）を構築"""
    parts = []
    for name in names:
        spec = SPEC_MASTER[name]
        sub = df[df["machine_name"] == name].copy()
        if sub.empty:
            continue
        sub["evaluable"] = sub["games_normalized"] >= spec["min_games"]
        sub["p_high"] = np.nan
        ev = sub[sub["evaluable"]]
        if len(ev):
            sub.loc[ev.index, "p_high"] = posterior_p_high(ev, spec)
        sub["is_high"] = (sub["p_high"] >= P56_HIGH).fillna(False)
        parts.append(sub[["date", "machine_number", "evaluable", "is_high"]])
    if not parts:
        return pd.DataFrame(columns=["date", "machine_number", "evaluable", "is_high"])
    return pd.concat(parts, ignore_index=True)


def report(hall: str, label: str, panel: pd.DataFrame) -> None:
    if panel.empty:
        print(f"  [{label}] 設置なし")
        return
    n_daily = panel.groupby("date")["machine_number"].size().mean()
    daily_high = panel[panel["evaluable"]].groupby("date")["is_high"].sum()
    if n_daily < 5:
        print(
            f"  [{label}] 設置台/日={n_daily:.1f} → 台数不足でバックテストスキップ "
            f"(高設定 平均{daily_high.mean():.2f}台/日)"
        )
        return
    r = backtest(panel)
    carry_mult = r["carry_cond"] / r["carry_base"] if r["carry_base"] else float("nan")
    print(
        f"  [{label}] 設置台/日={n_daily:.0f} 高設定平均{daily_high.mean():.2f}台/日 "
        f"0台の日={(daily_high == 0).mean():.0%}\n"
        f"    評価日数={r['eval_days']} precision@10%={r['precision']:.3f} "
        f"vs base={r['base_rate']:.3f} lift={r['lift']:.2f}x  "
        f">=1台的中の日={r['hit_ge1']:.1%}(ランダム{r['rand_hit_ge1']:.1%})\n"
        f"    据え置き: P(high|前日high)={r['carry_cond']:.3f} vs base={r['carry_base']:.3f} "
        f"(倍率{carry_mult:.2f}x)"
    )


def main() -> None:
    hana_names = [n for n, s in SPEC_MASTER.items() if s["track"] == "hana"]
    at_names = [n for n, s in SPEC_MASTER.items() if s["track"] == "at"]
    for hall, path in HALLS.items():
        df, _ = load_hall(path)
        print(f"\n{'=' * 70}\n[{hall}]")
        report(hall, "ハナハナ(キングハナハナ-30)", build_panel(df, hana_names))
        report(hall, "AT(モンキーV+北斗)", build_panel(df, at_names))


if __name__ == "__main__":
    main()
