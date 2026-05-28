# KPI Decision Memo

## Current KPI Snapshot
- n_pairs: 435
- hit_at_2_rate: 0.9908
- loss_mean: 746.67
- loss_p50 / p90 / p95: 0.00 / 1260.00 / 3920.00
- rank2_rescue_on_miss1: 0.8519
- critical_miss_rate: 0.0092
- catastrophic_rate: 0.0161

## Baseline Delta
- hit_at_2_rate: current=0.9908, baseline=0.8634, delta=+0.1274, direction=improved
- loss_mean: current=746.6667, baseline=1885.4167, delta=-1138.7500, direction=improved
- rank2_rescue_on_miss1: current=0.8519, baseline=0.3023, delta=+0.5495, direction=improved
- critical_miss_rate: current=0.0092, baseline=0.1389, delta=-0.1297, direction=improved
- catastrophic_rate: current=0.0161, baseline=0.0347, delta=-0.0186, direction=improved

## Decision
adopt_or_pilot
