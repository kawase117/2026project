# KPI Decision Memo

## Current KPI Snapshot
- n_pairs: 432
- hit_at_2_rate: 0.9931
- loss_mean: 838.66
- loss_p50 / p90 / p95: 0.00 / 1700.00 / 4390.00
- rank2_rescue_on_miss1: 0.8000
- critical_miss_rate: 0.0093
- catastrophic_rate: 0.0116

## Baseline Delta
- hit_at_2_rate: current=0.9931, baseline=0.9931, delta=+0.0000, direction=flat
- loss_mean: current=838.6574, baseline=908.1019, delta=-69.4444, direction=improved
- rank2_rescue_on_miss1: current=0.8000, baseline=0.7826, delta=+0.0174, direction=improved
- critical_miss_rate: current=0.0093, baseline=0.0116, delta=-0.0023, direction=improved
- catastrophic_rate: current=0.0116, baseline=0.0162, delta=-0.0046, direction=improved

## Decision
adopt_or_pilot
