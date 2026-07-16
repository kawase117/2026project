# -*- coding: utf-8 -*-
"""高設定候補リストの答え合わせ（予測 vs 実績の自動記録）

使い方:
  venv\\Scripts\\python.exe run_highsetting_answercheck.py

処理:
  document/predictions/picks_*.json（run_highsetting_daily.py が出力）を走査し、
  DBに実績データが入った対象日の分を評価して answercheck_log.csv に追記する。
  評価済み (target, hall, track) はスキップ（再実行安全）。

指標:
  - hits: 候補のうち高設定ラベルが付いた台数（評価可能=規定G数以上回された候補のみ）
  - precision: hits / 評価可能候補数
  - day_base: 当日のトラック内高設定率（ランダム選択の期待精度）
  - lift: precision / day_base
出力: 追記後に累積サマリを標準出力へ表示。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from eda.highsetting_base_rate_phase0 import HALLS  # noqa: E402
from eda.highsetting_v2_scorer import build_labeled_panel  # noqa: E402

PRED_DIR = PROJECT_ROOT / "document" / "predictions"
LOG_PATH = PRED_DIR / "answercheck_log.csv"
LOG_COLS = [
    "target",
    "hall",
    "track",
    "model",
    "n_picks",
    "n_eval",
    "hits",
    "precision",
    "day_base",
    "lift",
    "picks_diff_mean",
    "pool_diff_mean",
    "diff_edge",
]


def load_day_diff(hall: str, target: str) -> pd.DataFrame:
    """対象日の台別差枚（答え合わせの差枚エッジ記録用）"""
    import sqlite3

    con = sqlite3.connect(HALLS[hall])
    df = pd.read_sql_query(
        "select machine_number, diff_coins_normalized from machine_detailed_results where date = ?",
        con,
        params=(target,),
    )
    con.close()
    return df


def load_log() -> pd.DataFrame:
    if LOG_PATH.exists():
        return pd.read_csv(LOG_PATH, dtype={"target": str})
    return pd.DataFrame(columns=LOG_COLS)


def main() -> None:
    log = load_log()
    done = set(zip(log["target"], log["hall"], log["track"]))
    new_rows = []
    panel_cache: dict[tuple[str, str], pd.DataFrame] = {}

    for path in sorted(PRED_DIR.glob("picks_*.json")):
        records = json.loads(path.read_text(encoding="utf-8"))
        df = pd.DataFrame(records)
        for (target, hall, track, model), grp in df.groupby(["target", "hall", "track", "model"]):
            if (target, hall, track) in done:
                continue
            key = (hall, track)
            if key not in panel_cache:
                panel_cache[key] = build_labeled_panel(hall, track)
            panel = panel_cache[key]
            day = panel[panel["date"] == target]
            if day.empty:
                print(f"  未評価（実績データ待ち）: {target} {hall}/{track}")
                continue
            merged = grp.merge(day, on="machine_number", how="left")
            ev = merged[merged["evaluable"].fillna(False)]
            pool = day[day["evaluable"]]
            day_base = pool["is_high"].mean() if len(pool) else float("nan")
            hits = int(ev["is_high"].sum())
            precision = ev["is_high"].mean() if len(ev) else float("nan")
            lift = precision / day_base if day_base else float("nan")
            # 差枚エッジ（評価可能候補の平均差枚 vs トラック内評価可能台の平均差枚）
            diff = load_day_diff(hall, target)
            picks_diff = diff[diff["machine_number"].isin(ev["machine_number"])]["diff_coins_normalized"].mean()
            pool_diff = diff[diff["machine_number"].isin(pool["machine_number"])]["diff_coins_normalized"].mean()
            diff_edge = picks_diff - pool_diff if picks_diff == picks_diff and pool_diff == pool_diff else float("nan")
            new_rows.append(
                {
                    "target": target,
                    "hall": hall,
                    "track": track,
                    "model": model,
                    "n_picks": len(grp),
                    "n_eval": len(ev),
                    "hits": hits,
                    "precision": round(precision, 4) if precision == precision else "",
                    "day_base": round(day_base, 4) if day_base == day_base else "",
                    "lift": round(lift, 3) if lift == lift else "",
                    "picks_diff_mean": round(picks_diff, 1) if picks_diff == picks_diff else "",
                    "pool_diff_mean": round(pool_diff, 1) if pool_diff == pool_diff else "",
                    "diff_edge": round(diff_edge, 1) if diff_edge == diff_edge else "",
                }
            )
            done.add((target, hall, track))
            print(
                f"  評価: {target} {hall}/{track}({model}) "
                f"候補{len(grp)}台(評価可能{len(ev)}) 的中{hits}台 "
                f"precision={precision:.3f} base={day_base:.3f}"
            )

    if new_rows:
        log = pd.concat([log, pd.DataFrame(new_rows)], ignore_index=True)
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        log.to_csv(LOG_PATH, index=False, encoding="utf-8")
        print(f"\n{len(new_rows)}件を追記: {LOG_PATH}")
    else:
        print("\n新規評価なし")

    if len(log):
        print("\n=== 累積サマリ（ホール×トラック） ===")
        num = log.copy()
        for c in ("precision", "day_base", "hits", "n_eval", "diff_edge"):
            if c in num.columns:
                num[c] = pd.to_numeric(num[c], errors="coerce")
        g = num.groupby(["hall", "track"]).agg(
            days=("target", "nunique"),
            hits=("hits", "sum"),
            n_eval=("n_eval", "sum"),
            mean_prec=("precision", "mean"),
            mean_base=("day_base", "mean"),
            diff_edge=("diff_edge", "mean"),
        )
        g["lift"] = g["mean_prec"] / g["mean_base"]
        print(g.round(3).to_string())


if __name__ == "__main__":
    main()
