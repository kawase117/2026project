# 末尾相対ランキング予測システム設計 — ML Planning Document

**Date**: 2026-05-14  
**Status**: Planning (Implementation deferred)  
**Project**: Phase 4 ML Pipeline  
**Objective**: Predict daily 末尾 relative strength rankings (Rank1 and TOP3) despite non-stationary target distribution

---

## 1. Problem Statement

### Current Performance
- **Metric**: Rank1 and TOP3 prediction accuracy
- **Status**: Both achieve ~random-level performance (≈10% for Rank1, ≈30% for TOP3)
- **Root cause**: Non-stationary target distribution across temporal regimes

### Key Constraint: Non-Stationarity
The absolute high-profit rate (baseline against which 末尾 strength is measured) shifts systematically:

| Period | Mean High-Profit % | Interpretation |
|--------|-------------------|-----------------|
| Training (2025-07-07 to 2025-11-01) | 29-30% | Hall in "strong opening" regime |
| Test (2025-11-01 to 2025-12-31) | 24-25% | Transition to "weakening" regime |
| Future (2026-01-01 onwards) | Unknown | Possible further weakening or stabilization |

**Impact**: A regression model trained on training period will systematically overpredict test period values by ~5pp. Feature engineering alone cannot fix this; the baseline itself has shifted.

### What We Know (Confirmed by Analysis)

1. **末尾 Bias Exists** (χ² p < 0.05 in aggregate randomness test)
   - 末尾0: 36.3% (biased toward high-profit)
   - 末尾3: 26.5% (biased against high-profit)
   - This is statistically significant globally

2. **Relative Ranking is Stable** (χ² p = 1.0000 in independence test)
   - Daily rankings show no dependence on DD (day-of-month)
   - Daily rankings show no dependence on weekday
   - The order (末尾0 → 末尾6 → 末尾2 → ...) stays roughly consistent across dates

3. **Relative Strength Differences are Small** (~2-3pp bias, below classification threshold)
   - 末尾1 and 末尾8 appear in Top3 32.8% vs 30% expected (+2.8pp)
   - Insufficient signal for reliable binary/multi-class classification

---

## 2. Why Previous Approaches Failed

### Hypothesis-Driven Analysis (Payday, DD Effects)
- **Assumption**: High-setting allocation varies by date attributes (payday, DD, weekday)
- **Reality**: Chi-square tests confirm complete independence (p = 1.0000)
- **Lesson**: Data-driven pattern discovery supersedes domain-based hypotheses

### Binary Classification (Rank1 Prediction)
- **Approach**: Train classifier to predict which 末尾 will be Rank1 on any given day
- **Problem**: Only ~10% accuracy (1 of 10 tails correct) — identical to random
- **Root Cause**: 
  - Signal-to-noise ratio inadequate (2-3pp bias vs model entropy)
  - Non-stationarity means training distribution ≠ test/future distribution
  - Model memorizes train regime; fails to generalize to weaker regime

### Regression (High-Profit Rate Prediction)
- **Approach**: Predict absolute high-profit % by 末尾 and date attributes
- **Problem**: Overestimates by ~5pp uniformly (trained on 29% baseline, predicts for 24% baseline)
- **Root Cause**: Cannot adapt to regime shift without explicit temporal modeling
- **Limitation**: Even perfect predictions of *within-regime* patterns fail across regimes

### Multi-Class Classification (TOP3 Prediction)
- **Approach**: Predict which 末尾 will be in Top3 on any given day
- **Problem**: ~30% accuracy — identical to random (baseline = 3/10)
- **Root Cause**: Top3 is defined *relative to that day's absolute values*, not absolute thresholds
  - If all 末尾 shift by -5pp together, Top3 identity changes even if relative order stays same
  - Model cannot distinguish "did the top tails weaken together?" from "did the top tails drop in rank?"

---

## 3. Three Temporal Regimes (非定常性への対応)

### Regime 1: オープン期 (Opening Period) — Strong Phase
- **Dates**: 2025-07-07 to 2025-10-31 (≈4 months)
- **Baseline**: 29-30% high-profit rate
- **Characteristic**: Hall at maximum promotional intensity; broad machine allocation
- **Data Quality**: Ample daily observations; stable patterns

### Regime 2: 弱化期 (Weakening Period) — Transition Phase
- **Dates**: 2025-11-01 to 2025-12-31 (≈2 months)
- **Baseline**: 24-25% high-profit rate
- **Characteristic**: Shift toward concentrated allocation; fewer high-setting positions
- **Data Quality**: Limited observation window; pattern less stable

