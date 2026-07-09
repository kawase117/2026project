# ヒロキ Plan Budget Regime Report

- caution: diff-only is coarse; prefer share_of_total_diff plus hit104_lift for reading concentration
- source rows: 121335
- days: 547
- all_high: 124
- focused_machine: 11
- focused_category: 188
- balanced: 106
- recovery: 118
- decoy_heavy: 0

## Top Axes
- machine_name=マギアレコード 魔法少女まどか☆マギカ外伝: cumulative_share_of_total_diff=841.385, mean_excess=-0.416, hit104_lift=0.031
- atype=N: cumulative_share_of_total_diff=644.352, mean_excess=-12.433, hit104_lift=0.016
- machine_category=other: cumulative_share_of_total_diff=577.789, mean_excess=-30.491, hit104_lift=0.011
- kakuban_bin=2351-2360: cumulative_share_of_total_diff=531.270, mean_excess=1.824, hit104_lift=0.028
- machine_name=革命機ヴァルヴレイヴ2: cumulative_share_of_total_diff=499.147, mean_excess=80.488, hit104_lift=0.056
- machine_name=新鬼武者3: cumulative_share_of_total_diff=460.012, mean_excess=-22.637, hit104_lift=-0.011
- section=2355-2358: cumulative_share_of_total_diff=429.059, mean_excess=-57.722, hit104_lift=0.011
- section=2135-2138: cumulative_share_of_total_diff=355.212, mean_excess=-55.736, hit104_lift=0.018
- kakuban_bin=2151-2160: cumulative_share_of_total_diff=350.607, mean_excess=27.236, hit104_lift=0.045
- section=2360-2363: cumulative_share_of_total_diff=328.254, mean_excess=-84.535, hit104_lift=0.015
- section=2155-2158: cumulative_share_of_total_diff=327.319, mean_excess=-74.951, hit104_lift=0.030
- event_type=weekday: cumulative_share_of_total_diff=327.000, mean_excess=0.000, hit104_lift=0.000

## Offset Candidates
- atype: A -> N, gap=207.446, corr=-0.971, n=307
- atype: N -> A, gap=176.664, corr=-0.969, n=240
- kakuban_bin: 2141-2150 -> 2591-2600, gap=2884.971, corr=-0.101, n=66
- kakuban_bin: 2141-2150 -> 2491-2500, gap=2818.365, corr=0.048, n=109
- kakuban_bin: 2141-2150 -> 2501-2510, gap=2681.161, corr=-0.067, n=135
- kakuban_bin: 2141-2150 -> 2071-2080, gap=2667.447, corr=-0.209, n=143
- kakuban_bin: 2141-2150 -> 2561-2570, gap=2660.585, corr=0.065, n=69
- kakuban_bin: 2091-2100 -> 2141-2150, gap=2647.408, corr=0.152, n=121
- kakuban_bin: 2091-2100 -> 2561-2570, gap=2642.127, corr=-0.122, n=80
- kakuban_bin: 2141-2150 -> 2581-2590, gap=2637.447, corr=-0.052, n=73
- kakuban_bin: 2141-2150 -> 2121-2130, gap=2635.081, corr=0.005, n=141
- kakuban_bin: 2141-2150 -> 2341-2350, gap=2633.077, corr=-0.039, n=116

## Regime Notes
- all_high: concentrated positive days
- focused_machine: one machine_name dominates
- focused_category: one broader category dominates
- recovery: hall-relative z-score is low
- decoy_heavy: event-like days that do not convert into strong diff
