# -*- coding: utf-8 -*-
"""日次高設定候補リスト生成（4ホール × ジャグ/AT/ハナハナ）

使い方:
  venv\\Scripts\\python.exe run_highsetting_daily.py            # 各ホールのDB最新日+1日を対象
  venv\\Scripts\\python.exe run_highsetting_daily.py --target 20260716

前提: db/<ホール>.db が最新までスクレイプ済みであること（対象日の前日データまで必要）。
出力: 標準出力 + document/predictions/<target>_highsetting_candidates.md

モデル: ホール×トラック別チャンピオン（2026-07-15 walk-forward比較で確定）
  - v1 = 経験ベイズ（台別縮小率×据置倍率）
  - v2 = LightGBM（位置・カレンダー・履歴特徴量、全履歴で学習）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from eda.highsetting_base_rate_phase0 import HALLS  # noqa: E402
from eda.highsetting_v2_scorer import (  # noqa: E402
    FEATURES,
    LGB_PARAMS,
    build_features,
    build_labeled_panel,
)
from eda.highsetting_v4_features import V4_FEATURES, augment_v4  # noqa: E402

# walk-forward比較（warmup180日・同一評価窓）で確定したチャンピオンとlift実績
CHAMPIONS = {
    # jug: 2026-07-16 v4実験（lag+layout特徴量）でみとや=v4 1.60x、蒲田1=blend14 1.57xが最良。
    # ただし5戦略中の事後選択（多重比較バイアス）を含むため、answercheck_logの前方成績で要追認
    ("楽園蒲田", "jug"): ("v2", 1.26),
    ("蒲田7", "jug"): ("v1", 1.81),
    ("蒲田1", "jug"): ("blend14", 1.57),
    ("みとや", "jug"): ("v4", 1.60),
    # AT: 2026-07-16 エウレカTYPE-ART追加・戦国乙女4(K7/楽園/みとや)除外の新採用マスタで再検証
    ("楽園蒲田", "at"): ("v1", 1.91),
    ("蒲田7", "at"): ("v1", 2.66),
    ("蒲田1", "at"): ("v2", 1.90),
    ("みとや", "at"): ("v1", 2.22),
    ("楽園蒲田", "hana"): ("v2", 1.38),
    ("蒲田7", "hana"): ("v2", 1.14),
    ("蒲田1", "hana"): ("v2", 1.23),
    # みとや hana は設置なし
    # tech（技術介入機）: 2026-07-16検証。楽園のみv1 1.40xで採用。
    # K7=エッジなし(v1 0.43x/v2 0.99x)・みとや=高設定0.10台/日と薄すぎ・K1=台数不足のため非搭載
    ("楽園蒲田", "tech"): ("v1", 1.40),
}

PICK_RATIO = 0.10
MITOYA_EVENT_DDS = {1, 4, 7, 14, 17, 24, 27, 30}


def next_day(yyyymmdd: str) -> str:
    return (pd.Timestamp(yyyymmdd) + pd.Timedelta(days=1)).strftime("%Y%m%d")


def carry_multiplier(panel: pd.DataFrame) -> float:
    """v1用の据置倍率 P(high|前日high)/base を全履歴から推定"""
    p = panel[panel["evaluable"]].copy()
    dates = sorted(p["date"].unique())
    didx = {d: i for i, d in enumerate(dates)}
    p["di"] = p["date"].map(didx)
    prev = p[["di", "machine_number", "is_high"]].copy()
    prev["di"] += 1
    m = p.merge(prev, on=["di", "machine_number"], suffixes=("", "_prev"), how="inner")
    base = m["is_high"].mean()
    if not base:
        return 1.0
    cond = m.loc[m["is_high_prev"], "is_high"].mean()
    return float(cond / base) if cond == cond else 1.0


def score_track(hall: str, track: str, target: str | None):
    key = (hall, track)
    if key not in CHAMPIONS:
        return None
    model_name, lift = CHAMPIONS[key]
    panel = build_labeled_panel(hall, track)
    if panel.empty:
        return None
    if target:
        # as-of再現: 対象日より前のデータのみ使用（過去日の予測再生成＝答え合わせ用バックフィルにも対応）
        panel = panel[panel["date"] < target]
        if panel.empty:
            return None
    last_date = panel["date"].max()
    target_date = target or next_day(last_date)
    if next_day(last_date) != target_date:
        print(f"  (注意: {hall}/{track} データ最終日{last_date}と対象日{target_date}に間隔あり)")

    # 対象日の合成行（前営業日の設置ラインナップを引き継ぐ）
    last_rows = panel[panel["date"] == last_date][["machine_number", "machine_name"]]
    synth = last_rows.assign(date=target_date, evaluable=False, is_high=False)
    panel_ext = pd.concat([panel, synth], ignore_index=True)
    long = build_features(panel_ext)
    tomorrow = long[long["date"] == target_date].copy()
    hist = long[long["date"] < target_date]

    if model_name in ("v2", "v4", "blend14"):
        import lightgbm as lgb

        feats = FEATURES if model_name == "v2" else V4_FEATURES
        if model_name != "v2":
            long = augment_v4(long, hall)
            tomorrow = long[long["date"] == target_date].copy()
            hist = long[long["date"] < target_date]
        train = hist[hist["evaluable"]]
        model = lgb.LGBMClassifier(**LGB_PARAMS)
        model.fit(
            train[feats],
            train["is_high"].astype(int),
            categorical_feature=["dd", "weekday", "last_digit", "machine_cat"],
        )
        tomorrow["score"] = model.predict_proba(tomorrow[feats])[:, 1]
        if model_name == "blend14":
            cm = carry_multiplier(panel)
            v1 = tomorrow["m_rate_180"] * np.where(tomorrow["prev_high"] > 0, cm, 1.0)
            tomorrow["score"] = (
                tomorrow["score"].rank(pct=True) + pd.Series(v1, index=tomorrow.index).rank(pct=True)
            ) / 2
    else:
        cm = carry_multiplier(panel)
        tomorrow["score"] = tomorrow["m_rate_180"] * np.where(tomorrow["prev_high"] > 0, cm, 1.0)

    n_pick = max(1, int(np.ceil(len(tomorrow) * PICK_RATIO)))
    picks = tomorrow.nlargest(n_pick, "score")

    # 日レベル文脈: 対象DDの過去平均高設定台数
    ev_hist = panel[panel["evaluable"]].copy()
    ev_hist["dd"] = ev_hist["date"].str[6:8].astype(int)
    daily = ev_hist.groupby("date").agg(hi=("is_high", "sum"), dd=("dd", "first"))
    dd_t = int(target_date[6:8])
    ctx = {
        "model": model_name,
        "backtest_lift": lift,
        "target": target_date,
        "last_data": last_date,
        "dd_avg_high": float(daily.loc[daily["dd"] == dd_t, "hi"].mean()),
        "all_avg_high": float(daily["hi"].mean()),
        "n_pool": len(tomorrow),
        "mitoya_abstain": (hall == "みとや" and dd_t not in MITOYA_EVENT_DDS),
    }
    return picks, ctx


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=None, help="対象日 YYYYMMDD（省略時は各DB最新日+1）")
    args = ap.parse_args()

    lines = []
    pick_records = []
    header_date = args.target or "auto"
    lines.append(f"# 高設定候補リスト（対象日: {header_date}）\n")
    for hall in HALLS:
        for track, tlabel in (
            ("jug", "ジャグ"),
            ("at", "AT"),
            ("hana", "ハナハナ"),
            ("tech", "技術介入"),
        ):
            out = score_track(hall, track, args.target)
            if out is None:
                continue
            picks, ctx = out
            note = ""
            if ctx["mitoya_abstain"]:
                note = " ⚠非イベントDD: 高設定ゼロの可能性が高く棄権推奨"
            dd_ratio = ctx["dd_avg_high"] / ctx["all_avg_high"] if ctx["all_avg_high"] else float("nan")
            lines.append(
                f"\n## {hall} / {tlabel}（{ctx['model']}, 検証lift {ctx['backtest_lift']:.2f}x）"
                f"{note}\n"
                f"- 対象日: {ctx['target']}（データ最終日: {ctx['last_data']}）\n"
                f"- このDDの過去平均高設定: {ctx['dd_avg_high']:.2f}台/日"
                f"（全日平均 {ctx['all_avg_high']:.2f}、比 {dd_ratio:.2f}x）\n"
            )
            lines.append("| 台番号 | 機種 | スコア | 180日高設定率 | 前日高設定 |")
            lines.append("|---:|---|---:|---:|:--:|")
            for _, row in picks.iterrows():
                lines.append(
                    f"| {row['machine_number']} | {row['machine_name']} "
                    f"| {row['score']:.4f} | {row['m_rate_180']:.3f} "
                    f"| {'○' if row['prev_high'] > 0 else ''} |"
                )
                pick_records.append(
                    {
                        "hall": hall,
                        "track": track,
                        "model": ctx["model"],
                        "target": ctx["target"],
                        "machine_number": int(row["machine_number"]),
                        "machine_name": row["machine_name"],
                        "score": float(row["score"]),
                    }
                )
    report = "\n".join(lines)
    print(report)
    target_label = args.target or "auto"
    out_dir = PROJECT_ROOT / "document" / "predictions"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{target_label}_highsetting_candidates.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"\n保存: {out_path}")
    if pick_records:
        import json

        resolved = max(r["target"] for r in pick_records)
        picks_path = out_dir / f"picks_{resolved}.json"
        picks_path.write_text(json.dumps(pick_records, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"保存: {picks_path}（答え合わせ用）")


if __name__ == "__main__":
    main()
