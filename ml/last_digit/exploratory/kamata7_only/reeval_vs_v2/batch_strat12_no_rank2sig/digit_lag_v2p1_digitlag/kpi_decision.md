# KPI Decision Memo

## Current KPI Snapshot
- n_pairs: 432
- hit_at_2_rate: 0.9907
- loss_mean: 821.76
- loss_p50 / p90 / p95: 0.00 / 1600.00 / 4390.00
- rank2_rescue_on_miss1: 0.8077
- critical_miss_rate: 0.0116
- catastrophic_rate: 0.0162

## Baseline Delta
- hit_at_2_rate: current=0.9907, baseline=0.9931, delta=-0.0023, direction=worsened
- loss_mean: current=821.7593, baseline=908.1019, delta=-86.3426, direction=improved
- rank2_rescue_on_miss1: current=0.8077, baseline=0.7826, delta=+0.0251, direction=improved
- critical_miss_rate: current=0.0116, baseline=0.0116, delta=+0.0000, direction=flat
- catastrophic_rate: current=0.0162, baseline=0.0162, delta=+0.0000, direction=flat

## Decision
adopt_or_pilot
