# KPI Decision Memo

## Current KPI Snapshot
- n_pairs: 432
- hit_at_2_rate: 0.9907
- loss_mean: 900.93
- loss_p50 / p90 / p95: 0.00 / 2100.00 / 5625.00
- rank2_rescue_on_miss1: 0.7083
- critical_miss_rate: 0.0162
- catastrophic_rate: 0.0185

## Baseline Delta
- hit_at_2_rate: current=0.9907, baseline=0.9931, delta=-0.0023, direction=worsened
- loss_mean: current=900.9259, baseline=908.1019, delta=-7.1759, direction=improved
- rank2_rescue_on_miss1: current=0.7083, baseline=0.7826, delta=-0.0743, direction=worsened
- critical_miss_rate: current=0.0162, baseline=0.0116, delta=+0.0046, direction=worsened
- catastrophic_rate: current=0.0185, baseline=0.0162, delta=+0.0023, direction=worsened

## Decision
reject_or_rework
