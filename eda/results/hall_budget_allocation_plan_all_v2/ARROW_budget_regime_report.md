# ARROW Plan Budget Regime Report

- caution: diff-only is coarse; prefer share_of_total_diff plus hit104_lift for reading concentration
- source rows: 167779
- days: 538
- all_high: 120
- focused_machine: 11
- focused_category: 245
- balanced: 34
- recovery: 128
- decoy_heavy: 0

## Top Axes
- atype=N: cumulative_share_of_total_diff=538.734, mean_excess=3.480, hit104_lift=0.014
- machine_category=at_smart: cumulative_share_of_total_diff=526.385, mean_excess=13.568, hit104_lift=0.019
- section=601-860: cumulative_share_of_total_diff=449.189, mean_excess=1.894, hit104_lift=-0.001
- event_type=weekday: cumulative_share_of_total_diff=323.000, mean_excess=0.000, hit104_lift=0.000
- kakuban_bin=6-9: cumulative_share_of_total_diff=291.533, mean_excess=7.223, hit104_lift=0.002
- kakuban_bin=0-2: cumulative_share_of_total_diff=219.078, mean_excess=-15.038, hit104_lift=-0.002
- machine_name=東京喰種: cumulative_share_of_total_diff=183.573, mean_excess=85.989, hit104_lift=0.065
- machine_name=かぐや様は告らせたい: cumulative_share_of_total_diff=152.721, mean_excess=-48.320, hit104_lift=0.005
- machine_name=スマスロ北斗の拳: cumulative_share_of_total_diff=152.150, mean_excess=16.099, hit104_lift=0.025
- event_type=weekend: cumulative_share_of_total_diff=126.000, mean_excess=0.000, hit104_lift=0.000
- machine_name=モンキーターンV: cumulative_share_of_total_diff=92.016, mean_excess=48.925, hit104_lift=-0.007
- machine_name=回胴黙示録カイジ 狂宴: cumulative_share_of_total_diff=64.348, mean_excess=-51.732, hit104_lift=0.029

## Offset Candidates
- atype: N -> A, gap=249.029, corr=-0.993, n=272
- atype: A -> N, gap=231.219, corr=-0.994, n=266
- kakuban_bin: 0-2 -> 6-9, gap=258.757, corr=-0.489, n=239
- kakuban_bin: 3-5 -> 0-2, gap=251.590, corr=-0.344, n=266
- kakuban_bin: 6-9 -> 0-2, gap=243.695, corr=-0.424, n=280
- kakuban_bin: 0-2 -> 3-5, gap=243.606, corr=-0.236, n=239
- kakuban_bin: 3-5 -> 6-9, gap=237.689, corr=-0.326, n=266
- kakuban_bin: 6-9 -> 3-5, gap=219.031, corr=-0.396, n=280
- machine_category: bt -> hana_oki, gap=721.364, corr=-0.129, n=163
- machine_category: bt -> other, gap=708.425, corr=-0.041, n=163
- machine_category: hana_oki -> at_smart, gap=392.047, corr=-0.077, n=260
- machine_category: hana_oki -> bt, gap=385.570, corr=-0.069, n=164

## Regime Notes
- all_high: concentrated positive days
- focused_machine: one machine_name dominates
- focused_category: one broader category dominates
- recovery: hall-relative z-score is low
- decoy_heavy: event-like days that do not convert into strong diff
