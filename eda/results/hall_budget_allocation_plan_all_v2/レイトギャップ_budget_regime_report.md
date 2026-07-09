# レイトギャップ Plan Budget Regime Report

- caution: diff-only is coarse; prefer share_of_total_diff plus hit104_lift for reading concentration
- source rows: 172310
- days: 469
- all_high: 110
- focused_machine: 6
- focused_category: 218
- balanced: 41
- recovery: 94
- decoy_heavy: 0

## Top Axes
- machine_category=juggler: cumulative_share_of_total_diff=860.513, mean_excess=53.274, hit104_lift=-0.050
- machine_name=アイムジャグラーEX-TP: cumulative_share_of_total_diff=766.041, mean_excess=48.660, hit104_lift=-0.045
- atype=A: cumulative_share_of_total_diff=750.438, mean_excess=50.428, hit104_lift=0.006
- kakuban_bin=0-2: cumulative_share_of_total_diff=616.513, mean_excess=-6.701, hit104_lift=-0.000
- section=701-1018: cumulative_share_of_total_diff=538.265, mean_excess=-7.806, hit104_lift=0.002
- machine_category=other: cumulative_share_of_total_diff=332.252, mean_excess=-80.902, hit104_lift=-0.010
- event_type=weekday: cumulative_share_of_total_diff=279.000, mean_excess=0.000, hit104_lift=0.000
- machine_name=キン肉マン～7人の悪魔超人編～: cumulative_share_of_total_diff=269.125, mean_excess=47.556, hit104_lift=-0.006
- machine_name=マイジャグラーV: cumulative_share_of_total_diff=213.927, mean_excess=-141.771, hit104_lift=-0.098
- machine_name=ゴジラ対エヴァンゲリオン: cumulative_share_of_total_diff=190.414, mean_excess=-47.066, hit104_lift=-0.039
- machine_name=真・一騎当千: cumulative_share_of_total_diff=190.160, mean_excess=80.869, hit104_lift=0.027
- kakuban_bin=3-5: cumulative_share_of_total_diff=170.609, mean_excess=-19.783, hit104_lift=-0.005

## Offset Candidates
- atype: A -> N, gap=242.377, corr=-0.965, n=298
- atype: N -> A, gap=201.580, corr=-0.980, n=171
- kakuban_bin: 0-2 -> 3-5, gap=238.325, corr=-0.181, n=219
- kakuban_bin: 3-5 -> 0-2, gap=217.272, corr=-0.268, n=213
- kakuban_bin: 6-9 -> 3-5, gap=212.486, corr=-0.417, n=263
- kakuban_bin: 6-9 -> 0-2, gap=199.418, corr=-0.331, n=263
- kakuban_bin: 0-2 -> 6-9, gap=193.840, corr=-0.517, n=219
- kakuban_bin: 3-5 -> 6-9, gap=185.760, corr=-0.370, n=213
- machine_category: bt -> other, gap=708.905, corr=-0.071, n=159
- machine_category: hana_oki -> other, gap=394.570, corr=-0.206, n=274
- machine_category: other -> bt, gap=374.756, corr=-0.056, n=137
- machine_category: at_smart -> other, gap=351.953, corr=-0.370, n=232

## Regime Notes
- all_high: concentrated positive days
- focused_machine: one machine_name dominates
- focused_category: one broader category dominates
- recovery: hall-relative z-score is low
- decoy_heavy: event-like days that do not convert into strong diff
