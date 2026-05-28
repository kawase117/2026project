# 10時間プラン進捗

## Hour1: 2F_A評価
- available: True
- hit@2: 1.0
- rank1_match_rate: 0.9315068493150684
- top1_avg_diff_per_machine_median: 1300.0

## Hour2: BOTTOM3評価
- current_latest_day_overlap_mean: 0.5
- worst_model_ref_available: True
- worst1_hit_rate(ref): 0.7808219178082192

## Hour3-4: 朝サマリー
- file: `ml\last_digit\exploratory\kamata7_only\ten_hour_plan_20260527\hour3_morning_summary.txt`

## Hour5-6: 探索候補
- file: `ml\last_digit\exploratory\kamata7_only\ten_hour_plan_20260527\hour5_6_hypothesis_scout.md`

## Hour7-8: 次アクション
- `python -m ml.last_digit.target_auto_explore --db-path <最新DB> --output-root <新規dir>` を実行して再評価
