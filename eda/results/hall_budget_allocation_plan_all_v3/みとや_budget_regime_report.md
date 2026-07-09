# みとや Plan Budget Regime Report

- caution: diff-only is coarse; prefer share_of_total_diff plus hit104_lift for reading concentration
- source rows: 138418
- days: 547
- all_high: 125
- focused_machine: 23
- focused_category: 237
- balanced: 36
- recovery: 126
- decoy_heavy: 0

## Top Axes
- section=501-755: cumulative_share_of_total_diff=466.211, mean_excess=-1.200, hit104_lift=0.000
- machine_category=other: cumulative_share_of_total_diff=453.206, mean_excess=-48.709, hit104_lift=0.014
- atype=N: cumulative_share_of_total_diff=447.935, mean_excess=-9.025, hit104_lift=0.021
- event_type=weekday: cumulative_share_of_total_diff=289.000, mean_excess=0.000, hit104_lift=0.000
- kakuban_bin=621-630: cumulative_share_of_total_diff=154.394, mean_excess=-118.597, hit104_lift=-0.007
- machine_name=モンスターハンターライズ: cumulative_share_of_total_diff=140.403, mean_excess=9.367, hit104_lift=0.015
- kakuban_bin=581-590: cumulative_share_of_total_diff=135.194, mean_excess=-19.346, hit104_lift=0.028
- event_type=weekend: cumulative_share_of_total_diff=124.000, mean_excess=0.000, hit104_lift=0.000
- machine_name=スマスロ北斗の拳: cumulative_share_of_total_diff=109.935, mean_excess=209.212, hit104_lift=0.041
- kakuban_bin=731-740: cumulative_share_of_total_diff=106.880, mean_excess=75.624, hit104_lift=-0.029
- kakuban_bin=521-530: cumulative_share_of_total_diff=102.573, mean_excess=-129.580, hit104_lift=0.001
- atype=A: cumulative_share_of_total_diff=99.065, mean_excess=11.669, hit104_lift=-0.033

## Offset Candidates
- atype: A -> N, gap=213.539, corr=-0.989, n=299
- atype: N -> A, gap=211.808, corr=-0.990, n=248
- kakuban_bin: 571-580 -> 691-700, gap=1109.671, corr=-0.097, n=276
- kakuban_bin: 511-520 -> 631-640, gap=1108.043, corr=-0.109, n=257
- kakuban_bin: 501-510 -> 691-700, gap=1080.538, corr=-0.070, n=268
- kakuban_bin: 571-580 -> 701-710, gap=1080.403, corr=-0.054, n=276
- kakuban_bin: 571-580 -> 521-530, gap=1079.863, corr=-0.049, n=276
- kakuban_bin: 581-590 -> 631-640, gap=1077.765, corr=-0.072, n=238
- kakuban_bin: 631-640 -> 691-700, gap=1075.814, corr=-0.010, n=215
- kakuban_bin: 501-510 -> 631-640, gap=1075.588, corr=-0.095, n=268
- kakuban_bin: 531-540 -> 631-640, gap=1066.233, corr=-0.167, n=231
- kakuban_bin: 561-570 -> 631-640, gap=1062.533, corr=-0.067, n=280

## Regime Notes
- all_high: concentrated positive days
- focused_machine: one machine_name dominates
- focused_category: one broader category dominates
- recovery: hall-relative z-score is low
- decoy_heavy: event-like days that do not convert into strong diff
