# ヒロキ Plan Budget Regime Report

- caution: diff-only is coarse; prefer share_of_total_diff plus hit104_lift for reading concentration
- source rows: 121335
- days: 547
- all_high: 124
- focused_machine: 9
- focused_category: 223
- balanced: 73
- recovery: 118
- decoy_heavy: 0

## Top Axes
- kakuban_bin=6-9: share=1403.943, mean_excess=-9.746, hit104_lift=-0.002
- kakuban_bin=0-2: share=1370.903, mean_excess=6.879, hit104_lift=-0.001
- machine_category=other: share=1242.960, mean_excess=-30.491, hit104_lift=0.011
- atype=N: share=1186.520, mean_excess=-12.433, hit104_lift=0.016
- machine_category=at_smart: share=1113.994, mean_excess=4.809, hit104_lift=0.021
- kakuban_bin=3-5: share=1055.191, mean_excess=4.292, hit104_lift=0.004
- machine_name=マギアレコード 魔法少女まどか☆マギカ外伝: share=991.013, mean_excess=-0.416, hit104_lift=0.031
- atype=A: share=906.688, mean_excess=26.482, hit104_lift=-0.036
- machine_category=juggler: share=906.623, mean_excess=24.156, hit104_lift=-0.038
- machine_name=モンキーターンV: share=752.443, mean_excess=107.632, hit104_lift=0.016
- section=2355-2358: share=725.034, mean_excess=-57.722, hit104_lift=0.011
- machine_name=マイジャグラーV: share=648.465, mean_excess=42.995, hit104_lift=-0.036

## Offset Candidates
- atype: A -> N, gap=207.446, corr=-0.971, n=307
- atype: N -> A, gap=176.664, corr=-0.969, n=240
- kakuban_bin: 3-5 -> 6-9, gap=235.451, corr=-0.334, n=280
- kakuban_bin: 3-5 -> 0-2, gap=224.929, corr=-0.350, n=280
- kakuban_bin: 0-2 -> 3-5, gap=205.446, corr=-0.264, n=275
- kakuban_bin: 0-2 -> 6-9, gap=200.923, corr=-0.493, n=275
- kakuban_bin: 6-9 -> 3-5, gap=199.949, corr=-0.393, n=261
- kakuban_bin: 6-9 -> 0-2, gap=187.631, corr=-0.334, n=261
- machine_category: bt -> other, gap=848.223, corr=-0.084, n=155
- machine_category: hana_oki -> bt, gap=601.624, corr=0.020, n=215
- machine_category: hana_oki -> other, gap=558.529, corr=-0.082, n=302
- machine_category: hana_oki -> at_smart, gap=523.837, corr=0.043, n=302

## Regime Notes
- all_high: concentrated positive days
- focused_machine: one machine_name dominates
- focused_category: one broader category dominates
- recovery: hall-relative z-score is low
- decoy_heavy: event-like days that do not convert into strong diff