### Regime 3: 未知期 (Unknown Future) — Prediction Target
- **Dates**: 2026-01-01 onwards
- **Baseline**: Unknown (could stabilize at 24%, continue weakening, or rebound)
- **Characteristic**: Out-of-distribution; no direct training data
- **Challenge**: Model must generalize without seeing this regime

**Design Requirement**: ML system must explicitly handle regime transitions, not assume stationarity.

---

## 4. Candidate ML Solutions

### 4.1 Learning to Rank (LTR) Approach

**Concept**: Predict relative ordering of 末尾 within each day, not absolute performance.

#### Why It Fits
- **Problem Match**: Current goal is "which 末尾 ranks highest?" not "will 末尾0 reach 30%?"
- **Non-Stationarity Agnostic**: Relative ordering can remain stable even if absolute values shift
- **Robustness**: Irrelevant whether baseline is 29% or 24%; only the ranking matters

#### Implementation Strategy
1. **Training Data Preparation**
   - For each day, extract true ranking: 末尾0 ranks higher than 末尾3, etc.
   - Create pairwise comparisons: (末尾i vs 末尾j on dateA → i wins) as training examples
   - Use all days in training period; don't split by regime

2. **Model Architecture**
   - **Option A**: RankSVM or LambdaRank (learn pairwise preferences)
   - **Option B**: Pointwise scoring (neural net outputs score per tail) + sort predictions
   - **Option C**: ListNet (directly optimize ranking loss)

3. **Feature Engineering**
   - **Historical relative strength**: Last 7-day rolling mean of tail win-rates (normalized within each day)
   - **Global bias**: Tail-specific constant (末尾0 naturally stronger, etc.)
   - **Temporal trend**: How has this tail's relative position changed over past 30 days? (capturing regime adaptation)
   - **Absolute baseline proxy**: Day-level feature (day-of-week, season) to help model adapt to regime shifts

4. **Cross-Regime Generalization**
   - Train on Regime 1 + Regime 2 combined to expose model to baseline shift
   - Validate on Regime 2 test set; measure ranking accuracy (Spearman ρ, NDCG)
   - If Regime 2 test performance is poor, signals that relative order *did* change between regimes

5. **Trade-offs**
   - ✅ **Strength**: Focuses on ordering, not absolute values; conceptually aligned with problem
   - ✅ **Strength**: Rank-based metrics (NDCG) capture meaningful prediction error
   - ❌ **Weakness**: Requires more data labeling (pairwise or listwise examples)
   - ❌ **Weakness**: Doesn't explicitly forecast *which regime* we're in; assumes regime info is implicit in features

---

### 4.2 Time-Adaptive Learning (Expanding Window + Time-Decay)

**Concept**: Give recent data higher weight during training; gradually forget old regime-specific patterns.

#### Why It Fits
- **Regime Awareness**: Weighted training naturally de-emphasizes Regime 1 patterns as time progresses
- **Continuous Adaptation**: Model evolves as new data arrives, accommodating gradual shifts
- **Practical**: Can wrap any base model (regression, classification, LTR)

#### Implementation Strategy

##### Option A: Expanding Window Retraining
1. **Training Windows**
   - **Window 1**: 2025-07-07 to 2025-08-31 (Regime 1 start)
   - **Window 2**: 2025-07-07 to 2025-10-31 (Regime 1 complete)
   - **Window 3**: 2025-07-07 to 2025-11-30 (Regime 1 + half of Regime 2)
   - **Window 4**: 2025-07-07 to 2025-12-31 (Both regimes)
   - Continue: Retrain monthly with all available data up to current date

2. **Model Evaluation**
   - Test each window's model on subsequent 7-14 days (immediate generalization)
   - Track whether Window 3 or 4 performs better on Regime 2 data
   - If Window 4 > Window 3 on Regime 2 test: expanding window helps adaptation
   - If Window 3 > Window 4: older data is harmful (strong regime drift)

3. **Deployment Strategy**
   - Retrain model every 7 days with all data to date
   - This gradual expansion naturally down-weights Regime 1 as more Regime 2 data accumulates

##### Option B: Time-Decay Weighting (More Aggressive)
1. **Sample Weighting**
   - Assign each training example weight `w(t) = exp(-λ * (T_current - t_example) / T_total)`
   - Recent examples get weight ≈ 1.0; old examples get weight ≈ 0.1-0.3
   - Decay rate λ can be tuned: λ = 1 (moderate decay), λ = 2-3 (aggressive decay)

