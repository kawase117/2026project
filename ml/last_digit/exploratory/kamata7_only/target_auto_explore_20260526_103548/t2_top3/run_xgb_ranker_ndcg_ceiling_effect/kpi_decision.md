# KPI Decision Memo

## Current KPI Snapshot
- n_pairs: 435
- hit_at_2_rate: 0.9885
- loss_mean: 1066.90
- loss_p50 / p90 / p95: 0.00 / 2260.00 / 7500.00
- rank2_rescue_on_miss1: 0.7917
- critical_miss_rate: 0.0115
- catastrophic_rate: 0.0253

## Baseline Delta
- hit_at_2_rate: current=0.9885, baseline=0.9908, delta=-0.0023, direction=worsened
- loss_mean: current=1066.8966, baseline=746.6667, delta=+320.2299, direction=worsened
- rank2_rescue_on_miss1: current=0.7917, baseline=0.8519, delta=-0.0602, direction=worsened
- critical_miss_rate: current=0.0115, baseline=0.0092, delta=+0.0023, direction=worsened
- catastrophic_rate: current=0.0253, baseline=0.0161, delta=+0.0092, direction=worsened

## Decision
reject_or_rework
