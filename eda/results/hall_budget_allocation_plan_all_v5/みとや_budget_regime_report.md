# みとや Plan Budget Regime Report

- caution: diff-only is coarse; prefer share_of_total_diff plus hit104_lift for reading concentration
- source rows: 138418
- days: 547
- all_high: 125
- focused_machine: 25
- focused_category: 248
- balanced: 23
- recovery: 126
- decoy_heavy: 0

## Top Axes
- kakuban_bin=6-9: cumulative_share_of_total_diff=487.467, mean_excess=-15.760, hit104_lift=-0.003
- section=501-755: cumulative_share_of_total_diff=466.211, mean_excess=-1.200, hit104_lift=0.000
- machine_category=other: cumulative_share_of_total_diff=453.206, mean_excess=-48.709, hit104_lift=0.014
- atype=N: cumulative_share_of_total_diff=447.935, mean_excess=-9.025, hit104_lift=0.021
- kakuban_bin=0-2: cumulative_share_of_total_diff=366.397, mean_excess=15.502, hit104_lift=0.002
- event_type=weekday: cumulative_share_of_total_diff=289.000, mean_excess=0.000, hit104_lift=0.000
- machine_name=モンスターハンターライズ: cumulative_share_of_total_diff=140.403, mean_excess=9.367, hit104_lift=0.015
- event_type=weekend: cumulative_share_of_total_diff=124.000, mean_excess=0.000, hit104_lift=0.000
- machine_name=スマスロ北斗の拳: cumulative_share_of_total_diff=109.935, mean_excess=209.212, hit104_lift=0.041
- atype=A: cumulative_share_of_total_diff=99.065, mean_excess=11.669, hit104_lift=-0.033
- machine_name=吉宗: cumulative_share_of_total_diff=97.707, mean_excess=-100.992, hit104_lift=0.026
- machine_name=いざ！番長: cumulative_share_of_total_diff=96.784, mean_excess=-148.518, hit104_lift=-0.000

## Offset Candidates
- atype: A -> N, gap=213.539, corr=-0.989, n=299
- atype: N -> A, gap=211.808, corr=-0.990, n=248
- kakuban_bin: 3-5 -> 6-9, gap=258.227, corr=-0.431, n=277
- kakuban_bin: 0-2 -> 6-9, gap=252.019, corr=-0.402, n=288
- kakuban_bin: 6-9 -> 3-5, gap=224.990, corr=-0.384, n=254
- kakuban_bin: 0-2 -> 3-5, gap=218.430, corr=-0.274, n=288
- kakuban_bin: 3-5 -> 0-2, gap=210.271, corr=-0.242, n=277
- kakuban_bin: 6-9 -> 0-2, gap=204.385, corr=-0.366, n=254
- machine_category: bt -> hana_oki, gap=868.113, corr=0.030, n=141
- machine_category: bt -> other, gap=695.289, corr=0.054, n=141
- machine_category: bt -> at_smart, gap=639.058, corr=-0.121, n=141
- machine_category: at_smart -> hana_oki, gap=542.960, corr=-0.185, n=276

## Regime Notes
- all_high: concentrated positive days
- focused_machine: one machine_name dominates
- focused_category: one broader category dominates
- recovery: hall-relative z-score is low
- decoy_heavy: event-like days that do not convert into strong diff
