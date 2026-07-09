# 金時 Plan Budget Regime Report

- caution: diff-only is coarse; prefer share_of_total_diff plus hit104_lift for reading concentration
- source rows: 70550
- days: 547
- all_high: 121
- focused_machine: 23
- focused_category: 254
- balanced: 26
- recovery: 123
- decoy_heavy: 0

## Top Axes
- section=301-373: cumulative_share_of_total_diff=540.035, mean_excess=-64.523, hit104_lift=0.010
- atype=N: cumulative_share_of_total_diff=537.821, mean_excess=-44.728, hit104_lift=0.016
- machine_category=at_smart: cumulative_share_of_total_diff=450.004, mean_excess=-34.871, hit104_lift=0.022
- event_type=weekday: cumulative_share_of_total_diff=315.000, mean_excess=0.000, hit104_lift=0.000
- kakuban_bin=361-370: cumulative_share_of_total_diff=250.752, mean_excess=-103.332, hit104_lift=0.007
- kakuban_bin=351-360: cumulative_share_of_total_diff=198.171, mean_excess=-91.572, hit104_lift=0.005
- machine_name=からくりサーカス: cumulative_share_of_total_diff=179.628, mean_excess=-21.174, hit104_lift=0.034
- machine_category=hana_oki: cumulative_share_of_total_diff=153.083, mean_excess=-23.135, hit104_lift=0.063
- event_type=weekend: cumulative_share_of_total_diff=136.000, mean_excess=0.000, hit104_lift=0.000
- machine_name=革命機ヴァルヴレイヴ2: cumulative_share_of_total_diff=130.409, mean_excess=52.028, hit104_lift=0.047
- machine_name=戦姫絶唱シンフォギア 正義の歌: cumulative_share_of_total_diff=127.589, mean_excess=360.433, hit104_lift=0.018
- machine_name=ファンキージャグラー2: cumulative_share_of_total_diff=110.577, mean_excess=96.720, hit104_lift=-0.026

## Offset Candidates
- atype: A -> N, gap=278.914, corr=-0.978, n=354
- atype: N -> A, gap=218.820, corr=-0.983, n=193
- kakuban_bin: 371-380 -> 341-350, gap=1471.900, corr=-0.016, n=193
- kakuban_bin: 371-380 -> 351-360, gap=1471.492, corr=-0.110, n=193
- kakuban_bin: 371-380 -> 361-370, gap=1465.383, corr=-0.058, n=193
- kakuban_bin: 371-380 -> 331-340, gap=1431.827, corr=0.090, n=193
- kakuban_bin: 371-380 -> 311-320, gap=1388.818, corr=-0.031, n=193
- kakuban_bin: 371-380 -> 441-450, gap=1340.326, corr=-0.064, n=193
- kakuban_bin: 371-380 -> 321-330, gap=1340.194, corr=-0.041, n=193
- kakuban_bin: 371-380 -> 301-310, gap=1321.639, corr=-0.006, n=193
- kakuban_bin: 321-330 -> 331-340, gap=1017.615, corr=0.030, n=225
- kakuban_bin: 321-330 -> 341-350, gap=1010.540, corr=-0.082, n=225

## Regime Notes
- all_high: concentrated positive days
- focused_machine: one machine_name dominates
- focused_category: one broader category dominates
- recovery: hall-relative z-score is low
- decoy_heavy: event-like days that do not convert into strong diff
