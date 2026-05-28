#!/usr/bin/env python3
"""Analyze 2F vs 3F performance differences and feature importance."""

import json
import pandas as pd
import numpy as np
from pathlib import Path

# Load nextday prediction data (contains segment_floor2 and predictions)
nextday_file = Path(__file__).parent / "reports" / "machine_type_nextday_best_sgd_floor2_a0p5_b0p5.csv"
df_nextday = pd.read_csv(nextday_file)

print("=" * 90)
print("2F vs 3F PREDICTION & PERFORMANCE COMPARISON (NextDay - 2026-05-21)")
print("=" * 90)

# Group by segment and analyze targets
segments_found = []
for segment in sorted(df_nextday['segment_floor2'].unique()):
    seg_data = df_nextday[df_nextday['segment_floor2'] == segment]
    segments_found.append(segment)
    print(f"\n{segment} Floor:")
    print("-" * 60)
    print(f"  Total machines: {len(seg_data)}")

    for target in ['is_rank_1', 'is_top_2', 'is_top_3', 'is_top_5']:
        if target in seg_data.columns:
            hit_count = seg_data[target].sum()
            hit_rate = seg_data[target].mean() if len(seg_data) > 0 else 0
            print(f"  {target:12s}: {hit_count:3.0f} hits / {len(seg_data):3.0f} = {hit_rate:6.1%}")

print("\n" + "=" * 90)
print("PREDICTION PATTERN ANALYSIS")
print("=" * 90)

# Check if models are making varied predictions
for segment in sorted(segments_found):
    seg_data = df_nextday[df_nextday['segment_floor2'] == segment]

    print(f"\n{segment} Floor - Prediction Behavior:")
    print("-" * 60)

    # For is_rank_1, check if probability predictions vary
    if 'proba_is_rank_1' in seg_data.columns:
        prob_values = seg_data['proba_is_rank_1'].dropna()
        print(f"  is_rank_1 probabilities:")
        print(f"    Min: {prob_values.min():.4f}, Max: {prob_values.max():.4f}")
        print(f"    Mean: {prob_values.mean():.4f}, Std: {prob_values.std():.4f}")
        print(f"    Unique values: {prob_values.nunique()}")

        # Check if mostly predicting same value
        value_counts = prob_values.value_counts().head(3)
        print(f"    Top 3 values: {value_counts.to_dict()}")

# Load feature importance
feature_file = Path(__file__).parent / "reports" / "machine_type_feature_select_v1_importance.csv"
df_features = pd.read_csv(feature_file)

print("\n" + "=" * 90)
print("TOP 20 FEATURES (Overall Importance)")
print("=" * 90)

top_20 = df_features.head(20)[['feature', 'importance_top2', 'importance_top3', 'importance_top5', 'mean_importance']]
print("\n")
for idx, row in top_20.iterrows():
    rank = idx + 1
    print(f"{rank:2d}. {row['feature']:35s} | top2:{row['importance_top2']:7.4f} top3:{row['importance_top3']:7.4f} top5:{row['importance_top5']:7.4f} | avg:{row['mean_importance']:7.4f}")

# Segment-specific features
print("\n" + "=" * 90)
print("SEGMENT-SPECIFIC FEATURE IMPORTANCE (Top 5 by segment/target)")
print("=" * 90)

segment_feature_file = Path(__file__).parent / "v2/output/10h_plan_results/phase_a_threshold_0d/feature_importance_per_segment.csv"
if segment_feature_file.exists():
    df_seg_feat = pd.read_csv(segment_feature_file)

    for segment in ['2F_A', '2F_N', '3F_A', '3F_N']:
        seg_data = df_seg_feat[df_seg_feat['segment'] == segment]
        if len(seg_data) == 0:
            continue

        print(f"\n{segment}:")
        print("-" * 60)

        for target in ['target_is_top3', 'target_is_top5']:
            target_data = seg_data[seg_data['target'] == target].sort_values('importance_mean', ascending=False).head(5)
            if len(target_data) > 0:
                print(f"\n  {target} - Top 5 features:")
                for idx, (_, row) in enumerate(target_data.iterrows(), 1):
                    print(f"    {idx}. {row['feature']:30s}: {row['importance_mean']:8.2f} (±{row['importance_std']:5.2f})")

# Compare 2F vs 3F feature importance
print("\n" + "=" * 90)
print("2F vs 3F FEATURE IMPORTANCE COMPARISON (is_top3)")
print("=" * 90)

if segment_feature_file.exists():
    df_seg_feat = pd.read_csv(segment_feature_file)

    # Average 2F and 3F
    df_2f = df_seg_feat[df_seg_feat['segment'].str.startswith('2F')][df_seg_feat['target'] == 'target_is_top3']
    df_3f = df_seg_feat[df_seg_feat['segment'].str.startswith('3F')][df_seg_feat['target'] == 'target_is_top3']

    if len(df_2f) > 0 and len(df_3f) > 0:
        agg_2f = df_2f.groupby('feature')['importance_mean'].mean().sort_values(ascending=False)
        agg_3f = df_3f.groupby('feature')['importance_mean'].mean().sort_values(ascending=False)

        # Create comparison
        comparison = pd.DataFrame({
            '2F': agg_2f,
            '3F': agg_3f,
        }).fillna(0)
        comparison['Diff (3F-2F)'] = comparison['3F'] - comparison['2F']
        comparison['2F Rank'] = (agg_2f).rank(ascending=False)
        comparison['3F Rank'] = (agg_3f).rank(ascending=False)
        comparison = comparison.sort_values('2F', ascending=False).head(15)

        print("\nTop 15 Features - 2F vs 3F (is_top3):")
        print("-" * 80)
        for feature in comparison.index:
            print(f"{feature:35s} | 2F:{comparison.loc[feature, '2F']:7.2f}(#{int(comparison.loc[feature, '2F Rank']):2d}) vs 3F:{comparison.loc[feature, '3F']:7.2f}(#{int(comparison.loc[feature, '3F Rank']):2d}) | Δ:{comparison.loc[feature, 'Diff (3F-2F)']:+7.2f}")

print("\n" + "=" * 90)
print("KEY FINDINGS")
print("=" * 90)

print(f"""
1. SEGMENT DATA AVAILABLE: {", ".join(segments_found)}

2. PREDICTION BEHAVIOR:
   - Check if models make varied predictions or always same value
   - Use probability distributions to detect degenerate patterns

3. FEATURE IMPORTANCE:
   - Top features are consistent across targets (days_since_last_*, rolling_avg_*)
   - Segment-specific importance differs between 2F and 3F

4. NEXT STEPS:
   - Investigate why 2F shows lower hit rates despite having main machines
   - Check data quality/sample size for 2F vs 3F
   - Review threshold calibration for each segment
""")

print("=" * 90)
