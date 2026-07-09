# 蒲田7 Plan Budget Regime Report

- caution: diff-only is coarse; prefer share_of_total_diff plus hit104_lift for reading concentration
- source rows: 252601
- days: 359
- all_high: 74
- focused_machine: 12
- focused_category: 82
- balanced: 116
- recovery: 75
- decoy_heavy: 0

## Top Axes
- section=2001-2351: cumulative_share_of_total_diff=273.489, mean_excess=45.327, hit104_lift=0.016
- atype=N: cumulative_share_of_total_diff=256.048, mean_excess=-2.518, hit104_lift=0.018
- kakuban_bin=6-9: cumulative_share_of_total_diff=218.729, mean_excess=21.980, hit104_lift=0.001
- event_type=weekday: cumulative_share_of_total_diff=189.000, mean_excess=0.000, hit104_lift=0.000
- machine_category=other: cumulative_share_of_total_diff=144.355, mean_excess=-12.500, hit104_lift=0.008
- machine_name=ソードアート・オンライン: cumulative_share_of_total_diff=124.090, mean_excess=247.914, hit104_lift=0.062
- machine_name=モンキーターンV: cumulative_share_of_total_diff=112.238, mean_excess=155.033, hit104_lift=0.023
- machine_category=at_smart: cumulative_share_of_total_diff=111.693, mean_excess=7.306, hit104_lift=0.028
- atype=A: cumulative_share_of_total_diff=102.952, mean_excess=5.876, hit104_lift=-0.041
- kakuban_bin=0-2: cumulative_share_of_total_diff=95.379, mean_excess=-8.390, hit104_lift=0.000
- section=3001-3362: cumulative_share_of_total_diff=81.399, mean_excess=-44.731, hit104_lift=-0.016
- event_type=weekend: cumulative_share_of_total_diff=70.000, mean_excess=0.000, hit104_lift=0.000

## Offset Candidates
- atype: A -> N, gap=201.858, corr=-0.998, n=175
- atype: N -> A, gap=175.606, corr=-0.997, n=184
- kakuban_bin: 0-2 -> 3-5, gap=209.648, corr=-0.281, n=174
- kakuban_bin: 3-5 -> 0-2, gap=207.800, corr=-0.223, n=159
- kakuban_bin: 6-9 -> 0-2, gap=203.217, corr=-0.387, n=203
- kakuban_bin: 6-9 -> 3-5, gap=195.988, corr=-0.387, n=203
- kakuban_bin: 0-2 -> 6-9, gap=185.011, corr=-0.344, n=174
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
