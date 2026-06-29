# 予測粒度シフト実験: 台×週

## 固定前提
- DB: `C:\Users\apto117\Documents\pachinko-analyzer\src\2026project\db\マルハンメガシティ2000-蒲田7.db`
- min_games: `1500`
- history_days: `90`
- eval_weeks: `12`
- thresholds: `100.0, 101.0, 102.0, 103.0`
- top_k: `1, 3, 5`

## データ概要
| metric | mean_pct | median_pct | n_rows | n_weeks | n_machines |
| --- | --- | --- | --- | --- | --- |
| week_avg_payout_pct | 100.662 | 99.314 | 8452 | 12 | 714 |

## 数値特徴量
| feature | n | n_bins | spearman_rho | p_value | d0_mean_pct | d9_mean_pct | delta_pp |
| --- | --- | --- | --- | --- | --- | --- | --- |
| hist_metric_pct | 8452 | 10 | 0.043 | 0.000 | 99.892 | 102.120 | 2.228 |
| debut_days_since | 2663 | 10 | 0.030 | 0.121 | 100.155 | 101.245 | 1.089 |
| prev_week_avg_payout_pct | 8452 | 10 | 0.012 | 0.264 | 101.324 | 101.748 | 0.424 |
| prev_week_positive_days | 8452 | 5 | -0.006 | 0.589 | 101.236 | 100.309 | -0.927 |

## Lift テーブル
| feature | threshold | top_k | baseline_rate | selected_rate | lift | selected_n | baseline_n |
| --- | --- | --- | --- | --- | --- | --- | --- |
| hist_metric_pct | 100.000 | 1 | 0.461 | 0.417 | 0.903 | 12 | 8452 |
| hist_metric_pct | 100.000 | 3 | 0.461 | 0.444 | 0.963 | 36 | 8452 |
| hist_metric_pct | 100.000 | 5 | 0.461 | 0.450 | 0.975 | 60 | 8452 |
| hist_metric_pct | 101.000 | 1 | 0.407 | 0.417 | 1.023 | 12 | 8452 |
| hist_metric_pct | 101.000 | 3 | 0.407 | 0.417 | 1.023 | 36 | 8452 |
| hist_metric_pct | 101.000 | 5 | 0.407 | 0.433 | 1.064 | 60 | 8452 |
| hist_metric_pct | 102.000 | 1 | 0.353 | 0.417 | 1.182 | 12 | 8452 |
| hist_metric_pct | 102.000 | 3 | 0.353 | 0.361 | 1.024 | 36 | 8452 |
| hist_metric_pct | 102.000 | 5 | 0.353 | 0.383 | 1.087 | 60 | 8452 |
| hist_metric_pct | 103.000 | 1 | 0.305 | 0.333 | 1.092 | 12 | 8452 |
| hist_metric_pct | 103.000 | 3 | 0.305 | 0.306 | 1.001 | 36 | 8452 |
| hist_metric_pct | 103.000 | 5 | 0.305 | 0.317 | 1.037 | 60 | 8452 |
| prev_week_avg_payout_pct | 100.000 | 1 | 0.461 | 0.417 | 0.903 | 12 | 8452 |
| prev_week_avg_payout_pct | 100.000 | 3 | 0.461 | 0.444 | 0.963 | 36 | 8452 |
| prev_week_avg_payout_pct | 100.000 | 5 | 0.461 | 0.467 | 1.012 | 60 | 8452 |
| prev_week_avg_payout_pct | 101.000 | 1 | 0.407 | 0.417 | 1.023 | 12 | 8452 |
| prev_week_avg_payout_pct | 101.000 | 3 | 0.407 | 0.389 | 0.955 | 36 | 8452 |
| prev_week_avg_payout_pct | 101.000 | 5 | 0.407 | 0.433 | 1.064 | 60 | 8452 |
| prev_week_avg_payout_pct | 102.000 | 1 | 0.353 | 0.333 | 0.945 | 12 | 8452 |
| prev_week_avg_payout_pct | 102.000 | 3 | 0.353 | 0.361 | 1.024 | 36 | 8452 |
| prev_week_avg_payout_pct | 102.000 | 5 | 0.353 | 0.383 | 1.087 | 60 | 8452 |
| prev_week_avg_payout_pct | 103.000 | 1 | 0.305 | 0.333 | 1.092 | 12 | 8452 |
| prev_week_avg_payout_pct | 103.000 | 3 | 0.305 | 0.306 | 1.001 | 36 | 8452 |
| prev_week_avg_payout_pct | 103.000 | 5 | 0.305 | 0.317 | 1.037 | 60 | 8452 |
| prev_week_positive_days | 100.000 | 1 | 0.461 | 0.500 | 1.084 | 12 | 8452 |
| prev_week_positive_days | 100.000 | 3 | 0.461 | 0.500 | 1.084 | 36 | 8452 |
| prev_week_positive_days | 100.000 | 5 | 0.461 | 0.467 | 1.012 | 60 | 8452 |
| prev_week_positive_days | 101.000 | 1 | 0.407 | 0.333 | 0.819 | 12 | 8452 |
| prev_week_positive_days | 101.000 | 3 | 0.407 | 0.417 | 1.023 | 36 | 8452 |
| prev_week_positive_days | 101.000 | 5 | 0.407 | 0.350 | 0.860 | 60 | 8452 |
| prev_week_positive_days | 102.000 | 1 | 0.353 | 0.333 | 0.945 | 12 | 8452 |
| prev_week_positive_days | 102.000 | 3 | 0.353 | 0.417 | 1.182 | 36 | 8452 |
| prev_week_positive_days | 102.000 | 5 | 0.353 | 0.317 | 0.898 | 60 | 8452 |
| prev_week_positive_days | 103.000 | 1 | 0.305 | 0.250 | 0.819 | 12 | 8452 |
| prev_week_positive_days | 103.000 | 3 | 0.305 | 0.389 | 1.274 | 36 | 8452 |
| prev_week_positive_days | 103.000 | 5 | 0.305 | 0.300 | 0.983 | 60 | 8452 |
| debut_days_since | 100.000 | 1 | 0.449 | 0.333 | 0.742 | 12 | 2663 |
| debut_days_since | 100.000 | 3 | 0.449 | 0.278 | 0.618 | 36 | 2663 |
| debut_days_since | 100.000 | 5 | 0.449 | 0.333 | 0.742 | 60 | 2663 |
| debut_days_since | 101.000 | 1 | 0.370 | 0.333 | 0.901 | 12 | 2663 |
| debut_days_since | 101.000 | 3 | 0.370 | 0.278 | 0.751 | 36 | 2663 |
| debut_days_since | 101.000 | 5 | 0.370 | 0.317 | 0.856 | 60 | 2663 |
| debut_days_since | 102.000 | 1 | 0.294 | 0.333 | 1.134 | 12 | 2663 |
| debut_days_since | 102.000 | 3 | 0.294 | 0.278 | 0.945 | 36 | 2663 |
| debut_days_since | 102.000 | 5 | 0.294 | 0.317 | 1.077 | 60 | 2663 |
| debut_days_since | 103.000 | 1 | 0.237 | 0.250 | 1.057 | 12 | 2663 |
| debut_days_since | 103.000 | 3 | 0.237 | 0.222 | 0.939 | 36 | 2663 |
| debut_days_since | 103.000 | 5 | 0.237 | 0.283 | 1.198 | 60 | 2663 |

