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
- machine_category=other: share=1156.906, mean_excess=-8.529, hit104_lift=0.009
- machine_category=at_smart: share=1139.393, mean_excess=13.568, hit104_lift=0.019
- kakuban_bin=6-9: share=1133.033, mean_excess=7.223, hit104_lift=0.002
- atype=N: share=962.284, mean_excess=3.480, hit104_lift=0.014
- kakuban_bin=0-2: share=923.977, mean_excess=-15.038, hit104_lift=-0.002
- section=601-860: share=918.916, mean_excess=1.894, hit104_lift=-0.001
- kakuban_bin=3-5: share=819.144, mean_excess=5.494, hit104_lift=-0.001
- atype=A: share=737.741, mean_excess=-8.102, hit104_lift=-0.029
- machine_category=juggler: share=637.429, mean_excess=-4.108, hit104_lift=-0.047
- section=541-580: share=577.741, mean_excess=-17.167, hit104_lift=0.001
- machine_name=東京喰種: share=549.826, mean_excess=85.989, hit104_lift=0.065
- machine_name=スマスロ北斗の拳: share=453.936, mean_excess=16.099, hit104_lift=0.025

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
