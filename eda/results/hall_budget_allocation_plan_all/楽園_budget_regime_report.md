# 楽園 Plan Budget Regime Report

- caution: diff-only is coarse; prefer share_of_total_diff plus hit104_lift for reading concentration
- source rows: 257362
- days: 548
- all_high: 125
- focused_machine: 9
- focused_category: 242
- balanced: 43
- recovery: 129
- decoy_heavy: 0

## Top Axes
- kakuban_bin=6-9: share=939.597, mean_excess=3.013, hit104_lift=-0.004
- machine_category=at_smart: share=894.327, mean_excess=68.951, hit104_lift=0.021
- machine_category=other: share=841.609, mean_excess=-22.459, hit104_lift=0.006
- kakuban_bin=0-2: share=826.955, mean_excess=-6.574, hit104_lift=0.001
- kakuban_bin=3-5: share=809.852, mean_excess=3.072, hit104_lift=0.004
- atype=N: share=724.393, mean_excess=18.203, hit104_lift=0.013
- section=2100-2240: share=687.215, mean_excess=12.913, hit104_lift=0.007
- section=1000-1059: share=665.498, mean_excess=108.354, hit104_lift=0.017
- section=3107-3266: share=650.376, mean_excess=-4.437, hit104_lift=0.029
- section=2000-2077: share=601.069, mean_excess=-9.098, hit104_lift=-0.008
- section=1100-1216: share=469.582, mean_excess=-62.400, hit104_lift=-0.038
- atype=A: share=462.115, mean_excess=-49.645, hit104_lift=-0.034

## Offset Candidates
- atype: N -> A, gap=162.863, corr=-0.975, n=364
- atype: A -> N, gap=120.116, corr=-0.987, n=184
- kakuban_bin: 3-5 -> 0-2, gap=173.605, corr=-0.425, n=274
- kakuban_bin: 0-2 -> 3-5, gap=172.353, corr=-0.379, n=256
- kakuban_bin: 0-2 -> 6-9, gap=169.289, corr=-0.402, n=256
- kakuban_bin: 6-9 -> 0-2, gap=165.150, corr=-0.304, n=270
- kakuban_bin: 3-5 -> 6-9, gap=158.895, corr=-0.268, n=274
- kakuban_bin: 6-9 -> 3-5, gap=144.781, corr=-0.443, n=270
- machine_category: bt -> hana_oki, gap=554.031, corr=0.068, n=164
- machine_category: bt -> juggler, gap=547.125, corr=-0.002, n=164
- machine_category: bt -> other, gap=533.509, corr=-0.003, n=164
- machine_category: at_smart -> juggler, gap=230.098, corr=-0.240, n=360

## Regime Notes
- all_high: concentrated positive days
- focused_machine: one machine_name dominates
- focused_category: one broader category dominates
- recovery: hall-relative z-score is low
- decoy_heavy: event-like days that do not convert into strong diff
