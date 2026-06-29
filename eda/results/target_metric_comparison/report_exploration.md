# Part 1: Exploration

## Fixed Conditions
- DB: `C:\Users\apto117\Documents\pachinko-analyzer\src\2026project\db\マルハンメガシティ2000-蒲田7.db`
- min_games: `1500`
- history_days: `90`
- eval_days: `60`
- eval_rows: `36041`
- section_rows: `3110`

## Machine Metrics
| metric | spearman_rho | p_value | d0_hit104 | d9_hit104 | delta_pp |
| --- | --- | --- | --- | --- | --- |
| hit_104_rate | 0.042 | 0.000 | 0.290 | 0.372 | 0.082 |
| avg_payout | 0.029 | 0.000 | 0.338 | 0.377 | 0.038 |
| avg_diff | 0.013 | 0.013 | 0.339 | 0.359 | 0.020 |
| winsorized_diff | 0.011 | 0.041 | 0.339 | 0.360 | 0.020 |
| positive_rate | 0.003 | 0.514 | 0.331 | 0.343 | 0.012 |
| median_diff | -0.011 | 0.043 | 0.328 | 0.345 | 0.017 |
| median_payout | -0.015 | 0.005 | 0.342 | 0.344 | 0.003 |

## Section Metrics
| metric | spearman_rho | p_value | d0_section_hit_rate | d9_section_hit_rate | delta_pp |
| --- | --- | --- | --- | --- | --- |
| section_avg_hit_104_rate | 0.204 | 0.000 | 0.283 | 0.382 | 0.099 |
| section_avg_avg_payout | 0.150 | 0.000 | 0.327 | 0.364 | 0.037 |
| section_avg_avg_diff | 0.020 | 0.255 | 0.336 | 0.361 | 0.025 |
| section_avg_winsorized_diff | 0.000 | 0.981 | 0.335 | 0.359 | 0.024 |
| section_avg_positive_rate | -0.039 | 0.031 | 0.330 | 0.343 | 0.013 |
| section_avg_median_diff | -0.077 | 0.000 | 0.341 | 0.335 | -0.005 |
| section_avg_median_payout | -0.087 | 0.000 | 0.348 | 0.340 | -0.008 |

## Baseline
| metric | spearman_rho | p_value | d0_hit104 | d9_hit104 | delta_pp |
| --- | --- | --- | --- | --- | --- |
| hit_104_rate | 0.042 | 0.000 | 0.290 | 0.372 | 0.082 |
| metric | spearman_rho | p_value | d0_section_hit_rate | d9_section_hit_rate | delta_pp |
| --- | --- | --- | --- | --- | --- |
| section_avg_hit_104_rate | 0.204 | 0.000 | 0.283 | 0.382 | 0.099 |

Outputs written to `eda/results/target_metric_comparison`
