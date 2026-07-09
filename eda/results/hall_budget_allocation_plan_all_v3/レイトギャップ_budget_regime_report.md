# レイトギャップ Plan Budget Regime Report

- caution: diff-only is coarse; prefer share_of_total_diff plus hit104_lift for reading concentration
- source rows: 172310
- days: 469
- all_high: 110
- focused_machine: 8
- focused_category: 206
- balanced: 51
- recovery: 94
- decoy_heavy: 0

## Top Axes
- machine_category=juggler: cumulative_share_of_total_diff=860.513, mean_excess=53.274, hit104_lift=-0.050
- machine_name=アイムジャグラーEX-TP: cumulative_share_of_total_diff=766.041, mean_excess=48.660, hit104_lift=-0.045
- atype=A: cumulative_share_of_total_diff=750.438, mean_excess=50.428, hit104_lift=0.006
- section=701-1018: cumulative_share_of_total_diff=538.265, mean_excess=-7.806, hit104_lift=0.002
- kakuban_bin=811-820: cumulative_share_of_total_diff=332.434, mean_excess=54.219, hit104_lift=0.020
- machine_category=other: cumulative_share_of_total_diff=332.252, mean_excess=-80.902, hit104_lift=-0.010
- kakuban_bin=741-750: cumulative_share_of_total_diff=287.099, mean_excess=80.973, hit104_lift=-0.035
- event_type=weekday: cumulative_share_of_total_diff=279.000, mean_excess=0.000, hit104_lift=0.000
- machine_name=キン肉マン～7人の悪魔超人編～: cumulative_share_of_total_diff=269.125, mean_excess=47.556, hit104_lift=-0.006
- kakuban_bin=881-890: cumulative_share_of_total_diff=268.227, mean_excess=-86.514, hit104_lift=-0.024
- kakuban_bin=751-760: cumulative_share_of_total_diff=241.469, mean_excess=38.229, hit104_lift=-0.052
- kakuban_bin=601-610: cumulative_share_of_total_diff=227.710, mean_excess=28.714, hit104_lift=-0.002

## Offset Candidates
- atype: A -> N, gap=242.377, corr=-0.965, n=298
- atype: N -> A, gap=201.580, corr=-0.980, n=171
- kakuban_bin: 541-550 -> 871-880, gap=2140.352, corr=-0.093, n=18
- kakuban_bin: 541-550 -> 901-910, gap=1946.258, corr=0.141, n=18
- kakuban_bin: 541-550 -> 801-810, gap=1922.275, corr=0.127, n=18
- kakuban_bin: 541-550 -> 881-890, gap=1834.465, corr=0.178, n=18
- kakuban_bin: 541-550 -> 961-970, gap=1821.939, corr=-0.129, n=18
- kakuban_bin: 541-550 -> 921-930, gap=1787.363, corr=-0.299, n=18
- kakuban_bin: 541-550 -> 851-860, gap=1769.623, corr=-0.166, n=18
- kakuban_bin: 541-550 -> 981-990, gap=1742.332, corr=-0.082, n=18
- kakuban_bin: 541-550 -> 891-900, gap=1688.099, corr=-0.264, n=18
- kakuban_bin: 541-550 -> 811-820, gap=1637.777, corr=0.097, n=18

## Regime Notes
- all_high: concentrated positive days
- focused_machine: one machine_name dominates
- focused_category: one broader category dominates
- recovery: hall-relative z-score is low
- decoy_heavy: event-like days that do not convert into strong diff
