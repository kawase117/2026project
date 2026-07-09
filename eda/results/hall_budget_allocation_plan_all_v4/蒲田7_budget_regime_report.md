# 蒲田7 Plan Budget Regime Report

- caution: diff-only is coarse; prefer share_of_total_diff plus hit104_lift for reading concentration
- source rows: 252601
- days: 359
- all_high: 74
- focused_machine: 16
- focused_category: 44
- balanced: 150
- recovery: 75
- decoy_heavy: 0

## Top Axes
- atype=N: cumulative_share_of_total_diff=256.048, mean_excess=-2.518, hit104_lift=0.018
- event_type=weekday: cumulative_share_of_total_diff=189.000, mean_excess=0.000, hit104_lift=0.000
- machine_category=other: cumulative_share_of_total_diff=144.355, mean_excess=-12.500, hit104_lift=0.008
- machine_name=ソードアート・オンライン: cumulative_share_of_total_diff=124.090, mean_excess=247.914, hit104_lift=0.062
- kakuban_bin=2141-2150: cumulative_share_of_total_diff=123.436, mean_excess=71.253, hit104_lift=0.024
- section=2141-2150: cumulative_share_of_total_diff=123.436, mean_excess=71.253, hit104_lift=0.024
- machine_name=モンキーターンV: cumulative_share_of_total_diff=112.238, mean_excess=155.033, hit104_lift=0.023
- machine_category=at_smart: cumulative_share_of_total_diff=111.693, mean_excess=7.306, hit104_lift=0.028
- atype=A: cumulative_share_of_total_diff=102.952, mean_excess=5.876, hit104_lift=-0.041
- kakuban_bin=3071-3080: cumulative_share_of_total_diff=85.000, mean_excess=-304.640, hit104_lift=-0.017
- section=3071-3080: cumulative_share_of_total_diff=85.000, mean_excess=-304.640, hit104_lift=-0.017
- kakuban_bin=3051-3060: cumulative_share_of_total_diff=81.037, mean_excess=21.747, hit104_lift=0.003

## Offset Candidates
- atype: A -> N, gap=201.858, corr=-0.998, n=175
- atype: N -> A, gap=175.606, corr=-0.997, n=184
- kakuban_bin: 2351-2360 -> 3071-3080, gap=2887.715, corr=0.037, n=133
- kakuban_bin: 2351-2360 -> 2201-2210, gap=2829.457, corr=0.012, n=133
- kakuban_bin: 3391-3400 -> 3241-3250, gap=2731.496, corr=-0.148, n=140
- kakuban_bin: 3391-3400 -> 2201-2210, gap=2729.373, corr=-0.220, n=140
- kakuban_bin: 2351-2360 -> 3241-3250, gap=2690.257, corr=0.034, n=133
- kakuban_bin: 3391-3400 -> 3231-3240, gap=2637.349, corr=-0.207, n=140
- kakuban_bin: 2351-2360 -> 3061-3070, gap=2624.954, corr=0.064, n=133
- kakuban_bin: 2351-2360 -> 3231-3240, gap=2619.795, corr=-0.128, n=133
- kakuban_bin: 2351-2360 -> 3021-3030, gap=2616.450, corr=0.116, n=133
- kakuban_bin: 2351-2360 -> 3081-3090, gap=2608.557, corr=-0.098, n=133

## Regime Notes
- all_high: concentrated positive days
- focused_machine: one machine_name dominates
- focused_category: one broader category dominates
- recovery: hall-relative z-score is low
- decoy_heavy: event-like days that do not convert into strong diff
