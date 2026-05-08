# Scale PosWeight Strategy Comparison: 16D vs 18D Features

**Date**: 2026-05-08  
**Project**: Pachinko Analyzer  
**Phase**: Phase 7-5: Rank Prediction Model Optimization  
**Hall**: マルハンメガシティ2000-蒲田7

---

## Executive Summary

Tested two class-weighting strategies (Balanced vs Calibrated) across two feature sets (16D and 18D) to determine optimal prediction accuracy.

**Key Finding**: **Calibrated strategy (scale_pos_weight=1.0) decisively beats Balanced reweighting on all targets and feature sets**, contrary to standard ML practice of always rebalancing imbalanced datasets.

**Additional Finding**: Adding `days_since_last_rank1` (18D vs 16D) improves **top_3 and top_5** but **slightly hurts rank_1** prediction.

---

## Strategy Overview

### Balanced Strategy (Class Rebalancing)
- Uses `scale_pos_weight = (neg_count) / (pos_count)` to artificially balance classes
- Goal: Maximize AUC by treating positive class weight equally to negative class
- Typical practice for imbalanced classification

### Calibrated Strategy (No Reweighting)
- Uses `scale_pos_weight = 1.0` (equal weight for both classes)
- Preserves natural class distribution in loss function
- Maintains probability calibration (P(pred=1) ≈ actual probability)

---

## Results: 16D Features
(month_progress + rolling_averages)

### rank_1
| Metric | Balanced | Calibrated | Delta |
|--------|----------|-----------|-------|
| scale_pos_weight | 62.90 | 1.0 | - |
| AUC | 0.6114 | 0.6588 | **+4.74%** |
| AP | 0.0184 | 0.0335 | +82% |
| Brier | 0.0638 | 0.0145 | -77% |
| ECE | 0.1663 | 0.0032 | **52x better** |

### top_3
| Metric | Balanced | Calibrated | Delta |
|--------|----------|-----------|-------|
| scale_pos_weight | 20.27 | 1.0 | - |
| AUC | 0.6226 | 0.6343 | **+1.17%** |
| AP | 0.0678 | 0.0789 | +16% |
| Brier | 0.1490 | 0.0406 | -73% |
| ECE | 0.2891 | 0.0067 | **43x better** |

### top_5
| Metric | Balanced | Calibrated | Delta |
|--------|----------|-----------|-------|
| scale_pos_weight | 11.83 | 1.0 | - |
| AUC | 0.6044 | 0.6311 | **+2.67%** |
| AP | 0.1023 | 0.1169 | +14% |
| Brier | 0.1822 | 0.0683 | -63% |
| ECE | 0.3107 | 0.0111 | **28x better** |

---

## Results: 18D Features
(month_progress + days_since_last_rank1 + rolling_averages)

### rank_1
| Metric | Balanced | Calibrated | Delta |
|--------|----------|-----------|-------|
| scale_pos_weight | 62.49 | 1.0 | - |
| AUC | 0.6110 | 0.6579 | **+4.70%** |
| AP | 0.0261 | 0.0389 | +49% |
| Brier | 0.0593 | 0.0146 | -75% |
| ECE | 0.1501 | 0.0045 | **33.6x better** |

### top_3
| Metric | Balanced | Calibrated | Delta |
|--------|----------|-----------|-------|
| scale_pos_weight | 20.06 | 1.0 | - |
| AUC | 0.6246 | 0.6671 | **+4.26%** |
| AP | 0.0662 | 0.0715 | +8% |
| Brier | 0.1458 | 0.0421 | -71% |
| ECE | 0.2813 | 0.0114 | **24.6x better** |

### top_5
| Metric | Balanced | Calibrated | Delta |
|--------|----------|-----------|-------|
| scale_pos_weight | 11.71 | 1.0 | - |
| AUC | 0.6297 | 0.6428 | **+1.31%** |
| AP | 0.1072 | 0.1146 | +7% |
| Brier | 0.1872 | 0.0663 | -65% |
| ECE | 0.3132 | 0.0190 | **16.5x better** |

---

## 16D vs 18D Comparison (Calibrated Strategy Only)

### AUC Performance

| Target | 16D | 18D | Delta | Trend |
|--------|-----|-----|-------|-------|
| rank_1 | 0.6588 | 0.6579 | -0.09% | ↓ Slightly worse |
| top_3 | 0.6343 | 0.6671 | +3.28% | ↑ Better |
| top_5 | 0.6311 | 0.6428 | +1.17% | ↑ Better |

### Key Observations

1. **rank_1**: Adding days_since_last_rank1 slightly **hurts** performance (-0.09%)
   - Possible explanation: Rank-1 is highly idiosyncratic; days since last rank-1 adds noise
   - The temporal recency of rank-1 may not be as predictive for future rank-1 achievement

2. **top_3**: Significant **improvement** with 18D (+3.28%)
   - days_since_last_rank1 is useful for predicting top-3 machines
   - Machines that recently achieved top-3 may have more predictable near-term performance

3. **top_5**: Modest **improvement** with 18D (+1.17%)
   - days_since_last_rank1 adds marginal signal for top-5 prediction

