# KPI Decision Memo

## Current KPI Snapshot
- n_pairs: 432
- hit_at_2_rate: 0.9907
- loss_mean: 915.51
- loss_p50 / p90 / p95: 0.00 / 1390.00 / 4960.00
- rank2_rescue_on_miss1: 0.7742
- critical_miss_rate: 0.0162
- catastrophic_rate: 0.0208

## Baseline Delta
- hit_at_2_rate: current=0.9907, baseline=0.9931, delta=-0.0023, direction=worsened
- loss_mean: current=915.5093, baseline=908.1019, delta=+7.4074, direction=worsened
- rank2_rescue_on_miss1: current=0.7742, baseline=0.7826, delta=-0.0084, direction=worsened
- critical_miss_rate: current=0.0162, baseline=0.0116, delta=+0.0046, direction=worsened
- catastrophic_rate: current=0.0208, baseline=0.0162, delta=+0.0046, direction=worsened

## Decision
reject_or_rework
