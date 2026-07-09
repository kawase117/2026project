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
- kakuban_bin=3-5: cumulative_share_of_total_diff=723.670, mean_excess=6.924, hit104_lift=0.004
- section=301-373: cumulative_share_of_total_diff=540.035, mean_excess=-64.523, hit104_lift=0.010
- atype=N: cumulative_share_of_total_diff=537.821, mean_excess=-44.728, hit104_lift=0.016
- machine_category=at_smart: cumulative_share_of_total_diff=450.004, mean_excess=-34.871, hit104_lift=0.022
- event_type=weekday: cumulative_share_of_total_diff=315.000, mean_excess=0.000, hit104_lift=0.000
- machine_name=からくりサーカス: cumulative_share_of_total_diff=179.628, mean_excess=-21.174, hit104_lift=0.034
- machine_category=hana_oki: cumulative_share_of_total_diff=153.083, mean_excess=-23.135, hit104_lift=0.063
- event_type=weekend: cumulative_share_of_total_diff=136.000, mean_excess=0.000, hit104_lift=0.000
- machine_name=革命機ヴァルヴレイヴ2: cumulative_share_of_total_diff=130.409, mean_excess=52.028, hit104_lift=0.047
- machine_name=戦姫絶唱シンフォギア 正義の歌: cumulative_share_of_total_diff=127.589, mean_excess=360.433, hit104_lift=0.018
- machine_name=ファンキージャグラー2: cumulative_share_of_total_diff=110.577, mean_excess=96.720, hit104_lift=-0.026
- machine_name=ウルトラミラクルジャグラー: cumulative_share_of_total_diff=106.137, mean_excess=72.688, hit104_lift=-0.028

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
