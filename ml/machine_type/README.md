# Machine-Type ML

## 目的

`machine_name` 単位で翌日予測と信頼度チェックを行います。  
リーク対策として、予測時は実績列を特徴量から除外し、履歴特徴は `shift(1)` の prior-only で生成します。

## 実行コマンド

```powershell
venv\Scripts\python.exe -m ml.machine_type.machine_type_nextday --help
venv\Scripts\python.exe -m ml.machine_type.machine_type_monthly_check --help
venv\Scripts\python.exe -m ml.machine_type.machine_type_alpha_sensitivity --help
```

```powershell
venv\Scripts\python.exe -m ml.machine_type.machine_type_nextday --alpha 5.0 --model-type xgb --gpu-backend auto
venv\Scripts\python.exe -m ml.machine_type.machine_type_monthly_check --alpha 5.0 --eval-days 60 --model-type xgb --gpu-backend auto
venv\Scripts\python.exe -m ml.machine_type.machine_type_alpha_sensitivity --alphas 1,3,5,10 --eval-days 60 --model-type xgb --gpu-backend auto
```

```powershell
venv\Scripts\python.exe -m ml.machine_type.machine_type_nextday --alpha 0.5 --model-type sgd --gpu-backend cpu --segment-mode floor2 --segment-blend-weight 0.5 --prior-blend-weight 0.2 --recommend-k 3 --enforce-floor-diversity --min-confidence-margin 0.02
```

## 出力先

すべて `ml/machine_type/reports/` に出力されます。

## 主要ファイル

- `machine_type_nextday_prediction.csv`
  - 翌日ランキング（`nextday_rank`, `ensemble_score`）と `is_rank_1/is_top_2/is_top_3/is_top_5` の確率
  - `recommended_pick` / `recommended_pick_rank`（2F/3F制約付き推奨）
- `machine_type_nextday_prediction.json`
  - しきい値、`model_type`、`backend_used_by_target`、`skip_suggested` を含むサマリー
- `machine_type_nextday_prediction_audit_report.json`
  - 欠損・重複・新規機種件数などの監査結果
- `machine_type_reliability_daily.csv`
  - 日次 `F1/Recall/Precision/Hit@1/2/3/5` と `known_coverage`（未知機種を除いた予測可能率）
- `machine_type_reliability_monthly.csv`
  - 月次集計（`is_thursday` 切り）
- `machine_type_alpha_sensitivity_light.csv`
  - alpha ごとの軽量感度結果
- `machine_type_alpha_sensitivity_light_best.csv`
  - ターゲット別・木曜/非木曜別の最良 alpha

## リーク防止の実装方針

- `FORECAST_EXCLUDED_COLUMNS` に実績系列を定義し、予測特徴量から除外
- 履歴系は `shift(1)` / rolling / expanding を使用（当日値を使わない）
- 月次評価は各 `pred_date` ごとに「前日までの履歴 + 当日プレースホルダ」を作成し、`train_end < pred_date` を強制
- DB開始以前から存在していた機種の誤新台判定を避けるため、`is_left_censored` と `new_machine_flag_effective` を併用

## GPU 利用

- `--model-type xgb` + `--gpu-backend auto/cuda/gpu_hist` で GPU 実行
- `--gpu-backend auto` は GPU 初期化失敗時に CPU へフォールバック
- `--model-type sgd` は常に CPU

### prior blend
- `--prior-blend-weight` can blend model probabilities with prior target-rate features (`prior_rank1_rate`, `prior_top2_rate`, `prior_top3_rate`, `prior_top5_rate`).
- `0.0` uses model-only probabilities, `1.0` uses prior-only scores.

## 2026-05-23 evaluation snapshot

### Commands executed

```powershell
# Baseline (xgb)
venv\Scripts\python.exe -m ml.machine_type.machine_type_monthly_check --model-type xgb --eval-days 60 --output-prefix ml/machine_type/reports/machine_type_reliability_xgb_eval60

# LTR variants
venv\Scripts\python.exe -m ml.machine_type.machine_type_monthly_check --model-type ltr --eval-days 60 --output-prefix ml/machine_type/reports/machine_type_reliability_ltr_eval60
venv\Scripts\python.exe -m ml.machine_type.machine_type_monthly_check --model-type ltr --ltr-objective rank:pairwise --ltr-decay-lambda 0.3 --eval-days 60 --output-prefix ml/machine_type/reports/machine_type_reliability_ltr_pairwise_d03_eval60
venv\Scripts\python.exe -m ml.machine_type.machine_type_monthly_check --model-type ltr --ltr-objective rank:ndcg --ltr-decay-lambda 0.0 --eval-days 60 --output-prefix ml/machine_type/reports/machine_type_reliability_ltr_ndcg_d00_eval60
venv\Scripts\python.exe -m ml.machine_type.machine_type_monthly_check --model-type ltr --ltr-objective rank:ndcg --ltr-decay-lambda 0.6 --eval-days 60 --output-prefix ml/machine_type/reports/machine_type_reliability_ltr_ndcg_d06_eval60
```

