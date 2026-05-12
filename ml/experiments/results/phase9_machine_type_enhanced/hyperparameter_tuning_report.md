# Phase 10: Hyperparameter Tuning Results
## 16D Baseline Model Optimization

### Summary
Grid search over max_depth=[2,3,4,5] and learning_rate=[0.001, 0.005, 0.01, 0.02, 0.05] using time-series validation (last 57 dates for testing).

### RANK_1
**Best Parameters:**
- max_depth: 4
- learning_rate: 0.005
- n_estimators: 200

**Best AUC:** 0.7001
**AP:** 0.0412
**Brier:** 0.0139
**Hit@1:** 0.0000
**Hit@3:** 0.0000
**Hit@5:** 0.0000
**Best F1:** 0.1045 (threshold=0.070)

**Comparison to Baseline (MD=3, LR=0.01):**
- Baseline AUC: 0.6959
- Improvement: +0.0041 (+0.59%)

### TOP_3
**Best Parameters:**
- max_depth: 3
- learning_rate: 0.02
- n_estimators: 200

**Best AUC:** 0.6895
**AP:** 0.0822
**Brier:** 0.0405
**Hit@1:** 0.0000
**Hit@3:** 0.0000
**Hit@5:** 0.0000
**Best F1:** 0.1537 (threshold=0.086)

**Comparison to Baseline (MD=3, LR=0.01):**
- Baseline AUC: 0.6869
- Improvement: +0.0026 (+0.38%)

### TOP_5
**Best Parameters:**
- max_depth: 3
- learning_rate: 0.01
- n_estimators: 200

**Best AUC:** 0.6665
**AP:** 0.1322
**Brier:** 0.0644
**Hit@1:** 1.0000
**Hit@3:** 0.3333
**Hit@5:** 0.4000
**Best F1:** 0.2094 (threshold=0.129)

**Comparison to Baseline (MD=3, LR=0.01):**
- Baseline AUC: 0.6665
- Improvement: +0.0000 (+0.00%)

## Key Insights
- **rank_1** showed +0.59% AUC improvement with hyperparameter tuning
- **top_3** showed +0.38% AUC improvement with hyperparameter tuning
- **top_5** showed +0.00% AUC improvement with hyperparameter tuning

## Next Steps
1. Apply best hyperparameters in production
2. Consider feature interaction engineering for further improvements
3. Explore alternative domain attributes (island, position, etc.)