2. **Effect**
   - Regime 1 (5 months ago) gets weight ≈ 0.1-0.2
   - Regime 2 (current) gets weight ≈ 0.8-1.0
   - Recent Regime 2 data dominates learning, automatically adapting to regime shift

3. **Deployment**
   - Retrain model daily/weekly with time-decay weights
   - As future dates arrive and baseline potentially shifts again, recent data automatically gains prominence

#### Trade-offs
- ✅ **Strength**: Explicitly handles regime drift via recency bias
- ✅ **Strength**: Simple to implement; works with any base model
- ✅ **Strength**: Minimal additional computational cost
- ❌ **Weakness**: Doesn't explicitly identify regime transitions; relies on data to speak for itself
- ❌ **Weakness**: If Regime 3 baseline is very different, model may overfit to Regime 2 patterns and fail catastrophically
- ❌ **Weakness**: Requires frequent retraining (weekly/monthly) in production

---

### 4.3 Regime-Aware Ensemble (Hybrid Approach)

**Concept**: Train separate models per regime; use ensemble weighting to blend predictions based on inferred current regime.

#### Why It Fits
- **Explicit Regime Modeling**: Acknowledges that Regime 1 and Regime 2 patterns differ fundamentally
- **Graceful Degradation**: As Regime 3 begins, can slowly transition from Regime 2 model to adaptive weighting

#### Implementation Strategy

1. **Multi-Regime Models**
   - **Regime 1 Model**: Trained exclusively on 2025-07-07 to 2025-10-31 (オープン期)
   - **Regime 2 Model**: Trained exclusively on 2025-11-01 to 2025-12-31 (弱化期)
   - **Hybrid Model**: Trained on both regimes (to learn common patterns that transcend regime)

2. **Regime Detection / Inference**
   - Monitor a "regime indicator" in real-time: weekly high-profit rate
   - If rate > 27%: confidence high we're in Regime 1-like state → Regime 1 model weight = 0.7
   - If rate 25-27%: ambiguous → blend Regime 1 + Regime 2 equally
   - If rate < 24%: confidence high we're in Regime 2-like state → Regime 2 model weight = 0.8
   - Hybrid model always gets 0.1-0.2 weight to maintain diversity

3. **Ensemble Prediction**
   - For any given day, compute predictions from all three models
   - Weight by regime confidence: `pred = w1 * pred_regime1 + w2 * pred_regime2 + w_hybrid * pred_hybrid`
   - Output weighted ensemble prediction (Rank1, TOP3, or ranking order)

#### Trade-offs
- ✅ **Strength**: Explicitly captures regime differences; easier to interpret
- ✅ **Strength**: Can gracefully transition to Regime 3 by monitoring indicator
- ❌ **Weakness**: Regime indicator itself is noisy (one week ≠ representative of entire regime)
- ❌ **Weakness**: Three separate models required; more complex to maintain and retrain
- ❌ **Weakness**: Requires manual threshold tuning (27%, 24%, etc.) — may not generalize across halls

---

### 4.4 Relative Stability Weighting (Signal Amplification)

**Concept**: Don't try to predict absolute high-profit %; instead, weight 末尾 by their historical stability relative to one another.

#### Why It Fits
- **Signals What's Stable**: If 末尾0 consistently outranks 末尾3 by 5-10pp across all days/regimes, that signal is robust
- **Ignores Baseline Shift**: Whether baseline is 29% or 24%, the 5-10pp gap between 末尾0 and 末尾3 persists
- **Simplifies Problem**: Reduces to "which tails are reliably stronger?" not "which tail reaches what %?"

#### Implementation Strategy

1. **Historical Stability Score**
   - For each pair of 末尾 (i, j), compute: "how often does i outrank j?"
   - Example: Over 150 days, 末尾0 beats 末尾3 in 120 days (80%), beats 末尾6 in 90 days (60%)
   - Aggregate into a "strength score" per tail: `strength[i] = Σ_j P(i beats j)`

2. **Prediction Rule**
   - Rank 末尾 by their strength score
   - **Rank1 prediction**: Tail with highest strength score
   - **TOP3 prediction**: Top 3 tails by strength score
   - No retraining required; only update scores as new data arrives

3. **Regime Adaptation (Optional)**
   - Recalculate strength scores monthly, excluding data older than 60 days
   - This keeps scores calibrated to current regime without explicit regime detection