## 固定効果の要約
### section
| section | n | avg_week_payout | median_week_payout | avg_positive_days | avg_hist_metric |
| --- | --- | --- | --- | --- | --- |
| 3209-3217 | 106 | 105.558 | 101.643 | 2.726 | 0.368 |
| 2115-2128 | 12 | 105.313 | 103.699 | 2.083 | 0.348 |
| 3218-3233 | 192 | 104.108 | 101.459 | 2.599 | 0.370 |
| 2281-2297 | 50 | 103.886 | 98.558 | 1.740 | 0.349 |
| 2298-2313 | 71 | 103.551 | 100.793 | 2.521 | 0.408 |
| 3234-3249 | 192 | 102.317 | 101.321 | 2.531 | 0.396 |
| 3103-3116 | 70 | 102.218 | 100.658 | 2.071 | 0.385 |
| 3400-3401 | 12 | 101.434 | 101.717 | 3.000 | 0.399 |
|  | 5789 | 100.753 | 99.237 | 2.369 | 0.342 |
| 2172-2178 | 9 | 100.245 | 101.368 | 3.444 | 0.315 |
| 2314-2329 | 60 | 99.947 | 99.198 | 1.967 | 0.376 |
| 3168-3180 | 156 | 99.901 | 99.778 | 2.615 | 0.299 |
| 3295-3309 | 180 | 99.767 | 99.425 | 2.656 | 0.305 |
| 3310-3324 | 179 | 99.730 | 99.721 | 2.698 | 0.288 |
| 3001-3016 | 192 | 99.574 | 99.744 | 2.906 | 0.322 |

### segment
| segment | n | avg_week_payout | median_week_payout | avg_positive_days | avg_hist_metric |
| --- | --- | --- | --- | --- | --- |
| 2F_L_N | 72 | 103.786 | 99.694 | 2.125 | 0.333 |
| 3F_R_N | 396 | 103.168 | 100.842 | 2.417 | 0.378 |
| 3F_L_N | 232 | 102.591 | 100.982 | 2.677 | 0.378 |
| 2F_R_N | 165 | 101.054 | 99.082 | 2.194 | 0.384 |
|  | 5789 | 100.753 | 99.237 | 2.369 | 0.342 |
| 3F_L_A | 923 | 99.579 | 99.423 | 2.733 | 0.300 |
| 3F_R_A | 875 | 99.222 | 99.166 | 2.759 | 0.285 |

### debut_phase
| debut_phase | n | avg_week_payout | median_week_payout | avg_positive_days | avg_hist_metric |
| --- | --- | --- | --- | --- | --- |
| unknown | 5789 | 100.753 | 99.237 | 2.369 | 0.342 |
| pre_existing | 2663 | 100.463 | 99.425 | 2.640 | 0.319 |

Outputs written to `C:\Users\apto117\Documents\pachinko-analyzer\src\2026project\eda\results\granularity_shift_experiments\weekly_machine_prediction`
