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
- machine_category=at_smart: share=1357.404, mean_excess=10.478, hit104_lift=0.002
- atype=N: share=1348.142, mean_excess=-30.080, hit104_lift=-0.004
- machine_category=other: share=1230.661, mean_excess=-80.902, hit104_lift=-0.010
- atype=A: share=1157.951, mean_excess=50.428, hit104_lift=0.006
- machine_category=juggler: share=1114.714, mean_excess=53.274, hit104_lift=-0.050
- kakuban_bin=6-9: share=952.869, mean_excess=19.597, hit104_lift=0.004
- section=701-1018: share=946.297, mean_excess=-7.806, hit104_lift=0.002
- kakuban_bin=0-2: share=896.222, mean_excess=-6.701, hit104_lift=-0.000
- machine_name=アイムジャグラーEX-TP: share=887.126, mean_excess=48.660, hit104_lift=-0.045
- kakuban_bin=3-5: share=860.737, mean_excess=-19.783, hit104_lift=-0.005
- section=307-342: share=636.231, mean_excess=-6.746, hit104_lift=-0.015
- machine_name=革命機ヴァルヴレイヴ: share=587.082, mean_excess=-27.174, hit104_lift=-0.022

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