### Key comparison outputs

- `ml/machine_type/reports/machine_type_model_compare_eval60.csv`
  - per-target `hit_at_1`, `hit_at_3`, `f1`, `base_rate`, `base_rate_x3`, and lift ratios.
- `ml/machine_type/reports/machine_type_feature_group_ablation_eval30.csv`
  - feature-group ablation (`all`, `no_cross_section`, `no_rank_trend`, `no_smooth_ewm`).

### Current best (eval60 composite on top2/top3/top5)

- Winner: `xgb_default`
- Composite score definition: `0.6 * mean(hit_at_3) + 0.4 * mean(f1)` over `is_top_2/is_top_3/is_top_5`.
- Next-day run:
  - `ml/machine_type/reports/machine_type_nextday_xgb_eval60_winner.csv`
  - `ml/machine_type/reports/machine_type_nextday_xgb_eval60_winner.json`

### Follow-up tuning (2026-05-23 later run)

- Shortlist test (`eval12`) showed `no_smooth_ewm` slightly better than `all`.
  - `ml/machine_type/reports/machine_type_xgb_global_ablation_eval12_compare.csv`
- Medium-horizon confirmation (`eval40`) preserved the same direction:
  - `no_smooth_ewm` > `all`
  - file: `ml/machine_type/reports/machine_type_xgb_all_vs_noSmooth_compare.csv`
- Reference `eval60` winner remains `xgb_default` from the full comparison matrix:
  - `ml/machine_type/reports/machine_type_model_compare_eval60.csv`

## 2026-05-24 execution (ordered plan)

### 1) eval60 split runner

Use split runner for timeout-safe evaluation:

```powershell
venv\Scripts\python.exe -m ml.machine_type.machine_type_eval_split_runner --model-type xgb --eval-days-total 60 --batch-size 20 ...
```

### 2) no_smooth_ewm_no_rank_trend (eval30)

- Compare:
  - `no_smooth_ewm`
  - `no_smooth_ewm_no_rank_trend`
- Result:
  - `no_smooth_ewm_no_rank_trend` won at eval30.
- File:
  - `ml/machine_type/reports/machine_type_noSmooth_vs_noRank_eval30_compare.csv`

### 3) winner features eval60 (split)

- Run:
  - `xgb + global + no_smooth_ewm_no_rank_trend`
  - `eval_days_total=60, batch_size=20`
- Output:
  - `ml/machine_type/reports/machine_type_reliability_xgb_global_noSmoothEwmNoRank_eval60_split_daily.csv`

### 4) hybrid evaluation

- Evaluated:
  - rank1 from `ltr_ndcg_d00`
  - top2/3/5 from `xgb`
- Result:
  - No improvement vs xgb-only in this feature set.
- File:
  - `ml/machine_type/reports/machine_type_hybrid_compare_eval60_split.csv`

### 5) floor2 specialization

- Compared at eval30:
  - `global` vs `floor2 (blend=1.0 / 0.7)`
- Result:
  - `floor2, blend=0.7` was best at eval30.
- File:
  - `ml/machine_type/reports/machine_type_floor2_specialization_eval30_compare.csv`

### 6) Thursday/non-Thursday threshold split

- Full eval20/30 was too expensive in current implementation.
- Smoke eval3 showed degradation for threshold split.
- File:
  - `ml/machine_type/reports/machine_type_thsplit_smoke_compare.csv`

### 7) skip logic optimization

- Sweep over `top1-top2` margin on eval20 replay.
- Current best utility was `margin=0.00` (no skip).
- Files:
  - `ml/machine_type/reports/machine_type_skip_tuning_eval20.csv`
  - `ml/machine_type/reports/machine_type_skip_tuning_raw_eval20.csv`

### 8) nextday fixed output

- Finalized output (current best stable setting):
  - `ml/machine_type/reports/machine_type_nextday_xgb_global_noSmoothNoRank_final.csv`
  - `ml/machine_type/reports/machine_type_nextday_xgb_global_noSmoothNoRank_final.json`
