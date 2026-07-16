# -*- coding: utf-8 -*-
"""Phase 0c: ATトラックの高設定プロキシ位置予測（walk-forward）

呼び出し: venv/Scripts/python.exe eda/highsetting_predictability_at.py（単体実行）
eda/highsetting_predictability_phase0b.py の backtest() を再利用。
ラベル: games_normalized>=5000 かつ 機械割>=108% を高設定プロキシとする。
データ: db/<ホール>.db machine_detailed_results / machine_master（Phase 0bと同じ列）
出力: 集計のみ標準出力。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from eda.highsetting_base_rate_phase0 import HALLS, load_hall  # noqa: E402
from eda.highsetting_predictability_phase0b import backtest  # noqa: E402

MIN_GAMES_AT = 5000
AT_PAYOUT_HIGH = 108.0


def build_at_panel(path: Path):
    df, master = load_hall(path)
    df = df.merge(master, left_on="machine_name", right_on="machine_name_normalized", how="left")
    at = df[df["bt_flag"] == 1].copy()
    at["payout"] = 100.0 + at["diff_coins_normalized"] / (at["games_normalized"] * 3.0) * 100.0
    at["evaluable"] = at["games_normalized"] >= MIN_GAMES_AT
    at["is_high"] = at["evaluable"] & (at["payout"] >= AT_PAYOUT_HIGH)
    return at[["date", "machine_number", "evaluable", "is_high"]]


def main() -> None:
    for hall, path in HALLS.items():
        panel = build_at_panel(path)
        n_daily = panel.groupby("date")["machine_number"].size().mean()
        if n_daily < 8:
            print(f"\n[{hall}] AT設置台/日={n_daily:.0f} → 台数不足でスキップ")
            continue
        r = backtest(panel)
        print(
            f"\n[{hall}] AT(>={MIN_GAMES_AT}G, 機械割>={AT_PAYOUT_HIGH}%) 設置台/日={n_daily:.0f}\n"
            f"  評価日数={r['eval_days']}  precision@10%={r['precision']:.3f} "
            f"vs base={r['base_rate']:.3f}  lift={r['lift']:.2f}x\n"
            f"  平均的中台数/日={r['avg_hits']:.2f}  >=1台的中の日={r['hit_ge1']:.1%} "
            f"(ランダム期待={r['rand_hit_ge1']:.1%})  候補の評価可能率={r['pick_eval_share']:.1%}\n"
            f"  据え置き診断: P(high|前日high)={r['carry_cond']:.3f} "
            f"vs base={r['carry_base']:.3f} (倍率{r['carry_cond'] / r['carry_base']:.2f}x)"
        )


if __name__ == "__main__":
    main()
