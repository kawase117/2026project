# 楽園 Plan Budget Regime Report

- caution: diff-only is coarse; prefer share_of_total_diff plus hit104_lift for reading concentration
- source rows: 257362
- days: 548
- all_high: 125
- focused_machine: 9
- focused_category: 242
- balanced: 43
- recovery: 129
- decoy_heavy: 0

## Top Axes
- atype=N: cumulative_share_of_total_diff=466.599, mean_excess=18.203, hit104_lift=0.013
- machine_category=at_smart: cumulative_share_of_total_diff=437.724, mean_excess=68.951, hit104_lift=0.021
- event_type=weekday: cumulative_share_of_total_diff=366.000, mean_excess=0.000, hit104_lift=0.000
- kakuban_bin=0-2: cumulative_share_of_total_diff=285.657, mean_excess=-6.574, hit104_lift=0.001
- section=2000-2077: cumulative_share_of_total_diff=263.751, mean_excess=-9.098, hit104_lift=-0.008
- kakuban_bin=3-5: cumulative_share_of_total_diff=260.217, mean_excess=3.072, hit104_lift=0.004
- section=1000-1059: cumulative_share_of_total_diff=231.970, mean_excess=108.354, hit104_lift=0.017
- event_type=weekend: cumulative_share_of_total_diff=146.000, mean_excess=0.000, hit104_lift=0.000
- section=2100-2240: cumulative_share_of_total_diff=101.096, mean_excess=12.913, hit104_lift=0.007
- machine_category=juggler: cumulative_share_of_total_diff=92.484, mean_excess=-50.477, hit104_lift=-0.055
- machine_name=北斗の拳 転生の章2: cumulative_share_of_total_diff=87.264, mean_excess=216.610, hit104_lift=-0.002
- atype=A: cumulative_share_of_total_diff=81.401, mean_excess=-49.645, hit104_lift=-0.034

## Offset Candidates
- atype: N -> A, gap=162.863, corr=-0.975, n=364
- atype: A -> N, gap=120.116, corr=-0.987, n=184
- kakuban_bin: 3-5 -> 0-2, gap=173.605, corr=-0.425, n=274
- kakuban_bin: 0-2 -> 3-5, gap=172.353, corr=-0.379, n=256
- kakuban_bin: 0-2 -> 6-9, gap=169.289, corr=-0.402, n=256
- kakuban_bin: 6-9 -> 0-2, gap=165.150, corr=-0.304, n=270
- kakuban_bin: 3-5 -> 6-9, gap=158.895, corr=-0.268, n=274
- kakuban_bin: 6-9 -> 3-5, gap=144.781, corr=-0.443, n=270
- machine_category: bt -> hana_oki, gap=554.031, corr=0.068, n=164
- machine_category: bt -> juggler, gap=547.125, corr=-0.002, n=164
- machine_category: bt -> other, gap=533.509, corr=-0.003, n=164
- machine_category: at_smart -> juggler, gap=230.098, corr=-0.240, n=360

## Regime Notes
- all_high: concentrated positive days
- focused_machine: one machine_name dominates
- focused_category: one broader category dominates
- recovery: hall-relative z-score is low
- decoy_heavy: event-like days that do not convert into strong diff