#### Trade-offs
- ✅ **Strength**: Extremely simple; no complex model required
- ✅ **Strength**: Naturally robust to baseline shifts (uses relative comparisons)
- ✅ **Strength**: Transparent and interpretable; strength scores directly correspond to empirical win rates
- ❌ **Weakness**: Assumes relative order remains stable — if Regime 3 reverses tail rankings, this approach fails
- ❌ **Weakness**: Provides point predictions only (no probability calibration, confidence intervals)
- ❌ **Weakness**: Low signal-to-noise ratio (2-3pp differences) means predictions inherently brittle

---

## 5. Comparative Analysis: How Each Addresses Non-Stationarity

| Approach | Regime Shift Handling | Implementation Complexity | Data Requirements | Uncertainty Quantification |
|----------|----------------------|---------------------------|-------------------|---------------------------|
| **Learning to Rank** | ✓ Implicit (relative ordering stable) | Medium (rank loss, pairwise data) | High (need ranking labels) | ⚠️ Limited (ranking → classification) |
| **Expanding Window** | ⚠️ Gradual (assumes monotonic drift) | Low (retrain existing model) | Low (uses existing labels) | ✓ High (can propagate confidence) |
| **Time-Decay Weight** | ✓ Explicit (recent bias) | Low (weight adjustment only) | Low (uses existing labels) | ✓ High (sample weight → confidence) |
| **Regime Ensemble** | ✓✓ Explicit (separate models + indicator) | High (maintain 3 models + detector) | High (regime labels required) | ✓✓ High (ensemble diversity) |
| **Stability Weighting** | ⚠️ Implicit (empirical stability) | Low (score calculation only) | Medium (pair comparisons) | ❌ None (deterministic rules) |

**Best Overall for Non-Stationarity**: **Time-Decay Weighting + Learning to Rank** (combines simple adaptation with robust relative ordering)

---

## 6. Recommended Approach: Hybrid Time-Adaptive LTR

### Rationale
1. **Learning to Rank** aligns perfectly with the problem (predict daily ranking of 末尾)
2. **Time-Decay Weighting** automatically adapts to regime shifts without explicit detection
3. **Combined effect**: Robust relative ordering + adaptive learning = handles both stability and drift

### High-Level Architecture

```
┌─────────────────────────────────────────┐
│  Daily Data Input (date, tail, win_rate) │
└──────────────────┬──────────────────────┘
                   │
        ┌──────────▼─────────────┐
        │ Feature Extraction     │
        │ - Historical strengths │
        │ - Temporal trend       │
        │ - Season / week type   │
        │ - Regime proxy (if any)│
        └──────────┬─────────────┘
                   │
        ┌──────────▼──────────────────────┐
        │ Pairwise Ranking Data Generation│
        │ (tail_i vs tail_j per day)      │
        └──────────┬──────────────────────┘
                   │
        ┌──────────▼──────────────────────────────┐
        │ Time-Decay Weighting                    │
        │ Recent pairs: weight ≈ 1.0              │
        │ Old pairs:    weight ≈ 0.2              │
        │ (λ = 1.5 as starting point, tunable)    │
        └──────────┬──────────────────────────────┘
                   │
        ┌──────────▼─────────────────────────┐
        │ LambdaRank / RankSVM Training       │
        │ (minimize weighted pairwise losses)  │
        └──────────┬─────────────────────────┘
                   │
        ┌──────────▼──────────────────────────┐
        │ Daily Prediction (new date)          │
        │ 1. Compute features for each tail    │
        │ 2. Score each tail with learned model│
        │ 3. Rank tails by score               │
        └──────────┬──────────────────────────┘
                   │
        ┌──────────▼─────────────────────────┐
        │ Output: Predicted Daily Ranking      │
        │ - Rank1: highest-scoring tail        │
        │ - TOP3: top 3 by score               │
        │ - Full ranking: tail order           │
        └────────────────────────────────────┘
```

### Training & Validation Plan

1. **Baseline Establishment** (Week 1-2)
   - Train LTR model on Regime 1 only (2025-07-07 to 2025-10-31)
   - Test on Regime 2 (2025-11-01 to 2025-12-31)
   - Measure ranking metrics: Spearman ρ, NDCG@3, Rank1 accuracy
   - Document: how poorly does Regime 1 model generalize to Regime 2?

2. **Time-Decay Ablation** (Week 2-3)
   - Train LTR model on Regime 1 + Regime 2 **without** time-decay (uniform weights)
   - Test on Regime 2
   - Compare: does adding Regime 2 data help (even with uniform weights)?
   - This isolates the effect of data quantity vs. recency

