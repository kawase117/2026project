# ザシティ Plan Budget Regime Report

- caution: diff-only is coarse; prefer share_of_total_diff plus hit104_lift for reading concentration
- source rows: 61711
- days: 548
- all_high: 136
- focused_machine: 3
- focused_category: 153
- balanced: 129
- recovery: 127
- decoy_heavy: 0

## Top Axes
- machine_category=at_smart: share=786.680, mean_excess=-3.243, hit104_lift=0.040
- atype=N: share=739.547, mean_excess=-14.586, hit104_lift=0.034
- kakuban_bin=6-9: share=700.335, mean_excess=-1.519, hit104_lift=-0.003
- kakuban_bin=0-2: share=635.111, mean_excess=16.219, hit104_lift=0.005
- machine_category=other: share=617.042, mean_excess=-28.223, hit104_lift=0.028
- atype=A: share=567.554, mean_excess=22.479, hit104_lift=-0.049
- machine_category=juggler: share=562.161, mean_excess=21.847, hit104_lift=-0.052
- section=761-893: share=548.000, mean_excess=0.000, hit104_lift=0.000
- kakuban_bin=3-5: share=508.643, mean_excess=-13.579, hit104_lift=-0.001
- machine_name=マイジャグラーV: share=335.352, mean_excess=10.980, hit104_lift=-0.057
- machine_name=かぐや様は告らせたい: share=326.700, mean_excess=47.272, hit104_lift=0.048
- machine_name=ゴーゴージャグラー3: share=297.067, mean_excess=83.081, hit104_lift=-0.040

## Offset Candidates
- atype: A -> N, gap=284.836, corr=-0.988, n=299
- atype: N -> A, gap=260.459, corr=-0.981, n=249
- kakuban_bin: 0-2 -> 3-5, gap=313.652, corr=-0.288, n=268
- kakuban_bin: 0-2 -> 6-9, gap=313.389, corr=-0.465, n=268
- kakuban_bin: 3-5 -> 6-9, gap=277.437, corr=-0.426, n=257
- kakuban_bin: 6-9 -> 3-5, gap=271.211, corr=-0.491, n=273
- kakuban_bin: 3-5 -> 0-2, gap=269.122, corr=-0.242, n=257
- kakuban_bin: 6-9 -> 0-2, gap=263.521, corr=-0.415, n=273
- machine_category: bt -> other, gap=856.165, corr=0.064, n=108
- machine_category: hana_oki -> other, gap=854.364, corr=-0.070, n=271
- machine_category: bt -> at_smart, gap=848.211, corr=-0.049, n=108
- machine_category: hana_oki -> at_smart, gap=839.460, corr=-0.032, n=271

## Regime Notes
- all_high: concentrated positive days
- focused_machine: one machine_name dominates
- focused_category: one broader category dominates
- recovery: hall-relative z-score is low
- decoy_heavy: event-like days that do not convert into strong diff
