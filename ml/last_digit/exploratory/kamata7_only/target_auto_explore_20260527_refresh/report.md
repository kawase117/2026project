# Target Auto Explore Report

- output_root: `ml\last_digit\exploratory\kamata7_only\target_auto_explore_20260527_refresh`
- top2_baseline_topk: `ml\last_digit\exploratory\kamata7_only\target_auto_explore_20260527_refresh\top2_refit\run_xgb_ranker_ndcg_testperiod_topk.csv`

## Summary

```text
experiment target_label source_latest_date target_date  test_period_enabled       ceiling_status                                                                                                             ceiling_dir
top2_refit     is_top_2         2026-05-26  2026-05-27                 True                   ok                                                                                                                        
  t1_rank1    is_rank_1         2026-05-26  2026-05-27                 True                   ok ml\last_digit\exploratory\kamata7_only\target_auto_explore_20260527_refresh\t1_rank1\run_xgb_ranker_ndcg_ceiling_effect
   t2_top3     is_top_3         2026-05-26  2026-05-27                 True                   ok  ml\last_digit\exploratory\kamata7_only\target_auto_explore_20260527_refresh\t2_top3\run_xgb_ranker_ndcg_ceiling_effect
    worst1   is_worst_1         2026-05-26  2026-05-27                 True skipped_worst_target                                                                                                                        
```

## Worst1 Eval

- n: 584
- worst1_hit_rate: 0.7808219178082192
- worst2_cover_rate: 0.9794520547945206
- worst3_cover_rate: 0.9863013698630136
- pred1_negative_rate: 0.9674657534246576
- pred1_hard_negative_rate: 0.6352739726027398
- pred1_diff_median: -7800.0
- pred1_diff_mean: -11418.493150684932
