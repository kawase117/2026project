# KPI Decision Memo

## Current KPI Snapshot
- n_pairs: 584
- hit_at_2_rate: 0.9914
- loss_mean: 865.92
- loss_p50 / p90 / p95: 0.00 / 1970.00 / 5010.00
- rank2_rescue_on_miss1: 0.8214
- critical_miss_rate: 0.0086
- catastrophic_rate: 0.0188

## Baseline Delta
- hit_at_2_rate: current=0.9914, baseline=0.9932, delta=-0.0017, direction=worsened
- loss_mean: current=865.9247, baseline=610.7877, delta=+255.1370, direction=worsened
- rank2_rescue_on_miss1: current=0.8214, baseline=0.8919, delta=-0.0705, direction=worsened
- critical_miss_rate: current=0.0086, baseline=0.0068, delta=+0.0017, direction=worsened
- catastrophic_rate: current=0.0188, baseline=0.0120, delta=+0.0068, direction=worsened

## Decision
reject_or_rework
