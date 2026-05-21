# Tail LTR Checkpoint (2026-05-20)

## Scope
- Store: マルハンメガシティ2000-蒲田7（単店）
- Target: Top2（店舗平均超過 `excess = model_pm - store_day_pm`）
- Evaluation: Walk-Forward（未来データ固定評価）

## Current Status
- 厳密WF（再学習+閾値学習）Top2単独: `mean_excess +12.92`  
  Source: `db/experiments/tail_ltr_full_walkforward_ops_report.json`
- Top2 6h再探索ベスト（seed拡張）: `regime2_only + λ=0.75`  
  `mean_excess +10.48`, `95%CI [+1.20, +19.81]`, `p(excess>0)=0.986`  
  Source: `db/experiments/tail_ltr_top2_6h_best.json`
- 重負荷レジーム切替WF: `mean_excess +23.42`（608日）  
  Source: `db/experiments/tail_ltr_regime_switch_wf.csv`

## Wednesday Findings
- 水曜 vs 非水曜の分解（レジーム切替WF）:
  - Wednesday: `mean_excess -36.36`
  - NonWednesday: `mean_excess +32.48`
  - Gap: `-68.84`
- 水曜専用+非水曜専用の2系統WF:
  - Overall: `+13.60`
  - Wednesday only: `-24.98`
  - NonWednesday: `+20.03`
  Source: `db/experiments/tail_ltr_wed_dual_model_wf.json`

## Interpretation
- 「水曜は別法則」の可能性は高い。
- ただし、単純な曜日分割（同特徴量のまま）では改善せず。
- 次段階は「水曜専用特徴量」の導入が必須。

## Next Work (Planned)
1. 水曜専用特徴量（過去情報のみ）
- `tail_wed_win_rate_recent_8w`
- `tail_gap_since_last_wed_hit`
- `tail_wed_rotation_pos`
- `tail_entropy_wed_recent`

2. 比較実験（同一WF条件）
- Baseline: 重負荷レジーム切替WF
- Candidate A: 水曜専用特徴量 + 水曜モデル
- Candidate B: 水曜専用特徴量 + 水曜/非水曜ゲート

3. 採用判定
- `mean_excess > 0`
- `95%CI下限 > 0`
- `maxDD` が baseline より悪化しない
