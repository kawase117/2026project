# 蒲田1 Plan Budget Regime Report

- caution: diff-only is coarse; prefer share_of_total_diff plus hit104_lift for reading concentration
- source rows: 183997
- days: 535
- all_high: 118
- focused_machine: 25
- focused_category: 250
- balanced: 24
- recovery: 118
- decoy_heavy: 0

## Top Axes
- machine_category=at_smart: share=1288.502, mean_excess=27.468, hit104_lift=0.028
- kakuban_bin=0-2: share=1008.621, mean_excess=-18.332, hit104_lift=-0.005
- machine_category=other: share=1005.404, mean_excess=-26.447, hit104_lift=0.016
- kakuban_bin=3-5: share=1003.553, mean_excess=20.424, hit104_lift=0.004
- atype=N: share=981.192, mean_excess=2.047, hit104_lift=0.022
- kakuban_bin=6-9: share=786.454, mean_excess=-1.385, hit104_lift=0.001
- atype=A: share=746.170, mean_excess=-3.628, hit104_lift=-0.037
- section=2001-2381: share=673.453, mean_excess=-3.254, hit104_lift=-0.001
- machine_category=juggler: share=587.725, mean_excess=36.984, hit104_lift=-0.046
- machine_name=東京喰種: share=526.187, mean_excess=-198.284, hit104_lift=0.064
- machine_name=かぐや様は告らせたい: share=379.132, mean_excess=-60.539, hit104_lift=-0.007
- machine_name=からくりサーカス: share=376.840, mean_excess=104.702, hit104_lift=0.040

## Offset Candidates
- atype: N -> A, gap=221.942, corr=-0.994, n=269
- atype: A -> N, gap=213.032, corr=-0.995, n=266
- kakuban_bin: 3-5 -> 0-2, gap=248.707, corr=-0.329, n=285
- kakuban_bin: 3-5 -> 6-9, gap=242.840, corr=-0.391, n=285
- kakuban_bin: 0-2 -> 6-9, gap=240.957, corr=-0.432, n=257
- kakuban_bin: 6-9 -> 0-2, gap=237.857, corr=-0.471, n=275
- kakuban_bin: 6-9 -> 3-5, gap=207.747, corr=-0.256, n=275
- kakuban_bin: 0-2 -> 3-5, gap=200.003, corr=-0.305, n=257
- machine_category: bt -> hana_oki, gap=876.558, corr=-0.000, n=136
- machine_category: bt -> other, gap=790.502, corr=-0.120, n=136
- machine_category: bt -> at_smart, gap=775.632, corr=0.092, n=136
- machine_category: hana_oki -> bt, gap=440.250, corr=0.035, n=128

## Regime Notes
- all_high: concentrated positive days
- focused_machine: one machine_name dominates
- focused_category: one broader category dominates
- recovery: hall-relative z-score is low
- decoy_heavy: event-like days that do not convert into strong diff
