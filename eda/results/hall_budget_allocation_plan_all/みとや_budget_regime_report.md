# みとや Plan Budget Regime Report

- caution: diff-only is coarse; prefer share_of_total_diff plus hit104_lift for reading concentration
- source rows: 138418
- days: 547
- all_high: 125
- focused_machine: 19
- focused_category: 250
- balanced: 27
- recovery: 126
- decoy_heavy: 0

## Top Axes
- kakuban_bin=0-2: share=1163.730, mean_excess=5.946, hit104_lift=-0.000
- kakuban_bin=3-5: share=1120.821, mean_excess=7.526, hit104_lift=0.004
- kakuban_bin=6-9: share=941.976, mean_excess=-10.770, hit104_lift=-0.003
- machine_category=other: share=935.209, mean_excess=-48.709, hit104_lift=0.014
- machine_category=at_smart: share=909.723, mean_excess=24.443, hit104_lift=0.027
- atype=N: share=864.115, mean_excess=-9.025, hit104_lift=0.021
- section=501-755: share=697.325, mean_excess=-1.200, hit104_lift=0.000
- machine_category=juggler: share=676.490, mean_excess=41.759, hit104_lift=-0.039
- atype=A: share=646.901, mean_excess=11.669, hit104_lift=-0.033
- machine_name=東京喰種: share=534.960, mean_excess=-3.241, hit104_lift=0.062
- machine_name=マイジャグラーV: share=437.909, mean_excess=58.589, hit104_lift=-0.036
- machine_name=モンキーターンV: share=409.741, mean_excess=164.128, hit104_lift=0.027

## Offset Candidates
- atype: A -> N, gap=213.539, corr=-0.989, n=299
- atype: N -> A, gap=211.808, corr=-0.990, n=248
- kakuban_bin: 0-2 -> 6-9, gap=265.775, corr=-0.355, n=271
- kakuban_bin: 3-5 -> 6-9, gap=252.885, corr=-0.484, n=280
- kakuban_bin: 6-9 -> 0-2, gap=231.986, corr=-0.332, n=258
- kakuban_bin: 6-9 -> 3-5, gap=220.200, corr=-0.446, n=258
- kakuban_bin: 0-2 -> 3-5, gap=219.111, corr=-0.319, n=271
- kakuban_bin: 3-5 -> 0-2, gap=218.885, corr=-0.205, n=280
- machine_category: bt -> hana_oki, gap=868.113, corr=0.030, n=141
- machine_category: bt -> other, gap=695.289, corr=0.054, n=141
- machine_category: bt -> at_smart, gap=639.058, corr=-0.121, n=141
- machine_category: at_smart -> hana_oki, gap=542.960, corr=-0.185, n=276

## Regime Notes
- all_high: concentrated positive days
- focused_machine: one machine_name dominates
- focused_category: one broader category dominates
- recovery: hall-relative z-score is low
- decoy_heavy: event-like days that do not convert into strong diff
