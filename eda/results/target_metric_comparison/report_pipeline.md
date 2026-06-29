# Part 2: Pipeline

## Fixed Conditions
- top_k_sections: `5`
- top_n_machines: `5`
- chosen_metrics: `hit_104_rate, avg_payout, avg_diff`

## Strategy Comparison
| strategy | top_k_sec | top_n_machine | total_n | hit_104_rate | baseline | lift |
| --- | --- | --- | --- | --- | --- | --- |
| section_avg_hit_104_rate × hit_104_rate | 5 | 5 | 1481 | 0.404 | 0.404 | 1.000 |
| section_avg_avg_payout × avg_payout | 5 | 5 | 1481 | 0.375 | 0.404 | 0.927 |
| section_avg_avg_diff × avg_diff | 5 | 5 | 1474 | 0.355 | 0.404 | 0.877 |

Outputs written to `eda/results/target_metric_comparison`
