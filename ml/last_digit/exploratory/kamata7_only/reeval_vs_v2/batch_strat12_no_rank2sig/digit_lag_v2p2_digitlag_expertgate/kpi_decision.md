# KPI Decision Memo

## Current KPI Snapshot
- n_pairs: 432
- hit_at_2_rate: 0.9907
- loss_mean: 897.69
- loss_p50 / p90 / p95: 0.00 / 1300.00 / 4245.00
- rank2_rescue_on_miss1: 0.7692
- critical_miss_rate: 0.0139
- catastrophic_rate: 0.0208

## Baseline Delta
- hit_at_2_rate: current=0.9907, baseline=0.9931, delta=-0.0023, direction=worsened
- loss_mean: current=897.6852, baseline=908.1019, delta=-10.4167, direction=improved
- rank2_rescue_on_miss1: current=0.7692, baseline=0.7826, delta=-0.0134, direction=worsened
- critical_miss_rate: current=0.0139, baseline=0.0116, delta=+0.0023, direction=worsened
- catastrophic_rate: current=0.0208, baseline=0.0162, delta=+0.0046, direction=worsened

## Decision
reject_or_rework
