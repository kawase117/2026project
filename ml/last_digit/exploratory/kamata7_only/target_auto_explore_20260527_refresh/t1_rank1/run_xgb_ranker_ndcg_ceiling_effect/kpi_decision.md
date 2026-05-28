# KPI Decision Memo

## Current KPI Snapshot
- n_pairs: 584
- hit_at_2_rate: 0.9760
- loss_mean: 459.93
- loss_p50 / p90 / p95: 0.00 / 1070.00 / 2785.00
- rank2_rescue_on_miss1: 0.6154
- critical_miss_rate: 0.0257
- catastrophic_rate: 0.0017

## Baseline Delta
- hit_at_2_rate: current=0.9760, baseline=0.9932, delta=-0.0171, direction=worsened
- loss_mean: current=459.9315, baseline=610.7877, delta=-150.8562, direction=improved
- rank2_rescue_on_miss1: current=0.6154, baseline=0.8919, delta=-0.2765, direction=worsened
- critical_miss_rate: current=0.0257, baseline=0.0068, delta=+0.0188, direction=worsened
- catastrophic_rate: current=0.0017, baseline=0.0120, delta=-0.0103, direction=improved

## Decision
reject_or_rework
