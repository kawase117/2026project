# Phase 9-3: Feature Importance Diagnostic Report

## Summary

Phase 9-2 showed that machine-type features provided minimal AUC improvement:
- rank_1: +0.0042 (+0.61%) — only 6.5% of Phase 8-5's +0.0664 effect
- top_3: -0.0015 (-0.22%) — regression
- top_5: +0.0003 (+0.04%) — negligible

This diagnostic analyzes feature importance to understand why.

## RANK_1

**Machine-Type Total Importance (Gain):** 0.054151

**Machine-Type Feature Ranks (by Gain):**
  - machine_type_hana: rank 18/20
  - machine_type_oki: rank 19/20
  - machine_type_bt: rank 20/20
  - machine_type_other: rank 7/20

**Top 5 Features (by Gain):**
  1. days_since_rank_1: 0.196098
  2. machine_count: 0.103404
  3. avg_efficiency_28d: 0.070362
  4. avg_efficiency_14d: 0.065902
  5. avg_games_7d: 0.065034

**Top 5 Features (by Permutation AUC Drop):**
  1. days_since_rank_1: 11.941% AUC drop
  2. machine_count: 6.807% AUC drop
  3. avg_diff_14d: 1.315% AUC drop
  4. avg_games_7d: -1.194% AUC drop
  5. avg_games_21d: 1.066% AUC drop

## TOP_3

**Machine-Type Total Importance (Gain):** 0.088591

**Machine-Type Feature Ranks (by Gain):**
  - machine_type_hana: rank 18/20
  - machine_type_oki: rank 19/20
  - machine_type_bt: rank 20/20
  - machine_type_other: rank 3/20

**Top 5 Features (by Gain):**
  1. days_since_rank_1: 0.141508
  2. machine_count: 0.135050
  3. machine_type_other: 0.088591
  4. avg_games_28d: 0.084463
  5. avg_games_7d: 0.059547

**Top 5 Features (by Permutation AUC Drop):**
  1. machine_count: 12.772% AUC drop
  2. days_since_rank_1: 11.240% AUC drop
  3. machine_type_other: 3.413% AUC drop
  4. avg_diff_14d: 0.336% AUC drop
  5. avg_diff_35d: 0.259% AUC drop

## TOP_5

**Machine-Type Total Importance (Gain):** 0.152172

**Machine-Type Feature Ranks (by Gain):**
  - machine_type_hana: rank 18/20
  - machine_type_oki: rank 19/20
  - machine_type_bt: rank 20/20
  - machine_type_other: rank 2/20

**Top 5 Features (by Gain):**
  1. machine_count: 0.173532
  2. machine_type_other: 0.152172
  3. days_since_rank_1: 0.143352
  4. avg_games_28d: 0.092587
  5. avg_games_14d: 0.063472

**Top 5 Features (by Permutation AUC Drop):**
  1. machine_count: 11.815% AUC drop
  2. days_since_rank_1: 8.317% AUC drop
  3. machine_type_other: 8.041% AUC drop
  4. avg_games_7d: -0.541% AUC drop
  5. avg_games_35d: -0.128% AUC drop

## Interpretation

### Hypothesis 1: Multicollinearity
If machine-type features rank outside top 5 overall, their signal is likely already captured by baseline features.
This suggests rolling averages (avg_diff, avg_games, avg_efficiency) implicitly encode machine-type patterns.

### Hypothesis 2: Suboptimal Encoding
One-hot encoding with 83.7% 'other' dominance might dilute signal. Alternative encodings (target encoding, embedding) could be explored.

### Hypothesis 3: Feature Interactions
Machine-type might only improve predictions through interactions (e.g., machine_type X days_since_rank1).
This would require explicit interaction features.

### Next Steps
1. **If machine-type ranks low**: Conclude multicollinearity; skip machine-type and optimize baseline features instead
2. **If machine-type ranks high but AUC still low**: Explore interaction features and target encoding
3. **If XGBoost importance vs permutation differ significantly**: Investigate feature interactions

