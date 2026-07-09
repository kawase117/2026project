# ザシティ Plan Budget Regime Report

- caution: diff-only is coarse; prefer share_of_total_diff plus hit104_lift for reading concentration
- source rows: 61711
- days: 548
- all_high: 136
- focused_machine: 2
- focused_category: 137
- balanced: 146
- recovery: 127
- decoy_heavy: 0

## Top Axes
- atype=N: cumulative_share_of_total_diff=448.851, mean_excess=-14.586, hit104_lift=0.034
- machine_category=at_smart: cumulative_share_of_total_diff=302.574, mean_excess=-3.243, hit104_lift=0.040
- event_type=weekday: cumulative_share_of_total_diff=291.000, mean_excess=0.000, hit104_lift=0.000
- machine_name=かぐや様は告らせたい: cumulative_share_of_total_diff=165.221, mean_excess=47.272, hit104_lift=0.048
- kakuban_bin=851-860: cumulative_share_of_total_diff=158.692, mean_excess=-50.620, hit104_lift=0.035
- section=851-860: cumulative_share_of_total_diff=158.692, mean_excess=-50.620, hit104_lift=0.035
- machine_category=other: cumulative_share_of_total_diff=146.277, mean_excess=-28.223, hit104_lift=0.028
- machine_name=いざ！番長: cumulative_share_of_total_diff=139.980, mean_excess=-161.249, hit104_lift=0.015
- event_type=weekend: cumulative_share_of_total_diff=124.000, mean_excess=0.000, hit104_lift=0.000
- atype=A: cumulative_share_of_total_diff=99.149, mean_excess=22.479, hit104_lift=-0.049
- kakuban_bin=881-890: cumulative_share_of_total_diff=93.519, mean_excess=78.541, hit104_lift=0.046
- section=881-890: cumulative_share_of_total_diff=93.519, mean_excess=78.541, hit104_lift=0.046

## Offset Candidates
- atype: A -> N, gap=284.836, corr=-0.988, n=299
- atype: N -> A, gap=260.459, corr=-0.981, n=249
- kakuban_bin: 831-840 -> 891-900, gap=1058.715, corr=-0.008, n=57
- kakuban_bin: 881-890 -> 891-900, gap=1046.116, corr=-0.005, n=86
- kakuban_bin: 891-900 -> 831-840, gap=1042.702, corr=-0.127, n=60
- kakuban_bin: 891-900 -> 821-830, gap=942.428, corr=-0.087, n=60
- kakuban_bin: 891-900 -> 881-890, gap=934.638, corr=-0.009, n=60
- kakuban_bin: 831-840 -> 841-850, gap=922.638, corr=-0.048, n=209
- kakuban_bin: 841-850 -> 891-900, gap=915.634, corr=-0.041, n=88
- kakuban_bin: 891-900 -> 871-880, gap=914.514, corr=-0.218, n=60
- kakuban_bin: 861-870 -> 891-900, gap=908.167, corr=-0.148, n=72
- kakuban_bin: 871-880 -> 891-900, gap=905.448, corr=0.016, n=71

## Regime Notes
- all_high: concentrated positive days
- focused_machine: one machine_name dominates
- focused_category: one broader category dominates
- recovery: hall-relative z-score is low
- decoy_heavy: event-like days that do not convert into strong diff
