# 蒲田7 Plan Budget Regime Report

- caution: diff-only is coarse; prefer share_of_total_diff plus hit104_lift for reading concentration
- source rows: 253313
- days: 360
- all_high: 61
- focused_machine: 14
- focused_category: 91
- balanced: 129
- recovery: 65
- decoy_heavy: 0

## Top Axes
- section=2001-2351: share=441.474, mean_excess=45.343, hit104_lift=0.016
- section=3001-3362: share=401.694, mean_excess=-44.772, hit104_lift=-0.016
- kakuban_bin=6-9: share=343.962, mean_excess=22.049, hit104_lift=0.001
- atype=N: share=337.303, mean_excess=-1.688, hit104_lift=0.018
- machine_category=other: share=284.775, mean_excess=-12.575, hit104_lift=0.007
- machine_category=at_smart: share=277.047, mean_excess=8.954, hit104_lift=0.028
- kakuban_bin=3-5: share=264.207, mean_excess=-21.668, hit104_lift=-0.002
- kakuban_bin=0-2: share=261.175, mean_excess=-7.776, hit104_lift=0.000
- atype=A: share=200.336, mean_excess=3.956, hit104_lift=-0.041
- machine_name=東京喰種: share=192.677, mean_excess=-205.760, hit104_lift=0.053
- event_type=weekday: share=189.000, mean_excess=0.000, hit104_lift=0.000
- machine_name=モンキーターンV: share=188.720, mean_excess=155.074, hit104_lift=0.023

## Offset Candidates
- atype: A -> N, gap=201.858, corr=-0.998, n=175
- atype: N -> A, gap=179.965, corr=-0.997, n=185
- kakuban_bin: 0-2 -> 3-5, gap=211.274, corr=-0.285, n=175
- kakuban_bin: 3-5 -> 0-2, gap=207.800, corr=-0.223, n=159
- kakuban_bin: 6-9 -> 0-2, gap=201.410, corr=-0.391, n=204
- kakuban_bin: 6-9 -> 3-5, gap=196.638, corr=-0.380, n=204
- kakuban_bin: 0-2 -> 6-9, gap=184.900, corr=-0.339, n=175
- kakuban_bin: 3-5 -> 6-9, gap=169.299, corr=-0.346, n=159
- machine_category: bt -> other, gap=594.479, corr=-0.026, n=116
- machine_category: bt -> hana_oki, gap=570.027, corr=0.128, n=116
- machine_category: hana_oki -> other, gap=352.388, corr=0.125, n=143
- machine_category: other -> bt, gap=329.007, corr=0.030, n=142

## Regime Notes
- all_high: concentrated positive days
- focused_machine: one machine_name dominates
- focused_category: one broader category dominates
- recovery: hall-relative z-score is low
- decoy_heavy: event-like days that do not convert into strong diff
