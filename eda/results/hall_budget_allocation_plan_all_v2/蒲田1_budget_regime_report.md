# 蒲田1 Plan Budget Regime Report

- caution: diff-only is coarse; prefer share_of_total_diff plus hit104_lift for reading concentration
- source rows: 183997
- days: 535
- all_high: 118
- focused_machine: 25
- focused_category: 250
- balanced: 24
- recovery: 118
- decoy_heavy: 0

## Top Axes
- machine_category=other: cumulative_share_of_total_diff=539.379, mean_excess=-26.447, hit104_lift=0.016
- section=2001-2381: cumulative_share_of_total_diff=536.869, mean_excess=-3.254, hit104_lift=-0.001
- kakuban_bin=6-9: cumulative_share_of_total_diff=428.579, mean_excess=-1.385, hit104_lift=0.001
- atype=A: cumulative_share_of_total_diff=337.888, mean_excess=-3.628, hit104_lift=-0.037
- event_type=weekday: cumulative_share_of_total_diff=290.000, mean_excess=0.000, hit104_lift=0.000
- machine_category=juggler: cumulative_share_of_total_diff=226.431, mean_excess=36.984, hit104_lift=-0.046
- atype=N: cumulative_share_of_total_diff=197.112, mean_excess=2.047, hit104_lift=0.022
- machine_category=hana_oki: cumulative_share_of_total_diff=134.990, mean_excess=-160.885, hit104_lift=0.002
- machine_name=モンスターハンターライズ: cumulative_share_of_total_diff=123.082, mean_excess=153.842, hit104_lift=0.031
- machine_name=チバリヨ2プラス: cumulative_share_of_total_diff=112.188, mean_excess=-287.128, hit104_lift=0.007
- event_type=weekend: cumulative_share_of_total_diff=112.000, mean_excess=0.000, hit104_lift=0.000
- machine_name=ミリオンゴッド‐神々の軌跡‐: cumulative_share_of_total_diff=98.857, mean_excess=-1001.475, hit104_lift=-0.072

## Offset Candidates
- atype: N -> A, gap=221.942, corr=-0.994, n=269
- atype: A -> N, gap=213.032, corr=-0.995, n=266
- kakuban_bin: 3-5 -> 0-2, gap=248.707, corr=-0.329, n=285
- kakuban_bin: 3-5 -> 6-9, gap=242.840, corr=-0.391, n=285
- kakuban_bin: 0-2 -> 6-9, gap=240.957, corr=-0.432, n=257
- kakuban_bin: 6-9 -> 0-2, gap=237.857, corr=-0.471, n=275
- kakuban_bin: 6-9 -> 3-5, gap=207.747, corr=-0.256, n=275
- kakuban_bin: 0-2 -> 3-5, gap=200.003, corr=-0.305, n=257
- machine_category: bt -> hana_oki, gap=876.558, corr=-0.000, n=136
- machine_category: bt -> other, gap=790.502, corr=-0.120, n=136
- machine_category: bt -> at_smart, gap=775.632, corr=0.092, n=136
- machine_category: hana_oki -> bt, gap=440.250, corr=0.035, n=128

## Regime Notes
- all_high: concentrated positive days
- focused_machine: one machine_name dominates
- focused_category: one broader category dominates
- recovery: hall-relative z-score is low
- decoy_heavy: event-like days that do not convert into strong diff
