# 金時 Plan Budget Regime Report

- caution: diff-only is coarse; prefer share_of_total_diff plus hit104_lift for reading concentration
- source rows: 70550
- days: 547
- all_high: 121
- focused_machine: 20
- focused_category: 265
- balanced: 18
- recovery: 123
- decoy_heavy: 0

## Top Axes
- kakuban_bin=6-9: share=1486.979, mean_excess=5.150, hit104_lift=0.002
- machine_category=at_smart: share=1434.011, mean_excess=-34.871, hit104_lift=0.022
- machine_category=other: share=1261.847, mean_excess=-52.269, hit104_lift=0.010
- kakuban_bin=0-2: share=1239.898, mean_excess=-10.221, hit104_lift=-0.006
- kakuban_bin=3-5: share=1212.012, mean_excess=6.924, hit104_lift=0.004
- atype=N: share=1060.478, mean_excess=-44.728, hit104_lift=0.016
- section=301-373: share=1056.857, mean_excess=-64.523, hit104_lift=0.010
- section=401-475: share=863.336, mean_excess=55.084, hit104_lift=-0.009
- atype=A: share=840.184, mean_excess=58.569, hit104_lift=-0.021
- machine_category=juggler: share=750.786, mean_excess=72.277, hit104_lift=-0.033
- machine_name=モンキーターンV: share=640.360, mean_excess=126.228, hit104_lift=0.041
- machine_name=東京喰種: share=568.274, mean_excess=-124.379, hit104_lift=0.036

## Offset Candidates
- atype: A -> N, gap=278.914, corr=-0.978, n=354
- atype: N -> A, gap=218.820, corr=-0.983, n=193
- kakuban_bin: 0-2 -> 6-9, gap=304.081, corr=-0.349, n=252
- kakuban_bin: 6-9 -> 0-2, gap=298.454, corr=-0.473, n=277
- kakuban_bin: 3-5 -> 0-2, gap=271.743, corr=-0.162, n=273
- kakuban_bin: 0-2 -> 3-5, gap=258.814, corr=-0.367, n=252
- kakuban_bin: 3-5 -> 6-9, gap=256.242, corr=-0.442, n=273
- kakuban_bin: 6-9 -> 3-5, gap=239.865, corr=-0.358, n=277
- machine_category: bt -> other, gap=953.417, corr=-0.096, n=178
- machine_category: bt -> at_smart, gap=887.378, corr=-0.018, n=178
- machine_category: bt -> hana_oki, gap=865.816, corr=0.030, n=178
- machine_category: hana_oki -> other, gap=612.910, corr=-0.030, n=254

## Regime Notes
- all_high: concentrated positive days
- focused_machine: one machine_name dominates
- focused_category: one broader category dominates
- recovery: hall-relative z-score is low
- decoy_heavy: event-like days that do not convert into strong diff
