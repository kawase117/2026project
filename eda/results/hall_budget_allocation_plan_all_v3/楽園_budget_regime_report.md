# 楽園 Plan Budget Regime Report

- caution: diff-only is coarse; prefer share_of_total_diff plus hit104_lift for reading concentration
- source rows: 257362
- days: 548
- all_high: 125
- focused_machine: 10
- focused_category: 223
- balanced: 61
- recovery: 129
- decoy_heavy: 0

## Top Axes
- atype=N: cumulative_share_of_total_diff=466.599, mean_excess=18.203, hit104_lift=0.013
- machine_category=at_smart: cumulative_share_of_total_diff=437.724, mean_excess=68.951, hit104_lift=0.021
- event_type=weekday: cumulative_share_of_total_diff=366.000, mean_excess=0.000, hit104_lift=0.000
- section=2000-2077: cumulative_share_of_total_diff=263.751, mean_excess=-9.098, hit104_lift=-0.008
- section=1000-1059: cumulative_share_of_total_diff=231.970, mean_excess=108.354, hit104_lift=0.017
- event_type=weekend: cumulative_share_of_total_diff=146.000, mean_excess=0.000, hit104_lift=0.000
- section=2100-2240: cumulative_share_of_total_diff=101.096, mean_excess=12.913, hit104_lift=0.007
- machine_category=juggler: cumulative_share_of_total_diff=92.484, mean_excess=-50.477, hit104_lift=-0.055
- machine_name=北斗の拳 転生の章2: cumulative_share_of_total_diff=87.264, mean_excess=216.610, hit104_lift=-0.002
- atype=A: cumulative_share_of_total_diff=81.401, mean_excess=-49.645, hit104_lift=-0.034
- machine_name=かぐや様は告らせたい: cumulative_share_of_total_diff=80.346, mean_excess=-124.166, hit104_lift=-0.029
- machine_name=スマスロ北斗の拳: cumulative_share_of_total_diff=78.358, mean_excess=190.234, hit104_lift=0.055

## Offset Candidates
- atype: N -> A, gap=162.863, corr=-0.975, n=364
- atype: A -> N, gap=120.116, corr=-0.987, n=184
- kakuban_bin: 991-1000 -> 2091-2100, gap=3488.817, corr=-0.101, n=152
- kakuban_bin: 991-1000 -> 2041-2050, gap=3383.177, corr=0.020, n=171
- kakuban_bin: 991-1000 -> 1101-1110, gap=3347.931, corr=-0.022, n=171
- kakuban_bin: 991-1000 -> 1201-1210, gap=3305.008, corr=0.010, n=171
- kakuban_bin: 991-1000 -> 2111-2120, gap=3297.266, corr=0.075, n=171
- kakuban_bin: 991-1000 -> 1131-1140, gap=3290.514, corr=-0.054, n=171
- kakuban_bin: 991-1000 -> 1211-1220, gap=3287.949, corr=0.134, n=171
- kakuban_bin: 991-1000 -> 1111-1120, gap=3287.733, corr=-0.137, n=171
- kakuban_bin: 991-1000 -> 2031-2040, gap=3284.526, corr=0.074, n=170
- kakuban_bin: 991-1000 -> 3131-3140, gap=3279.196, corr=0.051, n=170

## Regime Notes
- all_high: concentrated positive days
- focused_machine: one machine_name dominates
- focused_category: one broader category dominates
- recovery: hall-relative z-score is low
- decoy_heavy: event-like days that do not convert into strong diff
