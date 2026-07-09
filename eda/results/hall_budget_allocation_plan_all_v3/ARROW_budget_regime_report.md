# ARROW Plan Budget Regime Report

- caution: diff-only is coarse; prefer share_of_total_diff plus hit104_lift for reading concentration
- source rows: 167779
- days: 538
- all_high: 120
- focused_machine: 11
- focused_category: 227
- balanced: 52
- recovery: 128
- decoy_heavy: 0

## Top Axes
- atype=N: cumulative_share_of_total_diff=538.734, mean_excess=3.480, hit104_lift=0.014
- machine_category=at_smart: cumulative_share_of_total_diff=526.385, mean_excess=13.568, hit104_lift=0.019
- section=601-860: cumulative_share_of_total_diff=449.189, mean_excess=1.894, hit104_lift=-0.001
- event_type=weekday: cumulative_share_of_total_diff=323.000, mean_excess=0.000, hit104_lift=0.000
- machine_name=東京喰種: cumulative_share_of_total_diff=183.573, mean_excess=85.989, hit104_lift=0.065
- machine_name=かぐや様は告らせたい: cumulative_share_of_total_diff=152.721, mean_excess=-48.320, hit104_lift=0.005
- machine_name=スマスロ北斗の拳: cumulative_share_of_total_diff=152.150, mean_excess=16.099, hit104_lift=0.025
- event_type=weekend: cumulative_share_of_total_diff=126.000, mean_excess=0.000, hit104_lift=0.000
- kakuban_bin=801-810: cumulative_share_of_total_diff=113.753, mean_excess=85.176, hit104_lift=0.064
- kakuban_bin=551-560: cumulative_share_of_total_diff=98.231, mean_excess=-5.785, hit104_lift=0.007
- kakuban_bin=731-740: cumulative_share_of_total_diff=97.429, mean_excess=22.892, hit104_lift=0.026
- machine_name=モンキーターンV: cumulative_share_of_total_diff=92.016, mean_excess=48.925, hit104_lift=-0.007

## Offset Candidates
- atype: N -> A, gap=249.029, corr=-0.993, n=272
- atype: A -> N, gap=231.219, corr=-0.994, n=266
- kakuban_bin: 791-800 -> 641-650, gap=1094.036, corr=0.049, n=270
- kakuban_bin: 791-800 -> 621-630, gap=1058.793, corr=-0.127, n=271
- kakuban_bin: 801-810 -> 571-580, gap=1050.969, corr=0.000, n=247
- kakuban_bin: 561-570 -> 641-650, gap=1049.602, corr=0.076, n=231
- kakuban_bin: 611-620 -> 651-660, gap=1041.575, corr=-0.043, n=252
- kakuban_bin: 611-620 -> 621-630, gap=1033.884, corr=-0.119, n=252
- kakuban_bin: 801-810 -> 641-650, gap=1029.929, corr=-0.006, n=265
- kakuban_bin: 801-810 -> 651-660, gap=1017.166, corr=-0.101, n=265
- kakuban_bin: 781-790 -> 621-630, gap=1014.632, corr=-0.103, n=253
- kakuban_bin: 801-810 -> 561-570, gap=1012.262, corr=-0.048, n=247

## Regime Notes
- all_high: concentrated positive days
- focused_machine: one machine_name dominates
- focused_category: one broader category dominates
- recovery: hall-relative z-score is low
- decoy_heavy: event-like days that do not convert into strong diff
