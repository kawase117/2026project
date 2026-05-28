# Target Auto Explore Report

- output_root: `ml\last_digit\exploratory\kamata7_only\target_auto_explore_20260526_103548`
- top2_baseline_topk: `ml\last_digit\exploratory\kamata7_only\target_auto_explore_20260526_103548\top2_refit\run_xgb_ranker_ndcg_testperiod_topk.csv`

## Summary

```text
experiment target_label source_latest_date target_date  test_period_enabled       ceiling_status                                                                                                            ceiling_dir
top2_refit     is_top_2         2026-05-25  2026-05-26                 True                   ok                                                                                                                       
  t1_rank1    is_rank_1         2026-05-25  2026-05-26                 True                   ok ml\last_digit\exploratory\kamata7_only\target_auto_explore_20260526_103548\t1_rank1\run_xgb_ranker_ndcg_ceiling_effect
   t2_top3     is_top_3         2026-05-25  2026-05-26                 True                   ok  ml\last_digit\exploratory\kamata7_only\target_auto_explore_20260526_103548\t2_top3\run_xgb_ranker_ndcg_ceiling_effect
    worst1   is_worst_1         2026-05-25  2026-05-26                 True skipped_worst_target                                                                                                                       
```

## Worst1 Eval

- n: 435
- worst1_hit_rate: 0.7885057471264367
- worst2_cover_rate: 0.9747126436781609
- worst3_cover_rate: 0.9839080459770115
- pred1_negative_rate: 0.960919540229885
- pred1_hard_negative_rate: 0.8022988505747126
- pred1_diff_median: -13600.0
- pred1_diff_mean: -14118.16091954023
