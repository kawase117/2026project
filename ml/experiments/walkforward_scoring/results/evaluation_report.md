# Section Prediction Evaluation

## Pooled Correlation
- Section score vs section hit rate: rho=0.172, p=0.0000
- Machine hist_metric vs hit flag: rho=-0.013, p=0.4959

## Summary by Top-K Sections
| top_k | section_baseline_rate_pct | section_top_rate_pct | section_lift | selected_machine_count | machine_baseline_rate_pct | selected_machine_rate_pct | selected_machine_lift | global_hist_rate_pct | global_hist_lift |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1.0 | 31.7 | 38.0 | 1.2 | 4.8 | 31.6 | 39.6 | 1.3 | 34.0 | 1.1 |
| 3.0 | 31.7 | 36.3 | 1.1 | 14.6 | 31.6 | 37.4 | 1.2 | 36.6 | 1.2 |
| 5.0 | 31.7 | 35.9 | 1.1 | 24.6 | 31.6 | 36.8 | 1.2 | 34.4 | 1.1 |
| 10.0 | 31.7 | 35.7 | 1.1 | 49.1 | 31.6 | 35.9 | 1.1 | 34.7 | 1.1 |

## Evaluation Files
- Section rows: 3172
- Summary rows: 240
- Machine rows: 2948

