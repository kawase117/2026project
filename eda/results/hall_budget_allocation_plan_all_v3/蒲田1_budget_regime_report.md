# 蒲田1 Plan Budget Regime Report

- caution: diff-only is coarse; prefer share_of_total_diff plus hit104_lift for reading concentration
- source rows: 183997
- days: 535
- all_high: 118
- focused_machine: 29
- focused_category: 231
- balanced: 39
- recovery: 118
- decoy_heavy: 0

## Top Axes
- machine_category=other: cumulative_share_of_total_diff=539.379, mean_excess=-26.447, hit104_lift=0.016
- section=2001-2381: cumulative_share_of_total_diff=536.869, mean_excess=-3.254, hit104_lift=-0.001
- atype=A: cumulative_share_of_total_diff=337.888, mean_excess=-3.628, hit104_lift=-0.037
- event_type=weekday: cumulative_share_of_total_diff=290.000, mean_excess=0.000, hit104_lift=0.000
- machine_category=juggler: cumulative_share_of_total_diff=226.431, mean_excess=36.984, hit104_lift=-0.046
- atype=N: cumulative_share_of_total_diff=197.112, mean_excess=2.047, hit104_lift=0.022
- kakuban_bin=2051-2060: cumulative_share_of_total_diff=139.841, mean_excess=-90.675, hit104_lift=0.033
- machine_category=hana_oki: cumulative_share_of_total_diff=134.990, mean_excess=-160.885, hit104_lift=0.002
- kakuban_bin=2031-2040: cumulative_share_of_total_diff=130.351, mean_excess=-45.253, hit104_lift=0.021
- machine_name=モンスターハンターライズ: cumulative_share_of_total_diff=123.082, mean_excess=153.842, hit104_lift=0.031
- kakuban_bin=2211-2220: cumulative_share_of_total_diff=122.181, mean_excess=-108.087, hit104_lift=0.016
- machine_name=チバリヨ2プラス: cumulative_share_of_total_diff=112.188, mean_excess=-287.128, hit104_lift=0.007

## Offset Candidates
- atype: N -> A, gap=221.942, corr=-0.994, n=269
- atype: A -> N, gap=213.032, corr=-0.995, n=266
- kakuban_bin: 2381-2390 -> 2211-2220, gap=2556.505, corr=-0.158, n=79
- kakuban_bin: 2381-2390 -> 2261-2270, gap=2515.325, corr=-0.002, n=79
- kakuban_bin: 2381-2390 -> 2081-2090, gap=2302.291, corr=-0.099, n=79
- kakuban_bin: 2381-2390 -> 2251-2260, gap=2279.582, corr=-0.035, n=79
- kakuban_bin: 2381-2390 -> 2331-2340, gap=2262.730, corr=-0.022, n=79
- kakuban_bin: 2381-2390 -> 2021-2030, gap=2229.738, corr=-0.059, n=79
- kakuban_bin: 2381-2390 -> 2271-2280, gap=2219.764, corr=-0.201, n=79
- kakuban_bin: 2381-2390 -> 2371-2380, gap=2172.682, corr=0.068, n=79
- kakuban_bin: 2381-2390 -> 2341-2350, gap=2169.305, corr=-0.050, n=79
- kakuban_bin: 2381-2390 -> 2161-2170, gap=2161.083, corr=-0.090, n=79

## Regime Notes
- all_high: concentrated positive days
- focused_machine: one machine_name dominates
- focused_category: one broader category dominates
- recovery: hall-relative z-score is low
- decoy_heavy: event-like days that do not convert into strong diff
