# KPI Decision Memo

## Current KPI Snapshot
- n_pairs: 584
- hit_at_2_rate: 0.9932
- loss_mean: 610.79
- loss_p50 / p90 / p95: 0.00 / 900.00 / 3500.00
- rank2_rescue_on_miss1: 0.8919
- critical_miss_rate: 0.0068
- catastrophic_rate: 0.0120

## Baseline Delta
- hit_at_2_rate: current=0.9932, baseline=0.8634, delta=+0.1297, direction=improved
- loss_mean: current=610.7877, baseline=1885.4167, delta=-1274.6290, direction=improved
- rank2_rescue_on_miss1: current=0.8919, baseline=0.3023, delta=+0.5896, direction=improved
- critical_miss_rate: current=0.0068, baseline=0.1389, delta=-0.1320, direction=improved
- catastrophic_rate: current=0.0120, baseline=0.0347, delta=-0.0227, direction=improved

## Decision
adopt_or_pilot
