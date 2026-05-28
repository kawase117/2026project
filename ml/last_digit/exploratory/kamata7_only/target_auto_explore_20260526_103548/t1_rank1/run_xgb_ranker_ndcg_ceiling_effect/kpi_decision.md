# KPI Decision Memo

## Current KPI Snapshot
- n_pairs: 435
- hit_at_2_rate: 0.9770
- loss_mean: 599.08
- loss_p50 / p90 / p95: 0.00 / 1560.00 / 3700.00
- rank2_rescue_on_miss1: 0.6207
- critical_miss_rate: 0.0253
- catastrophic_rate: 0.0023

## Baseline Delta
- hit_at_2_rate: current=0.9770, baseline=0.9908, delta=-0.0138, direction=worsened
- loss_mean: current=599.0805, baseline=746.6667, delta=-147.5862, direction=improved
- rank2_rescue_on_miss1: current=0.6207, baseline=0.8519, delta=-0.2312, direction=worsened
- critical_miss_rate: current=0.0253, baseline=0.0092, delta=+0.0161, direction=worsened
- catastrophic_rate: current=0.0023, baseline=0.0161, delta=-0.0138, direction=improved

## Decision
reject_or_rework