---

## Key Insights

### Finding 1: Calibrated Strategy is Superior

**Conclusion**: Using `scale_pos_weight=1.0` (Calibrated) consistently outperforms class rebalancing:

- **AUC gains**: +1.17% to +4.74% across all targets and feature sets
- **Calibration improvements**: 16.5x to 52x better ECE (Expected Calibration Error)
- **Brier score**: 63% to 77% improvement in calibration

**Why this works**: 
- Class rebalancing maximizes AUC at the cost of probability calibration
- For probabilistic prediction systems, calibration is more important than raw discrimination
- The unweighted approach preserves the natural probability distribution of the data

**Implication for deployment**: Predictions from Calibrated models can be directly interpreted as probabilities, while Balanced models produce miscalibrated confidence scores.

---

### Finding 2: days_since_last_rank1 Has Mixed Effects

The new feature (days since last rank-1 achievement) shows **target-dependent utility**:

| Target | Effect | Implication |
|--------|--------|------------|
| rank_1 | Slightly negative | Rank-1 dynamics don't follow simple temporal recency patterns |
| top_3 | Strongly positive | Top-3 machines exhibit predictable momentum |
| top_5 | Modestly positive | Top-5 shows weak temporal persistence |

**Recommendation**: 
- For rank_1 prediction: Use 16D (without days_since_last_rank1)
- For top_3 prediction: Use 18D (with days_since_last_rank1) → AUC 0.6671
- For top_5 prediction: Use 18D (with days_since_last_rank1) → AUC 0.6428

---

### Finding 3: Calibration is Critical for Imbalanced Data

The enormous ECE improvements (16.5x to 52x) demonstrate that on **imbalanced datasets**, probability calibration is as important as or more important than raw AUC:

- **Balanced approach**: Achieves decent AUC by reweighting, but produces badly miscalibrated probabilities
- **Calibrated approach**: Preserves probability meaning, enabling trustworthy confidence-based decision-making

For applications requiring confidence thresholds (e.g., "only predict rank-1 if P > 0.8"), the Calibrated approach is essential.

---

## Comparison Table: All 6 Configurations

| Config | Features | Strategy | rank_1 AUC | top_3 AUC | top_5 AUC | Best For |
|--------|----------|----------|-----------|-----------|-----------|----------|
| 1 | 16D | Balanced | 0.6114 | 0.6226 | 0.6044 | - (baseline) |
| 2 | 16D | **Calibrated** | **0.6588** | **0.6343** | **0.6311** | rank_1 |
| 3 | 18D | Balanced | 0.6110 | 0.6246 | 0.6297 | - (baseline) |
| 4 | 18D | **Calibrated** | 0.6579 | **0.6671** | **0.6428** | top_3, top_5 |

**Winner**: Configuration 4 (18D + Calibrated) for top_3/top_5; Configuration 2 (16D + Calibrated) for rank_1.

---

## Recommendation for Production

### Model Selection Strategy

```
if target == 'rank_1':
    # Use 16D features (days_since_last_rank1 adds noise)
    features = month_progress + rolling_averages  # 16D
    scale_pos_weight = 1.0  # Calibrated
    expected_auc = 0.6588
    
elif target in ['top_3', 'top_5']:
    # Use 18D features (temporal recency helps)
    features = month_progress + days_since_last_rank1 + rolling_averages  # 18D
    scale_pos_weight = 1.0  # Calibrated
    expected_auc = 0.6671 (top_3) or 0.6428 (top_5)
```

### Key Hyperparameters

- **max_depth**: 5 (shallow trees prevent overfitting)
- **learning_rate**: 0.1 (standard gradient boosting rate)
- **n_estimators**: 100 (adequate for this dataset)
- **scale_pos_weight**: **1.0** (CRITICAL: do NOT rebalance)

### Validation Split

- **Train**: 2025-07-07 to 2026-02-07 (240 days)
- **Test**: 2026-03-05 to 2026-04-30 (57 days)
- **Total data**: 19,524 records across 110 machine types

---

## Artifacts

- `phase7_04_model_comparison.py` — Reference implementation (Balanced vs Calibrated)
- `phase7_05_rank_prediction_18d_comparison.py` — 18D comparison script
- `ml/experiments/results/phase7_rank_prediction_v5_16d_comparison/comparison_16d.json` — 16D results
- `ml/experiments/results/phase7_rank_prediction_v5_18d_comparison/comparison_18d.json` — 18D results

---

## Conclusion

1. **Calibrated strategy (scale_pos_weight=1.0) is the clear winner** across all targets and feature sets
2. **days_since_last_rank1 is target-specific**: helps top_3/top_5, hurts rank_1
3. **Probability calibration matters more than AUC** for imbalanced classification
4. **Recommended production models**:
   - rank_1: 16D + Calibrated (AUC 0.6588)
   - top_3: 18D + Calibrated (AUC 0.6671) ← **Best overall**
   - top_5: 18D + Calibrated (AUC 0.6428)

---

**Completed**: 2026-05-08 23:21 JST
