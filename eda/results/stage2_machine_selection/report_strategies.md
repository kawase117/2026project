# Stage 2 Machine Selection Strategy Report

- Combined strategy keeps only features with `rho > 0` and `p < 0.1`.
- Strategy scores use within-section percentile ranks to stay comparable to `hist_metric`.

| strategy | hit_rate | lift | avg_diff | vs_hist_only |
| --- | --- | --- | --- | --- |
| combined | 0.4140 | 1.0412 | 481.3333 | 0.0000 |
| debut_weighted | 0.4140 | 1.0412 | 481.3333 | 0.0000 |
| hist_only | 0.4140 | 1.0412 | 481.3333 | 0.0000 |
| kakuban_weighted | 0.4167 | 1.0479 | 489.7333 | 8.4000 |
| momentum_weighted | 0.4127 | 1.0378 | 447.9333 | -33.4000 |
| trail_weighted | 0.4067 | 1.0227 | 442.7333 | -38.6000 |
