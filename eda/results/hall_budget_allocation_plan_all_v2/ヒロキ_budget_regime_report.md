# ヒロキ Plan Budget Regime Report

- caution: diff-only is coarse; prefer share_of_total_diff plus hit104_lift for reading concentration
- source rows: 121335
- days: 547
- all_high: 124
- focused_machine: 9
- focused_category: 223
- balanced: 73
- recovery: 118
- decoy_heavy: 0

## Top Axes
- machine_name=マギアレコード 魔法少女まどか☆マギカ外伝: cumulative_share_of_total_diff=841.385, mean_excess=-0.416, hit104_lift=0.031
- kakuban_bin=6-9: cumulative_share_of_total_diff=672.451, mean_excess=-9.746, hit104_lift=-0.002
- atype=N: cumulative_share_of_total_diff=644.352, mean_excess=-12.433, hit104_lift=0.016
- machine_category=other: cumulative_share_of_total_diff=577.789, mean_excess=-30.491, hit104_lift=0.011
- machine_name=革命機ヴァルヴレイヴ2: cumulative_share_of_total_diff=499.147, mean_excess=80.488, hit104_lift=0.056
- machine_name=新鬼武者3: cumulative_share_of_total_diff=460.012, mean_excess=-22.637, hit104_lift=-0.011
- section=2355-2358: cumulative_share_of_total_diff=429.059, mean_excess=-57.722, hit104_lift=0.011
- section=2135-2138: cumulative_share_of_total_diff=355.212, mean_excess=-55.736, hit104_lift=0.018
- section=2360-2363: cumulative_share_of_total_diff=328.254, mean_excess=-84.535, hit104_lift=0.015
- section=2155-2158: cumulative_share_of_total_diff=327.319, mean_excess=-74.951, hit104_lift=0.030
- event_type=weekday: cumulative_share_of_total_diff=327.000, mean_excess=0.000, hit104_lift=0.000
- section=2230-2233: cumulative_share_of_total_diff=313.090, mean_excess=1.982, hit104_lift=0.038

## Offset Candidates
- atype: A -> N, gap=207.446, corr=-0.971, n=307
- atype: N -> A, gap=176.664, corr=-0.969, n=240
- kakuban_bin: 3-5 -> 6-9, gap=235.451, corr=-0.334, n=280
- kakuban_bin: 3-5 -> 0-2, gap=224.929, corr=-0.350, n=280
- kakuban_bin: 0-2 -> 3-5, gap=205.446, corr=-0.264, n=275
- kakuban_bin: 0-2 -> 6-9, gap=200.923, corr=-0.493, n=275
- kakuban_bin: 6-9 -> 3-5, gap=199.949, corr=-0.393, n=261
- kakuban_bin: 6-9 -> 0-2, gap=187.631, corr=-0.334, n=261
- machine_category: bt -> other, gap=848.223, corr=-0.084, n=155
- machine_category: hana_oki -> bt, gap=601.624, corr=0.020, n=215
- machine_category: hana_oki -> other, gap=558.529, corr=-0.082, n=302
- machine_category: hana_oki -> at_smart, gap=523.837, corr=0.043, n=302

## Regime Notes
- all_high: concentrated positive days
- focused_machine: one machine_name dominates
- focused_category: one broader category dominates
- recovery: hall-relative z-score is low
- decoy_heavy: event-like days that do not convert into strong diff