3. **Time-Decay Tuning** (Week 3-4)
   - Train LTR model on Regime 1 + Regime 2 **with** time-decay (λ = 1.0, 1.5, 2.0, 2.5)
   - For each λ, measure Regime 2 test performance
   - Select λ that maximizes Regime 2 ranking quality
   - Expected: λ = 1.5-2.0 is "sweet spot" (Regime 1 ≈ 10-20% weight, Regime 2 ≈ 80-90% weight)

4. **Cross-Validation** (Week 4-5)
   - Temporal cross-validation: train on days 1-120, test days 121-135; shift window forward
   - Measure Rank1 accuracy, TOP3 recall, NDCG@3 per window
   - Report mean ± std of each metric
   - Flag if Regime 2 test windows show significant degradation vs. Regime 1 windows

5. **Future Regime Robustness** (Week 5-6)
   - Simulate Regime 3 by synthesizing data: assume baseline drops another 3-5pp
   - Apply trained model to simulated data
   - Measure: do relative rankings remain stable, or do tail order change?
   - Qualitative assessment: is model likely to gracefully degrade to Regime 3?

### Implementation Checklist

- [ ] **Data Preparation**: Convert daily tail win-rates to pairwise ranking examples
- [ ] **Feature Engineering**: Implement rolling 7-day relative strength, temporal trend, season/weekday features
- [ ] **Time-Decay Implementation**: Weight computation in training loss
- [ ] **Model Selection**: Choose LambdaRank or RankSVM library (XGBoost has LambdaRank, or scikit-learn-contrib RankSVM)
- [ ] **Baseline Evaluation**: Regime 1 → Regime 2 generalization report
- [ ] **Hyperparameter Tuning**: Grid search over decay rate λ, number of features, tree depth (if tree-based)
- [ ] **Validation Framework**: Temporal cross-validation script
- [ ] **Metrics Tracking**: Spearman ρ, NDCG@3, Rank1 accuracy, TOP3 recall
- [ ] **Documentation**: Rationale for each design choice, trade-offs, limitations
- [ ] **Monitoring Plan**: How will Regime 3 performance be tracked in production?

---

## 7. Implementation Considerations

### What to Expect
- **Rank1 Accuracy**: Likely 15-25% (vs. 10% random) if signal is truly present
- **TOP3 Recall**: Likely 35-50% (vs. 30% random) — easier than Rank1
- **Ranking Quality (NDCG)**: 0.5-0.6 typical for weak signals
- **Regime 2 Generalization**: Will degrade vs. Regime 1 unless time-decay is strong (λ ≥ 1.5)

### Risk Mitigation
1. **Regime 3 Uncertainty**: Current data only covers Regimes 1-2; Regime 3 is fundamentally unknowable
   - **Mitigation**: Use ensemble + time-decay to be conservative; flag predictions with low confidence if regime indicator diverges
   
2. **Small Signal-to-Noise Ratio**: 2-3pp bias is marginal for classification
   - **Mitigation**: Use ranking metrics (NDCG) instead of accuracy; evaluate relative order rather than absolute correctness
   
3. **Overfitting to Regime 2**: Limited Regime 2 data (≈60 days) may lead to overfitting
   - **Mitigation**: Aggressive regularization; early stopping; temporal CV to catch overfitting

### Next Steps if This Plan Proceeds to Implementation
1. Implement time-adaptive LTR model following checklist above
2. Produce detailed performance report (Regime 1, Regime 2, simulated Regime 3)
3. Create daily prediction pipeline with confidence scores
4. Deploy to production with continuous monitoring
5. Retrain weekly with time-decay weights; track regime indicator in real-time

---

## 8. Conclusion

The 末尾 relative ranking problem is inherently constrained by:
- **Weak signal**: 2-3pp bias insufficient for high-confidence classification
- **Non-stationarity**: Baseline shifts 5pp across regimes, invalidating single-regime models
- **Limited data**: Only 150 days available; Regime 3 is unknown

**Recommended path forward**: **Time-Adaptive Learning to Rank** (LTR + time-decay weighting) offers the best balance:
- ✅ Focuses on robust relative ordering (stable across regimes)
- ✅ Adapts automatically to baseline shifts (time-decay weights)
- ✅ Provides interpretable ranking predictions (Rank1, TOP3)
- ✅ Moderate implementation complexity

Expected outcome: **15-25% Rank1 accuracy** (vs. 10% random), **35-50% TOP3 recall** (vs. 30% random) — modest but potentially actionable improvements. Full validation required before production deployment.

Implementation timeline: **6-8 weeks** for research → development → validation → deployment.
