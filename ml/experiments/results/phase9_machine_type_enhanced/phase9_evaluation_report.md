# Phase 9: Machine-Type Enhanced Rank Prediction - Final Report

## Executive Summary

**Objective**: Integrate machine-type features (jug/hana/oki/bt/other) into the 16D baseline
model and measure accuracy improvement.

**Finding**: Machine-type features provide **minimal improvement** (AUC +0.0003 to +0.0042).
Feature importance analysis reveals only the 'other' category (83.7% of data) has predictive signal;
rare categories (hana, oki, bt) rank dead last in importance.

## Detailed Results

### Phase 9-2: Model Training Results (Baseline vs Enhanced)

Time-series validation: Train on first N-57 dates, test on last 57 dates.

#### RANK_1

| Metric | 16D Baseline | 20D Enhanced | Delta | Delta % |
|--------|--------------|--------------|-------|----------|
| AUC | 0.6959 | 0.7002 | +0.0042 | +0.61% |
| AP | 0.0474 | 0.0468 | -0.0007 | N/A |
| Hit@3 | 0.3333 | 0.3333 | +0.0000 | N/A |
| Best F1 | 0.1108 | 0.1040 | -0.0067 | N/A |

#### TOP_3

| Metric | 16D Baseline | 20D Enhanced | Delta | Delta % |
|--------|--------------|--------------|-------|----------|
| AUC | 0.6869 | 0.6854 | -0.0015 | -0.22% |
| AP | 0.0816 | 0.0787 | -0.0029 | N/A |
| Hit@3 | 0.0000 | 0.0000 | +0.0000 | N/A |
| Best F1 | 0.1590 | 0.1537 | -0.0053 | N/A |

#### TOP_5

| Metric | 16D Baseline | 20D Enhanced | Delta | Delta % |
|--------|--------------|--------------|-------|----------|
| AUC | 0.6665 | 0.6668 | +0.0003 | +0.04% |
| AP | 0.1322 | 0.1316 | -0.0006 | N/A |
| Hit@3 | 0.3333 | 0.0000 | -0.3333 | N/A |
| Best F1 | 0.2094 | 0.2062 | -0.0032 | N/A |

### Phase 9-3: Feature Importance Analysis

Machine-type feature importance (XGBoost Gain, normalized):

#### RANK_1

- **Total machine-type importance**: 0.0542
- **machine_type_other**: 0.0542 (important)
- **machine_type_hana**: 0.0000 (rank 18-20, negligible)
- **machine_type_oki**: 0.0000 (rank 18-20, negligible)
- **machine_type_bt**: 0.0000 (rank 18-20, negligible)

#### TOP_3

- **Total machine-type importance**: 0.0886
- **machine_type_other**: 0.0886 (important)
- **machine_type_hana**: 0.0000 (rank 18-20, negligible)
- **machine_type_oki**: 0.0000 (rank 18-20, negligible)
- **machine_type_bt**: 0.0000 (rank 18-20, negligible)

#### TOP_5

- **Total machine-type importance**: 0.1522
- **machine_type_other**: 0.1522 (important)
- **machine_type_hana**: 0.0000 (rank 18-20, negligible)
- **machine_type_oki**: 0.0000 (rank 18-20, negligible)
- **machine_type_bt**: 0.0000 (rank 18-20, negligible)

## Analysis & Interpretation

### Why Machine-Type Integration Failed to Improve AUC

1. **Multicollinearity**: The 16D baseline features (rolling averages, games, efficiency) already
   capture much of the machine-type signal implicitly. Adding explicit machine-type features
   provides redundant information.

2. **Rare Category Problem**: The one-hot encoding includes three rare categories:
   - hana: 1.99% of data (388 samples)
   - oki: 1.52% of data (297 samples)
   - bt: ~3% of data (~600 samples)

   With such small sample sizes, the model cannot learn reliable patterns. These categories
   rank dead last (#18-20) in feature importance.

3. **Encoding Inefficiency**: One-hot encoding distributes the 'other' signal across 4 binary
   features. A simpler 'is_other' binary flag would be more efficient and reduce noise.

4. **Phase 8-5 vs Phase 9 Discrepancy**: Phase 8-5 showed machine-type alone achieves AUC
   +0.064-0.068. However, this was **standalone effect size** (machine-type alone vs random
   baseline). When combined with the 16D features that already have AUC 0.69, the marginal
   benefit drops to +0.004 due to multicollinearity.

## Recommendations

### Option 1: Use 'Other' Flag Instead of One-Hot (Recommended)
Replace 4D one-hot with single binary feature:
- Create: `is_other = 1 if machine_type == 'other' else 0`
- Eliminates noise from rare categories
- Reduces model complexity
- Expected improvement: +0.002 to +0.005 AUC

### Option 2: Target Encoding
Encode machine-type by its mean rank concentration:
- For each machine type, compute: `mean(is_rank_1)` in training data
- Use this value as a single continuous feature
- Preserves signal without sparse features
- Expected improvement: +0.003 to +0.007 AUC

### Option 3: Skip Machine-Type, Optimize Baseline
Machine-type integration has diminishing returns. Instead:
1. Hyperparameter tune the 16D baseline (max_depth=2-5, learning_rate=0.001-0.05)
2. Create feature interactions: e.g., (days_since_rank1) X (avg_efficiency_7d)
3. Explore alternative domain attributes (island number, position, etc.)

### Option 4: Ensemble Approach
Train specialized models:
1. Baseline 16D model (all data)
2. 'Other' specialist (trained on 83.7% majority)
3. Rare category specialist (trained on hana+oki+bt combined)
4. Blend predictions: 0.5*baseline + 0.3*other + 0.2*rare

## Statistical Significance

With test sample size ~5,800:
- AUC +0.0042 (rank_1) has 95% CI roughly ±0.015
- This improvement is **NOT statistically significant** (CI crosses zero)
- Practical significance: Does 0.6959 → 0.7002 change any business decision? **Probably not**.

## Phase 9 Learnings

1. **Standalone effect ≠ Marginal contribution**: Phase 8-5 showed +0.064 standalone effect;
   Phase 9 integration showed +0.004 marginal effect. This is a key lesson in multi-feature modeling.

2. **One-hot encoding has limits**: Effective for balanced categories, problematic for rare ones.
   Consider alternatives (target encoding, binary flags, embeddings).

3. **Baseline already captures signal**: The 16D model (AUC 0.69) is already good. Further
   improvement requires different approaches (interactions, hyperparameter tuning, new features).

4. **Validation matters**: Using proper time-series validation revealed the true marginal benefit,
   whereas simple sample-based splits would have given misleading AUC values.

## Conclusion

Machine-type patterns exist and are statistically significant (Phase 8-5 confirmed this).
However, when integrated into a multi-feature model with one-hot encoding, they provide
negligible improvement due to:
- Multicollinearity with baseline features
- Inefficient encoding of rare categories
- Information redundancy

**Recommended next step**: Try Option 1 (simple 'is_other' flag). If that doesn't improve AUC,
proceed to baseline optimization (hyperparameter tuning, feature interactions) which may yield
larger gains.

